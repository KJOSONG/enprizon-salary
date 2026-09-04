"""井下计件 V2 路径临时例外（piece_underground + team_id）注入测试。

背景:
- LOWASA SOINGE MOLLEL 已从井下 Production TEAM 调入 Sort Crush (team_id=0, 不在任何班组花名册)
- 9-03 他在井下 MIZOZO (team_id=3) 出勤, 需用临时例外 piece_underground + team_id=3 覆盖
- V2 路径原本只用 _roster + _p_pairs, 不读 shift_adds (临时例外), 导致该员工无法进入计件池

基线失败证明 (修复前运行):
- test_v2_temp_exception_injects_into_pool: FAILED (assert '999' in {}) — V2 不读例外
- test_v2_temp_exception_acts_as_p_attendance: FAILED (assert '888' in {}) — 例外未视同 P
- test_v2_no_exception_control: PASSED (无例外时员工不计薪, 控制组)
- test_v2_temp_exception_team_id_zero_skipped: PASSED (team_id=0 跳过)
"""
import os
import sys
import sqlite3

import pytest

# 让 tests/ 能 import core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(tmp_path):
    """构造临时 data 目录 + kilwa.db, 含 overrides/team_id 列"""
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    # 兼容: 若 init_db 未含 team_id 列则补 (与并行 agent 对接)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(overrides)").fetchall()}
    if 'team_id' not in cols:
        conn.execute("ALTER TABLE overrides ADD COLUMN team_id INTEGER DEFAULT 0")
    conn.commit()
    conn.close()
    return data_folder


def _make_shift_data(date_str='2026-09-03', team_id=3, prod=None):
    """构造 V2 新格式 teams 维度的 shift_data 单日记录"""
    prod = prod or {'NICKEL（H）': 10, 'NICKEL（L）': 0, 'MAWE': 0}
    return [{
        'date': date_str,
        'teams': [
            {'team_id': team_id, 'prod': prod, 'exempt': False},
        ],
    }]


def _insert_p(conn, eid, date_str):
    conn.execute(
        "INSERT OR REPLACE INTO attendance_overrides (employee_id, date, status) VALUES (?,?,?)",
        (eid, date_str, 'P'),
    )


def test_v2_no_exception_control(tmp_path):
    """控制组: 无例外时, 不在 roster 的员工不计薪 (修复前后均成立)"""
    data_folder = _seed_db(tmp_path)

    from core.calculator import calc_underground_piece

    shift_data = _make_shift_data('2026-09-03', team_id=3,
                                  prod={'NICKEL（H）': 10, 'NICKEL（L）': 0, 'MAWE': 0})
    pricing = {
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
    }
    # 班组 3 花名册只含 EXISTING_EMP (有 P); eid=999 不在 roster, 无例外 → 不计薪
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    _insert_p(conn, 'EXISTING_EMP', '2026-09-03')
    conn.commit()
    conn.close()

    ug_team_members = {3: ['EXISTING_EMP']}

    result, _, _ = calc_underground_piece(
        shift_data, exclusions=set(), override_excludes={'permanent': set()},
        data_folder=data_folder, all_attendance_pairs=None,
        mode='v2', pricing=pricing, ug_team_members=ug_team_members,
    )

    assert '999' not in result, '无例外时 eid=999 不应计薪'
    assert 'EXISTING_EMP' in result, 'EXISTING_EMP 有 P 应计薪'


def test_v2_temp_exception_injects_into_pool(tmp_path):
    """修复后: piece_underground 例外 (team_id=3) 把员工注入 MIZOZO 计件池,
    且视同 P 出勤. 该员工应计薪 = 当日池均分."""
    data_folder = _seed_db(tmp_path)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    # 临时例外: eid=999, team_id=3 (MIZOZO), 9-03, shift=D
    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, start_date, end_date, shift, team_id)"
        " VALUES (?,?,?,  ?,?,?)",
        ('999', 'piece_underground', '2026-09-03', '2026-09-03', 'D', 3),
    )
    # EXISTING_EMP 有 P, 与 999 (例外视同 P) 一起均分
    _insert_p(conn, 'EXISTING_EMP', '2026-09-03')
    conn.commit()
    conn.close()

    from core.calculator import calc_underground_piece

    shift_data = _make_shift_data('2026-09-03', team_id=3,
                                  prod={'NICKEL（H）': 10, 'NICKEL（L）': 0, 'MAWE': 0})
    pricing = {
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
    }
    # 班组 3 花名册只含 EXISTING_EMP; eid=999 不在 roster, 靠例外注入
    ug_team_members = {3: ['EXISTING_EMP']}

    result, daily, _ = calc_underground_piece(
        shift_data, exclusions=set(), override_excludes={'permanent': set()},
        data_folder=data_folder, all_attendance_pairs=None,
        mode='v2', pricing=pricing, ug_team_members=ug_team_members,
    )

    # 修复后: eid=999 应进入班组 3 的计件池并参与均分
    assert '999' in result, '修复后 eid=999 应通过 piece_underground 例外注入计件池'
    # 班组当日池: 10 * 8000 * (10/40) = 20000; 均分给 EXISTING_EMP + 999 = 2 人 = 10000/人
    expected_per = 10000.0
    assert abs(result['999'] - expected_per) < 0.01, (
        f'eid=999 应分得 {expected_per}, 实际 {result.get("999")}'
    )
    assert abs(result.get('EXISTING_EMP', 0) - expected_per) < 0.01, (
        f'EXISTING_EMP 应分得 {expected_per}, 实际 {result.get("EXISTING_EMP")}'
    )


def test_v2_temp_exception_team_id_zero_skipped(tmp_path):
    """team_id=0 的例外无法定位班组 → 跳过, 不注入任何池"""
    data_folder = _seed_db(tmp_path)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, start_date, end_date, shift, team_id)"
        " VALUES (?,?,?,  ?,?,?)",
        ('999', 'piece_underground', '2026-09-03', '2026-09-03', 'D', 0),
    )
    _insert_p(conn, 'EXISTING_EMP', '2026-09-03')
    conn.commit()
    conn.close()

    from core.calculator import calc_underground_piece

    shift_data = _make_shift_data('2026-09-03', team_id=3,
                                  prod={'NICKEL（H）': 10, 'NICKEL（L）': 0, 'MAWE': 0})
    pricing = {
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
    }
    ug_team_members = {3: ['EXISTING_EMP']}

    result, _, _ = calc_underground_piece(
        shift_data, exclusions=set(), override_excludes={'permanent': set()},
        data_folder=data_folder, all_attendance_pairs=None,
        mode='v2', pricing=pricing, ug_team_members=ug_team_members,
    )

    assert '999' not in result, 'team_id=0 例外应被跳过, 不注入任何班组池'


def test_v2_temp_exception_acts_as_p_attendance(tmp_path):
    """例外视同 P 出勤: 即使 attendance_overrides 没有该员工当日 P,
    例外 (employee_id, date) 也应进入 _p_pairs, 通过 V2 P 筛选"""
    data_folder = _seed_db(tmp_path)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    # eid=888 例外: team_id=3, 9-03 (888 已在 roster, 但无 P → 靠例外视同 P)
    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, start_date, end_date, shift, team_id)"
        " VALUES (?,?,?,  ?,?,?)",
        ('888', 'piece_underground', '2026-09-03', '2026-09-03', 'D', 3),
    )
    # 不写 attendance_overrides P (验证例外自动视同 P)
    conn.commit()
    conn.close()

    from core.calculator import calc_underground_piece

    shift_data = _make_shift_data('2026-09-03', team_id=3,
                                  prod={'NICKEL（H）': 8, 'NICKEL（L）': 0, 'MAWE': 0})
    pricing = {
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
    }
    # 班组 3 花名册含 eid=888 (员工已在 roster), 但无 P 出勤 → 靠例外视同 P 计薪
    ug_team_members = {3: ['888']}

    result, _, _ = calc_underground_piece(
        shift_data, exclusions=set(), override_excludes={'permanent': set()},
        data_folder=data_folder, all_attendance_pairs=None,
        mode='v2', pricing=pricing, ug_team_members=ug_team_members,
    )

    # 修复后: 例外视同 P, 888 应计薪
    # 池: 8*8000*(8/40)=12800; 1 人均分 = 12800
    assert '888' in result, '例外视同 P 出勤后, 888 应计薪'
    expected = 12800.0
    assert abs(result['888'] - expected) < 0.01, (
        f'888 应分得 {expected}, 实际 {result.get("888")}'
    )
