<#
.SYNOPSIS
    SQLite 数据库备份脚本
.DESCRIPTION
    将 SQLite 数据库文件复制到指定备份目录，文件名自动包含时间戳。
    只做备份，不删除任何文件，不覆盖已有备份。
.PARAMETER DbPath
    SQLite 数据库文件路径（例如 .\data\customer_assistant.db）
.PARAMETER BackupDir
    备份目标目录（例如 D:\backups），目录不存在时会自动创建。
.EXAMPLE
    .\backup_sqlite.ps1 -DbPath ".\data\customer_assistant.db" -BackupDir "D:\backups"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$DbPath,

    [Parameter(Mandatory=$false)]
    [string]$BackupDir
)

# ── 参数校验 ──
if (-not $DbPath) {
    Write-Host "用法: .\backup_sqlite.ps1 -DbPath <数据库文件路径> -BackupDir <备份目录>" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "示例:"
    Write-Host "  .\backup_sqlite.ps1 -DbPath `".\data\customer_assistant.db`" -BackupDir `"D:\backups`""
    exit 1
}

if (-not $BackupDir) {
    Write-Host "用法: .\backup_sqlite.ps1 -DbPath <数据库文件路径> -BackupDir <备份目录>" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "示例:"
    Write-Host "  .\backup_sqlite.ps1 -DbPath `".\data\customer_assistant.db`" -BackupDir `"D:\backups`""
    exit 1
}

# ── 检查源文件 ──
if (-not (Test-Path $DbPath)) {
    Write-Host "错误: 源数据库文件不存在: $DbPath" -ForegroundColor Red
    exit 1
}

# ── 创建备份目录 ──
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "已创建备份目录: $BackupDir"
}

# ── 生成带时间戳的文件名（毫秒精度，降低同名概率）──
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$filename = [System.IO.Path]::GetFileNameWithoutExtension($DbPath)
$extension = [System.IO.Path]::GetExtension($DbPath)
$backupFile = Join-Path $BackupDir "backup_${filename}_${timestamp}${extension}"

# ── 覆盖保护：如果目标文件已存在则拒绝 ──
if (Test-Path $backupFile) {
    Write-Host "错误: 备份文件已存在，为避免覆盖已停止: $backupFile" -ForegroundColor Red
    exit 1
}

# ── 执行备份 ──
Write-Host "正在备份 SQLite 数据库..." -ForegroundColor Cyan
Write-Host "  源文件: $DbPath"
Write-Host "  目标文件: $backupFile"

try {
    Copy-Item -Path $DbPath -Destination $backupFile
    $backupSize = (Get-Item $backupFile).Length
    Write-Host "备份完成: $backupFile ($('{0:N0}' -f $backupSize) 字节)" -ForegroundColor Green
} catch {
    Write-Host "备份失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
