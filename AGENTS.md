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

### 测试工作流 (`test-workflow.sh`)
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

---

## 架构

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
| `calculator.py` | 四轨薪资计算: 井下计件/钻工计件/日薪/月薪 + 逐日单轨合并 |
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
- `static/js/i18n.js` — 中英双语切换 (通过 `data-i18n` 属性标记翻译键)
- 前端通过 `authFetch()` 封装所有 API 调用，自动处理 401 重定向登录页

### 薪资计算五轨道 (calculator.py 核心)

| 轨道 | 数据源 | 逻辑 |
|------|--------|------|
| 井下计件 | shift_production | 当日产量*井下单价 / 出勤人数, 人均平分 |
| 钻工计件 | driller_production | 当日产量*钻工单价 / (队员+1队长份额), 队长*2份额 |
| 破碎计件 | CRUSH TEAM 文件 | bags * 300TZS / 有效人数, 同日多条记录独立均分 |
| 日薪 | attendance | 日薪基数 * 出勤天数 |
| 月薪 | monthly_salary | 月薪基数 - A/L天数比例扣减 |

税前总额 = 井下计件 + 钻工计件 + 破碎计件 + 日薪 + 月薪
净额 = 税前总额 + 奖金 - 预支 - NSSF(税前总额*10%) - 罚款

**关键设计**: 逐日单轨模式 — 任一日期只归属一个轨道，从根本上杜绝双重计薪 bug。

### 例外覆盖系统
- `overrides` 表: start_date/end_date 均为空 → 永久覆盖; 有日期 → 临时例外 (只影响区间内)
- `attendance_overrides` 表: (employee_id, date) 联合主键, status 为 P/A/L
- 标记 A/L 的员工从当日计件分配中排除，当日总额由剩余人员平分（总额守恒）

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



---

## API 路由速览

| 路由 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/login` | POST | - | 登录 |
| `/api/auth/status` | GET | - | 认证状态 |
| `/api/admin/setup` | POST | - | 首次设置 admin |
| `/admin/users` | GET | super_admin | 用户管理 |
| `/source-info` | GET | login | 源文件信息 |
| `/reload` | POST | super_admin | 重新解析源文件 |
| `/upload-source` | POST | super_admin | 上传源文件 |
| `/set-month` | POST | super_admin | 设置当前月份 |
| `/employees` | GET | login | 获取员工列表 |
| `/employees/override` | POST | editor | 保存例外覆盖 |
| `/employees/remove-override` | POST | editor | 移除永久覆盖 |
| `/employees/remove-temp-override` | POST | editor | 移除临时例外 |
| `/employees/bonus-penalty` | POST | editor | 奖惩记录 |
| `/nssf/toggle` | POST | editor | 切换 NSSF |
| `/attendance` | GET | login | 获取出勤数据 |
| `/attendance/toggle` | POST | editor | 切换 A/L 状态 |
| `/salary` | GET | login | 获取薪资结果 |
| `/salary/verify` | GET | login | 薪资核对 |
| `/daily-wages` | GET | login | 日工资明细 |
| `/recalculate` | POST | editor | 重新计算 |
| `/export` / `/export/all` | POST | login | 导出 Excel |
| `/config` | GET/POST | admin | 系统配置 (单价等) |
| `/audit-log` | GET | login | 审计日志 |

---

## 原则

### 非侵入原则
所有非代码修改的工作（分析脚本、临时计算、报告）必须放在 `_work/` 或 `/tmp/`。不要在项目根目录留下额外文件。

### `_work/` 目录
- 已在 .gitignore 中
- 存放临时脚本、分析输出、临时文件
- 可随时安全删除
