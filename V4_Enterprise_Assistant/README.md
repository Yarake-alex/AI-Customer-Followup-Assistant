# AI 客户跟进助手 V4 企业增强版

AI 客户跟进助手 V4 是一个面向 ToB 销售客户管理场景的 AI 应用系统，集成客户管理、跟进记录、AI 跟进分析、RAG 知识库问答和 Agent 自动跟进方案。系统可以帮助销售人员维护客户资料、记录跟进过程、基于大模型生成客户总结与下一步建议，并结合产品资料知识库生成更有针对性的销售话术和跟进方案。

相比 V1/V2/V3，V4 不仅保留了客户管理、RAG 和 Agent 能力，还进一步加入了安全加固、数据库工程化、索引优化、上传限制、环境变量配置、pytest 自动化测试和 Docker 部署支持，更适合作为 AI 应用工程师方向的综合展示项目。

## 核心功能

- **客户管理**：支持客户新增、列表查看、详情查看、修改和删除。
- **跟进记录**：支持为客户维护历史跟进记录和下一步动作。
- **AI 跟进分析**：基于客户资料和跟进记录生成客户总结与下一步销售建议。
- **RAG 知识库问答**：支持上传 PDF、TXT、MD、CSV 资料，基于 TF-IDF 检索相关片段后调用大模型回答问题。
- **Agent 跟进助手**：自动组合客户资料、历史跟进记录和知识库内容，生成完整客户跟进方案。
- **安全加固**：支持 CORS 白名单、访问密码登录页 + HttpOnly Cookie 登录态、上传文件大小限制。
- **测试体系**：使用 pytest + FastAPI TestClient 覆盖核心接口、鉴权逻辑和上传限制。
- **Docker 部署**：支持通过 Dockerfile 和 docker-compose.yml 在云服务器上部署运行。

## 技术栈

- **后端框架**：FastAPI
- **ORM**：SQLAlchemy
- **数据库**：SQLite（本地开发）/ PostgreSQL（生产部署推荐）
- **配置管理**：pydantic-settings / `.env`
- **数据校验**：Pydantic
- **文档解析**：pypdf
- **文本检索**：scikit-learn TF-IDF
- **LLM 接口**：OpenAI-compatible API（支持 DeepSeek / 通义 / 智谱等兼容接口）
- **前端**：HTML、CSS、JavaScript
- **测试**：pytest、FastAPI TestClient
- **部署**：Docker、docker-compose

## 目录结构

```text
app/
├── main.py          # FastAPI 接口入口
├── config.py        # 环境变量配置
├── models.py        # SQLAlchemy 数据库模型
├── schemas.py       # Pydantic 请求/响应模型
├── database.py      # 数据库引擎与会话
├── db_init.py       # 数据库建表、字段升级、索引补建
├── llm.py           # LLM 调用封装
├── rag.py           # 文档解析、文本分块、TF-IDF 检索
└── agent.py         # Agent 自动跟进方案

static/
└── index.html       # 前端单页应用

tests/
├── conftest.py      # pytest 测试配置与临时数据库
└── test_api.py      # 核心接口测试

Dockerfile           # Docker 镜像构建文件
docker-compose.yml   # Docker Compose 启动配置
requirements.txt     # Python 依赖
.env.example         # 环境变量示例
.gitignore           # Git 忽略规则
README.md            # 项目说明
```

## 本地启动

```bash
python -m venv .venv
```

Windows：

```bash
.venv\Scripts\activate
```

Linux / macOS：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

复制环境变量文件：

```bash
copy .env.example .env
```

Linux / macOS：

```bash
cp .env.example .env
```

启动项目：

```bash
python -m uvicorn app.main:app --reload
```

启动后访问：

```text
http://127.0.0.1:8000
```

API 文档地址：

```text
http://127.0.0.1:8000/docs
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | 数据库连接地址，可用于本地、测试或部署环境，支持 SQLite / PostgreSQL | `sqlite:///./customer_assistant.db` |
| `MAX_UPLOAD_SIZE_MB` | 上传文件大小限制，单位 MB | `10` |
| `APP_ADMIN_USERNAME` | 首次启动自动创建的管理员用户名 | `admin` |
| `APP_ACCESS_PASSWORD` | 首次启动自动创建管理员账号时使用的登录密码，设置后所有业务接口需登录 | 空（本地开发免登录） |
| `ENABLE_PUBLIC_REGISTRATION` | 是否开放公开注册，生产环境建议保持 `false` | `false` |
| `SESSION_SECRET` | Cookie 签名密钥，`APP_ACCESS_PASSWORD` 设置时必填且 >= 32 字符 | 空 |
| `PUBLIC_SITE_URL` | 正式访问地址，建议填写 HTTPS 域名 | 空 |
| `APP_ENV` | 运行环境：`development` / `production` / `test` | `development` |
| `COOKIE_SECURE` | Cookie Secure 标志，HTTPS 部署设为 `true` | `false` |
| `LLM_PROVIDER` | `mock` 不调用真实模型；`openai_compatible` 使用真实 API | `mock` |
| `OPENAI_API_KEY` | LLM API Key | 空 |
| `OPENAI_BASE_URL` | LLM API 地址，例如 `https://api.deepseek.com` | 空 |
| `OPENAI_MODEL` | 模型名称，例如 `deepseek-chat` | `deepseek-chat` |
| `CORS_ORIGINS` | 允许跨域访问的前端地址，多个地址用英文逗号分隔 | 本地开发地址 |

本地开发推荐：

```env
LLM_PROVIDER=mock
APP_ACCESS_PASSWORD=
APP_ADMIN_USERNAME=admin
ENABLE_PUBLIC_REGISTRATION=false
SESSION_SECRET=
APP_ENV=development
COOKIE_SECURE=false
MAX_UPLOAD_SIZE_MB=10
DATABASE_URL=sqlite:///./customer_assistant.db
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:8000
```

使用 DeepSeek 示例：

```env
LLM_PROVIDER=openai_compatible
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat
```

生产环境建议设置：

```env
APP_ADMIN_USERNAME=admin
APP_ACCESS_PASSWORD=your-admin-password
ENABLE_PUBLIC_REGISTRATION=false
SESSION_SECRET=<上一步生成的值>
APP_ENV=production
COOKIE_SECURE=true
MAX_UPLOAD_SIZE_MB=10
PUBLIC_SITE_URL=https://your-domain.com
DATABASE_URL=postgresql+psycopg://ai_customer:strong-password@postgres:5432/ai_customer
CORS_ORIGINS=https://your-domain.com
```

生成强随机 SESSION_SECRET：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

注意：
- HTTP IP 部署时 `COOKIE_SECURE=false`，HTTPS 域名部署时必须设为 `true`。
- `APP_ACCESS_PASSWORD` 设置后，系统首次启动会创建 `APP_ADMIN_USERNAME` 管理员账号。管理员可通过 `/auth/users` 创建普通用户。
- Cookie 使用 HMAC-SHA256 签名，HttpOnly 防 XSS 窃取。

## 数据库说明

- 默认使用 SQLite 数据库，适合本地开发和演示。
- 生产环境推荐使用 PostgreSQL，项目已支持 `postgresql+psycopg://...` 连接地址。
- 默认数据库文件为 `customer_assistant.db`。
- 支持通过 `DATABASE_URL` 修改数据库路径。
- Docker 单机演示可使用：`sqlite:///./data/customer_assistant.db`。
- Docker PostgreSQL 部署可使用 `docker-compose.postgres.yml`。
- 详细 PostgreSQL 生产部署指南请参阅 [POSTGRES_DEPLOYMENT.md](POSTGRES_DEPLOYMENT.md)。
- 启动时会自动建表、补字段、补索引。
- 数据库文件不应提交到 GitHub。

不应上传的数据库文件包括：

```text
*.db
*.db-wal
*.db-shm
*.sqlite
*.sqlite3
```

## Docker 部署

项目支持 Docker 部署，适合部署到云服务器。

### 1. 准备 `.env`

```bash
cp .env.example .env
```

编辑 `.env`：

```env
LLM_PROVIDER=openai_compatible
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat

APP_ADMIN_USERNAME=admin
APP_ACCESS_PASSWORD=your-admin-password
ENABLE_PUBLIC_REGISTRATION=false
SESSION_SECRET=your-random-session-secret-at-least-32-chars
APP_ENV=production
COOKIE_SECURE=true
MAX_UPLOAD_SIZE_MB=10

PUBLIC_SITE_URL=https://your-domain.com
DATABASE_URL=postgresql+psycopg://ai_customer:strong-password@postgres:5432/ai_customer
CORS_ORIGINS=https://your-domain.com
```

### 2. 创建数据目录

```bash
mkdir -p data
```

### 3. 启动容器

```bash
docker compose up -d --build
```

如需使用 PostgreSQL 版本：

```bash
docker compose -f docker-compose.postgres.yml up -d --build
```

详细部署说明请参阅 [POSTGRES_DEPLOYMENT.md](POSTGRES_DEPLOYMENT.md)。

### 4. 查看运行状态

```bash
docker ps
```

查看日志：

```bash
docker logs -f ai-customer-v4
```

访问项目：

```text
http://your-server-ip:8000
```

访问接口文档：

```text
http://your-server-ip:8000/docs
```

停止容器：

```bash
docker compose down
```

## 部署前检查 / 本地运行 / 服务器部署

### 本地启动命令

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

访问地址：`http://127.0.0.1:8000`，健康检查：`http://127.0.0.1:8000/health`

### 本地测试命令

```bash
python -m pytest tests/ -v
```

测试使用临时 SQLite 数据库，不污染正式数据。LLM 使用 mock 模式，避免调用外部 API。

### 服务器 .env 必填项

部署到服务器时，`.env` 至少需要配置以下变量：

```env
# ── 必填项 ──
APP_ACCESS_PASSWORD=your-strong-password
SESSION_SECRET=<python -c "import secrets; print(secrets.token_hex(32))" 生成的值>
APP_ENV=production
COOKIE_SECURE=false          # 如果暂时还是 HTTP；HTTPS 部署时必须设为 true
DATABASE_URL=sqlite:///./data/customer_assistant.db   # Docker 单机部署；生产推荐 PostgreSQL

# ── 安全相关 ──
APP_ADMIN_USERNAME=admin
ENABLE_PUBLIC_REGISTRATION=false
MAX_UPLOAD_SIZE_MB=10
```

注意：
- `APP_ACCESS_PASSWORD` 和 `SESSION_SECRET` 是必须设置的，否则系统无法启动。
- `SESSION_SECRET` 长度不少于 32 字符。
- HTTP IP 访问时 `COOKIE_SECURE=false`，HTTPS 域名部署后改为 `true`。

### Embedding / 向量检索配置

如果没有 Embedding API，生产环境先保持向量检索关闭：

```env
VECTOR_SEARCH_ENABLED=false
```

等拿到 Embedding API 后再开启：

```env
VECTOR_SEARCH_ENABLED=true
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_KEY=your-embedding-api-key
EMBEDDING_BASE_URL=https://your-embedding-api-endpoint
EMBEDDING_MODEL_NAME=text-embedding-v3
EMBEDDING_DIMENSION=0          # 0 = 自动检测模型输出维度，或根据模型填写具体值
```

常见 Embedding API 兼容示例：
- **阿里云百炼 (Qwen)**：`EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`，`EMBEDDING_MODEL_NAME=text-embedding-v3`
- **智谱 (Zhipu)**：`EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4`，`EMBEDDING_MODEL_NAME=embedding-3`
- **与 LLM 同源**：如果 Embedding 和 LLM 使用同一个 API 地址和 Key，可以留空 `EMBEDDING_API_KEY` 和 `EMBEDDING_BASE_URL`，系统会自动沿用 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。

Docker 部署时，向量检索同样需要在 `.env` 中配置上述变量，`docker-compose.yml` 会自动加载。

### Docker 部署步骤

```bash
# 1. 准备环境变量
cp .env.example .env
# 编辑 .env，填写必填项（见上方"服务器 .env 必填项"）

# 2. 创建数据目录
mkdir -p data

# 3. 构建并启动
docker compose up -d --build

# 4. 检查健康状态
curl http://127.0.0.1:8000/health
# 或浏览器访问 http://your-server-ip:8000

# 5. 查看日志
docker logs -f ai-customer-v4

# 6. 停止
docker compose down
```

## 接口说明

| 端点 | 方法 | 说明 | 需登录 |
|---|---|---|---|
| `/` | GET | 前端页面 | 否 |
| `/health` | GET | 健康检查 | 否 |
| `/auth/login` | POST | 登录（获取 Cookie） | 否 |
| `/auth/users` | POST | 管理员创建普通用户 | 是 |
| `/auth/register` | POST | 公开注册（默认关闭） | 否 |
| `/auth/logout` | POST | 退出登录 | 否 |
| `/auth/me` | GET | 当前登录状态 | 否 |
| `/customers` | GET | 客户列表 | 是 |
| `/customers` | POST | 新增客户 | 是 |
| `/customers/{id}` | GET | 客户详情 | 是 |
| `/customers/{id}` | PUT | 修改客户 | 是 |
| `/customers/{id}` | DELETE | 删除客户 | 是 |
| `/customers/{id}/followups` | POST | 新增跟进记录 | 是 |
| `/customers/{id}/followups` | GET | 跟进记录列表 | 是 |
| `/customers/{id}/ai/summary` | POST | AI 跟进总结 | 是 |
| `/customers/{id}/ai/suggestion` | POST | AI 下一步建议 | 是 |
| `/rag/upload` | POST | 上传知识库文档 | 是 |
| `/rag/documents` | GET | 知识库文档列表 | 是 |
| `/rag/documents/{filename}` | DELETE | 删除指定文档 | 是 |
| `/rag/documents` | DELETE | 清空知识库 | 是 |
| `/rag/ask` | POST | 基于知识库问答 | 是 |
| `/agent/analyze` | POST | Agent 自动跟进分析 | 是 |

登录方式：打开页面后输入访问密码，登录成功后通过 HttpOnly Cookie 自动携带登录态。

## 安全加固

V4 版本加入了基础安全加固能力：

- 生产环境建议设置 `APP_ADMIN_USERNAME`、`APP_ACCESS_PASSWORD` 和 `SESSION_SECRET`；
- 首次启动自动创建管理员账号，管理员可创建普通用户；
- 客户、跟进记录和知识库资料按用户隔离；
- 所有业务接口需要先通过登录页认证，基于 HMAC-SHA256 签名 Cookie；
- Cookie 使用 HttpOnly 标志，防止 XSS 窃取；
- Cookie Secure 标志可通过 `COOKIE_SECURE` 配置；
- CORS 通过 `CORS_ORIGINS` 配置白名单；
- 上传文件通过 `MAX_UPLOAD_SIZE_MB` 限制大小；
- `.env` 和数据库文件禁止提交到 GitHub；
- 生产环境不建议使用 `--reload` 启动。

示例：

```env
APP_ADMIN_USERNAME=admin
APP_ACCESS_PASSWORD=your-admin-password
ENABLE_PUBLIC_REGISTRATION=false
SESSION_SECRET=<随机 32 字符以上密钥>
COOKIE_SECURE=true
PUBLIC_SITE_URL=https://your-domain.com
CORS_ORIGINS=https://your-domain.com
MAX_UPLOAD_SIZE_MB=10
```

## 测试说明

运行测试：

```bash
python -m pytest
```

测试覆盖内容：

- 客户新增；
- 客户列表查询；
- 跟进记录新增；
- 未登录请求业务接口返回 401；
- 错误密码登录返回 401；
- 正确密码登录成功并返回 HttpOnly Cookie；
- Cookie 不包含明文密码；
- GET /auth/me 返回登录状态；
- 退出登录后再次请求返回 401；
- 首页 / 和静态资源不需要登录；
- 上传超大文件返回 413；
- 上传小 TXT 文件成功；
- RAG 问答、Agent 分析等接口受登录保护。

测试说明：

- 测试使用临时 SQLite 数据库；
- 不污染正式 `customer_assistant.db`；
- LLM 使用 mock 模式，避免真实调用外部 API。

## V1 / V2 / V3 / V4 区别

| 版本 | 能力 | 说明 |
|---|---|---|
| V1 | 客户管理 + AI 跟进建议 | 实现客户信息维护、跟进记录和基础 AI 建议 |
| V2 | RAG 知识库问答 | 增加资料上传、文本切分、知识库检索和资料问答 |
| V3 | Agent 跟进助手 | 自动组合客户信息、跟进记录和知识库资料生成跟进方案 |
| V4 | 企业增强版 | 增加安全加固、数据库工程化、索引优化、测试体系和 Docker 部署 |

## 后续规划

- 引入 Alembic 管理正式数据库迁移；
- 增加 GitHub Actions 自动测试；
- 增加 JWT 登录和多用户权限系统；
- 将 TF-IDF 检索升级为 Embedding + 向量数据库；
- 增加跟进任务表、客户优先级评分和销售日报；
- 接入飞书、企业微信等消息通知渠道；
- 支持 Nginx 反向代理和域名部署。

## 项目说明

本项目为 AI 客户跟进助手系列的 V4 企业增强版，重点展示从基础 AI 功能到工程化 AI 应用的升级过程。项目不仅包含客户管理、AI 分析、RAG 和 Agent 能力，也补充了安全、测试、配置、数据库和 Docker 部署等工程实践内容，适合作为 AI 应用工程师方向的综合项目展示。
