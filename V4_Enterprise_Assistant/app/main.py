import csv
import io
import hmac
import json
import base64
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.config import settings
from app.models import Customer, FollowUp, DocumentChunk, User
from app.auth import create_user, verify_password, hash_password, utc_timestamp
from app.schemas import (
    CustomerCreate,
    CustomerOut,
    CustomerSearchResult,
    FollowUpCreate,
    FollowUpOut,
    AIResult,
    RagAsk,
    RagAnswer,
    RagSource,
    RagDocument,
    RagChunkOut,
    RagChunkList,
    AgentAnalyzeRequest,
    AgentAnalyzeResult,
    UserOut,
    UserCreateRequest,
    UserStatusUpdate,
    ChangePasswordRequest,
)
from app.llm import build_customer_context, call_llm
from app.rag import (
    extract_text_from_upload,
    split_text,
    retrieve_chunks,
    retrieve_chunks_vector,
    build_rag_prompt,
)
from app.agent import run_customer_followup_agent
from app.db_init import init_database

logger = logging.getLogger(__name__)

# ─── Production security validation — MUST run BEFORE init_database() ───
# In production, invalid config must block startup before touching the database.
if settings.APP_ENV == "production":
    from app.config import validate_production_settings
    try:
        _prod_warnings = validate_production_settings()
        for _w in _prod_warnings:
            logger.warning("Production config: %s", _w)
    except ValueError as exc:
        logger.critical("Production config fatal: %s", exc)
        raise

init_database()

app = FastAPI(
    title="AI 客户跟进助手 V4",
    description="客户管理 + AI 跟进分析 + RAG 知识库问答 + Agent 自动跟进方案",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Security headers middleware (lightweight, no new deps) ───
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    from fastapi.responses import Response as _Response
    response: _Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Session token helpers (stdlib HMAC, no extra deps) ───

def _make_user_session_token(user_id: int, secret: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": user_id, "t": utc_timestamp()}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), "sha256").digest()
    ).rstrip(b"=").decode()
    return f"{payload}.{sig}"


def _verify_session_token(token: str, secret: str) -> Optional[dict]:
    if "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), "sha256").digest()
    ).rstrip(b"=").decode()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(payload + "=="))
    except Exception:
        return None


# ─── Auth dependency ───

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """返回当前用户；APP_ACCESS_PASSWORD 为空时使用本地开发默认用户。"""
    if not settings.APP_ACCESS_PASSWORD:
        user = db.query(User).filter(User.username == settings.APP_ADMIN_USERNAME).first()
        if not user:
            raise HTTPException(status_code=500, detail="本地开发用户初始化失败")
        return user

    token = request.cookies.get("session")
    payload = _verify_session_token(token, settings.SESSION_SECRET) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    user_id = payload.get("uid")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求当前用户为管理员（role == 'admin'），否则返回 403。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    return current_user


# ─── Auth routes (no login required) ───

class LoginRequest(BaseModel):
    username: Optional[str] = None
    password: str


@app.post("/auth/login")
def auth_login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    if not settings.APP_ACCESS_PASSWORD:
        return {"message": "登录成功（本地开发模式）"}

    username = (data.username or settings.APP_ADMIN_USERNAME).strip()
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    token = _make_user_session_token(user.id, settings.SESSION_SECRET)
    resp = JSONResponse({"message": "登录成功", "username": user.username})
    resp.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=86400 * 7,
    )
    return resp


@app.post("/auth/users", response_model=UserOut)
def create_app_user(
    data: UserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    username = data.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少 3 个字符")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 个字符")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")

    role = data.role.strip() if data.role else "user"
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role 只能是 admin 或 user")

    user = create_user(
        db=db,
        username=username,
        password=data.password,
        is_admin=(role == "admin"),
        role=role,
    )
    return user


@app.post("/auth/register")
def register_user(data: UserCreateRequest, db: Session = Depends(get_db)):
    if not settings.ENABLE_PUBLIC_REGISTRATION:
        raise HTTPException(status_code=403, detail="当前未开放公开注册")

    username = data.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少 3 个字符")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 个字符")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = create_user(db=db, username=username, password=data.password, is_admin=False)
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}


@app.post("/auth/logout")
def auth_logout():
    resp = JSONResponse({"message": "已退出登录"})
    resp.delete_cookie(key="session", path="/")
    return resp


@app.get("/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    if not settings.APP_ACCESS_PASSWORD:
        return {"logged_in": True, "username": settings.APP_ADMIN_USERNAME, "role": "admin", "is_active": True}
    token = request.cookies.get("session")
    payload = _verify_session_token(token, settings.SESSION_SECRET) if token else None
    if payload:
        user = db.query(User).filter(User.id == payload.get("uid")).first()
        if user:
            return {
                "logged_in": True,
                "username": user.username,
                "role": user.role,
                "is_active": user.is_active,
            }
    return {"logged_in": False}


@app.get("/auth/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员查看用户列表。"""
    return db.query(User).order_by(User.id.asc()).all()


@app.patch("/auth/users/{user_id}/status")
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员启用/禁用用户。不能禁用自己。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员账号")
    user.is_active = data.is_active
    db.commit()
    return {"id": user.id, "username": user.username, "is_active": user.is_active}


@app.post("/auth/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前用户修改自己的密码。"""
    if not data.old_password:
        raise HTTPException(status_code=400, detail="旧密码不能为空")
    if not data.new_password or len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 个字符")

    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "密码修改成功"}


# ─── Public routes ───

@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/health")
def health_check():
    """部署健康检查接口，不需要登录。"""
    return {"status": "ok"}


# ─── Business routes (all require login) ───

def get_customer_for_user(db: Session, customer_id: int, user: User) -> Customer:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.user_id == user.id)
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


@app.post("/customers", response_model=CustomerOut)
def create_customer(
    data: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_data = data.model_dump()
    if not customer_data.get("followup_status"):
        customer_data["followup_status"] = "待跟进"
    customer = Customer(user_id=current_user.id, **customer_data)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@app.get("/customers", response_model=List[CustomerOut])
def list_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Customer)
        .filter(Customer.user_id == current_user.id)
        .order_by(Customer.id.desc())
        .all()
    )


# ─── CSV Import / Export / Due (must be before parameterized routes) ───


def _parse_optional_datetime(value: str) -> Optional[datetime]:
    """解析常见 ISO 日期格式，失败返回 None。"""
    if not value:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@app.post("/customers/import")
def import_customers_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入客户 CSV 文件，只导入到当前用户。"""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    try:
        raw = file.file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="无法读取文件内容")

    # 尝试 UTF-8-SIG 和 UTF-8 解码
    content = None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        raise HTTPException(status_code=400, detail="文件编码不支持，请使用 UTF-8 编码的 CSV 文件")

    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV 文件没有任何列")

    created = 0
    skipped = 0
    errors: list[dict] = []

    # 批量内去重追踪（导入过程中尚未提交到数据库的记录）
    batch_seen: set[tuple] = set()

    for row_num, row in enumerate(reader, start=2):
        try:
            name = (row.get("name") or "").strip()
            company = (row.get("company") or "").strip()

            if not name or not company:
                errors.append({"row": row_num, "reason": "name 和 company 为必填项"})
                continue

            phone = (row.get("phone") or "").strip() or None

            # 重复检测：优先 phone，其次 name + company
            if phone:
                duplicate_key = ("phone", phone)
                existing_in_db = (
                    db.query(Customer)
                    .filter(
                        Customer.user_id == current_user.id,
                        Customer.phone == phone,
                    )
                    .first()
                )
            else:
                duplicate_key = ("name_company", name, company)
                existing_in_db = (
                    db.query(Customer)
                    .filter(
                        Customer.user_id == current_user.id,
                        Customer.name == name,
                        Customer.company == company,
                    )
                    .first()
                )

            if existing_in_db or duplicate_key in batch_seen:
                skipped += 1
                continue

            raw_next_followup = (row.get("next_followup_at") or "").strip()
            next_followup_at = _parse_optional_datetime(raw_next_followup)
            if raw_next_followup and next_followup_at is None:
                errors.append({"row": row_num, "reason": "next_followup_at 日期格式不正确"})
                continue

            # 只有通过所有校验、确定要创建的行才加入去重集合
            batch_seen.add(duplicate_key)

            customer = Customer(
                user_id=current_user.id,
                name=name,
                company=company,
                phone=phone,
                email=(row.get("email") or "").strip() or None,
                industry=(row.get("industry") or "").strip() or None,
                level=(row.get("level") or "").strip() or None,
                intention=(row.get("intention") or "").strip() or None,
                cooperation_status=(row.get("cooperation_status") or "").strip() or None,
                source=(row.get("source") or "").strip() or None,
                remark=(row.get("remark") or "").strip() or None,
                next_followup_at=next_followup_at,
                followup_status=(row.get("followup_status") or "").strip() or "待跟进",
            )
            db.add(customer)
            created += 1
        except Exception as exc:
            errors.append({"row": row_num, "reason": str(exc)})

    db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


@app.get("/customers/export")
def export_customers_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出当前用户客户为 CSV 文件（UTF-8-SIG）。"""
    customers = (
        db.query(Customer)
        .filter(Customer.user_id == current_user.id)
        .order_by(Customer.id.asc())
        .all()
    )

    output = io.StringIO()
    output.write("﻿")  # UTF-8 BOM

    fieldnames = [
        "name", "company", "phone", "email", "industry", "level",
        "intention", "cooperation_status", "source", "remark",
        "last_followup_at", "next_followup_at", "followup_status", "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for c in customers:
        writer.writerow({
            "name": c.name,
            "company": c.company,
            "phone": c.phone or "",
            "email": c.email or "",
            "industry": c.industry or "",
            "level": c.level or "",
            "intention": c.intention or "",
            "cooperation_status": c.cooperation_status or "",
            "source": c.source or "",
            "remark": c.remark or "",
            "last_followup_at": c.last_followup_at.isoformat() if c.last_followup_at else "",
            "next_followup_at": c.next_followup_at.isoformat() if c.next_followup_at else "",
            "followup_status": c.followup_status or "",
            "created_at": c.created_at.isoformat() if c.created_at else "",
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": "attachment; filename=customers_export.csv",
        },
    )


@app.get("/customers/due", response_model=List[CustomerOut])
def list_due_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户需要跟进的客户（next_followup_at <= 当前时间 且状态非终态）。"""
    now = datetime.now()
    excluded_statuses = ["成交", "流失", "暂停"]

    return (
        db.query(Customer)
        .filter(
            Customer.user_id == current_user.id,
            Customer.next_followup_at <= now,
            Customer.followup_status.notin_(excluded_statuses),
        )
        .order_by(Customer.next_followup_at.asc())
        .all()
    )


@app.get("/customers/search", response_model=CustomerSearchResult)
def search_customers(
    q: Optional[str] = None,
    industry: Optional[str] = None,
    level: Optional[str] = None,
    intention: Optional[str] = None,
    cooperation_status: Optional[str] = None,
    followup_status: Optional[str] = None,
    source: Optional[str] = None,
    due_only: bool = False,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """搜索/筛选/分页 查询当前用户客户。"""
    query = db.query(Customer).filter(Customer.user_id == current_user.id)

    # 关键词搜索
    if q:
        q_like = f"%{q}%"
        query = query.filter(or_(
            Customer.name.ilike(q_like),
            Customer.company.ilike(q_like),
            Customer.phone.ilike(q_like),
            Customer.email.ilike(q_like),
            Customer.industry.ilike(q_like),
            Customer.source.ilike(q_like),
            Customer.remark.ilike(q_like),
        ))

    # 精确筛选
    if industry:
        query = query.filter(Customer.industry == industry)
    if level:
        query = query.filter(Customer.level == level)
    if intention:
        query = query.filter(Customer.intention == intention)
    if cooperation_status:
        query = query.filter(Customer.cooperation_status == cooperation_status)
    if followup_status:
        query = query.filter(Customer.followup_status == followup_status)
    if source:
        query = query.filter(Customer.source == source)

    # 只看到期待跟进客户
    if due_only:
        now = datetime.now()
        excluded_statuses = ["成交", "流失", "暂停"]
        query = query.filter(
            Customer.next_followup_at <= now,
            Customer.followup_status.notin_(excluded_statuses),
        )

    # 总数
    total = query.count()

    # 分页参数修正
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)

    # 排序
    if due_only:
        query = query.order_by(Customer.next_followup_at.asc())
    else:
        query = query.order_by(Customer.id.desc())

    # 总页数
    pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0
    if page > pages and total > 0:
        page = pages

    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    return CustomerSearchResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@app.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_customer_for_user(db, customer_id, current_user)


@app.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    data: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_for_user(db, customer_id, current_user)

    customer_data = data.model_dump()
    if not customer_data.get("followup_status"):
        customer_data["followup_status"] = "待跟进"

    for key, value in customer_data.items():
        setattr(customer, key, value)

    db.commit()
    db.refresh(customer)
    return customer


@app.delete("/customers/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_for_user(db, customer_id, current_user)

    db.delete(customer)
    db.commit()
    return {"message": "客户已删除"}


@app.post("/customers/{customer_id}/followups", response_model=FollowUpOut)
def create_followup(
    customer_id: int,
    data: FollowUpCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_for_user(db, customer_id, current_user)

    followup_data = {"content": data.content, "next_action": data.next_action}
    followup = FollowUp(customer_id=customer_id, **followup_data)
    db.add(followup)

    # 同步更新 Customer 跟进状态
    customer.last_followup_at = datetime.now()
    if data.next_followup_at is not None:
        customer.next_followup_at = data.next_followup_at
    if data.followup_status is not None:
        customer.followup_status = data.followup_status

    db.commit()
    db.refresh(followup)
    return followup


@app.get("/customers/{customer_id}/followups", response_model=List[FollowUpOut])
def list_followups(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_customer_for_user(db, customer_id, current_user)

    return (
        db.query(FollowUp)
        .filter(FollowUp.customer_id == customer_id)
        .order_by(FollowUp.created_at.desc())
        .all()
    )


@app.get("/followups/export")
def export_followups_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出当前用户客户相关的跟进记录为 CSV 文件（UTF-8-SIG）。"""
    followups = (
        db.query(FollowUp)
        .join(Customer, FollowUp.customer_id == Customer.id)
        .filter(Customer.user_id == current_user.id)
        .order_by(FollowUp.id.asc())
        .all()
    )

    output = io.StringIO()
    output.write("﻿")  # UTF-8 BOM

    fieldnames = [
        "customer_name", "company", "content", "next_action",
        "next_followup_at", "followup_status", "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for f in followups:
        writer.writerow({
            "customer_name": f.customer.name if f.customer else "",
            "company": f.customer.company if f.customer else "",
            "content": f.content or "",
            "next_action": f.next_action or "",
            "next_followup_at": f.customer.next_followup_at.isoformat() if f.customer and f.customer.next_followup_at else "",
            "followup_status": f.customer.followup_status if f.customer else "",
            "created_at": f.created_at.isoformat() if f.created_at else "",
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={
            "Content-Disposition": "attachment; filename=followups_export.csv",
        },
    )


@app.post("/customers/{customer_id}/ai/summary", response_model=AIResult)
def ai_summary(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_for_user(db, customer_id, current_user)

    followups = db.query(FollowUp).filter(FollowUp.customer_id == customer_id).order_by(FollowUp.created_at.asc()).all()
    context = build_customer_context(customer, followups)

    prompt = f"""
请根据下面的客户信息和历史跟进记录，生成一份客户跟进总结。
要求：
1. 判断客户当前阶段；
2. 总结客户需求和风险点；
3. 语言简洁，适合销售人员查看。

{context}
"""
    return AIResult(result=call_llm(prompt, feature="summary", user_id=current_user.id, db=db))


@app.post("/customers/{customer_id}/ai/suggestion", response_model=AIResult)
def ai_suggestion(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = get_customer_for_user(db, customer_id, current_user)

    followups = db.query(FollowUp).filter(FollowUp.customer_id == customer_id).order_by(FollowUp.created_at.asc()).all()
    context = build_customer_context(customer, followups)

    prompt = f"""
你是一个 ToB 销售顾问。请根据下面客户资料，生成下一步跟进建议。
要求：
1. 给出下一步要问客户的问题；
2. 给出一段可以直接复制使用的销售话术；
3. 给出跟进优先级判断；
4. 不要空泛，要具体。

{context}
"""
    return AIResult(result=call_llm(prompt, feature="suggestion", user_id=current_user.id, db=db))


@app.post("/rag/upload")
async def upload_rag_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    chunks = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件过大，最大允许 {settings.MAX_UPLOAD_SIZE_MB}MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    text_content = extract_text_from_upload(file, data)
    chunks = split_text(text_content)

    if not chunks:
        raise HTTPException(status_code=400, detail="文件内容为空，无法加入知识库")

    # ── Delete old vectors BEFORE SQL delete (Fix 1: avoid orphan vectors) ──
    if settings.VECTOR_SEARCH_ENABLED:
        try:
            from app.vector_store import get_vector_store
            vs = get_vector_store()
            if vs is not None:
                vs.delete_filename_chunks(current_user.id, file.filename)
        except Exception as exc:
            logger.warning(f"Vector pre-cleanup failed for '{file.filename}': {exc}")

    # 同名文件重新上传时，先删除旧片段，避免重复检索。
    db.query(DocumentChunk).filter(
        DocumentChunk.filename == file.filename,
        DocumentChunk.user_id == current_user.id,
    ).delete()

    for index, chunk in enumerate(chunks, start=1):
        db.add(DocumentChunk(
            user_id=current_user.id,
            filename=file.filename,
            chunk_index=index,
            content=chunk
        ))

    db.commit()

    # ── Vector indexing (fire-and-forget — failure does NOT fail the upload) ──
    if settings.VECTOR_SEARCH_ENABLED:
        try:
            from app.embeddings import get_embedding_service
            from app.vector_store import get_vector_store

            emb_svc = get_embedding_service()
            vs = get_vector_store()
            if vs is not None:
                # Fetch the chunks we just inserted (ordered by id to match chunk order)
                new_chunks = (
                    db.query(DocumentChunk)
                    .filter(
                        DocumentChunk.filename == file.filename,
                        DocumentChunk.user_id == current_user.id,
                    )
                    .order_by(DocumentChunk.id.asc())
                    .all()
                )
                if new_chunks:
                    texts = [c.content for c in new_chunks]
                    embeddings = emb_svc.embed_documents(texts)
                    vs.add_chunks(
                        ids=[c.id for c in new_chunks],
                        embeddings=embeddings,
                        metadatas=[
                            {
                                "user_id": c.user_id,
                                "filename": c.filename,
                                "chunk_index": c.chunk_index,
                            }
                            for c in new_chunks
                        ],
                    )
                    logger.info(
                        f"Vector indexed {len(new_chunks)} chunks for file '{file.filename}'"
                    )
        except Exception as exc:
            logger.warning(f"Vector indexing skipped (upload continues): {exc}")

    return {
        "message": "资料上传成功",
        "filename": file.filename,
        "chunks": len(chunks)
    }


@app.get("/rag/documents", response_model=List[RagDocument])
def list_rag_documents(
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.user_id == current_user.id)
    )

    # Optional filename search
    if q and q.strip():
        base = base.filter(DocumentChunk.filename.ilike(f"%{q.strip()}%"))

    rows = (
        base.with_entities(
            DocumentChunk.filename,
            func.count(DocumentChunk.id),
            func.max(DocumentChunk.created_at),
        )
        .group_by(DocumentChunk.filename)
        .all()
    )

    # Per-file vector index counts
    vs = None
    if settings.VECTOR_SEARCH_ENABLED:
        try:
            from app.vector_store import get_vector_store
            vs = get_vector_store()
        except Exception:
            pass

    result = []
    for filename, count, latest_ts in rows:
        file_indexed: Optional[int] = None
        if vs is not None and hasattr(vs, "count_file_chunks"):
            try:
                file_indexed = vs.count_file_chunks(current_user.id, filename)
            except Exception:
                pass  # Best-effort per file

        # Lightweight preview: first ~120 chars of the first chunk
        preview: Optional[str] = None
        first = (
            db.query(DocumentChunk.content)
            .filter(
                DocumentChunk.user_id == current_user.id,
                DocumentChunk.filename == filename,
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .first()
        )
        if first and first[0]:
            preview = first[0][:120]

        updated_at = latest_ts.isoformat() if latest_ts else None

        result.append(
            RagDocument(
                filename=filename,
                chunks=count,
                vector_indexed=file_indexed,
                updated_at=updated_at,
                preview=preview,
            )
        )

    return result


@app.get("/rag/documents/{filename}/chunks", response_model=RagChunkList)
def list_rag_file_chunks(
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all chunks for a single file, sorted by chunk_index."""
    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.user_id == current_user.id,
            DocumentChunk.filename == filename,
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=404, detail="资料文件不存在")

    return RagChunkList(
        filename=filename,
        chunks=[
            RagChunkOut(
                chunk_index=c.chunk_index,
                content=c.content,
                created_at=c.created_at.isoformat() if c.created_at else "",
            )
            for c in chunks
        ],
    )


@app.post("/rag/documents/{filename}/reindex")
def reindex_rag_file(
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reindex a single file's vector embeddings for the current user."""
    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.user_id == current_user.id,
            DocumentChunk.filename == filename,
        )
        .order_by(DocumentChunk.id.asc())
        .all()
    )

    if not chunks:
        raise HTTPException(status_code=404, detail="资料文件不存在")

    if not settings.VECTOR_SEARCH_ENABLED:
        return {
            "reindexed": False,
            "message": "向量搜索未启用",
            "filename": filename,
            "chunks": len(chunks),
        }

    try:
        from app.embeddings import get_embedding_service
        from app.vector_store import get_vector_store

        emb_svc = get_embedding_service()
        vs = get_vector_store()
        if vs is None:
            raise RuntimeError("Vector store unavailable")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量服务初始化失败：{exc}")

    try:
        # Clear only this user's file's vectors
        vs.delete_filename_chunks(current_user.id, filename)

        texts = [c.content for c in chunks]
        embeddings = emb_svc.embed_documents(texts)
        vs.add_chunks(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "user_id": c.user_id,
                    "filename": c.filename,
                    "chunk_index": c.chunk_index,
                }
                for c in chunks
            ],
        )

        logger.info(
            "Reindexed %d chunks for file '%s', user %d",
            len(chunks), filename, current_user.id,
        )
        return {
            "message": f"文件 {filename} 重新索引完成，共处理 {len(chunks)} 个片段",
            "chunks": len(chunks),
            "reindexed": True,
            "filename": filename,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"文件重新索引失败：{exc}")


@app.delete("/rag/documents/{filename}")
def delete_rag_document(
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted_count = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.filename == filename, DocumentChunk.user_id == current_user.id)
        .delete()
    )

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="资料不存在")

    db.commit()

    # ── Clean up vector store entries ──
    vector_warning: Optional[str] = None
    if settings.VECTOR_SEARCH_ENABLED:
        try:
            from app.vector_store import get_vector_store
            vs = get_vector_store()
            if vs is not None:
                vs.delete_filename_chunks(current_user.id, filename)
            else:
                vector_warning = "向量索引清理失败（向量存储不可用），索引可能不完整，建议点击「重建向量索引」"
        except Exception as exc:
            logger.error(f"Vector store cleanup failed for file '{filename}': {exc}")
            vector_warning = "向量索引清理失败，索引可能不完整，建议点击「重建向量索引」"

    resp = {
        "message": "资料已删除",
        "filename": filename,
        "deleted_chunks": deleted_count,
    }
    if vector_warning:
        resp["vector_warning"] = vector_warning
    return resp


@app.delete("/rag/documents")
def clear_rag_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted_count = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.user_id == current_user.id)
        .delete()
    )
    db.commit()

    # ── Clean up vector store entries ──
    vector_warning: Optional[str] = None
    if settings.VECTOR_SEARCH_ENABLED:
        try:
            from app.vector_store import get_vector_store
            vs = get_vector_store()
            if vs is not None:
                vs.delete_user_chunks(current_user.id)
            else:
                vector_warning = "向量索引清理失败（向量存储不可用），索引可能不完整，建议点击「重建向量索引」"
        except Exception as exc:
            logger.error(f"Vector store cleanup failed for user {current_user.id}: {exc}")
            vector_warning = "向量索引清理失败，索引可能不完整，建议点击「重建向量索引」"

    resp = {
        "message": "知识库已清空",
        "deleted_chunks": deleted_count,
    }
    if vector_warning:
        resp["vector_warning"] = vector_warning
    return resp


@app.post("/rag/ask", response_model=RagAnswer)
def rag_ask(
    data: RagAsk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    question = data.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    # Check that the user has at least one document uploaded
    chunk_count = (
        db.query(func.count(DocumentChunk.id))
        .filter(DocumentChunk.user_id == current_user.id)
        .scalar()
    )
    if not chunk_count:
        raise HTTPException(status_code=400, detail="请先上传产品资料或行业资料")

    retrieved = retrieve_chunks_vector(
        db, question, current_user.id, top_k=settings.VECTOR_SEARCH_TOP_K
    )
    if not retrieved:
        raise HTTPException(status_code=400, detail="知识库中没有检索到相关资料，请换个问法或上传更多资料")

    prompt = build_rag_prompt(question, retrieved)
    answer = call_llm(prompt, feature="rag_ask", user_id=current_user.id, db=db)

    return RagAnswer(
        answer=answer,
        sources=[
            RagSource(
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                content=chunk.content[:260]
            )
            for chunk in retrieved
        ]
    )


@app.post("/rag/reindex")
def rag_reindex(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-compute embeddings for all existing chunks and re-index in the vector store.

    Safe to call multiple times — idempotent per user.
    """
    if not settings.VECTOR_SEARCH_ENABLED:
        return {"message": "向量搜索未启用", "reindexed": False, "chunks": 0}

    try:
        from app.embeddings import get_embedding_service
        from app.vector_store import get_vector_store

        emb_svc = get_embedding_service()
        vs = get_vector_store()
        if vs is None:
            raise RuntimeError("Vector store unavailable")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"向量服务初始化失败：{exc}")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.user_id == current_user.id)
        .order_by(DocumentChunk.id.asc())
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="知识库为空，无需重新索引")

    try:
        # Clear existing vector entries for this user, then re-index
        vs.delete_user_chunks(current_user.id)

        texts = [c.content for c in chunks]
        embeddings = emb_svc.embed_documents(texts)
        vs.add_chunks(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "user_id": c.user_id,
                    "filename": c.filename,
                    "chunk_index": c.chunk_index,
                }
                for c in chunks
            ],
        )

        logger.info(f"Reindexed {len(chunks)} chunks for user {current_user.id}")
        return {
            "message": f"重新索引完成，共处理 {len(chunks)} 个片段",
            "chunks": len(chunks),
            "reindexed": True,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重新索引失败：{exc}")


@app.post("/agent/analyze", response_model=AgentAnalyzeResult)
def agent_analyze(
    data: AgentAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = (data.task or "帮我分析这个客户下一步怎么跟进").strip()

    try:
        steps, result, sources = run_customer_followup_agent(
            db=db,
            customer_id=data.customer_id,
            user_id=current_user.id,
            task=task,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return AgentAnalyzeResult(
        steps=steps,
        result=result,
        sources=sources,
    )


# ─── Admin: AI call logs ───


class AiCallLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    feature: str
    provider: str
    model: str
    prompt_chars: int
    response_chars: int
    estimated_prompt_tokens: int
    estimated_response_tokens: int
    status: str
    error_message: Optional[str] = None
    duration_ms: int
    created_at: str


class AiCallLogPage(BaseModel):
    items: List[AiCallLogOut]
    total: int
    page: int
    page_size: int
    pages: int


@app.get("/admin/ai-logs", response_model=AiCallLogPage)
def admin_ai_logs(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员查看 AI 调用日志（不返回 prompt 原文和 API Key）。"""
    from app.models import AiCallLog

    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)

    total = db.query(AiCallLog).count()
    pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0
    if page > pages and total > 0:
        page = pages

    offset = (page - 1) * page_size
    rows = (
        db.query(AiCallLog)
        .order_by(AiCallLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        AiCallLogOut(
            id=r.id,
            user_id=r.user_id,
            feature=r.feature,
            provider=r.provider,
            model=r.model,
            prompt_chars=r.prompt_chars,
            response_chars=r.response_chars,
            estimated_prompt_tokens=r.estimated_prompt_tokens,
            estimated_response_tokens=r.estimated_response_tokens,
            status=r.status,
            error_message=r.error_message,
            duration_ms=r.duration_ms,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]

    return AiCallLogPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
