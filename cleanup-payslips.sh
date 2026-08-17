#!/bin/bash
# 清理7天前的工资单PDF文件
PAYS_DIR="$(dirname "$0")/data/payslips"
if [ -d "$PAYS_DIR" ]; then
    find "$PAYS_DIR" -name "*.pdf" -type f -mtime +7 -delete
    echo "$(date): Cleaned payslips older than 7 days" >> "$(dirname "$0")/data/payslips/cleanup.log"
fi
