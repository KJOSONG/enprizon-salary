"""2026-10-26 OA 调薪申请（salary_change）回归测试。

背景（.codebuddy/specs/oa-salary-change/00-plan.md）：
- apply_approved_event 新增 salary_change 分支：主档更新 + 月度基线台账 + 清遗留永久覆盖
- 生效日期语义（防历史回溯）：
  * eff=1 号 → 基线台账 from_month=生效月，整月新值
  * eff 为月中 → 基线台账 from_month=次月，生效月由事件推导 override（start=eff，日粒度）接管
  * 生效月早于当前月 → RuntimeError（历史月永不回溯）
- 事件推导 override：仅生效月及以后生成，start=eff（既有逻辑，回归验证）
"""
import os
import sys
import sqlite3
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(tmp_path, day_rate=10000, monthly_salary=0, default_type='day_rate'):
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, day_rate, monthly_salary, status)"
        " VALUES (?,?,?,?,?,?,?)",
        ('EMP1', 'Test Employee', 'Logistics', default_type, day_rate, monthly_salary, 'active'))
    conn.commit()
    conn.close()
    return data_folder


def _next_month_first():
    """下个月 1 号（保证 ≥ 当前月，且未来可重跑）"""
    n = datetime.now()
    y, m = (n.year + (n.month // 12), (n.month % 12) + 1)
    return f'{y:04d}-{m:02d}-01'


def _mid_next_month():
    """下个月 15 号（月中生效用例）"""
    return _next_month_first()[:8] + '15'


def _sal_event(eff, salary_type='monthly', day_rate=0, monthly_salary=500000):
    return {
        'id': 1,
        'event_type': 'salary_change',
        'employee_id': 'EMP1',
        'effective_date': eff,
        'payload': '{"salary_type": "%s", "day_rate": %d, "monthly_salary": %d}' % (
            salary_type, day_rate, monthly_salary),
    }


def _emp_row(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    emp = conn.execute("SELECT * FROM employees WHERE id='EMP1'").fetchone()
    conn.close()
    return emp


def _base_history(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM employee_base_history WHERE employee_id='EMP1' ORDER BY from_month").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _override_rows(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM overrides WHERE employee_id='EMP1'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 审批落库 ──────────────────────────────────────────────

def test_salary_change_day1_base_from_eff_month(tmp_path):
    """eff=1 号 → 主档新值；基线台账 from_month=生效月；无遗留永久覆盖"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    eff = _next_month_first()
    apply_approved_event(data_folder, _sal_event(eff))
    emp = _emp_row(data_folder)
    assert emp['default_type'] == 'monthly'
    assert int(emp['monthly_salary']) == 500000
    hist = _base_history(data_folder)
    assert len(hist) == 2
    assert hist[-1]['from_month'] == eff[:7]
    assert hist[-1]['default_type'] == 'monthly'
    assert int(hist[-1]['monthly_salary']) == 500000
    # 旧基线（首条）保留旧值
    assert hist[0]['default_type'] == 'day_rate'
    assert int(hist[0]['day_rate']) == 10000
    assert _override_rows(data_folder) == []


def test_salary_change_mid_month_base_from_next_month(tmp_path):
    """eff 为月中 → 基线台账 from_month=次月（生效月由事件 override 日粒度接管）"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    eff = _mid_next_month()
    apply_approved_event(data_folder, _sal_event(eff))
    emp = _emp_row(data_folder)
    assert emp['default_type'] == 'monthly'
    hist = _base_history(data_folder)
    assert len(hist) == 2
    nm_y, nm_m = (int(eff[:4]) + (int(eff[5:7]) // 12), (int(eff[5:7]) % 12) + 1)
    assert hist[-1]['from_month'] == f'{nm_y:04d}-{nm_m:02d}'
    # 生效月不落新基线（eff 前的天数必须命中旧基线）
    assert hist[-1]['from_month'] != eff[:7]


def test_salary_change_clears_permanent_overrides(tmp_path):
    """遗留永久 override 被清（P26 HALIMA 先例：避免 override_type 掩盖新主档）"""
    data_folder = _seed_db(tmp_path)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, day_rate, start_date, end_date)"
        " VALUES ('EMP1', 'day_rate', 9999, '', '')")
    conn.commit()
    conn.close()
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _sal_event(_next_month_first()))
    assert _override_rows(data_folder) == []
    assert _emp_row(data_folder)['default_type'] == 'monthly'


def test_salary_change_past_month_rejected(tmp_path):
    """生效月早于当前月 → RuntimeError（历史月永不回溯）"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    old_eff = '2020-01-01'
    with pytest.raises(RuntimeError):
        apply_approved_event(data_folder, _sal_event(old_eff))
    emp = _emp_row(data_folder)
    assert emp['default_type'] == 'day_rate'
    assert int(emp['day_rate']) == 10000


def test_salary_change_invalid_base_rejected(tmp_path):
    """monthly 但基数为 0 → RuntimeError"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    with pytest.raises(RuntimeError):
        apply_approved_event(data_folder, _sal_event(_next_month_first(), monthly_salary=0))
    with pytest.raises(RuntimeError):
        apply_approved_event(data_folder, _sal_event(_next_month_first(), salary_type='bad_type'))


# ── 事件 → override 推导（app.py，月度语义回归） ──────────

def test_derive_overrides_salary_change_month_scope(tmp_path):
    """生效月生成 start=eff 的临时覆盖；生效月之前的月份不生成"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    eff = _next_month_first()
    apply_approved_event(data_folder, _sal_event(eff))
    # 事件行落库（真实流程中由 OA 创建、批准置 approved）
    import json as _json
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO employee_events (id, employee_id, event_type, effective_date, payload, operator_id, status)"
        " VALUES (1, 'EMP1', 'salary_change', ?, ?, 'tester', 'approved')",
        (eff, _json.dumps({'salary_type': 'monthly', 'day_rate': 0, 'monthly_salary': 500000})))
    conn.commit()
    conn.close()
    import app as appmod
    prev_y, prev_m = (int(eff[:4]) - (1 if eff[5:7] == '01' else 0),
                      12 if eff[5:7] == '01' else int(eff[5:7]) - 1)
    prev_month = f'{prev_y:04d}-{prev_m:02d}'
    assert appmod._derive_overrides_from_events(data_folder, prev_month) == {}
    cur = appmod._derive_overrides_from_events(data_folder, eff[:7])
    items = cur.get('EMP1') or []
    assert len(items) == 1
    assert items[0]['start_date'] == eff
    assert items[0]['end_date'].startswith(eff[:7])
    assert items[0]['salary_type'] == 'monthly'
    # 还原 import app 的副作用：app 启动会从本地库构建 namematch 全局索引 _AB_INDEX，
    # 不清空会让 init_db 的队长种子经 make_employee_id 解析出数字 id（如 '9'），
    # 与 test_oa_transfer_captain 等后续用例的种子数据 UNIQUE 冲突
    from core.namematch import _AB_INDEX
    _AB_INDEX.clear()
