# 备份与恢复指南

## 概述

AI 客户跟进助手 V4 支持两种数据库模式：SQLite（本地开发/Docker 单容器）和 PostgreSQL（生产部署）。

本指南覆盖两种模式的备份与恢复操作。

## 备份文件安全提醒

- 备份文件包含客户数据、跟进记录、知识库资料等敏感信息。
- 备份文件不要提交到 Git（项目 `.gitignore` 已排除 `*.db`、`*.sql`、`*.dump`）。
- 建议将备份存储到独立于服务器的位置（如 NAS、对象存储、加密 U 盘）。
- **不要批量删除旧备份文件**。清理旧备份应由管理员逐文件确认后手动操作。

---

## SQLite 备份

### 数据存储位置

| 运行方式 | 数据库路径 | 备注 |
|---|---|---|
| 本地开发 | `./customer_assistant.db` | 项目根目录 |
| Docker (默认 compose) | `./data/customer_assistant.db` | 挂载到容器内 `/app/data` |

### 备份方法

#### 本地开发

1. 先停止应用（可选，但建议停止以避免备份过程中数据写入）：
   ```
   Ctrl+C 停止 uvicorn
   ```

2. 复制数据库文件：
   ```powershell
   Copy-Item .\customer_assistant.db ".\backup_sqlite_$(Get-Date -Format yyyyMMdd_HHmmss).db"
   ```

#### Docker SQLite 模式

1. 找到数据目录（默认为项目根目录下的 `data/` 文件夹）。

2. 停止容器（可选但建议）：
   ```bash
   docker compose down
   ```

3. 复制数据库文件：
   ```powershell
   Copy-Item .\data\customer_assistant.db "D:\backups\backup_sqlite_$(Get-Date -Format yyyyMMdd_HHmmss).db"
   ```

4. 重新启动：
   ```bash
   docker compose up -d
   ```

#### 使用备份脚本

项目提供了 PowerShell 备份脚本 `scripts/backup_sqlite.ps1`：

```powershell
.\scripts\backup_sqlite.ps1 -DbPath ".\data\customer_assistant.db" -BackupDir "D:\backups"
```

脚本会自动在文件名中加入时间戳，不会覆盖已有备份，不会删除任何文件。

### SQLite 恢复

```powershell
# 1. 停止应用或容器
docker compose down

# 2. 将备份文件复制回数据目录
Copy-Item "D:\backups\backup_sqlite_20260709_120000.db" ".\data\customer_assistant.db"

# 3. 重新启动
docker compose up -d
```

---

## PostgreSQL 备份

### 数据存储位置

| 运行方式 | 数据位置 | 备注 |
|---|---|---|
| Docker Compose | Docker volume `postgres_data` | 独立于容器生命周期 |
| 外部 PostgreSQL（RDS/自建） | 由数据库服务管理 | 参考服务商备份策略 |

### pg_dump 备份

#### 从 Docker 容器内导出

```bash
# 导出为 SQL 文本文件（推荐，可读、可编辑）
docker exec ai-customer-v4-postgres pg_dump -U ai_customer ai_customer > "backup_pg_$(date +%Y%m%d_%H%M%S).sql"
```

#### 从宿主机直接连接导出

```bash
# 需先安装 postgresql-client 工具包
pg_dump -h localhost -p 5432 -U ai_customer ai_customer > "backup_pg_$(date +%Y%m%d_%H%M%S).sql"
```

#### 使用备份脚本

```powershell
.\scripts\backup_postgres.ps1 -ContainerName "ai-customer-v4-postgres" -DbUser "ai_customer" -DbName "ai_customer" -BackupDir "D:\backups"
```

脚本使用 `docker exec pg_dump` 导出，文件名包含时间戳，不覆盖已有备份，不删除任何文件。

### PostgreSQL 恢复

#### 恢复到 Docker 容器

```bash
# 方法 1：通过管道导入
docker exec -i ai-customer-v4-postgres psql -U ai_customer ai_customer < backup_pg_20260709_120000.sql
```

#### 恢复注意事项

- 恢复会覆盖现有数据。建议先在测试环境验证备份文件完整性。
- 如果数据库中有新增的表或列（通过 `upgrade_database()` 自动补齐），恢复旧备份不会丢失这些结构——因为应用启动时会自动执行 `upgrade_database()`。
- 恢复前建议先对当前数据库做一次额外备份：
  ```bash
  docker exec ai-customer-v4-postgres pg_dump -U ai_customer ai_customer > "pre_restore_$(date +%Y%m%d_%H%M%S).sql"
  ```

### Docker Volume 备份（完整数据目录）

此方法备份整个 PostgreSQL 数据目录，包含所有数据库和配置。

```bash
# 备份 volume
docker run --rm \
  -v ai-customer-followup-assistant-upload-v4_dev_postgres_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/postgres_volume_backup_$(date +%Y%m%d_%H%M%S).tar.gz -C /data .

# 恢复（需先停止容器）
docker compose -f docker-compose.postgres.yml down
docker run --rm \
  -v ai-customer-followup-assistant-upload-v4_dev_postgres_data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/postgres_volume_backup_20260709_120000.tar.gz -C /data
docker compose -f docker-compose.postgres.yml up -d
```

---

## 备份频率建议

| 场景 | 建议频率 | 保留周期 |
|---|---|---|
| 小团队日常使用 | 每日一次 | 至少 7-14 天 |
| 重要数据变更前（升级/迁移） | 变更前手动备份一次 | 长期保留 |
| 批量导入/导出操作前 | 操作前手动备份一次 | 保留至操作确认无误 |
| 低活跃度使用 | 每周一次 | 至少 4 周 |

---

## 恢复演练

- 定期（建议每季度）在测试环境上演练一次完整恢复流程。
- 演练步骤：
  1. 在测试环境启动干净的数据库实例。
  2. 使用最近一次备份文件恢复。
  3. 启动应用，验证登录、客户列表、知识库等功能正常。
- **不要在生产数据库上直接演练恢复**。先在测试环境验证流程，再考虑生产操作。

---

## 知识库文件与向量索引备份

### RAG 上传文件

- 上传的知识库文件内容存储在数据库 `document_chunks` 表中，包含于上述 SQLite/PostgreSQL 备份。
- 如果使用 Docker，`./data` 目录（SQLite 模式）也包含数据库文件，一并备份即可。

### ChromaDB 向量索引（VECTOR_SEARCH_ENABLED=true 时）

- ChromaDB 数据默认存储在 `./data/chroma_db` 目录。
- 备份时将此目录一并复制：
  ```powershell
  Copy-Item -Recurse .\data\chroma_db "D:\backups\chroma_db_$(Get-Date -Format yyyyMMdd_HHmmss)"
  ```
- 如果向量索引丢失或损坏，可以通过应用内的「重建向量索引」功能（`POST /rag/reindex`）从数据库重新生成，因此向量索引不是必须备份的。但备份可以节省重建时间。

### pgvector 向量索引（VECTOR_SEARCH_ENABLED=true + PostgreSQL 时）

- embedding 数据存储在 `document_chunks.embedding` 列中，包含于 `pg_dump` 备份。
- 无需额外备份步骤。

### VECTOR_SEARCH_ENABLED=false 时

- 不需要备份向量索引。只备份数据库文件和上传资料即可。

---

## 1Panel / 阿里云 / OpenResty 环境注意事项

### 1Panel

- 如果使用 1Panel 提供的 PostgreSQL 数据库，备份可使用 1Panel 自带的数据库备份功能。
- 也可以手动执行 `pg_dump`（需在 1Panel 容器内或通过其网络连接）。
- 备份文件建议下载到本地或其他独立存储。

### 阿里云 RDS

- 阿里云 RDS PostgreSQL 自带自动备份功能（默认保留 7 天）。
- 建议额外手动执行一次 `pg_dump` 导出到本地，作为异地备份。
- 连接示例：
  ```bash
  pg_dump -h <rds-endpoint> -p 5432 -U <username> -d <dbname> > backup.sql
  ```

### OpenResty / Nginx 反向代理

- 备份与反向代理无关，按上述数据库类型选择对应的备份方法。
- 建议同时备份 Nginx 配置文件，方便恢复时重建反向代理规则。

---

## 备份前检查清单

- [ ] 确认当前数据库类型（SQLite 或 PostgreSQL）。
- [ ] 确认备份目标目录有足够磁盘空间。
- [ ] 如果是生产环境，通知相关人员备份期间可能有短暂服务降级（如果停止容器）。
- [ ] 备份完成后，检查备份文件大小是否合理（不应为 0 字节）。
- [ ] 备份文件不要提交到 Git。

---

## 恢复前检查清单

- [ ] 确认备份文件完整（文件大小合理、可正常解压/读取）。
- [ ] 先在测试环境恢复并验证功能正常。
- [ ] 对当前生产数据库做一次额外备份（以防恢复出错需要回滚）。
- [ ] 通知相关人员恢复期间服务将不可用。
- [ ] 恢复完成后验证：登录、客户列表、知识库、跟进记录。

---

## 备份脚本

项目 `scripts/` 目录提供了两个备份脚本模板：

- `backup_sqlite.ps1`：SQLite 数据库备份（Windows PowerShell）
- `backup_postgres.ps1`：PostgreSQL 数据库备份（通过 `docker exec pg_dump`）

脚本特点：
- 只做备份，不删除任何文件，不覆盖已有备份。
- 文件名自动包含毫秒级时间戳（`yyyyMMdd_HHmmss_fff`），极大降低重名概率。
- 写入前检查目标文件是否已存在，如已存在则输出明确错误并退出（exit 1），不会静默覆盖。
- 不包含真实密码，敏感信息通过参数或环境变量传入。
- 参数缺失时输出使用说明并退出。
- 不包含 `Remove-Item -Recurse`、`rm -rf` 或任何批量删除命令。

注意：文档中手动 `>` 或 `Copy-Item` 示例可能在目标文件已存在时覆盖。正式备份建议使用 `scripts/backup_sqlite.ps1` 或 `scripts/backup_postgres.ps1`，脚本会检查同名文件并拒绝覆盖。

---

## 重要提醒

- **先备份，再升级，再验证**：每次应用升级或数据库结构变更前，务必备份。
- **不要批量删除备份**：手动检查并确认每份备份不再需要后再逐文件删除。
- **备份存储位置与生产服务器分离**：防止服务器故障导致备份一并丢失。
- **定期测试恢复流程**：备份能恢复才是有价值的备份。
