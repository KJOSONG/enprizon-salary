#!/bin/bash
# ═══════════════════════════════════════════════
# ENPRIZON LINDI PROJECT — 安全测试工作流
# ═══════════════════════════════════════════════
# 用法：
#   ./test-workflow.sh start   — 从备份创建 test.db
#   ./test-workflow.sh swap    — 用 test.db 替换生产 DB（做测试时用）
#   ./test-workflow.sh restore — 恢复生产 DB（测试完后）
#   ./test-workflow.sh clean   — 删除 test.db + prod_kilwa.db
#   ./test-workflow.sh run 'print("hi")'  — 快速运行（不推荐，建议 swap）
# ═══════════════════════════════════════════════
set -e

DATA_DIR="$HOME/WorkBuddy/kilwa-system/data"
BACKUP_DIR="${2:-$HOME/Desktop/enprizon_backups}"
DB_FILE="$DATA_DIR/kilwa.db"
TEST_DB="$DATA_DIR/test_kilwa.db"
PROD_SAVE="$DATA_DIR/prod_kilwa.db"

case "${1:-}" in
  start)
    if [ ! -f "$BACKUP_DIR/kilwa_latest.db" ]; then
      echo "❌ 备份文件不存在: $BACKUP_DIR/kilwa_latest.db"
      echo "   手动备份: cp data/kilwa.db Desktop/enprizon_backups/kilwa_latest.db"
      exit 1
    fi
    cp "$BACKUP_DIR/kilwa_latest.db" "$TEST_DB"
    echo "✅ test.db 已创建（来自备份）"
    echo "   路径: $TEST_DB"
    echo "   备份时间: $(ls -l "$BACKUP_DIR/kilwa_latest.db" | awk '{print $6,$7,$8}')"
    echo ""
    echo "下一步: ./test-workflow.sh swap"
    ;;

  swap)
    if [ ! -f "$TEST_DB" ]; then
      echo "❌ test.db 不存在。先执行 ./test-workflow.sh start"
      exit 1
    fi
    echo "🔄 保留生产 DB → prod_kilwa.db"
    cp "$DB_FILE" "$PROD_SAVE"
    echo "🔄 换入 test.db → kilwa.db"
    cp "$TEST_DB" "$DB_FILE"
    echo "✅ 现在可以运行测试代码了（操作的是 test_kilwa 的数据）"
    echo "   测试完后执行: ./test-workflow.sh restore"
    ;;

  restore)
    if [ ! -f "$PROD_SAVE" ]; then
      echo "❌ 未找到 prod_kilwa.db，无法恢复"
      exit 1
    fi
    echo "🔄 恢复生产 DB"
    cp "$PROD_SAVE" "$DB_FILE"
    rm "$PROD_SAVE"
    echo "✅ 生产 DB 已恢复，测试数据已隔离"
    ;;

  clean)
    if [ -f "$PROD_SAVE" ]; then
      echo "⚠️  prod_kilwa.db 仍然存在，可能你忘了 restore"
      echo "   执行: ./test-workflow.sh restore"
      exit 1
    fi
    if [ -f "$TEST_DB" ]; then
      rm "$TEST_DB"
      echo "✅ test_kilwa.db 已删除"
    else
      echo "ℹ️  test_kilwa.db 不存在"
    fi
    echo "✅ 状态: $(ls -la "$DB_FILE" | awk '{print $6,$7,$8}')"
    echo "   MD5: $(md5 -q "$DB_FILE")"
    ;;

  run)
    echo "⚠️  DEPRECATED: 请使用 start → swap → (测试) → restore → clean"
    echo "   这条命令不会隔离 DB，已禁用"
    exit 1
    ;;

  *)
    echo "用法: ./test-workflow.sh {start|swap|restore|clean}"
    echo ""
    echo "  start   — 从备份创建 test.db"
    echo "  swap    — 用 test.db 替换生产 DB（测试时）"
    echo "  restore — 恢复生产 DB（测试完）"
    echo "  clean   — 删除 test.db"
    echo ""
    echo "完整流程:"
    echo "  ./test-workflow.sh start"
    echo "  ./test-workflow.sh swap"
    echo "  # ... 运行测试代码（操作的是 test 数据）..."
    echo "  ./test-workflow.sh restore"
    echo "  ./test-workflow.sh clean"
    exit 1
    ;;
esac
