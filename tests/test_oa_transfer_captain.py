"""OA 调岗转钻工 captain id→名字 解析测试。

背景 (2026-09-04 生产事故):
- 调岗表单（桌面 index.html / 移动 mobile.html）value 绑定队长 employee_id，
  apply_approved_event 把 id 原样落库 overrides.captain（生产出现 captain='9'）
- calc_driller_piece 按名字串精确匹配 overrides.captain 与 driller_data 的 captain，
  '9' 永远匹配不上 → 该员工进不了队长池分钱
- 修复: 落库前经 _resolve_driller_captain_name 解析为队长名字（与采集链路
  eid→employees.name 同源）；employees.team_id 保持存队长 employee_id 原语义
"""
import os
import sys
import sqlite3

import pytest

# 让 tests/ 能 import core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    # 队长: employees.id='9' = BARAKA LAIZER；driller_captains.employee_id 也存 '9'
    conn.execute(
        "INSERT INTO employees (id, name, department, status) VALUES (?,?,?,?)",
        ('9', 'BARAKA LAIZER', 'Driller Team', 'active'))
    conn.execute(
        "INSERT INTO employees (id, name, department, status) VALUES (?,?,?,?)",
        ('VICTORTEST', 'Victor Test', 'Crush', 'active'))
    conn.execute(
        "INSERT INTO driller_captains (employee_id, name, sort_order) VALUES (?,?,?)",
        ('9', 'BARAKA LAIZER', 0))
    conn.commit()
    conn.close()
    return data_folder


def _make_transfer_event(captain_val):
    return {
        'id': 1,
        'event_type': 'transfer',
        'employee_id': 'VICTORTEST',
        'effective_date': '2026-09-04',
        'payload': '{"new_department": "Driller Team", "new_position": "Driller", '
                   f'"captain": "{captain_val}"' + '}',
    }


def _make_driller_data(date_str='2026-09-05'):
    return [{
        'date': date_str, 'captain': 'BARAKA LAIZER', 'slot': 0,
        'nh': 10, 'nl': 0, 'mw': 0, 'futa': 0, 'waya': 0, 'kibiriti': 0,
        'members': [], 'slots': [], 'has_members': False,
    }]


def test_captain_id_resolved_to_name_and_pays(tmp_path):
    """payload captain 传 id '9' → 落库名字 'BARAKA LAIZER'，calc_driller_piece 分到钱"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    from core.calculator import calc_driller_piece, make_employee_id

    apply_approved_event(data_folder, _make_transfer_event('9'))

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    ov = conn.execute(
        "SELECT captain FROM overrides WHERE employee_id='VICTORTEST' AND salary_type='piece_driller'"
    ).fetchone()
    team_id = conn.execute(
        "SELECT team_id FROM employees WHERE id='VICTORTEST'").fetchone()['team_id']
    conn.close()

    assert ov is not None
    assert ov['captain'] == 'BARAKA LAIZER', 'overrides.captain 必须落队长名字而非 id'
    assert str(team_id) == '9', 'employees.team_id 保持存队长 employee_id 原语义'

    result, _, _ = calc_driller_piece(_make_driller_data(), data_folder=data_folder)
    assert result.get('VICTORTEST', 0) > 0, '调岗员工应通过 override 注入队长池分到钱'
    cap_key = make_employee_id('BARAKA LAIZER')
    assert result.get(cap_key, 0) > 0, '队长 BARAKA 本身应有份额'


def test_captain_name_passthrough(tmp_path):
    """payload 直接传名字 → 原样落库（向后兼容）"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event

    apply_approved_event(data_folder, _make_transfer_event('BARAKA LAIZER'))

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    ov = conn.execute(
        "SELECT captain FROM overrides WHERE employee_id='VICTORTEST'").fetchone()
    conn.close()
    assert ov['captain'] == 'BARAKA LAIZER'


def test_captain_numeric_drid_fallback(tmp_path):
    """driller_captains.id 数字主键也能解析（员工已删等边缘场景的兜底路径之一）"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event
    from core.calculator import calc_driller_piece

    apply_approved_event(data_folder, _make_transfer_event('1'))

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    ov = conn.execute(
        "SELECT captain FROM overrides WHERE employee_id='VICTORTEST'").fetchone()
    conn.close()
    assert ov['captain'] == 'BARAKA LAIZER'

    result, _, _ = calc_driller_piece(_make_driller_data(), data_folder=data_folder)
    assert result.get('VICTORTEST', 0) > 0


def test_captain_unknown_kept_without_raise(tmp_path):
    """查无此人（防御路径）：不抛异常、按原值落库，主流程不阻塞"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event

    apply_approved_event(data_folder, _make_transfer_event('999'))

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    ov = conn.execute(
        "SELECT captain FROM overrides WHERE employee_id='VICTORTEST'").fetchone()
    team_id = conn.execute(
        "SELECT team_id FROM employees WHERE id='VICTORTEST'").fetchone()['team_id']
    conn.close()
    assert ov['captain'] == '999'
    assert str(team_id) == '999'


def test_underground_transfer_untouched(tmp_path):
    """控制组: 井下调岗 team_id 路径不受本次改动影响"""
    data_folder = _seed_db(tmp_path)
    from core.database import apply_approved_event

    event = {
        'id': 2,
        'event_type': 'transfer',
        'employee_id': 'VICTORTEST',
        'effective_date': '2026-09-04',
        'payload': '{"new_department": "Production TEAM （underground）", '
                   '"new_position": "", "team_id": 3}',
    }
    apply_approved_event(data_folder, event)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    ov = conn.execute(
        "SELECT salary_type, captain FROM overrides WHERE employee_id='VICTORTEST'").fetchone()
    team_id = conn.execute(
        "SELECT team_id FROM employees WHERE id='VICTORTEST'").fetchone()['team_id']
    conn.close()
    assert ov['salary_type'] == 'piece_underground'
    assert ov['captain'] == ''
    assert int(team_id) == 3
