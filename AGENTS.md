# AGENTS.md — ENPRIZON LINDI (enprizon-salary)

This file provides guidance to AI coding assistants working with code in this repository.

## 协作流程

此仓库是 `KJOSONG/enprizon-salary` 的本地克隆，可以直接编辑。

```
本地修改（经批准）→ git push → 云服务器 git pull + systemctl restart
```

| 操作 | 环境 | 命令 |
|------|------|------|
| 编辑代码 | 本地 | 直接改 |
| 推送到 GitHub | 本地 | `git push` |
| 拉取+重启 | 服务器 | `ssh my-server "cd /root/enprizon-salary && git pull && systemctl restart enprizon-salary"` |

服务器端快捷别名: `save-salary "msg"` (git add -A → commit → push → restart，一步完成)。

## 数据库安全

- 数据库文件 `data/*.db` 在 .gitignore 中，不会被 git 跟踪
- **永不用 `git stash drop`**，只用 `git stash pop` (2026-06-28 因 drop 导致 kilwa.db 永久删除)
- 涉及数据库结构的修改需格外谨慎，先在服务器备份后操作
- 不要在 gunicorn 运行时修改 venv

## 环境变量

| 变量 | 用途 | 缺省 |
|------|------|------|
| `KILWA_SECRET_KEY` | Flask session 加密密钥 | 随机生成（多进程/重启需一致） |
| `KILWA_SCRIPT_NAME` | Nginx 子路径前缀（如 `/salary`） | 空 |

---

## 命令速查

### 本地开发
```bash
# 安装依赖
pip install -r requirements.txt

# 前台启动
python3 app.py
# 或: ./start.sh start

# 后台启动
./start.sh bg

# 停止
./start.sh stop
```

### 服务器运维
```bash
ssh my-server                         # SSH alias: root@47.236.187.33:22222
systemctl status enprizon-salary      # 服务状态
journalctl -u enprizon-salary -f      # 跟踪日志
systemctl restart enprizon-salary     # 重启
```

### start.sh 关键细节
- **硬编码 Python 路径**: `/Users/osong/.workbuddy/binaries/python/envs/default/bin/python3` — 修改需确认路径存在
- **端口扫描**: `stop` 命令会扫 8080-8089 端口并 `kill -9`，可能误杀其他开发服务
- **动态端口**: `get_port()` 从日志提取实际绑定端口（最多等 8 秒），默认 8081

### Gunicorn 生产配置 (`gunicorn.conf.py`)
```python
bind = '127.0.0.1:8081'    # 仅本地监听，Nginx 反向代理对外暴露
workers = 1                 # SQLite 要求单 worker（写操作串行化）
threads = 2                 # 2 线程处理并发读取
timeout = 120               # 应对长时间重算
```
日志路径 `accesslog`、`errorlog` 硬编码为 `/root/enprizon-salary/`，本地开发时需注意。

### 测试工作流 (`test-workflow.sh`)

**注意: 项目无自动化单元测试（无 `test_*.py`、`tests/` 目录），测试完全依赖以下手工测试工作流。**
通过数据库替换实现安全测试，避免污染生产数据：
```bash
cd /root/enprizon-salary
bash test-workflow.sh start    # 从备份创建 test_kilwa.db
bash test-workflow.sh swap     # 保存生产 DB → 换入测试库
# ... 在前端执行测试操作 ...
bash test-workflow.sh restore  # 恢复生产 DB
bash test-workflow.sh clean    # 删除测试库
```
**警告**: `clean` 若发现 `prod_kilwa.db` 仍存在会拒绝执行，防止误删。

### 备份与恢复 (`backup.sh`, `restore.sh`)
服务器端脚本，确保数据安全：
```bash
bash backup.sh                    # 服务器端每日备份 (自动清理 30 天前)
bash restore.sh [备份路径]         # 停服 → 恢复指定备份 → 重启
```

---

## 架构

> 详见 `ARCHITECTURE.md` 获取更完整的架构说明。

### 数据流水线
```
data/source/ (5 种文件) → scan_source_files() → _run_pipeline()
  ├── 主文件 (产量+出勤) → parser.parse_all()
  ├── 通讯录 → addressbook.parse_address_book() → namematch 索引
  ├── 预支 → advance.parse_advance()
  ├── NSSF SDL → nssf.parse_sdl_list()
  └── 破碎队 → parser.parse_crush_sheet()

全部汇聚 → calculator.calculate_all() → verification.verify_salary() → APP_STATE 缓存 → API → SPA 前端
```
`scan_source_files()` 按 Sheet 名称优先匹配，回退到文件名关键词匹配。

### 核心模块 (`core/`)

| 文件 | 职责 |
|------|------|
| `parser.py` | Excel 解析 (3 Sheet → 结构化产量/出勤数据) |
| `namematch.py` | 姓名标准化 → employee_id (通讯录账号) |
| `addressbook.py` | 通讯录 Excel (ENPRIZON_LINDI_PROJECT.xlsx) 解析 |
| `calculator.py` | 五轨薪资计算: 井下计件/钻工计件/破碎计件/日薪/月薪 + 逐日单轨合并 |
| `database.py` | SQLite ORM + 审计日志 (UTC+3), 含 10 张表 (见下方) |
| `verification.py` | 双路径核对: 产量*单价 vs 计算结果求和, \|diff\| <= 10 视为舍入误差 |
| `exceptions.py` | 例外覆盖标记 (永久/临时, JSON + DB 兼容) |
| `advance.py` | 预支数据解析 |
| `pricing.py` | 单价配置 |
| `nssf.py` | NSSF (社保) 计算 |

### 前端
- `templates/index.html` — 单页 SPA (约 2,500 行 HTML+JS)，6 个页面: 数据台 → 员工页 → 薪资页 → 出勤页 → 日工资 → 设置
- `static/css/style.css` — 深色工业主题 (1,300+ 行 CSS 变量驱动)
- `static/js/chart.umd.min.js` — Chart.js 4.4.7 (本地打包，数据台图表依赖)
- `static/js/chartjs-plugin-datalabels.min.js` — 图表示值标签插件
- `static/js/i18n.js` — 中英双语切换 (通过 `data-i18n` 属性标记翻译键, `localStorage` 持久化语言选择). 翻译键以 `t('key.path')` 形式调用, 新增翻译需同时维护 `en` 和 `zh` 两棵翻译树
- 前端通过 `authFetch()` 封装所有 API 调用，自动处理 401 重定向登录页

### 薪资计算五轨道 (calculator.py 核心)

| 轨道 | 数据源 | 逻辑 |
|------|--------|------|
| 井下计件 | shift_production | 当日产量*井下单价 / 出勤人数, 人均平分 |
| 钻工计件 | driller_production | 当日产量*钻工单价 / (队员+1队长份额), 队长*2份额 |
| 破碎计件 | CRUSH TEAM 文件 | bags * 300TZS / 有效人数, 同日多条记录独立均分 |

> **注意**: 破碎计件单价 `PRICE_CRUSH = 300` TZS/bag 在 `calculator.py` 中硬编码，与井下/钻工单价不同，**不可通过 `/config` API 修改**。
| 日薪 | attendance | 日薪基数 * 出勤天数 |
| 月薪 | monthly_salary | 月薪基数 / 26 × 实际出勤天数, >=26天封顶为满勤基薪 |

税前总额 = 井下计件 + 钻工计件 + 破碎计件 + 日薪 + 月薪
净额 = 税前总额 + 奖金 + 司机津贴 - 预支 - NSSF(税前总额*10%) - 罚款

**关键设计**: 逐日单轨模式 — 任一日期只归属一个轨道，从根本上杜绝双重计薪 bug。

### 例外覆盖系统
- `overrides` 表: start_date/end_date 均为空 → 永久覆盖; 有日期 → 临时例外 (只影响区间内)
- `attendance_overrides` 表: (employee_id, date) 联合主键, status 为 P/A/L
- 标记 A/L 的员工从当日计件分配中排除，当日总额由剩余人员平分（总额守恒）

### 出勤状态字母 (`get_attendance()` API)

| 字母 | 颜色 | 含义 |
|------|------|------|
| `D` | 蓝 | 井下白班 |
| `N` | 青 | 井下夜班 |
| `B` | 紫 | 井下全天(D+N) |
| `R` | 青绿 | 钻工计件出勤 |
| `C` | 橙 | 破碎计件出勤 |
| `P` | 绿 | 日薪/月薪出勤 |
| `A` | 红 | 旷工(手动) |
| `L` | 黄 | 请假(手动) |
| `(P)` | 灰 | 月薪默认出勤 |

点击切换逻辑: R/C → A → L → 空 → P（与 D/N 一致，不可回到原始自动值）

### 权限模型
`super_admin` > `admin` > `editor` > `viewer`
- `super_admin_required` / `admin_required` / `editor_required` / `login_required` 装饰器
- 默认账号: `user` / `qweasd` (viewer)，`KEJU` 自动升级为 super_admin

### 数据库表清单 (`database.py`)

| 表 | 说明 |
|-----|------|
| `employees` | 员工缓存 (id/name/dept/type/day_rate/monthly_salary/nssf) |
| `overrides` | 薪资例外: 永久 (无日期) / 临时 (有 start_date/end_date) |
| `attendance_overrides` | 手动出勤标记 (employee_id+date 联合 PK, status P/A/L) |
| `settings` | 系统配置 (key-value, 如定价/NSSF 费率) |
| `monthly_data` | 月度薪资快照缓存 (month+employee_id 联合 PK) |
| `audit_log` | 操作审计日志 (UTC+3 时间戳) |
| `shift_additions` | 手动补井下计件班次 (employee_id+date+shift 唯一) |
| `driller_additions` | 手动补钻工分组 (employee_id+date+captain 唯一) |
| `bonus_penalties` | 按月奖惩 (employee_id+month 联合 PK) |
| `dismissed_employees` | 离职员工追踪 |
| `admin_users` | 用户认证 (加盐 SHA256 密码) |

### 硬排除名单 (`app.py` 第 40-45 行)
以下 6 人全局不显示、不计薪（通过 `make_employee_id()` 过滤）:
ERIC WANG QM, JIMMY, SET SAIL, 宋家成（Daria）, 宋科举KEJU, 宋科举

### 启动时自动初始化
- **本地**: `auto_load_source()` 自动扫描 `data/source/` 并加载**当前月份**数据
- **Gunicorn**: 模块导入时 `_gunicorn_init()` 执行 DB 初始化 + 源文件自动加载
- `_app_initialized` 标志防止 gunicorn worker 重载时重复初始化
- `_ensure_viewer_account()` 自动创建默认 viewer + 升级 KEJU 为 super_admin

### APP_STATE 内存缓存
`app.py` 全局 `APP_STATE = {}` 字典缓存所有解析结果（解析后的数据、员工、地址簿、源信息、当前月份）。`/reload` 端点会清空并重新填充此缓存。

### 已知数据边界/特殊情况

以下场景为源数据本身的正常边界，排查 bug 时不应误判:

| # | 情况 | 说明 |
|---|------|------|
| 1 | 5/25 夜班产量无人领取 | 产量 156,000 TZS，源数据缺员工名单 → 永久路径一二差异 |
| 2 | 钻工 5/1-5 无队员 | 部分队伍仅队长 1 人 |
| 3 | 同名多槽位 | 同一队长同天多次出现 → 产量合并，成员去重 |
| 4 | 跨 Sheet 人员 | 同时出现在产量表和日薪表 → 需手动指定类型 |
| 5 | 仅预支表人员 | 通讯录外人员，仅出现在预支表中 |



---

## API 路由速览

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/login` | POST | - | 登录 |
| `/api/logout` | POST | login | 登出 |
| `/api/auth/status` | GET | - | 认证状态 |
| `/api/admin/setup` | POST | - | 首次设置 admin |
| `/api/admin/change-password` | POST | login | 修改密码 |
| `/admin/users` | GET | super_admin | 用户管理 |
| `/admin/users/role` | POST | super_admin | 修改用户角色 |
| `/source-info` | GET | login | 源文件信息 |
| `/available-months` | GET | login | 可用月份列表 |
| `/reload` | POST | admin | 重新解析源文件 |
| `/upload-source` | POST | admin | 上传源文件 |
| `/download-source/<file_type>` | GET | login | 下载源文件 |
| `/set-month` | POST | editor | 设置当前月份 |
| `/employees` | GET | login | 获取员工列表 |
| `/employees/override` | POST | editor | 保存例外覆盖 |
| `/employees/remove-override` | POST | editor | 移除永久覆盖 |
| `/employees/remove-temp-override` | POST | editor | 移除临时例外 |
| `/employees/remove-override-by-id` | POST | editor | 按 ID 移除覆盖 |
| `/employees/bonus-penalty` | POST | editor | 奖惩记录 |
| `/employees/dismissed` | GET | login | 离职员工列表 |
| `/employees/dismiss` | POST | editor | 标记离职 |
| `/employees/restore` | POST | editor | 恢复离职 |
| `/nssf/toggle` | POST | editor | 切换 NSSF |
| `/nssf/list` | GET | login | NSSF 列表 |
| `/addressbook` | GET | login | 通讯录数据 |
| `/attendance` | GET | login | 获取出勤数据 |
| `/attendance/toggle` | POST | editor | 切换 A/L 状态 |
| `/salary` | GET | login | 获取薪资结果 |
| `/salary/verify` | GET | login | 薪资核对 |
| `/production` | GET | login | 产量数据 |
| `/production-verify` | GET | login | 产量核对 |
| `/daily-wages` | GET | login | 日工资明细 |
| `/driller-captains` | GET | login | 钻工队长列表 |
| `/recalculate` | POST | editor | 重新计算 |
| `/export` / `/export/all` | POST | login | 导出 Excel (全表) |
| `/export/employees` | POST | login | 导出员工列表 |
| `/export/attendance` | GET | login | 导出出勤数据 |
| `/config` | GET/POST | GET:login / POST:admin | 系统配置 (单价等) |
| `/audit-log` | GET | login | 审计日志 |

### 统一导出报表 (`/export/all`) Sheet 结构
| # | Sheet 名 | 内容 |
|---|---------|------|
| 1 | Employee Info | 员工信息: 姓名/部门/类型/基数/预支 |
| 2 | Salary Summary | 薪资总表: 五轨道 + 奖金/罚款/NSSF/实发 |
| 3 | Attendance | 出勤网格: 彩色状态单元格 D/N/B/R/C/P/A/L |
| 4 | Daily Wages | 日工资分布: 每人每天各轨道金额 |
| 5 | Production Summary | 产量汇总: 每日 NH/NL/MW 合计 |
| 6 | Driller Verification | 钻工核对: 路径一(产量x单价) vs 路径二(实际汇���)逐日对比 |
| 7 | Driller Team Details | 钻工出勤明细: 按队长分组, 每日产量/金额/人员 |

---

## 原则

### 非侵入原则
所有非代码修改的工作（分析脚本、临时计算、报告）必须放在 `_work/` 或 `/tmp/`。不要在项目根目录留下额外文件。

### `_work/` 目录
- 已在 .gitignore 中
- 存放临时脚本、分析输出、临时文件
- 可随时安全删除
