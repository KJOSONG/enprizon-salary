# P27 月份逻辑 — 实现设计（工程侧权威）

> **定位**：本文是 P27 月份基础设施在 enprizon-salary 中的权威实现设计，基于 `docs/P27_MONTH_LOGIC_SPEC.md` 冻结规格。
>
> **分支**：`feature/month-logic-p1p2p3` → `main` 分阶段合并（P1→P2→P3 独立验证门）
>
> **最后更新**：2026-08-26（P2 as-built 已验证，16+19+4 证据齐）

---

## 1. 激活门与阶段划分

P1 为热修复（前端钳制+缓存戳+导出守卫+密钥加固），不触及全局流水线结构；P2 为会话级月份与按月缓存重构；P3 为死代码审计与归档。阶段间强依赖：P1 绿后方可进 P2，P2 绿后方可进 P3。

| 阶段 | 触及面 | 是否改流水线 |
|---|---|---|
| P1 | `templates/index.html` 周期栏与切月扇出、`app.py` 导出守卫与月戳、`gunicorn.conf.py` 密钥注释 | 否（仅钳制与守卫） |
| P2 | `app.py` `MONTH_CACHE` 与会话解析链、`templates/index.html` 请求带参、全部 12 个端点 | 是（缓存键化） |
| P3 | `app.py` 死代码清查、`ARCHITECTURE.md` 归档 | 否 |

---

## 2. P1 热修复 — 钳制与失效

### 2.1 shiftMonth 钳制（`templates/index.html:2374`）

`shiftMonth(delta)` 原为纯日历算术，无边界即 `2026-08 → +2 → 2026-10` 空月 Headless。改为以 `GET /available-months` 返回的倒序列表为权威边界：

```
clampMonth(requested, availableMonths):
  if availableMonths includes requested → requested
  else → nearest bound (min/max) 并禁用对应箭头
```

`updatePeriodBar()` 同步 `periodLabel` 与隐藏 `monthSelect`，不再覆写为客户端时钟。禁用态通过 `periodPrev/periodNext.disabled` 与样式 `opacity:0.4` 表达。

### 2.2 切月扇出与过期页面

`changeMonth(month)` 原仅刷新 4 处（数据台/薪资/员工/产量），遗漏出勤等 10 页。改为：

- 切月成功后显式作废 `STATE.attendanceData / _dailyWages / OA pending-history / scoring* / collection history / audit` 缓存
- 下一次 `showTargetPage` 以戳比对 `STATE._monthStamp !== STATE.currentMonth` 触发重取
- 失败分支不更新 `STATE.currentMonth`，避免显示与数据错位

### 2.3 出勤网格月份徽标

出勤页工具栏新增粘性徽标 `YYYY-MM`，与周期栏同源 `STATE.currentMonth`，`updatePeriodBar` 派生。Headless 为真时附加 `· 预览` 后缀。

### 2.4 导出守卫

为 4 个导出端点（`POST /export`、`POST /export/employees`、`GET /export/attendance`、`POST /export/all`）追加可选 `?month=` 守卫：

- 带参时以参数为准，不以 `APP_STATE['month']` 为准
- 参数与全局戳不一致时按 `GET /salary?month=` 同款 `deepcopy` 过滤+临时 `calculate_all` 路径重算，不静默错月
- 文件名含请求月份，`core/atten_report.py` V2 标题行保持

---

## 3. P2 会话级月份与按月缓存

### 3.1 月份解析链（as-built）

所有数据端点统一经 `resolve_month()` + `g.view_month`（before_request `inject_view_month`）解析，优先级**严格**为：

```
1) ?month= 查询参数（且通过 MONTH_RE 校验 YYYY-MM）
2) POST JSON body 的 month 字段（导出类 POST 携带，与 1 同等校验）
3) session['view_month']（登录后由 POST /set-month 写入，KILWA_SECRET_KEY 固化后跨重启不丢失）
4) MONTH_CACHE 当前最大值（按 built_at 最大的 YYYY-MM 键，过滤 __all__）
5) APP_STATE['_month_stamp'] / APP_STATE['month'][:7] 全局戳
6) EAT.now YYYY-MM（坦桑尼亚 UTC+3）
```

`POST /set-month` 仅写 `session['view_month']` 并触发 `_run_pipeline(month_filter=month)` 落对应 `MONTH_CACHE[month]`，不改其他月份缓存。`GET` 类读端点通过 `_get_month_data(month)` 按月命中或 `deepcopy` 过滤后临时 `calculate_all`，不污染全局。

### 3.2 MONTH_CACHE 结构（as-built）

```
MONTH_CACHE: dict[str, MonthData]
MonthData = { main_data, employees, salary_result, config_snapshot, headless: bool, built_at, month, parsed, calculated }
全局锁：MONTH_CACHE_LOCK（保护字典结构 + LRU）
每键锁：MONTH_CACHE_LOCKS[month] -> threading.Lock（双检构建，避免同月并发重建）
容量：LRU 保留 3 个月，_month_cache_evict_if_needed() 按 built_at 最小逐出
```

`_run_pipeline(month_filter)` 返回 `MonthData` 并原子落 `MONTH_CACHE[month_key]`（`month_key = month_filter[:7] or '__all__'`）同时同步 `APP_STATE` 别名（`month`, `_month_stamp`, `headless`, `main_data`, `employees`, `salary_result`）；`_get_month_data(month)` 先查缓存命中直接返回，未命中则尝试 `deepcopy` 过滤路径（从 `__all__` 或 `APP_STATE.main_data` 深拷贝后按月过滤 + 临时 `calculate_all`，落新缓存项带独立 `built_at`），否则全量 `_run_pipeline`。

| 写入路径 | 失效键（per-month） | 备注 |
|---|---|---|
| `POST /api/collection/submit` | `submission_date[:7]` | `_invalidate_month_cache(date[:7])` |
| `POST /api/collection/edit` | `old_date[:7]` + `new_date[:7]` | 覆盖合并时双键 |
| `POST /attendance/toggle` | `date[:7] or g.view_month` |  |
| `POST /employees/override` | `effective_from or start_date[:7] or g.view_month` | 永久/临时区分 |
| `POST /employees/remove-override*` / `remove-temp-override` / `remove-override-by-id` | `g.view_month` 或行 `effective_from/start_date` | 按行解析 |
| `POST /employees/bonus-penalty` | `body month[:7]` |  |
| `POST /api/salary/inline-edit` | `month[:7]` |  |
| `POST /recalculate` | `g.view_month` 单键重建 | per-month 重算，非全清 |
| `POST /reload` | 全量清空 `MONTH_CACHE.clear()` | 唯一全清路径 |
| `POST /config` | 全量 `config_snapshot` 原地更新（不逐出） |  |

> **不变量**：任一写操作仅驱逐受影响月份，其余月份保持命中；`deepcopy` 隔离保证 `Aug篡改不染Jul`（已由 16 例单测覆盖）。

### 3.3 Headless 派生

原 `APP_STATE['headless']` 全局标志改为按月派生：`not bool(filtered_main_data['dates'])`。缓存内 `MonthData.headless` 随对应月份存储，响应中按解析月返回。

---

## 4. 涉及文件清单（P1→P2）

| 文件 | 阶段 | 变更 |
|---|---|---|
| `app.py:17,730,927,1046,1115,1188,2374` | P1+P2 | 密钥加固、`_month_stamp`、`MONTH_CACHE`、`resolve_month`、`_get_month_data`、导出守卫 |
| `templates/index.html:104,158,2374,3102,3124,5312` | P1+P2 | 周期栏钳制、`populateMonthSelect` 幂等、切月扇出、徽标 |
| `core/atten_report.py` | P1 | 已在 31364c1 完成 V2 标题行+自适应宽度，本阶段仅接入月参 |
| `gunicorn.conf.py` | P1 | 密钥必填注释 |
| `core/calculator.py` | P2 | 复用 `GET /salary?month=` 深拷贝路径，不改公式 |
| `templates/mobile.html:401` | P2 | 同会话解析链 |

---

## 5. 缓存与会话不变量

- `KILWA_SECRET_KEY` 持久化后，`session['view_month']` 跨重启不丢失；未配置则每次重启会话整体失效（与 `AGENTS.md` 会话章节一致）。
- `MONTH_CACHE` 键为 `YYYY-MM` 前缀匹配，与 `available-months` 5 类来源一致。
- `calculate_all` 与 `verify_salary` 逐日单轨合并结果按月缓存，主从一致。

---

## 6. 验证设计

### 6.1 P1 门（`_work/month-logic/verify_p1.sh`）

- 单测：`clampMonth(requested, availableMonths)` 4 例（越界上下、命中、空表）
- 单测：导出守卫错月 409 或重算正确
- 单测：密钥必填/固化
- curl：`/available-months` 边界、`GET /export/attendance?month=2026-08` 文件名含月、`/salary?month=` 深拷贝
- 浏览器：周期栏连点 `»»` 不进空 Headless；切月后出勤网格无 F5 即刷新；V2 出勤导出标题合并仍在

### 6.2 P2 门（`_work/month-logic/verify_p2.sh`）— as-built 2026-08-26

| 层 | 文件 | 规模 | 断言 |
|---|---|---|---|
| 单测 | `_work/month-logic/test_p2_session_cache.py` | **16 例** | cache hit/miss 4（命中同一性/隔离/不同对象/LRU=3）、session 优先级 4（?month>session>global、session>global、全局回退、POST body 覆盖）、端点参透 4（/salary、/production、/attendance、export 显式月无视会话）、失效 4（attendance toggle 仅目标月、collection submit 仅 payload 月、bonus-penalty 仅目标月、reload 全清） |
| curl | `_work/month-logic/verify_p2_curl.sh` | **19 断言** | 双罐登录分离（KEJU 各自会话）、`POST /set-month` 分设 2026-08/07 后 `GET /salary` 无参分流、并发 `GET /salary?month=2026-07` vs `?month=2026-08` 双向分流且 gross/headless 分叉、导出显式月 5 种（salary/attendance/POST body）均覆盖会话、toggle 2026-07-15 仅逐出 Jul 且双罐对 Aug 仍一致、回滚后会话仍隔离 |
| 浏览器 | `_work/month-logic/p2_playwright.py` → `p2_evidence/` | **4 张** | 双 `BrowserContext` 并发登录（A 2026-08 / B 2026-07）→ `01_a_aug_initial.png` vs `01_b_jul_initial.png` 显示不同 gross（21605114 vs 6718846）与 period 徽标；A 切 2026-08-15 后 `02_a_aug_after_toggle.png` 与 `02_b_jul_stable.png` 证明 B 的 2026-07 视图稳定无 clobber；覆盖 `README.md` 说明 |

合并阈值：`./verify_p2.sh` 一键串行 `pytest -v` + `verify_p2_curl.sh` + `p2_playwright.py`，任一非 0 即红。

---

## 7. 死代码与收尾（P3）

审计 `scan_source_files` / `parser.parse_all` / `advance.py` 等遗留；`_build_attendance_grid` 保持出勤网格与导出唯一源；`resolve_month` 归一；`ARCHITECTURE.md` 补充月份解析链与缓存键不变量。

> **P3 变更原则**：不做模块拆分，仅在 `app.py` 内归一与 `core/parser.py` / `core/advance.py` 原地标注；`data/source` 空目录保留（gitignored 种子回退用）。

---

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 密钥随机导致会话丢失 | P1 即加固，P2 会话测试含重启断言 |
| 导出错月 | P1 守卫 409/重算，不静默错月 |
| 缓存跨月污染 | 每月深拷贝隔离，写后按月失效 |
| 合成月误触 | 周期栏钳制+禁用态+预览后缀 |

回滚：`main` 为稳定点，`git pull origin main && systemctl restart enprizon-salary`。

---

## Appendix A — 死代码与重复逻辑审计（P3 as-built 2026-08-26）

> **审计方式**：`grep -rn "parse_all|scan_source_files|advance\.py|_get_requested_month|_month_stamp|_build_attendance_grid|APP_STATE\[" app.py core/*.py` + 人工核对调用图；**不直接删除未列项先留表**，被标 `REMOVE` 的项在同次提交内清理，避免半成品。

| # | 位置 | 符号 | 结论 | 依据与处置 |
|---|---|---|---|---|
| 1 | `app.py:92` | `SOURCE_DIR = data/source` | **KEEP（deprecate）** | 纯采集 Excel 已移除，空目录仅 `seed_new_tables_from_excel()` 首次种子回退用；保留常量与 `os.makedirs`，注释 `DEPRECATED: 纯采集模式已移除 Excel 源，仅种子回退保留`，不新增调用 |
| 2 | `app.py:93` | `OVERRIDES_FILE = data/overrides.json` | **REMOVE** | JSON 覆盖已迁移至 `overrides` 表（`core/database.py:736 _migrate_json`），无读方；保留会误导，删常量定义 |
| 3 | `app.py:782` | `os.makedirs(SOURCE_DIR)` | **KEEP（deprecate）** | 与 #1 同根，避免种子路径不存在；保留但标注 deprecated |
| 4 | `app.py:861` | `_get_requested_month()` | **KEEP（DEPRECATE shim）** | 重复 `resolve_month` 的 `?month=` + `JSON month` 解析；原 0 业务调用但 P1 测试依赖，P3 保留为薄包装 `return resolve_month(request)`，逻辑归一至 `resolve_month`，标注 DEPRECATED |
| 5 | `app.py:919` | `_resolve_export_month_data()` | **KEEP（DEPRECATE shim）** | 历史 lenient `deepcopy` 过滤 + `calculate_all` 路径与 `_get_month_data()` 快路径重复；导出已统一走 `resolve_month` + `_get_month_data`，P1 测试依赖，P3 保留为隔离 deep-copy 实现（不污染全局 `APP_STATE`），标注 DEPRECATED |
| 6 | `app.py:964` | `_build_attendance_grid_for_month()` | **REMOVE（consolidate）** | 130 行与 `_build_attendance_grid()` 逐日推导逻辑逐行重复；改为薄包装 `_build_attendance_grid(_md, _emps)` 代理，`_build_attendance_grid` 为唯一真源 |
| 7 | `app.py:4590` | `export_attendance()` 内联 attendance 构建 | **REMOVE（consolidate）** | 与 `_build_attendance_grid()` 的 `shift/driller/attendance/crush/manual` 推导重复；改为 `grid = _build_attendance_grid(mdw.main_data, mdw.employees)` 取 `dates/rows`，仅保留 Excel 着色与列宽逻辑 |
| 8 | `core/parser.py:328` | `parse_all()` | **DEPRECATE** | 主 Excel 解析入口，无调用方（`scan_source_files` + `parser.parse_all` 已在纯采集改造中移除，仅注释中提及）；保留文件但头部加 `DEPRECATED` docstring，标注“纯采集模式已移除，历史归档勿删” |
| 9 | `core/parser.py:98,198,263` | `parse_piece_rate_sheet` / `parse_daily_salary_sheet` / `parse_crush_sheet` | **DEPRECATE** | 同 #8 子函数，仅被 `parse_all` 调用；随 #8 同标注，不删代码便于追溯 |
| 10 | `core/parser.py:12-92` | `_norm_hdr` / `_build_col_map` / `_get_col` / `_find_driller_teams` / `_normalize_crush_date` / `parse_prod_string` | **DEPRECATE** | 仅服务 #9 的表头/产量辅助，无外部调用（grep 0）；随 #8 同标注 |
| 11 | `core/advance.py` | `parse_advance()` 全模块 | **DEPRECATE** | Excel 预支解析，数据源已改为 `bonus_penalties.advance` 月度手动项（P29-c）；0 调用方；文件保留但头部加 `DEPRECATED` 说明，不删以防审计追溯 |
| 12 | `data/source/` | 空目录（gitignored） | **KEEP** | 纯采集模式不再扫描 `data/source`（AGENTS.md 已载“已清空”），但保留空目录 + `.gitkeep` 语义；禁止散落 `*.xlsx`，种子回退期后可考虑移除 |
| 13 | `app.py:877` | `_month_stamp()` | **KEEP（internal）** | `APP_STATE['_month_stamp']` 薄包装，仅供 `resolve_month` 回退链第 5 级与导出 `EXPORT_STRICT_MONTH` 守卫读取；不对外暴露，与 `resolve_month` 不重复（职责：读全局戳 vs 解析请求月） |
| 14 | `app.py:888` | `resolve_month()` | **KEEP（single source of truth）** | 唯一月份解析器（`?month` > `JSON body` > `session['view_month']` > `MONTH_CACHE` > `_month_stamp` > `EAT.now`）；全部 12 读取端点已接入，`g.view_month` 由 `before_request inject_view_month` 注入 |
| 15 | `app.py:4205` | `_build_attendance_grid(md, employees)` | **KEEP（single source of truth）** | 出勤网格唯一真源；`GET /attendance` + `GET /export/attendance-report` 已复用，P3 后 `GET /export/attendance` 亦改此源；月参通过 `_get_month_data(month)` 取得 `main_data/employees` 传入，不再内联推导 |
| 16 | `app.py:2006,3139,3663...` | `APP_STATE` 直接读（非月份） | **KEEP** | `salary_result` / `employees` / `main_data` / `config` 等缓存读仍合法；月份相关读已收敛至 `resolve_month`/`g.view_month`/`_get_month_data`，`grep -rn "APP_STATE\[.month"` 仅剩 `inject_view_month` 回退与 `dismiss/restore` 等内部同步，不新增 |

> **验证**：`grep -rn "parse_all\|scan_source_files"` 仅剩 `parse_all` 定义与 `ARCHITECTURE.md` 历史描述，无活跃调用；`pytest _work/month-logic/test_p1_month_logic.py _work/month-logic/test_p2_session_cache.py` 绿；`GET /export/attendance?month=2026-08` 与 `GET /export/attendance-report?month=` 手工比对 `dates/rows` 与 API 一致。

---

*生成日期 2026-08-26 ｜ 工程侧权威，与 `docs/P27_MONTH_LOGIC_SPEC.md` 配套，P1/P2/P3 分阶段落地（P3 审计表见 Appendix A）*
