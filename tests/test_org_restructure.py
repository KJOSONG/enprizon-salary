"""2026-11 组织重组回归测试：井下/破碎部门新旧名双名兼容。

背景（docs/ORG_RESTRUCTURE_2026_PLAN.md）：
- DB 值改为 'Production TEAM'（去 "(underground)"）、'Sorting Team'（原 Sort Crush）、
  'Crushing Team'（原 Sort Crush/Crush Piece Rate），新增叶子 'Mining Department'（主管）
- 历史 dept_day_map / 月台账 / 旧事件 payload 仍携带旧名 → 全链路必须双名兼容
- 调入计件部门的自动类型映射必须同时认得新旧名；'Sorting Team' 不得误判为破碎计件
"""
import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, status) VALUES (?,?,?,?,?)",
        ('EMP1', 'Test Employee', 'Logistics', 'day_rate', 'active'))
    conn.commit()
    conn.close()
    return data_folder


def _transfer_event(new_dept, extra=''):
    return {
        'id': 1,
        'event_type': 'transfer',
        'employee_id': 'EMP1',
        'effective_date': '2026-11-01',
        'payload': '{"new_department": "%s", "new_position": ""%s}' % (new_dept, extra),
    }


def _emp_row(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    emp = conn.execute("SELECT * FROM employees WHERE id='EMP1'").fetchone()
    conn.close()
    return emp


def _override_types(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT salary_type FROM overrides WHERE employee_id='EMP1'").fetchall()
    conn.close()
    return [r['salary_type'] for r in rows]


# ── 调岗自动映射：新名 ──────────────────────────────────────

def test_transfer_new_ug_name_auto_piece(tmp_path):
    """调入 'Production TEAM'（新名）→ 自动 piece_underground + 必须带班组"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('Production TEAM', ', "team_id": 2'))
    emp = _emp_row(data_folder)
    assert emp['department'] == 'Production TEAM'
    assert emp['default_type'] == 'piece_underground'
    assert int(emp['team_id']) == 2
    assert 'piece_underground' in _override_types(data_folder)


def test_transfer_old_ug_name_still_auto_piece(tmp_path):
    """调入旧名 'Production TEAM （underground）'（历史事件兼容）→ 行为不变"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('Production TEAM （underground）', ', "team_id": 3'))
    emp = _emp_row(data_folder)
    assert emp['default_type'] == 'piece_underground'
    assert int(emp['team_id']) == 3


def test_transfer_new_crush_name_auto_piece(tmp_path):
    """调入 'Crushing Team'（新名）→ 自动 piece_crush，无需班组"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('Crushing Team'))
    emp = _emp_row(data_folder)
    assert emp['department'] == 'Crushing Team'
    assert emp['default_type'] == 'piece_crush'
    assert 'piece_crush' in _override_types(data_folder)


def test_transfer_old_crush_name_still_auto_piece(tmp_path):
    """调入旧名 'Sort Crush/Crush Piece Rate'（历史事件兼容）→ 行为不变"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('Sort Crush/Crush Piece Rate'))
    emp = _emp_row(data_folder)
    assert emp['default_type'] == 'piece_crush'


def test_transfer_sorting_team_not_crush(tmp_path):
    """调入 'Sorting Team'（分拣，非计件部门）→ 不自动切计件，保持原类型"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('Sorting Team'))
    emp = _emp_row(data_folder)
    assert emp['department'] == 'Sorting Team'
    assert emp['default_type'] == 'day_rate'
    assert _override_types(data_folder) == []


def test_transfer_mining_department_no_auto_piece(tmp_path):
    """调入 'Mining Department'（主管叶子，非计件目标）→ 不自动切计件"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('Mining Department'))
    emp = _emp_row(data_folder)
    assert emp['department'] == 'Mining Department'
    assert emp['default_type'] == 'day_rate'
    assert _override_types(data_folder) == []
    assert int(emp['team_id']) == 0


# ── calculator 井下判定双名兼容 ────────────────────────────

def test_calculator_is_ug_dual_name():
    from core.calculator import is_ug_production_emp
    assert is_ug_production_emp({'department': 'Production TEAM'})
    assert is_ug_production_emp({'department': 'Production TEAM （underground）'})
    assert is_ug_production_emp({'department': 'production team'})  # 大小写/空格规范化
    assert not is_ug_production_emp({'department': 'Mining Department'})
    assert not is_ug_production_emp({'department': 'Logistics'})


def test_calculator_ug_dept_set_contents():
    from core.calculator import _UG_DEPT_SET
    assert 'PRODUCTIONTEAM' in _UG_DEPT_SET
    assert 'PRODUCTIONTEAM(UNDERGROUND)' in _UG_DEPT_SET


# ── 员工编辑班组门控（database.update_employee_fields） ─────

def test_team_gate_new_ug_name_allows_team(tmp_path):
    data_folder = _seed_db(tmp_path)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute("UPDATE employees SET department='Production TEAM' WHERE id='EMP1'")
    conn.commit(); conn.close()
    from core.database import update_employee_fields
    update_employee_fields(data_folder, 'EMP1', {'team_id': 4})
    assert int(_emp_row(data_folder)['team_id']) == 4


def test_team_gate_non_team_dept_forces_zero(tmp_path):
    """'Mining Department' 主管不得挂班组 → team_id 强制归 0"""
    data_folder = _seed_db(tmp_path)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute("UPDATE employees SET department='Mining Department', team_id=2 WHERE id='EMP1'")
    conn.commit(); conn.close()
    from core.database import update_employee_fields
    update_employee_fields(data_folder, 'EMP1', {'team_id': 2})
    assert int(_emp_row(data_folder)['team_id']) == 0
