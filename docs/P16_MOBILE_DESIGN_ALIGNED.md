# P16 移动端设计对齐规范

> 由 frontend-designer 产出，基于 .design 原型 + 当前 mobile.html 实现，2026-08-14
> 用途：作为后续重写 `templates/mobile.html` 的蓝图。**本文档只读，不修改任何代码。**

---

## 0. 背景与材料

| 材料 | 路径 | 说明 |
|------|------|------|
| 设计 token 源 | `.design/enprizon-mobile/colors_and_type.css`（147 行） | Golden Time 设计系统变量（裸 hsl 分量写法） |
| 页面结构元数据 | `.design/enprizon-mobile/runtime-orchestration-summary.json`（424 行） | 4 页 dispatch 记录、token 引用清单、icon 清单 |
| 数据台设计稿 | `.design/enprizon-mobile/pages/dashboard.html`（1554 行） | Tailwind 4.3.1 + Lucide + Chart.js 4.4.7 |
| 员工设计稿 | `.design/enprizon-mobile/pages/employees.html`（2214 行） | 列表/档案/OA 三子页 + 2 个 Modal |
| 采集设计稿 | `.design/enprizon-mobile/pages/collection.html`（2027 行） | 4 个 entry 卡片 + 4 类表单 + 历史 |
| 出勤设计稿 | `.design/enprizon-mobile/pages/attendance.html`（2187 行） | 横向滑动日期条 + 编辑 Sheet + 批量面板 |
| 当前实现 | `templates/mobile.html`（717 行） | 单文件 SPA，自写 CSS + emoji/内联 SVG |
| 当前样式 | `static/css/mobile.css`（343 行） | 继承桌面 token + 移动端扩展变量 |
| 共享 i18n | `static/js/i18n.js`（1882 行） | 桌面端字典，**当前未被 mobile.html 实际使用** |
| 权威 spec | `docs/P16_MOBILE_FRONTEND_SPEC.md` | P16 原始方案（4 Tab、页面栈、Phase 1-5） |

**关键发现（先看结论）**：

1. **设计稿是 5-Tab（含「薪资」占位），spec 与当前实现是 4-Tab** —— 需要产品决策（见 §6 待确认）。
2. **设计稿 token 用「裸 hsl 分量 + `hsl(var(--x))`」写法；mobile.css 用「完整 hsl() 值」写法** —— 值等价，写法不同，互操作时有坑。
3. **设计稿字体 `--font-sans: Fraunces`（serif 编辑风）；spec §8.1 与当前实现用 Inter** —— 需决策（§3.2）。
4. **设计稿图标语言 = emoji + 少量内联 SVG**（搜索按钮是字符 `⌕`）；当前实现 tab 用内联 SVG、顶栏用 emoji —— 需统一（§3.1）。
5. **设计稿每页自带 i18n 字典（未抽取）；mobile.html 自带内联 I18N 字典（与 i18n.js 的 `I18N_DICT` 完全脱钩）** —— 需要统一 i18n 策略（§4）。
6. **设计稿出勤网格 = 左侧固定信息栏 + 右侧横向滚动 28px 圆形格 + 8 色 legend；当前实现 = 38px 圆角矩形格单行滚动、无 legend** —— 视觉差异最大的一处。

---

## 1. 设计 Token 核查

### 1.1 `.design`（colors_and_type.css）定义的全部 CSS 变量

来源：`colors_and_type.css:2-147`，四个设计稿页面头部 `<style id="theme-vars">` 均内嵌同一份（`dashboard.html:9-153` 等）。

| 类别 | 变量 | 亮色值（裸 hsl 分量） | 暗色值 |
|------|------|----------------------|--------|
| 背景 | `--background` `--card` `--popover` | `40 16% 98%` | `12 71.43% 1.37%` |
| 文字 | `--foreground` `--card-foreground` `--popover-foreground` | `37.5 15.69% 20%` | `41.54 18.84% 86.47%` |
| 文字 | `--muted-foreground` | `36 19.84% 49.41%` | `35 15% 60%` |
| 强调 | `--primary` | `37.5 15.69% 20%`（深棕） | `41.54 18.84% 86.47%` |
| 强调 | `--primary-foreground` | `40 16% 98%` | `12 71.43% 1.37%` |
| 强调 | `--secondary` | `55 24% 49.02%`（金） | `35 25% 30%` |
| 强调 | `--secondary-foreground` | `40 16% 98%` | `41.54 18.84% 86.47%` |
| 强调 | `--muted` | `44 26.32% 88.82%` | `35 15% 20%` |
| 强调 | `--accent` | `40 24.09% 73.14%`（暖金） | `35 25% 40%` |
| 强调 | `--accent-foreground` | `30 14% 30%` | `41.54 18.84% 86.47%` |
| 状态 | `--destructive` / `--destructive-foreground` | `0 84.2% 60.2%` / `0 0% 98%` | 同亮色 |
| 边框 | `--border` | `43.33 23.08% 84.71%` | `42.86 8.43% 16.27%` |
| 边框 | `--input` | `44 26.32% 88.82%` | `35 15% 20%` |
| 边框 | `--ring` | `37.5 15.69% 20%` | `35.45 29.73% 70.98%` |
| 图表 | `--chart-1` | `55 20% 80%` | `35 25% 60%` |
| 图表 | `--chart-2` | `0 15.34% 31.96%`（深红棕） | `20 20% 40%` |
| 图表 | `--chart-3` | `70.59 10.06% 66.86%` | `34.5 60.61% 87.06%` |
| 图表 | `--chart-4` | `55 24% 49.02%`（金） | `10 10% 50%` |
| 图表 | `--chart-5` | `28.99 91.75% 61.96%`（橙） | `13.74 78.17% 55.1%` |
| 侧边栏 | `--sidebar`* ~ `--sidebar-ring`（8 个） | 与 background/primary/accent/border 同值 | 暗色同值对应 |
| 字体 | `--font-sans` `--font-serif` | `Fraunces, ui-serif, serif` | 同 |
| 字体 | `--font-mono` | `monospace` | 同 |
| 几何 | `--radius` / `--radius-sm` / `--radius-md` / `--radius-lg` | `2rem` / `1rem` / `1.5rem` / `2rem` | 同 |
| 阴影 | `--shadow-2xs` ~ `--shadow-2xl`（7 个） | 全部 `hsl(35 15% 50% / 0.00)`（**alpha 0，无形影**） | `hsl(35 15% 5% / 0.00)` |
| 字距 | `--tracking-normal` | `0.01em` | 同 |
| 间距 | `--spacing` | `0.3rem` | 同 |

> `--sidebar*` 系列是桌面端侧边栏遗留，移动端不使用，但已包含在 `runtime-orchestration-summary.json:78-114` 的 token 引用清单中，属于「完整继承即可，无需单独适配」。

### 1.2 `mobile.css` 当前采用的 token

来源：`mobile.css:6-109`（`:root`）与 `mobile.css:111-149`（`.dark`）。

- 完整复刻了 `.design` 的语义色：`--background/--card/--popover/--foreground/--muted-foreground/--primary/--secondary/--muted/--accent/--destructive/--border/--input/--ring/--chart-1~5/--sidebar*`（**写法为 `hsl(…)` 完整值**）。
- 扩展了设计稿没有的变量：`--success/--success-bg/--warning/--warning-bg/--purple/--purple-bg`（出勤状态色）、`--danger/--danger-bg`、兼容别名 `--bg-primary/--text/--text-muted/--accent-dim/--cyan/--border-light/--shadow/--radius-lg/--radius-xl`、`--font-main: 'Fraunces'`、`--transition-fast/normal`。
- 移动端专属几何：`--touch-target: 44px`、`--safe-top/bottom/left/right`、`--tab-bar-height: 56px`、`--top-bar-height: 48px`、字号 `--text-xs~2xl`（11-24px）、间距 `--space-xs~2xl`（4-24px）。
- **缺失**：`--tracking-normal`、`--shadow-sm` 定义了但阴影全 alpha 0、`--radius-sm/md` 未定义（仅 `--radius` 与别名 `--radius-lg/xl`）。

### 1.3 对齐差异表

| Token | `.design` 值/写法 | `mobile.css` 当前值/写法 | 状态 |
|-------|------------------|------------------------|------|
| 颜色变量（约 30 个语义/图表色） | 裸分量，`hsl(var(--x))` 使用 | 完整 `hsl()` 值，`var(--x)` 使用 | ✅ 等价（写法不同，混合使用会出错） |
| `--chart-1~5` | 与设计稿同 | 与设计稿同 | ✅ 已对齐 |
| `--font-sans` | `Fraunces, ui-serif, serif` | 未定义 `--font-sans`；`--font-main` 为 Fraunces，body 用 `--font-ui`（Inter） | ⚠️ 不一致（见 §3.2） |
| `--tracking-normal` | `0.01em`（body 全局 letter-spacing） | 未定义 | ❌ 缺失 |
| `--radius` / `sm` / `md` / `lg` | `2rem` / `1rem` / `1.5rem` / `2rem` | 仅 `--radius: 2rem` + 别名 `--radius-lg/xl` | ❌ 缺 sm/md |
| `--shadow-xs` ~ `--shadow-2xl` | 完整 7 级（均 alpha 0） | 仅 `--shadow-xs/sm`（alpha 0） | ⚠️ 部分 |
| `--spacing` | `0.3rem` 基元，间距用 `calc(var(--spacing) * N)` | 定义了 `--space-*` 固定值（4/8/12/16/20/24px） | ⚠️ 两套体系并存 |
| 语义扩展（success/warning/purple） | 无 | 有 | ➕ mobile 扩展（出勤色需要） |
| 移动端几何（touch-target/safe-area/tab/top bar） | 无 | 有 | ➕ mobile 扩展 |
| 出勤状态色（D/N/P/A/L/C/R/B） | 散落在 attendance.html 的 `.status-*`（`attendance.html:812-819`），**未提成 token** | `mobile.css:258-265` `.st-*` + `mobile.css:287-294` `.att-cell__s.st-*` + `mobile.css:306-311` 圆点 | ⚠️ 未抽 token，三处硬编码重复 |

**结论**：颜色体系已对齐；**缺口集中在字体 token、tracking、radius-sm/md、shadow 全级、出勤状态色未 token 化、两套间距体系并存**。

---

## 2. 四个页面组件清单

### 2.1 数据台（Dashboard）

**页面用途**：纯产量导向的多维度交互仪表盘（6 KPI + 4 图表 + 破碎表），对应桌面端 P15 数据台。

**顶部结构（设计稿 `dashboard.html:343-385`）**：
- Period Bar（48px，`dashboard.html:583-595`）：左侧 `[◀] 2026年8月 [▶]`（点月份弹选择器），中间搜索按钮 `⌕`（44×44 圆角方块，`dashboard.html:607-631`），右侧语言胶囊 `中 / EN`（`dashboard.html:633-663`）。
- Control Bar（可折叠，`dashboard.html:360-385`）：标题「数据台」+「筛选 ▾」触发器（`filter-checkbox:checked` 展开）；展开后两行 Segmented：班次（全部/白班/夜班）、矿石类型（全部/NH/NL/MW）。

**主体组件（`dashboard.html:388-524`）**：
1. KPI 2×3 网格（`kpi-grid`，`dashboard.html:391-435`）：本月 NH / 本月 NL / 本月 MW / 日均车次 / 日最高（带 `kpi-sub` 日期小字）/ 白夜班比；每卡左侧 3px 彩色指示条（`ind-i2/i4/i5/ind-neutral`，`dashboard.html:886-894`）。
2. 错误状态（⚠ + 文案 + 重试按钮，`dashboard.html:438-442`）、空状态（∅ + 暂无产量数据，`dashboard.html:444-447`）。
3. 图表面板 ×4（`chart-panel`，圆角 `radius*0.82`、`--shadow-xs`、`padding 4*spacing`）：
   - 产量趋势折线（白班/夜班/合计三线 + legend，`dashboard.html:450-460`）；
   - 白班 vs 夜班（分组柱 + `cmp-tab` 切换 NH/NL/MW/合计，`dashboard.html:463-478`）；
   - 钻工组产量（堆叠柱，按 LAMBA LAMBA / SAKA SAKA / 其他，下钻 note，`dashboard.html:481-492`）；
   - 矿石类型占比（环形图 + 中心「总车次」文字 + 右侧百分比 legend，`dashboard.html:495-507`）。
4. 破碎产量表（`crush-card`：表头 + 三列行「日期/袋数/人数」+ 合计行，`dashboard.html:510-522`）。
5. 骨架屏（`skeleton`/`sk-val`/`sk-row`/`chart-loading`，`dashboard.html:1260-1275`）。

**与当前 mobile.html 的差异**：
- 当前 `mobile.html:62-66` 只有班次 Segmented，**缺矿石类型筛选**；
- 当前 KPI 卡（`mobile.css:219-222`）`::before` 用 `--secondary` 统一色，**缺彩色指示条**；
- 当前 KPI 卡无 `kpi-sub`（日最高日期小字）；
- 当前无错误/空状态组件（只有 loading 文案 `mobile.html:60`，失败时 `mobile.html:281` 改 loading 文案）；
- 当前无骨架屏（直接空转 loading）；
- 当前趋势图三线为 NH/NL/MW（`mobile.html:328-332`），设计稿是白班/夜班/合计；
- 当前破碎表为 `.card` + `.crush-row` 行（`mobile.html:84-87`），设计稿是独立 `crush-card` 三列表头+合计行；
- 当前顶栏为统一 top-bar（back+title+month+🔍🌐🌙），设计稿是 period-bar（月份+搜索+语言，**无主题切换**）。

**375px 适配要点**：KPI 卡 min-width 140px 两列；图表高度 trend 160px / 其余 120-160px（`dashboard.html:1266-1268`）；donut 160px 居中；tab 图例换行；`cmp-tab` 允许横向滚动；破碎表三列在 375px 下直接用 1fr 1fr 1fr。

### 2.2 员工（Employees）

**页面用途**：员工列表 → 档案详情 → 编辑档案 / OA 审批（待审 + 已审批）/ 请假申请的 Tab 内子页。

**顶部结构（设计稿 `employees.html:342-371`）**：
- Period Bar（48px）：`2026年8月 · Lind Mining` + 语言胶囊（无搜索/主题按钮）。
- 分段控制（`segmented-control`，圆角 999px，`employees.html:627-669`）：员工列表 / 待审(N) / 已审批。
- 搜索栏（`search-field`：input 底 + 放大镜 inline SVG，防抖 300ms，`employees.html:672-712`）。

**主体组件（`employees.html:374-555`）**：
1. 员工卡片列表（`emp-card`：40px 圆形头像 + 姓名（+en_name/别名）+ meta「工号 · 班组」+ 右 chevron；min-height 68px，底部 1px 分隔线，`employees.html:726-820`）。
2. 骨架屏（3 张 `skeleton-card`，`employees.html:1219-1252`）+ 错误态（⚠ SVG + 重试，`employees.html:389-397`）+ 空态（`employees.html:399-406`）。
3. 列表 footer「显示 N 人」（`employees.html:409`）。
4. 档案详情（`view-profile-detail`，`employees.html:416-457`）：返回头 + 80px 大头像 + 姓名 + id-tags（别名/工号）+ 基本信息 key-value 列表（10 行）+ 出勤统计三 mini 卡（`mini-stat-card`，`employees.html:969-994`）+ 薪资概览 + 「编辑档案」按钮。
5. 编辑档案 Modal（底部 sheet 弹层，`modal-overlay`+`modal-sheet`，8 字段，footer 取消/保存，`employees.html:524-536`）。
6. OA 待审（`oa-header` + 红色 `oa-badge` 计数 + `oa-card`：类型标题/人员/desc/日期 + [批准][拒绝] 按钮，`employees.html:462-494,1092-1130`）+ 骨架/错误/空三态。
7. OA 已审批（`oa-history-card` + `oa-status-badge.approved/rejected` 状态徽章，`employees.html:497-521,1388-1422`）。
8. 拒绝原因 Modal（textarea + 取消/确认拒绝，`employees.html:539-554`）。

**与当前 mobile.html 的差异**：
- 当前列表卡 `card-item`（`mobile.html:381-388`）头像 40px、姓名含别名、meta 为「#工号 · 班组 · 岗位」，无 en_name 拼接、无 chevron（用 › 字符）；
- 当前无骨架屏、无错误/空态（loading 直接内联文案）；
- 当前无列表 footer「显示 N 人」；
- 当前档案页（`mobile.html:408-424`）无出勤统计 mini 卡、无薪资概览、无 id-tags；
- 当前编辑用底部 Sheet（`openEditEmp`，`mobile.html:426-446`），设计稿用 Modal sheet（header+body+footer 三区）——交互同族，DOM 结构不同；
- 当前 OA 待审/已审批无红色 badge 计数（有待审数在 seg 标签内，`mobile.html:95`）；
- 当前拒绝用 `prompt()`（`mobile.html:478`），设计稿用专用 Modal。

**375px 适配要点**：员工卡 min-height 68px 保证点击热区；档案页 80px 头像居中；基本信息 value `word-break: break-all` 防长文本溢出；mini 卡三列等宽；Modal `max-width: 375px; border-radius 2rem*0.8 顶部圆角`（`employees.html:1289-1299`）。

### 2.3 数据采集（Collection）

**页面用途**：4 类采集（井下/钻工/破碎/出勤）的入口卡片 + 表单 + 最近提交历史。

**顶部结构（设计稿 `collection.html:342-359`）**：Period Bar（`2026年8月 ENPRIZON LINDI`）+ 页头「数据采集」+ 语言胶囊。

**主体组件（`collection.html:361-652`）**：
1. 4 张 entry 大卡片（`entry-card`：emoji 图标 + 标题 + 「本月已提交: N 条」+「上次提交: 8/13 白班」+ footer「进入采集 ›」，`collection.html:362-414`）。
2. 最近提交历史（`history-list`：日期（含白/夜班标注）/类型/摘要（人数），`collection.html:416-422`，渲染逻辑 `collection.html:839-874`）。
3. 井下表单（`form-underground`，`collection.html:424-518`）：返回头 + `form-message`（错误/成功内联提示）+ 日期 + **班次 toggle（白班(D)/夜班(N) 二选一，`collection.html:440-446`）** + NH/NL/MW 三数字 + 备注 + 备注2 + 出勤人员多选列表（`worker-item`：checkbox + 姓名 + 工号）+ 底部「已选: N 人」+ 提交。
4. 钻工表单（`collection.html:521-569`）：日期 + 队长下拉（driller_captains）+ NH/NL/MW + 队员多选。
5. 破碎表单（`collection.html:571-608`）：日期 + 破碎队人员多选 + Bag 数量 + 备注。
6. 出勤收集表单（`collection.html:611-652`）：日期 + 部门筛选 + **「全选出勤(P)」「全选旷工(A)」批量按钮（`collection.html:636-639`）** + 人员状态 select 列表 + 「共 N 人」计数。
7. 校验逻辑：`validateForm()`（`collection.html:1078-1111`）内联错误提示，提交按钮 loading「提交中...」（`collection.html:1151-1155`）。

**与当前 mobile.html 的差异**：
- 当前采集首页是简化 `card-item` 列表（`mobile.html:514-528`），**无「本月已提交/上次提交」计数 meta、无 entry-card footer、无图标语义**；
- 当前井下表单为 **Day + Night 双段同时填**（`renderUgForm`，`mobile.html:537-556`，双份 NH/NL/MW + 双份人员/驾驶），设计稿是**单班次 toggle**——这是**数据模型差异**，涉及后端 payload 结构；
- 当前井下表单**无备注/备注2 字段**；
- 当前采集人员选择用 checkbox 长列表（`empChecklistHTML`，`mobile.html:506-512`），设计稿是 `worker-item`（checkbox+姓名+工号行），交互相近；
- 当前出勤收集是「每行 select 状态」（`mobile.html:612`），设计稿是 select 列表 + 全选 P/A 批量按钮；
- 当前无内联 `form-message` 成功/错误提示（用 toast）；
- 当前钻工表单支持多队伍（`STATE._drSlots`，`mobile.html:559-586`），设计稿只有**单队长单队伍**——与井下一样是模型差异（spec §5.4 也是单队长）；
- 当前历史列表无白/夜班标注。

**375px 适配要点**：entry-card 高度自适应；worker-item 每行约 48px 高；表单输入 min-height 44px、`font-size: 16px` 防 iOS 缩放；数字输入 `inputmode="numeric" pattern="[0-9]*"`（`collection.html:450`）；submit-bar 底部固定或紧贴内容。

### 2.4 出勤（Attendance）

**页面用途**：全月出勤网格（横向滑动日期条）+ 单格状态编辑 + 批量标记 + 快捷操作。

**顶部结构（设计稿 `attendance.html:342-373`）**：
- Period Bar：`2026年8月 · 31天` + 语言胶囊；点击左半/右半切换上月/下月（`attendance.html:2082-2093`）。
- 大标题「出勤 - 2026年8月」（1.35rem/700）。
- 搜索栏（放大镜 + input）。
- 筛选行（`filter-row`）：部门 select + 日期 select + 「批量」按钮（动态注入，`attendance.html:2098-2109`）。

**主体组件（`attendance.html:375-483`）**：
1. Legend 图例条（`legend-strip`，8 色圆点：井下白班/井下夜班/日薪月薪/旷工/请假/破碎/钻工/双班，`attendance.html:376-385`）。
2. 出勤卡列表（`attendance-card`，`attendance.html:667-819`）：左侧固定 100px（头像 36px + 姓名 + id，`card-left` 背景 `muted/0.4`）+ 右侧 `date-strip-scroll` 横向滚动（日期行 + 状态行，28px 单元格，状态为**圆形** `status-cell` + 色底 `status-X { color: hsl(...); background: hsl(.../0.12) }`，周末日期变淡）；分页加载（`PAGE_SIZE=20` + 「加载更多」按钮，`attendance.html:1520,1631-1644`）。
3. 状态编辑底部 Sheet（`status-edit-sheet`：标题「修改出勤 - 8/15」+ 副标题人名工号 + 当前状态 + **8 状态按钮网格（P/A/L/D/N/C/R/B，字母 + 中文标签）** + 取消，`attendance.html:392-435,839-…`）。
4. 批量标记面板（`batch-marking`，`attendance.html:437-470`）：取消 + 标题「批量标记 已选: N 人」+ 员工勾选列表 + **日期范围（start ~ end）** + 6 状态按钮 + 进度条 + 「应用到选中 N 人」。
5. 快捷操作（`quick-actions`：+ 请假申请 / + 病假登记，`attendance.html:472-483`）。
6. 加载/错误/空三态（skeleton 卡 + ⚠/📋 图标，`attendance.html:1729-1756`）。

**与当前 mobile.html 的差异**：
- 当前出勤卡（`mobile.css:267-311`）是「单行 38px 圆角矩形格」+ 竖排日期/状态，设计稿是**「左侧固定 100px 信息栏 + 右侧 28px 圆形状态格横向滚动」**且状态格**带 12% 透明度底色**；
- 当前**无 legend 图例条**；
- 当前工具栏（`mobile.html:636-641`）为「搜索+部门 select+📅 跳转+批量按钮」，设计稿为「搜索+部门+日期筛选+批量」且支持**左右点按切月**；
- 当前编辑 sheet 6 状态（`mobile.html:676`），设计稿 8 状态（含 R 钻工/B 双班）；
- 当前批量标记为**单日期 + 6 状态**（`mobile.html:688-702`），设计稿为**日期范围 + 进度条**（`applyBatch`，`attendance.html:1897-1965`）；
- 当前无分页「加载更多」（130 人一次性渲染）；
- 当前无状态格 12% 色底（`mobile.css:282` 只设文字色）。

**375px 适配要点**：卡左栏固定 100px 不可压缩；右侧 28px 单元格 ×31 天 = 868px 横向滚动区，`scroll-snap-type: x mandatory` 对齐（`attendance.html:739`）；legend 允许换行；sheet 按钮网格 2 列；`touch-action: manipulation` 消除 300ms 延迟。

---

## 3. 视觉规范建议

### 3.1 技术栈：自写 CSS + inline SVG（维持现状） vs Tailwind + Lucide

| 维度 | 方案 A：Tailwind 4.3.1 browser + Lucide（设计稿用） | 方案 B：自写 CSS + inline SVG/emoji（当前实现用） |
|------|--------------------------------|--------------------------------|
| 依赖 | 2 个 CDN 脚本（`tailwindcss/browser@4.3.1` + `lucide@1.8.0`，`dashboard.html:156-157`） | 零新增依赖 |
| 部署 | `/salary/` 子路径 + CDN 可用性风险（Tailwind browser 运行时编译，首屏 JS 大） | 全静态，缓存友好，**与既有 Service Worker 策略（刻意不启用 SW）兼容** |
| token | 需 `@theme inline` 映射（`dashboard.html:160-194`） | 直接用 CSS 变量 |
| 维护 | class 冗长，动态渲染模板难读 | 与桌面端 style.css 同语言 |
| 一致性 | 与设计稿逐像素一致成本最低 | 需手写对齐 |

**建议**：**维持方案 B（自写 CSS + inline SVG）**。理由：
1. 系统部署在 `/salary/` 子路径且频繁发版，`@tailwindcss/browser` 是运行时编译器（约 300KB+），会显著拖慢移动端首屏；
2. 当前 `mobile.css` 已复刻 token，缺口只在 §1.3 列出的几个变量，补齐即可达到设计稿一致；
3. 图标建议**以 inline SVG 为准**（当前 tab bar 已是自绘 SVG，`mobile.html:118-131`），设计稿页面里混用 emoji 是导出原型行为，真实应统一为 SVG（`runtime-orchestration-summary.json:148-194` 提供 39 个 css-mask 图标名，可按需摘取 path 手写）。emoji 仅保留在内容场景（如采集卡片图标 ⛏🔩🪨📋、空态图标）。
4. 若后续要上 Tailwind，也应在 `mobile.css` 里用 `@theme` 编译构建，而非 CDN browser 版——但这是重构方向，不在本次对齐范围。

### 3.2 字体：Fraunces（serif） vs Inter（sans-serif）

| 方案 | 效果 | 代价 |
|------|------|------|
| 设计稿：`--font-sans: Fraunces`（全局 serif） | 英文/数字呈衬线编辑风，与 Golden Time 一致；**中文无衬线字重，fallback 系统字体** | 需引入 Fraunces webfont（增加 2 个 woff2），数字 KPI 呈 serif 可能影响可读性 |
| 当前：Inter（仅加载 400/500/600，`mobile.html:14`） | 全平台一致、中文 fallback 好、数字可读性强 | 与设计稿编辑风有差距 |
| **混合（建议）**：`--font-ui: Inter`（正文/UI）+ `--font-display: Fraunces`（仅品牌标题 / 登录页 / KPI 数值可选） | 兼顾可读性与编辑风 | 需补 `--font-display` token 与 2 处字体类 |

**建议**：采用**混合方案**，但**默认保持 Inter 为 UI 字体**（与 spec §8.1 `--font-ui: 'Inter'` 一致）。Fraunces 仅用于：登录页 LOGO、数据台 section 大标题（可选）、KPI 数值（可选，需先验证 4 位数在小字号可读性）。同时补齐 `--tracking-normal: 0.01em` 全局字距（设计稿 body 全局 `letter-spacing`，`colors_and_type.css:144-146`）。

### 3.3 圆角 / 间距 / 阴影统一标准

| 项 | 设计稿标准 | mobile.css 现状 | 对齐动作 |
|----|-----------|----------------|---------|
| 圆角基元 | `--radius: 2rem`；卡片 `calc(var(--radius) * 0.82)` ≈ 26px；seg 按钮 `*0.76` ≈ 24px；搜索框 `*0.52` ≈ 17px；按钮 `*0.62` ≈ 20px | 卡片 16px、按钮 12px、输入 12px、segmented 10px | 补 `--radius-sm/md/lg`，卡片统一 `--radius-lg` 或 16px+ |
| 间距 | `--spacing: 0.3rem`，页面 padding `*4`（19.2px）、卡 padding `*4`（19.2px）、卡间距 `*2.5`（12px） | `--space-*` 固定值（页面 12px、卡 12px） | 对齐为：页面水平 padding 16px、卡 padding 14-16px、卡间距 12px |
| 阴影 | 全 7 级 alpha 0（**视觉无阴影，靠边框+间距分层**） | `--shadow-xs/sm` alpha 0 | 保持「无阴影」原则，不引入 elevation |
| 触摸目标 | min-height 44px（按钮/搜索/seg） | `--touch-target: 44px` 已定义，部分组件 36px | 检查 seg-btn/cmp-tab 等低于 44px 的组件 |

### 3.4 暗色模式

- 设计稿 `.dark` 块（`colors_and_type.css:74-142`）已完整定义；mobile.css `.dark`（`mobile.css:111-149`）已复刻但**用了不同值**（background `30 15% 2%` vs 设计稿 `12 71.43% 1.37%`；ring `33 40% 55%` vs `35.45 29.73% 70.98%`）。
- **建议**：将 mobile.css `.dark` 全部改为与设计稿一致，避免双端暗色观感漂移；`theme-color` meta 随主题切换（当前 `applyTheme()` 已做，`mobile.html:204`）。
- 出勤状态色在暗色下保持饱和即可（当前 `.st-*` 与 `.att-cell__s.st-*` 双份硬编码，建议合并为单一 token 变量族 `--st-p/--st-a/...`）。

### 3.5 PWA manifest 视觉规范

- 当前 `static/manifest.webmanifest` + `static/icons/icon.svg` 已存在（Phase 5 完成，未启用 Service Worker——刻意，避免 `/salary/` 子路径缓存失效）。
- **建议**：保持不启用 SW；`theme-color` 在亮/暗分别 `hsl(40 16% 98%)` / `hsl(12 71.43% 1.37%)`（与设计稿 token 对齐，当前用 `hsl(30 15% 6%)`，`mobile.html:204`）；`background_color` 取亮色 background；图标背景建议用 `--primary` 深棕 + 暖金前景（Golden Time 双色），提交前先在 iOS 主屏验证圆角/刘海适配。

---

## 4. i18n 扩展清单

### 4.1 现状与问题

- 设计稿 4 页各自内联一套 zh/en 字典（`dashboard.html:1466-1543`、`employees.html:2121-2193`、`collection.html:1234-1302`、`attendance.html:2114-2166`）——**未抽取**。
- `mobile.html` 内联 `I18N` 字典（`mobile.html:170-195`），并用自有 `t()`（`mobile.html:196`）；`/static/js/i18n.js` 的 `I18N_DICT` 被加载（`mobile.html:148`）但**从未被 mobile.html 引用**。
- 后果：同一文案存在三份（设计稿/移动端内联/桌面字典），修改需三处同步。

**建议统一策略**：以 `static/js/i18n.js` 的 `I18N_DICT` 为唯一权威字典，mobile.html 的 `t()` 改为读取 `window.I18N_DICT`（带兼容回退），删除内联 `I18N`。若担心 i18n.js 过于臃肿（1882 行全量加载），可将移动端键独立为 `static/js/i18n.mobile.js` 并在 mobile.html 先于主字典加载——二者选一，需团队决策（§6）。

### 4.2 设计稿 4 页文本标签清单（含建议 i18n 键）

**数据台**（来源 `dashboard.html:344-547`）：

| 文本 | 建议键 | 当前状态 |
|------|--------|---------|
| 数据台 / 员工 / 采集 / 考勤 / 薪资 | tab_dashboard/tab_employees/tab_collection/tab_attendance/tab_salary | ✅ 已有（`mobile.html:171-194`） |
| 选择月份 | select_month | ✅（month） |
| 搜索 | search | ✅ |
| 中 / EN | lang_zh / lang_en | ✅ 结构内联 |
| 数据台（control-bar 标题） | dashboard_title | ✅（tab_dashboard） |
| 筛选 / 班次 / 矿石类型 | filter / shift / ore_type | ❌ 缺 filter / ore_type |
| 全部 / 白班 / 夜班 | all / day_shift / night_shift | ✅ |
| NH / NL / MW / 合计 | nh / nl / mw / total | ✅ |
| 本月 NH / 本月 NL / 本月 MW / 日均车次 / 日最高 / 白夜班比 | kpi_nh_month / kpi_nl_month / kpi_mw_month / kpi_daily_avg / kpi_day_max / kpi_ratio | ⚠️ 当前为 nh/nl/mw/daily_avg/day_max（`mobile.html:175`），缺「本月」前缀，白夜班比缺 |
| 产量趋势 / 白班 vs 夜班 / 钻工组产量 / 矿石类型占比 | chart_trend / chart_day_night / chart_driller / chart_ore | ✅（trend/day_night/driller_output/ore_type） |
| 点击柱子查看逐日明细 | chart_drill_note | ❌ |
| 破碎产量 / 日期 / 袋 / 人 / 合计 | crush_table / date / bags / emp / total | ✅（bags/emp 已有） |
| 数据加载失败 / 重试 / 暂无产量数据 | load_fail / retry / no_data | ⚠️ load_fail 有，retry 有，no_data 缺（有 no_emp） |
| 请先登录 | login_required | ⚠️ 有（`mobile.html:182` need_editor 旁） |

**员工**（来源 `employees.html:344-553`）：

| 文本 | 建议键 | 当前状态 |
|------|--------|---------|
| 员工列表 / 待审 / 已审批 | emp_list / oa_pending / oa_history | ✅ |
| 搜索员工... | search_emp_ph | ❌（当前用 search 键） |
| 显示 {n} 人 | show_n | ❌（当前内联拼接 `mobile.html:394`） |
| 加载失败 / 无法获取员工数据 / 重试 | load_fail / emp_load_err / retry | ⚠️ 部分 |
| 暂无员工数据 / 请先导入员工信息 | no_emp / emp_empty_desc | ⚠️ no_emp 有，desc 缺 |
| 员工档案 / 返回员工列表 | emp_profile / back | ⚠️ profile 缺、back 缺（有 topback） |
| 别名 / 工号 / 班组 | alias / custom_number / team | ✅ |
| 基本信息 / 部门 / 岗位 / 性别 / 出生日期 / 电话 / NIDA / NSSF / 银行 / 薪资类别 | basic_info / dept / position / gender / dob / phone / nida / nssf / bank / salary_type | ✅ 大部分（`mobile.html:176-179`），dob 缺 |
| 出勤统计 (本月) / 出勤 / 请假 / 旷工 | att_stats / att_days / leave_days / absent_days | ❌ |
| 薪资概览 (本月) / 应发 / 实发 | salary_overview / gross / net | ❌ |
| 编辑档案 / 取消 / 保存 | edit_profile / cancel / save | ⚠️ edit_profile 有，cancel/save 缺 |
| 待审批 / {n} 条待审批 / 暂无待审批事项 / 所有申请已处理完毕 | oa_pending_title / oa_badge_label / no_oa / oa_done_desc | ⚠️ no_oa 有，其余缺 |
| 调岗/请假/入职/薪资变更/离职/病假 申请 | oa_transfer/oa_leave/oa_hire/oa_salary/oa_dismiss/oa_sick | ✅ 前 5 个有（`mobile.html:179`），sick 缺 |
| 批准 / 拒绝 / 拒绝原因 / 请填写拒绝原因 / 确认拒绝 | approve / reject / reject_reason / reject_hint / confirm_reject | ⚠️ approve/reject 有，reason 用 prompt 无 modal 键 |

**采集**（来源 `collection.html:342-651`）：

| 文本 | 建议键 | 当前状态 |
|------|--------|---------|
| 数据采集（页头） | collection_title | ⚠️ 用 tab_collection |
| 井下出渣采集 / 钻工组采集 / 破碎计件采集 / 出勤收集 | col_ug / col_dr / col_cr / col_att | ✅ |
| 本月已提交 / 上次提交 / {n} 条 | col_month_count / col_last_submit / col_items | ❌（当前用 recent_submits/submits） |
| 进入采集 | col_enter | ❌ |
| 最近提交历史 / 加载中... / 暂无提交记录 | col_history / loading / no_history | ⚠️ recent_submits 有、no_history 有、loading 有 |
| 日期 / 班次 / 白班(D) / 夜班(N) | date / shift / day_shift / night_shift | ✅ 大部分 |
| NICKEL(H) 车次 / NICKEL(L) 车次 / MAWE 车次 | nh / nl / mw | ⚠️ 已有 nh/nl/mw，缺「车次」后缀样式 |
| 备注 / 备注2 | remark / remark2 | ❌ |
| 出勤人员 (多选) / 队员 (多选) / 破碎队人员 | col_emps / members / crush_crew | ✅ col_emps/members 有 |
| 已选: {n} 人 | col_selected_count | ⚠️ 有 `col_selected_count: '已选 {n} 人'`（i18n.js:47）但移动端内联未用 |
| 提交 / 提交中... / 提交成功 / 提交失败 | submit / submitting / success / fail | ⚠️ submit/submitted/fail 有，submitting/success 缺 |
| 请选择日期 / 请至少选择一位出勤人员 / Bag 数量必须大于 0 | val_date / val_workers / val_bags | ❌ |
| 队长 / -- 请选择队长 -- | captain / pick_captain | ✅ |
| 全选出勤(P) / 全选旷工(A) | batch_all_p / batch_all_a | ❌ |
| 共 {n} 人 | col_total_count | ❌ |
| 部门筛选 / 全部 | dept_filter / all_depts | ✅ |

**出勤**（来源 `attendance.html:342-483`）：

| 文本 | 建议键 | 当前状态 |
|------|--------|---------|
| 出勤 - {month} | att_title | ⚠️ att_month 有 |
| 搜索 | search | ✅ |
| 部门 / 日期 / 批量 | dept / date / batch_mark | ⚠️ dept/all_depts 有、batch_mark 有、date 有 |
| 井下白班 / 井下夜班 / 日薪月薪 / 旷工 / 请假 / 破碎 / 钻工 / 双班（legend 与状态共用） | st_d / st_n / st_p / st_a / st_l / st_c / st_r / st_b | ✅ 有 st_p/a/l/d/n/c；**st_r/st_b 缺** |
| 修改出勤 - {m}/{d} / 当前: / 取消 | edit_att / att_current_label / cancel | ⚠️ edit_att 有，其余缺 |
| 加载更多 ({a}/{b}) | load_more | ❌ |
| 暂无出勤数据 | no_att_data | ❌ |
| 批量标记 / 已选: {n} 人 / 日期范围 / 至 / 应用到选中 {n} 人 | batch_title / batch_selected / batch_range / batch_to / batch_apply | ⚠️ 仅 batch_mark/selected 部分 |
| 正在标记 {a}/{b}... / 完成! 已标记 {n} 条记录 | batch_progress / batch_done | ❌ |
| 快捷操作 / 请假申请 / 病假登记 | quick_actions / leave_apply / leave_sick | ✅ |

### 4.3 建议新增 i18n 键（~50 个）

> 命名沿用既有 snake_case；zh/en 双语；数组/对象类型的验证文案建议扁平化为独立键。

```text
# 通用
filter, ore_type, back, save, cancel, confirm, submit, submitting, success,
load_fail, no_data, retry, login_required, select_month, search_emp_ph,
col_selected_count({n}), show_n({n})

# 数据台
kpi_nh_month, kpi_nl_month, kpi_mw_month, kpi_ratio, chart_drill_note

# 员工
emp_profile, emp_load_err, emp_empty_desc, show_n, alias, dob,
att_stats, att_days, leave_days, absent_days,
salary_overview, gross, net,
oa_badge_label({n}), oa_done_desc, reject_hint, confirm_reject,
oa_sick

# 采集
col_month_count, col_last_submit, col_items, col_enter, col_history,
remark, remark2, crush_crew, col_total_count,
val_date, val_workers, val_bags, batch_all_p, batch_all_a

# 出勤
st_r, st_b, att_current_label, load_more, no_att_data,
batch_title, batch_selected, batch_range, batch_to, batch_apply,
batch_progress, batch_done
```

> 说明：以上为「建议键」，其中部分值已存在于 `mobile.html` 内联字典或 `i18n.js`（如 `col_selected_count` 在 `i18n.js:47`），统一字典时应先复用再新增，避免重复键。

---

## 5. 重写范围评估

### 5.1 行数估算

| 文件 | 当前 | 目标 | 增量 | 说明 |
|------|------|------|------|------|
| `templates/mobile.html` | 717 行 | **约 1600-2000 行** | +900-1300 | 补齐 4 页设计稿组件、骨架/错误/空三态、批量面板、页面栈；JS 仍内联 |
| `static/css/mobile.css` | 343 行 | **约 700-900 行** | +400-550 | 新增出勤 legend/圆形状态格/批量面板/Modal/entry-card/form 组件样式、token 补齐 |
| `static/js/i18n.js`（或新 `i18n.mobile.js`） | — | +50 键 | +50 | 见 §4.3 |

> 对照 spec §9.2 预估（mobile.html 2000-2500 行、mobile.css 800-1200 行）：本次为**视觉对齐重写**而非全功能重写，规模略低于 spec 上限。若 5-Tab（含薪资）获批，需再 +200-300 行。

### 5.2 需要新增/重构的 JS 函数与状态

| 类别 | 新增/重构 | 说明 |
|------|----------|------|
| 状态 | `STATE.tabStacks`（页面栈，spec §10.3） | 档案/OA/采集表单均需 push/pop |
| 状态 | `STATE.colForm`（当前表单类型） | 替代全局 `STATE.colType` |
| 状态 | `STATE.attBatchRange = { start, end }`、`STATE.attBatchTotal/Progress` | 设计稿批量标记是日期范围 + 进度 |
| 状态 | `STATE.dashFilters = { shift, ore }` | 新增矿石类型筛选 |
| 工具 | `openSheet/closeSheet` 增加参数校验 + 遮罩手势 | 当前 `openSheet(title, body)` 无遮罩点击关闭逻辑复用问题（`mobile.html:249-250`） |
| 渲染 | 骨架屏函数 `skeletonCard()`、错误/空态统一函数 `stateBox(type, icon, title, desc, action)` | 3 页复用 |
| 渲染 | `renderKpiCard(k)` 带 `ind-iX` 彩色指示条 | 对齐设计稿 KPI |
| 渲染 | 出勤卡重写 `renderAttCard(emp)`：左固定栏 + 右 28px 圆形格 + legend | 全量替换当前 `renderAttGrid` 单元格结构 |
| 渲染 | 批量面板 `openBatchPanel/applyBatch` 增加日期范围与进度条 | 参照 `attendance.html:1897-1965` |
| 交互 | 员工档案 `openEditModal`（Modal sheet 三区结构） | 对齐设计稿 Modal，而非复用 `openEditEmp` |
| 交互 | 采集表单内联校验 `validateColForm(type)` + `form-message` | 替代纯 toast |
| 交互 | 提交按钮 loading 态 | `submitting` 禁用 + 文案 |
| i18n | `t()` 改为读共享字典（见 §4.1） | 删除内联 `I18N` |

### 5.3 是否拆分 mobile.html（目前单文件 SPA）

**建议：维持单文件，不拆分。**

理由：
1. 目标 1600-2000 行仍在单文件可控范围（桌面端 index.html ~4000 行先例，AGENTS.md 明确「尽量避免增加不必要的模块拆分」）；
2. 无构建系统，拆分意味着多个 `<script>` 靠全局函数互相引用，命名空间与加载顺序反而更脆弱；
3. 若确实要拆，**唯一合理切分点**是：`templates/mobile.html`（结构）+ 将 JS 抽为 `static/js/mobile.js`（约 1200 行）+ `mobile.css`——但需同步处理 Flask 模板变量 `{{ version }}` 的静态资源版本号，属额外工程，非本次必要。

### 5.4 风险点（后端 API 配合）

| 风险 | 等级 | 说明 |
|------|------|------|
| **井下采集「单班次 toggle」vs 当前「Day+Night 双段」** | 🔴 高 | 设计稿 `collection.html:440-446` 的 payload 是 `{date, shift: 'D'|'N', nickel_h, nickel_l, mawe, worker_ids}`；当前 `mobile.html:554-556` 提交 `{day:{...}, night:{...}}`。P9 后端 `POST /api/collection/submit` 对 underground 已支持哪种结构需验证（AGENTS.md 记载采集是 4 类，需读 `app.py` 中 `api_collection_submit` 的 payload 解析）；**若后端只认双段结构，则单班次需后端配合，或保留双段但视觉改单班次段式呈现** |
| 钻工「单队长」vs「多队伍」 | 🟡 中 | 设计稿单队长单队伍；当前 `STATE._drSlots` 支持多队伍。后端 driller payload 结构需确认 |
| 出勤 8 状态（R/B） | 🟢 低 | `POST /attendance/toggle` 已支持 R/B（AGENTS.md 出勤状态字母含 R/B），仅前端 sheet 按钮补齐 |
| 员工档案「出勤统计/薪资概览」数据 | 🟡 中 | 设计稿 mini 卡数据来自哪？当前 `/api/employees/:id` 返回字段是否含 `attendance_days/leave_days/gross/net`？若缺需后端补字段或前端聚合 `/attendance` + `/salary` 数据 |
| `GET /attendance?month=` 参数 | 🟡 中 | 设计稿按 month 请求（`attendance.html:1581`）；当前 `loadAttendance` 无 month 参数（`mobile.html:623`）。需确认后端是否支持 month 过滤 |
| 月份左右点按切月 | 🟢 低 | 依赖 `/available-months` 存在性；已有 `/set-month` |

> 所有 🔴/🟡 风险项均需**后端读代码确认后再定稿重写方案**，建议重写前先让 team-lead 确认 P9 采集 payload 契约（`app.py` 中 `api_collection_submit`）。

---

## 6. 验收标准

### 6.1 数据台（Dashboard）

- [ ] 6 张 KPI 卡 2×3 网格，每卡左侧 3px 彩色指示条，色值 = 设计稿 `ind-i2/i4/i5/neutral`
- [ ] 「日最高」卡显示日期小字（kpi-sub）
- [ ] 筛选控制栏可折叠展开，含班次（全部/白班/夜班）+ 矿石类型（全部/NH/NL/MW）两组 Segmented
- [ ] 产量趋势图三线（白班/夜班/合计）带 legend；切换矿石类型/班次后图表与 KPI 联动刷新
- [ ] 白班 vs 夜班分组柱带 NH/NL/MW/合计 切换 tab
- [ ] 钻工组堆叠柱按班组上色，点击柱体弹出逐日明细 Sheet
- [ ] 矿石环形图中心显示总车次，右侧百分比 legend
- [ ] 破碎表三列（日期/袋数/人数）+ 合计行，背景 `--muted`
- [ ] 加载态骨架屏、错误态（⚠+重试）、空态（暂无产量数据）三态齐全
- [ ] 图表在 375px 不溢出、无横向滚动条

### 6.2 员工（Employees）

- [ ] 分段控制（员工列表/待审(N)/已审批）圆角 999px、待审带红色数字 badge
- [ ] 搜索框实时过滤（防抖 300ms），占位文案 i18n
- [ ] 员工卡：40px 头像 + 姓名（+en_name/别名）+ 工号 · 班组 + chevron，列表底部「显示 N 人」
- [ ] 骨架屏/错误（可重试）/空态三态齐全
- [ ] 档案页：80px 头像 + 姓名 + 别名/工号 tags + 基本信息 10 行 + 出勤统计 3 mini 卡 + 薪资概览 + 编辑档案按钮（admin+ 可见）
- [ ] 编辑档案 Modal（顶部圆角 sheet）：字段顺序与展示页一致，部门仅 super_admin 可改
- [ ] OA 待审卡：类型+人名+摘要+日期 + [批准][拒绝]，批准后列表即时移除
- [ ] 拒绝走专用 Modal（非 `prompt()`），必填原因
- [ ] OA 已审批：状态徽章 approved/rejected 区分

### 6.3 数据采集（Collection）

- [ ] 4 张 entry 大卡片：图标 + 标题 + 「本月已提交 N 条」+「上次提交」+「进入采集 ›」
- [ ] 最近提交历史：日期（含白/夜班标注）+ 类型 + 摘要
- [ ] 井下表单：单班次 toggle（白班(D)/夜班(N)）+ NH/NL/MW + 备注 + 备注2 + worker 多选 + 「已选 N 人」
- [ ] 表单内联校验错误（form-message 红字）+ 提交成功绿字提示 + 按钮「提交中...」loading 态
- [ ] 钻工表单：队长下拉（driller_captains）+ 队员多选 + 三产量数字
- [ ] 破碎表单：袋数（数字键盘）+ 人员多选 + 备注
- [ ] 出勤收集：部门筛选 + 全选出勤(P)/全选旷工(A) 批量按钮 + 人员状态 select + 「共 N 人」
- [ ] 提交后 toast + 自动返回采集首页 + 历史/计数刷新
- [ ] 数字输入 `inputmode="numeric"` 触发数字键盘

### 6.4 出勤（Attendance）

- [ ] Legend 图例条 8 色（D/N/P/A/L/C/R/B）显示
- [ ] 出勤卡：左侧固定信息栏（头像/姓名/工号）+ 右侧横向滚动日期条（28px 圆形状态格，色底 12% 透明度）
- [ ] 周末日期数字变淡；当前日期高亮
- [ ] 搜索 + 部门筛选 + 日期跳转前端过滤；月份左右点按切月
- [ ] 单格编辑 Sheet：8 状态按钮（P/A/L/D/N/C/R/B）+ 当前状态显示 + 取消
- [ ] 批量面板：员工勾选列表 + 日期范围（start~end）+ 状态选择 + 进度条 + 应用到选中
- [ ] 分页「加载更多」（每页 20 人）
- [ ] 快捷操作：+ 请假申请 / + 病假登记
- [ ] 加载骨架 / 错误重试 / 空态三态齐全

### 6.5 全局

- [ ] 4 Tab 图标统一 inline SVG，当前 Tab 高亮 `--primary`
- [ ] 顶栏：月份选择（Sheet）+ 搜索展开 + 语言胶囊 + 主题切换（决策项见 §6 待确认）
- [ ] 暗色模式：`.dark` token 与设计稿一致，`theme-color` 随主题更新
- [ ] i18n 全部文案中英双语，无中文硬编码残留
- [ ] 所有触摸目标 ≥44px，iOS 输入字号 16px 防缩放
- [ ] 无 CDN 运行时依赖，离线/弱网下静态资源可用

### 6.6 真机适配要求

| 平台 | 最低版本 | 验证点 |
|------|---------|--------|
| iOS Safari | **iOS 15**（2019-2021 主流机型，支持 `100dvh`、`env(safe-area-inset-*)`、`scroll-snap`） | 刘海屏 safe-area、底栏手势、日期 input 原生控件、横向滚动卡顿 |
| Android Chrome | **Chrome 90**（Android 9+） | `100dvh` 兼容回退 `100vh`、`-webkit-` 前缀、`inputmode` 数字键盘、长按误触 |
| PWA 安装 | iOS 主屏 + Android 添加至桌面 | 图标/名称/启动屏、`theme-color`、无 SW 时版本更新即刷新 |

> 注：`100dvh` 在 iOS 15.4+ 才完整支持，Android Chrome 108+ 原生支持；建议 CSS 写 `height: 100vh; height: 100dvh;` 双行回退（`mobile.css:170` 当前单用 `100dvh`，旧机型需回退）。

---

## 7. 待确认事项

1. **Tab 数量**：设计稿为 5-Tab（含「薪资」占位，`dashboard.html:544-547` 等 4 页均有），spec §2.1 与当前实现为 4-Tab。**薪资 Tab 是否纳入本次对齐？** 若纳入需新增薪资总表/日工资页面（+200-300 行）与后端 `/salary`、`/daily-wages` 对接。
2. **井下采集数据模型**：设计稿单班次 toggle vs 当前双段（Day+Night）提交。需读 `app.py` 的 `api_collection_submit` 确认 P9 后端 payload 契约，决定「单班次（需后端改）」还是「保留双段、视觉改单段式」。
3. **钻工采集多队伍**：设计稿单队长单队伍 vs 当前多队伍。是否保留多队伍能力（当前已实现且 P9 后端支持 `teams[]`）？
4. **员工档案「出勤统计/薪资概览」数据来源**：`/api/employees/:id` 是否返回聚合数据？需确认是否需要前端聚合 `/attendance` + `/salary`。
5. **字体决策**：接受「Inter 为主 + Fraunces 仅品牌/可选 KPI」的混合方案，还是完全跟随设计稿全局 Fraunces？
6. **i18n 统一策略**：以 `i18n.js` 的 `I18N_DICT` 为权威（删移动端内联 I18N），还是新建 `i18n.mobile.js` 独立字典？
7. **顶栏按钮**：设计稿 period-bar 无主题切换按钮（`dashboard.html:343-357`），当前有 🌙。是否保留主题切换（涉及暗色模式验收）？
8. **出勤「日期筛选」**：设计稿有日期 select（`attendance.html:368-371`）用于跳转，当前用 📅 按钮 + 日期 Sheet 实现。保留哪种交互？

---

## 8. 已确认决策（2026-08-14，用户拍板）

| # | 决策项 | 结论 | 影响 |
|---|--------|------|------|
| 1 | Tab 数量 | **4-Tab 保持现状**（数据台/员工/采集/出勤） | 不加薪资 Tab，不动 /salary、/daily-wages；设计稿 5-Tab 的「薪资」占位忽略 |
| 2 | 井下采集数据模型 | **保留双段结构**（day+night 同时填） | 后端契约 `app.py:1728-1729` 已是双段，零后端改动；视觉可优化为白/夜分段展示 |
| 3 | 钻工采集 | **保留多队伍 teams[]** | 后端 `app.py:1746` 已支持；视觉对齐设计稿单队长样式但支持多队 |
| 4 | 字体 | **Inter 为主 + Fraunces 仅品牌/可选 KPI**（设计师 §3.2 混合方案） | 补 `--font-display` token；保持 `--font-ui: Inter` |
| 5 | i18n | **统一到 `static/js/i18n.js` 的 I18N_DICT**，删除 mobile.html 内联 I18N | mobile.html `t()` 改读 `window.I18N_DICT`；新增 ~50 键（§4.3） |
| 6 | 主题切换 | **保留顶栏 🌙** | 设计稿 period-bar 无主题按钮，但保留（涉及暗色模式验收） |
| 7 | 出勤日期跳转 | **保留 📅 按钮 + 日期 Sheet** | 不采用设计稿 select 下拉 |
| 8 | 技术栈 | **自写 CSS + inline SVG**（不采用 Tailwind CDN） | 零新增依赖；图标统一 inline SVG，emoji 仅内容场景（§3.1 方案 B） |
| 9 | 暗色模式 | **mobile.css `.dark` 改为与设计稿一致** | 背景 `12 71.43% 1.37%`、ring `35.45 29.73% 70.98%` 等（§3.4） |
| 10 | 拆分策略 | **维持单文件 mobile.html，不拆分** | 目标 1600-2000 行（§5.1/5.3） |

> 重写实现（frontend-dev）必须遵守上表决策；🔴/🟡 风险项（§5.4）中井下/钻工已因保留双段+多队伍而消除，剩余风险为员工档案聚合数据与 `/attendance` 月份参数（前端聚合或后端补字段，实现时确认）。
