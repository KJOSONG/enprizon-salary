# P28 请假规则变更 — 逻辑规格说明

> **文档目的**：描述"请假保护集合扩展 + 年假折算计发 + 病假改 OA 审批 + 取消 Y 标记"这一组变更的业务规则、公式、边界条件与实现约束，作为代码改造的对照规格与部署前评审依据。
>
> **文档状态**：所有规则已与管理者确认；本文档为冻结规格，不包含替代方案。
>
> **重要定位**：本变更是**在现有五轨计薪体系上的增量扩展**，由 DB 配置键控制生效范围，**不改变任何既有计薪轨道的基础公式**。

---

## 0. 变更总览

| 规则 | 简称 | 性质 | 生效条件 |
|------|------|------|----------|
| R1 | A_W 保护集合扩展 | V2 月末系数 | 仅 `underground_mode='v2'` 生效月 |
| R2 | 计件人头排除集合扩展 | 全局（不限模式） | 部署即生效 |
| R3 | 取消年假手动标记 Y | 全局 | 部署即生效 |
| R4 | 井下年假折算计发 | 日薪轨道特判 | 仅 v2 生效月 + UG 员工 |
| R5 | 病假改 OA 审批 | 全局 | 部署即生效 |
| R6 | 所有请假自动写网格 | 全局 | 部署即生效 |
| R7 | 新增配置键 `ug_annual_leave_monthly` | 配置 | 部署即生效 |
| R8 | 出勤码 SK 前端支持 | 全局 | 部署即生效 |

---

## 1. 背景与动机

### 1.1 既有问题

1. **A_W 保护集合过窄**：V2 月末出勤系数 `A_W` 的分母只从 {L, NU, E} 三类缺勤中扣除，调休（T）和病假（SK）同样属于"非自愿/非惩罚性缺勤"，却被计入分母，导致合法缺勤员工被双重惩罚。
2. **计件分配排除集过窄**：当日井下计件池只排除 {A, L, NU, E}，T 和 SK 员工仍被纳入均分分母，导致出勤者实际分得更少。
3. **年假 Y 标记混乱**：桌面端出勤网格存在 Y（年假手动标记）切换入口，与 NU（审批通过年假）语义重叠，且 Y 不走 OA 审批流程，数据质量不可控。
4. **病假免审直批**：旧端点 `POST /api/leave/sick` 直接落 P（视为出勤），绕过 OA 审批，无法追踪、无法扣余额、无法与出勤网格联动。
5. **病假余额扣减缺失**：普通请假（casual）审批通过后只落 L，未扣减余额；病假余额扣减逻辑仅在旧免审端点存在，OA 审批路径缺失。

### 1.2 设计目标

- 所有"非惩罚性缺勤"在 A_W 分母和计件排除集中一致处理。
- 年假统一走 OA 审批，NU 为唯一年假出勤码，Y 彻底退出。
- 病假走 OA 审批，扣 14 天/年余额，逐日落 SK。
- 所有请假类型（年假/调休/病假/普通请假）审批通过后自动写入出勤网格。
- 井下年假（NU）按配置月薪折算逐日计发，保障性收入独立于 V2 零和计件体系。

---

## 2. 出勤状态语义总表（冻结）

以下为全部出勤码的完整语义定义，作为后续所有规则的参照基准。

| 状态 | 全称 | 是否出勤 | 是否计薪 | 是否计入日薪/月薪出勤天数 | 是否排除计件分配 | A_W 保护（分母扣减） | 只读/可手动标记 | 触发条件 |
|------|------|----------|----------|--------------------------|------------------|----------------------|-----------------|----------|
| P | Present（出勤） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | ✅ 可手动 | 正常出勤 |
| A | Absent（旷工） | ❌ 否 | ❌ 否 | ❌ 否 | ✅ 是 | ❌ 否（分母不降，A_W 被罚） | ✅ 可手动 | 旷工 |
| L | Leave（请假） | ❌ 否 | ❌ 否 | ❌ 否 | ✅ 是 | ✅ 是（分母扣减） | ✅ 可手动 | 普通请假审批通过 |
| **NU** | **Annual Leave Paid（年假计薪）** | ❌ 否 | ✅ **是**（见 R4） | ❌ 否（不计入日/月薪出勤天） | ✅ 是 | ✅ 是 | **❌ 只读**（审批写入） | 年假审批通过 |
| **E** | Exempt（豁免） | ❌ 否 | ❌ 否 | ❌ 否 | ✅ 是 | ✅ 是 | ✅ 可手动 | 设备故障/矿面未备等可控缺量 |
| **T** | Time Off（调休） | ❌ 否 | ❌ 否 | ❌ 否 | ✅ 是（R2 扩展） | ✅ 是（R1 扩展） | ✅ 可手动 | 调休审批通过 |
| **SK** | **Sick Leave（病假）** | ❌ 否 | ❌ 否 | ❌ 否 | ✅ 是（R2 扩展） | ✅ 是（R1 扩展） | ✅ 可手动 | 病假审批通过 |
| S | Sick（事假） | ❌ 否 | ❌ 否 | ❌ 否 | ❌ 否 | ❌ 否 | ✅ 可手动 | 事假（当前不受保护，保持现状） |
| Y | ~~年假手动标记~~ | ~~❌ 否~~ | ~~❌ 否~~ | ~~❌ 否~~ | ~~❌ 否~~ | ~~❌ 否~~ | ~~✅ 可手动~~ | **已取消（R3）** |
| D | Day Shift（井下白班） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | ✅ 可手动 | 井下白班自动/手动 |
| N | Night Shift（井下夜班） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | ✅ 可手动 | 井下夜班自动/手动 |
| B | Both（D+N） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | ✅ 可手动 | 白班+夜班 |
| R | Driller（钻工） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | ✅ 可手动 | 钻工出勤 |
| C | Crush（破碎） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | ✅ 可手动 | 破碎出勤 |
| (P) | Monthly Default（月薪默认） | ✅ 是 | ✅ 是 | ✅ 是 | ❌ 否 | ❌ 否 | 系统自动 | 月薪员工默认 |

> **关键区分**：
> - **NU vs SK**：NU = 年假计薪（有保障性收入，只读）；SK = 病假（无保障性收入，可手动标记）。
> - **NU vs L**：NU = 审批通过年假（有折算收入，只读）；L = 普通请假（无收入，可手动）。
> - **T vs L**：T = 调休（有余额扣减，可手动）；L = 普通请假（无余额扣减，可手动）。
> - **E vs A**：E = 豁免（可控缺量，不罚 A_W）；A = 旷工（惩罚性，A_W 降低）。
> - **S 保持现状**：事假当前不在保护集合、不在排除集，本次变更不移动 S。

---

## 3. R1：V2 A_W 保护集合扩展

### 3.1 规则

V2 月末出勤系数 `A_W` 的受保护缺勤集合从 `{L, NU, E}` 扩展为 `{L, NU, E, T, SK}`。

**公式**（`_get_v2_attendance()`，`core/calculator.py` 约 1769 行）：

```python
# 变更前
if status in ('L', 'NU', 'E'):
    result[eid]['exempt'] += 1

# 变更后
if status in ('L', 'NU', 'E', 'T', 'SK'):
    result[eid]['exempt'] += 1
```

`A_W = min(worked_days / (26 − exempt_days), 1.0)`，其中 `exempt_days` 现在包含 T 和 SK 天数。

### 3.2 生效条件

仅当 `underground_mode == 'v2'` 且 `month_prefix >= v2_effective_from` 时生效。服务器当前 `underground_mode='piecework'`，此规则**当前不生效**，切 v2 后激活。

### 3.3 边界情况

- `eligible_days <= 0`（全月豁免）时 `A_W = 1.0`，不惩罚。
- T/SK 与 L/NU/E 在 A_W 计算中完全等价，无优先级差异。

---

## 4. R2：计件人头排除集合扩展

### 4.1 规则

当日井下计件池分配时，从分母排除的人员集合从 `{A, L, NU, E}` 扩展为 `{A, L, NU, E, T, SK}`。

**两处 SQL 同步修改**（`core/calculator.py`）：

| 位置 | 函数 | 行号（约） |
|------|------|-----------|
| 第一处 | `calculate_all()` | ~726 |
| 第二处 | `compute_daily_breakdown()` | ~1187 |

```python
# 变更前（两处相同）
"SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L','NU','E')"

# 变更后
"SELECT employee_id, date FROM attendance_overrides WHERE status IN ('A','L','NU','E','T','SK')"
```

### 4.2 全局生效

此规则**不限 v2 模式**，piecework / scoring / v2 三种模式下全部生效。部署即生效，与服务器当前模式无关。

### 4.3 总额守恒

被排除者（T/SK）的当日份额由剩余出勤者平分，当日计件总额不变。极端情况（全班 T/SK）→ 当日池无人领取，金额滚入 0 人除零保护路径（与现有 A/L/NU/E 行为一致）。

### 4.4 S（事假）保持现状

S 不在保护集合、不在排除集，本次变更不移动 S。

---

## 5. R3：取消年假手动标记 Y

### 5.1 规则

- **桌面端**：出勤网格状态切换循环移除 Y 选项。
- **移动端**：出勤状态选项列表移除 Y。
- **后端写入校验**：`save_attendance_override()`（`core/database.py` 约 922 行）拒绝写入 `status='Y'`，返回错误或静默忽略。
- **历史数据**：已有 Y 记录**一律不迁移、不改语义**，历史月份计算结果不得变化。

### 5.2 实现要点

```python
# core/database.py save_attendance_override 增加校验
VALID_STATUSES = {'P', 'A', 'L', 'D', 'N', 'B', 'R', 'C', 'S', 'Y', 'T', 'NU', 'E', 'SK'}
# 变更：Y 从 VALID_STATUSES 移除，或写入时拦截
```

历史 Y 数据保留原样，仅前端不再显示/切换 Y，新写入被拦截。旧月份读取时 Y 按现有逻辑处理（不参与计件、不计薪），结果不变。

---

## 6. R4：井下年假折算计发

### 6.1 规则

部门为 `Production TEAM （underground）`（数据库存储全角括号「（」「）」）且生效薪资类型 `override_type or default_type == 'piece_underground'` 的员工，每个审批通过的年假天（出勤码 NU）按 `ug_annual_leave_monthly / 26` 逐日计发。

**Per-day 取整公式**（两处必须一致）：

```python
per_day = round(ug_annual_leave_monthly / 26)
```

### 6.2 性质

- 这笔钱走**日薪轨道特判条目**（不用员工自身 `daily_rate`）。
- 属于 V2 零和计件体系**之外**的保障性收入。
- **不得计入 `ug_base`**、**不得破坏 `coefficient_conservation` 守恒检查**。
- 三处必须同步镜像：
  1. `calculate_all()` — 主计算路径
  2. `compute_daily_breakdown()` — 日工资明细
  3. `core/verification.py` 双路径核对中的日薪重建（约 1414/1430/1478 行区域已有 P/NU 计入逻辑可参照）

### 6.3 部门名规范化

数据库存储 `Production TEAM （underground）`（全角括号），后端比较必须做规范化处理：

```python
def _norm_dept(s):
    """参考前端 normDept 思路：规范化空格/全角括号/大写"""
    if not s:
        return ''
    return s.replace('（', '(').replace('）', ')').replace(' ', '').upper()
# 判定：_norm_dept(dept) == 'PRODUCTIONTEAM(UNDERGROUND)'
```

### 6.4 生效条件

仅当 `underground_mode == 'v2'` 且 `month_prefix >= v2_effective_from` 时生效。服务器当前 piecework 模式，此规则**当前不生效**。

### 6.5 配置键

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `ug_annual_leave_monthly` | int | `400000` | 井下年假折算月薪基数（TZS），必须为正数 |

---

## 7. R5：病假改 OA 审批

### 7.1 规则

新增 `employee_events` 事件类型 `'sick'`，审批路由走现有 `approval_routes` 机制。

**审批通过事务内**（`core/database.py` `apply_approved_event()`，约 1159 行起）：

1. `deduct_sick_leave()` 扣 14 天/年余额（余额不足则整单拒绝，回滚）。
2. 逐日落出勤码 `SK`（与 NU/T 同款事务逻辑）。

### 7.2 SK 语义

| 属性 | 值 |
|------|-----|
| 是否出勤 | 否 |
| 是否计薪 | 否 |
| 是否计入日薪/月薪出勤天数 | 否 |
| 是否排除计件分配 | 是（R2） |
| A_W 保护 | 是（R1） |
| 手动可标记/可修改 | 是（不像 NU 只读） |
| 审批写入 | 是（OA 审批通过后自动落 SK） |

### 7.3 旧端点兼容

`POST /api/leave/sick`（`app.py` 约 2180 行）保留路由，但内部改为：

- 创建 `employee_events` 待审事件（`event_type='sick'`），走 OA 审批流程。
- **不再免审直批**、**不再落 P**。
- 返回文案改为 `"已提交审批"`（原 `"病假已登记（免审），出勤已落 P"`）。

### 7.4 病假余额扣减

`deduct_sick_leave()` 扣减逻辑（`core/database.py`）：

```python
def deduct_sick_leave(data_folder, employee_id, year, days, default_entitled=14, conn=None):
    """扣减病假余额，余额不足返回 False"""
    # 年额度 = max(config['sick_leave_days'], default_entitled)
    # 已用 + days <= 额度 → 扣减并返回 True
    # 否则返回 False（事务回滚）
```

---

## 8. R6：所有请假申请自动写入出勤网格

### 8.1 已有逻辑

`apply_approved_event()` 中已有：

| 事件类型 | 出勤码 | 余额扣减 |
|----------|--------|----------|
| `annual_leave` | NU | `deduct_annual_leave()` |
| `comp_leave` | T | `deduct_comp_leave()` |

### 8.2 需补齐

核实普通请假（`casual`）是否有对应事件类型及自动写 L 的事务逻辑。若缺失，补齐同款事务逻辑：

```python
elif etype == 'casual':
    # 普通请假：扣余额（如有）+ 逐日落 L
    # 与 annual_leave/comp_leave 同款事务模式
```

### 8.3 病假（sick）

R5 审批通过后已在事务内逐日落 SK（见 §7.2）。

---

## 9. R7：配置键 `ug_annual_leave_monthly`

### 9.1 新增配置

| 键 | 类型 | 默认值 | 校验 |
|----|------|--------|------|
| `ug_annual_leave_monthly` | int | `400000` | 必须为正数 |

### 9.2 配置读取

`core/database.py` `_get_default_config()`（约 845 行）增加：

```python
cfg.setdefault('ug_annual_leave_monthly', 400000)
```

默认值字典同步（约 861 行）。

### 9.3 配置保存校验

`save_config()`（约 882 行）增加：

```python
if 'ug_annual_leave_monthly' in config:
    v = config['ug_annual_leave_monthly']
    if not isinstance(v, (int, float)) or v <= 0:
        raise ValueError(f"ug_annual_leave_monthly must be positive, got {v!r}")
```

### 9.4 前端

计薪参数页新增输入框（前端开发者负责，本文档仅记录需求）。

---

## 10. R8：出勤码 SK 前端支持

### 10.1 桌面端（`templates/index.html`）

- 出勤网格状态选项列表新增 `SK`（文案"病假"/"Sick Leave"）。
- 配色：建议橙色系（与 L 黄色区分），具体色值由前端设计师确认。
- i18n 中英文案（`static/js/i18n.js`）：
  - `attendance.status.SK` = `"病假"` / `"Sick Leave"`
  - `attendance.status.SK.tooltip` = `"病假（OA审批通过）"` / `"Sick Leave (OA approved)"`

### 10.2 移动端（`templates/mobile.html`）

- 出勤状态 select 选项新增 `SK`。
- 与桌面端 i18n 保持一致。

### 10.3 Y 移除

- 桌面端切换循环移除 Y。
- 移动端状态选项移除 Y。
- i18n 中 Y 相关文案保留（历史兼容），但不再在前端状态列表中引用。

---

## 11. 与既有机制的关系

### 11.1 出勤码语义矩阵

```
        计薪  计件排除  A_W保护  只读  触发方式
P       ✅    ❌      ❌      ❌    手动/自动
A       ❌    ✅      ❌(罚)   ❌    手动
L       ❌    ✅      ✅      ❌    手动/审批
NU      ✅    ✅      ✅      ✅    审批（年假）
E       ❌    ✅      ✅      ❌    手动（豁免）
T       ❌    ✅(R2)  ✅(R1)   ❌    手动/审批（调休）
SK      ❌    ✅(R2)  ✅(R1)   ❌    审批（病假）
S       ❌    ❌      ❌      ❌    手动（事假，保持现状）
Y       ❌    ❌      ❌      ❌    ~~已取消~~
```

### 11.2 与 V2 凸性计件的关系

| 规则 | V2 生效 | piecework 生效 | scoring 生效 |
|------|---------|----------------|--------------|
| R1 A_W 保护扩展 | ✅ | ❌ | ❌ |
| R2 计件排除扩展 | ✅ | ✅ | ❌（scoring 无计件池） |
| R3 取消 Y | ✅ | ✅ | ✅ |
| R4 年假折算 | ✅ | ❌ | ❌ |
| R5 病假改 OA | ✅ | ✅ | ✅ |
| R6 自动写网格 | ✅ | ✅ | ✅ |
| R7 配置键 | ✅ | 配置存在但不生效 | 配置存在但不生效 |
| R8 SK 前端 | ✅ | ✅ | ✅ |

### 11.3 与 P25 V2 的关系

- R1/R4 是 V2 月末系数的扩展，仅在 `underground_mode='v2'` 生效月激活。
- R2 是全局规则，三种模式均生效（scoring 无计件池故不涉及）。
- R3/R5/R6/R8 是全局 UI/数据规则，与计薪模式无关。
- R7 配置键在 piecework/scoring 模式下存在但不生效，无副作用。

---

## 12. 受影响文件与端点

### 12.1 后端文件

| 文件 | 改动 |
|------|------|
| `core/calculator.py` | R1：`_get_v2_attendance()` exempt 集合加 T/SK（~1789 行）；R2：两处 SQL IN 集合加 T/SK（~726/~1187 行） |
| `core/database.py` | R3：`save_attendance_override()` 校验拒绝 Y（~922 行）；R5：`apply_approved_event()` 补 sick 事件分支（~1159 行起）；R6：核实/补齐 casual 写 L 逻辑；R7：`_get_default_config()` + `save_config()` 增 `ug_annual_leave_monthly`（~845/~882 行） |
| `app.py` | R5：`POST /api/leave/sick` 改为创建待审事件（~2180 行） |

### 12.2 前端文件

| 文件 | 改动 |
|------|------|
| `templates/index.html` | R3：移除 Y 切换；R8：出勤网格增 SK 选项+i18n |
| `templates/mobile.html` | R3：移除 Y 选项；R8：出勤状态增 SK |
| `static/js/i18n.js` | R8：SK 中英文案 |

### 12.3 数据库变更

| 表 | 变更 |
|----|------|
| `settings` | 新增配置键 `ug_annual_leave_monthly`（默认 400000） |
| `attendance_overrides` | 允许 SK 写入；拒绝 Y 新写入；历史 Y 保留 |
| `employee_events` | 新增 `event_type='sick'` 支持 |

### 12.4 API 端点

| 端点 | 变更 |
|------|------|
| `POST /api/leave/sick` | 改为创建待审 OA 事件，返回"已提交审批" |
| `POST /config` | 新增 `ug_annual_leave_monthly` 校验 |
| `GET/POST /api/attendance` | 前端 SK 支持（后端无改动，SK 已是合法状态） |

---

## 13. 前端改动清单

### 13.1 桌面端（`templates/index.html`）

| 页面 | 改动 |
|------|------|
| 出勤网格 | 状态切换循环移除 Y；选项列表新增 SK（配色+文案）；i18n 引用 |
| 计薪参数页 | 新增 `ug_annual_leave_monthly` 输入框（前端开发者负责） |

### 13.2 移动端（`templates/mobile.html`）

| 页面 | 改动 |
|------|------|
| 出勤收集 | 状态 select 移除 Y；新增 SK 选项 |

### 13.3 i18n（`static/js/i18n.js`）

```javascript
// 新增
'attendance.status.SK': '病假',
'attendance.status.SK.tooltip': '病假（OA审批通过）',
'attendance.status.SK.en': 'Sick Leave',
'attendance.status.SK.tooltip.en': 'Sick Leave (OA approved)',

// Y 相关保留历史文案但不在前端状态列表中引用
```

---

## 14. 边界情况与异常处理

### 14.1 病假余额不足

`deduct_sick_leave()` 返回 `False` → `apply_approved_event()` 抛 `RuntimeError` → 事务回滚 → 事件状态保持 `pending`，出勤网格不落 SK。

### 14.2 全月豁免

`eligible_days = 26 − exempt_days <= 0` → `A_W = 1.0`，不惩罚（与现有 L/NU/E 行为一致）。

### 14.3 历史 Y 数据

历史月份 Y 记录保留原样，仅前端不再显示/切换。旧月份读取时 Y 按现有逻辑处理（不参与计件、不计薪），结果不变。

### 14.4 病假跨月

OA 审批的 `effective_date` 跨月时，`apply_approved_event()` 逐日计算，每落在不同月份的天数独立处理（与年假/调休同款逻辑）。

### 14.5 配置键不存在

旧库无 `ug_annual_leave_monthly` 键时，`_get_default_config()` `setdefault` 补默认值 400000，向后兼容。

---

## 15. 验收标准

### 15.1 R1 — A_W 保护集合

- [ ] `_get_v2_attendance()` 中 `exempt` 统计包含 T 和 SK。
- [ ] V2 生效月，T/SK 天数从 A_W 分母（26 − exempt_days）中扣除。
- [ ] Piecework/scoring 模式下 A_W 计算不受影响（R1 仅 v2 生效）。

### 15.2 R2 — 计件排除集合

- [ ] `core/calculator.py` ~726 行 SQL `IN ('A','L','NU','E','T','SK')`。
- [ ] `core/calculator.py.py` ~1187 行 SQL `IN ('A','L','NU','E','T','SK')`。
- [ ] Piecework 模式下 T/SK 员工当日不计入井下计件池分母。
- [ ] 当日计件总额守恒（被排除者份额由剩余出勤者平分）。

### 15.3 R3 — 取消 Y

- [ ] 桌面端出勤网格状态切换循环无 Y。
- [ ] 移动端出勤状态选项无 Y。
- [ ] `save_attendance_override()` 拒绝写入 `status='Y'`。
- [ ] 历史 Y 数据不变，历史月份计算结果不变。

### 15.4 R4 — 年假折算

- [ ] UG 部门（`normDept == 'PRODUCTIONTEAM(UNDERGROUND)'`）+ `piece_underground` 类型员工，NU 天按 `round(ug_annual_leave_monthly / 26)` 计发。
- [ ] 该笔钱走日薪轨道特判，不计入 `ug_base`。
- [ ] `coefficient_conservation` 检查不受影响（V2 零和守恒仍成立）。
- [ ] `calculate_all` / `compute_daily_breakdown` / `verification.py` 三处 per-day 取整公式一致。
- [ ] Piecework 模式下此规则不生效。

### 15.5 R5 — 病假改 OA

- [ ] `POST /api/leave/sick` 返回 `"已提交审批"`，不再落 P。
- [ ] 审批通过后 `deduct_sick_leave()` 扣 14 天/年余额。
- [ ] 审批通过后逐日落 SK。
- [ ] 余额不足时审批拒绝，事务回滚。
- [ ] `employee_events` 支持 `event_type='sick'`，走 `approval_routes`。

### 15.6 R6 — 自动写网格

- [ ] 年假审批通过 → 自动落 NU（已有，回归测试确认）。
- [ ] 调休审批通过 → 自动落 T（已有，回归测试确认）。
- [ ] 病假审批通过 → 自动落 SK（R5 新增，确认）。
- [ ] 普通请假（casual）审批通过 → 自动落 L（补齐后确认）。

### 15.7 R7 — 配置键

- [ ] `POST /config` 写入 `ug_annual_leave_monthly` 成功。
- [ ] 非正数被拒绝（400）。
- [ ] 旧库无此键时自动补默认值 400000。

### 15.8 R8 — SK 前端

- [ ] 桌面端出勤网格显示 SK 选项，可切换。
- [ ] 移动端出勤状态 select 含 SK。
- [ ] i18n 中英文案正确加载。
- [ ] Y 在桌面端和移动端均不可见/不可选。

---

## 16. 部署与回滚说明

### 16.1 服务器当前状态

服务器当前 `underground_mode='piecework'`（线性计件）。

| 规则 | 当前生效？ | 切 v2 后生效？ |
|------|-----------|---------------|
| R1 A_W 保护扩展 | ❌ 否 | ✅ 是 |
| R2 计件排除扩展 | ✅ 是（部署即生效） | ✅ 是 |
| R3 取消 Y | ✅ 是（部署即生效） | ✅ 是 |
| R4 年假折算 | ❌ 否 | ✅ 是 |
| R5 病假改 OA | ✅ 是（部署即生效） | ✅ 是 |
| R6 自动写网格 | ✅ 是（部署即生效） | ✅ 是 |
| R7 配置键 | ✅ 存在（部署即生效） | ✅ 是 |
| R8 SK 前端 | ✅ 是（部署即生效） | ✅ 是 |

### 16.2 部署顺序

1. **后端部署**（`core/calculator.py` + `core/database.py` + `app.py`）：R2/R3/R5/R6/R7 部署即生效；R1/R4 在 v2 生效月激活。
2. **前端部署**（`templates/*` + `static/js/i18n.js`）：R3/R8 部署即生效。
3. **配置切换**（如需激活 R1/R4）：在计薪参数页选 `underground_mode='v2'` + 填 `v2_effective_from`，下月生效。

### 16.3 回滚预案

- 后端回滚：`git pull origin main` + `systemctl restart`，所有规则恢复旧行为。
- R2 回滚影响：T/SK 重新纳入计件池分母，当日分配金额变化（需重算当月）。
- R5 回滚影响：病假恢复免审直批 P 行为。
- 历史 Y 数据不受回滚影响（已保留原样）。

---

## 17. 团队分工

| 团队 | 负责文件 | 负责规则 |
|------|---------|---------|
| **后端** | `core/calculator.py` + `core/database.py` + `app.py` | R1/R2/R3/R4/R5/R6/R7 |
| **前端** | `templates/index.html` + `templates/mobile.html` + `static/js/i18n.js` | R3/R8（R7 输入框） |

**禁止跨域编辑**：后端不碰前端文件，前端不碰后端逻辑文件。

---

*生成日期：2026-08-23 ｜ 分支：feature/v2-leave-rules ｜ 供部署前评审使用*
