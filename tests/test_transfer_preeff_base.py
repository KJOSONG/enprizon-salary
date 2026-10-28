"""P55d: 当月月中调岗的生效前基数保护——转入计件清零主档时补旧基数区间 override。

背景（2026-10 AMOSI 批次案例）：OA 调岗批准把主档 day_rate/monthly_salary 清零，
生效日之前的当月天数按旧类型计薪却取不到基数 → 生效前工资全丢（25 号月薪 600k、
78/185/186/180/188/194 日薪 10k）。修复：审批时补 [当月1号, 生效日前一天] 的
旧类型旧基数区间 override。
"""
import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    from core.database import init_db
    init_db(str(d))
    conn = sqlite3.connect(os.path.join(str(d), 'kilwa.db'))
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, day_rate, monthly_salary, status)"
        " VALUES (?,?,?,?,?,?,?)",
        ('EMP1', 'Test Employee', 'Mining Department', 'monthly', 0, 600000, 'active'))
    conn.commit()
    conn.close()
    return str(d)


def _transfer_event(eff, extra=''):
    return {
        'id': 900,
        'event_type': 'transfer',
        'employee_id': 'EMP1',
        'status': 'approved',
        'effective_date': eff,
        'payload': '{"new_department": "Production TEAM", "new_position": "member",'
                   ' "team_id": 1, "new_type": "piece_underground", "old_type": "monthly",'
                   ' "old_day_rate": 0, "old_monthly_salary": 600000,'
                   ' "old_department": "Mining Department"' + extra + '}',
    }


def _ovr_rows(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT salary_type, day_rate, monthly_salary, start_date, end_date FROM overrides"
        " WHERE employee_id='EMP1' ORDER BY start_date").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def test_midmonth_transfer_writes_preeff_base_override(tmp_path):
    """月中调岗：补 [当月1号, 生效日前一天] 的旧类型旧基数区间 override"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('2026-10-27'))
    rows = _ovr_rows(data_folder)
    pre = [r for r in rows if r['salary_type'] == 'monthly']
    assert len(pre) == 1, rows
    assert pre[0]['start_date'] == '2026-10-01'
    assert pre[0]['end_date'] == '2026-10-26'
    assert float(pre[0]['monthly_salary']) == 600000.0
    piece = [r for r in rows if r['salary_type'] == 'piece_underground']
    assert len(piece) == 1 and piece[0]['start_date'] == '2026-10-27'


def test_firstday_transfer_skips_preeff_override(tmp_path):
    """生效日为 1 号：区间为空，不写保护 override"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    apply_approved_event(data_folder, _transfer_event('2026-11-01'))
    rows = _ovr_rows(data_folder)
    assert not [r for r in rows if r['salary_type'] == 'monthly']
    assert [r for r in rows if r['salary_type'] == 'piece_underground']


def test_piece_to_piece_no_preeff_override(tmp_path):
    """旧类型为计件（基数 0）：无可保护基数，不写 override"""
    data_folder = _seed_db(tmp_path)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute("UPDATE employees SET default_type='piece_crush', day_rate=0, monthly_salary=0 WHERE id='EMP1'")
    conn.commit()
    conn.close()
    from core.database import apply_approved_event
    ev = _transfer_event('2026-10-27')
    ev['payload'] = ev['payload'].replace('"old_type": "monthly"', '"old_type": "piece_crush"') \
        .replace('"old_monthly_salary": 600000', '"old_monthly_salary": 0')
    apply_approved_event(data_folder, ev)
    rows = _ovr_rows(data_folder)
    assert not [r for r in rows if r['salary_type'] == 'monthly']


def test_perm_override_case_no_duplicate(tmp_path):
    """基数挂永久 override（82 EKON 模式）：永久行天然覆盖生效前天数，不重复补区间"""
    data_folder = _seed_db(tmp_path)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary, start_date, end_date)"
        " VALUES ('EMP1', 'monthly', 0, 450000, '', '')")
    conn.execute("UPDATE employees SET monthly_salary=0 WHERE id='EMP1'")
    conn.commit()
    conn.close()
    from core.database import apply_approved_event
    ev = _transfer_event('2026-10-27')
    ev['payload'] = ev['payload'].replace('"old_monthly_salary": 600000', '"old_monthly_salary": 450000')
    apply_approved_event(data_folder, ev)
    rows = _ovr_rows(data_folder)
    monthly = [r for r in rows if r['salary_type'] == 'monthly']
    # 永久行原样保留（覆盖生效前天数），不新加重复区间
    assert len(monthly) == 1
    assert monthly[0]['end_date'] == ''
    assert float(monthly[0]['monthly_salary']) == 450000.0
