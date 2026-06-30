"""
薪资计算引擎（四轨）
1. 井下计件（N/S 列） NH×6000 + NL×5000 + MW×4000，平分
2. 钻工计件（T-Z/AF-AI 列） NH×5000 + NL×4000 + MW×3000，队长×2份额制
3. 日薪（Daily Salary 表）日薪基数×出勤天数
4. 月薪（手动标记）月薪基数
"""
from collections import defaultdict
from calendar import monthrange
from datetime import datetime, date
from .namematch import canonical, make_employee_id, is_driller_leader, DRILLER_LEADERS

# ── 单价 ─────────────────────────────────────────────────
PRICES_UNDERGROUND = {'NICKEL（H）': 6000, 'NICKEL（L）': 5000, 'MAWE': 4000}
PRICES_DRILLER = {'NICKEL（H）': 5000, 'NICKEL（L）': 4000, 'MAWE': 3000}

TODAY = date.today()
CURRENT_MONTH = TODAY.month
CURRENT_YEAR = TODAY.year

# ═══════════════════════════════════════════════════════════
#  1. 井下计件计算
# ═══════════════════════════════════════════════════════════

def calc_underground_piece(shift_data, exclusions, override_excludes, data_folder=None):
    """
    计算井下工人计件工资
    白班+夜班合并，总金额均分给出勤人员
    返回: { employee_id: total_salary }, { employee_id: { date: amount } }
    """
    result = defaultdict(float)
    daily = defaultdict(lambda: defaultdict(float))
    daily_shifts = defaultdict(lambda: defaultdict(set))  # daily_shifts[eid][date] = {'D','N'}
    total_production = defaultdict(float)

    # 加载手动加入计件分配（从 overrides 表读取，展开日期区间）
    shift_adds = {}
    import os
    if data_folder:
        dbp = os.path.join(data_folder, 'kilwa.db')
        if os.path.exists(dbp):
            import sqlite3
            conn = sqlite3.connect(dbp)
            try:
                for r in conn.execute("SELECT employee_id, start_date, end_date, shift FROM overrides WHERE salary_type='piece_underground' AND shift!='' AND start_date!=''").fetchall():
                    eid, s, e, sh = r[0], r[1], r[2], r[3]
                    end = e or s
                    from datetime import datetime as _dt, timedelta as _td
                    d = _dt.strptime(s, '%Y-%m-%d')
                    d_end = _dt.strptime(end, '%Y-%m-%d')
                    while d <= d_end:
                        shift_adds[(eid, d.strftime('%Y-%m-%d'))] = sh
                        d += _td(days=1)
            except: pass
            conn.close()

    for day in shift_data:
        date_str = day['date']
        day_emps = day.get('day_emps', [])
        night_emps = day.get('night_emps', [])
        day_prod = day.get('day_prod')
        night_prod = day.get('night_prod')

        # 白班
        if day_emps and day_prod:
            total = sum(day_prod[k] * PRICES_UNDERGROUND[k] for k in PRICES_UNDERGROUND)
            valid = _filter_valid(day_emps, exclusions, override_excludes, date_str)
            # 按 eid 去重：同一人同一天被不同提交者列出多次时只计一次
            seen = set()
            deduped = []
            for e in valid:
                eid = make_employee_id(e)
                if eid and eid not in seen:
                    seen.add(eid)
                    deduped.append(e)
            valid = deduped
            # 手动加入白班的人（排除 A/L：请假/旷工人不加入分配）
            existing_ids = {make_employee_id(e) for e in valid if make_employee_id(e)}
            for (eid, dt), sh in shift_adds.items():
                if dt == date_str and sh == 'D' and eid not in existing_ids and (eid, date_str) not in exclusions:
                    valid.append(eid)
                    existing_ids.add(eid)
            if valid and total > 0:
                per = total / len(valid)
                for e in valid:
                    eid = make_employee_id(e)
                    if eid:
                        result[eid] += per
                        daily[eid][date_str] += per
                        daily_shifts[eid][date_str].add('D')
                        total_production['nh'] += day_prod.get('NICKEL（H）', 0) / len(valid)
                        total_production['nl'] += day_prod.get('NICKEL（L）', 0) / len(valid)
                        total_production['mw'] += day_prod.get('MAWE', 0) / len(valid)

        # 夜班
        if night_emps and night_prod:
            total = sum(night_prod[k] * PRICES_UNDERGROUND[k] for k in PRICES_UNDERGROUND)
            valid = _filter_valid(night_emps, exclusions, override_excludes, date_str)
            # 按 eid 去重：同一人同一天被不同提交者列出多次时只计一次
            seen = set()
            deduped = []
            for e in valid:
                eid = make_employee_id(e)
                if eid and eid not in seen:
                    seen.add(eid)
                    deduped.append(e)
            valid = deduped
            # 手动加入夜班的人（排除 A/L）
            existing_ids = {make_employee_id(e) for e in valid if make_employee_id(e)}
            for (eid, dt), sh in shift_adds.items():
                if dt == date_str and sh == 'N' and eid not in existing_ids and (eid, date_str) not in exclusions:
                    valid.append(eid)
                    existing_ids.add(eid)
            if valid and total > 0:
                per = total / len(valid)
                for e in valid:
                    eid = make_employee_id(e)
                    if eid:
                        result[eid] += per
                        daily[eid][date_str] += per
                        daily_shifts[eid][date_str].add('N')

    return dict(result), {eid: dict(d) for eid, d in daily.items()}, {eid: {dt: ''.join(sorted(s)) for dt, s in sh.items()} for eid, sh in daily_shifts.items()}

def _filter_valid(emps, exclusions, override_excludes, date_str):
    """过滤出计件有效人员（去除永久排除 + 当日排除）"""
    valid = []
    for e in emps:
        eid = make_employee_id(e)
        if not eid:
            continue
        if eid in override_excludes.get('permanent', set()):
            continue
        if (eid, date_str) in exclusions:
            continue
        valid.append(e)
    return valid

# ═══════════════════════════════════════════════════════════
#  2. 钻工计件计算
# ═══════════════════════════════════════════════════════════

def calc_driller_piece(driller_data, data_folder=None, exclusions=None):
    """
    计算钻工计件工资
    - 同队长同天多槽位 → 合并产量，成员合并去重
    - 队长无条件加入成员列表
    - 空成员名单日 → 仅队长1人
    - 总薪资/(人数+1) × 队长2份/队员1份
    返回: { employee_id: total_salary }, duplications, { employee_id: { date: amount } }
    """
    import sqlite3, os
    result = defaultdict(float)
    daily = defaultdict(lambda: defaultdict(float))  # daily[employee_id][date] = amount
    duplications = []
    exclusions = exclusions or set()

    # 加载 A/L 排除
    att_exclusions = set()
    if data_folder:
        db_path = os.path.join(data_folder, 'kilwa.db')
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L')").fetchall()
            conn.close()
            for r in rows:
                att_exclusions.add((r[0], r[1]))

    # 合并 A/L 排除 + 外部排除（含日期区间 override）
    combined_exclusions = exclusions | att_exclusions

    # 按 (日期, 队长) 分组合并
    groups = defaultdict(lambda: {
        'nh': 0, 'nl': 0, 'mw': 0,
        'futa': 0, 'waya': 0, 'kibiriti': 0,
        'members': set(), 'slots': [], 'has_members': False,
    })

    for d in driller_data:
        key = (d['date'], d['captain'])
        g = groups[key]
        g['nh'] += d['nh']
        g['nl'] += d['nl']
        g['mw'] += d['mw']
        g['futa'] += d['futa']
        g['waya'] += d['waya']
        g['kibiriti'] += d['kibiriti']
        g['slots'].append(d['slot'])
        if d['members']:
            g['members'].update(d['members'])
            g['has_members'] = True

    # 计算每组薪资
    # 加载手动加入钻工组的人（从 overrides 表读取，展开日期区间）
    driller_adds = {}
    if data_folder:
        import os
        dbp = os.path.join(data_folder, 'kilwa.db')
        if os.path.exists(dbp):
            import sqlite3
            conn = sqlite3.connect(dbp)
            try:
                for r in conn.execute("SELECT employee_id, start_date, end_date, captain FROM overrides WHERE salary_type='piece_driller' AND captain!='' AND start_date!=''").fetchall():
                    eid, s, e, cap = r[0], r[1], r[2], r[3]
                    end = e or s
                    from datetime import datetime as _dt, timedelta as _td
                    d = _dt.strptime(s, '%Y-%m-%d')
                    d_end = _dt.strptime(end, '%Y-%m-%d')
                    while d <= d_end:
                        driller_adds[(eid, d.strftime('%Y-%m-%d'))] = cap
                        d += _td(days=1)
            except: pass
            conn.close()

    for (date_str, captain), g in groups.items():
        total_salary = g['nh'] * PRICES_DRILLER['NICKEL（H）'] + \
                       g['nl'] * PRICES_DRILLER['NICKEL（L）'] + \
                       g['mw'] * PRICES_DRILLER['MAWE']
        if total_salary <= 0:
            continue

        # 构建成员列表（队长无条件加入，但过滤 A/L 成员）
        if g['has_members']:
            all_members = [m for m in g['members'] if (make_employee_id(m), date_str) not in combined_exclusions]
        else:
            all_members = []
        cap_norm = make_employee_id(captain)
        cap_member = canonical(captain)
        # 队长也受 A/L 排除影响：若队长请假/旷工，不计入分配也不享受队长双倍份额
        cap_excluded = cap_norm and (cap_norm, date_str) in combined_exclusions
        # 用 make_employee_id 比较，避免 short name vs canonical name 不匹配
        existing_ids = {make_employee_id(m) for m in all_members if make_employee_id(m)}
        if cap_member and not cap_excluded and cap_norm not in existing_ids:
            all_members.append(cap_member)

        # 统计手动加入钻工组的人数
        driller_add_count = sum(1 for (eid, dt), cp in driller_adds.items()
                                if dt == date_str and cp == captain and eid != cap_norm)

        headcount = len(all_members)
        # 分母 = 成员人数 + 队长额外份额(+1, 因队长拿双倍) + 手动加入的人
        # 若队长被排除(A/L), 则取消队长的 +1 份额
        captain_bonus = 0 if cap_excluded else 1
        denominator = headcount + captain_bonus + driller_add_count
        if denominator <= 0:
            continue  # 无人可分配（队长A/L + 无队员 + 无手动加入者）
        per_share = total_salary / denominator

        for mn in all_members:
            mn_id = make_employee_id(mn)
            if mn_id:
                shares = 2 if mn_id == cap_norm else 1
                amt = per_share * shares
                result[mn_id] += amt
                daily[mn_id][date_str] += amt

        # 手动加入钻工组的人
        for (eid, dt), cp in driller_adds.items():
            if dt == date_str and cp == captain and eid != cap_norm:
                amt = per_share * 1
                result[eid] += amt
                daily[eid][dt] += amt

    return dict(result), duplications, {eid: dict(d) for eid, d in daily.items()}

# ═══════════════════════════════════════════════════════════
#  3. 日薪计算
# ═══════════════════════════════════════════════════════════

def calc_day_salary(attendance_data, employees, overrides, data_folder=None, shift_data=None, date_range_overrides=None):
    """
    计算日薪工资
    根据 Daily Salary 表找出勤天数，乘以日薪基数
    排除 A（旷工）和 L（请假）的天数
    overrides 中标记为 day_rate 的可覆盖日薪基数
    如果员工被标记为 day_rate，也计入产量表（shift_production）中的出勤天数
    date_range_overrides: {eid: (start_date, end_date)} 限定日薪仅统计区间内天数
    返回: { employee_id: total_salary }
    """
    import json, os
    result = defaultdict(float)
    date_range_overrides = date_range_overrides or {}

    # 加载手动出勤覆盖（SQLite）
    att_overrides = {}
    if data_folder:
        db_path = os.path.join(data_folder, 'kilwa.db')
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT employee_id, date, status FROM attendance_overrides").fetchall()
            conn.close()
            for r in rows:
                att_overrides[f"{r[0]}|{r[1]}"] = r[2]

    # 判断某员工是否被覆盖为日薪（且无日期区间，或日期在区间内）
    def is_overridden_day_rate(eid, date_str=None):
        if eid in overrides:
            for o in overrides[eid]:
                if o.get('salary_type') == 'day_rate':
                    # 如果有日期区间限制
                    start = o.get('start_date') or ''
                    end = o.get('end_date') or ''
                    if start or end:
                        if date_str:
                            if start and date_str < start: continue
                            if end and date_str > end: continue
                            return True
                    else:
                        return True
        return False

    # 统计每人出勤天数，扣除 A/L
    day_counts = defaultdict(int)
    counted_pairs = set()

    # 来源1：日薪出勤表
    for day in attendance_data:
        dt = day.get('date', '')
        for e in day.get('normal', []):
            eid = make_employee_id(e)
            if not eid:
                continue
            # 按 (eid, date) 去重：同一人同一天被不同提交者列出多次时只计一次
            if (eid, dt) in counted_pairs:
                continue
            # 如果有日期区间且该日不在区间内，跳过
            if eid in date_range_overrides:
                dstart, dend = date_range_overrides[eid]
                if dstart and dt < dstart: continue
                if dend and dt > dend: continue
            key = f'{eid}|{dt}'
            if key in att_overrides:
                if att_overrides[key] in ('A', 'L'):
                    continue
            counted_pairs.add((eid, dt))
            day_counts[eid] += 1

    # 来源2：产量表（仅对被覆盖为日薪的员工）
    if shift_data:
        for day in shift_data:
            dt = day['date']
            for e in day.get('day_emps', []):
                eid = make_employee_id(e)
                if eid and is_overridden_day_rate(eid, dt):
                    # 按 (eid, date) 去重
                    if (eid, dt) in counted_pairs:
                        continue
                    key = f'{eid}|{dt}'
                    if key in att_overrides:
                        if att_overrides[key] in ('A', 'L'):
                            continue
                    counted_pairs.add((eid, dt))
                    day_counts[eid] += 1
            for e in day.get('night_emps', []):
                eid = make_employee_id(e)
                if eid and is_overridden_day_rate(eid, dt):
                    # 按 (eid, date) 去重
                    if (eid, dt) in counted_pairs:
                        continue
                    key = f'{eid}|{dt}'
                    if key in att_overrides:
                        if att_overrides[key] in ('A', 'L'):
                            continue
                    counted_pairs.add((eid, dt))
                    day_counts[eid] += 1

    # 来源3：手动 P 覆盖（仅限当月，与来源1/2的月份一致）
    _month_prefixes = set()
    for d in list(attendance_data) + list(shift_data or []):
        dt = d.get('date', '')
        if dt:
            _month_prefixes.add(dt[:7])
    for key, status in att_overrides.items():
        if status == 'P':
            parts = key.split('|')
            if len(parts) == 2:
                eid, dt = parts[0], parts[1]
                if _month_prefixes and dt[:7] not in _month_prefixes:
                    continue
                if (eid, dt) not in counted_pairs:
                    day_counts[eid] += 1

    # 查找日薪基数
    emp_map = {}
    for emp in employees:
        emp_map[emp['id']] = emp

    for eid, days in day_counts.items():
        # 默认日薪基数 = 0（需手动设置）
        day_rate = 0

        # 先看覆盖标记
        if eid in overrides:
            for o in overrides[eid]:
                if o.get('salary_type') == 'day_rate' and o.get('day_rate', 0) > 0:
                    day_rate = o['day_rate']

        # 再看员工信息表
        if day_rate == 0 and eid in emp_map:
            day_rate = emp_map[eid].get('day_rate', 0)

        if day_rate > 0:
            result[eid] = day_rate * days

    return dict(result)

# ═══════════════════════════════════════════════════════════
#  4. 月薪计算
# ═══════════════════════════════════════════════════════════

def calc_monthly_salary(employees, overrides):
    """
    计算月薪工资
    被标记为 monthly 的员工，取月薪基数
    优先取 override，回退到员工基础字段
    返回: { employee_id: total_salary }
    """
    result = {}
    emp_map = {e['id']: e for e in employees}
    for eid, ovs in overrides.items():
        for o in ovs:
            if o.get('salary_type') == 'monthly' and o.get('monthly_salary', 0) > 0:
                result[eid] = o['monthly_salary']
    # 回退：没有 override 的月薪员工，用基础字段
    for emp in employees:
        eid = emp['id']
        if eid not in result and (emp.get('default_type') == 'monthly' or emp.get('override_type') == 'monthly'):
            if emp.get('monthly_salary', 0) > 0:
                result[eid] = emp['monthly_salary']
    return result

# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def calculate_all(main_data, employees, overrides=None, exclusions=None, pricing=None, data_folder=None, bonus_penalties=None):
    """
    完整四轨计算
    pricing: {underground_prices, driller_prices, nssf_rate} 来自 `core/pricing`
    bonus_penalties: {employee_id: {bonus: int, penalty: int}} 当月奖金/罚款
    """
    overrides = overrides or {}
    exclusions = exclusions or set()
    pricing = pricing or {}
    up = pricing.get('underground_prices', PRICES_UNDERGROUND)
    dp = pricing.get('driller_prices', PRICES_DRILLER)
    nssf_rate = pricing.get('nssf_rate', 0.10)

    # 临时覆盖模块级单价常量，让子函数使用配置值
    import sys
    mod = sys.modules[__name__]
    old_up, old_dp = mod.PRICES_UNDERGROUND, mod.PRICES_DRILLER
    mod.PRICES_UNDERGROUND = up
    mod.PRICES_DRILLER = dp

    try:
        override_excludes = {'permanent': set()}
        import os
        for eid, ovs in overrides.items():
            for o in ovs:
                if o.get('type') == 'exclusion' and o.get('action') == 'add':
                    pass

        # 加载出勤覆盖（A/L不计入计件分配）
        att_exclusions = set()
        if data_folder:
            db_path = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(db_path):
                import sqlite3
                conn = sqlite3.connect(db_path)
                rows = conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L')").fetchall()
                conn.close()
                for r in rows:
                    att_exclusions.add((r[0], r[1]))

        shift_data = main_data.get('shift_production', [])
        driller_data = main_data.get('driller_production', [])
        attendance_data = main_data.get('attendance', [])

        # 构建日期类型映射：有 date_range override 的员工，按日期决定类型
        has_date_range = set()
        range_exclusions = set()
        date_range_overrides = {}
        date_type_map = defaultdict(dict)  # {eid: {date: salary_type}}
        for eid, ovs in overrides.items():
            for o in ovs:
                st = o.get('salary_type', '')
                start = o.get('start_date') or ''
                end = o.get('end_date') or ''
                if st in ('day_rate', 'monthly') and (start or end):
                    has_date_range.add(eid)
                    date_range_overrides[eid] = (start, end)
                    # 区间内天数排除计件
                    for day in shift_data:
                        dt = day['date']
                        if start and dt < start: continue
                        if end and dt > end: continue
                        range_exclusions.add((eid, dt))
                if st in ('piece_underground', 'piece_driller') and (start or end):
                    has_date_range.add(eid)
                    # 区间内按此类型计算
                    for day in shift_data + [{'date': d} for d in set(d['date'] for d in attendance_data if d.get('date'))]:
                        dt = day['date'] if isinstance(day, dict) and 'date' in day else ''
                        if not dt: continue
                        if start and dt < start: continue
                        if end and dt > end: continue
                        date_type_map[eid][dt] = st

        # 合并计件排除 + 出勤排除 + 日期区间排除
        combined_exclusions = exclusions | att_exclusions | range_exclusions

        # 逐日类型排除：非井下计件类型的人不参与井下计件分配
        # 基准 = 永久类型（忽略日期区间），加上日期区间的逐日覆盖
        all_shift_dates = sorted(set(d['date'] for d in shift_data if d.get('date')))
        ug_type_excl = set()
        dr_type_excl = set()
        for emp in employees:
            eid = emp['id']
            # 永久类型（忽略日期区间覆盖）
            perm_type = emp['default_type']
            if eid in overrides:
                for o in overrides[eid]:
                    st = o.get('salary_type', '')
                    s, e = o.get('start_date') or '', o.get('end_date') or ''
                    if st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller') and not (s or e):
                        perm_type = st
            # 日期区间覆盖
            date_range_types = {}
            for o in overrides.get(eid, []):
                st = o.get('salary_type', '')
                start = o.get('start_date') or ''
                end = o.get('end_date') or ''
                if st in ('piece_underground', 'piece_driller', 'day_rate', 'monthly') and (start or end):
                    for dt in all_shift_dates:
                        if (not start or dt >= start) and (not end or dt <= end):
                            date_range_types[dt] = st
            for dt in all_shift_dates:
                dtype = date_range_types.get(dt, perm_type)
                if dtype != 'piece_underground':
                    ug_type_excl.add((eid, dt))
                if dtype != 'piece_driller':
                    dr_type_excl.add((eid, dt))

        underground_sal, ug_daily, ug_shifts = calc_underground_piece(shift_data, combined_exclusions | ug_type_excl, override_excludes, data_folder)
        driller_sal, duplications, driller_daily = calc_driller_piece(driller_data, data_folder, combined_exclusions | dr_type_excl)
        day_sal = calc_day_salary(attendance_data, employees, overrides, data_folder, shift_data, date_range_overrides)
        monthly_sal = calc_monthly_salary(employees, overrides)
    finally:
        mod.PRICES_UNDERGROUND = old_up
        mod.PRICES_DRILLER = old_dp

    # 合并例外覆盖逻辑:
    emp_map = {}
    for emp in employees:
        emp_map[emp['id']] = emp

    bonus_penalties = bonus_penalties or {}
    result_employees = []
    total_gross = 0
    total_bonus = 0
    total_penalty = 0
    total_advance = 0
    total_nssf = 0
    total_net = 0

    # ── 提取当月年月前缀（循环前计算一次）──
    month_prefix = ''
    for d in list(shift_data) + list(attendance_data):
        dt = d.get('date', '')
        if dt: month_prefix = dt[:7]; break
    if not month_prefix:
        for dt in main_data.get('dates', []):
            if dt: month_prefix = dt[:7]; break
    calendar_days_global = 30
    if month_prefix:
        from calendar import monthrange
        _y, _m = int(month_prefix[:4]), int(month_prefix[5:7])
        _, calendar_days_global = monthrange(_y, _m)

    for emp in employees:
        eid = emp['id']
        name = emp['name']

        # 确定该员工的实际薪资类型（仅永久覆盖影响 effective_type，临时例外走日期区间逻辑）
        effective_type = emp['default_type']
        if eid in overrides:
            for o in overrides[eid]:
                has_range = bool(o.get('start_date', '') or o.get('end_date', ''))
                if not has_range and o.get('salary_type') in ('day_rate', 'monthly', 'piece_underground', 'piece_driller'):
                    effective_type = o['salary_type']

        pu = round(underground_sal.get(eid, 0))
        pd = round(driller_sal.get(eid, 0))
        dr = round(day_sal.get(eid, 0))
        ms = round(monthly_sal.get(eid, 0))
        advance = emp.get('advance_total', 0)

        # 只按有效类型发放薪资，其他轨道清零
        if eid not in has_date_range:
            if effective_type == 'piece_underground':
                pd = dr = ms = 0
            elif effective_type == 'piece_driller':
                pu = dr = ms = 0
            elif effective_type == 'day_rate':
                pu = pd = ms = 0
            elif effective_type == 'monthly':
                pu = pd = dr = 0
        else:
            # 有日期区间：逐日确定类型，只统计对应轨道的金额
            dt_map = date_type_map.get(eid, {})
            default = emp['default_type']
            all_dt = sorted(set(
                list(ug_daily.get(eid, {}).keys()) +
                list(driller_daily.get(eid, {}).keys())
            ))
            pu = pd = 0
            piece_days = 0
            ug_ed = ug_daily.get(eid, {})
            dr_ed = driller_daily.get(eid, {})
            for dt in all_dt:
                dtype = dt_map.get(dt, default)
                if dtype == 'piece_underground':
                    pu += round(ug_ed.get(dt, 0))
                    piece_days += 1
                elif dtype == 'piece_driller':
                    pd += round(dr_ed.get(dt, 0))
                    piece_days += 1
            # 日期区间覆盖涉及 day_rate/monthly 时，零化对方轨道
            _has_dr_date_range = any(
                o.get('salary_type') == 'day_rate' and (o.get('start_date') or o.get('end_date'))
                for o in overrides.get(eid, [])
            )
            _has_ms_date_range = any(
                o.get('salary_type') == 'monthly' and (o.get('start_date') or o.get('end_date'))
                for o in overrides.get(eid, [])
            )
            if _has_dr_date_range and not _has_ms_date_range:
                ms = 0
            if _has_ms_date_range and not _has_dr_date_range:
                dr = 0

        # ── 月薪统一扣减：计件覆盖天数 + A/L缺勤天数，按自然日比例扣除 ──
        if ms > 0 and effective_type == 'monthly':
            calendar_days = calendar_days_global
            # 统计计件覆盖天数（仅限有日期区间的临时计件例外）
            piece_days_for_ms = 0
            if eid in has_date_range:
                dt_map = date_type_map.get(eid, {})
                piece_days_for_ms = sum(1 for dtype in dt_map.values() if dtype in ('piece_underground', 'piece_driller'))
            # 统计 A/L 天数
            absent_days = 0
            if data_folder and os.path.exists(os.path.join(data_folder, 'kilwa.db')) and month_prefix:
                import sqlite3
                conn2 = sqlite3.connect(os.path.join(data_folder, 'kilwa.db'))
                abs_rows = conn2.execute(
                    "SELECT COUNT(*) FROM attendance_overrides WHERE employee_id=? AND status IN ('A','L') AND date LIKE ?",
                    (eid, month_prefix + '%')
                ).fetchone()
                conn2.close()
                if abs_rows and abs_rows[0] > 0:
                    absent_days = abs_rows[0]
            # 统一扣减
            if piece_days_for_ms > 0 or absent_days > 0:
                paid_days = max(0, calendar_days - piece_days_for_ms - absent_days)
                ms = round(ms * paid_days / calendar_days)

        gross = pu + pd + dr + ms
        bp = bonus_penalties.get(eid, {})
        bonus = int(bp.get('bonus', 0) or 0)
        penalty = int(bp.get('penalty', 0) or 0)
        nssf = round(gross * nssf_rate) if emp.get('nssf_enrolled', False) else 0
        net = gross + bonus - advance - nssf - penalty

        total_gross += gross
        total_bonus += bonus
        total_penalty += penalty
        total_advance += advance
        total_nssf += nssf
        total_net += net

        # 标记临时例外（仅显示与当前月份有重叠的）
        temp_exception = ''
        temp_overrides = []
        for o in overrides.get(eid, []):
            s, e = o.get('start_date',''), o.get('end_date','')
            if s or e:
                # 过滤：只保留与当前月份有重叠的临时例外
                if month_prefix:
                    import calendar as _cal
                    _y, _m = int(month_prefix[:4]), int(month_prefix[5:7])
                    _, _last = _cal.monthrange(_y, _m)
                    month_start = month_prefix + '-01'
                    month_end = f'{month_prefix}-{_last:02d}'
                    if (s and s > month_end) or (e and e < month_start):
                        continue  # 该例外完全在当前月份之外，跳过
                st_label = {'day_rate':'日薪','monthly':'月薪','piece_underground':'井下','piece_driller':'钻工'}.get(o.get('salary_type',''),'')
                note = f' {o.get("note","")}' if o.get('note') else ''
                temp_exception = f'{temp_exception}{st_label} {s}~{e}{note}  '
                temp_overrides.append({
                    'id': o.get('id'),
                    'label': f'{st_label} {s}~{e}{note}',
                    'salary_type': o.get('salary_type', ''),
                    'start_date': s,
                    'end_date': e,
                    'note': o.get('note', ''),
                })

        result_employees.append({
            'employee_id': eid,
            'name': name,
            'salary_type': effective_type,
            'piece_underground': round(pu),
            'piece_driller': round(pd),
            'day_rate': round(dr),
            'monthly': round(ms),
            'gross': round(gross),
            'bonus': bonus,
            'penalty': penalty,
            'advance': round(advance),
            'nssf': round(nssf),
            'net': round(net),
            'temp_exception': temp_exception,
            'temp_overrides': temp_overrides,
        })

    return {
        'employees': result_employees,
        'total_gross': round(total_gross),
        'total_bonus': round(total_bonus),
        'total_penalty': round(total_penalty),
        'total_advance': round(total_advance),
        'total_nssf': round(total_nssf),
        'total_net': round(total_net),
        'duplications': duplications,
        # 逐日计件原始数据（用于核对面板逐日对比）
        'ug_daily': {eid: {dt: round(amt) for dt, amt in ds.items()} for eid, ds in ug_daily.items()},
        'driller_daily': {eid: {dt: round(amt) for dt, amt in ds.items()} for eid, ds in driller_daily.items()},
    }

# ═══════════════════════════════════════════════════════════
#  5. 逐日工资明细
# ═══════════════════════════════════════════════════════════

def compute_daily_breakdown(main_data, employees, overrides=None, exclusions=None, pricing=None, data_folder=None):
    """
    计算每个员工每天的工资明细（基于权威计算函数）
    返回: { employee_id: { 'name': str, 'department': str, 'salary_type': str,
                            'daily': { '2026-05-01': amount, ... }, 'total': int } }
    """
    overrides = overrides or {}
    exclusions = exclusions or set()
    pricing = pricing or {}
    up = pricing.get('underground_prices', PRICES_UNDERGROUND)
    dp = pricing.get('driller_prices', PRICES_DRILLER)

    import sys, os, sqlite3
    mod = sys.modules[__name__]
    old_up, old_dp = mod.PRICES_UNDERGROUND, mod.PRICES_DRILLER
    mod.PRICES_UNDERGROUND = up
    mod.PRICES_DRILLER = dp

    shift_data = main_data.get('shift_production', [])
    driller_data = main_data.get('driller_production', [])
    attendance_data = main_data.get('attendance', [])

    try:
        # A/L + 日期区间排除（与 calculate_all 完全一致）
        att_exclusions = set()
        has_date_range = set()
        range_exclusions = set()
        date_range_overrides = {}
        if data_folder:
            db_path = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                for r in conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L')").fetchall():
                    att_exclusions.add((r[0], r[1]))
                conn.close()

        for eid, ovs in overrides.items():
            for o in ovs:
                st, start, end = o.get('salary_type',''), o.get('start_date','') or '', o.get('end_date','') or ''
                if st in ('day_rate','monthly') and (start or end):
                    has_date_range.add(eid)
                    for day in shift_data:
                        dt = day['date']
                        if start and dt < start: continue
                        if end and dt > end: continue
                        range_exclusions.add((eid, dt))
                    date_range_overrides[eid] = (start, end)

        combined_excl = exclusions | att_exclusions | range_exclusions

        # 逐日类型排除（与 calculate_all 一致）
        all_shift_dates = sorted(set(d['date'] for d in shift_data if d.get('date')))
        ug_type_excl = set()
        dr_type_excl = set()
        for emp in employees:
            eid = emp['id']
            # 永久类型（忽略日期区间覆盖）
            perm_type = emp['default_type']
            if eid in overrides:
                for o in overrides[eid]:
                    st = o.get('salary_type', '')
                    s, e = o.get('start_date') or '', o.get('end_date') or ''
                    if st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller') and not (s or e):
                        perm_type = st
            date_range_types = {}
            for o in overrides.get(eid, []):
                st = o.get('salary_type', '')
                start = o.get('start_date') or ''
                end = o.get('end_date') or ''
                if st in ('piece_underground', 'piece_driller', 'day_rate', 'monthly') and (start or end):
                    for dt in all_shift_dates:
                        if (not start or dt >= start) and (not end or dt <= end):
                            date_range_types[dt] = st
            for dt in all_shift_dates:
                dtype = date_range_types.get(dt, perm_type)
                if dtype != 'piece_underground':
                    ug_type_excl.add((eid, dt))
                if dtype != 'piece_driller':
                    dr_type_excl.add((eid, dt))

        # 用权威函数计算逐日数据
        ug_sal, ug_daily, ug_shifts = calc_underground_piece(shift_data, combined_excl | ug_type_excl, {'permanent': set()}, data_folder)
        dr_sal, dups, dr_daily = calc_driller_piece(driller_data, data_folder, combined_excl | dr_type_excl)
        day_sal = calc_day_salary(attendance_data, employees, overrides, data_folder, shift_data, date_range_overrides)
        month_sal = calc_monthly_salary(employees, overrides)

        # 日薪的逐日分摊
        ds_daily = defaultdict(lambda: defaultdict(float))
        # 加载手动出勤覆盖（A/L/P 全量，用于与 calc_day_salary 完全一致的过滤）
        att_all = {}
        if data_folder:
            import sqlite3, os
            dbp = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(dbp):
                conn = sqlite3.connect(dbp)
                try:
                    for r in conn.execute("SELECT employee_id, date, status FROM attendance_overrides").fetchall():
                        att_all[(r[0], r[1])] = r[2]
                except: pass
                conn.close()
        emp_map = {e['id']: e for e in employees}
        for eid, total in day_sal.items():
            # 收集出勤日期——严格与 calc_day_salary 三来源一致
            # 用计数器而非 set：同日白班+夜班 = 2次（与 calc_day_salary 双重计数一致）
            date_counts = defaultdict(int)
            counted = set()
            # 来源1：日薪出勤表（含 date_range_overrides 过滤）
            for d in attendance_data:
                dt = d.get('date','')
                for e in d.get('normal', []):
                    if make_employee_id(e) != eid:
                        continue
                    # 按 (eid, date) 去重
                    if (eid, dt) in counted:
                        continue
                    if eid in date_range_overrides:
                        dstart, dend = date_range_overrides[eid]
                        if dstart and dt < dstart: continue
                        if dend and dt > dend: continue
                    if att_all.get((eid, dt)) in ('A', 'L'):
                        continue
                    counted.add((eid, dt))
                    date_counts[dt] += 1
            # 来源2：产量表（仅对 is_overridden_day_rate 的员工——与 calc_day_salary 一致）
            def _has_day_rate_override(eid, dt):
                for o in overrides.get(eid, []):
                    if o.get('salary_type') == 'day_rate':
                        s, e = o.get('start_date') or '', o.get('end_date') or ''
                        ov_dr = o.get('day_rate', 0)
                        if s or e:
                            if (not s or dt >= s) and (not e or dt <= e) and ov_dr > 0:
                                return True
                        elif not s and not e:
                            return True
                return False
            for d in shift_data:
                dt = d.get('date','')
                for e in d.get('day_emps', []) + d.get('night_emps', []):
                    if make_employee_id(e) != eid:
                        continue
                    if not _has_day_rate_override(eid, dt):
                        continue
                    # 按 (eid, date) 去重
                    if (eid, dt) in counted:
                        continue
                    if att_all.get((eid, dt)) in ('A', 'L'):
                        continue
                    counted.add((eid, dt))
                    date_counts[dt] += 1  # 同日白班+夜班计2次，与 calc_day_salary 一致
            # 来源3：手动 P 覆盖（仅限当月日期）
            _p_month_prefixes = set()
            for _d in list(attendance_data) + list(shift_data):
                _dd = _d.get('date', '')
                if _dd: _p_month_prefixes.add(_dd[:7])
            for (peid, pdt), st in att_all.items():
                if peid == eid and st == 'P' and (eid, pdt) not in counted:
                    if _p_month_prefixes and pdt[:7] not in _p_month_prefixes:
                        continue
                    date_counts[pdt] += 1
            if not date_counts:
                continue
            # 逐日确定日薪基数 × 当日次数（支持日期区间覆盖）
            for dt, count in sorted(date_counts.items()):
                dr = 0
                for o in overrides.get(eid, []):
                    if o.get('salary_type') == 'day_rate':
                        start = o.get('start_date') or ''
                        end = o.get('end_date') or ''
                        ov_dr = o.get('day_rate', 0)
                        if ov_dr > 0:
                            if (not start or dt >= start) and (not end or dt <= end):
                                dr = ov_dr
                                break
                if dr == 0 and eid in emp_map:
                    dr = emp_map[eid].get('day_rate', 0)
                if dr > 0:
                    ds_daily[eid][dt] += dr * count  # count>1 表示同日多班次

        # 月薪的逐日分摊（按自然月日历天数，与 calculate_all 对齐）
        ms_daily = defaultdict(lambda: defaultdict(float))
        # 确定当月自然月全部日期
        _all_data_dates = sorted(set(
            d['date'] for d in shift_data + attendance_data + driller_data if d.get('date')
        ))
        _ym = ''
        if _all_data_dates:
            _ym = _all_data_dates[0][:7]
            _year, _month = int(_ym[:4]), int(_ym[5:7])
            _, _last_day = monthrange(_year, _month)
            ms_dates = set(f"{_year}-{_month:02d}-{_day:02d}" for _day in range(1, _last_day + 1))
        else:
            ms_dates = set()
        # 当月自然日数（与 calculate_all 一致，用于 A/L ��例计算）
        _calendar_days = _last_day if _ym else 30
        # 加载当月 A/L 覆盖
        ms_absent = defaultdict(set)
        if data_folder:
            import sqlite3 as _sq3, os as _os
            dbp = _os.path.join(data_folder, 'kilwa.db')
            if _os.path.exists(dbp):
                conn = _sq3.connect(dbp)
                try:
                    for r in conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L')").fetchall():
                        ms_absent[r[0]].add(r[1])
                except: pass
                conn.close()
        # 构建与 calculate_all 对齐的 adjusted month_sal（含 A/L 比例扣减）
        adjusted_month_sal = {}
        for eid, base_total in month_sal.items():
            emp = emp_map.get(eid)
            if emp:
                eff_type = emp.get('override_type') or emp.get('default_type', '')
                if eff_type == 'monthly' and base_total > 0 and _ym:
                    # 完全复用 calculate_all 的 A/L 扣减逻辑
                    absent_in_data = 0
                    if data_folder:
                        import sqlite3 as _sq3b, os as _osb
                        _dbp2 = _osb.path.join(data_folder, 'kilwa.db')
                        if _osb.path.exists(_dbp2):
                            _conn2 = _sq3b.connect(_dbp2)
                            try:
                                _abs = _conn2.execute(
                                    "SELECT COUNT(*) FROM attendance_overrides WHERE employee_id=? AND status IN ('A','L') AND date LIKE ?",
                                    (eid, _ym + '%')
                                ).fetchone()
                                if _abs: absent_in_data = _abs[0]
                            except: pass
                            _conn2.close()
                    if absent_in_data > 0:
                        _ratio = max(0, (_calendar_days - absent_in_data) / _calendar_days)
                        base_total = round(base_total * _ratio)
            adjusted_month_sal[eid] = base_total
        # 按自然月日历均摊（A/L 日 = 0）
        for eid, total in adjusted_month_sal.items():
            absent_days = len(ms_absent.get(eid, set()) & ms_dates)
            adj_days = max(len(ms_dates) - absent_days, 1)
            per_base = total // adj_days
            remainder = total % adj_days
            day_idx = 0
            for dt in sorted(ms_dates):
                if dt in ms_absent.get(eid, set()):
                    ms_daily[eid][dt] = 0
                else:
                    extra = 1 if day_idx < remainder else 0
                    ms_daily[eid][dt] += per_base + extra
                    day_idx += 1

        # 合并最终结果——逐日按 effective_type 选轨（与 calculate_all 一致）
        # 合并自然月日期 + 数据日期，确保月薪员工覆盖全部日历天
        _data_dates = set(d['date'] for d in shift_data + attendance_data + driller_data if d.get('date'))
        all_dates = sorted(ms_dates | _data_dates) if ms_dates else sorted(_data_dates)
        result = {}

        for emp in employees:
            eid = emp['id']
            # 确定永久 effective_type（仅无日期区间的覆盖影响基础类型）
            eff = emp['default_type']
            if eid in overrides:
                for o in overrides[eid]:
                    has_range = bool(o.get('start_date', '') or o.get('end_date', ''))
                    if not has_range and o.get('salary_type') in ('day_rate','monthly','piece_underground','piece_driller'):
                        eff = o['salary_type']

            # 构建逐日 effective_type 映射（包含 piece 类临时例外）
            per_date_type = {}
            if eid in overrides:
                for o in overrides[eid]:
                    s = o.get('start_date','') or ''
                    e = o.get('end_date','') or ''
                    if s or e:
                        st = o.get('salary_type','')
                        if st in ('piece_underground','piece_driller','day_rate','monthly'):
                            for dt in all_dates:
                                if (not s or dt >= s) and (not e or dt <= e):
                                    per_date_type[dt] = st

            # 构建 temp_overrides（仅显示与当前月份有重叠的）
            temp_override_list = []
            _mb_prefix = ''
            for _d in all_dates:
                if _d:
                    _mb_prefix = _d[:7]
                    break
            if eid in overrides:
                for o in overrides[eid]:
                    s, e = o.get('start_date',''), o.get('end_date','')
                    if s or e:
                        # 过滤：只保留与当前月份有重叠的临时例外
                        if _mb_prefix:
                            import calendar as _cal2
                            _y2, _m2 = int(_mb_prefix[:4]), int(_mb_prefix[5:7])
                            _, _last2 = _cal2.monthrange(_y2, _m2)
                            _ms2 = _mb_prefix + '-01'
                            _me2 = f'{_mb_prefix}-{_last2:02d}'
                            if (s and s > _me2) or (e and e < _ms2):
                                continue
                        st_label = {'day_rate':'日薪','monthly':'月薪','piece_underground':'井下','piece_driller':'钻工'}.get(o.get('salary_type',''),'')
                        note = f' {o.get("note","")}' if o.get('note') else ''
                        temp_override_list.append({
                            'id': o.get('id'),
                            'label': f'{st_label} {s}~{e}{note}',
                            'salary_type': o.get('salary_type', ''),
                            'start_date': s,
                            'end_date': e,
                            'note': o.get('note', ''),
                        })

            daily = defaultdict(float)
            shifts_info = {}

            # 逐日按 effective_type 选取对应轨道数据
            for dt in all_dates:
                dt_eff = per_date_type.get(dt, eff)

                if dt_eff == 'piece_underground':
                    amt = ug_daily.get(eid, {}).get(dt, 0)
                    if amt > 0:
                        daily[dt] = round(amt)
                        s = ug_shifts.get(eid, {}).get(dt, '')
                        if s: shifts_info[dt] = s
                elif dt_eff == 'piece_driller':
                    amt = dr_daily.get(eid, {}).get(dt, 0)
                    if amt > 0:
                        daily[dt] = round(amt)
                elif dt_eff == 'day_rate':
                    amt = ds_daily.get(eid, {}).get(dt, 0)
                    if amt > 0:
                        daily[dt] = round(amt)
                elif dt_eff == 'monthly':
                    amt = ms_daily.get(eid, {}).get(dt, 0)
                    if dt in ms_absent.get(eid, set()):
                        daily[dt] = 0
                    elif amt > 0:
                        daily[dt] = round(amt)

            if daily:
                result[eid] = {
                    'name': emp['name'],
                    'department': emp.get('department', ''),
                    'salary_type': eff,
                    'effective_type': eff,
                    'daily': dict(daily),
                    'daily_shifts': shifts_info,
                    'total': round(sum(daily.values())),
                    'override_dates': sorted(per_date_type.keys()) if per_date_type else [],
                    'temp_overrides': temp_override_list,
                }

    finally:
        mod.PRICES_UNDERGROUND = old_up
        mod.PRICES_DRILLER = old_dp

    return result
