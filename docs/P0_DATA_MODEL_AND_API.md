# P0 数据模型与接口契约

> **状态**：v2（评审修订 — 年假需审批+短取值 S/Y/T + 产量/出勤收集表单）
> **最后更新**：2026-08-12
> **依赖**：`REFACTOR_SPEC.md` v3（PRD）、`DEV_WORKFLOW.md`
> **产出物**：表结构定义 + API 端点草图 + 前端导航重建要点

---

## 1. 概述

本文档定义了 enprizon-salary 重构的 **P0 阶段** 产出的数据模型（SQLite 表结构）和后端 API 契约。P0 的目标：
1. 定稿所有新表 / 扩展表的字段（8 张新表 + 1 张扩展现有 employees）
2. 定稿所有新 API 端点的路径、方法、参数、返回值
3. 给出前端导航层级重建的技术要点

后续 P1–P5 各阶段将以此契约为准实现，契约一旦定稿即为"接口铁律"，前端和后端并行开发。

---

## 2. 设计原则

- **SQLite 增量建表**：`CREATE TABLE IF NOT EXISTS`，不破坏现有 11 张表。
- **时间字段统一 UTC+3**：`DATETIME('now', 'localtime')`（东非时间）。
- **employee_id 延续现有体系**：通讯录账号（如 `111`、`128`）。
- **JSON 扩展字段**：自定义/可变字段存 `TEXT` 列（JSON），标准字段独立列。
- **表单引擎 schema 驱动**：字段定义存表，前端统一渲染器。
- **权限三元组 (module, action, scope)**：用户继承角色预设 + 可单独增删细粒度权限。

---

## 3. 新表结构

### 3.1 员工主档（employees — 扩展现有表）

> 现有 `employees` 表已有 8 列：`id, name, department, default_type, day_rate, monthly_salary, nssf_enrolled, phone, note`。
> 重构在现有表上 **加列**（ALTER TABLE），不改删已有列。

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | TEXT PK | 是 | 员工 ID（通讯录账号, 如 `111`） |
| `name` | TEXT | 是 | 显示名 |
| `department` | TEXT | | 部门 |
| `position` | TEXT | | **新加**：岗位 |
| `skill_level` | TEXT | | **新加**：技能等级 |
| `hire_date` | TEXT | | **新加**：入职日期 YYYY-MM-DD |
| `nida_number` | TEXT | | **新加**：NIDA 证件号 |
| `nssf_number` | TEXT | | **新加**：NSSF 社保号（独立列） |
| `phone` | TEXT | | 电话 |
| `bank_name` | TEXT | | **新加**：银行名称 |
| `bank_account` | TEXT | | **新加**：银行账号 |
| `bank_owner` | TEXT | | **新加**：户名 |
| `status` | TEXT | 'active' | **新加**：在职状态 (active/dismissed/suspended) |
| `dismissed_at` | TEXT | | **新加**：离职日期（与 `dismissed_employees` 表同步） |
| `default_type` | TEXT | 'day_rate' | 旧列保留，逐步被 `salary_type_override` 替代 |
| `day_rate` | INTEGER | 0 | 旧列保留 |
| `monthly_salary` | INTEGER | 0 | 旧列保留 |
| `nssf_enrolled` | INTEGER | 0 | 旧列保留 |
| `note` | TEXT | | 旧列保留 |
| `custom_fields` | TEXT | '{}' | **新加**：兜底 JSON 列，表单引擎加的自定义字段存此 |

**迁移 SQL**（随 `init_db()` 追加）：

```sql
-- 逐列尝试 ALTER TABLE ADD COLUMN（SQLite 不支持 IF NOT EXISTS 加列，需 try/except）
ALTER TABLE employees ADD COLUMN position TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN skill_level TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN hire_date TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN nida_number TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN nssf_number TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN bank_name TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN bank_account TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN bank_owner TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN status TEXT DEFAULT 'active';
ALTER TABLE employees ADD COLUMN dismissed_at TEXT DEFAULT '';
ALTER TABLE employees ADD COLUMN custom_fields TEXT DEFAULT '{}';
```

**约束说明**：
- `status` = `active` | `dismissed` | `suspended`（只有 active 参与计薪）
- `dismissed_at` 填 '' 表示未离职，填日期表示离职日 → 与 `dismissed_employees` 表双向同步（写一端，另一端只读）
- 新系统入职流程直接写这批列，旧系统 `overrides` 的 salary_type / day_rate / monthly_salary 继续可用但被事件流逐步取代

---

### 3.2 生命周期事件（employee_events）

> 替代机制：OA 审批产出的事件自动驱动计薪，逐步取代 `overrides` 手动覆盖。

```sql
CREATE TABLE IF NOT EXISTS employee_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- hire / transfer / dismiss / salary_change / skill_change / reinstatement
    effective_date TEXT NOT NULL,      -- YYYY-MM-DD 生效日
    snapshot TEXT NOT NULL DEFAULT '{}', -- JSON: 变更前状态快照（用于回滚/审计）
    payload TEXT NOT NULL DEFAULT '{}',  -- JSON: 变更内容（新部门/新薪资/新岗位等）
    operator_id TEXT NOT NULL,         -- 操作人（提交审批的人）
    approved_by TEXT DEFAULT '',       -- 审批人
    rejected_by TEXT DEFAULT '',       -- 驳回操作人
    reject_reason TEXT DEFAULT '',     -- 驳回原因（驳回必填）
    status TEXT NOT NULL DEFAULT 'pending', -- pending / approved / rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_events_employee ON employee_events(employee_id, effective_date);
CREATE INDEX IF NOT EXISTS idx_events_status ON employee_events(status);
```

**event_type 枚举**：

| 值 | 含义 | payload 示例 |
|----|------|-------------|
| `hire` | 入职 | `{"name":"JOHN DOE","department":"Mining","position":"Driller",...}` |
| `transfer` | 调岗 | `{"old_department":"Mining","new_department":"Crushing","old_position":"","new_position":"Operator"}` |
| `dismiss` | 离职 | `{"dismissed_at":"2026-09-01","reason":"...","attach":"end_of_contract"}` |
| `salary_change` | 薪资变更 | `{"old_monthly_salary":300000,"new_monthly_salary":350000,"old_day_rate":0,"new_day_rate":12000}` |
| `skill_change` | 技能等级变更 | `{"old_skill_level":"Junior","new_skill_level":"Senior"}` |
| `reinstatement` | 复职 | `{"hire_date":"2026-06-01","reinstated_at":"2026-09-01","reason":"错误离职纠正"}` |

**计薪推导规则**：每月计算时，查询 `effective_date <= 本月最后一天 AND status = 'approved'` 的事件，按时间排序，从前一个已知状态开始，逐步应用事件，推导出员工当月每一天的部门/类型/薪资，作为计薪输入。

**约束**：
- 同员工同类型 `pending` 事件仅允许一条（冲突检测）。
- 调岗/薪资变 `effective_date` 不得早于入职日。
- 离职后不可再提交任意事件（除非先复职）。
- 复职 (reinstatement) ：需前置有一个 `dismiss` 事件，复职后恢复为 `active`。
- `snapshot` 记录变更前的员工状态（用于审批人参考 + 审计回滚）。

---

### 3.3 请假记录（leave_requests）

```sql
CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,          -- casual / annual / compensatory
    start_date TEXT NOT NULL,          -- YYYY-MM-DD
    end_date TEXT NOT NULL,            -- YYYY-MM-DD（单天时 = start_date）
    duration_days INTEGER NOT NULL DEFAULT 1, -- 请假天数
    reason TEXT DEFAULT '',            -- 事假原因（必填；年假/调休可选）
    submitted_by TEXT NOT NULL,        -- 提单人（班组长代提）
    approved_by TEXT DEFAULT '',       -- 审批人（仅事假）
    status TEXT NOT NULL DEFAULT 'pending', -- pending / approved / rejected
    reject_reason TEXT DEFAULT '',     -- 驳回原因（驳回必填）
    transferred_to TEXT DEFAULT '',    -- 转交对象（user_id）
    balance_before INTEGER DEFAULT 0,  -- 提交前余额（年假/调休，用于审批参考）
    balance_after INTEGER DEFAULT 0,   -- 审批后余额
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_leave_employee ON leave_requests(employee_id, start_date);
CREATE INDEX IF NOT EXISTS idx_leave_status ON leave_requests(status);
CREATE INDEX IF NOT EXISTS idx_leave_month ON leave_requests(start_date);
```

**审批规则**：
- `casual`（事假）→ 提交 → 待审 → 批准 / 驳回（填 reject_reason）/ 转交（填 transferred_to）→ 批准后自动落出勤状态 `S`
- `annual`（年假）→ **也需审批** → 提交 → 待审 → 批准 / 驳回 / 转交 → 批准后扣余额 + 落出勤 `Y`
- `compensatory`（调休）→ 提交即 `status='approved'`（免审）→ 自动扣余额 + 落出勤 `T`

**年假申请资格（提交时硬拦截）**：
- 必须同时满足：① `nssf_enrolled=1` ② `nida_number` 非空 ③ 入职满 1 年（`hire_date` 距今天数 ≥ 365）
- 不满足任一 → 返回 `{"error":"该员工不符合年假申请条件（需缴纳 NSSF、有 NIDA 证件号、入职满 1 年）"}`

**额度检验（提交时拦截）**：
- 年假余额不足 → `{"error":"年假余额不足, 当前剩余 X 天"}`
- 调休余额不足 → `{"error":"调休余额不足, 当前剩余 X 天"}`
- 事假不校验额度

**出勤联动**：
- 请假批准后，自动向 `attendance_overrides` 写入对应日期：
  - 事假 → `status = 'S'`
  - 年假 → `status = 'Y'`
  - 调休 → `status = 'T'`

---

### 3.4 请假余额（leave_balances）

```sql
CREATE TABLE IF NOT EXISTS leave_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,          -- annual / compensatory
    total_entitled INTEGER NOT NULL DEFAULT 0,  -- 总额度（天）
    used INTEGER NOT NULL DEFAULT 0,           -- 已休天数
    balance INTEGER NOT NULL DEFAULT 0,         -- 剩余天数（衍生 = total - used）
    as_of_month TEXT NOT NULL,                  -- YYYY-MM 归属月份
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    UNIQUE(employee_id, leave_type, as_of_month)
);
CREATE INDEX IF NOT EXISTS idx_balance_employee ON leave_balances(employee_id, leave_type);
```

**计算规则**：

| 类型 | 额度规则 | 说明 |
|------|---------|------|
| 年假 | 每年 1 月 1 日自动发放 **28 天**给符合资格员工 | 仅限 `nssf_enrolled=1` 且 `nida_number` 非空的正式员工；入职未满 1 年不发放 |
| 调休 | `在职月数 × 4` | 每个完整月累积 4 天（不满月 = 0；离职月按实计） |

**年假发放逻辑**（每年 1 月 1 日系统自动执行）：
```python
# 每年 1/1 自动为满足条件的员工发放 28 天年假额度
eligible = employees WHERE nssf_enrolled=1 AND nida_number!='' AND status='active'
for emp in eligible:
    if days_since(emp.hire_date) >= 365:
        INSERT INTO leave_balances (employee_id, leave_type, total_entitled, as_of_month)
        VALUES (emp.id, 'annual', 28, f'{current_year}-01')
```

**年假余额调整**：
- 管理员可在系统配置中手动修改某员工的 `leave_balances.total_entitled`（增加或扣减）
- 也可通过修改 `employees.hire_date` 来间接控制年假发放资格（入职不满 1 年 → 不发放）
- 所有余额修改操作写入 `audit_log`

> `used` = 计算 `leave_requests` 中该类型已批准的 `SUM(duration_days)`。
> `balance` = `entitled - used`。这三个值由 API 实时计算返回。

---

### 3.5 司机名单（driver_roster）

```sql
CREATE TABLE IF NOT EXISTS driver_roster (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    effective_from TEXT NOT NULL,      -- YYYY-MM-DD
    effective_to TEXT DEFAULT '',      -- YYYY-MM-DD, 空 = 永久
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_driver_roster_employee ON driver_roster(employee_id);
```

**用途**：
- 白名单管控：仅名单内人员可在出勤网格勾选"驾驶"，触发 5,000 TZS/班司机津贴。
- `effective_to` 为空表示永久有效；有值表示该日之后失去驾驶资格。
- 历史记录保留（不物理删除，逻辑过期）。

**校验逻辑**：
- 出勤提交"驾驶"勾选时 → 查 `employee_id` 在 `driver_roster` 且有有效记录（`effective_from <= 出勤日 <= (effective_to 或 ∞)`）
- 不在名单 → 返回 `{"error":"该员工不在司机名单中，无法勾选驾驶"}`

**津贴计薪逻辑**（替代旧 `_apply_driver_allowance`）：
- 每月计算时，统计该员工当月勾选"驾驶"的班次数 → 津贴 = 班次数 × 5,000 → 流入净额。
- 仅井下出渣工人产生，其他部门不涉及。

---

### 3.6 表单定义（form_schemas / form_fields）

```sql
CREATE TABLE IF NOT EXISTS form_schemas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    form_name TEXT NOT NULL UNIQUE,    -- 表单标识: 'employee_onboarding' / 'employee_profile' 等
    form_label TEXT NOT NULL,          -- 中文标签
    form_label_en TEXT DEFAULT '',     -- 英文标签
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS form_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,          -- 字段名（存 JSON 的 key）
    field_type TEXT NOT NULL DEFAULT 'text', -- text / number / select / date / textarea / toggle
    field_label TEXT NOT NULL,         -- 中文标签
    field_label_en TEXT DEFAULT '',    -- 英文标签
    options TEXT DEFAULT '[]',         -- JSON: [{"value":"option1","label":"选项1","label_en":"Option1"}]
    required INTEGER DEFAULT 0,        -- 0/1 是否必填
    default_value TEXT DEFAULT '',     -- 默认值
    placeholder TEXT DEFAULT '',
    visible_roles TEXT DEFAULT '[]',   -- JSON: ['super_admin','admin']，空数组 = 所有角色可见
    sort_order INTEGER DEFAULT 0,      -- 排序
    is_builtin INTEGER DEFAULT 0,      -- 0=自定义, 1=内置不可删
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (schema_id) REFERENCES form_schemas(id),
    UNIQUE(schema_id, field_name)
);
CREATE INDEX IF NOT EXISTS idx_form_fields_schema ON form_fields(schema_id, sort_order);
```

**设计说明**：
- 每张表单一个 `schema` → 多条 `field` 记录。
- 前端统一 `FormRenderer(schema_name)` 组件：读 fields → 按 sort_order 渲染表单控件。
- 内置字段 (`is_builtin=1`) 不可删除，自定义字段可增删改。
- 数据存储：标准字段落独立列，自定义字段写 `employees.custom_fields` JSON。

**默认种子数据（6 张预置表单）**：

| schema_name | 说明 | 关键字段 |
|-------------|------|---------|
| `employee_onboarding` | 入职表单 | name/dept/position/hire_date/nida/nssf_number/phone/bank_* |
| `employee_profile` | 员工档案编辑表单 | 同 onboarding + 可编辑的自定义字段 |
| `employee_oa_transfer` | 调岗 OA 表单 | new_department/new_position/effective_date |
| `attendance_collection` | 出勤收集表（各部门提交） | date + 花名册点选员工 + P/A/S/Y/T 状态 + 是否驾驶 |
| `production_underground` | 产量收集 — 井下出渣 | date/shift(D/N)/NICKEL_H/NICKEL_L/MAWE 产量 + 工人名单 |
| `production_driller` | 产量收集 — 钻工组 | date/captain/NICKEL_H/NICKEL_L/MAWE 产量 + 队员名单 |
| `production_crush` | 产量收集 — 破碎计件 | date/bags + 工人名单 |

**不再构建产量收集表单的字段**（仅旧系统做数据迁移时解析，Web 表单不展示）：
- `WAYA` / `KIBIRITI` / `IED` / `FUTA`（炸药/引信/油耗，已在原 Excel 中存在但新系统不录入）

---

### 3.7 权限（permissions / user_grants / user_roles）

```sql
-- 预设角色（角色本身是 admin_users.role 的增强版）
CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name TEXT NOT NULL UNIQUE,    -- super_admin / admin / manager / team_lead / viewer
    role_label TEXT NOT NULL,          -- 中文标签
    role_label_en TEXT DEFAULT '',
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 权限定义（独立于角色）
CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,              -- 模块: employees / attendance / production / salary / scoring / system / oa
    action TEXT NOT NULL,              -- 动作: view / create / edit / delete / approve / export
    description TEXT DEFAULT '',
    UNIQUE(module, action)
);

-- 角色预设权限（角色 → 继承哪些权限）
CREATE TABLE IF NOT EXISTS role_permissions (
    role_name TEXT NOT NULL,
    permission_id INTEGER NOT NULL,
    data_scope TEXT NOT NULL DEFAULT 'all', -- all / team / self（该角色默认数据范围）
    PRIMARY KEY (role_name, permission_id),
    FOREIGN KEY (role_name) REFERENCES user_roles(role_name),
    FOREIGN KEY (permission_id) REFERENCES permissions(id)
);

-- 用户个性化权限（在角色基础上增删）
CREATE TABLE IF NOT EXISTS user_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,             -- admin_users.username
    permission_id INTEGER NOT NULL,
    data_scope TEXT NOT NULL DEFAULT 'all', -- all / team / self
    granted_by TEXT DEFAULT '',
    granted_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    revoked INTEGER DEFAULT 0,         -- 0=有效, 1=已撤销
    FOREIGN KEY (permission_id) REFERENCES permissions(id),
    UNIQUE(user_id, permission_id)
);
CREATE INDEX IF NOT EXISTS idx_user_grants_user ON user_grants(user_id);

-- 班组长-班组 关联（决定 "team" scope 的数据范围）
CREATE TABLE IF NOT EXISTS team_memberships (
    team_lead_user_id TEXT NOT NULL,   -- 班组长 login user
    employee_id TEXT NOT NULL,         -- 其组内员工
    PRIMARY KEY (team_lead_user_id, employee_id),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
```

**权限优先级（从高到低）**：
1. `user_grants` 中显式授予且未撤销 → 以此为准
2. `role_permissions` 角色预设 → 作为默认值
3. 没有任何权限 → 拒绝访问

**权限判定伪代码**：
```python
def has_permission(user_id, module, action, target_employee_id=None):
    # 1. 查 user_grants（revoked=0）→ 有则直接返回
    # 2. 查 user.role → role_permissions → 有则继续
    # 3. 查 data_scope:
    #    - 'all': 允许
    #    - 'team': 查 team_memberships 确认 target_employee_id 属于该班组
    #    - 'self': 仅限自己
    # 4. 全无 → 拒绝
```

**预设种子数据**：

| 角色 | 模块:动作 | 数据范围 |
|------|----------|----------|
| super_admin | 全部:* | all |
| admin | 全部:* | all |
| manager | all:view + production:create/edit + attendance:create/edit + oa:create | all |
| team_lead | production:create/edit,attendance:create/edit,oa:create | team |
| viewer | all:view | all |

---

### 3.8 旧数据归档（archived_kilwa — 概念表）

不建物理表。通过 SQLite `ATTACH DATABASE` 将旧 `kilwa.db` 挂载为 `archived_kilwa`，提供只读查询，数据模型对齐现有 11 张表结构不变。

```sql
-- app 启动时
ATTACH DATABASE 'data/kilwa.db' AS archived_kilwa;
```

前端在"系统管理 → 旧数据归档"页面提供只读查询。
不回溯、不事件化，旧库数据不迁移到新表（C4 约束）。

---

### 3.9 评分与客观层表（P3+P10，2026-08-13 回写）

权威 schema 见 `core/database.py`（init_db 内 `CREATE TABLE IF NOT EXISTS`）。评分奖金三层模型数值以《生产团队绩效考核体系管理手册.docx》为准（详见 `REFACTOR_SPEC.md` §5.6.6）。

**scoring_cards** — 评分卡主表（旧表，P10 起录入走新表 `scoring_card_entries`，本表保留兼容）

```sql
CREATE TABLE scoring_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week INTEGER NOT NULL,
    team INTEGER NOT NULL,          -- 班组 id（对应 employee_groups.id）
    card_no TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '工友',  -- '工友' | '管理'
    month TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(week, team, card_no, source, month)
);
```

**scoring_entries** — 评分明细（旧表，按被评人一行；新录入写入 `scoring_card_entries`）

```sql
CREATE TABLE scoring_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL REFERENCES scoring_cards(id),
    target_wid TEXT NOT NULL,           -- 被评人工号（如 W1）
    target_employee_id TEXT NOT NULL,   -- 被评人 employee_id
    initiative INTEGER DEFAULT 0,       -- 6 维：主动/勤快/纪律/协作/安全/驾驶
    diligence INTEGER DEFAULT 0,
    discipline INTEGER DEFAULT 0,
    cooperation INTEGER DEFAULT 0,
    safety INTEGER DEFAULT 0,
    driving INTEGER DEFAULT NULL,       -- 仅驾驶员评，非驾驶员 NULL
    UNIQUE(card_id, target_wid)
);
```

**scoring_card_entries** — 评分明细（**新表，P10 重设计，奖金计算读此表**）

```sql
CREATE TABLE scoring_card_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week INTEGER NOT NULL,
    team_id INTEGER NOT NULL,           -- 班组 id
    card_no TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '工友',
    subject_employee_id TEXT NOT NULL,  -- 被评人 employee_id
    subject_name TEXT,
    initiative INTEGER, diligence INTEGER, discipline INTEGER,
    cooperation INTEGER, safety INTEGER, driving INTEGER,
    operator_id TEXT,                   -- 评分人
    submitted_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(week, team_id, card_no, source, subject_employee_id)
);
```

**objective_records** — 客观层数据（R1/R2 → 当日 S）

```sql
CREATE TABLE objective_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    team INTEGER NOT NULL,              -- 班组 id
    planned_output REAL DEFAULT 0,      -- 计划出渣量（管理手工设定）
    actual_output REAL DEFAULT 0,       -- 实际出渣量（由井下采集自动带出：当日 nh+nl+mw）
    total_hours REAL DEFAULT 0,         -- 在井总时长
    effective_hours REAL DEFAULT 0,     -- 有效作业时间
    week INTEGER NOT NULL,
    daily_s REAL DEFAULT 0,             -- 当日 S = R1×70% + R2×30%（计划=0 时 = R2×30%）
    UNIQUE(record_date, team)
);
```

计算函数：
- `save_objective_entry()`（`core/database.py`）：R1 = actual/planned×100（不封顶）、R2 = min(effective/total×100, 100)、daily_s = R1×0.7 + R2×0.3（planned=0 时 S = R2×0.3）
- `get_monthly_objective()`（`core/database.py`）：月度 S = 全月当日 S 均值；发放比例 **90/80/70/60 五档**（≥90→1.0, 80-89→0.95, 70-79→0.9, 60-69→0.8, <60→0.7）

---

## 4. 现有表演进

### 4.1 attendance_overrides（出勤覆盖表）

> 现有列: `employee_id, date, status (P/A/L)`
> **重构**：扩展 `status` 的取值范围，新增请假类型区分。

**新 status 取值**：

| 值 | 含义 | 来源 | 冲突说明 |
|----|------|------|----------|
| `P` | 出勤 | 旧有 / 手动标记 | |
| `A` | 旷工 | 旧有 / 手动标记 | ⚠️ 保留，不可复用为年假 |
| `L` | 请假（旧版） | 旧有，逐步被三态替代 | 保留兼容，前端不再新增 |
| `S` | 事假 (Shi4) | 请假审批通过自动写入 | S=事假首字母 |
| `Y` | 年假 (Year) | 请假审批通过自动写入 | Y=Year/年假首字母 |
| `T` | 调休 (Tiao2) | 请假记录后自动写入 | T=调休首字母 |

> 取值设计约束：**单个英文字母**，在出勤网格单元格中不撑宽列。
> 已占用的单字母不可复用：`D`(井下白班)、`N`(夜班)、`B`(D+N)、`R`(钻工)、`C`(破碎)、`P`(出勤)、`A`(旷工)、`L`(旧请假)。
> 因此事假/年假/调休分别用 S/Y/T，不与现有值冲突。

### 4.2 dismissed_employees（离职员工表）

> 保留现有表，但 `dismiss` 事件通过 OA 流程产生后**双向同步**：
> - `employees.status = 'dismissed'`, `employees.dismissed_at = 事件.effective_date`
> - `dismissed_employees` 表同步写入相同记录
> - 前端显示不再只查 `dismissed_employees`，改为查 `employees WHERE status='dismissed'`

### 4.3 其他表（不变）

| 表 | 状态 | 说明 |
|----|------|------|
| `monthly_data` | 沿用 | 薪资结果快照，保持结构不变 |
| `settings` | 沿用 | 计薪参数，`/config` API 不变 |
| `audit_log` | 沿用 | 审计日志，所有新操作也写此表 |
| `shift_additions` | 沿用 | 产量 Web 录入直写此表 |
| `driller_additions` | 沿用 | 产量 Web 录入直写此表 |
| `bonus_penalties` | 沿用 | 保持现有结构 |
| `admin_users` | 演进 | 用户认证表，role 列继续使用；新增 `user_roles` 表作为权限定义 |

---

## 5. API 端点契约

> 所有端点前缀为 `/api`（需要登录 session）或 `/api/public`（无需认证）。
> 权限标注：(S=super_admin, A=admin, M=manager, T=team_lead, V=viewer)。
> 时间格式：`YYYY-MM-DD`、`YYYY-MM`。
> 返回格式：`{"success": bool, "data": ..., "error": "..."}`。

### 5.1 员工管理 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/employees` | V+ | 员工列表。参数：`?status=active` / `?department=Mining` / `?search=name` / `?page=1&limit=50`。返回分页员工列表 |
| GET | `/api/employees/<id>` | V+ | 员工档案详情：基本信息 + 最近事件 + 请假汇总 + 关联薪资入口 |
| POST | `/api/employees/<id>` | M+ | 编辑员工基本信息（含银行字段、技能等级等） |
| GET | `/api/employees/<id>/events` | V+ | 员工生命周期时间线。参数：`?type=transfer&year=2026` |
| GET | `/api/employees/<id>/timeline` | V+ | 时间线：按日期排序的事件列表（含请假记录） |
| GET | `/api/employees/<id>/leaves` | V+ | 员工请假记录汇总。参数：`?year=2026` / `?type=annual` |

### 5.2 OA 审批 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/oa/events` | T+ | 发起 OA 事件（hire/transfer/dismiss/salary_change/skill_change）。Body: {event_type, employee_id, effective_date, payload} |
| GET | `/api/oa/pending` | A+ | 待审批列表（按提交时间排序） |
| GET | `/api/oa/pending/count` | A+ | 待审批数量（badge 数字） |
| POST | `/api/oa/events/<id>/approve` | A+ | 批准事件 |
| POST | `/api/oa/events/<id>/reject` | A+ | 驳回事件。Body: {reject_reason}（必填） |
| POST | `/api/oa/events/<id>/transfer` | A+ | 转交事件。Body: {transferred_to}（user_id） |
| GET | `/api/oa/events` | M+ | 事件列表（已审批+待审）。参数：`?status=pending` / `?employee_id=xxx` / `?type=hire` / `?month=2026-08` |

**关键约束实现**：
- 防自批：`POST /api/oa/events/<id>/approve` 中，当前用户 = 提交人 → 拒绝
- 冲突检测：同一员工同一类型不能有多个 `pending` 事件
- 合法日期：`effective_date` 不能早于入职日（`hire_date`）
- 离职阻断：离职员工不能提交新 OA 事件

### 5.3 请假 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/leaves` | T+ | 提交请假。Body: {employee_id, leave_type, start_date, end_date, reason?} |
| GET | `/api/leaves` | M+ | 请假列表。参数：`?employee_id=xxx` / `?type=annual` / `?status=pending` / `?month=2026-08` / `?page=1` |
| GET | `/api/leaves/<id>` | V+ | 单条请假详情 |
| POST | `/api/leaves/<id>/approve` | A+ | 批准请假（**事假和年假通用**，调休免审批不走此接口） |
| POST | `/api/leaves/<id>/reject` | A+ | 驳回请假。Body: {reject_reason}（必填） |
| POST | `/api/leaves/<id>/transfer` | A+ | 转交请假。Body: {transferred_to} |
| GET | `/api/leaves/balances/<employee_id>` | V+ | 查员工年假/调休余额 |
| GET | `/api/leaves/balances` | M+ | 批量查余额。参数：`?department=Mining`（可选） |
| PUT | `/api/leaves/balances/<employee_id>/annual` | A+ | 管理员手动调整年假余额。Body: {total_entitled: 28} |

**提交时校验逻辑**：
```python
# 年假资格校验（硬拦截）
if leave_type == "annual":
    if not employee.nssf_enrolled or not employee.nida_number:
        return {"error": "该员工不符合年假申请条件（需缴纳 NSSF、有 NIDA 证件号）"}
    if days_since(employee.hire_date) < 365:
        return {"error": "该员工入职未满 1 年，不得申请年假"}
    entitled = get_annual_balance(employee.id, current_year)
    used = sum_approved_leave_days(employee.id, 'annual', current_year)
    if used + requested_days > entitled:
        return {"error": f"年假余额不足, 当前剩余 {entitled - used} 天"}
elif leave_type == "compensatory":
    entitled = compute_compensatory_entitled(employee.hire_date)
    used = sum_approved_leave_days(employee.id, 'compensatory')
    if used + requested_days > entitled:
        return {"error": f"调休余额不足, 当前剩余 {entitled - used} 天"}

# 调休免审直接通过；事假和年假进入 awaiting approval 流程
if leave_type == "compensatory":
    status = "approved"
else:
    status = "pending"
```

**余额计算函数**：

```python
def compute_annual_entitled(employee_id, year):
    """年假额度：从 leave_balances 表读取（每年 1/1 自动发放），管理员可手动调整"""
    balance = db.query("SELECT total_entitled FROM leave_balances WHERE employee_id=? AND leave_type='annual' AND as_of_month LIKE ?",
                       (employee_id, f"{year}-%"))
    return balance[0] if balance else 0

def is_eligible_for_annual_leave(employee):
    """年假资格：nssf_enrolled=1 AND nida_number 非空 AND 入职满 1 年"""
    if not employee.nssf_enrolled or not employee.nida_number:
        return False
    return (today - employee.hire_date).days >= 365

def compute_compensatory_entitled(hire_date_str):
    """调休额度：在职完整月数 × 4"""
    full_months = compute_full_months_since_hire()
    return full_months * 4
```

### 5.4 考勤 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/attendance` | V+ | 月度出勤网格。参数：`?month=2026-08` / `?department=Mining` |
| POST | `/api/attendance/toggle` | T+ | 手动标记出勤（P/A/L/S/Y/T）。Body: {employee_id, date, status} |
| POST | `/api/attendance/drive` | T+ | 勾选/取消"驾驶"。Body: {employee_id, date, drive: bool} |
| POST | `/api/attendance/collect` | T+ | **出勤收集表提交**（部门负责人一次性提交当日本组多人出勤）。Body: {date, entries: [{employee_id, status(P/A/S/Y/T), drive?}]} |
| GET | `/api/attendance/roster` | T+ | 获取花名册（本组员工列表，供出勤收集表点选）。返回 [{employee_id, name, department}] |

**出勤收集表设计要点**：
- 前端从 `GET /api/attendance/roster` 获取花名册，渲染为**可搜索/多选的点名列表**，部门负责人点选即可，不手输姓名
- 提交时每个 entry 可附带 `status`（P/A/S/Y/T）和可选的 `drive` 勾选
- 驾驶勾选校验同旧逻辑：不在 `driver_roster` 则拦截

**驾驶勾选校验**：
```python
# 出勤提交前
if drive:
    if not is_on_driver_roster(employee_id, date):
        return {"error": "该员工不在司机名单中"}
```

### 5.5 产量录入 API

> 产量采集走表单引擎渲染（`production_underground` / `production_driller` / `production_crush` 三张 schema），数据直写现有 `shift_additions` / `driller_additions` 表 + 产量临时表。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/production` | V+ | 产量列表。参数：`?month=2026-08` / `?track=underground`(piece_underground/driller/crush) |
| GET | `/api/production/my-team` | T+ | 仅返回本组产量（班组长权限过滤） |
| POST | `/api/production/underground/submit` | T+ | 提交井下产量（从 `production_underground` 表单渲染的 UI 收集）。Body: {date, entries: [{employee_id, shift(D/N), NH, NL, MW}]} |
| POST | `/api/production/driller/submit` | T+ | 提交钻工产量（从 `production_driller` 表单渲染）。Body: {date, captain_id, entries: [{employee_id, NH, NL, MW}]} |
| POST | `/api/production/crush/submit` | T+ | 提交破碎计件（从 `production_crush` 表单渲染）。Body: {date, bags, employee_ids: [...]} |

**产量数据流**：
```
生产表单 UI (schema 驱动渲染) → POST submit API 校验
  → 写入 production_records 表（新增，统一产量存储）
  → 计薪时 calculator 从此表读取（替代 Excel parser 的同源数据）
  → 旧 shift_additions / driller_additions 继续用于手动补充，与 production_records 合并
```

**新增产量存储表**（独立于 shift/driller additions，后者仅用于手动补录）：

```sql
CREATE TABLE IF NOT EXISTS production_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,              -- YYYY-MM-DD
    track TEXT NOT NULL,            -- underground / driller / crush
    employee_id TEXT NOT NULL,
    shift TEXT DEFAULT '',          -- D / N (仅 underground)
    captain_id TEXT DEFAULT '',     -- 钻工队长 (仅 driller)
    nh REAL DEFAULT 0,             -- NICKEL（H）产量
    nl REAL DEFAULT 0,             -- NICKEL（L）产量
    mw REAL DEFAULT 0,             -- MAWE 产量
    bags INTEGER DEFAULT 0,        -- 破碎袋数 (仅 crush)
    submitted_by TEXT NOT NULL,    -- 录入人
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_prod_date ON production_records(date);
CREATE INDEX IF NOT EXISTS idx_prod_track ON production_records(track, date);
```

> 班组长 `team` scope：通过 `team_memberships` 表确定本组员工，越权访问他组 → 空/拒绝。
> **炸药/柴油不再录入**：旧系统解析的 WAYA/KIBIRITI/IED/FUTA 字段仅为历史数据迁移保留，Web 表单不展示。

### 5.6 司机名单 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/driver-roster` | M+ | 司机名单列表。参数：`?active_only=1`（仅有效期内） |
| POST | `/api/driver-roster` | A+ | 添加司机。Body: {employee_id} |
| DELETE | `/api/driver-roster/<id>` | A+ | 移除司机（设 effective_to = 当天，不物理删除） |
| GET | `/api/driver-roster/check/<employee_id>` | T+ | 检查某人是否在司机名单中 |

### 5.7 表单引擎 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/forms/schemas` | M+ | 表单列表。返回所有 schema 名称和标签 |
| GET | `/api/forms/schemas/<name>` | M+ | 表单字段定义。参数：`?lang=zh/en`。返回按 sort_order 排的字段列表 |
| POST | `/api/forms/fields` | A+ | 添加字段。Body: {schema_id, field_name, field_type, field_label, ...} |
| PUT | `/api/forms/fields/<id>` | A+ | 编辑字段 |
| DELETE | `/api/forms/fields/<id>` | A+ | 删除字段。is_builtin=1 的拒绝删除 |

### 5.8 权限管理 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/admin/permissions` | S+ | 权限定义列表（module/action 全量） |
| GET | `/api/admin/roles` | S+ | 所有角色及预设权限 |
| GET | `/api/admin/users/<username>/grants` | S+ | 某用户的个性化权限 |
| POST | `/api/admin/users/<username>/grants` | S+ | 为用户增/删权限。Body: {permission_id, data_scope, action: grant/revoke} |
| GET | `/api/admin/team-members` | M+ | 班组关联列表（班组长→员工映射） |
| POST | `/api/admin/team-members` | A+ | 添加班组关联。Body: {team_lead_user_id, employee_id} |
| DELETE | `/api/admin/team-members` | A+ | 删除班组关联。Body: {team_lead_user_id, employee_id} |

### 5.9 种子导入 API（P0/P5）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/seed/employees` | S+ | 从旧 kilwa.db 批量导入在职员工 → 新 employees 表（含入职事件）。Body: {month: "2026-08"} |
| GET | `/api/seed/preview` | S+ | 预览待导入员工列表（用于确认） |

**导入逻辑**：
```python
# 读旧库中出现在 monthly_data 最近月的中所有 employee_id
# 对于每个 employee_id，查旧 employees 表取 name/dept → INSERT OR REPLACE 入新 employees 表
# 为每人额外写入一条 hire event（effective_date = 入职日或 '2024-01-01' 默认值）
# 写入 audit_log
# 旧库不删不改
```

### 5.10 薪资计算 API（保持兼容）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/recalculate` | M+ | 触发重新计算（沿用现有逻辑），但输入数据源逐步从 Excel parser 切换到 DB 直读 |
| GET | `/api/salary` | V+ | 薪资总表 |
| GET | `/api/salary/verify` | V+ | 双路径核对 |
| GET | `/api/daily-wages` | V+ | 日工资明细 |
| POST | `/api/export` | M+ | 薪资 Excel 导出 |
| POST | `/api/export/all` | M+ | 英文版全量导出（7 Sheet） |

### 5.11 评分与客观层 API（P3+P10，2026-08-13 回写）

权限缩写：S=super_admin, A=admin, M=editor(编辑), V=viewer，"+"表示及以上。

**评分卡录入（新表 `scoring_card_entries`，P10 主路径）**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/scoring/card` | M+ | 提交/更新一张评分卡。Body: {week, team_id, card_no, source, rows:[{subject_employee_id, subject_name, initiative, diligence, discipline, cooperation, safety, driving}]}。先删后插 |
| GET | `/api/scoring/card` | M+ | 读取一张卡明细。Query: team_id, week, card_no, source |
| DELETE | `/api/scoring/card` | M+ | 删除一张卡。Query: team_id, week, card_no, source |
| GET | `/api/scoring/entries` | M+ | 查询评分明细（新表）。Query: team_id, week, source |
| GET | `/api/scoring/team/<int:team_id>/month/<month>` | M+ | 按班组+月份取评分全员列表（含 custom_number 工号） |
| POST | `/api/scoring/card/batch` | M+ | 批量提交（**兼容接口，写旧表** scoring_cards/scoring_entries，供 Excel 导入脚本使用） |

**评分汇总/配置/奖金**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/scoring/summary/<int:team>` | M+ | 班组汇总：逐人 peer_behavior / mgmt_behavior / final_behavior（管理 1.5 票）/ coefficient / deviation + 三闸 gates（零方差/最高档/管理偏离）。**读新表，旧表回退** |
| GET | `/api/scoring/week/<int:team>/<int:week>` | M+ | 周评分卡列表（旧表） |
| GET | `/api/scoring/config` | A+ | 评分配置（mgmt_vote_weight=1.5 / mgmt_deviation_threshold=15 / zero_variance_threshold=8 / max_tier_ratio=0.3） |
| POST | `/api/scoring/config` | A+ | 更新评分配置 |
| GET | `/api/scoring/bonus/<int:team>` | M+ | 班组奖金池预览。Query: half_pool（前端可传半池值）→ 返回 team_pool = half_pool×distribution_ratio、ratio、monthly_s |

**客观层（R1/R2 → S）**

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/objective/entry` | M+ | 客观层录入。Body: {record_date, team, week, planned_output, actual_output, total_hours, effective_hours}。返回 daily_s。**actual_output 可由前端从井下采集自动带出** |
| GET | `/api/objective/daily/<int:team>` | M+ | 班组客观记录列表 |
| GET | `/api/objective/monthly/<int:team>` | M+ | 月度 S 汇总（monthly_s + distribution_ratio，分档 90/80/70/60） |

**奖金计算链路**（`core/calculator.py` `_get_scoring_bonus`，scoring 模式并入净额）：
- 半池 = max((当月 NICKEL(H) 车次 − 600), 0) × 20,000 × 50%（仅 NICKEL(H)，NICKEL(L)/MAWE 不计）
- 班实际池 = 半池 × distribution_ratio（来自 `get_monthly_objective`）
- 个人奖金 = 班实际池 × (个人系数 ÷ Σ本班系数)；读新表 `scoring_card_entries`（旧表回退），与 summary 共用系数逻辑

---

## 6. 前端导航重建要点

### 6.1 信息架构实现

> 对应 PRD §4 导航树，重构 `templates/index.html` 的页面结构。

**新页面状态**（替代旧平铺 tab）：

```javascript
// 顶层模块
MODULES = ['dashboard', 'employees', 'oa', 'attendance', 'production', 'scoring', 'salary', 'system']

// 子页面（二级/三级路由）
SUB_PAGES = {
  employees: ['list', 'profile'],      // profile 需要 employee_id 参数
  oa: ['pending', 'history'],
  attendance: ['grid'],
  production: ['underground', 'driller', 'crush'],
  scoring: ['cards', 'summary', 'panel'],  // P3
  salary: ['table', 'daily', 'verify', 'export'],
  system: ['users', 'permissions', 'forms', 'params', 'archive']
}
```

**周期上下文条**（顶部常驻）：
```html
<div id="period-bar">
  <button id="prev-month">«</button>
  <span id="current-month">2026-08</span>
  <button id="next-month">»</button>
</div>
```
- 懒加载：切换到未加载的月份时再 fetch 数据。
- 状态保持：切换月份不清空缓存，后台 fetch + 渲染。

### 6.2 父子页面路由

```
# 员工列表页
state.currentView = {module: 'employees', page: 'list'}
→ 渲染员工表格（搜索/筛选/分页）

# 点击某员工姓名
state.currentView = {module: 'employees', page: 'profile', params: {id: '111'}}
→ 渲染员工档案页（基本信息+时间线+请假+关联入口）
```

路由实现：URL hash `#employees/profile/111` → 解析后 showPage。

### 6.3 状态管理扩展

```javascript
// 扩展现有 STATE 对象
STATE = {
  currentMonth: '2026-08',
  currentView: {module: 'dashboard', page: null, params: {}},
  // ...现有缓存保持不变
}
```

---

## 7. 开发顺序建议

在 P0 阶段，建议按以下顺序阅读/评审/实现：

1. **表结构**（本文 §3）：先确认字段无遗漏/多余，然后用 `init_db()` 增量建表
2. **API 定义**（本文 §5）：前后端并行开发的分界线
3. **导航重建**（本文 §6）：新 IA 的 DOM 骨架 + 路由，不涉及数据
4. **种子数据**（本文 §5.9）：确认导入逻辑覆盖所有现有员工

评审通过后，P1 开始按 §5.1–5.2（员工+OA）实现首切片。

---

## 附录 A: 字段类型速查

| 类型 | SQLite | 说明 |
|------|--------|------|
| 整数 | INTEGER | 员工数、天数、金额 |
| 浮点 | REAL | 薪资明细（保留精度） |
| 字符串 | TEXT | 姓名、日期、JSON |
| 布尔 | INTEGER (0/1) | nssf_enrolled, required, revoked 等 |

所有 JSON 列存 `TEXT` 类型，后端用 `json.loads/dumps` 读写。

## 附录 B: 表依赖关系（外键）

```
employees (root)
  ├── employee_events (FK → employees)
  ├── leave_requests (FK → employees)
  ├── leave_balances (FK → employees)
  ├── driver_roster (FK → employees)
  ├── team_memberships (FK → employees)
  ├── attendance_overrides (FK → employees, 现有)
  ├── production_records (FK → employees, 新增)
  ├── dismissed_employees (FK → employees, 现有)
  └── monthly_data (FK → employees, 现有)

form_schemas
  └── form_fields (FK → form_schemas)

permissions
  ├── role_permissions (FK → permissions)
  └── user_grants (FK → permissions)

admin_users (现有认证表)
  └── user_grants (FK → admin_users.username)
```

## 附录 C: 授权装饰器扩展

```python
# 现有装饰器链（保留）
@require_super_admin → @require_admin → @require_editor → @login_required

# 新增细粒度检查
def require_permission(module, action):
    """检查登录用户是否有 (module, action) 权限"""
    # 实现: 查 user_grants(未撤销) → 回退到 role_permissions → 根据 data_scope 过滤
    pass
```

使用示例：
```python
@login_required
def get_employees():
    require_permission('employees', 'view')
    # ...
```
