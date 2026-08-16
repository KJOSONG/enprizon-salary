#!/bin/bash
# cleanup-test-artifacts.sh — 测试产物 TTL 自动清理
# 机制：_work/ 目录永久保留；内部子目录/文件按 TTL 清理
#   - 默认清理超过 3 天的产物（保留近期可跨会话复用）
#   - 用法: bash cleanup-test-artifacts.sh            # 清 >3 天
#          bash cleanup-test-artifacts.sh --all       # 清空全部（慎用）
#          bash cleanup-test-artifacts.sh --dir 名称   # 删除指定任务产物
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/_work"
TTL_DAYS="${TTL_DAYS:-3}"

if [ ! -d "$WORK" ]; then
  echo "[cleanup] _work/ 不存在，无需清理"
  exit 0
fi

if [ "$1" = "--all" ]; then
  find "$WORK" -mindepth 1 -delete
  echo "[cleanup] 已清空 _work/ 全部内容（目录保留）"
  exit 0
fi

if [ "$1" = "--dir" ]; then
  target="$WORK/$2"
  if [ -d "$target" ] || [ -f "$target" ]; then
    rm -rf "$target"
    echo "[cleanup] 已删除任务产物: $2"
  else
    echo "[cleanup] 未找到: $2"
  fi
  exit 0
fi

# TTL 清理：删除超过 N 天的子目录与文件（目录保留）
count=$(find "$WORK" -mindepth 1 -mtime +"$TTL_DAYS" | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  find "$WORK" -mindepth 1 -mtime +"$TTL_DAYS" -exec rm -rf {} +
  echo "[cleanup] 已清理超过 ${TTL_DAYS} 天的测试产物（${count} 项）"
else
  echo "[cleanup] 无超过 ${TTL_DAYS} 天的测试产物"
fi
