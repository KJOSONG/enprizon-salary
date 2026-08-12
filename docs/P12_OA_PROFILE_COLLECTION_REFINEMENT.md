# P12 阶段详设 — OA 子页化 / 员工档案页 / 数据采集修正 / 系统清理收尾

> **状态**：v1（2026-08-12，v4 验收后 10 条有效反馈定稿）
> **最后更新**：2026-08-12
> **依赖**：`REFACTOR_SPEC.md` v5（PRD §0.1 / §5 / §11-P12 / §13 验收）、`DEV_WORKFLOW.md`、`docs/P0_DATA_MODEL_AND_API.md`
> **定位**：本文档是 P12 的实施对照清单，逐条列出"现状代码 → v5 目标 → 改动点"。代码会变、目标不变。

---

## 0. 反馈清单索引（用户原话编号 → PRD v5 编号）

| 用户编号 | PRD v5 编号 | 主题 | 状态 |
|----------|-------------|------|------|
| 1 | #1 / D30 | OA 三申请升格平级子页；入职申请=完整档案表单 | 待实施 |
| 2 | #2 / D31 | 员工档案独立完整页 + 简历尺寸头像 | 待实施 |
| 3 | #3 / D32 | 档案页三类假期余额显示且可修改 | 待实施 |
| 5（第一个） | #5a / D33 | 姓名可选中复制，点击才跳转 | 待实施 |
| 4 | #4 / D34 | 井下出渣采集三列标签 + Day/Night 双备注 | 待实施 |
| 5（第二个） | #5b / D35 | 钻工队长名单化 + "添加队伍"先选队长 | 待实施 |
| 6 | #6 / D36 | 评分模块改名"评分系统"，补 i18n | 待实施 |
| 7 | #7 / D37 | 驾驶勾选移到井下采集；出勤收集按部门 | 待实施 |
| 8 | #8 / D38 | 选人弹层/选中框统一样式 | 待实施 |
| 9 | #9 / D39 | 计薪参数页删除旧司机津贴项；新增钻工队长名单 | 待实施 |
| 10 | — | 笔误，忽略（用户确认） | 已剔除 |

---

## 1. P12.1 — OA 三申请升格平级子页（v5 #1 / D30）

### 现状（代码）
- `templates/index.html:230-272`：入职/调岗/离职申请是**员工列表页底部一张卡片**内嵌的 3 个切换按钮 + 内联小表单。
- 入职表单仅有 4 字段：姓名/部门/岗位/入职日期（`index.html:239-248`）。
- 调岗/离职：姓名模糊搜 + 少量字段（`index.html:249-271`）。
- `MODULES.employees.children = ['list']`（`index.html:1250`）——侧栏只有"员工列表"一个子页。
- OA 待审/历史：员工页顶部 Tabs（`index.html:189-193`），保留。

### v5 目标
- 侧栏"员工管理"下出现 **4 个平级子页**：员工列表 / 入职申请 / 调岗申请 / 离职申请（`MODULES.employees.children = ['list','hire','transfer','dismiss']`）。
- 点击侧栏"入职申请"→ 打开**独立子页**，表单 = 员工档案**全部基本信息字段**（姓名/性别/出生日期/电话+255/部门/岗位/班组/技能等级/入职日期/NIDA/NSSF/银行名称·账号·户名/薪资类别/薪资基数），字段类型约束同 §5.1.3。
- 审批通过后**自动创建员工记录**（含 employee_id 分配）→ 出现在员工列表。

### 改动点
1. `MODULES` 增 `employees.children`（`index.html:1250`）；`SUBPAGE_TARGETS` 加 `employees/hire`、`employees/transfer`、`employees/dismiss` 映射（`index.html:1259-1275`）。
2. `i18n.js` 补 `nav_employees_hire / nav_employees_transfer / nav_employees_dismiss`（中英）。
3. 删除 `index.html:230-272` 列表底部卡片；原提交逻辑 `submitApply()` 迁移到独立子页。
4. 入职表单字段扩充为档案全字段，提交流程沿用 `employee_events`（`POST /api/events` 或现有申请端点），审批通过后创建员工。
5. 审批通过自动入列表：审批回调里创建 `employees` 行 + `employee_events(hire)` + 审计。

### 验收
- 侧栏可见 4 个子页；入职申请表单含全部档案字段；审批通过后员工出现在列表。

---

## 2. P12.2 — 员工档案独立完整页（v5 #2 / D31）

### 现状（代码）
- 员工档案是 **modal 弹窗**：`employeeProfileModal`（`index.html:331-382`），`showEmployeeProfile()` 打开（`index.html:1811`）。
- 头像 `<img id="pfAvatar">` 尺寸 56×56px 圆形（`index.html:344`）。
- 列表行/姓名点击都 navigate 到 `employees/list?id=`，依赖弹窗展示（`index.html:1788-1792`）。

### v5 目标
- 员工档案为**独立子页**：`#employees/profile?id=<employee_id>`（`MODULES.employees.children` 加 `profile`）。
- 头像按**简历照尺寸**展示：建议 96×120px（3:4，方形圆角）；上传/预览/删除保留，列表行内小头像（32-40px）共用同一文件。

### 改动点
1. 新页面容器 `page-employees-profile`（或复用弹窗 DOM 结构迁移到 page 层）。
2. `SUBPAGE_TARGETS` 加 `employees/profile`；`navigate('employees','profile',{id})` 传参。
3. 头像容器改 96×120px 简历尺寸，CSS 方形圆角；`pfAvatar` 从圆形改方形。
4. 弹窗逻辑 `showEmployeeProfile/closeEmployeeProfile` 迁移为页面加载逻辑（`loadEmployeeProfilePage()`），保留字段编辑/头像上传/时间线/请假记录。

### 验收
- 点击员工 → 跳转 `#employees/profile?id=` 独立页（非弹窗）；头像 3:4 简历尺寸。

---

## 3. P12.3 — 档案页三类假期余额显示且可修改（v5 #3 / D32）

### 现状（代码）
- 弹窗已显示年假/调休/病假余额（只读，`index.html:1854-1864`）。
- 仅病假有"🎛 病假余额"调整按钮（`index.html:370`，`adjustSickBalance()`）。
- 后端：`GET /api/leave/balance/<eid>`；病假调整端点存在。

### v5 目标
- 档案页显示 **年假/调休/病假三类余额**，每类带"调整"按钮。
- 调整写 `leave_balances` 的 `total_entitled` / `used`，写审计日志。

### 改动点
1. 前端余额区改为三行各带"调整"按钮（年假/调休/病假），复用病假调整交互，推广到三类。
2. 后端新增/复用调整 API（建议 `POST /api/leave/balance/adjust`，参数 `eid / leave_type / field / value`），写 `leave_balances` + `audit_log`。
3. 权限：admin+ 可调。

### 验收
- 三类余额均可调整，落库 + 审计。

---

## 4. P12.4 — 姓名可选中复制、点击才跳转（v5 #5a / D33）

### 现状（代码）
- 整行 `tr` 绑定 `onclick="navigate('employees','list',{id})"`（`index.html:1788`）。
- 姓名 `<a>` 绑定 click navigate（`index.html:1791-1792`）——拖选文本时松手也会触发跳转。

### v5 目标
- 鼠标**选中姓名**（拖选/双击选词）仅选中，**不跳转**，可正常复制。
- **点击**姓名或行 → 跳转档案页。

### 改动点
1. 姓名 `<a>` 去掉 click navigate，改用 `onclick="if(!window.getSelection().toString())navigate(...)"` 或在 `mousedown` 记录、`mouseup` 有选区则不跳。
2. `tr` 保留点击跳转，但用 `onclick="if(!window.getSelection().toString())navigate(...)"` 防拖选触发。
3. CSS：姓名加 `user-select:text`（行内其它列保持默认）。

### 验收
- 拖选姓名可复制且不跳转；单击跳档案页。

---

## 5. P12.5 — 井下出渣采集：三列标签 + 双备注 + 驾驶勾选（v5 #4 / D34 + #7 / D37）

### 现状（代码）
- `renderUgCollectionForm()`（`index.html:3887-3935`）：`prodRow()` 只标一行 `NICKEL(H)` 标签，后面 3 个无标签输入框（`index.html:3893-3899`）。
- 备注只有一个 `ugRemark`，位于 Day 段与 Night 段之间（`index.html:3914`）——Day 下方有、Night 下方无。
- **无驾驶勾选**。
- 出勤人员弹层：`openEmpPicker('underground', ...)`（`index.html:3903`），通用弹层 `empPickerModal` 只含 checkbox 列表，无驾驶列。

### v5 目标
- Day/Night 各一段，每段内：
  - **三列带标签**：`NICKEL(H) | NICKEL(L) | MAWE`。
  - **独立 Remark**（Day Remark / Night Remark）。
  - 出勤人员选择弹层内**每人带"驾驶"勾选**，仅 `driver_roster` 内人员可勾。
- payload 结构调整：`{day:{nh,nl,mw,emps,remark,drivers}, night:{nh,nl,mw,emps,remark,drivers}}`。

### 改动点
1. `prodRow()` 改为生成三列各带 `label`（`NICKEL(H)`/`NICKEL(L)`/`MAWE`）。
2. Day/Night 段各加 Remark input；后端 `submitUgCollection()` payload 增加 `day.remark` / `night.remark`。
3. 选人弹层在 `underground` 关键词下渲染"驾驶"列：checkbox 仅在 `driver_roster` 名单内可勾（后端 `GET /api/driver-roster` 或复用 `is_driver` 逻辑）。
4. 后端 `_merge_collection_to_main_data()` 与计算引擎识别 `drivers`，勾选者计司机津贴。
5. 出勤收集页**移除**驾驶勾选（见 P12.7）。

### 验收
- 三列列头可见；Day/Night 各有一个备注；弹层内司机名单人员可勾驾驶，非名单人员禁勾。

---

## 6. P12.6 — 钻工队长名单化 + "添加队伍"先选队长（v5 #5b / D35）

### 现状（代码）
- 队长下拉列出**全部钻工部门员工**：`caps = filterEmpByDept(pool, 'driller')`（`index.html:3971`）。
- 按钮文案"添加队长"直接加空槽（`index.html:3962`，`addDrSlot()` `index.html:4008-4011`）。
- `renderDrSlots()` 默认 3 空槽（`renderDrCollectionForm` 默认 `[{},{},{}]`，`index.html:3954`）。

### v5 目标
- 队长下拉**只列队长名单内人员**（新表 `driller_captains`，当前 3 人：BARAKA LAIZER / JOHN BOAY BURA / SHEDRACK PINIEL LAIZER）。
- 按钮改"**添加队伍**"：点击 → **先弹人员选择**（仅名单内）→ 选定队长 → 生成新队伍槽位（队长预填），与默认 3 队同一数据流。

### 改动点
1. 新表 `driller_captains`（employee_id UNIQUE / name / sort_order），初始种入 3 人（`app.py` init 或迁移脚本）。
2. 新增 `GET/POST/PUT/DELETE /api/driller-captains`（admin+），计薪参数页维护。
3. `renderDrSlots()` 队长下拉改为从 `driller_captains` 取（`GET /api/driller-captains`）。
4. `addDrSlot()` 改为弹层选队长（复用 `empPickerModal`，过滤名单）→ 选定后 push 槽位并预填 captain。
5. 提交 payload 不变（teams[]），后端校验 captain ∈ driller_captains。

### 验收
- 队长下拉只列名单 3 人；"添加队伍"先选队长再生成槽位；默认 3 槽位对应名单 3 人。

---

## 7. P12.7 — 出勤收集：按部门选择 + 移除驾驶（v5 #7 / D37）

### 现状（代码）
- `renderAttCollectionForm()`（`index.html:4142-4171`）：`roster = filterEmpByDept(pool,'other')`（`index.html:4146`），**无部门下拉**。
- 每行有"驾驶"checkbox（`index.html:4162`），提交时写 `is_driver`（`index.html:4189`），后端校验 driver_roster（`app.py:1860-1868`）。

### v5 目标
- 顶部**部门下拉**：列出来井下/钻工/破碎以外的所有部门 + "全部"，选定后花名册只显示该部门员工。
- **移除**每行"驾驶"勾选；提交 payload 不再含 `is_driver`。
- 后端 `collection_submit` 的 attendance 分支删除 is_driver 处理。

### 改动点
1. `renderAttCollectionForm()` 顶部加部门下拉（从 employees 去重取非井下/钻工/破碎部门）。
2. 花名册按所选部门过滤；移除驾驶列。
3. `submitAttCollection()` 不再收集/提交 `is_driver`。
4. `app.py:1853-1868` attendance 分支删 is_driver 校验与 `add_driver` 调用。
5. 历史 payload 兼容：读取旧 payload 时忽略 `is_driver` 字段。

### 验收
- 部门下拉过滤花名册；无驾驶列；后端不再校验 is_driver。

---

## 8. P12.8 — 选人弹层/选中框统一样式（v5 #8 / D38）

### 现状（代码）
- 人员多选弹层 `empPickerModal`（`index.html:384-396`）：列表行 checkbox 样式内联。
- 三个弹层渲染函数样式内联且略不一致：`openEmpPicker()`（`index.html:3844-3849`）、`renderDrMemberRows()`（`index.html:4043-4049`）、出勤收集花名册（`index.html:4154-4164`）。
- 表单中已选人员显示为 `<span>` 文本，无统一 chips 样式。

### v5 目标
- 弹层 checkbox 行、已选人员显示框统一公共样式类，全采集表单对齐。

### 改动点
1. `static/css/style.css` 新增公共类：`.picker-row`（弹层行）、`.emp-chips` / `.chip`（已选人员标签）。
2. 三处弹层行改 `class="picker-row"`；已选人员显示改 `<div class="emp-chips"><span class="chip">…</span></div>`。
3. 移除内联 style，统一变量（`--border`/`--radius`/`--bg-secondary`）。

### 验收
- 全采集表单选人弹层与已选显示样式一致、对齐美观。

---

## 9. P12.9 — 计薪参数页：删除旧司机津贴项 + 新增钻工队长名单（v5 #9 / D39）

### 现状（代码）
- `page-settings`（`index.html:546-605`）含"司机津贴"卡片：`cfg_driver_allowance`（`index.html:583-587`）。
- `loadConfig()` 填值 `index.html:3280`；`saveConfig()` 提交 `index.html:3305`；默认值 `index.html:3327`。
- 无钻工队长名单维护 UI。

### v5 目标
- **删除**"司机津贴"卡片及 `driver_allowance` 在 saveConfig/resetConfig 的读写。
- **新增**"钻工队长名单"维护区（增删改 `driller_captains`）。
- 司机津贴单价沿用既有默认 5,000/班，**不新增配置项**（v5 #10 笔误已确认）。

### 改动点
1. 删除 `index.html:583-587` 司机津贴卡片。
2. `loadConfig()`/`saveConfig()`/默认值中移除 `driver_allowance` 字段（`index.html:3280/3305/3327`）。
3. 页面加"钻工队长名单"卡片：列表 + 添加（选员工）/删除/排序，调 `driller_captains` CRUD API。
4. 后端 `/config` 仍接受其它字段；`driver_allowance` 键忽略或保留（不展示）。

### 验收
- 页面无全局司机津贴输入；钻工队长名单可增删改。

---

## 10. P12.10 — 评分模块改名"评分系统"（v5 #6 / D36）

### 现状（代码）
- `MODULES.scoring.label = 'nav_scoring'`（`index.html:1254`），但 `i18n.js` **无 `nav_scoring` 键** → 侧栏直接显示原始 key "nav_scoring"。
- 移动端底部导航 `data-i18n="nav_scoring"` 回退显示"评分"（`index.html:848`）。
- 子页键 `nav_scoring_card / summary / objective` 也未定义。

### v5 目标
- 侧栏模块名显示"**评分系统**"；补 `nav_scoring` 与 `nav_scoring_card/summary/objective` 中/英 i18n 键。

### 改动点
1. `i18n.js` zh：`nav_scoring: '评分系统'`，`nav_scoring_card: '评分卡录入'`、`nav_scoring_summary: '评分汇总'`、`nav_scoring_objective: '客观录入'`（或沿用现有文案）。
2. `i18n.js` en：`nav_scoring: 'Scoring'` 等。
3. 如保留模块 ID `scoring` 即可，仅修 label 键。

### 验收
- 侧栏显示"评分系统"，无原始键名；中英切换正常。

---

## 11. 数据模型变更汇总（P12 新增）

| 表/键 | 变化 | 说明 |
|--------|------|------|
| `driller_captains` | **新表** | 钻工队长名单（employee_id UNIQUE / name / sort_order），初始种入 3 人 |
| `settings` | 移除读写 | `driver_allowance`（旧全局手工津贴）不再在计薪参数页读写（键本身可留库不展示） |
| `collection_submissions.payload` | 结构扩展 | underground payload 增加 `day.remark / night.remark / day.drivers / night.drivers`；attendance payload 移除 `is_driver` |

---

## 12. 验收核对清单（对应 PRD §13.1/13.2 v5 增量）

- [ ] 侧栏员工管理 4 子页：列表/入职/调岗/离职；入职表单全字段；审批后自动入列表
- [ ] 点击员工 → `#employees/profile?id=` 独立页；头像 96×120px 简历尺寸
- [ ] 档案页年假/调休/病假三类余额均可调整，写审计
- [ ] 拖选姓名不跳转可复制；单击跳档案页
- [ ] 井下采集三列标签可见；Day/Night 各备注；弹层内司机可勾驾驶
- [ ] 钻工队长下拉只列名单 3 人；"添加队伍"先选队长再生成槽位
- [ ] 出勤收集有部门下拉过滤；无驾驶列
- [ ] 全采集表单选人弹层/选中框统一样式
- [ ] 计薪参数页无全局司机津贴输入；有钻工队长名单维护
- [ ] 侧栏评分模块显示"评分系统"，无原始键名
- [ ] i18n 中英切换下上述全部文案无遗漏
