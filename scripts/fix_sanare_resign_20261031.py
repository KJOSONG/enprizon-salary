#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P55f(2026-10-31, 用户批准)：修正 Sanare Sautindogo Mollel(67) 错挂的历史离职事件 #73
（8-18 录入时生效日期误为 2026-01-07，且当时 id 67 尚未入职、落库从未成功执行）。
处理：① #73 effective_date → 2026-10-01（用户指定）；② 重放 apply_approved_event
（写 dismissed_employees + employees.status='dismissed'）；③ audit_log 留痕。"""
import json
import sqlite3
import sys
import os
from datetime import datetime as _dt, timezone as _tz, timedelta as _tdh

sys.path.insert(0, '/root/enprizon-salary')

db_path = sys.argv[1] if len(sys.argv) > 1 else 'data/kilwa.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
now = _dt.now(_tz(_tdh(hours=3))).strftime('%Y-%m-%d %H:%M:%S')

ev = conn.execute("SELECT * FROM employee_events WHERE id=73").fetchone()
assert ev is not None and ev['event_type'] == 'dismiss', '事件 #73 不存在或类型不符'
print('修正前: eff=%s status=%s' % (ev['effective_date'], ev['status']))

# ① 修正生效日期（先提交释放写锁，再走 apply 的独立连接）
conn.execute("UPDATE employee_events SET effective_date='2026-10-01' WHERE id=73")
conn.commit()

# ② 重放离职落库
event = dict(ev)
event['effective_date'] = '2026-10-01'
from core.database import apply_approved_event
apply_approved_event(os.path.dirname(db_path), event)

# ③ 审计
conn.execute(
    "INSERT INTO audit_log (timestamp, action, employee_id, detail, operator) VALUES (?,?,?,?,?)",
    (now, 'resign_date_fix', '67',
     json.dumps({'event_id': 73, 'old_effective_date': '2026-01-07',
                 'new_effective_date': '2026-10-01', 'applied': True,
                 'reason': '用户批准: 日期误录修正并执行离职落库'}, ensure_ascii=False),
     'KEJU-script'))
conn.commit()

emp = conn.execute("SELECT id, name, status, dismissed_at FROM employees WHERE id=67").fetchone()
dis = conn.execute("SELECT employee_id, note, dismissed_at FROM dismissed_employees WHERE employee_id='67'").fetchone()
print('employees: status=%s dismissed_at=%s' % (emp['status'], emp['dismissed_at']))
print('dismissed_employees: %s' % (dict(dis) if dis else None))
conn.close()
print('DONE')
