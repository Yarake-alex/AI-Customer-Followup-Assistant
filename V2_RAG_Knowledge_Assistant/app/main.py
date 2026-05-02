from typing import List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Customer, FollowUp, DocumentChunk
from app.schemas import (
    CustomerCreate,
    CustomerOut,
    FollowUpCreate,
    FollowUpOut,
    AIResult,
    RagAsk,
    RagAnswer,
    RagSource,
    RagDocument,
)
from app.llm import build_customer_context, call_llm
from app.rag import extract_text_from_upload, split_text, retrieve_chunks, build_rag_prompt


Base.metadata.create_all(bind=engine)


def upgrade_database():
    """
    兼容旧数据库。
    如果之前已经生成过 customer_assistant.db，旧 customers 表里可能没有 cooperation_status 字段。
    这里启动时自动补上字段，避免手动删库。
    """
    with engine.connect() as conn:
        columns = conn.execute(text("PRAGMA table_info(customers)")).fetchall()
        column_names = [col[1] for col in columns]

        if "cooperation_status" not in column_names:
            conn.execute(text("ALTER TABLE customers ADD COLUMN cooperation_status VARCHAR(20)"))
            conn.commit()


upgrade_database()

app = FastAPI(
    title="AI 客户跟进助手 V2",
    description="客户管理 + 跟进记录 + AI 总结 + AI 跟进建议 + RAG 知识库问答",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/customers", response_model=CustomerOut)
def create_customer(data: CustomerCreate, db: Session = Depends(get_db)):
    customer = Customer(**data.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@app.get("/customers", response_model=List[CustomerOut])
def list_customers(db: Session = Depends(get_db)):
    return db.query(Customer).order_by(Customer.id.desc()).all()


@app.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


@app.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, data: CustomerCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    for key, value in data.model_dump().items():
        setattr(customer, key, value)

    db.commit()
    db.refresh(customer)
    return customer


@app.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    db.delete(customer)
    db.commit()
    return {"message": "客户已删除"}


@app.post("/customers/{customer_id}/followups", response_model=FollowUpOut)
def create_followup(customer_id: int, data: FollowUpCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    followup = FollowUp(customer_id=customer_id, **data.model_dump())
    db.add(followup)
    db.commit()
    db.refresh(followup)
    return followup


@app.get("/customers/{customer_id}/followups", response_model=List[FollowUpOut])
def list_followups(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    return (
        db.query(FollowUp)
        .filter(FollowUp.customer_id == customer_id)
        .order_by(FollowUp.created_at.desc())
        .all()
    )


@app.post("/customers/{customer_id}/ai/summary", response_model=AIResult)
def ai_summary(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

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
    return AIResult(result=call_llm(prompt))


@app.post("/customers/{customer_id}/ai/suggestion", response_model=AIResult)
def ai_suggestion(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

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
    return AIResult(result=call_llm(prompt))


@app.post("/rag/upload")
async def upload_rag_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    text_content = extract_text_from_upload(file, data)
    chunks = split_text(text_content)

    if not chunks:
        raise HTTPException(status_code=400, detail="文件内容为空，无法加入知识库")

    # 同名文件重新上传时，先删除旧片段，避免重复检索。
    db.query(DocumentChunk).filter(DocumentChunk.filename == file.filename).delete()

    for index, chunk in enumerate(chunks, start=1):
        db.add(DocumentChunk(
            filename=file.filename,
            chunk_index=index,
            content=chunk
        ))

    db.commit()
    return {
        "message": "资料上传成功",
        "filename": file.filename,
        "chunks": len(chunks)
    }


@app.get("/rag/documents", response_model=List[RagDocument])
def list_rag_documents(db: Session = Depends(get_db)):
    rows = (
        db.query(DocumentChunk.filename, func.count(DocumentChunk.id))
        .group_by(DocumentChunk.filename)
        .all()
    )

    return [
        RagDocument(filename=filename, chunks=count)
        for filename, count in rows
    ]


@app.delete("/rag/documents/{filename}")
def delete_rag_document(filename: str, db: Session = Depends(get_db)):
    deleted_count = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.filename == filename)
        .delete()
    )

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="资料不存在")

    db.commit()
    return {
        "message": "资料已删除",
        "filename": filename,
        "deleted_chunks": deleted_count
    }


@app.delete("/rag/documents")
def clear_rag_documents(db: Session = Depends(get_db)):
    deleted_count = db.query(DocumentChunk).delete()
    db.commit()

    return {
        "message": "知识库已清空",
        "deleted_chunks": deleted_count
    }


@app.post("/rag/ask", response_model=RagAnswer)
def rag_ask(data: RagAsk, db: Session = Depends(get_db)):
    question = data.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    chunks = db.query(DocumentChunk).order_by(DocumentChunk.id.asc()).all()
    if not chunks:
        raise HTTPException(status_code=400, detail="请先上传产品资料或行业资料")

    retrieved = retrieve_chunks(question, chunks, top_k=4)
    if not retrieved:
        raise HTTPException(status_code=400, detail="知识库中没有检索到相关资料，请换个问法或上传更多资料")

    prompt = build_rag_prompt(question, retrieved)
    answer = call_llm(prompt)

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
