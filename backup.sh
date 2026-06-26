#!/bin/bash
# ═══════════════════════════════════════════════
# ENPRIZON LINDI PROJECT — 一键备份脚本（覆盖模式）
# ═══════════════════════════════════════════════
set -e

BACKUP_DIR="${1:-$HOME/Desktop/enprizon_backups}"
DB_FILE="$HOME/WorkBuddy/kilwa-system/data/kilwa.db"

mkdir -p "$BACKUP_DIR"

echo "📦 正在备份 ENPRIZON LINDI PROJECT..."

if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/kilwa_latest.db"
    echo "   ✅ 数据库已备份: kilwa_latest.db ($(du -h "$DB_FILE" | cut -f1))"
else
    echo "   ⚠️  未找到数据库文件，无法备份"
    exit 1
fi

echo ""
echo "✅ 备份完成！路径: $BACKUP_DIR"
echo "   恢复命令: cp $BACKUP_DIR/kilwa_latest.db $HOME/WorkBuddy/kilwa-system/data/kilwa.db"
