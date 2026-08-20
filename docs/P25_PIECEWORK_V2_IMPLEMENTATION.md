# 计件薪资制度 V2 — enprizon-salary 实现设计

> **定位**：本文档是"闸控计件（凸性加速）"在 enprizon-salary 中的权威实现设计，基于已批准的工程计划（`.omo/plans/piecework-v2.md`）和逻辑规格（`docs/计件薪资制度V2_系统规格说明.md`）。
>
> **分支**：`feature/piecework-v2`
>
> **最后更新**：2026-08-20

---

## 1. 模式定位：第三计薪模式

V2 是 `underground_mode` 的**第三种枚举值**，与现有 `piecework` 和 `scoring` 平级共存：

| 模式 | 行为 | 回退 |
|------|------|------|
| `piecework` | 线性计件：日池 = Σ(物料×单价)，按人头均分，月末不重分配 | 原样保留 |
| `scoring` | 评分制：固定月薪 + 三层奖金池 | 原样保留 |
| **`v2`** | 凸性加速计件：日池含凸性倍率 + 月末出勤/行为系数零和再分配 | 切回 piecework 即安全 |

**关键设计决策**：

- 不是布尔开关（~~`piecework_accelerator`~~），是独立模式值。选 v2 走凸性全量；选 piecework 走线性，逐字节不变。
- `piecework` 和 `scoring` 两模式行为与升级前完全一致，`underground_mode != 'v2'` 时全走旧逻辑。
- 历史月份不重算；`v2_effective_from` 之前月份保持原有结果。

---

## 2. 班组对齐：复用 `employee_groups`

**不新建任何团队表**。V2 井下生产按班组归属，复用已有的 `employee_groups` 表（当前含 LAMBA LAMBA / SAKA SAKA 两个种子班组，配有 CRUD 接口 + 前端管理页）。

| 已否决方案 | 原因 |
|-----------|------|
| 新建 `teams` 表 | 与 `employee_groups` 功能完全重复 |
| 新建 `team_rosters` 每日花名册表 | 采集 payload 按班组提交已携带归属信息，无需独立花名册 |
| 新建 `production_exemptions` 豁免表 | 豁免通过采集 payload 的 `exempt` 布尔字段承载，无需独立表 |

**班组归属落地**：井下采集提交时，白班/夜班各携带 `team_id`（employee_groups 的 id）和 `exempt`（布尔，设备故障豁免）。`_merge_collection_to_main_data` 将其写入 shift_production 记录的 `day_team`/`night_team`/`day_exempt`/`night_exempt` 字段。`team_id=0` 的班次跳过计件池计算并累计进 warning（非破坏性）。

---

## 3. 配置键

全部可编辑，前端计薪参数页维护，`POST /config` 落库：

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `underground_mode` | str | `'piecework'` | 合法值扩为 `piecework \| scoring \| v2` |
| `accel_target` | int | `40` | 固定班组目标车次（不随人数缩放） |
| `accel_prices` | dict | `{'NICKEL（H）':8000, 'NICKEL（L）':5000, 'MAWE':3000}` | 凸性模式物料单价（TZS/车） |
| `accel_w_a` | float | `0.6` | 月末系数出勤权重（w_a > w_b） |
| `accel_w_b` | float | `0.4` | 月末系数行为权重 |
| `accel_full_days` | int | `26` | 满勤天数（A_W 分母基准） |
| `v2_effective_from` | str | `''` | 生效月份（"YYYY-MM"），空=不生效 |

**校验规则**：`accel_target` 必须为正整数；`accel_w_a > accel_w_b`；`accel_prices` 三键齐全（NICKEL（H）/NICKEL（L）/MAWE）。非法值返回 400。

**单价分工**：mode 为 piecework 时用 `underground_prices`（现有 6000/5000/4000 线性计件）；mode 为 v2 时用 `accel_prices`。两者互不干扰。

---

## 4. 凸性日池公式

### 4.1 激活条件（门控）

```
v2_active = (underground_mode == 'v2') AND (month_prefix >= v2_effective_from)
```

两个条件同时满足才走凸性分支；任一不满足走原线性逻辑。

### 4.2 日池计算

对班组 T、日期 d、班次 s（D 或 N）：

```
MAWE_d , L_d , H_d    = 当日三类物料装载车次
total_cars_d           = MAWE_d + L_d + H_d
pool_{T,d,s}           = (MAWE_d × 3000 + L_d × 5000 + H_d × 8000) × multiplier_d
```

倍率逻辑：

```
if exempt_d == true:
    multiplier_d = 1.0          # 豁免日锁 1.0，不惩罚
elif team_id == 0:
    skip（跳过计件池，累计 warning）  # 未分配班组，不参与计算
else:
    multiplier_d = total_cars_d / accel_target   # 不封顶
```

**凸性效果**：日池 = 物料×单价 × (车次/目标)，工资对产量的弹性约等于 2（双倍敏感）。40 车 → ×1.0；50 车 → ×1.25；30 车 → ×0.75；80 车 → ×2.0。

### 4.3 每日均分到人

```
headcount_{T,d,s} = 当日该班组实际出勤人数（排除 A/L/NU/E）
per_head_{T,d,s}  = pool_{T,d,s} / headcount_{T,d,s}
```

每名出勤工人 W，将其当日所在班组的 `per_head` 累加入个人基数 `base_W`。

---

## 5. 月末零和再分配

月度循环结束后，对所有 `piece_underground` 类型工人执行零和归一化。**总额不多发不少发**。

### 5.1 出勤系数 A_W

```
eligible_days  = accel_full_days(26) − exempt_days
    exempt_days = 当月 status ∈ {L, NU, E} 的天数
worked_days    = 当月实际出勤（status=P）天数
A_W = min(worked_days / eligible_days, 1.0)
    eligible_days <= 0 时 A_W = 1.0（全豁免不罚）
```

- 旷工/挑活干（A）：worked 低、eligible 不降 → A_W < 1 → 惩罚
- 请假(L)/年假(NU)/豁免(E)：eligible 同步下降 → A_W 不受损

### 5.2 行为系数 B_W

复用现有 `compute_scoring_individuals` 产出的互评系数：

```
entries = get_scoring_card_entries(data_folder, month=month_prefix)  # 取全月全部班组
norm = normalize_scoring_entries(entries)
indiv = compute_scoring_individuals(norm, get_scoring_config(data_folder))
B_W[eid] = indiv.get(eid, {}).get('coefficient', 1.0)  # 缺省 1.0，防 KeyError
```

无互评数据时 B_W 全为 1.0，行为维度无区分。互评须持续录入。

### 5.3 综合系数 C_W 与归一化

```
C_W = accel_w_a × A_W + accel_w_b × B_W
raw_W = base_W × C_W
k = F / Σ raw_W            # F = Σ base_W = 全月固定总额
f_W = C_W × k              # 最终缩放系数
final_W = base_W × f_W
```

**总额恒定**：`Σ final_W = k × Σ raw_W = k × (F/k) = F`。

归一化因子 k 是同一个标量乘给所有人，不改变高低排序（C_W 越高者 final 占比越高，差距被拉大），但总额压回固定值 F。

### 5.4 计算示例

| 工人 | base | 出勤天 | A_W | B_W | C_W=0.6A+0.4B | raw=base×C |
|------|------|--------|-----|-----|----------------|------------|
| X | 600,000 | 26 | 1.0 | 1.2 | 1.080 | 648,000 |
| Y | 400,000 | 20 | 0.769 | 0.8 | 0.7815 | 312,600 |
| | | | | | **Σraw=960,600** | |

```
k = 1,000,000 / 960,600 = 1.04102
final_X = 648,000 × 1.04102 ≈ 674,581
final_Y = 312,600 × 1.04102 ≈ 325,319
Σfinal ≈ 1,000,000  ✓
```

X（满勤+高行为）由 600k 升至 674.6k，Y（缺勤+低行为）由 400k 降至 325.3k，差距由 200k 拉大到 349k 且总额恒定。

---

## 6. 出勤状态 E（豁免）

`E` 语义：**未出勤、不计薪、不计 A_W 惩罚**（区别于 NU 计薪，区别于 A 惩罚）。

落地四处：

1. `att_exclusions` SQL（计件人头排除）：`IN ('A','L','NU','E')`
2. `absent` 判定（逐日累加缺席）：`in ('A','L','E')`
3. 日薪/月薪轨道缺勤排除：所有 `in ('A','L')` 同步加 `E`
4. `E` 计入 `apply_v2_month_end` 的 `exempt_days` 集合（与 L/NU 同列）

`save_attendance_override` 接受 `E`。

---

## 7. calculate_all 集成

### 7.1 两阶段改法

1. **逐日循环**：按原逻辑累积 `base[eid] = pu`（尊重 per_date_type + absent/nu），不改用 `sum(ug_daily[eid].values())` 的平铺和
2. **循环后**：若 v2 active，调 `apply_v2_month_end(base, ...)` 得 `f_W`，再对每个井下工人 `pu_final = round(base[eid] × f_W[eid])` 并据此重算 gross/nssf/paye/net

### 7.2 返回体新增字段

- `ug_coefficient: {eid: f_W}`
- `ug_base: {eid: base[eid]}`
- `ug_daily` 保持 base 不被原地改写

### 7.3 防 scoring 重定向

v2 active 时 scoring 重定向块跳过（显式 `elif underground_mode == 'v2': pass`，两处）；评分奖金仍 `== 'scoring'` 才发。

### 7.4 日明细镜像

`compute_daily_breakdown` 复用与 `calculate_all` 完全相同的 `apply_v2_month_end` 产出；逐日 `daily[dt] = round(ug_daily[eid][dt] × f_W[eid])`。日明细总额 == 薪资页 piece_underground 逐人相等。

---

## 8. 验证体系

### 8.1 双路径核对

V2 月度 `Σ piece_underground(final) == Σ 日池 base`（零和归一不破总额），`|diff| ≤ 10` 视为舍入。逐日对比在 V2 下松弛（月末再分配破坏逐日相等），改为月度总额 0 偏差 + 系数守恒。

`verify_salary` 同步改：新增 `coefficient_conservation` 检查（`|Σ(base) − Σ(final)| ≤ 10`）；V2 下 daily_comparison 标记 `relaxed: true`。

### 8.2 日明细 == 薪资页

`compute_daily_breakdown` 与 `calculate_all` 共用同一 V2 月末系数，逐人逐日相等（AGENTS.md 硬性不变量）。

### 8.3 持久化

`monthly_data` 新增 `ug_base`（REAL DEFAULT 0）和 `ug_coefficient`（REAL DEFAULT 1.0）两列，`save_monthly_result` 同步写入。`piece_underground` 存 final（base × f_W）。

### 8.4 纯逻辑单测

`_work/piecework-v2/test_v2.py` 覆盖：凸性池公式、豁免锁 1.0、`apply_v2_month_end` 守恒（Σfinal==Σbase）、B_W 缺省 1.0、`v2_effective_from` 门控、E 排除。

---

## 9. 前端改动清单

### 9.1 桌面端（`templates/index.html`）

| 页面 | 改动 |
|------|------|
| 计薪参数页 | `cfg_ug_mode` 增第三选项 `value="v2"`（文案"凸性计件 V2"）；选 v2 时显示 accel_target/accel_prices(H/L/MAWE)/accel_w_a/accel_w_b/accel_full_days/v2_effective_from 输入框 |
| 井下采集表单 | 日/夜班各增班组 `<select>`（选项来自 `GET /api/employee_groups`）+「设备故障豁免」checkbox；payload `day`/`night` 加 `team_id`/`exempt` |
| 出勤网格 | 状态选项增 `E`（豁免），切换循环在井下工人新增 `E`；i18n 中/EN |
| 薪资总表 | V2 月新增/悬浮展示 base/A/B/C/f（读 `/salary` 返回的 `ug_coefficient` 与 base） |
| 日工资明细 | 逐日额 = base × f_W，与薪资页一致 |
| 周公示看板（新增） | 班组/当日车次(MAWE·L·H)/基础池/倍率/班组池/各人base/各人C(仅V2)/各人final(仅V2) |
| 员工列表 | Production TEAM (underground) 部门下按 team_id 分组/加「班组」筛选项；档案页显示班组名 |

### 9.2 移动端（`templates/mobile.html`）

| 页面 | 改动 |
|------|------|
| 井下采集 | 增班组 `<select>`（`GET /api/employee_groups`）+ 豁免 checkbox；payload 带 `team_id`/`exempt` |
| 出勤收集 | 状态 select 增 `E` 选项；与桌面端 i18n 一致 |

移动端不新增配置页/评分页。

---

## 10. 门控与历史兼容

- **唯一激活条件**：`underground_mode == 'v2' AND month_prefix >= v2_effective_from`
- 两个条件缺一不可；`v2_effective_from` 为空时 v2 永不激活
- 历史月份不重算；不回溯填历史 team_id
- piecework/scoring 模式下行为逐字节不变

---

## 11. 范围约束（Must-NOT）

- 不新建 `teams` / `team_rosters` / `production_exemptions` 表
- 不重算历史月份
- 不改动 `scoring` 三层奖金池（产量层/客观层/主观层）计算
- 不改钻工/破碎/日薪/月薪轨道公式
- 不做滚动 4 周行为分（B_W 直接复用现有互评系数）
- 不在移动端新增配置页/评分页

---

## 12. 验收标准

- [ ] `underground_mode='v2'` 下月度 `Σ piece_underground(final) == Σ 日池 base`（零和归一，≤10 舍入）
- [ ] 同产量 V2 比 piecework 收入差距显著拉大（治懒）
- [ ] 旷工 A → A_W < 1 被罚；L/NU/E → 不罚
- [ ] 设备故障豁免日倍率锁 1.0（可编辑、可审计）
- [ ] 井下生产按班组（`employee_groups`）归属，与评分系统班组对齐；不新建 teams 表
- [ ] `piecework` / `scoring` 两模式行为与升级前逐字节一致
- [ ] 双路径核对月度 0 偏差；日明细 == 薪资页（逐人逐日）
- [ ] 历史月份不重算；`v2_effective_from` 之前月份保持线性结果
- [ ] 40 车目标 / 单价 / 权重 / 满勤天数 / 生效月全部后台可编辑

---

*本文档与 V2 逻辑规格说明（`docs/计件薪资制度V2_系统规格说明.md`）配套使用。实现计划见 `.omo/plans/piecework-v2.md`。*
