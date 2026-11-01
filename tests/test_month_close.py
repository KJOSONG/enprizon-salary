"""月度关账（closed_months）回归测试（2026-11-01）。

关账后该月所有薪资相关写操作 409 拒绝：
- 采集提交/编辑/豁免、出勤标记（单个+批量）
- 奖金/罚款/预支（弹窗+行内编辑）、改薪资/临时例外/覆盖删除
- OA 申请（生效日/假期区间落在关账月）、审批/驳回/撤销/修改
- 关账/解锁仅超管，写审计 month_close/month_open
只读查看与导出不受影响。临时例外区间跨关账月、远期哨兵 9999-12-31 有界展开。
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
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
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


def _close(ctx, month, closed=True, role='super_admin', username='tc'):
    appmod, data_folder, client = ctx
    if role != 'super_admin' or username != 'tc':
        with client.session_transaction() as s:
            s['role'] = role
            s['username'] = username
    r = client.post('/api/months/close', json={'month': month, 'closed': closed})
    with client.session_transaction() as s:
        s['role'] = 'super_admin'
        s['username'] = 'tc'
    return r


# ── DB helpers ──────────────────────────────

def test_closed_months_roundtrip(ctx):
    appmod, data_folder, _ = ctx
    from core.database import get_closed_months, set_month_closed
    assert get_closed_months(data_folder) == []
    set_month_closed(data_folder, '2026-10', True, 'tc')
    assert get_closed_months(data_folder) == ['2026-10']
    set_month_closed(data_folder, '2026-09', True, 'tc')
    assert get_closed_months(data_folder) == ['2026-09', '2026-10']
    set_month_closed(data_folder, '2026-10', False, 'tc')
    assert get_closed_months(data_folder) == ['2026-09']


def test_close_writes_audit(ctx):
    appmod, data_folder, _ = ctx
    from core.database import get_conn
    set_month_closed = None
    from core.database import set_month_closed as _smc
    _smc(data_folder, '2026-10', True, 'tc')
    conn = get_conn(data_folder)
    rows = conn.execute(
        "SELECT action, operator FROM audit_log WHERE action IN ('month_close','month_open')"
        " ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0]['action'] == 'month_close' and rows[0]['operator'] == 'tc'
    _smc(data_folder, '2026-10', False, 'tc')
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT action FROM audit_log WHERE action LIKE 'month_%' ORDER BY id").fetchall()
    conn.close()
    assert rows[-1]['action'] == 'month_open'


# ── guard helpers ───────────────────────────

def test_month_span_clamps_sentinel(ctx):
    appmod, _, _ = ctx
    with appmod.app.test_request_context():
        ms = appmod._month_span_months('2026-09-15', '9999-12-31')
        assert len(ms) == 24  # 哨兵值有界展开
        assert '2026-10' in ms and '2026-09' in ms


def test_guard_months_closed_shape(ctx):
    appmod, data_folder, _ = ctx
    from core.database import set_month_closed as _smc
    _smc(data_folder, '2026-10', True, 'tc')
    with appmod.app.test_request_context():
        ok = appmod._guard_months_closed(['2026-11'])
        assert ok is None
        resp, code = appmod._guard_months_closed(['2026-10-05', '2026-11'])
        assert code == 409
        body = resp.get_json()
        assert body['error'] == 'month_closed' and body['months'] == ['2026-10']


# ── 关账/解锁端点 ────────────────────────────

def test_close_endpoint_super_admin_only(ctx):
    appmod, data_folder, client = ctx
    r = _close(ctx, '2026-10', True, role='viewer', username='tc')
    assert r.status_code == 403
    r = _close(ctx, '2026-10', True)
    assert r.status_code == 200 and r.get_json()['closed'] is True
    r = client.get('/api/months/closed')
    assert r.get_json()['closed_months'] == ['2026-10']


def test_close_endpoint_bad_month(ctx):
    _, _, client = ctx
    r = client.post('/api/months/close', json={'month': 'bad', 'closed': True})
    assert r.status_code == 400


# ── 写路径 409 ───────────────────────────────

def test_collection_submit_blocked_in_closed_month(ctx):
    appmod, data_folder, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/collection/submit', json={
        'form_type': 'attendance', 'submission_date': '2026-10-05', 'payload': {'marks': []}})
    assert r.status_code == 409 and r.get_json()['error'] == 'month_closed'
    # 未关账月放行（走到业务校验层，不再报 month_closed）
    r = client.post('/api/collection/submit', json={
        'form_type': 'attendance', 'submission_date': '2026-11-05', 'payload': {'marks': []}})
    assert r.get_json().get('error') != 'month_closed'


def test_attendance_batch_blocked(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/attendance/batch', json={'date': '2026-10-05', 'marks': []})
    assert r.status_code == 409
    r = client.post('/api/attendance/batch', json={'date': '2026-11-05', 'marks': []})
    assert r.status_code == 200


def test_salary_inline_edit_blocked(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/salary/inline-edit', json={
        'employee_id': '1', 'field': 'bonus', 'value': 100, 'month': '2026-10'})
    assert r.status_code == 409


def test_bonus_penalty_blocked(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/employees/bonus-penalty', json={
        'employee_id': '1', 'month': '2026-10', 'bonus': 100, 'penalty': 0})
    assert r.status_code == 409


def test_oa_apply_blocked_in_closed_month(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/oa/events', json={
        'event_type': 'overtime', 'employee_id': '1', 'effective_date': '2026-10-05',
        'payload': {'date': '2026-10-05', 'hours': 1}})
    assert r.status_code == 409
    # 跨月假期展开：11-30 起 3 天含关账月？不含（11-30~12-02），放行到业务层
    r = client.post('/api/oa/events', json={
        'event_type': 'annual_leave', 'employee_id': '1', 'effective_date': '2026-11-30',
        'payload': {'days': 3}})
    assert r.get_json().get('error') != 'month_closed'
    # 10-31 起 3 天跨入 11 月之前先覆盖 10 月 → 拒绝
    r = client.post('/api/oa/events', json={
        'event_type': 'annual_leave', 'employee_id': '1', 'effective_date': '2026-10-31',
        'payload': {'days': 3}})
    assert r.status_code == 409


def test_oa_approve_blocked_for_closed_month_event(ctx):
    appmod, data_folder, client = ctx
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO employee_events (employee_id, event_type, effective_date, snapshot, payload,"
        " operator_id, status) VALUES ('1','overtime','2026-10-05','{}','{\"date\":\"2026-10-05\"}','x','pending')")
    conn.commit()
    conn.close()
    _close(ctx, '2026-10', True)
    r = client.post('/api/oa/events/1/approve', json={})
    assert r.status_code == 409


def test_permanent_override_blocked_when_any_closed(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/employees/override', json={
        'employee_id': '1', 'salary_type': 'monthly', 'monthly_salary': 100000})
    assert r.status_code == 409
    # 临时例外区间跨关账月同样拒绝
    r = client.post('/employees/override', json={
        'employee_id': '1', 'salary_type': 'day_rate', 'day_rate': 100,
        'start_date': '2026-09-01', 'end_date': '2026-10-31'})
    assert r.status_code == 409
    # 区间不涉关账月放行
    r = client.post('/employees/override', json={
        'employee_id': '1', 'salary_type': 'day_rate', 'day_rate': 100,
        'start_date': '2026-11-01', 'end_date': '2026-11-30'})
    assert r.status_code == 200


def test_profile_salary_fields_blocked_when_any_closed(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/employees/1', json={'default_type': 'monthly'})
    assert r.status_code == 409
    # 非薪资字段不受影响（走到后续业务逻辑）
    r = client.post('/api/employees/1', json={'phone': '123'})
    assert r.status_code != 409


def test_salary_type_change_blocked_in_closed_month(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/employees/1/salary-type', json={
        'salary_type': 'monthly', 'monthly_salary': 100000, 'day_rate': 0,
        'effective_month': '2026-10'})
    assert r.status_code == 409
    r = client.post('/api/employees/1/salary-type', json={
        'salary_type': 'monthly', 'monthly_salary': 100000, 'day_rate': 0,
        'effective_month': '2026-11'})
    assert r.status_code != 409


def test_production_shift_blocked(ctx):
    _, _, client = ctx
    _close(ctx, '2026-10', True)
    r = client.post('/api/production/shift', json={'employee_id': '1', 'date': '2026-10-05', 'shift': 'D'})
    assert r.status_code == 409
