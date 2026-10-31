"""薪资总表部门口径修复回归测试（2026-10-31）。

背景：部门重整（org-restructure-2026-11）只校正了 2026-11 基线，10 月基线仍在旧部门。
薪资总表此前按"主档当前部门"筛选（_empAll），与逐日明细/实际计薪的"当月基线部门"不一致
（实测 Crushing Team 总表 11 人 vs 明细 6 人，且混入旧部门的 day_rate/monthly 行）。

修复：calculate_all 薪资行新增 department 字段（= 当月基线部门，与 compute_daily_breakdown
同源）；前端筛选/下拉优先用行内 department。

主档部门 ≠ 当月基线部门时，薪资行 department 必须取基线（与日明细一致），而非主档。
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
    # 主档已是新部门 Crushing Team，但 2026-10 基线台账仍是旧部门 Sort Crush
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, status)"
        " VALUES ('EMP1', 'EMP1', 'Crushing Team', 'day_rate', 'active')")
    conn.execute(
        "INSERT INTO employee_base_history"
        " (employee_id, from_month, department, default_type, day_rate, monthly_salary,"
        "  team_id, note, operator_id)"
        " VALUES ('EMP1', '2026-10', 'Sort Crush', 'monthly', 0, 400000, 0, 'test', 'tester')")
    conn.commit()
    conn.close()
    return data_folder


@pytest.fixture()
def app_ctx(tmp_path):
    data_folder = _seed_db(tmp_path)
    import app as appmod
    old = appmod.app.config.get('DATA_FOLDER')
    appmod.app.config['DATA_FOLDER'] = data_folder
    yield appmod, data_folder
    if old is not None:
        appmod.app.config['DATA_FOLDER'] = old
    from core.namematch import _AB_INDEX
    _AB_INDEX.clear()


def _empty_md():
    return {'shift_production': [], 'driller_production': [], 'attendance': [],
            'crush_production': [], 'dates': []}


def test_salary_row_uses_month_baseline_department(app_ctx):
    """薪资行 department = 当月基线部门（Sort Crush），不是主档当前部门"""
    appmod, data_folder = app_ctx
    emps = appmod._resolve_base_from_history(
        appmod.load_employees_from_db(data_folder), '2026-10')
    assert emps[0]['department'] == 'Sort Crush'
    from core.calculator import calculate_all
    res = calculate_all(
        _empty_md(), emps, overrides={}, exclusions=set(), pricing={},
        data_folder=data_folder, bonus_penalties={})
    row = next(r for r in res['employees'] if r['employee_id'] == 'EMP1')
    assert row['department'] == 'Sort Crush'


def test_salary_row_department_matches_daily_breakdown(app_ctx):
    """薪资行与逐日明细的 department 同源同值（同月同员工）"""
    appmod, data_folder = app_ctx
    from core.calculator import compute_daily_breakdown, calculate_all
    emps = appmod._resolve_base_from_history(
        appmod.load_employees_from_db(data_folder), '2026-10')
    # 有出勤才有日明细行（compute_daily_breakdown 零条目员工不出行）
    md = _empty_md()
    md['dates'] = ['2026-10-05']
    md['attendance'] = [{'date': '2026-10-05', 'normal': ['EMP1']}]
    res = calculate_all(
        md, emps, overrides={}, exclusions=set(), pricing={},
        data_folder=data_folder, bonus_penalties={})
    daily = compute_daily_breakdown(
        md, emps, overrides={}, exclusions=set(), pricing={},
        data_folder=data_folder)
    row = next(r for r in res['employees'] if r['employee_id'] == 'EMP1')
    assert row['department'] == daily['EMP1']['department'] == 'Sort Crush'


def test_salary_row_department_fallback_current_dept(app_ctx):
    """无基线台账的员工 → 行 department = 主档部门（原行为不回归）"""
    appmod, data_folder = app_ctx
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, status)"
        " VALUES ('EMP2', 'No History', 'Mining Department', 'day_rate', 'active')")
    conn.commit()
    conn.close()
    emps = appmod._resolve_base_from_history(
        appmod.load_employees_from_db(data_folder), '2026-10')
    from core.calculator import calculate_all
    res = calculate_all(
        _empty_md(), emps, overrides={}, exclusions=set(), pricing={},
        data_folder=data_folder, bonus_penalties={})
    row = next(r for r in res['employees'] if r['employee_id'] == 'EMP2')
    assert row['department'] == 'Mining Department'
