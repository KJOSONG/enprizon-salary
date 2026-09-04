"""全局搜索 search_all 离职员工过滤测试（qa F7）。

需求：管理员（super_admin）需能搜到离职员工档案/历史；
editor/viewer 维持排除。默认 include_dismissed=False 保持原行为。
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
    conn.execute("INSERT INTO employees (id, name, department, status) VALUES (?,?,?,?)",
                 ('EMP_ACTIVE', 'Active Emp', 'Crush', 'active'))
    conn.execute("INSERT INTO employees (id, name, department, status) VALUES (?,?,?,?)",
                 ('EMP_GONE', 'Gone Emp', 'Crush', 'dismissed'))
    conn.execute("INSERT OR REPLACE INTO dismissed_employees (employee_id, note, dismissed_at) VALUES (?,?,?)",
                 ('EMP_GONE', 'test', '2026-09-01'))
    conn.commit()
    conn.close()
    return data_folder


def test_search_excludes_dismissed_by_default(tmp_path):
    data_folder = _seed_db(tmp_path)
    from core.database import search_all
    results = search_all(data_folder, 'Gone')
    assert all(r['id'] != 'EMP_GONE' for r in results)


def test_search_includes_dismissed_when_allowed(tmp_path):
    data_folder = _seed_db(tmp_path)
    from core.database import search_all
    results = search_all(data_folder, 'Gone', include_dismissed=True)
    assert any(r['id'] == 'EMP_GONE' for r in results)
