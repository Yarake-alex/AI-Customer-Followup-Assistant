import os
import pytest

# 设置不依赖路径的测试环境变量，在导入 app.main 前生效
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["MAX_UPLOAD_SIZE_MB"] = "1"
os.environ["LLM_PROVIDER"] = "mock"

# DATABASE_URL 和 app.main 导入放在 client fixture 中，
# 以便使用 tmp_path_factory 创建临时数据库


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    """创建测试客户端，使用临时 SQLite 数据库，不污染项目目录。"""
    tmp_dir = tmp_path_factory.mktemp("data")
    db_path = tmp_dir / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)
