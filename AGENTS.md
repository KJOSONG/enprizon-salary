# AGENTS.md — ENPRIZON LINDI (enprizon-salary)

薪资计算系统。上传 Excel → 五轨解析 → SPA 前端展示。部署在阿里云新加坡 (47.236.187.33)。

## 相关文档

- `README.md`：快速上手、五文件输入格式、部署与命令速查（面向新接手者）
- `ARCHITECTURE.md`：设计决策与重构理由（单轨重构 e6b9487、employee_id 迁移、双路径核对逻辑），**代码会变、理由不变**，深挖架构优先读它
- `REFACTOR_SPEC.md`：重构 PRD（需求、验收标准、用户流程），评审后少改
- `DEV_WORKFLOW.md`：工程协作约定（分支模型、纵向切片、提交/推送纪律、部署时机）
- `docs/P0_DATA_MODEL_AND_API.md`：P0 数据模型 + API 契约，重构期新表/新接口的权威来源
- `docs/P12_OA_PROFILE_COLLECTION_REFINEMENT.md`：P12 阶段详设（OA 子页化 / 档案独立页 / 数据采集修正 / 系统清理收尾），实施对照清单
- `docs/P13_OA_NOTIFY_QA_REFINEMENT.md`：P13 阶段详设（筛选修复 / OA 自审规则 / 请假子页 / 通知铃铛 / 审批人设定 / 中英双语审查），实施对照清单

## 协作流程

本地修改 → `git push` → 服务器 `git pull && systemctl restart enprizon-salary`
服务器快捷别名: `save-salary "msg"`（git add -A → commit → push → restart 一步完成）

- **绝不在 `main` 上直接开发**；重构工作在 `refactor` 分支进行，服务器在重构完成前始终留在 `main`
- **不擅自推送**：推送到远程/服务器需明确批准（见 DEV_WORKFLOW §6）；未完成前绝不半成品上服务器
- **回滚预案**：`main` 是稳定点，服务器异常即 `git checkout main` + 重启回退

## 数据库安全

- `data/*.db` 被 gitignore，不会被 git 跟踪。`data/source/*.xlsx` 同样被 gitignore
- **绝不用 `git stash drop`**（2026-06-28 因此导致 kilwa.db 永久丢失），只用 `git stash pop`
- 改数据库结构前先在服务器备份

## 环境变量

| 变量 | 说明 |
|------|------|
| `KILWA_SECRET_KEY` | Flask session 密钥。不设置则每次重启随机生成 → 所有会话失效 |
| `KILWA_SCRIPT_NAME` | Nginx 子路径前缀（如 `/salary`） |

## 命令

### 本地开发
```bash
pip install -r requirements.txt   # 仅 flask, openpyxl, pandas，无 gunicorn
python3 app.py                    # 前台（自动找空闲端口 ≥8080）
./start.sh start                  # 同上
./start.sh bg                     # 后台运行
./start.sh stop                   # 扫描 8080-8089 端口 kill -9（可能误杀其他服务）
```
`start.sh` 的 Python 路径硬编码为 `/Users/osong/.workbuddy/binaries/python/envs/default/bin/python3`。

### 服务器运维
```bash
ssh my-server                     # root@47.236.187.33:22222
systemctl restart enprizon-salary
journalctl -u enprizon-salary -f  # 跟踪日志
```

### 测试（无自动化测试！）
项目无 `test_*.py` 或 `tests/` 目录，默认手工测试通过数据库替换实现。纯逻辑（计薪引擎、事件驱动推导、请假余额、权限判定）可补轻量 `pytest` 校验（见 `DEV_WORKFLOW.md` §7），测试产物放 `_work/` 或独立测试目录，勿污染根目录。

手工测试数据库隔离流程：
```bash
cd /root/enprizon-salary
bash test-workflow.sh start       # 备份 → test_kilwa.db
bash test-workflow.sh swap        # 保存生产库 → 换入测试库
# ... 在前端执行测试操作 ...
bash test-workflow.sh restore     # 恢复生产库
bash test-workflow.sh clean       # 删除测试库（`prod_kilwa.db` 存在时拒绝，防止误删）
```
`test-workflow.sh` 使用 `$HOME/WorkBuddy/kilwa-system/data` 和 `$HOME/Desktop/enprizon_backups` 路径。

### 代码风格
项目无 linter、formatter 配置（无 `.flake8`、`black`、`prettier`、ESLint 等）。修改代码时优先保持与周围代码风格一致。文件普遍偏长（`app.py` ~3340 lines, `calculator.py` ~1420 lines, `database.py` ~1730 lines, `index.html` ~4000 lines），尽量避免增加不必要的模块拆分。

### 备份与恢复（服务器端）
```bash
bash backup.sh                    # 每日备份，自动清理 7 天前
bash restore.sh [备份路径]         # 停服 → 恢复 → 重启
```

## Gunicorn 生产配置（`gunicorn.conf.py`）

`workers=1`（SQLite 要求单 worker），`threads=2`，`timeout=120`。
日志路径硬编码为 `/root/enprizon-salary/`，本地开发会失败。

- **数据库**：SQLite **WAL 模式**，文件 `data/kilwa.db`
- **Nginx 反代**：`/salary/` → `127.0.0.1:8081`，对应环境变量 `KILWA_SCRIPT_NAME=/salary`

## 会话与认证
- Flask 默认 filesystem session（`data/flask_session/`），`KILWA_SECRET_KEY` 决定加密密钥
- 不设 `KILWA_SECRET_KEY` → 每次重启随机生成 → 全部用户登出
- 装饰器链：`@require_super_admin` → `@require_admin` → `@require_editor` → `@login_required`
- **P4 新增**：`@require_permission(module, action)` 细粒度权限（角色继承 + 单独授权），已接入 OA 审批 + 导出端点
- 密码存储：SHA256(username + salt + password)，salt 随机生成存入 `admin_users`
- 默认账号 `user/qweasd`（viewer），`KEJU` 首次登录自动升级为 super_admin

## 启动初始化

- **本地** `python3 app.py`：`init_db()` + `_migrate_json()`（旧 JSON 一次性迁移）+ `auto_load_source()`（扫描 `data/source/` 加载当前月份）
- **Gunicorn**：`_gunicorn_init()` 通过 `_app_initialized` 标志防止重复初始化
- `_ensure_viewer_account()` 自动创建默认 viewer 账号 + 升级 KEJU 为 super_admin
- `_migrate_json()` 仅在 `overrides` 表为空时运行一次（检测到有数据则跳过）
- **P5 新增**：`_backup_to_archive()` 首次启动自动备份 `kilwa.db` → `archived_kilwa.db`
- **P5 新增**：`seed_new_tables_from_excel()` 从 `data/source/*.xlsx` 重建 employees + hire 事件（仅首次）
- **P5 新增**：`seed_default_forms()` 预置 6 张表单 schema（入职/档案/调岗/出勤/产量×3）
- **P5 新增**：`init_default_permissions()` 初始化 4 角色默认权限到 `permissions` 表
- **Headless 模式**：切换到无 Excel 源数据的月份时，自动生成该月所有自然日期，仅支持出勤记录（P/A/L 手动标记），不支持产量/计件数据。手动标记安全持久化，后续上传源数据后自动继承。前端顶部显示 "Preview Mode" 横幅

## 架构要点

### 数据流水线
```
data/source/ (5 种 Excel) → scan_source_files() → _run_pipeline()
  ├── 主文件（产量+出勤）→ parser.parse_all()
  ├── 通讯录 → addressbook → namematch 索引（employee_id = 通讯录账号）
  ├── 预支 → advance.parse_advance()
  ├── NSSF SDL → nssf.parse_sdl_list()
  └── 破碎队 → parser.parse_crush_sheet()
全部 → calculator.calculate_all() → verification.verify_salary() → APP_STATE 缓存 → API
```
文件匹配：按 Sheet 名优先，回退到文件名关键词。

### employee_id 生成链路（`namematch.py`）

`make_employee_id(name)` 三级匹配（调试姓名对不上时优先排查这一级）：
1. 去空格/去括号/大写 → 查通讯录索引 `_AB_INDEX` → 返回**通讯录账号**（如 `111`、`128`、`005`）
2. 未命中 → 查 `_LEGACY_CANONICAL`（短名→全名回退表）→ 再查通讯录
3. 仍失败 → 回退姓名"去空格大写"（兼容离职 / 通讯录外人员，此类 employee_id 仍为旧格式）

> 2026-06-30 起全部表 `employee_id` 已从"姓名格式"整体迁移为"通讯录账号"，但未匹配通讯录者可能保留旧格式。

### 目录约定

| 目录 | 内容 | Git |
|------|------|-----|
| `data/` | `kilwa.db` 主数据库、Flask sessions/ | gitignored |
| `data/source/` | 5 种源 Excel 文件 + 上传缓存 | gitignored |
| `data/backups/` | 数据库备份（服务器端） | gitignored |
| `_work/` | 临时分析脚本、调试报告 | gitignored |
| `templates/` | Jinja2 模板（仅 `index.html`） | 跟踪 |
| `static/css/` | 样式文件（`style.css`） | 跟踪 |
| `static/js/` | 前端 JS（i18n + Chart.js CDN 缓存） | 跟踪 |
| `core/` | 12 个后端模块（含 `__init__.py`） | 跟踪 |

### 薪资五轨道（`calculator.py`）

| 轨道 | 数据源 | 逻辑 |
|------|--------|------|
| 井下计件 | shift_production（D/N 班） | 当日产量 × 井下单价 / 出勤人数，人均平分 |
| 钻工计件 | driller_production（队长制） | 当日产量 × 钻工单价 /（队员+1 队长份额），队长×2 份额 |
| 破碎计件 | CRUSH TEAM 文件 | bags × 300 / 有效人数，同日多条记录独立均分 |
| 日薪 | attendance | 日薪基数 × 出勤天数 |
| 月薪 | employees.monthly_salary | 基数 / 26 × 实出勤，A/L 按天比例扣减，≥26 天封顶满薪 |

**单轨模式**：任一日期只归属一个轨道，杜绝双重计薪。

税前总额 = 井下 + 钻工 + 破碎 + 日薪 + 月薪
净额 = 税前 + 奖金 + 司机津贴 - 预支 - NSSF(10%) - 罚款

### 定价机制（非显而易见）

三个价格常量 `PRICES_UNDERGROUND`、`PRICES_DRILLER`、`PRICE_CRUSH`（300）在 `calculator.py` 顶部硬编码。但每次 `calculate_all()` 从 DB config 读取并**全局猴子补丁覆盖**模块变量，结束后恢复。`/config` API 可修改 `crush_price` → 下次计算生效。**硬编码常量 ≠ 不可修改**。

### 例外覆盖（P5: 逐步被事件驱动取代）

- `overrides` 表：`start_date`/`end_date` 都空 → 永久覆盖（改变整月类型）；有日期 → 临时例外（仅影响区间）
- `attendance_overrides` 表：(employee_id, date) 联合 PK，status P/A/L/D/N/C/S/Y/T
- **P5 事件驱动**：`employee_events` 中已批准的 transfer/salary_change/resign 事件自动转换为 overrides（`_derive_overrides_from_events()`）
- **优先级**：事件推导覆盖 > 手动 DB 覆盖
- 标记 A/L 的员工从当日计件分配排除，总额守恒（剩余人员平分）

### 计薪模式切换（P5-b）

- `settings` 表 `underground_mode` 键：`piecework`（默认，纯计件）| `scoring`（评分模式）
- **scoring 模式**：井下工人 = 固定月薪（monthly_salary/26×出勤天数）+ 司机津贴（5000/天）+ 评分奖金
- **piecework 模式**：保持原有五轨计件逻辑不变
- 通过 `/config` API 切换，recalculate 后生效
- 双路径核对在两种模式下均应保持 0 偏差

### 出勤状态字母

D(蓝)=井下白班, N(青)=井下夜班, B(紫)=D+N, R(青绿)=钻工, C(橙)=破碎, P(绿)=日薪/月薪, A(红)=旷工, L(黄)=请假, (P)(灰)=月薪默认

点按切换：R/C → A → L → 空 → P（不可回到原始自动值）

### 代码修改关键不变量

改 `calculator.py` / `app.py` 前务必遵守：

- **单轨模式源于 v3.0 重构（commit e6b9487）**，目的是从架构上根除"双重计薪" bug。任何改动都必须保证 **任一日期只归属一个轨道**，不可让某员工某天同时被多个轨道计薪。
- **日工资明细必须与薪资页一致**：`compute_daily_breakdown()` 与 `calculate_all()` 共用同一套 `per_date_type` + 四轨子函数结果，按相同逐日选轨逻辑生成明细。"日工资明细页"与"薪资总表应发金额"必须逐人逐日相等（总则硬性要求），改计算逻辑时两者要同步验证。
- **总额守恒**：A/L 标记员工从当日计件分配排除后，剩余人员平分，当日计件总额不变（极端情况：队长 A/L 且无队员除外）。

### 前端技术栈

- **单文件 SPA**：`templates/index.html`（~3500+ lines），所有 JS 内联在 `<script>` 标签中，无独立 JS 模块或构建系统
- **P0 导航重建**：侧边栏 + 面包屑 + hash 路由 `#module/subpage?key=val`，8 个主模块：数据台/员工/OA/考勤/产量/评分/薪资/系统
- **15+ 个页面标签**：数据台（Dashboard）/ 员工列表 / 员工档案 / OA 待审 / OA 历史 / 出勤网格 / 薪资总表 / 日工资明细 / 产量×3（井下/钻工/破碎）/ 评分×3（录入/汇总/客观）/ 系统配置 / 用户权限 / 表单自定义 / 旧数据归档
- **国际化 (i18n)**：`static/js/i18n.js`（~800+ 键）支持中英文即时切换
- **图表**：Chart.js v4.4.7 + chartjs-plugin-datalabels
- **P4 新增**：全局搜索（顶栏，防抖300ms，跨 employees/salary/production/attendance）
- **P4 新增**：移动端响应式（44px触摸目标、16px防iOS缩放、侧边栏手势、底部导航）
- **暗系工业风 UI**：`static/css/style.css`（~1900 lines），CNPC 主题色系

### 前端数据流

- 所有 API 调用通过内联 `fetch()` 发送，浏览器自动携带 `session` cookie 认证
- 全局 `STATE` 对象缓存当前月份薪资/出勤/产量等全部数据
- 用户操作流程：表单交互 → `fetch` API 调用 → 后端更新 DB + 返回结果 → 前端局部更新 DOM 或调用 `recalculate()` 全面刷新
- `recalculate()` 触发后端重算后，按需刷新薪资、出勤、日工资相关页面标签
- `showPage(name)` 切换页面标签，优先从 `STATE` 读取缓存，其次 fetch

### 导出系统

| 端点 | 输出 | 需认证 | 说明 |
|------|------|--------|------|
| `POST /export` | Excel 3 Sheet | editor+ | 薪资总表 + 核对 + 日明细 |
| `POST /export/employees` | Excel | editor+ | 员工花名册（类型/NSSF/奖惩） |
| `GET /export/attendance` | Excel | editor+ | 出勤网格导出 |
| `POST /export/all` | Excel 7 Sheet | editor+ | 英文版统一导出（员工信息+薪资+出勤+日工资+产量+钻工核对+钻工明细） |

### 司机津贴（P11 改造）

旧 `_apply_driver_allowance()`（按部门名/岗位含"司机"自动匹配）将于 **P11 删除**。v4 改为：由出勤勾选"驾驶"触发，须在校验 `driver_roster` 名单内，自动 5,000/班 计津贴并流入薪资总表 `driver_allowance` 列。

### 权限模型

`super_admin` > `admin` > `editor` > `viewer`。默认账号 `user/qweasd`（viewer），`KEJU` 自动升 super_admin。

### 数据库表（P5 18+ 张 + P7-P10 增量）

| 表 | 说明 | 阶段 |
|-----|------|------|
| `employees` | 员工主档（P1：position/skill_level/hire_date/NIDA/NSSF/银行；**P7 增** gender/date_of_birth/avatar_path；**P10 增** custom_number/team_id） | P0+P1+P7+P10 |
| `overrides` | 薪资例外：永久/临时（逐步被 employee_events 取代） | P0 |
| `attendance_overrides` | 手动出勤标记 P/A/L/D/N/C/S/Y/T/**P(病假)** | P0+P8 |
| `settings` | 系统配置 key-value（定价/NSSF/underground_mode/scoring） | P0 |
| `monthly_data` | 月度薪资快照缓存 | P0 |
| `audit_log` | 操作审计（强制 UTC+3） | P0 |
| `shift_additions` | 手动补井下计件班次 | P0 |
| `driller_additions` | 手动补钻工分组 | P0 |
| `bonus_penalties` | 月度奖惩 | P0 |
| `dismissed_employees` | 离职追踪 | P0 |
| `admin_users` | 用户认证（加盐 SHA256） | P0 |
| `employee_events` | OA 生命周期事件（入职/调岗/离职/薪资变/请假） | P1 |
| `leave_balances` | 年假/调休余额（**P8 增** 病假 14 天/年默认） | P2+P8 |
| `leave_requests` | 请假申请（**P8 增** leave_type='sick' 病假） | P2+P5+P8 |
| `driver_roster` | 司机白名单 | P2 |
| `scoring_cards/entries` | 评分卡 + 6 维评分（**P10 重设计**：班组+全员+自定义工号+一张张卡） | P3+P10 |
| `objective_records` | 客观产量数据（R1/R2→S） | P3 |
| `permissions` | 细粒度权限定义（模块×动作） | P4 |
| `user_grants` | 用户单独授权（覆盖角色默认） | P4 |
| `form_schemas/fields` | Schema 驱动表单定义 | P4 |
| **`collection_submissions`** | **P9 新增**：数据采集提交主表（井下/钻工/破碎/出勤收集 4 类） | P9 |
| **`collection_history`** | **P9 新增**：编辑历史版本表（旧 payload 留档） | P9 |
| **`employee_groups`** | **P10 新增**：班组表（LAMBA LAMBA / SAKA SAKA 等） | P10 |
| **`driller_captains`** | **v5 新增**：钻工队长名单（当前 3 人，计薪参数页维护） | v5 |

### 硬排除名单（`app.py:40-45`）

6 人全局隐藏、不计薪：ERIC WANG QM, JIMMY, SET SAIL, 宋家成（Daria）, 宋科举KEJU, 宋科举

### APP_STATE 内存缓存

全局 `APP_STATE = {}` 缓存解析结果。`/reload` 清空并重新填充。重启后丢失。

### 已知数据边界（非 bug）

1. 5/25 夜班产量无人领取（156,000 TZS，源数据缺员工名单 → 路径一二永久差异）
2. 钻工 5/1-5 无队员（仅队长 1 人）
3. 同名多槽位（同队长同天多次出现 → 产量合并，成员去重）
4. 跨 Sheet 人员（产量表+日薪表同时出现 → 需手动指定类型）
5. 仅预支表人员（通讯录外，仅出现在预支表中）

## 代码分工速查

### 后端模块（`core/` 12 个文件，行数为约数会随版本漂移，仅供参考）

| 文件 | 职责 |
|------|------|
| `app.py` | Flask 路由 + 认证 + 会话 + 数据管线编排（~3340 lines, 43 API 端点） |
| `core/calculator.py` | 五轨计算 + 逐日单轨合并 + 日工资明细（~1420 lines） |
| `core/parser.py` | Excel 解析（表头扫描驱动，产量/日薪/破碎 3 个解析函数，~330 lines） |
| `core/verification.py` | 双路径核对（产量×单价 vs 实际分配，|diff|≤10 视为舍入，~300 lines） |
| `core/namematch.py` | 姓名标准化 + employee_id 生成 + 员工主列表（~250 lines） |
| `core/database.py` | SQLite ORM（11 张表）+ 审计日志（~1730 lines） |
| `core/addressbook.py` | 通讯录 Excel 解析（~150 lines） |
| `core/advance.py` | 预支数据解析（~80 lines） |
| `core/nssf.py` | NSSF SDL 社保名单解析（~40 lines） |
| `core/exceptions.py` | 例外覆盖标记加载，兼容 JSON + DB（~25 lines） |
| `core/pricing.py` | 单价配置代理，模块常量（~10 lines） |
| `core/__init__.py` | 包初始化（1 line） |

### 模块依赖层级

```
app.py (Flask 路由 / 认证 / 数据管线)
 ├── core/parser.py         (Excel→结构化数据)
 │    ├── core/addressbook.py (通讯录解析)
 │    ├── core/advance.py     (预支解析)
 │    └── core/nssf.py         (NSSF SDL 解析)
 ├── core/namematch.py       (姓名标准化 / employee_id)
 ├── core/calculator.py      (五轨计算 / 逐日合并)
 │    └── core/pricing.py     (单价配置)
 ├── core/database.py        (SQLite ORM / 审计)
 ├── core/verification.py    (双路径核对)
 └── core/exceptions.py      (例外覆盖加载)
```

### 关键 API 端点

| 方法 | 路由 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/login` | 公开 | 登录，建立 session |
| POST | `/api/logout` | 公开 | 登出 |
| GET | `/api/auth/status` | 公开 | 当前用户登录状态 |
| GET | `/` | 公开 | SPA 入口页面 |
| GET | `/source-info` | editor+ | 当前加载的源文件列表 |
| GET | `/available-months` | editor+ | 可用月份列表 |
| POST | `/set-month` | editor+ | 切换到指定月份 |
| POST | `/reload` | editor+ | 清空 APP_STATE，重新扫描源文件 + 计算 |
| POST | `/recalculate` | editor+ | 触发重新计算（不重扫源文件） |
| POST | `/upload-source` | admin+ | 上传 Excel 源文件 |
| GET | `/download-source/<file_type>` | editor+ | 下载原始源文件 |
| GET | `/salary` | editor+ | 薪资总表数据（含核对差异） |
| GET | `/salary/verify` | editor+ | 双路径核对详情 |
| GET | `/attendance` | editor+ | 出勤网格数据 |
| POST | `/attendance/toggle` | editor+ | 手动标记出勤 P/A/L |
| GET | `/employees` | editor+ | 员工列表 + 例外覆盖 |
| POST | `/employees/override` | editor+ | 添加薪资例外（永久/临时） |
| POST | `/employees/remove-override` | editor+ | 删除例外覆盖 |
| POST | `/employees/bonus-penalty` | editor+ | 添加月度奖惩 |
| GET | `/employees/dismissed` | editor+ | 离职员工列表 |
| POST | `/employees/dismiss` | admin+ | 标记员工离职 |
| GET/POST | `/config` | admin+ | 读取/修改定价、NSSF 费率 |
| GET | `/nssf/list` | editor+ | NSSF 社保名单 |
| GET | `/production` | editor+ | 产量数据 |
| GET | `/production-verify` | editor+ | 钻工产量核对 |
| GET | `/daily-wages` | editor+ | 日工资明细 |
| GET | `/driller-captains` | editor+ | 钻工队长/队员列表（读主数据） |
| **GET/POST/PUT/DELETE** | **`/api/driller-captains`** | **admin+** | **P12 新增**：`driller_captains` 名单 CRUD（计薪参数页维护，钻工采集队长下拉数据源） |
| GET | `/audit-log` | admin+ | 审计日志 |
| POST | `/export` | editor+ | 薪资 Excel（3 Sheet） |
| POST | `/export/employees` | editor+ | 员工花名册 Excel |
| GET | `/export/attendance` | editor+ | 出勤网格 Excel |
| POST | `/export/all` | editor+ | 英文版全量导出（7 Sheet） |
| GET | `/admin/users` | super_admin | 用户管理页面 |
| POST | `/admin/users/role` | super_admin | 修改用户角色 |
| POST | `/api/admin/change-password` | 登录用户 | 修改自身密码 |
| GET | `/api/permissions/users` | admin+ | 用户权限矩阵 |
| POST | `/api/permissions/grant` | super_admin | 单独授权 |
| DELETE | `/api/permissions/grant` | super_admin | 撤销授权 |
| GET | `/api/search?q=&scope=` | 登录用户 | 全局搜索（P4；**P6 简化为无 scope**） |
| GET/POST/PUT/DELETE | `/api/forms/schema/*` | 登录/超管 | 表单自定义CRUD（P4） |
| GET | `/api/archive/months` | 登录用户 | 归档月份列表（P5） |
| GET | `/api/archive/salary?month=` | 登录用户 | 归档薪资查询（P5） |
| **POST** | **`/api/employees/avatar`** | **admin+** | **P7 新增**：员工头像上传（≤2MB image/png/jpeg） |
| **POST** | **`/api/employees/avatar/delete`** | **admin+** | **P7 新增**：删除员工头像 |
| **POST** | **`/api/leave/sick`** | **登录用户** | **P8 新增**：病假申请（免审，落 P 出勤，扣 14 天/年余额） |
| **POST** | **`/api/collection/submit`** | **editor+** | **P9 新增**：数据采集提交（井下/钻工/破碎/出勤收集） |
| **GET** | **`/api/collection/history?form_type=&month=`** | **editor+** | **P9 新增**：数据采集历史表 |
| **POST** | **`/api/collection/edit/<submission_id>`** | **editor+** | **P9 新增**：再编辑历史提交（写 collection_history） |
| **GET/POST/PUT/DELETE** | **`/api/employee_groups/*`** | **admin+** | **P10 新增**：班组 CRUD（LAMBA LAMBA / SAKA SAKA） |
| **GET** | **`/api/scoring/team/<team_id>/month/<month>`** | **editor+** | **P10 新增**：按班组+月份取评分卡全员列表（含 custom_number） |
| **POST** | **`/api/scoring/card/batch`** | **editor+** | **P10 新增**：批量提交评分卡（一张张卡） |
| **删除** | **`/upload-source`、`/download-source/<file_type>`** | **P11** | **UI 隐藏**；保留为批量导入过渡 API |

### 前端文件

| 文件 | 职责 |
|------|------|
| `templates/index.html` | 单页 SPA（~4000 lines，15+ 页面标签，全部 JS 内联） |
| `static/css/style.css` | 暗系工业风 UI 主题（~1940 lines，含 P4 响应式） |
| `static/js/i18n.js` | 中英文翻译字典（800+ 键）+ 运行时切换引擎 |
| `static/js/chart.umd.min.js` | Chart.js v4.4.7 |
| `static/js/chartjs-plugin-datalabels.min.js` | 图表数据标签插件 |

### 运维脚本

| 文件 | 用途 |
|------|------|
| `start.sh` | 本地开发启动（Python 路径硬编码） |
| `backup.sh` | 服务器每日备份 kilwa.db，7 天自动清理 |
| `restore.sh` | 服务器停服→恢复→重启 |
| `test-workflow.sh` | 测试库安全隔离（start/swap/restore/clean） |
| `gunicorn.conf.py` | 生产配置（127.0.0.1:8081, 1 worker, 2 threads, 120s timeout） |

## 原则

- 临时分析脚本、报告放在 `_work/`（已 gitignore，可随时删除）

## 重构状态（2026-08-12）

**分支**: `refactor`（本地已 checkout 且推送到 GitHub，**未部署服务器**）
**阶段**: **P0-P12 全部完成，v5 本地验收通过**（REFACTOR_SPEC.md v5 已落地，P12 代码已改未提交）
**v6**: 验收后 10 条有效反馈已对齐并入 **REFACTOR_SPEC.md v6**，实施归入 **P13**（DEV_WORKFLOW §5），尚未动代码
**服务器**: 仍在运行 `main` 分支旧代码，待部署切换 refactor 分支

### 重构新增主要功能

| 阶段 | 新增 |
|------|------|
| P0 | 导航重建（侧边栏+面包屑+hash路由）、前端 IA 重构 |
| P1 | employee_events 表、OA 审批流程（入职/调岗/离职/薪资变） |
| P2 | 考勤批量提交、请假系统（年假/调休余额）、产量 Web 录入 |
| P3 | 评分模型（6维匿名互评+三闸面板+奖金并入净额） |
| P4 | 细粒度权限、全局搜索、表单自定义引擎、手机端响应式 |
| P5 | 旧数据 ATTACH 归档、事件驱动计薪桥接、计薪模式切换（计件↔评分） |
| P6 | 顶部交互清理（登录前月份选择器删除 / period-bar bug 修复 / 搜索简化 / 员工页合并抽屉） |
| P7 | 员工档案字段扩展（性别/年龄/头像上传/字段类型校验/电话+255/薪资类别可改） |
| P8 | OA 合并入员工 + 请假增加病假（姓名索引/员工列表 id/审批落库闭环） |
| P9 | 数据采集模块重设计（4 表单 + 提交页+历史区+再编辑 + D+N 同表 + reload 持久化） |
| P10 | 评分模块重设计（班组 LAMBA/SAKA + 自定义工号 + 一张张卡 + month 维度） |
| P11 | 系统清理 + 薪资总表新列（源文件管理 UI 删除 / 司机津贴 is_driver 机制 / driver_allowance 列 / 生产薪资改名） |
| **P12** | **v5 需求对齐迭代**（OA 三申请独立子页+入职全字段 / 档案独立页+简历头像+余额可改 / 姓名可选中复制 / 井下三列标签+双备注+驾驶勾选 / 钻工队长名单化+添加队伍 / 出勤收集按部门 / 采集选中框对齐 / 计薪参数删司机津贴+队长名单 / 评分系统改名） |
| **P13** | **v6 需求对齐迭代**（部门筛选修复 / 档案子页移出侧栏 / OA 自审分角色+审批详情 / 请假子页 / 侧栏折叠样式 / 入职头像 / 入职后跳转待审 / 通知铃铛红点 / 后台指定审批人 / 全页面中英双语） |

### 下一步

1. **本地验证**：`python3 app.py` 检查所有页面无 JS 错误
2. **P13 实施**：按 REFACTOR_SPEC.md v6（§0.2/§11-P13）落地 10 条有效反馈，逐项对照 §13 验收
3. **推送部署**：服务器 `git checkout refactor && systemctl restart enprizon-salary`
4. **git 清理**：提交误跟踪的 `data/kilwa.db-wal`/`data/kilwa.db-shm` 删除（.gitignore 已补防）
