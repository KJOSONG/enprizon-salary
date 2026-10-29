"""P55e: 病假补贴豁免（工伤等特殊情况）——sick_subsidy_exempt=1 跳过三证检查。

背景：AMOSI HARUNA(27) 工伤，NIDA/TIN 未录入 → 三证不齐 → 病假补贴 0。
用户批准增加豁免开关（super_admin 档案页切换），豁免后三证检查直接合格。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.calculator import sick_subsidy_eligible, sick_subsidy_eligible_batch


def test_exempt_emp_dict_direct():
    """emp 自带 exempt=1 且三证缺失 → 合格"""
    emp = {'id': '27', 'nida_number': '', 'nssf_number': '48880294', 'tin_number': '',
           'sick_subsidy_exempt': 1}
    assert sick_subsidy_eligible(emp) is True


def test_no_exempt_missing_certs():
    """无豁免且三证缺失 → 不合格（AMOSI 原状态）"""
    emp = {'id': '27', 'nida_number': '', 'nssf_number': '48880294', 'tin_number': ''}
    assert sick_subsidy_eligible(emp) is False


def test_exempt_zero_falls_back_to_certs():
    """exempt=0 时按三证判定"""
    emp = {'id': 'x', 'nida_number': '1', 'nssf_number': '2', 'tin_number': '3',
           'sick_subsidy_exempt': 0}
    assert sick_subsidy_eligible(emp) is True
    emp2 = {'id': 'y', 'nida_number': '', 'nssf_number': '2', 'tin_number': '3',
            'sick_subsidy_exempt': 0}
    assert sick_subsidy_eligible(emp2) is False


def test_batch_exempt():
    emps = [
        {'id': 'a', 'nida_number': '', 'nssf_number': '', 'tin_number': '',
         'sick_subsidy_exempt': 1},
        {'id': 'b', 'nida_number': '', 'nssf_number': '', 'tin_number': ''},
        {'id': 'c', 'nida_number': '1', 'nssf_number': '2', 'tin_number': '3'},
    ]
    r = sick_subsidy_eligible_batch(emps)
    assert r['a'] is True
    assert r['b'] is False
    assert r['c'] is True


def test_batch_db_fallback_exempt(tmp_path):
    """emp 不带三证列 → 回退 DB 补查，DB 中 exempt=1 → 合格"""
    d = tmp_path / 'data'
    d.mkdir()
    import sqlite3
    conn = sqlite3.connect(os.path.join(str(d), 'kilwa.db'))
    conn.execute(
        "CREATE TABLE employees (id TEXT PRIMARY KEY, nida_number TEXT DEFAULT '',"
        " nssf_number TEXT DEFAULT '', tin_number TEXT DEFAULT '',"
        " sick_subsidy_exempt INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO employees (id, sick_subsidy_exempt) VALUES ('27', 1)")
    conn.execute("INSERT INTO employees (id, sick_subsidy_exempt) VALUES ('28', 0)")
    conn.commit()
    conn.close()
    emps = [{'id': '27'}, {'id': '28'}]
    r = sick_subsidy_eligible_batch(emps, data_folder=str(d))
    assert r['27'] is True
    assert r['28'] is False
