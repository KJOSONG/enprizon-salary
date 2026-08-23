# P29 权限体系 V2.1 重设计规格

> **状态**：✅ 已实施（feature/p29-permission-v2，本地验证通过，待批准推送部署）｜需求文本冻结，本文件仍是权威需求来源
> **性质**：业务规格 + 工程设计合一（对标 `docs/P25_PIECEWORK_V2_SPEC.md` 的文档定位）
> **接手须知**：新 agent 接续此任务时以本文件为准，**不要重新调研需求、不要更改 §2 已冻结的决策**。文中行号为 2026-08-23 快照，会随代码漂移，以函数名/权限键名为准。
> **分支策略**：大改动 → 建 `feature/p29-permission-v2` 分支，KEJU 团队并行（DEV_WORKFLOW 约定）

---

## 0. 任务一句话

把 P18 权限框架的「目录结构」重造为与真实 UI 一致、动作语义严格分层（看 / 操作 / 申请 / 管理）的体系：
新增 `oa:apply`（自助申请）与采集表单级粒度（4 键），取消业务操作员预设，新增 collector/applicant 两个内置角色；
同时修复一批端点漏挂细粒度权限的安全不一致，并在 OA 审批详情中显示提交人。

---

## 1. 背景与诊断（为什么重造）

用户原话：「角色管理中的权限分组（数据台/产量/出勤/员工/OA/薪资/评分/系统）与系统页面板块（数据台/员工/出勤/薪资/数据采集/评分系统/系统管理）对不上，设计混乱，需要细化并重新设计」。

探查确认的 6 个根因：

| # | 问题 | 证据 |
|---|------|------|
| 1 | 目录有「产量」组（`production:*`），但 Web 侧边栏无产量模块；界面叫「数据采集」目录却叫「产量采集」 | `MODULES` 定义 index.html:1917 无 production；`PERMISSION_CATALOG` database.py:1420 |
| 2 | `oa:view` 描述含"发起申请"，看与申捆绑 → 无法做出"仅能提交请假/加班"的最小账号 | database.py:1432 |
| 3 | 申请类端点只挂 `@editor_required`，无细粒度键 | `/api/oa/events` app.py:1761、`/api/oa/leave`:2131、`/api/leave/sick`:2181 |
| 4 | 端点不一致：approve 挂了 `oa:approve` 但 reject/revoke/edit 没有；采集提交端点门槛与前端不对齐 | app.py:1876/1904/1930 |
| 5 | 移动端混用 `role==='admin'` 硬编码（6 处）与 `hasPermission()`；档案页请假/加班按钮零门槛而快捷入口要 `oa:view` | mobile.html:1068/1074/1174、811-812 vs 1616/1624 |
| 6 | viewer 默认无 salary/scoring/system view，「看所有页面但零编辑」做不到 | `ROLE_DEFAULT_PERMISSIONS` database.py:1387 |

另（需求①）：OA 详情看不到提交人 —— `employee_events.operator_id` 存了提交人用户名（app.py:1778 写入 session username），但接口只回显 `employee_name`（事件主体员工），前端从未渲染 operator 字段。

---

## 2. 已批准决策记录（❄️ 冻结，不得擅自变更）

用户于 2026-08-23 两轮确认：

| # | 决策 |
|---|------|
| D1 | Web 侧边栏将「审批中心」从员工板块独立成模块，位置紧挨员工下方 |
| D2 | 取消内置预设「业务操作员」（editor 不再作为内置角色播种，存量 editor 用户平移保权，见 §9） |
| D3 | 数据采集粒度到表单级：可授权某人只能提交某一个表单；采集员对自己提交的数据有再编辑权 |
| D4 | collector 自动继承 applicant 全部权限（为替他人提交加班/请假）；入职/调岗/离职申请开放给普通申请人（归入 `oa:apply`，不再要求 `employees:edit`） |
| D5 | 纯 viewer 可看薪资总表；拥有全部模块查看权限，唯独没有任何编辑/提交/管理权限 |
| D6 | collector 给予 `attendance:view` |
| D7 | 微调能力保留：任意角色可用角色编辑器增删 `role_permissions`，任意用户可用 user_grants allow/deny 单独加减（deny 优先）；唯一例外 super_admin 恒为 `*:*` 不参与微调（防锁死安全锚点） |

早期决策点结论（第一轮方案已确认）：`oa:apply` 覆盖 请假/病假/加班/入职/调岗/离职 六类申请；viewer 含薪资只读。

---

## 3. 新权限目录 V2.1（8 模块 · 21 键）

判定链不变：`super_admin → user_grants deny → user_grants allow → role_permissions(含继承) → false`（database.py:1581 check_permission）。
键格式仍为 `module:action` 精确匹配字符串；前端 `hasPermission(module, action)` 与 `'*:*'` 通配逻辑两端均不改。

| 模块组 | 键 | 名称 | 说明 | 旧键迁移 |
|--------|-----|------|------|---------|
| 数据台 | `dashboard:view` | 数据台查看 | 数据台页＋产量图表接口数据 | `dashboard:view` ＋ `production:view` 并入 |
| 员工 | `employees:view` | 员工查看 | 员工列表/档案 | 同名 |
| 员工 | `employees:edit` | 员工编辑 | 档案编辑/调岗类型/头像/奖惩 | 同名 |
| 员工 | `employees:export` | 员工导出 | 花名册导出 | 同名 |
| 审批中心 | `oa:view` | OA 查看 | 待审/历史列表纯浏览（语义收窄，不再含发起申请） | 同名收窄 |
| 审批中心 | `oa:apply` ⭐ | 发起申请 | 请假/病假/加班/入职/调岗/离职六类 | **新增**（从 oa:view 与 @editor_required 拆出） |
| 审批中心 | `oa:approve` | OA 审批 | 批准/驳回/撤销/编辑事件 | 补齐 reject/revoke/edit 三处漏挂 |
| 出勤 | `attendance:view` | 出勤查看 | 出勤网格只读 | 同名 |
| 出勤 | `attendance:edit` | 出勤编辑 | 标记/批量/保存计算 | 同名 |
| 出勤 | `attendance:export` | 出勤导出 | 出勤 Excel | 同名 |
| 薪资 | `salary:view` | 薪资查看 | 总表/日工资明细/核对/旧数据归档 | 同名＋归档并入 |
| 薪资 | `salary:export` | 薪资导出 | 三类薪资导出 | 同名 |
| 数据采集 | `collection:view` | 采集历史查看 | 采集记录列表/再编辑入口 | 新增（原靠 @editor_required 兜底） |
| 数据采集 | `collection:underground` ⭐ | 井下出渣提交 | 仅此一个采集表单 | `production:edit` 拆分 |
| 数据采集 | `collection:driller` ⭐ | 钻工组提交 | 同上 | `production:edit` 拆分 |
| 数据采集 | `collection:crush` ⭐ | 破碎计件提交 | 同上 | `production:edit` 拆分 |
| 数据采集 | `collection:attendance` ⭐ | 出勤收集提交 | 同上（注意 module 是 collection，与 attendance 模块无冲突） | `production:edit` 拆分 |
| 评分 | `scoring:view` | 评分查看 | 汇总/客观/周公示 | 同名 |
| 评分 | `scoring:edit` | 评分录入 | 评分卡录入 | 同名 |
| 系统 | `system:view` | 参数查看 | 计薪参数页可见（读取）；参数**保存**另受 admin 角色基线约束（见 §7 config 行） | 同名 |
| 系统 | `system:manage` | 系统管理 | 用户/角色/审批人路由/表单自定义（实际仍限 super_admin 生效） | 同名 |

> `production:*` 目录项删除。旧 `production:edit` 等价能力 = `collection:view` ＋ 4 个表单键。
> 权限编辑器 UI 分组 = 上表模块组列，顺序即侧边栏顺序，从此目录=菜单一一对应。

---

## 4. 内置角色预设 V2.1（5 个）

```python
ROLE_DEFAULT_PERMISSIONS_V2 = {
    'super_admin': {'*': ['*']},          # 恒定，不参与微调
    'admin': {                            # 全业务，不含 system:manage
        'dashboard':  ['view'],
        'employees':  ['view', 'edit', 'export'],
        'oa':         ['view', 'apply', 'approve'],
        'attendance': ['view', 'edit', 'export'],
        'salary':     ['view', 'export'],
        'collection': ['view', 'underground', 'driller', 'crush', 'attendance'],
        'scoring':    ['view', 'edit'],
        'system':     ['view'],
    },
    'collector': {                        # ⭐新 数据采集员（继承 applicant）
        'dashboard':  ['view'],
        'collection': ['view', 'underground', 'driller', 'crush', 'attendance'],
        'attendance': ['view'],           # D6
        'oa':         ['apply'],          # D4 继承 applicant
    },
    'applicant': {                        # ⭐新 自助申请人
        'dashboard':  ['view'],
        'oa':         ['apply'],
    },
    'viewer': {                           # 全查看零写入（D5）
        'dashboard':  ['view'],
        'employees':  ['view'],
        'oa':         ['view'],
        'attendance': ['view'],
        'salary':     ['view'],           # 含薪资总表只读
        'collection': ['view'],
        'scoring':    ['view'],
        'system':     ['view'],
    },
}
```

配套常量变更：

| 常量 | 现值 | V2.1 |
|------|------|------|
| `BUILTIN_ROLES` | super_admin/admin/editor/viewer | **super_admin/admin/collector/applicant/viewer** |
| `ROLE_HIERARCHY`（database.py:1417） | admin→editor→viewer | **仅 `{'collector': ['applicant']}`**（字面实现 D4「自动继承」；其余内置角色预设自足、平铺；自定义角色仍平铺不变） |
| `ROLE_LEVELS`（database.py:1385） | super_admin:3/admin:2/editor:1/viewer:0 | 追加 `'collector': 0, 'applicant': 0`；**editor:1 必须保留**（大量端点仍以 `@editor_required` 作基线兜底，删掉会把存量 editor 用户当 viewer 拒掉） |

角色定位速查：admin=系统管理员全局日常；collector=田间采集员（4 表单全开，可按 D3/D7 收窄到单表单）；applicant=普通员工自助申请；viewer=审计只读全页可见。

---

## 5. Web 端映射（index.html）

### 5.1 侧边栏结构 V2.1（D1：审批中心独立）

```
◆  数据台      dashboard:view
👥 员工        employees:view
   ├ 员工列表 / 员工档案            → employees:view
   └ 入职/调岗/离职/请假/加班 申请   → oa:apply          ← D4 改挂
📨 审批中心    (oa:view || oa:apply) 任一即可见       ← 新独立模块，紧挨员工下方（D1）
   ├ 待审批                        → oa:view（approve 按钮另需 oa:approve）
   └ 审批历史                      → 同上
📅 出勤        attendance:view（保存计算按钮 attendance:edit）
💰 薪资        salary:view（导出按钮 salary:export；归档子页 salary:view）
⚒  数据采集    (collection:view || 任一表单键) 任一即可见
   ├ 井下出渣 / 钻工组 / 破碎计件 / 出勤收集 4 子页 → 各挂各的表单键
★  评分系统    scoring:view（录入页 scoring:edit）
⚙  系统管理    system:view 或 system:manage
   ├ 计薪参数                       → system:view
   ├ 用户与权限 / 表单自定义         → system:manage
   └ 旧数据归档                     → salary:view
```

### 5.2 机制升级（两处小改）

1. **模块可见性从"单键判定"改为"持该模块任意一键即显示"**：新增 JS helper `hasAnyPermission(module) => CATALOG_ACTIONS[module].some(a => hasPermission(module, a))`。这是 applicant 能看到审批中心、单表单采集员能看到数据采集板块的前提。
2. **MODULES 的 children 支持 `perm` 字段**（现在只有模块级一刀切）：`children: [{id:'leave', perm:'oa:apply'}, ...]`；`navigate()`/`showTargetPage()` 两级守卫在模块级检查之外增加子页级检查（复用现有 toast+回跳 dashboard 逻辑）。

### 5.3 其余前端改造点

- `data-perm` 属性按新目录重标（现存 10 处：index.html 121/522/576/702/824/914/916/919/928/939）。
- OA 待审/历史两页正式挂到审批中心模块下（i18n 键 `nav_oa_pending`/`nav_oa_history` 已存在；实施时定位现有 page DOM 挪挂载点）。
- 权限编辑器 UI 分组直接渲染新 CATALOG 的 group 字段。
- OA 徽标 `updateOaSideBadge()`（index.html:1996）门槛改为 `(hasPermission('oa','view')||hasPermission('oa','apply')) && hasPermission('oa','approve')`。

---

## 6. 移动端映射（mobile.html）

Tab 保持 4 个常显（不隐藏），无权限区域显示引导空态；动作级门槛全部换新键：

| 位置 | 行号快照 | 现状 | V2.1 |
|------|---------|------|------|
| 采集 4 卡片入口 | 1122-1124 | `production:edit` 一刀切 | 各卡片挂各自表单键 |
| 快捷请假/加班 | 1616/1624 | `oa:view` ❌ | `oa:apply` ✅ |
| 档案页请假/加班按钮 | 811-812 | **无门槛** ❌ | `oa:apply` ✅（修复不一致） |
| 病假免审快捷 quickSick | 1612 | 无门槛 | `oa:apply` |
| 出勤批量按钮/格子编辑 | 1479/1508 | `attendance:edit` | 不变 |
| 档案薪资区/编辑按钮 | 771/782 | `salary:view`/`employees:edit` | 不变 |
| OA 列表加载 | 1663/1723/1744 | `oa:view` | `(oa:view \|\| oa:apply)`；仅 apply 时强制只看自己提交的（operator_id==username 过滤，与采集历史 mine:true 同款模式） |
| 采集历史 mine 过滤 | 1067-1075 | role 硬编码 | 有 `collection:view` 可看全部历史；仅表单键者只看自己的 |
| `role==='admin'/'super_admin'` 硬编码 ×6 | 821/832/1068/1074/1174/1665 | 散落 | 收敛为单一 `isAdminLevel()` helper；涉及超管专属字段（部门编辑等）保留 super_admin 判定 |

---

## 7. 后端改造清单（app.py，行号为快照）

**装饰器统一**（安全修复 + 重构双重性质；沿用本仓库既有组合惯例：角色基线 + 细粒度键双保险）：

| 端点 | 快照行 | 现状 | V2.1 目标 |
|------|--------|------|----------|
| `POST /api/collection/submit` | ~2401 | 仅 `@editor_required` | handler 内按 payload 表单类型动态 `check_permission(u,'collection',<type>)`（type ∈ underground/driller/crush/attendance，与动作名天然对齐） |
| `POST /api/collection/edit/<id>` | ~2535 | owner-or-admin + editor | 叠加对应表单键校验；owner-or-admin 规则保留 |
| `GET /api/collection/history` | ~2473 | editor + `production:view` | `(collection:view \|\| 任一表单键)`；仅表单键者强制 mine 过滤 |
| `GET /api/production` | 2474 | `production:view` | `dashboard:view` |
| `GET /api/production/dashboard` | 3315 | `production:view` | `dashboard:view` |
| `GET /production-verify` | 3271 | `production:view` | `salary:view` |
| `POST /api/oa/events`（加班/入职/调岗/离职） | 1761 | 仅 `@editor_required` | ＋`oa:apply` |
| `POST /api/oa/leave` | 2131 | 仅 `@editor_required` | ＋`oa:apply` |
| `POST /api/leave/sick` | 2181 | 仅 `@editor_required` | ＋`oa:apply` |
| `POST /api/oa/events/<id>/approve` | 1836 | `oa:approve` ✅ | 不变 |
| `POST /api/oa/events/<id>/reject` | 1876 | 无细粒度 ❌ | 补 `oa:approve` |
| `POST /api/oa/events/<id>/revoke` | 1904 | 内联判断 | 补 `oa:approve`（保留"本人可撤自己的申请"） |
| `POST /api/oa/events/<id>/edit` | 1930 | 内联判断 | 补 `oa:approve` |
| `GET /api/oa/pending`·`pending/count`·`history`·`events/<id>` | 1802-1893 | `oa:view` | 改 `(oa:view \|\| oa:apply)`；仅 apply 者返回体过滤为自己的提交 |
| `GET /api/config` | 3151 | `@admin_required` | `@login_required + system:view` |
| `POST /config` | — | admin 基线 | 保持 `@admin_required` 基线不变（viewer 虽有 system:view 只读也写不了）；前端保存按钮维持 `.admin-only` |
| `/export/employees` | 3754 | 无细粒度（P18 已知遗留） | 补 `employees:export` |
| `/export/attendance` | 3487 与 3819 **两条同路径路由** ⚠️ | view/export 混挂 | 合并去重后统一挂 `attendance:export` |
| `POST /export`、`/export/all` | 3658/4002/4646/4698 | salary:export | 不变（顺带清理重复路由定义） |
| `/api/archive/months`·`archive/salary` | — | 登录即可 | `salary:view` |
| `POST /employees/bonus-penalty` | 1570 | 仅 editor | ＋`employees:edit` |
| `/set-month`、`/available-months` | 1171 等 | `@editor_required` | **降为 `@login_required`**（月份上下文是 UX 状态非数据暴露；否则 collector/applicant 的移动端月份切换会 403） |

> ⚠️ 实施时注意：两个探索代理对 `/api/collection/submit` 的现状装饰器报告有出入（一说仅 @editor_required:2401，一说 production:view:2474），以实施时实际代码为准，目标态不变。

> 📌 **实施记录（T7）**：采集三端点（submit/history/edit）最终落地为 `@login_required` + handler 内动态表单键校验，**放弃了原 editor 角色地板**。理由：collector 是 0 级角色，若保留 editor 地板则 collector 无法提交采集，整个角色人设失效；表单类型与动作名天然对齐，动态键校验已覆盖越权风险。

---

## 8. A 期：OA 详情显示提交人（小改，可独立先行上线）

数据已存在（`employee_events.operator_id` = 提交人用户名），缺口纯在展示层：

1. 后端（可选增强）：`get_pending_events`/`get_processed_events`/`get_event`（database.py:1942/1957/2180）已 `SELECT e.*` 含 operator_id，无需改 SQL 即可透传；如需中文显示名，后续给 `admin_users` 加 display_name 列，接口不动。
2. Web 前端三处渲染「提交人：{operator_id} · {created_at}」：待审列表行、审批详情弹窗、审批历史行。
3. 移动端同步两处：OA 列表项、OA 详情页。
4. 验收：任意账号提交一条请假申请 → 审批人视角三处均可见提交人用户名。

---

## 9. 数据迁移方案（幂等启动迁移 `_migrate_permissions_v2()`）

1. **内置五角色一次性强制重播种**为新预设（§4）。理由：预设定义本身是用户逐条批准的产物（含 viewer 新增薪资查看等行为变化），map-in-place 无法干净达成。重播种前把旧 role_permissions 全量写入 audit_log。
2. **自定义角色 key 平移**（不增不减语义）：
   - `production:view → dashboard:view`
   - `production:edit → collection:view ＋ collection:{underground,driller,crush,attendance}`（1 行展开为 5 行）
   - 其余键恒等映射；翻译后删除残留 `production:*` 行
   - user_grants 同规则平移（deny 行同样处理）
3. **存量 editor 用户**：editor 已不在 BUILTIN_ROLES/预设中，但其 role_permissions 行按上述规则平移后原样保留 → 权限不变、系统照常识别（check_permission 读 DB 行不关心 built-in 与否）；super_admin 可随时在界面删除该角色或改派人员。
4. **幂等性**：以 settings 表标记键 `perm_v2_migrated=1` 控制，只跑一次；重复启动跳过。
5. 兼容不变式：`/api/auth/status` 返回结构不变 `{logged_in, username, role, permissions[]}`，permissions 元素换成新键——两端 `hasPermission()` 零改动。

---

## 10. 实施分期与验收

| 期 | 内容 | 规模 | 验收标准 |
|----|------|------|---------|
| **A** | OA 提交人显示（§8） | 小，独立先行 | 双端三处可见提交人＋时间 |
| B | 目录 V2.1 ＋ 迁移脚本 ＋ §7 端点全量统一 | 核心·后端 | `_work/p29/` 轻 pytest：check_permission 五角色×关键键矩阵、迁移幂等（跑两次结果一致）、deny 优先序；test-workflow.sh swap 手工走查 |
| C | Web 端 §5 全部改造 | 前端 | persona×页面矩阵走查：5 个内置角色各登录一遍，侧边栏可见性与矩阵一致、无权访问 hash 直跳被守卫拦截回 dashboard |
| D | 移动端 §6 对齐 | 前端 | collector/applicant/viewer 三角色真机走查采集卡片/快捷申请/出勤编辑/OA 入口 |
| E | 权限编辑器 UI 分组重排 ＋ ARCHITECTURE.md 权限章节重写 ＋ AGENTS.md 更新 | 收尾 | 编辑器分组=侧边栏板块一一对应 |

B/C/D 可并行（feature 分支），E 收尾合并。部署前手动备份 `data/backups/kilwa_before_p29_<时间戳>.db`，推送需用户批准（save-salary 流程）。

---

## 11. 关键代码锚点（2026-08-23 探查快照）

| 内容 | 位置 |
|------|------|
| `PERMISSION_CATALOG`（18 键旧目录） | core/database.py:1420-1438 |
| `ROLE_DEFAULT_PERMISSIONS` / `ROLE_HIERARCHY` / `ROLE_LEVELS` / `BUILTIN_ROLES` | database.py:1387-1444 |
| `init_default_permissions()` / `get_role_permissions()` / `check_permission()` | database.py:1446 / 1485 / 1581-1628 |
| `require_permission` 装饰器及四个角色装饰器 | app.py:57-118 |
| 角色 CRUD（P18D）create/rename/delete/reset/edit | app.py:397-530 |
| `/api/permissions/users` 矩阵端点 | app.py:298-321 |
| OA 端点簇 pending/history/approve/reject/detail/revoke/edit | app.py:1761-1992 |
| `employee_events` 表结构（operator_id 在 L199） | database.py:192-209 |
| `approval_routes` 表 / `ALLOWED_APPROVAL_EVENT_TYPES` | database.py:533 / app.py:1997 |
| 事件创建写入 operator_id | app.py:1778 |
| Web MODULES/SUBPAGE_TARGETS/renderSidebar/navigate/showTargetPage | index.html:1917-1952 / 1960-1993 / 2037-2071 / 2073-2129 |
| `hasPermission` / `_authState` / data-perm 批量显隐 | index.html:1596-1604 / 1672-1675 |
| 移动端 `hasPermission`/`checkAuth`/doLogin | mobile.html:419-433 / 486-504 |
| 采集历史 mine 过滤 / owner-or-admin 编辑 | mobile.html:1067-1082 / 1171-1175 |

---

## 12. 红线（实施时禁止事项）

1. ❌ 不改 check_permission 判定链顺序；❌ 不允许 grant/deny 影响 super_admin。
2. ❌ 不删 `ROLE_LEVELS['editor']`（存量 editor 用户兼容依赖它）。
3. ❌ 两端 `hasPermission()` 保持精确匹配＋`'*:*'` 通配，不引入前缀/通配符匹配逻辑。
4. ❌ 不动 calculator/计薪管线任何文件（本任务与计算无关）。
5. ❌ 前端部门比较继续用 `normDept()`（全角括号陷阱），本任务新代码涉及部门时同理。
6. ❌ 迁移必须幂等且有 settings 标记；重播种前必须落 audit_log。
7. ❌ 未获用户批准不得推送远程/服务器。

---

## 13. 开放问题（已全部解决，2026-08-23 实施确认）

1. ✅ `admin_users` 是否已有显示名列？→ **无 display_name 列**，A 期直接显示 username。
2. ✅ `/export/attendance` 双路由定义（3487/3819）哪个是死代码？→ 实际只有单一路由，无需合并。
3. ✅ 撤销(revoked)状态事件对本人是否可见？→ **可见**（本人可查看自己已撤销的申请）。
