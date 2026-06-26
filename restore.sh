#!/bin/bash
# ═══════════════════════════════════════════════
# ENPRIZON LINDI PROJECT — 一键恢复脚本
# ═══════════════════════════════════════════════
set -e
cd "$(dirname "$0")"

BACKUP_FILE="${1:-$HOME/Desktop/enprizon_backups/kilwa_latest.db}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ 未找到备份文件: $BACKUP_FILE"
    echo "用法: ./restore.sh [备份文件路径]"
    exit 1
fi

# 关系统：杀光 8080-8089 所有进程
echo "🛑 正在关闭系统..."
lsof -ti:8080-8089 2>/dev/null | xargs kill 2>/dev/null || true
sleep 2
# 再补一刀
lsof -ti:8080-8089 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# 恢复
cp "$BACKUP_FILE" data/kilwa.db
echo "✅ 数据库已恢复: $(du -h "$BACKUP_FILE" | cut -f1)"

# 开系统
echo "🚀 正在启动系统..."
rm -f .kilwa.pid .kilwa.log
./start.sh bg

echo ""
echo "✅ 恢复完成！请查看上方 '浏览器打开' 地址"
