"""
SQLite 数据库层 — 统一持久化
替代所有 JSON 文件
"""
import json, os, sqlite3, hashlib, secrets

DB_FILE = 'kilwa.db'

def get_conn(data_folder):
    path = os.path.join(data_folder, DB_FILE)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db(data_folder):
    """建表 + 迁移旧 JSON 数据"""
    conn = get_conn(data_folder)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            department TEXT DEFAULT '',
            default_type TEXT DEFAULT 'day_rate',
            day_rate INTEGER DEFAULT 0,
            monthly_salary INTEGER DEFAULT 0,
            nssf_enrolled INTEGER DEFAULT 0,
            phone TEXT DEFAULT '',
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            salary_type TEXT DEFAULT '',
            day_rate INTEGER DEFAULT 0,
            monthly_salary INTEGER DEFAULT 0,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            note TEXT DEFAULT '',
            type TEXT DEFAULT '',
            shift TEXT DEFAULT '',
            captain TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS attendance_overrides (
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'A',
            PRIMARY KEY (employee_id, date)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_data (
            month TEXT NOT NULL,
            employee_id TEXT NOT NULL,
            salary_type TEXT DEFAULT '',
            piece_underground REAL DEFAULT 0,
            piece_driller REAL DEFAULT 0,
            piece_crush REAL DEFAULT 0,
            day_rate REAL DEFAULT 0,
            monthly REAL DEFAULT 0,
            gross REAL DEFAULT 0,
            advance REAL DEFAULT 0,
            nssf REAL DEFAULT 0,
            net REAL DEFAULT 0,
            PRIMARY KEY (month, employee_id)
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_month ON monthly_data(month);
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            action TEXT NOT NULL,
            employee_id TEXT DEFAULT '',
            detail TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
    """)
    # 兼容旧表，新增 shift/captain 列
    for col in ['shift', 'captain']:
        try:
            conn.execute(f"ALTER TABLE overrides ADD COLUMN {col} TEXT DEFAULT ''")
        except: pass
    # 月份隔离：新增 effective_from 列（"YYYY-MM"），空白=全局生效
    try:
        conn.execute("ALTER TABLE overrides ADD COLUMN effective_from TEXT DEFAULT ''")
    except: pass
    # P1: employees 扩展列
    _emp_new_cols = [
        ('position', 'TEXT DEFAULT \'\''),
        ('skill_level', 'TEXT DEFAULT \'\''),
        ('hire_date', 'TEXT DEFAULT \'\''),
        ('nida_number', 'TEXT DEFAULT \'\''),
        ('nssf_number', 'TEXT DEFAULT \'\''),
        ('bank_name', 'TEXT DEFAULT \'\''),
        ('bank_account', 'TEXT DEFAULT \'\''),
        ('bank_owner', 'TEXT DEFAULT \'\''),
        ('status', 'TEXT DEFAULT \'active\''),
        ('dismissed_at', 'TEXT DEFAULT \'\''),
        ('custom_fields', 'TEXT DEFAULT \'{}\''),
    ]
    for col, defn in _emp_new_cols:
        try:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {col} {defn}")
        except: pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS shift_additions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            shift TEXT NOT NULL DEFAULT 'D',
            UNIQUE(employee_id, date, shift)
        );
        CREATE TABLE IF NOT EXISTS driller_additions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            captain TEXT NOT NULL DEFAULT '',
            UNIQUE(employee_id, date, captain)
        );
        CREATE TABLE IF NOT EXISTS bonus_penalties (
            employee_id TEXT NOT NULL,
            month TEXT NOT NULL,
            bonus INTEGER DEFAULT 0,
            penalty INTEGER DEFAULT 0,
            PRIMARY KEY (employee_id, month)
        );
        CREATE TABLE IF NOT EXISTS dismissed_employees (
            employee_id TEXT PRIMARY KEY,
            dismissed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            action TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'all',
            scope_value TEXT DEFAULT '',
            UNIQUE(module, action, scope_type, scope_value)
        );
        CREATE TABLE IF NOT EXISTS user_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            permission_id INTEGER NOT NULL,
            grant_type TEXT NOT NULL DEFAULT 'allow',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (username) REFERENCES admin_users(username),
            FOREIGN KEY (permission_id) REFERENCES permissions(id),
            UNIQUE(username, permission_id)
        );
        CREATE TABLE IF NOT EXISTS employee_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            snapshot TEXT NOT NULL DEFAULT '{}',
            payload TEXT NOT NULL DEFAULT '{}',
            operator_id TEXT NOT NULL,
            approved_by TEXT DEFAULT '',
            rejected_by TEXT DEFAULT '',
            reject_reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_events_employee ON employee_events(employee_id, effective_date);
        CREATE INDEX IF NOT EXISTS idx_events_status ON employee_events(status);
        CREATE TABLE IF NOT EXISTS leave_balances (
            employee_id TEXT NOT NULL,
            year TEXT NOT NULL,
            annual_entitled INTEGER DEFAULT 28,
            annual_used INTEGER DEFAULT 0,
            comp_entitled INTEGER DEFAULT 0,
            comp_used INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (employee_id, year)
        );
        CREATE TABLE IF NOT EXISTS driver_roster (
            employee_id TEXT PRIMARY KEY,
            allowance_per_day INTEGER DEFAULT 5000,
            effective_from TEXT DEFAULT '',
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS scoring_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week INTEGER NOT NULL,
            team INTEGER NOT NULL,
            card_no TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '工友',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(week, team, card_no, source)
        );
        CREATE TABLE IF NOT EXISTS scoring_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL REFERENCES scoring_cards(id),
            target_wid TEXT NOT NULL,
            target_employee_id TEXT NOT NULL,
            initiative INTEGER DEFAULT 0,
            diligence INTEGER DEFAULT 0,
            discipline INTEGER DEFAULT 0,
            cooperation INTEGER DEFAULT 0,
            safety INTEGER DEFAULT 0,
            driving INTEGER DEFAULT NULL,
            UNIQUE(card_id, target_wid)
        );
        CREATE TABLE IF NOT EXISTS objective_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_date TEXT NOT NULL,
            team INTEGER NOT NULL,
            planned_output REAL DEFAULT 0,
            actual_output REAL DEFAULT 0,
            total_hours REAL DEFAULT 0,
            effective_hours REAL DEFAULT 0,
            week INTEGER NOT NULL,
            daily_s REAL DEFAULT 0,
            UNIQUE(record_date, team)
        );
        CREATE TABLE IF NOT EXISTS form_schemas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            table_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS form_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_id INTEGER NOT NULL,
            field_key TEXT NOT NULL,
            field_type TEXT NOT NULL DEFAULT 'text',
            label_zh TEXT NOT NULL DEFAULT '',
            label_en TEXT NOT NULL DEFAULT '',
            options TEXT DEFAULT '[]',
            placeholder_zh TEXT DEFAULT '',
            placeholder_en TEXT DEFAULT '',
            required INTEGER DEFAULT 0,
            visible_roles TEXT DEFAULT '[]',
            sort_order INTEGER DEFAULT 0,
            is_custom INTEGER DEFAULT 0,
            default_value TEXT DEFAULT '',
            FOREIGN KEY (schema_id) REFERENCES form_schemas(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

    # 迁移：旧版 admin_users 表无 role 列时自动添加
    try:
        conn.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        conn.commit()
    except Exception:
        pass  # 列已存在则跳过

    # 迁移：新增 piece_crush 列
    for col in ['piece_crush']:
        try:
            conn.execute(f"ALTER TABLE monthly_data ADD COLUMN {col} REAL DEFAULT 0")
        except: pass

    # 迁移：清理旧的重复覆盖记录（按人员+类型+日期区间去重，保留最新一条，排除记录不受影响）
    conn.executescript("""
        DELETE FROM overrides WHERE rowid NOT IN (
            SELECT MAX(rowid) FROM overrides WHERE type!='exclusion'
            GROUP BY employee_id, salary_type, start_date, end_date
        ) AND type!='exclusion';
        DELETE FROM monthly_data WHERE month='all';
    """)
    conn.commit()
    _migrate_json(conn, data_folder)
    conn.close()

def _migrate_json(conn, data_folder):
    """将旧 JSON 文件导入 SQLite（仅首次运行）"""
    c = conn.cursor()

    # 检查是否已有数据
    row = c.execute("SELECT COUNT(*) FROM overrides").fetchone()
    if row[0] > 0:
        return  # 已迁移过

    # 迁移 overrides.json → overrides 表
    ov_file = os.path.join(data_folder, 'overrides.json')
    if os.path.exists(ov_file):
        with open(ov_file, 'r') as f:
            ovs = json.load(f)
        for eid, items in ovs.items():
            for item in items:
                c.execute(
                    "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary, start_date, end_date, note, type) VALUES (?,?,?,?,?,?,?,?)",
                    (eid, item.get('salary_type',''), item.get('day_rate',0), item.get('monthly_salary',0),
                     item.get('start_date',''), item.get('end_date',''), item.get('note',''), item.get('type',''))
                )

    # 迁移 nssf.json → employees.nssf_enrolled
    nssf_file = os.path.join(data_folder, 'nssf.json')
    if os.path.exists(nssf_file):
        with open(nssf_file, 'r') as f:
            nssfs = json.load(f)
        for eid, info in nssfs.items():
            if info.get('enrolled'):
                c.execute("INSERT OR REPLACE INTO employees (id, nssf_enrolled) VALUES (?,1)", (eid,))

    # 迁移 attendance_overrides.json → attendance_overrides 表
    att_file = os.path.join(data_folder, 'attendance_overrides.json')
    if os.path.exists(att_file):
        with open(att_file, 'r') as f:
            atts = json.load(f)
        for key, val in atts.items():
            parts = key.split('|')
            if len(parts) == 2:
                eid, dt = parts
                if isinstance(val, bool):
                    status = 'A'
                elif val in ('A','L'):
                    status = val
                else:
                    continue
                c.execute("INSERT OR REPLACE INTO attendance_overrides (employee_id, date, status) VALUES (?,?,?)",
                          (eid, dt, status))

    # 迁移 pricing.json → settings 表
    pr_file = os.path.join(data_folder, 'pricing.json')
    if os.path.exists(pr_file):
        with open(pr_file, 'r') as f:
            pr = json.load(f)
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('config', ?)", (json.dumps(pr),))

    conn.commit()


# ── 员工例外 overrides ────────────────────────

def load_overrides(data_folder, month=None):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM overrides ORDER BY id").fetchall()
    conn.close()
    result = {}
    for r in rows:
        eid = r['employee_id']
        if eid not in result:
            result[eid] = []
        # 按月过滤：跳过尚未生效的覆盖
        eff = r['effective_from'] or ''
        if month and eff and eff > month:
            continue
        result[eid].append({
            'id': r['id'],
            'salary_type': r['salary_type'] or '',
            'day_rate': r['day_rate'] or 0,
            'monthly_salary': r['monthly_salary'] or 0,
            'start_date': r['start_date'] or '',
            'end_date': r['end_date'] or '',
            'note': r['note'] or '',
            'type': r['type'] or '',
            'shift': r['shift'] or '',
            'captain': r['captain'] or '',
            'effective_from': eff,
        })
    # 去重：同一员工的永久覆盖（无日期区间），只保留 effective_from 最大的
    for eid in list(result.keys()):
        perms = [o for o in result[eid] if not o['start_date'] and not o['end_date'] and o['salary_type'] and o['type'] != 'exclusion']
        if len(perms) > 1:
            # 保留 effective_from 最大的那条，删除其余的
            perms.sort(key=lambda x: x['effective_from'], reverse=True)
            keep_id = perms[0]['id']
            result[eid] = [o for o in result[eid] if not (not o['start_date'] and not o['end_date'] and o['salary_type'] and o['type'] != 'exclusion') or o['id'] == keep_id]
    return result

def save_override(data_folder, data):
    conn = get_conn(data_folder)
    eid = data.get('employee_id', '')
    st = data.get('salary_type', '')
    tp = data.get('type', '')
    action = data.get('action', 'add')
    eff = data.get('effective_from', '')
    # 排除记录的日期存 start_date
    start = data.get('start_date', '')
    if tp == 'exclusion' and not start:
        start = data.get('date', '')

    if tp == 'exclusion' and action == 'remove':
        # 恢复计件：删除该排除记录
        conn.execute("DELETE FROM overrides WHERE employee_id=? AND type='exclusion' AND start_date=?",
                     (eid, start))
        conn.commit()
        conn.close()
        return

    # 排除记录：多个日期各自独立（不按 salary_type 去重）
    if tp == 'exclusion':
        conn.execute("DELETE FROM overrides WHERE employee_id=? AND type='exclusion' AND start_date=?",
                     (eid, start))
    else:
        # 普通薪资覆盖
        if start or data.get('end_date', ''):
            # 临时例外（有日期区间）：只删相同日期区间的旧记录，保留不同日期的
            conn.execute(
                "DELETE FROM overrides WHERE employee_id=? AND salary_type=? AND type=? AND start_date=? AND end_date=?",
                (eid, st, tp, start, data.get('end_date',''))
            )
        else:
            # 永久设置（无日期区间）：按 employee_id + salary_type + effective_from 去重，不同月保留独立记录
            conn.execute("DELETE FROM overrides WHERE employee_id=? AND salary_type=? AND type=? AND COALESCE(effective_from,'')=?",
                         (eid, st, tp, eff))
            conn.execute("DELETE FROM overrides WHERE employee_id=? AND type='' AND start_date='' AND salary_type!=? AND COALESCE(effective_from,'')=?",
                         (eid, st, eff))

    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary, start_date, end_date, note, type, shift, captain, effective_from) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (eid, st, data.get('day_rate',0), data.get('monthly_salary',0),
         start, data.get('end_date',''), data.get('note',''), tp,
         data.get('shift',''), data.get('captain',''), eff)
    )
    conn.commit()
    conn.close()

def remove_override(data_folder, employee_id, index):
    if index is None or not isinstance(index, int):
        return
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT id FROM overrides WHERE employee_id=? ORDER BY id", (employee_id,)).fetchall()
    if 0 <= index < len(rows):
        conn.execute("DELETE FROM overrides WHERE id=?", (rows[index]['id'],))
        conn.commit()
    conn.close()

def load_daily_exclusions(data_folder):
    """兼容旧的 exclusions 接口"""
    ovs = load_overrides(data_folder)
    result = set()
    for eid, items in ovs.items():
        for item in items:
            if item.get('type') == 'exclusion' and item.get('start_date'):
                result.add((eid, item['start_date']))
    return result

def save_exclusion(data_folder, data):
    save_override(data_folder, data)


# ── NSSF 社保 ──────────────────────────────────

def load_nssf_enrollment(data_folder):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT id, nssf_enrolled FROM employees WHERE nssf_enrolled=1").fetchall()
    conn.close()
    return {r['id']: {'enrolled': True} for r in rows}

def save_nssf_enrollment(data_folder, employee_id, enrolled):
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO employees (id, nssf_enrolled) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET nssf_enrolled=?",
        (employee_id, 1 if enrolled else 0, 1 if enrolled else 0)
    )
    conn.commit()
    conn.close()


# ── 计算参数 settings ─────────────────────────

def load_config(data_folder):
    conn = get_conn(data_folder)
    row = conn.execute("SELECT value FROM settings WHERE key='config'").fetchone()
    conn.close()
    if row:
        return json.loads(row['value'])
    # 返回默认值
    return {
        'underground_prices': {'NICKEL（H）': 6000, 'NICKEL（L）': 5000, 'MAWE': 4000},
        'driller_prices': {'NICKEL（H）': 5000, 'NICKEL（L）': 4000, 'MAWE': 3000},
        'crush_price': 300,
        'nssf_rate': 0.10,
    }

def save_config(data_folder, config):
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('config', ?) ON CONFLICT(key) DO UPDATE SET value=?",
        (json.dumps(config), json.dumps(config))
    )
    conn.commit()
    conn.close()
    return True


# ── 出勤覆盖 attendance ──────────────────────

def load_attendance_overrides(data_folder):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM attendance_overrides").fetchall()
    conn.close()
    result = {}
    for r in rows:
        key = f"{r['employee_id']}|{r['date']}"
        result[key] = r['status']
    return result

def save_attendance_override(data_folder, employee_id, date, status):
    """保存手动出勤标记：P出勤 A旷工 L请假"""
    if status == '' or status == 'R':
        # 空值 = 复位：删除手动覆盖，恢复自动
        return delete_attendance_override(data_folder, employee_id, date)
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO attendance_overrides (employee_id, date, status) VALUES (?,?,?) ON CONFLICT(employee_id,date) DO UPDATE SET status=?",
        (employee_id, date, status, status)
    )
    conn.commit()
    conn.close()

def delete_attendance_override(data_folder, employee_id, date):
    """删除某人的某天手动覆盖记录"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM attendance_overrides WHERE employee_id=? AND date=?", (employee_id, date))
    conn.commit()
    conn.close()

# ── 审计日志 ──────────────────────────────────

def log_audit(data_folder, action, employee_id='', detail='{}'):
    """写入一条审计日志（UTC+3 坦桑尼亚时间）"""
    from datetime import datetime, timezone, timedelta
    tz_tz = timezone(timedelta(hours=3))
    now = datetime.now(tz_tz).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO audit_log (timestamp, action, employee_id, detail) VALUES (?,?,?,?)",
        (now, action, employee_id, detail)
    )
    conn.commit()
    conn.close()

# ── 手动加入计件分配 ──────────────────────

def save_shift_addition(data_folder, employee_id, date, shift):
    """手动加入井下计件：白班(D)/夜班(N)"""
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT OR REPLACE INTO shift_additions (employee_id, date, shift) VALUES (?,?,?)",
        (employee_id, date, shift)
    )
    conn.commit()
    conn.close()

def remove_shift_addition(data_folder, employee_id, date):
    """删除手动加入记录"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM shift_additions WHERE employee_id=? AND date=?", (employee_id, date))
    conn.commit()
    conn.close()

def load_shift_additions(data_folder):
    """加载所有手动加入的井下记录"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM shift_additions").fetchall()
    conn.close()
    return {(r['employee_id'], r['date']): r['shift'] for r in rows}

def save_driller_addition(data_folder, employee_id, date, captain):
    """手动加入钻工组"""
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT OR REPLACE INTO driller_additions (employee_id, date, captain) VALUES (?,?,?)",
        (employee_id, date, captain)
    )
    conn.commit()
    conn.close()

def remove_driller_addition(data_folder, employee_id, date):
    """删除手动加入钻工组记录"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM driller_additions WHERE employee_id=? AND date=?", (employee_id, date))
    conn.commit()
    conn.close()

def load_driller_additions(data_folder):
    """加载所有手动加入的钻工记录"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM driller_additions").fetchall()
    conn.close()
    return {(r['employee_id'], r['date']): r['captain'] for r in rows}

# ── 奖金/罚款 ──────────────────────────────────

def load_bonus_penalties(data_folder, month):
    """加载指定月份的奖金/罚款数据 → {employee_id: {bonus: int, penalty: int}}"""
    if not month:
        return {}
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM bonus_penalties WHERE month=?", (month,)).fetchall()
    conn.close()
    return {r['employee_id']: {'bonus': r['bonus'], 'penalty': r['penalty']} for r in rows}

def save_bonus_penalty(data_folder, employee_id, month, bonus, penalty):
    """保存单个员工的奖金/罚款"""
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO bonus_penalties (employee_id, month, bonus, penalty) VALUES (?,?,?,?) "
        "ON CONFLICT(employee_id,month) DO UPDATE SET bonus=?, penalty=?",
        (employee_id, month, bonus or 0, penalty or 0, bonus or 0, penalty or 0)
    )
    conn.commit()
    conn.close()

def get_audit_logs(data_folder, limit=200):
    """取最近的审计日志"""
    conn = get_conn(data_folder)
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── 每月工资结果 ──────────────────────────────

def save_monthly_result(data_folder, month, result):
    """保存一整个月的工资结果到 monthly_data（覆盖旧版）"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM monthly_data WHERE month=?", (month,))
    for emp in result.get('employees', []):
        conn.execute(
            """INSERT INTO monthly_data (month, employee_id, salary_type,
               piece_underground, piece_driller, piece_crush, day_rate, monthly,
               gross, advance, nssf, net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (month, emp.get('employee_id') or emp.get('name',''), emp.get('salary_type',''),
             emp.get('piece_underground',0), emp.get('piece_driller',0),
             emp.get('piece_crush',0),
             emp.get('day_rate',0), emp.get('monthly',0),
             emp.get('gross',0), emp.get('advance',0),
             emp.get('nssf',0), emp.get('net',0))
        )
    conn.commit()
    conn.close()

def list_monthly_months(data_folder):
    """返回 DB 中已有的月份列表"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT DISTINCT month FROM monthly_data ORDER BY month DESC").fetchall()
    conn.close()
    return [r['month'] for r in rows]

# ── 离职员工管理 ──────────────────────────

def load_dismissed(data_folder):
    """返回已离职员工 ID 集合"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT employee_id FROM dismissed_employees").fetchall()
    conn.close()
    return {r['employee_id'] for r in rows}

def dismiss_employee(data_folder, employee_id, note=''):
    """标记员工为离职"""
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT OR REPLACE INTO dismissed_employees (employee_id, note, dismissed_at) VALUES (?,?,datetime('now','localtime'))",
        (employee_id, note)
    )
    conn.commit()
    conn.close()

def restore_employee(data_folder, employee_id):
    """恢复已离职员工"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM dismissed_employees WHERE employee_id=?", (employee_id,))
    conn.commit()
    conn.close()

def load_dismissed_with_info(data_folder):
    """返回已离职员工详情列表"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM dismissed_employees ORDER BY dismissed_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_monthly_result(data_folder, month):
    """从 DB 加载某个月的工资结果"""
    conn = get_conn(data_folder)
    # 加载员工姓名映射
    name_map = {}
    try:
        emp_rows = conn.execute("SELECT id, name FROM employees").fetchall()
        for r in emp_rows:
            name_map[r['id']] = r['name']
    except: pass
    rows = conn.execute("SELECT * FROM monthly_data WHERE month=? ORDER BY net DESC", (month,)).fetchall()
    conn.close()
    if not rows:
        return None
    employees = []
    tg = ta = tn = tnet = 0
    for r in rows:
        eid = r['employee_id']
        name = name_map.get(eid, eid)
        employees.append({
            'name': name, 'employee_id': eid, 'salary_type': r['salary_type'] or '',
            'piece_underground': r['piece_underground'], 'piece_driller': r['piece_driller'],
            'piece_crush': r['piece_crush'], 'day_rate': r['day_rate'], 'monthly': r['monthly'],
            'gross': r['gross'], 'advance': r['advance'],
            'nssf': r['nssf'], 'net': r['net'],
        })
        tg += r['gross']; ta += r['advance']; tn += r['nssf']; tnet += r['net']
    return {'employees': employees, 'total_gross': tg, 'total_advance': ta,
            'total_nssf': tn, 'total_net': tnet, 'duplications': []}

# ── 管理员密码管理 ──────────────────────────────────

def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"

def _verify_password(password, stored_hash):
    salt, h = stored_hash.split(':')
    return hashlib.sha256((salt + password).encode()).hexdigest() == h

def get_user_role(data_folder, username):
    """返回用户的角色: 'super_admin' | 'admin' | 'editor' | 'viewer' | None"""
    conn = get_conn(data_folder)
    row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row['role'] if row else None

ROLE_LEVELS = {'super_admin': 3, 'admin': 2, 'editor': 1, 'viewer': 0}

ROLE_DEFAULT_PERMISSIONS = {
    'super_admin': {'*': ['*']},
    'admin': {
        'dashboard': ['view'],
        'employees': ['view', 'edit'],
        'oa': ['view', 'approve'],
        'attendance': ['view', 'edit'],
        'salary': ['view', 'export'],
        'production': ['view', 'edit'],
        'scoring': ['view', 'edit'],
        'system': ['view'],
    },
    'editor': {
        'dashboard': ['view'],
        'employees': ['view'],
        'oa': ['view'],
        'attendance': ['view', 'edit'],
        'salary': ['view'],
        'production': ['view', 'edit'],
        'scoring': ['view'],
    },
    'viewer': {
        'dashboard': ['view'],
        'salary': ['view'],
    },
}

ALL_MODULES = ['dashboard', 'employees', 'oa', 'attendance', 'salary', 'production', 'scoring', 'system']
ALL_ACTIONS = ['view', 'edit', 'approve', 'export', 'manage']

def init_default_permissions(data_folder):
    """初始化默认权限数据到 permissions 表（幂等）"""
    conn = get_conn(data_folder)
    for role, grants in ROLE_DEFAULT_PERMISSIONS.items():
        for module, actions in grants.items():
            for action in actions:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO permissions (module, action, scope_type, scope_value) VALUES (?,?,?,?)",
                        (module, action, 'all', ''))
                except:
                    pass
    conn.commit()
    conn.close()

def get_permissions(data_folder):
    """查询全部权限定义"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM permissions ORDER BY module, action").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_role_default_grants(role):
    """获取角色默认权限 [{module, actions}]"""
    grants = ROLE_DEFAULT_PERMISSIONS.get(role, {})
    result = []
    for module, actions in grants.items():
        result.append({'module': module, 'actions': actions})
    return result

def get_user_grants(data_folder, username):
    """查询用户单独授权列表"""
    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT g.*, p.module, p.action, p.scope_type, p.scope_value
        FROM user_grants g
        JOIN permissions p ON g.permission_id = p.id
        WHERE g.username = ?
        ORDER BY p.module, p.action
    """, (username,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def grant_user_permission(data_folder, username, module, action, grant_type='allow'):
    """为用户添加单独授权"""
    conn = get_conn(data_folder)
    # 确保 permission 存在
    conn.execute(
        "INSERT OR IGNORE INTO permissions (module, action, scope_type, scope_value) VALUES (?,?,?,?)",
        (module, action, 'all', ''))
    pid = conn.execute(
        "SELECT id FROM permissions WHERE module=? AND action=? AND scope_type='all'",
        (module, action)).fetchone()
    if pid:
        conn.execute(
            "INSERT OR REPLACE INTO user_grants (username, permission_id, grant_type) VALUES (?,?,?)",
            (username, pid['id'], grant_type))
    conn.commit()
    conn.close()

def revoke_user_grant(data_folder, username, permission_id):
    """撤销用户单独授权"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM user_grants WHERE username=? AND permission_id=?",
                 (username, permission_id))
    conn.commit()
    conn.close()

def check_permission(data_folder, username, module, action, scope_value=''):
    """权限检查：角色继承 + 单独授权覆盖"""
    conn = get_conn(data_folder)
    # 查用户角色
    role_row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    if not role_row:
        conn.close()
        return False
    role = role_row['role']

    # super_admin 拥有所有权限
    if role == 'super_admin':
        conn.close()
        return True

    # 1. 查单独授权（deny 优先）
    deny = conn.execute("""
        SELECT 1 FROM user_grants g
        JOIN permissions p ON g.permission_id = p.id
        WHERE g.username=? AND p.module=? AND p.action=? AND g.grant_type='deny'
    """, (username, module, action)).fetchone()
    if deny:
        conn.close()
        return False

    allow = conn.execute("""
        SELECT 1 FROM user_grants g
        JOIN permissions p ON g.permission_id = p.id
        WHERE g.username=? AND p.module=? AND p.action=? AND g.grant_type='allow'
    """, (username, module, action)).fetchone()
    if allow:
        conn.close()
        return True

    # 2. 角色默认权限
    grants = ROLE_DEFAULT_PERMISSIONS.get(role, {})
    # 通配模块 *
    if '*' in grants and '*' in grants['*']:
        conn.close()
        return True
    module_grants = grants.get(module, [])
    if '*' in module_grants:
        conn.close()
        return True
    conn.close()
    return action in module_grants

def get_user_permissions_summary(data_folder, username):
    """获取某用户的完整权限摘要：{module: {view: 'role'|'grant'|'deny', ...}}"""
    conn = get_conn(data_folder)
    role_row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    if not role_row:
        conn.close()
        return None
    role = role_row['role']

    # 角色默认
    role_grants = ROLE_DEFAULT_PERMISSIONS.get(role, {})
    summary = {}
    for module in ALL_MODULES:
        summary[module] = {}
        for action in ALL_ACTIONS:
            if '*' in role_grants and '*' in role_grants['*']:
                summary[module][action] = 'role'
            elif action in role_grants.get(module, []) or '*' in role_grants.get(module, []):
                summary[module][action] = 'role'
            else:
                summary[module][action] = 'none'

    # 单独授权覆盖
    grants = conn.execute("""
        SELECT p.module, p.action, g.grant_type
        FROM user_grants g JOIN permissions p ON g.permission_id = p.id
        WHERE g.username=?
    """, (username,)).fetchall()
    for g in grants:
        if g['module'] in summary and g['action'] in summary[g['module']]:
            summary[g['module']][g['action']] = g['grant_type']
    conn.close()
    return summary

def list_all_users(data_folder):
    """返回所有用户列表 [{username, role, created_at}]"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT username, role, created_at FROM admin_users ORDER BY created_at").fetchall()
    conn.close()
    return [{'username': r['username'], 'role': r['role'], 'created_at': r['created_at']} for r in rows]

def set_user_role(data_folder, username, role):
    """修改用户角色"""
    if role not in ROLE_LEVELS:
        raise ValueError(f'未知角色: {role}')
    conn = get_conn(data_folder)
    conn.execute("UPDATE admin_users SET role=? WHERE username=?", (role, username))
    conn.commit()
    conn.close()

def set_admin_password(data_folder, username, password):
    conn = get_conn(data_folder)
    pwd_hash = _hash_password(password)
    conn.execute("INSERT OR REPLACE INTO admin_users (username, password_hash) VALUES (?, ?)",
                 (username, pwd_hash))
    conn.commit()
    conn.close()

def verify_admin(data_folder, username, password):
    conn = get_conn(data_folder)
    row = conn.execute("SELECT password_hash FROM admin_users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row:
        return False
    return _verify_password(password, row['password_hash'])

def has_admin(data_folder):
    conn = get_conn(data_folder)
    row = conn.execute("SELECT COUNT(*) as cnt FROM admin_users").fetchone()
    conn.close()
    return row['cnt'] > 0


# ── P1: 员工生命周期事件 ─────────────────────

def create_event(data_folder, data):
    """创建 OA 事件，返回 event_id"""
    conn = get_conn(data_folder)
    cur = conn.execute("""
        INSERT INTO employee_events (employee_id, event_type, effective_date,
            snapshot, payload, operator_id, status)
        VALUES (?,?,?,?,?,?,?)
    """, (data['employee_id'], data['event_type'], data['effective_date'],
          data.get('snapshot', '{}'), data.get('payload', '{}'),
          data['operator_id'], data.get('status', 'pending')))
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid

def get_pending_events(data_folder):
    """获取所有待审批事件"""
    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT e.*, em.name as employee_name
        FROM employee_events e
        LEFT JOIN employees em ON e.employee_id = em.id
        WHERE e.status = 'pending'
        ORDER BY e.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_employee_events(data_folder, employee_id):
    """获取某员工的所有生命周期事件（按时间倒序）"""
    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT * FROM employee_events
        WHERE employee_id = ?
        ORDER BY effective_date DESC, created_at DESC
    """, (employee_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def approve_event(data_folder, event_id, approved_by):
    """批准事件：更新 status + approved_by"""
    conn = get_conn(data_folder)
    conn.execute("""
        UPDATE employee_events
        SET status='approved', approved_by=?, updated_at=datetime('now','localtime')
        WHERE id=? AND status='pending'
    """, (approved_by, event_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0

def reject_event(data_folder, event_id, rejected_by, reason):
    """驳回事件"""
    conn = get_conn(data_folder)
    conn.execute("""
        UPDATE employee_events
        SET status='rejected', rejected_by=?, reject_reason=?,
            updated_at=datetime('now','localtime')
        WHERE id=? AND status='pending'
    """, (rejected_by, reason, event_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0

def get_event(data_folder, event_id):
    """获取单个事件详情"""
    conn = get_conn(data_folder)
    row = conn.execute("SELECT * FROM employee_events WHERE id=?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── P1: 员工档案扩展查询 ───────────────────

def get_employee_profile(data_folder, employee_id):
    """获取员工完整档案：基本信息 + 事件数 + 请假数"""
    conn = get_conn(data_folder)
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    if not emp:
        conn.close()
        return None
    # 统计事件和请假数
    event_count = conn.execute(
        "SELECT COUNT(*) FROM employee_events WHERE employee_id=?", (employee_id,)
    ).fetchone()[0]
    leave_count = conn.execute(
        "SELECT COUNT(*) FROM leave_requests WHERE employee_id=?"
    ).fetchone()[0] if _table_exists(conn, 'leave_requests') else 0
    conn.close()
    return {**dict(emp), 'event_count': event_count, 'leave_count': leave_count}

def update_employee_fields(data_folder, employee_id, fields):
    """更新员工扩展字段（position/skill_level/hire_date/nida_*/nssf_*/bank_*）"""
    allowed = {'position', 'skill_level', 'hire_date', 'nida_number',
               'nssf_number', 'bank_name', 'bank_account', 'bank_owner',
               'phone', 'note', 'status', 'dismissed_at', 'custom_fields'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    conn = get_conn(data_folder)
    sets = ', '.join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [employee_id]
    conn.execute(f"UPDATE employees SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return True

def list_employees_extended(data_folder, status_filter=None, department=None):
    """返回扩展员工列表（含新列）"""
    conn = get_conn(data_folder)
    sql = "SELECT * FROM employees WHERE 1=1"
    params = []
    if status_filter:
        sql += " AND status=?"
        params.append(status_filter)
    if department:
        sql += " AND department=?"
        params.append(department)
    sql += " ORDER BY name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _table_exists(conn, table):
    """检查表是否存在"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return bool(row)


# ── P2: 假期余额 ─────────────────────

def get_leave_balance(data_folder, employee_id, year):
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND year=?",
        (employee_id, year)).fetchone()
    conn.close()
    if not row:
        return {
            'annual_entitled': 28, 'annual_used': 0,
            'comp_entitled': 0, 'comp_used': 0
        }
    return dict(row)

def add_leave_balance(data_folder, employee_id, year, annual=0, comp=0):
    conn = get_conn(data_folder)
    conn.execute("""
        INSERT INTO leave_balances (employee_id, year, annual_entitled, comp_entitled)
        VALUES (?,?,?,?)
        ON CONFLICT(employee_id, year) DO UPDATE SET
            annual_entitled=annual_entitled+?,
            comp_entitled=comp_entitled+?,
            updated_at=datetime('now','localtime')
    """, (employee_id, year, annual, comp, annual, comp))
    conn.commit()
    conn.close()

def deduct_annual_leave(data_folder, employee_id, year, days):
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT annual_entitled, annual_used FROM leave_balances WHERE employee_id=? AND year=?",
        (employee_id, year)).fetchone()
    if not row or (row['annual_entitled'] - row['annual_used']) < days:
        conn.close()
        return False
    conn.execute("""
        UPDATE leave_balances SET annual_used=annual_used+?,
            updated_at=datetime('now','localtime')
        WHERE employee_id=? AND year=?
    """, (days, employee_id, year))
    conn.commit()
    conn.close()
    return True

def deduct_comp_leave(data_folder, employee_id, year, days):
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT comp_entitled, comp_used FROM leave_balances WHERE employee_id=? AND year=?",
        (employee_id, year)).fetchone()
    if not row or (row['comp_entitled'] - row['comp_used']) < days:
        conn.close()
        return False
    conn.execute("""
        UPDATE leave_balances SET comp_used=comp_used+?,
            updated_at=datetime('now','localtime')
        WHERE employee_id=? AND year=?
    """, (days, employee_id, year))
    conn.commit()
    conn.close()
    return True


# ── P2: 年假资格校验 ────────────────

def check_annual_leave_eligible(data_folder, employee_id):
    conn = get_conn(data_folder)
    emp = conn.execute(
        "SELECT nssf_enrolled, nida_number, hire_date FROM employees WHERE id=?",
        (employee_id,)).fetchone()
    conn.close()
    reasons = []
    if not emp:
        return {'eligible': False, 'reasons': ['员工不存在']}
    if not emp['nssf_enrolled']:
        reasons.append('未参加NSSF')
    if not emp['nida_number']:
        reasons.append('NIDA证件号为空')
    if emp['hire_date']:
        import datetime
        try:
            hd = datetime.datetime.strptime(emp['hire_date'], '%Y-%m-%d')
            if (datetime.datetime.now() - hd).days < 365:
                reasons.append('入职不满1年({}天)'.format((datetime.datetime.now() - hd).days))
        except:
            reasons.append('入职日期格式无效')
    else:
        reasons.append('入职日期为空')
    return {'eligible': len(reasons) == 0, 'reasons': reasons}


# ── P2: 司机名单 ────────────────────

def is_driver(data_folder, employee_id):
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT 1 FROM driver_roster WHERE employee_id=?", (employee_id,)).fetchone()
    conn.close()
    return bool(row)

def list_drivers(data_folder):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM driver_roster").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_driver(data_folder, employee_id, allowance=5000, note=''):
    conn = get_conn(data_folder)
    conn.execute("""
        INSERT OR REPLACE INTO driver_roster (employee_id, allowance_per_day, note)
        VALUES (?,?,?)
    """, (employee_id, allowance, note))
    conn.commit()
    conn.close()


# ── P3: 评分计算引擎 ──────────────────

def submit_scoring_card(data_folder, week, team, card_no, source, entries):
    conn = get_conn(data_folder)
    cur = conn.execute(
        "INSERT INTO scoring_cards (week, team, card_no, source) VALUES (?,?,?,?)",
        (week, team, card_no, source))
    card_id = cur.lastrowid
    for e in entries:
        conn.execute("""
            INSERT INTO scoring_entries (card_id, target_wid, target_employee_id,
                initiative, diligence, discipline, cooperation, safety, driving)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (card_id, e['wid'], e['employee_id'],
              e.get('initiative', 0), e.get('diligence', 0),
              e.get('discipline', 0), e.get('cooperation', 0),
              e.get('safety', 0), e.get('driving')))
    conn.commit()
    conn.close()
    return card_id

def get_week_cards(data_folder, team, week):
    conn = get_conn(data_folder)
    cards = conn.execute(
        "SELECT * FROM scoring_cards WHERE team=? AND week=? ORDER BY source, card_no",
        (team, week)).fetchall()
    result = []
    for c in cards:
        entries = conn.execute(
            "SELECT * FROM scoring_entries WHERE card_id=?", (c['id'],)).fetchall()
        result.append({**dict(c), 'entries': [dict(e) for e in entries]})
    conn.close()
    return result

def get_all_scoring_entries(data_folder, team):
    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT se.*, sc.week, sc.source FROM scoring_entries se
        JOIN scoring_cards sc ON se.card_id = sc.id
        WHERE sc.team=? ORDER BY sc.week, sc.source, se.target_wid
    """, (team,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_objective_entry(data_folder, record_date, team, planned, actual, total_h, effective_h, week):
    conn = get_conn(data_folder)
    r1 = (actual / planned * 100) if planned > 0 else 0
    r2 = min((effective_h / total_h * 100) if total_h > 0 else 0, 100)
    daily_s = (r1 * 0.7 + r2 * 0.3) if planned > 0 else (r2 * 0.3)
    conn.execute("""
        INSERT OR REPLACE INTO objective_records (record_date, team, planned_output,
            actual_output, total_hours, effective_hours, week, daily_s)
        VALUES (?,?,?,?,?,?,?,?)
    """, (record_date, team, planned, actual, total_h, effective_h, week, round(daily_s, 2)))
    conn.commit()
    conn.close()
    return daily_s

def get_objective_records(data_folder, team):
    conn = get_conn(data_folder)
    rows = conn.execute(
        "SELECT * FROM objective_records WHERE team=? ORDER BY record_date", (team,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_monthly_objective(data_folder, team):
    rows = get_objective_records(data_folder, team)
    if not rows:
        return {'monthly_s': 0, 'distribution_ratio': 0.7, 'planned_sum': 0, 'actual_sum': 0}
    monthly_s = sum(r['daily_s'] for r in rows) / max(len(rows), 1)
    if monthly_s >= 95: ratio = 1.0
    elif monthly_s >= 85: ratio = 0.95
    elif monthly_s >= 75: ratio = 0.9
    elif monthly_s >= 65: ratio = 0.85
    elif monthly_s >= 55: ratio = 0.8
    else: ratio = 0.7
    return {'monthly_s': round(monthly_s, 2), 'distribution_ratio': ratio,
            'planned_sum': sum(r['planned_output'] for r in rows),
            'actual_sum': sum(r['actual_output'] for r in rows)}

def get_scoring_config(data_folder):
    conn = get_conn(data_folder)
    defaults = {'mgmt_vote_weight': 1.5, 'mgmt_deviation_threshold': 15,
                'zero_variance_threshold': 8, 'max_tier_ratio': 0.3}
    config = {}
    for k in defaults:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        config[k] = float(row['value']) if row and row['value'] else defaults[k]
    conn.close()
    return config

def save_scoring_config(data_folder, data):
    conn = get_conn(data_folder)
    allowed = ['mgmt_vote_weight', 'mgmt_deviation_threshold', 'zero_variance_threshold', 'max_tier_ratio']
    for k, v in data.items():
        if k in allowed:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, str(v)))
    conn.commit()
    conn.close()


# ── P4: 全局搜索 ──────────────────

def search_all(data_folder, query, scope='all'):
    """跨表模糊搜索，返回 [{type, id, title, subtitle, url}]，最多30条"""
    conn = get_conn(data_folder)
    results = []
    q = f'%{query}%'

    if scope in ('all', 'employees'):
        rows = conn.execute(
            "SELECT id, name, department, default_type FROM employees "
            "WHERE name LIKE ? OR department LIKE ? OR id LIKE ? LIMIT 20",
            (q, q, q)).fetchall()
        for r in rows:
            results.append({
                'type': 'employee', 'id': r['id'],
                'title': r['name'],
                'subtitle': f"{r['department']} - {r['default_type']}",
                'url': f'#employees/profile?id={r["id"]}'
            })

    if scope in ('all', 'attendance'):
        rows = conn.execute(
            "SELECT DISTINCT employee_id, date FROM attendance_overrides "
            "WHERE employee_id LIKE ? OR date LIKE ? OR status LIKE ? LIMIT 20",
            (q, q, q)).fetchall()
        for r in rows:
            results.append({
                'type': 'attendance', 'id': r['employee_id'],
                'title': f"出勤 - {r['employee_id']}",
                'subtitle': r['date'],
                'url': '#attendance'
            })

    if scope in ('all', 'salary'):
        rows = conn.execute(
            "SELECT employee_id, month, gross, net FROM monthly_data "
            "WHERE employee_id LIKE ? OR month LIKE ? LIMIT 20",
            (q, q)).fetchall()
        for r in rows:
            results.append({
                'type': 'salary', 'id': r['employee_id'],
                'title': f"{r['month']} 薪资 - {r['employee_id']}",
                'subtitle': f"应发: {r['gross']:,.0f} 实发: {r['net']:,.0f}" if r['gross'] is not None else '—',
                'url': '#salary/table'
            })

    if scope in ('all', 'production'):
        for table, label_prefix in [('shift_additions', '井下'), ('driller_additions', '钻工')]:
            try:
                rows = conn.execute(
                    f"SELECT DISTINCT employee_id, date FROM {table} "
                    "WHERE employee_id LIKE ? OR date LIKE ? LIMIT 10",
                    (q, q)).fetchall()
                for r in rows:
                    results.append({
                        'type': 'production', 'id': r['employee_id'],
                        'title': f"{label_prefix}产量 - {r['employee_id']}",
                        'subtitle': r['date'],
                        'url': '#production/underground'
                    })
            except:
                pass

    conn.close()
    return results[:30]


# ── P4: 表单自定义 ──────────────────

def list_form_schemas(data_folder):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM form_schemas ORDER BY created_at").fetchall()
    # 为每个 schema 附加字段数
    result = []
    for r in rows:
        cnt = conn.execute("SELECT COUNT(*) FROM form_fields WHERE schema_id=?", (r['id'],)).fetchone()[0]
        result.append({**dict(r), 'field_count': cnt})
    conn.close()
    return result

def get_form_schema(data_folder, schema_id):
    conn = get_conn(data_folder)
    schema = conn.execute("SELECT * FROM form_schemas WHERE id=?", (schema_id,)).fetchone()
    if not schema:
        conn.close()
        return None
    fields = conn.execute(
        "SELECT * FROM form_fields WHERE schema_id=? ORDER BY sort_order",
        (schema_id,)).fetchall()
    conn.close()
    return {**dict(schema), 'fields': [dict(f) for f in fields]}

def create_form_schema(data_folder, data):
    conn = get_conn(data_folder)
    cur = conn.execute(
        "INSERT INTO form_schemas (name, description, table_name) VALUES (?,?,?)",
        (data['name'], data.get('description', ''), data.get('table_name', '')))
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid

def update_form_schema(data_folder, schema_id, data):
    conn = get_conn(data_folder)
    sets = []
    vals = []
    for k in ['name', 'description', 'table_name']:
        if k in data:
            sets.append(f"{k}=?")
            vals.append(data[k])
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        vals.append(schema_id)
        conn.execute(f"UPDATE form_schemas SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()

def delete_form_schema(data_folder, schema_id):
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM form_fields WHERE schema_id=?", (schema_id,))
    conn.execute("DELETE FROM form_schemas WHERE id=?", (schema_id,))
    conn.commit()
    conn.close()

def add_form_field(data_folder, schema_id, data):
    conn = get_conn(data_folder)
    conn.execute("""
        INSERT INTO form_fields (schema_id, field_key, field_type, label_zh, label_en,
            options, placeholder_zh, placeholder_en, required, visible_roles,
            sort_order, is_custom, default_value)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (schema_id, data['field_key'], data.get('field_type', 'text'),
          data.get('label_zh', ''), data.get('label_en', ''),
          json.dumps(data.get('options', [])),
          data.get('placeholder_zh', ''), data.get('placeholder_en', ''),
          data.get('required', 0), json.dumps(data.get('visible_roles', [])),
          data.get('sort_order', 0), data.get('is_custom', 0),
          data.get('default_value', '')))
    conn.commit()
    conn.close()

def update_form_field(data_folder, field_id, data):
    conn = get_conn(data_folder)
    sets = []
    vals = []
    for k in ['field_key', 'field_type', 'label_zh', 'label_en', 'placeholder_zh',
              'placeholder_en', 'required', 'sort_order', 'is_custom', 'default_value']:
        if k in data:
            sets.append(f"{k}=?")
            vals.append(data[k])
    if 'options' in data:
        sets.append("options=?")
        vals.append(json.dumps(data['options']))
    if 'visible_roles' in data:
        sets.append("visible_roles=?")
        vals.append(json.dumps(data['visible_roles']))
    if sets:
        vals.append(field_id)
        conn.execute(f"UPDATE form_fields SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()

def delete_form_field(data_folder, field_id):
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM form_fields WHERE id=?", (field_id,))
    conn.commit()
    conn.close()

def seed_default_forms(data_folder):
    """初始化预设表单（入职/档案编辑），幂等"""
    conn = get_conn(data_folder)
    # 检查是否已有表单
    count = conn.execute("SELECT COUNT(*) FROM form_schemas").fetchone()[0]
    if count > 0:
        conn.close()
        return

    # 入职表单
    conn.execute("INSERT INTO form_schemas (name, description, table_name) VALUES (?,?,?)",
                 ('employee_onboarding', '员工入职表单', 'employees'))
    sid = conn.execute("SELECT id FROM form_schemas WHERE name='employee_onboarding'").fetchone()['id']

    onboarding_fields = [
        ('name', 'text', '姓名', 'Name', 1, 1),
        ('department', 'text', '部门', 'Department', 1, 2),
        ('position', 'text', '岗位', 'Position', 0, 3),
        ('hire_date', 'date', '入职日期', 'Hire Date', 1, 4),
        ('nida_number', 'text', 'NIDA 证件号', 'NIDA Number', 0, 5),
        ('nssf_number', 'text', 'NSSF 社保号', 'NSSF Number', 0, 6),
        ('phone', 'text', '电话', 'Phone', 0, 7),
        ('bank_name', 'text', '银行名称', 'Bank Name', 0, 8),
        ('bank_account', 'text', '银行账号', 'Bank Account', 0, 9),
        ('bank_owner', 'text', '户名', 'Account Owner', 0, 10),
        ('default_type', 'select', '薪资类型', 'Salary Type', 1, 11),
        ('day_rate', 'number', '日薪基数', 'Day Rate', 0, 12),
        ('monthly_salary', 'number', '月薪基数', 'Monthly Salary', 0, 13),
    ]
    for f_key, f_type, lzh, len_val, req, order in onboarding_fields:
        options = '[]'
        df = ''
        if f_key == 'default_type':
            options = json.dumps(['day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'])
            df = 'day_rate'
        conn.execute("""
            INSERT INTO form_fields (schema_id, field_key, field_type, label_zh, label_en,
                options, required, sort_order, is_custom, default_value)
            VALUES (?,?,?,?,?,?,?,?,0,?)
        """, (sid, f_key, f_type, lzh, len_val, options, req, order, df))

    # 档案编辑表单
    conn.execute("INSERT INTO form_schemas (name, description, table_name) VALUES (?,?,?)",
                 ('employee_profile', '员工档案编辑', 'employees'))
    sid2 = conn.execute("SELECT id FROM form_schemas WHERE name='employee_profile'").fetchone()['id']

    profile_fields = onboarding_fields + [
        ('skill_level', 'text', '技能等级', 'Skill Level', 0, 14),
        ('status', 'select', '状态', 'Status', 1, 15),
        ('custom_fields', 'text', '自定义字段(JSON)', 'Custom Fields', 0, 16),
    ]
    for f_key, f_type, lzh, len_val, req, order in profile_fields:
        options = '[]'
        df = ''
        if f_key == 'default_type':
            options = json.dumps(['day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'])
            df = 'day_rate'
        elif f_key == 'status':
            options = json.dumps(['active', 'inactive'])
            df = 'active'
        conn.execute("""
            INSERT INTO form_fields (schema_id, field_key, field_type, label_zh, label_en,
                options, required, sort_order, is_custom, default_value)
            VALUES (?,?,?,?,?,?,?,?,0,?)
        """, (sid2, f_key, f_type, lzh, len_val, options, req, order, df))

    conn.commit()
    conn.close()
