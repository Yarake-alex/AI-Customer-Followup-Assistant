<#
.SYNOPSIS
    PostgreSQL 数据库备份脚本（通过 docker exec pg_dump）
.DESCRIPTION
    在运行的 PostgreSQL Docker 容器上执行 pg_dump 导出，备份文件自动包含时间戳。
    只做备份，不删除任何文件，不覆盖已有备份。
.PARAMETER ContainerName
    PostgreSQL Docker 容器名称（例如 ai-customer-v4-postgres）
.PARAMETER DbUser
    数据库用户名（例如 ai_customer）
.PARAMETER DbName
    数据库名称（例如 ai_customer）
.PARAMETER BackupDir
    备份目标目录（例如 D:\backups），目录不存在时会自动创建。
.EXAMPLE
    .\backup_postgres.ps1 -ContainerName "ai-customer-v4-postgres" -DbUser "ai_customer" -DbName "ai_customer" -BackupDir "D:\backups"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$ContainerName,

    [Parameter(Mandatory=$false)]
    [string]$DbUser,

    [Parameter(Mandatory=$false)]
    [string]$DbName,

    [Parameter(Mandatory=$false)]
    [string]$BackupDir
)

# ── 参数校验 ──
if (-not $ContainerName -or -not $DbUser -or -not $DbName -or -not $BackupDir) {
    Write-Host "用法: .\backup_postgres.ps1 -ContainerName <容器名> -DbUser <用户名> -DbName <数据库名> -BackupDir <备份目录>" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "示例:"
    Write-Host "  .\backup_postgres.ps1 -ContainerName `"ai-customer-v4-postgres`" -DbUser `"ai_customer`" -DbName `"ai_customer`" -BackupDir `"D:\backups`""
    exit 1
}

# ── 检查 Docker 是否可用 ──
$dockerAvailable = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerAvailable) {
    Write-Host "错误: 未找到 docker 命令。请确认 Docker 已安装且在 PATH 中。" -ForegroundColor Red
    exit 1
}

# ── 检查容器是否运行 ──
$containerRunning = docker ps --format "{{.Names}}" 2>$null | Select-String -Pattern "^$ContainerName$"
if (-not $containerRunning) {
    Write-Host "错误: 容器 '$ContainerName' 未运行或不存在。" -ForegroundColor Red
    Write-Host "运行中的容器列表:"
    docker ps --format "  - {{.Names}}" 2>$null
    exit 1
}

# ── 创建备份目录 ──
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "已创建备份目录: $BackupDir"
}

# ── 生成带时间戳的文件名（毫秒精度，降低同名概率）──
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$backupFile = Join-Path $BackupDir "backup_${DbName}_${timestamp}.sql"

# ── 覆盖保护：如果目标文件已存在则拒绝 ──
if (Test-Path $backupFile) {
    Write-Host "错误: 备份文件已存在，为避免覆盖已停止: $backupFile" -ForegroundColor Red
    exit 1
}

# ── 执行备份 ──
Write-Host "正在备份 PostgreSQL 数据库..." -ForegroundColor Cyan
Write-Host "  容器: $ContainerName"
Write-Host "  数据库: $DbName"
Write-Host "  目标文件: $backupFile"

try {
    docker exec $ContainerName pg_dump -U $DbUser $DbName > $backupFile

    if ($LASTEXITCODE -ne 0) {
        Write-Host "备份失败: docker exec pg_dump 返回退出码 $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }

    if (Test-Path $backupFile) {
        $backupSize = (Get-Item $backupFile).Length
        if ($backupSize -eq 0) {
            Write-Host "警告: 备份文件大小为 0 字节，可能备份不完整。" -ForegroundColor Yellow
        } else {
            Write-Host "备份完成: $backupFile ($('{0:N0}' -f $backupSize) 字节)" -ForegroundColor Green
        }
    } else {
        Write-Host "警告: 备份文件未生成，pg_dump 可能未产生输出。" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "备份失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
