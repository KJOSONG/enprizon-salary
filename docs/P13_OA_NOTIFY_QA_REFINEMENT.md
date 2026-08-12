# P13 阶段详设 — 筛选修复 / OA 自审规则 / 请假子页 / 通知 / 审批人设定 / 中英双语审查

> **状态**：v1（2026-08-12，v5 验收后 10 条有效反馈定稿）
> **最后更新**：2026-08-12
> **依赖**：`REFACTOR_SPEC.md` v6（PRD §0.2 / §5.2 / §11-P13 / §13 验收）、`DEV_WORKFLOW.md`、`docs/P12_OA_PROFILE_COLLECTION_REFINEMENT.md`（P12 已实现基线）
> **定位**：P13 的实施对照清单，逐条列出"现状代码 → v6 目标 → 改动点"。代码会变、目标不变。

---

## 0. 反馈清单索引（用户原话 → PRD v6 编号）

| 用户编号 | PRD v6 编号 | 主题 | 状态 |
|----------|-------------|------|------|
| 1 | #1 / D40 | 员工列表部门筛选修复 | 待实施 |
| 2 | #2 / D41 | 员工档案子页移出侧栏 | 待实施 |
| 3 | #3 / D42/D43 | OA 自审规则分角色 + 审批详情展开 | 待实施 |
| 4 | #4 / D44 | 请假申请升格侧栏子页 | 待实施 |
| 5 | #5 / D45 | 侧栏折叠底部区样式优化 | 待实施 |
| 6 | #6 / D46 | 入职表单加头像上传 | 待实施 |
| 7 | #7 / D47 | 入职提交后自动进待审批页 | 待实施 |
| 8 | #8 / D48 | 顶部通知铃铛/红点 | 待实施 |
| 9 | #9 / D49 | 超级管理员后台指定审批人 | 待实施 |
| 10 | #10 / D50 | 全页面字段中英双语审查 | 待实施 |

---

## 1. P13.1 — 员工列表部门筛选修复（v6 #1 / D40）

### 现状（代码）
- `renderEmployeeTable()`（`templates/index.html:1824-1867`）：每次调用都重建 `empFilterDept` 下拉（1834-1837），**不保留当前选中值** → 用户选部门触发 onchange 重绘后，下拉回到"全部部门"，筛选看似无效。
- `empFilterDept` 的 onchange 绑定 `renderEmployeeTable()`（`index.html:204`）。
- `fillApplyDepts()`（`index.html:3859-3873`）读取 `empFilterDept` 填充入职/调岗子页部门下拉，但**不改写它**，非冲突源。

### v6 目标
- 选部门后列表即时过滤，且下拉选中值在渲染后保留。

### 改动点
1. `renderEmployeeTable()`：重建下拉前读取 `sel.value`，重建后 `sel.value = prevVal`（在 `sel.innerHTML=...` 之后恢复）。
2. 或改为"部门选项仅在首次/部门集合变化时填充"，避免每次重建。
3. 回归：搜索框 + 部门筛选可叠加；切页/进档案返回后筛选仍生效。

### 验收
- 选部门 → 列表过滤正确；下拉值不重置；与搜索叠加正常。

---

## 2. P13.2 — 员工档案子页移出侧栏（v6 #2 / D41）

### 现状（代码）
- `MODULES.employees.children = ['list','hire','transfer','dismiss','profile']`（`index.html:1300`）——`profile` 出现在侧栏。
- 点击侧栏"员工档案"无 id → `showTargetPage`（`index.html:1432-1436`）无 eid 时 `navigate('employees','list')` → 闪跳回列表。
- `SUBPAGE_TARGETS['employees/profile']='employees-profile'`（`index.html:1314`）映射存在。

### v6 目标
- 侧栏不显示"员工档案"子页；`#employees/profile?id=` 仍可直达（列表点员工进入）。

### 改动点
1. `MODULES.employees.children` 改为 `['list','hire','transfer','dismiss','leave']`（顺带补 P13.4 请假子页），**去掉 `'profile'`**。
2. 保留 `SUBPAGE_TARGETS['employees/profile']` 映射（hash 直达不受影响）。
3. 验证 `renderSidebar` 只渲染 children 列表项，无 profile。

### 验收
- 侧栏员工模块只有 列表/入职/调岗/离职/请假；`#employees/profile?id=128` 直达档案页正常。

---

## 3. P13.3 — OA 自审规则分角色 + 审批详情展开（v6 #3 / D42/D43）

### 现状（代码）
- 批准：`oa_approve_event`（`app.py:1556-1581`）对所有角色一律 `operator_id==username → 400 "不能审批自己提交的事件"`（1566-1567）。
- 驳回：`oa_reject_event`（`app.py:1583-1599`）**无自审限制** → 可自己驳回。不对称。
- 详情：`loadOAPending()`（`index.html:3563-3589`）卡片只有类型/姓名/日期/提交人，**无 payload 展示**、无"查看详情"。

### v6 目标
1. 自审规则分角色：
   - `super_admin` 可批准自己提交的事件。
   - 其他角色自己提交的事件：只能驳回，不能批准。
2. 审批卡片可展开查看表单 payload 全字段（尤其入职 18 字段）。

### 改动点（后端 `app.py`）
1. `oa_approve_event`：拦截条件改为 `event['operator_id'] == username and session.get('role') != 'super_admin'` → 400。
2. `oa_reject_event`：保持不限（或对 super_admin 亦不设限，维持可自驳）。

### 改动点（前端 `index.html`）
3. `loadOAPending()`：卡片加"查看详情"按钮 → 展开区展示 `ev.payload`（JSON 解析后按字段名渲染中文标签，如 姓名/部门/岗位/性别/出生日期/…），含所有提交字段。
4. 需要后端 `GET /api/oa/pending` 返回 `payload` 字段（确认 `get_pending_events` 已含；若缺则补）。
5. 批准按钮：若当前用户==operator 且非 super_admin，前端禁用并提示"不能批准自己提交"。

### 验收
- KEJU 提交的事件 KEJU 可批准；admin 提交的事件 admin 自己不能批准但能驳回；点"查看详情"可见入职全部字段。

---

## 4. P13.4 — 请假申请升格侧栏子页（v6 #4 / D44）

### 现状（代码）
- "新建请假"按钮在 OA 待审 Tab 内（`index.html:236`），表单 `leaveForm`（239-267）随待审页显示。
- `submitLeave()`（`index.html:3660-3694`）提交后 `loadOAPending()`。

### v6 目标
- 请假申请为侧栏员工管理平级子页（员工列表下方），移出待审批页。

### 改动点
1. `MODULES.employees.children` 加 `'leave'`（见 P13.2）；`SUBPAGE_TARGETS['employees/leave']='employees-leave'`。
2. 新建 `page-employees-leave` 独立页，把 `leaveForm` 表单迁移（含姓名/工号 typeahead、类型、日期、天数、备注）。
3. 删除 OA 待审页顶部"新建请假"按钮（`index.html:236`）与 `leaveForm` 块（239-267）；`showLeaveForm()` 改 `navigate('employees','leave')` 或删除。
4. `submitLeave()` 成功后留在本页并清空（或跳转相应结果）。
5. i18n：`nav_employees_leave`（请假申请 / Leave Application）。
6. `showTargetPage` 增加 `employees-leave` 触发表单初始化。

### 验收
- 侧栏员工模块有"请假申请"子页；待审批页无"新建请假"按钮；请假提交正常。

---

## 5. P13.5 — 侧栏折叠底部区样式优化（v6 #5 / D45）

### 现状（代码）
- 侧栏折叠样式已有基础（`style.css:1632-1655`）：footer 折叠 padding、lang 按钮缩小、user nav-btn 缩小。
- 问题：折叠态下 `.sidebar-lang`/`.sidebar-user` 仍可能溢出/不整齐（文字挤、按钮换行）。

### v6 目标
- 折叠态下中英切换/登录/改密/退出紧凑对齐（图标化或单字，不溢出）。

### 改动点
1. `style.css` 折叠态：`.sidebar.collapsed .lang-toggle-btn` 显示为单字符（中/EN）固定宽；`.sidebar-user .nav-btn` 图标化（改用 emoji/icon，隐藏文字）。
2. `.sidebar-user` 折叠时垂直堆叠或隐藏"改密"，保留登录/退出。
3. 展开态保持现状。

### 验收
- 折叠侧栏后底部区对齐、无溢出、可操作。

---

## 6. P13.6 — 入职表单加入头像上传（v6 #6 / D46）

### 现状（代码）
- 入职表单（`index.html:286-323`）无头像字段。
- 档案页头像上传：`uploadEmployeeAvatar()`（`index.html:1912+`）读 `pfAvatarFile`，POST `/api/employees/avatar`（admin+）。入职场景暂无 employee_id（提交后才生成）。

### v6 目标
- 入职表单支持上传头像（PNG/JPG ≤2MB，预览）。

### 改动点
1. 入职表单加头像上传区（文件选择 + 预览），暂存 base64 或 file。
2. 提交 `POST /api/oa/events`（hire）payload 携带头像数据（base64 dataURL）或临时路径。
3. 后端 `apply_approved_event()` hire 分支：若 payload 含头像，写入 `static/avatars/<employee_id>.<ext>` 并置 `employees.avatar_path`。
4. 复用档案页上传的校验（类型/大小）。

### 验收
- 入职表单可上传头像并预览；审批通过后档案页显示该头像。

---

## 7. P13.7 — 入职提交后自动进待审批页（v6 #7 / D47）

### 现状（代码）
- `submitApply('hire')`（`index.html:3645-3716`）成功后清空表单留在原页。

### v6 目标
- 入职申请提交成功后自动切换到 OA 待审 Tab。

### 改动点
1. `submitApply` 成功分支：`switchEmpTab('oa-pending')` + `loadOAPending()`（若入职表单在独立子页，则 `navigate('employees','list')` 后切 Tab，或直接 `navigate` 到带 oa-pending 态）。
2. 提示 toast "已提交，进入审批流程"。

### 验收
- 提交入职后页面自动进入待审批列表。

---

## 8. P13.8 — 顶部通知铃铛/红点（v6 #8 / D48）

### 现状（代码）
- 无通知 UI。已有 `GET /api/oa/pending/count`（`app.py:1540-1546`）返回 `{count}`。

### v6 目标
- 顶部通知铃铛 + 红点：有待审批事项时红点；点开列出"待你审批"（类型/提交人/时间），点击跳转 OA 待审。

### 改动点（前端 `index.html`）
1. period-bar 右侧加铃铛按钮（`#notifBell`）+ 红点徽标（count>0 显示）。
2. 下拉面板 `#notifPanel`：加载 `GET /api/oa/pending` 渲染"待你审批"列表（类型/提交人/时间），点击 `navigate('employees','list')` + `switchEmpTab('oa-pending')`。
3. 轮询或登录/切换月后刷新 count；审批动作后刷新。
4. 无权限用户（viewer 无审批权）不显示铃铛。

### 验收
- 有待审批事项时顶部铃铛红点；点开列出事项；点击跳转待审页。

---

## 9. P13.9 — 超级管理员后台指定审批人（v6 #9 / D49）

### 现状（代码）
- 审批人固定为所有有 `oa.approve` 权限者（`@require_permission('oa','approve')`），提交人不可选。
- `employee_events` 表无审批人字段。

### v6 目标
- super_admin 在后台指定某用户为指定类型事件的审批人；未指定走默认流（KEJU）。

### 改动点（建议方案，实施时按 PRD §8.2 定）
1. 数据：`employee_events` 加列 `approver TEXT DEFAULT ''`（或新表 `approval_routes(event_type, approver_username, sort_order)`）。
2. 后台 UI：系统→用户与权限（或员工管理）新增"审批人设定"：按事件类型（入职/调岗/离职/请假）指定审批用户。
3. 事件创建：默认写入 approver=设定值（无则留空=默认流）。
4. 待审列表：`GET /api/oa/pending` 按 approver 过滤（空=默认所有人可见/KEJU）。

### 验收
- super_admin 可设指定审批人；提交后事件出现在该审批人待审列表；未指定走默认流。

---

## 10. P13.10 — 全页面字段中英双语审查（v6 #10 / D50）

### 现状（代码）
- 硬编码中文 113 处（`templates/index.html` 静态 HTML 文本，未带 data-i18n），中英切换后仍显示中文。
- `i18n.js` 已有 800+ 键，但覆盖不全（P12 补了 26 键仍余 113 处）。

### v6 目标
- 全页面展示字段无硬编码中文；中英切换完整无遗漏。

### 改动点
1. 逐页扫描 `templates/index.html` 静态文本，把硬编码中文替换为 `data-i18n` 键（113 处）。
2. `i18n.js` 补齐对应中英键（含 JS 模板字符串内生成的文案：toast、确认框、标签）。
3. 脚本辅助：用 Python 正则扫描 `>[中文]<` 输出清单，逐条替换后二次扫描清零。
4. 验收：`switchLang('en')` 后页面无中文残留（除姓名/部门等业务数据）。

### 验收
- 中英切换后无硬编码中文残留；新增/既有页面文案均双语。

---

## 11. 数据模型变更汇总（P13 待定）

| 表/列 | 变化 | 说明 |
|--------|------|------|
| `employee_events.approver` | 加列（或新建 `approval_routes`） | 审批人设定（v6 #9），实施时按 PRD §8.2 定 |
| `notifications` | 可能新建 | 通知已读状态（v6 #8，若需已读/未读）；仅红点可无表 |
| `employees.avatar_path` | 复用 | 入职头像审批通过后写入（v6 #6） |

其余 7 条为纯前端/逻辑改动，无表结构变化。

---

## 12. 验收核对清单（对应 PRD §13 v6 增量）

- [ ] 员工列表选部门筛选生效，选中值保留
- [ ] 侧栏无"员工档案"子页；`#employees/profile?id=` 直达正常
- [ ] super_admin 可自批；其他角色自提交仅可驳；审批卡片可展开看 payload
- [ ] 请假申请为侧栏平级子页；待审批页无"新建请假"按钮
- [ ] 侧栏折叠底部区紧凑对齐
- [ ] 入职表单可上传头像（≤2MB PNG/JPG），审批后档案页可见
- [ ] 入职提交后自动进入待审批页
- [ ] 顶部铃铛红点；点开列出"待你审批"可跳转
- [ ] super_admin 后台可指定审批人；未指定走默认流
- [ ] 中英切换后无硬编码中文残留（113 处清零）
- [ ] i18n 中英切换下全部文案无遗漏
