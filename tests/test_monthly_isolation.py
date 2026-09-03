"""月度隔离：员工部门/薪资基线台账（employee_base_history）行为测试。

验证：
- record_base_change 建立旧基线 + 新基线，永不改写旧条目
- resolve_base_for_month 按 from_month 解析（过去=旧基线，当前/未来=新基线）
- 直接改部门/薪资默认生效当月 → 过去月份不受影响
"""
import os, shutil, sqlite3

import pytest


def _seed_emp(tmp_path, eid='1'):
    """在临时 data 目录里造一个最小 employees 行 + monthly_data，返回 data_folder"""
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)

    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.database import init_db
    init_db(data_folder)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO employee_events (employee_id,event_type,effective_date,operator_id,status,payload,snapshot)"
        " VALUES (?,'hire',?,'system','approved','{}','{}')", (eid, '2026-03-15'))
    conn.execute(
        "INSERT INTO employees (id,name,department,default_type,day_rate,monthly_salary,team_id,status)"
        " VALUES (?,?,?,?,?,?,?,?)", (eid, 'TEST', 'Logistics', 'day_rate', 5000, 0, 0, 'active'))
    conn.execute("INSERT INTO monthly_data (month,employee_id,gross) VALUES ('2026-04',? ,0)", (eid,))
    conn.commit()
    conn.close()
    return data_folder


def test_record_and_resolve_isolation(tmp_path):
    from core.database import record_base_change, resolve_base_for_month, load_base_history

    eid = '1'
    data_folder = _seed_emp(tmp_path, eid)

    # 首次直改薪资（生效当月 2026-09）：应建立【旧基线】+【新基线】
    record_base_change(data_folder, eid, '2026-09',
                       new={'default_type': 'monthly', 'day_rate': 0, 'monthly_salary': 1000000},
                       operator_id='KEJU', note='直改薪资')

    hist = load_base_history(data_folder, eid)
    assert len(hist) == 2, '应建立 2 条台账（旧基线 + 新基线）'
    old_entry = next(h for h in hist if h['from_month'] != '2026-09')
    # 旧基线保留原值
    assert old_entry['department'] == 'Logistics'
    assert old_entry['default_type'] == 'day_rate'

    # 过去月份解析到旧基线，当前/未来解析到新基线
    aug = resolve_base_for_month(data_folder, eid, '2026-08')
    assert aug is not None and aug['default_type'] == 'day_rate' and aug['monthly_salary'] == 0
    sep = resolve_base_for_month(data_folder, eid, '2026-09')
    assert sep['default_type'] == 'monthly' and sep['monthly_salary'] == 1000000


def test_direct_dept_change_does_not_leak_to_past(tmp_path):
    from core.database import record_base_change, resolve_base_for_month

    eid = '1'
    data_folder = _seed_emp(tmp_path, eid)

    def _set_main(fields):
        conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
        conn.execute(
            "UPDATE employees SET department=?, default_type=?, day_rate=?, monthly_salary=? WHERE id=?",
            (fields.get('department', 'Logistics'), fields.get('default_type', 'day_rate'),
             fields.get('day_rate', 5000), fields.get('monthly_salary', 0), eid))
        conn.commit()
        conn.close()

    # 直改部门生效当月（模拟 api_employee_update：先记台账[读旧主档]，再写主档）
    record_base_change(data_folder, eid, '2026-09',
                       new={'department': 'Mechanic Tean'}, operator_id='KEJU', note='直改部门')
    _set_main({'department': 'Mechanic Tean'})
    # 直改薪资生效当月（模拟 api_employee_salary_type：先记台账[读当前主档]，再写主档）
    record_base_change(data_folder, eid, '2026-09',
                       new={'default_type': 'monthly', 'monthly_salary': 1000000}, operator_id='KEJU', note='直改薪资')
    _set_main({'department': 'Mechanic Tean', 'default_type': 'monthly', 'day_rate': 0, 'monthly_salary': 1000000})

    # 生效月之前不受新部门/新薪资影响
    aug = resolve_base_for_month(data_folder, eid, '2026-08')
    assert aug['department'] == 'Logistics' and aug['default_type'] == 'day_rate'
    # 生效月及之后为新
    sep = resolve_base_for_month(data_folder, eid, '2026-09')
    assert sep['department'] == 'Mechanic Tean' and sep['default_type'] == 'monthly'
    # 未来照旧沿用最新
    oct_ = resolve_base_for_month(data_folder, eid, '2026-10')
    assert oct_['department'] == 'Mechanic Tean' and oct_['monthly_salary'] == 1000000


def test_resolve_returns_none_without_any_history(tmp_path):
    from core.database import resolve_base_for_month

    eid = '1'
    data_folder = _seed_emp(tmp_path, eid)
    # 尚无台账 → 返回 None（调用方回退当前 employees 主档）
    assert resolve_base_for_month(data_folder, eid, '2026-08') is None