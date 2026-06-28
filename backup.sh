#!/bin/bash
# ═══════════════════════════════════════════════
# Enprizon Salary — 数据库自动备份脚本
# ═══════════════════════════════════════════════
set -e

BACKUP_DIR="/root/salary-backup"
DB="/root/enprizon-salary/data/kilwa.db"
DATE=$(date +%Y%m%d)

# 备份数据库
cp "$DB" "$BACKUP_DIR/kilwa.$DATE.db"

# 删除30天前的旧备份
find "$BACKUP_DIR" -name 'kilwa.*.db' -mtime +30 -delete

echo "薪资系统备份完成: $DATE  |  数据库: $(du -sh $BACKUP_DIR/kilwa.$DATE.db | cut -f1)"
