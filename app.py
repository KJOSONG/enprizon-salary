"""
ENPRIZON LINDI PROJECT — Flask 主入口
"""
import json, os, sys, socket, io, time, secrets
from flask import Flask, jsonify, request, send_from_directory, render_template, send_file, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.config['PREFERRED_URL_SCHEME'] = 'http'
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get('KILWA_SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB 上传上限

@app.context_processor
def inject_static_url():
    prefix = os.environ.get('KILWA_SCRIPT_NAME', '')
    def _static(filename):
        return f'{prefix}/static/{filename}'
    return dict(static_url=_static)

APP_VERSION = str(int(time.time()))

# 禁用浏览器缓存，确保每次加载最新数据
@app.after_request
def disable_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

BASE_DIR = os.path.dirname(__file__)
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['DATA_FOLDER'] = os.path.join(BASE_DIR, 'data')
SOURCE_DIR = os.path.join(BASE_DIR, 'data', 'source')
OVERRIDES_FILE = os.path.join(BASE_DIR, 'data', 'overrides.json')

# ── 硬排除名单（这5人全局不显示、不计薪） ─────────────
HARD_EXCLUDE_IDS = set()
for raw_name in ['Eric Wang QM', 'JIMMY', 'Set sail', '宋家成（Daria）', '宋科举KEJU', '宋科举']:
    from core.namematch import make_employee_id
    eid = make_employee_id(raw_name)
    if eid:
        HARD_EXCLUDE_IDS.add(eid)

# ── 登录认证 ────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'unauthorized', 'need_login': True}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """仅允许 admin 及以上角色执行的操作（editor/viewer 不可用）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'unauthorized', 'need_login': True}), 401
        from core.database import ROLE_LEVELS
        lvl = ROLE_LEVELS.get(session.get('role', ''), 0)
        if lvl < ROLE_LEVELS['admin']:
            return jsonify({'ok': False, 'error': 'forbidden', 'need_admin': True}), 403
        return f(*args, **kwargs)
    return decorated

def editor_required(f):
    """仅允许 editor 及以上角色执行的操作（viewer 不可用）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'unauthorized', 'need_login': True}), 401
        from core.database import ROLE_LEVELS
        lvl = ROLE_LEVELS.get(session.get('role', ''), 0)
        if lvl < ROLE_LEVELS['editor']:
            return jsonify({'ok': False, 'error': 'forbidden', 'need_admin': True}), 403
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    """仅允许 super_admin 执行的操作"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'unauthorized', 'need_login': True}), 401
        from core.database import ROLE_LEVELS
        lvl = ROLE_LEVELS.get(session.get('role', ''), 0)
        if lvl < ROLE_LEVELS['super_admin']:
            return jsonify({'ok': False, 'error': 'forbidden', 'need_admin': True}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/api/login', methods=['POST'])
def api_login():
    from core.database import verify_admin, has_admin, set_admin_password
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not has_admin(app.config['DATA_FOLDER']):
        return jsonify({'ok': False, 'error': 'no_admin', 'need_setup': True})

    if verify_admin(app.config['DATA_FOLDER'], username, password):
        session['logged_in'] = True
        session['username'] = username
        from core.database import get_user_role
        session['role'] = get_user_role(app.config['DATA_FOLDER'], username) or 'admin'
        _audit('login', '', json.dumps({'user': username}))
        return jsonify({'ok': True})
    _audit('login_fail', '', json.dumps({'user': username}))
    return jsonify({'ok': False, 'error': 'invalid_credentials'})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    _audit('logout', '', json.dumps({'user': session.get('username', '')}))
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    from core.database import has_admin
    return jsonify({
        'logged_in': session.get('logged_in', False),
        'username': session.get('username', ''),
        'role': session.get('role', ''),
        'has_admin': has_admin(app.config['DATA_FOLDER']),
    })

@app.route('/api/admin/setup', methods=['POST'])
def admin_setup():
    from core.database import has_admin, set_admin_password
    if has_admin(app.config['DATA_FOLDER']):
        return jsonify({'ok': False, 'error': 'admin_exists'})
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'ok': False, 'error': 'missing_fields'})
    if len(password) < 4:
        return jsonify({'ok': False, 'error': 'password_too_short'})
    set_admin_password(app.config['DATA_FOLDER'], username, password)
    session['logged_in'] = True
    session['username'] = username
    session['role'] = 'super_admin'
    _audit('admin_setup', '', json.dumps({'user': username}))
    return jsonify({'ok': True})

@app.route('/api/admin/change-password', methods=['POST'])
@login_required
def admin_change_password():
    from core.database import verify_admin, set_admin_password
    data = request.get_json(silent=True) or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not new_password or len(new_password) < 4:
        return jsonify({'ok': False, 'error': 'password_too_short'})
    if not verify_admin(app.config['DATA_FOLDER'], session['username'], old_password):
        return jsonify({'ok': False, 'error': 'invalid_old_password'})
    set_admin_password(app.config['DATA_FOLDER'], session['username'], new_password)
    _audit('password_change', '', json.dumps({'user': session['username']}))
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: 用户角色管理（仅 super_admin）
# ═══════════════════════════════════════════════════════════

@app.route('/admin/users', methods=['GET'])
@super_admin_required
def list_users():
    from core.database import list_all_users
    users = list_all_users(app.config['DATA_FOLDER'])
    return jsonify({'ok': True, 'users': users})

@app.route('/admin/users/role', methods=['POST'])
@super_admin_required
def update_user_role():
    from core.database import set_user_role, ROLE_LEVELS
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    role = data.get('role', '').strip()
    if not username or role not in ROLE_LEVELS:
        return jsonify({'ok': False, 'error': '无效参数'}), 400
    try:
        set_user_role(app.config['DATA_FOLDER'], username, role)
        _audit('role_change', username, json.dumps({'new_role': role}))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

def strip_dept(dept):
    """去掉 ENPRIZON LINDI PROJECT 前缀，保留子部门；纯顶层部门保留原名"""
    if not dept:
        return ''
    if dept == 'ENPRIZON LINDI PROJECT':
        return 'ENPRIZON LINDI PROJECT'
    return dept.replace('ENPRIZON LINDI PROJECT/', '')

def _apply_driver_allowance(result):
    """从配置读取司机津贴，加入实发合计（企业级手工输入）"""
    if not result:
        return
    da = (APP_STATE.get('config') or {}).get('driver_allowance', 0)
    if da:
        result['total_net'] = round(result.get('total_net', 0) + da)
    result['driver_allowance'] = da

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)
os.makedirs(SOURCE_DIR, exist_ok=True)

# ── 数据状态 ─────────────────────────────────────────────
APP_STATE = {
    'main_file': None,
    'advance_file': None,
    'addressbook_file': None,
    'basic_info_file': None,
    'parsed': False,
    'calculated': False,
    'employees': [],
    'salary_result': None,
    'address_book': {},
    'source_info': {},          # {type: filename} 记录实际加载的源文件
    'month': None,              # 当前筛选的月份 "2026-05"
    'headless': False,          # 无源数据月份模式
}

def _audit(action, employee_id='', detail='{}'):
    """写审计日志（快捷包装）"""
    from core.database import log_audit
    log_audit(app.config['DATA_FOLDER'], action, employee_id, detail)

# ═══════════════════════════════════════════════════════════
#  文件名无关的文件扫描（按内容特征识别）
# ═══════════════════════════════════════════════════════════

def scan_source_files():
    """扫描 data/source/ 下所有 .xlsx，按内容特征识别"""
    if not os.path.exists(SOURCE_DIR):
        return {}

    import openpyxl
    files = {'main': None, 'advance': None, 'addressbook': None, 'nssf': None, 'crush': None}
    found = []

    for fname in os.listdir(SOURCE_DIR):
        if not fname.endswith('.xlsx'):
            continue
        fpath = os.path.join(SOURCE_DIR, fname)
        try:
            wb = openpyxl.load_workbook(fpath, data_only=True, read_only=True)
            sheets = wb.sheetnames
            wb.close()
        except Exception:
            continue

        found.append((fname, fpath, sheets))

    # 按特征匹配
    for fname, fpath, sheets in found:
        if not files['main'] and ('Piece Rate salary attendance EV' in sheets or 'Daily salary attendance EVERY D' in sheets):
            files['main'] = fpath
        elif not files['advance'] and any('预支' in s for s in sheets):
            files['advance'] = fpath
        elif not files['addressbook'] and any('成员列表' in s or '通讯录' in s for s in sheets):
            files['addressbook'] = fpath
        elif not files['nssf'] and 'Tanzania Mainland' in sheets and 'SDL' in fname.upper():
            files['nssf'] = fpath
        elif not files['crush'] and 'CRUSH TEAM Production Data' in sheets:
            files['crush'] = fpath

    # 回退：按文件名关键词
    if not files['main']:
        for fname, fpath, sheets in found:
            low = fname.lower()
            if 'attendance' in low or 'piece' in low or 'rate' in low or 'main' in low:
                files['main'] = fpath
                break
    if not files['advance']:
        for fname, fpath, sheets in found:
            if '预支' in fname or 'advance' in fname.lower():
                files['advance'] = fpath
                break
    if not files['addressbook']:
        for fname, fpath, sheets in found:
            if '通讯录' in fname or 'address' in fname.lower() or 'contact' in fname.lower():
                files['addressbook'] = fpath
                break
    if not files['nssf']:
        for fname, fpath, sheets in found:
            if 'sdl' in fname.lower() or 'nssf' in fname.lower():
                files['nssf'] = fpath
                break
    if not files['crush']:
        for fname, fpath, sheets in found:
            if 'crush' in fname.lower():
                files['crush'] = fpath
                break

    return files

# ═══════════════════════════════════════════════════════════
#  核心解析+计算引擎（被 auto_load 和 /reload 复用）
# ═══════════════════════════════════════════════════════════

def _run_pipeline(files, month_filter=None):
    """
    执行完整的数据加载→解析→计算管线
    files: {main, advance, addressbook} 文件路径
    month_filter: "2026-05" 或 None（全部）
    返回: (ok, msg)
    """
    from core.parser import parse_all, parse_crush_sheet
    from core.namematch import build_master_list, make_employee_id, canonical
    from core.advance import parse_advance
    from core.addressbook import parse_address_book
    from core.calculator import calculate_all

    if not files.get('main'):
        return False, '未找到主文件（缺少产量/考勤数据表）'
    # ── 通讯录（必须在 build_master_list 之前加载，使 make_employee_id 使用通讯录账号）──
    address_book = {}
    if files.get('addressbook'):
        address_book = parse_address_book(files['addressbook'])
    APP_STATE['address_book'] = address_book


    main_data = parse_all(files['main'])

    # ── 破碎计件数据（非必需）──
    crush_production = []
    if files.get('crush'):
        crush_production = parse_crush_sheet(files['crush'])
    main_data['crush_production'] = crush_production
    employees = build_master_list(main_data)

    # 收集考勤中实际出现的人
    attendance_ids = set()
    for sp in main_data.get('shift_production', []):
        for e in sp.get('day_emps', []):
            eid = make_employee_id(e)
            if eid: attendance_ids.add(eid)
        for e in sp.get('night_emps', []):
            eid = make_employee_id(e)
            if eid: attendance_ids.add(eid)
    for sp in main_data.get('attendance', []):
        for e in sp.get('normal', []):
            eid = make_employee_id(e)
            if eid: attendance_ids.add(eid)

    for cp in crush_production:
        for e in cp.get('personnel', []):
            eid = make_employee_id(e)
            if eid: attendance_ids.add(eid)


    # 通讯录加载后重建硬排除名单（基于账号）
    global HARD_EXCLUDE_IDS
    HARD_EXCLUDE_IDS = set()
    for raw_name in ['Eric Wang QM', 'JIMMY', 'Set sail', '宋家成（Daria）', '宋科举KEJU', '宋科举']:
        from core.namematch import make_employee_id
        eid = make_employee_id(raw_name)
        if eid:
            HARD_EXCLUDE_IDS.add(eid)

    for emp in employees:
        eid = emp['id']
        if eid in address_book:
            info = address_book[eid]
            raw_dept = info.get('department', '')
            emp['department'] = strip_dept(raw_dept)
            emp['phone'] = info.get('phone', '')

            if info.get('guessed_type') and emp['default_type'] in ('both', 'day_rate', 'piece_underground', 'piece_driller'):
                gtype = info['guessed_type']
                if gtype in ('piece_driller', 'piece_underground') and emp['default_type'] == 'both':
                    emp['default_type'] = gtype
                    emp['source'] = 'piece_rate_sheet'
        else:
            emp['department'] = ''
            # 考勤有但通讯录没有 → 标记
            if eid in attendance_ids:
                emp['_note'] = '已离职/通讯录待确认'
            emp['phone'] = ''

    # ── 预支 ──
    advance_data = None
    if files.get('advance'):
        advance_data = parse_advance(files['advance'], month=month_filter)

    if advance_data:
        for emp in employees:
            aid = emp['id']
            emp['advance_total'] = advance_data.get(aid, {}).get('total', 0)

    existing_ids = set(e['id'] for e in employees)
    if advance_data:
        for eid, adv in advance_data.items():
            if eid not in existing_ids:
                name = canonical(adv.get('name', '')) or adv.get('name', eid)
                employees.append({
                    'id': eid, 'name': name, 'default_type': 'advance_only',
                    'source': 'advance_sheet', 'override_type': None, 'overrides': [],
                    'day_rate': 0, 'monthly_salary': 0, 'advance_total': adv['total'],
                    'department': strip_dept(address_book.get(eid, {}).get('department', '')),
                    'phone': address_book.get(eid, {}).get('phone', ''),
                })
                existing_ids.add(eid)

    # ── 顶层部门人员（仅通讯录中存在但不在主数据/预支中的人，不设默认全勤）──
    for eid, info in address_book.items():
        if eid not in existing_ids and info.get("department") == "ENPRIZON LINDI PROJECT":
            employees.append({
                "id": eid, "name": info["name"], "default_type": "day_rate",
                "source": "top_department", "override_type": None, "overrides": [],
                "day_rate": 0, "monthly_salary": 0,
                "advance_total": advance_data.get(eid, {}).get("total", 0) if advance_data else 0,
                "department": "ENPRIZON LINDI PROJECT", "phone": info.get("phone", ""),
            })

    # ── 硬排除过滤 ──
    employees = [e for e in employees if e['id'] not in HARD_EXCLUDE_IDS]

    # ── 离职员工过滤 ──
    from core.database import load_dismissed
    dismissed = load_dismissed(app.config['DATA_FOLDER'])
    employees = [e for e in employees if e['id'] not in dismissed]

    # ── NSSF（社保） ──
    nssf_members = {}
    if files.get('nssf'):
        from core.nssf import parse_sdl_list
        nssf_members = parse_sdl_list(files['nssf'])
    APP_STATE['nssf_sdl_members'] = nssf_members

    # 加载持久化的 NSSF 参保状态
    from core.nssf import load_nssf_enrollment
    nssf_enrollment = load_nssf_enrollment(app.config['DATA_FOLDER'])

    # 初始参保：SDL 名单中的人自动参保
    for emp in employees:
        eid = emp['id']
        if eid in nssf_members and eid not in nssf_enrollment:
            from core.nssf import save_nssf_enrollment
            save_nssf_enrollment(app.config['DATA_FOLDER'], eid, True)
            nssf_enrollment[eid] = {'enrolled': True}
        emp['nssf_enrolled'] = nssf_enrollment.get(eid, {}).get('enrolled', False)

    # ── 加载持久化的日薪/月薪基数 + override_type ──
    from core.database import load_overrides as _load_ov
    saved_overrides = _load_ov(app.config['DATA_FOLDER'])
    for emp in employees:
        eid = emp['id']
        if eid in saved_overrides:
            for o in saved_overrides[eid]:
                has_range = bool(o.get('start_date', '') or o.get('end_date', ''))
                st = o.get('salary_type', '')
                # 仅永久覆盖（无日期区间）更新 override_type，临时例外不影响基础类型
                if not has_range and st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                    emp['override_type'] = st
                # 日薪/月薪基数（临时例外也需要用于 calc_day_salary）
                if st == 'day_rate' and o.get('day_rate', 0) > 0:
                    emp['day_rate'] = o['day_rate']
                if st == 'monthly' and o.get('monthly_salary', 0) > 0:
                    emp['monthly_salary'] = o['monthly_salary']
        # 清零：仅基于永久覆盖类型，临时例外不触发清零
        ot = emp.get('override_type')
        if ot == 'day_rate':
            emp['monthly_salary'] = 0
        elif ot == 'monthly':
            emp['day_rate'] = 0
        elif ot in ('piece_underground', 'piece_driller', 'piece_crush'):
            emp['day_rate'] = 0
            emp['monthly_salary'] = 0

    # ── 月份筛选（过滤所有数据源，不仅仅是 dates） ──
    if month_filter:
        for key in ('dates', 'shift_production', 'driller_production', 'attendance', 'crush_production'):
            if main_data.get(key):
                if key == 'dates':
                    main_data[key] = [d for d in main_data[key] if d.startswith(month_filter)]
                else:
                    main_data[key] = [d for d in main_data[key] if d.get('date', '').startswith(month_filter)]

    # ── 加载计算配置（仅首次） ──
    if not APP_STATE.get('config'):
        from core.pricing import load_config
        APP_STATE['config'] = load_config(app.config['DATA_FOLDER'])

    # ── 计算（传入当前覆盖，确保手动调整生效） ──
    from core.exceptions import load_overrides as _load_override_ov, load_daily_exclusions as _load_excl
    from core.database import load_bonus_penalties as _load_bp
    overrides = _load_override_ov(app.config['DATA_FOLDER'])
    exclusions = _load_excl(app.config['DATA_FOLDER'])
    bonus_penalties = _load_bp(app.config['DATA_FOLDER'], month_filter) if month_filter else {}
    result = calculate_all(main_data, employees, overrides=overrides, exclusions=exclusions,
                           pricing=APP_STATE['config'], data_folder=app.config['DATA_FOLDER'],
                           bonus_penalties=bonus_penalties)

    # ── 司机津贴（企业级手工输入，计入实发合计） ──
    _apply_driver_allowance(result)
    APP_STATE['parsed'] = True
    APP_STATE['calculated'] = True
    APP_STATE['employees'] = employees
    APP_STATE['main_data'] = main_data
    APP_STATE['advance_data'] = advance_data
    APP_STATE['salary_result'] = result
    APP_STATE['month'] = month_filter
    APP_STATE['source_info'] = {
        'main': os.path.basename(files['main']) if files.get('main') else None,
        'advance': os.path.basename(files['advance']) if files.get('advance') else None,
        'addressbook': os.path.basename(files['addressbook']) if files.get('addressbook') else None,
        'crush': os.path.basename(files['crush']) if files.get('crush') else None,
    }

    # 保存当月结果到数据库（仅在有月份筛选时，确保数据准确）
    if result and month_filter and main_data.get('dates'):
        from core.database import save_monthly_result
        save_monthly_result(app.config['DATA_FOLDER'], month_filter, result)

    return True, f'已加载 {len(employees)} 名员工，应发 {result["total_gross"]:,} TZS'

# ═══════════════════════════════════════════════════════════
#  静态页面
# ═══════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html', version=APP_VERSION)

@app.route('/static/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

# ═══════════════════════════════════════════════════════════
#  API: 数据源信息
# ═══════════════════════════════════════════════════════════

@app.route('/source-info', methods=['GET'])
def get_source_info():
    """返回当前加载的源文件信息"""
    return jsonify(APP_STATE.get('source_info', {}))

@app.route('/available-months', methods=['GET'])
def get_available_months():
    """返回可选的月份列表（源数据 + 数据库 + 当前及未来月份）"""
    from datetime import datetime
    months = set()
    # 从已加载的源数据提取
    md = APP_STATE.get('main_data', {})
    for d in md.get('dates', []):
        months.add(d[:7])
    # 从数据库补充历史月份
    from core.database import list_monthly_months, get_conn
    months.update(list_monthly_months(app.config['DATA_FOLDER']))
    # 包含当前月及未来2个月（支持提前记录出勤）
    now = datetime.now()
    for i in range(3):
        y = now.year + (now.month + i - 1) // 12
        m = (now.month + i - 1) % 12 + 1
        months.add(f'{y}-{m:02d}')
    # 从出勤覆盖表和奖金罚款表补充月份
    try:
        conn = get_conn(app.config['DATA_FOLDER'])
        for r in conn.execute("SELECT DISTINCT substr(date,1,7) FROM attendance_overrides WHERE date LIKE '____-__-__'").fetchall():
            if r[0]: months.add(r[0])
        for r in conn.execute("SELECT DISTINCT month FROM bonus_penalties").fetchall():
            if r[0]: months.add(r[0])
        conn.close()
    except: pass
    return jsonify(sorted(months, reverse=True))

# ═══════════════════════════════════════════════════════════
#  API: 重新加载
# ═══════════════════════════════════════════════════════════

@app.route('/reload', methods=['POST'])
@admin_required
def reload_source():
    """从 data/source/ 重新加载所有数据"""
    files = scan_source_files()
    ok, msg = _run_pipeline(files, month_filter=APP_STATE.get('month'))
    if not ok:
        return jsonify({'ok': False, 'error': msg})
    _audit('reload_source', '', json.dumps({'employees': len(APP_STATE['employees'])}))
    return jsonify({
        'ok': True, 'message': msg,
        'summary': {
            'total_employees': len(APP_STATE['employees']),
            'piece_underground': sum(1 for e in APP_STATE['employees'] if e['default_type'] == 'piece_underground'),
            'piece_driller': sum(1 for e in APP_STATE['employees'] if e['default_type'] == 'piece_driller'),
            'piece_crush': sum(1 for e in APP_STATE['employees'] if e['default_type'] == 'piece_crush'),
            'day_rate': sum(1 for e in APP_STATE['employees'] if e['default_type'] == 'day_rate'),
            'advance_only': sum(1 for e in APP_STATE['employees'] if e['default_type'] == 'advance_only'),
            'overlap_need_decision': sum(1 for e in APP_STATE['employees'] if e.get('source') in ('both',)),
        },
        'employees': APP_STATE['employees'],
        'dates': APP_STATE['main_data'].get('dates', []),
        'salary': APP_STATE['salary_result'],
    })

# ═══════════════════════════════════════════════════════════
#  API: 上传源文件
# ═══════════════════════════════════════════════════════════

ALLOWED_FILE_TYPES = {'main', 'advance', 'addressbook', 'nssf', 'crush'}

# ═══════════════════════════════════════════════════════════
#  API: 下载源文件模板
# ═══════════════════════════════════════════════════════════

@app.route('/download-source/<file_type>', methods=['GET'])
@login_required
def download_source(file_type):
    """下载当前源文件作为模板参考"""
    if file_type not in ALLOWED_FILE_TYPES:
        return jsonify({'ok': False, 'error': f'无效的文件类型: {file_type}'}), 400

    files = scan_source_files()
    filepath = files.get(file_type)
    if not filepath or not os.path.exists(filepath):
        return jsonify({'ok': False, 'error': f'当前无{file_type}类型的源文件, 请先上传'}), 404

    filename = os.path.basename(filepath)
    return send_file(filepath, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def _validate_source_file(file_type, filepath):
    """校验上传文件是否能被对应解析器正确解析并返回有效数据"""
    try:
        if file_type == 'main':
            from core.parser import parse_all
            data = parse_all(filepath)
            if not data.get('dates'):
                return False, '主文件中未找到任何日期数据，请确认 Sheet1/Sheet2 包含有效日期'
            if not data.get('employees') and not data.get('shift_production'):
                return False, '主文件中未找到员工或产量数据，请检查表格格式'
            return True, ''

        elif file_type == 'advance':
            from core.advance import parse_advance
            data = parse_advance(filepath)
            if not data:
                return False, '预支文件中未提取到任何预支记录，请确认 B 列为姓名、C 列为笔数、D 列为总额'
            return True, ''

        elif file_type == 'addressbook':
            from core.addressbook import parse_address_book
            data = parse_address_book(filepath)
            if not data:
                return False, '通讯录文件中未提取到任何员工信息，请确认 Sheet 名为「成员列表」且含有效数据'
            return True, ''

        elif file_type == 'nssf':
            from core.nssf import parse_sdl_list
            data = parse_sdl_list(filepath)
            if not data:
                return False, 'NSSF 文件中未提取到任何参保记录，请确认 Sheet 名为「Tanzania Mainland」'
            return True, ''

        elif file_type == 'crush':
            from core.parser import parse_crush_sheet
            data = parse_crush_sheet(filepath)
            if not data:
                return False, '破碎计件文件中未找到有效数据，请确认 Sheet 名为「CRUSH TEAM Production Data」'
            return True, ''

    except Exception as e:
        return False, f'文件解析失败: {str(e)}'

@app.route('/upload-source', methods=['POST'])
@admin_required
def upload_source():
    """管理员上传 Excel 源文件，自动覆盖旧文件并重载数据"""
    file_type = request.form.get('file_type', '')
    if file_type not in ALLOWED_FILE_TYPES:
        return jsonify({'ok': False, 'error': f'无效的文件类型: {file_type}'}), 400

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'ok': False, 'error': '未选择文件'}), 400

    if not file.filename.lower().endswith('.xlsx'):
        return jsonify({'ok': False, 'error': '仅支持 .xlsx 格式文件'}), 400

    # 确保目录存在
    os.makedirs(SOURCE_DIR, exist_ok=True)

    # 扫描当前文件，删除同类型的旧文件
    import openpyxl
    for fname in os.listdir(SOURCE_DIR):
        if not fname.endswith('.xlsx'):
            continue
        fpath = os.path.join(SOURCE_DIR, fname)
        try:
            wb = openpyxl.load_workbook(fpath, data_only=True, read_only=True)
            sheets = wb.sheetnames
            wb.close()
        except Exception:
            continue

        # 按类型匹配删除
        is_main = 'Piece Rate salary attendance EV' in sheets or 'Daily salary attendance EVERY D' in sheets
        is_advance = any('预支' in s for s in sheets)
        is_addressbook = any('成员列表' in s or '通讯录' in s for s in sheets)
        is_nssf = 'Tanzania Mainland' in sheets and 'SDL' in fname.upper()

        if (file_type == 'main' and is_main) or \
           (file_type == 'advance' and is_advance) or \
           (file_type == 'addressbook' and is_addressbook) or \
           (file_type == 'nssf' and is_nssf):
            os.remove(fpath)

    # 保存新文件
    safe_name = secure_filename(file.filename)
    save_path = os.path.join(SOURCE_DIR, safe_name)
    file.save(save_path)

    # ── 校验：解析试运行 ──
    ok, validate_msg = _validate_source_file(file_type, save_path)
    if not ok:
        os.remove(save_path)  # 校验失败，删除文件
        return jsonify({'ok': False, 'error': validate_msg}), 400

    # 重新加载数据管线
    files = scan_source_files()
    ok, msg = _run_pipeline(files, month_filter=APP_STATE.get('month'))
    if not ok:
        # 管线失败也删除已上传文件，避免污染
        os.remove(save_path)
        return jsonify({'ok': False, 'error': msg}), 500

    _audit('upload_source', file_type, safe_name)

    return jsonify({
        'ok': True,
        'message': msg,
        'filename': safe_name,
        'source_info': APP_STATE.get('source_info', {}),
        'summary': {
            'total_employees': len(APP_STATE['employees']),
        },
        'employees': APP_STATE['employees'],
        'salary': APP_STATE['salary_result'],
    })

# ═══════════════════════════════════════════════════════════
#  API: 月份切换
# ═══════════════════════════════════════════════════════════

@app.route('/set-month', methods=['POST'])
@editor_required
def set_month():
    """切换月份筛选，始终以当前覆盖重算。无源数据的月份自动进入 Headless 预览模式"""
    data = request.get_json()
    month = data.get('month', '')

    files = scan_source_files()
    ok, msg = _run_pipeline(files, month_filter=month if month != 'all' else None)
    if not ok:
        return jsonify({'ok': False, 'error': msg})

    # ── Headless 模式：当月无源数据但员工列表存在 → 生成当月全部日期 ──
    APP_STATE['headless'] = False
    if month and month != 'all':
        md = APP_STATE.get('main_data', {})
        if not md.get('dates') and APP_STATE.get('employees'):
            import calendar
            y, m = int(month[:4]), int(month[5:7])
            _, last_day = calendar.monthrange(y, m)
            generated_dates = [f'{month}-{d:02d}' for d in range(1, last_day + 1)]
            md['dates'] = generated_dates
            md['shift_production'] = []
            md['driller_production'] = []
            md['attendance'] = []
            APP_STATE['main_data'] = md
            APP_STATE['headless'] = True
            msg = f'预览模式 — {month} 暂无源数据，已生成 {len(generated_dates)} 个日期列，仅支持出勤记录'

    # 加载完成后始终按当前覆盖重算（保证手动类型/出勤等生效）
    from core.calculator import calculate_all
    from core.exceptions import load_overrides, load_daily_exclusions
    from core.database import load_bonus_penalties as _load_bp2
    overrides = load_overrides(app.config['DATA_FOLDER'])
    exclusions = load_daily_exclusions(app.config['DATA_FOLDER'])
    bonus_penalties = _load_bp2(app.config['DATA_FOLDER'], month) if month else {}
    result = calculate_all(
        main_data=APP_STATE.get('main_data', {}),
        employees=APP_STATE.get('employees', []),
        overrides=overrides, exclusions=exclusions,
        pricing=APP_STATE.get('config', {}),
        data_folder=app.config['DATA_FOLDER'],
        bonus_penalties=bonus_penalties,
    )
    # ── 司机津贴 ──
    _apply_driver_allowance(result)
    APP_STATE['salary_result'] = result

    return jsonify({'ok': True, 'message': msg, 'salary': result, 'headless': APP_STATE.get('headless', False)})

# ═══════════════════════════════════════════════════════════
#  API: 员工管理
# ═══════════════════════════════════════════════════════════

@app.route('/employees', methods=['GET'])
def get_employees():
    from core.exceptions import load_overrides
    from core.database import load_bonus_penalties as _load_bp_emp
    overrides = load_overrides(app.config['DATA_FOLDER'])
    month = APP_STATE.get('month')
    bonus_penalties = _load_bp_emp(app.config['DATA_FOLDER'], month) if month else {}
    for emp in APP_STATE.get('employees', []):
        eid = emp['id']
        emp['overrides'] = overrides.get(eid, [])
        # 根据 overrides 同步覆盖字段（仅永久覆盖影响 override_type）
        emp['override_type'] = None
        for o in emp['overrides']:
            has_range = bool(o.get('start_date', '') or o.get('end_date', ''))
            st = o.get('salary_type')
            if not has_range and st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                emp['override_type'] = st
            if st == 'day_rate' and o.get('day_rate', 0) > 0:
                emp['day_rate'] = o['day_rate']
            if st == 'monthly' and o.get('monthly_salary', 0) > 0:
                emp['monthly_salary'] = o['monthly_salary']
        # 清零不匹配最终类型的基数
        ot = emp.get('override_type')
        if ot == 'day_rate':
            emp['monthly_salary'] = 0
        elif ot == 'monthly':
            emp['day_rate'] = 0
        elif ot in ('piece_underground', 'piece_driller', 'piece_crush'):
            emp['day_rate'] = 0
            emp['monthly_salary'] = 0
        # 附加当月奖金/罚款
        bp = bonus_penalties.get(eid, {})
        emp['bonus'] = bp.get('bonus', 0)
        emp['penalty'] = bp.get('penalty', 0)
    return jsonify({'employees': APP_STATE.get('employees', []), 'headless': APP_STATE.get('headless', False)})

@app.route('/employees/override', methods=['POST'])
@editor_required
def save_override():
    data = request.get_json()
    eid = data.get('employee_id', '')
    if data.get('type') == 'exclusion':
        from core.exceptions import save_exclusion
        save_exclusion(app.config['DATA_FOLDER'], data)
    else:
        from core.exceptions import save_override as _save
        _save(app.config['DATA_FOLDER'], data)
        # 同步内存状态（临时例外不改变 override_type）
        for emp in APP_STATE.get('employees', []):
            if emp['id'] == eid:
                has_range = bool(data.get('start_date', '') or data.get('end_date', ''))
                st = data.get('salary_type')
                if not has_range and st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                    emp['override_type'] = st
                if st == 'day_rate' and data.get('day_rate', 0) > 0:
                    emp['day_rate'] = data['day_rate']
                if st == 'monthly' and data.get('monthly_salary', 0) > 0:
                    emp['monthly_salary'] = data['monthly_salary']
                break
    _audit('override_save', eid, json.dumps({
        'name': next((e['name'] for e in APP_STATE.get('employees',[]) if e['id']==eid), eid),
        'salary_type': data.get('salary_type'),
        'day_rate': data.get('day_rate',0),
        'monthly_salary': data.get('monthly_salary',0),
    }))
    return jsonify({'ok': True})

@app.route('/employees/remove-override', methods=['POST'])
@editor_required
def remove_override():
    data = request.get_json()
    from core.exceptions import remove_override
    remove_override(app.config['DATA_FOLDER'], data.get('employee_id'), data.get('index'))
    return jsonify({'ok': True})

@app.route('/employees/remove-temp-override', methods=['POST'])
@editor_required
def remove_temp_override():
    """删除指定员工的所有临时例外（有日期区间的 override），由薪资页面备注管理触发"""
    data = request.get_json()
    eid = data.get('employee_id', '')
    if not eid:
        return jsonify({'ok': False, 'error': '缺少 employee_id'}), 400
    import sqlite3, os
    db_path = os.path.join(app.config['DATA_FOLDER'], 'kilwa.db')
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM overrides WHERE employee_id=? AND (start_date!='' OR end_date!='') AND (type IS NULL OR type != 'exclusion')", (eid,))
    conn.commit()
    conn.close()
    _audit('remove_temp_override', eid)
    return jsonify({'ok': True})

@app.route('/employees/remove-override-by-id', methods=['POST'])
@editor_required
def remove_override_by_id():
    """按数据库 ID 删除单条覆盖记录"""
    data = request.get_json()
    oid = data.get('override_id')
    if not oid:
        return jsonify({'ok': False, 'error': '缺少 override_id'}), 400
    import sqlite3, os
    db_path = os.path.join(app.config['DATA_FOLDER'], 'kilwa.db')
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM overrides WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    _audit('remove_override_by_id', str(oid))
    return jsonify({'ok': True})

@app.route('/employees/bonus-penalty', methods=['POST'])
@editor_required
def save_bonus_penalty():
    """保存单个员工的奖金/罚款（当月独立）"""
    import json as _json
    data = request.get_json()
    eid = data.get('employee_id', '')
    month = data.get('month', '')
    bonus = data.get('bonus', 0)
    penalty = data.get('penalty', 0)
    if not eid or not month:
        return jsonify({'ok': False, 'error': '缺少 employee_id 或 month'}), 400
    from core.database import save_bonus_penalty as _save_bp
    _save_bp(app.config['DATA_FOLDER'], eid, month, bonus, penalty)
    _audit('bonus_penalty_update', eid, _json.dumps({'month': month, 'bonus': bonus, 'penalty': penalty}))
    return jsonify({'ok': True})

# ── 离职员工管理 ──

@app.route('/employees/dismissed', methods=['GET'])
def get_dismissed_employees():
    """获取已离职员工列表（含姓名）"""
    from core.database import load_dismissed_with_info
    dismissed = load_dismissed_with_info(app.config['DATA_FOLDER'])
    # 从当前员工列表补姓名
    emp_map = {e['id']: e.get('name', e['id']) for e in APP_STATE.get('employees', [])}
    # 也尝试从历史数据中查找（因为离职员工已不在 employees 中）
    for d in dismissed:
        d['name'] = emp_map.get(d['employee_id'], d['employee_id'])
    return jsonify(dismissed)

@app.route('/employees/dismiss', methods=['POST'])
@editor_required
def dismiss_employee_api():
    """标记员工为离职（从列表中隐藏，可恢复）"""
    import json as _json
    data = request.get_json()
    eid = data.get('employee_id', '')
    note = data.get('note', '')
    if not eid:
        return jsonify({'ok': False, 'error': '缺少 employee_id'}), 400
    from core.database import dismiss_employee as _dismiss
    _dismiss(app.config['DATA_FOLDER'], eid, note)
    _audit('dismiss_employee', eid, _json.dumps({'note': note}))
    # 从内存列表中移除
    APP_STATE['employees'] = [e for e in APP_STATE.get('employees', []) if e['id'] != eid]
    return jsonify({'ok': True})

@app.route('/employees/restore', methods=['POST'])
@editor_required
def restore_employee_api():
    """恢复已离职员工"""
    data = request.get_json()
    eid = data.get('employee_id', '')
    if not eid:
        return jsonify({'ok': False, 'error': '缺少 employee_id'}), 400
    from core.database import restore_employee as _restore
    _restore(app.config['DATA_FOLDER'], eid)
    _audit('restore_employee', eid)
    # 重新加载以获取完整员工数据
    files = scan_source_files()
    ok, msg = _run_pipeline(files, month_filter=APP_STATE.get('month') if APP_STATE.get('month') != 'all' else None)
    return jsonify({'ok': True, 'message': msg})

# ═══════════════════════════════════════════════════════════
#  API: NSSF（社保）
# ═══════════════════════════════════════════════════════════

@app.route('/nssf/list', methods=['GET'])
def get_nssf_list():
    """获取 NSSF 参保状态列表"""
    from core.nssf import load_nssf_enrollment
    enrollment = load_nssf_enrollment(app.config['DATA_FOLDER'])
    sdl = APP_STATE.get('nssf_sdl_members', {})
    return jsonify({
        'enrollment': enrollment,
        'sdl_members': {k: v['name'] for k, v in sdl.items()},
    })

@app.route('/nssf/toggle', methods=['POST'])
@editor_required
def toggle_nssf():
    """切换某人的 NSSF 参保状态"""
    data = request.get_json()
    eid = data.get('employee_id')
    enrolled = data.get('enrolled', False)
    from core.nssf import save_nssf_enrollment
    save_nssf_enrollment(app.config['DATA_FOLDER'], eid, enrolled)
    # 同步内存状态
    for emp in APP_STATE.get('employees', []):
        if emp['id'] == eid:
            emp['nssf_enrolled'] = enrolled
            break
    _audit('nssf_toggle', eid, json.dumps({'enrolled': enrolled}))
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: 通讯录
# ═══════════════════════════════════════════════════════════

@app.route('/addressbook', methods=['GET'])
def get_addressbook():
    book = APP_STATE.get('address_book', {})
    from collections import defaultdict
    by_dept = defaultdict(list)
    for eid, info in book.items():
        dept = info.get('department', '未分类')
        by_dept[dept].append({'id': eid, **info})
    sorted_depts = sorted(by_dept.items(), key=lambda x: -len(x[1]))
    return jsonify({
        'total': len(book),
        'departments': [{'name': d, 'count': len(p), 'people': p} for d, p in sorted_depts]
    })

# ═══════════════════════════════════════════════════════════
#  API: 计算参数配置
# ═══════════════════════════════════════════════════════════

@app.route('/config', methods=['GET'])
def get_config():
    from core.pricing import load_config
    return jsonify(load_config(app.config['DATA_FOLDER']))

@app.route('/config', methods=['POST'])
@admin_required
def save_config():
    from core.pricing import load_config, save_config as _save_cfg
    incoming = request.get_json()
    config = load_config(app.config['DATA_FOLDER'])
    config.update(incoming)
    _save_cfg(app.config['DATA_FOLDER'], config)
    APP_STATE['config'] = config  # 同步内存
    _audit('config_update', '', json.dumps({'keys': list(incoming.keys())}))
    return jsonify({'ok': True, 'config': config})

# ═══════════════════════════════════════════════════════════
#  API: 计算/薪资
# ═══════════════════════════════════════════════════════════

@app.route('/recalculate', methods=['POST'])
@admin_required
def recalculate():
    if not APP_STATE.get('parsed'):
        return jsonify({'ok': False, 'error': '请先加载数据'})
    from core.calculator import calculate_all
    from core.exceptions import load_overrides, load_daily_exclusions
    from core.database import load_bonus_penalties as _load_bp3
    overrides = load_overrides(app.config['DATA_FOLDER'])
    exclusions = load_daily_exclusions(app.config['DATA_FOLDER'])
    month = APP_STATE.get('month')
    bonus_penalties = _load_bp3(app.config['DATA_FOLDER'], month) if month else {}
    result = calculate_all(
        main_data=APP_STATE.get('main_data', {}),
        employees=APP_STATE.get('employees', []),
        overrides=overrides, exclusions=exclusions,
        pricing=APP_STATE.get('config', {}),
        data_folder=app.config['DATA_FOLDER'],
        bonus_penalties=bonus_penalties,
    )
    # ── 司机津贴 ──
    _apply_driver_allowance(result)
    APP_STATE['calculated'] = True
    APP_STATE['salary_result'] = result
    _audit('recalculate', '', json.dumps({'total_gross': result['total_gross']}))
    return jsonify({'ok': True, 'result': result})

@app.route('/salary', methods=['GET'])
def get_salary():
    return jsonify({'result': APP_STATE.get('salary_result'), 'headless': APP_STATE.get('headless', False)})

# ═══════════════════════════════════════════════════════════
#  API: 薪资双路径核对
# ═══════════════════════════════════════════════════════════

@app.route('/salary/verify', methods=['GET'])
def verify_salary():
    """双路径薪资核对：路径一（产量×单价基准计算）vs 路径二（实际汇总）"""
    from core.verification import verify_salary as do_verify
    from core.calculator import PRICES_UNDERGROUND, PRICES_DRILLER

    main_data = APP_STATE.get('main_data', {})
    salary_result = APP_STATE.get('salary_result')

    if not main_data or not salary_result:
        return jsonify({'error': '数据尚未就绪，请先加载源文件并执行计算'}), 400

    try:
        config = APP_STATE.get('config') or {}
        up = config.get('underground_prices') or PRICES_UNDERGROUND
        dp = config.get('driller_prices') or PRICES_DRILLER
        result = do_verify(main_data, salary_result, up, dp)
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'error': f'核对失败: {str(e)}'}), 500

# ═══════════════════════════════════════════════════════════
#  API: 产量
# ═══════════════════════════════════════════════════════════

@app.route('/production', methods=['GET'])
def get_production():
    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])

    shift_daily = []
    for d in shift_prod:
        dp = d.get('day_prod') or {}
        np = d.get('night_prod') or {}
        shift_daily.append({
            'date': d['date'],
            'nh': (dp.get('NICKEL（H）', 0) or 0) + (np.get('NICKEL（H）', 0) or 0),
            'nl': (dp.get('NICKEL（L）', 0) or 0) + (np.get('NICKEL（L）', 0) or 0),
            'mw': (dp.get('MAWE', 0) or 0) + (np.get('MAWE', 0) or 0),
        })

    from collections import defaultdict
    cap_totals = defaultdict(lambda: {'nh': 0, 'nl': 0, 'mw': 0, 'futa': 0, 'waya': 0, 'kibiriti': 0, 'name': ''})
    for d in driller_prod:
        cap = d['captain']
        cap_totals[cap]['name'] = cap
        cap_totals[cap]['nh'] += d['nh']
        cap_totals[cap]['nl'] += d['nl']
        cap_totals[cap]['mw'] += d['mw']
        cap_totals[cap]['futa'] += d['futa']
        cap_totals[cap]['waya'] += d['waya']
        cap_totals[cap]['kibiriti'] += d['kibiriti']

    driller_summary = [v for _, v in sorted(cap_totals.items())]
    return jsonify({
        'shift_production': shift_daily,
        'driller_production': driller_summary,
        'driller_consumables': [{'name': v['name'],
                                  'futa': v['futa'], 'waya': v['waya'],
                                  'kibiriti': v['kibiriti']}
                                for v in driller_summary],
    })

# ═══════════════════════════════════════════════════════════
#  API: 产量核验（逐日对比钻工组与井下合计）
# ═══════════════════════════════════════════════════════════

@app.route('/production-verify', methods=['GET'])
def get_production_verify():
    """返回逐日钻工组产量与井下白班+夜班产量对比"""
    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])

    # 井下逐日合计
    shift_daily = {}
    for d in shift_prod:
        dp = d.get('day_prod') or {}
        np = d.get('night_prod') or {}
        dt = d['date']
        if dt not in shift_daily:
            shift_daily[dt] = {'nh': 0, 'nl': 0, 'mw': 0}
        shift_daily[dt]['nh'] += (dp.get('NICKEL（H）', 0) or 0) + (np.get('NICKEL（H）', 0) or 0)
        shift_daily[dt]['nl'] += (dp.get('NICKEL（L）', 0) or 0) + (np.get('NICKEL（L）', 0) or 0)
        shift_daily[dt]['mw'] += (dp.get('MAWE', 0) or 0) + (np.get('MAWE', 0) or 0)

    # 钻工逐日分组
    from collections import defaultdict
    driller_daily = defaultdict(lambda: defaultdict(lambda: {'nh': 0, 'nl': 0, 'mw': 0}))
    for d in driller_prod:
        dt = d['date']
        cap = d['captain']
        driller_daily[dt][cap]['nh'] += d['nh']
        driller_daily[dt][cap]['nl'] += d['nl']
        driller_daily[dt][cap]['mw'] += d['mw']

    # 构建返回数据
    all_dates = sorted(set(list(shift_daily.keys()) + list(driller_daily.keys())))
    result = {}
    for dt in all_dates:
        dtot = {'nh': 0, 'nl': 0, 'mw': 0}
        groups = []
        for cap, g in sorted(driller_daily.get(dt, {}).items()):
            groups.append({'captain': cap, 'nh': g['nh'], 'nl': g['nl'], 'mw': g['mw']})
            dtot['nh'] += g['nh']; dtot['nl'] += g['nl']; dtot['mw'] += g['mw']
        st = shift_daily.get(dt, {'nh': 0, 'nl': 0, 'mw': 0})
        result[dt] = {
            'driller_groups': groups,
            'driller_total': dtot,
            'shift_total': st,
            'match': dtot['nh'] == st['nh'] and dtot['nl'] == st['nl'] and dtot['mw'] == st['mw'],
        }
    return jsonify(result)

# ═══════════════════════════════════════════════════════════
#  API: 逐日工资明细
# ═══════════════════════════════════════════════════════════

@app.route('/daily-wages', methods=['GET'])
def get_daily_wages():
    """返回每个员工的逐日工资"""
    from core.calculator import compute_daily_breakdown
    from core.exceptions import load_overrides, load_daily_exclusions
    if not APP_STATE.get('main_data'):
        return jsonify({})
    result = compute_daily_breakdown(
        main_data=APP_STATE['main_data'],
        employees=APP_STATE['employees'],
        overrides=load_overrides(app.config['DATA_FOLDER']),
        exclusions=load_daily_exclusions(app.config['DATA_FOLDER']),
        pricing=APP_STATE.get('config', {}),
        data_folder=app.config['DATA_FOLDER'],
    )
    # 合并出勤手动覆盖（P/A/L）到逐日工资结果
    import sqlite3, os
    att_ov = {}
    db_path = os.path.join(app.config['DATA_FOLDER'], 'kilwa.db')
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            for r in conn.execute("SELECT employee_id, date FROM attendance_overrides").fetchall():
                key = f"{r[0]}|{r[1]}"
                att_ov[key] = True
        except: pass
        conn.close()
    # 构建每个员工的 att_override_dates
    for eid, e in result.items():
        att_dates = []
        for dt in e.get('daily', {}):
            if f"{eid}|{dt}" in att_ov:
                att_dates.append(dt)
        if att_dates:
            e['att_override_dates'] = att_dates
        else:
            e['att_override_dates'] = []
    return jsonify(result)

# ═══════════════════════════════════════════════════════════
#  API: 钻工队长列表（用于临时例外弹窗）
# ═══════════════════════════════════════════════════════════

@app.route('/driller-captains', methods=['GET'])
def get_driller_captains():
    """返回所有钻工队长列表（不按日期过滤，用于临时例外弹窗）"""
    md = APP_STATE.get('main_data', {})
    captains = set()
    for d in md.get('driller_production', []):
        captains.add(d['captain'])
    return jsonify(sorted(captains))

# ═══════════════════════════════════════════════════════════
#  API: 出勤网格
# ═══════════════════════════════════════════════════════════

@app.route('/attendance', methods=['GET'])
def get_attendance():
    """返回出勤网格：每人每天的状态。P=出勤 A=旷工 L=请假"""
    import json as _json
    from collections import defaultdict
    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])
    attendance_data = md.get('attendance', [])
    employees = APP_STATE.get('employees', [])

    # 收集所有日期
    all_dates = sorted(set(
        list(set(d['date'] for d in shift_prod)) +
        list(set(d.get('date', '') for d in attendance_data)) +
        list(md.get('dates', []))
    ))
    # 补全当月全部自然日（确保没有数据时也能看到所有日期）
    if all_dates:
        from calendar import monthrange
        ym = all_dates[0][:7]
        if ym and len(ym) == 7:
            y, m = int(ym[:4]), int(ym[5:7])
            _, last_day = monthrange(y, m)
            all_dates = sorted(set(all_dates) | set(f"{ym}-{d:02d}" for d in range(1, last_day + 1)))

    # 收集每人每天的状态（原始来源）
    day_status = defaultdict(dict)
    day_origin = defaultdict(dict)  # 'auto' or 'manual'

    # 加载手动覆盖
    from core.database import load_attendance_overrides
    manual = load_attendance_overrides(app.config['DATA_FOLDER'])

    # 井下计件：白班=D 夜班=N 全天=B
    for d in shift_prod:
        dt = d['date']
        for e in d.get('day_emps', []):
            from core.namematch import make_employee_id
            eid = make_employee_id(e)
            if eid:
                day_status[eid][dt] = 'D'
                day_origin[eid][dt] = 'auto'
        for e in d.get('night_emps', []):
            eid = make_employee_id(e)
            if eid:
                existing = day_status.get(eid, {}).get(dt, '')
                day_status[eid][dt] = 'B' if existing == 'D' else 'N'
                day_origin[eid][dt] = 'auto'

    # 钻工出勤
    for d in driller_prod:
        dt = d['date']
        from core.namematch import make_employee_id, canonical
        cap_id = make_employee_id(d['captain'])
        if cap_id and dt not in day_status.get(cap_id, {}):
            day_status[cap_id][dt] = 'R'
            day_origin[cap_id][dt] = 'auto'
        for m in d.get('members', []):
            mid = make_employee_id(m)
            if mid and dt not in day_status.get(mid, {}):
                day_status[mid][dt] = 'R'
                day_origin[mid][dt] = 'auto'

    # 破碎计件出勤
    crush_data = md.get('crush_production', [])
    for d in crush_data:
        dt = d['date']
        for e in d.get('personnel', []):
            eid = make_employee_id(e)
            if eid and dt not in day_status.get(eid, {}):
                day_status[eid][dt] = 'C'
                day_origin[eid][dt] = 'auto'

    # 日薪出勤
    for d in attendance_data:
        dt = d['date']
        for e in d.get('normal', []):
            eid = make_employee_id(e)
            if eid and dt not in day_status.get(eid, {}):
                day_status[eid][dt] = 'P'
                day_origin[eid][dt] = 'auto'

    # 月薪默认出勤
    type_labels = {'piece_crush': '破碎计件','piece_underground':'井下计件','piece_driller':'钻工计件','day_rate':'日薪','monthly':'月薪','advance_only':'仅预支'}
    rows = []

    for emp in employees:
        eid = emp['id']
        status_row = {}
        origin_row = {}
        auto_row = {}

        for dt in all_dates:
            # 手动覆盖优先
            mkey = f'{eid}|{dt}'
            if mkey in manual:
                status_row[dt] = manual[mkey]  # 'P','A','L'
                origin_row[dt] = 'manual'
            else:
                auto_val = day_status.get(eid, {}).get(dt, '')
                # 顶层部门月薪人员：数据为空时默认全勤
                if not auto_val and emp.get('department') == 'ENPRIZON LINDI PROJECT' and (emp.get('override_type') == 'monthly' or emp.get('default_type') == 'monthly'):
                    auto_val = 'P'
                status_row[dt] = auto_val
                origin_row[dt] = 'auto' if auto_val else ''
            # 原始自动值（用于前端判断是否与手动不同）
            raw_auto = day_status.get(eid, {}).get(dt, '')
            # 顶层部门月薪人员：标记(P)显示灰色背景
            if not raw_auto and emp.get('department') == 'ENPRIZON LINDI PROJECT' and (emp.get('override_type') == 'monthly' or emp.get('default_type') == 'monthly'):
                raw_auto = '(P)'

            auto_row[dt] = raw_auto

        rows.append({
            'id': eid,
            'name': emp.get('name', ''),
            'type': type_labels.get(emp.get('override_type') or emp.get('default_type', ''), emp.get('default_type', '')),
            'days': status_row,
            'origin': origin_row,
            'auto': auto_row,
            'editable': True,  # 所有人都可手动标记 A/L
        })

    return jsonify({'dates': all_dates, 'rows': rows})


@app.route('/attendance/toggle', methods=['POST'])
@editor_required
def toggle_attendance():
    """手动标��某人某天的状态：P出勤 A旷工 L请假"""
    import json as _json
    data = request.get_json()
    eid = data.get('employee_id')
    date = data.get('date')
    status = data.get('status', 'P')  # 'P', 'A', 'L'

    from core.database import save_attendance_override
    save_attendance_override(app.config['DATA_FOLDER'], eid, date, status)
    _audit('attendance_toggle', eid, json.dumps({'date': date, 'status': status}))
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: 审计日志
# ═══════════════════════════════════════════════════════════

@app.route('/audit-log', methods=['GET'])
def get_audit_log():
    from core.database import get_audit_logs
    logs = get_audit_logs(app.config['DATA_FOLDER'])
    return jsonify(logs)


# ═══════════════════════════════════════════════════════════
#  API: 导出 Excel
# ═══════════════════════════════════════════════════════════

@app.route('/export', methods=['POST'])
@login_required
def export_salary():
    result = APP_STATE.get('salary_result')
    if not result:
        return jsonify({'ok': False, 'error': '请先计算薪资'})

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Salary Summary'

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill('solid', fgColor='185FA5')
    header_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'),
                          top=Side(style='thin'), bottom=Side(style='thin'))

    headers = ['Name', 'Type', 'Underground Piece(TZS)', 'Driller Piece(TZS)', 'Crush Piece(TZS)',
               'Day Rate(TZS)', 'Monthly(TZS)', 'Gross Total(TZS)',
               'Bonus(TZS)', 'Penalty(TZS)', 'Advance Deduction(TZS)', 'NSSF(TZS)', 'Net Salary(TZS)']
    for col, h in enumerate(headers, 1):
        cell = ws.cell(1, col, h)
        cell.font = header_font; cell.fill = header_fill
        cell.alignment = header_align; cell.border = thin_border

    type_map = {'piece_crush': 'Crush Piece', 'piece_underground': 'Underground Piece', 'piece_driller': 'Driller Piece',
                'day_rate': 'Day Rate', 'monthly': 'Monthly', 'both': 'Unspecified', 'advance_only': 'Advance Only'}
    total_fill = PatternFill('solid', fgColor='FFF3CD')

    for i, emp in enumerate(result['employees'], 2):
        gross = (emp.get('piece_underground', 0) or 0) + \
                (emp.get('piece_driller', 0) or 0) + \
                (emp.get('piece_crush', 0) or 0) + \
                (emp.get('day_rate', 0) or 0) + (emp.get('monthly', 0) or 0)
        bonus = int(emp.get('bonus', 0) or 0)
        penalty = int(emp.get('penalty', 0) or 0)
        nssf = emp.get('nssf', 0) or 0
        net = gross + bonus - (emp.get('advance', 0) or 0) - nssf - penalty
        vals = [
            emp['name'] or '', type_map.get(emp.get('salary_type', ''), emp.get('salary_type', '')),
            int(emp.get('piece_underground', 0) or 0), int(emp.get('piece_driller', 0) or 0),
            int(emp.get('piece_crush', 0) or 0),
            int(emp.get('day_rate', 0) or 0), int(emp.get('monthly', 0) or 0),
            int(gross), bonus, penalty, int(emp.get('advance', 0) or 0), int(nssf), int(net),
        ]
        for col, v in enumerate(vals, 1):
            cell = ws.cell(i, col, v); cell.border = thin_border
            cell.alignment = Alignment(horizontal='left' if col == 1 else 'right')
            if col > 1: cell.number_format = '#,##0'

    total_row = len(result['employees']) + 2
    ws.cell(total_row, 1, 'Total').font = Font(bold=True, size=11)
    ws.cell(total_row, 1).fill = total_fill; ws.cell(total_row, 1).border = thin_border

    # 井下(C), 钻工(D), 日薪(E), 月薪(F), 应发(G), 奖金(H), 罚款(I), 预支(J), NSSF(K) → SUM公式
    for ci in [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
        letter = chr(64 + ci)
        cell = ws.cell(total_row, ci, f'=SUM({letter}2:{letter}{total_row-1})')
        cell.font = Font(bold=True); cell.fill = total_fill; cell.border = thin_border
        cell.number_format = '#,##0'

    # 实发(12=L) = G+H-I-J-K + 司机津贴  (G=gross, H=bonus, I=penalty, J=advance, K=nssf)
    da = result.get('driver_allowance', 0)
    net_formula = f'=G{total_row}+H{total_row}-I{total_row}-J{total_row}-K{total_row}+{int(da)}' if da else f'=G{total_row}+H{total_row}-I{total_row}-J{total_row}-K{total_row}'
    ws.cell(total_row, 12, net_formula).font = Font(bold=True)
    ws.cell(total_row, 12).fill = total_fill; ws.cell(total_row, 12).border = thin_border
    ws.cell(total_row, 12).number_format = '#,##0'

    for i, w in enumerate([18, 12, 16, 16, 16, 16, 16, 16, 14, 14, 16, 16, 16], 1):
        ws.column_dimensions[chr(64+i)].width = w

    # Sheet 2: 产量
    ws2 = wb.create_sheet('Production Summary')
    for ci, h in enumerate(['Date', 'NICKEL(H)', 'NICKEL(L)', 'MAWE'], 1):
        c = ws2.cell(1, ci, h); c.font = header_font; c.fill = header_fill

    md = APP_STATE.get('main_data', {})
    for i, d in enumerate(md.get('shift_production', []), 2):
        dp = d.get('day_prod') or {}; np = d.get('night_prod') or {}
        ws2.cell(i, 1, d['date'])
        ws2.cell(i, 2, (dp.get('NICKEL（H）', 0) or 0) + (np.get('NICKEL（H）', 0) or 0))
        ws2.cell(i, 3, (dp.get('NICKEL（L）', 0) or 0) + (np.get('NICKEL（L）', 0) or 0))
        ws2.cell(i, 4, (dp.get('MAWE', 0) or 0) + (np.get('MAWE', 0) or 0))

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='ENPRIZON_LINDI_Salary.xlsx')

# ═══════════════════════════════════════════════════════════
#  API: 导出员工信息表
# ═══════════════════════════════════════════════════════════

@app.route('/export/employees', methods=['POST'])
@login_required
def export_employees():
    """导出员工信息表（薪资类型、日薪基数、月薪基数、预支）"""
    employees = APP_STATE.get('employees', [])
    if not employees:
        return jsonify({'ok': False, 'error': '无员工数据'})

    from core.exceptions import load_overrides
    overrides = load_overrides(app.config['DATA_FOLDER'])

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Employee Info'

    hf = Font(bold=True, color='FFFFFF', size=11)
    hfill = PatternFill('solid', fgColor='185FA5')
    ha = Alignment(horizontal='center', vertical='center')
    tb = Border(left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin'))

    headers = ['Name', 'Department', 'Type', 'Day Rate(TZS)', 'Monthly Base(TZS)', 'Advance This Month(TZS)', 'Notes']
    for ci, h in enumerate(headers, 1):
        c = ws.cell(1, ci, h); c.font = hf; c.fill = hfill; c.alignment = ha; c.border = tb

    type_map = {'piece_underground':'Underground Piece','piece_driller':'Driller Piece',
                'day_rate':'Day Rate','monthly':'Monthly','both':'Unspecified','advance_only':'Advance Only'}
    total_fill = PatternFill('solid', fgColor='FFF3CD')

    for i, emp in enumerate(employees, 2):
        eid = emp['id']
        note = emp.get('_note', '')
        if not note and eid in overrides:
            note = '; '.join(f"{o.get('start_date','')}~{o.get('end_date','')} {o.get('salary_type','')}" for o in overrides[eid])

        vals = [
            emp.get('name', ''),
            emp.get('department', ''),
            type_map.get(emp.get('default_type',''), emp.get('default_type','')),
            int(emp.get('day_rate', 0) or 0),
            int(emp.get('monthly_salary', 0) or 0),
            int(emp.get('advance_total', 0) or 0),
            note,
        ]
        for ci, v in enumerate(vals, 1):
            c = ws.cell(i, ci, v); c.border = tb
            c.alignment = Alignment(horizontal='left' if ci in (1,2,3,7) else 'right')
            if 4 <= ci <= 6: c.number_format = '#,##0'

    for i, w in enumerate([16, 22, 12, 16, 16, 16, 30], 1):
        ws.column_dimensions[chr(64+i)].width = w

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='ENPRIZON_LINDI_Employees.xlsx')

# ═══════════════════════════════════════════════════════════
#  API: 导出出勤表
# ═══════════════════════════════════════════════════════════

@app.route('/export/attendance', methods=['GET'])
@login_required
def export_attendance():
    """导出出勤网格为 Excel，含状态颜色标记"""
    from collections import defaultdict
    from core.namematch import make_employee_id, canonical

    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])
    attendance_data = md.get('attendance', [])
    employees = APP_STATE.get('employees', [])

    # ── 收集所有日期 ──
    all_dates = sorted(set(
        list(set(d['date'] for d in shift_prod)) +
        list(set(d.get('date', '') for d in attendance_data)) +
        list(md.get('dates', []))
    ))

    # ── 自动出勤状态（复用 GET /attendance 逻辑） ──
    day_status = defaultdict(dict)
    for d in shift_prod:
        dt = d['date']
        for e in d.get('day_emps', []):
            eid = make_employee_id(e)
            if eid: day_status[eid][dt] = 'D'
        for e in d.get('night_emps', []):
            eid = make_employee_id(e)
            if eid:
                existing = day_status.get(eid, {}).get(dt, '')
                day_status[eid][dt] = 'B' if existing == 'D' else 'N'
    for d in driller_prod:
        dt = d['date']
        cap_id = make_employee_id(d['captain'])
        if cap_id and dt not in day_status.get(cap_id, {}):
            day_status[cap_id][dt] = 'P'
        for m in d.get('members', []):
            mid = make_employee_id(m)
            if mid and dt not in day_status.get(mid, {}):
                day_status[mid][dt] = 'P'
    for d in attendance_data:
        dt = d['date']
        for e in d.get('normal', []):
            eid = make_employee_id(e)
            if eid and dt not in day_status.get(eid, {}):
                day_status[eid][dt] = 'P'

    # ── 加载手动覆盖 ──
    from core.database import load_attendance_overrides
    manual = load_attendance_overrides(app.config['DATA_FOLDER'])

    # ── 构建行数据 ──
    type_labels = {'piece_crush': 'Crush Piece', 'piece_underground': 'Underground Piece', 'piece_driller': 'Driller Piece',
                   'day_rate': 'Day Rate', 'monthly': 'Monthly', 'advance_only': 'Advance Only'}
    rows = []
    for emp in employees:
        eid = emp.get('id', '')
        emp_type = emp.get('override_type') or emp.get('default_type', '')
        is_monthly = (emp_type == 'monthly')

        row_days = {}
        for dt in all_dates:
            kid = f"{eid}|{dt}"
            if kid in manual:
                row_days[dt] = manual[kid]  # 手动覆盖优先
            elif eid in day_status and dt in day_status[eid]:
                row_days[dt] = day_status[eid][dt]
            elif is_monthly:
                row_days[dt] = '(P)'  # 月薪默认出勤
            else:
                row_days[dt] = ''

        rows.append({
            'name': emp.get('name', ''),
            'type': type_labels.get(emp_type, emp_type),
            'days': row_days,
        })

    if not rows:
        return jsonify({'ok': False, 'error': '无出勤数据'})

    # ── 生成 Excel ──
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Attendance'

    hfont = Font(bold=True, color='FFFFFF', size=11)
    hfill = PatternFill('solid', fgColor='185FA5')
    ha = Alignment(horizontal='center', vertical='center', wrap_text=True)
    tb = Border(left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin'))

    # 状态 → 颜色（与 UI 保持一致）
    fill_map = {
        'D':  PatternFill('solid', fgColor='3B82F6'),   # Day Shift
        'N':  PatternFill('solid', fgColor='06B6D4'),   # Night Shift
        'B':  PatternFill('solid', fgColor='8B5CF6'),   # Both (Day+Night)
        'P':  PatternFill('solid', fgColor='10B981'),   # Present
        'A':  PatternFill('solid', fgColor='EF4444'),   # Absent
        'L':  PatternFill('solid', fgColor='F59E0B'),   # Leave
        'R':  PatternFill('solid', fgColor='14B8A6'),   # Driller
        'C':  PatternFill('solid', fgColor='F97316'),   # Crush
        '(P)': PatternFill('solid', fgColor='9CA3AF'),  # Monthly Default
    }
    text_color = Font(color='FFFFFF', bold=True)

    # ── Headers ──
    headers = ['Name', 'Type'] + all_dates
    for ci, h in enumerate(headers, 1):
        c = ws.cell(1, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb

    # ── 数据行 ──
    for ri, row in enumerate(rows, 2):
        ws.cell(ri, 1, row['name']).border = tb
        c_type = ws.cell(ri, 2, row['type']); c_type.border = tb
        c_type.alignment = Alignment(horizontal='center')

        for di, dt in enumerate(all_dates):
            status = row['days'].get(dt, '')
            c = ws.cell(ri, 3 + di, status)
            c.border = tb
            c.alignment = Alignment(horizontal='center', vertical='center')
            # 状态着色
            sf = fill_map.get(status)
            if sf:
                c.fill = sf
                c.font = text_color
            elif status == '':
                c.fill = PatternFill('solid', fgColor='F3F4F6')

    # ── 列宽 ──
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 12
    ws.freeze_panes = 'C2'

    # 日期列宽度
    for di in range(len(all_dates)):
        col_letter = chr(67 + di) if di < 24 else ''
        if col_letter:
            ws.column_dimensions[col_letter].width = 7

    # ── 添加图例 sheet ──
    ws2 = wb.create_sheet('Legend')
    legend = [
        ('D', 'Day Shift', '3B82F6'),
        ('N', 'Night Shift', '06B6D4'),
        ('B', 'Both (Day+Night)', '8B5CF6'),
        ('P', 'Present', '10B981'),
        ('A', 'Absent', 'EF4444'),
        ('L', 'Leave', 'F59E0B'),
        ('R', 'Driller', '14B8A6'),
        ('C', 'Crush', 'F97316'),
        ('(P)', 'Monthly Default', '9CA3AF'),
    ]
    ws2.cell(1, 1, 'Code').font = Font(bold=True)
    ws2.cell(1, 2, 'Meaning').font = Font(bold=True)
    ws2.column_dimensions['A'].width = 10
    ws2.column_dimensions['B'].width = 26
    for i, (code, meaning, color) in enumerate(legend, 2):
        c1 = ws2.cell(i, 1, code)
        c1.fill = PatternFill('solid', fgColor=color)
        c1.font = Font(color='FFFFFF', bold=True)
        c1.alignment = Alignment(horizontal='center')
        ws2.cell(i, 2, meaning)

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    month = APP_STATE.get('month', '')
    fname = f'ENPRIZON_LINDI_Attendance_{month}.xlsx' if month else 'ENPRIZON_LINDI_Attendance.xlsx'
    return send_file(buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=fname)

# ═══════════════════════════════════════════════════════════
#  API: 统一导出（所有报表合并为一个文件）
# ═══════════════════════════════════════════════════════════

@app.route('/export/all', methods=['POST'])
@login_required
def export_all():
    """一次性导出：员工信息 → 薪资总表 → 出勤表 → 日工资分布 → 产量汇总"""
    try:
        return _do_export_all()
    except Exception as e:
        import traceback, sys
        print(f'[EXPORT ERROR] {e}', file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': str(e), 'ok': False}), 500


def _do_export_all():
    """导出逻辑体，方便包装错误处理"""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from datetime import datetime

    # ── 公共样式 ──
    hfont = Font(bold=True, color='FFFFFF', size=11)
    hfill = PatternFill('solid', fgColor='185FA5')
    ha = Alignment(horizontal='center', vertical='center', wrap_text=True)
    tb = Border(left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin'))
    total_fill = PatternFill('solid', fgColor='FFF3CD')
    type_map = {'piece_underground':'Underground Piece','piece_driller':'Driller Piece',
                'day_rate':'Day Rate','monthly':'Monthly','both':'Unspecified','advance_only':'Advance Only'}

    wb = openpyxl.Workbook()
    # 删除默认空 sheet
    wb.remove(wb.active)

    # ── 辅助：解析日期字符串为 datetime ──
    def parse_dt(s):
        try: return datetime.strptime(str(s)[:10], '%Y-%m-%d')
        except: return s

    # ═══════════════════════════════════════════════════════
    #  Sheet 1: 员工信息
    # ═══════════════════════════════════════════════════════
    employees = APP_STATE.get('employees', [])
    if employees:
        from core.exceptions import load_overrides
        overrides = load_overrides(app.config['DATA_FOLDER'])
        ws1 = wb.create_sheet('Employee Info')
        headers1 = ['Name', 'Department', 'Type', 'Day Rate(TZS)', 'Monthly Base(TZS)', 'Advance(TZS)', 'Notes']
        for ci, h in enumerate(headers1, 1):
            c = ws1.cell(1, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
        for i, emp in enumerate(employees, 2):
            eid = emp['id']
            note = emp.get('_note', '')
            if not note and eid in overrides:
                note = '; '.join(f"{o.get('start_date','')}~{o.get('end_date','')} {o.get('salary_type','')}" for o in overrides[eid])
            vals = [
                emp.get('name',''), emp.get('department',''),
                type_map.get(emp.get('default_type',''), emp.get('default_type','')),
                int(emp.get('day_rate',0) or 0), int(emp.get('monthly_salary',0) or 0),
                int(emp.get('advance_total',0) or 0), note,
            ]
            for ci, v in enumerate(vals, 1):
                c = ws1.cell(i, ci, v); c.border = tb
                c.alignment = Alignment(horizontal='left' if ci in (1,2,3,7) else 'right')
                if 4 <= ci <= 6: c.number_format = '#,##0'
        for i, w in enumerate([18, 22, 12, 16, 16, 16, 30], 1):
            ws1.column_dimensions[chr(64+i)].width = w
        ws1.freeze_panes = 'A2'

    # ═══════════════════════════════════════════════════════
    #  Sheet 2: 薪资总表
    # ═══════════════════════════════════════════════════════
    result = APP_STATE.get('salary_result')
    if result:
        ws2 = wb.create_sheet('Salary Summary')
        headers2 = ['Name', 'Type', 'Underground Piece(TZS)', 'Driller Piece(TZS)', 'Crush Piece(TZS)',
                    'Day Rate(TZS)', 'Monthly(TZS)', 'Gross Total(TZS)',
                    'Bonus(TZS)', 'Penalty(TZS)', 'Advance Deduction(TZS)', 'NSSF(TZS)', 'Net Salary(TZS)']
        for ci, h in enumerate(headers2, 1):
            c = ws2.cell(1, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb

        _type_map2 = {'piece_crush':'Crush Piece','piece_underground':'Underground Piece','piece_driller':'Driller Piece',
                      'day_rate':'Day Rate','monthly':'Monthly','both':'Unspecified','advance_only':'Advance Only'}
        for i, emp in enumerate(result['employees'], 2):
            gross = (emp.get('piece_underground',0) or 0) + (emp.get('piece_driller',0) or 0) + \
                    (emp.get('piece_crush',0) or 0) + \
                    (emp.get('day_rate',0) or 0) + (emp.get('monthly',0) or 0)
            bonus = int(emp.get('bonus', 0) or 0)
            penalty = int(emp.get('penalty', 0) or 0)
            nssf = emp.get('nssf',0) or 0
            net = gross + bonus - (emp.get('advance',0) or 0) - nssf - penalty
            vals = [
                emp.get('name','') or '', _type_map2.get(emp.get('salary_type',''), emp.get('salary_type','')),
                int(emp.get('piece_underground',0) or 0), int(emp.get('piece_driller',0) or 0),
                int(emp.get('piece_crush',0) or 0),
                int(emp.get('day_rate',0) or 0), int(emp.get('monthly',0) or 0),
                int(gross), bonus, penalty, int(emp.get('advance',0) or 0), int(nssf), int(net),
            ]
            for ci, v in enumerate(vals, 1):
                c = ws2.cell(i, ci, v); c.border = tb
                c.alignment = Alignment(horizontal='left' if ci == 1 else 'right')
                if ci > 1: c.number_format = '#,##0'

        tr = len(result['employees']) + 2
        ws2.cell(tr, 1, 'Total').font = Font(bold=True, size=11)
        ws2.cell(tr, 1).fill = total_fill; ws2.cell(tr, 1).border = tb
        # 井下(C), 钻工(D), 日薪(E), 月薪(F), 应发(G), 奖金(H), 罚款(I), 预支(J), NSSF(K) → SUM
        for ci in [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
            lt = chr(64 + ci)
            c = ws2.cell(tr, ci, f'=SUM({lt}2:{lt}{tr-1})')
            c.font = Font(bold=True); c.fill = total_fill; c.border = tb
            c.number_format = '#,##0'
        # 实发(L12) = G+H-I-J-K + 司机津贴
        da_val = result.get('driver_allowance', 0)
        net_f = f'=G{tr}+H{tr}-I{tr}-J{tr}-K{tr}+{int(da_val)}' if da_val else f'=G{tr}+H{tr}-I{tr}-J{tr}-K{tr}'
        ws2.cell(tr, 12, net_f).font = Font(bold=True)
        ws2.cell(tr, 12).fill = total_fill; ws2.cell(tr, 12).border = tb
        ws2.cell(tr, 12).number_format = '#,##0'
        for i, w in enumerate([18, 12, 16, 16, 16, 16, 16, 16, 14, 14, 16, 16, 16], 1):
            ws2.column_dimensions[chr(64+i)].width = w
        ws2.freeze_panes = 'A2'

    # ═══════════════════════════════════════════════════════
    #  Sheet 3: 出勤表
    # ═══════════════════════════════════════════════════════
    md = APP_STATE.get('main_data', {})
    if md and employees:
        from collections import defaultdict
        from core.namematch import make_employee_id
        shift_prod = md.get('shift_production', [])
        driller_prod = md.get('driller_production', [])
        attendance_data = md.get('attendance', [])
        all_dates = sorted(set(
            list(set(d['date'] for d in shift_prod)) +
            list(set(d.get('date', '') for d in attendance_data)) +
            list(md.get('dates', []))
        ))

        # 收集自动状态
        day_status = defaultdict(dict)
        for d in shift_prod:
            dt = d['date']
            for e in d.get('day_emps', []):
                eid = make_employee_id(e)
                if eid: day_status[eid][dt] = 'D'
            for e in d.get('night_emps', []):
                eid = make_employee_id(e)
                if eid:
                    existing = day_status.get(eid, {}).get(dt, '')
                    day_status[eid][dt] = 'B' if existing == 'D' else 'N'
        for d in driller_prod:
            dt = d['date']
            cap_id = make_employee_id(d['captain'])
            if cap_id and dt not in day_status.get(cap_id, {}):
                day_status[cap_id][dt] = 'P'
            for m in d.get('members', []):
                mid = make_employee_id(m)
                if mid and dt not in day_status.get(mid, {}):
                    day_status[mid][dt] = 'P'
        for d in attendance_data:
            dt = d['date']
            for e in d.get('normal', []):
                eid = make_employee_id(e)
                if eid and dt not in day_status.get(eid, {}):
                    day_status[eid][dt] = 'P'

        from core.database import load_attendance_overrides
        manual = load_attendance_overrides(app.config['DATA_FOLDER'])

        # 状态 → 颜色
        fill_map = {
            'D': PatternFill('solid', fgColor='3B82F6'),
            'N': PatternFill('solid', fgColor='06B6D4'),
            'B': PatternFill('solid', fgColor='8B5CF6'),
            'P': PatternFill('solid', fgColor='10B981'),
            'A': PatternFill('solid', fgColor='EF4444'),
            'L': PatternFill('solid', fgColor='F59E0B'),
            'R': PatternFill('solid', fgColor='14B8A6'),
            'C': PatternFill('solid', fgColor='F97316'),
            '(P)': PatternFill('solid', fgColor='9CA3AF'),
        }
        white_bold = Font(color='FFFFFF', bold=True)
        grey_fill = PatternFill('solid', fgColor='F3F4F6')
        date_fmt = 'yyyy-mm-dd'

        att_rows = []
        for emp in employees:
            eid = emp.get('id', '')
            emp_type = emp.get('override_type') or emp.get('default_type', '')
            is_monthly = (emp_type == 'monthly')
            row_days = {}
            for dt in all_dates:
                kid = f"{eid}|{dt}"
                if kid in manual:
                    row_days[dt] = manual[kid]
                elif eid in day_status and dt in day_status[eid]:
                    row_days[dt] = day_status[eid][dt]
                elif is_monthly:
                    row_days[dt] = '(P)'
                else:
                    row_days[dt] = ''
            att_rows.append({
                'name': emp.get('name', ''),
                'type': type_map.get(emp_type, emp_type),
                'days': row_days,
            })

        if att_rows:
            ws3 = wb.create_sheet('Attendance')
            ws3.cell(1, 1, 'Name').font = hfont; ws3.cell(1, 1).fill = hfill
            ws3.cell(1, 1).alignment = ha; ws3.cell(1, 1).border = tb
            ws3.cell(1, 2, 'Type').font = hfont; ws3.cell(1, 2).fill = hfill
            ws3.cell(1, 2).alignment = ha; ws3.cell(1, 2).border = tb
            for di, dt in enumerate(all_dates):
                c = ws3.cell(1, 3 + di, parse_dt(dt))
                c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
                c.number_format = date_fmt

            for ri, row in enumerate(att_rows, 2):
                ws3.cell(ri, 1, row['name']).border = tb
                c_type = ws3.cell(ri, 2, row['type']); c_type.border = tb
                c_type.alignment = Alignment(horizontal='center')
                for di, dt in enumerate(all_dates):
                    status = row['days'].get(dt, '')
                    c = ws3.cell(ri, 3 + di, status)
                    c.border = tb
                    c.alignment = Alignment(horizontal='center', vertical='center')
                    sf = fill_map.get(status)
                    if sf:
                        c.fill = sf; c.font = white_bold
                    elif status == '':
                        c.fill = grey_fill

            ws3.column_dimensions['A'].width = 22
            ws3.column_dimensions['B'].width = 12
            ws3.freeze_panes = 'C2'

    # ═══════════════════════════════════════════════════════
    #  Sheet 4: 日工资分布
    # ═══════════════════════════════════════════════════════
    if md and employees:
        from core.calculator import compute_daily_breakdown
        from core.exceptions import load_overrides as _ld_ov, load_daily_exclusions
        dw_result = compute_daily_breakdown(
            main_data=md, employees=employees,
            overrides=_ld_ov(app.config['DATA_FOLDER']),
            exclusions=load_daily_exclusions(app.config['DATA_FOLDER']),
            pricing=APP_STATE.get('config', {}),
            data_folder=app.config['DATA_FOLDER'],
        )
        # 合并 att_override_dates
        import sqlite3 as _sq, os as _os
        att_ov_map = {}
        db_path = _os.path.join(app.config['DATA_FOLDER'], 'kilwa.db')
        if _os.path.exists(db_path):
            conn = _sq.connect(db_path)
            try:
                for r in conn.execute("SELECT employee_id, date FROM attendance_overrides").fetchall():
                    att_ov_map[f"{r[0]}|{r[1]}"] = True
            except: pass
            conn.close()
        for eid, e in dw_result.items():
            e['att_override_dates'] = [dt for dt in e.get('daily', {}) if f"{eid}|{dt}" in att_ov_map]

        # 收集所有日期
        dw_all_dates = set()
        for e in dw_result.values():
            dw_all_dates.update(e.get('daily', {}).keys())
        dw_dates = sorted(dw_all_dates)

        if dw_dates and dw_result:
            ws4 = wb.create_sheet('Daily Wages')
            ws4.cell(1, 1, 'Name').font = hfont; ws4.cell(1, 1).fill = hfill
            ws4.cell(1, 1).alignment = ha; ws4.cell(1, 1).border = tb
            ws4.cell(1, 2, 'Type').font = hfont; ws4.cell(1, 2).fill = hfill
            ws4.cell(1, 2).alignment = ha; ws4.cell(1, 2).border = tb
            for di, dt in enumerate(dw_dates):
                c = ws4.cell(1, 3 + di, parse_dt(dt))
                c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
                c.number_format = date_fmt
            # 合计列
            total_col = 3 + len(dw_dates)
            c = ws4.cell(1, total_col, 'Total(TZS)')
            c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb

            override_fill = PatternFill('solid', fgColor='FFF9C4')  # 黄色标记
            grey_font = Font(color='808080')
            ri = 2
            for emp in employees:
                eid = emp['id']
                e = dw_result.get(eid)
                if not e: continue
                emp_type2 = emp.get('override_type') or emp.get('default_type', '')
                is_monthly2 = (emp_type2 == 'monthly')

                ws4.cell(ri, 1, e['name']).border = tb
                ct = ws4.cell(ri, 2, type_map.get(emp_type2, emp_type2))
                ct.border = tb; ct.alignment = Alignment(horizontal='center')

                for di, dt in enumerate(dw_dates):
                    amt = e.get('daily', {}).get(dt, 0)
                    shift = e.get('daily_shifts', {}).get(dt, '')
                    label = f"{int(amt)} {shift}" if shift and amt > 0 else (int(amt) if amt > 0 else '')
                    c = ws4.cell(ri, 3 + di, label if label else None)
                    c.border = tb
                    c.alignment = Alignment(horizontal='right')
                    if amt > 0: c.number_format = '#,##0'
                    # 覆盖日期黄色标记
                    if dt in e.get('override_dates', []) or dt in e.get('att_override_dates', []):
                        c.fill = override_fill
                    # 月薪灰色
                    if is_monthly2 and dt in e.get('daily', {}) and dt not in e.get('override_dates', []):
                        if not e.get('att_override_dates') or dt not in e.get('att_override_dates', []):
                            c.font = grey_font

                # 合计 = SUM 公式
                col_end = 3 + len(dw_dates) - 1
                col_end_letter = chr(64 + col_end) if col_end <= 26 else ''
                if col_end_letter:
                    c_total = ws4.cell(ri, total_col,
                        f'=SUM(C{ri}:{col_end_letter}{ri})' if col_end >= 3 else None)
                else:
                    c_total = ws4.cell(ri, total_col, e.get('total', 0))
                c_total.border = tb; c_total.alignment = Alignment(horizontal='right')
                c_total.number_format = '#,##0'
                c_total.font = Font(bold=True)
                ri += 1

            # 合计行
            ws4.cell(ri, 1, 'Total').font = Font(bold=True)
            ws4.cell(ri, 1).fill = total_fill; ws4.cell(ri, 1).border = tb
            ws4.cell(ri, 2, '').fill = total_fill; ws4.cell(ri, 2).border = tb
            for di in range(len(dw_dates)):
                col = 3 + di
                c = ws4.cell(ri, col, f'=SUM({chr(64+col)}2:{chr(64+col)}{ri-1})' if col <= 26 else 0)
                c.font = Font(bold=True); c.fill = total_fill; c.border = tb
                c.number_format = '#,##0'
            c = ws4.cell(ri, total_col, f'=SUM({chr(64+total_col)}2:{chr(64+total_col)}{ri-1})' if total_col <= 26 else 0)
            c.font = Font(bold=True); c.fill = total_fill; c.border = tb
            c.number_format = '#,##0'

            ws4.column_dimensions['A'].width = 22
            ws4.column_dimensions['B'].width = 12
            if total_col <= 26:
                ws4.column_dimensions[chr(64+total_col)].width = 14
            ws4.freeze_panes = 'C2'

    # ═══════════════════════════════════════════════════════
    #  Sheet 5: 产量汇总
    # ═══════════════════════════════════════════════════════
    if md and md.get('shift_production'):
        ws5 = wb.create_sheet('Production Summary')
        for ci, h in enumerate(['Date', 'NICKEL(H)', 'NICKEL(L)', 'MAWE'], 1):
            c = ws5.cell(1, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
        for i, d in enumerate(md.get('shift_production', []), 2):
            dp = d.get('day_prod') or {}; np = d.get('night_prod') or {}
            c_dt = ws5.cell(i, 1, parse_dt(d['date']))
            c_dt.number_format = date_fmt; c_dt.border = tb
            ws5.cell(i, 2, (dp.get('NICKEL（H）', 0) or 0) + (np.get('NICKEL（H）', 0) or 0)).border = tb
            ws5.cell(i, 3, (dp.get('NICKEL（L）', 0) or 0) + (np.get('NICKEL（L）', 0) or 0)).border = tb
            ws5.cell(i, 4, (dp.get('MAWE', 0) or 0) + (np.get('MAWE', 0) or 0)).border = tb
        for i, w in enumerate([14, 14, 14, 10], 1):
            ws5.column_dimensions[chr(64+i)].width = w
        ws5.freeze_panes = 'A2'

    # ═══════════════════════════════════════════════════════
    #  Sheet 6: 钻工计件双路径核对
    # ═══════════════════════════════════════════════════════
    if result and md and md.get('driller_production'):
        try:
            from core.verification import verify_salary
            from core.calculator import PRICES_UNDERGROUND, PRICES_DRILLER
            ver = verify_salary(md, result, PRICES_UNDERGROUND, PRICES_DRILLER)
            d_info = ver.get('driller', {})
            d_p1 = ver.get('path1_details', {}).get('driller', [])
            d_dc = ver.get('daily_comparison', {}).get('driller', [])

            if d_p1 or d_dc:
                ws7 = wb.create_sheet('Driller Verification')
                diff_fill = PatternFill('solid', fgColor='FEF2F2')
                diff_font = Font(color='DC2626', bold=True)
                round_font = Font(color='9CA3AF', italic=True)
                section_font = Font(bold=True, size=12, color='185FA5')
                r = 1

                # ── 路径一：基准计算（产量 × 单价）──
                ws7.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
                c = ws7.cell(r, 1, 'Path 1: Production x Price')
                c.font = section_font; r += 1
                for ci, h in enumerate(['Date', 'Captain', 'NH', 'NL', 'MW', 'Amount(TZS)'], 1):
                    c = ws7.cell(r, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
                r += 1
                for d in d_p1:
                    ws7.cell(r, 1, d['date']).border = tb
                    ws7.cell(r, 2, d.get('captain', '')).border = tb
                    ws7.cell(r, 3, d.get('nh', 0)).border = tb
                    ws7.cell(r, 4, d.get('nl', 0)).border = tb
                    ws7.cell(r, 5, d.get('mw', 0)).border = tb
                    c_amt = ws7.cell(r, 6, d.get('total', 0))
                    c_amt.border = tb; c_amt.number_format = '#,##0'
                    c_amt.font = Font(bold=True)
                    r += 1

                # ── 路径一合计行 ──
                c = ws7.cell(r, 1, 'Path 1 Total')
                c.font = Font(bold=True); c.fill = total_fill; c.border = tb
                for ci in range(2, 6): ws7.cell(r, ci, '').fill = total_fill; ws7.cell(r, ci).border = tb
                c_total = ws7.cell(r, 6, f'=SUM(F{r-len(d_p1)}:F{r-1})')
                c_total.font = Font(bold=True); c_total.fill = total_fill; c_total.border = tb
                c_total.number_format = '#,##0'
                r += 2

                # ── 逐日对比（路径一 vs 路径二）──
                ws7.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
                c = ws7.cell(r, 1, 'Driller Daily Comparison: Path 1 vs Path 2')
                c.font = section_font; r += 1
                for ci, h in enumerate(['Date', 'Path 1(TZS)', 'Path 2(TZS)', 'Diff(TZS)', 'Note'], 1):
                    c = ws7.cell(r, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
                r += 1
                for dc_row in d_dc:
                    ws7.cell(r, 1, dc_row['date']).border = tb
                    ws7.cell(r, 2, dc_row['path1']).border = tb
                    ws7.cell(r, 3, dc_row['path2']).border = tb
                    c_diff = ws7.cell(r, 4, dc_row['diff'])
                    c_diff.border = tb; c_diff.number_format = '#,##0'
                    note = ''
                    if dc_row['diff'] != 0:
                        if dc_row.get('is_rounding'):
                            note = 'Rounding'
                            c_diff.font = round_font
                        else:
                            c_diff.font = diff_font
                            ws7.cell(r, 1).fill = diff_fill
                            ws7.cell(r, 2).fill = diff_fill
                            ws7.cell(r, 3).fill = diff_fill
                            ws7.cell(r, 4).fill = diff_fill
                    ws7.cell(r, 5, note).border = tb
                    if note: ws7.cell(r, 5).font = round_font
                    r += 1

                # ── 汇总行 ──
                c = ws7.cell(r, 1, 'Summary')
                c.font = Font(bold=True); c.fill = total_fill; c.border = tb
                for ci in [2, 3, 4]:
                    col_l = chr(64+ci)
                    c = ws7.cell(r, ci, f'=SUM({col_l}{r-len(d_dc)}:{col_l}{r-1})')
                    c.font = Font(bold=True); c.fill = total_fill; c.border = tb
                    c.number_format = '#,##0'
                ws7.cell(r, 5, f'Path1={d_info.get("path1",0):,}  Path2={d_info.get("path2",0):,}').fill = total_fill
                ws7.cell(r, 5).border = tb; ws7.cell(r, 5).font = Font(size=10)

                for i, w in enumerate([14, 18, 8, 8, 8, 14, 6], 1):
                    ws7.column_dimensions[chr(64+i)].width = w
                ws7.freeze_panes = 'A2'
        except Exception as e:
            import traceback
            traceback.print_exc()
            pass  # 核对失败不影响导出

    # ═══════════════════════════════════════════════════════
    #  Sheet 7: 钻工计件出勤明细
    # ═══════════════════════════════════════════════════════
    if md and md.get('driller_production'):
        # ── 队长名规范化映射（与 core/namematch.py 一致）──
        _captain_canonical = {
            'SHEDRACK': 'SHEDRACK PINIEL LAIZER',
            'SHEDRACKPINIELLAIZER': 'SHEDRACK PINIEL LAIZER',
            'JOHN': 'JOHN BOAY BURA',
            'JOHNBOAYBURA': 'JOHN BOAY BURA',
            'BARAKALAIZER': 'BARAKA LAIZER',
            'JOSEPH': 'JOSEPH DONALD',
            'JOSEPHDONALD': 'JOSEPH DONALD',
        }
        def _norm_captain(name):
            key = re.sub(r'\s+', '', re.sub(r'\s*\([^)]*\)\s*', '', str(name))).upper()
            return _captain_canonical.get(key, str(name))

        from collections import defaultdict
        captain_groups = defaultdict(list)
        for d in md['driller_production']:
            cap = _norm_captain(d['captain'])
            captain_groups[cap].append(d)

        captain_order = ['SHEDRACK PINIEL LAIZER', 'JOHN BOAY BURA', 'BARAKA LAIZER', 'JOSEPH DONALD']

        if any(captain_groups.get(c) for c in captain_order):
            ws7 = wb.create_sheet('Driller Team Details')
            section_font = Font(bold=True, size=12, color='185FA5')
            subtotal_fill = PatternFill('solid', fgColor='E8F4FD')

            r = 1
            grand_nh = grand_nl = grand_mw = grand_amt = 0

            for cap_name in captain_order:
                records = captain_groups.get(cap_name, [])
                if not records:
                    continue
                records.sort(key=lambda d: d['date'])

                # ── 队长标题行 ──
                ws7.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
                c = ws7.cell(r, 1, f'Captain: {cap_name} ({len(records)} days)')
                c.font = section_font
                r += 1

                # ── 表头 ──
                sub_headers = ['Date', 'NH', 'NL', 'MW', 'Amount(TZS)', 'Headcount', 'Personnel']
                for ci, h in enumerate(sub_headers, 1):
                    c = ws7.cell(r, ci, h)
                    c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
                r += 1

                # ── 数据行 ──
                cap_nh = cap_nl = cap_mw = cap_amt = 0
                for rec in records:
                    nh = rec.get('nh', 0) or 0
                    nl = rec.get('nl', 0) or 0
                    mw = rec.get('mw', 0) or 0
                    amt = nh * 5000 + nl * 4000 + mw * 3000
                    # 出勤人员列表（队长 + 成员）
                    member_list = [_norm_captain(rec['captain'])] + (rec.get('members', []) or [])
                    cap_nh += nh; cap_nl += nl; cap_mw += mw; cap_amt += amt

                    ws7.cell(r, 1, parse_dt(rec['date'])).border = tb
                    ws7.cell(r, 2, nh).border = tb
                    ws7.cell(r, 3, nl).border = tb
                    ws7.cell(r, 4, mw).border = tb
                    c = ws7.cell(r, 5, amt); c.border = tb; c.number_format = '#,##0'
                    ws7.cell(r, 6, len(member_list)).border = tb
                    ws7.cell(r, 7, ', '.join(member_list)).border = tb
                    r += 1

                # ── 小计行 ──
                ws7.cell(r, 1, f'{cap_name.split()[0]} Subtotal').font = Font(bold=True)
                for ci in [1, 2, 3, 4, 5, 6, 7]:
                    ws7.cell(r, ci).fill = subtotal_fill; ws7.cell(r, ci).border = tb
                ws7.cell(r, 2, cap_nh).number_format = '#,##0'
                ws7.cell(r, 3, cap_nl).number_format = '#,##0'
                ws7.cell(r, 4, cap_mw).number_format = '#,##0'
                ws7.cell(r, 5, cap_amt).number_format = '#,##0'
                grand_nh += cap_nh; grand_nl += cap_nl; grand_mw += cap_mw; grand_amt += cap_amt
                r += 2  # 空行分隔

            # ── 总计行 ──
            ws7.cell(r, 1, 'Grand Total').font = Font(bold=True, size=11)
            for ci in [1, 2, 3, 4, 5, 6, 7]:
                ws7.cell(r, ci).fill = total_fill; ws7.cell(r, ci).border = tb
            ws7.cell(r, 2, grand_nh).number_format = '#,##0'
            ws7.cell(r, 3, grand_nl).number_format = '#,##0'
            ws7.cell(r, 4, grand_mw).number_format = '#,##0'
            ws7.cell(r, 5, grand_amt).number_format = '#,##0'

            # ── 列宽 ──
            ws7.column_dimensions['A'].width = 14
            ws7.column_dimensions['B'].width = 10
            ws7.column_dimensions['C'].width = 10
            ws7.column_dimensions['D'].width = 10
            ws7.column_dimensions['E'].width = 18
            ws7.column_dimensions['F'].width = 10
            ws7.column_dimensions['G'].width = 60
            ws7.freeze_panes = 'A2'

    # ── 文件名 ──
    month = APP_STATE.get('month', '')
    fname = f'ENPRIZON_LINDI_{month}.xlsx' if month else 'ENPRIZON_LINDI_Report.xlsx'
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=fname)


# ═══════════════════════════════════════════════════════════
#  自动加载源文件
# ═══════════════════════════════════════════════════════════

def find_free_port(start=8080, max_try=100):
    for port in range(start, start + max_try):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    return start

def _ensure_viewer_account():
    """确保默认账号存在 + KEJU 为 super_admin"""
    from core.database import get_conn, _hash_password
    conn = get_conn(app.config['DATA_FOLDER'])

    # user 账号（viewer 角色）
    existing = conn.execute("SELECT username FROM admin_users WHERE username='user'").fetchone()
    if not existing:
        pwd_hash = _hash_password('qweasd')
        conn.execute(
            "INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)",
            ('user', pwd_hash, 'viewer')
        )
        conn.commit()
        print('  ✓ 已创建 viewer 账号 (user / qweasd)')
    else:
        # 修正已存在的 user 角色为 viewer
        conn.execute("UPDATE admin_users SET role='viewer' WHERE username='user' AND role!='viewer'")
        conn.commit()

    # KEJU 升级为 super_admin
    conn.execute("UPDATE admin_users SET role='super_admin' WHERE username='KEJU' AND role!='super_admin'")
    conn.commit()

    conn.close()

def auto_load_source():
    files = scan_source_files()
    if not files.get('main'):
        return False

    APP_STATE['main_file'] = files['main']
    APP_STATE['advance_file'] = files.get('advance')
    APP_STATE['addressbook_file'] = files.get('addressbook')

    # 默认加载当前真实月份，而非全部月份
    from datetime import datetime
    current_month = datetime.now().strftime('%Y-%m')
    ok, msg = _run_pipeline(files, month_filter=current_month)
    print(f'  {msg}')
    _ensure_viewer_account()
    return ok

# ── gunicorn 启动时自动加载数据（python app.py 时跳过，由 __main__ 处理）──
_app_initialized = False

def _gunicorn_init():
    global _app_initialized
    if _app_initialized:
        return
    _app_initialized = True
    from core.database import init_db
    init_db(app.config['DATA_FOLDER'])
    loaded = auto_load_source()
    if loaded:
        print('  ✓ 源数据已自动加载')
    else:
        print('  ⚠ data/source/ 下缺少主文件')

if __name__ != '__main__':
    _gunicorn_init()

if __name__ == '__main__':
    from core.database import init_db
    _app_initialized = True
    init_db(app.config['DATA_FOLDER'])

    port = find_free_port(8080)
    print('=' * 50)
    print('  ENPRIZON LINDI PROJECT')
    print(f'  启动地址: http://localhost:{port}')
    loaded = auto_load_source()
    if not loaded:
        print('  ⚠ data/source/ 下缺少主文件，请放入再重启')
    print('=' * 50)
    app.run(debug=False, host='0.0.0.0', port=port)
