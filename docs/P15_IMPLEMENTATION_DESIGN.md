# P15 实施设计：井下评分奖金计算对齐手册

**日期**: 2026-08-13
**依据**: `docs/P15_SCORING_BONUS_ALIGNMENT.md` + `REFACTOR_SPEC.md §5.6.3-5.6.8`
**决策**: 用户确认 — 实际出渣强制自动(当日全部产量)；匿名投票不记录评分人；客观层未填计划不计入发放；8月按近似值

---

## 〇、事实依据（已核实的代码现状）

| # | 事实 | 位置 |
|---|------|------|
| F1 | `_merge_collection_to_main_data` 已把井下采集建成 `shift_production`（`date` + `day_prod/night_prod = {'NICKEL（H）':nh,...}`），`_run_pipeline` 已按 month 过滤 | app.py:1638-1639, 691-697 |
| F2 | `calc_underground_piece` 用 `PRICES_UNDERGROUND[k]`（键 `NICKEL（H）` 全角括号）访问 | calculator.py:74-79 |
| F3 | `scoring_card_entries` **无 month 列**；UNIQUE=(week,team_id,card_no,source,subject_employee_id)；8月 162 行全 week=1 | DB 实测 |
| F4 | `objective_records` 本地为空；`get_monthly_objective` 空 → monthly_s=0, ratio=0.7 | database.py:1759-1762 |
| F5 | `save_scoring_card_entries` 不写 month | database.py:1692-1707 |
| F6 | `/config` POST 是 `config.update(incoming)` 全量替换；新键不会被冲掉 | app.py:2357-2360 |
| F7 | `_get_scoring_bonus` 每员工无条件调用，读旧表(空)→恒 0；**需加 `underground_mode=='scoring'` 门** | calculator.py:900, 1385-1452 |
| F8 | 管道构建 employees dict **不含 team_id**（SELECT 6 字段） | app.py:520-544 |
| F9 | summary 无 month 参数、无去极值、三闸无豁免 | app.py:2160-2235 |
| F10 | `compute_daily_breakdown` 不调用 `_get_scoring_bonus`（奖金只入薪资总表 bonus） | calculator.py:977-1382 |

---

## 一、改动文件清单

### 1. `core/database.py`
| 改动 | 行号 | 说明 |
|------|------|------|
| 迁移：`scoring_card_entries` 加 `month` 列 + 重建 UNIQUE(含 month) + 回填 | 244-262, 333-359 先例 | 仿 scoring_cards P10-fix；回填 `UPDATE ... SET month=substr(submitted_at,1,7)` |
| `save_scoring_card_entries` 加 `month` 参数 | 1692 | INSERT 补 month |
| `get_scoring_card_entries` 加 `month=None` 过滤 | 1709 | WHERE 补 month |
| `delete_scoring_card_entries` 加 `month` | 1729 | DELETE 补 month |
| `get_monthly_objective` 分档 90/80/70/60 | 1764-1769 | **R2** |
| `load_config` 默认加 `scoring_nh_threshold=600`/`scoring_nh_price=20000` | 632-639 | **R1** |

### 2. `core/calculator.py`（核心 R1/R3/R4）
| 改动 | 说明 |
|------|------|
| 新增 `compute_scoring_pool(main_data, pricing)` | **R1** 产量层 |
| 新增 `normalize_scoring_entries(entries)` | **R4** 新旧表行归一化 |
| 新增 `compute_scoring_individuals(normalized, config)` | **R4** 共享系数（去极值+分票+1.5票加权+系数表） |
| 新增 `compute_team_bonuses(data_folder, team_id, month, pool_info)` | **R3** 单班全量（含旧表回退+守恒） |
| 重写 `_get_scoring_bonus` | 1385-1452 | 缓存 `compute_team_bonuses` 结果 |
| `calculate_all` 接入 | ~784, 900 | pool_info + 模式门 + month/team_id |

### 3. `app.py`
| 改动 | 行号 | 说明 |
|------|------|------|
| 员工查询补 `team_id` | 520 | SELECT + dict 加字段 |
| `scoring_summary` 重写 | 2160-2235 | month 参数 + pool 块 + 个人 bonus + **R7 豁免** |
| `scoring_submit_card` 加 month | 1981-2005 | 收 month；驾驶≤2 后端校验 |
| 新增 `/api/objective/suggest?date=` | 客观层区 | **R5** 当日总产量(NH+NL+MAWE) |
| 客观录入端点支持编辑已提交记录 | 2237-2247 | **R5** |
| 删除残桩 `/api/scoring/bonus/<team>` | 2279-2290 | 能力并入 summary |

### 4. `templates/index.html` + `static/js/i18n.js`
- 评分汇总页：池展示卡 + 个人奖金列 + 守恒/无客观标记（`loadScoringSummary` 5300-5316）
- 客观录入：objDate onchange 自动带出 actual（只读）；计划出渣未填提示；在井总时长默认10h；编辑已提交
- 评分卡：传 month；驾驶≤2 前端校验
- i18n 新键

### 5. `_work/verify_p15_scoring.py`（新增验证脚本）
双场景，tempfile 临时库，不污染 `data/kilwa.db`。

---

## 二、共享函数签名 + 伪代码（核心交付）

```python
# ── R1 产量层 ─────────────────────────────────────────
def compute_scoring_pool(main_data, pricing):
    """当月 NICKEL(H) 车次 → 总池/半池。仅 NICKEL（H），NL/MAWE 不计。"""
    threshold = int(pricing.get('scoring_nh_threshold', 600) or 600)
    price     = int(pricing.get('scoring_nh_price', 20000) or 20000)
    nh_count = 0
    for day in main_data.get('shift_production', []):
        dp = day.get('day_prod') or {}; np = day.get('night_prod') or {}
        nh_count += int(dp.get('NICKEL（H）', 0) or 0) + int(np.get('NICKEL（H）', 0) or 0)
    total_pool = max(nh_count - threshold, 0) * price
    return {'nh_count': nh_count, 'total_pool': total_pool, 'half_pool': total_pool // 2}


# ── R4 归一化 ─────────────────────────────────────────
def normalize_scoring_entries(entries):
    """输入 DB 行 dict（新表或旧表结构）→ 统一 [{subject_employee_id, subject_name, source, avg}]。
    匿名原则：不依赖 operator_id，只保留 source（工友/管理）。"""
    out = []
    for e in entries:
        eid = e.get('subject_employee_id') or e.get('target_employee_id') or e.get('employee_id') or ''
        if not eid: continue
        dims = [e.get('initiative'), e.get('diligence'), e.get('discipline'),
                e.get('cooperation'), e.get('safety')]
        if e.get('driving') not in (None, ''): dims.append(e.get('driving'))
        filled = [d for d in dims if d]
        if not filled: continue
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
    if not v: return 0.0, 0
    if len(v) >= 3:
        v.sort(); v = v[1:-1]
    return sum(v) / len(v), len(v)


# ── R4 共享系数（summary 与奖金唯一来源） ─────────────
def compute_scoring_individuals(normalized, config):
    """分票(工友/管理) → 去极值 → 管理1.5票加权 → 系数表。返回 {eid: {...}}"""
    mgmt_w = float(config.get('mgmt_vote_weight', 1.5))
    by_target = defaultdict(list)
    for r in normalized:
        by_target[r['subject_employee_id']].append(r)
    out = {}
    for eid, rows in by_target.items():
        peers = [r for r in rows if r['source'] != '管理']
        mgmts = [r for r in rows if r['source'] == '管理']
        peer_avg, peer_n = _trimmed_mean([r['avg'] for r in peers])
        mgmt_avg, _      = _trimmed_mean([r['avg'] for r in mgmts])
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


# ── R3 单班全量奖金 ──────────────────────────────────
def compute_team_bonuses(data_folder, team_id, month, pool_info):
    """返回 {individuals, sum_coef, monthly_s, distribution_ratio, actual_pool,
             bonuses:{eid:int}, conserved, objective_missing}"""
    from core.database import get_scoring_card_entries, get_all_scoring_entries, \
                              get_monthly_objective, get_scoring_config
    entries = get_scoring_card_entries(data_folder, team_id=team_id, month=month)
    if not entries:
        try: entries = get_all_scoring_entries(data_folder, team_id)
        except Exception: entries = []
    norm = normalize_scoring_entries(entries)
    if not norm:
        return {'individuals': {}, 'sum_coef': 0, 'monthly_s': 0, 'distribution_ratio': 0.7,
                'actual_pool': 0, 'bonuses': {}, 'conserved': True, 'objective_missing': True}
    individuals = compute_scoring_individuals(norm, get_scoring_config(data_folder))
    obj = get_monthly_objective(data_folder, team_id)
    if obj['monthly_s'] == 0:   # 无客观数据 → 不发（用户决策：未填计划不计入发放）
        return {'individuals': individuals, 'sum_coef': 0, 'monthly_s': 0,
                'distribution_ratio': obj['distribution_ratio'], 'actual_pool': 0,
                'bonuses': {eid: 0 for eid in individuals}, 'conserved': True, 'objective_missing': True}
    actual_pool = int(pool_info['half_pool'] * obj['distribution_ratio'])
    sum_coef = sum(i['coefficient'] for i in individuals.values())
    if actual_pool <= 0 or sum_coef <= 0:
        return {..., 'bonuses': {eid: 0 for eid in individuals}, 'conserved': True}
    # 最大余数法：保证 Σ个人奖金 == 班实际池
    exact  = {eid: actual_pool * ind['coefficient'] / sum_coef for eid, ind in individuals.items()}
    floors = {eid: int(x) for eid, x in exact.items()}
    remain = actual_pool - sum(floors.values())
    for eid in sorted(exact, key=lambda k: exact[k] - int(exact[k]), reverse=True)[:remain]:
        floors[eid] += 1
    return {'individuals': individuals, 'sum_coef': sum_coef, 'monthly_s': obj['monthly_s'],
            'distribution_ratio': obj['distribution_ratio'], 'actual_pool': actual_pool,
            'bonuses': floors, 'conserved': sum(floors.values()) == actual_pool,
            'objective_missing': False}


# ── R3 个人奖金查询（重写原 1385-1452） ──────────────
_SCORING_BONUS_CACHE = {}

def _get_scoring_bonus(data_folder, employee_id, month_prefix='', pool_info=None, team_id=0):
    if not pool_info or pool_info.get('total_pool', 0) <= 0 or not team_id:
        return 0
    key = (data_folder, month_prefix, team_id)
    if key not in _SCORING_BONUS_CACHE:
        _SCORING_BONUS_CACHE[key] = compute_team_bonuses(data_folder, team_id, month_prefix, pool_info)
    return int(_SCORING_BONUS_CACHE[key]['bonuses'].get(employee_id, 0) or 0)
```

`calculate_all` 内接入（约 784、900 行）：
```python
pool_info = compute_scoring_pool(main_data, pricing)
if underground_mode == 'scoring':
    _SCORING_BONUS_CACHE.clear()
# 员工循环内（替换原 900-902）：
if underground_mode == 'scoring':
    scoring_bonus = _get_scoring_bonus(data_folder, eid, month_prefix, pool_info, emp.get('team_id'))
    if scoring_bonus > 0:
        bonus += scoring_bonus
```

**decision 记录**：`sum_coef` = 当月该班被评成员各自的系数之和（取自 individuals），未录入评分的成员不计入。

---

## 三、决策点结论

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 共享系数函数位置 | `core/calculator.py`（依赖方向 calculator→database，app.py 直接 import） |
| 2 | 月份过滤 | **加 month 列 + 重建 UNIQUE**（按 week 推断不可行：week 是月内周次，跨月重复会覆盖数据） |
| 3 | NICKEL(H) 汇总 | `calculate_all` 内从 `main_data['shift_production']` 算（与计件同源，month 已过滤） |
| 4 | 配置键 | `settings['config']` JSON：`scoring_nh_threshold=600`、`scoring_nh_price=20000`，双保险 `.get()` 兜底 |
| 5 | 前端数据流 | 扩展 `/api/scoring/summary/<team>` 响应：`pool` 块 + `individuals[].bonus`，不新建端点；删除残桩 `/api/scoring/bonus` |
| 6 | 客观层带出 | 后端 `/api/objective/suggest?date=`（与 APP_STATE 同源），前端只读自动填充；计划出渣未填→该日不计入+提醒；在井总时长默认10h；已提交可编辑 |
| 7 | 验证脚本 | `_work/verify_p15_scoring.py`，tempfile 临时库，双场景断言 |

---

## 四、实施顺序（纵向切片）

**切片 1 — 后端计算核心（离线可测）**
1. R2 分档（database.py）
2. month 列迁移 + save/get/delete 签名扩展
3. calculator.py 四个共享函数 + `_get_scoring_bonus` 重写 + `calculate_all` 接入（pool_info + 模式门）
4. app.py 员工查询补 team_id
5. `_work/verify_p15_scoring.py` 双场景 → A/B 全 PASS + 跑 `p14_full_verify.py` 回归

**切片 2 — summary 端点**
6. `scoring_summary` 重写（month、pool、bonus、R7 豁免）
7. 删除残桩 `/api/scoring/bonus/<team>`

**切片 3 — 前端**
8. 评分汇总页池展示 + 个人奖金列（index.html + i18n）
9. 客观录入自动带出 + 计划出渣提醒 + 默认10h + 编辑
10. 评分卡传 month + 驾驶≤2 校验（前端+后端）

**切片 4 — 配置与回归**
11. config 默认值 + 计薪参数页可选输入框
12. 全量回归：双路径核对 0 偏差、日明细与总表一致、piecework 不受影响

---

## 五、风险与缓解

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| 1 | 8月 162 行无 month（回填 submitted_at 前 7 位可解决） | 低 | 幂等回填 |
| 2 | `objective_records` 空 → monthly_s=0 → 发 0（用户已确认：未填计划不计入发放） | 中 | 前端 `objective_missing:true` 标记 + 提醒补录 |
| 3 | UNIQUE 重建迁移有丢失风险 | 高 | 仿 scoring_cards P10-fix 上线模式；迁移前备份；断言行数=162 |
| 4 | 去极值使 summary 数值变化（原全量平均） | 低 | 符合手册，预期变更 |
| 5 | 总额守恒逐人四舍五入漂移 | 低 | 最大余数法；`conserved` 字段展示 |
| 6 | piecework 模式误发奖金 | 中 | `underground_mode=='scoring'` 门 |
| 7 | 性能（每员工调用） | 低 | `_SCORING_BONUS_CACHE` 按 (folder, month, team) 缓存，calculate_all 每次 clear |
