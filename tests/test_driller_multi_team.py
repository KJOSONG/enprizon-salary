"""P54 钻工同队长同日多队伍独立结算测试。

背景（01-plan §5.1）：
- 唯一键从 (date, captain) 扩展为 (date, captain, slot)，slot 缺省 0=旧格式字节兼容
- 每个 (date, captain, slot) 组独立执行现有公式（池 = nh×5000 + nl×4000 + mw×3000）
- driller_adds（override 手动加入）归该队长当日最小 slot 组（主队）
- _dr_team_upsert 归属/冲突按 (captain, slot)；rebuild 同键替换

模板沿用 test_oa_transfer_captain.py 的 _seed_db/_make_driller_data 形状（slot 缺省 0）。
"""
import os
import sys
import json
import sqlite3
import importlib.util

import pytest

# 让 tests/ 能 import core
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

D = '2026-09-05'
H, L, M = 5000, 4000, 3000  # PRICES_DRILLER 默认单价（直接调 calc_driller_piece 未被 /config 猴子补丁覆盖）


def _mk(name):
    """测试进程内无通讯录索引 → make_employee_id 走姓名回退（去空格大写）"""
    from core.calculator import make_employee_id
    return make_employee_id(name)


def _team(captain, slot=None, nh=0, nl=0, mw=0, members=None):
    t = {
        'date': D, 'captain': captain,
        'nh': nh, 'nl': nl, 'mw': mw, 'futa': 0, 'waya': 0, 'kibiriti': 0,
        'members': members or [], 'slots': [], 'has_members': bool(members),
    }
    if slot is not None:
        t['slot'] = slot
    return t


def _seed_db(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    data_folder = str(d)
    from core.database import init_db
    init_db(data_folder)
    return data_folder


def _seed_submission(data_folder, payload, date=D, operator='opA'):
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute(
        "INSERT INTO collection_submissions (form_type, submission_date, payload, operator_id, month, version)"
        " VALUES ('driller', ?, ?, ?, ?, 1)",
        (date, json.dumps(payload, ensure_ascii=False), operator, date[:7]))
    conn.commit()
    conn.close()


# ═══════════════ 计算链：calc_driller_piece ═══════════════

def test_1_two_teams_same_captain_independent_pools(tmp_path):
    """同队长同日两队（slot 1/2，不同成员）：各自独立分池，队长每池 2 份，互不混池"""
    from core.calculator import calc_driller_piece
    data = [
        _team('CAP A', slot=1, nh=10, members=['MEM X']),
        _team('CAP A', slot=2, nh=20, members=['MEM Y']),
    ]
    result, _, _ = calc_driller_piece(data)
    cap = _mk('CAP A')
    # 池1 = 10×5000 = 50000，份额 = 成员X(1) + 队长(1+1额外份额) = 3 份 → 每份 16666.67
    assert result[_mk('MEM X')] == pytest.approx(50000 / 3)
    # 池2 = 20×5000 = 100000，同样 3 份 → Y 1 份、队长 2 份
    assert result[_mk('MEM Y')] == pytest.approx(100000 / 3)
    assert result[cap] == pytest.approx(50000 / 3 * 2 + 100000 / 3 * 2)
    # 总额守恒 = 两池之和
    assert sum(result.values()) == pytest.approx(50000 + 100000)


def test_2_single_team_no_slot_unchanged(tmp_path):
    """同队长单队无 slot 字段：结果与改动前公式逐分一致（回归锚）"""
    from core.calculator import calc_driller_piece
    # 无 slot 键（历史 payload 形状）
    data = [_team('CAP A', nh=10, members=['MEM X'])]
    result, _, _ = calc_driller_piece(data)
    assert result[_mk('MEM X')] == pytest.approx(50000 / 3)
    assert result[_mk('CAP A')] == pytest.approx(100000 / 3)
    # slot=None/0 同样退化为旧行为
    result2, _, _ = calc_driller_piece([_team('CAP A', slot=0, nh=10, members=['MEM X'])])
    assert result2 == result
    # 空成员名单日：仅队长 1 人拿全额（分母 = 队长1 + 队长份额1 = 2，队长 2 份 = 100%）
    result3, _, _ = calc_driller_piece([_team('CAP A', nh=10)])
    assert result3[_mk('CAP A')] == pytest.approx(50000)


def test_3_mixed_day_three_pools(tmp_path):
    """混合天：队长 A 单队（无 slot）+ 队长 B 两队（slot 1/2）→ 三池各自正确"""
    from core.calculator import calc_driller_piece
    data = [
        _team('CAP A', nh=10, members=['MEM X']),                    # 池1 50000
        _team('CAP B', slot=1, nl=10, members=['MEM Y']),            # 池2 40000
        _team('CAP B', slot=2, mw=10, members=['MEM Z']),            # 池3 30000
    ]
    result, _, _ = calc_driller_piece(data)
    assert result[_mk('MEM X')] == pytest.approx(50000 / 3)
    assert result[_mk('CAP A')] == pytest.approx(100000 / 3)
    assert result[_mk('MEM Y')] == pytest.approx(40000 / 3)
    assert result[_mk('CAP B')] == pytest.approx(40000 / 3 * 2 + 20000)  # B 池 2 份 + C 池 2/2
    assert result[_mk('MEM Z')] == pytest.approx(10000)
    assert sum(result.values()) == pytest.approx(50000 + 40000 + 30000)


def test_4_driller_adds_go_to_min_slot_group(tmp_path):
    """driller_adds：override 队员多队天落入最小 slot 组（主队）、单队天落唯一组"""
    data_folder = _seed_db(tmp_path)
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.execute("INSERT INTO overrides (employee_id, salary_type, start_date, end_date, captain)"
                 " VALUES ('OV1', 'piece_driller', ?, ?, 'CAP A')", (D, D))
    conn.commit()
    conn.close()

    from core.calculator import calc_driller_piece
    data = [
        _team('CAP A', slot=1, nh=10, members=['MEM X']),
        _team('CAP A', slot=2, nh=20, members=['MEM Y']),
    ]
    att = {(_mk('CAP A'), D), (_mk('MEM X'), D), (_mk('MEM Y'), D), (_mk('OV1'), D)}
    result, _, _ = calc_driller_piece(data, data_folder=data_folder,
                                      all_attendance_pairs=att)
    # 池1（最小 slot）= 50000，份额 = X(1)+队长(1+1)+OV1(1) = 4 份 → 每份 12500
    assert result[_mk('OV1')] == pytest.approx(12500)
    # 池2 不含 OV1：Y 33333.33、队长 66666.67（若 OV1 混入池2 会摊薄）
    assert result[_mk('MEM Y')] == pytest.approx(100000 / 3)
    assert result[_mk('CAP A')] == pytest.approx(12500 * 2 + 100000 / 3 * 2)

    # 单队天：override 落唯一组（slot 0）
    data2 = [_team('CAP A', nh=10, members=['MEM X'])]
    result2, _, _ = calc_driller_piece(data2, data_folder=data_folder,
                                       all_attendance_pairs={(_mk('CAP A'), D), (_mk('MEM X'), D), (_mk('OV1'), D)})
    assert result2[_mk('OV1')] == pytest.approx(12500)


def test_5_al_exclusion_conservation(tmp_path):
    """A/L 排除：某队员 A 标记后从两队同时剔除，各池总额守恒（剩余人平分）"""
    from core.calculator import calc_driller_piece
    data = [
        _team('CAP A', slot=1, nh=10, members=['MEM X', 'MEM X2']),
        _team('CAP A', slot=2, nh=20, members=['MEM Y', 'MEM X']),
    ]
    exclusions = {(_mk('MEM X'), D)}
    result, _, _ = calc_driller_piece(data, att_exclusions=exclusions)
    assert _mk('MEM X') not in result
    # 池1 = 50000：剩 X2 + 队长 → 3 份额（X2 1 + 队长 1+1）→ 每份 16666.67，队长 2 份 33333.33
    assert result[_mk('MEM X2')] == pytest.approx(50000 / 3)
    # 池2 = 100000：剩 Y + 队长 → Y 33333.33、队长 66666.67
    assert result[_mk('MEM Y')] == pytest.approx(100000 / 3)
    assert sum(result.values()) == pytest.approx(50000 + 100000)


# ═══════════════ 提交链：_dr_team_upsert（导入 app.py 但屏蔽启动块）═══════════════

_APP_MOD = None


def _app():
    """导入 app 模块（屏蔽 __main__/gunicorn 初始化触发，只取函数定义）"""
    global _APP_MOD
    if _APP_MOD is None:
        src_path = os.path.join(ROOT, 'app.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        src = src.replace("if __name__ != '__main__':", "if False:") \
                 .replace("if __name__ == '__main__':", "if False:")
        spec = importlib.util.spec_from_file_location('app_p54_tests', src_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules['app_p54_tests'] = mod
        exec(compile(src, src_path, 'exec'), mod.__dict__)
        _APP_MOD = mod
    return _APP_MOD


def test_6_upsert_keys_and_conflict(tmp_path):
    """_dr_team_upsert：同 (captain, slot) patch 替换；同 captain 不同 slot 互不覆盖不冲突；
    他人提交同 (captain, slot) → 冲突"""
    data_folder = _seed_db(tmp_path)
    mod = _app()

    # 同一用户一次提交同队长两队（slot 1/2）→ 两行
    ok, err, _, sids, caps = mod._dr_team_upsert(
        data_folder, D,
        [_team('9', slot=1, nh=10), _team('9', slot=2, nh=20)], 'opA', False)
    assert ok, err
    assert len(sids) == 2

    # 同 (captain, slot) 二次提交（本人）→ 行内 patch 替换，行数不变
    ok, err, _, sids2, _ = mod._dr_team_upsert(
        data_folder, D, [_team('9', slot=1, nh=11)], 'opA', False)
    assert ok, err
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT payload FROM collection_submissions WHERE form_type='driller'").fetchall()
    conn.close()
    assert len(rows) == 2
    payloads = sorted((t for r in rows for t in json.loads(r['payload'])['teams']),
                      key=lambda t: t.get('slot', 0))
    assert payloads[0]['nh'] == 11 and payloads[0]['slot'] == 1  # 已替换
    assert payloads[1]['nh'] == 20 and payloads[1]['slot'] == 2  # 未动

    # 同 captain 不同 slot 互不覆盖：他人可提交同队长 slot 3
    ok, err, _, _, _ = mod._dr_team_upsert(
        data_folder, D, [_team('9', slot=3, nh=30)], 'opB', False)
    assert ok, err

    # 他人提交同 (captain, slot=1) → 冲突 400 语义（ok=False）
    ok, err, params, _, _ = mod._dr_team_upsert(
        data_folder, D, [_team('9', slot=1, nh=99)], 'opB', False)
    assert not ok
    assert 'opA' in err or 'opA' in str(params)


def test_7_rebuild_two_slots_two_records(tmp_path):
    """rebuild：同 (date, captain) 不同 slot 两条提交 → driller_production 2 条记录、
    slot 正确；重放（全量重建）结果确定一致"""
    data_folder = _seed_db(tmp_path)
    _seed_submission(data_folder, {'teams': [{'captain': '9', 'slot': 2, 'nh': 20, 'members': ['101']}]},
                     date='2026-09-05', operator='opA')
    _seed_submission(data_folder, {'teams': [{'captain': '9', 'slot': 1, 'nh': 10, 'members': ['102']}]},
                     date='2026-09-05', operator='opB')
    mod = _app()
    mod.app.config['DATA_FOLDER'] = data_folder  # rebuild 内部读 app.config['DATA_FOLDER']

    def _run():
        md = {'shift_production': [], 'driller_production': [], 'crush_production': []}
        mod.rebuild_main_data_from_collections(md)
        return sorted(
            [(r['date'], r['captain'], int(r.get('slot', 0) or 0), r['nh'], tuple(r['members']))
             for r in md['driller_production']])

    recs = _run()
    assert len(recs) == 2
    assert {r[2] for r in recs} == {1, 2}
    assert {r[3] for r in recs} == {10, 20}
    # 重放（全量重建语义）逐项一致（subs (submission_date, id) ASC 确定性）
    assert _run() == recs


def test_7b_rebuild_no_slot_single_record(tmp_path):
    """回归锚：两条无 slot 的历史提交同 (date, captain) → 仍 1 条记录（后者覆盖前者，旧语义）"""
    data_folder = _seed_db(tmp_path)
    _seed_submission(data_folder, {'teams': [{'captain': '9', 'nh': 10, 'members': ['101']}]},
                     date='2026-09-05', operator='opA')
    _seed_submission(data_folder, {'teams': [{'captain': '9', 'nh': 20, 'members': ['102']}]},
                     date='2026-09-05', operator='opB')
    mod = _app()
    mod.app.config['DATA_FOLDER'] = data_folder
    md = {'shift_production': [], 'driller_production': [], 'crush_production': []}
    mod.rebuild_main_data_from_collections(md)
    assert len(md['driller_production']) == 1
    assert md['driller_production'][0]['nh'] == 20  # 后提交（id 更大）覆盖
    assert int(md['driller_production'][0].get('slot', 0)) == 0
