# AGENTS.md — ENPRIZON LINDI (enprizon-salary)

> **TL;DR**：坦桑尼亚矿业薪资系统。纯采集驱动（无 Excel 源）：P9 采集提交 → DB → `_run_pipeline()` 重建 → 五轨计薪 → SPA 展示。部署阿里云新加坡 47.236.187.33:8081（`/salary/` 子路径）。**当前 main=2d8228e，服务 active（P30/P31/P32 已部署 2026-09-02；P29 权限 V2.1 于 2026-08-23 部署）**。改计算逻辑必读记忆 `salary_calc_logic.md`；协作流程见 §协作流程 + `DEV_WORKFLOW.md`。

## 相关文档

- `README.md`：快速上手、部署与命令速查（面向新接手者）

- `ARCHITECTURE.md`：设计决策与重构理由（单轨重构 e6b9487、employee\_id 迁移、双路径核对逻辑），**代码会变、理由不变**，深挖架构优先读它

- `REFACTOR_SPEC.md`：重构 PRD（需求、验收标准、用户流程），评审后少改

- `DEV_WORKFLOW.md`：工程协作约定（分支模型、纵向切片、提交/推送纪律、部署时机）——**工作流唯一权威**

- `docs/P0_DATA_MODEL_AND_API.md`：P0 数据模型 + API 契约，新表/新接口的权威来源

- `docs/P12/P13/P14/P15_*.md`：各阶段详设与实施对照清单（见 §重构状态）

- `docs/P25_PIECEWORK_V2_SPEC.md`：计件薪资制度 V2 逻辑规格（凸性加速 + 月末零和再分配，业务侧权威）

- `docs/P25_PIECEWORK_V2_IMPLEMENTATION.md`：V2 实现设计（第三模式、班组对齐、公式、前端清单，工程侧权威）

- `docs/P29_PERMISSION_V2_SPEC.md`：权限体系 V2.1 重设计规格（✅ 已部署上线 2026-08-23；需求文本冻结，接手必读）

## 协作流程

```
本地修改 → 展示变更 → 用户批准 → git push → 服务器 git pull && systemctl restart
```

- **小改动**（单文件小改/查询/回答）：直接在本地 `main` 上做，不建分支。

- **大改动**（≥3 需求或跨多模块）：**建 feature 分支 + KEJU 团队并行**（designer/dev/qa 同开工，严禁串行）。团队配置见记忆 `project_team_config.md`，并行规则见记忆 `feedback_workflow.md`。

- **不擅自推送**：推送到远程/服务器需**用户明确批准**；未完成前绝不半成品上服务器。

- **服务器快捷别名**：`save-salary`（本地 git push 后，服务器自动 git pull 并重启，详见 §命令）。

- **回滚预案**：`main` 是稳定点，服务器异常即 `git pull origin main` + 重启回退。

- **agentmemory 整合**：任务开始先 `smart-search` recall 相关记忆，任务完成 `remember` 沉淀（REST localhost:3111，见记忆 `feedback_workflow.md`）。

## 数据库安全

- `data/*.db` 被 gitignore，不会被 git 跟踪。`data/source/*.xlsx` 同样被 gitignore

- **绝不用** **`git stash drop`**（2026-06-28 因此导致 kilwa.db 永久丢失），只用 `git stash pop`

- 改数据库结构前先在服务器备份（见 §备份与恢复 + 记忆 `backup_spec.md`）

- 备份目录规范：手动安全备份 → `data/backups/`（只留最新 1 个）；每日自动 → `/root/salary-backup/`（backup.sh 留 7 天）；`data/` 根目录**禁止散落** **`*.bak*`**；`archived_kilwa.db` 归档永久保留

## 环境变量

| 变量                  | 说明                                     |
| ------------------- | -------------------------------------- |
| `KILWA_SECRET_KEY`  | Flask session 密钥。不设置则每次重启随机生成 → 所有会话失效 |
| `KILWA_SCRIPT_NAME` | Nginx 子路径前缀（如 `/salary`）               |

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
# SSH 连接（密钥认证，端口 22222）
ssh -p 22222 -i /Users/osong/new.pem root@47.236.187.33

# 部署流程（本地推送后）
ssh -p 22222 -i /Users/osong/new.pem root@47.236.187.33 "cd /root/enprizon-salary && git pull && systemctl restart enprizon-salary"

# 一键部署快捷别名（添加到 ~/.zshrc 或 ~/.bashrc）
alias save-salary='ssh -p 22222 -i /Users/osong/new.pem root@47.236.187.33 "cd /root/enprizon-salary && git pull && systemctl restart enprizon-salary"'

# 查看服务状态
ssh -p 22222 -i /Users/osong/new.pem root@47.236.187.33 "systemctl status enprizon-salary"

# 跟踪日志
ssh -p 22222 -i /Users/osong/new.pem root@47.236.187.33 "journalctl -u enprizon-salary -f"
```

### 测试（无自动化测试！）

项目无 `test_*.py` 或 `tests/` 目录，默认手工测试通过数据库替换实现。纯逻辑（计薪引擎、事件驱动推导、请假余额、权限判定）可补轻量 `pytest` 校验（见 `DEV_WORKFLOW.md` §7），**测试产物放** **`_work/`**，结束后按 TTL 机制清理（见 §测试产物清理）。

手工测试数据库隔离流程（服务器）：

```bash
cd /root/enprizon-salary
bash test-workflow.sh start       # 备份 → test_kilwa.db
bash test-workflow.sh swap        # 保存生产库 → 换入测试库
# ... 在前端执行测试操作 ...
bash test-workflow.sh restore     # 恢复生产库
bash test-workflow.sh clean       # 删除测试库（`prod_kilwa.db` 存在时拒绝，防止误删）
```

`test-workflow.sh` 使用 `$HOME/WorkBuddy/kilwa-system/data` 和 `$HOME/Desktop/enprizon_backups` 路径。

### 测试产物清理（TTL 机制，2026-08-16；任务完成即清理为硬规则，2026-09-02）

- `_work/` 目录**永久保留**（gitignored），产物按任务放 `_work/<任务名>/`

- 新任务开始：`bash cleanup-test-artifacts.sh`（清 >3 天旧产物）

- 部署完成：`bash cleanup-test-artifacts.sh --dir <任务名>`（删本次产物）

- 🚨 **任务完成即清理（2026-09-02 用户明令，硬规则）**：每个任务收尾时**必须**删除本次产生的全部临时产物，不等 TTL——
  ① `_work/<任务名>/`（脚本/截图/pycache）用 `--dir` 清；
  ② 系统临时文件：`/tmp` 下的脚本/PDF/补丁、浏览器 QA 会话目录（如 `.playwright-mcp/`）、**会话 cookie 文件（含凭据，必删）**；
  ③ 测试期间写入业务目录的文件（如 `data/payslips/` 测试导出）与测试库数据：只删**自己本次生成的**，按时间戳+字节数精确匹配，严禁误删用户/生产既有文件；
  ④ 收尾时自查：`git status` 应干净（无任务残留未跟踪文件）。

- 详见记忆 `feedback_test_artifacts.md` / `backup_spec.md`

### 代码风格

项目无 linter、formatter 配置（无 `.flake8`、`black`、`prettier`、ESLint 等）。修改代码时优先保持与周围代码风格一致。文件普遍偏长（`app.py` \~3340 lines, `calculator.py` \~1420 lines, `database.py` \~1730 lines, `index.html` \~4000 lines），尽量避免增加不必要的模块拆分。

### 备份与恢复（服务器端）

```bash
bash backup.sh                    # 每日备份 → /root/salary-backup/，自动清理 7 天前
bash restore.sh [备份路径]         # 停服 → 恢复 → 重启
```

手动安全备份（部署前）：`sqlite3.backup` → `data/backups/kilwa_before_<版本>_<时间戳>.db`，部署验证后只留最新 1 个。

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

- 密码存储：SHA256(salt + password)，salt 随机生成存入 `admin_users`（格式 `salt:hash`）

- 默认账号 `user/qweasd`（viewer），`KEJU` 首次登录自动升级为 super\_admin

- 🔒 **AI 代理验证专用账号（2026-09-02 用户明令，项目自始至终铁律）**：`keju_check` / `000000`（super\_admin）。**生产端已具备**，本地无则新建（salted SHA256 写入 `admin_users`）。两端统一用此账号做 AI 自动化验证

- 🚨 **绝对禁止改动生产端任何用户的密码**——无论任何理由（测试、排查、修复），一律不得对生产库 `admin_users.password_hash` 执行 UPDATE/重置。需要特定密码的测试账号 → 在**本地库**新建或改密

- 🚨 **铁律（2026-08-23 用户明令）**：测试账号只能用于测试，且**测试全程绝不能污染生产库原始数据**；需要最新数据时，把生产库拉到本地在本地测（拉取副本后可任意改密/造数，测完恢复本地原库）。本地超管：`KEJU` / `0000`

## 启动初始化

- **本地** `python3 app.py`：`init_db()` + `_migrate_json()`（旧 JSON 一次性迁移）+ `auto_load_source()`（从采集数据 + DB 重建当前月份，`data/source/` 已不再使用）

- **Gunicorn**：`_gunicorn_init()` 通过 `_app_initialized` 标志防止重复初始化

- `_ensure_viewer_account()` 自动创建默认 viewer 账号 + 升级 KEJU 为 super\_admin

- `_migrate_json()` 仅在 `overrides` 表为空时运行一次（检测到有数据则跳过）

- **P5 新增**：`_backup_to_archive()` 首次启动自动备份 `kilwa.db` → `archived_kilwa.db`（**此文件永久保留，勿删**）

- **P5 新增**：`seed_new_tables_from_excel()` 从 `data/source/*.xlsx` 重建 employees + hire 事件（仅首次）

- **P5 新增**：`seed_default_forms()` 预置 6 张表单 schema（入职/档案/调岗/出勤/产量×3）

- **P5 新增**：`init_default_permissions()` 初始化 4 角色默认权限到 `permissions` 表

- **P26-d 新增**：`_migrate_localtime_timestamps()` 启动迁移——**全系统时间戳统一 UTC+3（EAT）**。服务器曾为 CST(UTC+8)，旧表 DEFAULT `datetime('now','localtime')` 写入的时间快 5 小时；迁移重建所有含 localtime 默认值的表为 `+3 hours`，并按运行机偏移修正存量（EAT 本机只重建不平移；CST 服务器对 2026-08-14\~15 EAT 运行期之外的行 -5h）。audit\_log/dismissed\_employees/approval\_routes 数据为显式 UTC+3 写入不受影响

- **服务器时区**：生产机 `timedatectl` 与 systemd 单元均设 `Africa/Dar_es_Salaam`（UTC+3），保证任何 `localtime` 用法与 `datetime.now()`（工资单文件名）均为坦桑尼亚时间

- **Headless 模式**：切换到无数据月份时，自动生成该月所有自然日期，仅支持出勤记录（P/A/L 手动标记），前端顶部显示 "Preview Mode" 横幅

## 架构要点

### 数据流水线（纯采集模式）

```
采集提交（井下/钻工/破碎/出勤 4 类）→ collection_submissions + attendance_overrides（DB）
  → _run_pipeline() 从 DB 重建 main_data
       ├── rebuild_main_data_from_collections()：采集记录重建 shift/driller/crush 产量 + 出勤
       └── build_attendance_from_overrides()：出勤标记重建
  → employees 从 DB 读取（load_employees_from_db，替代通讯录 Excel 索引）
  → calculator.calculate_all() → verification.verify_salary() → APP_STATE 缓存 → API
```

月份范围由采集数据中的日期生成（不再扫描 `data/source/`，该目录已清空）。`scan_source_files()` 与 `parser.parse_all()`（Excel 解析）已在纯采集改造中移除；Excel 仅保留于历史归档（`data/archived_*`）。

> **P30 井下采集班组化（✅ 已部署 2026-09-01，main=9abd4cc + UX修正 adbf787）**：井下出渣采集改为**班组产量制**——payload 新格式 `{"teams":[{team_id,nh,nl,mw,exempt,remark}]}`（无 day/night/emps/drivers），一日一条提交；井下工人出勤并入**出勤收集**（部门选 `Production TEAM （underground）` → 选班组 → 人员逐人标 P/A/L/SK/T/E + 驾驶勾选），payload `{department,team_id,marks,drivers}`，upsert 键扩为 (form,date,department,team\_id)（`collection_submissions` 懒迁移 `team_id` 列）。**格式分支原则**：消费端一律按"rec 含 `teams` 键=新格式 / 含 `day_prod`=旧格式"分流，旧 payload 逐字保留 → 8 月及更早零改动（验收=改动前后 2026-08 全员薪资逐分 0 差异）。计算链 `ug_team_members` kwarg（app 构建花名册 → calculator/verification），池分母=班组当日 P 人数，零出勤班组跳过+警告。驾驶白名单语义：`driver_roster` **非空才校验**（空=未启用，兼容生产现状）。新增豁免二次编辑端点 `POST /api/collection/exempt/<id>`（仅 super\_admin，版本归档+审计 `collection_exempt_edit`）。数据台按数据格式分支：新格式月渲染班组对比图+班组 KPI，旧月白夜班原样。

> `employee_id` 生成链路（`namematch.py`）在纯采集模式下从 **DB** **`employees`** **表**构建 `_AB_INDEX`（不再依赖通讯录 Excel），其余三级匹配逻辑不变（见下）。

### employee\_id 生成链路（`namematch.py`）

`make_employee_id(name)` 三级匹配（调试姓名对不上时优先排查这一级）：

1. 去空格/去括号/大写 → 查通讯录索引 `_AB_INDEX` → 返回**通讯录账号**（如 `111`、`128`、`005`）
2. 未命中 → 查 `_LEGACY_CANONICAL`（短名→全名回退表）→ 再查通讯录
3. 仍失败 → 回退姓名"去空格大写"（兼容离职 / 通讯录外人员，此类 employee\_id 仍为旧格式）

> 2026-06-30 起全部表 `employee_id` 已从"姓名格式"整体迁移为"通讯录账号"，但未匹配通讯录者可能保留旧格式。

### 目录约定

| 目录              | 内容                                                                            | Git        |
| --------------- | ----------------------------------------------------------------------------- | ---------- |
| `data/`         | `kilwa.db` 主数据库、`backups/`（手动安全备份）、`archived_kilwa.db`（归档，永久）、Flask sessions/ | gitignored |
| `data/source/`  | 已清空（纯采集模式不再使用）                                                                | gitignored |
| `data/backups/` | 手动安全备份（`kilwa_before_*`，只留最新 1 个）                                             | gitignored |
| `_work/`        | 测试产物/临时分析脚本（按任务分子目录，TTL 清理）                                                   | gitignored |
| `templates/`    | Jinja2 模板（`index.html` 桌面 SPA + `mobile.html` 移动端 SPA）                        | 跟踪         |
| `static/css/`   | 样式文件（`style.css` + `mobile.css`）                                              | 跟踪         |
| `static/js/`    | 前端 JS（i18n + Chart.js CDN 缓存）                                                 | 跟踪         |
| `core/`         | 12 个后端模块（含 `__init__.py`）                                                     | 跟踪         |

### 薪资五轨道（`calculator.py`）

| 轨道   | 数据源                       | 逻辑                                 |
| ---- | ------------------------- | ---------------------------------- |
| 井下计件 | shift\_production（D/N 班）  | 当日产量 × 井下单价 / 出勤人数，人均平分            |
| 钻工计件 | driller\_production（队长制）  | 当日产量 × 钻工单价 /（队员+1 队长份额），队长×2 份额   |
| 破碎计件 | crush\_production         | bags × 300 / 有效人数，同日多条记录独立均分       |
| 日薪   | attendance + 井下 D/N 出勤    | 日薪基数 × 出勤天数                        |
| 月薪   | employees.monthly\_salary | 基数 / 26 × 实出勤，A/L 按天比例扣减，≥26 天封顶满薪 |

**单轨模式**：任一日期只归属一个轨道，杜绝双重计薪。

**UG 部门双条件（2026-08-16 用户明确）**：Production TEAM (underground) 部门只有 `default_type=piece_underground` 才参与井下计件/scoring；日薪/月薪员工通过井下采集出勤显示 D/N 属真实出勤，但不参与计件，按自身类型计薪。薪资类型判定**用** **`override_type or default_type`，不能只看 default\_type**（ENPRIZON LINDI PROJECT 部门 8 人 default=day\_rate 但 override=monthly 实际月薪）。详见记忆 `salary_calc_logic.md`。

税前总额 = 井下 + 钻工 + 破碎 + 日薪 + 月薪 + 加班费
净额 = 税前 + 奖金 + 司机津贴 - 预支 - NSSF(10%) - PAYE - 罚款
（P29-c：奖金/罚款/预支均为 bonus\_penalties 表月度手动项，支持薪资总表行内编辑；预支旧员工字段 advance\_total 已废弃恒 0 仅兜底）

### 定价机制（非显而易见）

三个价格常量 `PRICES_UNDERGROUND`、`PRICES_DRILLER`、`PRICE_CRUSH`（300）在 `calculator.py` 顶部硬编码。但每次 `calculate_all()` 从 DB config 读取并**全局猴子补丁覆盖**模块变量，结束后恢复。`/config` API 可修改 `crush_price` → 下次计算生效。**硬编码常量 ≠ 不可修改**。加班费公式参数（overtime\_base=400000/26/8/1.5）同理由 `/config` 可改。

### 例外覆盖（P5: 逐步被事件驱动取代）

- `overrides` 表：`start_date`/`end_date` 都空 → 永久覆盖（改变整月类型）；有日期 → 临时例外（仅影响区间）

- `attendance_overrides` 表：(employee\_id, date) 联合 PK，status P/A/L/D/N/C/S/Y/T/NU

- **P5 事件驱动**：`employee_events` 中已批准的 transfer/salary\_change/resign 事件自动转换为 overrides（`_derive_overrides_from_events()`）

- **优先级**：事件推导覆盖 > 手动 DB 覆盖

- 标记 A/L/NU 的员工从当日计件分配排除，总额守恒（剩余人员平分）

- **P23-R4 缓存同步**：员工/覆盖修改后 `_refresh_employees_cache()` 全量重建缓存，改薪资后无需 reload 即生效（避免缓存陈旧金额错误）

### 计薪模式切换（P5-b）

- `settings` 表 `underground_mode` 键：`piecework`（默认，纯计件）| `scoring`（评分模式）

- **scoring 模式**：井下工人 = 固定月薪（monthly\_salary/26×出勤天数）+ 司机津贴（5000/天）+ 评分奖金

- **piecework 模式**：保持原有五轨计件逻辑不变

- 通过 `/config` API 切换，recalculate 后生效

- 双路径核对在两种模式下均应保持 0 偏差

### 评分奖金三层模型（以《生产团队绩效考核体系管理手册.docx》为准）

- **① 产量层**：总池**仅由 NICKEL(H) 车次生成** = max((NICKEL(H) 车次 − 600), 0) × 20,000；NICKEL(L)/MAWE 不计；<600 车次 → 无池；半池 = 总池×50%

- **② 客观层**：S = R1×70% + R2×30%（R1=实际出渣÷计划出渣，不封顶；R2=有效÷在井，≤100）；月度 S = 当日 S 均值；发放比例 **90/80/70/60 五档**（≥90→100%, 80-89→95%, 70-79→90%, 60-69→80%, <60→70%）；班实际池 = 半池×发放比例

- **③ 主观层**：6 维互评去极值 → 行为分=(均值−1)/4×100 → 系数（≥85→1.2/70-84→1.0/60-69→0.8/<60→0.5），管理 1.5 票加权；个人奖金 = 班实际池×(个人系数÷Σ本班系数)

- **渣产量（总产量）只进客观层 R1 定折扣，不参与奖金池生成**；R1 实际出渣量**改由手动录入**

- 代码注意：`_get_scoring_bonus` 读新表 `scoring_card_entries`（含旧表回退）；发放比例分档在 `get_monthly_objective`（`core/database.py`）统一为 90/80/70/60；半池禁止硬编码

### 加班费（P23，2026-08-16）

- OA `overtime` 事件 → 审批通过写 `overtime_records` 表（event\_id/employee\_id/date/start\_time/end\_time/hours/amount）

- 公式：`hours × overtime_base / overtime_work_days / overtime_hours_per_day × overtime_rate`（默认 400000/26/8/1.5，计薪参数页可改）

- hours 规则：0.5h 一档向下取整、end\<start 跨天、>12h 拒绝；前端实时算 + 后端审批重算兜底

- 加班费并入 gross（独立 `overtime` 展示字段 + `total_overtime`），日明细逐日叠加；撤销自动回滚

### 出勤状态字母

D(蓝)=井下白班, N(青)=井下夜班, B(紫)=D+N, R(青绿)=钻工, C(橙)=破碎, P(绿)=日薪/月薪, A(红)=旷工, L(黄)=请假, S=事假, Y=年假, T=调休, **E(浅紫)=豁免**(未出勤不计薪不计 A\_W 罚), NU(紫深)=年假计薪(只读), (P)(灰)=月薪默认

点按切换：R/C → A → L → 空 → P（不可回到原始自动值）。**NU 只读**（审批写入，防采集覆盖）。

### 代码修改关键不变量

改 `calculator.py` / `app.py` 前务必遵守：

- **单轨模式源于 v3.0 重构（commit e6b9487）**，目的是从架构上根除"双重计薪" bug。任何改动都必须保证 **任一日期只归属一个轨道**，不可让某员工某天同时被多个轨道计薪。

- **日工资明细必须与薪资页一致**：`compute_daily_breakdown()` 与 `calculate_all()` 共用同一套 `per_date_type` + 四轨子函数结果，按相同逐日选轨逻辑生成明细。"日工资明细页"与"薪资总表应发金额"必须逐人逐日相等（总则硬性要求），改计算逻辑时两者要同步验证。

- **总额守恒**：A/L 标记员工从当日计件分配排除后，剩余人员平分，当日计件总额不变（极端情况：队长 A/L 且无队员除外）。

- **override\_type 优先**：判断薪资类型用 `override_type or default_type`（P22-FIX 教训，见 §薪资五轨道）。

- **日期/数量区间展开必须有硬上限（2026-09-04 OOM 瘫痪事故铁律）**：从 DB 读 `start_date/end_date` 做逐日（逐格/逐项）展开的循环，必须 clamp 到 `_OVERRIDE_EXPAND_MAX_DAYS`（800 天，`calculator.py` 顶部常量）。**永久哨兵值（`9999-12-31` 等）与展开循环组合 = 定时炸弹**：单条哨兵行曾把 `calc_driller_piece` 撑到 291 万天迭代 / +932MB / 10s CPU，894MB 服务器被 OOM killer 循环击杀瘫痪半天。新增任何"按区间展开"代码（calculator/导出/明细）必须复用同一 clamp 常量；写入远期 end_date 的功能（如 OA 调岗自动转计件 `core/database.py`）上线前必须验证消费方有界。

- **生产服务器只有 894MB 内存**：单请求内存预算 <100MB 常态、峰值 <500MB。禁止在请求路径加载全表到内存后再 Python 过滤大集合；新功能上线前用 `python3` + RSS 采样跑一遍主流程（方法见 memory `project_oom_incident_20260904.md`）。

- **落库字段必须存"消费方期望的形态"**：如 `overrides.captain` 存**队长名字**（与产量数据 `driller_data['captain']` 同源、能过 `make_employee_id` 解析），不能存下拉框 id（曾发生 captain='9' 导致员工进不了队长池分钱）。表单 value 绑定与落库形态要前后端对齐，新增下拉字段时先查消费方的匹配逻辑。

### 前端技术栈

- **单文件 SPA**：`templates/index.html`（\~4000 lines），所有 JS 内联在 `<script>` 标签中，无独立 JS 模块或构建系统

- **P0 导航重建**：侧边栏 + 面包屑 + hash 路由 `#module/subpage?key=val`，8 个主模块：数据台/员工/OA/考勤/产量/评分/薪资/系统

- **15+ 个页面标签**：数据台（Dashboard）/ 员工列表 / 员工档案 / OA 待审 / OA 历史 / 出勤网格 / 薪资总表 / 日工资明细 / 产量×3（井下/钻工/破碎）/ 评分×3（录入/汇总/客观）/ 系统配置 / 用户权限 / 表单自定义 / 旧数据归档

- **国际化 (i18n)**：`static/js/i18n.js`（800+ 键）支持中英文即时切换

- **图表**：Chart.js v4.4.7 + chartjs-plugin-datalabels

- **P4 新增**：全局搜索（顶栏，防抖300ms，跨 employees/salary/production/attendance）+ 移动端响应式

- **P22 壳层布局**：应用壳层固定（顶部栏/面包屑/筛选框 sticky，`.main` 唯一滚动区，切页重置滚动顶部）

- **Golden Time 暖白编辑风 UI**：`static/css/style.css`（\~1940 lines）

### 前端数据流

- 所有 API 调用通过内联 `fetch()` 发送，浏览器自动携带 `session` cookie 认证

- 全局 `STATE` 对象缓存当前月份薪资/出勤/产量等全部数据

- 用户操作流程：表单交互 → `fetch` API 调用 → 后端更新 DB + 返回结果 → 前端局部更新 DOM 或调用 `recalculate()` 全面刷新

- `showPage(name)` 切换页面标签，优先从 `STATE` 读取缓存，其次 fetch

### 导出系统

| 端点                       | 输出            | 需认证     | 说明                                   |
| ------------------------ | ------------- | ------- | ------------------------------------ |
| `POST /export`           | Excel 3 Sheet | editor+ | 薪资总表 + 核对 + 日明细                      |
| `POST /export/employees` | Excel         | editor+ | 员工花名册（类型/NSSF/奖惩）                    |
| `GET /export/attendance` | Excel         | editor+ | 出勤网格导出                               |
| `POST /export/all`       | Excel 7 Sheet | editor+ | 英文版统一导出（员工信息+薪资+出勤+日工资+产量+钻工核对+钻工明细） |

### 司机津贴（P11 改造）

由出勤勾选"驾驶"触发，须在校验 `driver_roster` 名单内，自动 5,000/班 计津贴并流入薪资总表 `driver_allowance` 列。

### 权限模型（P29 V2.1）

细粒度目录 **21 键 / 8 模块**（数据台/员工/审批中心/出勤/薪资/数据采集/评分/系统，production:\* 已移除：view→dashboard:view、edit→collection:view+4 表单键）。动作四类：`view`（看页面）/ 操作键（approve/edit/export 等）/ `apply`（提交 OA 申请）/ `manage`（角色授权管理）。

内置五角色：`super_admin`(*:*) > `admin` > `collector`（采集 4 表单键+employees:view+attendance:view）> `applicant`（oa:view+oa:apply 只看自己申请）> `viewer`（全模块 view 含薪资只读）。**档案页薪资板块硬角色门控（P29-c）：仅 super\_admin/admin/viewer 可见，与权限键无关**（collector 凭 employees:view 浏览全员但不泄薪资）。继承仅一条字面映射 `ROLE_HIERARCHY={'collector':['applicant']}`；custom 角色平级。**editor 已降出内置角色且生产已删**，但 `ROLE_LEVELS['editor']=1` 保留（旧装饰器基线兼容）。判定走 check\_permission（role\_permissions + user\_grants）。迁移版本化：settings.perm\_v2\_migrated 数字版本（当前 2），预设演进自动重播种。薪资总表支持奖金/罚款/预支行内编辑（POST /api/salary/inline-edit，employees:edit 门控，写 bonus\_penalties 含 advance 列）。

运营侧两个高频点：**OA 申请三端点挂** **`oa:apply`**（POST /api/oa/events、/api/oa/leave、/api/leave/sick），读端点 (oa:view||oa:apply) 且仅 apply 者只看自己的提交；**数据采集按表单类型动态校验** **`collection:<type>`**（underground/driller/crush/attendance），无 editor 角色地板（collector 是 0 级角色，地板会废掉整个 persona）。默认账号 `user/qweasd`（viewer），`KEJU` 自动升 super\_admin。启动迁移 `_migrate_permissions_v2()` 幂等（settings.perm\_v2\_migrated=1）。

### 数据库表（P5 18+ 张 + P7-P23 增量）

| 表                            | 说明                                                                                                                                                                                                              | 阶段                         |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| `employees`                  | 员工主档（P1：position/skill\_level/hire\_date/NIDA/NSSF/银行；**P7 增** gender/date\_of\_birth/avatar\_path；**P10 增** custom\_number/team\_id；**P14.5 增** alias；**P20 增** annual\_leave\_override；**P21 增** tin\_number） | P0+P1+P7+P10+P14.5+P20+P21 |
| `overrides`                  | 薪资例外：永久/临时（逐步被 employee\_events 取代）                                                                                                                                                                             | P0                         |
| `attendance_overrides`       | 手动出勤标记 P/A/L/D/N/C/S/Y/T/NU                                                                                                                                                                                     | P0+P8                      |
| `settings`                   | 系统配置 key-value（定价/NSSF/underground\_mode/scoring/overtime 参数/**perm\_v2\_migrated 迁移标志**）                                                                                                                       | P0                         |
| `monthly_data`               | 月度薪资快照缓存                                                                                                                                                                                                        | P0                         |
| `audit_log`                  | 操作审计（强制 UTC+3）                                                                                                                                                                                                  | P0                         |
| `shift_additions`            | 手动补井下计件班次                                                                                                                                                                                                       | P0                         |
| `driller_additions`          | 手动补钻工分组                                                                                                                                                                                                         | P0                         |
| `bonus_penalties`            | 月度奖惩＋预支（P29-c 补 advance 列：预支改月度手动录入，calculator 由此取值替代恒 0 的旧员工字段）                                                                                                                                                | P0+P29-c                   |
| `dismissed_employees`        | 离职追踪                                                                                                                                                                                                            | P0                         |
| `admin_users`                | 用户认证（加盐 SHA256）                                                                                                                                                                                                 | P0                         |
| `employee_events`            | OA 生命周期事件（入职/调岗/离职/薪资变/请假/**加班**）                                                                                                                                                                               | P1+P23                     |
| `leave_balances`             | 年假/调休余额（**P8 增** 病假 14 天/年默认）                                                                                                                                                                                   | P2+P8                      |
| `leave_requests`             | 请假申请（**P8 增** leave\_type='sick' 病假）                                                                                                                                                                            | P2+P5+P8                   |
| `driver_roster`              | 司机白名单                                                                                                                                                                                                           | P2                         |
| `scoring_cards/entries`      | 评分卡 + 6 维评分（**P10 重设计**；奖金计算读**新表** `scoring_card_entries`）                                                                                                                                                     | P3+P10                     |
| `objective_records`          | 客观产量数据（R1/R2→S；R1 实际出渣量**手工录入**）                                                                                                                                                                                | P3                         |
| `permissions`                | 细粒度权限注册表（**P29 V2.1 目录：8 模块×21 键**，启动迁移重置）                                                                                                                                                                      | P4+P29                     |
| `user_grants`                | 用户单独授权（覆盖角色默认；P29 迁移翻译 production 旧键，deny 复制×5）                                                                                                                                                                 | P4+P29                     |
| `form_schemas/fields`        | Schema 驱动表单定义                                                                                                                                                                                                   | P4                         |
| **`collection_submissions`** | **P9 新增**：数据采集提交主表（井下/钻工/破碎/出勤收集 4 类）                                                                                                                                                                           | P9                         |
| **`collection_history`**     | **P9 新增**：编辑历史版本表（旧 payload 留档）                                                                                                                                                                                 | P9                         |
| **`employee_groups`**        | **P10 新增**：班组表（LAMBA LAMBA / SAKA SAKA 等）                                                                                                                                                                       | P10                        |
| **`driller_captains`**       | **v5 新增**：钻工队长名单（当前 3 人，计薪参数页维护）                                                                                                                                                                                | v5                         |
| **`approval_routes`**        | **P13 新增**：审批人路由表（event\_type → 指定审批人）                                                                                                                                                                          | P13                        |
| **`role_permissions`**       | **P18 新增**：角色默认权限（DB 可编辑；P29 重置为五内置角色预设）                                                                                                                                                                        | P18+P29                    |
| **`overtime_records`**       | **P23 新增**：加班记录（event\_id 外键/employee\_id/date/起止时间/hours/amount）                                                                                                                                               | P23                        |

### 硬排除名单（`app.py:40-45`）

6 人全局隐藏、不计薪：ERIC WANG QM, JIMMY, SET SAIL, 宋家成（Daria）, 宋科举KEJU, 宋科举

### APP\_STATE 内存缓存

全局 `APP_STATE = {}` 缓存解析结果。`/reload` 清空并重新填充。重启后丢失。**P23-R4**：员工/覆盖修改端点调 `_refresh_employees_cache()` 全量重建，避免缓存陈旧。

### 已知数据边界（非 bug）

1. 5/25 夜班产量无人领取（156,000 TZS，源数据缺员工名单 → 路径一二永久差异）
2. 钻工 5/1-5 无队员（仅队长 1 人）
3. 同名多槽位（同队长同天多次出现 → 产量合并，成员去重）
4. 跨 Sheet 人员（产量表+日薪表同时出现 → 需手动指定类型）
5. 仅预支表人员（通讯录外，仅出现在预支表中）
6. 双路径舍入差额约 ±2\~8 TZS（QA 接受容差，非 bug）
7. 日明细只显示当月有日工资金额的人（无出勤员工不显示属正常）

## 代码分工速查

### 后端模块（`core/` 12 个文件，行数为约数会随版本漂移，仅供参考）

| 文件                     | 职责                                                    | <br /> | <br />                |
| ---------------------- | ----------------------------------------------------- | :----- | :-------------------- |
| `app.py`               | Flask 路由 + 认证 + 会话 + 数据管线编排（\~3340 lines, 43+ API 端点） | <br /> | <br />                |
| `core/calculator.py`   | 五轨计算 + 逐日单轨合并 + 日工资明细 + 加班费并入（\~1420 lines）           | <br /> | <br />                |
| `core/parser.py`       | Excel 解析（**已无调用方，遗留死代码**）                             | <br /> | <br />                |
| `core/verification.py` | 双路径核对（产量×单价 vs 实际分配，                                  | diff   | ≤10 视为舍入，\~300 lines） |
| `core/namematch.py`    | 姓名标准化 + employee\_id 生成 + 员工主列表（\~250 lines）          | <br /> | <br />                |
| `core/database.py`     | SQLite ORM（30+ 张表）+ 审计日志 + 加班时长计算（\~1730 lines）       | <br /> | <br />                |
| `core/addressbook.py`  | 通讯录解析（\~150 lines，仍被使用）                               | <br /> | <br />                |
| `core/advance.py`      | 预支数据解析（\~80 lines，遗留）                                 | <br /> | <br />                |
| `core/nssf.py`         | NSSF SDL 社保名单解析（\~40 lines，仍被使用）                      | <br /> | <br />                |
| `core/exceptions.py`   | 例外覆盖标记加载，兼容 JSON + DB（\~25 lines）                     | <br /> | <br />                |
| `core/pricing.py`      | 单价配置代理，模块常量（\~10 lines）                               | <br /> | <br />                |
| `core/__init__.py`     | 包初始化（1 line）                                          | <br /> | <br />                |

### 模块依赖层级

```
app.py (Flask 路由 / 认证 / 数据管线)
 ├── core/parser.py         (Excel→结构化数据)   ← 遗留死代码
 │    ├── core/addressbook.py (通讯录解析)
 │    ├── core/advance.py     (预支解析)
 │    └── core/nssf.py         (NSSF SDL 解析)
 ├── core/namematch.py       (姓名标准化 / employee_id)
 ├── core/calculator.py      (五轨计算 / 逐日合并 / 加班费)
 │    └── core/pricing.py     (单价配置)
 ├── core/database.py        (SQLite ORM / 审计 / overtime)
 ├── core/verification.py    (双路径核对)
 └── core/exceptions.py      (例外覆盖加载)
```

> 纯采集模式下：`core/parser.py`、`core/advance.py` 已无调用方（Excel 源已废弃），属遗留死代码；`core/nssf.py`、`core/addressbook.py` 仍被使用。数据主路径为 `_run_pipeline()` ← `collection_submissions`/`attendance_overrides`/`employees`（DB）。

### 关键 API 端点

| 方法                  | 路由                                 | 权限                                    | 说明                                                                            |
| ------------------- | ---------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------- |
| POST                | `/api/login`                       | 公开                                    | 登录，建立 session                                                                 |
| POST                | `/api/logout`                      | 公开                                    | 登出                                                                            |
| GET                 | `/api/auth/status`                 | 公开                                    | 当前用户登录状态                                                                      |
| GET                 | `/`                                | 公开                                    | SPA 入口页面                                                                      |
| GET                 | `/available-months`                | editor+                               | 可用月份列表                                                                        |
| POST                | `/set-month`                       | editor+                               | 切换到指定月份                                                                       |
| POST                | `/reload`                          | editor+                               | 清空 APP\_STATE，从 DB 重建当前月份 + 计算（兜底用）                                           |
| POST                | `/recalculate`                     | editor+                               | 触发重新计算（采集提交自动调用，无需手动点）                                                        |
| GET                 | `/salary`                          | editor+                               | 薪资总表数据（含核对差异）                                                                 |
| GET                 | `/salary/verify`                   | editor+                               | 双路径核对详情                                                                       |
| GET                 | `/attendance`                      | editor+                               | 出勤网格数据                                                                        |
| POST                | `/attendance/toggle`               | editor+                               | 手动标记出勤                                                                        |
| GET                 | `/employees`                       | editor+                               | 员工列表 + 例外覆盖                                                                   |
| POST                | `/employees/override`              | editor+                               | 添加薪资例外（永久/临时）                                                                 |
| POST                | `/employees/remove-override*`      | editor+                               | 删除例外覆盖                                                                        |
| POST                | `/employees/bonus-penalty`         | editor+                               | 添加月度奖惩                                                                        |
| GET                 | `/employees/dismissed`             | editor+                               | 离职员工列表                                                                        |
| POST                | `/employees/dismiss`               | admin+                                | 标记员工离职                                                                        |
| GET/POST            | `/config`                          | admin+                                | 读取/修改定价、NSSF 费率、加班参数                                                          |
| GET                 | `/nssf/list`                       | editor+                               | NSSF 社保名单                                                                     |
| GET                 | `/production`                      | editor+                               | 产量数据                                                                          |
| GET                 | `/api/production/dashboard`        | login\_required                       | 数据台产量仪表盘                                                                      |
| GET                 | `/production-verify`               | salary:view OR dashboard:view（P31 双键） | 产量核验（P31: teams 分支+顶层汇总）                                                      |
| GET                 | `/daily-wages`                     | editor+                               | 日工资明细                                                                         |
| GET/POST/PUT/DELETE | `/api/driller-captains`            | admin+                                | 钻工队长名单 CRUD                                                                   |
| GET                 | `/audit-log`                       | admin+                                | 审计日志                                                                          |
| POST                | `/export`                          | editor+                               | 薪资 Excel（3 Sheet）                                                             |
| POST                | `/export/employees`                | editor+                               | 员工花名册 Excel                                                                   |
| GET                 | `/export/attendance`               | editor+                               | 出勤网格 Excel                                                                    |
| POST                | `/export/all`                      | editor+                               | 英文版全量导出（7 Sheet）                                                              |
| GET                 | `/admin/users`                     | super\_admin                          | 用户管理页面                                                                        |
| POST                | `/admin/users/role`                | super\_admin                          | 修改用户角色                                                                        |
| POST                | `/admin/users/create`              | super\_admin                          | 新增登录用户                                                                        |
| POST                | `/admin/users/change-password`     | super\_admin                          | 修改指定用户密码                                                                      |
| POST                | `/api/admin/change-password`       | 登录用户                                  | 修改自身密码（全角色可用）                                                                 |
| GET                 | `/api/permissions/users`           | admin+                                | 用户权限矩阵                                                                        |
| POST/DELETE         | `/api/permissions/grant`           | super\_admin                          | 单独授权/撤销                                                                       |
| GET                 | `/api/search?q=`                   | 登录用户                                  | 全局搜索（含别名）                                                                     |
| GET/POST/PUT/DELETE | `/api/forms/schema/*`              | 登录/超管                                 | 表单自定义 CRUD                                                                    |
| GET                 | `/api/archive/months`              | 登录用户                                  | 归档月份列表                                                                        |
| GET                 | `/api/archive/salary?month=`       | 登录用户                                  | 归档薪资查询                                                                        |
| POST                | `/api/employees/avatar`            | admin+                                | 员工头像上传（前端压缩 ≤2MB）                                                             |
| POST                | `/api/employees/avatar/delete`     | admin+                                | 删除员工头像                                                                        |
| POST                | `/api/leave/sick`                  | 登录用户                                  | 病假申请（免审）                                                                      |
| POST                | `/api/collection/submit`           | editor+                               | 数据采集提交（4 类）                                                                   |
| GET                 | `/api/collection/history`          | editor+                               | 数据采集历史                                                                        |
| POST                | `/api/collection/edit/<id>`        | editor+                               | 再编辑历史提交                                                                       |
| GET                 | `/api/collection/roster`           | 持任一采集键或 scoring:edit                  | 采集/评分表单轻量花名册（仅 id/name/dept 等 7 字段，不含薪酬数据）P29-b                               |
| POST                | `/api/salary/inline-edit`          | employees:edit                        | 薪资总表行内编辑奖金/罚款/预支（写 bonus\_penalties 含 advance 列，审计 salary\_inline\_edit）P29-c |
| GET/POST/PUT/DELETE | `/api/employee_groups/*`           | admin+                                | 班组 CRUD                                                                       |
| GET                 | `/api/scoring/team/<id>/month/<m>` | editor+                               | 评分卡全员列表                                                                       |
| POST                | `/api/scoring/card/batch`          | editor+                               | 批量提交评分卡                                                                       |
| GET/POST            | `/api/oa/*`                        | 登录/editor                             | OA 待审/历史/审批/撤销/编辑                                                             |
| POST                | `/api/employees/<id>/salary-type`  | editor+                               | 修改员工薪资类别+基数                                                                   |

### 前端文件

| 文件                                           | 职责                                              |
| -------------------------------------------- | ----------------------------------------------- |
| `templates/index.html`                       | 桌面单页 SPA（\~4000 lines，15+ 页面标签，全部 JS 内联）        |
| `templates/mobile.html`                      | 移动端独立 SPA（\~1124 lines，数据台/员工/采集/出勤 4 Tab + 登录） |
| `static/css/style.css`                       | Golden Time 暖白编辑风 UI 主题（\~1940 lines）           |
| `static/css/mobile.css`                      | 移动端布局/组件样式                                      |
| `static/js/i18n.js`                          | 中英文翻译字典（800+ 键）+ 运行时切换引擎                        |
| `static/js/chart.umd.min.js`                 | Chart.js v4.4.7                                 |
| `static/js/chartjs-plugin-datalabels.min.js` | 图表数据标签插件                                        |

### 移动端前端（P16/P17，已上线）

独立移动端 SPA（**非响应式改造**），与桌面端 `index.html` 平行，共享后端 API 与 `i18n.js`。权威方案见 `docs/P16_MOBILE_FRONTEND_SPEC.md`。

**技术特点**：

- 4 标签底部 Tab Bar：📊数据台 / 👥员工 / 📋采集 / ⏱出勤

- 顶栏含月份切换、搜索、🌐语言(中/EN)、🌙主题切换，均 localStorage 持久化

- 所有 API 调用经 `fetch()` + `credentials:'same-origin'`；未登录显示登录页

- 数据台：6 KPI + 产量趋势/白夜班/钻工堆叠/矿石环形 4 图 + 破碎卡片列表

- 员工：列表/档案/编辑/OA 待审-已审批/请假申请/加班申请

- 采集：井下出渣/钻工组/破碎计件/出勤收集 4 表单 + 首页历史

- 出勤：横向滑动 31 天网格 + 长按/点按编辑 + 批量标记 + 部门筛选 + 请假/病假快捷入口

- PWA 可安装（manifest + SVG 图标）；**刻意不启用 Service Worker**（子路径频繁部署，SW 缓存会导致不刷新）

- 后端零改动（仅 `/m` 路由 + UA 重定向）

> ⚠️ **`.design/enprizon-mobile/`** **等是设计工具导出原型，不是可运行代码**，已被 gitignore 排除。真正的实现是 `mobile.html` + `mobile.css`。

### 运维脚本

| 文件                          | 用途                                                      |
| --------------------------- | ------------------------------------------------------- |
| `start.sh`                  | 本地开发启动（Python 路径硬编码）                                    |
| `backup.sh`                 | 服务器每日备份 → `/root/salary-backup/`，7 天自动清理                |
| `restore.sh`                | 服务器停服→恢复→重启                                             |
| `test-workflow.sh`          | 测试库安全隔离（start/swap/restore/clean）                       |
| `cleanup-test-artifacts.sh` | 测试产物 TTL 清理（\_work 保留，清 >3 天 / `--dir` 按任务）             |
| `gunicorn.conf.py`          | 生产配置（127.0.0.1:8081, 1 worker, 2 threads, 120s timeout） |

## 原则

- 临时分析脚本、测试产物放 `_work/`（已 gitignore），按 TTL 机制清理，**`_work/`** **目录本身保留**

- **任务完成即删除全部临时文件（硬规则）**：临时脚本/测试产物/cookie/QA 会话目录/测试生成的业务文件，收尾必清（见 §测试产物清理）

- 复杂任务（≥3 需求）用 KEJU 团队并行（designer/dev/qa），简单任务直接做

- 判断薪资类型用 `override_type or default_type`

- **日期区间展开必 clamp / 哨兵值消费方必设防 / 落库形态=消费方期望**（2026-09-04 OOM 事故三条铁律，详见 §代码修改关键不变量）

## 重构状态（2026-09-02 更新，main=2d8228e；P29/P30/P31/P32 已部署）

**分支**: `main`（小改动直接在 main 做；大改动建 feature 分支合并；原 `refactor` 分支已删除）
**阶段**: **P0-P29 全部完成并部署**（P18 权限框架 / P19 别名搜索 / P20 年假豁免 / P21 年假计薪+TIN / P22 一批需求 / P22-FIX 日明细 / P23 照片加班审计缓存同步 / UI 壳层布局 / P24 安全修复与登录体验 / P25 计件薪资 V2 凸性加速 / P26-P28 / **P29 权限体系 V2.1（已部署 2026-08-23，迁移幂等完成）** / **P30 井下班组化（已部署 2026-09-01）** / **P31 数据台班组化（已部署 2026-09-02）** / **P32 出勤采集排除已批假期 + 数据台趋势tooltip班组物料（已部署 2026-09-02）**）
**纯采集模式**: 已移除 Excel 数据源依赖。薪资全部由 P9 采集驱动，提交后自动触发计算；employees 从 DB 读取；data/source 目录已清空
**部署**: 已部署至阿里云 `main` 分支（systemctl restart enprizon-salary），当前 main=2d8228e，服务 active
**团队**: KEJU 团队（designer/dev/qa）并行工作流，复杂任务必用；agentmemory 已整合（开始 recall / 完成 remember）

### 最近阶段新增功能（P18-P29 摘要）

| 阶段          | 新增                                                                                                                                                                                                                                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **P18**     | **权限重构**：role\_permissions 表 + check\_permission DB 判定 + 敏感端点全挂 @require\_permission + 前端菜单/路由按权限过滤 + 权限编辑器 UI（P18b-d）+ 双 Tab（P18C）+ 角色 CRUD（P18D）+ P18E UI 重构 + P18F 登出修复                                                                                                                                   |
| **P19**     | 移动端登录页语言切换 / 全系统搜索支持别名 / 权限 grant 值归一化                                                                                                                                                                                                                                                                       |
| **P20**     | 员工档案 annual\_leave\_override 豁免开关（NSSF+NIDA），仅 OA 审批人可改                                                                                                                                                                                                                                                      |
| **P21**     | 年假计薪+请假撤销编辑+NU状态+TIN字段+计件双条件(R4)+错误双语+员工改名                                                                                                                                                                                                                                                                   |
| **P22**     | 自助改密/OA历史类型筛选/档案姓名上移/D-N高对比色/移动端档案薪资规则                                                                                                                                                                                                                                                                       |
| **P22-FIX** | 日工资明细 105→107（UG 部门 day\_rate 员工计入），override\_type 优先判定                                                                                                                                                                                                                                                      |
| **P23**     | 照片放大压缩/加班申请计费(overtime\_records+参数可改)/审计日志移权限页/缓存同步bug修复                                                                                                                                                                                                                                                     |
| **P24**     | 安全修复（登录角色回退降级/恒时密码比较/会话Cookie加固/OA审批原子化等）+ 登录体验（密码可见图标/错误提示/取消账户锁定）                                                                                                                                                                                                                                          |
| **P25**     | **计件薪资制度 V2（凸性加速计件）**：第三模式 `underground_mode='v2'` + 班组对齐 employee\_groups + 出勤 E 豁免 + 子部门筛选（详见下方 P25 专节）                                                                                                                                                                                                    |
| **P29**     | **权限体系 V2.1**：目录重造 21 键/8 模块（production:\* 移除，目录=页面）+ 五内置角色（新增 collector/applicant，editor 降级但 ROLE\_LEVELS 保留）+ 三表幂等迁移（perm\_v2\_migrated 标志 + audit\_log 备份）+ OA apply/approve 分离（oa:apply）+ 采集动态表单键门控 + Web 审批中心独立模块（五类申请表单归入其下，员工板块扁平化直入列表，IA 修订 2026-08-23）+ 移动端 isAdminLevel 收敛（详见 ARCHITECTURE.md §十一） |
| **UI**      | 壳层布局（顶部栏/面包屑/筛选框固定，内容区滚动，切页重置）+ modal Apple 风格动画 + toast 顶部居中                                                                                                                                                                                                                                                |

### 纯采集模式修复的 Bug（2026-08-13）

1. **`parse_crush_sheet`** **选错 sheet**：企业微信导出文件带"智能表1"空壳 → 优先选 `CRUSH TEAM Production Data`
2. **破碎表头带"数字"后缀**：`How many Bgas -数字` 匹配失败 → 补充匹配 key
3. **`load_overrides`** **去重 bug**：同 effective\_from 多条永久覆盖时误删有金额的 monthly → 同优先级保留有金额的
4. **`calculate_all`** **顶层 monthly 满勤**：薪资总表与日工资明细不一致（12天 vs 26天）→ 遍历 present\_dates 补满26天
5. **namematch 索引**：纯采集模式从 DB employees 表构建 `_AB_INDEX`（替代通讯录 Excel）
6. **井下计件人均虚高**：井下工人被 day\_rate/monthly 永久覆盖后从计件分配排除 → 分母错误致人均翻倍 → 清理历史覆盖残留 + 38 AYUBU default\_type 修正
7. **计薪参数保存无效**：`cfg_ug_mode` 绑定不存在的 `saveUndergroundMode()` + 单价 `||6000` 吞 0 值 → 改绑 `saveConfig()`
8. **评分汇总无数据**：`/api/scoring/summary` 读旧表 `scoring_entries` → 改为从新表读 + 旧表回退

## P25 计件薪资制度 V2（凸性加速，已部署）

权威文档：`docs/P25_PIECEWORK_V2_SPEC.md`（业务规格）+ `docs/P25_PIECEWORK_V2_IMPLEMENTATION.md`（实现设计）。

- **模式**：`underground_mode` 增第三值 `'v2'`（piecework/scoring 原样保留可回退）。V2 = 凸性团队计件（日）+ 评分行为系数（月末零和再分配）的统一模式。

- **开关语义（重要）**：V2 是 DB 配置开关——`underground_mode='v2'` 且 `month_prefix >= v2_effective_from` 才激活；部署本身**不改变任何计薪行为**（服务器当前仍 piecework）。启用方式：计薪参数页选「凸性计件 V2」+ 填 `v2_effective_from`。

- **日池公式**：`pool = Σ(物料×accel_prices[8000/5000/3000]) × (exempt ? 1.0 : 总车次/accel_target[40])`，按班人头均分；`team_id==0` 班次跳过（采集未选班组）。豁免 = 采集页每班「设备故障豁免」勾选。

- **月末再分配**：`apply_v2_month_end`：`A_W=出勤/(26−豁免{L,NU,E})`、`B_W=复用评分互评系数(compute_scoring_individuals, 缺省 1.0)`、`C_W=0.6A+0.4B`、`k=F/Σ(base×C)`、`final=base×C×k`（零和守恒，Σfinal==Σbase）。

- **班组 = 子部门**：井下生产按 `employee_groups`（LAMBA LAMBA/SAKA SAKA）归属，**不新建 teams 表**；采集 payload `day/night` 带 `team_id`+`exempt`。前端员工列表 UG 员工部门列显示班组名；档案页部门下方班组行；员工/薪资/日工资/出勤 4 处筛选框支持班组（子部门）筛选；计薪参数页「添加班组」= 在 UG 部门下加子部门，增删后各筛选自动同步。

- **出勤** **`E`（豁免）**：未出勤不计薪、不计 A\_W 罚（区别于 NU 计薪）；已入 att\_exclusions/absent/日薪排除与 A\_W exempt\_days。

- **数据/核对**：`monthly_data` 增 `ug_base`/`ug_coefficient` 列；`verify_salary` V2 分支 + `coefficient_conservation`（≤10 舍入）字段，逐日对比在 V2 下松弛。

- **⚠️ 前端陷阱**：DB 部门名是**全角括号** `Production TEAM （underground）`；前端比较一律用 `normDept()`（index.html 内，规范化空格/全角括号/大写）再比 `'PRODUCTIONTEAM(UNDERGROUND)'`，**禁用裸字符串比较**。

- **测试**：38 个 pytest（凸性池/月末守恒/门控/豁免）曾在 `_work/piecework-v2/`，部署后已按 TTL 清理；纯逻辑改动可重建同款用例。

### 下一步

1. **P29 权限体系 V2.1 ✅ 已部署（2026-08-23）**：main=be3efce 上线，服务器首启迁移日志确认「P29 权限目录 V2.1 迁移完成」，perm\_v2\_migrated=1、五内置角色行数精确、存量 editor 平移保留；回滚预案=data/backups/kilwa\_before\_p29\_20260823\_194713.db。后续观察项：各角色登录走查 + 权限编辑器分组显示
2. **P30 井下班组化 ✅ 已部署（2026-09-01，main=9abd4cc + UX修正 adbf787）**：班组产量制 + 出勤收集并入 UG 班组 + 数据台班组图 + 豁免超管二次编辑（详见上方 §数据流水线 P30 注）；同日 UX 修正（adbf787）：用户角色下拉弃用 editor 补 collector/applicant（后端两端点拒 editor）、豁免操作明朗化（琥珀高亮+徽章+confirm）、出勤 UG 班组过滤严格化（无班组井下员工不出现）；验收证据：pytest 25 绿（19 新 + 6 旧）、同库新旧代码（3c9484c vs 9abd4cc）2026-08 逐人逐字段 0 差异、沙箱 piecework+v2 双模式端到端走查全过、浏览器三表面实测（UX 修正截图 \_work/ux-fixes/）；回滚预案=data/backups/kilwa\_before\_uxfix\_20260901\_210000.db；⚠️ 部署当晚生产 8 月总额较 17:02 基线 −133,846 TZS 系用户业务操作（员工30罚款100000→0、43 转月薪、94/LARISAIDLARI 日薪清零，audit\_log 可查），非代码回归
   1b. **P31 数据台班组化 ✅ 已部署（2026-09-02，已合入 main=2d8228e）**：数据台消费端全面适配 P30 `teams` 新格式——趋势图每班组一条线（`TEAM_COLORS` #B05A3C/#7A8B5C/#E8923E 循环，桌面/移动共享）、「班次」筛选新格式月动态替换为班组筛选（`_dashFilters.shift` 语义扩 `all|team_id`，作用面=趋势+KPI+对比卡）、白夜班对比卡新格式月改班组总产量单指标分组柱（隐藏矿石 tab 强制 total，移动端同步重置 `dnTab='all'`）、KPI 第 6 卡新格式月改班组占比卡（上下堆叠各班组线色实时 pct）、KPI 数值全站统一 `fmtK`（1 位小数+千分位）+ body `font-variant-numeric: lining-nums tabular-nums` + `--font-main` 去 Georgia、桌面图表布局自适应（`.chart-fixed-h` 固定高 300/260 + `.data-dashboard>.card{min-width:0}` + x 轴 autoSkip/maxTicksLimit 8|15 + datalabels >16 天抽样 + resizeDelay:120）、移动端 `loadDashboard` 显式 `?month=`（修切月时序错月）+ `drawTrend` 单一数据源 + labels 首末日期月份断言（console.warn）、新增 `/production-verify` teams 分支（`shift_daily[dt]=Σteams`，旧格式逐字保留；权限放宽 `salary:view OR dashboard:view`；新格式月顶层下发 `verify_days/match_days/mismatch_days`）+ 数据台底部产量核验卡（仅 `salary:view` 且新格式月渲染，chips/sticky 表格/仅看差异筛选/行点击 toast）。**红线遵守**：不改 `/api/production/dashboard`/采集 payload/`core/calculator.py`/`core/verification.py`；8 月及更早旧格式月界面与数据零改动（旧格式响应与改造前逐字段一致有 pytest 断言）。验证：pytest 9/9 绿（新格式 4+旧格式回归 2+边界 1+权限 2；P30 既有 25 例已被 TTL 清理不可执行，其保护面=计算链红线未触碰）、浏览器实测 8 月桌面+移动零改动回归、9 月合成数据全功能走查（班组筛选联动/占比 53%÷47% 复核/核验卡筛选 26→3 行/toast 明细）、1920/1440/1366 三档 31 天无横向滚动、880/560 断点高度正确、375px 无横滚。规格=docs/P31\_DASHBOARD\_TEAM\_SPEC.md（定稿 10 决策），视觉=docs/P31\_DASHBOARD\_TEAM\_PREVIEW\.html；测试 \_work/p31-dashboard-team/。**回滚：无数据迁移、无计算链触碰，回退到 P30 提交即可**
   1c. **P32 出勤采集排除已批假期 + 数据台趋势tooltip班组物料 ✅ 已部署（2026-09-02，main=2d8228e）**：①出勤收集隐藏当日已有已批假期（NU/T/SK/L）的员工——花名册 `/api/collection/roster?date=` 返回布尔 `approved_leave`（不泄薪酬），桌面+移动出勤收集表单实时守卫隐藏+不提交+编辑合并跳过+日期切换即时生效，提示条「本日已有审批通过假期 N 人，已自动隐藏」；新增超管端点 `POST /api/collection/cleanup-routed-leave`（dry\_run 默认），清理采集自动路由、与被批假期冲突的 pending 请假OA（仅 `source=collection_routing`，不误删正常申请）；生产已清理 2026-09-01/02 为 ADAM #53 自动生成的 2 条冲突 casual（audit=`oa_purge_dup_collection`）。②数据台产量趋势 tooltip：新格式按班组拆分 NH/NL/MW，仅显示有产量的物料（0 不显示；单物料筛选仍显单值）；生产实测发现并修复 `selTids` 块级作用域致新格式悬停崩溃（提升为函数级 `let`）。验证：pytest 3/3 绿、桌面/移动浏览器走查无回归、生产 9 月终验 `LAMBA LAMBA: NH 15 NL 4 MW 15`/`SAKA SAKA: MW 28`/`MIZOZO: MW 22`。关联规则：出勤采集移除 E 状态（P31 后仅井下 teams\[].exempt 表达豁免）
3. **V2 上线验收**：服务器切 `underground_mode='v2'` 前需确认班组采集数据完整（当前历史采集无 team\_id，v2 下计 0——需先按班组补录或从下月起启用）；**注意生产 settings.config 当前** **`underground_mode='scoring'`**（2026-09-01 快照确认），切 V2 前新格式班组产量在 scoring 下不计件
4. **服务器备份清理**：`data/backups/` 只留最新 1 个手动备份（部署前备份 `kilwa_before_v2_20260821_012438.db` 为当前最新）
5. **P18 遗留**（可选 backlog）：/export/employees、/export/attendance 未挂细粒度权限；PERMISSION\_CATALOG 中文硬编码待 i18n
6. **移动端真机验收**：采集班组选择器 + 出勤 E 在真机走查

