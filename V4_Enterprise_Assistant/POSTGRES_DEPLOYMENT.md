# PostgreSQL 生产部署指南

## 本地 SQLite 与生产 PostgreSQL 的区别

| | SQLite（本地开发） | PostgreSQL（生产部署） |
|---|---|---|
| 使用场景 | 本地开发、演示 | 云服务器生产环境 |
| 默认配置 | 开箱即用，无需额外配置 | 需设置 `DATABASE_URL` 和相关环境变量 |
| 向量检索 | ChromaDB（嵌入模式） | pgvector（需 PostgreSQL 镜像内置扩展） |
| 并发支持 | 有限（单写者） | 完善的并发读写支持 |
| 连接驱动 | 内置 sqlite3 | 需安装 psycopg（`requirements-db-pg.txt`） |
| 数据持久化 | 本地 `.db` 文件 | Docker volume 或云数据库服务 |

## 推荐环境变量

生产环境 `.env` 最小配置：

```env
# ── 数据库 ──
DATABASE_URL=postgresql+psycopg://ai_customer:your-strong-password@postgres:5432/ai_customer

# ── 认证（必填）──
APP_ADMIN_USERNAME=admin
APP_ACCESS_PASSWORD=your-strong-admin-password
SESSION_SECRET=<python -c "import secrets; print(secrets.token_hex(32))" 生成的值>

# ── 安全 ──
ENABLE_PUBLIC_REGISTRATION=false
COOKIE_SECURE=true          # HTTPS 部署时必须为 true；HTTP IP 访问时设为 false
APP_ENV=production

# ── 向量检索（默认关闭）──
VECTOR_SEARCH_ENABLED=false
```

说明：
- `DATABASE_URL` 支持以下格式（均自动规范化为 `postgresql+psycopg://`）：
  - 推荐：`postgresql+psycopg://user:password@host:5432/dbname`
  - 兼容：`postgresql://user:password@host:5432/dbname`（自动添加 `+psycopg` 驱动）
  - 兼容：`postgres://user:password@host:5432/dbname`（自动改写为 `postgresql+psycopg://`）
- 项目统一使用 psycopg v3 作为 PostgreSQL 驱动（`requirements-db-pg.txt`）。
- `DATABASE_URL` 中的主机名应使用 Docker 服务名（如 `postgres`），不要写 `localhost`。
- 向量检索默认关闭（`VECTOR_SEARCH_ENABLED=false`），无需配置 Embedding API。
- 不要将 `.env` 提交到 Git。

## Docker Compose PostgreSQL 部署

### 1. 准备 .env 文件

```bash
cp .env.example .env
# 编辑 .env，按上一节填写必填项
```

### 2. 启动服务

```bash
docker compose -f docker-compose.postgres.yml up -d --build
```

此命令会启动两个容器：
- `ai-customer-v4-postgres`：PostgreSQL 16 + pgvector 扩展
- `ai-customer-v4`：FastAPI 应用

应用容器会等待 PostgreSQL 健康检查通过后再启动。

### 3. 验证

```bash
# 健康检查
curl http://your-server-ip:8000/health

# 查看日志
docker logs -f ai-customer-v4
```

### 4. 停止

```bash
docker compose -f docker-compose.postgres.yml down
```

### 5. PostgreSQL 镜像说明

`docker-compose.postgres.yml` 使用 `pgvector/pgvector:0.8.0-pg16` 镜像，该镜像内置了 pgvector 扩展。即使不启用向量检索，也可以正常使用该镜像——pgvector 扩展只在 `VECTOR_SEARCH_ENABLED=true` 时才会被激活。

如果不想使用 pgvector 镜像（纯 PostgreSQL），可以将 image 改为 `postgres:16`，但后续如需向量检索则需要手动安装 pgvector 扩展。

## 首次启动自动初始化

应用首次启动时会自动执行以下操作（无需手动运行 SQL）：

1. **create_tables**：根据 SQLAlchemy 模型创建所有表。
2. **upgrade_database**：兼容旧版本数据库，自动补齐缺失的列（如 `users.role`、`users.is_active`、`customers.last_followup_at` 等）。PostgreSQL 下使用 `TIMESTAMP` 类型，SQLite 下使用 `DATETIME` 类型。
3. **create_indexes**：幂等补建索引，使用 `CREATE INDEX IF NOT EXISTS`。
4. **_migrate_pgvector**：仅在 `VECTOR_SEARCH_ENABLED=true` 且数据库为 PostgreSQL 时，创建 pgvector 扩展和 embedding 列。
5. **ensure_default_user**：确保 `APP_ADMIN_USERNAME` 管理员账号存在。

旧数据库升级顺序已保证：`users.role` 和 `users.is_active` 列会先于 `ensure_default_user()` 补齐，避免启动失败。

## 1Panel / OpenResty / 阿里云部署注意事项

### 1Panel

- 在 1Panel 中创建容器时，使用 `docker-compose.postgres.yml` 的内容。
- 如果 1Panel 已提供 PostgreSQL 数据库，将 `DATABASE_URL` 中的主机名改为 1Panel 提供的数据库地址，并移除 compose 中的 postgres 服务。
- 确保应用容器能访问 PostgreSQL 端口（默认 5432）。

### OpenResty / Nginx 反向代理

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

反向代理时：
- 设置 `COOKIE_SECURE=true`（HTTPS）。
- 设置 `PUBLIC_SITE_URL=https://your-domain.com`。
- 设置 `CORS_ORIGINS=https://your-domain.com`。

### 阿里云

- 安全组开放 8000 端口（或反向代理端口）。
- 如需使用阿里云 RDS PostgreSQL，将 `DATABASE_URL` 改为 RDS 连接地址，并移除 compose 中的 postgres 服务。
- 建议使用 ESSD 云盘提升数据库 IO 性能。

## 数据库备份

### pg_dump 备份

```bash
# 从 Docker 容器内导出
docker exec ai-customer-v4-postgres pg_dump -U ai_customer ai_customer > backup_$(date +%Y%m%d).sql

# 恢复
docker exec -i ai-customer-v4-postgres psql -U ai_customer ai_customer < backup_20260708.sql
```

### Docker Volume 备份

```bash
# 备份 volume
docker run --rm -v ai-customer-followup-assistant-upload-v4_dev_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_backup.tar.gz -C /data .

# 恢复（需先停止容器）
docker compose -f docker-compose.postgres.yml down
docker run --rm -v ai-customer-followup-assistant-upload-v4_dev_postgres_data:/data -v $(pwd):/backup alpine tar xzf /backup/postgres_backup.tar.gz -C /data
docker compose -f docker-compose.postgres.yml up -d
```

### 定期备份建议

- 使用 cron 每天执行一次 `pg_dump`。
- 备份文件存储到独立于服务器的位置（如对象存储、NAS）。
- 保留最近 7-14 天的备份。

## 回滚注意事项

- 从 SQLite 切换到 PostgreSQL 后，数据不互通。如需回滚到 SQLite，数据不会自动同步。
- 回滚前务必先备份 PostgreSQL 数据。
- Docker Compose 回滚：停止容器 → 恢复旧 volume 备份 → 重新启动。
- 如果是首次部署后发现问题，可以 `docker compose down -v` 清除数据卷重新开始（会丢失所有数据）。

## pgvector / 向量检索说明

- **默认不启用**：`VECTOR_SEARCH_ENABLED=false`，不会使用 pgvector 扩展，不需要配置 Embedding API。
- **普通 PostgreSQL 部署**：可以不启用向量检索，项目使用 TF-IDF 作为知识库检索方式，功能完整可用。
- **pgvector 镜像**：`docker-compose.postgres.yml` 使用的 `pgvector/pgvector:0.8.0-pg16` 镜像已内置 pgvector 扩展，但扩展只在 `VECTOR_SEARCH_ENABLED=true` 时才会被激活（`CREATE EXTENSION IF NOT EXISTS vector`）。
- **使用纯 PostgreSQL 镜像**：可以将 image 改为 `postgres:16`，不影响正常功能（仅无法使用 pgvector 向量检索）。

后续如需启用向量检索：

```env
VECTOR_SEARCH_ENABLED=true
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_KEY=your-embedding-api-key
EMBEDDING_BASE_URL=https://your-embedding-api-endpoint
EMBEDDING_MODEL_NAME=text-embedding-v3
EMBEDDING_DIMENSION=0          # 0 = 自动检测
```

常见 Embedding API：
- 阿里云百炼：`EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- 智谱：`EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4`
- 与 LLM 同源：留空 `EMBEDDING_API_KEY` 和 `EMBEDDING_BASE_URL`，自动沿用 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。

## 常见问题

**Q: 启动后无法连接数据库？**
A: 检查 `DATABASE_URL` 格式是否正确，确认 PostgreSQL 容器已健康启动（`docker ps` 查看状态）。推荐格式为 `postgresql+psycopg://user:password@host:5432/dbname`。如果使用了 `postgres://` 或 `postgresql://` 格式，项目会自动规范化为 `postgresql+psycopg://`。

**Q: 旧 SQLite 数据能迁移到 PostgreSQL 吗？**
A: 目前不支持自动数据迁移。如需迁移，建议导出 CSV 后在新系统中导入。

**Q: 能否同时使用 SQLite 的 docker-compose.yml？**
A: 可以。默认 `docker-compose.yml` 使用 SQLite，数据存储在 `./data` 目录。`docker-compose.postgres.yml` 使用 PostgreSQL。两者互不影响。

**Q: 不用 Docker 怎么连 PostgreSQL？**
A: 直接在 `.env` 中设置 `DATABASE_URL` 指向你的 PostgreSQL 实例（推荐格式 `postgresql+psycopg://`），然后 `pip install -r requirements-db-pg.txt`，正常启动应用即可。
