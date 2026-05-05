# AI 客户跟进助手 V3

客户管理 + AI 跟进分析 + RAG 知识库问答 + Agent 自动跟进方案。

## 技术栈

- **框架**: FastAPI
- **ORM**: SQLAlchemy
- **数据库**: SQLite（本地文件 `customer_assistant.db`）
- **文档解析**: pypdf
- **文本检索**: scikit-learn TF-IDF
- **LLM**: OpenAI-compatible 接口（支持 DeepSeek / 通义 / 智谱 等）

## 目录结构

```
app/
├── main.py          # FastAPI 接口入口
├── config.py        # 环境变量配置
├── models.py        # SQLAlchemy 数据库模型
├── schemas.py       # Pydantic 请求/响应模型
├── database.py      # 数据库引擎与会话
├── db_init.py       # 数据库建表、字段升级、索引补建
├── llm.py           # LLM 调用封装
├── rag.py           # 文档解析、文本分块、向量检索
└── agent.py         # Agent 自动跟进方案
static/
└── index.html       # 前端单页应用
```

## 本地启动

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env    # Windows
# cp .env.example .env    # Linux / macOS

uvicorn app.main:app --reload
```

启动后访问 http://127.0.0.1:8000。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MAX_UPLOAD_SIZE_MB` | 上传文件大小限制（MB） | 10 |
| `ADMIN_API_KEY` | 管理接口密钥，生产环境必须设置强随机值 | 空（不鉴权） |
| `LLM_PROVIDER` | `mock` 不调用真实模型；`openai_compatible` 使用 API | mock |
| `OPENAI_API_KEY` | LLM API Key | — |
| `OPENAI_BASE_URL` | LLM API 地址，例如 `https://api.deepseek.com` | — |
| `OPENAI_MODEL` | 模型名，例如 `deepseek-chat` | deepseek-chat |
| `CORS_ORIGINS` | 允许的前端跨域地址，逗号分隔 | 本地多个开发地址 |

**mock 模式**: `LLM_PROVIDER=mock` 时不需要任何 API Key，系统使用预设回复，适合本地开发和前端调试。

## 数据库说明

- 默认使用项目根目录的 `customer_assistant.db`
- 启动时自动建表、补字段、补索引，无需手动执行 SQL
- `.env` 中暂不支持修改数据库路径
- `*.db`、`*.db-wal`、`*.db-shm` 不应提交到版本控制

## 接口说明

| 端点 | 方法 | 说明 | 需管理密钥 |
|---|---|---|---|
| `/customers` | GET | 客户列表 | 否 |
| `/customers` | POST | 新增客户 | 否 |
| `/customers/{id}` | GET | 客户详情 | 否 |
| `/customers/{id}` | PUT | 修改客户 | 否 |
| `/customers/{id}` | DELETE | 删除客户 | 是 |
| `/customers/{id}/followups` | POST | 新增跟进记录 | 否 |
| `/customers/{id}/followups` | GET | 跟进记录列表 | 否 |
| `/customers/{id}/ai/summary` | POST | AI 跟进总结 | 是 |
| `/customers/{id}/ai/suggestion` | POST | AI 下一步建议 | 是 |
| `/rag/upload` | POST | 上传知识库文档 | 是 |
| `/rag/documents` | GET | 知识库文档列表 | 否 |
| `/rag/documents/{filename}` | DELETE | 删除指定文档 | 是 |
| `/rag/documents` | DELETE | 清空知识库 | 是 |
| `/rag/ask` | POST | 基于知识库问答 | 是 |
| `/agent/analyze` | POST | Agent 自动跟进分析 | 是 |

需要管理密钥的接口，请求头需携带 `X-Admin-Key`。

## 安全加固

```bash
# 生产环境必须设置强随机密钥
ADMIN_API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# CORS 只允许可信域名
CORS_ORIGINS=https://your-frontend.example.com

# 根据业务需求调整上传大小限制
MAX_UPLOAD_SIZE_MB=20
```

- `.env` 文件包含敏感信息，禁止提交到版本控制
- 数据库文件包含业务数据，禁止提交到版本控制
- 生产环境不应使用 `--reload`

## 后续规划

- Alembic 数据库迁移
- 更完整的单元测试与集成测试
- RAG 检索优化（Embedding + 向量数据库）
- 登录与权限系统
- 文件存储与审计日志
