"""P57: 破碎计件同日多组（组 1/组 2，镜像钻工 P54 slot）——
合并层按 (date, slot) 独立成池（存量无 slot 视为 1）；占用校验排除自身。"""
import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _crush_slot_taken, _merge_collection_to_main_data, _crush_slot_taken as _cst


def _app():
    import app as appmod
    return appmod


def _seed(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    from core.database import init_db
    init_db(str(d))
    conn = sqlite3.connect(os.path.join(str(d), 'kilwa.db'))
    try:
        conn.execute("ALTER TABLE collection_submissions ADD COLUMN team_id INTEGER DEFAULT 0")
    except Exception:
        pass
    # 组 1（存量无 slot）与组 2 同日两条提交
    conn.execute(
        "INSERT INTO collection_submissions (form_type, submission_date, payload, operator_id, month)"
        " VALUES ('crush','2026-10-30',?, 'c','2026-10')",
        (json.dumps({'bags': 100, 'emps': ['11', '12']}),))
    conn.execute(
        "INSERT INTO collection_submissions (form_type, submission_date, payload, operator_id, month)"
        " VALUES ('crush','2026-10-30',?, 'c','2026-10')",
        (json.dumps({'slot': 2, 'bags': 50, 'emps': ['13']}),))
    conn.commit()
    conn.close()
    return str(d)


def test_merge_two_slots_both_persist(tmp_path):
    data_folder = _seed(tmp_path)
    md = {'crush_production': []}
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT submission_date, payload FROM collection_submissions WHERE form_type='crush'"
        " ORDER BY id").fetchall()
    conn.close()
    for r in rows:
        _merge_collection_to_main_data(md, 'crush', r['submission_date'], json.loads(r['payload']))
    recs = md['crush_production']
    assert len(recs) == 2, recs
    by_slot = {r['slot']: r for r in recs}
    assert by_slot[1]['bags'] == 100 and by_slot[2]['bags'] == 50
    # 同 slot 重复合并 → 原位覆盖（编辑语义），不追加
    _merge_collection_to_main_data(md, 'crush', '2026-10-30', {'slot': 1, 'bags': 120, 'emps': ['11']})
    assert len(md['crush_production']) == 2
    assert [r for r in md['crush_production'] if r['slot'] == 1][0]['bags'] == 120


def test_legacy_no_slot_counts_as_slot1(tmp_path):
    data_folder = _seed(tmp_path)
    assert _crush_slot_taken(data_folder, '2026-10-30', 1) is True
    assert _crush_slot_taken(data_folder, '2026-10-30', 2) is True


def test_slot_occupancy_exclude_self(tmp_path):
    data_folder = _seed(tmp_path)
    # 排除组 2 自身（编辑场景）→ 组 2 不算被占
    rows = _cst.__globals__  # noqa: 占位，真实断言如下
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    sid2 = conn.execute(
        "SELECT id FROM collection_submissions WHERE form_type='crush' AND submission_date='2026-10-30'"
        " AND payload LIKE '%\"slot\": 2%'").fetchone()[0]
    conn.close()
    assert _crush_slot_taken(data_folder, '2026-10-30', 2, exclude_id=sid2) is False
    assert _crush_slot_taken(data_folder, '2026-10-30', 2) is True


def test_slot_free_on_other_date(tmp_path):
    data_folder = _seed(tmp_path)
    assert _crush_slot_taken(data_folder, '2026-10-29', 1) is False
    assert _crush_slot_taken(data_folder, '2026-10-29', 2) is False


def test_submit_flow_two_groups_replace_same_slot(tmp_path):
    """P57 提交流端到端：组 1 提交 → 组 2 提交（并存）→ 组 1 重提=替换组 1（组 2 不动）"""
    d = tmp_path / 'data'
    d.mkdir()
    from core.database import init_db
    init_db(str(d))
    conn = sqlite3.connect(os.path.join(str(d), 'kilwa.db'))
    conn.execute("INSERT OR REPLACE INTO admin_users (username, password_hash, role) VALUES ('t','','super_admin')")
    conn.commit()
    conn.close()
    mod = _app()
    mod.app.config['DATA_FOLDER'] = str(d)
    client = mod.app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 't'
        sess['role'] = 'super_admin'

    def sub(payload):
        return client.post('/api/collection/submit', json={
            'form_type': 'crush', 'submission_date': '2026-10-30', 'payload': payload})

    assert sub({'bags': 100, 'emps': ['11', '12'], 'slot': 1}).get_json()['ok'] is True
    assert sub({'bags': 60, 'emps': ['13'], 'slot': 2}).get_json()['ok'] is True
    # 组 1 重提 → 替换组 1（不新增行、组 2 不受影响）
    assert sub({'bags': 120, 'emps': ['11'], 'slot': 1}).get_json()['ok'] is True
    conn = sqlite3.connect(os.path.join(str(d), 'kilwa.db'))
    rows = conn.execute(
        "SELECT payload FROM collection_submissions WHERE form_type='crush' AND submission_date='2026-10-30'"
        " ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 2
    slots = {}
    for (p,) in rows:
        pd = json.loads(p)
        slots[pd['slot']] = pd['bags']
    assert slots == {1: 120, 2: 60}
    # 合并层：两池独立
    md = {'crush_production': []}
    mod.rebuild_main_data_from_collections(md)
    assert len(md['crush_production']) == 2
    assert {r['slot']: r['bags'] for r in md['crush_production']} == {1: 120, 2: 60}
