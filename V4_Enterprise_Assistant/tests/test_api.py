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


@pytest.fixture(scope="module")
def customer_id(client):
    """创建一个测试客户，供需要真实客户 ID 的测试使用。"""
    resp = client.post("/customers", json=CUSTOMER_DATA)
    assert resp.status_code == 200
    return resp.json()["id"]


class TestCustomers:
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


class TestAuth:
    """受保护接口鉴权测试。"""

    @pytest.mark.parametrize("url", [
        "/customers/99999",
        "/rag/documents",
        "/rag/documents/test.md",
    ])
    def test_protected_no_key(self, client, url):
        resp = client.delete(url)
        assert resp.status_code == 403

    def test_protected_wrong_key(self, client):
        resp = client.delete("/customers/99999", headers={"X-Admin-Key": "wrong-key"})
        assert resp.status_code == 403

    def test_protected_correct_key(self, client):
        """正确密钥应该通过鉴权（客户不存在则返回 404，而非 403）。"""
        resp = client.delete("/customers/99999", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 404


class TestUpload:
    def test_upload_too_large(self, client):
        """超过 MAX_UPLOAD_SIZE_MB=1 的文件应返回 413。"""
        content = b"x" * (1024 * 1024 + 1)
        resp = client.post(
            "/rag/upload",
            files={"file": ("big.txt", content, "text/plain")},
            headers={"X-Admin-Key": "test-admin-key"},
        )
        assert resp.status_code == 413
        assert "文件过大" in resp.text

    def test_upload_small_file(self, client):
        """小于限制的文本文件应上传成功并返回片段数。"""
        content = b"hello world, this is a test document for RAG knowledge base."
        resp = client.post(
            "/rag/upload",
            files={"file": ("test.txt", content, "text/plain")},
            headers={"X-Admin-Key": "test-admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks"] > 0
        assert data["filename"] == "test.txt"


class TestRagAsk:
    def test_rag_ask_no_key(self, client):
        """/rag/ask 没有 X-Admin-Key 应返回 403。"""
        resp = client.post("/rag/ask", json={"question": "test"})
        assert resp.status_code == 403


class TestAgent:
    def test_agent_analyze_no_key(self, client):
        """/agent/analyze 没有 X-Admin-Key 应返回 403。"""
        resp = client.post(
            "/agent/analyze",
            json={"customer_id": 1, "task": "test"},
        )
        assert resp.status_code == 403
