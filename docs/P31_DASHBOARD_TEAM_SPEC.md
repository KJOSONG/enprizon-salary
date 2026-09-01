# P31 数据台班组化改造 — 执行规格（Work Plan）

> 状态：定稿，可直接执行 · 2026-09-02
> 视觉定稿参照：`docs/P31_DASHBOARD_TEAM_PREVIEW.html`（评审通过的高保真预览，视觉细节以它为准）
> 格式分支铁律：消费端按"rec 含 `teams` 键 = 新格式 / 含 `day_prod` = 旧格式"分流；**8 月及更早旧格式月界面与数据零改动**

## TL;DR (For humans)

数据台消费端全面适配 P30 班组产量制（`teams` 新格式）：趋势图从 NH/NL/MW 三线改为**每班组一条线**；「班次」筛选动态替换为**班组筛选**；「白班 vs 夜班」对比卡改为**班组总产量对比**（仅 total，无矿石 tab）；`/production-verify` 产量核验加 `teams` 格式分支并以新卡并入数据台；桌面趋势图修复横向扩张（grid `min-width:0` + 固定高容器 + 刻度/标签自适应）；移动端修 month 传参时序错月与 labels 双来源错位。**全页数字统一 lining+tabular**（去 Georgia oldstyle）。

**为什么**：9 月起采集 payload 为班组制（无 day/night 维度），现有消费端按 `total_*` 前缀取值 → 9 月趋势三线恒 0、班次控件失效、核验 API 恒 0。后端 `/api/production/dashboard`（app.py ~L4311）已返回逐日 `teams:[{team_id,team_name,nh,nl,mw,total}]`，无需改动，纯消费端适配 + 核验端点分支。

**不会做什么**：不改 `/api/production/dashboard`、不改采集 payload 与 `core/calculator.py`/`core/verification.py` 计算链、不做移动端核验卡（后续可选）、旧格式月（2026-08 及更早）界面零改动。

**工作量**：5 Phase（A 后端+测试先行 → B 桌面班组化 → C 桌面自适应 → D 移动端 → E 核验卡+i18n+回归）。

**分支**：`feature/p31-dashboard-team`（6 需求跨多模块，按 DEV_WORKFLOW §2 走 feature 分支，不碰 main）。

---

## Scope

### In scope
- `app.py` `/production-verify`（~L4396）：`teams`/`day_prod` 格式分支 + 权限放宽（`salary:view` OR `dashboard:view`）+ 顶层汇总字段。
- `templates/index.html` 数据台：班组筛选控件（动态生成）、趋势图班组线分流、对比卡 total-only、核验卡、`getProdValue` 新格式修正。
- `static/css/style.css`：`.data-dashboard > .card { min-width:0 }`、`.chart-fixed-h` 高度体系、核验卡样式、全局数字排版。
- `templates/mobile.html`：`loadDashboard` 显式 `?month=`、`drawTrend` 重写（班组线+单一数据源）、`drawDayNight` dnTab 重置。
- `static/js/i18n.js`：新增 zh+en key（清单见 Phase E）。
- `tests/`：`/production-verify` 新格式 pytest + 旧格式逐字段回归断言。
- `AGENTS.md`：P31 完成后追加条目（同 P30 格式）。

### Out of scope (Must-NOT-Have)
- 不改 `/api/production/dashboard`（已返回逐日 teams 数组，直接消费）。
- 不改采集 payload、`core/calculator.py`、`core/verification.py` 计算链（P30 红线：8 月薪资 0 差异）。
- 不改旧格式月的任何渲染路径（`isNewDashFormat()` / `sp.some(s=>s.teams)` 为 false 时逐字走原逻辑）。
- 不做移动端核验卡、不做周公示/导出适配。
- 不新建任何数据库表/字段。

---

## 已定稿决策（不再询问，照此实现）

1. **格式分支铁律**：一律按"rec 含 `teams` 键=新格式 / 含 `day_prod`=旧格式"分流（同 P30 消费端原则）。
2. **班组筛选作用面** = 趋势图 + KPI + 对比卡（与旧"班次"筛选作用面一致）；旧格式月控件原样。
3. **趋势图新格式** = 每班组一条线；矿石筛选≠全部时线值取 `tm[ore]`，否则 `tm.total`；旧格式 = 现状 NH/NL/MW 三线 + 白夜班 tooltip 不动。
4. **对比卡新格式** = 班组总产量单指标分组柱，隐藏矿石 tab 且强制 `dayNightOre='total'`；移动端同时重置 `STATE.dnTab='all'`。
5. **核验卡位置** = 数据台底部（破碎产量卡之后）全宽；仅 `hasPermission('salary','view')` 用户请求并渲染。
6. **核验口径** = 钻工逐日合计 vs Σ班组 teams 逐日合计；差值 = 钻工合计 − 井下合计；卡内注明口径文案。
7. **数字排版规范（全站）**：`body { font-variant-numeric: lining-nums tabular-nums; }`；`--font-main` 去掉 Georgia（其数字为 oldstyle 且不支持 lnum），改为 `'Fraunces', 'Times New Roman', ui-serif, serif`。KPI 数值固定 1 位小数+千分位（`minimumFractionDigits:1, maximumFractionDigits:1`）。
8. **KPI 第 6 卡（新格式月）**：删除「2 班组/班组汇总」；只显示各班组占比，**上下堆叠**（不横排），每班组用各自线色，占比由当月数据实时计算（`teamTotal/Σtotal` 四舍五入取整%），卡片内容垂直居中。
9. **班组线色 `TEAM_COLORS`**：`#B05A3C`（暖陶土）、`#7A8B5C`（金橄榄）、`#E8923E`（琥珀，第 3 备用），循环取色；桌面/移动共享同一常量；`team_name` 缺失回退 `班组 {team_id}`。
10. **月份断言**（移动端）：趋势图重绘后校验 labels 首末日期属于 `STATE.currentMonth`，否则 `console.warn`。

## 前端视觉规格（预览定稿，照抄实现）

- **固定高容器**：`.chart-fixed-h { position:relative; width:100%; height:300px }`，副图 `.h260 { height:260px }`；`@media(max-width:900px)` 240/200；`@media(max-width:600px)` 200/180。数据台 4 张图 canvas 全部包入，移除 `height="280"` 属性依赖。
- **grid 收缩**：`.data-dashboard > .card { min-width: 0; }`（4 图卡 + KPI 全生效）。
- **x 轴自适应**：`ticks:{ autoSkip:true, maxRotation:0, maxTicksLimit: isSmallScreen()?8:15 }`。
- **datalabels 抽样**：天数 >16 时按 `Math.ceil(n/16)` 步长抽样显示，仅显示值 >0 的点；字号 9、`anchor:'end', align:'top'`。
- **`resizeDelay: 120`**。
- **核验卡结构**：标题行（`产量核验` + 口径 note + 右侧 segmented `全部/仅看差异`）→ 摘要 chips（`核验 N 天` / `✓ 一致 N 天` success-bg / `▲ 差异 N 天` warning-bg）→ 表格（sticky 表头，`max-height:320px` 滚动；列：日期/钻工组/钻工合计/井下合计/差值/状态徽章；差异行 warning 5% 底色、差值列加粗琥珀）→ 行点击 toast 显示当日各钻工组明细。徽章文字色用 `color-mix(in srgb, 状态色 60-65%, foreground)` 保证 ≥4.5:1。
- **KPI 数字**：`fmtK = toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})`；第 6 卡百分比行 `font-size:15px; font-weight:600; display:flex; flex-direction:column; gap:3px`。

---

## 实现任务

### Phase A — 后端核验分支 + 测试（先行，独立可测）
- [ ] A1 `app.py /production-verify`：`shift_prod` 循环加 `teams` 分支（新格式 `shift_daily[dt] = Σ teams(nh/nl/mw)`），旧格式逻辑逐字保留；权限装饰器改为 `salary:view` OR `dashboard:view`（沿用 P29 多权限写法）。
- [ ] A2 响应顶层加 `verify_days/match_days/mismatch_days`（保留既有逐日结构不变）。
- [ ] A3 pytest：新格式 fixture（teams 一日一条）断言 shift_total/match；旧格式 fixture 断言响应与改造前逐字段一致。**门禁：既有 25 例全绿 + 新增全绿。**

### Phase B — 桌面班组化（index.html）
- [ ] B1 `initDashControls`：新格式月隐藏 `dashShiftToggle` 原三钮、渲染动态班组 segmented（全部 + 当月出现过的班组，`data-value=team_id`），label i18n `dash_shift`→`dash_team_filter`；旧格式月原样。`STATE._dashFilters.shift` 语义扩为 `'all'|team_id`。
- [ ] B2 `renderProductionTrend`：按 `isNewDashFormat()` 分流——新格式 `datasets` = 选中班组（或全部）每日 total（或 `tm[ore]`），线色 `TEAM_COLORS`，图例班组名；tooltip 逐班组值；onClick `showDayDetailPopup` 不动。**同时修 `getProdValue` 新格式恒 0 缺陷**（新格式不再走 `total_` 前缀路径）。
- [ ] B3 `renderDashboardKPI`：新格式月第 6 卡改占比卡（决策 8）；数字统一 `fmtK`。
- [ ] B4 `renderDayNightCompare`：新格式月隐藏 `dashDayNightOreTab`、强制 total-only 分组柱（`TEAM_COLORS`），标题复用 `dash_team_compare`。
- **门禁**：8 月截图/人工比对与改造前一致；9 月三卡符合本规格。

### Phase C — 桌面自适应（index.html + style.css）
- [ ] C1 `.data-dashboard > .card { min-width:0 }` + `.chart-fixed-h` 体系 + 4 canvas 包裹。
- [ ] C2 x 轴 maxTicksLimit/autoSkip/maxRotation + datalabels 抽样 + `resizeDelay:120`。
- **门禁**：1366/1440/1920 三档 + 31 天数据无横向滚动、无横向扩张；600/900 断点高度正确。

### Phase D — 移动端（mobile.html）
- [ ] D1 `loadDashboard`：请求带 `?month=STATE.currentMonth`，以响应 `d.month` 回写 `STATE.currentMonth` 与顶栏。
- [ ] D2 `drawTrend` 重写：labels 与 datasets 同一数据源；新格式班组线（共享 `TEAM_COLORS`），旧格式原逻辑；保留 ChartZoom/十字光标/双击重置。
- [ ] D3 `drawDayNight` 新格式入口 `STATE.dnTab='all'` + tab 高亮同步。
- [ ] D4 月份断言（决策 10）。
- **门禁**：真机/模拟器切月 A↔B↔A 首末日期恒属所选月；375px 无横向滚动。

### Phase E — 核验卡 UI + i18n + 回归
- [ ] E1 index.html 新增核验卡（结构见视觉规格）+ `loadVerifyData/renderVerifyCard`（权限门控）+ segmented 过滤 + 行点击 toast。
- [ ] E2 style.css 核验卡样式（chips/table/badge，`color-mix` 文字色）。
- [ ] E3 i18n.js 新增（zh+en）：`dash_team_filter`、`verify_title`、`verify_scope_note`、`verify_all`、`verify_only_diff`、`verify_days`、`verify_match_days`、`verify_mismatch_days`、`verify_col_group/dtotal/stotal/diff/status`、`verify_match`、`verify_diff`；旧 `verify_day_amt` 等不删。
- [ ] E4 全局数字排版（决策 7）：style.css `--font-main` 与 body 规则。
- [ ] E5 全量回归：pytest 全绿；8 月桌面+移动走查（控件/三线/对比 tab 与改造前一致）；9 月全功能走查；`AGENTS.md` 追加 P31 条目。

## 终验清单
- [ ] 9 月：班组趋势线/班组筛选联动/total-only 对比/核验卡（逐日、差异行可筛可点）
- [ ] 8 月：零改动回归（DOM 结构 + 交互 + pytest 0 差异）
- [ ] 布局：三档桌面无横滚；移动切月正确；数字全站 lining+tabular
- [ ] git 单 feature 分支，提交粒度按 Phase，便于单点回滚

## 回滚
前端模板/静态资源 + 单端点分支，整分支不合并/`git revert` 即回滚；无数据迁移、无计算链触碰。
