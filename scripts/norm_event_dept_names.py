#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调岗事件链遗留部门名归一（2026-10-27 治本修复）。

背景：部门重整只改 employees.department，未迁移历史已批准调岗事件 payload 中的
new_department/old_department。P40-d _apply_transfer_day_view 以事件链为按日归属
权威，导致目标部门为旧名的员工（Halid hasan/60、JEREMIAH/170 → "Mechanic Team"）
在采集花名册中被归到已不存在的部门，出勤提交找不到人。

归一规则（只动 event_type='transfer' AND status='approved' 的 payload）：
  1. 结构性改名（无条件）：
     'Production TEAM （underground）' → 'Production TEAM'        （全角括号旧名，isUgDept 本就等价）
     'Mechanic Team'                   → 'Engineering & Maintenance Department'
  2. 拆分继承（按员工现部门消歧，且绝不把非 UG 旧名映射进 UG）：
     Sort Crush 家族 {'Sort Crush', 'Sort Crush/Crush Piece Rate', '分拣破碎[EN:Sort Crush]'}
        → 员工现部门 ∈ {'Sorting Team','Crushing Team'} ? 现部门 : 'Sorting Team'
     Logistics 家族 {'Logistics', 'Logistics/Ground production'}
        → 员工现部门 ∈ 树内非 UG ? 现部门 : 'Materials & Logistics Department'
  3. rejected/pending 事件不触碰（day view 只读 approved，历史记录保持原样）。

幂等：已归一的值不会再被匹配。每次变更写 audit_log(action='event_dept_norm')。

用法：
  python3 scripts/norm_event_dept_names.py /path/to/kilwa.db            # dry-run
  python3 scripts/norm_event_dept_names.py /path/to/kilwa.db --apply    # 写入
"""
import json
import sqlite3
import sys

TREE = {
    'Mining Department', 'Production TEAM', 'Driller Team',
    'Engineering & Maintenance Department', 'Site Operations & Services Department',
    'Materials & Logistics Department', 'Sorting Team', 'Crushing Team',
    'RIG', 'ENPRIZON LINDI PROJECT',
}
NON_UG_TREE = TREE - {'Production TEAM'}
UG_LEGACY = {'Production TEAM （underground）': 'Production TEAM'}
MECHANIC_LEGACY = {'Mechanic Team': 'Engineering & Maintenance Department'}
SORTCRUSH_LEGACY = {'Sort Crush', 'Sort Crush/Crush Piece Rate', '分拣破碎[EN:Sort Crush]'}
SORTCRUSH_SPLIT_OK = {'Sorting Team', 'Crushing Team'}
SORTCRUSH_DEFAULT = 'Sorting Team'
LOGISTICS_LEGACY = {'Logistics', 'Logistics/Ground production'}
LOGISTICS_DEFAULT = 'Materials & Logistics Department'


def norm(value, cur_dept):
    """单个部门字段归一；无需变更时原样返回。"""
    if not value:
        return value
    if value in UG_LEGACY:
        return UG_LEGACY[value]
    if value in MECHANIC_LEGACY:
        return MECHANIC_LEGACY[value]
    if value in SORTCRUSH_LEGACY:
        # 守卫：拆分继承只落 Sorting/Crushing，绝不映射进 UG 或树外值
        return cur_dept if cur_dept in SORTCRUSH_SPLIT_OK else SORTCRUSH_DEFAULT
    if value in LOGISTICS_LEGACY:
        # 守卫：只落树内非 UG
        return cur_dept if cur_dept in NON_UG_TREE else LOGISTICS_DEFAULT
    return value


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    db_path = sys.argv[1]
    apply_mode = '--apply' in sys.argv[2:]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur_map = {str(r['id']): (r['department'] or '') for r in
               conn.execute("SELECT id, department FROM employees").fetchall()}
    rows = conn.execute(
        "SELECT id, employee_id, payload FROM employee_events"
        " WHERE event_type='transfer' AND status='approved' ORDER BY id").fetchall()

    changes = []
    for r in rows:
        try:
            payload = json.loads(r['payload'] or '{}')
        except (TypeError, ValueError):
            continue
        cur = cur_map.get(str(r['employee_id']), '')
        field_changes = {}
        for field in ('new_department', 'old_department'):
            old_v = payload.get(field) or ''
            new_v = norm(old_v, cur)
            if new_v != old_v:
                payload[field] = new_v
                field_changes[field] = [old_v, new_v]
        if field_changes:
            changes.append((r['id'], str(r['employee_id']), field_changes,
                            json.dumps(payload, ensure_ascii=False)))

    print('mode=%s events_scanned=%d events_changed=%d' % (
        'APPLY' if apply_mode else 'DRY-RUN', len(rows), len(changes)))
    for eid, emp, fc, _new_payload in changes:
        for field, (o, n) in fc.items():
            print('  event#%s emp=%s %s: %r -> %r' % (eid, emp, field, o, n))

    if not apply_mode:
        print('DRY-RUN: 未写入任何数据。确认无误后加 --apply 执行。')
        conn.close()
        return

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M:%S')
    for eid, emp, fc, new_payload in changes:
        conn.execute("UPDATE employee_events SET payload=? WHERE id=?", (new_payload, eid))
        conn.execute(
            "INSERT INTO audit_log (timestamp, action, employee_id, detail, operator)"
            " VALUES (?,?,?,?,?)",
            (now, 'event_dept_norm', emp,
             json.dumps({'event_id': eid, 'changes': fc}, ensure_ascii=False),
             'KEJU-script'))
    conn.commit()
    conn.close()
    print('APPLIED: %d 条事件已归一并写入 audit_log(event_dept_norm)。' % len(changes))


if __name__ == '__main__':
    main()
