"""P55g: LAMBA LAMBA(1)/SAKA SAKA(2) 2026-10-30 司机奖金取消——
命中的出勤提交不设置 driver 标志（津贴=0），其他班组不受影响；提交照常落库。"""
import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    # 三个班组 + 驱动者出勤行
    for tid, name in ((1, 'LAMBA LAMBA'), (2, 'SAKA SAKA'), (3, 'MIZOZO')):
        conn.execute("INSERT OR IGNORE INTO employee_groups (id, name) VALUES (?,?)", (tid, name))
    conn.execute("INSERT INTO employees (id, name, department, default_type, team_id, status)"
                 " VALUES ('D1','Drv One','Production TEAM','piece_underground',1,'active')")
    conn.execute("INSERT INTO employees (id, name, department, default_type, team_id, status)"
                 " VALUES ('D2','Drv Two','Production TEAM','piece_underground',2,'active')")
    conn.execute("INSERT INTO employees (id, name, department, default_type, team_id, status)"
                 " VALUES ('D3','Drv Three','Production TEAM','piece_underground',3,'active')")
    for eid in ('D1', 'D2', 'D3'):
        conn.execute("INSERT INTO attendance_overrides (employee_id, date, status, is_driver)"
                     " VALUES (?, '2026-10-30', 'P', 0)", (eid,))
    # 三个班组的出勤提交（10-30）：班组1/2 带 drivers，班组3 对照
    subs = [
        ('2026-10-30', 'Production TEAM', 1, {'submission_date': '2026-10-30', 'department': 'Production TEAM',
                                              'team_id': 1, 'marks': [{'employee_id': 'D1', 'status': 'P'}],
                                              'drivers': ['D1']}),
        ('2026-10-30', 'Production TEAM', 2, {'submission_date': '2026-10-30', 'department': 'Production TEAM',
                                              'team_id': 2, 'marks': [{'employee_id': 'D2', 'status': 'P'}],
                                              'drivers': ['D2']}),
        ('2026-10-30', 'Production TEAM', 3, {'submission_date': '2026-10-30', 'department': 'Production TEAM',
                                              'team_id': 3, 'marks': [{'employee_id': 'D3', 'status': 'P'}],
                                              'drivers': ['D3']}),
        # 对照：班组1 的 10-29 提交（未取消日期）带 drivers
        ('2026-10-29', 'Production TEAM', 1, {'submission_date': '2026-10-29', 'department': 'Production TEAM',
                                              'team_id': 1, 'marks': [{'employee_id': 'D1', 'status': 'P'}],
                                              'drivers': ['D1']}),
    ]
    for sd, dept, tid, payload in subs:
        conn.execute(
            "INSERT INTO collection_submissions (form_type, submission_date, payload, operator_id, month, department, team_id)"
            " VALUES ('attendance', ?, ?, 't', '2026-10', ?, ?)",
            (sd, json.dumps(payload), dept, tid))
    conn.commit()
    conn.close()
    return str(d)


def test_reapply_skips_cancelled_teams(tmp_path):
    data_folder = _seed(tmp_path)
    mod = _app()
    mod.app.config['DATA_FOLDER'] = data_folder
    mod._reapply_driver_flags_for_date(data_folder, '2026-10-30')
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    flags = {r[0]: r[1] for r in conn.execute(
        "SELECT employee_id, is_driver FROM attendance_overrides WHERE date='2026-10-30'").fetchall()}
    conn.close()
    # 班组1/2 的 10-30 司机标志被取消（津贴=0）
    assert flags.get('D1') == 0
    assert flags.get('D2') == 0
    # 对照班组3 正常设置
    assert flags.get('D3') == 1


def test_reapply_other_dates_unaffected(tmp_path):
    data_folder = _seed(tmp_path)
    mod = _app()
    mod.app.config['DATA_FOLDER'] = data_folder
    mod._reapply_driver_flags_for_date(data_folder, '2026-10-29')
    conn = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
    flags = {r[0]: r[1] for r in conn.execute(
        "SELECT employee_id, is_driver FROM attendance_overrides WHERE date='2026-10-29'").fetchall()}
    conn.close()
    # 未取消日期照常设置
    assert flags.get('D1') == 1
