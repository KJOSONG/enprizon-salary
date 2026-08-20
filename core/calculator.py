"""
薪资计算引擎（四轨）
1. 生产薪资（N/S 列） NH×6000 + NL×5000 + MW×4000，平分
2. 钻工计件（T-Z/AF-AI 列） NH×5000 + NL×4000 + MW×3000，队长×2份额制
3. 日薪（Daily Salary 表）日薪基数×出勤天数
4. 月薪（手动标记）月薪基数
"""
from collections import defaultdict
from calendar import monthrange
from datetime import datetime, date, timezone, timedelta
import os
from .namematch import canonical, make_employee_id, is_driller_leader, DRILLER_LEADERS

# ── 单价 ─────────────────────────────────────────────────
PRICES_UNDERGROUND = {'NICKEL（H）': 6000, 'NICKEL（L）': 5000, 'MAWE': 4000}
PRICES_DRILLER = {'NICKEL（H）': 5000, 'NICKEL（L）': 4000, 'MAWE': 3000}
PRICE_CRUSH = 300  # TZS/bag

# P21 R4: 井下计件目标部门（注意 DB 实际值含空格 + 全角括号，匹配一律经 _norm_dept 规范化）
PRODUCTION_UG_DEPT = 'Production TEAM （underground）'

def compute_paye(taxable_income):
    """
    坦桑尼亚个人所得税（PAYE）累进税率计算
    taxable_income: 应税收入（总收入 - NSSF）
    返回: PAYE 金额
    """
    if taxable_income <= 270000:
        return 0
    elif taxable_income <= 520000:
        return (taxable_income - 270000) * 0.08
    elif taxable_income <= 760000:
        return 20000 + (taxable_income - 520000) * 0.20
    elif taxable_income <= 1000000:
        return 68000 + (taxable_income - 760000) * 0.25
    else:
        return 128000 + (taxable_income - 1000000) * 0.30

def _norm_dept(s):
    """部门名规范化：去所有空格 + 全角括号归一为半角 + 大写（防历史数据漂移，禁止裸字符串比较）"""
    import re
    return re.sub(r'\s+', '', (s or '')).replace('（', '(').replace('）', ')').upper()

# 业务时区：坦桑尼亚 UTC+3（服务器可能为其他时区，全系统统一以此为准）
EAT = timezone(timedelta(hours=3))
TODAY = datetime.now(EAT).date()
CURRENT_MONTH = TODAY.month
CURRENT_YEAR = TODAY.year

# ═══════════════════════════════════════════════════════════
#  1. 生产薪资计算
# ═══════════════════════════════════════════════════════════

def calc_underground_piece(shift_data, exclusions, override_excludes, data_folder=None, all_attendance_pairs=None, mode=None, pricing=None):
    """
    计算井下工人计件工资
    白班+夜班合并，总金额均分给出勤人员
    V2 mode: 按班组做凸性加速池（accel_prices + multiplier）
    返回: { employee_id: total_salary }, { employee_id: { date: amount } }
    """
    result = defaultdict(float)
    daily = defaultdict(lambda: defaultdict(float))
    daily_shifts = defaultdict(lambda: defaultdict(set))  # daily_shifts[eid][date] = {'D','N'}
    v2_warnings = []  # V2: team_id==0 shifts skipped

    v2_active = (mode == 'v2' and pricing is not None)
    v2_accel_target = int(pricing.get('accel_target', 40) or 40) if v2_active else 40
    v2_prices = (pricing.get('accel_prices') or {}) if v2_active else {}

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
        day_team = day.get('day_team', 0)
        night_team = day.get('night_team', 0)
        day_exempt = day.get('day_exempt', False)
        night_exempt = day.get('night_exempt', False)

        # 白班
        if day_emps and day_prod:
            valid = _filter_valid(day_emps, exclusions, override_excludes, date_str)
            seen = set()
            deduped = []
            for e in valid:
                eid = make_employee_id(e)
                if eid and eid not in seen:
                    seen.add(eid)
                    deduped.append(e)
            valid = deduped
            existing_ids = {make_employee_id(e) for e in valid if make_employee_id(e)}
            for (eid, dt), sh in shift_adds.items():
                if dt == date_str and sh == 'D' and eid not in existing_ids \
                        and (eid, date_str) not in exclusions \
                        and (eid, date_str) in attendance_pairs:
                    valid.append(eid)
                    existing_ids.add(eid)

            if valid:
                if v2_active and day_team == 0:
                    v2_warnings.append(f"team_id=0 day shift {date_str} skipped")
                elif v2_active:
                    prices = v2_prices
                    total_cars = sum(day_prod.get(k, 0) for k in prices)
                    multiplier = 1.0 if day_exempt else total_cars / v2_accel_target
                    pool = sum(day_prod.get(k, 0) * prices.get(k, 0) for k in prices) * multiplier
                    per = pool / len(valid) if valid else 0
                    for e in valid:
                        eid = make_employee_id(e)
                        if eid:
                            result[eid] += per
                            daily[eid][date_str] += per
                            daily_shifts[eid][date_str].add('D')
                else:
                    total = sum(day_prod[k] * PRICES_UNDERGROUND[k] for k in PRICES_UNDERGROUND)
                    if total > 0:
                        per = total / len(valid)
                        for e in valid:
                            eid = make_employee_id(e)
                            if eid:
                                result[eid] += per
                                daily[eid][date_str] += per
                                daily_shifts[eid][date_str].add('D')

        # 夜班
        if night_emps and night_prod:
            valid = _filter_valid(night_emps, exclusions, override_excludes, date_str)
            seen = set()
            deduped = []
            for e in valid:
                eid = make_employee_id(e)
                if eid and eid not in seen:
                    seen.add(eid)
                    deduped.append(e)
            valid = deduped
            existing_ids = {make_employee_id(e) for e in valid if make_employee_id(e)}
            for (eid, dt), sh in shift_adds.items():
                if dt == date_str and sh == 'N' and eid not in existing_ids \
                        and (eid, date_str) not in exclusions \
                        and (eid, date_str) in attendance_pairs:
                    valid.append(eid)
                    existing_ids.add(eid)

            if valid:
                if v2_active and night_team == 0:
                    v2_warnings.append(f"team_id=0 night shift {date_str} skipped")
                elif v2_active:
                    prices = v2_prices
                    total_cars = sum(night_prod.get(k, 0) for k in prices)
                    multiplier = 1.0 if night_exempt else total_cars / v2_accel_target
                    pool = sum(night_prod.get(k, 0) * prices.get(k, 0) for k in prices) * multiplier
                    per = pool / len(valid) if valid else 0
                    for e in valid:
                        eid = make_employee_id(e)
                        if eid:
                            result[eid] += per
                            daily[eid][date_str] += per
                            daily_shifts[eid][date_str].add('N')
                else:
                    total = sum(night_prod[k] * PRICES_UNDERGROUND[k] for k in PRICES_UNDERGROUND)
                    if total > 0:
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

def _enrich_shift_with_dn_attendance(shift_data, employees, data_folder):
    """将手动标记 D/N 的员工注入到 shift_production 的 day_emps/night_emps 中"""
    if not data_folder or not shift_data:
        return
    db_path = os.path.join(data_folder, 'kilwa.db')
    if not os.path.exists(db_path):
        return
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT employee_id, date, status FROM attendance_overrides WHERE status IN ('D','N')"
    ).fetchall()
    conn.close()
    if not rows:
        return
    all_eids = {emp['id']: emp.get('name', '') for emp in employees}
    # 按日期分组
    dn_by_date = defaultdict(lambda: {'D': [], 'N': []})
    for eid, dt, status in rows:
        name = all_eids.get(eid)
        if name:
            dn_by_date[dt][status].append(name)
    for day in shift_data:
        dt = day.get('date', '')
        extra = dn_by_date.get(dt)
        if not extra:
            continue
        existing_day = set(day.get('day_emps', []))
        existing_night = set(day.get('night_emps', []))
        for name in extra['D']:
            if name not in existing_day:
                day.setdefault('day_emps', []).append(name)
        for name in extra['N']:
            if name not in existing_night:
                day.setdefault('night_emps', []).append(name)


def _enrich_crush_with_p_attendance(crush_data, employees, data_folder):
    """将手动标记 C 的员工加入到当日破碎队人员列表中，并返回 C 标记覆盖用于 per_date_type"""
    c_overrides = {}  # 返回: {eid: [date, ...]} 用于覆盖 per_date_type
    if not data_folder:
        return c_overrides
    db_path = os.path.join(data_folder, 'kilwa.db')
    if not os.path.exists(db_path):
        return c_overrides
    # 构建所有员工的 ID→名称 映射
    all_eids = {}
    for emp in employees:
        all_eids[emp['id']] = emp.get('name', '')
    if not all_eids:
        return c_overrides
    # 仅查询 status='C'（破碎）的记录；'P'（出勤）应走日薪轨道，不应注入破碎队
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT employee_id, date FROM attendance_overrides WHERE status = 'C'"
    ).fetchall()
    conn.close()
    # 按日期收集应加入的额外员工名称，同时收集 C 覆盖
    extra_by_date = defaultdict(list)
    for eid, dt in rows:
        name = all_eids.get(eid)
        if name:
            extra_by_date[dt].append(name)
            c_overrides.setdefault(eid, []).append(dt)
    if not extra_by_date:
        return c_overrides
    # 注入到 crush_data 的每条记录的 personnel 中
    for day in crush_data:
        dt = day.get('date', '')
        extra_names = extra_by_date.get(dt, [])
        if extra_names:
            existing = set(day.get('personnel', []))
            for name in extra_names:
                if name not in existing:
                    day['personnel'].append(name)
    return c_overrides

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

        # 统计手动加入钻工组的人数（排除 A/L 缺勤者 + 空出勤者 + 已在产量成员名单的人）
        driller_add_count = sum(1 for (eid, dt), cp in driller_adds.items()
                                if dt == date_str and cp == captain and eid != cap_norm
                                and (eid, date_str) not in combined_exclusions
                                and (eid, date_str) in driller_attendance
                                and eid not in existing_ids)

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
        # 已存在于 all_members（产量数据）的人跳过——防同一人双份支付
        # （原实现：产量数据含此人 + overrides 手动名单也含 → 支付两份，分母还虚增）
        for (eid, dt), cp in driller_adds.items():
            if dt == date_str and cp == captain and eid != cap_norm \
                    and (eid, date_str) not in combined_exclusions \
                    and (eid, date_str) in driller_attendance \
                    and eid not in existing_ids:
                amt = per_share * 1
                result[eid] += amt
                daily[eid][dt] += amt

    return dict(result), [], {eid: dict(d) for eid, d in daily.items()}

# ═══════════════════════════════════════════════════════════
#  3. 日薪计算
# ═══════════════════════════════════════════════════════════

def get_day_rate_for_date(overrides, emp_map, eid, date_str):
    """R3: 按天取日薪基数（calculate_all / calc_day_salary / compute_daily_breakdown 统一使用）。
    规则（临时例外优先于永久）:
      1. 日期区间内匹配的临时例外（start_date/end_date 非空且含该日、day_rate>0）→ 取其金额
      2. 否则取永久覆盖（无日期区间、day_rate>0）
      3. 否则回退员工默认 day_rate
    返回 >0 的基数；无则返回 0。"""
    ovs = overrides.get(eid) or []
    # 1. 临时例外：日期区间内匹配（优先级最高）
    for o in ovs:
        if o.get('salary_type') != 'day_rate':
            continue
        s = o.get('start_date') or ''
        e = o.get('end_date') or ''
        if not (s or e):
            continue
        if o.get('day_rate', 0) > 0 and (not s or date_str >= s) and (not e or date_str <= e):
            return o['day_rate']
    # 2. 永久覆盖
    for o in ovs:
        if o.get('salary_type') != 'day_rate':
            continue
        s = o.get('start_date') or ''
        e = o.get('end_date') or ''
        if s or e:
            continue
        if o.get('day_rate', 0) > 0:
            return o['day_rate']
    # 3. 回退默认
    emp = emp_map.get(eid) or {}
    return emp.get('day_rate', 0) or 0


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

    # P22-FIX: 判断某员工是否为日薪——以 override_type 优先，其次 default_type。
    # 修复 UG 部门 day_rate 员工通过井下采集提交 D/N 出勤后，薪资总表计了日薪、
    # 但日工资明细缺失的问题（员工 36/52 案例）。
    # 注意：ENPRIZON LINDI PROJECT 部门员工 default_type=day_rate 但 override_type=monthly，
    # 必须按 override_type 判定（实际月薪），不能只看 default_type。
    _emp_by_id = {e['id']: e for e in employees}
    def is_overridden_day_rate(eid, date_str=None):
        _ee = _emp_by_id.get(eid, {})
        _eff = _ee.get('override_type') or _ee.get('default_type')
        if _eff == 'day_rate':
            return True
        if eid in overrides:
            for o in overrides[eid]:
                if o.get('salary_type') == 'day_rate':
                    # 有日期区间的临时覆盖按区间判断；永久 day_rate 覆盖已由 override_type 体现
                    start = o.get('start_date') or ''
                    end = o.get('end_date') or ''
                    if start or end:
                        if date_str:
                            if start and date_str < start: continue
                            if end and date_str > end: continue
                            return True
        return False

    # 统计每人出勤天数，扣除 A/L（R3: 按天收集日期，供逐日取基数）
    day_dates = defaultdict(set)
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
                if att_overrides[key] in ('A', 'L', 'E'):
                    continue
            counted_pairs.add((eid, dt))
            day_dates[eid].add(dt)

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
                        if att_overrides[key] in ('A', 'L', 'E'):
                            continue
                    counted_pairs.add((eid, dt))
                    day_dates[eid].add(dt)
            for e in day.get('night_emps', []):
                eid = make_employee_id(e)
                if eid and is_overridden_day_rate(eid, dt):
                    # 按 (eid, date) 去重
                    if (eid, dt) in counted_pairs:
                        continue
                    key = f'{eid}|{dt}'
                    if key in att_overrides:
                        if att_overrides[key] in ('A', 'L', 'E'):
                            continue
                    counted_pairs.add((eid, dt))
                    day_dates[eid].add(dt)

    # 来源3：手动 P 覆盖 / P21 R2: NU 年假覆盖（仅限当月，日薪轨道计入出勤天数）
    _month_prefixes = set()
    for d in list(attendance_data) + list(shift_data or []):
        dt = d.get('date', '')
        if dt:
            _month_prefixes.add(dt[:7])
    _effective_prefixes = _month_prefixes
    if not _effective_prefixes and month_prefix:
        _effective_prefixes = {month_prefix}
    for key, status in att_overrides.items():
        if status in ('P', 'NU'):
            parts = key.split('|')
            if len(parts) == 2:
                eid, dt = parts[0], parts[1]
                if _effective_prefixes and dt[:7] not in _effective_prefixes:
                    continue
                if (eid, dt) not in counted_pairs:
                    day_dates[eid].add(dt)

    # 查找日薪基数（R3: 逐日取基数，临时例外金额按日期区间生效）
    emp_map = {}
    for emp in employees:
        emp_map[emp['id']] = emp

    for eid, dates in day_dates.items():
        total = 0
        for dt in dates:
            total += get_day_rate_for_date(overrides, emp_map, eid, dt)
        if total > 0:
            result[eid] = total

    return dict(result)

# ═══════════════════════════════════════════════════════════
#  4. 月薪计算
# ═══════════════════════════════════════════════════════════

def calc_monthly_salary(employees, overrides, underground_mode='piecework'):
    """
    计算月薪工资
    被标记为 monthly 的员工，取月薪基数
    优先取 override，回退到员工基础字段
    P14.4: scoring 模式下井下工人（default_type 仍为 piece_underground）也自动按月薪基数计算，
           无需用户手动改员工薪资类型
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
        if eid in result:
            continue
        eff_type = emp.get('override_type') or emp.get('default_type', '')
        # P14.4: scoring 模式下井下工人（default_type 仍为 piece_underground）自动纳入月薪轨道。
        # 按 default_type 识别（模式优先），即使 override_type 被其他类型覆盖也按月薪基数计算
        is_monthly = eff_type == 'monthly' or (
            underground_mode == 'scoring' and emp.get('default_type') == 'piece_underground')
        if is_monthly and emp.get('monthly_salary', 0) > 0:
            result[eid] = emp['monthly_salary']
    return result
def calculate_all(main_data, employees, overrides=None, exclusions=None, pricing=None, data_folder=None, bonus_penalties=None):
    overrides = overrides or {}
    exclusions = exclusions or set()
    pricing = pricing or {}
    up = pricing.get('underground_prices', PRICES_UNDERGROUND)
    dp = pricing.get('driller_prices', PRICES_DRILLER)
    nssf_rate = pricing.get('nssf_rate', 0.10)
    underground_mode = pricing.get('underground_mode', 'piecework')  # P5-b: scoring | piecework

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
                # P21 R2: NU（年假）加入计件分配排除，剩余人员平分（总额守恒）
                for r in conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L','NU','E')").fetchall():
                    att_exclusions.add((r[0], r[1]))
                conn.close()

        shift_data = main_data.get('shift_production', [])
        driller_data = main_data.get('driller_production', [])
        attendance_data = main_data.get('attendance', [])
        crush_data = main_data.get('crush_production', [])

        # D/N 手动标记：将人员注入 shift_data（必须在 all_attendance_pairs 构建之前）
        _enrich_shift_with_dn_attendance(shift_data, employees, data_folder)

        # C/P 手动标记：先将人员注入 crush_data（必须在 all_attendance_pairs 构建之前，否则后续检查会误排除）
        c_overrides = _enrich_crush_with_p_attendance(crush_data, employees, data_folder)

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

        # 破碎计件文件即破碎出勤：将 crush_data 中出现的 (员工,日期) 自动标记为 piece_crush，
        # 使出勤网格/日工资页筛选"破碎计件"可见（无需逐日手动标 C）。
        for day in crush_data:
            dt = day.get('date', '')
            if not dt:
                continue
            for e in day.get('personnel', []):
                eid = make_employee_id(e)
                if eid and dt not in per_date_type.get(eid, {}):
                    per_date_type[eid][dt] = 'piece_crush'

        # C/P 手动标记：将对应日期覆盖为 piece_crush（crush_data 已在构建 all_attendance_pairs 前注入人员）
        for eid, dates in c_overrides.items():
            for dt in dates:
                per_date_type[eid][dt] = 'piece_crush'

        # P14.3: 评分模式 — 井下工人全体重定向为 monthly
        # 按 default_type 识别（模式优先），与 override_type 无关：
        # 即使井下工人被 day_rate/monthly 永久覆盖覆盖了 override_type，
        # scoring 模式下仍按月薪轨道计，无需用户改员工类型（P14.4）
        scoring_employees = set()
        if underground_mode == 'scoring':
            for emp in employees:
                eid = emp['id']
                # P21 M6/R4: 双条件——井下计件重定向 monthly 需「类型=piece_underground ∧ 部门=目标井下部门」
                if emp.get('default_type') == 'piece_underground' \
                        and _norm_dept(emp.get('department')) == _norm_dept(PRODUCTION_UG_DEPT):
                    scoring_employees.add(eid)
                    for dt in all_dates:
                        per_date_type[eid][dt] = 'monthly'

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
                # P14.3: 非井下计件类型一律从井下计件排除。
                # scoring 模式下井下工人已在 per_date_type 准备阶段被一次性改写为 monthly，
                # 因此无需再按 scoring_employees 运行时逐个判断（该集合仅保留供评分奖金等下游使用）。
                # P21 M6/R4: 双条件——部门不在目标井下部门的 piece_underground 同样排除（当前 bug 根修）
                if dtype != 'piece_underground' \
                        or _norm_dept(emp.get('department')) != _norm_dept(PRODUCTION_UG_DEPT):
                    ug_type_excl.add((eid, dt))
                if dtype != 'piece_driller': dr_type_excl.add((eid, dt))
                if dtype != 'piece_crush': cr_type_excl.add((eid, dt))

        underground_sal, ug_daily, ug_shifts = calc_underground_piece(shift_data, combined_exclusions | ug_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs, mode=underground_mode, pricing=pricing)
        driller_sal, _, driller_daily = calc_driller_piece(driller_data, data_folder, combined_exclusions | dr_type_excl, att_exclusions=att_exclusions, all_attendance_pairs=all_attendance_pairs)
        crush_sal, crush_daily, crush_shifts = calc_crush_piece(crush_data, combined_exclusions | cr_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs)
        monthly_base = calc_monthly_salary(employees, overrides, underground_mode=underground_mode)
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

    # P23 R2: 读本月加班记录（审批通过后落库 overtime_records）
    ot_total = defaultdict(float)
    ot_daily = defaultdict(dict)
    if data_folder and month_prefix:
        _dbp = os.path.join(data_folder, 'kilwa.db')
        if os.path.exists(_dbp):
            try:
                _oc = sqlite3.connect(_dbp)
                for _r in _oc.execute(
                        "SELECT employee_id, date, amount FROM overtime_records WHERE date LIKE ?",
                        (month_prefix + '%',)).fetchall():
                    ot_total[_r[0]] += _r[2]
                    ot_daily[_r[0]][_r[1]] = _r[2]
                _oc.close()
            except Exception:
                ot_total, ot_daily = defaultdict(float), defaultdict(dict)

    # P15: 产量层奖金池（scoring 模式）— 与计件同源 shift_production，month 已过滤
    pool_info = compute_scoring_pool(main_data, pricing)
    if underground_mode == 'scoring':
        _SCORING_BONUS_CACHE.clear()

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

    # P21 R2: NU 天（年假批准自动写入，只读）计入出勤——日薪/月薪轨道按天计薪
    for (eid, dt), st in att_overrides.items():
        if st == 'NU':
            if month_prefix and dt[:7] != month_prefix:
                continue
            present_dates[eid].add(dt)

    # top department monthly: add 26 working days for full attendance
    if month_prefix:
        _y2, _m2 = int(month_prefix[:4]), int(month_prefix[5:7])
        for emp in employees:
            if emp.get("department") == "ENPRIZON LINDI PROJECT" and (emp.get("override_type") == "monthly" or emp.get("default_type") == "monthly"):
                eid = emp["id"]
                for d_day in range(1, 27):
                    present_dates[eid].add(f"{_y2}-{_m2:02d}-{d_day:02d}")

    final_dates = sorted(set(
        list(d['date'] for d in shift_data + attendance_data + driller_data + crush_data if d.get('date')) +
        # P21 R2: 当月 NU 年假天并入迭代范围——保证日明细与薪资页对 day_rate/monthly 员工逐日一致
        [dt for (_e, dt), st in att_overrides.items() if st == 'NU' and (not month_prefix or dt[:7] == month_prefix)]
    ))

    bonus_penalties = bonus_penalties or {}
    result_employees = []

    for emp in employees:
        eid = emp['id']
        eff_type = emp.get('override_type') or emp['default_type']
        pu = pd_val = dr_total = ms_total = cr_total = 0.0
        monthly_present_count = 0

        # 顶层部门 monthly 员工满勤26天：遍历 present_dates（已补1-26号），
        # 与 compute_daily_breakdown 的整月遍历保持一致，避免薪资页与日明细差异
        if emp.get("department") == "ENPRIZON LINDI PROJECT" and (
                emp.get("override_type") == "monthly" or emp.get("default_type") == "monthly"):
            _iter_dates = sorted(present_dates[eid])
        else:
            _iter_dates = final_dates

        for dt in _iter_dates:
            dtype = per_date_type.get(eid, {}).get(dt, eff_type)
            absent = att_overrides.get((eid, dt)) in ('A', 'L', 'E')   # P21 R2: absent 含 E（豁免不出勤）
            nu = att_overrides.get((eid, dt)) == 'NU'             # P21 R2: 年假（计薪）

            # P21 R2: NU 天在计件轨道排除（同 L），在日薪/月薪轨道计入出勤天数
            if dtype == 'piece_underground' and not absent and not nu:
                pu += ug_daily.get(eid, {}).get(dt, 0)
            elif dtype == 'piece_driller' and not absent and not nu:
                pd_val += driller_daily.get(eid, {}).get(dt, 0)
            elif dtype == 'piece_crush' and not absent and not nu:
                cr_total += crush_daily.get(eid, {}).get(dt, 0)
            elif dtype == 'day_rate' and not absent and (dt in present_dates[eid] or nu):
                dr_total += get_day_rate_for_date(overrides, emp_map, eid, dt)
            elif dtype == 'monthly' and not absent and (dt in present_dates[eid] or nu):
                monthly_present_count += 1

        # 月薪：实际出勤 >= 26天封顶为满勤基薪
        mb = monthly_base.get(eid, 0)
        if mb > 0 and monthly_present_count > 0:
            effective_days = min(monthly_present_count, working_days)
            ms_total = effective_days * (mb / working_days)

        pu = round(pu); pd_val = round(pd_val); dr_total = round(dr_total); ms_total = round(ms_total); cr_total = round(cr_total)
        ot = round(ot_total.get(eid, 0))  # P23 R2: 加班费并入税前（可独立展示）
        gross = pu + pd_val + dr_total + ms_total + cr_total + ot
        advance = emp.get('advance_total', 0)
        bp = bonus_penalties.get(eid, {})
        bonus = int(bp.get('bonus', 0) or 0)
        penalty = int(bp.get('penalty', 0) or 0)

        # P15: 评分奖金并入（scoring 模式门；piecework 模式绝不发奖金）
        scoring_bonus = 0
        if underground_mode == 'scoring':
            scoring_bonus = _get_scoring_bonus(data_folder, eid, month_prefix, pool_info, emp.get('team_id'))
        if scoring_bonus > 0:
            bonus += scoring_bonus

        # P15: 司机津贴（5,000/天 × 该月出勤勾选"驾驶"天数；任何人勾选即计，不要求司机名单）
        driver_days = 0
        if data_folder:
            try:
                db_path = os.path.join(data_folder, 'kilwa.db')
                if os.path.exists(db_path):
                    dc = sqlite3.connect(db_path)
                    crows = dc.execute(
                        "SELECT COUNT(*) FROM attendance_overrides WHERE employee_id=? AND date LIKE ? AND is_driver=1",
                        (eid, month_prefix + '%')).fetchone()
                    if crows:
                        driver_days = crows[0]
                    dc.close()
            except:
                driver_days = 0
        driver_allowance = driver_days * 5000

        nssf = round((gross + driver_allowance) * nssf_rate) if emp.get('nssf_enrolled', False) else 0
        taxable_income = gross + driver_allowance - nssf
        tin_number = (emp.get('tin_number') or '').strip()
        paye = round(compute_paye(taxable_income)) if tin_number else 0
        net = gross + bonus + driver_allowance - nssf - paye - advance - penalty

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
            'overtime': ot,  # P23 R2: 加班费（已含于 gross）
            'gross': gross, 'bonus': bonus, 'penalty': penalty,
            'driver_allowance': driver_allowance,
            'advance': round(advance), 'nssf': nssf, 'paye': paye, 'net': net,
            'temp_exception': temp_exception, 'temp_overrides': temp_overrides,
        })

    return {
        'employees': result_employees,
        'total_gross': sum(e['gross'] for e in result_employees),
        'total_overtime': sum(e['overtime'] for e in result_employees),  # P23 R2
        'total_bonus': sum(e['bonus'] for e in result_employees),
        'total_penalty': sum(e['penalty'] for e in result_employees),
        'total_advance': sum(e['advance'] for e in result_employees),
        'total_nssf': sum(e['nssf'] for e in result_employees),
        'total_paye': sum(e['paye'] for e in result_employees),
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
    underground_mode = pricing.get('underground_mode', 'piecework')

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
                # P21 R2: NU（年假）加入计件分配排除（与 calculate_all C6 保持一致）
                for r in conn.execute("SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L','NU','E')").fetchall():
                    att_exclusions.add((r[0], r[1]))
                conn.close()

        # D/N 手动标记：将人员注入 shift_data（必须在 all_attendance_pairs 构建之前）
        _enrich_shift_with_dn_attendance(shift_data, employees, data_folder)

        # C/P 手动标记：先将人员注入 crush_data（必须在 all_attendance_pairs 构建之前）
        c_overrides = _enrich_crush_with_p_attendance(crush_data, employees, data_folder)

        # ── 构建全局出勤集合（包含三个数��源）──
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
        # 破碎计件文件即破碎出勤：将 crush_data 中出现的 (员工,日期) 自动标记为 piece_crush，
        # 使出勤网格/日工资页筛选"破碎计件"可见（无需逐日手动标 C）。
        for day in crush_data:
            dt = day.get('date', '')
            if not dt:
                continue
            for e in day.get('personnel', []):
                eid = make_employee_id(e)
                if eid and dt not in per_date_type.get(eid, {}):
                    per_date_type[eid][dt] = 'piece_crush'

        # C/P 手动标记：将对应日期覆盖为 piece_crush（crush_data 已在构建 all_attendance_pairs 前注入人员）
        for eid, dates in c_overrides.items():
            for dt in dates:
                per_date_type[eid][dt] = 'piece_crush'

        # P14.3: 评分模式 — 井下工人全体重定向为 monthly（与 calculate_all 保持一致，供下方类型排除使用）
        # 按 default_type 识别，模式优先，不受 override_type 影响（P14.4）
        scoring_employees = set()
        if underground_mode == 'scoring':
            for emp in employees:
                eid = emp['id']
                # P21 M6/R4: 双条件（与 calculate_all 一致）
                if emp.get('default_type') == 'piece_underground' \
                        and _norm_dept(emp.get('department')) == _norm_dept(PRODUCTION_UG_DEPT):
                    scoring_employees.add(eid)
                    for dt in all_dates:
                        per_date_type[eid][dt] = 'monthly'
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
                # P14.3: 非井下计件类型一律从井下计件排除（scoring 井下工人已前置改写为 monthly）
                # P21 M6/R4: 双条件——部门不符同样排除（与 calculate_all 一致）
                if dtype != 'piece_underground' \
                        or _norm_dept(emp.get('department')) != _norm_dept(PRODUCTION_UG_DEPT):
                    ug_type_excl.add((eid, dt))
                if dtype != 'piece_driller': dr_type_excl.add((eid, dt))
                if dtype != 'piece_crush': cr_type_excl.add((eid, dt))

        ug_sal, ug_daily, ug_shifts = calc_underground_piece(shift_data, combined_excl | ug_type_excl, {'permanent': set()}, data_folder, all_attendance_pairs, mode=underground_mode, pricing=pricing)
        dr_sal, dups, dr_daily = calc_driller_piece(driller_data, data_folder, combined_excl | dr_type_excl, att_exclusions=att_exclusions, all_attendance_pairs=all_attendance_pairs)
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

        # P23 R2: 读本月加班记录（与 calculate_all 同一来源，保证日明细与薪资页一致）
        ot_daily_br = defaultdict(dict)
        if data_folder and _ym:
            _dbp3 = os.path.join(data_folder, 'kilwa.db')
            if os.path.exists(_dbp3):
                try:
                    _oc3 = sqlite3.connect(_dbp3)
                    for _r3 in _oc3.execute(
                            "SELECT employee_id, date, amount FROM overtime_records WHERE date LIKE ?",
                            (_ym + '%',)).fetchall():
                        ot_daily_br[_r3[0]][_r3[1]] = _r3[2]
                    _oc3.close()
                except Exception:
                    ot_daily_br = defaultdict(dict)


        day_sal = calc_day_salary(attendance_data, employees, overrides, data_folder, shift_data, month_prefix=_ym)
        month_sal = calc_monthly_salary(employees, overrides, underground_mode=underground_mode)

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
                    if att_all.get((eid, dt)) in ('A', 'L', 'E'): continue
                    counted.add((eid, dt))
                    date_counts[dt] += 1
            def _has_dr_ov(eid, dt):
                # P22-FIX: 以 override_type 优先判定日薪（ENPRIZON LINDI PROJECT 部门
                # default_type=day_rate 但 override_type=monthly，不能误判为日薪）
                _ee = emp_map.get(eid, {})
                _eff = _ee.get('override_type') or _ee.get('default_type')
                if _eff == 'day_rate':
                    return True
                for o in overrides.get(eid, []):
                    if o.get('salary_type') == 'day_rate':
                        s, e = o.get('start_date') or '', o.get('end_date') or ''
                        if s or e:
                            if (not s or dt >= s) and (not e or dt <= e) and o.get('day_rate', 0) > 0: return True
                return False
            for d in shift_data:
                dt = d.get('date', '')
                for e in d.get('day_emps', []) + d.get('night_emps', []):
                    if make_employee_id(e) != eid: continue
                    if not _has_dr_ov(eid, dt): continue
                    if (eid, dt) in counted: continue
                    if att_all.get((eid, dt)) in ('A', 'L', 'E'): continue
                    counted.add((eid, dt))
                    date_counts[dt] += 1
            _p_month = set()
            for _d in list(attendance_data) + list(shift_data):
                _dd = _d.get('date', '')
                if _dd: _p_month.add(_dd[:7])
            for (peid, pdt), st in att_all.items():
                # P21 R2: NU 年假天计入日薪（与 calc_day_salary 来源3 一致）
                if peid == eid and st in ('P', 'NU') and (eid, pdt) not in counted:
                    if _p_month and pdt[:7] not in _p_month: continue
                    date_counts[pdt] += 1
            if not date_counts: continue
            for dt, count in sorted(date_counts.items()):
                # R3: 逐日取基数（临时例外按日期区间生效）
                dr = get_day_rate_for_date(overrides, emp_map, eid, dt)
                if dr > 0: ds_daily[eid][dt] += dr * count

        # 补充：仅有手动 P 标记、无 Excel 出勤记录的员工（day_sal 中不存在）
        _p_month = set()
        for _d in list(attendance_data) + list(shift_data):
            _dd = _d.get('date', '')
            if _dd: _p_month.add(_dd[:7])
        for (peid, pdt), st in att_all.items():
            # P21 R2: NU 年假天同样补充进日薪明细
            if st not in ('P', 'NU') or peid in ds_daily: continue
            if _ym and pdt[:7] != _ym: continue
            if _p_month and pdt[:7] not in _p_month: continue
            # R3: 逐日取基数（临时例外按日期区间生效）
            dr = get_day_rate_for_date(overrides, emp_map, peid, pdt)
            if dr > 0: ds_daily[peid][pdt] += dr

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
            # P21 R2: NU 年假天计入月薪出勤天数（与 calculate_all present_dates 一致）
            if st in ('P', 'NU') and (not _ym or pdt[:7] == _ym):
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
                # A/L/E 排除与 calculate_all 对齐（原实现漏排除，日明细与薪资总表月薪不一致）
                if dtype == 'monthly' and dt in present[eid] \
                        and att_all.get((eid, dt)) not in ('A', 'L', 'E'):
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
                # P14.3: 轨道类型统一以 per_date_type 为准（含 scoring 改写后的 monthly，
                # 与 calculate_all 861 行保持一致），pdt/eff 仅作兜底
                dt_eff = per_date_type.get(eid, {}).get(dt, pdt.get(dt, eff))
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

            # P23 R2: 加班额叠加到对应日（不进入单轨选型，只加层；ot_daily_br 已按当月过滤）
            for _odt, _oamt in ot_daily_br.get(eid, {}).items():
                daily[_odt] = round(daily.get(_odt, 0) + _oamt)

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

# ═══════════════════════════════════════════════════════════
#  P15: 评分奖金三层模型（产量层/客观层/主观层，对齐手册）
#  summary 端点与 _get_scoring_bonus 共用本区函数，保证展示与计薪一致
# ═══════════════════════════════════════════════════════════

def compute_scoring_pool(main_data, pricing):
    """R1 产量层：当月 NICKEL(H) 车次 → 总池/半池。
    仅 NICKEL（H）（全角括号），NICKEL（L）/MAWE 不参与。"""
    threshold = int(pricing.get('scoring_nh_threshold', 600) or 600)
    price     = int(pricing.get('scoring_nh_price', 20000) or 20000)
    nh_count = 0
    for day in main_data.get('shift_production', []):
        dp = day.get('day_prod') or {}
        np = day.get('night_prod') or {}
        nh_count += int(dp.get('NICKEL（H）', 0) or 0) + int(np.get('NICKEL（H）', 0) or 0)
    total_pool = max(nh_count - threshold, 0) * price
    return {'nh_count': nh_count, 'total_pool': total_pool, 'half_pool': total_pool // 2}


def normalize_scoring_entries(entries):
    """R4: 新旧表行归一化 → [{subject_employee_id, subject_name, source, avg}]。
    匿名原则：不依赖 operator_id；driving 非空才入第 6 维。"""
    out = []
    for e in entries:
        eid = e.get('subject_employee_id') or e.get('target_employee_id') or e.get('employee_id') or ''
        if not eid:
            continue
        dims = [e.get('initiative'), e.get('diligence'), e.get('discipline'),
                e.get('cooperation'), e.get('safety')]
        if e.get('driving') not in (None, ''):
            dims.append(e.get('driving'))
        filled = [d for d in dims if d]
        if not filled:
            continue
        out.append({
            'subject_employee_id': eid,
            'subject_name': e.get('subject_name') or e.get('target_wid') or e.get('wid') or eid,
            'source': e.get('source', '工友'),
            'avg': sum(filled) / len(filled),
        })
    return out


def _trimmed_mean(votes):
    """去极值：>=3 票剔最高/最低各 1 后取均值；<3 直接取均值。返回 (均值, 有效票数)。"""
    v = [x for x in votes if x > 0]
    if not v:
        return 0.0, 0
    if len(v) >= 3:
        v.sort()
        v = v[1:-1]
    return sum(v) / len(v), len(v)


def compute_scoring_individuals(normalized, config):
    """R4 共享系数：分票(工友/管理) → 去极值 → 管理 1.5 票加权 → 系数表。
    返回 {eid: {wid, peer_avg, peer_behavior, mgmt_behavior, final_behavior,
               coefficient, deviation, peer_votes, mgmt_votes}}"""
    mgmt_w = float(config.get('mgmt_vote_weight', 1.5))
    by_target = defaultdict(list)
    for r in normalized:
        by_target[r['subject_employee_id']].append(r)
    out = {}
    for eid, rows in by_target.items():
        peers = [r for r in rows if r['source'] != '管理']
        mgmts = [r for r in rows if r['source'] == '管理']
        peer_avg, peer_n = _trimmed_mean([r['avg'] for r in peers])
        mgmt_avg, _ = _trimmed_mean([r['avg'] for r in mgmts])
        peer_behavior = (peer_avg - 1) / 4 * 100 if peer_avg > 0 else 0
        mgmt_behavior = (mgmt_avg - 1) / 4 * 100 if mgmt_avg > 0 else 0
        if mgmt_behavior > 0:
            final_behavior = (peer_behavior * peer_n + mgmt_behavior * mgmt_w) / (peer_n + mgmt_w)
        else:
            final_behavior = peer_behavior
        coefficient = 1.2 if final_behavior >= 85 else \
                      1.0 if final_behavior >= 70 else \
                      0.8 if final_behavior >= 60 else 0.5
        out[eid] = {
            'wid': rows[0]['subject_name'],
            'peer_avg': round(peer_avg, 2), 'peer_behavior': round(peer_behavior, 2),
            'mgmt_behavior': round(mgmt_behavior, 2), 'final_behavior': round(final_behavior, 2),
            'coefficient': coefficient,
            'deviation': round(abs(peer_behavior - mgmt_behavior), 2) if mgmt_behavior > 0 else 0,
            'peer_votes': peer_n, 'mgmt_votes': len(mgmts),
        }
    return out


def compute_team_bonuses(data_folder, team_id, month, pool_info):
    """R3 单班全量奖金：新表优先 + 旧表回退；无客观数据 → 发 0（用户决策）；
    最大余数法保证 Σ个人奖金 == 班实际池。"""
    from core.database import get_scoring_card_entries, get_all_scoring_entries, \
                              get_monthly_objective, get_scoring_config
    entries = get_scoring_card_entries(data_folder, team_id=team_id, month=month)
    if not entries:
        try:
            entries = get_all_scoring_entries(data_folder, team_id)
        except Exception:
            entries = []
    norm = normalize_scoring_entries(entries)
    if not norm:
        return {'individuals': {}, 'sum_coef': 0, 'monthly_s': 0, 'distribution_ratio': 0.7,
                'actual_pool': 0, 'bonuses': {}, 'conserved': True, 'objective_missing': True}
    individuals = compute_scoring_individuals(norm, get_scoring_config(data_folder))
    obj = get_monthly_objective(data_folder, team_id, month)
    if obj['monthly_s'] == 0:   # 无客观数据 → 不发（未填计划不计入发放）
        return {'individuals': individuals, 'sum_coef': 0, 'monthly_s': 0,
                'distribution_ratio': obj['distribution_ratio'], 'actual_pool': 0,
                'bonuses': {eid: 0 for eid in individuals}, 'conserved': True,
                'objective_missing': True}
    actual_pool = int(pool_info['half_pool'] * obj['distribution_ratio'])
    sum_coef = sum(i['coefficient'] for i in individuals.values())
    if actual_pool <= 0 or sum_coef <= 0:
        return {'individuals': individuals, 'sum_coef': sum_coef, 'monthly_s': obj['monthly_s'],
                'distribution_ratio': obj['distribution_ratio'], 'actual_pool': actual_pool,
                'bonuses': {eid: 0 for eid in individuals}, 'conserved': True,
                'objective_missing': False}
    # 最大余数法：保证 Σ个人奖金 == 班实际池
    exact = {eid: actual_pool * ind['coefficient'] / sum_coef for eid, ind in individuals.items()}
    floors = {eid: int(x) for eid, x in exact.items()}
    remain = actual_pool - sum(floors.values())
    for eid in sorted(exact, key=lambda k: exact[k] - int(exact[k]), reverse=True)[:remain]:
        floors[eid] += 1
    return {'individuals': individuals, 'sum_coef': sum_coef, 'monthly_s': obj['monthly_s'],
            'distribution_ratio': obj['distribution_ratio'], 'actual_pool': actual_pool,
            'bonuses': floors, 'conserved': sum(floors.values()) == actual_pool,
            'objective_missing': False}


# ── P3: 评分奖金并入 ──────────────────
_SCORING_BONUS_CACHE = {}

def _get_scoring_bonus(data_folder, employee_id, month_prefix='', pool_info=None, team_id=0):
    """从评分数据获取员工个人奖金（无池/无班组 → 0）。
    结果按 (data_folder, month, team) 缓存，calculate_all 每次先 clear。"""
    if not pool_info or pool_info.get('total_pool', 0) <= 0 or not team_id:
        return 0
    key = (data_folder, month_prefix, team_id)
    if key not in _SCORING_BONUS_CACHE:
        _SCORING_BONUS_CACHE[key] = compute_team_bonuses(data_folder, team_id, month_prefix, pool_info)
    return int(_SCORING_BONUS_CACHE[key]['bonuses'].get(employee_id, 0) or 0)
