# Kilwa Nickel 本地管理系统 — 开发文档

> 本文档供 WorkBuddy 专家团 / 开发者使用，完整描述业务逻辑、数据模型、技术架构和实现要点。
> 开发者：KEJU（柯举）— 常驻坦桑尼亚林迪地区，Kilwa Nickel 项目矿业运营者

---

## 一、项目概述

### 1.1 目标
构建一个本地运行的 Web 系统，用户**拖入原始 Excel 文件** → 自动解析 → 展示可编辑表格 → 用户调整 → 点按钮重算 → 输出全员工资总表和可视化汇报。所有用户编辑的记录持久化存储到 SQLite，下次启动自动加载。

### 1.2 技术选型
| 层面 | 使用 |
|------|------|
| 后端 | Python Flask 3.x |
| Excel | openpyxl |
| 前端 | 单页 HTML + JS + Chart.js（CDN） |
| 持久化 | SQLite（`data/kilwa.db`） |
| 部署 | `python app.py` → 浏览器 `localhost:8080` |

---

## 二、项目结构

```
kilwa-system/
├── app.py                     # Flask 主入口 + 全部路由
├── requirements.txt           # flask, openpyxl
├── core/
│   ├── parser.py              # Excel 解析（3个Sheet）
│   ├── namematch.py           # 姓名标准化 + 员工分类
│   ├── calculator.py          # 四轨计算引擎 + 逐日明细
│   ├── database.py            # SQLite 持久化（overrides/exclusion/config/Audit）
│   ├── exceptions.py          # 例外标记加载（兼容旧JSON）
│   ├── verification.py        # 双路径薪资核对 + 逐日对比
│   ├── advance.py             # 预支解析
├── data/
│   ├── kilwa.db               # SQLite 主库
│   └── source/                # 源 Excel 文件
├── static/css/style.css       # 全部样式
├── templates/index.html       # 单页应用（SPA）
├── start.sh / backup.sh / restore.sh
└── uploads/                   # 上传临时文件
```

---

## 三、输入文件和数据源

### 3.1 主文件
`data/source/Attendance+data+daily+and+piece+rate.xlsx`

3 个子表:
- **Sheet 1**: `Piece Rate salary attendance EV` — 产量 + 出勤 + 钻工（28天）
- **Sheet 2**: `Daily salary attendance EVERY D` — 日薪出勤记录


### 3.2 辅助文件
- `预支汇总数据.xlsx` — 预支记录（46人）
- `ENPRIZON LINDI PROJECT通讯录 (1).xlsx` — 员工通讯录（129人）

---

## 四、数据库设计（SQLite）

### 4.1 `overrides` — 薪资例外/覆盖

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| employee_id | TEXT | 员工ID |
| salary_type | TEXT | piece_underground / piece_driller / day_rate / monthly |
| day_rate | INTEGER | 日薪基数 |
| monthly_salary | INTEGER | 月薪基数 |
| start_date | TEXT | 开始日期（空=永久覆盖，非空=临时例外） |
| end_date | TEXT | 结束日期 |
| note | TEXT | 备注 |
| shift | TEXT | 井下计件班次：D/N |
| captain | TEXT | 钻工计件队长名 |

**区分永久/临时**：`start_date` 和 `end_date` 都为空 → 永久覆盖；任一非空 → 临时例外。

### 4.2 `attendance_overrides` — 出勤手动标记

| 列 | 类型 | 说明 |
|----|------|------|
| employee_id | TEXT | 员工ID |
| date | TEXT | 日期 |
| status | TEXT | P(出勤) / A(旷工) / L(请假) |

联合主键 `(employee_id, date)`，UPSERT 写入。

### 4.3 其他表
- `employees` — 员工基础信息缓存
- `settings` — 系统配置（单价等）
- `monthly_data` — 月度数据快照
- `audit_log` — 操作审计日志

---

## 五、姓名标准化管线（namematch.py）

```
make_employee_id(name):
  1. canonical(name)      → 短名/变体 映射到 标准全名
  2. re.sub(r'\s+', '', c).upper() → 去空格大写 = 唯一ID

例: 'JOSEPH DONALD(JOSEPH  DONALD MWAKALINGA)'
 → canonical → 'JOSEPH DONALD'
 → make_employee_id → 'JOSEPHDONALD'
```

---

## 六、四轨薪资计算（calculator.py）

### 6.1 轨道定义

| 轨道 | 数据源 | 单价 | 计算逻辑 |
|------|--------|------|---------|
| 井下计件 | `shift_production`（白班/夜班） | NH=6000, NL=5000, MW=4000 | 当日产量 ÷ 有效人数 |
| 钻工计件 | `driller_production`（队长+队员） | NH=5000, NL=4000, MW=3000 | 产量 ÷ (队员数+1队长份额+手动加入) |
| 日薪 | `attendance` | 员工 `day_rate` | 日薪基数 × 出勤天数 |
| 月薪 | `employees` | 员工 `monthly_salary` | 月薪 - A/L比例扣减 |

### 6.2 井下计件详细逻辑（`calc_underground_piece`）

```
对每天:
  白班: 有效人员 = day_emps - A/L排除 - ug_type_excl + shift_adds
       人均 = (NH×6000 + NL×5000 + MW×4000) / len(有效)
  夜班: 同上，使用 night_emps
  
  shift_adds: 从 overrides 表加载有 shift（D/N）的 piece_underground 临时例外，
              展开日期区间后加入对应班次
```

### 6.3 钻工计件详细逻辑（`calc_driller_piece`）

```
对每队·每天:
  产量总额 = NH×5000 + NL×4000 + MW×3000
  队员 = members - A/L排除 - dr_type_excl
  队长也受 A/L 排除 → cap_excluded 标记

  分母 = len(队员) + captain_bonus + 手动加入人数
  captain_bonus = 0（队长A/L）或 1（队长正常）
  
  每人份额 = 产量总额 / 分母
  队长得 份额×2（shares=2）
  队员得 份额×1

  队长A/L + 0队员 → denominator=0 → 跳过（产量无人接收）
```

### 6.4 日薪详细逻辑（`calc_day_salary`）

```
三个来源统计出勤天数:
  1. attendance F列（Normal attendance）
  2. shift_production 中的 day_emps/night_emps（日薪人员也在井下名单中）
  3. attendance_overrides 中的 P 标记（手动加的出勤）

A/L 覆盖 → 不计入出勤天数
日期区间 day_rate override → 区间内用覆盖的 day_rate
```

### 6.5 月薪详细逻辑（`calc_monthly_salary`）

```
月薪基数检查:
  1. 永久 day_rate override → 不计入月薪
  2. 员工 monthly_salary 或 override 中的 monthly_salary
  
当月 A/L 扣减:
  比例 = max(0, (当月工作日 - A/L天数) / 当月工作日)
  实发 = 月薪基数 × 比例
```

### 6.6 类型覆盖合并（`calculate_all`）

```
阶段1: 构建排除集合
  att_exclusions = attendance_overrides WHERE status IN ('A','L')
  has_date_range = 有日期区间的 overrides
  date_type_map = {eid: {date: type}}  ← 临时例外逐日映射
  ug_type_excl = {(eid, date)}  ← 非井下类型的人从井下排除
  dr_type_excl = {(eid, date)}  ← 非钻工类型的人从钻工排除

阶段2: 四轨计算
  传入 combined_exclusions | ug_type_excl | dr_type_excl

阶段3: 逐员合并
  永久覆盖 → 改变 effective_type（salary_type列显示）
  无日期区间:
    effective_type = piece_underground → 其他轨道清零, 只保留 pu
    effective_type = piece_driller    → 其他轨道清零, 只保留 pd
  有日期区间（含 piece 临时例外）:
    逐日按 date_type_map 选轨 ← 只统计对应轨道的 ug_daily/driller_daily 金额
    例: NANE DAUDI(driller), 临时井下05-03~14 → pu=ug_daily[05-03~14], pd=driller_daily[其他日期]
```

**关键**：临时例外只改变日期区间内的计件轨道，不改变 `salary_type` 标签。`salary_type` 仍显示永久类型，临时例外以 `temp_overrides` 标签展示。

---

## 七、出勤系统

### 7.1 状态循环

| 原始 | →1 | →2 | →3 | →4 |
|------|----|----|----|----|
| D (白班) | A (旷工) | L (请假) | '' (复位回D) | A... |
| N (夜班) | A (旷工) | L (请假) | '' (复位回N) | A... |
| P (出勤) | A (旷工) | L (请假) | '' (复位回P) | A... |
| '' (空) | P (出勤) | A (旷工) | L (请假) | ''... |

### 7.2 A/L 对计件的级联影响

```
出勤页标记 A/L → attendance_overrides 写入
                → recalculate() 触发
                → att_exclusions 加载 → 员工从当日分配中排除
                → 剩余人员平分当日产量
```

**总额守恒原则**：

| 场景 | 总额 |
|------|------|
| 井下 D/N → A/L | **不变**（其余人平分） |
| 钻工队员 A/L | **不变**（其余人平分） |
| 钻工队长 A/L + 有队员 | **不变**（队员平分，队长排除） |
| 钻工队长 A/L + 0队员 | **减产量值**（无人接收，体现在核对差异） |

---

## 八、双路径核对（verification.py）

### 8.1 路径说明

```
路径一（基准计算）：产量 × 单价，按日求和
  井下: Σ 每天（白班+夜班）× 单价
  钻工: Σ 每天各队 × 单价

路径二（实际汇总）：salary_result 中 piece_underground / piece_driller 求和
  → _path2_by_type: 按员工粒度
  → _path2_daily:   按日期粒度 ← 新增，与路径一逐日对齐
```

### 8.2 逐日对比（`daily_comparison`）

返回 `{date, path1, path2, diff, is_rounding}` 数组：
- `|diff| ≤ 10` → `is_rounding=true`, `diff=0`（浮点舍入，视为一致）
- `|diff| > 10` → 真实差异，前端高亮标红

### 8.3 当前核对状态

| 轨道 | path1 | path2 | diff | 原因 |
|------|-------|-------|------|------|
| 井下 | 9,115,000 | 8,959,001 | -155,998 | 05-25 夜班产量 156,000 无人（源数据缺员工） |
| 钻工 | 6,962,500 | 6,962,501 | +1 | 浮点舍入 |

---

## 九、逐日工资明细（`compute_daily_breakdown`）

### 9.1 与 `calculate_all` 的对称性

使用完全相同的排除逻辑（A/L + 类型 + 日期区间），调用相同的底层函数（`calc_underground_piece` / `calc_driller_piece` / `calc_day_salary` / `calc_monthly_salary`）。

### 9.2 逐日选轨合并

```
对每个员工、每个日期:
  dt_eff = per_date_type.get(日期, effective_type)
  
  dt_eff == piece_underground → 取 ug_daily[员工][日期]
  dt_eff == piece_driller    → 取 driller_daily[员工][日期]
  dt_eff == day_rate         → 取 ds_daily[员工][日期]
  dt_eff == monthly          → 取 ms_daily[员工][日期]
```

### 9.3 输出字段

```json
{
  "name": "NANE DAUDI",
  "salary_type": "piece_driller",
  "effective_type": "piece_driller",
  "daily": {"2026-05-03": 18273, "2026-05-16": 18000, ...},
  "daily_shifts": {"2026-05-03": "D"},
  "total": 407026,
  "override_dates": ["2026-05-03", ..."2026-05-14"],
  "temp_overrides": [{
    "id": 271, "label": "井下 2026-05-03~2026-05-03",
    "salary_type": "piece_underground"
  }],
  "att_override_dates": [...]
}
```

---

## 十、前端模块联动

```
┌────────────────────────────────────────────────┐
│                  员工页                         │
│  ⚙ 模态框 — 例外管理:                          │
│    ① 薪资类型设置（永久）→ /employees/override │
│    ② 添加临时例外         → /employees/override │
│    ③ 已有临时例外列表     → 预览 + ✕删除        │
│  备注列: 显示覆盖信息                           │
│  出勤状态: NSSF 开关                            │
└────────────┬───────────────────────────────────┘
             │ 保存后自动 recalculate()
             ▼
┌────────────────────────────────────────────────┐
│                  出勤页                         │
│  点击格子 → toggleAttDay() → /attendance/toggle │
│  自动触发 recalculate() + loadAttendance()      │
└────────────┬───────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────┐
│                  薪资页                         │
│  薪资表: 四轨道 + 临时例外列(只读预览)          │
│  核对面板: path1/path2/diff + 逐日对比表        │
│  日工资: 逐日明细 + override_dates 黄色虚线     │
│  产量: 可视化图表                          │
└────────────────────────────────────────────────┘
```

---

## 十一、API 路由总表

| 方法 | 路由 | 用途 |
|------|------|------|
| GET | `/` | 主页面 |
| POST | `/upload` | 上传并解析文件 |
| GET | `/employees` | 员工列表（含 override_type / overrides） |
| POST | `/employees/override` | 保存薪资覆盖（永久/临时） |
| POST | `/employees/remove-override` | 按索引删除覆盖 |
| POST | `/employees/remove-temp-override` | 批量删除临时例外 |
| POST | `/employees/remove-override-by-id` | 按数据库 ID 删除单条 |
| GET | `/salary` | 薪资计算结果（含 ug_daily/driller_daily） |
| POST | `/recalculate` | 触发重算 |
| GET | `/salary/verify` | 双路径核对（含 daily_comparison） |
| GET | `/daily-wages` | 逐日工资明细 |
| GET | `/production` | 产量数据 |
| GET | `/production-verify` | 产量路径一逐日明细 |
| GET | `/attendance` | 出勤网格数据 |
| POST | `/attendance/toggle` | 切换出勤状态（P/A/L） |
| GET | `/driller-captains` | 钻工队长列表 |
| POST | `/nssf/toggle` | 切换 NSSF 参保 |
| GET | `/config` | 获取配置（单价等） |
| POST | `/config` | 保存配置 |
| POST | `/export` | 导出 Excel |

| GET | `/audit` | 审计日志 |

---

## 十二、已知数据边界

1. **2026-05-25 夜班**：产量 156,000 但员工名单为空 → path1/path2 差异
2. **钻工 5月1-5日**：部分队伍无成员名单 → 仅队长1人
3. **同名多槽位**：同队长同天多次出现 → 产量合并、成员去重
4. **6人跨 Sheet**：同时出现在产量和日薪数据 → 需用户指定类型
5. **预支但不在主表**：Rickson 等人 → 单独列出

---

## 十三、启动方式

```bash
cd /Users/osong/WorkBuddy/kilwa-system
python3 app.py
# 浏览器 → http://localhost:8080
```

端口 8080 硬编码，如需更改编辑 `app.py`。

---

*文档版本: v2.0 | 最后更新: 2026-05-31 | 联系人: KEJU*
