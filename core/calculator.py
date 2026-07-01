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
import os
from .namematch import canonical, make_employee_id, is_driller_leader, DRILLER_LEADERS

# ── 单价 ─────────────────────────────────────────────────
PRICES_UNDERGROUND = {'NICKEL（H）': 6000, 'NICKEL（L）': 5000, 'MAWE': 4000}
PRICES_DRILLER = {'NICKEL（H）': 5000, 'NICKEL（L）': 4000, 'MAWE': 3000}
PRICE_CRUSH = 300  # TZS/bag

TODAY = date.today()
CURRENT_MONTH = TODAY.month
CURRENT_YEAR = TODAY.year

# ═══════════════════════════════════════════════════════════
#  1. 井下计件计算
# ═══════════════════════════════════════════════════════════

def calc_underground_piece(shift_data, exclusions, override_excludes, data_folder=None, all_attendance_pairs=None):
    """
    计算井下工人计件工资
    白班+夜班合并，总金额均分给出勤人员
    返回: { employee_id: total_salary }, { employee_id: { date: amount } }
    """
    result = defaultdict(float)
    daily = defaultdict(lambda: defaultdict(float))
    daily_shifts = defaultdict(lambda: defaultdict(set))  # daily_shifts[eid][date] = {'D','N'}

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

    # 构建出勤日集合（使用外部传入的全局集合，或内部构建）
    if all_attendance_pairs is not None:
        attendance_pairs = all_attendance_pairs
    else:
        attendance_pairs = set()
        for day in shift_data:
            dt = day.get('date', '')
            for e in day.get('day_emps', []) + day.get('night_emps', []):
                eid_check = make_employee_id(e)
                if eid_check:
                    attendance_pairs.add((eid_check, dt))

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
            # 手动加入白班的人（排除 A/L：请假/旷工人不加入分配，且必须有出勤记录）
            existing_ids = {make_employee_id(e) for e in valid if make_employee_id(e)}
            for (eid, dt), sh in shift_adds.items():
                if dt == date_str and sh == 'D' and eid not in existing_ids \
                        and (eid, date_str) not in exclusions \
                        and (eid, date_str) in attendance_pairs:
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
            # 手动加入夜班的人（排除 A/L，且必须有出勤记录）
            existing_ids = {make_employee_id(e) for e in valid if make_employee_id(e)}
            for (eid, dt), sh in shift_adds.items():
                if dt == date_str and sh == 'N' and eid not in existing_ids \
                        and (eid, date_str) not in exclusions \
                        and (eid, date_str) in attendance_pairs:
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
#  1b. 破碎计件计算
# ═══════════════════════════════════════════════════════════

def _enrich_crush_with_p_attendance(crush_data, employees, data_folder):
    """将手动标记 P 的破碎计件员工加入到当日破碎队人员列表中"""
    if not data_folder:
        return
    db_path = os.path.join(data_folder, 'kilwa.db')
    if not os.path.exists(db_path):
        return
    # 收集破碎计件类型的所有员工 ID→名称 映射
    crush_eids = {}
    for emp in employees:
        pt = emp.get('override_type') or emp.get('default_type', '')
        if pt == 'piece_crush':
            crush_eids[emp['id']] = emp.get('name', '')
    if not crush_eids:
        return
    # 查询 attendance_overrides 中 status='P' 的记录
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT employee_id, date FROM attendance_overrides WHERE status='P'"
    ).fetchall()
    conn.close()
    # 按日期收集应加入的额外员工名称
    extra_by_date = defaultdict(list)
    for eid, dt in rows:
        name = crush_eids.get(eid)
        if name:
            extra_by_date[dt].append(name)
    if not extra_by_date:
        return
    # 注入到 crush_data 的每条记录的 personnel 中
    for day in crush_data:
        dt = day.get('date', '')
        extra_names = extra_by_date.get(dt, [])
        if extra_names:
            existing = set(day.get('personnel', []))
            for name in extra_names:
                if name not in existing:
                    day['personnel'].append(name)

def calc_crush_piece(crush_data, exclusions, override_excludes, data_folder=None, all_attendance_pairs=None):
    """
    计算破碎计件工资
    - 同一天多条记录：各自独立均分，人员当日金额为各记录分摊之和
    - A/L 排除：被标记 A/L 的破碎队成员从当日计件分配中排除
    返回: (result_dict, daily_dict, daily_shifts_dict)
    """
    result = defaultdict(float)
    daily = defaultdict(lambda: defaultdict(float))
    daily_shifts = defaultdict(lambda: defaultdict(set))

    if all_attendance_pairs is not None:
        attendance_pairs = all_attendance_pairs
    else:
        attendance_pairs = set()
        for day in crush_data:
            dt = day.get('date', '')
            for e in day.get('personnel', []):
                eid = make_employee_id(e)
                if eid:
                    attendance_pairs.add((eid, dt))

    for day in crush_data:
        date_str = day['date']
        bags = day.get('bags', 0) or 0
        personnel = day.get('personnel', [])

        if not personnel or bags <= 0:
            continue

        total = bags * PRICE_CRUSH
        valid = _filter_valid(personnel, exclusions, override_excludes, date_str)
        # 按 eid 去重
        seen = set()
        deduped = []
        for e in valid:
            eid = make_employee_id(e)
            if eid and eid not in seen:
                seen.add(eid)
                deduped.append(e)
        valid = deduped

        if valid and total > 0:
            per = total / len(valid)
            for e in valid:
                eid = make_employee_id(e)
                if eid:
                    result[eid] += per
                    daily[eid][date_str] += per
                    daily_shifts[eid][date_str].add('C')

    return dict(result), {eid: dict(d) for eid, d in daily.items()}, {eid: {dt: ''.join(sorted(s)) for dt, s in sh.items()} for eid, sh in daily_shifts.items()}

# ═══════════════════════════════════════════════════════════
#  2. 钻工计件计算
# ═══════════════════════════════════════════════════════════

def calc_driller_piece(driller_data, data_folder=None, exclusions=None, att_exclusions=None, all_attendance_pairs=None):
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
    exclusions = exclusions or set()

    # 使用传入的 A/L 排除（避免重复查询数据库）
    att_exclusions = att_exclusions or set()

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

    # 构建出勤日集合（使用外部传入的全局集合，或内部构建）
    if all_attendance_pairs is not None:
        driller_attendance = all_attendance_pairs
    else:
        driller_attendance = set()
        for d in driller_data:
            dt = d.get('date', '')
            cap_id = make_employee_id(d.get('captain', ''))
            if cap_id:
                driller_attendance.add((cap_id, dt))
            for m in d.get('members', []):
                mid = make_employee_id(m)
                if mid:
                    driller_attendance.add((mid, dt))

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

        # 统计手动加入钻工组的人数（排除 A/L 缺勤者 + 空出勤者）
        driller_add_count = sum(1 for (eid, dt), cp in driller_adds.items()
                                if dt == date_str and cp == captain and eid != cap_norm
                                and (eid, date_str) not in combined_exclusions
                                and (eid, date_str) in driller_attendance)

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

        # 手动加入钻工组的人（排除 A/L 缺勤者 + 空出勤者）
        for (eid, dt), cp in driller_adds.items():
            if dt == date_str and cp == captain and eid != cap_norm \
                    and (eid, date_str) not in combined_exclusions \
                    and (eid, date_str) in driller_attendance:
                amt = per_share * 1
                result[eid] += amt
                daily[eid][dt] += amt

    return dict(result), [], {eid: dict(d) for eid, d in daily.items()}

# ═══════════════════════════════════════════════════════════
#  3. 日薪计算
# ═══════════════════════════════════════════════════════════

def calc_day_salary(attendance_data, employees, overrides, data_folder=None, shift_data=None, date_range_overrides=None, month_prefix=None):
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

    # 来源3：手动 P 覆盖（仅限当月）
    _month_prefixes = set()
    for d in list(attendance_data) + list(shift_data or []):
        dt = d.get('date', '')
        if dt:
            _month_prefixes.add(dt[:7])
    _effective_prefixes = _month_prefixes
    if not _effective_prefixes and month_prefix:
        _effective_prefixes = {month_prefix}
    for key, status in att_overrides.items():
        if status == 'P':
            parts = key.split('|')
            if len(parts) == 2:
                eid, dt = parts[0], parts[1]
                if _effective_prefixes and dt[:7] not in _effective_prefixes:
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
def calculate_all(main_data, employees, overrides=None, exclusions=None, pricing=None, data_folder=None, bonus_penalties=None):
    overrides = overrides or {}
    exclusions = exclusions or set()
    pricing = pricing or {}
    up = pricing.get('underground_prices', PRICES_UNDERGROUND)
    dp = pricing.get('driller_prices', PRICES_DRILLER)
    nssf_rate = pricing.get('nssf_rate', 0.10)

    import sys, sqlite3
    mod = sys.modules[__name__]
    old_up, old_dp, old_cr = mod.PRICES_UNDERGROUND, mod.PRICES_DRILLER, mod.PRICE_CRUSH
    mod.PRICES_UNDERGROUND = up
    mod.PRICES_DRILLER = dp
    mod.PRICE_CRUSH = pricing.get('crush_price', PRICE_CRUSH)

    try:
        att_exclusions = set()
        if data_folder:
            db_path = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                for r in conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L')").fetchall():
                    att_exclusions.add((r[0], r[1]))
                conn.close()

        shift_data = main_data.get('shift_production', [])
        driller_data = main_data.get('driller_production', [])
        attendance_data = main_data.get('attendance', [])
        crush_data = main_data.get('crush_production', [])

        # ── 构建全局出勤集合（包含三个数据源）──
        all_attendance_pairs = set()
        for day in shift_data:
            dt = day.get('date', '')
            if not dt: continue
            for e in day.get('day_emps', []) + day.get('night_emps', []):
                eid_check = make_employee_id(e)
                if eid_check:
                    all_attendance_pairs.add((eid_check, dt))
        for d in driller_data:
            dt = d.get('date', '')
            if not dt: continue
            cap_id = make_employee_id(d.get('captain', ''))
            if cap_id:
                all_attendance_pairs.add((cap_id, dt))
            for m in d.get('members', []):
                mid = make_employee_id(m)
                if mid:
                    all_attendance_pairs.add((mid, dt))
        for day in attendance_data:
            dt = day.get('date', '')
            if not dt: continue
            for e in day.get('normal', []):
                if isinstance(e, dict):
                    eid_check = e.get('employee_id')
                else:
                    eid_check = make_employee_id(e)
                if eid_check:
                    all_attendance_pairs.add((eid_check, dt))

        for day in crush_data:
            dt = day.get('date', '')
            if not dt: continue
            for e in day.get('personnel', []):
                eid = make_employee_id(e)
                if eid:
                    all_attendance_pairs.add((eid, dt))

        # ── 统一逐日类型映射 per_date_type[eid][date] = salary_type ──
        per_date_type = defaultdict(dict)
        range_exclusions = set()
        all_dates = sorted(set(
            list(d['date'] for d in shift_data if d.get('date')) +
            list(d['date'] for d in driller_data if d.get('date')) +
            list(d['date'] for d in attendance_data if d.get('date'))
        ))
        for eid, ovs in overrides.items():
            for o in ovs:
                st = o.get('salary_type', '')
                start = o.get('start_date') or ''
                end = o.get('end_date') or ''
                if st not in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                    continue
                if not (start or end):
                    continue
                for dt in all_dates:
                    if start and dt < start: continue
                    if end and dt > end: continue
                    per_date_type[eid][dt] = st
                if st in ('day_rate', 'monthly'):
                    for day in shift_data:
                        dt = day['date']
                        if start and dt < start: continue
                        if end and dt > end: continue
                        range_exclusions.add((eid, dt))

        # 临时计件例外：检查该员工当天是否有实际出勤记录（三个数据源都查）
        for eid in list(per_date_type.keys()):
            for dt, dtype in list(per_date_type[eid].items()):
                if dtype in ('piece_underground', 'piece_driller', 'piece_crush'):
                    if (eid, dt) not in all_attendance_pairs:
                        att_exclusions.add((eid, dt))

        combined_exclusions = exclusions | att_exclusions | range_exclusions

        all_shift_dates = sorted(set(
            list(d['date'] for d in shift_data if d.get('date')) +
            list(d['date'] for d in crush_data if d.get('date'))
        ))
        ug_type_excl = set()
        dr_type_excl = set()
        cr_type_excl = set()
        for emp in employees:
            eid = emp['id']
            perm_type = emp['default_type']
            if eid in overrides:
                for o in overrides[eid]:
                    st = o.get('salary_type', ''); s, e = o.get('start_date') or '', o.get('end_date') or ''
                    if st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush') and not (s or e):
                        perm_type = st
            for dt in all_shift_dates:
                dtype = per_date_type.get(eid, {}).get(dt, perm_type)
                if dtype != 'piece_underground': ug_type_excl.add((eid, dt))
                if dtype != 'piece_driller': dr_type_excl.add((eid, dt))
                if dtype != 'piece_crush': cr_type_excl.add((eid, dt))

        underground_sal, ug_daily, ug_shifts = calc_underground_piece(shift_data, combined_exclusions | ug_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs)
        driller_sal, _, driller_daily = calc_driller_piece(driller_data, data_folder, combined_exclusions | dr_type_excl, att_exclusions=att_exclusions, all_attendance_pairs=all_attendance_pairs)
        _enrich_crush_with_p_attendance(crush_data, employees, data_folder)
        crush_sal, crush_daily, crush_shifts = calc_crush_piece(crush_data, combined_exclusions | cr_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs)
        monthly_base = calc_monthly_salary(employees, overrides)
    finally:
        mod.PRICES_UNDERGROUND = old_up
        mod.PRICES_DRILLER = old_dp
        mod.PRICE_CRUSH = old_cr

    month_prefix = ''
    for d in list(shift_data) + list(attendance_data):
        dt = d.get('date', '')
        if dt: month_prefix = dt[:7]; break
    if not month_prefix:
        for dt in main_data.get('dates', []):
            if dt: month_prefix = dt[:7]; break
    working_days = 26  # 月薪按 26 天均分

    att_overrides = {}
    manual_p = defaultdict(set)
    if data_folder:
        db_path = os.path.join(data_folder, 'kilwa.db')
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            for r in conn.execute("SELECT employee_id, date, status FROM attendance_overrides").fetchall():
                att_overrides[(r[0], r[1])] = r[2]
                if r[2] == 'P': manual_p[r[0]].add(r[1])
            conn.close()

    emp_map = {e['id']: e for e in employees}
    day_rate_map = {}
    for eid in emp_map:
        dr = 0
        for o in overrides.get(eid, []):
            if o.get('salary_type') == 'day_rate' and o.get('day_rate', 0) > 0:
                dr = o['day_rate']
        if dr == 0: dr = emp_map[eid].get('day_rate', 0)
        if dr > 0: day_rate_map[eid] = dr

    present_dates = defaultdict(set)
    for d in attendance_data:
        dt = d.get('date', '')
        for e in d.get('normal', []):
            if isinstance(e, dict):
                eid = e.get('employee_id')
            else:
                eid = make_employee_id(e)
            if eid: present_dates[eid].add(dt)
    for d in shift_data:
        dt = d.get('date', '')
        for e in d.get('day_emps', []) + d.get('night_emps', []):
            eid = make_employee_id(e)
            if eid: present_dates[eid].add(dt)
    for d in driller_data:
        dt = d.get('date', '')
        cap_id = make_employee_id(d.get('captain', ''))
        if cap_id: present_dates[cap_id].add(dt)
        for m in d.get('members', []):
            mid = make_employee_id(m)
            if mid: present_dates[mid].add(dt)

    for d in crush_data:
        dt = d.get('date', '')
        for e in d.get('personnel', []):
            eid = make_employee_id(e)
            if eid: present_dates[eid].add(dt)

    for eid, dates in manual_p.items():
        if month_prefix:
            present_dates[eid] |= {dt for dt in dates if dt[:7] == month_prefix}
        else:
            present_dates[eid] |= dates

    # top department monthly: add 26 working days for full attendance
    if month_prefix:
        _y2, _m2 = int(month_prefix[:4]), int(month_prefix[5:7])
        for emp in employees:
            if emp.get("department") == "ENPRIZON LINDI PROJECT" and (emp.get("override_type") == "monthly" or emp.get("default_type") == "monthly"):
                eid = emp["id"]
                for d_day in range(1, 27):
                    present_dates[eid].add(f"{_y2}-{_m2:02d}-{d_day:02d}")

    final_dates = sorted(set(
        list(d['date'] for d in shift_data + attendance_data + driller_data + crush_data if d.get('date'))
    ))

    bonus_penalties = bonus_penalties or {}
    result_employees = []

    for emp in employees:
        eid = emp['id']
        eff_type = emp.get('override_type') or emp['default_type']
        pu = pd_val = dr_total = ms_total = cr_total = 0.0
        monthly_present_count = 0

        for dt in final_dates:
            dtype = per_date_type.get(eid, {}).get(dt, eff_type)
            absent = att_overrides.get((eid, dt)) in ('A', 'L')

            if dtype == 'piece_underground' and not absent:
                pu += ug_daily.get(eid, {}).get(dt, 0)
            elif dtype == 'piece_driller' and not absent:
                pd_val += driller_daily.get(eid, {}).get(dt, 0)
            elif dtype == 'piece_crush' and not absent:
                cr_total += crush_daily.get(eid, {}).get(dt, 0)
            elif dtype == 'day_rate' and not absent and dt in present_dates[eid]:
                dr_total += day_rate_map.get(eid, 0)
            elif dtype == 'monthly' and not absent and dt in present_dates[eid]:
                monthly_present_count += 1

        # 月薪：实际出勤 >= 26天封顶为满勤基薪
        mb = monthly_base.get(eid, 0)
        if mb > 0 and monthly_present_count > 0:
            effective_days = min(monthly_present_count, working_days)
            ms_total = effective_days * (mb / working_days)

        pu = round(pu); pd_val = round(pd_val); dr_total = round(dr_total); ms_total = round(ms_total); cr_total = round(cr_total)
        gross = pu + pd_val + dr_total + ms_total + cr_total
        advance = emp.get('advance_total', 0)
        bp = bonus_penalties.get(eid, {})
        bonus = int(bp.get('bonus', 0) or 0)
        penalty = int(bp.get('penalty', 0) or 0)
        nssf = round(gross * nssf_rate) if emp.get('nssf_enrolled', False) else 0
        net = gross + bonus - advance - nssf - penalty

        temp_exception = ''
        temp_overrides = []
        for o in overrides.get(eid, []):
            s, e = o.get('start_date', ''), o.get('end_date', '')
            if s or e:
                if month_prefix:
                    import calendar as _cal
                    _y3, _m3 = int(month_prefix[:4]), int(month_prefix[5:7])
                    _, _last = _cal.monthrange(_y3, _m3)
                    month_start = month_prefix + '-01'
                    month_end = f'{month_prefix}-{_last:02d}'
                    if (s and s > month_end) or (e and e < month_start):
                        continue
                st_label = {'day_rate': '日薪', 'monthly': '月薪', 'piece_underground': '井下', 'piece_driller': '钻工', 'piece_crush': '破碎'}.get(o.get('salary_type', ''), '')
                note = f' {o.get("note", "")}' if o.get('note') else ''
                temp_exception += f'{st_label} {s}~{e}{note}  '
                temp_overrides.append({
                    'id': o.get('id'), 'salary_type': o.get('salary_type', ''),
                    'start_date': s, 'end_date': e, 'note': o.get('note', ''),
                    'label': f'{st_label} {s}~{e}{note}',
                })

        result_employees.append({
            'employee_id': eid, 'name': emp['name'], 'salary_type': eff_type,
            'piece_underground': pu, 'piece_driller': pd_val,
            'piece_crush': cr_total, 'day_rate': dr_total, 'monthly': ms_total,
            'gross': gross, 'bonus': bonus, 'penalty': penalty,
            'advance': round(advance), 'nssf': nssf, 'net': net,
            'temp_exception': temp_exception, 'temp_overrides': temp_overrides,
        })

    return {
        'employees': result_employees,
        'total_gross': sum(e['gross'] for e in result_employees),
        'total_bonus': sum(e['bonus'] for e in result_employees),
        'total_penalty': sum(e['penalty'] for e in result_employees),
        'total_advance': sum(e['advance'] for e in result_employees),
        'total_nssf': sum(e['nssf'] for e in result_employees),
        'total_net': sum(e['net'] for e in result_employees),
        'duplications': [],
        'ug_daily': {eid: {dt: round(amt) for dt, amt in ds.items()} for eid, ds in ug_daily.items()},
        'driller_daily': {eid: {dt: round(amt) for dt, amt in ds.items()} for eid, ds in driller_daily.items()},
        'crush_daily': {eid: {dt: round(amt) for dt, amt in ds.items()} for eid, ds in crush_daily.items()},
    }


# ═══════════════════════════════════════════════════════════
#  日工资明细（复用逐日单轨逻辑）
# ═══════════════════════════════════════════════════════════

def compute_daily_breakdown(main_data, employees, overrides=None, exclusions=None, pricing=None, data_folder=None):
    """逐日工资明细，与 calculate_all 共用 per_date_type + 子函数结果"""
    overrides = overrides or {}
    exclusions = exclusions or set()
    pricing = pricing or {}
    up = pricing.get('underground_prices', PRICES_UNDERGROUND)
    dp = pricing.get('driller_prices', PRICES_DRILLER)

    import sys, os, sqlite3
    mod = sys.modules[__name__]
    old_up, old_dp, old_cr = mod.PRICES_UNDERGROUND, mod.PRICES_DRILLER, mod.PRICE_CRUSH
    mod.PRICES_UNDERGROUND = up
    mod.PRICES_DRILLER = dp
    mod.PRICE_CRUSH = pricing.get('crush_price', PRICE_CRUSH)

    shift_data = main_data.get('shift_production', [])
    driller_data = main_data.get('driller_production', [])
    attendance_data = main_data.get('attendance', [])
    crush_data = main_data.get('crush_production', [])

    try:
        att_exclusions = set()
        if data_folder:
            dbp = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(dbp):
                conn = sqlite3.connect(dbp)
                for r in conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L')").fetchall():
                    att_exclusions.add((r[0], r[1]))
                conn.close()

        # ── 构建全局出勤集合（包含三个数据源）──
        all_attendance_pairs = set()
        for day in shift_data:
            dt = day.get('date', '')
            if not dt: continue
            for e in day.get('day_emps', []) + day.get('night_emps', []):
                eid_check = make_employee_id(e)
                if eid_check: all_attendance_pairs.add((eid_check, dt))
        for d in driller_data:
            dt = d.get('date', '')
            if not dt: continue
            cap_id = make_employee_id(d.get('captain', ''))
            if cap_id: all_attendance_pairs.add((cap_id, dt))
            for m in d.get('members', []):
                mid = make_employee_id(m)
                if mid: all_attendance_pairs.add((mid, dt))
        for day in attendance_data:
            dt = day.get('date', '')
            if not dt: continue
            for e in day.get('normal', []):
                if isinstance(e, dict):
                    eid_check = e.get('employee_id')
                else:
                    eid_check = make_employee_id(e)
                if eid_check: all_attendance_pairs.add((eid_check, dt))

        for day in crush_data:
            dt = day.get('date', '')
            if not dt: continue
            for e in day.get('personnel', []):
                eid = make_employee_id(e)
                if eid:
                    all_attendance_pairs.add((eid, dt))

        per_date_type = defaultdict(dict)
        range_exclusions = set()
        all_dates = sorted(set(
            list(d['date'] for d in shift_data if d.get('date')) +
            list(d['date'] for d in driller_data if d.get('date')) +
            list(d['date'] for d in attendance_data if d.get('date')) +
            list(d['date'] for d in crush_data if d.get('date'))
        ))
        for eid, ovs in overrides.items():
            for o in ovs:
                st = o.get('salary_type', '')
                start = o.get('start_date') or ''
                end = o.get('end_date') or ''
                if st not in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                    continue
                if not (start or end): continue
                for dt in all_dates:
                    if start and dt < start: continue
                    if end and dt > end: continue
                    per_date_type[eid][dt] = st
                if st in ('day_rate', 'monthly'):
                    for day in shift_data:
                        dt = day['date']
                        if start and dt < start: continue
                        if end and dt > end: continue
                        range_exclusions.add((eid, dt))
        # 临时计件例外：检查全局出勤集合
        for eid in list(per_date_type.keys()):
            for dt, dtype in list(per_date_type[eid].items()):
                if dtype in ('piece_underground', 'piece_driller', 'piece_crush'):
                    if (eid, dt) not in all_attendance_pairs:
                        att_exclusions.add((eid, dt))
        combined_excl = exclusions | att_exclusions | range_exclusions

        all_shift_dates = sorted(set(
            list(d['date'] for d in shift_data if d.get('date')) +
            list(d['date'] for d in driller_data if d.get('date')) +
            list(d['date'] for d in crush_data if d.get('date'))
        ))
        ug_type_excl = set()
        dr_type_excl = set()
        cr_type_excl = set()
        for emp in employees:
            eid = emp['id']
            perm_type = emp['default_type']
            if eid in overrides:
                for o in overrides[eid]:
                    st = o.get('salary_type', ''); s, e = o.get('start_date') or '', o.get('end_date') or ''
                    if st in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush') and not (s or e):
                        perm_type = st
            for dt in all_shift_dates:
                dtype = per_date_type.get(eid, {}).get(dt, perm_type)
                if dtype != 'piece_underground': ug_type_excl.add((eid, dt))
                if dtype != 'piece_driller': dr_type_excl.add((eid, dt))
                if dtype != 'piece_crush': cr_type_excl.add((eid, dt))

        ug_sal, ug_daily, ug_shifts = calc_underground_piece(shift_data, combined_excl | ug_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs)
        dr_sal, dups, dr_daily = calc_driller_piece(driller_data, data_folder, combined_excl | dr_type_excl, att_exclusions=att_exclusions, all_attendance_pairs=all_attendance_pairs)
        _enrich_crush_with_p_attendance(crush_data, employees, data_folder)
        crush_sal, crush_daily, crush_shifts = calc_crush_piece(crush_data, combined_excl | cr_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs)

        # 提前检测月份前缀（供 calc_day_salary 和月薪计算使用）
        _ym = ''
        _alld = sorted(set(
            list(d['date'] for d in shift_data + attendance_data + driller_data + crush_data if d.get('date'))
        ))
        if _alld:
            _ym = _alld[0][:7]
        elif 'dates' in main_data:
            for _dt in main_data.get('dates', []):
                if _dt:
                    _ym = _dt[:7]
                    break

        day_sal = calc_day_salary(attendance_data, employees, overrides, data_folder, shift_data, month_prefix=_ym)
        month_sal = calc_monthly_salary(employees, overrides)

        # 出勤覆盖
        att_all = {}
        if data_folder:
            dbp2 = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(dbp2):
                conn = sqlite3.connect(dbp2)
                for r in conn.execute("SELECT employee_id, date, status FROM attendance_overrides").fetchall():
                    att_all[(r[0], r[1])] = r[2]
                conn.close()

        # 日薪逐日分摊
        ds_daily = defaultdict(lambda: defaultdict(float))
        emp_map = {e['id']: e for e in employees}
        for eid, total in day_sal.items():
            date_counts = defaultdict(int)
            counted = set()
            for d in attendance_data:
                dt = d.get('date', '')
                for e in d.get('normal', []):
                    if make_employee_id(e) != eid: continue
                    if (eid, dt) in counted: continue
                    if att_all.get((eid, dt)) in ('A', 'L'): continue
                    counted.add((eid, dt))
                    date_counts[dt] += 1
            def _has_dr_ov(eid, dt):
                for o in overrides.get(eid, []):
                    if o.get('salary_type') == 'day_rate':
                        s, e = o.get('start_date') or '', o.get('end_date') or ''
                        if s or e:
                            if (not s or dt >= s) and (not e or dt <= e) and o.get('day_rate', 0) > 0: return True
                        elif not s and not e: return True
                return False
            for d in shift_data:
                dt = d.get('date', '')
                for e in d.get('day_emps', []) + d.get('night_emps', []):
                    if make_employee_id(e) != eid: continue
                    if not _has_dr_ov(eid, dt): continue
                    if (eid, dt) in counted: continue
                    if att_all.get((eid, dt)) in ('A', 'L'): continue
                    counted.add((eid, dt))
                    date_counts[dt] += 1
            _p_month = set()
            for _d in list(attendance_data) + list(shift_data):
                _dd = _d.get('date', '')
                if _dd: _p_month.add(_dd[:7])
            for (peid, pdt), st in att_all.items():
                if peid == eid and st == 'P' and (eid, pdt) not in counted:
                    if _p_month and pdt[:7] not in _p_month: continue
                    date_counts[pdt] += 1
            if not date_counts: continue
            for dt, count in sorted(date_counts.items()):
                dr = 0
                for o in overrides.get(eid, []):
                    if o.get('salary_type') == 'day_rate':
                        s, e = o.get('start_date') or '', o.get('end_date') or ''
                        if o.get('day_rate', 0) > 0:
                            if (not s or dt >= s) and (not e or dt <= e):
                                dr = o['day_rate']; break
                if dr == 0 and eid in emp_map:
                    dr = emp_map[eid].get('day_rate', 0)
                if dr > 0: ds_daily[eid][dt] += dr * count

        # 月薪逐日分摊
        ms_daily = defaultdict(lambda: defaultdict(float))
        if _ym:
            _y, _m = int(_ym[:4]), int(_ym[5:7])
            _, _last = monthrange(_y, _m)
            ms_dates_set = set(f"{_y}-{_m:02d}-{d:02d}" for d in range(1, _last + 1))
        else:
            ms_dates_set = set()
            _last = 30
        _cal_days = 26  # 月薪按 26 天均分

        present = defaultdict(set)
        for d in attendance_data:
            dt = d.get('date', '')
            for e in d.get('normal', []):
                if isinstance(e, dict):
                    eid = e.get('employee_id')
                else:
                    eid = make_employee_id(e)
                if eid: present[eid].add(dt)
        for d in shift_data:
            dt = d.get('date', '')
            for e in d.get('day_emps', []) + d.get('night_emps', []):
                eid = make_employee_id(e)
                if eid: present[eid].add(dt)
        for d in driller_data:
            dt = d.get('date', '')
            cap_id = make_employee_id(d.get('captain', ''))
            if cap_id: present[cap_id].add(dt)
            for m in d.get('members', []):
                mid = make_employee_id(m)
                if mid: present[mid].add(dt)

        for d in crush_data:
            dt = d.get('date', '')
            for e in d.get('personnel', []):
                eid = make_employee_id(e)
                if eid: present[eid].add(dt)

        for (peid, pdt), st in att_all.items():
            if st == 'P' and (not _ym or pdt[:7] == _ym):
                present[peid].add(pdt)

        # top department monthly: add 26 working days for full attendance
        if _ym:
            for emp in employees:
                if emp.get("department") == "ENPRIZON LINDI PROJECT" and (emp.get("override_type") == "monthly" or emp.get("default_type") == "monthly"):
                    eid = emp["id"]
                    for d_day in range(1, 27):
                        present[eid].add(f"{_y}-{_m:02d}-{d_day:02d}")


        for eid, base in month_sal.items():
            if not _ym or base <= 0: continue
            monthly_present_dates = []
            for dt in sorted(ms_dates_set):
                dtype = per_date_type.get(eid, {}).get(dt, emp_map.get(eid, {}).get('override_type') or emp_map.get(eid, {}).get('default_type', ''))
                if dtype == 'monthly' and dt in present[eid]:
                    monthly_present_dates.append(dt)
            effective_days = min(len(monthly_present_dates), 26)
            per_day = base / 26
            for dt in monthly_present_dates[:effective_days]:
                ms_daily[eid][dt] += per_day

        # 最终逐日结果
        final_dates = sorted(ms_dates_set | set(
            d['date'] for d in shift_data + attendance_data + driller_data + crush_data if d.get('date')
        ))
        result = {}
        for emp in employees:
            eid = emp['id']
            eff = emp.get('override_type') or emp['default_type']
            if eid in overrides:
                for o in overrides[eid]:
                    if not (o.get('start_date') or o.get('end_date')) and o.get('salary_type') in ('day_rate', 'monthly', 'piece_underground', 'piece_driller', 'piece_crush'):
                        eff = o['salary_type']

            pdt = {}
            if eid in overrides:
                for o in overrides[eid]:
                    s, e = o.get('start_date', '') or '', o.get('end_date', '') or ''
                    if (s or e) and o.get('salary_type', '') in ('piece_underground', 'piece_driller', 'piece_crush', 'day_rate', 'monthly'):
                        for dt in final_dates:
                            if (not s or dt >= s) and (not e or dt <= e):
                                pdt[dt] = o['salary_type']

            temp_list = []
            _mb = ''
            for _d in final_dates:
                if _d: _mb = _d[:7]; break
            if eid in overrides:
                for o in overrides[eid]:
                    s, e = o.get('start_date', ''), o.get('end_date', '')
                    if s or e:
                        if _mb:
                            import calendar as _cal2
                            _y2, _m2 = int(_mb[:4]), int(_mb[5:7])
                            _, _last2 = _cal2.monthrange(_y2, _m2)
                            if (s and s > f'{_mb}-{_last2:02d}') or (e and e < f'{_mb}-01'): continue
                        st_label = {'day_rate': '日薪', 'monthly': '月薪', 'piece_underground': '井下', 'piece_driller': '钻工', 'piece_crush': '破碎'}.get(o.get('salary_type', ''), '')
                        note = f' {o.get("note", "")}' if o.get('note') else ''
                        temp_list.append({
                            'id': o.get('id'), 'salary_type': o.get('salary_type', ''),
                            'start_date': s, 'end_date': e, 'note': o.get('note', ''),
                            'label': f'{st_label} {s}~{e}{note}',
                        })

            daily = defaultdict(float)
            shifts_info = {}
            for dt in final_dates:
                dt_eff = pdt.get(dt, eff)
                if dt_eff == 'piece_underground':
                    amt = ug_daily.get(eid, {}).get(dt, 0)
                    if amt > 0:
                        daily[dt] = round(amt)
                        s = ug_shifts.get(eid, {}).get(dt, '')
                        if s: shifts_info[dt] = s
                elif dt_eff == 'piece_driller':
                    amt = dr_daily.get(eid, {}).get(dt, 0)
                    if amt > 0: daily[dt] = round(amt)
                elif dt_eff == 'piece_crush':
                    amt = crush_daily.get(eid, {}).get(dt, 0)
                    if amt > 0:
                        daily[dt] = round(amt)
                        s = crush_shifts.get(eid, {}).get(dt, '')
                        if s: shifts_info[dt] = s
                elif dt_eff == 'day_rate':
                    amt = ds_daily.get(eid, {}).get(dt, 0)
                    if amt > 0: daily[dt] = round(amt)
                elif dt_eff == 'monthly':
                    amt = ms_daily.get(eid, {}).get(dt, 0)
                    if amt > 0: daily[dt] = round(amt)

            if daily:
                result[eid] = {
                    'name': emp['name'], 'department': emp.get('department', ''),
                    'salary_type': eff, 'effective_type': eff,
                    'daily': dict(daily), 'daily_shifts': shifts_info,
                    'total': round(sum(daily.values())),
                    'override_dates': sorted(pdt.keys()) if pdt else [],
                    'temp_overrides': temp_list,
                }
    finally:
        mod.PRICES_UNDERGROUND = old_up
        mod.PRICES_DRILLER = old_dp
        mod.PRICE_CRUSH = old_cr
    return result
