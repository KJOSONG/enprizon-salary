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

---

## 架构

### 数据流水线
```
Excel 输入 → parser.py → namematch.py → calculator.py → app.py (API) → 前端 SPA
                   │              │
             通讯录索引查找   employee_id 生成（通讯录账号, 如 111, 128, 005）
```

### 核心模块 (`core/`)

| 文件 | 职责 |
|------|------|
| `parser.py` | Excel 解析 (3 Sheet → 结构化产量/出勤数据) |
| `namematch.py` | 姓名标准化 → employee_id (通讯录账号) |
| `addressbook.py` | 通讯录 Excel (ENPRIZON_LINDI_PROJECT.xlsx) 解析 |
| `calculator.py` | 四轨薪资计算: 井下计件/钻工计件/日薪/月薪 + 逐日单轨合并 |
| `database.py` | SQLite ORM + 审计日志 (UTC+3) |
| `verification.py` | 双路径核对 (产量*单价 vs 计算结果求和) |
| `exceptions.py` | 例外覆盖标记 (永久/临时, JSON + DB 兼容) |
| `advance.py` | 预支数据解析 |
| `pricing.py` | 单价配置 |
| `nssf.py` | NSSF (社保) 计算 |

### 前端
- `templates/index.html` — 单页 SPA (约 6000 行 JS)，三页面联动: 员工页 → 出勤页 → 薪资页
- `static/` — CSS/JS 静态资源

### 四轨薪资计算 (calculator.py 核心)

| 轨道 | 数据源 | 逻辑 |
|------|--------|------|
| 井下计件 | shift_production | 当日产量*单价 / 出勤人数, 人均平分 |
| 钻工计件 | driller_production | 当日产量*单价 / (队员+1队长份额), 队长*2份额 |
| 日薪 | attendance | 日薪基数 * 出勤天数 |
| 月薪 | monthly_salary | 月薪基数 - A/L天数比例扣减 |

**关键设计**: 逐日单轨模式 — 任一日期只归属一个轨道，从根本上杜绝双重计薪 bug。

### 例外覆盖系统
- `overrides` 表: start_date/end_date 均为空 → 永久覆盖; 有日期 → 临时例外 (只影响区间内)
- `attendance_overrides` 表: (employee_id, date) 联合主键, status 为 P/A/L
- 标记 A/L 的员工从当日计件分配中排除，当日总额由剩余人员平分（总额守恒）

### 权限模型
`super_admin` > `admin` > `editor` > `viewer`
- `super_admin_required` / `admin_required` / `editor_required` / `login_required` 装饰器

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
所��非代码修改的工作（分析脚本、临时计算、报告）必须放在 `_work/` 或 `/tmp/`。不要在项目根目录留下额外文件。

### `_work/` 目录
- 已在 .gitignore 中
- 存放临时脚本、分析输出、临时文件
- 可随时安全删除
