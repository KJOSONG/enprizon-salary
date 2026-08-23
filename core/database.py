"""
SQLite 数据库层 — 统一持久化
替代所有 JSON 文件
"""
import json, os, sqlite3, hashlib, hmac, secrets

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
            is_driver INTEGER DEFAULT 0,
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
            paye REAL DEFAULT 0,
            net REAL DEFAULT 0,
            PRIMARY KEY (month, employee_id)
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_month ON monthly_data(month);
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
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
    # PAYE: 新增 paye 列到 monthly_data
    try:
        conn.execute("ALTER TABLE monthly_data ADD COLUMN paye REAL DEFAULT 0")
    except: pass
    # V2 piecework: 持久化 unscaled base 和缩放系数
    try:
        conn.execute("ALTER TABLE monthly_data ADD COLUMN ug_base REAL DEFAULT 0")
    except: pass
    try:
        conn.execute("ALTER TABLE monthly_data ADD COLUMN ug_coefficient REAL DEFAULT 1.0")
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
        # P7: 员工档案字段扩展
        ('gender', 'TEXT DEFAULT \'\''),
        ('date_of_birth', 'TEXT DEFAULT \'\''),
        ('avatar_path', 'TEXT DEFAULT \'\''),
        # P10: 评分班组
        ('custom_number', 'TEXT DEFAULT \'\''),
        ('team_id', 'INTEGER DEFAULT 0'),
        # 档案别名
        ('alias', 'TEXT DEFAULT \'\''),
        # P20: 年假资格豁免（开启后绕过 NSSF + NIDA 检查，仅 OA 审批人可改）
        ('annual_leave_override', 'INTEGER DEFAULT 0'),
        # P21 R3: TIN 号码（年假资格检查要求有值）
        ('tin_number', 'TEXT DEFAULT \'\''),
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
            dismissed_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
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
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            FOREIGN KEY (username) REFERENCES admin_users(username),
            FOREIGN KEY (permission_id) REFERENCES permissions(id),
            UNIQUE(username, permission_id)
        );
        CREATE TABLE IF NOT EXISTS role_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            module TEXT NOT NULL,
            action TEXT NOT NULL,
            allow INTEGER NOT NULL DEFAULT 1,
            UNIQUE(role, module, action)
        );
        CREATE TABLE IF NOT EXISTS employee_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            snapshot TEXT NOT NULL DEFAULT '{}',
            payload TEXT NOT NULL DEFAULT '{}',
            operator_id TEXT NOT NULL,
            approver TEXT DEFAULT '',
            approved_by TEXT DEFAULT '',
            rejected_by TEXT DEFAULT '',
            reject_reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
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
            sick_entitled INTEGER DEFAULT 14,
            sick_used INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now','+3 hours')),
            PRIMARY KEY (employee_id, year)
        );
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            leave_type TEXT NOT NULL DEFAULT 'casual',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days INTEGER DEFAULT 1,
            reason TEXT DEFAULT '',
            submitted_by TEXT NOT NULL DEFAULT '',
            reviewer TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            approved_by TEXT DEFAULT '',
            rejected_by TEXT DEFAULT '',
            reject_reason TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
        );
        CREATE INDEX IF NOT EXISTS idx_leave_employee ON leave_requests(employee_id);
        CREATE INDEX IF NOT EXISTS idx_leave_status ON leave_requests(status);
        CREATE TABLE IF NOT EXISTS overtime_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL DEFAULT '',
            end_time TEXT NOT NULL DEFAULT '',
            hours REAL NOT NULL DEFAULT 0,
            amount REAL NOT NULL DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
        );
        CREATE INDEX IF NOT EXISTS idx_overtime_emp ON overtime_records(employee_id, date);
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
            month TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','+3 hours')),
            UNIQUE(week, team, card_no, source, month)
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
        CREATE TABLE IF NOT EXISTS scoring_card_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            card_no TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '工友',
            subject_employee_id TEXT NOT NULL,
            subject_name TEXT,
            initiative INTEGER,
            diligence INTEGER,
            discipline INTEGER,
            cooperation INTEGER,
            safety INTEGER,
            driving INTEGER,
            operator_id TEXT,
            submitted_at TEXT DEFAULT (datetime('now','+3 hours')),
            month TEXT DEFAULT '',
            UNIQUE(week, team_id, card_no, source, month, subject_employee_id)
        );
        CREATE INDEX IF NOT EXISTS idx_sce_team_week ON scoring_card_entries(team_id, week);
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
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
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
    # P8: 旧库 leave_balances 补病假额度列
    for col in ['sick_entitled INTEGER DEFAULT 14', 'sick_used INTEGER DEFAULT 0']:
        try:
            conn.execute(f"ALTER TABLE leave_balances ADD COLUMN {col}")
        except: pass
    # P11: 旧库 attendance_overrides 补 is_driver 列
    try:
        conn.execute("ALTER TABLE attendance_overrides ADD COLUMN is_driver INTEGER DEFAULT 0")
    except: pass
    # P10: 旧库 scoring_cards 补 month 列
    try:
        conn.execute("ALTER TABLE scoring_cards ADD COLUMN month TEXT DEFAULT ''")
    except: pass
    # P10-fix: UNIQUE 约束缺 month → 跨月评分冲突；重建表（保留数据）
    try:
        _sc_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='scoring_cards'").fetchone()
        _sc_ddl = _sc_sql['sql'] if _sc_sql else ''
        _uniq_idx = _sc_ddl.find('UNIQUE')
        _uniq_txt = _sc_ddl[_uniq_idx:] if _uniq_idx >= 0 else ''
        if 'month' not in _uniq_txt:
            conn.executescript("""
                CREATE TABLE scoring_cards_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week INTEGER NOT NULL,
                    team INTEGER NOT NULL,
                    card_no TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '工友',
                    month TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','+3 hours')),
                    UNIQUE(week, team, card_no, source, month)
                );
                INSERT INTO scoring_cards_new (id, week, team, card_no, source, month, created_at)
                    SELECT id, week, team, card_no, source, COALESCE(month,''), created_at FROM scoring_cards;
                DROP TABLE scoring_cards;
                ALTER TABLE scoring_cards_new RENAME TO scoring_cards;
            """)
    except Exception as _e:
        pass
    # P15: scoring_card_entries 加 month 列 + 重建 UNIQUE（含 month），仿 scoring_cards P10-fix
    try:
        conn.execute("ALTER TABLE scoring_card_entries ADD COLUMN month TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # 列已存在则跳过
    try:
        _sce_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='scoring_card_entries'").fetchone()
        _sce_ddl = _sce_sql['sql'] if _sce_sql else ''
        _sce_uniq_idx = _sce_ddl.find('UNIQUE')
        _sce_uniq_txt = _sce_ddl[_sce_uniq_idx:] if _sce_uniq_idx >= 0 else ''
        if 'month' not in _sce_uniq_txt:
            conn.executescript("""
                CREATE TABLE scoring_card_entries_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    card_no TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '工友',
                    subject_employee_id TEXT NOT NULL,
                    subject_name TEXT,
                    initiative INTEGER,
                    diligence INTEGER,
                    discipline INTEGER,
                    cooperation INTEGER,
                    safety INTEGER,
                    driving INTEGER,
                    operator_id TEXT,
                    submitted_at TEXT DEFAULT (datetime('now','+3 hours')),
                    month TEXT DEFAULT '',
                    UNIQUE(week, team_id, card_no, source, month, subject_employee_id)
                );
                INSERT INTO scoring_card_entries_new
                    (id, week, team_id, card_no, source, subject_employee_id, subject_name,
                     initiative, diligence, discipline, cooperation, safety, driving,
                     operator_id, submitted_at, month)
                    SELECT id, week, team_id, card_no, source, subject_employee_id, subject_name,
                     initiative, diligence, discipline, cooperation, safety, driving,
                     operator_id, submitted_at, COALESCE(month,'') FROM scoring_card_entries;
                DROP TABLE scoring_card_entries;
                ALTER TABLE scoring_card_entries_new RENAME TO scoring_card_entries;
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sce_team_week ON scoring_card_entries(team_id, week)")
    except Exception as _e:
        pass
    # P15: 回填 month = submitted_at 前 7 位（8月 162 行）
    try:
        conn.execute(
            "UPDATE scoring_card_entries SET month=substr(submitted_at,1,7) WHERE month='' OR month IS NULL")
        conn.commit()
    except Exception:
        pass
    # P9: 数据采集提交 + 编辑历史
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS collection_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_type TEXT NOT NULL,
            submission_date TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            operator_id TEXT NOT NULL,
            month TEXT NOT NULL,
            department TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            version INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_cs_month ON collection_submissions(month, form_type);
        CREATE INDEX IF NOT EXISTS idx_cs_date ON collection_submissions(submission_date);
        CREATE TABLE IF NOT EXISTS collection_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            payload TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours')),
            FOREIGN KEY (submission_id) REFERENCES collection_submissions(id)
        );
        CREATE TABLE IF NOT EXISTS employee_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
        );
        CREATE TABLE IF NOT EXISTS driller_captains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
        );
    """)
    # 出勤收集留痕按部门×日期: collection_submissions 加 department 列
    # 旧行 department 留 ''（旧 payload 是混部门合并的，无法准确回填）
    try:
        conn.execute("ALTER TABLE collection_submissions ADD COLUMN department TEXT DEFAULT ''")
    except: pass
    # P10: 种子班组
    conn.execute("INSERT OR IGNORE INTO employee_groups (id, name, description) VALUES (1, 'LAMBA LAMBA', '评分班组 1')")
    conn.execute("INSERT OR IGNORE INTO employee_groups (id, name, description) VALUES (2, 'SAKA SAKA', '评分班组 2')")
    # P12: 种子钻工队长名单（employee_id 优先匹配 employees 表，回退 make_employee_id，再回退姓名）
    try:
        from core.namematch import make_employee_id
        _cap_names = ['BARAKA LAIZER', 'JOHN BOAY BURA', 'SHEDRACK PINIEL LAIZER']
        _cap_eid = {}
        for _r in conn.execute("SELECT id, name FROM employees").fetchall():
            _cap_eid[str(_r['name'] or '').strip().upper()] = _r['id']
        for _i, _nm in enumerate(_cap_names):
            _eid = _cap_eid.get(_nm.strip().upper()) or make_employee_id(_nm) or _nm
            conn.execute(
                "INSERT OR IGNORE INTO driller_captains (employee_id, name, sort_order) VALUES (?,?,?)",
                (_eid, _nm, _i))
    except Exception:
        pass
    # P13: 旧库 employee_events 补 approver 列（兼容迁移）
    try:
        conn.execute("ALTER TABLE employee_events ADD COLUMN approver TEXT DEFAULT ''")
    except Exception:
        pass
    # P21 M4: 撤销事件列（保留原 approved 审计轨迹）
    try:
        conn.execute("ALTER TABLE employee_events ADD COLUMN revoked_by TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE employee_events ADD COLUMN revoked_at TEXT DEFAULT ''")
    except Exception:
        pass
    # P13: 审批人路由表（event_type → 指定审批人，空 = 不指定）
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS approval_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL UNIQUE,
            approver TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','+3 hours'))
        );
    """)
    conn.commit()
    _migrate_json(conn, data_folder)
    _migrate_localtime_timestamps(conn)
    conn.close()

def _migrate_localtime_timestamps(conn, offset_h=None):
    """P26-d: 全表时间戳统一 UTC+3（坦桑尼亚时间）。

    旧版建表 DEFAULT 为 datetime('now','localtime')——在 CST(UTC+8) 服务器上写入的
    时间比 UTC+3 快 5 小时（audit_log 显式 UTC+3 不受影响）。2026-08-14~15 数据库
    曾在本机（UTC+3）运行，该时段行已是正确 EAT，不可平移。
    规则：
      1) 所有 DDL 含 localtime 的表重建：DEFAULT 改 '+3 hours'（幂等，已迁移则跳过）；
      2) 运行机偏移 ≠3h（如服务器 CST）时：存储值按 EAT 解释落在
         EAT_WINDOW=2026-08-14 00:00 ~ 2026-08-15 23:59 之外的行 -5h（服务器写入期）；
      3) 运行机偏移 ==3h（本机 EAT）时：只重建 DDL，不平移数据（本地行均为 EAT）；
      4) audit_log / dismissed_employees / approval_routes：数据由代码显式 UTC+3
         写入，只重建 DDL 不平移。
    offset_h 供测试注入；None 时按运行机实际偏移计算。
    """
    c = conn.cursor()
    if offset_h is None:
        row = c.execute(
            "SELECT (strftime('%s','now','localtime') - strftime('%s','now')) / 3600").fetchone()
        offset_h = int(row[0])
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%localtime%'")]
    if not tables:
        return
    NO_SHIFT_TABLES = {'audit_log', 'dismissed_employees', 'approval_routes'}
    W0, W1 = '2026-08-14 00:00:00', '2026-08-15 23:59:59'
    shifted, rebuilt = [], []
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        for t in tables:
            ddl = c.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
            if not ddl or 'localtime' not in ddl:
                continue
            loc_cols = set()
            for ln in ddl.split('\n'):
                if 'localtime' in ln:
                    loc_cols.add(ln.strip().split()[0].strip('"'))
            new_t = t + '__tz'
            c.execute(f'DROP TABLE IF EXISTS "{new_t}"')
            c.execute(ddl.replace(t, new_t, 1).replace(
                "datetime('now','localtime')", "datetime('now','+3 hours')"))
            names = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")').fetchall()]
            shift_cols = loc_cols if (t not in NO_SHIFT_TABLES and offset_h != 3) else set()
            sel = []
            for nm in names:
                if nm in shift_cols:
                    sel.append(
                        f'CASE WHEN "{nm}" IS NULL OR "{nm}"=\'\' '
                        f'OR ("{nm}" >= \'{W0}\' AND "{nm}" <= \'{W1}\') '
                        f'THEN "{nm}" ELSE datetime("{nm}", \'-5 hours\') END')
                else:
                    sel.append(f'"{nm}"')
            c.execute(
                f'INSERT INTO "{new_t}" ({", ".join(f"\"{n}\"" for n in names)}) '
                f'SELECT {", ".join(sel)} FROM "{t}"')
            idxs = c.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
                "AND sql IS NOT NULL", (t,)).fetchall()
            c.execute(f'DROP TABLE "{t}"')
            c.execute(f'ALTER TABLE "{new_t}" RENAME TO "{t}"')
            for (isql,) in idxs:
                c.execute(isql)
            rebuilt.append(t)
            if shift_cols:
                shifted.append(t)
        conn.execute("COMMIT")
        print(f"[migration] 时区统一 UTC+3: 重建 {len(rebuilt)} 张表 {rebuilt}"
              f"{'，存量 -5h 平移: ' + str(shifted) if shifted else ''}")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass

def _migrate_permissions_v2(data_folder):
    """P29: 权限体系 V2.1 一次性幂等迁移(docs/P29_PERMISSION_V2_SPEC.md §9)

    - settings.perm_v2_migrated=1 已迁移则直接返回(重复启动跳过)
    - 变更前把 permissions/role_permissions/user_grants 三表全量快照写入 audit_log
    - 内置四角色(admin/collector/applicant/viewer)按 V2 预设强制重播种;
      super_admin 硬编码全权限永不落表,不触碰
    - production:view → dashboard:view;production:edit → collection:view+4 表单键(1 行展开 5 行)
      作用于自定义角色/存量 editor 的 role_permissions 与全部 user_grants(deny 行同样平移)
    """
    conn = get_conn(data_folder)
    row = conn.execute("SELECT value FROM settings WHERE key='perm_v2_migrated'").fetchone()
    if row and row['value'] == '1':
        conn.close()
        return
    c = conn.cursor()
    try:
        conn.execute("BEGIN")
        # 1) 三表全量预态快照 → audit_log(UTC+3,与 log_audit 同格式)
        backup = {}
        for t in ('permissions', 'role_permissions', 'user_grants'):
            backup[t] = [dict(r) for r in c.execute(f'SELECT * FROM {t}').fetchall()]
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            "INSERT INTO audit_log (timestamp, action, employee_id, detail) VALUES (?,?,?,?)",
            (now, 'p29_migration_backup', '', json.dumps(backup, ensure_ascii=False)))
        # 2) 内置角色重播种(V2 预设;super_admin 不落表)
        for role in ('admin', 'collector', 'applicant', 'viewer'):
            c.execute("DELETE FROM role_permissions WHERE role=?", (role,))
            for module, actions in ROLE_DEFAULT_PERMISSIONS.get(role, {}).items():
                for action in actions:
                    c.execute(
                        "INSERT OR REPLACE INTO role_permissions (role, module, action, allow) VALUES (?,?,?,1)",
                        (role, module, action))

        # 3) permissions 注册表翻译: find-or-create 去重(INSERT OR IGNORE 后 SELECT id)
        def _find_or_create(module, action):
            c.execute(
                "INSERT OR IGNORE INTO permissions (module, action, scope_type, scope_value) VALUES (?,?,?,?)",
                (module, action, 'all', ''))
            return c.execute(
                "SELECT id FROM permissions WHERE module=? AND action=? AND scope_type='all'",
                (module, action)).fetchone()[0]

        PROD_VIEW_TARGET = ('dashboard', 'view')
        PROD_EDIT_TARGETS = [
            ('collection', 'view'), ('collection', 'underground'), ('collection', 'driller'),
            ('collection', 'crush'), ('collection', 'attendance')]
        # user_grants 平移: view 重指向目标;edit 复制到 5 个目标(同 username+grant_type),然后删源行
        for r in c.execute("SELECT id, action FROM permissions WHERE module='production'").fetchall():
            src_id, act = r[0], r[1]
            if act == 'view':
                targets = [PROD_VIEW_TARGET]
            elif act == 'edit':
                targets = PROD_EDIT_TARGETS
            else:
                targets = []  # 其余 production:* 无等价新键,授权随源行一并删除
            tgt_ids = [_find_or_create(m, a) for m, a in targets]
            grants = c.execute(
                "SELECT username, grant_type FROM user_grants WHERE permission_id=?", (src_id,)).fetchall()
            for g in grants:
                for tid in tgt_ids:
                    c.execute(
                        "INSERT OR IGNORE INTO user_grants (username, permission_id, grant_type) VALUES (?,?,?)",
                        (g[0], tid, g[1]))
            c.execute("DELETE FROM user_grants WHERE permission_id=?", (src_id,))
            c.execute("DELETE FROM permissions WHERE id=?", (src_id,))
        # 4) role_permissions 翻译(非重播种角色: 自定义 + 存量 editor);allow 值保留,已有目标行不覆盖
        for r in c.execute(
                "SELECT id, role, action, allow FROM role_permissions WHERE module='production'").fetchall():
            rid, role, act, allow = r[0], r[1], r[2], r[3]
            if act == 'view':
                targets = [PROD_VIEW_TARGET]
            elif act == 'edit':
                targets = PROD_EDIT_TARGETS
            else:
                targets = []
            for m, a in targets:
                c.execute(
                    "INSERT OR IGNORE INTO role_permissions (role, module, action, allow) VALUES (?,?,?,?)",
                    (role, m, a, allow))
            c.execute("DELETE FROM role_permissions WHERE id=?", (rid,))
        # 5) 标记一次性完成,单次事务提交
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('perm_v2_migrated', '1')")
        conn.execute("COMMIT")
        print('[migration] P29 权限目录 V2.1 迁移完成')
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
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
            # 保留 effective_from 最大的那条；同 effective_from 时优先保留有金额的（day_rate>0 或 monthly_salary>0）；
            # 仍打平（双方都有金额）时保留 id 最大的（最近添加的意图胜出，P26 修复：
            # 旧代码稳定排序保留最早 id，导致 day_rate 永久覆盖掩盖后续 monthly 覆盖）
            perms.sort(key=lambda x: (x['effective_from'],
                                      1 if (x['day_rate'] > 0 or x['monthly_salary'] > 0) else 0,
                                      x['id']), reverse=True)
            keep_id = perms[0]['id']
            result[eid] = [o for o in result[eid] if not (not o['start_date'] and not o['end_date'] and o['salary_type'] and o['type'] != 'exclusion') or o['id'] == keep_id]
    return result


def clear_permanent_overrides(data_folder, employee_id):
    """P26: 删除员工的所有永久覆盖（无日期区间、非排除记录）。

    档案页修改薪资类别时调用——新类型写入 employees.default_type 后，遗留的
    永久覆盖会以 override_type 优先掩盖新类型（计算与档案展示均不生效）。
    临时例外（有日期区间）与排除记录不受影响。
    """
    conn = get_conn(data_folder)
    conn.execute("""
        DELETE FROM overrides
        WHERE employee_id=? AND type != 'exclusion'
          AND (start_date IS NULL OR start_date='')
          AND (end_date IS NULL OR end_date='')
    """, (employee_id,))
    conn.commit()
    conn.close()

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
        cfg = json.loads(row['value'])
        # P15: 新键兜底（旧库 config 无此键时补默认，.get() 双保险）
        cfg.setdefault('scoring_nh_threshold', 600)
        cfg.setdefault('scoring_nh_price', 20000)
        # P23 R2: 加班费参数兜底（旧库 config 无此键时补默认）
        cfg.setdefault('overtime_base', 400000)            # 加班基数 TZS
        cfg.setdefault('overtime_work_days', 26)           # 月工作天数
        cfg.setdefault('overtime_hours_per_day', 8)        # 日工作小时
        cfg.setdefault('overtime_rate', 1.5)               # 加班倍率
        # V2 凸性计件参数兜底
        cfg.setdefault('accel_target', 40)
        cfg.setdefault('accel_prices', {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000})
        cfg.setdefault('accel_w_a', 0.6)
        cfg.setdefault('accel_w_b', 0.4)
        cfg.setdefault('accel_full_days', 26)
        cfg.setdefault('v2_effective_from', '')
        # P28 R7: 井下年假折算月薪基数兜底（旧库无此键时补默认）
        cfg.setdefault('ug_annual_leave_monthly', 400000)
        return cfg
    # 返回默认值
    return {
        'underground_prices': {'NICKEL（H）': 6000, 'NICKEL（L）': 5000, 'MAWE': 4000},
        'driller_prices': {'NICKEL（H）': 5000, 'NICKEL（L）': 4000, 'MAWE': 3000},
        'crush_price': 300,
        'nssf_rate': 0.10,
        'underground_mode': 'piecework',
        'sick_leave_days': 14,
        'scoring_nh_threshold': 600,   # P15: 产量层 NICKEL(H) 门槛（车次）
        'scoring_nh_price': 20000,     # P15: 产量层超门槛单价（TZS/车次）
        'overtime_base': 400000,       # P23 R2: 加班基数 TZS
        'overtime_work_days': 26,      # P23 R2: 月工作天数
        'overtime_hours_per_day': 8,   # P23 R2: 日工作小时
        'overtime_rate': 1.5,          # P23 R2: 加班倍率
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
        'accel_w_a': 0.6,
        'accel_w_b': 0.4,
        'accel_full_days': 26,
        'v2_effective_from': '',
        'ug_annual_leave_monthly': 400000,  # P28 R7: 井下年假折算月薪基数（TZS）
    }

def save_config(data_folder, config):
    mode = config.get('underground_mode', 'piecework')
    if mode not in ('piecework', 'scoring', 'v2'):
        raise ValueError(f"underground_mode must be piecework|scoring|v2, got '{mode}'")
    if 'accel_target' in config:
        at = config['accel_target']
        if not isinstance(at, int) or at <= 0:
            raise ValueError(f"accel_target must be a positive integer, got {at!r}")
    wa = config.get('accel_w_a')
    wb = config.get('accel_w_b')
    if wa is not None and wb is not None and wa <= wb:
        raise ValueError(f"accel_w_a ({wa}) must be > accel_w_b ({wb})")
    if 'accel_prices' in config:
        ap = config['accel_prices']
        required_keys = {'NICKEL（H）', 'NICKEL（L）', 'MAWE'}
        if not required_keys.issubset(ap.keys()):
            missing = required_keys - set(ap.keys())
            raise ValueError(f"accel_prices missing keys: {missing}")
    # P28 R7: 井下年假折算月薪基数必须为正数
    if 'ug_annual_leave_monthly' in config:
        v = config['ug_annual_leave_monthly']
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ValueError(f"ug_annual_leave_monthly must be positive, got {v!r}")
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

# P28 R3: 手动出勤允许状态 = 原有码 − Y + SK（Y 年假手动标记已取消，NU 为唯一年假码且只读）
_ATT_VALID_STATUSES = ('P', 'A', 'L', 'D', 'N', 'B', 'R', 'C', 'S', 'T', 'NU', 'E', 'SK')

def save_attendance_override(data_folder, employee_id, date, status, is_driver=0):
    """保存手动出勤标记：P出勤 A旷工 L请假 T调休 SK病假；P28 R3: 拒绝 Y（年假改 OA 审批落 NU，
    历史 Y 行保留不动）；P11 增 is_driver（0/1，出勤勾选驾驶，旧调用不受影响）"""
    if status == '' or status == 'R':
        # 空值 = 复位：删除手动覆盖，恢复自动
        return delete_attendance_override(data_folder, employee_id, date)
    if status == 'Y':
        raise ValueError("Y（年假手动标记）已取消：请走 OA 年假审批（批准后自动落 NU）")
    if status not in _ATT_VALID_STATUSES:
        raise ValueError(f"无效的出勤状态: {status!r}")
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO attendance_overrides (employee_id, date, status, is_driver) VALUES (?,?,?,?) "
        "ON CONFLICT(employee_id,date) DO UPDATE SET status=?, is_driver=?",
        (employee_id, date, status, 1 if is_driver else 0, status, 1 if is_driver else 0)
    )
    conn.commit()
    conn.close()

def get_attendance_status(data_folder, employee_id, date):
    """P21 R2: 查询某人某天的手动出勤状态（无覆盖返回 ''）"""
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT status FROM attendance_overrides WHERE employee_id=? AND date=?",
        (employee_id, date)).fetchone()
    conn.close()
    return row['status'] if row else ''

def delete_attendance_override(data_folder, employee_id, date):
    """删除某人的某天手动覆盖记录"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM attendance_overrides WHERE employee_id=? AND date=?", (employee_id, date))
    conn.commit()
    conn.close()

def mark_driver_flag(data_folder, employee_id, date):
    """P12: 井下采集勾选驾驶 → 只置 is_driver=1，不覆盖已有 status（A/L 手动标记保留）"""
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT INTO attendance_overrides (employee_id, date, status, is_driver) VALUES (?,?,'P',1) "
        "ON CONFLICT(employee_id,date) DO UPDATE SET is_driver=1",
        (employee_id, date))
    conn.commit()
    conn.close()

def clear_driver_flag(data_folder, employee_id, date):
    """B1b: 清除某人的某天司机标志（is_driver 置 0），供编辑移除驾驶勾选时清理残留"""
    conn = get_conn(data_folder)
    conn.execute("UPDATE attendance_overrides SET is_driver=0 WHERE employee_id=? AND date=?",
                 (employee_id, date))
    conn.commit()
    conn.close()

def clear_driver_flags_for_date(data_folder, date):
    """B1b: 清除某日期所有井下提交的司机标志残留（is_driver 置 0），供全量重建使用"""
    conn = get_conn(data_folder)
    conn.execute("UPDATE attendance_overrides SET is_driver=0 WHERE date=? AND is_driver=1", (date,))
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
               gross, advance, nssf, paye, net, ug_base, ug_coefficient)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (month, emp.get('employee_id') or emp.get('name',''), emp.get('salary_type',''),
             emp.get('piece_underground',0), emp.get('piece_driller',0),
             emp.get('piece_crush',0),
             emp.get('day_rate',0), emp.get('monthly',0),
             emp.get('gross',0), emp.get('advance',0),
             emp.get('nssf',0), emp.get('paye',0), emp.get('net',0),
             emp.get('ug_base',0), emp.get('ug_coefficient',1.0))
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
        "INSERT OR REPLACE INTO dismissed_employees (employee_id, note, dismissed_at) VALUES (?,?,datetime('now','+3 hours'))",
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


def _calc_overtime_hours(start_time, end_time):
    """P23 R2: 加班时长计算（纯函数，后端审批权威兜底）。

    规则：
    - 解析 HH:MM；end < start 视为跨天（次日结束）
    - 跨天: hours = (24h − start) + end；同天: hours = end − start
    - 按 0.5h 一档向下取整（不足半小时不计）
    - hours > 12 视为无效（返回 0）；hours ≤ 0 无效
    示例: 18:00-22:00→4.0；18:00-22:20→4.0；18:00-22:40→4.5；22:00-02:00→4.0；19:30-21:00→1.5
    """
    import math
    try:
        def _parse(t):
            if not t or ':' not in str(t):
                raise ValueError
            hh, mm = str(t).strip().split(':')
            return int(hh) * 60 + int(mm)
        st_min = _parse(start_time)
        et_min = _parse(end_time)
    except (ValueError, TypeError):
        return 0.0
    diff = et_min - st_min
    if diff < 0:
        diff += 24 * 60  # 跨天
    hours = diff / 60.0
    if hours <= 0 or hours > 12:
        return 0.0
    return math.floor(hours * 2) / 2.0

def apply_approved_event(data_folder, event):
    """P8: OA 事件审批通过后落员工主档（PRD §5.2 效果列，与 overrides 推导叠加）

    hire    → 创建/补全 employees 记录 + status='active'
    transfer→ 更新 employees.department/position
    dismiss/resign → 写 dismissed_employees + 置 employees.status='dismissed' + dismissed_at
    annual_leave/comp_leave/sick/casual → 扣对应余额（如有）+ 逐日落出勤 NU/T/SK/L
    （P21 R1/R2；P28 R5/R6，事务内任一步失败整体回滚）
    """
    eid = event.get('employee_id', '')
    etype = event.get('event_type', '')
    eff = event.get('effective_date', '')
    try:
        payload = json.loads(event.get('payload', '{}') or '{}')
    except:
        payload = {}
    conn = get_conn(data_folder)
    try:
        if etype == 'hire':
            # P12: 全字段落库（payload 键 → employees 列，salary_type → default_type）
            _fmap = [
                ('name', 'name'), ('department', 'department'), ('position', 'position'),
                ('gender', 'gender'), ('date_of_birth', 'date_of_birth'), ('phone', 'phone'),
                ('skill_level', 'skill_level'), ('nida_number', 'nida_number'),
                ('nssf_number', 'nssf_number'), ('tin_number', 'tin_number'),
                ('bank_name', 'bank_name'),
                ('bank_account', 'bank_account'), ('bank_owner', 'bank_owner'),
                ('salary_type', 'default_type'), ('day_rate', 'day_rate'),
                ('monthly_salary', 'monthly_salary'), ('team_id', 'team_id'),
                ('custom_number', 'custom_number'),
            ]
            _cols = [c for _, c in _fmap]
            _vals = [payload.get(k, '') for k, _ in _fmap]
            exists = conn.execute("SELECT 1 FROM employees WHERE id=?", (eid,)).fetchone()
            if exists:
                _sets = ', '.join(f"{c}=COALESCE(NULLIF(?,''),{c})" for c in _cols)
                conn.execute(
                    f"UPDATE employees SET {_sets},"
                    " hire_date=COALESCE(NULLIF(?,''),hire_date),"
                    " status='active' WHERE id=?",
                    tuple(_vals) + (eff, eid))
            else:
                _all_cols = ['id'] + _cols + ['hire_date', 'status']
                _all_vals = [eid] + _vals + [eff or '', 'active']
                _ph = ', '.join(['?'] * len(_all_cols))
                conn.execute(
                    f"INSERT OR IGNORE INTO employees ({', '.join(_all_cols)}) VALUES ({_ph})",
                    _all_vals)
            # P17: 工号唯一递增 — 入职无 custom_number 时生成 现有最大数字工号+1
            # (原 P14.11: custom_number 为空时等于 employee_id，已废弃)
            _cn = (payload.get('custom_number') or '').strip()
            if not _cn:
                _rows = conn.execute(
                    "SELECT custom_number FROM employees WHERE custom_number IS NOT NULL AND custom_number != ''"
                ).fetchall()
                _nums = []
                for _r in _rows:
                    try:
                        _nums.append(int(str(_r[0]).strip()))
                    except (ValueError, TypeError):
                        pass
                _cn = str((max(_nums) if _nums else 0) + 1)
                conn.execute("UPDATE employees SET custom_number=? WHERE id=?", (_cn, eid))
            # P13: 入职头像 base64 dataURL 落盘（≤2MB，PNG/JPG）
            avatar_data = payload.get('avatar_data', '') or ''
            if avatar_data:
                import base64, re
                _m = re.match(r'^data:image/(png|jpe?g);base64,(.+)$', avatar_data, re.S)
                if _m:
                    _ext = '.png' if _m.group(1) == 'png' else '.jpg'
                    try:
                        _raw = base64.b64decode(_m.group(2))
                    except Exception:
                        _raw = b''
                    if _raw and len(_raw) <= 2 * 1024 * 1024:
                        _safe_eid = re.sub(r'[^A-Za-z0-9_\-]', '_', eid) or 'emp'
                        _adir = os.path.join(os.path.dirname(os.path.dirname(
                            os.path.abspath(__file__))), 'static', 'avatars')
                        os.makedirs(_adir, exist_ok=True)
                        if not os.path.exists(os.path.join(_adir, '.gitkeep')):
                            open(os.path.join(_adir, '.gitkeep'), 'w').close()
                        # 删除同 id 旧头像（可能扩展名不同）
                        for _old in os.listdir(_adir):
                            if _old.startswith(_safe_eid + '.'):
                                os.remove(os.path.join(_adir, _old))
                        _fname = _safe_eid + _ext
                        with open(os.path.join(_adir, _fname), 'wb') as _f:
                            _f.write(_raw)
                        conn.execute(
                            "UPDATE employees SET avatar_path=? WHERE id=?",
                            (f'static/avatars/{_fname}', eid))
        elif etype == 'transfer':
            new_dept = payload.get('new_department', '')
            new_pos = payload.get('new_position', '')
            if new_dept:
                conn.execute("UPDATE employees SET department=? WHERE id=?", (new_dept, eid))
            if new_pos:
                conn.execute("UPDATE employees SET position=? WHERE id=?", (new_pos, eid))
        elif etype in ('dismiss', 'resign'):
            note = payload.get('reason', '')
            if eff:
                conn.execute(
                    "INSERT OR REPLACE INTO dismissed_employees (employee_id, note, dismissed_at) VALUES (?,?,?)",
                    (eid, note, eff))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO dismissed_employees (employee_id, note, dismissed_at) VALUES (?,?,datetime('now','+3 hours'))",
                    (eid, note))
            conn.execute(
                "UPDATE employees SET status='dismissed',"
                " dismissed_at=COALESCE(NULLIF(?,''), dismissed_at) WHERE id=?",
                (eff, eid))
        elif etype in ('annual_leave', 'comp_leave', 'sick', 'casual'):
            # P21 R1/R2: 请假批准落库 — 扣余额 + 逐日落出勤覆盖（NU=年假 / T=调休）
            # P28 R5/R6: 增病假（扣病假余额+落 SK）与普通请假（无余额，落 L）
            # 必须与 deduct_* 共享同一事务，任一步失败整体回滚
            try:
                days = int(payload.get('days', 1) or 1)
            except (TypeError, ValueError):
                days = 1
            if days < 1:
                days = 1
            year = eff[:4] if len(eff) >= 4 else ''
            if not year:
                raise RuntimeError('请假事件缺少生效日期，无法批准')
            if etype == 'annual_leave':
                ok = deduct_annual_leave(data_folder, eid, year, days, conn=conn)
                if not ok:
                    raise RuntimeError('年假余额不足，无法批准')
                st = 'NU'
            elif etype == 'comp_leave':
                ok = deduct_comp_leave(data_folder, eid, year, days, conn=conn)
                if not ok:
                    raise RuntimeError('调休余额不足，无法批准')
                st = 'T'
            elif etype == 'sick':
                _cfg = load_config(data_folder)
                ok = deduct_sick_leave(data_folder, eid, year, days,
                                       default_entitled=int(_cfg.get('sick_leave_days', 14) or 14),
                                       conn=conn)
                if not ok:
                    raise RuntimeError('病假余额不足，无法批准')
                st = 'SK'
            else:  # casual：普通请假无余额扣减
                st = 'L'
            from datetime import datetime as _dt, timedelta as _td
            try:
                d0 = _dt.strptime(eff, '%Y-%m-%d')
            except (TypeError, ValueError):
                raise RuntimeError(f'请假事件生效日期格式无效: {eff}')
            for _i in range(days):
                _ds = (d0 + _td(days=_i)).strftime('%Y-%m-%d')
                conn.execute(
                    "INSERT INTO attendance_overrides (employee_id, date, status, is_driver) VALUES (?,?,?,0) "
                    "ON CONFLICT(employee_id,date) DO UPDATE SET status=?, is_driver=0",
                    (eid, _ds, st, st))
        elif etype == 'overtime':
            # P23 R2: 加班审批通过 → 后端兜底重算 hours + 按 config 公式落 overtime_records
            _date = str(payload.get('date') or eff or '')
            _st = str(payload.get('start_time') or '')
            _et = str(payload.get('end_time') or '')
            if not _date:
                raise RuntimeError('加班事件缺少日期')
            _hours = _calc_overtime_hours(_st, _et)
            if _hours <= 0:
                raise RuntimeError('加班起止时间无效或超出 12 小时上限')
            _cfg = load_config(data_folder)
            _amt = _hours * (_cfg.get('overtime_base', 400000)
                             / _cfg.get('overtime_work_days', 26)
                             / _cfg.get('overtime_hours_per_day', 8)
                             * _cfg.get('overtime_rate', 1.5))
            conn.execute(
                "INSERT INTO overtime_records (event_id, employee_id, date, start_time, end_time, hours, amount, note)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (event['id'], eid, _date, _st, _et, _hours, round(_amt),
                 str(payload.get('note') or '')))
        conn.commit()
    finally:
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
    # 恒时比较，防时序侧信道攻击（原为 ==，字节级短路泄露哈希前缀）
    return hmac.compare_digest(hashlib.sha256((salt + password).encode()).hexdigest(), h)

def get_user_role(data_folder, username):
    """返回用户的角色: 'super_admin' | 'admin' | 'editor' | 'viewer' | None"""
    conn = get_conn(data_folder)
    row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row['role'] if row else None

# P29 权限体系 V2.1(docs/P29_PERMISSION_V2_SPEC.md §4): 追加 collector/applicant 两角色
# 红线 §12-2: editor:1 必须保留(存量 editor 用户兼容依赖 @editor_required 基线兜底)
ROLE_LEVELS = {'super_admin': 3, 'admin': 2, 'editor': 1, 'viewer': 0, 'collector': 0, 'applicant': 0}

# P29 V2.1 五内置角色预设(spec §4, 用户逐条批准的产物):
# editor 预设移除——存量 editor 的 role_permissions 行由 _migrate_permissions_v2 平移后原样保留
ROLE_DEFAULT_PERMISSIONS = {
    'super_admin': {'*': ['*']},
    # admin = 全业务，不含 system:manage
    'admin': {
        'dashboard': ['view'],
        'employees': ['view', 'edit', 'export'],
        'oa': ['view', 'apply', 'approve'],
        'attendance': ['view', 'edit', 'export'],
        'salary': ['view', 'export'],
        'collection': ['view', 'underground', 'driller', 'crush', 'attendance'],
        'scoring': ['view', 'edit'],
        'system': ['view'],
    },
    # collector = 数据采集员(继承 applicant): 4 表单全开,可按 user_grants 收窄到单表单
    'collector': {
        'dashboard': ['view'],
        'collection': ['view', 'underground', 'driller', 'crush', 'attendance'],
        'attendance': ['view'],
        'oa': ['apply'],
    },
    # applicant = 普通员工自助申请
    'applicant': {
        'dashboard': ['view'],
        'oa': ['apply'],
    },
    # viewer = 全查看零写入(D5)
    'viewer': {
        'dashboard': ['view'], 'employees': ['view'], 'oa': ['view'],
        'attendance': ['view'], 'salary': ['view'], 'collection': ['view'],
        'scoring': ['view'], 'system': ['view'],
    },
}

# P29 V2.1: 仅 collector 继承 applicant(字面实现 D4「自动继承」);其余内置角色预设自足、平铺
ROLE_HIERARCHY = {'collector': ['applicant']}

# P29b: 权限项元数据(module:action → 名称/功能说明/分组),前端权限编辑器渲染用
# V2.1 目录 8 模块 · 21 键(spec §3);分组顺序即侧边栏顺序;production:* 目录项删除
PERMISSION_CATALOG = {
    'dashboard:view': {'name': '数据台查看', 'desc': '数据台页＋产量图表接口数据', 'group': '数据台'},
    'employees:view': {'name': '员工查看', 'desc': '查看员工列表/档案', 'group': '员工'},
    'employees:edit': {'name': '员工编辑', 'desc': '编辑员工档案(别名/班组/电话等)', 'group': '员工'},
    'employees:export': {'name': '员工导出', 'desc': '导出员工花名册', 'group': '员工'},
    'oa:view': {'name': 'OA 查看', 'desc': '待审/历史列表纯浏览，不含发起申请', 'group': '审批中心'},
    'oa:apply': {'name': '发起申请', 'desc': '请假/病假/加班/入职/调岗/离职六类申请', 'group': '审批中心'},
    'oa:approve': {'name': 'OA 审批', 'desc': '批准/驳回/撤销/编辑事件', 'group': '审批中心'},
    'attendance:view': {'name': '出勤查看', 'desc': '查看出勤网格', 'group': '出勤'},
    'attendance:edit': {'name': '出勤编辑', 'desc': '标记/批量修改出勤,保存计算', 'group': '出勤'},
    'attendance:export': {'name': '出勤导出', 'desc': '导出出勤 Excel', 'group': '出勤'},
    'salary:view': {'name': '薪资查看', 'desc': '查看薪资总表/日工资明细/核对/旧数据归档', 'group': '薪资'},
    'salary:export': {'name': '薪资导出', 'desc': '导出薪资 Excel', 'group': '薪资'},
    'collection:view': {'name': '采集历史查看', 'desc': '采集记录列表/再编辑入口', 'group': '数据采集'},
    'collection:underground': {'name': '井下出渣提交', 'desc': '仅授权井下出渣采集表单提交', 'group': '数据采集'},
    'collection:driller': {'name': '钻工组提交', 'desc': '仅授权钻工组采集表单提交', 'group': '数据采集'},
    'collection:crush': {'name': '破碎计件提交', 'desc': '仅授权破碎计件采集表单提交', 'group': '数据采集'},
    'collection:attendance': {'name': '出勤收集提交', 'desc': '仅授权出勤收集采集表单提交', 'group': '数据采集'},
    'scoring:view': {'name': '评分查看', 'desc': '查看评分汇总/客观数据', 'group': '评分'},
    'scoring:edit': {'name': '评分录入', 'desc': '录入/编辑评分卡', 'group': '评分'},
    'system:view': {'name': '参数查看', 'desc': '计薪参数页可见（读取），参数保存另受 admin 角色基线约束', 'group': '系统'},
    'system:manage': {'name': '系统管理', 'desc': '用户/角色/审批人路由/表单自定义(仅超级管理员有效)', 'group': '系统'},
}

ALL_MODULES = ['dashboard', 'employees', 'oa', 'attendance', 'salary', 'collection', 'scoring', 'system']
ALL_ACTIONS = ['view', 'edit', 'apply', 'approve', 'export', 'manage', 'underground', 'driller', 'crush', 'attendance']

# P29 V2.1: 内置五角色(管理员/采集员/申请人/查看者) — 保护不可删除,sync 仅同步这 4 个落表角色,不触碰自定义角色
BUILTIN_ROLES = ['super_admin', 'admin', 'collector', 'applicant', 'viewer']

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

def sync_role_permissions(data_folder):
    """P18: 角色默认权限字典 → role_permissions 表(REPLACE 语义,可重复执行)

    - super_admin 不写表(硬编码全权限)
    - P18D: 仅同步内置角色(viewer/editor/admin),自定义角色保留不动
      (否则重跑 sync 会清掉自定义角色的权限配置)
    """
    conn = get_conn(data_folder)
    for role, grants in ROLE_DEFAULT_PERMISSIONS.items():
        if role == 'super_admin':
            continue
        if role not in BUILTIN_ROLES:
            continue
        conn.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        for module, actions in grants.items():
            if module == '*':
                continue
            for action in actions:
                conn.execute(
                    "INSERT OR REPLACE INTO role_permissions (role, module, action, allow) VALUES (?,?,?,1)",
                    (role, module, action))
    conn.commit()
    conn.close()

def get_role_permissions(data_folder, role):
    """P18: 角色有效权限集合(含继承展开)

    super_admin → {'*':{'*'}}(全权限)
    admin → admin ∪ editor ∪ viewer
    editor → editor ∪ viewer
    viewer → 仅自身
    返回 {module: set(action)}
    """
    if role == 'super_admin':
        return {'*': {'*'}}
    # 收集自身 + 继承链上的角色
    roles = [role]
    queue = list(ROLE_HIERARCHY.get(role, []))
    while queue:
        r = queue.pop(0)
        roles.append(r)
        queue.extend(ROLE_HIERARCHY.get(r, []))
    conn = get_conn(data_folder)
    result = {}
    try:
        ph = ', '.join('?' * len(roles))
        rows = conn.execute(
            f"SELECT module, action FROM role_permissions WHERE role IN ({ph}) AND allow=1",
            roles).fetchall()
        for r in rows:
            result.setdefault(r['module'], set()).add(r['action'])
    finally:
        conn.close()
    return result

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
    """撤销用户单独授权（按 permission_id）"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM user_grants WHERE username=? AND permission_id=?",
                 (username, permission_id))
    conn.commit()
    conn.close()

def revoke_user_grant_by_action(data_folder, username, module, action):
    """撤销用户单独授权（按 module + action 查找 permission_id 后删除）"""
    conn = get_conn(data_folder)
    pid_row = conn.execute(
        "SELECT id FROM permissions WHERE module=? AND action=? AND scope_type='all'",
        (module, action)).fetchone()
    if pid_row:
        conn.execute("DELETE FROM user_grants WHERE username=? AND permission_id=?",
                     (username, pid_row['id']))
    conn.commit()
    conn.close()

def check_permission(data_folder, username, module, action, scope_value=''):
    """P18: 权限检查 — 完全读 DB(role_permissions 继承展开 + user_grants 覆盖)

    判定顺序:
      1. super_admin → True
      2. user_grants deny(module/action 匹配) → False
      3. user_grants allow(module/action 匹配) → True
      4. role_permissions(含继承展开) allow=1 → True
      5. 否则 → False
    """
    conn = get_conn(data_folder)
    try:
        # 查用户角色
        role_row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
        if not role_row:
            return False
        role = role_row['role']

        # 1. super_admin 拥有所有权限
        if role == 'super_admin':
            return True

        # 2. 单独授权 deny 优先
        deny = conn.execute("""
            SELECT 1 FROM user_grants g
            JOIN permissions p ON g.permission_id = p.id
            WHERE g.username=? AND p.module=? AND p.action=? AND g.grant_type='deny'
        """, (username, module, action)).fetchone()
        if deny:
            return False

        # 3. 单独授权 allow
        allow = conn.execute("""
            SELECT 1 FROM user_grants g
            JOIN permissions p ON g.permission_id = p.id
            WHERE g.username=? AND p.module=? AND p.action=? AND g.grant_type='allow'
        """, (username, module, action)).fetchone()
        if allow:
            return True

        # 4. 角色默认权限(含继承展开)读 role_permissions 表
        perms = get_role_permissions(data_folder, role)
        if '*' in perms and '*' in perms['*']:
            return True
        actions = perms.get(module, set())
        return '*' in actions or action in actions
    finally:
        conn.close()

def get_user_permissions(data_folder, username):
    """P18 阶段2: 返回用户有效权限集合 ['module:action', ...]

    super_admin → ['*:*'];其余按角色继承展开 + user_grants 覆盖
    (deny 移除对应项,allow 追加对应项)
    """
    conn = get_conn(data_folder)
    try:
        role_row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
        if not role_row:
            return []
        role = role_row['role']
        if role == 'super_admin':
            return ['*:*']
        perms = get_role_permissions(data_folder, role)
        result = set()
        for module, actions in perms.items():
            if module == '*':
                result.add('*:*')
            else:
                for a in actions:
                    if a == '*':
                        result.add(module + ':*')
                    else:
                        result.add(module + ':' + a)
        # user_grants 覆盖
        grants = conn.execute("""
            SELECT p.module, p.action, g.grant_type
            FROM user_grants g JOIN permissions p ON g.permission_id = p.id
            WHERE g.username=?
        """, (username,)).fetchall()
        for g in grants:
            key = g['module'] + ':' + g['action']
            if g['grant_type'] == 'deny':
                result.discard(key)
            else:
                result.add(key)
        return sorted(result)
    finally:
        conn.close()

def get_user_permissions_summary(data_folder, username):
    """获取某用户的完整权限摘要：{module: {view: 'role'|'grant'|'deny'|'none'}}

    角色部分基于 role_permissions 表 + 继承展开(get_role_permissions),
    不用 ROLE_DEFAULT_PERMISSIONS 硬编码字典 —— 否则权限表修改不生效、自定义角色全 none。
    """
    conn = get_conn(data_folder)
    role_row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    if not role_row:
        conn.close()
        return None
    role = role_row['role']

    # 角色有效权限(role_permissions 表 + 继承展开;super_admin 返回 {'*': {'*'}})
    role_perms = get_role_permissions(data_folder, role)
    summary = {}
    for module in ALL_MODULES:
        summary[module] = {}
        for action in ALL_ACTIONS:
            if ('*' in role_perms and '*' in role_perms['*']) or \
               (module in role_perms and ('*' in role_perms[module] or action in role_perms[module])):
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
            # 归一化: user_grants.grant_type 为 'allow'/'deny',契约返回 'grant'/'deny'
            summary[g['module']][g['action']] = 'grant' if g['grant_type'] == 'allow' else 'deny'
    conn.close()
    return summary

def list_all_users(data_folder):
    """返回所有用户列表 [{username, role, created_at}]"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT username, role, created_at FROM admin_users ORDER BY created_at").fetchall()
    conn.close()
    return [{'username': r['username'], 'role': r['role'], 'created_at': r['created_at']} for r in rows]

def set_user_role(data_folder, username, role):
    """修改用户角色(内置 + 自定义角色均允许)"""
    # 校验: 内置角色或 role_permissions 表中已存在的自定义角色
    if role not in ROLE_LEVELS:
        conn = get_conn(data_folder)
        try:
            exists = conn.execute("SELECT 1 FROM role_permissions WHERE role=? LIMIT 1", (role,)).fetchone()
        finally:
            conn.close()
        if not exists:
            raise ValueError(f'未知角色: {role}')
    conn = get_conn(data_folder)
    conn.execute("UPDATE admin_users SET role=? WHERE username=?", (role, username))
    conn.commit()
    conn.close()

def set_admin_password(data_folder, username, password):
    """更新指定用户密码（UPSERT，保留已有 role，避免改密码把角色重置为默认 admin）"""
    conn = get_conn(data_folder)
    pwd_hash = _hash_password(password)
    conn.execute("""
        INSERT INTO admin_users (username, password_hash, role)
        VALUES (?, ?, 'admin')
        ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash
    """, (username, pwd_hash))
    conn.commit()
    conn.close()

def create_admin_user(data_folder, username, password, role):
    """创建新登录用户（含角色）。返回 'ok' / 'exists' / 'invalid_role' / 'invalid_input'"""
    username = (username or '').strip()
    password = password or ''
    if not username or len(password) < 6:
        return 'invalid_input'
    if role not in ROLE_LEVELS:
        return 'invalid_role'
    conn = get_conn(data_folder)
    exists = conn.execute("SELECT 1 FROM admin_users WHERE username=?", (username,)).fetchone()
    if exists:
        conn.close()
        return 'exists'
    pwd_hash = _hash_password(password)
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
        (username, pwd_hash, role))
    conn.commit()
    conn.close()
    return 'ok'

def reset_admin_password(data_folder, username, new_password):
    """超级管理员重置指定用户密码（不要求旧密码，保留 role）。返回 'ok' / 'not_found' / 'invalid_input'"""
    username = (username or '').strip()
    new_password = new_password or ''
    if not username or len(new_password) < 6:
        return 'invalid_input'
    conn = get_conn(data_folder)
    row = conn.execute("SELECT 1 FROM admin_users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close()
        return 'not_found'
    pwd_hash = _hash_password(new_password)
    conn.execute("UPDATE admin_users SET password_hash=? WHERE username=?", (pwd_hash, username))
    conn.commit()
    conn.close()
    return 'ok'

def rename_admin_user(data_folder, old_username, new_username):
    """重命名登录用户（同步 user_grants 授权 + approval_routes 审批人）。
    返回 'ok' / 'not_found' / 'exists' / 'invalid_input'"""
    old_username = (old_username or '').strip()
    new_username = (new_username or '').strip()
    if not old_username or not new_username:
        return 'invalid_input'
    conn = get_conn(data_folder)
    row = conn.execute("SELECT 1 FROM admin_users WHERE username=?", (old_username,)).fetchone()
    if not row:
        conn.close()
        return 'not_found'
    dup = conn.execute("SELECT 1 FROM admin_users WHERE username=? AND username<>?", (new_username, old_username)).fetchone()
    if dup:
        conn.close()
        return 'exists'
    try:
        # user_grants.username 外键引用 admin_users.username，重命名时需临时关闭外键
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute("UPDATE admin_users SET username=? WHERE username=?", (new_username, old_username))
        conn.execute("UPDATE user_grants SET username=? WHERE username=?", (new_username, old_username))
        conn.execute("UPDATE approval_routes SET approver=? WHERE approver=?", (new_username, old_username))
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
        return 'ok'
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        conn.close()
        return 'invalid_input'

def delete_admin_user(data_folder, username):
    """删除登录用户（自动清理 user_grants 授权 + approval_routes 审批人设定）。
    返回 'ok' / 'not_found' / 'last_super_admin'"""
    username = (username or '').strip()
    if not username:
        return 'not_found'
    conn = get_conn(data_folder)
    row = conn.execute("SELECT role FROM admin_users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close()
        return 'not_found'
    # 防止删除最后一个 super_admin（系统锁定）
    if row['role'] == 'super_admin':
        cnt = conn.execute("SELECT COUNT(*) AS c FROM admin_users WHERE role='super_admin'").fetchone()['c']
        if cnt <= 1:
            conn.close()
            return 'last_super_admin'
    conn.execute("DELETE FROM user_grants WHERE username=?", (username,))
    conn.execute("DELETE FROM approval_routes WHERE approver=?", (username,))
    conn.execute("DELETE FROM admin_users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return 'ok'

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


# ── P13: 审批人路由 ─────────────────────────

def get_approval_routes(data_folder):
    """P13: 审批人路由全表 [{id, event_type, approver}]"""
    conn = get_conn(data_folder)
    rows = conn.execute(
        "SELECT id, event_type, approver FROM approval_routes ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_approval_route(data_folder, event_type, approver):
    """P13: 设置某事件类型的指定审批人（UPSERT）"""
    conn = get_conn(data_folder)
    conn.execute("""
        INSERT INTO approval_routes (event_type, approver, updated_at)
        VALUES (?,?,datetime('now','+3 hours'))
        ON CONFLICT(event_type) DO UPDATE SET
            approver=excluded.approver,
            updated_at=datetime('now','+3 hours')
    """, (event_type, approver))
    conn.commit()
    conn.close()

def delete_approval_route(data_folder, route_id):
    """P13: 删除审批人路由，返回是否影响行"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM approval_routes WHERE id=?", (route_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0

def get_approver_for_event(data_folder, event_type):
    """P13: 取指定事件类型的审批人；未设定返回 ''"""
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT approver FROM approval_routes WHERE event_type=?",
        (event_type,)
    ).fetchone()
    conn.close()
    return (row['approver'] if row else '') or ''

# ── P1: 员工生命周期事件 ─────────────────────

def create_event(data_folder, data):
    """创建 OA 事件，返回 event_id"""
    conn = get_conn(data_folder)
    cur = conn.execute("""
        INSERT INTO employee_events (employee_id, event_type, effective_date,
            snapshot, payload, operator_id, approver, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (data['employee_id'], data['event_type'], data['effective_date'],
          data.get('snapshot', '{}'), data.get('payload', '{}'),
          data['operator_id'], data.get('approver', ''), data.get('status', 'pending')))
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid

def update_pending_event(data_folder, event_id, fields):
    """P21 R1: 修改待审事件（仅限 status='pending'）—— 更新 payload/effective_date/updated_at"""
    sets, vals = [], []
    if 'payload' in fields and fields['payload'] is not None:
        sets.append('payload=?')
        vals.append(fields['payload'])
    if 'effective_date' in fields and fields['effective_date'] is not None:
        sets.append('effective_date=?')
        vals.append(fields['effective_date'])
    if not sets:
        return False
    vals += [event_id]
    conn = get_conn(data_folder)
    cur = conn.execute(
        f"UPDATE employee_events SET {', '.join(sets)},"
        " updated_at=datetime('now','+3 hours') WHERE id=? AND status='pending'",
        vals)
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_pending_events(data_folder, approver='', is_super_admin=False, operator_filter=None):
    """获取待审批事件；approver 指定时仅返回该审批人或 super_admin 可见的事件，
    未指定审批人（''）的事件所有人可见
    P29 T4: operator_filter（oa:apply-only 用户）时忽略审批人路由，
    仅返回该提交人自己的 pending 事件"""
    conn = get_conn(data_folder)
    if operator_filter:
        rows = conn.execute("""
            SELECT e.*, em.name as employee_name
            FROM employee_events e
            LEFT JOIN employees em ON e.employee_id = em.id
            WHERE e.status = 'pending' AND e.operator_id = ?
            ORDER BY e.created_at DESC
        """, (operator_filter,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    rows = conn.execute("""
        SELECT e.*, em.name as employee_name
        FROM employee_events e
        LEFT JOIN employees em ON e.employee_id = em.id
        WHERE e.status = 'pending'
          AND (? = '' OR e.approver = '' OR e.approver = ? OR ? = 1)
        ORDER BY e.created_at DESC
    """, (approver, approver, 1 if is_super_admin else 0)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_processed_events(data_folder, event_type=None, operator_filter=None):
    """P8: 获取所有已处理（approved/rejected）事件，JOIN 员工姓名；P21 M4 增加 revoked
    P22 R2: 增加 event_type 可选过滤（None 时不过滤）
    P29 T4: operator_filter（oa:apply-only 用户）时仅返回该提交人的事件
    （全状态含 revoked——撤销结果对本人可见）"""
    conn = get_conn(data_folder)
    sql = """
        SELECT e.*, em.name as employee_name
        FROM employee_events e
        LEFT JOIN employees em ON e.employee_id = em.id
        WHERE e.status IN ('approved', 'rejected', 'revoked')
    """
    params = []
    if event_type:
        sql += " AND e.event_type=?"
        params.append(event_type)
    if operator_filter:
        sql += " AND e.operator_id=?"
        params.append(operator_filter)
    sql += " ORDER BY e.updated_at DESC, e.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
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
        SET status='approved', approved_by=?, updated_at=datetime('now','+3 hours')
        WHERE id=? AND status='pending'
    """, (approved_by, event_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0

def unapprove_event(data_folder, event_id):
    """P24-SEC: 审批事务回滚 — 将 approved 事件置回 pending（apply 副作用失败时撤销抢占锁）"""
    conn = get_conn(data_folder)
    conn.execute("""
        UPDATE employee_events
        SET status='pending', approved_by='', updated_at=datetime('now','+3 hours')
        WHERE id=? AND status='approved'
    """, (event_id,))
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
            updated_at=datetime('now','+3 hours')
        WHERE id=? AND status='pending'
    """, (rejected_by, reason, event_id))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0

def revoke_event(data_folder, event_id, revoked_by):
    """P21 M4: 撤销事件（approved 或 pending → revoked，保留原审计轨迹）

    leave 事件（annual_leave/comp_leave/sick/casual）同时：
      - 回滚余额（restore_annual_leave / restore_comp_leave / restore_sick_leave，防负）
      - 删除按 effective_date+days 逐日写下的 attendance_overrides（NU/T/SK/L）
    全部在同一事务内，任一步失败整体回滚。
    """
    conn = get_conn(data_folder)
    try:
        ev = conn.execute("SELECT * FROM employee_events WHERE id=?", (event_id,)).fetchone()
        if not ev:
            return False
        if ev['status'] not in ('approved', 'pending'):
            return False
        conn.execute(
            "UPDATE employee_events SET status='revoked', revoked_by=?,"
            " revoked_at=datetime('now','+3 hours'),"
            " updated_at=datetime('now','+3 hours') WHERE id=?",
            (revoked_by, event_id))
        if ev['event_type'] in ('annual_leave', 'comp_leave', 'sick', 'casual'):
            # P28 R5/R6: 病假/普通请假撤销与年假/调休同款——回滚余额（如有）+ 删逐日出勤
            try:
                payload = json.loads(ev['payload'] or '{}')
            except Exception:
                payload = {}
            try:
                days = int(payload.get('days', 1) or 1)
            except (TypeError, ValueError):
                days = 1
            if days < 1:
                days = 1
            eff = ev['effective_date'] or ''
            year = eff[:4] if len(eff) >= 4 else ''
            if year:
                if ev['event_type'] == 'annual_leave':
                    restore_annual_leave(data_folder, ev['employee_id'], year, days, conn=conn)
                elif ev['event_type'] == 'comp_leave':
                    restore_comp_leave(data_folder, ev['employee_id'], year, days, conn=conn)
                elif ev['event_type'] == 'sick':
                    restore_sick_leave(data_folder, ev['employee_id'], year, days, conn=conn)
            from datetime import datetime as _dt, timedelta as _td
            try:
                d0 = _dt.strptime(eff, '%Y-%m-%d')
            except (TypeError, ValueError):
                d0 = None
            if d0:
                for _i in range(days):
                    _ds = (d0 + _td(days=_i)).strftime('%Y-%m-%d')
                    conn.execute(
                        "DELETE FROM attendance_overrides WHERE employee_id=? AND date=?",
                        (ev['employee_id'], _ds))
        elif ev['event_type'] == 'overtime':
            # P23 R2: 撤销加班 → 删除对应 overtime_records（同事务内，薪资即时回退）
            conn.execute("DELETE FROM overtime_records WHERE event_id=?", (event_id,))
        conn.commit()
        return True
    finally:
        conn.close()

def edit_approved_leave_event(data_folder, event_id, new_date, new_days, operator):
    """P21 M4: 已批年假/调休同月修改——单事务内「撤销旧单 → 扣新余额 → 写新出勤 → 批准新单」

    仅限同月（new_date[:7] == 原 effective_date[:7]），跨月返回错误。
    approver 保留原事件设定。任一步失败整体回滚。
    返回 (ok, msg)：成功 msg=新事件 id；失败 msg=错误描述。
    """
    from datetime import datetime as _dt, timedelta as _td
    conn = get_conn(data_folder)
    try:
        ev = conn.execute("SELECT * FROM employee_events WHERE id=?", (event_id,)).fetchone()
        if not ev or ev['status'] != 'approved':
            return False, '事件不存在或未批准'
        if ev['event_type'] not in ('annual_leave', 'comp_leave'):
            return False, '仅请假事件可修改'
        if ev['effective_date'][:7] != (new_date or '')[:7]:
            return False, '跨月修改需先撤销后重新申请'
        try:
            payload = json.loads(ev['payload'] or '{}')
        except Exception:
            payload = {}
        try:
            old_days = int(payload.get('days', 1) or 1)
        except (TypeError, ValueError):
            old_days = 1
        if old_days < 1:
            old_days = 1
        year = ev['effective_date'][:4]
        eid = ev['employee_id']
        etype = ev['event_type']
        approver = ev['approver'] or ''
        # 1) 撤销旧单（置 revoked + 回滚余额 + 删旧 NU/T）
        conn.execute(
            "UPDATE employee_events SET status='revoked', revoked_by=?,"
            " revoked_at=datetime('now','+3 hours'),"
            " updated_at=datetime('now','+3 hours') WHERE id=?",
            (operator, event_id))
        if etype == 'annual_leave':
            restore_annual_leave(data_folder, eid, year, old_days, conn=conn)
        else:
            restore_comp_leave(data_folder, eid, year, old_days, conn=conn)
        try:
            d0 = _dt.strptime(ev['effective_date'], '%Y-%m-%d')
        except (TypeError, ValueError):
            d0 = None
        if d0:
            for _i in range(old_days):
                _ds = (d0 + _td(days=_i)).strftime('%Y-%m-%d')
                conn.execute(
                    "DELETE FROM attendance_overrides WHERE employee_id=? AND date=?",
                    (eid, _ds))
        # 2) 创建新单（pending，approver 保留）
        new_payload = json.dumps({
            'days': new_days,
            'note': payload.get('note', ''),
            'event_type': etype,
        }, ensure_ascii=False)
        cur = conn.execute(
            "INSERT INTO employee_events (employee_id, event_type, effective_date,"
            " snapshot, payload, operator_id, approver, status)"
            " VALUES (?,?,?,?,?,?,?,'pending')",
            (eid, etype, new_date, ev['snapshot'] or '{}', new_payload,
             ev['operator_id'], approver))
        new_id = cur.lastrowid
        # 3) 扣新余额 + 写新出勤
        if etype == 'annual_leave':
            ok = deduct_annual_leave(data_folder, eid, year, new_days, conn=conn)
            if not ok:
                raise RuntimeError('年假余额不足，无法修改')
            st = 'NU'
        else:
            ok = deduct_comp_leave(data_folder, eid, year, new_days, conn=conn)
            if not ok:
                raise RuntimeError('调休余额不足，无法修改')
            st = 'T'
        d1 = _dt.strptime(new_date, '%Y-%m-%d')
        for _i in range(new_days):
            _ds = (d1 + _td(days=_i)).strftime('%Y-%m-%d')
            conn.execute(
                "INSERT INTO attendance_overrides (employee_id, date, status, is_driver) VALUES (?,?,?,0) "
                "ON CONFLICT(employee_id,date) DO UPDATE SET status=?, is_driver=0",
                (eid, _ds, st, st))
        # 4) 批准新单
        conn.execute(
            "UPDATE employee_events SET status='approved', approved_by=?,"
            " updated_at=datetime('now','+3 hours') WHERE id=? AND status='pending'",
            (operator, new_id))
        conn.commit()
        return True, new_id
    except RuntimeError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def get_event(data_folder, event_id):
    """获取单个事件详情"""
    conn = get_conn(data_folder)
    row = conn.execute("SELECT * FROM employee_events WHERE id=?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_approved_events_for_month(data_folder, month):
    """获取指定月份及之前生效的已批准事件（按类型筛选可用于计薪的事件）"""
    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT * FROM employee_events
        WHERE status = 'approved'
        AND event_type IN ('hire', 'transfer', 'salary_change', 'resign', 'dismiss')
        AND effective_date <= ?
        ORDER BY employee_id, effective_date
    """, (month,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
        "SELECT COUNT(*) FROM leave_requests WHERE employee_id=?", (employee_id,)
    ).fetchone()[0] if _table_exists(conn, 'leave_requests') else 0
    conn.close()
    return {**dict(emp), 'event_count': event_count, 'leave_count': leave_count}

def update_employee_fields(data_folder, employee_id, fields):
    """更新员工扩展字段（position/skill_level/hire_date/nida_*/nssf_*/bank_* 及 P7 gender/dob/phone、P8 department）"""
    allowed = {'position', 'skill_level', 'hire_date', 'nida_number',
               'nssf_number', 'bank_name', 'bank_account', 'bank_owner',
               'phone', 'note', 'status', 'dismissed_at', 'custom_fields',
               'gender', 'date_of_birth', 'avatar_path', 'department',
               'team_id', 'custom_number', 'alias',
               'tin_number',
               'name'}  # P21 M5/R6: TIN + 改名（旧名入 alias 由 app.py 处理）
    # 班组仅井下出渣/钻工部门——其他部门（按部门名判定）一律 team_id 置 0
    if fields.get('team_id'):
        conn = get_conn(data_folder)
        _row = conn.execute("SELECT department FROM employees WHERE id=?", (employee_id,)).fetchone()
        conn.close()
        if _row:
            _dept = (_row['department'] or '').replace(' ', '').replace('（', '(').replace('）', ')').upper()
            if _dept not in ('PRODUCTIONTEAM(UNDERGROUND)', 'DRILLERTEAM'):
                fields['team_id'] = 0
    updates = {k: v for k, v in fields.items() if k in allowed}
    # 归一化 NSSF/TIN 号码：去除连字符与空白（统一格式）
    for _k in ('nssf_number', 'tin_number'):
        if _k in updates and updates[_k] is not None:
            updates[_k] = str(updates[_k]).replace('-', '').strip()
    # NSSF 参保以 nssf_number 有值为准（填号即参保）
    if 'nssf_number' in updates:
        updates['nssf_enrolled'] = bool(updates['nssf_number'])
    if not updates:
        return False
    conn = get_conn(data_folder)
    sets = ', '.join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [employee_id]
    conn.execute(f"UPDATE employees SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return True

def update_employee_salary_type(data_folder, employee_id, salary_type, day_rate, monthly_salary):
    """P7: 更新员工薪资类别与基数（default_type + day_rate/monthly_salary）"""
    if salary_type not in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
        return False
    conn = get_conn(data_folder)
    conn.execute(
        "UPDATE employees SET default_type=?, day_rate=?, monthly_salary=? WHERE id=?",
        (salary_type, int(day_rate or 0), int(monthly_salary or 0), employee_id))
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
            'comp_entitled': 0, 'comp_used': 0,
            'sick_entitled': 14, 'sick_used': 0
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
            updated_at=datetime('now','+3 hours')
    """, (employee_id, year, annual, comp, annual, comp))
    conn.commit()
    conn.close()

def deduct_annual_leave(data_folder, employee_id, year, days, conn=None):
    """扣减年假余额；余额不足返回 False。conn 非 None 时共享事务（不 commit/close）"""
    own = conn is None
    if own:
        conn = get_conn(data_folder)
    try:
        row = conn.execute(
            "SELECT annual_entitled, annual_used FROM leave_balances WHERE employee_id=? AND year=?",
            (employee_id, year)).fetchone()
        if not row or (row['annual_entitled'] - row['annual_used']) < days:
            return False
        conn.execute("""
            UPDATE leave_balances SET annual_used=annual_used+?,
                updated_at=datetime('now','+3 hours')
            WHERE employee_id=? AND year=?
        """, (days, employee_id, year))
        if own:
            conn.commit()
        return True
    finally:
        if own:
            conn.close()

def restore_annual_leave(data_folder, employee_id, year, days, conn=None):
    """P21 R1: 撤销年假时反向恢复余额（防负：MAX(annual_used-?,0)）。
    conn 非 None 时共享事务（不 commit/close）"""
    own = conn is None
    if own:
        conn = get_conn(data_folder)
    try:
        conn.execute("""
            UPDATE leave_balances SET annual_used=MAX(annual_used-?,0),
                updated_at=datetime('now','+3 hours')
            WHERE employee_id=? AND year=?
        """, (days, employee_id, year))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()

def restore_comp_leave(data_folder, employee_id, year, days, conn=None):
    """P21 R1: 撤销调休时反向恢复余额（防负：MAX(comp_used-?,0)）。
    conn 非 None 时共享事务（不 commit/close）"""
    own = conn is None
    if own:
        conn = get_conn(data_folder)
    try:
        conn.execute("""
            UPDATE leave_balances SET comp_used=MAX(comp_used-?,0),
                updated_at=datetime('now','+3 hours')
            WHERE employee_id=? AND year=?
        """, (days, employee_id, year))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()

def deduct_comp_leave(data_folder, employee_id, year, days, conn=None):
    """扣减调休余额；余额不足返回 False。conn 非 None 时共享事务（不 commit/close）"""
    own = conn is None
    if own:
        conn = get_conn(data_folder)
    try:
        row = conn.execute(
            "SELECT comp_entitled, comp_used FROM leave_balances WHERE employee_id=? AND year=?",
            (employee_id, year)).fetchone()
        if not row or (row['comp_entitled'] - row['comp_used']) < days:
            return False
        conn.execute("""
            UPDATE leave_balances SET comp_used=comp_used+?,
                updated_at=datetime('now','+3 hours')
            WHERE employee_id=? AND year=?
        """, (days, employee_id, year))
        if own:
            conn.commit()
        return True
    finally:
        if own:
            conn.close()

# ── P8: 病假余额 ─────────────────────────

def deduct_sick_leave(data_folder, employee_id, year, days, default_entitled=14, conn=None):
    """扣减病假余额（懒初始化：无行时按 default_entitled 建行）；余额不足返回 False。
    conn 非 None 时共享事务（不 commit/close），供 OA 审批事务内调用"""
    own = conn is None
    if own:
        conn = get_conn(data_folder)
    try:
        row = conn.execute(
            "SELECT sick_entitled, sick_used FROM leave_balances WHERE employee_id=? AND year=?",
            (employee_id, year)).fetchone()
        if not row:
            conn.execute(
                "INSERT OR IGNORE INTO leave_balances (employee_id, year, sick_entitled, sick_used) VALUES (?,?,?,0)",
                (employee_id, year, default_entitled))
            row = {'sick_entitled': default_entitled, 'sick_used': 0}
        if (row['sick_entitled'] - row['sick_used']) < days:
            return False
        conn.execute("""
            UPDATE leave_balances SET sick_used=sick_used+?,
                updated_at=datetime('now','+3 hours')
            WHERE employee_id=? AND year=?
        """, (days, employee_id, year))
        if own:
            conn.commit()
        return True
    finally:
        if own:
            conn.close()

def restore_sick_leave(data_folder, employee_id, year, days, conn=None):
    """P28 R5: 撤销病假事件时反向恢复余额（防负：MAX(sick_used-?,0)）。
    conn 非 None 时共享事务（不 commit/close）"""
    own = conn is None
    if own:
        conn = get_conn(data_folder)
    try:
        conn.execute("""
            UPDATE leave_balances SET sick_used=MAX(sick_used-?,0),
                updated_at=datetime('now','+3 hours')
            WHERE employee_id=? AND year=?
        """, (days, employee_id, year))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()

def insert_leave_request(data_folder, data):
    """写入 leave_requests 记录（status 由调用方指定）"""
    conn = get_conn(data_folder)
    cur = conn.execute("""
        INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, reason, submitted_by, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (data['employee_id'], data.get('leave_type', 'casual'),
          data['start_date'], data.get('end_date', data['start_date']),
          data.get('days', 1), data.get('reason', ''),
          data.get('submitted_by', ''), data.get('status', 'pending')))
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid

def adjust_leave_balance(data_folder, employee_id, year, sick_entitled=None, sick_used=None,
                         annual_entitled=None, annual_used=None, comp_entitled=None, comp_used=None):
    """P8/P12: 手动调整员工假期余额（annual/comp/sick 各 entitled/used，None 表示不修改）"""
    conn = get_conn(data_folder)
    conn.execute(
        "INSERT OR IGNORE INTO leave_balances (employee_id, year) VALUES (?,?)",
        (employee_id, year))
    conn.commit()
    sets, vals = [], []
    for col, val in [('sick_entitled', sick_entitled), ('sick_used', sick_used),
                     ('annual_entitled', annual_entitled), ('annual_used', annual_used),
                     ('comp_entitled', comp_entitled), ('comp_used', comp_used)]:
        if val is not None:
            sets.append(f"{col}=?")
            vals.append(int(val))
    if not sets:
        conn.close()
        return False
    vals += [employee_id, year]
    conn.execute(f"UPDATE leave_balances SET {', '.join(sets)}, updated_at=datetime('now','+3 hours') WHERE employee_id=? AND year=?", vals)
    conn.commit()
    conn.close()
    return True


# ── P28: 调休月度累积 ────────────────

COMP_MONTHLY_DAYS = 4  # 每月调休额度（月=4周，每周1天）
_COMP_ACCRUAL_KEY = 'comp_leave_accrued_through'

def _eat_now():
    import datetime
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))

def _parse_ym(s):
    """解析 YYYY-MM → (year, month)，非法返回 None"""
    try:
        if len(s) == 7 and s[4] == '-' and s[0] != '-':
            y, m = int(s[:4]), int(s[5:7])
            if 1 <= m <= 12:
                return y, m
    except ValueError:
        pass
    return None

def _comp_days_for_hire_month(day):
    """入职当月按周折算——月=4周，入职所在周起每周计1天：
    第1周(1-7日)→4天，第2周(8-14)→3天，第3周(15-21)→2天，第4周(22-31)→1天"""
    week = min((day + 6) // 7, 4)
    return 5 - week

def accrue_comp_leave_monthly(data_folder):
    """P28: 调休余额按月自动入账（每月+4，月初一次性；入职当月按周折算；
    hire_date 为空视为老员工整月；仅 active 员工）。

    幂等：settings 键 comp_leave_accrued_through 记水位（YYYY-MM），只补水位之后
    的月份；首次启用只入账当前月，不回溯历史。BEGIN IMMEDIATE 下先抢写锁再读
    水位，并发调用不会双倍入账。返回 {'accrued_months', 'employees'}，无欠账返回 None。
    """
    import datetime
    cur_ym = _eat_now().strftime('%Y-%m')
    conn = get_conn(data_folder)
    try:
        conn.execute("BEGIN IMMEDIATE")  # 先抢写锁、后读水位，防并发双记账
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_COMP_ACCRUAL_KEY,)).fetchone()
        wm = (row['value'] or '').strip() if row else ''
        cur_pair = _parse_ym(cur_ym)
        wm_pair = _parse_ym(wm)
        if wm_pair is not None and cur_pair is not None and wm_pair >= cur_pair:
            conn.rollback()  # 已入账到当前月；水位超前（时钟回拨/手改）同样跳过
            return None
        months = []
        if wm_pair and cur_pair:
            y, m = wm_pair
            ty, tm = cur_pair
            while (y, m) != (ty, tm):
                m += 1
                if m > 12:
                    y, m = y + 1, 1
                months.append(f'{y:04d}-{m:02d}')
        if not months:
            months = [cur_ym]  # 首次启用或水位非法：只入账当前月

        emps = conn.execute(
            "SELECT id, hire_date FROM employees WHERE status='active'").fetchall()
        credited = set()
        for ym in months:
            yy, mm = int(ym[:4]), int(ym[5:7])
            for e in emps:
                hd = (e['hire_date'] or '').strip()
                days = COMP_MONTHLY_DAYS
                if hd:
                    try:
                        d = datetime.date.fromisoformat(hd)
                        if (d.year, d.month) > (yy, mm):
                            continue
                        if (d.year, d.month) == (yy, mm):
                            days = _comp_days_for_hire_month(d.day)
                    except ValueError:
                        pass  # hire_date 格式无效 → 按老员工给整月
                if days <= 0:
                    continue
                conn.execute("""
                    INSERT INTO leave_balances (employee_id, year, comp_entitled)
                    VALUES (?, ?, ?)
                    ON CONFLICT(employee_id, year) DO UPDATE SET
                        comp_entitled=comp_entitled+?,
                        updated_at=datetime('now','+3 hours')
                """, (e['id'], str(yy), days, days))
                credited.add(e['id'])
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (_COMP_ACCRUAL_KEY, cur_ym))
        conn.commit()
        return {'accrued_months': months, 'employees': len(credited)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── P2: 年假资格校验 ────────────────

def check_annual_leave_eligible(data_folder, employee_id):
    """P21 R3: 年假资格检查（NSSF 改为查 nssf_number 有值；新增 TIN 检查）

    返回结构化 reason codes（no_nssf/no_nida/no_tin/no_hire_date/invalid_hire_date/under_1year）
    + 保留中文 reasons 供旧调用方展示。
    豁免开关（annual_leave_override）跳过 NSSF + NIDA + TIN，但入职日期仍必须。
    """
    conn = get_conn(data_folder)
    emp = conn.execute(
        "SELECT nssf_enrolled, nssf_number, nida_number, hire_date, annual_leave_override, tin_number "
        "FROM employees WHERE id=?", (employee_id,)).fetchone()
    conn.close()
    if not emp:
        return {'eligible': False, 'reasons': ['员工不存在'], 'codes': ['no_employee']}

    def _check_hire_date():
        """入职日期检查：返回 (code, reason)，通过返回 (None, None)"""
        if not emp['hire_date']:
            return 'no_hire_date', '入职日期为空'
        import datetime
        try:
            hd = datetime.datetime.strptime(emp['hire_date'], '%Y-%m-%d').replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=3)))
            eat_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
            if (eat_now - hd).days < 365:
                return 'under_1year', '入职不满1年({}天)'.format((eat_now - hd).days)
        except Exception:
            return 'invalid_hire_date', '入职日期格式无效'
        return None, None

    codes, reasons = [], []
    # P20: 豁免开关开启后跳过 NSSF + NIDA + TIN 检查，但仍保留入职年限检查
    if emp['annual_leave_override']:
        code, reason = _check_hire_date()
        if code:
            codes.append(code)
            reasons.append(reason)
        return {'eligible': len(codes) == 0, 'reasons': reasons, 'codes': codes}

    # P21 R3: NSSF 以 nssf_number 有值为准（nssf_enrolled 布尔可能滞后）
    if not (emp['nssf_number'] or '').strip():
        codes.append('no_nssf')
        reasons.append('未参加NSSF')
    if not (emp['nida_number'] or '').strip():
        codes.append('no_nida')
        reasons.append('NIDA证件号为空')
    if not (emp['tin_number'] or '').strip():
        codes.append('no_tin')
        reasons.append('TIN号码为空')
    code, reason = _check_hire_date()
    if code:
        codes.append(code)
        reasons.append(reason)
    return {'eligible': len(codes) == 0, 'reasons': reasons, 'codes': codes}


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

# ── P14.8: 评分原始记录（一张卡 9 行明细） ──

def save_scoring_card_entries(data_folder, week, team_id, card_no, source, rows, month=None):
    """保存一张评分卡的全部行（按 UNIQUE 键 UPSERT，重录覆盖）。P15: month 参数，None 兼容旧调用"""
    conn = get_conn(data_folder)
    for r in rows:
        conn.execute("""
            INSERT OR REPLACE INTO scoring_card_entries
                (week, team_id, card_no, source, subject_employee_id, subject_name,
                 initiative, diligence, discipline, cooperation, safety, driving, month)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (week, team_id, card_no, source,
              r.get('subject_employee_id', '') or r.get('employee_id', ''),
              r.get('subject_name', '') or r.get('name', ''),
              r.get('initiative'), r.get('diligence'), r.get('discipline'),
              r.get('cooperation'), r.get('safety'), r.get('driving'),
              month or r.get('month') or ''))
    conn.commit()
    conn.close()

def get_scoring_card_entries(data_folder, team_id=None, week=None, card_no=None, source=None, month=None):
    """按条件组合查询评分原始记录。P15: month 参数（None 不过滤，兼容旧调用）"""
    conn = get_conn(data_folder)
    where, params = [], []
    if team_id is not None:
        where.append('team_id=?'); params.append(team_id)
    if week is not None:
        where.append('week=?'); params.append(week)
    if card_no:
        where.append('card_no=?'); params.append(card_no)
    if source:
        where.append('source=?'); params.append(source)
    if month:
        where.append('month=?'); params.append(month)
    sql = 'SELECT * FROM scoring_card_entries'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY week, team_id, card_no, source, id'
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_scoring_card_entries(data_folder, week, team_id, card_no, source, month=None):
    """删除整张卡（重录时先删再插）。P15: month 参数，None 兼容旧调用（按旧 UNIQUE 语义）"""
    conn = get_conn(data_folder)
    if month:
        conn.execute("""
            DELETE FROM scoring_card_entries WHERE week=? AND team_id=? AND card_no=? AND source=? AND month=?
        """, (week, team_id, card_no, source, month))
    else:
        conn.execute("""
            DELETE FROM scoring_card_entries WHERE week=? AND team_id=? AND card_no=? AND source=?
        """, (week, team_id, card_no, source))
    conn.commit()
    conn.close()

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

def get_objective_records(data_folder, team, month=None):
    """P15: 支持按月过滤（month='YYYY-MM'，None 不过滤兼容旧调用）"""
    conn = get_conn(data_folder)
    if month:
        rows = conn.execute(
            "SELECT * FROM objective_records WHERE team=? AND substr(record_date,1,7)=? ORDER BY record_date",
            (team, month)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM objective_records WHERE team=? ORDER BY record_date", (team,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_monthly_objective(data_folder, team, month=None):
    # P15 用户决策：无计划出渣量（planned<=0）的记录不计入发放（不参与 S 汇总）
    rows = [r for r in get_objective_records(data_folder, team, month) if r['planned_output'] > 0]
    if not rows:
        return {'monthly_s': 0, 'distribution_ratio': 0.7, 'planned_sum': 0, 'actual_sum': 0}
    monthly_s = sum(r['daily_s'] for r in rows) / max(len(rows), 1)
    # P15: 手册 90/80/70/60 五档（无 0.85 档）
    if monthly_s >= 90: ratio = 1.0
    elif monthly_s >= 80: ratio = 0.95
    elif monthly_s >= 70: ratio = 0.9
    elif monthly_s >= 60: ratio = 0.8
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
            "WHERE name LIKE ? OR department LIKE ? OR id LIKE ? OR alias LIKE ? OR custom_number LIKE ? LIMIT 20",
            (q, q, q, q, q)).fetchall()
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
            except Exception:
                pass  # 表可能不存在，跳过

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
        sets.append("updated_at=datetime('now','+3 hours')")
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

    # 调岗OA表单
    conn.execute("INSERT INTO form_schemas (name, description, table_name) VALUES (?,?,?)",
                 ('oa_transfer', '调岗审批表单', 'employee_events'))
    sid3 = conn.execute("SELECT id FROM form_schemas WHERE name='oa_transfer'").fetchone()['id']
    transfer_fields = [
        ('employee_id', 'text', '员工ID', 'Employee ID', 1, 1),
        ('old_department', 'text', '原部门', 'Old Department', 1, 2),
        ('new_department', 'text', '新部门', 'New Department', 1, 3),
        ('new_position', 'text', '新岗位', 'New Position', 0, 4),
        ('effective_date', 'date', '生效日期', 'Effective Date', 1, 5),
        ('note', 'textarea', '备注', 'Note', 0, 6),
    ]
    for f_key, f_type, lzh, len_val, req, order in transfer_fields:
        conn.execute("""
            INSERT INTO form_fields (schema_id, field_key, field_type, label_zh, label_en,
                options, required, sort_order, is_custom, default_value)
            VALUES (?,?,?,?,?,?,?,?,0,'')
        """, (sid3, f_key, f_type, lzh, len_val, '[]', req, order))

    # 出勤收集表单
    conn.execute("INSERT INTO form_schemas (name, description, table_name) VALUES (?,?,?)",
                 ('attendance_collection', '出勤收集（花名册点选）', 'attendance_overrides'))
    sid4 = conn.execute("SELECT id FROM form_schemas WHERE name='attendance_collection'").fetchone()['id']
    att_fields = [
        ('employee_id', 'text', '员工', 'Employee', 1, 1),
        ('date', 'date', '日期', 'Date', 1, 2),
        ('status', 'select', '出勤状态', 'Status', 1, 3),
        ('is_driver', 'checkbox', '当日驾驶', 'Is Driver', 0, 4),
    ]
    for f_key, f_type, lzh, len_val, req, order in att_fields:
        opts = '[]'
        if f_key == 'status':
            opts = json.dumps(['P', 'A', 'L', 'S', 'Y', 'T', 'D', 'N', 'R', 'C'])
        conn.execute("""
            INSERT INTO form_fields (schema_id, field_key, field_type, label_zh, label_en,
                options, required, sort_order, is_custom, default_value)
            VALUES (?,?,?,?,?,?,?,?,0,'')
        """, (sid4, f_key, f_type, lzh, len_val, opts, req, order))

    # 产量录入表单（井下/钻工/破碎三个共用同一结构）
    prod_specs = [
        ('production_underground', '井下出渣产量录入', 'shift_additions'),
        ('production_driller', '钻工组产量录入', 'driller_additions'),
        ('production_crush', '破碎计件产量录入', 'shift_additions'),
    ]
    for pname, pdesc, ptable in prod_specs:
        conn.execute("INSERT INTO form_schemas (name, description, table_name) VALUES (?,?,?)",
                     (pname, pdesc, ptable))
        psid = conn.execute("SELECT id FROM form_schemas WHERE name=?", (pname,)).fetchone()['id']
        prod_fields = [
            ('employee_id', 'text', '员工', 'Employee', 1, 1),
            ('date', 'date', '日期', 'Date', 1, 2),
            ('nickel_h', 'number', 'Nickel(H)产量', 'Nickel(H) Output', 0, 3),
            ('nickel_l', 'number', 'Nickel(L)产量', 'Nickel(L) Output', 0, 4),
            ('mawe', 'number', 'MAWE产量', 'MAWE Output', 0, 5),
        ]
        for f_key, f_type, lzh, len_val, req, order in prod_fields:
            conn.execute("""
                INSERT INTO form_fields (schema_id, field_key, field_type, label_zh, label_en,
                    options, required, sort_order, is_custom, default_value)
                VALUES (?,?,?,?,?,?,?,?,0,'')
            """, (psid, f_key, f_type, lzh, len_val, '[]', req, order))

    conn.commit()
    conn.close()


# ── P5: 旧数据归档 ──────────────────

def attach_archive_db(data_folder, alias='archived'):
    """ATTACH 旧 kilwa.db 为只读归档数据库，返回连接或 None"""
    import os
    archive_path = os.path.join(data_folder, 'archived_kilwa.db')
    if not os.path.exists(archive_path):
        return None
    conn = get_conn(data_folder)
    try:
        conn.execute(f"ATTACH DATABASE ? AS {alias}", (archive_path,))
    except Exception:
        conn.close()
        return None
    return conn

def list_archive_months(data_folder):
    """返回归档数据库中可查询的月份列表"""
    conn = attach_archive_db(data_folder)
    if not conn:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT month FROM archived.monthly_data ORDER BY month DESC"
        ).fetchall()
        conn.close()
        return [r['month'] for r in rows]
    except Exception:
        try:
            conn.close()
        except:
            pass
        return []

def get_archive_salary(data_folder, month):
    """从归档数据库查询指定月份的薪资数据（只读）"""
    conn = attach_archive_db(data_folder)
    if not conn:
        return None
    try:
        name_map = {}
        emp_rows = conn.execute("SELECT id, name FROM archived.employees").fetchall()
        for r in emp_rows:
            name_map[r['id']] = r['name']
        rows = conn.execute(
            "SELECT * FROM archived.monthly_data WHERE month=? ORDER BY net DESC",
            (month,)).fetchall()
        conn.close()
        employees = []
        tg = ta = tn = tnet = 0
        for r in rows:
            eid = r['employee_id']
            name = name_map.get(eid, eid)
            employees.append({
                'name': name, 'employee_id': eid,
                'salary_type': r['salary_type'] or '',
                'piece_underground': r['piece_underground'],
                'piece_driller': r['piece_driller'],
                'piece_crush': r.get('piece_crush', 0),
                'day_rate': r['day_rate'], 'monthly': r['monthly'],
                'gross': r['gross'], 'advance': r['advance'],
                'nssf': r['nssf'], 'net': r['net'],
            })
            tg += r['gross']; ta += r['advance']; tn += r['nssf']; tnet += r['net']
        return {
            'employees': employees,
            'total_gross': tg, 'total_advance': ta,
            'total_nssf': tn, 'total_net': tnet,
            'month': month
        }
    except Exception:
        try:
            conn.close()
        except:
            pass
        return None


# ── P9: 数据采集提交 collection ─────────────────────────

def insert_collection_submission(data_folder, form_type, submission_date, payload, operator_id, department=''):
    """写入一条采集提交，返回 submission_id"""
    month = (submission_date or '')[:7]
    conn = get_conn(data_folder)
    cur = conn.execute("""
        INSERT INTO collection_submissions (form_type, submission_date, payload, operator_id, month, department, version)
        VALUES (?,?,?,?,?,?,1)
    """, (form_type, submission_date, json.dumps(payload, ensure_ascii=False), operator_id, month, department))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid

def get_collection_submissions(data_folder, form_type=None, month=None, date=None, operator=None):
    """查询采集提交列表（最新版本），按日期倒序。form_type/month/date/operator 可过滤"""
    conn = get_conn(data_folder)
    sql = "SELECT * FROM collection_submissions WHERE 1=1"
    params = []
    if form_type:
        sql += " AND form_type=?"
        params.append(form_type)
    if month:
        sql += " AND month=?"
        params.append(month)
    if date:
        sql += " AND submission_date=?"
        params.append(date)
    if operator:
        sql += " AND operator_id=?"
        params.append(operator)
    sql += " ORDER BY submission_date DESC, updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_collection_submission(data_folder, submission_id):
    conn = get_conn(data_folder)
    row = conn.execute("SELECT * FROM collection_submissions WHERE id=?", (submission_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_collection_submission(data_folder, submission_id, payload, operator_id, date=None):
    """再编辑：版本+1，旧 payload 写 collection_history，返回是否成功。
    date 可选：B1 修复——编辑改日期时同步更新 submission_date 与 month"""
    conn = get_conn(data_folder)
    row = conn.execute(
        "SELECT payload, version FROM collection_submissions WHERE id=?", (submission_id,)).fetchone()
    if not row:
        conn.close()
        return False
    old_payload = row['payload']
    old_version = row['version']
    new_version = old_version + 1
    conn.execute("""
        INSERT INTO collection_history (submission_id, version, payload, operator_id)
        VALUES (?,?,?,?)
    """, (submission_id, old_version, old_payload, operator_id))
    if date:
        conn.execute("""
            UPDATE collection_submissions SET payload=?, version=?, operator_id=?, submission_date=?, month=?,
                updated_at=datetime('now','+3 hours')
            WHERE id=?
        """, (json.dumps(payload, ensure_ascii=False), new_version, operator_id, date, (date or '')[:7], submission_id))
    else:
        conn.execute("""
            UPDATE collection_submissions SET payload=?, version=?, operator_id=?,
                updated_at=datetime('now','+3 hours')
            WHERE id=?
        """, (json.dumps(payload, ensure_ascii=False), new_version, operator_id, submission_id))
    conn.commit()
    conn.close()
    return True

def delete_collection_submission(data_folder, submission_id):
    """B1: 删除一条采集提交（编辑改日期覆盖合并时清理被编辑的旧行）。
    先删关联 collection_history（外键约束），再删提交行"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM collection_history WHERE submission_id=?", (submission_id,))
    conn.execute("DELETE FROM collection_submissions WHERE id=?", (submission_id,))
    conn.commit()
    conn.close()
    return True

def get_collection_history(data_folder, submission_id):
    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT * FROM collection_history WHERE submission_id=? ORDER BY version DESC
    """, (submission_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── P10: 评分班组 employee_groups ─────────────────────────

def list_employee_groups(data_folder):
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM employee_groups ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_employee_group(data_folder, group_id):
    conn = get_conn(data_folder)
    row = conn.execute("SELECT * FROM employee_groups WHERE id=?", (group_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_employee_group(data_folder, name, description=''):
    conn = get_conn(data_folder)
    try:
        cur = conn.execute("INSERT INTO employee_groups (name, description) VALUES (?,?)",
                           (name.strip(), description))
        conn.commit()
        gid = cur.lastrowid
    except Exception:
        conn.close()
        return None
    conn.close()
    return gid

def update_employee_group(data_folder, group_id, name, description=None):
    conn = get_conn(data_folder)
    exists = conn.execute("SELECT 1 FROM employee_groups WHERE id=?", (group_id,)).fetchone()
    if not exists:
        conn.close()
        return False
    try:
        if description is not None:
            conn.execute("UPDATE employee_groups SET name=?, description=? WHERE id=?",
                         (name.strip(), description, group_id))
        else:
            conn.execute("UPDATE employee_groups SET name=? WHERE id=?", (name.strip(), group_id))
        conn.commit()
    except Exception:
        conn.close()
        return False
    conn.close()
    return True

def delete_employee_group(data_folder, group_id):
    conn = get_conn(data_folder)
    # 解除员工关联 + 删除班组
    conn.execute("UPDATE employees SET team_id=0 WHERE team_id=?", (group_id,))
    conn.execute("DELETE FROM employee_groups WHERE id=?", (group_id,))
    conn.commit()
    conn.close()
    return True


# ── P12: 钻工队长名单 driller_captains ────────────────────

def get_driller_captains(data_folder):
    """返回钻工队长名单 [{id, employee_id, name, sort_order}]，按 sort_order 排序"""
    conn = get_conn(data_folder)
    rows = conn.execute("SELECT * FROM driller_captains ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_driller_captain(data_folder, employee_id, name):
    """新增钻工队长（sort_order 取 max+1）；重复 employee_id 返回 None"""
    conn = get_conn(data_folder)
    exists = conn.execute(
        "SELECT 1 FROM driller_captains WHERE employee_id=?", (employee_id,)).fetchone()
    if exists:
        conn.close()
        return None
    row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM driller_captains").fetchone()
    cur = conn.execute(
        "INSERT INTO driller_captains (employee_id, name, sort_order) VALUES (?,?,?)",
        (employee_id, name, row['n']))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid

def update_driller_captain(data_folder, captain_id, name=None, sort_order=None):
    """更新钻工队长（name/sort_order 均可 None）；不存在返回 False"""
    conn = get_conn(data_folder)
    exists = conn.execute("SELECT 1 FROM driller_captains WHERE id=?", (captain_id,)).fetchone()
    if not exists:
        conn.close()
        return False
    sets, vals = [], []
    if name is not None:
        sets.append("name=?")
        vals.append(name)
    if sort_order is not None:
        sets.append("sort_order=?")
        vals.append(int(sort_order))
    if not sets:
        conn.close()
        return False
    vals.append(captain_id)
    conn.execute(f"UPDATE driller_captains SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return True

def delete_driller_captain(data_folder, captain_id):
    """删除钻工队长"""
    conn = get_conn(data_folder)
    conn.execute("DELETE FROM driller_captains WHERE id=?", (captain_id,))
    conn.commit()
    conn.close()
    return True
