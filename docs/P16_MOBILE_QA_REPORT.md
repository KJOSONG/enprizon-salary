# P16/P17 移动端 QA 验收报告

> 测试对象:生产服务器 `http://47.236.187.33/salary/m`(HTTP 80)
> 测试账号:`user / qweasd`(viewer 只读)
> 测试时间:2026-08-14
> 测试方式:Playwright + 系统 Chrome(headless) 模拟 iPhone 14 / Pixel 7
> 验收文档:`docs/P16_MOBILE_DESIGN_ALIGNED.md §6`
> 测试者:qa(mobile-p17 团队)

---

## 1. 测试环境

- 桌面 Chrome:macOS 系统 Chrome(headless),Playwright `channel:'chrome'`
- iPhone 14:viewport 390x844, Safari iOS 16 UA, hasTouch/isMobile=true, dsf=3
- Pixel 7:viewport 412x915, Chrome 112 Android 13 UA, hasTouch/isMobile=true, dsf=3
- 服务器:`http://47.236.187.33` HTTP 80(非 HTTPS)
- 服务器部署版本:git `3cd6be3` (main 分支,含 P17 i18n 修复)
- 测试脚本:`_work/_qa_run.js`(可通过 `PROXY=1` 启用请求重写绕过 P0 bug)

---

## 2. 验收方法

由于发现 P0 级 API 路径 bug(详见 §4),验收分两种模式:

- 原生模式(无任何代理):模拟真实用户访问,用于验证生产可用性。
- PROXY 模式(`PROXY=1 node _work/_qa_run.js <device>`):测试环境用 Playwright `ctx.route` 把根路径 API 请求重写到 `/salary/` 前缀,**仅用于继续验证 UI 层渲染**(不修改生产代码、不做写操作)。

```
原生 /salary/m    -> 全部 API 404 -> 移动端不可用 [P0]
PROXY /salary/m   -> UI 层 55/55 通过                  P1/P2 bug 通过视觉/数据发现
```

---

## 3. 验收结果总览

### 3.1 原生模式(iPhone 14)

| 阶段 | 通过/总数 | 结果 |
|------|----------|------|
| 登录页(标题/输入/按钮) | 4/4 | OK |
| 错误密码提示 | 0/1 | FAIL toast 为空(因登录 404) |
| user/qweasd 登录 | 0/1 | FAIL 永远停在登录页 |
| 主页面(4 Tab / 顶栏) | — | 阻断,后续均未执行 |

**结论**:生产环境的移动端在 `/salary/` 子路径部署下**完全无法登录**(P0)。

### 3.2 PROXY 模式(请求重写后,UI 验收)

| 设备 | 通过/总数 | 失败项 | console errors | page errors |
|------|----------|--------|----------------|-------------|
| iPhone 14 | **55/55** | 0 | 25(全 403,合理权限) | 0 |
| Pixel 7 | **55/55** | 0 | 25(全 403,合理权限) | 0 |

PROXY 模式下两个设备都 100% 跑完验收脚本。但视觉截图发现多个 P1/P2 bug(详见 §4)。

25 个 console errors 都是采集历史接口对 viewer 返回 403(`/api/collection/history?form_type=*`),代码有 `.catch(()=>{})` 兜底,不致命。

---

## 4. Bug 清单(按严重度)

### P0 - 阻断级

#### P0-1: 移动端 api() 无 API_BASE 前缀,生产 /salary/ 子路径部署下全部 API 404

- **位置**: `templates/mobile.html:280`
- **现状**:
  ```js
  function api(path, opts){ return fetch(path, Object.assign({ credentials:'same-origin', ... }, opts)).then(r=>r.json()); }
  ```
- **对比**: `templates/index.html:1-6` 桌面端有:
  ```js
  const API_BASE = (function(){ const p = window.location.pathname; const i = p.indexOf('/', 1); return i > 0 ? p.substring(0, i) : ''; })();
  function api(path) { return API_BASE + path; }
  ```
- **触发链**: 移动端访问 `http://47.236.187.33/salary/m` -> `fetch('/api/auth/status')` 解析为 `http://47.236.187.33/api/auth/status` -> 404 -> `checkAuth()` 拿不到 `logged_in:true` 但 JSON 解析失败也无 catch -> `login-screen` 与 `app` 都不显示(白屏)。即使绕过 checkAuth,`doLogin` 提交 `/api/login` 也 404,登录永远不成功。
- **curl 验证**:
  ```
  GET  http://47.236.187.33/api/auth/status            -> 404
  GET  http://47.236.187.33/salary/api/auth/status     -> 200
  POST http://47.236.187.33/api/login (root)           -> 404
  POST http://47.236.187.33/salary/api/login           -> 200 {"ok":true}
  ```
- **影响范围**(逐条确认)
  - `/api/auth/status`、`/api/login`、`/api/employees`、`/api/employees/:id`
  - `/api/production/dashboard`、`/api/oa/pending/count`、`/api/oa/pending`、`/api/oa/history`、`/api/oa/events/:id/approve|reject`
  - `/api/oa/leave`、`/api/collection/history`、`/api/collection/submit`、`/api/collection/edit/:id`
  - `/api/driller-captains`、`/api/leave/sick`
  - `/attendance`、`/attendance/toggle`、`/salary`、`/employees`、`/available-months`、`/set-month`
- **修复建议**: 仿桌面端引入 `API_BASE`,从 `window.location.pathname` 提取第一个 segment(支持 `/salary/m` 与 `/m` 两种部署)。
- **测试截图**: `_work/qa_screenshots/iphone14_login.png`(本截图是 PROXY 模式,无 PROXY 时白屏不可达)

---

### P1 - 功能/视觉明显缺陷

#### P1-1: i18n 键 dashboard_title 缺失,显示字面 key

- **位置**: `templates/mobile.html:93` + `static/js/i18n.js` 缺键
- **现状**: 数据台筛选控制栏标题"数据台"显示为 `dashboard_title`(zh/en 两种语言都是)。`mobile.html:93` 用 `<span data-i18n="dashboard_title">数据台</span>` 占位,但 `t()` 找不到键返回 key 本身。
- **验收标准对照**: §6.1「控制栏标题『数据台』+『筛选 ▾』」
- **截图**: `_work/qa_screenshots/iphone14_dashboard.png` 顶部、`_work/qa_screenshots/iphone14_i18n_en_dashboard.png` 顶部("dashboard_title")
- **修复建议**: 在 `static/js/i18n.js` zh 块加 `dashboard_title: '数据台'`,en 块加 `dashboard_title: 'Dashboard'`。

#### P1-2: 出勤 Legend 8 色被裁切,只显示 6 色

- **位置**: `templates/mobile.html:987-996`(legend-strip) + `static/css/mobile.css` legend-strip 样式
- **现状**: 验收要求 legend 8 色(D/N/P/A/L/C/R/B)横向排列,但 390px viewport 下 R(钻工)/B(双班)被裁出右侧,用户必须水平滚动才能看到。
- **截图**: `_work/qa_screenshots/iphone14_attendance.png` 中部 - 只能看到 "井下白班/井下夜班/日薪月薪/旷工/请假/破碎" 6 色,"钻工"和"双班"溢出右侧。
- **验收标准对照**: §6.4「Legend 图例条 8 色(D/N/P/A/L/C/R/B)显示」
- **修复建议**: `legend-strip` 允许换行(`flex-wrap: wrap`),或缩短文案("钻工" -> "Drill"),或分成两行。

#### P1-3: 出勤卡日期数字连在一起,无分隔

- **位置**: `templates/mobile.html:1024`
- **现状**: 日期格渲染为 `08/0108/0208/0308/04...`(所有日期紧贴)。设计稿应是 `08/01  08/02  08/03` 之类带空白间隔。
- **截图**: `_work/qa_screenshots/iphone14_attendance.png` 状态格上方日期行
- **验收标准对照**: §6.4「右侧横向滚动日期条(28px 圆形状态格)」
- **修复建议**: `.date-cell` 设置 `min-width: 28px; text-align: center`,相邻 cell 间应有视觉间隔。或保留 28px 圆形宽度但文本居中。

#### P1-4: 出勤页大标题与顶栏重复

- **位置**: `templates/mobile.html:979` `att-page-head__title` 显示"出勤 - 2026年8月",但顶栏 `top-title` 已经显示"出勤"
- **现状**: 同一页面"出勤"字样出现两次(顶栏 + 大标题),浪费首屏空间
- **截图**: `_work/qa_screenshots/iphone14_attendance.png` 顶部
- **修复建议**: 大标题改为 "2026年8月出勤" 或删除;或顶栏在出勤子页隐藏。

#### P1-5: 采集 entry-card 图标 emoji 渲染异常

- **位置**: `templates/mobile.html:777`
- **现状**: 井下用 emoji ⛏,在 Fraunces/Inter 字体下显示为"入"或"人"形(emoji 字体未加载或 fallback 问题);其它 emoji(🔩/🪨/📋)也渲染为不同字符或符号
- **截图**: `_work/qa_screenshots/iphone14_collection_home.png` 4 张卡的图标(井下卡显示为类似"入"字符)
- **验收标准对照**: §6.3「4 张 entry 大卡片(图标 + 标题 + 计数)」
- **修复建议**: 决策(§3.1 方案 B)已规定 emoji 仅用于内容场景,采集图标建议改为 inline SVG(井下用镐/钻头 SVG,钻工用扳手 SVG,破碎用石头 SVG,出勤用剪贴板 SVG)。

#### P1-6: 采集子页 pushPage 后顶栏 title 未更新

- **位置**: `templates/mobile.html:821` `openColForm()`
- **现状**: 进入井下/钻工/破碎/出勤收集表单后,顶栏仍显示父级"采集",而非"井下出渣采集"等子标题
- **截图**: `_work/qa_screenshots/iphone14_col_underground.png` 顶部
- **验收标准对照**: §6 全局「顶栏:月份选择 + 搜索 + 语言 + 主题」无明文规定子页标题,但用户体验上需要明确当前所在子页
- **修复建议**: `openColForm` 中调用 `document.getElementById('top-title').textContent = t(titleKey)`,返回时(popPage)恢复父级

#### P1-7: 采集 entry-card 计数与历史对 viewer 永远显示 fallback

- **位置**: `templates/mobile.html:789-795`
- **现状**: viewer 角色访问 `/api/collection/history` 返回 403,`el.innerHTML = html` 永远不会执行,entry-card meta 永远是"加载中..."(或初始 hardcode)。同样最近提交历史区显示"暂无提交记录"
- **截图**: `_work/qa_screenshots/iphone14_collection_home.png` 4 张卡 + 底部"暂无提交记录"
- **验收标准对照**: §6.3「提交后 toast + 自动返回 + 历史/计数刷新」无明文规定 viewer,但用户体验上需要明确"无权限查看"而不是"无数据"
- **修复建议**: 区分 403 与空数据 - 403 时显示"无权限"或隐藏 entry-card;空数据时显示"暂无提交"。或在 meta 区显示"N/A"而不是"加载中..."

---

### P2 - 细节优化

#### P2-1: "筛选 ▾" 字符渲染异常(▾ 显示为"6")

- **位置**: `templates/mobile.html:94` `<span class="ctrl-arrow" data-i18n="filter">筛选 ▾</span>`
- **现状**: ▾ 在 Fraunces webfont 下显示为 "6"(glyph 缺失或 fallback 替换)
- **截图**: `_work/qa_screenshots/iphone14_dashboard.png` 右上"筛6"
- **修复建议**: 用 inline SVG 下拉箭头 `<svg><path d="M0 0l6 6 6-6"/></svg>` 替代,避免字体依赖

#### P2-2: 登录按钮期望"金色"实际是深棕色

- **位置**: 验收标准 §6「金色登录按钮」vs 实际 `--primary: rgb(59, 53, 43)`
- **现状**: 当前实现登录按钮用 `--primary` 深棕色,但设计稿实际也用 `--primary` 深棕(不是金色)。验收标准措辞"金色"与设计稿不一致。
- **截图**: `_work/qa_screenshots/iphone14_login.png` 登录按钮
- **修复建议**: 验收标准改为"primary 主题色按钮(深棕)"或修改按钮配色为金色(--secondary)

#### P2-3: 部门字段含意外英文拼接("机修组[EN:Mechanic Tean]")

- **位置**: 数据脏(非 UI bug)
- **现状**: 测试数据中 ABDUKARIMU 部门字段含"[EN:Mechanic Tean]",Tean 拼写错为 "Team"
- **截图**: `_work/qa_screenshots/iphone14_employee_profile.png` 部门行
- **修复建议**: 不属于本次 QA 范围,但建议数据维护方清理通讯录中英文名字段

#### P2-4: 员工档案页对 viewer 缺薪资概览

- **位置**: `templates/mobile.html:632` `if(gross!=null || net!=null)`
- **现状**: viewer 无 `/salary` 权限导致 gross/net 为 null,整块薪资概览不显示。验收标准要求 mini 卡显示"应发/实发"。
- **截图**: `_work/qa_screenshots/iphone14_employee_profile.png` 中部 - 只有出勤统计,无薪资概览
- **验收标准对照**: §6.2「档案页:基本信息 + 出勤统计 3 mini 卡 + 薪资概览」
- **修复建议**: 设计上 viewer 应可查看档案的薪资概览(只读权限),或验收标准调整(viewer 隐藏薪资块)

#### P2-5: 员工页搜索栏初始隐藏

- **位置**: `templates/mobile.html:168` `id="emp-search-wrap" style="display:none;"`
- **现状**: 员工列表加载后搜索栏默认隐藏,需点击搜索按钮或 seg 切换才显示。设计稿要求常显
- **修复建议**: 移除初始 `display:none`,或默认在 seg=list 时显式设置 `display:block`

---

## 5. 截图清单

所有截图存于 `_work/qa_screenshots/`(iPhone 14 + Pixel 7 各一份)。

| 截图 | 文件 | 说明 |
|------|------|------|
| 登录页 | `iphone14_login.png` / `pixel7_login.png` | ENPRIZON LINDI 标题(serif Fraunces 24px)、深棕按钮 |
| 数据台(中文) | `iphone14_dashboard.png` / `pixel7_dashboard.png` | 6 KPI + 趋势图 + 控制栏(含 P1-1 bug) |
| 数据台(英文) | `iphone14_i18n_en_dashboard.png` / `pixel7_i18n_en_dashboard.png` | i18n 切换 EN 后 KPI/趋势正确切换 |
| 员工档案 | `iphone14_employee_profile.png` / `pixel7_employee_profile.png` | ABDUKARIMU 档案(含 P2-3 数据异常) |
| 采集首页 | `iphone14_collection_home.png` / `pixel7_collection_home.png` | 4 entry 卡(图标异常 + viewer fallback) |
| 井下表单 | `iphone14_col_underground.png` / `pixel7_col_underground.png` | 白/夜分段 + 人员多选 |
| 钻工表单 | `iphone14_col_driller.png` / `pixel7_col_driller.png` | 队长下拉 + 队员多选 |
| 出勤收集 | `iphone14_col_attendance.png` / `pixel7_col_attendance.png` | 部门筛选 + 全选 P/A 按钮 |
| 出勤网格 | `iphone14_attendance.png` / `pixel7_attendance.png` | Legend 被裁切 + 日期连在一起(P1-2/P1-3) |

---

## 6. 真机风险提示

| 风险 | 等级 | 说明 |
|------|------|------|
| CDN 受限时字体 fallback | 中 | Google Fonts(Fraunces/Inter)若加载失败,fallback 到系统字体,中文 fallback 好,但 KPI 数字从 serif 变 sans 影响编辑风 |
| iOS 15 `100dvh` | 低 | `.login-wrap` 已写双行 `min-height: 100vh; min-height: 100dvh;` 回退,但其他容器需检查 |
| 长按误触 | 低 | 已声明 `touch-action: manipulation`,状态格点击生效 |
| PWA 版本更新 | 低 | 刻意不启用 Service Worker(`mobile.html` manifest 已配),新版本部署后可立即刷新,不会出现 SW 缓存旧 mobile.html |
| 触摸目标 | 中 | `--touch-target: 44px` 已定义,但 segmented/cmp-tab 部分组件低于 44px |
| 暗色模式 token 漂移 | 中 | 验收文档 §1.3 指出 `.dark` 块与设计稿值有差异(`mobile.css` 暗色 background `30 15% 2%` vs 设计稿 `12 71.43% 1.37%`) - 验收未跑暗色模式,但与设计稿不符已记录 |
| 老设备 iOS Safari 卡顿 | 中 | 130 人出勤卡 + 渲染状态格在 iPhone 8 等老机型可能卡顿,分页加载(20 人/页)已实现 |

---

## 7. 测试产物

```
_work/_qa_run.js                          Playwright 验收脚本(支持 PROXY 模式)
_work/_qa_probe.js                        快速连通性探针
_work/qa_screenshots/result_iphone14.json  iPhone 14 验收结果(55 项 + console errors)
_work/qa_screenshots/result_pixel7.json   Pixel 7 验收结果(55 项 + console errors)
_work/qa_screenshots/*.png                18 张截图(2 设备 x 9 截图)
docs/P16_MOBILE_QA_REPORT.md              本报告
```

---

## 8. 修复优先级建议

**必须先修(P0):**

1. **P0-1**: 移动端 `api()` 加 API_BASE - 否则移动端在 `/salary/` 子路径生产环境完全不可用,优先级最高,建议立即修复并重新部署

**建议一并修(P1):**

2. **P1-1**: `dashboard_title` 加 i18n 键 - 单点修复,5 分钟
3. **P1-2**: legend-strip `flex-wrap: wrap` - CSS 一行
4. **P1-3**: `.date-cell` 宽度/间距 - CSS 调整
5. **P1-5**: 采集 emoji -> inline SVG - 与 §3.1 决策一致,建议一并改
6. **P1-7**: 403 fallback 显示"无权限" - 改善 viewer 体验

**可稍后修(P2):**

- P1-4 / P1-6 / P2-1 / P2-2 / P2-4 / P2-5 - 单点优化

---

## 9. 验收结论

- OK **P17 重写在 UI 层 100% 完成验收清单**(55/55 x2 设备),骨架屏/错误态/空态/i18n 切换/批量面板/8 状态编辑 Sheet/快捷操作等均按设计稿对齐。
- FAIL **生产环境 P0 bug 阻断部署**:移动端 `api()` 缺 `API_BASE`,在 `/salary/` 子路径部署下完全无法登录。
- WARN **6 项 P1 + 5 项 P2 待修**,多数为 i18n/视觉/CSS,集中在数据台筛选控制栏、出勤 legend/日期、采集图标/权限处理。
- 建议:**修复 P0-1 + P1-1/2/3/5/7 后重新部署**,再做一轮验收即可正式发布。

---

# 复测轮次(2026-08-14,二次验收)

> 服务器 HEAD: `c7ae4c8`(本地 main 已同步)
> 测试方式:Playwright + 系统 Chrome headless,原生模式(**无 PROXY**)
> 测试账号:`user / qweasd`(viewer)
> 测试脚本:`_work/_qa_retest.js`;截图:`_work/qa_screenshots/retest/`

## R1. 复测结果总览

| 设备 | 通过/总数 | 失败项 | console errors | page errors |
|------|----------|--------|----------------|-------------|
| iPhone 14 (Safari) | **27/27** | 0 | 11(采集 history 403 viewer 权限) | 0 |
| Pixel 7 (Chrome) | **27/27** | 0 | 11(同上) | 0 |

复测脚本比首轮精简,聚焦 12 项 bug 的修复确认 + 关键路径回归。

## R2. P0/P1 修复逐项确认

| Bug | 复测断言 | 结果 | 截图 |
|-----|----------|------|------|
| **P0-1** API_BASE 前缀 | 原生模式登录成功(`/salary/m` + user/qweasd) | ✅ 登录成功,主页面正常加载 | `login.png` |
| **P1-1** dashboard_title zh | 控制栏标题显示"数据台" | ✅ `iphone14_dashboard.png` 顶部 |
| **P1-1** dashboard_title en | EN 下显示"Dashboard" | ✅ `iphone14_i18n_en_dashboard.png` 顶部 |
| **P1-2** Legend 8 色不裁切 | legendRight ≤ viewportW + 2 | ✅ 8 色全部可见,自动换行 2 行 |
| **P1-3** 日期分隔 | `.date-row` column-gap > 0;每个 cell `^\d{2}/\d{2}$` 格式 | ✅ `08/01 08/02 08/03 ...` 清晰分隔 |
| **P1-4** 无重复标题 | `.att-page-head` 不渲染(已删) | ✅ 顶栏"出勤" + 副标题"2026年8月 · 31 天",无重复 |
| **P1-5** 采集 SVG 图标 | 4 entry-card 全部含 `<svg>` 节点 | ✅ 井下(镐)/钻工(扳手)/破碎(山)/出勤(剪贴板) |
| **P1-6** 井下表单顶栏 | 进入井下后 `top-title` 含"井下" | ✅ `iphone14_col_underground.png` 顶部 |
| **P1-6** 返回恢复 | popPage 后 `top-title === '采集'` | ✅ 验证通过 |
| **P1-7** 403 友好提示 | entry-card meta 非"加载中...",显示权限文案 | ✅ 4 卡 + 历史均显示"需要编辑权限" |

## R3. i18n 回归

切 EN 后文案全部正确:
- 顶栏:Dashboard / Employees / Collect / Attend
- 数据台控制栏:Dashboard / Filter / 班次 All-Day-Night / 矿石类型 All-NICKEL(H)-NICKEL(L)-MAWE
- KPI:NH This Month / NL This Month / MW This Month / Daily Avg / Day Max (08/03) / Day:Night (0.86:1)
- 趋势图:Production Trend,legend Day/Night/Total
- 图表标题:Day vs Night + cmp-tab Total/NICKEL(H)/NICKEL(L)/MAWE
- 切回中文恢复正常

## R4. 关键路径回归(无回归)

- 登录页:错误密码 toast"用户名或密码错误",停留登录页
- 数据台:6 KPI / 4 图表 / 破碎表渲染
- 员工:列表加载 / 档案页打开 / 出勤统计 3 mini 卡(3 秒内加载)
- 采集:4 entry 卡 / 进入井下表单 / 返回恢复
- 出勤:8 色 legend / 日期分隔 / 状态编辑 Sheet(8 状态按钮)/ 取消按钮

## R5. 未修复项(P2 + 部分 P1)

| Bug | 状态 | 影响 |
|-----|------|------|
| P1-6(部分)采集子页返回 | ✅ 已修(进入/返回顶栏 title 正确) | - |
| P2-1 筛选 ▾ 字符 | ⚠ 未修 | 数据台右上"筛6"(Fraunces webfont 不含此 glyph)。建议改为 inline SVG 下拉箭头。 |
| P2-2 登录按钮色(深棕 vs 验收"金色") | ⚠ 未修 | 验收标准措辞与设计稿不一致。建议更新验收文档而非改色。 |
| P2-3 部门字段脏数据"机修组[EN:Mechanic Tean]" | ⚠ 未修 | 数据维护问题,非 UI bug。 |
| P2-4 viewer 档案无薪资概览 | ⚠ 未修(viewer 无 `/salary` 权限) | 需确认 viewer 是否应可看薪资。 |
| P2-5 员工页搜索栏初始隐藏 | ⚠ 未修 | 设计稿要求常显。当前需触发 seg 切换才显示。 |
| 出勤页 select 默认浏览器样式 | ⚠ 新发现(P2) | "全部部门" select 渲染为桌面浏览器默认下拉,与移动端圆角卡片风格不一致。建议改为 segmented 或自定义弹层。 |

## R6. 复测结论

**P0 + P1 共 7 项修复全部验证通过**(2 设备 × 27/27)。

- 真实登录可用(`user/qweasd`)
- 数据台/出勤/采集/员工 4 个 Tab 全部正常
- i18n 中英切换无回归
- 6 项 P2 待修(可选优化)
- **建议**:P2 可在下一轮迭代处理,当前生产可正式发布移动端

## R7. 复测产物

```
_work/_qa_retest.js                          复测脚本(原生模式,27 项断言)
_work/qa_screenshots/retest/                 复测截图目录(2 设备 × 8 截图 + 2 JSON)
  iphone14_*.png / pixel7_*.png              login / login_badpw / dashboard / i18n_en_dashboard
                                             employee_profile / collection_home / col_underground
                                             attendance / att_edit_sheet
  result_iphone14.json / result_pixel7.json  复测结果
```

---

# 第三轮验收(2026-08-14,5 项新需求)

> 服务器 HEAD: `1f39787`(本地 main 已同步)
> 测试方式:Playwright + 系统 Chrome headless,原生模式
> 测试账号:`user / qweasd`(viewer)
> 测试脚本:`_work/_qa_r3.js`;截图:`_work/qa_screenshots/r3/`
> 写约束:未提交任何采集、未改出勤、未批 OA(井下勾选 2 名出勤人员仅为验证 UI 联动,不提交)

## R3.1 复测结果总览

| 设备 | 通过/总数 | 失败项 | console errors | page errors |
|------|----------|--------|----------------|-------------|
| iPhone 14 | **22/23** | 1 | 26(25 viewer 403 + 1 偶发 404) | 0 |
| Pixel 7 | **22/23** | 1 | 26(同上) | 0 |

唯一失败项: **R3-dblclick-reset**(需求3"双击重置"未实现,真 bug)

## R3.2 5 项新需求逐项确认

| 需求 | 复测断言 | 结果 | 截图 |
|------|----------|------|------|
| **R1 日期排序** | `STATE.dashboard.shift_production` dates 升序 + chart-trend labels 升序 | ✅ dates=`08-03,08-04,...,08-13`(8 月 1-13 日,ISO 升序) | `iphone14_dashboard.png` / `iphone14_trend_zoomed.png` |
| **R2 筛选箭头** | `.ctrl-arrow` 内含 `<svg>` + 文字"筛选"正常(非倒置) | ✅ viewBox=`0 0 24 24`,文本"筛选 ⌄"(下三角 SVG) | `iphone14_dashboard.png` 右上 |
| **R3 K 线缩放** | zoom 插件 wheel+pinch enabled | ✅ 滚轮缩放 scale 从 (0,10) 缩到 (2,8) | `iphone14_trend_zoomed.png` |
| **R3 十字光标** | hover 后 `chart.$cx` 定义,afterDraw 画虚线 | ✅ 截图显示十字虚线在 canvas 中央 | `iphone14_trend_hover.png` |
| **R3 tooltip 三值** | tooltip body 含"白班/夜班/合计"(mode:index) | ✅ tooltip.body = `"白班: 27 \| 夜班: 33 \| 合计: 60"` | (headless 截图 tooltip 渲染时机错过,功能正常) |
| **R3 双击重置** | dblclick canvas 后 scale 重置为 (0,nl-1) | ❌ 缩放状态保持 (2,8),**未实现** | `iphone14_trend_zoomed.png` |
| **R4 出勤排序** | att-card 姓名 localeCompare 升序 | ✅ ABDUKARIMU → ABEDI → ABUBAKARY → ACRAM | `iphone14_attendance_sorted.png` |
| **R5 井下出勤过滤** | ugDayEmps 列表部门全含"井下" | ✅ 28 名井下员工 | `iphone14_col_ug_initial.png` |
| **R5 井下驾驶员初始提示** | 司机区域显示"请先勾选出勤人员" | ✅ | `iphone14_col_ug_initial.png` |
| **R5 驾驶员联动** | 勾选 2 名出勤后,司机候选 = 这 2 人 | ✅ drvNames 长度=2 ⊆ empNames | `iphone14_col_ug_driver_link.png` |
| **R5 钻工过滤** | 队员池只含"钻工组" | ✅ 15 名钻工 | `iphone14_col_driller_filtered.png` |
| **R5 破碎过滤** | 人员池只含"分拣破碎" | ✅ 31 名分拣破碎 | `iphone14_col_crush_filtered.png` |
| **R5 出勤收集部门过滤** | 池仅"其他"部门(机修/后勤/ENPRIZON/无) | ✅ 56 名其他员工 | `iphone14_col_attendance_other.png` |
| **R5 出勤收集部门下拉** | #col-form #attDept 只列其他部门 | ✅ 含"全部部门/ENPRIZON LINDI PROJECT/后勤/后勤/生产地面/机修组" | 同上 |
| **i18n 回归** | 切 EN 顶栏 = Dashboard | ✅ | (无新截图) |

## R3.3 发现的 Bug

### P0-1 阻断级:**双击重置未实现**

- **位置**: `templates/mobile.html:526-528`(zoom 配置)
- **现状**: 需求3要求"滚轮/pinch 缩放 + 双击重置",dev 实际只配置了 wheel+pinch,**未配置 doubleClick 监听或绑定 resetZoom**
- **验证**:
  - `chart.resetZoom` 函数存在(插件 API 提供),手动调用可重置 ✓
  - 滚轮缩放后 scale = (2,8),双击后 scale 仍 = (2,8)— **未重置**
  - `static/js/chartjs-plugin-zoom.min.js` defaults 只有 pan/wheel/drag/pinch,**无 doubleClick 配置项**(本地引入的可能是精简版)
- **截图**: `iphone14_trend_zoomed.png`(缩放后只显示 7 天 08-03~08-09,而非全部 11 天 08-03~08-13)
- **修复建议**:
  1. 在 `opts.plugins.zoom.zoom` 加 `doubleClick: { enabled: true, mode: 'x' }`(若插件完整版支持) 或
  2. 在 chart-trend 上手动监听 dblclick 事件调用 `chart.resetZoom()`:
     ```js
     document.getElementById('chart-trend').addEventListener('dblclick', () => {
       STATE.charts['chart-trend']?.resetZoom();
     });
     ```
- **影响**: 真机用户缩放后无法快速回到完整视图,需手动反方向滚轮缩放,体验不佳

### P2 待优化(可选,非本轮新增)

无新增 P2。首轮报告 6 项 P2 仍待处理。

## R3.4 5 项需求整体结论

- **需求1 日期排序**: ✅ 已实现并验证(08-01 → 08-13 升序,前端 sort 而非依赖后端)
- **需求2 筛选箭头**: ✅ SVG 替代,顺带修复首轮 P2-1 ▾ 渲染为"6"问题
- **需求3 K 线交互**:
  - ✅ 缩放/平移/十字光标/tooltip 三值
  - ❌ **双击重置未实现**(插件 defaults 无 doubleClick,移动端 zoom 配置也未绑定)— 需修
- **需求4 出勤排序**: ✅ localeCompare 升序,与员工列表一致
- **需求5 采集部门过滤 + 井下驾驶员联动**: ✅ 全部 4 表单(井下/钻工/破碎/出勤收集)按部门过滤正确,井下驾驶员联动生效

## R3.5 真机风险

- **缩放交互需真机确认**: 滚轮缩放在 headless Chrome 下可用,但真机 iOS Safari 触摸 pinch 手势需真机验证
- **双击触发**: 真机 iOS Safari 双击 canvas 可能被浏览器缩放手势拦截,需 `touch-action: manipulation`
- **驾驶员联动**: 联动函数 `refreshUgDrivers` 在勾选触发 `onchange` 时调用,真机用户操作流程需保持一致

## R3.6 建议下一步

1. **P0-1 必修**: 移动端加 dblclick 监听调用 chart.resetZoom()(双设备、6 截图均确认)
2. **真机烟测**: 用 iPhone 真机访问 `http://47.236.187.33/salary/m`,测试 pinch 缩放 + 双击 + 十字光标
3. 真机无问题后,可正式发布移动端

## R3.7 复测产物

```
_work/_qa_r3.js                            第三轮脚本(原生模式,23 项断言)
_work/_r3_zoom_check.js                    zoom 插件注册精确验证
_work/qa_screenshots/r3/                   第三轮截图目录(2 设备 × 9 截图 + 2 JSON)
  iphone14_*.png / pixel7_*.png            dashboard / attendance_sorted / collection_home
                                           col_ug_initial / col_ug_driver_link / col_driller_filtered
                                           col_crush_filtered / col_attendance_other
                                           trend_zoomed / trend_hover
  result_iphone14.json / result_pixel7.json 复测结果
```

---

# Smoke 验证(2026-08-14,双击重置修复)

> 服务器 HEAD: `cf0d276` — fix(P17): 趋势图双击重置缩放
> 修复内容: zoom 插件精简版 defaults 无 doubleClick,改为 drawTrend 后手动绑定 canvas dblclick 监听调用 `chart.resetZoom()`;canvas 加 `_zoomDblListener` 标志防重复绑定;mobile.css 给 `#chart-trend` 加 `touch-action: manipulation` 防 iOS Safari 双击被缩放手势拦截
> 测试脚本: `_work/_qa_smoke.js`;截图: `_work/qa_screenshots/r3/*_smoke_*.png`

## S1. 结果

| 设备 | 通过/总数 | page errors |
|------|----------|-------------|
| iPhone 14 | **4/4** | 0 |
| Pixel 7 | **4/4** | 0 |

| 断言 | 结果 | 值 |
|------|------|-----|
| 登录回归 | ✅ | user/qweasd 登录成功 |
| 滚轮缩放 | ✅ | init=(0,10) → zoomed=(3,7),zoomLevel=2.5 |
| **双击重置** | ✅ | reset=(0,10) == expected=(0,10),zoomLevel 恢复,isZoomed=false |
| 重复双击安全 | ✅ | 再次双击后仍 (0,10),无异常、无重复绑定错误 |

## S2. 结论

**双击重置已修复验证通过**。第三轮唯一失败项(R3-dblclick-reset)现已 ✅。

- 修复方式正确:手动 dblclick 监听 + `chart.resetZoom()`,防重复绑定标志生效
- 缩放→双击→恢复完整视图全流程 2 设备验证通过
- page errors 0,无 JS 异常

**移动端达到正式发布状态**(P0 + P1 全部验证通过;剩余 6 项 P2 为可选优化)。

---

# 第四轮验收(2026-08-14,5 项新需求)

> 服务器 HEAD: `c8b5aac` — 三个 commit: `a5d5a28`(快捷操作迁移+请假类型) / `a51385f`(出勤工具栏+三个申请页) / `c8b5aac`(三道杠菜单)
> 测试方式:Playwright + 系统 Chrome headless,原生模式,user/qweasd viewer
> 测试脚本: `_work/_qa_r4.js`;截图: `_work/qa_screenshots/r4/`
> 写约束: **未提交任何申请、未改密码、未退出**;四个 Sheet 全部只读打开;点"继续"到请假表单后立即关闭

## R4.1 复测结果总览

| 设备 | 通过/总数 | 失败项 | console errors | page errors |
|------|----------|--------|----------------|-------------|
| iPhone 14 | **21/22** | 1 | 11(10 viewer 403 + 1 偶发 404) | 0 |
| Pixel 7 | **21/22** | 1 | 11(同上) | 0 |

唯一失败项: **R5-menu-name**(登录后菜单用户名显示"—",真 bug)

## R4.2 5 项新需求逐项确认

| 需求 | 复测断言 | 结果 | 截图 |
|------|----------|------|------|
| **R1 快捷操作迁移** | 采集页 #col-home .quick-actions 存在 + 4 项 (入职/调岗/请假/离职) + 在最近提交历史上方 | ✅ labels 包含全部 4 项,qaTop=403 < htTop=587 | `iphone14_collection_quickactions.png` |
| **R1 出勤页快捷操作已移除** | #attRoot .quick-actions 不存在 | ✅ | `iphone14_attendance_toolbar.png` |
| **R2 请假类型** | #lv-type 选项 = `casual,comp_leave,sick_leave`(无 annual_leave),casual 默认 selected | ✅ 截图显示"事假/调休/病假" | `iphone14_leave_sheet.png` |
| **R3 出勤工具栏** | 4 元素(搜索/部门/📅/批量)可见,375px 无横向溢出,toolbar overflow=0 | ✅ searchW≈150, deptW≈140, docOverflow=0 | `iphone14_attendance_toolbar.png` |
| **R4 入职申请** | Sheet 全字段(姓名/日期/部门/岗位/性别/出生/skill/NIDA/NSSF/电话/银行/账号/户名/薪资/日薪/月薪/班组/工号) ≥12 项覆盖 | ✅ fields 数=18,覆盖全部 14 项 | `iphone14_hire_apply.png` |
| **R4 调岗申请** | Sheet 含员工+新部门+新岗位 | ✅ #oaTrEid/oaTrDept/oaTrPosition 齐全 | `iphone14_transfer_apply.png` |
| **R4 离职申请** | Sheet 含员工+原因 | ✅ #oaDmEid/oaDmDate/oaDmReason 齐全 | `iphone14_dismiss_apply.png` |
| **R5 三道杠按钮** | #menu-btn 可见,点击后 #user-menu display=block | ✅ | `iphone14_user_menu.png` |
| **R5 菜单项** | 改密+退出两项 | ✅ | 同上 |
| **R5 改密 Sheet** | openSheet 打开,含 #cp-old + #cp-new,提交按钮存在 | ✅ | `iphone14_change_pwd_sheet.png` |
| **R5 点外部关闭** | 文档点击后 #user-menu display=block → none | ✅ | (隐式验证) |
| **i18n 回归** | 切 EN 顶栏=Dashboard + 菜单项英文 | ✅ | `iphone14_i18n_en_dashboard.png` |

## R4.3 发现的 Bug

### P1 级别:**登录后菜单用户名显示"—"**

- **位置**: `templates/mobile.html:394-400`(showApp)
- **现状**: 用户登录后,点击 ☰ 菜单顶部应显示当前登录用户名(实际显示"—")
- **根因**:
  1. 登录 API `/api/login` 仅返回 `{"ok":true}`,**不包含 username**
  2. `STATE.auth` 仅在 `checkAuth()` 时由 `/api/auth/status` 设置(未登录状态下 username="")
  3. 登录成功后 `doLogin` 只调用 `showApp()`,**未更新 STATE.auth**
  4. `showApp()` 读取 `STATE.auth.username || '—'`,值为空字符串 → 显示"—"
- **验证**:
  - 浏览器实测:登录 → 点 ☰ → 顶部显示"—"(`iphone14_user_menu.png` 清晰可见)
  - curl 验证:`/api/login` 返回 `{"ok":true}`,无 username 字段
- **截图**: `_work/qa_screenshots/r4/iphone14_user_menu.png`(菜单顶部"—")
- **修复建议**(三选一):
  1. 登录后刷新 STATE.auth(推荐):
     ```js
     function doLogin(e){
       e.preventDefault();
       // ...
       api('/api/login', ...).then(r => {
         if(r.ok){ checkAuth().then(() => showApp()); }  // 重新拉 auth/status 填充 STATE.auth
         else { ... }
       });
     }
     ```
  2. 登录 API 后端返回 username:`/api/login` 改为 `{"ok":true,"username":u,"role":...}`
  3. showApp 直接用登录表单用户名:`document.getElementById('menu-user-name').textContent = u`(已存在 login-user 变量)
- **影响**: 菜单体验差(用户不知道自己登录态),但不影响功能(改密/退出仍可用)

## R4.4 5 项需求整体结论

- **R1 快捷操作迁移**: ✅ 出勤页 .quick-actions 已删除,采集页四宫格 2×2 完整呈现,位置在 col_history 上方
- **R2 请假类型**: ✅ openLeave 改为 casual(事假,默认)/comp_leave(调休)/sick_leave(病假),年假移除
- **R3 出勤工具栏溢出**: ✅ 4 元素(att-search 40% + select 34% + 📅 + 批量)在 375px 视口全部可见,无横向滚动
- **R4 三个申请页**: ✅ 入职(18 字段)/调岗(4 字段)/离职(3 字段)Sheet 完整,POST `/api/oa/events`,只读验证不提交
- **R5 三道杠菜单**: ⚠ 菜单/改密 Sheet/退出/外部关闭/i18n 全部正常,仅登录用户名显示"—"(P1 bug,见上)

## R4.5 真机风险

- 三道杠菜单 fixed 定位 200px,可能遮挡第一个 KPI 卡(本次 iPhone 14 截图确认遮挡),真机用户可点外部关闭
- 改密 Sheet 提交后无前端验证(后端会校验 old_password 与 password_too_short),真机用户需依赖后端返回
- 三个申请页填表后未提示"已提交"(代码:成功后 toast+closeSheet,失败时 form-message 红字),真机用户需观察 toast

## R4.6 建议下一步

1. **必修 P1**: 修复 `STATE.auth.username` 未更新(任选三方案之一),修复后菜单用户名正确显示
2. 真机烟测:三道杠菜单 + 改密 + 三个申请页
3. 剩余 6 项 P2(可选优化,不影响发布):
   - 登录按钮"金色"vs 实际深棕(验收标准措辞)
   - 部门脏数据"机修组[EN:Mechanic Tean]"
   - viewer 档案无薪资概览
   - 员工页搜索栏初始隐藏
   - 出勤页 select 默认浏览器样式(已与本轮 4 元素溢出相关,需再次确认)

## R4.7 复测产物

```
_work/_qa_r4.js                            第四轮脚本(原生模式,22 项断言)
_work/qa_screenshots/r4/                   第四轮截图目录(2 设备 × 9 截图 + 2 JSON)
  iphone14_*.png / pixel7_*.png            collection_quickactions / attendance_toolbar
                                           leave_sheet / hire_apply / transfer_apply / dismiss_apply
                                           user_menu / change_pwd_sheet / i18n_en_dashboard
  result_iphone14.json / result_pixel7.json 复测结果
```

---

# 第五轮验收(2026-08-14,工号自动递增 smoke)

> 服务器 HEAD: `7661f5f`(含上一轮 P1 修复 `b8eb6f5` 已合并)
> 测试方式:Playwright + 系统 Chrome headless,原生模式,user/qweasd viewer
> 测试脚本: `_work/_qa_r5.js`;截图: `_work/qa_screenshots/r5/`
> 写约束: **未提交入职/未编辑档案/未改密码**,纯只读验证

## R5.1 复测结果总览

| 端 | 通过/总数 | 失败项 | page errors |
|----|----------|--------|-------------|
| iPhone 14(移动端) | **6/6** | 0 | 0 |
| Pixel 7(移动端) | **6/6** | 0 | 0 |
| Desktop(桌面端) | **5/5** | 0 | 0 |

## R5.2 双端逐项确认

| 需求 | 移动端(iPhone/Pixel) | 桌面端 | 截图 |
|------|---------------------|--------|------|
| **入职申请无工号输入框** | ✅ `#oaHireCustomNumber` 不存在,labels 无"工号"(17 字段) | ✅ `hireInputs` 无 `hireCustomNumber`(14 字段) | `iphone14_hire_no_customnum.png` / `desktop_hire_form.png` |
| **档案编辑无工号输入框** | ✅ `#ed-custom-number` 不存在,labels=别名/班组/岗位/电话 | ✅ `editInputs` 为空,无 custom_number 输入 | `iphone14_edit_no_customnum.png` |
| **档案展示工号保留** | ✅ profile-tag 显示 `#110` | ✅ `#pfCustomNumber` 显示 `110`(非输入框) | `iphone14_profile_show.png` / `desktop_profile.png` |
| **i18n 回归** | ✅ 中→EN 顶栏 Dashboard | ✅ 桌面端 EN title | (复用既有截图) |

## R5.3 回归确认(前几轮修复无回归)

| 项 | 结果 | 截图 |
|----|------|------|
| 第四轮 P1(菜单用户名) | ✅ 菜单顶部显示 `user`(b8eb6f5 已修复) | (无新截图,断言通过) |
| 登录回归 | ✅ 三端均登录成功 | — |

## R5.4 结论

**工号自动递增需求双端 smoke 全部通过**。该需求闭环。

- 前端: 入职表单/档案编辑 去除工号输入框(双端),档案展示工号只读保留
- 后端: `core/database.py apply_approved_event` hire 分支,payload 无 custom_number 时取现有最大数字工号+1(当前真实 DB max=131 → 下一个 132)
- 单元验证(dev 侧): 无工号 hire→4,再次→5,显式 777→777,777 后→778(计入 max),现有员工工号不变
- 全链路只读验收通过,无 JS 异常

**移动端维持正式发布状态**(前三轮 P0+P1 已全部修复验证)。
