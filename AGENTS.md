# AGENTS.md — ENPRIZON LINDI (enprizon-salary)

薪资计算系统。上传 Excel → 五轨解析 → SPA 前端展示。部署在阿里云新加坡 (47.236.187.33)。

## 协作流程

本地修改 → `git push` → 服务器 `git pull && systemctl restart enprizon-salary`
服务器快捷别名: `save-salary "msg"`（git add -A → commit → push → restart 一步完成）

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
项目无 `test_*.py` 或 `tests/` 目录。手工测试通过数据库替换实现：
```bash
cd /root/enprizon-salary
bash test-workflow.sh start       # 备份 → test_kilwa.db
bash test-workflow.sh swap        # 保存生产库 → 换入测试库
# ... 在前端执行测试操作 ...
bash test-workflow.sh restore     # 恢复生产库
bash test-workflow.sh clean       # 删除测试库（`prod_kilwa.db` 存在时拒绝，防止误删）
```
`test-workflow.sh` 使用 `$HOME/WorkBuddy/kilwa-system/data` 和 `$HOME/Desktop/enprizon_backups` 路径。

### 备份与恢复（服务器端）
```bash
bash backup.sh                    # 每日备份，自动清理 30 天前
bash restore.sh [备份路径]         # 停服 → 恢复 → 重启
```

## Gunicorn 生产配置（`gunicorn.conf.py`）

`workers=1`（SQLite 要求单 worker），`threads=2`，`timeout=120`。
日志路径硬编码为 `/root/enprizon-salary/`，本地开发会失败。

## 启动初始化

- **本地** `python3 app.py`：`init_db()` + `_migrate_json()`（旧 JSON 一次性迁移）+ `auto_load_source()`（扫描 `data/source/` 加载当前月份）
- **Gunicorn**：`_gunicorn_init()` 通过 `_app_initialized` 标志防止重复初始化
- `_ensure_viewer_account()` 自动创建默认 viewer 账号 + 升级 KEJU 为 super_admin
- `_migrate_json()` 仅在 `overrides` 表为空时运行一次（检测到有数据则跳过）
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
文件匹配：按 Sheet 名优先，回退到文件名关键词。未匹配通讯录的姓名走旧格式（去空格大写）。

### 薪资五轨道（`calculator.py`）

| 轨道 | 数据源 | 逻辑 |
|------|--------|------|
| 井下计件 | shift_production（D/N 班） | 当日产量 × 井下单价 / 出勤人数，人均平分 |
| 钻工计件 | driller_production（队长制） | 当日产量 × 钻工单价 /（队员+1 队长份额），队长×2 份额 |
| 破碎计件 | CRUSH TEAM 文件 | bags × 300 / 有效人数，同日多条记录独立均分 |
| 日薪 | attendance | 日薪基数 × 出勤天数 |
| 月薪 | employees.monthly_salary | 基数 / 26 × 实出勤，≥26 天封顶满薪 |

**单轨模式**：任一日期只归属一个轨道，杜绝双重计薪。

税前总额 = 井下 + 钻工 + 破碎 + 日薪 + 月薪
净额 = 税前 + 奖金 + 司机津贴 - 预支 - NSSF(10%) - 罚款

### 定价机制（非显而易见）

三个价格常量 `PRICES_UNDERGROUND`、`PRICES_DRILLER`、`PRICE_CRUSH`（300）在 `calculator.py` 顶部硬编码。但每次 `calculate_all()` 从 DB config 读取并**全局猴子补丁覆盖**模块变量，结束后恢复。`/config` API 可修改 `crush_price` → 下次计算生效。**硬编码常量 ≠ 不可修改**。

### 例外覆盖

- `overrides` 表：`start_date`/`end_date` 都空 → 永久覆盖（改变整月类型）；有日期 → 临时例外（仅影响区间）
- `attendance_overrides` 表：(employee_id, date) 联合 PK，status P/A/L
- 标记 A/L 的员工从当日计件分配排除，总额守恒（剩余人员平分）

### 出勤状态字母

D(蓝)=井下白班, N(青)=井下夜班, B(紫)=D+N, R(青绿)=钻工, C(橙)=破碎, P(绿)=日薪/月薪, A(红)=旷工, L(黄)=请假, (P)(灰)=月薪默认

点按切换：R/C → A → L → 空 → P（不可回到原始自动值）

### 前端技术栈

- **单文件 SPA**：`templates/index.html`（~128KB），所有 JS 内联在 `<script>` 标签中，无独立 JS 模块或构建系统
- **6 个页面标签**：数据台（Dashboard） / 员工管理 / 出勤网格 / 薪资总表（含核对面板） / 日工资明细 / 系统配置（含审计日志、上传、定价、权限管理）
- **国际化 (i18n)**：`static/js/i18n.js`（~864 lines）支持中英文即时切换，通过 `data-i18n` / `data-i18n-placeholder` / `data-i18n-html` 属性驱动，语言偏好存 `localStorage.kilwa_lang`，切换后自动刷新当前页面渲染
- **图表**：Chart.js v4.4.7 + chartjs-plugin-datalabels，用于数据台产量趋势图和日工资分布图
- **状态管理**：全局 `STATE` 对象缓存当前页数据，`recalculate()` 后自动刷新薪资/出勤/日工资相关页面
- **暗系工业风 UI**：`static/css/style.css`（~1338 lines），CNPC 主题色系

### 导出系统

| 端点 | 输出 | 需认证 | 说明 |
|------|------|--------|------|
| `POST /export` | Excel 3 Sheet | editor+ | 薪资总表 + 核对 + 日明细 |
| `POST /export/employees` | Excel | editor+ | 员工花名册（类型/NSSF/奖惩） |
| `GET /export/attendance` | Excel | editor+ | 出勤网格导出 |
| `POST /export/all` | Excel 7 Sheet | editor+ | 英文版统一导出（员工信息+薪资+出勤+日工资+产量+钻工核对+钻工明细） |

### 司机津贴

`_apply_driver_allowance()` — 部门名含"司机"或岗位含 "driver" 的员工，自动加 5,000 TZS/天 × 出勤天数津贴，合入净额计算。

### 权限模型

`super_admin` > `admin` > `editor` > `viewer`。默认账号 `user/qweasd`（viewer），`KEJU` 自动升 super_admin。

### 数据库 11 张表

| 表 | 说明 |
|-----|------|
| `employees` | 员工缓存（id/name/dept/type/day_rate/monthly_salary/nssf） |
| `overrides` | 薪资例外：永久/临时 |
| `attendance_overrides` | 手动出勤标记 P/A/L |
| `settings` | 系统配置 key-value（定价、NSSF 费率） |
| `monthly_data` | 月度薪资快照缓存 |
| `audit_log` | 操作审计（强制 UTC+3） |
| `shift_additions` | 手动补井下计件班次 |
| `driller_additions` | 手动补钻工分组 |
| `bonus_penalties` | 月度奖惩 |
| `dismissed_employees` | 离职追踪 |
| `admin_users` | 用户认证（加盐 SHA256） |

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

### 后端模块（`core/` 10 个文件）

| 文件 | 职责 |
|------|------|
| `app.py` | Flask 路由 + 认证 + 会话 + 数据管线编排（~2458 lines, 41 个 API 端点） |
| `core/calculator.py` | 五轨计算 + 逐日单轨合并 + 日工资明细（~1221 lines） |
| `core/parser.py` | Excel 解析（表头扫描驱动，产量/日薪/破碎 3 个解析函数） |
| `core/namematch.py` | 姓名标准化 + employee_id 生成 + 员工主列表 |
| `core/database.py` | SQLite ORM（11 张表）+ 审计日志（~623 lines） |
| `core/verification.py` | 双路径核对（产量×单价 vs 实际分配，|diff|≤10 视为舍入） |
| `core/addressbook.py` | 通讯录 Excel 解析 |
| `core/advance.py` | 预支数据解析 |
| `core/nssf.py` | NSSF SDL 社保名单解析 |
| `core/pricing.py` | 单价配置代理（模块常量） |
| `core/exceptions.py` | 例外覆盖标记加载（兼容 JSON + DB） |

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

### 前端文件

| 文件 | 职责 |
|------|------|
| `templates/index.html` | 单页 SPA（~128KB, ~2488 lines，6 页面标签，全部 JS 内联） |
| `static/css/style.css` | 暗系工业风 UI 主题（~1338 lines） |
| `static/js/i18n.js` | 中英文翻译字典（760+ 键）+ 运行时切换引擎 |
| `static/js/chart.umd.min.js` | Chart.js v4.4.7 |
| `static/js/chartjs-plugin-datalabels.min.js` | 图表数据标签插件 |

### 运维脚本

| 文件 | 用途 |
|------|------|
| `start.sh` | 本地开发启动（Python 路径硬编码） |
| `backup.sh` | 服务器每日备份 kilwa.db，30 天自动清理 |
| `restore.sh` | 服务器停服→恢复→重启 |
| `test-workflow.sh` | 测试库安全隔离（start/swap/restore/clean） |
| `gunicorn.conf.py` | 生产配置（127.0.0.1:8081, 1 worker, 2 threads, 120s timeout） |

## 原则

- 临时分析脚本、报告放在 `_work/`（已 gitignore，可随时删除）
