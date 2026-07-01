"""
姓名标准化管线（通讯录驱动）
原始名（含企业微信别名括号）→ 去别名 → 通讯录索引查找 → (账号, 显示名)
"""
import re

# ── 通讯录驱动的员工索引（key: 变体去空格大写 → (账号, 显示名)）──
_AB_INDEX = {}

# ── 遗留 CANONICAL 映射（通讯录外人员的手动回退）──
_LEGACY_CANONICAL = {
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

# ── 已知钻工队长（显示名列表）──
DRILLER_LEADER_NAMES = [
    'SHEDRACK PINIEL LAIZER',
    'JOHN BOAY BURA',
    'BARAKA LAIZER',
    'JOSEPH DONALD',
]

# ── 钻工队长账号（load_address_book_index 后自动计算）──
DRILLER_LEADERS = []


def load_address_book_index(filepath):
    """从通讯录 Excel 加载员工索引，填充 _AB_INDEX"""
    global _AB_INDEX, DRILLER_LEADERS
    _AB_INDEX = {}
    import openpyxl
    wb = openpyxl.load_workbook(filepath, data_only=True)
    sheet = None
    for name in ['成员列表', 'Sheet1']:
        if name in wb.sheetnames:
            sheet = name
            break
    if not sheet:
        wb.close()
        return
    ws = wb[sheet]
    header_row = None
    for row in range(1, (ws.max_row or 0) + 1):
        v = ws.cell(row, 1).value
        if v and '姓名' in str(v):
            header_row = row
            break
    if not header_row:
        wb.close()
        return
    for row in range(header_row + 1, (ws.max_row or 0) + 1):
        name_raw = ws.cell(row, 1).value
        acct = ws.cell(row, 2).value
        alias = ws.cell(row, 3).value
        if not name_raw:
            continue
        name_str = str(name_raw).strip()
        acct_str = str(acct).strip() if acct else ''
        alias_str = str(alias).strip() if alias else ''
        if not acct_str:
            continue
        display = alias_str if alias_str else strip_alias(name_str)
        # 姓名变体
        key_name = norm_key_static(name_str)
        if key_name:
            _AB_INDEX[key_name] = (acct_str, display)
        # 别名变体
        if alias_str:
            key_alias = norm_key_static(alias_str)
            if key_alias:
                _AB_INDEX[key_alias] = (acct_str, display)
        # 带括号的原始姓名去括号后
        sa = strip_alias(name_str)
        if sa:
            key_sa = re.sub(r'\s+', '', sa).upper()
            if key_sa and key_sa != key_name:
                _AB_INDEX[key_sa] = (acct_str, display)
        # 去最后一个词的键（用于匹配短名如 ADHIRUDIN SIJAE RASHID -> ADHIRUDINSIJAE）
        sa_words = sa.split()
        if len(sa_words) > 1:
            short_name = ' '.join(sa_words[:-1])
            short_key = re.sub(r'\s+', '', short_name).upper()
            if short_key and short_key not in _AB_INDEX:
                _AB_INDEX[short_key] = (acct_str, display)
    wb.close()
    # 自动计算钻工队长账号（修改列表内容而非重新赋值，确保外部 import 可见）
    DRILLER_LEADERS.clear()
    for leader_name in DRILLER_LEADER_NAMES:
        for key, (acct, _) in _AB_INDEX.items():
            leader_key = re.sub(r'\s+', '', leader_name).upper()
            if key == leader_key:
                DRILLER_LEADERS.append(acct)
                break


def _is_na(val):
    if val is None: return True
    if isinstance(val, float) and (val != val): return True
    return False


def strip_alias(name):
    if not name or _is_na(name):
        return ''
    return re.sub(r'\s*\([^)]*\)\s*', '', str(name)).strip()


def norm_key_static(name):
    """去空格+大写（静态版本，不依赖 CANONICAL）"""
    sa = strip_alias(name)
    if not sa:
        return ''
    return re.sub(r'\s+', '', sa).upper()


def canonical(name):
    """标准化姓名：通讯录查找 → 显示名；未匹配时回退到遗留 CANONICAL + strip_alias"""
    if not name or _is_na(name):
        return None
    key = norm_key_static(name)
    # 通讯录索引优先
    if _AB_INDEX and key in _AB_INDEX:
        return _AB_INDEX[key][1]  # 返回显示名
    # 遗留 CANONICAL 回退
    if key in _LEGACY_CANONICAL:
        return _LEGACY_CANONICAL[key]
    # 最终回退：去括号结果
    result = strip_alias(name)
    return result if result else None


def make_employee_id(name):
    """生成唯一员工ID：通讯录 → 账号；未匹配时回退到姓名去空格大写"""
    if not name or _is_na(name):
        return None
    key = norm_key_static(name)
    # 遗留 CANONICAL：短名先展开为全名，再查通讯录
    full_name = None
    if key in _LEGACY_CANONICAL:
        full_name = _LEGACY_CANONICAL[key]
        full_key = re.sub(r'\s+', '', full_name).upper()
        if _AB_INDEX and full_key in _AB_INDEX:
            return _AB_INDEX[full_key][0]
    # 通讯录索引直接查找
    if _AB_INDEX and key in _AB_INDEX:
        return _AB_INDEX[key][0]
    # 遗留 CANONICAL → 转换为旧格式 ID
    if full_name:
        return re.sub(r'\s+', '', full_name).upper()
    # 最终回退
    c = strip_alias(name)
    return re.sub(r'\s+', '', c).upper() if c else None


def display_name(name):
    """返回该员工的显示名（别名优先，否则去括号的姓名）"""
    if not name or _is_na(name):
        return ''
    key = norm_key_static(name)
    if _AB_INDEX and key in _AB_INDEX:
        return _AB_INDEX[key][1]
    return strip_alias(name) or str(name)


def is_driller_leader(name_or_id):
    """判断是否为已知的钻工队长（支持传入账号或姓名）"""
    eid = make_employee_id(name_or_id) if name_or_id else None
    return eid in DRILLER_LEADERS if eid else False


def split_names(raw_str):
    """拆分名称字符串（逗号/分号分隔）→ 标准化姓名列表（显示名）"""
    if not raw_str or _is_na(raw_str):
        return []
    parts = re.split(r'\s*[;,、\n]\s*', str(raw_str))
    result = []
    for p in parts:
        c = canonical(p.strip())
        if c:
            result.append(c)
    return result


def build_master_list(main_data):
    """
    构建员工主列表
    根据人员来源自动分类
    """
    piece_rate_people = main_data.get('piece_rate_people', {})
    daily_salary_people = main_data.get('daily_salary_people', {})

    driller_people = piece_rate_people.get('driller', set())
    underground_people = piece_rate_people.get('underground', set())

    all_ids = set()
    for name in driller_people: all_ids.add(make_employee_id(name))
    for name in underground_people: all_ids.add(make_employee_id(name))
    for name in daily_salary_people: all_ids.add(make_employee_id(name))

    employees = []
    for eid in sorted(eid for eid in all_ids if eid):
        in_driller = any(make_employee_id(n) == eid for n in driller_people)
        in_underground = any(make_employee_id(n) == eid for n in underground_people)
        in_daily = any(make_employee_id(n) == eid for n in daily_salary_people)

        in_piece = in_driller or in_underground

        if in_piece and not in_daily:
            source = 'piece_rate_sheet'
            default_type = 'piece_driller' if in_driller else 'piece_underground'
        elif in_daily and not in_piece:
            source = 'daily_salary_sheet'
            default_type = 'day_rate'
        else:
            source = 'both'
            default_type = 'both'

        # 取第一个出现的显示名
        name = ''
        if in_driller:
            name = next((display_name(n) for n in driller_people if make_employee_id(n) == eid), '')
        if not name and in_underground:
            name = next((display_name(n) for n in underground_people if make_employee_id(n) == eid), '')
        if not name:
            name = next((display_name(n) for n in daily_salary_people if make_employee_id(n) == eid), eid)

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
