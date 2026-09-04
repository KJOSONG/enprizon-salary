"""overrides 日期区间展开硬上限回归测试。

背景（2026-09-04 生产 OOM 事故）:
- OA 调岗自动转计件写入 end_date='9999-12-31' 永久哨兵 (core/database.py:1669/1675)
- calc_underground_piece / calc_driller_piece 的 `while d <= d_end` 逐日展开无上限
- 单条例外膨胀到 ~291 万天: 实测 calc_driller_piece +932MB / 10.2s CPU
- 服务器 894MB 内存 → OOM killer 循环击杀 worker，系统瘫痪大半天

修复: 两处展开循环 d_end = min(d_end, d + _OVERRIDE_EXPAND_MAX_DAYS=800)

基线失败证明 (修复前运行):
- test_driller_sentinel_end_date_bounded: 修复前 ~2.9M 天展开, 测试实质挂起(超时失败)
- test_underground_sentinel_end_date_bounded: 同上
"""
import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.calculator import _OVERRIDE_EXPAND_MAX_DAYS


def _seed_db(tmp_path):
    """构造临时 data 目录 + kilwa.db, 含 overrides/team_id 列"""
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)

    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(overrides)").fetchall()}
    if 'team_id' not in cols:
        conn.execute("ALTER TABLE overrides ADD COLUMN team_id INTEGER DEFAULT 0")
    conn.commit()
    conn.close()
    return data_folder


def _insert_sentinel_override(data_folder, eid, salary_type, start_date, captain='', team_id=0):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary,"
        " start_date, end_date, note, type, shift, captain, effective_from, team_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, salary_type, 0, 0, start_date, '9999-12-31', '调岗哨兵', '', '', captain, '', team_id),
    )
    conn.commit()
    conn.close()


def test_driller_sentinel_end_date_bounded(tmp_path):
    """钻工例外 end_date='9999-12-31' 时展开必须有界（修复前会展开 291 万天挂起/爆内存）"""
    data_folder = _seed_db(tmp_path)
    # start_date 设为远期 2090-01-01: 若无 clamp, 展开到 9999 年 = 290 万天
    _insert_sentinel_override(data_folder, '100', 'piece_driller', '2090-01-01',
                              captain='CAP A')

    from core.calculator import calc_driller_piece
    driller_data = [{
        'date': '2090-01-01', 'captain': 'CAP A', 'slot': 0,
        'nh': 4, 'nl': 0, 'mw': 0, 'futa': 0, 'waya': 0, 'kibiriti': 0,
        'members': [],
    }]
    result, _, daily = calc_driller_piece(driller_data, data_folder=data_folder)
    # 例外员工应正常进入队长池分钱（哨兵不破坏正常业务语义）
    assert '100' in result, '例外员工应被注入队长池并分得份额'


def test_underground_sentinel_end_date_bounded(tmp_path):
    """井下例外 end_date='9999-12-31' + team_id>0 时展开必须有界"""
    data_folder = _seed_db(tmp_path)
    _insert_sentinel_override(data_folder, '200', 'piece_underground', '2090-01-01',
                              team_id=3)

    from core.calculator import calc_underground_piece
    shift_data = [{
        'date': '2090-01-01',
        'teams': [
            {'team_id': 3, 'prod': {'NICKEL（H）': 10, 'NICKEL（L）': 0, 'MAWE': 0}, 'exempt': False},
        ],
    }]
    # ug_team_members 提供班组花名册（不含员工200, 靠例外注入）
    ug_team_members = {3: ['OTHER1']}
    pricing = {
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
        'underground_mode': 'v2',
    }
    result, daily, shifts = calc_underground_piece(
        shift_data, set(), {'permanent': set()}, data_folder=data_folder,
        mode='v2', pricing=pricing, ug_team_members=ug_team_members)
    assert '200' in result, '例外员工应被注入班组计件池并分得份额'


def test_expand_limit_constant():
    """上限常量须存在且合理（>2 个月, <3 年）"""
    assert 60 <= _OVERRIDE_EXPAND_MAX_DAYS <= 1000


def test_sentinel_expand_covers_beyond_800_days(tmp_path):
    """哨兵展开上界=数据最大日期，突破 start+800 天（修复前 800 天后断薪）"""
    data_folder = _seed_db(tmp_path)
    # start='2025-06-01' + 800 天 = '2027-08-10'；数据日 '2027-09-01' 超出该截断
    _insert_sentinel_override(data_folder, '300', 'piece_driller', '2025-06-01',
                              captain='CAP B')

    from core.calculator import calc_driller_piece
    driller_data = [{
        'date': '2027-09-01', 'captain': 'CAP B', 'slot': 0,
        'nh': 6, 'nl': 0, 'mw': 0, 'futa': 0, 'waya': 0, 'kibiriti': 0,
        'members': [],
    }]
    result, _, _ = calc_driller_piece(driller_data, data_folder=data_folder)
    assert '300' in result, '哨兵例外生效超 800 天后仍应覆盖当前计薪数据日（断薪回归）'


def test_sentinel_with_empty_data_no_expand(tmp_path):
    """哨兵+空数据：不展开不炸，返回空结果"""
    data_folder = _seed_db(tmp_path)
    _insert_sentinel_override(data_folder, '400', 'piece_driller', '2025-06-01',
                              captain='CAP C')

    from core.calculator import calc_driller_piece
    result, _, _ = calc_driller_piece([], data_folder=data_folder)
    assert result == {}
    assert '400' not in result
