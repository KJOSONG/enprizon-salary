# P14：v7 验收后 8 条有效反馈（2026-08-13）

> **背景**: REFACTOR_SPEC.md v6 验收后，用户在 2026-08-13 提出 8 条新的产品/工程问题。本文档是 P14 阶段的实施详设，对应 PRD §0.3。

## 需求理解（与用户对齐后）

### 问题 1（域：登录入口）：未登录即弹登录

**现状**: `init()`（templates/index.html:1695）先 `checkAuth()` 再 `fetch('/salary')`，未登录触发 401，被 `catch (e) {}` 静默吞掉 → 空白数据台 + 右上角"登录"按钮。

**v7 需求**: 检测未登录立即 `openLoginModal()`，不再空白加载后让用户找右上角。

**改动**:
- `init()`: checkAuth 返回 false → 立即 `openLoginModal()`，不继续渲染数据台/薪资表
- 登录成功回调（1296 附近）保留：补 `fetch('/salary')` + 渲染

### 问题 2（域：登录后首页）：首屏自动渲染

**现状**: 1308 注释 `init() 登录前跑，未登录时 /salary 401` → 登录后 init 已跑过，STATE.salaryResult 仍是空 → 用户看到"加载中"，手动切月才刷新。

**v7 需求**: 登录成功后立即拉数据渲染首页。

**改动**:
- `submitLogin` 成功回调（1296 附近）：调 `await fetch('/salary')` + `renderDashboard` + `renderSalaryTable` + `populateMonthSelect` + 更新 period-bar

### 问题 3（域：井下双重计薪）：scoring 与 piecework 互斥

**现状**: `core/calculator.py:721-729` scoring 模式下 `scoring_employees`（井下工人）per_date_type 改为 monthly；但 865 行 `if dtype == 'piece_underground' and not absent: pu += ...` 仍会跑——若 `ug_type_excl` 没正确生效就双重计薪。

**v7 需求（用户对齐）**: **评分/计件二选一，全局生效**。
- 设置 `scoring` → 井下工人当月走月薪 + 司机津贴 + 评分奖金（**不再**计件）
- 设置 `piecework` → 井下工人按计件

**改动**:
- `calculate_all` 顶部：拿到 `underground_mode` 后，根据模式一次性改写 `per_date_type`（scoring → 井下工人全体 monthly；piecework → 维持原 per_date_type）
- 删除 721-729 行的运行时重写逻辑（已前置到 per_date_type 准备阶段）
- 删除 `ug_type_excl` 中井下 scoring 员工的特殊判断（已统一处理）
- `config` 页 `/config` 接口可改 `underground_mode`；前端设置项明确显示当前模式与井下工人数量

### 问题 4（域：计薪模式与员工类型）：单一开关

**现状**: 模式设置 + 员工薪资类型是双轨（用户既要切模式，又要保证员工 default_type 是 piece_underground 才生效）。

**v7 需求**: 设置模式后系统自动处理，**无需**手动改员工薪资类型。

**改动**:
- 沿用问题 3 的 per_date_type 重写逻辑：scoring → 井下工人当月 per_date_type=monthly；员工 default_type 维持原样
- 前端 `/config` 页：模式开关旁加提示"切换模式后井下工人当月按月薪计算，无需修改员工薪资类型"
- 删除"先改模式再改员工类型"的引导

### 问题 5（域：薪资类型编辑）：档案页显示

**现状**: `/api/employees/<id>/salary-type` 接口（app.py:1156）存在；P12 提到薪资类别可改。但档案页（v5 独立页）是否展示编辑入口待确认。

**v7 需求**: 档案页"基本信息"区块显示薪资类型编辑卡片（下拉）。

**改动**:
- `templates/index.html` 档案页 `#employees/profile`：在基本信息区块加"薪资类型"select（day_rate / monthly / piece_underground / piece_driller / piece_crush），保存调 `/api/employees/<id>/salary-type`
- i18n 键：`profile_salary_type`、`opt_day_rate` 等

### 问题 6（域：临时例外）：档案页恢复入口

**现状**: `app.py:954 remove_temp_override` 接口存在；前端无添加/查看临时例外的 UI。

**v7 需求**: 档案页加"临时例外"区块：列出该员工所有临时例外 + 添加入口。

**改动**:
- 新增 API（必要时）：`POST /api/employees/<id>/temp-override`（已有 save_override 通用，参数 employee_id/salary_type/start_date/end_date/day_rate/monthly_salary）
- 档案页加"临时例外"区块：表格列出 | 起始 | 结束 | 类型 | 操作 |；底部"添加"按钮弹窗
- i18n 键：`profile_temp_overrides`、`temp_override_add`

### 问题 7（域：评分录入页面）：完全重做

**参考文件**:
- `/Users/osong/WorkBuddy/坦桑法规/output/矿区管理/评分卡/8月第一周第二组/01.jpeg`（匿名评分卡 jpeg：一卡涵盖全班组 W1-W9 9 人 6 维）
- `/Users/osong/WorkBuddy/坦桑法规/output/矿区管理/工具与脚本/井下出渣工人评分系统.xlsx`（含使用说明/评分卡打印版/评分录入/个人汇总/客观录入/客观计算/奖金计算）

**核心设计语义**:
- 一张评分卡 = 班组内某评分人对全班组 W1-W9 9 人各打 6 维分（主动/勤快/纪律/协作/安全/驾驶）
- 评分录入页流程：选组别 → 系统调出"圈住的人"（班组全员） → 录入完一张全组的人后 → 下一张（不同卡号/不同评分人） → 下一张旁边有"完成"按钮（前 5 维必填后可点；驾驶操作仅驾驶员填，非驾驶员可空）

**v7 需求**: 完全重做评分录入页，对齐参考文件的"一张卡=全班组9人"语义。

**改动**:
- 前端 `#score-input` 页：
  - 顶部：选班组 → 自动加载全员 W1..W9 + 当前已录入卡号列表
  - 一张卡视图：左侧 9 人列表（W1-W9），每人 5+1 个 input（主动/勤快/纪律/协作/安全/驾驶）；右侧"完成"按钮（disabled 条件：W1-W9 中每人 5 维都 1-5）
  - 完成一张 → 自动跳下一张（卡号递增或选下一个未完成卡号）
  - 不允许跳过班组只录某几个人（除非留空，前 5 维可空）
- 数据模型：`scoring_card_entries`（每行=一张卡上某人的评分）
  - 字段：week, team_id, card_no, source（工友/管理）, subject_eid, subject_name, initiative, diligence, discipline, cooperation, safety, driving
  - 索引：(week, team_id, card_no) 唯一

### 问题 8（域：评分录入记录）：记录可查

**现状**: scoring_entries 表可能仅存汇总，缺每张卡每行记录。

**v7 需求**: 保留所有原始评分记录（一张卡 9 行），支持按周次/班组/卡号/被评人查询。

**改动**:
- `scoring_card_entries` 表（问题 7 已定义）
- 新增 `GET /api/scoring/entries?team=&week=&card=&subject=` 返回记录列表
- 档案页或独立页可查（按班组+周次展开"评分记录"）

---

## 档案页第二轮反馈（2026-08-13，4 条）

### 问题 9（域：档案页"表单模式"按钮）：删除

**现状**: 档案页底部信息区有 `📝 表单模式` 按钮（templates/index.html:425 `toggleSchemaForm`），点击后把 form_schema 引擎（P4 表单自定义）的 `employee_profile` schema 渲染进档案页底部（`#profileSchemaForm`），与"编辑"弹窗功能重复。

**用户判断**: 无意义，不应放在这里。

**改动**:
- 删除档案页 `📝 表单模式` 按钮（425 行）与 `#profileSchemaForm` 容器（426 行）
- `toggleSchemaForm` / `renderFormFromSchemaByName` 函数保留（后台"表单自定义"页可能用），但档案页不再调用
- 档案编辑统一走 `editEmployeeProfile()` 弹窗

### 问题 10（域：班组选择适用范围）：仅井下生产工人

**现状**: 班组 select（`#hireTeamId` 入职表单 294 行、`pfEdit_team_id` 档案编辑 2247 行）对所有员工显示。

**用户判断**: 班组选择只对井下生产工人有效。

**改动**:
- 前端：入职表单 / 档案编辑弹窗中，仅当员工岗位/部门属于"生产组井下"（`filterEmpByDept(pool,'underground')` 判定）时显示班组 select；其他岗位隐藏
- 后端：`POST /api/employees`（入职）与 `POST /api/employees/<id>`（编辑）校验——非井下生产岗位的 team_id 一律置 0（不落库）
- 已存在的非井下员工 team_id 清理（可选，迁移脚本）

### 问题 11（域：工号生成规则）：工号来源于 ID

**现状**: 入职表单 `#hireCustomNumber`（295 行）+ 档案编辑 `pfEdit_custom_number`（2248 行）都是手输文本框，可自定义任意工号。

**用户确认（2026-08-13）**: **工号就来源于 ID（employee_id）**。

**改动**:
- 入职表单：工号字段只读，提示"工号 = 员工 ID，提交后自动生成"；后端 `apply_approved_event` hire 分支 custom_number 为空时自动设为 employee_id
- 档案编辑：工号字段只读，显示 `custom_number || id`
- 现有员工回填：`UPDATE employees SET custom_number = id WHERE custom_number=''`（已执行，130/130）
- 评分页/列表等工号展示 fallback：`custom_number || id`

### 问题 12（域：编辑按钮位置）：移至合适位置

**现状**: `✎ 编辑` 按钮（424 行）与 `📝 表单模式` 按钮（425 行）都放在档案页底部信息区最下方（余额调整行之下）。

**用户判断**: 编辑按钮应放在合适位置而不是最下方。

**改动**:
- `✎ 编辑` 按钮移至档案页头部（头像卡片旁 / 标题栏右侧），与基本信息并列
- 删除"表单模式"按钮后，底部仅保留余额调整（年假/调休/病假），不再混杂
- 头像上传按钮（402 行）也属头部操作，可一并归位

---

## 数据库变更

### 新增表

```sql
CREATE TABLE scoring_card_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    card_no TEXT NOT NULL,           -- "01", "02"... 或工友匿名 "9"（自评）
    source TEXT NOT NULL,            -- '工友' | '管理'
    subject_employee_id TEXT NOT NULL,  -- 被评人 eid
    subject_name TEXT,               -- 冗余存储便于报表/打印
    initiative INTEGER,              -- 1-5
    diligence INTEGER,
    discipline INTEGER,
    cooperation INTEGER,
    safety INTEGER,
    driving INTEGER,                 -- 可空（非驾驶员）
    operator_id TEXT,
    submitted_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(week, team_id, card_no, source, subject_employee_id)
);
CREATE INDEX idx_sce_team_week ON scoring_card_entries(team_id, week);
```

> 旧 `scoring_entries` 表可保留作为汇总缓存（去极值后的行为分/系数/偏离），由 trigger 或读时计算。

## API 变更

### 新增

| 方法 | 路由 | 说明 |
|------|------|------|
| GET  | `/api/scoring/entries?team=&week=&card=` | 查某班组某周所有卡记录 |
| GET  | `/api/scoring/card?team=&week=&card=` | 查单卡 9 行（含 6 维） |
| POST | `/api/scoring/card` | 一次保存单卡 9 行（payload 9 行，card_no 唯一） |
| POST | `/api/employees/<id>/temp-override` | 添加临时例外（若 save_override 不够用） |

### 调整

- `/config` (POST): `underground_mode` 切 scoring 时**自动**对井下工人应用月薪轨道（不再要求员工 default_type）
- `/api/employees/<id>/salary-type` (POST): 档案页接入（UI 化）

## 前端变更

| 页面 | 改动 |
|------|------|
| `#dashboard` | 登录后立即拉数据（移除"加载中"占位） |
| `#employees/profile` | 加"薪资类型"select；加"临时例外"区块（表格 + 添加弹窗）；**删除"表单模式"按钮**；编辑按钮移头部；工号只读；班组字段仅井下岗位显示 |
| `#employees/new`（入职表单） | 班组字段仅井下岗位显示；工号只读自动生成（next-number） |
| `#score-input` | 完全重做：选班组 → 一卡 9 人 6 维 → 完成按钮 → 翻下一张 |
| `#config` | 模式切换增加提示文案 |

## 验收要点（§13-P14）

1. 未登录进入系统立即弹出登录 Modal（无需手动点右上角）
2. 登录成功后首屏数据台正确渲染（无"加载中"，无空表）
3. 设置 scoring 后井下工人当月月薪轨道，无计件（井下车间报表 piece_underground 列=0）
4. 设置 piecework 后井下工人按计件（piece_underground 列>0）
5. 档案页可改员工薪资类型（day_rate/monthly/piece_*），保存生效
6. 档案页可添加/查看/删除该员工的临时例外
7. 评分录入页：选组别 → 全班组 9 人一卡 → 完成（前 5 维必填）→ 翻下一张 → 全部完成后显示"该班组本周录入完成"
8. 评分录入记录可查（按周次/班组/卡号）；汇总页按记录去极值算行为分
9. **档案页无"表单模式"按钮**；底部仅余额调整，编辑按钮在头部
10. **班组字段仅井下生产工人显示**；非井下员工保存后 team_id=0
11. **新入职工号自动生成**（custom_number 最大值+1），入职表单工号只读；现有员工工号不变
12. **档案页编辑按钮在头部**（头像旁/标题栏），不在最下方

## 风险与注意

- 评分录入页完全重做工作量较大（前端 UI + 数据模型 + API 三层）
- 井下计薪模式切换时，历史月份不应回溯（按 effective_from 持久化设置）
- 档案页薪资类型与"井下计薪模式"可能冲突——以模式优先（问题 4 决定）
- 班组字段改造涉及入职 API + 编辑 API 后端校验（非井下岗位 team_id 置 0），需同步处理
- 工号自动生成需确定格式（纯数字序号 vs W+序号），实施前与用户确认（P14.11）