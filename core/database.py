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

def load_overrides(data_folder):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM overrides ORDER BY id").fetchall()
    conn.close()
    result = {}
    for r in rows:
        eid = r['employee_id']
        if eid not in result:
            result[eid] = []
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
        })
    return result

def save_override(data_folder, data):
    conn = get_conn(data_folder)
    eid = data.get('employee_id', '')
    st = data.get('salary_type', '')
    tp = data.get('type', '')
    action = data.get('action', 'add')
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
            # 永久设置（无日期区间）：按 employee_id + salary_type 去重，不影响临时例外
            conn.execute("DELETE FROM overrides WHERE employee_id=? AND salary_type=? AND type=?",
                         (eid, st, tp))
            conn.execute("DELETE FROM overrides WHERE employee_id=? AND type='' AND start_date='' AND salary_type!=?",
                         (eid, st))

    conn.execute(
        "INSERT INTO overrides (employee_id, salary_type, day_rate, monthly_salary, start_date, end_date, note, type, shift, captain) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (eid, st, data.get('day_rate',0), data.get('monthly_salary',0),
         start, data.get('end_date',''), data.get('note',''), tp,
         data.get('shift',''), data.get('captain',''))
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
