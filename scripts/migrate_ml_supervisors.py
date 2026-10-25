#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-10-26 物资物流部（M&L）两名部门主管归位（幂等，可安全重跑）。

方案：docs/ORG_RESTRUCTURE_2026_PLAN.md §九（M&L 按采矿部同构设部门级主管叶子）。
- GASPER IBRAHIMU(84)：Sorting Team → Materials & Logistics Department（分拣主管，
  position 已有 'supervisor-sorting'，不动）
- MALIKI HARUNI(90)：Sorting Team → Materials & Logistics Department（破碎主管，
  position 空 → 补记 'supervisor-crush'；其 10-25 调岗申请 #541 误选
  Site Operations & Services Department 已被拒，本次按组织图直接归位）

背景：EKON LEONARD(82) 已由 OA 事件 535 批准转 Production TEAM（10-26 生效），
破碎主管席位空出，由 MALIKI 接任；两名主管与采矿部三主管同构——落部门同名叶子
'Materials & Logistics Department'，team_id=0，薪资类型/基数/override 零改动，
出勤采集归「其他部门」池（与 Sorting Team 现行为一致），历史月薪资不受影响。

原则：
- 只改 employees.department（+ MALIKI position 补记），类型/基数/override/team_id 零改动
- 逐人写 audit_log(action='org_restructure')，含 old/new 部门与 position 变更
- 硬校验：两人必须 active、team_id=0、迁移后 M&L 叶子恰为 2 人；分布漂移仅告警
"""
import json
import sqlite3
import sys

DB = '/root/enprizon-salary/data/kilwa.db'
OPERATOR = 'ml-supervisors-2026-10-26'
TARGET = 'Materials & Logistics Department'

# (id, 目标部门, 新 position 或 None)
PER_ID_MOVES = [
    ('84', TARGET, None),                # GASPER IBRAHIMU, 分拣主管（position 已存）
    ('90', TARGET, 'supervisor-crush'),  # MALIKI HARUNI, 破碎主管（补 position）
]
# 2026-10-26 生产快照（含 10-25 晚批量调岗后现状）+ 本次两人调动后的预期分布
EXPECTED_AFTER = {
    'Production TEAM': 32, 'Sorting Team': 23, 'Crushing Team': 14,
    'Materials & Logistics Department': 2, 'Driller Team': 12,
    'Mining Department': 4, 'Engineering & Maintenance Department': 17,
    'Site Operations & Services Department': 25, 'ENPRIZON LINDI PROJECT': 9,
    'RIG': 7,
}


def main():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    changes = []

    def audit(eid, old, new, old_pos=None, new_pos=None):
        detail = {'old_department': old, 'new_department': new}
        if new_pos is not None:
            detail['old_position'] = old_pos
            detail['new_position'] = new_pos
        cur.execute(
            "INSERT INTO audit_log (action, employee_id, detail, operator) VALUES (?,?,?,?)",
            ('org_restructure', eid, json.dumps(detail, ensure_ascii=False), OPERATOR))

    # ── 1) 人级调动 ──
    for eid, target, new_pos in PER_ID_MOVES:
        row = cur.execute(
            "SELECT id, name, department, position, team_id FROM employees WHERE id=? AND status='active'",
            (eid,)).fetchone()
        if row is None:
            sys.exit(f"[abort] id={eid} 不存在或非 active，请先核实生产库")
        if row['department'] == target and (new_pos is None or (row['position'] or '') == new_pos):
            print(f"[skip] id={eid} {row['name']} 已在 {target}"
                  + (f"（position={row['position']}）" if new_pos else ""))
            continue
        if row['team_id'] not in (0, None):
            sys.exit(f"[abort] id={eid} {row['name']} team_id={row['team_id']} 非预期（方案要求 0）")
        old = row['department']
        old_pos = row['position'] or ''
        if new_pos is not None and old_pos != new_pos:
            cur.execute("UPDATE employees SET department=?, position=? WHERE id=?", (target, new_pos, eid))
        else:
            cur.execute("UPDATE employees SET department=? WHERE id=?", (target, eid))
        changes.append((eid, old, target))
        audit(eid, old, target, old_pos, new_pos)
        pos_note = f"，position: {old_pos or '空'} -> {new_pos}" if new_pos is not None and old_pos != new_pos else ""
        print(f"[move] id={eid} {row['name']}: {old} -> {target}{pos_note}")

    conn.commit()

    # ── 2) 校验 ──
    leaf = cur.execute(
        "SELECT COUNT(*) c FROM employees WHERE status='active' AND department=?", (TARGET,)
    ).fetchone()['c']
    if leaf != len(PER_ID_MOVES):
        sys.exit(f"[FAIL] {TARGET} 叶子应有 {len(PER_ID_MOVES)} 人，实际 {leaf}")
    dist = {r['department']: r['c'] for r in cur.execute(
        "SELECT department, COUNT(*) c FROM employees WHERE status='active' GROUP BY department")}
    total = sum(dist.values())
    print('---- 迁移后部门分布 ----')
    for dept, cnt in sorted(dist.items()):
        exp = EXPECTED_AFTER.get(dept)
        mark = ''
        if exp is not None and exp != cnt:
            mark = f'  (预期 {exp}，漂移 {cnt - exp:+d})'
        elif exp is None:
            mark = '  (未知部门)'
        print(f"{dept}: {cnt}{mark}")
    print(f"合计 {total} 人；本次变更 {len(changes)} 条")
    conn.close()
    print('[OK] 迁移完成')


if __name__ == '__main__':
    main()
