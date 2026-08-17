"""
ENPRIZON LINDI PROJECT — Flask 主入口
"""
import json, os, sys, socket, io, time, secrets, re
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_from_directory, render_template, send_file, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from functools import wraps

# 业务时区：坦桑尼亚 UTC+3（服务器可能为其他时区，全系统统一以此为准）
EAT = timezone(timedelta(hours=3))

app = Flask(__name__)
app.config['PREFERRED_URL_SCHEME'] = 'http'
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get('KILWA_SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB 上传上限
# 会话 Cookie 安全加固（防 CSRF/劫持：SameSite 严格 + HttpOnly；Secure 仅 HTTPS 时开启）
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('KILWA_HTTPS', '') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True

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

def require_permission(module, action):
    """细粒度权限检查：角色继承 + 单独授权"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('logged_in'):
                return jsonify({'ok': False, 'error': 'unauthorized', 'need_login': True}), 401
            from core.database import check_permission
            username = session.get('username', '')
            if not check_permission(app.config['DATA_FOLDER'], username, module, action):
                _audit('perm_denied', '', json.dumps({'user': username, 'module': module, 'action': action}))
                return jsonify({'ok': False, 'error': 'forbidden', 'need_permission': module}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

# ── 登录暴力破解防护（轻量内存限速：失败计数 + 锁定窗口） ──────
_LOGIN_FAILS = {}          # key: "ip|username" → [fail_count, lock_until_ts]
_LOGIN_MAX_FAILS = 5       # 5 次失败
_LOGIN_LOCK_SECONDS = 900  # 锁定 15 分钟

def _login_blocked(key):
    """返回 True 表示该 key 当前处于锁定窗口内"""
    entry = _LOGIN_FAILS.get(key)
    if not entry:
        return False
    import time as _t
    if _t.time() < entry[1]:
        return True
    if entry[1] > 0:
        _LOGIN_FAILS.pop(key, None)
    return False

def _login_fail_record(key):
    """记录一次失败；达到阈值则开启锁定窗口，返回剩余锁定秒数"""
    import time as _t
    cnt, lock_until = _LOGIN_FAILS.get(key, (0, 0))
    cnt += 1
    if cnt >= _LOGIN_MAX_FAILS:
        lock_until = _t.time() + _LOGIN_LOCK_SECONDS
        _LOGIN_FAILS[key] = (0, lock_until)
        return _LOGIN_LOCK_SECONDS
    _LOGIN_FAILS[key] = (cnt, lock_until)
    return 0

def _login_success_reset(key):
    _LOGIN_FAILS.pop(key, None)

@app.route('/api/login', methods=['POST'])
def api_login():
    from core.database import verify_admin, has_admin, set_admin_password
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    client_ip = request.remote_addr or 'unknown'
    lock_key = f'{client_ip}|{username}'

    if _login_blocked(lock_key):
        return jsonify({'ok': False, 'error': 'too_many_attempts', 'need_wait': True}), 429

    if not has_admin(app.config['DATA_FOLDER']):
        return jsonify({'ok': False, 'error': 'no_admin', 'need_setup': True})

    if verify_admin(app.config['DATA_FOLDER'], username, password):
        _login_success_reset(lock_key)
        # 登录前重建会话，防 session fixation（攻击者预置的 cookie 在登录后作废）
        session.clear()
        session['logged_in'] = True
        session['username'] = username
        from core.database import get_user_role
        # 安全修复：角色查询失败时回退到最低权限 viewer，而非 admin
        # （原为 or 'admin'，一旦 get_user_role 返回 None 即越权为管理员）
        session['role'] = get_user_role(app.config['DATA_FOLDER'], username) or 'viewer'
        _audit('login', '', json.dumps({'user': username}))
        return jsonify({'ok': True})
    wait = _login_fail_record(lock_key)
    _audit('login_fail', '', json.dumps({'user': username}))
    if wait:
        return jsonify({'ok': False, 'error': 'too_many_attempts', 'need_wait': True,
                        'retry_after': wait}), 429
    return jsonify({'ok': False, 'error': 'invalid_credentials'})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    _audit('logout', '', json.dumps({'user': session.get('username', '')}))
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    from core.database import has_admin, get_user_permissions
    return jsonify({
        'logged_in': session.get('logged_in', False),
        'username': session.get('username', ''),
        'role': session.get('role', ''),
        'has_admin': has_admin(app.config['DATA_FOLDER']),
        # P18 阶段2: 用户有效权限摘要(如 ['dashboard:view','salary:view'])
        'permissions': get_user_permissions(app.config['DATA_FOLDER'], session.get('username', ''))
            if session.get('logged_in') else [],
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
    if not new_password or len(new_password) < 6:
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
    if not username or not role:
        return jsonify({'ok': False, 'error': '无效参数'}), 400
    try:
        set_user_role(app.config['DATA_FOLDER'], username, role)
        _audit('role_change', username, json.dumps({'new_role': role}))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/admin/users/create', methods=['POST'])
@super_admin_required
def create_user():
    """超级管理员新增登录用户（含角色）"""
    from core.database import create_admin_user
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    role = (data.get('role') or 'viewer').strip()
    result = create_admin_user(app.config['DATA_FOLDER'], username, password, role)
    if result == 'ok':
        _audit('user_create', username, json.dumps({'role': role}))
        return jsonify({'ok': True})
    if result == 'exists':
        return jsonify({'ok': False, 'error': '用户名已存在'}), 400
    if result == 'invalid_role':
        return jsonify({'ok': False, 'error': '无效角色'}), 400
    return jsonify({'ok': False, 'error': '用户名或密码不合法（密码至少6位）'}), 400

@app.route('/admin/users/change-password', methods=['POST'])
@super_admin_required
def change_user_password():
    """超级管理员修改指定用户密码（不要求旧密码）"""
    from core.database import reset_admin_password
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    new_password = data.get('new_password') or ''
    result = reset_admin_password(app.config['DATA_FOLDER'], username, new_password)
    if result == 'ok':
        _audit('user_password_reset', username, json.dumps({}))
        return jsonify({'ok': True})
    if result == 'not_found':
        return jsonify({'ok': False, 'error': '用户不存在'}), 404
    return jsonify({'ok': False, 'error': '密码至少6位'}), 400

@app.route('/admin/users/rename', methods=['POST'])
@super_admin_required
def rename_user():
    """超级管理员重命名用户（同步 user_grants 授权 + approval_routes 审批人）"""
    from core.database import rename_admin_user
    data = request.get_json(silent=True) or {}
    old_username = (data.get('username') or '').strip()
    new_username = (data.get('new_username') or '').strip()
    result = rename_admin_user(app.config['DATA_FOLDER'], old_username, new_username)
    if result == 'ok':
        _audit('user_rename', old_username, json.dumps({'new_username': new_username}))
        return jsonify({'ok': True})
    if result == 'not_found':
        return jsonify({'ok': False, 'error': '用户不存在'}), 404
    if result == 'exists':
        return jsonify({'ok': False, 'error': '用户名已存在'}), 400
    return jsonify({'ok': False, 'error': '用户名不合法'}), 400

@app.route('/admin/users/delete', methods=['POST'])
@super_admin_required
def delete_user():
    """超级管理员删除用户（自动清理 user_grants 授权 + approval_routes 审批人）"""
    from core.database import delete_admin_user
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    result = delete_admin_user(app.config['DATA_FOLDER'], username)
    if result == 'ok':
        _audit('user_delete', username, json.dumps({}))
        return jsonify({'ok': True})
    if result == 'not_found':
        return jsonify({'ok': False, 'error': '用户不存在'}), 404
    if result == 'last_super_admin':
        return jsonify({'ok': False, 'error': '不能删除最后一个超级管理员'}), 400
    return jsonify({'ok': False, 'error': '删除失败'}), 400

# ═══════════════════════════════════════════════════════════
#  API: 细粒度权限管理（super_admin 管理授权）
# ═══════════════════════════════════════════════════════════

@app.route('/api/permissions/users', methods=['GET'])
@admin_required
def api_permissions_users():
    """P18C: 用户列表 + 角色 + permissions 摘要 + 单用户 grants 明细"""
    from core.database import (list_all_users, get_user_permissions_summary,
                               get_conn, PERMISSION_CATALOG)
    conn = get_conn(app.config['DATA_FOLDER'])
    users = list_all_users(app.config['DATA_FOLDER'])
    try:
        for u in users:
            u['permissions'] = get_user_permissions_summary(app.config['DATA_FOLDER'], u['username'])
            rows = conn.execute(
                """SELECT p.module, p.action, g.grant_type
                   FROM user_grants g JOIN permissions p ON g.permission_id = p.id
                   WHERE g.username=? ORDER BY p.module, p.action""",
                (u['username'],)).fetchall()
            u['grants'] = [{
                'module': r['module'], 'action': r['action'], 'grant_type': r['grant_type'],
                'name': (PERMISSION_CATALOG.get(r['module'] + ':' + r['action']) or {})
                        .get('name', r['module'] + ':' + r['action']),
            } for r in rows]
    finally:
        conn.close()
    return jsonify({'ok': True, 'users': users})

@app.route('/api/permissions/roles', methods=['GET'])
@super_admin_required
def api_permissions_roles():
    """P18b+P18D: 角色权限列表(含继承展开 + 来源标记 + 元数据 + 角色 CRUD 元信息)

    query: ?role=X 只返回该角色(含继承展开 effective + source_role)
    """
    from core.database import (get_conn, ROLE_LEVELS, ROLE_HIERARCHY,
                               ROLE_DEFAULT_PERMISSIONS, PERMISSION_CATALOG,
                               get_role_permissions, BUILTIN_ROLES)
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        rows = conn.execute(
            "SELECT role, module, action, allow FROM role_permissions ORDER BY role, module, action"
        ).fetchall()
        # 权限项计数(allow=1)
        perm_counts = {}
        for r in rows:
            if r['allow'] == 1:
                perm_counts[r['role']] = perm_counts.get(r['role'], 0) + 1
        # 用户分配计数
        user_counts = {}
        for r in conn.execute("SELECT role, COUNT(*) c FROM admin_users GROUP BY role").fetchall():
            user_counts[r['role']] = r['c']
    finally:
        conn.close()

    table_roles = set(perm_counts.keys())
    all_roles = sorted(set(table_roles) | set(ROLE_LEVELS.keys()))

    def _inherit_chain(r):
        chain = [r]
        q = list(ROLE_HIERARCHY.get(r, []))
        while q:
            x = q.pop(0)
            chain.append(x)
            q.extend(ROLE_HIERARCHY.get(x, []))
        return chain

    def _source_of(r, module, action):
        # 该权限项来自继承链上哪一级(自身或下级角色);表里 allow=1 的第一级
        for rr in _inherit_chain(r):
            for row in rows:
                if row['role'] == rr and row['module'] == module and row['action'] == action and row['allow'] == 1:
                    return rr
        return r

    role_filter = request.args.get('role', '').strip()
    inherited = {}
    for r in all_roles:
        perms = get_role_permissions(app.config['DATA_FOLDER'], r)
        inherited[r] = [
            {'module': m, 'action': a,
             'source_role': _source_of(r, m, a) if r != 'super_admin' else 'super_admin'}
            for m, acts in perms.items() for a in acts if m != '*'
        ]
    resp = {
        'ok': True,
        'roles': [{'role': r, 'builtin': (r in BUILTIN_ROLES or r == 'super_admin'),
                   'permission_count': perm_counts.get(r, 0), 'user_count': user_counts.get(r, 0)}
                  for r in all_roles],
        'hierarchy': ROLE_HIERARCHY,
        'catalog': PERMISSION_CATALOG,
        'defaults': ROLE_DEFAULT_PERMISSIONS,
        'permissions': [dict(r) for r in rows],
        'effective': inherited,
    }
    if role_filter:
        if role_filter not in all_roles:
            return jsonify({'ok': False, 'error': 'unknown_role'}), 400
        resp['effective'] = {role_filter: inherited[role_filter]}
        resp['roles'] = [x for x in resp['roles'] if x['role'] == role_filter]
    return jsonify(resp)

@app.route('/api/permissions/roles', methods=['POST'])
@super_admin_required
def api_permissions_roles_create():
    """P18D: 新增角色 — body {name, permissions:[{module,action,allow}]}"""
    from core.database import get_conn, ROLE_LEVELS, PERMISSION_CATALOG
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        # 冲突: 内置角色名 / 已存在角色名
        if name in ROLE_LEVELS:
            return jsonify({'ok': False, 'error': 'role_name_exists'}), 400
        exists = conn.execute("SELECT 1 FROM role_permissions WHERE role=? LIMIT 1", (name,)).fetchone()
        if exists:
            return jsonify({'ok': False, 'error': 'role_name_exists'}), 400
        permissions = data.get('permissions') or []
        for p in permissions:
            module = (p.get('module') or '').strip()
            action = (p.get('action') or '').strip()
            if module and action:
                conn.execute(
                    "INSERT OR REPLACE INTO role_permissions (role, module, action, allow) VALUES (?,?,?,?)",
                    (name, module, action, 1 if int(p.get('allow', 1)) else 0))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/permissions/roles/rename', methods=['PUT'])
@super_admin_required
def api_permissions_roles_rename():
    """P18D: 重命名角色 — body {old, new},同步 role_permissions + admin_users"""
    from core.database import get_conn, ROLE_LEVELS, BUILTIN_ROLES
    data = request.get_json(silent=True) or {}
    old = (data.get('old') or '').strip()
    new = (data.get('new') or '').strip()
    if not old or not new:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        # old 必须存在(内置或自定义)
        exists_old = conn.execute("SELECT 1 FROM role_permissions WHERE role=? LIMIT 1", (old,)).fetchone()
        if not exists_old and old not in ROLE_LEVELS:
            return jsonify({'ok': False, 'error': 'unknown_role'}), 400
        # new 不能与内置或其他角色冲突
        if new in ROLE_LEVELS:
            return jsonify({'ok': False, 'error': 'role_name_exists'}), 400
        exists_new = conn.execute("SELECT 1 FROM role_permissions WHERE role=? LIMIT 1", (new,)).fetchone()
        if exists_new:
            return jsonify({'ok': False, 'error': 'role_name_exists'}), 400
        conn.execute("UPDATE role_permissions SET role=? WHERE role=?", (new, old))
        conn.execute("UPDATE admin_users SET role=? WHERE role=?", (new, old))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/permissions/roles/<role>', methods=['DELETE'])
@super_admin_required
def api_permissions_roles_delete(role):
    """P18D: 删除角色 — 内置拒绝,有用户拒绝"""
    from core.database import get_conn, BUILTIN_ROLES
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        if role in BUILTIN_ROLES or role == 'super_admin':
            return jsonify({'ok': False, 'error': 'role_builtin_nodel'}), 400
        cnt = conn.execute("SELECT COUNT(*) c FROM admin_users WHERE role=?", (role,)).fetchone()
        if cnt and cnt['c'] > 0:
            return jsonify({'ok': False, 'error': 'role_has_users'}), 400
        conn.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/permissions/roles/reset', methods=['POST'])
@super_admin_required
def api_permissions_roles_reset():
    """P18b: 将指定角色 role_permissions 重置为 ROLE_DEFAULT_PERMISSIONS 默认"""
    from core.database import get_conn, ROLE_DEFAULT_PERMISSIONS
    data = request.get_json(silent=True) or {}
    role = (data.get('role') or '').strip()
    if role not in ROLE_DEFAULT_PERMISSIONS or role == 'super_admin':
        return jsonify({'ok': False, 'error': 'invalid_role'}), 400
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        conn.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        grants = ROLE_DEFAULT_PERMISSIONS[role]
        for module, actions in grants.items():
            if module == '*':
                continue
            for action in actions:
                conn.execute(
                    "INSERT OR REPLACE INTO role_permissions (role, module, action, allow) VALUES (?,?,?,1)",
                    (role, module, action))
    finally:
        conn.commit()
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/permissions/roles', methods=['PUT'])
@super_admin_required
def api_permissions_roles_put():
    """P18: 角色权限编辑 — 写 role_permissions(REPLACE)

    body: {role, module, action, allow} 或 {updates:[{role,module,action,allow}, ...]}
    """
    from core.database import get_conn
    data = request.get_json(silent=True) or {}
    updates = data.get('updates') if isinstance(data.get('updates'), list) else [data]
    if not updates:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        for u in updates:
            role = (u.get('role') or '').strip()
            module = (u.get('module') or '').strip()
            action = (u.get('action') or '').strip()
            if not role or not module or not action:
                return jsonify({'ok': False, 'error': 'missing_fields'}), 400
            if role == 'super_admin':
                return jsonify({'ok': False, 'error': 'super_admin_immutable'}), 400
            allow = 1 if int(u.get('allow', 1)) else 0
            conn.execute(
                "INSERT OR REPLACE INTO role_permissions (role, module, action, allow) VALUES (?,?,?,?)",
                (role, module, action, allow))
    finally:
        conn.commit()
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/permissions/grant', methods=['POST'])
@super_admin_required
def api_permissions_grant():
    from core.database import grant_user_permission
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    module = data.get('module', '').strip()
    action = data.get('action', '').strip()
    grant_type = data.get('grant_type', 'allow')
    if not username or not module or not action:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    try:
        grant_user_permission(app.config['DATA_FOLDER'], username, module, action, grant_type)
        _audit('perm_grant', username, json.dumps({'module': module, 'action': action, 'type': grant_type}))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/permissions/grant', methods=['DELETE'])
@super_admin_required
def api_permissions_revoke():
    from core.database import revoke_user_grant_by_action
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    module = data.get('module', '').strip()
    action = data.get('action', '').strip()
    if not username or not module or not action:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    try:
        revoke_user_grant_by_action(app.config['DATA_FOLDER'], username, module, action)
        _audit('perm_revoke', username, json.dumps({'module': module, 'action': action}))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/permissions/init-defaults', methods=['POST'])
@super_admin_required
def api_permissions_init_defaults():
    from core.database import init_default_permissions
    init_default_permissions(app.config['DATA_FOLDER'])
    _audit('perm_init_defaults', '', '{}')
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: 全局搜索
# ═══════════════════════════════════════════════════════════

@app.route('/api/search', methods=['GET'])
@login_required
def global_search():
    q = request.args.get('q', '').strip()
    scope = request.args.get('scope', 'all')
    if len(q) < 2:
        return jsonify({'ok': False, 'error': 'query_too_short', 'results': []})
    from core.database import search_all
    results = search_all(app.config['DATA_FOLDER'], q, scope)
    return jsonify({'ok': True, 'results': results, 'q': q, 'scope': scope})

# ═══════════════════════════════════════════════════════════
#  API: 表单自定义管理
# ═══════════════════════════════════════════════════════════

@app.route('/api/forms/schemas', methods=['GET'])
@login_required
def api_form_schemas():
    from core.database import list_form_schemas
    schemas = list_form_schemas(app.config['DATA_FOLDER'])
    return jsonify({'ok': True, 'schemas': schemas})

@app.route('/api/forms/schema/<int:schema_id>', methods=['GET'])
@login_required
def api_form_schema(schema_id):
    from core.database import get_form_schema
    schema = get_form_schema(app.config['DATA_FOLDER'], schema_id)
    if not schema:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return jsonify({'ok': True, 'schema': schema})

@app.route('/api/forms/schema', methods=['POST'])
@super_admin_required
def api_create_form_schema():
    from core.database import create_form_schema
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'ok': False, 'error': 'missing_name'}), 400
    try:
        sid = create_form_schema(app.config['DATA_FOLDER'], data)
        _audit('form_schema_create', '', json.dumps({'name': data['name']}))
        return jsonify({'ok': True, 'id': sid})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/forms/schema/<int:schema_id>', methods=['PUT'])
@super_admin_required
def api_update_form_schema(schema_id):
    from core.database import update_form_schema
    data = request.get_json(silent=True) or {}
    update_form_schema(app.config['DATA_FOLDER'], schema_id, data)
    _audit('form_schema_update', '', json.dumps({'id': schema_id}))
    return jsonify({'ok': True})

@app.route('/api/forms/schema/<int:schema_id>', methods=['DELETE'])
@super_admin_required
def api_delete_form_schema(schema_id):
    from core.database import delete_form_schema
    delete_form_schema(app.config['DATA_FOLDER'], schema_id)
    _audit('form_schema_delete', '', json.dumps({'id': schema_id}))
    return jsonify({'ok': True})

@app.route('/api/forms/schema/<int:schema_id>/fields', methods=['POST'])
@super_admin_required
def api_add_form_field(schema_id):
    from core.database import add_form_field
    data = request.get_json(silent=True) or {}
    if not data.get('field_key'):
        return jsonify({'ok': False, 'error': 'missing_field_key'}), 400
    add_form_field(app.config['DATA_FOLDER'], schema_id, data)
    _audit('form_field_add', '', json.dumps({'schema_id': schema_id, 'key': data['field_key']}))
    return jsonify({'ok': True})

@app.route('/api/forms/schema/<int:schema_id>/fields/<int:field_id>', methods=['PUT'])
@super_admin_required
def api_update_form_field(schema_id, field_id):
    from core.database import update_form_field
    data = request.get_json(silent=True) or {}
    update_form_field(app.config['DATA_FOLDER'], field_id, data)
    return jsonify({'ok': True})

@app.route('/api/forms/schema/<int:schema_id>/fields/<int:field_id>', methods=['DELETE'])
@super_admin_required
def api_delete_form_field(schema_id, field_id):
    from core.database import delete_form_field
    delete_form_field(app.config['DATA_FOLDER'], field_id)
    return jsonify({'ok': True})

@app.route('/api/forms/seed-defaults', methods=['POST'])
@super_admin_required
def api_seed_default_forms():
    from core.database import seed_default_forms
    seed_default_forms(app.config['DATA_FOLDER'])
    _audit('form_seed_defaults', '', '{}')
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: 旧数据归档
# ═══════════════════════════════════════════════════════════

@app.route('/api/archive/months', methods=['GET'])
@login_required
def archive_months():
    from core.database import list_archive_months
    months = list_archive_months(app.config['DATA_FOLDER'])
    # 检查归档是否存在
    import os
    exists = os.path.exists(os.path.join(app.config['DATA_FOLDER'], 'archived_kilwa.db'))
    return jsonify({'ok': True, 'months': months, 'archived': exists})

@app.route('/api/archive/salary', methods=['GET'])
@login_required
def archive_salary():
    from core.database import get_archive_salary
    month = request.args.get('month', '').strip()
    if not month:
        return jsonify({'ok': False, 'error': 'missing_month'}), 400
    data = get_archive_salary(app.config['DATA_FOLDER'], month)
    if data is None:
        return jsonify({'ok': False, 'error': 'archive_unavailable'}), 404
    return jsonify({'ok': True, 'data': data})

def strip_dept(dept):
    """去掉 ENPRIZON LINDI PROJECT 前缀，保留子部门；纯顶层部门保留原名"""
    if not dept:
        return ''
    if dept == 'ENPRIZON LINDI PROJECT':
        return 'ENPRIZON LINDI PROJECT'
    return dept.replace('ENPRIZON LINDI PROJECT/', '')

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
#  P9: Web 采集数据回填（纯采集模式唯一数据源，见 collection_submit）
# ═══════════════════════════════════════════════════════════
#  核心解析+计算引擎（被 auto_load 和 /reload 复用）
# ═══════════════════════════════════════════════════════════

def _derive_overrides_from_events(data_folder, month):
    """从已批准的 employee_events 推导当月 overrides（事件→覆盖桥接）"""
    from core.database import get_approved_events_for_month
    from calendar import monthrange

    events = get_approved_events_for_month(data_folder, month)
    derived = {}

    if month and len(month) == 7:
        y, m = int(month[:4]), int(month[5:7])
        _, last_day = monthrange(y, m)
        month_end = f'{month}-{last_day:02d}'
    else:
        month_end = ''

    for ev in events:
        eid = ev['employee_id']
        if eid not in derived:
            derived[eid] = []

        try:
            payload = json.loads(ev.get('payload', '{}'))
        except:
            payload = {}

        eff = ev.get('effective_date', '')

        if ev['event_type'] == 'transfer':
            # 调岗 → 临时覆盖（effective_date 到月底）
            new_type = payload.get('new_type', payload.get('salary_type', ''))
            if new_type in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                derived[eid].append({
                    'id': f'event_{ev["id"]}',
                    'salary_type': new_type,
                    'day_rate': payload.get('day_rate', 0),
                    'monthly_salary': payload.get('monthly_salary', 0),
                    'start_date': eff,
                    'end_date': month_end,
                    'note': f'OA调岗 #{ev["id"]}',
                    'type': '',
                    'shift': '', 'captain': '',
                    'effective_from': month,
                })
        elif ev['event_type'] == 'salary_change':
            # 薪资变更 → 临时覆盖
            derived[eid].append({
                'id': f'event_{ev["id"]}',
                'salary_type': payload.get('salary_type', ''),
                'day_rate': payload.get('day_rate', 0),
                'monthly_salary': payload.get('monthly_salary', 0),
                'start_date': eff,
                'end_date': month_end,
                'note': f'OA薪资变 #{ev["id"]}',
                'type': '',
                'shift': '', 'captain': '',
                'effective_from': month,
            })
        elif ev['event_type'] in ('resign', 'dismiss'):
            # 离职 → 排除（从 effective_date 开始不计薪）
            derived[eid].append({
                'id': f'event_{ev["id"]}',
                'salary_type': '',
                'day_rate': 0, 'monthly_salary': 0,
                'start_date': eff,
                'end_date': month_end,
                'note': f'OA离职 #{ev["id"]}',
                'type': 'exclusion',
                'shift': '', 'captain': '',
                'effective_from': month,
            })

    return derived

def load_employees_from_db(data_folder):
    """纯采集模式：从 employees 表读取员工列表（含薪资覆盖、NSSF、离职过滤、硬排除）"""
    from core.database import get_conn, load_dismissed
    from core.namematch import make_employee_id

    conn = get_conn(data_folder)
    rows = conn.execute("""
        SELECT id, name, department, default_type, day_rate, monthly_salary,
               nssf_enrolled, phone, team_id, custom_number
        FROM employees ORDER BY CAST(id AS INTEGER)
    """).fetchall()
    conn.close()

    employees = []
    for r in rows:
        eid = r['id']
        if not eid or eid in HARD_EXCLUDE_IDS:
            continue
        employees.append({
            'id': eid,
            'name': r['name'] or eid,
            'department': r['department'] or '',
            'default_type': r['default_type'] or 'day_rate',
            'source': 'db',
            'override_type': None,
            'overrides': [],
            'day_rate': r['day_rate'] or 0,
            'monthly_salary': r['monthly_salary'] or 0,
            'advance_total': 0,
            'phone': r['phone'] or '',
            'nssf_enrolled': bool(r['nssf_enrolled']),
            'team_id': r['team_id'] or 0,   # P15: 评分奖金按班组归属
            'custom_number': r['custom_number'] or '',  # 工号（新入职自动递增生成）
        })

    # 离职过滤
    dismissed = load_dismissed(data_folder)
    employees = [e for e in employees if e['id'] not in dismissed]
    return employees


def _build_db_ab_index(data_folder):
    """纯采集模式：从 employees 表构建 namematch 索引（_AB_INDEX），替代通讯录 Excel
    使 make_employee_id('EMA BUKWIMBA') 反查到新ID（如 '34'）。
    注意：若 _AB_INDEX 已有通讯录加载的数据（如启动时通讯录种子），本函数用 DB 覆盖/补充，
    DB 优先保证新ID体系一致。
    """
    from core.namematch import _AB_INDEX, _EXTRA_AB_ENTRIES, strip_alias
    from core.database import get_conn
    import re as _re
    _conn = get_conn(data_folder)
    _rows = _conn.execute("SELECT id, name, alias FROM employees").fetchall()
    _conn.close()
    # 保留已有索引（通讯录加载的变体），DB 精确姓名覆盖
    for _eid, _name, _alias in _rows:
        if not _name:
            continue
        _sa = strip_alias(str(_name))
        _key = _re.sub(r'\s+', '', _sa).upper()
        if _key:
            _AB_INDEX[_key] = (str(_eid), _sa)
        # 去最后一个词的短名
        _words = _sa.split()
        if len(_words) > 1:
            _short = _re.sub(r'\s+', '', ' '.join(_words[:-1])).upper()
            _AB_INDEX.setdefault(_short, (str(_eid), _sa))
        # P19: 非空别名也建立索引(setdefault 不覆盖姓名主键)
        if _alias:
            _sa_alias = strip_alias(str(_alias))
            _ak = _re.sub(r'\s+', '', _sa_alias).upper()
            if _ak:
                _AB_INDEX.setdefault(_ak, (str(_eid), _sa_alias))
    # 补充通讯录外人员（离职等）
    for _k, _v in _EXTRA_AB_ENTRIES.items():
        _AB_INDEX.setdefault(_k, _v)


def build_attendance_from_overrides(main_data, data_folder):
    """纯采集模式：从 attendance_overrides 构建 main_data['attendance']
    将 P（出勤）写入 normal 列表，供出勤网格与日薪/月薪计算使用
    """
    from core.database import get_conn
    conn = get_conn(data_folder)
    rows = conn.execute(
        "SELECT employee_id, date FROM attendance_overrides WHERE status='P' ORDER BY date"
    ).fetchall()
    conn.close()
    by_date = {}
    for r in rows:
        by_date.setdefault(r['date'], []).append(r['employee_id'])
    attendance = []
    for dt in sorted(by_date):
        attendance.append({'date': dt, 'normal': by_date[dt], 'leave': [], 'absent': []})
    main_data['attendance'] = attendance


def _run_pipeline(month_filter=None):
    """
    纯采集模式：从数据库（collection_submissions + attendance_overrides + employees）重建并计算
    month_filter: "2026-05" 或 None（全部）
    返回: (ok, msg)
    """
    from core.calculator import calculate_all

    # ── main_data 从采集记录重建 ──
    main_data = {
        'shift_production': [], 'driller_production': [],
        'crush_production': [], 'attendance': [], 'dates': [],
        'piece_rate_people': {'driller': set(), 'underground': set()},
        'daily_salary_people': set(),
    }
    rebuild_main_data_from_collections(main_data)
    build_attendance_from_overrides(main_data, app.config['DATA_FOLDER'])
    # dates：产量采集日期 + 出勤日期
    _dates = set(main_data.get('dates', []))
    for _k in ('shift_production', 'driller_production', 'crush_production', 'attendance'):
        for _d in main_data.get(_k, []):
            if _d.get('date'):
                _dates.add(_d['date'])
    main_data['dates'] = sorted(_dates)

    # ── employees 从 DB 读取 ──
    employees = load_employees_from_db(app.config['DATA_FOLDER'])
    if not employees:
        return False, '员工表为空，请先导入通讯录或员工数据'

    # ── 构建 namematch 索引（纯采集模式：从 DB employees 表，不依赖通讯录 Excel）──
    # 使 make_employee_id('EMA BUKWIMBA') 能反查新ID（采集回填的 main_data 用姓名，
    # 计算引擎需再转回 eid；之前依赖通讯录 Excel 加载 _AB_INDEX，纯采集模式下改为 DB）
    _build_db_ab_index(app.config['DATA_FOLDER'])

    APP_STATE['address_book'] = {}

    # ── NSSF（社保）参保状态 ──
    from core.nssf import load_nssf_enrollment
    nssf_enrollment = load_nssf_enrollment(app.config['DATA_FOLDER'])
    for emp in employees:
        emp['nssf_enrolled'] = nssf_enrollment.get(emp['id'], {}).get('enrolled', False)
    APP_STATE['nssf_sdl_members'] = {}

    # ── 加载持久化的日薪/月薪基数 + override_type ──
    from core.database import load_overrides as _load_ov
    saved_overrides = _load_ov(app.config['DATA_FOLDER'], month=month_filter)

    # P5-b: 合并事件驱动的覆盖（事件优先级高于DB覆盖）
    events_overrides = _derive_overrides_from_events(app.config['DATA_FOLDER'], month_filter) if month_filter else {}
    for eid, eovs in events_overrides.items():
        if eid not in saved_overrides:
            saved_overrides[eid] = []
        # 事件覆盖追加到列表前面（优先级更高）
        saved_overrides[eid] = eovs + saved_overrides[eid]

    for emp in employees:
        eid = emp['id']
        if eid in saved_overrides:
            for o in saved_overrides[eid]:
                has_range = bool(o.get('start_date', '') or o.get('end_date', ''))
                st = o.get('salary_type', '')
                # 仅永久覆盖（无日期区间）更新 override_type，临时例外不影响基础类型
                if not has_range and st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                    emp['override_type'] = st
                # R3b: 仅永久覆盖更新基础基数。临时例外由 get_day_rate_for_date 按天读取，
                # 写入 emp.day_rate 会污染默认字段，导致区间外回退到例外金额
                if not has_range:
                    if st == 'day_rate' and o.get('day_rate', 0) > 0:
                        emp['day_rate'] = o['day_rate']
                    if st == 'monthly' and o.get('monthly_salary', 0) > 0:
                        emp['monthly_salary'] = o['monthly_salary']
        # 清零：仅基于永久覆盖类型，临时例外不触发清零
        ot = emp.get('override_type')
        # P14.4: 井下工人（default_type=piece_underground）在 scoring 模式下按月薪轨道，
        # 即使 override_type 被 day_rate 覆盖也保留 monthly_salary，不做清零
        if emp.get('default_type') == 'piece_underground':
            pass
        elif ot == 'day_rate':
            emp['monthly_salary'] = 0
        elif ot == 'monthly':
            emp['day_rate'] = 0
        elif ot in ('piece_underground', 'piece_driller', 'piece_crush'):
            emp['day_rate'] = 0
            emp['monthly_salary'] = 0

    # ── 预支（纯采集模式暂不支持预支采集，预留空） ──
    advance_data = None

    # ── P9: Web 采集数据回填（main_data 已含采集数据，无需重复合并） ──

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
    overrides = _load_override_ov(app.config['DATA_FOLDER'], month=month_filter)
    exclusions = _load_excl(app.config['DATA_FOLDER'])
    bonus_penalties = _load_bp(app.config['DATA_FOLDER'], month_filter) if month_filter else {}
    result = calculate_all(main_data, employees, overrides=overrides, exclusions=exclusions,
                           pricing=APP_STATE['config'], data_folder=app.config['DATA_FOLDER'],
                           bonus_penalties=bonus_penalties)

    APP_STATE['parsed'] = True
    APP_STATE['calculated'] = True
    APP_STATE['employees'] = employees
    APP_STATE['main_data'] = main_data
    APP_STATE['advance_data'] = advance_data
    APP_STATE['salary_result'] = result
    APP_STATE['month'] = month_filter
    APP_STATE['source_info'] = {}

    # 保存当月结果到数据库（仅在有月份筛选时，确保数据准确）
    if result and month_filter and main_data.get('dates'):
        from core.database import save_monthly_result
        save_monthly_result(app.config['DATA_FOLDER'], month_filter, result)

    return True, f'已加载 {len(employees)} 名员工，应发 {result["total_gross"]:,} TZS'


def _refresh_employees_cache():
    """P23 R4: 写 DB 后刷新员工缓存 + 重算。

    override_type 推导 + 互斥清零逻辑集中在 _run_pipeline，写操作后全量重建，
    避免在端点内做副本同步造成逻辑漂移（save_override 旧手动同步即漂移例证）。
    APP_STATE 未加载时返回 None。
    """
    if not APP_STATE.get('parsed'):
        return None
    _month = APP_STATE.get('month')
    return _run_pipeline(month_filter=_month if _month != 'all' else None)


def _sync_employee_cache(eid, fields):
    """P23 R4: 轻量同步单个员工字段（不触发全量重建），用于纯展示字段。"""
    for _emp in APP_STATE.get('employees', []):
        if _emp.get('id') == eid:
            _emp.update(fields)
            break

# ═══════════════════════════════════════════════════════════
#  静态页面
# ═══════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html', version=APP_VERSION)

@app.route('/static/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

# ── 移动端专属路由（P16）──
@app.route('/m')
def mobile_index():
    return render_template('mobile.html', version=APP_VERSION)


_MOBILE_UA_TOKENS = ('iphone', 'ipad', 'ipod', 'android', 'mobile', 'windows phone', 'blackberry')


@app.before_request
def mobile_redirect():
    """移动端 UA 访问 / 时重定向到 /m；桌面端访问 /m 不反向跳转（便于调试）。
    使用 url_for 以尊重 KILWA_SCRIPT_NAME 子路径（如 /salary），避免重定向到根 /m 导致 404。"""
    if request.path == '/' and any(t in request.headers.get('User-Agent', '').lower() for t in _MOBILE_UA_TOKENS):
        return redirect(url_for('mobile_index'))

# ═══════════════════════════════════════════════════════════
#  API: 数据源信息
# ═══════════════════════════════════════════════════════════

@app.route('/source-info', methods=['GET'])
@login_required
def get_source_info():
    """纯采集模式：无源文件信息，返回空"""
    return jsonify({})

@app.route('/available-months', methods=['GET'])
@login_required
def get_available_months():
    """返回可选的月份列表（纯采集模式：从 collection_submissions + 数据库补充）"""
    from datetime import datetime
    from core.database import get_conn
    months = set()
    # 从已加载的 main_data（采集回填后的数据）提取
    md = APP_STATE.get('main_data', {})
    for d in md.get('dates', []):
        months.add(d[:7])
    # 从 collection_submissions 提取（采集数据的权威月份来源）
    try:
        conn = get_conn(app.config['DATA_FOLDER'])
        for r in conn.execute(
            "SELECT DISTINCT substr(submission_date,1,7) FROM collection_submissions "
            "WHERE submission_date LIKE '____-__-__'").fetchall():
            if r[0]: months.add(r[0])
        conn.close()
    except Exception:
        pass
    # 从数据库补充历史月份
    from core.database import list_monthly_months
    months.update(list_monthly_months(app.config['DATA_FOLDER']))
    # 从出勤覆盖表和奖金罚款表补充月份
    try:
        conn = get_conn(app.config['DATA_FOLDER'])
        for r in conn.execute("SELECT DISTINCT substr(date,1,7) FROM attendance_overrides WHERE date LIKE '____-__-__'").fetchall():
            if r[0]: months.add(r[0])
        for r in conn.execute("SELECT DISTINCT month FROM bonus_penalties").fetchall():
            if r[0]: months.add(r[0])
        conn.close()
    except: pass
    # 包含当前月及未来2个月（支持提前记录出勤）
    now = datetime.now(EAT)
    for i in range(3):
        y = now.year + (now.month + i - 1) // 12
        m = (now.month + i - 1) % 12 + 1
        months.add(f'{y}-{m:02d}')
    return jsonify(sorted(months, reverse=True))

# ═══════════════════════════════════════════════════════════
#  API: 重新加载
# ═══════════════════════════════════════════════════════════

@app.route('/reload', methods=['POST'])
@admin_required
def reload_source():
    """纯采集模式：从数据库重新加载所有数据"""
    ok, msg = _run_pipeline(month_filter=APP_STATE.get('month'))
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
#  API: 月份切换
# ═══════════════════════════════════════════════════════════

@app.route('/set-month', methods=['POST'])
@editor_required
def set_month():
    """切换月份筛选，始终以当前覆盖重算。纯采集模式下从采集数据构建"""
    data = request.get_json()
    month = data.get('month', '')

    ok, msg = _run_pipeline(month_filter=month if month != 'all' else None)
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
    overrides = load_overrides(app.config['DATA_FOLDER'], month=month)
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
    APP_STATE['salary_result'] = result

    return jsonify({'ok': True, 'message': msg, 'salary': result, 'headless': APP_STATE.get('headless', False)})

# ═══════════════════════════════════════════════════════════
#  API: 员工管理 (旧端点 - deprecated, 已迁移到 /api/employees)
# ═══════════════════════════════════════════════════════════

@app.route('/employees', methods=['GET'])
@login_required
def get_employees():
    """[DEPRECATED] 旧版员工列表 — 已迁移到 /api/employees"""
    from core.exceptions import load_overrides
    from core.database import load_bonus_penalties as _load_bp_emp
    import copy as _copy
    month = request.args.get('month') or APP_STATE.get('month')
    overrides = load_overrides(app.config['DATA_FOLDER'], month=month)
    bonus_penalties = _load_bp_emp(app.config['DATA_FOLDER'], month) if month else {}
    # 深拷贝副本再附加展示字段，绝不原地篡改 APP_STATE 缓存
    # （原实现直接改 emp，污染 override_type/day_rate/monthly_salary 导致后续计薪错误）
    employees_copy = _copy.deepcopy(APP_STATE.get('employees', []))
    for emp in employees_copy:
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
        # 清零不匹配最终类型的基数（P14.4: 井下工人保留 monthly_salary，供 scoring 模式使用）
        ot = emp.get('override_type')
        if emp.get('default_type') == 'piece_underground':
            pass
        elif ot == 'day_rate':
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
    return jsonify({'employees': employees_copy, 'headless': APP_STATE.get('headless', False)})

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
        # 后端兜底：永久覆盖（无日期区间）自动注入 effective_from
        if not data.get('effective_from') and not data.get('start_date') and not data.get('end_date'):
            data['effective_from'] = APP_STATE.get('month', '')
        _save(app.config['DATA_FOLDER'], data)
        # P23 R4: 全量重建缓存（override_type 推导 + 互斥清零集中在 _run_pipeline，
        # 不再在端点内手动同步，避免副本漂移）
        _refresh_employees_cache()
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
    _refresh_employees_cache()  # P23 R4: 删除永久覆盖后 override_type 需重推导
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
    _refresh_employees_cache()  # P23 R4
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
    _refresh_employees_cache()  # P23 R4
    _audit('remove_override_by_id', str(oid))
    return jsonify({'ok': True})

@app.route('/api/employees/<employee_id>/temp-overrides', methods=['GET'])
@login_required
@require_permission('employees', 'view')
def api_employee_temp_overrides(employee_id):
    """P14.6: 返回该员工的所有临时例外（有日期区间的覆盖记录）"""
    from core.database import get_conn
    conn = get_conn(app.config['DATA_FOLDER'])
    rows = conn.execute(
        "SELECT id, salary_type, day_rate, monthly_salary, start_date, end_date, note "
        "FROM overrides WHERE employee_id=? AND (start_date!='' OR end_date!='') "
        "AND (type IS NULL OR type != 'exclusion') ORDER BY start_date",
        (employee_id,)).fetchall()
    conn.close()
    return jsonify({'overrides': [dict(r) for r in rows]})

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
@login_required
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
    # P23 R4: 恢复员工重新进缓存（补 dismiss 过滤的对称逻辑），并重算薪资
    ok, msg = _refresh_employees_cache() or (None, None)
    return jsonify({'ok': True, 'message': msg})


# ═══════════════════════════════════════════════════════════
#  P1: 种子导入 — 将现有员工初始化到新模型
# ═══════════════════════════════════════════════════════════

@app.route('/api/seed/employees', methods=['POST'])
@editor_required
def seed_employees():
    """从 APP_STATE + 旧 employees 表导入在职员工到新扩展列 + hire 事件"""
    import json as _json
    from core.database import get_conn, log_audit
    conn = get_conn(app.config['DATA_FOLDER'])
    count = 0
    # 来源1: APP_STATE 中的员工（来自 Excel 解析，136 人）
    for emp in APP_STATE.get('employees', []):
        eid = emp.get('id', '')
        name = emp.get('name', '')
        dept = emp.get('department', '')
        if not eid:
            continue
        # 跳过已离职
        dismissed = conn.execute(
            "SELECT 1 FROM dismissed_employees WHERE employee_id=?", (eid,)).fetchone()
        if dismissed:
            continue
        # 确保 employees 表中有记录
        conn.execute("""
            INSERT OR REPLACE INTO employees (id, name, department, status, hire_date, phone)
            VALUES (?,?,?,'active',COALESCE((SELECT hire_date FROM employees WHERE id=?),'2024-01-01'),?)
        """, (eid, name, dept, eid, emp.get('phone', '')))
        # 补 hire 事件
        existing = conn.execute(
            "SELECT 1 FROM employee_events WHERE employee_id=? AND event_type='hire'", (eid,)).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO employee_events (employee_id, event_type, effective_date,
                    payload, operator_id, status)
                VALUES (?, 'hire', COALESCE((SELECT hire_date FROM employees WHERE id=?), '2024-01-01'),
                    ?, 'system', 'approved')
            """, (eid, eid, _json.dumps({'name': name, 'department': dept})))
            count += 1
    conn.commit()
    conn.close()
    log_audit(app.config['DATA_FOLDER'], 'seed_employees', 'system',
              _json.dumps({'total': len(APP_STATE.get('employees', [])), 'imported': count}))
    return jsonify({'ok': True, 'imported': count,
                    'total': len(APP_STATE.get('employees', [])),
                    'message': f'已导入 {count} 名员工的入职事件'})


# ═══════════════════════════════════════════════════════════
#  P1 API: 员工档案
# ═══════════════════════════════════════════════════════════

@app.route('/api/employees', methods=['GET'])
@login_required
@require_permission('employees', 'view')
def api_employees():
    """员工列表（扩展版，含新字段 + overrides + bonus/penalties）"""
    from core.database import list_employees_extended, load_bonus_penalties as _load_bp
    from core.exceptions import load_overrides as _load_ov
    month = request.args.get('month') or APP_STATE.get('month')
    status = request.args.get('status', 'active')
    dept = request.args.get('department')
    employees = list_employees_extended(app.config['DATA_FOLDER'],
                                        status_filter=status, department=dept)
    # P5-c: 补 overrides + bonus_penalties（与旧 /employees 端点对齐）
    bonus_penalties = _load_bp(app.config['DATA_FOLDER'], month) if month else {}
    overrides_data = _load_ov(app.config['DATA_FOLDER'], month=month) if month else {}
    for emp in employees:
        eid = emp['id']
        emp['overrides'] = overrides_data.get(eid, [])
        bp = bonus_penalties.get(eid, {})
        emp['bonus'] = bp.get('bonus', 0)
        emp['penalty'] = bp.get('penalty', 0)
    return jsonify({'employees': employees})

@app.route('/api/employees/<employee_id>', methods=['GET'])
@login_required
@require_permission('employees', 'view')
def api_employee_profile(employee_id):
    """员工档案详情"""
    from core.database import get_employee_profile, load_overrides
    profile = get_employee_profile(app.config['DATA_FOLDER'], employee_id)
    if not profile:
        return jsonify({'error': '员工不存在'}), 404
    # R1b: 合并覆盖基数（对齐计算侧 _run_pipeline 逻辑：永久覆盖 > 默认）
    # employees.day_rate/monthly_salary 可能为 0（真实基数在 overrides 表），
    # 档案页需展示计算侧实际生效的类型与基数，否则"日薪 · 0 TZS/天"。
    month = APP_STATE.get('month') or ''
    db_ovs = load_overrides(app.config['DATA_FOLDER'], month=month)
    ev_ovs = _derive_overrides_from_events(app.config['DATA_FOLDER'], month) if month else {}
    all_ovs = (ev_ovs.get(employee_id, []) or []) + (db_ovs.get(employee_id, []) or [])
    override_type = profile.get('override_type') or None
    day_rate = profile.get('day_rate') or 0
    monthly_salary = profile.get('monthly_salary') or 0
    for o in all_ovs:
        st = o.get('salary_type', '')
        has_range = bool(o.get('start_date') or o.get('end_date'))
        # R3b: 仅永久覆盖（无日期区间）更新类型与基础基数；
        # 临时例外由 get_day_rate_for_date 按天读取，不污染档案基础展示
        if not has_range and st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
            override_type = st
        if not has_range:
            if st == 'day_rate' and o.get('day_rate', 0) > 0:
                day_rate = o['day_rate']
            if st == 'monthly' and o.get('monthly_salary', 0) > 0:
                monthly_salary = o['monthly_salary']
    # 清零对齐计算侧（按最终 override_type）
    if override_type == 'day_rate':
        monthly_salary = 0
    elif override_type == 'monthly':
        day_rate = 0
    elif override_type in ('piece_underground', 'piece_driller', 'piece_crush'):
        day_rate = 0
        monthly_salary = 0
    profile['override_type'] = override_type
    profile['day_rate'] = day_rate
    profile['monthly_salary'] = monthly_salary
    return jsonify({'employee': profile})

@app.route('/api/employees/<employee_id>/events', methods=['GET'])
@login_required
@require_permission('employees', 'view')
def api_employee_events(employee_id):
    """员工生命周期时间线"""
    from core.database import get_employee_events
    events = get_employee_events(app.config['DATA_FOLDER'], employee_id)
    return jsonify({'events': events})

@app.route('/api/employees/<employee_id>/annual-leave-override', methods=['POST'])
@editor_required
@require_permission('oa', 'approve')
def api_employee_annual_leave_override(employee_id):
    """P20: 切换员工年假资格豁免（仅 OA 审批人）——开启后跳过 NSSF + NIDA 检查"""
    from core.database import get_conn, log_audit
    data = request.get_json() or {}
    v = data.get('override')
    if v in (True, 'true', '1', 1):
        new_val = 1
    elif v in (False, 'false', '0', 0):
        new_val = 0
    else:
        return jsonify({'ok': False, 'error': 'override 必须是 0 或 1'}), 400
    conn = get_conn(app.config['DATA_FOLDER'])
    row = conn.execute("SELECT annual_leave_override FROM employees WHERE id=?",
                       (employee_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'ok': False, 'error': '员工不存在'}), 404
    conn.execute("UPDATE employees SET annual_leave_override=? WHERE id=?",
                 (new_val, employee_id))
    conn.commit()
    conn.close()
    _sync_employee_cache(employee_id, {'annual_leave_override': new_val})  # P23 R4 轻量同步
    log_audit(app.config['DATA_FOLDER'], 'annual_leave_override_toggle',
              employee_id, json.dumps({'override': new_val,
                  'operator': session.get('username', '')}))
    return jsonify({'ok': True, 'override': new_val})

@app.route('/api/employees/<employee_id>', methods=['POST'])
@editor_required
def api_employee_update(employee_id):
    """编辑员工基本信息（P21 M5/R6: 支持改名，旧名自动入 alias 并重建索引）"""
    from core.database import update_employee_fields, log_audit, get_conn
    data = request.get_json() or {}
    # 部门仅超级管理员可直改；非超管改不同部门值 → 拒绝（须走 OA 调岗审批）
    if 'department' in data and session.get('role') != 'super_admin':
        conn = get_conn(app.config['DATA_FOLDER'])
        row = conn.execute("SELECT department FROM employees WHERE id=?", (employee_id,)).fetchone()
        conn.close()
        if row and (row['department'] or '') != (data.get('department') or ''):
            return jsonify({'ok': False, 'error': '部门仅超级管理员可修改，或通过OA调岗审批'}), 403
    # P21 M5/R6: 改名联动——旧名合并进 alias（逗号分隔去重，跳过空），保证旧名反查/搜索仍命中
    renamed = False
    if 'name' in data:
        conn = get_conn(app.config['DATA_FOLDER'])
        row = conn.execute("SELECT name, alias FROM employees WHERE id=?", (employee_id,)).fetchone()
        conn.close()
        if row:
            old_name = (row['name'] or '').strip()
            new_name = (data.get('name') or '').strip()
            if new_name and old_name and old_name != new_name:
                alias_set = []
                if row['alias']:
                    alias_set = [a.strip() for a in str(row['alias']).split(',') if a.strip()]
                if old_name not in alias_set:
                    alias_set.append(old_name)
                data['alias'] = ', '.join(alias_set)
                renamed = True
    ok = update_employee_fields(app.config['DATA_FOLDER'], employee_id, data)
    if ok:
        if renamed or 'alias' in data:
            _build_db_ab_index(app.config['DATA_FOLDER'])  # 改名/别名即时生效（采集/出勤反查）
        log_audit(app.config['DATA_FOLDER'], 'employee_update', employee_id,
                  json.dumps(data))
    _refresh_employees_cache()  # P23 R4: 基本字段/月薪基数变更后全量重建
    return jsonify({'ok': ok})

@app.route('/api/employees/<employee_id>/salary-type', methods=['POST'])
@editor_required
def api_employee_salary_type(employee_id):
    """P7: 修改员工薪资类别+基数 — 同步 employees 主档 + 写 salary_change 事件"""
    from core.database import update_employee_salary_type, create_event, log_audit
    from datetime import datetime
    data = request.get_json() or {}
    st = data.get('salary_type', '')
    if st not in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
        return jsonify({'ok': False, 'error': '无效的薪资类别'}), 400
    # 基数必须为数字，否则 400（避免 int() 抛 ValueError → 500）
    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    day_rate = _to_int(data.get('day_rate', 0))
    monthly_salary = _to_int(data.get('monthly_salary', 0))
    if day_rate is None or monthly_salary is None:
        return jsonify({'ok': False, 'error': '薪资基数必须是数字'}), 400
    ok = update_employee_salary_type(app.config['DATA_FOLDER'], employee_id,
                                     st, day_rate, monthly_salary)
    if not ok:
        return jsonify({'ok': False, 'error': '员工不存在'}), 404
    # 写 salary_change 事件（approved，本月 1 号生效）→ 时间线记录 + 下月起覆盖推导
    username = session.get('username', 'unknown')
    create_event(app.config['DATA_FOLDER'], {
        'employee_id': employee_id,
        'event_type': 'salary_change',
        'effective_date': datetime.now(EAT).strftime('%Y-%m-01'),
        'snapshot': '{}',
        'payload': json.dumps({'salary_type': st, 'day_rate': day_rate,
                               'monthly_salary': monthly_salary},
                              ensure_ascii=False),
        'operator_id': username,
        'status': 'approved',
    })
    log_audit(app.config['DATA_FOLDER'], 'employee_salary_type', employee_id,
              json.dumps({'salary_type': st, 'day_rate': day_rate,
                          'monthly_salary': monthly_salary}))
    _refresh_employees_cache()  # P23 R4: 核心修复点——薪资类型/基数变更后立即重算
    return jsonify({'ok': True})

# ── P7: 员工头像 ─────────────────────────────
ALLOWED_AVATAR_EXTS = ('.png', '.jpg', '.jpeg')

@app.route('/api/employees/avatar', methods=['POST'])
@admin_required
def api_employee_avatar_upload():
    """P7: 上传员工头像 → static/avatars/<employee_id>.<ext>（PNG/JPG ≤2MB）"""
    from core.database import update_employee_fields, log_audit
    eid = request.form.get('employee_id', '').strip()
    file = request.files.get('file')
    if not eid or not file or not file.filename:
        return jsonify({'ok': False, 'error': '缺少员工ID或文件'}), 400
    # 路径穿越防护：eid 仅允许字母数字/下划线/连字符
    if not re.fullmatch(r'[A-Za-z0-9_\-]+', eid):
        return jsonify({'ok': False, 'error': '无效的员工ID'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_AVATAR_EXTS:
        return jsonify({'ok': False, 'error': '仅支持 PNG/JPG 图片'}), 400
    # 大小校验（≤2MB）
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({'ok': False, 'error': '图片超过 2MB 限制'}), 400
    # 内容魔数校验（PNG / JPEG）
    head = file.read(8)
    file.seek(0)
    is_png = head[:8] == b'\x89PNG\r\n\x1a\n'
    is_jpg = head[:3] == b'\xff\xd8\xff'
    if not (is_png or is_jpg):
        return jsonify({'ok': False, 'error': '文件内容不是有效的 PNG/JPG 图片'}), 400
    avatar_dir = os.path.join(BASE_DIR, 'static', 'avatars')
    os.makedirs(avatar_dir, exist_ok=True)
    if not os.path.exists(os.path.join(avatar_dir, '.gitkeep')):
        open(os.path.join(avatar_dir, '.gitkeep'), 'w').close()
    # 删除同 id 的旧头像（可能是不同扩展名）
    for old in os.listdir(avatar_dir):
        if old.startswith(eid + '.'):
            os.remove(os.path.join(avatar_dir, old))
    new_name = f'{eid}{ext}'
    file.save(os.path.join(avatar_dir, new_name))
    avatar_path = f'static/avatars/{new_name}'
    update_employee_fields(app.config['DATA_FOLDER'], eid, {'avatar_path': avatar_path})
    _sync_employee_cache(eid, {'avatar_path': avatar_path})  # P23 R4 纯展示字段轻量同步
    log_audit(app.config['DATA_FOLDER'], 'employee_avatar', eid,
              json.dumps({'avatar_path': avatar_path}))
    return jsonify({'ok': True, 'avatar_path': avatar_path})

@app.route('/api/employees/avatar/delete', methods=['POST'])
@admin_required
def api_employee_avatar_delete():
    """P7: 删除员工头像（删文件 + 清空 avatar_path）"""
    from core.database import update_employee_fields, log_audit
    data = request.get_json() or {}
    eid = data.get('employee_id', '')
    if not re.fullmatch(r'[A-Za-z0-9_\-]+', eid):
        return jsonify({'ok': False, 'error': '无效的员工ID'}), 400
    # 读取当前 avatar_path 删除文件
    from core.database import get_employee_profile
    profile = get_employee_profile(app.config['DATA_FOLDER'], eid)
    if profile and profile.get('avatar_path'):
        rel = profile['avatar_path']
        if rel.startswith('static/avatars/'):
            fpath = os.path.join(BASE_DIR, rel.replace('/', os.sep))
            if os.path.exists(fpath):
                os.remove(fpath)
    update_employee_fields(app.config['DATA_FOLDER'], eid, {'avatar_path': ''})
    _sync_employee_cache(eid, {'avatar_path': ''})  # P23 R4 纯展示字段轻量同步
    log_audit(app.config['DATA_FOLDER'], 'employee_avatar_delete', eid,
              json.dumps({'avatar_path': ''}))
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
#  P1 API: OA 审批
# ═══════════════════════════════════════════════════════════

@app.route('/api/oa/events', methods=['POST'])
@editor_required
def oa_create_event():
    """发起 OA 事件（入职/调岗/离职/薪资变更等）"""
    from core.database import create_event, log_audit
    data = request.get_json()
    if not data or not data.get('event_type'):
        return jsonify({'ok': False, 'error': '缺少必填字段'}), 400
    # P8: 入职申请无 employee_id 时，用姓名经 namematch 生成
    if not data.get('employee_id') and data.get('event_type') == 'hire':
        from core.namematch import make_employee_id
        name = (data.get('payload') or {}).get('name', '') or ''
        data['employee_id'] = make_employee_id(name) or name
        if not data['employee_id']:
            return jsonify({'ok': False, 'error': '无法生成员工ID（请检查姓名）'}), 400
    if not data.get('employee_id'):
        return jsonify({'ok': False, 'error': '缺少必填字段'}), 400
    data['operator_id'] = session.get('username', 'unknown')
    # P23 R2: 加班事件校验——必填 date/start_time/end_time，起止时间后端重算合法
    if data.get('event_type') == 'overtime':
        from core.database import _calc_overtime_hours
        _pl = data.get('payload') or {}
        if not (_pl.get('date') and _pl.get('start_time') and _pl.get('end_time')):
            return jsonify({'ok': False, 'error': '加班申请缺少日期或起止时间'}), 400
        _h = _calc_overtime_hours(_pl.get('start_time'), _pl.get('end_time'))
        if _h <= 0:
            return jsonify({'ok': False, 'error': '加班起止时间无效或超出 12 小时上限'}), 400
        # 以后端计算为准（防前端伪造），同时保证 hours>0
        _pl['hours'] = _h
        data['payload'] = _pl
    # P13: 按事件类型取指定审批人写入（未设定为 ''）
    from core.database import get_approver_for_event
    data['approver'] = get_approver_for_event(app.config['DATA_FOLDER'], data.get('event_type', ''))
    # payload / snapshot 是 dict，需要序列化为 JSON 字符串
    data['payload'] = json.dumps(data.get('payload', {}), ensure_ascii=False)
    data['snapshot'] = json.dumps(data.get('snapshot', {}), ensure_ascii=False)
    event_id = create_event(app.config['DATA_FOLDER'], data)
    log_audit(app.config['DATA_FOLDER'], 'oa_create_event',
              data['employee_id'], json.dumps(data))
    return jsonify({'ok': True, 'event_id': event_id})

@app.route('/api/oa/pending', methods=['GET'])
@login_required
@require_permission('oa', 'view')
def oa_pending():
    """待审批事件列表（P13: 按当前用户为审批人过滤，super_admin 全可见）"""
    from core.database import get_pending_events
    events = get_pending_events(
        app.config['DATA_FOLDER'],
        approver=session.get('username', ''),
        is_super_admin=(session.get('role') == 'super_admin'))
    return jsonify({'events': events})

@app.route('/api/oa/pending/count', methods=['GET'])
@login_required
@require_permission('oa', 'view')
def oa_pending_count():
    """待审批数量（P13: 与列表同一过滤规则）"""
    from core.database import get_pending_events
    events = get_pending_events(
        app.config['DATA_FOLDER'],
        approver=session.get('username', ''),
        is_super_admin=(session.get('role') == 'super_admin'))
    return jsonify({'count': len(events)})

@app.route('/api/oa/history', methods=['GET'])
@login_required
@require_permission('oa', 'view')
def oa_history():
    """P8: 已处理事件列表（approved/rejected）；P22 R2: 支持 ?type= 按事件类型筛选"""
    from core.database import get_processed_events
    ev_type = (request.args.get('type') or '').strip() or None
    events = get_processed_events(app.config['DATA_FOLDER'], event_type=ev_type)
    return jsonify({'events': events})

@app.route('/api/oa/events/<int:event_id>/approve', methods=['POST'])
@editor_required
@require_permission('oa', 'approve')
def oa_approve_event(event_id):
    """批准 OA 事件"""
    from core.database import approve_event, get_event, log_audit, apply_approved_event
    username = session.get('username', '')
    event = get_event(app.config['DATA_FOLDER'], event_id)
    if not event:
        return jsonify({'ok': False, 'error': '事件不存在'}), 404
    # P13: 自审限制——super_admin 例外，可批准自己提交的事件
    if event['operator_id'] == username and session.get('role') != 'super_admin':
        return jsonify({'ok': False, 'error': '不能批准自己提交的事件'}), 400
    # 并发安全：先用 approve_event 原子抢占（pending→approved，WHERE status='pending'），
    # 抢到的请求才执行副作用；失败回滚状态。防同一事件并发双审批/双扣。
    ok = approve_event(app.config['DATA_FOLDER'], event_id, username)
    if not ok:
        return jsonify({'ok': False, 'error': '事件状态已变化，请刷新后重试'}), 409
    try:
        apply_approved_event(app.config['DATA_FOLDER'], event)
    except Exception as e:
        from core.database import unapprove_event
        unapprove_event(app.config['DATA_FOLDER'], event_id)
        log_audit(app.config['DATA_FOLDER'], 'oa_apply_failed', event['employee_id'],
                  json.dumps({'event_id': event_id, 'event_type': event['event_type'],
                              'error': str(e)}))
        return jsonify({'ok': False, 'error': f'批准失败: {str(e)}'}), 400
    log_audit(app.config['DATA_FOLDER'], 'oa_approve',
              event['employee_id'], json.dumps({'event_id': event_id}))
    _refresh_employees_cache()  # P23 R2/R4: 批准（加班落库/入职/调岗）后薪资缓存即时生效
    return jsonify({'ok': True})

@app.route('/api/oa/events/<int:event_id>/reject', methods=['POST'])
@editor_required
@require_permission('oa', 'approve')
def oa_reject_event(event_id):
    """驳回 OA 事件"""
    from core.database import reject_event, get_event, log_audit
    data = request.get_json()
    reason = (data or {}).get('reject_reason', '')
    if not reason:
        return jsonify({'ok': False, 'error': '驳回原因不能为空'}), 400
    username = session.get('username', '')
    ok = reject_event(app.config['DATA_FOLDER'], event_id, username, reason)
    if ok:
        event = get_event(app.config['DATA_FOLDER'], event_id)
        if event:
            log_audit(app.config['DATA_FOLDER'], 'oa_reject',
                      event['employee_id'], json.dumps({'event_id': event_id, 'reason': reason}))
    return jsonify({'ok': ok})

@app.route('/api/oa/events/<int:event_id>', methods=['GET'])
@login_required
@require_permission('oa', 'view')
def oa_event_detail(event_id):
    """P21 M4: 单个事件详情（前端编辑/撤销预填用）"""
    from core.database import get_event
    ev = get_event(app.config['DATA_FOLDER'], event_id)
    if not ev:
        return jsonify({'error': '事件不存在'}), 404
    return jsonify({'event': ev})

@app.route('/api/oa/events/<int:event_id>/revoke', methods=['POST'])
@editor_required
def oa_revoke_event(event_id):
    """P21 M4: 撤销事件（已批需 oa:approve 权限；待审仅申请人本人或 super_admin）"""
    from core.database import get_event, revoke_event, log_audit, check_permission
    username = session.get('username', '')
    event = get_event(app.config['DATA_FOLDER'], event_id)
    if not event:
        return jsonify({'ok': False, 'error': '事件不存在'}), 404
    if event['status'] not in ('approved', 'pending'):
        return jsonify({'ok': False, 'error': '该事件状态不可撤销'}), 400
    # 权限分支
    if event['status'] == 'approved':
        if not check_permission(app.config['DATA_FOLDER'], username, 'oa', 'approve'):
            return jsonify({'ok': False, 'error': '无权撤销已批事件（需 OA 审批权限）'}), 403
    else:
        if event['operator_id'] != username and session.get('role') != 'super_admin':
            return jsonify({'ok': False, 'error': '只能撤销自己提交的待审事件'}), 403
    ok = revoke_event(app.config['DATA_FOLDER'], event_id, username)
    if not ok:
        return jsonify({'ok': False, 'error': '撤销失败（事件可能已处理）'}), 400
    log_audit(app.config['DATA_FOLDER'], 'oa_revoke', event['employee_id'],
              json.dumps({'event_id': event_id, 'event_type': event['event_type']}))
    _refresh_employees_cache()  # P23 R2: 撤销加班/请假后薪资缓存即时回退
    return jsonify({'ok': True})

@app.route('/api/oa/events/<int:event_id>/edit', methods=['POST'])
@editor_required
def oa_edit_event(event_id):
    """P21 M4: 修改请假事件
    - 待审: update_pending_event（payload.days + effective_date）
    - 已批: 仅限同月修改（edit_approved_leave_event 事务内撤销重建），跨月 400
    """
    from core.database import (get_event, update_pending_event, log_audit, check_permission,
                               edit_approved_leave_event)
    data = request.get_json() or {}
    username = session.get('username', '')
    event = get_event(app.config['DATA_FOLDER'], event_id)
    if not event:
        return jsonify({'ok': False, 'error': '事件不存在'}), 404
    if event['event_type'] not in ('annual_leave', 'comp_leave'):
        return jsonify({'ok': False, 'error': '仅请假事件可修改'}), 400
    # 权限（同 revoke）
    if event['status'] == 'approved':
        if not check_permission(app.config['DATA_FOLDER'], username, 'oa', 'approve'):
            return jsonify({'ok': False, 'error': '无权修改已批事件（需 OA 审批权限）'}), 403
    else:
        if event['operator_id'] != username and session.get('role') != 'super_admin':
            return jsonify({'ok': False, 'error': '只能修改自己提交的待审事件'}), 403

    new_date = (data.get('effective_date') or '').strip()
    new_days = data.get('days')
    try:
        new_days = int(new_days) if new_days is not None else None
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': '无效的天数'}), 400
    if not new_date:
        return jsonify({'ok': False, 'error': '缺少生效日期'}), 400
    if new_days is not None and new_days < 1:
        return jsonify({'ok': False, 'error': '天数至少为 1'}), 400

    if event['status'] == 'pending':
        try:
            payload = json.loads(event['payload'] or '{}')
        except Exception:
            payload = {}
        if new_days is not None:
            payload['days'] = new_days
        fields = {'effective_date': new_date, 'payload': json.dumps(payload, ensure_ascii=False)}
        ok = update_pending_event(app.config['DATA_FOLDER'], event_id, fields)
        if not ok:
            return jsonify({'ok': False, 'error': '修改失败（事件可能已处理）'}), 400
        log_audit(app.config['DATA_FOLDER'], 'oa_edit', event['employee_id'],
                  json.dumps({'event_id': event_id, 'status': 'pending', 'new_date': new_date, 'days': new_days}))
        return jsonify({'ok': True})

    # 已批：同月修改（事务内撤销重建）
    if new_days is None:
        try:
            new_days = int(json.loads(event['payload'] or '{}').get('days', 1) or 1)
        except (TypeError, ValueError):
            new_days = 1
    ok, msg = edit_approved_leave_event(app.config['DATA_FOLDER'], event_id, new_date, new_days, username)
    if not ok:
        return jsonify({'ok': False, 'error': str(msg)}), 400
    log_audit(app.config['DATA_FOLDER'], 'oa_edit', event['employee_id'],
              json.dumps({'event_id': event_id, 'status': 'approved', 'new_date': new_date,
                          'days': new_days, 'new_event_id': msg}))
    return jsonify({'ok': True, 'event_id': event_id, 'new_event_id': msg})


# ── P13: 审批人路由（super_admin 后台指定） ─────────────

ALLOWED_APPROVAL_EVENT_TYPES = ('hire', 'transfer', 'dismiss', 'leave', 'overtime')

# ── P21 M7/R5: 年假资格错误双语（后端无 i18n 模块，硬编码两套文案） ──
_LEAVE_ERR_MSG = {
    'zh': {
        'no_nssf': '未参加NSSF',
        'no_nida': 'NIDA证件号为空',
        'no_tin': 'TIN号码为空',
        'no_hire_date': '入职日期为空',
        'invalid_hire_date': '入职日期格式无效',
        'no_employee': '员工不存在',
        'under_1year': '入职不满1年({days}天)',
        'prefix': '年假资格不足: ',
    },
    'en': {
        'no_nssf': 'NSSF not enrolled',
        'no_nida': 'NIDA number is empty',
        'no_tin': 'TIN number is empty',
        'no_hire_date': 'Hire date is empty',
        'invalid_hire_date': 'Invalid hire date format',
        'no_employee': 'Employee not found',
        'under_1year': 'Less than 1 year since hire ({days} days)',
        'prefix': 'Annual leave eligibility failed: ',
    },
}

def _leave_err_msg(codes, reasons, lang):
    """按 reason codes 拼双语错误串（codes 来自 check_annual_leave_eligible）"""
    import re
    lang = 'en' if (lang or '') == 'en' else 'zh'
    d = _LEAVE_ERR_MSG[lang]
    parts = []
    for i, code in enumerate(codes):
        if code == 'under_1year':
            days = '?'
            if reasons and i < len(reasons):
                _m = re.search(r'\((\d+)', str(reasons[i]))
                if _m:
                    days = _m.group(1)
            parts.append(d['under_1year'].format(days=days))
        else:
            parts.append(d.get(code, code))
    return d['prefix'] + ', '.join(parts)

def _require_super_admin():
    """内部校验 super_admin，返回错误响应或 None"""
    if session.get('role') != 'super_admin':
        return jsonify({'ok': False, 'error': 'forbidden', 'need_admin': True}), 403
    return None

@app.route('/api/approval-routes', methods=['GET'])
@admin_required
def api_approval_routes_list():
    """P13: 审批人路由全表"""
    from core.database import get_approval_routes
    routes = get_approval_routes(app.config['DATA_FOLDER'])
    return jsonify({'routes': routes})

@app.route('/api/approval-routes', methods=['POST'])
@admin_required
def api_approval_routes_set():
    """P13: 设置事件类型的指定审批人"""
    _block = _require_super_admin()
    if _block:
        return _block
    from core.database import set_approval_route, get_user_role, log_audit
    data = request.get_json() or {}
    event_type = (data.get('event_type') or '').strip()
    approver = (data.get('approver') or '').strip()
    if event_type not in ALLOWED_APPROVAL_EVENT_TYPES:
        return jsonify({'ok': False, 'error': '无效的事件类型'}), 400
    if not approver or not get_user_role(app.config['DATA_FOLDER'], approver):
        return jsonify({'ok': False, 'error': '审批人不存在'}), 400
    set_approval_route(app.config['DATA_FOLDER'], event_type, approver)
    log_audit(app.config['DATA_FOLDER'], 'approval_route_set', '',
              json.dumps({'event_type': event_type, 'approver': approver}))
    return jsonify({'ok': True})

@app.route('/api/approval-routes/<int:route_id>', methods=['DELETE'])
@admin_required
def api_approval_routes_delete(route_id):
    """P13: 删除审批人路由（清除指定审批人，恢复为所有人可见）"""
    _block = _require_super_admin()
    if _block:
        return _block
    from core.database import delete_approval_route, log_audit
    ok = delete_approval_route(app.config['DATA_FOLDER'], route_id)
    if ok:
        log_audit(app.config['DATA_FOLDER'], 'approval_route_delete', '',
                  json.dumps({'route_id': route_id}))
    return jsonify({'ok': ok})


# ═══════════════════════════════════════════════════════════
#  P2 API: 考勤批量提交 + 请假 + 产量录入
# ═══════════════════════════════════════════════════════════

@app.route('/api/attendance/batch', methods=['POST'])
@editor_required
@require_permission('attendance', 'edit')
def attendance_batch_submit():
    from core.database import save_attendance_override, log_audit, is_driver, add_driver, get_attendance_status
    data = request.get_json()
    if not data or 'date' not in data or 'marks' not in data:
        return jsonify({'ok': False, 'error': '缺少 date 或 marks'}), 400
    date = data['date']
    count = 0
    for m in data['marks']:
        eid = m.get('employee_id', '')
        status = m.get('status', '')
        if not eid or not status:
            continue
        # P21 R2: NU 只读——禁止手动设置或覆盖审批写入的年假状态
        if status == 'NU':
            return jsonify({'ok': False, 'error': f'NU（年假）状态由审批管理，禁止手动修改（{eid}）'}), 403
        if get_attendance_status(app.config['DATA_FOLDER'], eid, date) == 'NU':
            return jsonify({'ok': False, 'error': f'NU（年假）状态由审批管理，禁止手动修改（{eid}）'}), 403
        save_attendance_override(app.config['DATA_FOLDER'], eid, date, status)
        count += 1
        if m.get('is_driver') and not is_driver(app.config['DATA_FOLDER'], eid):
            add_driver(app.config['DATA_FOLDER'], eid)
    log_audit(app.config['DATA_FOLDER'], 'attendance_batch', session.get('username',''),
              json.dumps({'date': date, 'count': count}))
    return jsonify({'ok': True, 'count': count})

@app.route('/api/attendance/roster', methods=['GET'])
@login_required
def attendance_roster():
    dept = request.args.get('department', '')
    from core.database import list_employees_extended
    emps = list_employees_extended(app.config['DATA_FOLDER'], status_filter='active', department=dept)
    return jsonify({'employees': emps})

@app.route('/api/oa/leave', methods=['POST'])
@editor_required
def oa_submit_leave():
    from core.database import create_event, log_audit, check_annual_leave_eligible
    data = request.get_json()
    if not data or 'employee_id' not in data or 'event_type' not in data:
        return jsonify({'ok': False, 'error': '缺少必填字段'}), 400
    event_type = data['event_type']
    eid = data['employee_id']
    if event_type == 'annual_leave':
        # P21 R3/M7: 资格检查返回结构化 codes；错误按请求 lang 双语拼装（保留 error 字符串字段）
        chk = check_annual_leave_eligible(app.config['DATA_FOLDER'], eid)
        if not chk['eligible']:
            lang = (data.get('lang') or 'zh')
            return jsonify({'ok': False,
                            'error': _leave_err_msg(chk.get('codes', []), chk.get('reasons', []), lang),
                            'codes': chk.get('codes', [])}), 403
    # P21 R1: comp_leave 由「提交即生效」改为「创建 pending 事件」，审批通过才扣余额+落 T
    data['operator_id'] = session.get('username', 'unknown')
    data['payload'] = json.dumps({
        'days': data.get('days', 1),
        'note': data.get('note', ''),
        'event_type': event_type,
    }, ensure_ascii=False)
    event_id = create_event(app.config['DATA_FOLDER'], {
        'employee_id': eid,
        'event_type': event_type,
        'effective_date': data['effective_date'],
        'payload': data['payload'],
        'snapshot': '{}',
        'operator_id': data['operator_id'],
    })
    log_audit(app.config['DATA_FOLDER'], 'oa_create_event', eid,
              json.dumps({'event_type': event_type, 'event_id': event_id}))
    return jsonify({'ok': True, 'event_id': event_id})

@app.route('/api/leave/balance/<employee_id>', methods=['GET'])
@login_required
def leave_balance(employee_id):
    import datetime as _dt
    year = request.args.get('year', str(_dt.datetime.now(_dt.timezone(_dt.timedelta(hours=3))).year))
    from core.database import get_leave_balance
    balance = get_leave_balance(app.config['DATA_FOLDER'], employee_id, year)
    return jsonify({'balance': balance})

@app.route('/api/leave/sick', methods=['POST'])
@editor_required
def leave_sick():
    """P8: 病假申请（editor+，免审）— 落档 + 扣病假余额 + 落出勤 P（视为出勤，不参与计件）"""
    from core.database import insert_leave_request, deduct_sick_leave, save_attendance_override, log_audit, get_employee_profile
    from core.pricing import load_config
    from datetime import datetime, timedelta
    data = request.get_json() or {}
    eid = data.get('employee_id', '')
    date = data.get('effective_date', '')
    if not eid or not date:
        return jsonify({'ok': False, 'error': '缺少员工或日期'}), 400
    if not get_employee_profile(app.config['DATA_FOLDER'], eid):
        return jsonify({'ok': False, 'error': '员工不存在'}), 404
    try:
        days = int(data.get('days', 1))
        if days < 1:
            raise ValueError
        d0 = datetime.strptime(date, '%Y-%m-%d')
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': '无效的日期或天数'}), 400
    year = str(d0.year)
    cfg = load_config(app.config['DATA_FOLDER'])
    sick_default = int(cfg.get('sick_leave_days', 14) or 14)
    ok = deduct_sick_leave(app.config['DATA_FOLDER'], eid, year, days, default_entitled=sick_default)
    if not ok:
        return jsonify({'ok': False, 'error': '病假余额不足'}), 403
    insert_leave_request(app.config['DATA_FOLDER'], {
        'employee_id': eid, 'leave_type': 'sick',
        'start_date': date, 'end_date': (d0 + timedelta(days=days - 1)).strftime('%Y-%m-%d'),
        'days': days, 'reason': data.get('note', ''),
        'submitted_by': session.get('username', 'unknown'), 'status': 'approved',
    })
    for i in range(days):
        d = (d0 + timedelta(days=i)).strftime('%Y-%m-%d')
        save_attendance_override(app.config['DATA_FOLDER'], eid, d, 'P')
    log_audit(app.config['DATA_FOLDER'], 'leave_sick', eid,
              json.dumps({'date': date, 'days': days}))
    return jsonify({'ok': True, 'message': '病假已登记（免审），出勤已落 P'})

@app.route('/api/leave/balance/adjust', methods=['POST'])
@admin_required
def leave_balance_adjust():
    """P8: 手动调整员工病假余额（写审计）"""
    from core.database import adjust_leave_balance, log_audit
    import datetime as _dt
    data = request.get_json() or {}
    eid = data.get('employee_id', '')
    year = str(data.get('year', _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=3))).year))
    if not eid:
        return jsonify({'ok': False, 'error': '缺少员工ID'}), 400
    ok = adjust_leave_balance(app.config['DATA_FOLDER'], eid, year,
                              sick_entitled=data.get('sick_entitled'),
                              sick_used=data.get('sick_used'),
                              annual_entitled=data.get('annual_entitled'),
                              annual_used=data.get('annual_used'),
                              comp_entitled=data.get('comp_entitled'),
                              comp_used=data.get('comp_used'))
    if not ok:
        return jsonify({'ok': False, 'error': '无有效调整字段'}), 400
    log_audit(app.config['DATA_FOLDER'], 'leave_balance_adjust', eid,
              json.dumps({'year': year, 'sick_entitled': data.get('sick_entitled'),
                          'sick_used': data.get('sick_used'),
                          'annual_entitled': data.get('annual_entitled'),
                          'annual_used': data.get('annual_used'),
                          'comp_entitled': data.get('comp_entitled'),
                          'comp_used': data.get('comp_used')}))
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  P9 API: 数据采集
# ═══════════════════════════════════════════════════════════

def _collection_payload_names(payload, form_type):
    """把 payload 中的 eid 集合转成姓名（与 Excel 解析 main_data 同构）"""
    from core.database import get_conn
    name_map = {}
    conn = None
    try:
        conn = get_conn(app.config['DATA_FOLDER'])
        for r in conn.execute("SELECT id, name FROM employees").fetchall():
            name_map[r['id']] = r['name']
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    def _names(eids):
        return [name_map.get(e, e) for e in (eids or [])]
    return name_map, _names

def _merge_collection_to_main_data(main_data, form_type, date, payload):
    """P9: 单条采集提交合并进 main_data（Web 采集覆盖 Excel 同日期）"""
    _, _names = _collection_payload_names(payload, form_type)
    if form_type == 'underground':
        day = payload.get('day') or {}
        night = payload.get('night') or {}
        rec = {
            'date': date,
            'day_prod': {'NICKEL（H）': day.get('nh', 0), 'NICKEL（L）': day.get('nl', 0), 'MAWE': day.get('mw', 0)},
            'night_prod': {'NICKEL（H）': night.get('nh', 0), 'NICKEL（L）': night.get('nl', 0), 'MAWE': night.get('mw', 0)},
            'day_emps': _names(day.get('emps')),
            'night_emps': _names(night.get('emps')),
        }
        shift = main_data.setdefault('shift_production', [])
        for i, x in enumerate(shift):
            if x.get('date') == date:
                shift[i] = rec
                return
        shift.append(rec)
    elif form_type == 'driller':
        driller = main_data.setdefault('driller_production', [])
        _, _names2 = _collection_payload_names(payload, form_type)
        for team in (payload.get('teams') or []):
            cap = team.get('captain', '')
            if not cap:
                continue
            cap_name = _names2([cap])[0]
            rec = {
                'date': date,
                'captain': cap_name,
                'slot': 0,
                'nh': team.get('nh', 0), 'nl': team.get('nl', 0), 'mw': team.get('mw', 0),
                'futa': 0, 'waya': 0, 'kibiriti': 0,
                'members': _names2(team.get('members')),
                'slots': [],
                'has_members': bool(team.get('members')),
            }
            for i, x in enumerate(driller):
                if x.get('date') == date and x.get('captain') == cap_name:
                    driller[i] = rec
                    break
            else:
                driller.append(rec)
    elif form_type == 'crush':
        crush = main_data.setdefault('crush_production', [])
        rec = {'date': date, 'bags': payload.get('bags', 0), 'personnel': _names(payload.get('emps'))}
        for i, x in enumerate(crush):
            if x.get('date') == date:
                crush[i] = rec
                return
        crush.append(rec)

def rebuild_main_data_from_collections(main_data):
    """P9: /reload 后从 collection_submissions 最新版本回填 main_data（Web 采集覆盖 Excel 同日期）
    B1: 全量重建语义——先清空产量数组，再从 DB 最新提交重建，杜绝双日期残留"""
    from core.database import get_collection_submissions
    main_data['shift_production'] = []
    main_data['driller_production'] = []
    main_data['crush_production'] = []
    subs = get_collection_submissions(app.config['DATA_FOLDER'])
    for s in subs:
        try:
            payload = json.loads(s.get('payload', '{}'))
        except (TypeError, ValueError):
            continue
        if s.get('form_type') in ('underground', 'driller', 'crush'):
            _merge_collection_to_main_data(main_data, s['form_type'], s['submission_date'], payload)

def _reapply_driver_flags():
    """B1: 全量重建 main_data 后重设井下 driver 标志。
    B1b: 先清除再重设——先清除每个井下提交日期上所有残留 is_driver，
    再对当前 payload.drivers 重设 mark_driver_flag，杜绝编辑移除驾驶勾选后津贴仍被计算"""
    from core.database import get_collection_submissions, mark_driver_flag, clear_driver_flags_for_date
    subs = get_collection_submissions(app.config['DATA_FOLDER'])
    # 第一遍：按井下提交日期清除残留 is_driver（is_driver 只由井下采集驱动，按日期清 0 安全）
    ug_dates = sorted({s.get('submission_date') for s in subs
                       if s.get('form_type') == 'underground' and s.get('submission_date')})
    for _dt in ug_dates:
        clear_driver_flags_for_date(app.config['DATA_FOLDER'], _dt)
    # 第二遍：按当前 payload.drivers 重设
    for s in subs:
        if s.get('form_type') != 'underground':
            continue
        try:
            payload = json.loads(s.get('payload', '{}'))
        except (TypeError, ValueError):
            continue
        drivers = []
        for _shift in ('day', 'night'):
            drivers += (payload.get(_shift) or {}).get('drivers') or []
        for _eid in drivers:
            mark_driver_flag(app.config['DATA_FOLDER'], _eid, s.get('submission_date'))

def _filter_marks_by_department(marks, dept):
    """A5: 出勤收集兜底校验 — 仅保留 department 与提交部门一致的员工（防前端漏过滤）"""
    if not dept:
        return marks or [], 0
    dept_map = {}
    try:
        dept_map = {str(e.get('id')): (e.get('department') or '') for e in (APP_STATE.get('employees') or [])}
    except Exception:
        pass
    if not dept_map:
        from core.database import get_conn
        conn = None
        try:
            conn = get_conn(app.config['DATA_FOLDER'])
            dept_map = {str(r['id']): (r['department'] or '') for r in conn.execute(
                "SELECT id, department FROM employees").fetchall()}
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
    kept, discarded = [], 0
    for m in marks or []:
        eid = str(m.get('employee_id') or '')
        # 仅当能查到员工部门且与提交部门不符才丢弃；未知员工（离职/通讯录外）保守保留
        emp_dept = dept_map.get(eid) if eid else None
        if emp_dept is not None and emp_dept != dept:
            discarded += 1
            continue
        kept.append(m)
    return kept, discarded

@app.route('/api/collection/submit', methods=['POST'])
@editor_required
def collection_submit():
    """P9: 数据采集提交 — 写 collection_submissions + 合并 main_data + 重算"""
    from datetime import datetime
    from core.database import insert_collection_submission, update_collection_submission, \
        get_collection_submissions, save_attendance_override, mark_driver_flag, log_audit
    data = request.get_json() or {}
    form_type = data.get('form_type', '')
    date = data.get('submission_date', '')
    payload = data.get('payload') or {}
    if form_type not in ('underground', 'driller', 'crush', 'attendance'):
        return jsonify({'ok': False, 'error': '无效表单类型'}), 400
    if not date:
        return jsonify({'ok': False, 'error': '缺少日期'}), 400
    if date > datetime.now(EAT).strftime('%Y-%m-%d'):
        return jsonify({'ok': False, 'error': '不能提交未来日期'}), 400
    username = session.get('username', 'unknown')
    dept = (payload.get('department') or '').strip()

    # 出勤收集：写 attendance_overrides（batch 语义），collection 仅作留痕
    discarded = 0
    if form_type == 'attendance':
        marks = payload.get('marks') or []
        # A5: 后端兜底校验 — payload 带 department 时丢弃部门不符员工（防前端漏过滤）
        if dept:
            marks, discarded = _filter_marks_by_department(marks, dept)
            payload['marks'] = marks
        # P21: NU（年假）由审批管理，采集提交不得覆盖——命中即拒绝整批（防部分写入）
        from core.database import get_attendance_status
        for m in marks:
            eid = m.get('employee_id', '')
            if eid and get_attendance_status(app.config['DATA_FOLDER'], eid, date) == 'NU':
                return jsonify({'ok': False,
                                'error': f'NU（年假）状态由审批管理，禁止覆盖（员工 {eid} · {date}）'}), 403
        for m in marks:
            eid = m.get('employee_id', '')
            status = m.get('status', '')
            if not eid or not status:
                continue
            # P12: 只写 status，驾驶标记改由井下采集的 drivers 处理
            save_attendance_override(app.config['DATA_FOLDER'], eid, date, status)

    # upsert collection_submissions by (form_type, date) [attendance 另加 department 维度]
    existing = get_collection_submissions(app.config['DATA_FOLDER'], form_type=form_type)
    if form_type == 'attendance' and dept:
        ex = next((e for e in existing if e['submission_date'] == date
                   and (e.get('department') or '') == dept), None)
    else:
        ex = next((e for e in existing if e['submission_date'] == date), None)
    if ex:
        update_collection_submission(app.config['DATA_FOLDER'], ex['id'], payload, username)
        sid = ex['id']
    else:
        sid = insert_collection_submission(app.config['DATA_FOLDER'], form_type, date, payload, username,
                                           department=dept)

    # 合并 main_data + 重算（仅产量类；出勤已直写 attendance_overrides）
    if form_type in ('underground', 'driller', 'crush') and APP_STATE.get('main_data'):
        # B1: 全量重建（替代增量合并），杜绝编辑改日期后新旧双日期数据残留导致产量重复
        rebuild_main_data_from_collections(APP_STATE['main_data'])
        _reapply_driver_flags()
        _recalc_internal()

    log_audit(app.config['DATA_FOLDER'], 'collection_submit', '',
              json.dumps({'form_type': form_type, 'date': date, 'sid': sid, 'department': dept}))
    result = {'ok': True, 'submission_id': sid}
    if discarded:
        result['discarded'] = discarded
        result['warning'] = '已忽略 %d 名部门不符的员工' % discarded
    return jsonify(result)

@app.route('/api/collection/history', methods=['GET'])
@editor_required
@require_permission('production', 'view')
def collection_history():
    """P9: 采集提交历史（按 form_type/month/date/operator 过滤）
    R5: 非 admin(editor)强制 operator=当前登录用户名（后端安全，只看本人提交）"""
    from core.database import get_collection_submissions
    form_type = request.args.get('form_type')
    month = request.args.get('month') or APP_STATE.get('month')
    date = request.args.get('date')
    operator = request.args.get('operator')
    role = session.get('role', '')
    if role not in ('admin', 'super_admin'):
        operator = session.get('username', '')
    subs = get_collection_submissions(app.config['DATA_FOLDER'], form_type=form_type, month=month,
                                      date=date, operator=operator)
    return jsonify({'submissions': subs})

@app.route('/api/collection/driller-teams', methods=['GET'])
@editor_required
def collection_driller_teams():
    """P9: 钻工队长→组员 eid 映射（聚合 main_data + 采集历史），供成员选择弹层默认勾选"""
    from core.database import get_conn, get_collection_submissions
    md = APP_STATE.get('main_data', {})
    name_to_id = {}
    conn = None
    try:
        conn = get_conn(app.config['DATA_FOLDER'])
        for r in conn.execute("SELECT id, name FROM employees").fetchall():
            name_to_id[r['name']] = r['id']
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    teams = {}
    for d in md.get('driller_production', []):
        cap = d.get('captain', '')
        if not cap:
            continue
        cid = name_to_id.get(cap, cap)
        mids = [name_to_id.get(m, m) for m in (d.get('members') or [])]
        teams.setdefault(cid, [])
        for m in mids:
            if m not in teams[cid]:
                teams[cid].append(m)
    # 采集历史补充（覆盖/新增的队长组员）
    for s in get_collection_submissions(app.config['DATA_FOLDER'], form_type='driller'):
        try:
            payload = json.loads(s.get('payload', '{}'))
        except (TypeError, ValueError):
            continue
        for t in (payload.get('teams') or []):
            cid = t.get('captain', '')
            if not cid:
                continue
            teams.setdefault(cid, [])
            for m in (t.get('members') or []):
                if m not in teams[cid]:
                    teams[cid].append(m)
    return jsonify({'teams': teams})

@app.route('/api/collection/edit/<int:submission_id>', methods=['POST'])
@editor_required
def collection_edit(submission_id):
    """P9: 再编辑采集提交（仅本人或 admin+），版本+1 + 旧版写 history + 重新合并 main_data"""
    from datetime import datetime
    from core.database import get_collection_submission, get_collection_submissions, update_collection_submission, \
        delete_collection_submission, log_audit, delete_attendance_override, save_attendance_override
    username = session.get('username', 'unknown')
    sub = get_collection_submission(app.config['DATA_FOLDER'], submission_id)
    if not sub:
        return jsonify({'ok': False, 'error': '提交不存在'}), 404
    is_admin = (session.get('role') in ('admin', 'super_admin'))
    if sub['operator_id'] != username and not is_admin:
        return jsonify({'ok': False, 'error': '只能编辑本人提交或管理员可改'}), 403
    data = request.get_json() or {}
    payload = data.get('payload') or {}
    form_type = sub['form_type']
    old_date = sub['submission_date']
    new_date = data.get('submission_date') or old_date
    if new_date > datetime.now(EAT).strftime('%Y-%m-%d'):
        return jsonify({'ok': False, 'error': '不能提交未来日期'}), 400

    # P21: NU（年假）由审批管理，编辑出勤收集不得覆盖——在任何 DB 修改之前拦截
    if form_type == 'attendance':
        from core.database import get_attendance_status
        for m in (payload.get('marks') or []):
            eid = m.get('employee_id', '')
            if eid and get_attendance_status(app.config['DATA_FOLDER'], eid, new_date) == 'NU':
                return jsonify({'ok': False,
                                'error': f'NU（年假）状态由审批管理，禁止覆盖（员工 {eid} · {new_date}）'}), 403

    # B1: 日期变更 → 若目标日期已有同 form_type 提交则覆盖合并（更新目标行、删除被编辑旧行），
    #     否则仅更新本行日期。同步更新 submission_date + month 列（payload 内 date 不再作为唯一来源）
    merged_target = None  # B1b: 覆盖合并的目标行（attendance 分支需清理其旧 marks）
    sub_dept = ''
    if form_type == 'attendance':
        try:
            sub_dept = (json.loads(sub['payload'] or '{}').get('department') or '').strip()
        except Exception:
            sub_dept = ''
    if new_date != old_date:
        existing = get_collection_submissions(app.config['DATA_FOLDER'], form_type=form_type)
        if form_type == 'attendance' and sub_dept:
            # 出勤留痕按部门×日期：改日期只与同部门的行合并，避免误并到其他部门行
            ex = next((e for e in existing if e['id'] != submission_id
                       and e['submission_date'] == new_date
                       and (e.get('department') or '') == sub_dept), None)
        else:
            ex = next((e for e in existing if e['id'] != submission_id and e['submission_date'] == new_date), None)
        if ex:
            ok = update_collection_submission(app.config['DATA_FOLDER'], ex['id'], payload, username, date=new_date)
            delete_collection_submission(app.config['DATA_FOLDER'], submission_id)
            submission_id = ex['id']
            merged_target = ex
        else:
            ok = update_collection_submission(app.config['DATA_FOLDER'], submission_id, payload, username, date=new_date)
    else:
        ok = update_collection_submission(app.config['DATA_FOLDER'], submission_id, payload, username)
    if not ok:
        return jsonify({'ok': False, 'error': '更新失败'}), 500
    # 重新合并 + 重算
    if form_type in ('underground', 'driller', 'crush') and APP_STATE.get('main_data'):
        # B1: 全量重建（替代增量合并），杜绝编辑改日期后新旧双日期数据残留导致产量重复
        rebuild_main_data_from_collections(APP_STATE['main_data'])
        _reapply_driver_flags()
        _recalc_internal()
    elif form_type == 'attendance':
        # 出勤收集编辑: 先删旧 marks 覆盖再写新(避免残留),与 submit 语义一致
        # B1: 日期变更时旧日期的 marks 也要清理，新 marks 落到新日期
        # P21: 删除时跳过 NU 天（年假由审批管理，不随采集编辑被清掉）
        from core.database import get_attendance_status as _att_st
        try:
            old_payload = json.loads(sub['payload'] or '{}')
            for m in (old_payload.get('marks') or []):
                if m.get('employee_id') and _att_st(app.config['DATA_FOLDER'], m['employee_id'], old_date) != 'NU':
                    delete_attendance_override(app.config['DATA_FOLDER'], m['employee_id'], old_date)
        except Exception:
            pass
        # B1b: 覆盖合并场景——目标行(new_date)原来的 marks 也要删除，避免残留
        if merged_target:
            try:
                target_payload = json.loads(merged_target['payload'] or '{}')
                for m in (target_payload.get('marks') or []):
                    if m.get('employee_id') and _att_st(app.config['DATA_FOLDER'], m['employee_id'], new_date) != 'NU':
                        delete_attendance_override(app.config['DATA_FOLDER'], m['employee_id'], new_date)
            except Exception:
                pass
        for m in (payload.get('marks') or []):
            eid = m.get('employee_id', '')
            status = m.get('status', '')
            if not eid or not status:
                continue
            save_attendance_override(app.config['DATA_FOLDER'], eid, new_date, status)
    log_audit(app.config['DATA_FOLDER'], 'collection_edit', '',
              json.dumps({'submission_id': submission_id, 'form_type': form_type,
                          'date': new_date}))
    return jsonify({'ok': True, 'submission_id': submission_id})

@app.route('/api/production/shift', methods=['POST'])
@editor_required
def production_shift_entry():
    data = request.get_json()
    from core.database import get_conn, log_audit
    conn = get_conn(app.config['DATA_FOLDER'])
    conn.execute(
        "INSERT OR REPLACE INTO shift_additions (employee_id, date, shift) VALUES (?,?,?)",
        (data['employee_id'], data['date'], data.get('shift', 'D')))
    conn.commit()
    conn.close()
    log_audit(app.config['DATA_FOLDER'], 'production_shift', data['employee_id'],
              json.dumps(data))
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
#  P10 API: 评分班组
# ═══════════════════════════════════════════════════════════

@app.route('/api/employee_groups', methods=['GET'])
@login_required
def api_employee_groups_list():
    """P10: 班组列表"""
    from core.database import list_employee_groups
    groups = list_employee_groups(app.config['DATA_FOLDER'])
    return jsonify({'groups': groups})

@app.route('/api/employee_groups', methods=['POST'])
@admin_required
def api_employee_groups_create():
    """P10: 创建班组（admin+）"""
    from core.database import create_employee_group, log_audit
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': '班组名不能为空'}), 400
    gid = create_employee_group(app.config['DATA_FOLDER'], name, data.get('description', ''))
    if not gid:
        return jsonify({'ok': False, 'error': '班组名已存在'}), 400
    log_audit(app.config['DATA_FOLDER'], 'employee_group_create', '',
              json.dumps({'name': name}))
    return jsonify({'ok': True, 'group_id': gid})

@app.route('/api/employee_groups/<int:group_id>', methods=['PUT'])
@admin_required
def api_employee_groups_update(group_id):
    """P10: 改名班组（admin+）"""
    from core.database import update_employee_group, log_audit
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': '班组名不能为空'}), 400
    ok = update_employee_group(app.config['DATA_FOLDER'], group_id, name,
                               data.get('description'))
    if not ok:
        return jsonify({'ok': False, 'error': '班组不存在或名称冲突'}), 400
    log_audit(app.config['DATA_FOLDER'], 'employee_group_update', '',
              json.dumps({'group_id': group_id, 'name': name}))
    return jsonify({'ok': True})

@app.route('/api/employee_groups/<int:group_id>', methods=['DELETE'])
@admin_required
def api_employee_groups_delete(group_id):
    """P10: 删除班组（admin+，解除员工关联）"""
    from core.database import delete_employee_group, log_audit
    delete_employee_group(app.config['DATA_FOLDER'], group_id)
    log_audit(app.config['DATA_FOLDER'], 'employee_group_delete', '',
              json.dumps({'group_id': group_id}))
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
#  P12 API: 钻工队长名单 driller_captains
# ═══════════════════════════════════════════════════════════

@app.route('/api/driller-captains', methods=['GET'])
@login_required
def api_driller_captains_list():
    """P12: 钻工队长名单（钻工采集队长下拉数据源）"""
    from core.database import get_driller_captains
    captains = get_driller_captains(app.config['DATA_FOLDER'])
    return jsonify({'captains': captains})

@app.route('/api/driller-captains', methods=['POST'])
@admin_required
def api_driller_captains_create():
    """P12: 新增钻工队长（admin+）；name 可空则从 employees 查"""
    from core.database import get_conn, add_driller_captain, log_audit
    data = request.get_json() or {}
    eid = (data.get('employee_id') or '').strip()
    if not eid:
        return jsonify({'ok': False, 'error': '缺少员工ID'}), 400
    name = (data.get('name') or '').strip()
    if not name:
        conn = None
        try:
            conn = get_conn(app.config['DATA_FOLDER'])
            r = conn.execute("SELECT name FROM employees WHERE id=?", (eid,)).fetchone()
            name = r['name'] if r else ''
        except Exception:
            name = ''
        finally:
            if conn:
                conn.close()
    if not name:
        return jsonify({'ok': False, 'error': '缺少姓名（员工不存在）'}), 400
    cid = add_driller_captain(app.config['DATA_FOLDER'], eid, name)
    if not cid:
        return jsonify({'ok': False, 'error': '该员工已在钻工队长名单'}), 400
    log_audit(app.config['DATA_FOLDER'], 'driller_captain_create', eid,
              json.dumps({'name': name}))
    return jsonify({'ok': True, 'captain': {'id': cid, 'employee_id': eid, 'name': name}})

@app.route('/api/driller-captains/<int:captain_id>', methods=['PUT'])
@admin_required
def api_driller_captains_update(captain_id):
    """P12: 更新钻工队长（name/sort_order，admin+）"""
    from core.database import update_driller_captain, log_audit
    data = request.get_json() or {}
    ok = update_driller_captain(app.config['DATA_FOLDER'], captain_id,
                                name=data.get('name'), sort_order=data.get('sort_order'))
    if not ok:
        return jsonify({'ok': False, 'error': '队长不存在或无有效字段'}), 400
    log_audit(app.config['DATA_FOLDER'], 'driller_captain_update', '',
              json.dumps({'id': captain_id, **data}))
    return jsonify({'ok': True})

@app.route('/api/driller-captains/<int:captain_id>', methods=['DELETE'])
@admin_required
def api_driller_captains_delete(captain_id):
    """P12: 删除钻工队长（admin+）"""
    from core.database import delete_driller_captain, log_audit
    delete_driller_captain(app.config['DATA_FOLDER'], captain_id)
    log_audit(app.config['DATA_FOLDER'], 'driller_captain_delete', '',
              json.dumps({'id': captain_id}))
    return jsonify({'ok': True})

@app.route('/api/driver-roster', methods=['GET'])
@editor_required
def api_driver_roster():
    """P12: 司机名单 employee_id 列表（井下采集驾驶勾选数据源）"""
    from core.database import list_drivers
    drivers = [d['employee_id'] for d in list_drivers(app.config['DATA_FOLDER'])]
    return jsonify({'drivers': drivers})


# ═══════════════════════════════════════════════════════════
#  P3 API: 评分系统
# ═══════════════════════════════════════════════════════════

@app.route('/api/scoring/card', methods=['POST'])
@editor_required
def scoring_submit_card():
    from core.database import (submit_scoring_card, save_scoring_card_entries,
                               delete_scoring_card_entries, log_audit)
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': '缺少数据'}), 400
    # P14.8: 新格式 rows（一张卡 9 行明细）→ 先删再插，覆盖重录
    if 'rows' in data:
        week = data.get('week')
        team_id = data.get('team_id')
        card_no = data.get('card_no')
        source = data.get('source', '工友')
        month = data.get('month', '') or (APP_STATE.get('month') or '')
        rows = data.get('rows') or []
        if week is None or team_id is None or not card_no:
            return jsonify({'ok': False, 'error': '缺少 week/team_id/card_no'}), 400
        if not rows:
            return jsonify({'ok': False, 'error': '缺少评分行'}), 400
        # P15: 每班驾驶 ≤2 人（匿名原则：一张卡内最多 2 名驾驶员有驾驶维评分；driving<=0 不计）
        driver_count = sum(1 for r in rows if int(r.get('driving') or 0) > 0)
        if driver_count > 2:
            return jsonify({'ok': False, 'error': '每班驾驶最多勾选 2 人'}), 400
        delete_scoring_card_entries(app.config['DATA_FOLDER'], week, team_id, card_no, source, month)
        save_scoring_card_entries(app.config['DATA_FOLDER'], week, team_id, card_no, source, rows, month)
        log_audit(app.config['DATA_FOLDER'], 'scoring_card_entries', session.get('username',''),
                  json.dumps({'week': week, 'team_id': team_id, 'card_no': card_no,
                              'source': source, 'month': month, 'count': len(rows)}))
        return jsonify({'ok': True, 'count': len(rows)})
    # 旧格式 entries（P3 逐行）兼容保留
    if 'entries' not in data:
        return jsonify({'ok': False, 'error': '缺少评分数据'}), 400
    week = data['week']
    team = data['team']
    card_no = data['card_no']
    source = data.get('source', '工友')
    entries = data['entries']
    card_id = submit_scoring_card(app.config['DATA_FOLDER'], week, team, card_no, source, entries)
    log_audit(app.config['DATA_FOLDER'], 'scoring_card', session.get('username',''),
              json.dumps({'card_id': card_id, 'week': week, 'team': team, 'source': source}))
    return jsonify({'ok': True, 'card_id': card_id})

# ── P14.8: 评分原始记录查询/删除（周次/班组/卡号/被评人） ──

@app.route('/api/scoring/entries', methods=['GET'])
@editor_required
@require_permission('scoring', 'view')
def scoring_entries_list():
    """P14.8: 评分原始记录列表（team/week/card/source 组合过滤）"""
    from core.database import get_scoring_card_entries
    team = request.args.get('team', type=int)
    week = request.args.get('week', type=int)
    card = request.args.get('card', '') or None
    source = request.args.get('source', '') or None
    rows = get_scoring_card_entries(app.config['DATA_FOLDER'],
                                    team_id=team, week=week, card_no=card, source=source)
    return jsonify({'ok': True, 'entries': rows, 'count': len(rows)})

@app.route('/api/scoring/card', methods=['GET'])
@editor_required
@require_permission('scoring', 'view')
def scoring_card_get():
    """P14.8: 查询单卡全部行（9 行明细）"""
    from core.database import get_scoring_card_entries
    team = request.args.get('team', type=int)
    week = request.args.get('week', type=int)
    card = request.args.get('card', '')
    source = request.args.get('source', '工友')
    if team is None or week is None or not card:
        return jsonify({'ok': False, 'error': '缺少 team/week/card'}), 400
    rows = get_scoring_card_entries(app.config['DATA_FOLDER'],
                                    team_id=team, week=week, card_no=card, source=source)
    return jsonify({'ok': True, 'rows': rows, 'count': len(rows)})

@app.route('/api/scoring/card', methods=['DELETE'])
@editor_required
def scoring_card_delete():
    """P14.8: 删除单卡（重录/废弃）"""
    from core.database import delete_scoring_card_entries, log_audit
    data = request.get_json(silent=True) or {}
    week = data.get('week') if data.get('week') is not None else request.args.get('week', type=int)
    team_id = data.get('team_id') if data.get('team_id') is not None else request.args.get('team', type=int)
    card_no = data.get('card_no') or request.args.get('card', '')
    source = data.get('source', request.args.get('source', '工友'))
    if week is None or team_id is None or not card_no:
        return jsonify({'ok': False, 'error': '缺少 week/team_id/card_no'}), 400
    delete_scoring_card_entries(app.config['DATA_FOLDER'], week, team_id, card_no, source,
                                month=data.get('month') or request.args.get('month', ''))
    log_audit(app.config['DATA_FOLDER'], 'scoring_card_delete', '',
              json.dumps({'week': week, 'team_id': team_id, 'card_no': card_no,
                          'source': source, 'month': data.get('month') or request.args.get('month', '')}))
    return jsonify({'ok': True})

# ── P10: 评分录入（班组+月份，一张卡一人） ──

@app.route('/api/scoring/team/<int:team_id>/month/<month>', methods=['GET'])
@editor_required
@require_permission('scoring', 'view')
def scoring_team_month(team_id, month):
    """P10: 班组全员（custom_number 升序，无工号排后）+ 该月已提交评分（按 source 分组，预填回显）"""
    from core.database import get_conn, get_employee_group
    group = get_employee_group(app.config['DATA_FOLDER'], team_id)
    if not group:
        return jsonify({'ok': False, 'error': '班组不存在'}), 404
    conn = get_conn(app.config['DATA_FOLDER'])
    emps = conn.execute("""
        SELECT id, name, custom_number, team_id FROM employees
        WHERE team_id=? AND status='active'
        ORDER BY CASE WHEN custom_number='' OR custom_number IS NULL THEN 1 ELSE 0 END, custom_number
    """, (team_id,)).fetchall()
    rows = conn.execute("""
        SELECT se.*, sc.source FROM scoring_entries se
        JOIN scoring_cards sc ON se.card_id = sc.id
        WHERE sc.team=? AND sc.month=?
    """, (team_id, month)).fetchall()
    conn.close()
    by_source = {}
    for r in rows:
        by_source.setdefault(r['source'], {})[r['target_employee_id']] = {
            'initiative': r['initiative'], 'diligence': r['diligence'],
            'discipline': r['discipline'], 'cooperation': r['cooperation'],
            'safety': r['safety'], 'driving': r['driving'],
        }
    employees = [{'id': e['id'], 'name': e['name'], 'custom_number': e['custom_number'] or ''}
                 for e in emps]
    return jsonify({'group': group, 'employees': employees, 'submitted': by_source})

@app.route('/api/scoring/card/batch', methods=['POST'])
@editor_required
def scoring_card_batch():
    """P10: 批量提交评分卡（team+month+source 先删旧再插新 → 覆盖更新）
    body: {team_id, month, source, cards:[{employee_id, wid, 6 维, driving, note}]}"""
    from core.database import get_conn, log_audit
    data = request.get_json() or {}
    team = data.get('team_id')
    month = data.get('month', '')
    source = data.get('source', '工友')
    cards = data.get('cards') or []
    if not team or not month:
        return jsonify({'ok': False, 'error': '缺少班组或月份'}), 400
    if not cards:
        return jsonify({'ok': False, 'error': '缺少评分数据'}), 400
    username = session.get('username', 'unknown')
    conn = get_conn(app.config['DATA_FOLDER'])
    try:
        # 删除该班组+月份+来源的旧卡（先删 entries 再删卡）
        old = conn.execute(
            "SELECT id FROM scoring_cards WHERE team=? AND month=? AND source=?",
            (team, month, source)).fetchall()
        for oc in old:
            conn.execute("DELETE FROM scoring_entries WHERE card_id=?", (oc['id'],))
        conn.execute("DELETE FROM scoring_cards WHERE team=? AND month=? AND source=?",
                     (team, month, source))
        # 一人一卡：card_no = custom_number 或 employee_id 兜底
        for card in cards:
            eid = card.get('employee_id', '')
            if not eid:
                continue
            wid = card.get('wid', '') or card.get('custom_number', '') or eid
            cur = conn.execute("""
                INSERT OR REPLACE INTO scoring_cards (week, team, card_no, source, month)
                VALUES (0,?,?,?,?)
            """, (team, wid, source, month))
            card_id = cur.lastrowid
            conn.execute("""
                INSERT OR REPLACE INTO scoring_entries (card_id, target_wid, target_employee_id,
                    initiative, diligence, discipline, cooperation, safety, driving)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (card_id, wid, eid,
                  int(card.get('initiative') or 0), int(card.get('diligence') or 0),
                  int(card.get('discipline') or 0), int(card.get('cooperation') or 0),
                  int(card.get('safety') or 0),
                  card.get('driving') if card.get('driving') is not None else None))
        conn.commit()
    finally:
        conn.close()
    log_audit(app.config['DATA_FOLDER'], 'scoring_card_batch', '',
              json.dumps({'team': team, 'month': month, 'source': source,
                          'count': len(cards), 'operator': username}))
    return jsonify({'ok': True, 'count': len(cards)})

@app.route('/api/scoring/week/<int:team>/<int:week>', methods=['GET'])
@login_required
@require_permission('scoring', 'view')
def scoring_week_cards(team, week):
    from core.database import get_week_cards
    cards = get_week_cards(app.config['DATA_FOLDER'], team, week)
    return jsonify({'cards': cards})

@app.route('/api/scoring/summary/<int:team>', methods=['GET'])
@login_required
@require_permission('scoring', 'view')
def scoring_summary(team):
    """P15: 评分汇总（与 _get_scoring_bonus 共用共享函数，含去极值 + 三闸 R7 豁免）
    ?month= 缺省用当前月；响应含 pool 块 + individuals[].bonus"""
    from core.calculator import compute_scoring_pool, compute_team_bonuses
    from core.database import get_scoring_config
    from core.pricing import load_config
    data_folder = app.config['DATA_FOLDER']
    month = request.args.get('month', '') or (APP_STATE.get('month') or '')
    # 产量层：与计薪同源 main_data（month 已过滤）
    pricing = load_config(data_folder)
    main_data = APP_STATE.get('main_data') or {}
    pool = compute_scoring_pool(main_data, pricing)
    # 单班全量（新表优先 + 旧表回退 + 守恒），内部已做分票/去极值/1.5票加权/系数
    tb = compute_team_bonuses(data_folder, team, month, pool)
    result = []
    for eid, ind in tb['individuals'].items():
        row = dict(ind)
        row['employee_id'] = eid
        row['bonus'] = tb['bonuses'].get(eid, 0)
        result.append(row)
    # 三闸 + R7 豁免（全班 final_behavior>=85 且 max(deviation)<10 → 最高档上限失效）
    behaviors = [r['final_behavior'] for r in result]
    deviations = [r['deviation'] for r in result]
    variance_range = max(behaviors) - min(behaviors) if len(behaviors) > 1 else 0
    config = get_scoring_config(data_folder)
    max_tier_count = sum(1 for r in result if r['coefficient'] >= 1.1)
    max_tier_ratio = max_tier_count / max(len(result), 1)
    deviation_threshold = config.get('mgmt_deviation_threshold', 15)
    dev_count = sum(1 for r in result if r['deviation'] > deviation_threshold)
    r7_exempt = bool(result) and all(r['final_behavior'] >= 85 for r in result) and max(deviations) < 10
    gates = {
        'zero_variance_triggered': variance_range <= config.get('zero_variance_threshold', 8) and len(behaviors) > 1,
        'max_tier_triggered': (max_tier_ratio > config.get('max_tier_ratio', 0.3)) and not r7_exempt,
        'mgmt_deviation_triggered': dev_count > 0,
        'variance_range': round(variance_range, 2),
        'max_tier_count': max_tier_count, 'max_tier_ratio': round(max_tier_ratio, 4),
        'deviation_count': dev_count,
        'r7_exempt': r7_exempt,
    }
    pool_block = {
        'nh_count': pool['nh_count'],
        'total_pool': pool['total_pool'],
        'half_pool': pool['half_pool'],
        'monthly_s': tb['monthly_s'],
        'distribution_ratio': tb['distribution_ratio'],
        'actual_pool': tb['actual_pool'],
        'sum_coef': tb['sum_coef'],
        'objective_missing': tb['objective_missing'],
        'conserved': tb['conserved'],
    }
    return jsonify({'individuals': result, 'gates': gates, 'pool': pool_block, 'month': month})

@app.route('/api/objective/entry', methods=['POST'])
@editor_required
def objective_entry():
    from core.database import save_objective_entry, log_audit
    data = request.get_json()
    # 实际出渣量改为手动录入（产量采集无按班组提交来源，不再从产量自动带出）
    data['actual_output'] = float(data.get('actual_output') or 0)
    daily_s = save_objective_entry(app.config['DATA_FOLDER'], data['record_date'],
        data['team'], data['planned_output'], data['actual_output'],
        data['total_hours'], data['effective_hours'], data['week'])
    log_audit(app.config['DATA_FOLDER'], 'objective_entry', session.get('username',''),
              json.dumps(data))
    return jsonify({'ok': True, 'daily_s': daily_s})

@app.route('/api/objective/daily/<int:team>', methods=['GET'])
@login_required
def objective_daily(team):
    from core.database import get_objective_records
    records = get_objective_records(app.config['DATA_FOLDER'], team)
    return jsonify({'records': records})

@app.route('/api/objective/monthly/<int:team>', methods=['GET'])
@login_required
def objective_monthly(team):
    from core.database import get_monthly_objective
    month = request.args.get('month') or APP_STATE.get('month', '')   # P15: 按月过滤
    summary = get_monthly_objective(app.config['DATA_FOLDER'], team, month or None)
    return jsonify(summary)

@app.route('/api/scoring/config', methods=['GET'])
@login_required
@require_permission('scoring', 'view')
def scoring_config_get():
    from core.database import get_scoring_config
    config = get_scoring_config(app.config['DATA_FOLDER'])
    return jsonify(config)

@app.route('/api/scoring/config', methods=['POST'])
@editor_required
def scoring_config_save():
    from core.database import save_scoring_config, log_audit
    data = request.get_json()
    save_scoring_config(app.config['DATA_FOLDER'], data)
    log_audit(app.config['DATA_FOLDER'], 'scoring_config', session.get('username',''), json.dumps(data))
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: NSSF（社保）
# ═══════════════════════════════════════════════════════════

@app.route('/nssf/list', methods=['GET'])
@login_required
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
@login_required
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
@login_required
@require_permission('system', 'view')
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
    result = _recalc_internal()
    if result is None:
        return jsonify({'ok': False, 'error': '请先加载数据'})
    return jsonify({'ok': True, 'result': result})

def _recalc_internal():
    """P9: 内部重算（供 /recalculate 与采集提交复用）；无数据返回 None"""
    if not APP_STATE.get('parsed'):
        return None
    from core.calculator import calculate_all
    from core.exceptions import load_overrides, load_daily_exclusions
    from core.database import load_bonus_penalties as _load_bp3
    month = APP_STATE.get('month')
    overrides = load_overrides(app.config['DATA_FOLDER'], month=month)
    exclusions = load_daily_exclusions(app.config['DATA_FOLDER'])
    bonus_penalties = _load_bp3(app.config['DATA_FOLDER'], month) if month else {}
    result = calculate_all(
        main_data=APP_STATE.get('main_data', {}),
        employees=APP_STATE.get('employees', []),
        overrides=overrides, exclusions=exclusions,
        pricing=APP_STATE.get('config', {}),
        data_folder=app.config['DATA_FOLDER'],
        bonus_penalties=bonus_penalties,
    )
    APP_STATE['calculated'] = True
    APP_STATE['salary_result'] = result
    _audit('recalculate', '', json.dumps({'total_gross': result['total_gross']}))
    return result

@app.route('/salary', methods=['GET'])
@login_required
@require_permission('salary', 'view')
def get_salary():
    month = request.args.get('month')
    if month and APP_STATE.get('main_data') and APP_STATE.get('employees'):
        # 按请求月份临时过滤计算，不修改 APP_STATE
        from core.calculator import calculate_all
        from core.exceptions import load_overrides, load_daily_exclusions
        from core.database import load_bonus_penalties as _load_bp
        import copy
        md = copy.deepcopy(APP_STATE['main_data'])
        for key in ('dates', 'shift_production', 'driller_production', 'attendance', 'crush_production'):
            if md.get(key):
                if key == 'dates':
                    md[key] = [d for d in md[key] if d.startswith(month)]
                else:
                    md[key] = [d for d in md[key] if d.get('date', '').startswith(month)]
        overrides = load_overrides(app.config['DATA_FOLDER'], month=month)
        exclusions = load_daily_exclusions(app.config['DATA_FOLDER'])
        bonus_penalties = _load_bp(app.config['DATA_FOLDER'], month)
        result = calculate_all(md, APP_STATE['employees'], overrides=overrides, exclusions=exclusions,
                               pricing=APP_STATE.get('config', {}), data_folder=app.config['DATA_FOLDER'],
                               bonus_penalties=bonus_penalties)
        if isinstance(result, dict):
            result['month'] = month  # 新算的临时结果，直接挂元数据
        return jsonify({'result': result, 'month': month, 'headless': not bool(md.get('dates'))})
    res = APP_STATE.get('salary_result')
    if isinstance(res, dict):
        res = {**res, 'month': APP_STATE.get('month', '')}  # 浅拷贝，防污染缓存
    return jsonify({'result': res, 'month': APP_STATE.get('month', ''), 'headless': APP_STATE.get('headless', False)})

# ═══════════════════════════════════════════════════════════
#  API: 薪资双路径核对
# ═══════════════════════════════════════════════════════════

@app.route('/salary/verify', methods=['GET'])
@login_required
@require_permission('salary', 'view')
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
@login_required
@require_permission('production', 'view')
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
#  API: 数据台产量仪表盘（P15: 白夜班分离 + 钻工逐日明细 + 破碎）
# ═══════════════════════════════════════════════════════════

@app.route('/api/production/dashboard', methods=['GET'])
@login_required
@require_permission('production', 'view')
def get_production_dashboard():
    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])
    crush_prod = md.get('crush_production', [])

    # ── 井下产量: 白班/夜班/合计 三者分离 ──
    shift_daily = []
    for d in shift_prod:
        dp = d.get('day_prod') or {}
        np = d.get('night_prod') or {}
        shift_daily.append({
            'date': d['date'],
            'day_nh': dp.get('NICKEL（H）', 0) or 0,
            'day_nl': dp.get('NICKEL（L）', 0) or 0,
            'day_mw': dp.get('MAWE', 0) or 0,
            'night_nh': np.get('NICKEL（H）', 0) or 0,
            'night_nl': np.get('NICKEL（L）', 0) or 0,
            'night_mw': np.get('MAWE', 0) or 0,
            'total_nh': (dp.get('NICKEL（H）', 0) or 0) + (np.get('NICKEL（H）', 0) or 0),
            'total_nl': (dp.get('NICKEL（L）', 0) or 0) + (np.get('NICKEL（L）', 0) or 0),
            'total_mw': (dp.get('MAWE', 0) or 0) + (np.get('MAWE', 0) or 0),
        })

    # ── 钻工产量: 逐日明细（非队长汇总） ──
    driller_daily = []
    for d in driller_prod:
        driller_daily.append({
            'date': d['date'],
            'captain': d['captain'],
            'nh': d['nh'],
            'nl': d['nl'],
            'mw': d['mw'],
            'members': d.get('members', []),
        })

    # ── 破碎产量: 逐日 ──
    crush_daily = []
    for c in crush_prod:
        crush_daily.append({
            'date': c['date'],
            'bags': c['bags'],
            'personnel_count': len(c.get('personnel', [])),
        })

    return jsonify({
        'month': md.get('dates', [''])[0][:7] if md.get('dates') else '',
        'shift_production': shift_daily,
        'driller_production': driller_daily,
        'crush_production': crush_daily,
    })


# ═══════════════════════════════════════════════════════════
#  API: 产量核验（逐日对比钻工组与井下合计）
# ═══════════════════════════════════════════════════════════

@app.route('/production-verify', methods=['GET'])
@login_required
@require_permission('production', 'view')
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
@login_required
@require_permission('salary', 'view')
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
@login_required
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
@login_required
@require_permission('attendance', 'view')
def get_attendance():
    """返回出勤网格：每人每天的状态。P=出勤 A=旷工 L=请假"""
    import json as _json
    from collections import defaultdict
    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])
    attendance_data = md.get('attendance', [])
    employees = APP_STATE.get('employees', [])

    # 收集所有日期（含钻工+破碎计件日期）
    all_dates = sorted(set(
        list(set(d['date'] for d in shift_prod)) +
        list(set(d['date'] for d in driller_prod)) +
        list(set(d.get('date', '') for d in attendance_data)) +
        list(set(d.get('date', '') for d in (md.get('crush_production') or []))) +
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

    # 生产薪资：白班=D 夜班=N 全天=B
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
    type_labels = {'piece_crush': '破碎计件','piece_underground':'生产薪资','piece_driller':'钻工计件','day_rate':'日薪','monthly':'月薪','advance_only':'仅预支','address_book':'通讯录'}
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
            'department': emp.get('department', ''),
            'custom_number': emp.get('custom_number', '') or '',
            'days': status_row,
            'origin': origin_row,
            'auto': auto_row,
            'editable': True,  # 所有人都可手动标记 A/L
        })

    return jsonify({'dates': all_dates, 'rows': rows})


@app.route('/attendance/toggle', methods=['POST'])
@editor_required
@require_permission('attendance', 'edit')
def toggle_attendance():
    """手动标��某人某天的状态：P出勤 A旷工 L请假"""
    import json as _json
    data = request.get_json()
    eid = data.get('employee_id')
    date = data.get('date')
    status = data.get('status', 'P')  # 'P', 'A', 'L'

    # P21 R2: NU（年假）状态由审批自动写入，禁止手动设置或修改（只读）
    from core.database import save_attendance_override, get_attendance_status
    if status == 'NU':
        return jsonify({'ok': False, 'error': 'NU（年假）状态由审批管理，禁止手动修改'}), 403
    if get_attendance_status(app.config['DATA_FOLDER'], eid, date) == 'NU':
        return jsonify({'ok': False, 'error': 'NU（年假）状态由审批管理，禁止手动修改'}), 403
    save_attendance_override(app.config['DATA_FOLDER'], eid, date, status)
    _audit('attendance_toggle', eid, json.dumps({'date': date, 'status': status}))
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════
#  API: 审计日志
# ═══════════════════════════════════════════════════════════

@app.route('/audit-log', methods=['GET'])
@admin_required
def get_audit_log():
    from core.database import get_audit_logs
    logs = get_audit_logs(app.config['DATA_FOLDER'])
    return jsonify(logs)


# ═══════════════════════════════════════════════════════════
#  API: 导出 Excel
# ═══════════════════════════════════════════════════════════

@app.route('/export', methods=['POST'])
@login_required
@require_permission('salary', 'export')
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

    headers = ['Name', 'Type', 'Underground Piece Rate(TZS)', 'Driller Piece(TZS)', 'Crush Piece(TZS)',
               'Day Rate(TZS)', 'Monthly(TZS)', 'Gross Total(TZS)',
               'Bonus(TZS)', 'Driver Allowance(TZS)', 'Penalty(TZS)', 'Advance Deduction(TZS)', 'NSSF(TZS)', 'Net Salary(TZS)']
    for col, h in enumerate(headers, 1):
        cell = ws.cell(1, col, h)
        cell.font = header_font; cell.fill = header_fill
        cell.alignment = header_align; cell.border = thin_border

    type_map = {'piece_crush': 'Crush Piece', 'piece_underground': 'Underground Piece Rate', 'piece_driller': 'Driller Piece',
                'day_rate': 'Day Rate', 'monthly': 'Monthly', 'both': 'Unspecified', 'advance_only': 'Advance Only', 'address_book': 'Address Book'}
    total_fill = PatternFill('solid', fgColor='FFF3CD')

    for i, emp in enumerate(result['employees'], 2):
        gross = (emp.get('piece_underground', 0) or 0) + \
                (emp.get('piece_driller', 0) or 0) + \
                (emp.get('piece_crush', 0) or 0) + \
                (emp.get('day_rate', 0) or 0) + (emp.get('monthly', 0) or 0)
        bonus = int(emp.get('bonus', 0) or 0)
        penalty = int(emp.get('penalty', 0) or 0)
        nssf = emp.get('nssf', 0) or 0
        driver = int(emp.get('driver_allowance', 0) or 0)
        net = gross + bonus + driver - (emp.get('advance', 0) or 0) - nssf - penalty
        vals = [
            emp['name'] or '', type_map.get(emp.get('salary_type', ''), emp.get('salary_type', '')),
            int(emp.get('piece_underground', 0) or 0), int(emp.get('piece_driller', 0) or 0),
            int(emp.get('piece_crush', 0) or 0),
            int(emp.get('day_rate', 0) or 0), int(emp.get('monthly', 0) or 0),
            int(gross), bonus, driver, penalty, int(emp.get('advance', 0) or 0), int(nssf), int(net),
        ]
        for col, v in enumerate(vals, 1):
            cell = ws.cell(i, col, v); cell.border = thin_border
            cell.alignment = Alignment(horizontal='left' if col == 1 else 'right')
            if col > 1: cell.number_format = '#,##0'

    total_row = len(result['employees']) + 2
    ws.cell(total_row, 1, 'Total').font = Font(bold=True, size=11)
    ws.cell(total_row, 1).fill = total_fill; ws.cell(total_row, 1).border = thin_border

    # 井下(C), 钻工(D), 破碎(E), 日薪(F), 月薪(G), 应发(H), 奖金(I), 司机(J), 罚款(K), 预支(L), NSSF(M) → SUM公式
    for ci in [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]:
        letter = chr(64 + ci)
        cell = ws.cell(total_row, ci, f'=SUM({letter}2:{letter}{total_row-1})')
        cell.font = Font(bold=True); cell.fill = total_fill; cell.border = thin_border
        cell.number_format = '#,##0'

    # 实发(14=N) = H+I+J-K-L-M  (H=gross, I=bonus, J=driver, K=penalty, L=advance, M=nssf)
    net_formula = f'=H{total_row}+I{total_row}+J{total_row}-K{total_row}-L{total_row}-M{total_row}'
    ws.cell(total_row, 14, net_formula).font = Font(bold=True)
    ws.cell(total_row, 14).fill = total_fill; ws.cell(total_row, 14).border = thin_border
    ws.cell(total_row, 14).number_format = '#,##0'

    for i, w in enumerate([18, 12, 16, 16, 16, 16, 16, 16, 14, 16, 14, 16, 16, 16], 1):
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
@require_permission('employees', 'export')
def export_employees():
    """导出员工信息表（薪资类型、日薪基数、月薪基数、预支）"""
    employees = APP_STATE.get('employees', [])
    if not employees:
        return jsonify({'ok': False, 'error': '无员工数据'})

    from core.exceptions import load_overrides
    overrides = load_overrides(app.config['DATA_FOLDER'], month=APP_STATE.get('month'))

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

    type_map = {'piece_underground':'Underground Piece Rate','piece_driller':'Driller Piece',
                'day_rate':'Day Rate','monthly':'Monthly','both':'Unspecified','advance_only':'Advance Only','address_book':'Address Book'}
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
@require_permission('attendance', 'export')
def export_attendance():
    """导出出勤网格为 Excel，含状态颜色标记"""
    from collections import defaultdict
    from core.namematch import make_employee_id, canonical

    md = APP_STATE.get('main_data', {})
    shift_prod = md.get('shift_production', [])
    driller_prod = md.get('driller_production', [])
    attendance_data = md.get('attendance', [])
    employees = APP_STATE.get('employees', [])

    # ── 收集所有日期（含钻工+破碎计件日期）──
    all_dates = sorted(set(
        list(set(d['date'] for d in shift_prod)) +
        list(set(d['date'] for d in driller_prod)) +
        list(set(d.get('date', '') for d in attendance_data)) +
        list(set(d.get('date', '') for d in (md.get('crush_production') or []))) +
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
    type_labels = {'piece_crush': 'Crush Piece', 'piece_underground': 'Underground Piece Rate', 'piece_driller': 'Driller Piece',
                   'day_rate': 'Day Rate', 'monthly': 'Monthly', 'advance_only': 'Advance Only', 'address_book': 'Address Book'}
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
@require_permission('salary', 'export')
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
    type_map = {'piece_underground':'Underground Piece Rate','piece_driller':'Driller Piece',
                'day_rate':'Day Rate','monthly':'Monthly','both':'Unspecified','advance_only':'Advance Only','address_book':'Address Book'}

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
        overrides = load_overrides(app.config['DATA_FOLDER'], month=APP_STATE.get('month'))
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
        headers2 = ['Name', 'Type', 'Underground Piece Rate(TZS)', 'Driller Piece(TZS)', 'Crush Piece(TZS)',
                    'Day Rate(TZS)', 'Monthly(TZS)', 'Gross Total(TZS)',
                    'Bonus(TZS)', 'Driver Allowance(TZS)', 'Penalty(TZS)', 'Advance Deduction(TZS)', 'NSSF(TZS)', 'Net Salary(TZS)']
        for ci, h in enumerate(headers2, 1):
            c = ws2.cell(1, ci, h); c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb

        _type_map2 = {'piece_crush':'Crush Piece','piece_underground':'Underground Piece Rate','piece_driller':'Driller Piece',
                      'day_rate':'Day Rate','monthly':'Monthly','both':'Unspecified','advance_only':'Advance Only','address_book':'Address Book'}
        for i, emp in enumerate(result['employees'], 2):
            gross = (emp.get('piece_underground',0) or 0) + (emp.get('piece_driller',0) or 0) + \
                    (emp.get('piece_crush',0) or 0) + \
                    (emp.get('day_rate',0) or 0) + (emp.get('monthly',0) or 0)
            bonus = int(emp.get('bonus', 0) or 0)
            penalty = int(emp.get('penalty', 0) or 0)
            nssf = emp.get('nssf',0) or 0
            driver = int(emp.get('driver_allowance', 0) or 0)
            net = gross + bonus + driver - (emp.get('advance',0) or 0) - nssf - penalty
            vals = [
                emp.get('name','') or '', _type_map2.get(emp.get('salary_type',''), emp.get('salary_type','')),
                int(emp.get('piece_underground',0) or 0), int(emp.get('piece_driller',0) or 0),
                int(emp.get('piece_crush',0) or 0),
                int(emp.get('day_rate',0) or 0), int(emp.get('monthly',0) or 0),
                int(gross), bonus, driver, penalty, int(emp.get('advance',0) or 0), int(nssf), int(net),
            ]
            for ci, v in enumerate(vals, 1):
                c = ws2.cell(i, ci, v); c.border = tb
                c.alignment = Alignment(horizontal='left' if ci == 1 else 'right')
                if ci > 1: c.number_format = '#,##0'

        tr = len(result['employees']) + 2
        ws2.cell(tr, 1, 'Total').font = Font(bold=True, size=11)
        ws2.cell(tr, 1).fill = total_fill; ws2.cell(tr, 1).border = tb
        # 井下(C), 钻工(D), 破碎(E), 日薪(F), 月薪(G), 应发(H), 奖金(I), 司机(J), 罚款(K), 预支(L), NSSF(M) → SUM
        for ci in [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]:
            lt = chr(64 + ci)
            c = ws2.cell(tr, ci, f'=SUM({lt}2:{lt}{tr-1})')
            c.font = Font(bold=True); c.fill = total_fill; c.border = tb
            c.number_format = '#,##0'
        # 实发(14=N) = H+I+J-K-L-M  (H=gross, I=bonus, J=driver, K=penalty, L=advance, M=nssf)
        net_f = f'=H{tr}+I{tr}+J{tr}-K{tr}-L{tr}-M{tr}'
        ws2.cell(tr, 14, net_f).font = Font(bold=True)
        ws2.cell(tr, 14).fill = total_fill; ws2.cell(tr, 14).border = tb
        ws2.cell(tr, 14).number_format = '#,##0'
        for i, w in enumerate([18, 12, 16, 16, 16, 16, 16, 16, 14, 16, 14, 16, 16, 16], 1):
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
            list(set(d['date'] for d in driller_prod)) +
            list(set(d.get('date', '') for d in attendance_data)) +
            list(set(d.get('date', '') for d in (md.get('crush_production') or []))) +
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
                day_status[cap_id][dt] = 'R'
            for m in d.get('members', []):
                mid = make_employee_id(m)
                if mid and dt not in day_status.get(mid, {}):
                    day_status[mid][dt] = 'R'
        # 破碎计件出勤
        crush_data = md.get('crush_production', [])
        for d in crush_data:
            dt = d['date']
            for e in d.get('personnel', []):
                eid = make_employee_id(e)
                if eid and dt not in day_status.get(eid, {}):
                    day_status[eid][dt] = 'C'
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
            is_top_dept_monthly = is_monthly and emp.get('department') == 'ENPRIZON LINDI PROJECT'
            row_days = {}
            for dt in all_dates:
                kid = f"{eid}|{dt}"
                if kid in manual:
                    row_days[dt] = manual[kid]
                elif eid in day_status and dt in day_status[eid]:
                    row_days[dt] = day_status[eid][dt]
                elif is_top_dept_monthly:
                    row_days[dt] = 'P'
                else:
                    row_days[dt] = ''
            att_rows.append({
                'name': emp.get('name', ''),
                'type': type_map.get(emp_type, emp_type),
                'dept': emp.get('department', ''),
                'days': row_days,
            })

        if att_rows:
            ws3 = wb.create_sheet('Attendance')
            ws3.cell(1, 1, 'Name').font = hfont; ws3.cell(1, 1).fill = hfill
            ws3.cell(1, 1).alignment = ha; ws3.cell(1, 1).border = tb
            ws3.cell(1, 2, 'Type').font = hfont; ws3.cell(1, 2).fill = hfill
            ws3.cell(1, 2).alignment = ha; ws3.cell(1, 2).border = tb
            ws3.cell(1, 3, 'Department').font = hfont; ws3.cell(1, 3).fill = hfill
            ws3.cell(1, 3).alignment = ha; ws3.cell(1, 3).border = tb
            for di, dt in enumerate(all_dates):
                c = ws3.cell(1, 4 + di, parse_dt(dt))
                c.font = hfont; c.fill = hfill; c.alignment = ha; c.border = tb
                c.number_format = date_fmt

            for ri, row in enumerate(att_rows, 2):
                ws3.cell(ri, 1, row['name']).border = tb
                c_type = ws3.cell(ri, 2, row['type']); c_type.border = tb
                c_type.alignment = Alignment(horizontal='center')
                ws3.cell(ri, 3, row['dept']).border = tb
                for di, dt in enumerate(all_dates):
                    status = row['days'].get(dt, '')
                    c = ws3.cell(ri, 4 + di, status)
                    c.border = tb
                    c.alignment = Alignment(horizontal='center', vertical='center')
                    sf = fill_map.get(status)
                    if sf:
                        c.fill = sf; c.font = white_bold
                    elif status == '':
                        c.fill = grey_fill

            ws3.column_dimensions['A'].width = 22
            ws3.column_dimensions['B'].width = 12
            ws3.column_dimensions['C'].width = 22
            ws3.freeze_panes = 'D2'

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
        # ── 队长名规范化（通过员工账号匹配，避免通讯录别名差异）──
        from core.namematch import make_employee_id as _neid

        def _norm_captain(name):
            """标准化队长名称为统一格式，通过 make_employee_id 匹配"""
            import re as _re
            eid = _neid(name)
            # 已知钻工队长 (账号 → 标准显示名)
            _leader_map = {
                _neid('SHEDRACK PINIEL LAIZER'): 'SHEDRACK PINIEL LAIZER',
                _neid('JOHN BOAY BURA'): 'JOHN BOAY BURA',
                _neid('BARAKA LAIZER'): 'BARAKA LAIZER',
                _neid('JOSEPH DONALD'): 'JOSEPH DONALD',
            }
            if eid and eid in _leader_map:
                return _leader_map[eid]
            # 回退：去空格大写匹配
            key = _re.sub(r'\s+', '', _re.sub(r'\s*\([^)]*\)\s*', '', str(name))).upper()
            return key

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
#  PDF 工资单导出
# ═══════════════════════════════════════════════════════════

def _build_slip_data(emp, salary_result, employees_db, month):
    from core.database import get_employee_profile
    profile = get_employee_profile(app.config['DATA_FOLDER'], emp.get('employee_id', ''))
    
    gross = (emp.get('piece_underground', 0) or 0) + (emp.get('piece_driller', 0) or 0) + \
            (emp.get('piece_crush', 0) or 0) + (emp.get('day_rate', 0) or 0) + (emp.get('monthly', 0) or 0)
    
    type_labels = {
        'piece_underground': 'Underground', 'piece_driller': 'Driller',
        'piece_crush': 'Crush', 'day_rate': 'Day Rate', 'monthly': 'Monthly'
    }
    
    return {
        'employee_id': emp.get('employee_id', ''),
        'name': emp.get('name', ''),
        'department': profile.get('department', '') if profile else '',
        'position': profile.get('position', '') if profile else '',
        'nssf_number': profile.get('nssf_number', '') if profile else '',
        'tin_number': profile.get('tin_number', '') if profile else '',
        'nssf_enrolled': profile.get('nssf_enrolled', False) if profile else False,
        'month': month,
        'salary_type_label': type_labels.get(emp.get('salary_type', ''), emp.get('salary_type', '')),
        'piece_underground': int(emp.get('piece_underground', 0) or 0),
        'piece_driller': int(emp.get('piece_driller', 0) or 0),
        'piece_crush': int(emp.get('piece_crush', 0) or 0),
        'day_rate': int(emp.get('day_rate', 0) or 0),
        'monthly': int(emp.get('monthly', 0) or 0),
        'overtime': int(emp.get('overtime', 0) or 0),
        'bonus': int(emp.get('bonus', 0) or 0),
        'driver_allowance': int(emp.get('driver_allowance', 0) or 0),
        'gross': int(gross),
        'nssf': int(emp.get('nssf', 0) or 0),
        'paye': int(emp.get('paye', 0) or 0),
        'advance': int(emp.get('advance', 0) or 0),
        'penalty': int(emp.get('penalty', 0) or 0),
        'nssf_rate': 0.10,
        'total_deductions': int((emp.get('nssf', 0) or 0) + (emp.get('paye', 0) or 0) + \
                                (emp.get('advance', 0) or 0) + (emp.get('penalty', 0) or 0)),
        'taxable_income': int(gross - (emp.get('nssf', 0) or 0)),
        'net': int(emp.get('net', 0) or 0),
        'attendance_days': 0,
    }


@app.route('/export/payslip/<employee_id>', methods=['GET'])
@login_required
@require_permission('salary', 'export')
def export_payslip_single(employee_id):
    try:
        from weasyprint import HTML
        from flask import render_template
        import io
        
        month = request.args.get('month', APP_STATE.get('month', ''))
        download = request.args.get('download', '0') == '1'
        
        result = APP_STATE.get('salary_result')
        if not result:
            return jsonify({'error': 'No salary data. Please recalculate.', 'ok': False}), 400
        
        emp = None
        for e in result.get('employees', []):
            if str(e.get('employee_id', '')) == str(employee_id):
                emp = e
                break
        
        if not emp:
            return jsonify({'error': f'Employee {employee_id} not found', 'ok': False}), 404
        
        slip_data = _build_slip_data(emp, result, APP_STATE.get('employees', []), month)
        html_content = render_template('payslip.html', slips=[slip_data])
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        
        filename = f'payslip_{employee_id}_{month}.pdf'
        return send_file(buf,
            mimetype='application/pdf',
            as_attachment=download,
            download_name=filename if download else None)
            
    except Exception as e:
        import traceback, sys
        print(f'[PDF EXPORT ERROR] {e}', file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': str(e), 'ok': False}), 500


@app.route('/export/payslips-all', methods=['POST'])
@login_required
@require_permission('salary', 'export')
def export_payslips_all():
    try:
        from weasyprint import HTML
        from flask import render_template
        import io
        
        data = request.get_json(silent=True) or {}
        month = data.get('month', APP_STATE.get('month', ''))
        
        result = APP_STATE.get('salary_result')
        if not result:
            return jsonify({'error': 'No salary data. Please recalculate.', 'ok': False}), 400
        
        employees = result.get('employees', [])
        if not employees:
            return jsonify({'error': 'No employees found', 'ok': False}), 404
        
        slips = []
        for emp in employees:
            slip_data = _build_slip_data(emp, result, APP_STATE.get('employees', []), month)
            slips.append(slip_data)
        
        html_content = render_template('payslip.html', slips=slips)
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        
        filename = f'payslips_all_{month}.pdf'
        return send_file(buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename)
            
    except Exception as e:
        import traceback, sys
        print(f'[PDF BATCH EXPORT ERROR] {e}', file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': str(e), 'ok': False}), 500


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

# ── P5: 用 Excel 种子新表 ──────────

def _backup_to_archive():
    """首次启动时自动备份 kilwa.db → archived_kilwa.db（如果归档不存在）"""
    import shutil
    db_path = os.path.join(app.config['DATA_FOLDER'], 'kilwa.db')
    archive_path = os.path.join(app.config['DATA_FOLDER'], 'archived_kilwa.db')
    if os.path.exists(db_path) and not os.path.exists(archive_path):
        shutil.copy2(db_path, archive_path)
        print('  ✓ 已自动备份 kilwa.db → archived_kilwa.db')

def seed_new_tables_from_excel():
    """仅首次运行：当 employees 表为空时，从通讯录 Excel 种子 employees"""
    from core.database import get_conn
    conn = get_conn(app.config['DATA_FOLDER'])
    # 检查 employees 是否已有数据（防止重复种子）
    count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if count > 10:
        conn.close()
        return False  # 已有数据，跳过

    print('  ► 从通讯录种子 employees 表...')
    # 纯采集模式：找 data/source 下可用的通讯录文件（仅首次导入用）
    import glob
    ab_path = None
    for _p in sorted(glob.glob(os.path.join(SOURCE_DIR, '*.xlsx'))):
        try:
            import openpyxl
            _wb = openpyxl.load_workbook(_p, data_only=True, read_only=True)
            _sheets = _wb.sheetnames
            _wb.close()
            if any('成员列表' in s or '通讯录' in s for s in _sheets):
                ab_path = _p
                break
        except Exception:
            continue
    if not ab_path:
        conn.close()
        return False

    from core.addressbook import parse_address_book
    from core.database import create_event
    ab_data = parse_address_book(ab_path)
    if not ab_data:
        conn.close()
        return False

    seen = set()
    for eid, info in ab_data.items():
        if not eid or eid in seen or eid in HARD_EXCLUDE_IDS:
            continue
        seen.add(eid)
        dept = strip_dept(info.get('department', ''))
        dtype = info.get('guessed_type') or 'day_rate'
        try:
            conn.execute("""
                INSERT OR IGNORE INTO employees (id, name, department, default_type, day_rate, monthly_salary)
                VALUES (?,?,?,?,?,?)
            """, (eid, info['name'], dept, dtype, 0, 0))
            create_event(app.config['DATA_FOLDER'], {
                'employee_id': eid, 'event_type': 'hire',
                'effective_date': '2026-01-01',
                'snapshot': json.dumps({'name': info['name'], 'department': dept, 'type': dtype}),
                'payload': '{}', 'operator_id': 'system', 'status': 'approved',
            })
        except Exception:
            pass

    print(f'  ✓ 已从通讯录种子 {len(seen)} 名员工 + hire 事件')
    conn.commit()
    conn.close()
    return True

def auto_load_source():
    """纯采集模式：从数据库重建并加载当前月份数据"""
    from datetime import datetime
    current_month = datetime.now(EAT).strftime('%Y-%m')
    chosen_month = current_month

    ok, msg = _run_pipeline(month_filter=chosen_month)
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
    from core.database import init_default_permissions, sync_role_permissions, seed_default_forms
    init_default_permissions(app.config['DATA_FOLDER'])
    sync_role_permissions(app.config['DATA_FOLDER'])
    seed_default_forms(app.config['DATA_FOLDER'])
    _backup_to_archive()
    seed_new_tables_from_excel()
    loaded = auto_load_source()
    if loaded:
        print('  ✓ 源数据已自动加载')
    else:
        print('  ⚠ data/source/ 下缺少主文件')

if __name__ != '__main__':
    _gunicorn_init()

if __name__ == '__main__':
    from core.database import init_db, init_default_permissions, sync_role_permissions, seed_default_forms
    _app_initialized = True
    init_db(app.config['DATA_FOLDER'])
    init_default_permissions(app.config['DATA_FOLDER'])
    sync_role_permissions(app.config['DATA_FOLDER'])
    seed_default_forms(app.config['DATA_FOLDER'])
    _backup_to_archive()
    seed_new_tables_from_excel()

    port = find_free_port(8080)
    print('=' * 50)
    print('  ENPRIZON LINDI PROJECT')
    print(f'  启动地址: http://localhost:{port}')
    loaded = auto_load_source()
    if not loaded:
        print('  ⚠ data/source/ 下缺少主文件，请放入再重启')
    print('=' * 50)
    app.run(debug=False, host='0.0.0.0', port=port)
