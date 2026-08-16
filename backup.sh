#!/bin/bash
# ═══════════════════════════════════════════════
# Enprizon Salary — 每日自动备份脚本（cron 3:05）
# 备份目录规范（2026-08-16 统一）：
#   - 每日自动备份 → /root/salary-backup/kilwa.YYYYMMDD.db（本脚本，保留 7 天）
#   - 手动安全备份（部署前）→ data/backups/kilwa_before_<版本>_<时间戳>.db（只留最新 1 个）
#   - 禁止备份文件散落在 data/ 根目录
# ═══════════════════════════════════════════════
set -e

BACKUP_DIR="/root/salary-backup"
DB="/root/enprizon-salary/data/kilwa.db"
DATE=$(date +%Y%m%d)

# 备份数据库
cp "$DB" "$BACKUP_DIR/kilwa.$DATE.db"

# 删除7天前的旧备份
find "$BACKUP_DIR" -name 'kilwa.*.db' -mtime +7 -delete

echo "薪资系统备份完成: $DATE  |  数据库: $(du -sh $BACKUP_DIR/kilwa.$DATE.db | cut -f1)"
