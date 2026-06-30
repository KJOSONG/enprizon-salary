"""
薪资双路径核对模块
──────────────────────────────────────────────
路径一（基准计算）：直接从原始产量 × 单价计算总金额
  - 井下计件：白班 NH×6000 + NL×5000 + MW×4000
              + 夜班 NH×6000 + NL×5000 + MW×4000
  - 钻工计件：各队 NH×5000 + NL×4000 + MW×3000

路径二（实际汇总）：按薪资类型分类，汇总实际发放工资
  - 井下计件工人：piece_underground 合计
  - 钻工计件工人：piece_driller 合计

核对：自动对齐对比，输出差异明细
"""

from collections import defaultdict

# 默认单价（可通过参数覆盖）
DEFAULT_PRICES_UNDERGROUND = {'NICKEL（H）': 6000, 'NICKEL（L）': 5000, 'MAWE': 4000}
DEFAULT_PRICES_DRILLER = {'NICKEL（H）': 5000, 'NICKEL（L）': 4000, 'MAWE': 3000}


def verify_salary(main_data, salary_result, prices_underground=None, prices_driller=None):
    """
    执行双路径薪资核对
    ──────────────────────────────
    参数：
        main_data      — 解析后的原始数据（含 shift_production / driller_production）
        salary_result  — 计算引擎产出的薪资结果（含 employees 和 total_xxx）
        prices_*       — 可选覆盖单价，默认使用系统单价

    返回：
        {
            'underground': {
                'path1': int,            # 基准计算总额
                'path2': int,            # 实际汇总总额
                'diff': int,             # 差值（path2 - path1）
                'match': bool,           # 是否完全一致
            },
            'driller': { ...同上... },
            'overall_match': bool,       # 整体是否一致
            'path1_details': {           # 路径一 逐日明细
                'underground': [{date, day_total, night_total, combined}, ...],
                'driller': [{date, captain, total, nh, nl, mw}, ...],
            },
            'path2_details': {           # 路径二 逐人明细
                'underground': [{name, amount}, ...],
                'driller': [{name, amount}, ...],
            },
        }
    """
    pu = prices_underground or DEFAULT_PRICES_UNDERGROUND
    pd = prices_driller or DEFAULT_PRICES_DRILLER

    # ── 路径一：基准计算 ────────────────────────
    ug_path1, ug_daily = _path1_underground(main_data.get('shift_production', []), pu)
    dr_path1, dr_daily = _path1_driller(main_data.get('driller_production', []), pd)

    # ── 路径二：实际汇总 ────────────────────────
    ug_path2, ug_people = _path2_by_type(salary_result, 'piece_underground')
    dr_path2, dr_people = _path2_by_type(salary_result, 'piece_driller')

    # ── 路径二按日汇总（与路径一逐日对齐）────────
    ug_path2_daily = _path2_daily(salary_result, 'ug_daily')
    dr_path2_daily = _path2_daily(salary_result, 'driller_daily')

    # ── 逐日对比表 ──────────────────────────────
    ug_daily_comparison = _build_daily_comparison(main_data.get('shift_production', []), ug_path2_daily, pu, 'underground')
    dr_daily_comparison = _build_daily_comparison(main_data.get('driller_production', []), dr_path2_daily, pd, 'driller')

    # ── 比对 ────────────────────────────────────
    ug_diff = ug_path2 - ug_path1
    dr_diff = dr_path2 - dr_path1

    return {
        'underground': {
            'path1': ug_path1,
            'path2': ug_path2,
            'diff': ug_diff,
            'match': ug_diff == 0,
        },
        'driller': {
            'path1': dr_path1,
            'path2': dr_path2,
            'diff': dr_diff,
            'match': dr_diff == 0,
        },
        'overall_match': (ug_diff == 0) and (dr_diff == 0),
        'path1_details': {
            'underground': ug_daily,
            'driller': dr_daily,
        },
        'path2_details': {
            'underground': ug_people,
            'driller': dr_people,
        },
        'daily_comparison': {
            'underground': ug_daily_comparison,
            'driller': dr_daily_comparison,
        },
    }


# ═══════════════════════════════════════════════════════════
#  路径一 内部实现
# ═══════════════════════════════════════════════════════════

def _path1_underground(shift_production, prices):
    """
    路径一 — 井下计件基准计算
    直接从产量数据求和，不涉及人员分配
    返回: (总金额, 逐日明细)
    """
    daily = []
    total = 0

    for day in shift_production:
        day_prod = day.get('day_prod') or {}
        night_prod = day.get('night_prod') or {}

        day_total = 0
        night_total = 0

        if day_prod:
            day_total = sum(
                (day_prod.get(k, 0) or 0) * prices.get(k, 0)
                for k in prices
            )

        if night_prod:
            night_total = sum(
                (night_prod.get(k, 0) or 0) * prices.get(k, 0)
                for k in prices
            )

        combined = day_total + night_total
        total += combined

        daily.append({
            'date': day.get('date', ''),
            'day_total': day_total,
            'night_total': night_total,
            'combined': combined,
            'nh': (day_prod.get('NICKEL（H）', 0) or 0) + (night_prod.get('NICKEL（H）', 0) or 0),
            'nl': (day_prod.get('NICKEL（L）', 0) or 0) + (night_prod.get('NICKEL（L）', 0) or 0),
            'mw': (day_prod.get('MAWE', 0) or 0) + (night_prod.get('MAWE', 0) or 0),
        })

    return round(total), daily


def _path1_driller(driller_production, prices):
    """
    路径一 — 钻工计件基准计算
    直接从钻工产量数据求和（按日期+队长聚合）
    注意：钻工产量数据使用短key（nh/nl/mw），需映射到单价key
    返回: (总金额, 逐队明细)
    """
    # 短key → 单价key 映射
    SHORT_KEY_MAP = {'nh': 'NICKEL（H）', 'nl': 'NICKEL（L）', 'mw': 'MAWE'}

    # 按 (日期, 队长) 聚合（同路径一需要稳定，不切割）
    groups = defaultdict(lambda: {
        'nh': 0, 'nl': 0, 'mw': 0,
    })

    for d in driller_production:
        key = (d.get('date', ''), d.get('captain', ''))
        g = groups[key]
        g['nh'] += d.get('nh', 0) or 0
        g['nl'] += d.get('nl', 0) or 0
        g['mw'] += d.get('mw', 0) or 0

    daily = []
    total = 0

    for (date_str, captain), g in sorted(groups.items()):
        # 通过映射表转换为单价key计算金额
        amt = 0
        for short_k, v in g.items():
            price_k = SHORT_KEY_MAP.get(short_k, short_k)
            amt += v * prices.get(price_k, 0)

        total += amt
        daily.append({
            'date': date_str,
            'captain': captain,
            'total': amt,
            'nh': g['nh'],
            'nl': g['nl'],
            'mw': g['mw'],
        })

    return round(total), daily


# ═══════════════════════════════════════════════════════════
#  路径二 内部实现
# ═══════════════════════════════════════════════════════════

def _path2_by_type(salary_result, target_type):
    """
    路径二 — 按实际收到的薪资金额汇总（不依赖 salary_type 标签，避免遗漏跨类型员工）
    target_type: 'piece_underground' | 'piece_driller'
    返回: (总金额, 逐人明细)
    """
    employees = salary_result.get('employees', []) if salary_result else []
    people = []
    total = 0

    field_map = {
        'piece_underground': 'piece_underground',
        'piece_driller': 'piece_driller',
    }

    field = field_map.get(target_type)
    if not field:
        return 0, []

    for emp in employees:
        amt = round(emp.get(field, 0) or 0)
        if amt <= 0:
            continue
        total += amt
        people.append({
            'name': emp.get('name', ''),
            'amount': amt,
            'salary_type': emp.get('salary_type', ''),  # 保留真实类型标签用于核对
        })

    return total, people


def _path2_daily(salary_result, field_key):
    """
    路径二按日汇总：从 ug_daily / driller_daily 按日期求和
    field_key: 'ug_daily' | 'driller_daily'
    返回: { '2026-05-01': 362000, ... }
    """
    daily = (salary_result or {}).get(field_key, {})
    result = defaultdict(float)
    for eid, dates in daily.items():
        for dt, amt in dates.items():
            result[dt] += amt
    return {dt: round(amt) for dt, amt in result.items()}


def _build_daily_comparison(production_data, path2_daily, prices, track):
    """
    构建逐日对比表，路径一与路径二对齐
    track: 'underground' | 'driller'
    返回: [{date, path1, path2, diff}, ...]
    """
    SHORT_KEY_MAP = {'nh': 'NICKEL（H）', 'nl': 'NICKEL（L）', 'mw': 'MAWE'}
    # 路径一按日汇总
    path1_by_date = defaultdict(float)
    if track == 'underground':
        for day in production_data:
            dt = day.get('date', '')
            dp = day.get('day_prod') or {}
            np = day.get('night_prod') or {}
            if dp:
                path1_by_date[dt] += sum((dp.get(k, 0) or 0) * prices.get(k, 0) for k in prices)
            if np:
                path1_by_date[dt] += sum((np.get(k, 0) or 0) * prices.get(k, 0) for k in prices)
    else:  # driller — 按(日期,队长)分组合并多slot，避免重复计算
        dr_groups = defaultdict(lambda: {'nh': 0, 'nl': 0, 'mw': 0})
        for d in production_data:
            dt = d.get('date', '')
            key = (dt, d.get('captain', ''))
            dr_groups[key]['nh'] += d.get('nh', 0) or 0
            dr_groups[key]['nl'] += d.get('nl', 0) or 0
            dr_groups[key]['mw'] += d.get('mw', 0) or 0
        for (dt, _cap), g in dr_groups.items():
            total = 0
            for short_k in ['nh', 'nl', 'mw']:
                price_k = SHORT_KEY_MAP[short_k]
                total += g[short_k] * prices.get(price_k, 0)
            path1_by_date[dt] += total

    # 合并所有日期
    all_dates = sorted(set(list(path1_by_date.keys()) + list(path2_daily.keys())))
    result = []
    for dt in all_dates:
        p1 = round(path1_by_date.get(dt, 0))
        p2 = path2_daily.get(dt, 0)
        diff = p2 - p1
        # 小额差异为浮点舍入（人均分产除不尽），视为一致
        is_rounding = abs(diff) <= 10
        result.append({
            'date': dt,
            'path1': p1,
            'path2': p2,
            'diff': 0 if is_rounding else diff,
            'is_rounding': is_rounding,
        })
    return result
