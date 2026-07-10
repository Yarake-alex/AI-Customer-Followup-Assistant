import pytest

CUSTOMER_DATA = {
    "name": "张三",
    "company": "测试科技有限公司",
    "phone": "13800138000",
    "email": "zhangsan@test.com",
    "industry": "汽车电子",
    "level": "A",
    "intention": "高",
    "cooperation_status": "跟进洽谈",
}


def login(client):
    """辅助函数：用 test-password 登录。"""
    client.cookies.clear()
    resp = client.post("/auth/login", json={"password": "test-password"})
    assert resp.status_code == 200


# ─── Auth Tests ───

class TestAuth:
    def test_health_check_public(self, client):
        """GET /health 不需要登录，返回 {"status": "ok"}。"""
        client.cookies.clear()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_no_login_returns_401(self, client):
        client.cookies.clear()
        resp = client.get("/customers")
        assert resp.status_code == 401

    def test_wrong_password_returns_401(self, client):
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "wrong-password"})
        assert resp.status_code == 401

    def test_correct_password_logs_in(self, client):
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        assert resp.status_code == 200
        data = resp.json()
        assert "登录成功" in data["message"]

    def test_login_cookie_has_httponly(self, client):
        """登录返回的 Set-Cookie 必须包含 HttpOnly。"""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        set_cookie = resp.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie, "Cookie 缺少 HttpOnly 标志"

    def test_login_cookie_no_plain_password(self, client):
        """Cookie 中不能包含明文密码。"""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        set_cookie = resp.headers.get("set-cookie", "")
        assert "test-password" not in set_cookie, "Cookie 中不应出现明文密码"

    def test_auth_me_unauthenticated(self, client):
        """未登录时 GET /auth/me 返回 logged_in=false。"""
        client.cookies.clear()
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json() == {"logged_in": False}

    def test_auth_me_authenticated(self, client):
        """登录后 GET /auth/me 返回 logged_in=true。"""
        client.cookies.clear()
        login(client)
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["logged_in"] is True
        assert resp.json()["username"] == "admin"

    def test_root_public(self, client):
        """首页 / 不需要登录。"""
        client.cookies.clear()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_login_then_access_protected_route(self, client):
        client.cookies.clear()
        login(client)
        resp = client.get("/customers")
        assert resp.status_code == 200

    def test_logout_clears_session(self, client):
        client.cookies.clear()
        login(client)
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        resp = client.get("/customers")
        assert resp.status_code == 401

    def test_rag_ask_no_login(self, client):
        client.cookies.clear()
        resp = client.post("/rag/ask", json={"question": "test"})
        assert resp.status_code == 401

    def test_agent_no_login(self, client):
        client.cookies.clear()
        resp = client.post("/agent/analyze", json={"customer_id": 1, "task": "test"})
        assert resp.status_code == 401

    def test_dev_mode_no_password(self, client, monkeypatch):
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "")
        client.cookies.clear()
        resp = client.get("/customers")
        assert resp.status_code == 200

    def test_admin_can_create_user(self, client):
        client.cookies.clear()
        login(client)
        resp = client.post(
            "/auth/users",
            json={"username": "sales-user", "password": "sales-user-password"},
        )
        assert resp.status_code in (200, 409)

    def test_customer_data_is_scoped_by_user(self, client):
        client.cookies.clear()
        login(client)
        client.post(
            "/auth/users",
            json={"username": "isolated-user", "password": "isolated-user-password"},
        )
        resp = client.post("/customers", json={**CUSTOMER_DATA, "name": "管理员客户"})
        assert resp.status_code == 200

        client.cookies.clear()
        resp = client.post(
            "/auth/login",
            json={"username": "isolated-user", "password": "isolated-user-password"},
        )
        assert resp.status_code == 200

        resp = client.get("/customers")
        assert resp.status_code == 200
        assert resp.json() == []


# ─── Customer Tests ───

@pytest.fixture
def customer_id(client):
    """创建一个测试客户，供需要真实客户 ID 的测试使用。"""
    login(client)
    resp = client.post("/customers", json=CUSTOMER_DATA)
    assert resp.status_code == 200
    return resp.json()["id"]


class TestCustomers:
    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_create_customer(self, client):
        resp = client.post("/customers", json=CUSTOMER_DATA)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "张三"
        assert data["company"] == "测试科技有限公司"
        assert data["phone"] == "13800138000"
        assert data["email"] == "zhangsan@test.com"
        assert data["industry"] == "汽车电子"
        assert data["level"] == "A"
        assert data["intention"] == "高"
        assert data["cooperation_status"] == "跟进洽谈"
        assert "id" in data

    def test_list_customers(self, client):
        # 每个测试自己创建所需数据，不依赖其他测试的执行顺序
        client.post("/customers", json=CUSTOMER_DATA)
        resp = client.get("/customers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1


class TestFollowups:
    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_create_followup(self, client, customer_id):
        resp = client.post(
            f"/customers/{customer_id}/followups",
            json={"content": "电话沟通，客户对产品感兴趣", "next_action": "发送产品资料和报价"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "电话沟通，客户对产品感兴趣"
        assert data["next_action"] == "发送产品资料和报价"
        assert data["customer_id"] == customer_id
        assert "id" in data


class TestUpload:
    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_upload_too_large(self, client):
        """超过 MAX_UPLOAD_SIZE_MB=1 的文件应返回 413。"""
        content = b"x" * (1024 * 1024 + 1)
        resp = client.post(
            "/rag/upload",
            files={"file": ("big.txt", content, "text/plain")},
        )
        assert resp.status_code == 413
        assert "文件过大" in resp.text

    def test_upload_small_file(self, client):
        """小于限制的文本文件应上传成功并返回片段数。"""
        content = b"hello world, this is a test document for RAG knowledge base."
        resp = client.post(
            "/rag/upload",
            files={"file": ("test.txt", content, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks"] > 0
        assert data["filename"] == "test.txt"


class TestRagAsk:
    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_rag_ask_auth_passed(self, client):
        """已登录，鉴权通过（结果可能因知识库有无资料而异，但不返回 401）。"""
        resp = client.post("/rag/ask", json={"question": "test"})
        assert resp.status_code != 401


class TestAgent:
    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_agent_customer_not_found(self, client):
        """已登录但客户不存在，应返回 404（鉴权通过）。"""
        resp = client.post(
            "/agent/analyze",
            json={"customer_id": 99999, "task": "test"},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Vector RAG Tests — 真实向量检索路径（EMBEDDING_PROVIDER=test）
# 每个测试使用独立的 SQLite + ChromaDB（function-scoped fixture）
# ═══════════════════════════════════════════════════════════════


class TestVectorUpload:
    """向量索引路径的上传测试。"""

    def test_upload_indexes_vectors(self, vector_client):
        """上传文件后，per-file vector_indexed > 0。"""
        resp = vector_client.post(
            "/rag/upload",
            files={"file": ("test.txt", b"Hello world. This is a test document for vector indexing.")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks"] > 0

        list_resp = vector_client.get("/rag/documents")
        assert list_resp.status_code == 200
        docs = list_resp.json()
        assert len(docs) == 1
        assert docs[0]["filename"] == "test.txt"
        assert docs[0]["vector_indexed"] is not None
        assert docs[0]["vector_indexed"] == data["chunks"], (
            f"Expected per-file indexed={data['chunks']}, got {docs[0]['vector_indexed']}"
        )

    def test_per_file_vector_counts(self, vector_client):
        """每个文件独立上报 vector_indexed，互不干扰。"""
        vector_client.post(
            "/rag/upload",
            files={"file": ("a.txt", b"Document A content for vector testing.")},
        )
        vector_client.post(
            "/rag/upload",
            files={"file": ("b.txt", b"Document B different content for indexing.")},
        )

        docs = vector_client.get("/rag/documents").json()
        docs.sort(key=lambda d: d["filename"])

        assert docs[0]["filename"] == "a.txt"
        assert docs[0]["vector_indexed"] == docs[0]["chunks"]
        assert docs[1]["filename"] == "b.txt"
        assert docs[1]["vector_indexed"] == docs[1]["chunks"]

    def test_vector_search_after_upload(self, vector_client):
        """上传资料后，向量检索应返回相关片段。"""
        vector_client.post(
            "/rag/upload",
            files={"file": ("product.txt", b"LCD display panel for automotive dashboard.")},
        )

        resp = vector_client.post(
            "/rag/ask",
            json={"question": "car display panel"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert len(data["sources"]) > 0
        assert data["sources"][0]["filename"] == "product.txt"

    def test_reupload_same_file(self, vector_client):
        """同名文件重传：旧向量清除 → 新向量写入，无重复 ID，列表唯一。"""
        resp1 = vector_client.post(
            "/rag/upload",
            files={"file": ("same.txt", b"Version one content for testing reupload.")},
        )
        assert resp1.status_code == 200

        resp2 = vector_client.post(
            "/rag/upload",
            files={"file": ("same.txt", b"Version two updated content for testing reupload.")},
        )
        assert resp2.status_code == 200

        docs = vector_client.get("/rag/documents").json()
        filenames = [d["filename"] for d in docs]
        assert filenames.count("same.txt") == 1
        # After reupload, all chunks should be indexed
        assert docs[0]["vector_indexed"] == docs[0]["chunks"]


class TestVectorDelete:
    """向量索引路径的删除测试。"""

    def test_delete_clears_vectors(self, vector_client):
        """删除文件后向量同步清除，保留的文件不受影响。"""
        vector_client.post(
            "/rag/upload",
            files={"file": ("keep.txt", b"This file should remain in the knowledge base.")},
        )
        vector_client.post(
            "/rag/upload",
            files={"file": ("remove.txt", b"This file will be deleted from the knowledge base.")},
        )

        import urllib.parse
        encoded = urllib.parse.quote("remove.txt", safe="")
        del_resp = vector_client.delete(f"/rag/documents/{encoded}")
        assert del_resp.status_code == 200
        # vector_warning should NOT be present when sync succeeds
        assert "vector_warning" not in del_resp.json()

        docs = vector_client.get("/rag/documents").json()
        filenames = [d["filename"] for d in docs]
        assert "keep.txt" in filenames
        assert "remove.txt" not in filenames
        # Remaining file should have full vector coverage
        assert docs[0]["vector_indexed"] == docs[0]["chunks"]

    def test_clear_all_vectors(self, vector_client):
        """清空全部后列表为空。"""
        vector_client.post(
            "/rag/upload",
            files={"file": ("clear_me.txt", b"Content that will be cleared.")},
        )

        del_resp = vector_client.delete("/rag/documents")
        assert del_resp.status_code == 200
        assert "vector_warning" not in del_resp.json()

        docs = vector_client.get("/rag/documents").json()
        assert len(docs) == 0


class TestVectorDualUserIsolation:
    """真正的双用户向量隔离测试。"""

    def test_dual_user_isolation(self, vector_client_dual_user):
        """用户 A 和用户 B 互相看不到对方的资料和检索结果。"""
        admin, user2 = vector_client_dual_user

        # Admin uploads doc A
        admin.post(
            "/rag/upload",
            files={"file": ("admin_doc.txt", b"Admin proprietary knowledge about LCD displays.")},
        )
        # User2 uploads doc B
        user2.post(
            "/rag/upload",
            files={"file": ("user2_doc.txt", b"User2 proprietary knowledge about OLED displays.")},
        )

        # Admin lists documents — only admin_doc
        admin_docs = admin.get("/rag/documents").json()
        admin_files = [d["filename"] for d in admin_docs]
        assert "admin_doc.txt" in admin_files
        assert "user2_doc.txt" not in admin_files

        # User2 lists documents — only user2_doc
        user2_docs = user2.get("/rag/documents").json()
        user2_files = [d["filename"] for d in user2_docs]
        assert "user2_doc.txt" in user2_files
        assert "admin_doc.txt" not in user2_files

        # Admin searches — should only find LCD results
        admin_ask = admin.post("/rag/ask", json={"question": "display technology"})
        assert admin_ask.status_code == 200
        for s in admin_ask.json()["sources"]:
            assert s["filename"] == "admin_doc.txt", f"Admin saw {s['filename']}"

        # User2 searches — should only find OLED results
        user2_ask = user2.post("/rag/ask", json={"question": "display technology"})
        assert user2_ask.status_code == 200
        for s in user2_ask.json()["sources"]:
            assert s["filename"] == "user2_doc.txt", f"User2 saw {s['filename']}"


class TestVectorReindex:
    """向量索引重建测试。"""

    def test_reindex_endpoint(self, vector_client):
        """重建索引后，per-file vector_indexed 恢复完整。"""
        vector_client.post(
            "/rag/upload",
            files={"file": ("reindex_test.txt", b"Reindex test content for vector database.")},
        )

        reindex_resp = vector_client.post("/rag/reindex")
        assert reindex_resp.status_code == 200
        data = reindex_resp.json()
        assert data["reindexed"] is True
        assert data["chunks"] > 0
        assert "重新索引完成" in data["message"]

        # Verify per-file counts match
        docs = vector_client.get("/rag/documents").json()
        assert docs[0]["vector_indexed"] == docs[0]["chunks"]

    def test_reindex_empty_knowledge_base(self, vector_client):
        """空知识库调用 reindex 应返回 400。"""
        resp = vector_client.post("/rag/reindex")
        assert resp.status_code == 400
        assert "为空" in resp.json()["detail"]


class TestVectorFallback:
    """向量异常回退测试。"""

    def test_vector_disabled_falls_back(self, logged_in_client):
        """VECTOR_SEARCH_ENABLED=false 时，应回退到 TF-IDF 检索。"""
        logged_in_client.post(
            "/rag/upload",
            files={"file": ("fallback.txt", b"TF-IDF fallback test content.")},
        )

        resp = logged_in_client.post(
            "/rag/ask",
            json={"question": "fallback test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        # mock TF-IDF fallback marker
        assert "【AI模拟RAG回答】" in data["answer"]


# ═══════════════════════════════════════════════════════════════
# Phase 1 Tests — 客户新字段、导入/导出、待跟进管理
# ═══════════════════════════════════════════════════════════════


class TestCustomerNewFields:
    """新字段创建/读取测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_create_customer_with_new_fields(self, client):
        """创建客户时可传入新字段，读取时返回新字段。"""
        resp = client.post("/customers", json={
            **CUSTOMER_DATA,
            "source": "展会",
            "remark": "意向客户，需重点跟进",
            "next_followup_at": "2026-07-15T10:00:00",
            "followup_status": "待跟进",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "张三"
        assert data["source"] == "展会"
        assert data["remark"] == "意向客户，需重点跟进"
        assert data["next_followup_at"] is not None
        assert data["followup_status"] == "待跟进"
        assert data["last_followup_at"] is None  # 新建客户无跟进记录

    def test_create_customer_default_followup_status(self, client):
        """不传 followup_status 时默认为 待跟进。"""
        resp = client.post("/customers", json=CUSTOMER_DATA)
        assert resp.status_code == 200
        data = resp.json()
        assert data["followup_status"] == "待跟进"

    def test_update_customer_new_fields(self, client):
        """更新客户时可修改新字段。"""
        resp = client.post("/customers", json=CUSTOMER_DATA)
        cid = resp.json()["id"]

        resp = client.put(f"/customers/{cid}", json={
            **CUSTOMER_DATA,
            "source": "转介绍",
            "remark": "已发送报价",
            "followup_status": "已跟进",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "转介绍"
        assert data["remark"] == "已发送报价"
        assert data["followup_status"] == "已跟进"

    def test_create_customer_null_followup_status(self, client):
        """POST /customers 显式传入 followup_status: null 不应 500，应归一为 待跟进。"""
        resp = client.post("/customers", json={
            **CUSTOMER_DATA,
            "followup_status": None,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["followup_status"] == "待跟进"

    def test_update_customer_null_followup_status(self, client):
        """PUT /customers/{id} 显式传入 followup_status: null 不应 500，应归一为 待跟进。"""
        # 先创建客户（初始状态为已跟进）
        resp = client.post("/customers", json={
            **CUSTOMER_DATA,
            "followup_status": "已跟进",
        })
        assert resp.status_code == 200
        cid = resp.json()["id"]

        # 更新时显式传 null
        resp = client.put(f"/customers/{cid}", json={
            **CUSTOMER_DATA,
            "followup_status": None,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["followup_status"] == "待跟进"


class TestFollowupSyncCustomer:
    """创建跟进记录后同步更新 Customer 字段。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_followup_updates_last_followup_at(self, client, customer_id):
        """创建跟进记录后，Customer.last_followup_at 被更新。"""
        # Verify last_followup_at is None before followup
        resp = client.get(f"/customers/{customer_id}")
        assert resp.json()["last_followup_at"] is None

        resp = client.post(
            f"/customers/{customer_id}/followups",
            json={"content": "电话沟通", "next_action": "发送资料"},
        )
        assert resp.status_code == 200

        resp = client.get(f"/customers/{customer_id}")
        data = resp.json()
        assert data["last_followup_at"] is not None, "创建跟进后 last_followup_at 应被设置"

    def test_followup_updates_next_followup_and_status(self, client, customer_id):
        """创建跟进时传入 next_followup_at 和 followup_status，Customer 对应字段被更新。"""
        resp = client.post(
            f"/customers/{customer_id}/followups",
            json={
                "content": "电话沟通",
                "next_action": "发送资料",
                "next_followup_at": "2026-08-01T09:00:00",
                "followup_status": "已跟进",
            },
        )
        assert resp.status_code == 200

        resp = client.get(f"/customers/{customer_id}")
        data = resp.json()
        assert data["next_followup_at"] is not None
        assert "2026-08-01" in data["next_followup_at"]
        assert data["followup_status"] == "已跟进"


class TestCsvImport:
    """CSV 导入测试。"""

    CSV_HEADER = (
        "name,company,phone,email,industry,level,intention,"
        "cooperation_status,source,remark,next_followup_at,followup_status"
    )

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_import_success(self, client):
        """CSV 导入成功，返回 created 计数。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            "李四,四通科技,13900001111,lisi@test.com,汽车电子,A,高,跟进洽谈,展会,备注1,,待跟进\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8-sig"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert len(data["errors"]) == 0

    def test_import_missing_name_company_errors(self, client):
        """缺少 name 或 company 时不阻塞其他行，返回 errors。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            ",,13900001111,a@test.com,行业,A,高,跟进洽谈,,,,\n"  # 缺少 name 和 company
            "王五,五洲集团,13900002222,b@test.com,行业,B,中,跟进洽谈,,,,\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert len(data["errors"]) == 1
        assert data["errors"][0]["row"] == 2  # 数据第2行（header是第1行）

    def test_import_duplicate_skipped(self, client):
        """重复客户返回 skipped，同一用户内重复检测生效。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            "赵六,六合科技,13900003333,z6@test.com,行业,A,高,跟进洽谈,,,,待跟进\n"
            "赵六,六合科技,13900003333,z6@test.com,行业,A,高,跟进洽谈,,,,已跟进\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["skipped"] == 1

    def test_import_duplicate_by_name_company_no_phone(self, client):
        """phone 为空时用 name + company 判断重复。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            "钱七,七星电子,,,,,,,,,\n"
            "钱七,七星电子,,,,,,,,,\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["skipped"] == 1

    def test_import_rejects_non_csv(self, client):
        """非 CSV 文件扩展名应被拒绝。"""
        resp = client.post(
            "/customers/import",
            files={"file": ("test.txt", b"not csv", "text/plain")},
        )
        assert resp.status_code == 400

    def test_import_invalid_next_followup_at_errors(self, client):
        """CSV 中一行 next_followup_at 为非法日期时，该行进入 errors，其他合法行仍可创建。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            "孙八,八达科技,13900004444,sunba@test.com,汽车电子,A,高,跟进洽谈,,,abc,待跟进\n"
            "周九,九州集团,13900005555,zhoujiu@test.com,汽车电子,B,中,跟进洽谈,,,,待跟进\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 只有第二行（合法日期为空）应该被创建
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert len(data["errors"]) == 1
        assert data["errors"][0]["row"] == 2  # 第一行数据
        assert "next_followup_at" in data["errors"][0]["reason"]

    def test_import_invalid_next_followup_at_not_created(self, client):
        """非法日期行不应被创建到数据库。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            "吴十,十全科技,13900006666,wu10@test.com,汽车电子,A,高,跟进洽谈,,,bad-date,待跟进\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 0
        assert len(data["errors"]) == 1
        # 确认该客户没有被创建
        list_resp = client.get("/customers")
        customers = list_resp.json()
        names = [c["name"] for c in customers]
        assert "吴十" not in names

    def test_invalid_date_does_not_poison_batch_seen(self, client):
        """非法日期行不应加入 batch_seen，后续同 phone 的合法行仍可创建。"""
        csv_content = (
            f"{self.CSV_HEADER}\n"
            "郑一,正一科技,13900007777,zhengyi@test.com,汽车电子,A,高,跟进洽谈,,,bad-date,待跟进\n"
            "郑一,正一科技,13900007777,zhengyi@test.com,汽车电子,A,高,跟进洽谈,,,,待跟进\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 第一行非法日期 → errors；第二行合法 → created
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert len(data["errors"]) == 1
        assert data["errors"][0]["row"] == 2
        assert "next_followup_at" in data["errors"][0]["reason"]
        # 确认郑一存在于客户列表
        list_resp = client.get("/customers")
        customers = list_resp.json()
        names = [c["name"] for c in customers]
        assert "郑一" in names


class TestCsvImportCrossUser:
    """不同用户之间重复检测隔离。"""

    def test_cross_user_duplicate_isolation(self, client):
        """A 用户已有客户不应导致 B 用户导入 skipped。"""
        login(client)

        # Admin creates a customer
        client.post("/customers", json={
            "name": "跨用户测试", "company": "跨用户公司", "phone": "13800000001"
        })

        # Create a second user
        client.post(
            "/auth/users",
            json={"username": "import-user", "password": "import-user-password"},
        )

        # Login as second user
        client.cookies.clear()
        resp = client.post(
            "/auth/login",
            json={"username": "import-user", "password": "import-user-password"},
        )
        assert resp.status_code == 200

        # Second user imports same customer — should NOT be skipped
        csv_header = "name,company,phone,email,industry,level,intention,cooperation_status,source,remark,next_followup_at,followup_status"
        csv_content = (
            f"{csv_header}\n"
            "跨用户测试,跨用户公司,13800000001,test@test.com,,,,,,,\n"
        )
        resp = client.post(
            "/customers/import",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should be created, not skipped — different user
        assert data["created"] == 1
        assert data["skipped"] == 0


class TestCsvExport:
    """CSV 导出测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_export_only_current_user_customers(self, client):
        """导出只包含当前用户客户。"""
        client.post("/customers", json={
            "name": "导出测试", "company": "导出公司", "phone": "13800009999"
        })

        resp = client.get("/customers/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        # Check raw bytes for content since StreamingResponse uses iter
        content = resp.content.decode("utf-8-sig")
        assert "导出测试" in content
        assert "导出公司" in content

    def test_export_utf8_bom(self, client):
        """导出文件包含 UTF-8 BOM。"""
        client.post("/customers", json={
            "name": "BOM测试", "company": "BOM公司"
        })
        resp = client.get("/customers/export")
        # UTF-8 BOM is bytes EF BB BF
        assert resp.content[:3] == b"\xef\xbb\xbf"


class TestFollowupExport:
    """跟进记录导出测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_export_only_current_user_followups(self, client):
        """跟进记录导出只包含当前用户客户的跟进记录。"""
        # Create customer and followup
        resp = client.post("/customers", json={
            "name": "跟进导出测试", "company": "跟进导出公司"
        })
        cid = resp.json()["id"]
        client.post(
            f"/customers/{cid}/followups",
            json={"content": "测试跟进内容", "next_action": "测试下一步"},
        )

        resp = client.get("/followups/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        content = resp.text
        assert "跟进导出测试" in content
        assert "测试跟进内容" in content


class TestDueCustomers:
    """待跟进客户接口测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_due_returns_only_current_user(self, client):
        """只返回当前用户的到期客户。"""
        # Create a customer with next_followup_at in the past
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "到期客户",
            "next_followup_at": "2020-01-01T00:00:00",
            "followup_status": "待跟进",
        })

        resp = client.get("/customers/due")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data]
        assert "到期客户" in names

    def test_due_excludes_closed_statuses(self, client):
        """不返回状态为 成交、流失、暂停 的客户。"""
        for status, name in [("成交", "成交客户"), ("流失", "流失客户"), ("暂停", "暂停客户")]:
            client.post("/customers", json={
                **CUSTOMER_DATA,
                "name": name,
                "phone": f"138{hash(name)%100000000:08d}",
                "next_followup_at": "2020-01-01T00:00:00",
                "followup_status": status,
            })

        resp = client.get("/customers/due")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data]
        assert "成交客户" not in names
        assert "流失客户" not in names
        assert "暂停客户" not in names

    def test_due_orders_by_next_followup_asc(self, client):
        """按 next_followup_at 升序排列。"""
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "较晚到期",
            "phone": "13800000101",
            "next_followup_at": "2020-01-10T00:00:00",
            "followup_status": "待跟进",
        })
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "较早到期",
            "phone": "13800000102",
            "next_followup_at": "2020-01-01T00:00:00",
            "followup_status": "待跟进",
        })

        resp = client.get("/customers/due")
        assert resp.status_code == 200
        data = resp.json()
        # 较早的在前面
        assert len(data) >= 2
        due_names = [c["name"] for c in data if c["name"] in ("较早到期", "较晚到期")]
        assert due_names[0] == "较早到期"
        assert due_names[1] == "较晚到期"


class TestDueCustomersCrossUser:
    """待跟进客户跨用户隔离测试。"""

    def test_due_cross_user_isolation(self, client):
        """用户 B 看不到用户 A 的待跟进客户。"""
        login(client)

        # Admin creates a due customer
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "管理员待跟进",
            "phone": "13800000201",
            "next_followup_at": "2020-01-01T00:00:00",
            "followup_status": "待跟进",
        })

        # Create and login as second user
        client.post(
            "/auth/users",
            json={"username": "due-user", "password": "due-user-password"},
        )
        client.cookies.clear()
        resp = client.post(
            "/auth/login",
            json={"username": "due-user", "password": "due-user-password"},
        )
        assert resp.status_code == 200

        # Second user should see no due customers
        resp = client.get("/customers/due")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data]
        assert "管理员待跟进" not in names


# ═══════════════════════════════════════════════════════════════
# Phase 2 Tests — 客户搜索、筛选、分页
# ═══════════════════════════════════════════════════════════════


class TestCustomerSearch:
    """客户搜索/筛选/分页接口测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_search_no_params_returns_all(self, client):
        """未传参数时，返回当前用户客户。"""
        client.post("/customers", json={**CUSTOMER_DATA, "name": "搜索测试A"})
        client.post("/customers", json={**CUSTOMER_DATA, "name": "搜索测试B", "phone": "13900000001"})

        resp = client.get("/customers/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert data["page"] == 1
        assert data["page_size"] == 10
        names = [c["name"] for c in data["items"]]
        assert "搜索测试A" in names
        assert "搜索测试B" in names

    def test_q_searches_name(self, client):
        """q 可以搜索客户 name。"""
        client.post("/customers", json={**CUSTOMER_DATA, "name": "独特姓名测试"})
        client.post("/customers", json={**CUSTOMER_DATA, "name": "普通客户", "phone": "13900000002"})

        resp = client.get("/customers/search", params={"q": "独特姓名"})
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data["items"]]
        assert "独特姓名测试" in names
        assert "普通客户" not in names

    def test_q_searches_company(self, client):
        """q 可以搜索 company。"""
        client.post("/customers", json={**CUSTOMER_DATA, "company": "独特科技有限公司"})
        client.post("/customers", json={**CUSTOMER_DATA, "company": "普通公司", "phone": "13900000003"})

        resp = client.get("/customers/search", params={"q": "独特科技"})
        assert resp.status_code == 200
        data = resp.json()
        companies = [c["company"] for c in data["items"]]
        assert "独特科技有限公司" in companies
        assert "普通公司" not in companies

    def test_q_searches_phone_or_email(self, client):
        """q 可以搜索 phone 或 email。"""
        client.post("/customers", json={**CUSTOMER_DATA, "phone": "13912345678"})
        client.post("/customers", json={**CUSTOMER_DATA, "email": "unique@test.com", "phone": "13900000004"})

        resp = client.get("/customers/search", params={"q": "13912345678"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) >= 1

        resp = client.get("/customers/search", params={"q": "unique@test"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) >= 1

    def test_followup_status_filter(self, client):
        """followup_status 筛选生效。"""
        client.post("/customers", json={**CUSTOMER_DATA, "followup_status": "已跟进", "phone": "13900000005"})
        client.post("/customers", json={**CUSTOMER_DATA, "followup_status": "待跟进", "phone": "13900000006"})

        resp = client.get("/customers/search", params={"followup_status": "已跟进"})
        assert resp.status_code == 200
        data = resp.json()
        for c in data["items"]:
            assert c["followup_status"] == "已跟进"

    def test_level_filter(self, client):
        """level 筛选生效。"""
        client.post("/customers", json={**CUSTOMER_DATA, "level": "A", "phone": "13900000007"})
        client.post("/customers", json={**CUSTOMER_DATA, "level": "B", "phone": "13900000008"})

        resp = client.get("/customers/search", params={"level": "A"})
        assert resp.status_code == 200
        data = resp.json()
        for c in data["items"]:
            assert c["level"] == "A"

    def test_intention_filter(self, client):
        """intention 筛选生效。"""
        client.post("/customers", json={**CUSTOMER_DATA, "intention": "高", "phone": "13900000009"})
        client.post("/customers", json={**CUSTOMER_DATA, "intention": "低", "phone": "13900000010"})

        resp = client.get("/customers/search", params={"intention": "高"})
        assert resp.status_code == 200
        data = resp.json()
        for c in data["items"]:
            assert c["intention"] == "高"

    def test_due_only_filter(self, client):
        """due_only=true 只返回当前用户到期且非终态客户。"""
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "到期待跟进",
            "phone": "13900000011",
            "next_followup_at": "2020-01-01T00:00:00",
            "followup_status": "待跟进",
        })
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "未来才跟进",
            "phone": "13900000012",
            "next_followup_at": "2099-01-01T00:00:00",
            "followup_status": "待跟进",
        })
        client.post("/customers", json={
            **CUSTOMER_DATA,
            "name": "到期但已成交",
            "phone": "13900000013",
            "next_followup_at": "2020-01-01T00:00:00",
            "followup_status": "成交",
        })

        resp = client.get("/customers/search", params={"due_only": "true"})
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data["items"]]
        assert "到期待跟进" in names
        assert "未来才跟进" not in names
        assert "到期但已成交" not in names

    def test_pagination_page_and_page_size(self, client):
        """分页 page/page_size 生效。"""
        for i in range(5):
            client.post("/customers", json={
                **CUSTOMER_DATA,
                "name": f"分页测试{i}",
                "phone": f"1390000002{i}",
            })

        resp = client.get("/customers/search", params={"page": "1", "page_size": "2"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) <= 2
        assert data["total"] >= 5
        assert data["pages"] >= 3

    def test_pagination_returns_correct_fields(self, client):
        """total、page、page_size、pages 返回正确。"""
        client.post("/customers", json=CUSTOMER_DATA)

        resp = client.get("/customers/search")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert data["total"] >= 1
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_search_cross_user_isolation(self, client):
        """不同用户之间搜索结果隔离。"""
        login(client)
        client.post("/customers", json={**CUSTOMER_DATA, "name": "管理员专属客户"})

        client.post("/auth/users", json={"username": "search-iso-user", "password": "search-iso-pass"})
        client.cookies.clear()
        resp = client.post("/auth/login", json={"username": "search-iso-user", "password": "search-iso-pass"})
        assert resp.status_code == 200

        resp = client.get("/customers/search", params={"q": "管理员"})
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data["items"]]
        assert "管理员专属客户" not in names

    def test_old_list_customers_still_works(self, client):
        """原 GET /customers 不受影响。"""
        client.post("/customers", json=CUSTOMER_DATA)
        resp = client.get("/customers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1


# ═══════════════════════════════════════════════════════════════
# Phase 3 Tests — 账号权限增强
# ═══════════════════════════════════════════════════════════════


class TestUserModel:
    """User 模型字段测试。"""

    def test_default_admin_has_role_admin(self, client):
        """默认 admin 用户 role 为 admin，is_active 为 true。"""
        login(client)
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"
        assert data["is_active"] is True

    def test_auth_me_returns_role_and_is_active(self, client):
        """auth/me 返回 role 和 is_active。"""
        login(client)
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert "role" in resp.json()
        assert "is_active" in resp.json()


class TestOldDatabaseUpgrade:
    """旧数据库升级测试：users 表缺少 role/is_active 时不应启动失败。"""

    def test_old_db_without_role_and_is_active_upgrades(self, tmp_path, monkeypatch):
        """旧 SQLite 数据库无 role/is_active 列时，init_database 不应报错。"""
        import sqlite3
        import sys
        import os as _os

        db_path = tmp_path / "old_v3.db"
        conn = sqlite3.connect(str(db_path))
        # Old V3 users table: no role, no is_active
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_admin BOOLEAN DEFAULT 0 NOT NULL,
                created_at DATETIME
            )
        """)
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("admin", "dummy-hash", 1),
        )
        conn.commit()
        conn.close()

        # Point to this old DB
        _os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        _os.environ["VECTOR_SEARCH_ENABLED"] = "false"

        # Reload app modules so new DB takes effect
        for mod in sorted(sys.modules):
            if mod.startswith("app."):
                del sys.modules[mod]

        from app.db_init import init_database
        init_database()

        # Verify role and is_active columns now exist and have correct values
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("PRAGMA table_info('users')")
        columns = [row[1] for row in cur.fetchall()]
        assert "role" in columns, f"role column missing after upgrade. Columns: {columns}"
        assert "is_active" in columns, f"is_active column missing after upgrade. Columns: {columns}"

        cur = conn.execute("SELECT username, role, is_active FROM users WHERE username = 'admin'")
        row = cur.fetchone()
        assert row is not None
        assert row[1] == "admin", f"Expected admin role, got {row[1]}"
        assert row[2] == 1, f"Expected is_active=1, got {row[2]}"
        conn.close()


class TestAdminCreateUser:
    """管理员创建用户测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_admin_can_create_user_with_defaults(self, client):
        """管理员创建用户，默认 role=user，is_active=true。"""
        resp = client.post("/auth/users", json={
            "username": "new-user-1", "password": "new-user-pass",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "new-user-1"
        assert data["role"] == "user"
        assert data["is_active"] is True
        assert "password_hash" not in data

    def test_admin_can_create_user_with_role(self, client):
        """管理员可指定 role。"""
        resp = client.post("/auth/users", json={
            "username": "new-admin-1", "password": "new-admin-pass", "role": "admin",
        })
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_normal_user_cannot_create_user(self, client):
        """普通用户不能创建用户，返回 403。"""
        # Admin creates a normal user first
        client.post("/auth/users", json={
            "username": "normal-guy", "password": "normal-pass",
        })
        # Login as normal user
        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "normal-guy", "password": "normal-pass",
        })
        assert resp.status_code == 200
        # Try to create another user
        resp = client.post("/auth/users", json={
            "username": "illegal-user", "password": "illegal-pass",
        })
        assert resp.status_code == 403

    def test_cannot_create_duplicate_username(self, client):
        """不能创建重名用户。"""
        client.post("/auth/users", json={
            "username": "dup-user", "password": "dup-pass",
        })
        resp = client.post("/auth/users", json={
            "username": "dup-user", "password": "another-pass",
        })
        assert resp.status_code == 409


class TestListUsers:
    """管理员查看用户列表测试。"""

    def test_admin_can_list_users(self, client):
        """管理员可以查看用户列表，响应不含 password_hash。"""
        login(client)
        resp = client.get("/auth/users")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        for u in data:
            assert "id" in u
            assert "username" in u
            assert "role" in u
            assert "is_active" in u
            assert "password_hash" not in u

    def test_normal_user_cannot_list_users(self, client):
        """普通用户不能查看用户列表，返回 403。"""
        login(client)
        client.post("/auth/users", json={
            "username": "list-denied", "password": "list-denied-pass",
        })
        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "list-denied", "password": "list-denied-pass",
        })
        assert resp.status_code == 200
        resp = client.get("/auth/users")
        assert resp.status_code == 403


class TestUserStatus:
    """管理员启用/禁用用户测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_admin_can_disable_user(self, client):
        """管理员可以禁用其他用户。"""
        resp = client.post("/auth/users", json={
            "username": "disable-me", "password": "disable-me-pass",
        })
        uid = resp.json()["id"]
        resp = client.patch(f"/auth/users/{uid}/status", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_admin_cannot_disable_self(self, client):
        """管理员不能禁用自己。"""
        me = client.get("/auth/me").json()
        # Get admin user id from user list
        users = client.get("/auth/users").json()
        admin_user = [u for u in users if u["role"] == "admin"][0]
        resp = client.patch(f"/auth/users/{admin_user['id']}/status", json={"is_active": False})
        assert resp.status_code == 400

    def test_disabled_user_cannot_login(self, client):
        """禁用用户不能登录。"""
        resp = client.post("/auth/users", json={
            "username": "disabled-login", "password": "disabled-pass",
        })
        uid = resp.json()["id"]
        client.patch(f"/auth/users/{uid}/status", json={"is_active": False})

        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "disabled-login", "password": "disabled-pass",
        })
        assert resp.status_code == 403
        assert "已被禁用" in resp.json()["detail"]

    def test_disabled_user_session_rejected(self, client):
        """禁用用户已有旧 session 访问受保护接口应被拒绝。"""
        # Create and login as a user
        resp = client.post("/auth/users", json={
            "username": "session-kill", "password": "session-kill-pass",
        })
        uid = resp.json()["id"]
        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "session-kill", "password": "session-kill-pass",
        })
        assert resp.status_code == 200
        # Save the session cookie value from set-cookie header
        set_cookie = resp.headers.get("set-cookie", "")
        # Extract session=<value> from set-cookie
        saved_session = None
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("session="):
                saved_session = part.split("=", 1)[1]
                break
        assert saved_session is not None, "No session cookie found in login response"

        # Admin disables this user
        client.cookies.clear()
        login(client)
        client.patch(f"/auth/users/{uid}/status", json={"is_active": False})

        # Restore the disabled user's OLD session cookie
        client.cookies.clear()
        client.cookies.set("session", saved_session)

        # Old session should be rejected on protected endpoint
        resp = client.get("/customers")
        assert resp.status_code == 403, f"Expected 403 for disabled user session, got {resp.status_code}"

        # Also verify re-login is rejected
        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "session-kill", "password": "session-kill-pass",
        })
        assert resp.status_code == 403

    def test_admin_can_reenable_user(self, client):
        """管理员可以重新启用用户，启用后可以登录。"""
        resp = client.post("/auth/users", json={
            "username": "reenable-me", "password": "reenable-pass",
        })
        uid = resp.json()["id"]
        client.patch(f"/auth/users/{uid}/status", json={"is_active": False})
        client.patch(f"/auth/users/{uid}/status", json={"is_active": True})

        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "reenable-me", "password": "reenable-pass",
        })
        assert resp.status_code == 200

    def test_normal_user_cannot_change_status(self, client):
        """普通用户不能修改用户状态。"""
        resp = client.post("/auth/users", json={
            "username": "status-denied", "password": "status-denied-pass",
        })
        uid = resp.json()["id"]
        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "status-denied", "password": "status-denied-pass",
        })
        assert resp.status_code == 200
        resp = client.patch(f"/auth/users/{uid}/status", json={"is_active": False})
        assert resp.status_code == 403


class TestChangePassword:
    """修改密码测试。"""

    @pytest.fixture(autouse=True)
    def _auth(self, client):
        login(client)

    def test_change_password_success(self, client):
        """当前用户修改密码成功，然后恢复原密码避免影响其他测试。"""
        resp = client.post("/auth/change-password", json={
            "old_password": "test-password",
            "new_password": "new-test-password",
        })
        assert resp.status_code == 200
        assert "成功" in resp.json()["message"]
        # Restore original password so subsequent tests can log in
        client.post("/auth/change-password", json={
            "old_password": "new-test-password",
            "new_password": "test-password",
        })

    def test_old_password_cannot_login_after_change(self, client):
        """修改密码后旧密码不能登录，新密码可以登录。"""
        # Create a fresh user
        client.post("/auth/users", json={
            "username": "pw-test-user", "password": "pw-old-pass",
        })
        client.cookies.clear()
        client.post("/auth/login", json={
            "username": "pw-test-user", "password": "pw-old-pass",
        })
        # Change password
        client.post("/auth/change-password", json={
            "old_password": "pw-old-pass",
            "new_password": "pw-new-pass",
        })
        client.cookies.clear()
        # Old password should fail
        resp = client.post("/auth/login", json={
            "username": "pw-test-user", "password": "pw-old-pass",
        })
        assert resp.status_code == 401
        # New password should succeed
        resp = client.post("/auth/login", json={
            "username": "pw-test-user", "password": "pw-new-pass",
        })
        assert resp.status_code == 200

    def test_change_password_wrong_old_fails(self, client):
        """修改密码时 old_password 错误会失败。"""
        resp = client.post("/auth/change-password", json={
            "old_password": "wrong-password",
            "new_password": "irrelevant",
        })
        assert resp.status_code == 400
        assert "错误" in resp.json()["detail"]

    def test_change_password_short_new_fails(self, client):
        """新密码太短会失败。"""
        resp = client.post("/auth/change-password", json={
            "old_password": "test-password",
            "new_password": "ab",
        })
        assert resp.status_code == 400

    def test_disabled_user_cannot_change_password(self, client):
        """禁用用户不能修改密码。"""
        resp = client.post("/auth/users", json={
            "username": "cp-disabled", "password": "cp-disabled-pass",
        })
        uid = resp.json()["id"]
        client.patch(f"/auth/users/{uid}/status", json={"is_active": False})
        client.cookies.clear()
        # Try to login (should fail)
        resp = client.post("/auth/login", json={
            "username": "cp-disabled", "password": "cp-disabled-pass",
        })
        assert resp.status_code == 403
