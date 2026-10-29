#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P55d 数据修复（2026-10-28，用户批准）：
1. DASTANI LOMWADI(101)：无区间永久 piece_crush override（6 月时代残留）截断到
   2026-09-07（钻工调岗生效日前一天）——修类型标签污染，历史破碎轨道保留。
2. AZIZI SWALEH(29)：10-05 与破碎组工作但采集名单漏登+无轨道 →
   a) 补单日 piece_crush override [2026-10-05,2026-10-05]；
   b) 破碎提交 #700 emps 补 "29"（version+1，旧 payload 落 collection_history）。
每步写 audit_log。幂等：条件不满足即跳过。
"""
import json
import sqlite3
import sys
from datetime import datetime as _dt, timezone as _tz, timedelta as _tdh

db_path = sys.argv[1] if len(sys.argv) > 1 else 'data/kilwa.db'
apply_mode = '--apply' in sys.argv

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
now = _dt.now(_tz(_tdh(hours=3))).strftime('%Y-%m-%d %H:%M:%S')
acts = []


def audit(action, eid, detail):
    conn.execute("INSERT INTO audit_log (timestamp, action, employee_id, detail, operator)"
                 " VALUES (?,?,?,?,?)", (now, action, eid, json.dumps(detail, ensure_ascii=False), 'KEJU-script'))


# ── 1. DASTANI(101) 类型残留截断 ──
row = conn.execute(
    "SELECT id, start_date, end_date FROM overrides WHERE employee_id='101'"
    " AND salary_type='piece_crush' AND IFNULL(start_date,'')='' AND IFNULL(end_date,'')=''"
    " AND IFNULL(day_rate,0)=0 AND IFNULL(monthly_salary,0)=0").fetchone()
if row:
    print('1) 101 piece_crush 永久行 id=%s → end_date=2026-09-07' % row['id'])
    acts.append(('trim', '101'))
    if apply_mode:
        conn.execute("UPDATE overrides SET end_date='2026-09-07' WHERE id=?", (row['id'],))
        audit('override_type_trim', '101',
              {'override_id': row['id'], 'salary_type': 'piece_crush', 'new_end_date': '2026-09-07',
               'reason': 'P55d DASTANI 调岗(9-8→钻工)后旧计件类型残留污染标签'})
else:
    print('1) 101 无需处理（已截断或不存在）')

# ── 2a. AZIZI(29) 单日轨道 override ──
dup = conn.execute(
    "SELECT COUNT(*) AS c FROM overrides WHERE employee_id='29' AND salary_type='piece_crush'"
    " AND start_date='2026-10-05' AND end_date='2026-10-05'").fetchone()['c']
if int(dup) == 0:
    print('2a) 29 补单日 piece_crush override [2026-10-05,2026-10-05]')
    acts.append(('ovr', '29'))
    if apply_mode:
        conn.execute(
            "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary, start_date, end_date, note, type, shift, captain, effective_from)"
            " VALUES ('29','piece_crush',0,0,'2026-10-05','2026-10-05','AZIZI 10-05 与破碎组工作(用户确认),单日轨道', '', '', '', '')")
        audit('transfer_track_day_override', '29',
              {'salary_type': 'piece_crush', 'start': '2026-10-05', 'end': '2026-10-05',
               'reason': '10-05 与破碎组工作但调岗生效日为 10-06,补单日轨道(用户批准)'})
else:
    print('2a) 29 已存在 10-05 轨道 override')

# ── 2b. 破碎提交 #700 emps 补 29 ──
sub = conn.execute("SELECT id, version, payload FROM collection_submissions WHERE id=700").fetchone()
if sub:
    payload = json.loads(sub['payload'])
    emps = [str(x) for x in (payload.get('emps') or [])]
    if '29' not in emps:
        print('2b) 提交#700 emps 补 29 (v%s → v%s)' % (sub['version'], sub['version'] + 1))
        acts.append(('crush_edit', '29'))
        if apply_mode:
            conn.execute("INSERT INTO collection_history (submission_id, version, payload, operator_id)"
                         " VALUES (?,?,?,?)", (700, sub['version'], sub['payload'], 'KEJU-script'))
            emps.append('29')
            payload['emps'] = emps
            conn.execute("UPDATE collection_submissions SET payload=?, version=version+1,"
                         " updated_at=datetime('now','+3 hours') WHERE id=700",
                         (json.dumps(payload, ensure_ascii=False),))
            audit('collection_edit', '29',
                  {'submission_id': 700, 'change': 'emps append 29',
                   'reason': 'AZIZI 10-05 参与破碎(用户批准),名单漏登补录'})
    else:
        print('2b) 提交#700 已含 29')
else:
    print('2b) 提交 #700 不存在！')

print('mode=%s actions=%d' % ('APPLY' if apply_mode else 'DRY-RUN', len(acts)))
if apply_mode:
    conn.commit()
    print('COMMITTED.')
conn.close()
