#!/bin/bash
cd "$(dirname "$0")"
PIDFILE=".kilwa.pid"
PYTHON="/Users/osong/.workbuddy/binaries/python/envs/default/bin/python3"

# 从日志中提取实际端口（最多等 8 秒）
get_port() {
    for i in 1 2 3 4 5 6 7 8; do
        local p=$(grep -o "localhost:[0-9]*" .kilwa.log 2>/dev/null | tail -1 | cut -d: -f2)
        [ -n "$p" ] && echo "$p" && return
        sleep 1
    done
    echo "8081"
}

case "${1:-start}" in
  start|run)
    $PYTHON app.py
    ;;
  bg|background|daemon)
    nohup $PYTHON app.py > .kilwa.log 2>&1 &
    echo $! > "$PIDFILE"
    echo "ENPRIZON LINDI 已后台启动 (PID: $(cat $PIDFILE))"
    PORT=$(get_port)
    echo "浏览器打开 http://localhost:$PORT"
    echo ""
    grep -E "(自动加载|应发合计|实发合计)" .kilwa.log 2>/dev/null | sed 's/^  //'
    echo ""
    echo "用 'kilwa-stop' 或 '$0 stop' 关闭"
    ;;
  stop)
    PIDS=""
    # 方法1：PID 文件
    if [ -f "$PIDFILE" ]; then
      PIDS=$(cat "$PIDFILE")
      rm -f "$PIDFILE"
    fi
    # 方法2：端口扫描（兜底，处理所有残留进程）
    PORT_PIDS=$(lsof -ti:8080-8089 2>/dev/null)
    if [ -n "$PORT_PIDS" ]; then
      PIDS="$PIDS $PORT_PIDS"
    fi

    if [ -n "$PIDS" ]; then
      echo "$PIDS" | xargs kill 2>/dev/null
      sleep 1
      # 再补一刀
      lsof -ti:8080-8089 2>/dev/null | xargs kill -9 2>/dev/null
      echo "ENPRIZON LINDI 已停止"
    else
      echo "未找到运行中的 ENPRIZON LINDI 实例"
    fi
    ;;
  restart)
    $0 stop; sleep 1; $0 bg
    ;;
  *)
    echo "用法: $0 [start|bg|stop|restart]"
    echo "  start  前台启动 (默认)"
    echo "  bg     后台启动 (关终端仍运行)"
    echo "  stop   关闭后台实例"
esac
