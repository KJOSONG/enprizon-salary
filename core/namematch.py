"""
姓名标准化管线
从原始名（含企业微信别名括号）→ 去别名 → 去空格大写 → CANONICAL映射 → 标准全名
"""
import re

# ── CANONICAL 映射表（短名/变体 → 标准全名） ─────
CANONICAL = {
    'SHEDRACK':                  'SHEDRACK PINIEL LAIZER',
    'SHEDRACKPINIELLAIZER':      'SHEDRACK PINIEL LAIZER',
    'JOHN':                      'JOHN BOAY BURA',
    'JOHNBOAYBURA':              'JOHN BOAY BURA',
    'BARAKALAIZER':              'BARAKA LAIZER',
    'JOSEPH':                    'JOSEPH DONALD',
    'JOSEPHDONALD':              'JOSEPH DONALD',
    'JULIASISAYA':              'JULIAS ISAYA',
    'JOSHUATAJIRI':             'JOSHUA TAJIRI',
    'SHAFIRIYAHAYA':            'SHAFIRI YAHAYA',
    'HERIMAULIDI':              'HERI MAULIDI',
    'HOSEALAIZER':              'HOSEA LAIZER',
    'BONIKIVUYO':               'BONI KIVUYO',
    'RAMAZANISAIDINAMAWALA':    'RAMAZANI SAIDI NAMAWALA',
}

# ── 已知钻工队长 ──────────────────────────────────
DRILLER_LEADERS = [
    'SHEDRACK PINIEL LAIZER',
    'JOHN BOAY BURA',
    'BARAKA LAIZER',
    'JOSEPH DONALD',
]

def _is_na(val):
    """替代 pd.isna 的简单检查"""
    if val is None: return True
    if isinstance(val, float) and (val != val): return True  # NaN
    return False

def strip_alias(name):
    """去除企业微信别名括号，如 'JOSEPH DONALD(JOSEPH  DONALD MWAKALINGA)' → 'JOSEPH DONALD'"""
    if not name or _is_na(name):
        return ''
    return re.sub(r'\s*\([^)]*\)\s*', '', str(name)).strip()

def norm_key(name):
    """去空格+大写，用于CANONICAL映射匹配"""
    return re.sub(r'\s+', '', strip_alias(name)).upper()

def canonical(name):
    """标准化姓名：短名/别名 → 标准全名"""
    if not name or _is_na(name):
        return None
    key = norm_key(name)
    if key in CANONICAL:
        return CANONICAL[key]
    result = strip_alias(name)
    return result if result else None

def make_employee_id(name):
    """生成唯一员工ID（去空格大写标准化名）"""
    c = canonical(name)
    if not c:
        return None
    return re.sub(r'\s+', '', c).upper()

def is_driller_leader(name):
    """判断是否为已知的钻工队长"""
    c = canonical(name)
    return c in DRILLER_LEADERS if c else False

def split_names(raw_str):
    """拆分名称字符串（逗号/分号/空格分隔）→ 标准化姓名列表"""
    if not raw_str or _is_na(raw_str):
        return []
    parts = re.split(r'\s*[;,]\s*', str(raw_str))
    result = []
    for p in parts:
        c = canonical(p.strip())
        if c:
            result.append(c)
    return result

def build_master_list(main_data):
    """
    构建员工主列表
    根据人员来源自动分类：
      - 仅出现于 Piece Rate 表（N/S 列或 AF-AI 列）→ 计件
      - 仅出现于 Daily Salary 表 → 日薪
      - 同时出现 → source='both'，需要用户指定
    返回: [{
        id, name, raw_names, default_type, source,
        day_rate: 0, monthly_salary: 0, advance_total: 0
    }]
    """
    piece_rate_people = main_data.get('piece_rate_people', {})
    daily_salary_people = main_data.get('daily_salary_people', {})

    # 区分钻工 vs 井下工人
    driller_people = piece_rate_people.get('driller', set())
    underground_people = piece_rate_people.get('underground', set())

    # 所有人员
    all_ids = set()
    for name in driller_people: all_ids.add(make_employee_id(name))
    for name in underground_people: all_ids.add(make_employee_id(name))
    for name in daily_salary_people: all_ids.add(make_employee_id(name))

    employees = []
    for eid in sorted(all_ids):
        in_driller = any(make_employee_id(n) == eid for n in driller_people)
        in_underground = any(make_employee_id(n) == eid for n in underground_people)
        in_daily = any(make_employee_id(n) == eid for n in daily_salary_people)

        # 区分来源
        in_piece = in_driller or in_underground

        if in_piece and not in_daily:
            source = 'piece_rate_sheet'
            if in_driller:
                default_type = 'piece_driller'
            else:
                default_type = 'piece_underground'
        elif in_daily and not in_piece:
            source = 'daily_salary_sheet'
            default_type = 'day_rate'
        else:
            source = 'both'
            default_type = 'both'

        # 取第一个出现的标准化名
        name = ''
        if in_driller:
            name = next((canonical(n) for n in driller_people if make_employee_id(n) == eid), '')
        if not name and in_underground:
            name = next((canonical(n) for n in underground_people if make_employee_id(n) == eid), '')
        if not name:
            name = next((canonical(n) for n in daily_salary_people if make_employee_id(n) == eid), eid)

        employees.append({
            'id': eid,
            'name': name,
            'default_type': default_type,
            'source': source,
            'override_type': None,
            'overrides': [],
            'day_rate': 0,
            'monthly_salary': 0,
            'advance_total': 0,
        })

    return employees
