#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-11 组织重组数据迁移（幂等，可安全重跑）。

方案：docs/ORG_RESTRUCTURE_2026_PLAN.md（v2 生产库核实版）
原则：
- 只改 employees.department（active 员工），类型/基数/override/team_id 零改动
- 人级调动先执行（部分人当前就在待合并部门里），bulk 部门映射后执行
- 逐人写 audit_log(action='org_restructure')，含 old/new 部门
- 硬校验：迁移后 active 员工不得残留旧部门名；分布与预期逐行对照（漂移仅告警）
"""
import json
import sqlite3
import sys

DB = '/root/enprizon-salary/data/kilwa.db'
OPERATOR = 'org-restructure-2026-11'

# (id, target_dept)；三主管 team_id 必须为 0（方案 1.3）
PER_ID_MOVES = [
    ('25', 'Mining Department'),   # ADHIRUDINI SIJAE RASHID, monthly
    ('52', 'Mining Department'),   # YUSUPH HAMISI MTWIKU, monthly
    ('30', 'Mining Department'),   # RUPIMO MASAGA KADOSHI, day_rate
    ('118', 'Site Operations & Services Department'),  # JORAM JACOB NYANGORO, 加油员
    ('126', 'Site Operations & Services Department'),  # RAMAZANI MASAME, 加油员
    ('127', 'ENPRIZON LINDI PROJECT'),                 # LAMEKI HARUNA KASEMA, 工程部部长
    ('82', 'Crushing Team'),       # EKON LEONARD, 破碎主管
]
# (old, new)；人级调动之后执行（仅 active）
BULK_RENAMES = [
    ('Production TEAM （underground）', 'Production TEAM'),
    ('Sort Crush', 'Sorting Team'),
    ('Sort Crush/Crush Piece Rate', 'Crushing Team'),
    ('Logistics', 'Site Operations & Services Department'),
    ('Logistics/Ground production', 'Site Operations & Services Department'),
]
# 以 2026-10-25 生产快照为基准的预期分布（当日新入职会漂移，仅告警不阻断）
EXPECTED_AFTER = {
    'Production TEAM': 24, 'Driller Team': 12, 'Mining Department': 3,
    'Engineering & Maintenance Department': 17,
    'Site Operations & Services Department': 26,
    'Sorting Team': 33, 'Crushing Team': 15, 'RIG': 7,
    'ENPRIZON LINDI PROJECT': 9,
}
OLD_NAMES = tuple(o for o, _ in BULK_RENAMES)


def main():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    changes = []

    def audit(eid, old, new):
        cur.execute(
            "INSERT INTO audit_log (action, employee_id, detail, operator) VALUES (?,?,?,?)",
            ('org_restructure', eid,
             json.dumps({'old_department': old, 'new_department': new}, ensure_ascii=False),
             OPERATOR))

    # ── 1) 人级调动 ──
    for eid, target in PER_ID_MOVES:
        row = cur.execute(
            "SELECT id, name, department, team_id FROM employees WHERE id=? AND status='active'",
            (eid,)).fetchone()
        if row is None:
            print(f"[skip] id={eid} 不存在或非 active")
            continue
        if row['department'] == target:
            print(f"[skip] id={eid} {row['name']} 已在 {target}")
            continue
        if row['team_id'] not in (0, None):
            sys.exit(f"[abort] id={eid} {row['name']} team_id={row['team_id']} 非预期（方案要求 0）")
        old = row['department']
        cur.execute("UPDATE employees SET department=? WHERE id=?", (target, eid))
        changes.append((eid, old, target))
        audit(eid, old, target)
        print(f"[move] id={eid} {row['name']}: {old} -> {target}")

    # ── 2) bulk 部门改名/合并 ──
    for old, new in BULK_RENAMES:
        rows = cur.execute(
            "SELECT id, name FROM employees WHERE department=? AND status='active'",
            (old,)).fetchall()
        for r in rows:
            cur.execute("UPDATE employees SET department=? WHERE id=?", (new, r['id']))
            changes.append((r['id'], old, new))
            audit(r['id'], old, new)
        print(f"[bulk] {old} -> {new}: {len(rows)} 人")

    conn.commit()

    # ── 3) 校验 ──
    left = cur.execute(
        "SELECT COUNT(*) c FROM employees WHERE status='active' AND department IN (?,?,?,?,?)",
        OLD_NAMES).fetchone()['c']
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
    print(f"合计 {total} 人；本次变更 {len(changes)} 条；旧部门名残留 {left}")
    conn.close()
    if left != 0:
        sys.exit('[FAIL] 仍残留旧部门名，禁止退出为成功')
    print('[OK] 迁移完成')


if __name__ == '__main__':
    main()
