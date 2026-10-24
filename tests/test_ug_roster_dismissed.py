"""离职成员不得出现在 UG 班组花名册（_build_ug_team_members）回归测试。

2026-10-25 用户裁决：已离职成员不应出现在现有花名册中。
语义：month 月之前（dismissed_at 月份 < month）离职者剔除；离职当月及历史月保留
（当月可能仍有其出勤标记，保历史重算逐分不变）；month=None（全量口径）一并剔除。
"""
import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope='module')
def appmod():
    import app as app_module
    return app_module


def _seed(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    # 在职井下工（班组 1）
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, team_id, status) "
        "VALUES ('100','ACTIVE UG','Production TEAM （underground）','piece_underground',1,'active')")
    # 离职井下工：上月离职（班组 1）
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, team_id, status, dismissed_at) "
        "VALUES ('200','GONE LAST MONTH','Production TEAM （underground）','piece_underground',1,'dismissed','2026-10-01')")
    # 离职井下工：本月离职（班组 2）
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, team_id, status, dismissed_at) "
        "VALUES ('300','GONE THIS MONTH','Production TEAM （underground）','piece_underground',2,'dismissed','2026-11-05')")
    conn.commit()
    conn.close()
    return data_folder


def test_dismissed_excluded_from_following_months(appmod, tmp_path):
    """上月离职者不得出现在 11 月花名册；本月离职者保留（当月仍可能有标记）"""
    data_folder = _seed(tmp_path)
    m = appmod._build_ug_team_members(data_folder, month='2026-11')
    assert '100' in m.get(1, []), '在职成员必须在'
    assert '200' not in m.get(1, []), '上月离职者必须剔除'
    assert '300' in m.get(2, []), '本月离职者保留（历史重算口径不变）'


def test_dismissed_kept_in_dismissal_and_prior_months(appmod, tmp_path):
    """历史月（离职当月/之前）保留——保 8/9/10 月重算零差异"""
    data_folder = _seed(tmp_path)
    m_oct = appmod._build_ug_team_members(data_folder, month='2026-10')
    assert '200' in m_oct.get(1, []), '10 月（离职当月）必须保留'
    assert '300' in m_oct.get(2, []), '未离职者必须保留'


def test_dismissed_excluded_when_month_none(appmod, tmp_path):
    """month=None（全量口径）剔除全部离职者"""
    data_folder = _seed(tmp_path)
    m = appmod._build_ug_team_members(data_folder, month=None)
    assert '100' in m.get(1, [])
    assert '200' not in m.get(1, [])
    assert '300' not in m.get(2, [])
