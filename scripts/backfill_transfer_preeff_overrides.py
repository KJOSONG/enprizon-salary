#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P55d 数据回填：当月月中调岗（转入计件）后，生效前当月天数按旧类型旧基数计薪所需
的区间 override 缺失（基数只挂主档、被审批清零）→ 生效前工资丢失。

本脚本扫描指定月份内生效的已批准调岗事件，对满足以下全部条件的员工补一条
[当月1号, 生效日前一天] 的旧类型旧基数 override：
  1. old_type ∈ (day_rate, monthly) 且旧基数 > 0（取事件 payload 的 old_* 字段，
     审批时由 resolve_effective_base 固化，可追溯）；
  2. 生效日非当月 1 号（区间非空）；
  3. 员工主档对应基数当前为 0（损失判定——基数还在主档的没丢，如调回原类型的）；
  4. 无同类型永久 override（基数仍挂账，如 82 EKON）；
  5. 无同类型同区间的既有 override（幂等）。
每条补录写 audit_log(action='transfer_preeff_backfill')。

用法：
  python3 scripts/backfill_transfer_preeff_overrides.py /path/to/kilwa.db 2026-10            # dry-run
  python3 scripts/backfill_transfer_preeff_overrides.py /path/to/kilwa.db 2026-10 --apply    # 写入
"""
import json
import sqlite3
import sys


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    db_path, month = sys.argv[1], sys.argv[2]
    apply_mode = '--apply' in sys.argv[3:]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    events = conn.execute(
        "SELECT id, employee_id, effective_date, payload FROM employee_events"
        " WHERE event_type='transfer' AND status='approved' AND substr(effective_date,1,7)=?"
        " ORDER BY id", (month,)).fetchall()

    inserts = []
    for ev in events:
        eid = str(ev['employee_id'])
        eff = (ev['effective_date'] or '')[:10]
        try:
            payload = json.loads(ev['payload'] or '{}')
        except (TypeError, ValueError):
            continue
        old_type = (payload.get('old_type') or '').strip()
        try:
            old_day = float(payload.get('old_day_rate') or 0)
            old_month = float(payload.get('old_monthly_salary') or 0)
        except (TypeError, ValueError):
            continue
        old_amt = old_day if old_type == 'day_rate' else (old_month if old_type == 'monthly' else 0)
        if old_type not in ('day_rate', 'monthly') or old_amt <= 0:
            continue
        if eff[8:10] == '01':  # 生效日为 1 号，区间空
            continue
        emp = conn.execute(
            "SELECT day_rate, monthly_salary FROM employees WHERE id=?", (eid,)).fetchone()
        if not emp:
            continue
        cur_base = float(emp['day_rate'] or 0) if old_type == 'day_rate' else float(emp['monthly_salary'] or 0)
        if cur_base > 0:  # 主档基数还在（调回/未清零），无损失
            continue
        perm = conn.execute(
            "SELECT COUNT(*) AS c FROM overrides WHERE employee_id=? AND salary_type=?"
            " AND IFNULL(start_date,'')='' AND IFNULL(end_date,'')=''", (eid, old_type)).fetchone()['c']
        if int(perm) > 0:  # 基数挂永久 override，计薪端仍可取到
            continue
        start = eff[:7] + '-01'
        from datetime import datetime as _dt, timedelta as _td
        end = (_dt.strptime(eff, '%Y-%m-%d') - _td(days=1)).strftime('%Y-%m-%d')
        dup = conn.execute(
            "SELECT COUNT(*) AS c FROM overrides WHERE employee_id=? AND salary_type=?"
            " AND start_date=? AND end_date=?", (eid, old_type, start, end)).fetchone()['c']
        if int(dup) > 0:
            continue
        inserts.append((eid, old_type, old_amt, start, end, ev['id']))

    print('mode=%s month=%s events_scanned=%d to_backfill=%d' % (
        'APPLY' if apply_mode else 'DRY-RUN', month, len(events), len(inserts)))
    for eid, st, amt, s, e, evid in inserts:
        print('  emp=%s %s %s [2026-10-01 风格区间 %s ~ %s] (event #%s)' % (eid, st, amt, s, e, evid))

    if not apply_mode:
        print('DRY-RUN: 未写入。确认后加 --apply。')
        conn.close()
        return

    from datetime import datetime as _dtn, timezone as _tz, timedelta as _tdh
    now = _dtn.now(_tz(_tdh(hours=3))).strftime('%Y-%m-%d %H:%M:%S')
    for eid, st, amt, s, e, evid in inserts:
        conn.execute(
            "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary, start_date, end_date, note, type, shift, captain, effective_from)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, st, amt if st == 'day_rate' else 0, amt if st == 'monthly' else 0,
             s, e, f'OA调岗生效前基数保护(回填) #{evid}', '', '', '', ''))
        conn.execute(
            "INSERT INTO audit_log (timestamp, action, employee_id, detail, operator)"
            " VALUES (?,?,?,?,?)",
            (now, 'transfer_preeff_backfill', eid,
             json.dumps({'event_id': evid, 'salary_type': st, 'amount': amt,
                         'start': s, 'end': e}, ensure_ascii=False), 'KEJU-script'))
    conn.commit()
    conn.close()
    print('APPLIED: %d 条生效前基数保护 override 已补录。请重算/重启使 10 月缓存失效。' % len(inserts))


if __name__ == '__main__':
    main()
