"""井下出渣采集 MZIGO 备注必填回归测试（2026-11-04）。

需求：井下出渣采集提交的备注栏设为必填，提示语固定为
"Please fill MZIGO from which driller team"（注明 MZIGO 来自哪个钻工班组）。
- 新格式：teams 中每个班组 remark 必填
- 旧格式：day/night 有产量（nh+nl+mw>0）的班次 remark 必填
- 后端 /api/collection/submit 与 /api/collection/edit 双端拦截；桌面/移动前端同步提示
"""
import os
import sys
import json
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MZ = 'Please fill MZIGO from which driller team'


def test_mzigo_error_new_format():
    from app import _ug_mzigo_remark_error
    # 任一班组合并后 remark 为空 → 报错
    assert _ug_mzigo_remark_error({'teams': [
        {'team_id': 1, 'nh': 10, 'remark': 'MZIGO from driller team 1'},
        {'team_id': 2, 'nh': 5, 'remark': '   '},
    ]}) == MZ
    # 全部填写 → 放行
    assert _ug_mzigo_remark_error({'teams': [
        {'team_id': 1, 'nh': 10, 'remark': 'MZIGO A'},
        {'team_id': 2, 'nh': 0, 'remark': 'MZIGO B'},
    ]}) is None
    # 空 teams → 放行（无班次数据由其他校验拦）
    assert _ug_mzigo_remark_error({'teams': []}) is None


def test_mzigo_error_old_format():
    from app import _ug_mzigo_remark_error
    # 有产量但备注空 → 报错
    assert _ug_mzigo_remark_error({'day': {'nh': 10, 'nl': 0, 'mw': 0, 'remark': ''},
                                   'night': {'nh': 0, 'nl': 0, 'mw': 0, 'remark': ''}}) == MZ
    assert _ug_mzigo_remark_error({'day': {'nh': 0, 'nl': 0, 'mw': 0, 'remark': ''},
                                   'night': {'nh': 3, 'nl': 1, 'mw': 0, 'remark': ' '}}) == MZ
    # 无产量班次不要求备注
    assert _ug_mzigo_remark_error({'day': {'nh': 0, 'nl': 0, 'mw': 0, 'remark': ''},
                                   'night': {'nh': 0, 'nl': 0, 'mw': 0, 'remark': ''}}) is None
    assert _ug_mzigo_remark_error({'day': {'nh': 10, 'nl': 0, 'mw': 0, 'remark': 'MZIGO D'},
                                   'night': {'nh': 0, 'nl': 0, 'mw': 0, 'remark': ''}}) is None
    # 非 dict payload 容错
    assert _ug_mzigo_remark_error(None) is None
    assert _ug_mzigo_remark_error('x') is None


def _seed_db(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    from core.database import init_db
    data_folder = str(d)
    init_db(data_folder)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    try:
        conn.execute("ALTER TABLE collection_submissions ADD COLUMN team_id INTEGER DEFAULT 0")
    except Exception:
        pass
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


def test_submit_blocked_without_mzigo_remark(ctx):
    _, _, client = ctx
    r = client.post('/api/collection/submit', json={
        'form_type': 'underground', 'submission_date': '2026-11-03',
        'payload': {'teams': [{'team_id': 1, 'nh': 10, 'nl': 0, 'mw': 0, 'exempt': False, 'remark': ''}]}})
    assert r.status_code == 400 and r.get_json()['error'] == MZ


def test_submit_passes_with_mzigo_remark(ctx):
    """备注齐全时不再报 MZIGO 错（后续班组校验另有其错）"""
    _, _, client = ctx
    r = client.post('/api/collection/submit', json={
        'form_type': 'underground', 'submission_date': '2026-11-03',
        'payload': {'teams': [{'team_id': 1, 'nh': 10, 'nl': 0, 'mw': 0, 'exempt': False,
                               'remark': 'MZIGO from driller team 1'}]}})
    body = r.get_json()
    assert body.get('error') != MZ


def test_submit_old_format_blocked_without_remark(ctx):
    _, _, client = ctx
    r = client.post('/api/collection/submit', json={
        'form_type': 'underground', 'submission_date': '2026-11-03',
        'payload': {'day': {'nh': 10, 'nl': 0, 'mw': 0, 'emps': [], 'drivers': [], 'remark': '', 'team_id': 0, 'exempt': False},
                    'night': {'nh': 0, 'nl': 0, 'mw': 0, 'emps': [], 'drivers': [], 'remark': '', 'team_id': 0, 'exempt': False}}})
    assert r.status_code == 400 and r.get_json()['error'] == MZ
