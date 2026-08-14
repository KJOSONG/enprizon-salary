# P18 用户权限管理框架重构方案

> 2026-08-14 制定,基于前后端权限调研报告(详见下方引用),用户确认 4 项决策。
> 用途:P0 阶段实施蓝图。分阶段实施,每阶段可部署验证。

## 一、问题根因(为什么"取消薪资权限"不生效)

| 层面 | 现状 | 证据 |
|------|------|------|
| 后端数据端点 | `/salary`、`/daily-wages`、`/salary/verify`、`/export` 只挂 `@login_required`,任何登录用户可读 | app.py:2466/2682/2501/2902 |
| 细粒度权限 | `@require_permission` 仅挂 2 端点(OA 审批 + export/all) | app.py:1448/3245 |
| 角色默认权限 | 硬编码 Python 字典 `ROLE_DEFAULT_PERMISSIONS`,`viewer` 默认含 `salary:view` | database.py:1079-1104 |
| 权限判定 | `check_permission` 读代码字典不读表;permissions 表无 role 列 | database.py:1189-1234 |
| 权限 UI | 点击"取消"实际是添加 allow 授权,无 deny 路径 | index.html:6936-6959 |
| 前端菜单 | renderSidebar 只判登录态,薪资菜单全量渲染,hash 可直达 | index.html:1627-1656 |

**结论**:端点裸奔 + 角色硬编码 + 前端不消费权限 + UI 无法取消,四层叠加。

## 二、目标模型(用户已确认)

```
角色(admin_users.role) → 角色默认权限(DB role_permissions 表,可编辑)
        ↓
用户单独授权(user_grants allow/deny 覆盖)
        ↓
统一判定 has_permission(module, action):
  super_admin → 全权限
  user_grants.deny → 拒绝
  user_grants.allow → 允许
  角色权限(DB,支持继承) → 允许/拒绝
        ↓
后端端点 @require_permission + 前端菜单/路由同步过滤
```

## 三、已确认决策

| # | 决策 | 结论 |
|---|------|------|
| 1 | 权限模型 | 角色 + 单用户双重(角色默认权限 DB 可编辑 + user_grants allow/deny 覆盖) |
| 2 | viewer 薪资 | **去掉** viewer 默认 `salary:view`,改为仅 dashboard 视图;薪资由 admin/editor 及以上查看 |
| 3 | 角色继承 | 支持:super_admin 继承全部;admin 继承 editor+viewer;editor 继承 viewer |
| 4 | 实施方式 | 分阶段实施,每阶段可部署验证 |

## 四、数据模型设计

### 4.1 新建表 `role_permissions`

```sql
CREATE TABLE IF NOT EXISTS role_permissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,            -- super_admin | admin | editor | viewer
  module TEXT NOT NULL,          -- dashboard | employees | oa | attendance | production | scoring | salary | system
  action TEXT NOT NULL,          -- view | edit | approve | export | ...
  allow INTEGER NOT NULL DEFAULT 1,  -- 1=允许 0=拒绝(角色级显式拒绝)
  UNIQUE(role, module, action)
);
```

- 角色默认权限从 `ROLE_DEFAULT_PERMISSIONS` 字典迁移至此表(迁移脚本,可重复执行 REPLACE)
- `permissions` 表保留为"权限定义清单"(module/action 元数据,供 UI 渲染),不再参与判定
- `user_grants` 保留单用户 allow/deny,优先级高于角色

### 4.2 角色继承规则(判定时展开)

```
有效权限(role) = 自身角色权限 ∪ 继承的下级角色权限
  viewer   = {dashboard.view}
  editor   = viewer ∪ editor 自身
  admin    = editor ∪ admin 自身
  super_admin = 全部(硬编码)
```

实现:`get_role_permissions(role)` 按角色层级递归并集。

### 4.3 判定优先级(has_permission)

```
1. super_admin → True
2. user_grants[user][module][action] == deny → False
3. user_grants[user][module][action] == allow → True
4. role_permissions(含继承展开)[role][module][action] == 1 → True
5. 否则 → False
```

## 五、分阶段实施

### 阶段 1:后端核心(解决"取消权限不生效"bug)

1. 建 `role_permissions` 表 + 迁移脚本(ROLE_DEFAULT_PERMISSIONS 字典 → 表,REPLACE 可重跑)
2. 重写 `check_permission` / 新增 `has_permission`,改读 DB(角色继承展开 + user_grants)
3. 敏感端点挂 `@require_permission`:
   - `GET /salary`、`GET /salary/verify`、`GET /daily-wages` → `('salary','view')`
   - `POST /export`、`POST /export/all` → `('salary','export')`
   - `GET /config` → `('system','view')`(或 admin)
   - 其余编辑端点按需补(attendance/production/employees edit 等)
4. **viewer 默认去掉 salary:view**(迁移时 viewer 只写 dashboard.view)
5. 新增 `GET /api/permissions/roles`(角色权限列表)+ `PUT /api/permissions/roles`(角色权限编辑,超管)
6. 单元验证:临时 DB 断言判定顺序、角色继承、viewer 无 salary

**验收**:取消某角色 salary:view 后,该角色用户访问 `/salary` 返回 403(解决用户反映的 bug)

### 阶段 2:前后端同步

1. `GET /api/auth/status` 增加 `permissions` 摘要(用户有效权限数组,如 `['dashboard:view','salary:view']`)
2. 前端桌面端:`_authState.permissions` + `hasPermission(module, action)`;`renderSidebar` 按权限过滤模块/子页;`navigate` 无权拦截提示;登录后按权限决定是否拉取薪资
3. 前端移动端:`STATE.auth.permissions` 同步;采集/出勤编辑入口按权限显示
4. 权限管理 UI:新增"角色权限编辑"视图(module×action 勾选矩阵),与单用户 grants 分开展示

**验收**:viewer 登录看不到薪资菜单;直输 `#salary/table` 被拦截;移动端编辑入口按权限显示

### 阶段 3:加固 + 测试

1. `/export` 与 `/export/all` 权限口径统一
2. 双端口径统一(桌面端 editor-only vs 移动端 admin-only → 统一走 hasPermission)
3. 自动化测试:权限判定单测(判定顺序/继承/viewer 无薪资/deny 优先)
4. 权限管理 UI 交互修复(点击 role 来源不再产生垃圾 allow grant)

## 六、风险与注意

- **改角色需重新登录**:session 存 role 快照(app.py:122-126)。阶段 2 后 auth/status 每次实时算权限,前端刷新即可
- **迁移数据**:role_permissions 初始化要与当前字典语义一致,避免上线后权限漂移
- **移动端**:4 Tab 不含薪资,主要影响编辑入口(采集/出勤/档案)与数据台(需 permission 判断是否拉取含薪资 KPI)
- **测试**:项目无自动化测试体系,阶段 3 建议在 `_work/` 建独立 pytest 校验权限判定

## 七、参考报告

- 后端:`_work/permission_framework_report.md`(general-purpose-17 产出)
- 前端:general-purpose-18 前端权限调研报告(对话内)
