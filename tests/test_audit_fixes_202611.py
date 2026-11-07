"""audit-fixes-202611 批次B 回归测试（2026-11-07）。

覆盖 4 项审计修复：
- #6 collection_edit 改期到已关账月 → 409
- #7 oa_edit_event 改期到关账月 / 延长天数跨入关账月 → 409；days>365 → 400 且零写入；
  edit_approved_event 数据库层兜底拒绝 >366
- #8 api_employee_update 部门/班组直改 guard 月份改 effective_month 口径；
  api_employee_salary_type 事件 effective_date == from_month+'-01'，且 >=from_month
  的缓存键被 _invalidate_month_cache_from 驱逐
"""
import os
import sys
import json
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_db(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    from core.database import init_db
    data_folder = str(d)
    init_db(data_folder)
    db = os.path.join(data_folder, 'kilwa.db')
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO employees (id, name, department, default_type, status)"
        " VALUES ('1', 'Test Emp', 'Mining Department', 'day_rate', 'active')")
    # 测试账号（super_admin 全权限硬编码，无需 grant 行）
    try:
        conn.execute(
            "INSERT INTO admin_users (username, password_hash, salt, role)"
            " VALUES ('tc', 'x', 's', 'super_admin')")
    except sqlite3.OperationalError:
        conn.execute(
            "INSERT INTO admin_users (username, password_hash, role)"
            " VALUES ('tc', 'x', 'super_admin')")
    conn.commit()
    conn.close()
    # collection_submissions.team_id 懒迁移列（init_db 未建，消费端 _ensure 兜底；测试直补）
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(collection_submissions)").fetchall()]
    if 'team_id' not in cols:
        conn.execute("ALTER TABLE collection_submissions ADD COLUMN team_id TEXT DEFAULT ''")
        conn.commit()
    conn.close()
    return data_folder


@pytest.fixture()
def ctx(tmp_path):
    data_folder = _seed_db(tmp_path)
    import app as appmod
    old = appmod.app.config.get('DATA_FOLDER')
    appmod.app.config['DATA_FOLDER'] = data_folder
    client = appmod.app.test_client()
    with client.session_transaction() as s:
        s['logged_in'] = True
        s['username'] = 'tc'
        s['role'] = 'super_admin'
    yield appmod, data_folder, client
    if old is not None:
        appmod.app.config['DATA_FOLDER'] = old
    from core.namematch import _AB_INDEX
    _AB_INDEX.clear()


def _close(ctx, month, closed=True):
    appmod, data_folder, client = ctx
    from core.database import set_month_closed
    set_month_closed(data_folder, month, closed, 'tc')


def _insert_event(data_folder, event_type, eff_date, payload, status='pending'):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    cur = conn.execute(
        "INSERT INTO employee_events (employee_id, event_type, effective_date, snapshot,"
        " payload, operator_id, status) VALUES ('1',?,?,?,?,?,?)",
        (event_type, eff_date, '{}', json.dumps(payload), 'tc', status))
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def _insert_submission(data_folder, form_type, date, payload):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    cur = conn.execute(
        "INSERT INTO collection_submissions (form_type, submission_date, payload,"
        " operator_id, month) VALUES (?,?,?,?,?)",
        (form_type, date, json.dumps(payload), 'tc', date[:7]))
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def _att_override_count(data_folder):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    n = conn.execute("SELECT COUNT(*) FROM attendance_overrides").fetchone()[0]
    conn.close()
    return n


# ── #6 采集编辑改期关账闸门 ──────────────────────

def test_collection_edit_to_closed_month_409(ctx):
    appmod, data_folder, client = ctx
    sid = _insert_submission(data_folder, 'attendance', '2026-11-05', {'marks': []})
    _close(ctx, '2026-10')
    # 原日期（11 月未关账）过关账闸门，走到业务层
    r = client.post('/api/collection/edit/%d' % sid,
                    json={'payload': {'marks': []}})
    assert r.status_code != 409
    # 改期到已关账月 → 409（新日期 guard，审计修复#6）
    r = client.post('/api/collection/edit/%d' % sid,
                    json={'payload': {'marks': []}, 'submission_date': '2026-10-20'})
    assert r.status_code == 409 and r.get_json()['error'] == 'month_closed'


# ── #7 OA 事件编辑关账闸门 + days 上限 ────────────

def test_oa_edit_reschedule_to_closed_month_409(ctx):
    _, data_folder, client = ctx
    eid = _insert_event(data_folder, 'annual_leave', '2026-11-05', {'days': 2})
    _close(ctx, '2026-10')
    r = client.post('/api/oa/events/%d/edit' % eid,
                    json={'effective_date': '2026-10-20', 'days': 2})
    assert r.status_code == 409 and r.get_json()['error'] == 'month_closed'


def test_oa_edit_extend_days_into_closed_month_409(ctx):
    _, data_folder, client = ctx
    # 原事件 11-28 起 3 天（不涉关账月），延长到 10 天跨入已关账的 12 月 → 409
    eid = _insert_event(data_folder, 'annual_leave', '2026-11-28', {'days': 3})
    _close(ctx, '2026-12')
    r = client.post('/api/oa/events/%d/edit' % eid,
                    json={'effective_date': '2026-11-28', 'days': 10})
    assert r.status_code == 409 and r.get_json()['error'] == 'month_closed'
    # 不延长（3 天，仍止于 11 月）→ 放行到业务层
    r = client.post('/api/oa/events/%d/edit' % eid,
                    json={'effective_date': '2026-11-28', 'days': 3})
    assert r.get_json().get('error') != 'month_closed'


def test_oa_edit_days_over_limit_400_no_writes(ctx):
    appmod, data_folder, client = ctx
    eid = _insert_event(data_folder, 'annual_leave', '2026-11-05', {'days': 2})
    assert _att_override_count(data_folder) == 0
    r = client.post('/api/oa/events/%d/edit' % eid,
                    json={'effective_date': '2026-11-05', 'days': 10 ** 6})
    assert r.status_code == 400
    assert _att_override_count(data_folder) == 0  # 零写入
    # 数据库层兜底：直接调 edit_approved_event 同样拒绝（需已批事件走到参数校验）
    _insert_event(data_folder, 'annual_leave', '2026-11-05', {'days': 2}, status='approved')
    from core.database import edit_approved_event
    ok, msg = edit_approved_event(data_folder, 2, '2026-11-05', 10 ** 6, 'tc')
    assert ok is False and msg


# ── #8 直改部门/薪资口径 ────────────────────────

def test_employee_update_effective_month_closed_409(ctx):
    _, data_folder, client = ctx
    _close(ctx, '2026-10')
    # 生效月=关账月 → 409（原 guard 只判当前月，会被绕过）
    r = client.post('/api/employees/1', json={
        'department': 'New Department', 'effective_month': '2026-10'})
    assert r.status_code == 409 and r.get_json()['error'] == 'month_closed'
    # 生效月未关账 → 放行
    r = client.post('/api/employees/1', json={
        'department': 'New Department', 'effective_month': '2026-11'})
    assert r.status_code != 409
    # 缺省 effective_month（当前月）不受关账月影响
    r = client.post('/api/employees/1', json={'team_id': 3})
    assert r.status_code != 409


def test_salary_type_effective_date_and_cache_invalidation(ctx):
    appmod, data_folder, client = ctx
    # 预置缓存键：2026-10（<from_month 应保留）、2026-11/2026-12（>=from_month 应驱逐）
    with appmod.MONTH_CACHE_LOCK:
        appmod.MONTH_CACHE['2026-10'] = object()
        appmod.MONTH_CACHE['2026-11'] = object()
        appmod.MONTH_CACHE['2026-12'] = object()
    r = client.post('/api/employees/1/salary-type', json={
        'salary_type': 'monthly', 'monthly_salary': 100000, 'day_rate': 0,
        'effective_month': '2026-11'})
    assert r.status_code == 200
    # 事件 effective_date == from_month+'-01'（原硬编码当前月 1 号）
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT effective_date FROM employee_events WHERE event_type='salary_change'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row and row['effective_date'] == '2026-11-01'
    # >= from_month 的已缓存月份被驱逐，< from_month 保留
    assert '2026-10' in appmod.MONTH_CACHE
    assert '2026-11' not in appmod.MONTH_CACHE
    assert '2026-12' not in appmod.MONTH_CACHE
