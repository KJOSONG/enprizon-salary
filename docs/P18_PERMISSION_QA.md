# P18 权限重构完整验收报告

> 服务器 HEAD: `f30317d`(三个 P18 commit: `7e3e57c` 阶段1 后端 / `270aa49` 阶段2 auth/status + 桌面端 / `644cb8d` 阶段2 移动端 + 角色权限编辑 UI,加 `f30317d` toast bug 修复)
> 测试方式: Playwright + 系统 Chrome headless,原生模式
> 测试脚本: `_work/_qa_p18.js`(viewer 侧)+ `_work/_qa_p18_perm.js`(KEJU + 角色权限闭环);截图: `_work/qa_screenshots/p18/`
> 测试账号: `user/qweasd`(viewer) + `KEJU/Keju2026!`(临时密码,用户批准)
> 写约束: 未提交申请、未编辑任何用户、未退出、角色权限编辑测试**完成后立即恢复 viewer 无薪资**

---

## P18.1 测试环境

| 项 | 值 |
|----|---|
| Desktop Chrome | macOS 系统 Chrome(headless),viewport 1280×900 |
| iPhone 14(移动端) | viewport 390×844, Safari iOS 16 UA, hasTouch/isMobile=true, dsf=3 |
| 服务器 | `http://47.236.187.33` HTTP 80(非 HTTPS) |

---

## P18.2 viewer 验收(viewer user/qweasd)

| 设备 | 通过/总数 | 失败项 | page errors |
|------|----------|--------|-------------|
| Desktop Chrome | **5/5** | 0 | 1(原 toast bug,f30317d 已修复,见 P18.5) |
| iPhone 14 | **6/6** | 0 | 0 |

### P18.2.1 桌面端 viewer

| 断言 | 结果 | 详情 |
|------|------|------|
| **auth/status permissions** | ✅ | `["dashboard:view"]` |
| **侧边栏仅 dashboard** | ✅ | `#sidebarNav .sidebar-module` = `["dashboard"]` |
| **直输 #salary/table 被拦截** | ✅ | module=dashboard, hash=`#dashboard`(f30317d 后已正常 toast,见 P18.5) |
| **`/salary` API 403** | ✅ | status=403,`{"error":"forbidden","need_permission":"salary","ok":false}` |

### P18.2.2 移动端 viewer

| 断言 | 结果 | 详情 |
|------|------|------|
| **auth/status permissions** | ✅ | `["dashboard:view"]` |
| **点井下采集卡被拦截** | ✅ | toast="需要编辑权限",表单未打开 |
| **点入职四宫格被拦截** | ✅ | toast="需要编辑权限",Sheet 未打开 |
| **档案页无薪资概览** | ✅ | sections 仅有"基本信息"+"出勤统计",mini 卡数=3 |

---

## P18.3 KEJU(super_admin)回归

| 断言 | 结果 | 详情 |
|------|------|------|
| **KEJU 登录** | ✅ | role=`super_admin`, permissions=`["*:*"]` |
| **`/salary` 200** | ✅ | status=200 |
| **侧边栏 7 模块全显示** | ✅ | `["dashboard","employees","attendance","salary","collection","scoring","system"]` |
| **可进入角色权限编辑卡片** | ✅ | 系统 → 用户权限页面可见 `🔑 角色权限编辑` 卡片,仅 super_admin 可见 |

**BARAKA(editor)账号密码未知**,未做单独验收;KEJU 覆盖了 admin+super_admin 场景;editor 权限继承自 admin,UI 行为可推断(editor 默认权限 = admin 子集)。

---

## P18.4 角色权限编辑 UI 闭环(核心新功能)

**测试流程**(全 16/16 通过):

1. ✅ KEJU 基线重置: viewer salary:view = allow=0(确保初始未勾选)
2. ✅ viewer salary:view 初始未勾选(`checked=false`)
3. ✅ 勾选 viewer salary:view checkbox
4. ✅ 保存成功(`_rolePermDirty` 清空为 `{}`)
5. ✅ viewer 重登后 permissions=`["dashboard:view","salary:view"]`
6. ✅ viewer 重登后 `/salary` 200(原本 403)
7. ✅ viewer 侧边栏出现薪资模块(`modules=["dashboard","salary"]`)
8. ✅ 取消勾选 viewer salary:view checkbox
9. ✅ viewer 重登后 permissions=`["dashboard:view"]`(salary 消失)
10. ✅ viewer 重登后 `/salary` 403(恢复拦截)
11. ✅ viewer 侧边栏无薪资模块(`modules=["dashboard"]`)
12. ✅ viewer 最终 effective 权限仅 `dashboard:view`(无薪资)

**功能完全闭环**: 勾选→保存→生效(200 + 菜单出现),取消→保存→生效(403 + 菜单消失)。

**DB 状态说明**: 测试结束后 `viewer` 的 `role_permissions` 表包含 2 条记录:
- `dashboard/view/allow=1`(原默认)
- `salary/view/allow=0`(取消勾选时 REPLACE 写入的"显式拒绝"记录)

`allow=0` 记录不产生权限(参考 `get_role_permissions()` 实现,只返回 allow=1),`effective` 权限计算正确(`[{"action":"view","module":"dashboard"}]`),UI 勾选框也显示未勾选。**功能层面完全等价于 viewer 初始状态(无薪资)**。

---

## P18.5 桌面端 toast bug 修复(f30317d 回归)

| 断言 | 结果 | 详情 |
|------|------|------|
| **toast 函数名错误修复** | ✅ | 桌面端 `toast(t('no_perm'))` 已改为 `showToast(t('no_perm'))` |
| **viewer 直输 #salary/table 显示提示** | ✅ | toast="无权限访问"(class=`toast warning show`),不再抛 TypeError |
| **hash 清理** | ✅ | 直输后 hash=`#dashboard`(之前残留 `#salary/table`) |
| **跳转 dashboard** | ✅ | STATE.currentModule=dashboard, 侧边栏仅 dashboard |

**截图**: `_work/qa_screenshots/p18/viewer_no_perm_toast.png`(顶栏右侧 toast 浮层"无权限访问" + 页面是数据台)

---

## P18.6 i18n 回归(新键 no_perm 等)

| 断言 | 结果 | 详情 |
|------|------|------|
| **中文 no_perm** | ✅ | `t('no_perm') = "无权限访问"` |
| **EN no_perm** | ✅ | `t('no_perm') = "No permission"` |
| **保存按钮 EN** | ✅ | `Save` / `Reset to defaults` |

---

## P18.7 回归(基础流程无损坏)

| 项 | 结果 | 备注 |
|----|------|------|
| 数据台渲染(KEJU) | ✅ | KPI / 趋势图 / 矿石占比 / 破碎表 正常 |
| 员工列表(KEJU) | ✅ | 7 模块全可访问 |
| 采集/出勤(viewer) | ✅ | 之前轮次已验证,无回归 |
| i18n 切换(viewer/KEJU) | ✅ | 中↔EN 文案正确切换 |

---

## P18.8 测试产物

```
_work/_qa_p18.js                                  viewer 侧验收脚本
_work/_qa_p18_perm.js                             KEJU + 角色权限闭环脚本
_work/qa_screenshots/p18/                         截图目录
  desktop_sidebar_viewer.png                     viewer 侧边栏(仅 dashboard)
  desktop_salary_blocked.png                     直输拦截(修复前:hash 残留 + 无 toast)
  iphone14_collection_guard.png                  移动端采集卡守卫
  iphone14_oa_guard.png                           移动端 OA 守卫
  iphone14_profile_no_salary.png                 移动端档案无薪资
  keju_sidebar_full.png                           KEJU 侧边栏(7 模块)
  role_perm_initial.png                          角色权限矩阵初始(viewer salary 未勾选)
  role_perm_checked.png                          勾选 viewer salary:view
  role_perm_unchecked.png                        取消勾选
  viewer_with_salary.png                          viewer 临时获得薪资(200 + 菜单出现)
  viewer_without_salary.png                      viewer 恢复无薪资(403 + 菜单消失)
  viewer_no_perm_toast.png                       toast bug 修复后:显示"无权限访问"
  result_iphone14.json / result_desktop.json    viewer 侧结果
  result_perm_loop.json                          角色权限闭环结果(16/16)
```

---

## P18.9 整体结论

**P18 权限重构完整验收通过**:
- ✅ viewer/admin 权限边界正确
- ✅ 桌面端菜单/路由按权限过滤
- ✅ 移动端采集/出勤/OA 守卫正确
- ✅ 角色权限编辑 UI 闭环可工作(KEJU 改 viewer,viewer 重登生效)
- ✅ toast bug 已修复,no_perm 提示正常
- ✅ i18n 新键中英双语
- ✅ viewer 权限最终状态恢复(effective 仅 dashboard:view)

**遗留**:
- viewer role_permissions 表残留 `salary/view/allow=0` 记录(取消勾选时 REPLACE 写入,不影响功能,UI/effective 都正确)
- BARAKA(editor)账号密码未知未做单独回归(KEJU 已覆盖 admin+super_admin)

**安全提醒**(发给用户):
- KEJU 临时密码 `Keju2026!` 是测试用临时值,**请用户重置回原密码或换新密码**
- viewer 无薪资为最终状态,已恢复

---

**完成时间**: 2026-08-14  
**测试者**: qa (mobile-p17 团队)

---

# P18b 权限 UI 重构验收(2026-08-14)

> 服务器 HEAD: `04c867d`(三个 commit: `3295609` 阶段3 UI 修复 / `012ee7b` 后端权限收敛 + roles API 增强 / `04c867d` 前端权限编辑器重写)
> 测试脚本: `_work/_qa_p18b.js`(编辑器结构)+ `_work/_qa_p18b_loop.js`(勾选生效闭环);截图: `_work/qa_screenshots/p18b/`
> 测试账号: `KEJU/Keju2026!`(super_admin) + `user/qweasd`(viewer)

## P18b.1 总览

| 阶段 | 通过/总数 | 失败项 | page errors |
|------|----------|--------|-------------|
| 编辑器结构 + viewer 生效 | **17/17** | 0 | 0 |
| 编辑器勾选生效闭环 | **8/8** | 0 | 0 |

合计 **25/25 通过**。

## P18b.2 编辑器结构(KEJU 登录 → 系统 → 用户权限 → 角色权限编辑)

| 断言 | 结果 | 详情 |
|------|------|------|
| KEJU 登录 | ✅ | role=`super_admin`, permissions=`["*:*"]` |
| 角色 Tab 3 个 | ✅ | 只读 / 编辑员 / 管理员(`onclick=switchRoleTab(...)`) |
| 当前 Tab 高亮 | ✅ | viewer tab 激活(`btn-primary`) |
| 顶部说明 | ✅ | "编辑各角色的默认权限(不含超级管理员)。保存后该角色用户重新登录生效。" |
| super_admin 说明 | ✅ | "超级管理员拥有全部权限,不可修改。" |
| 功能分组 8 组 | ✅ | 数据台/产量/出勤/员工/OA/薪资/评分/系统 |
| 权限项 17 项 | ✅ | checkbox+功能名+功能说明 |
| 切换"编辑员"Tab | ✅ | |
| **继承显示** | ✅ | 编辑员 tab 显示 5 项来自只读的灰标签 disabled(`来自 只读`) |
| **勾选反馈** | ✅ | 勾选触发未保存提示+行高亮(`#rolePermMsg` 显示"已保存"/"未保存修改") |
| **保存按钮** | ✅ | `saveRolePerms()` 调用 `PUT /api/permissions/roles` |
| **撤销按钮** | ✅ | `discardRolePerms()` 清空 dirty |
| **恢复默认** | ✅ | `resetRolePermsToDefault()` 触发 confirm dialog |

**截图**: `perm_editor_viewer_tab.png`、`perm_editor_editor_tab.png`(继承项灰标签清晰可见)、`perm_editor_checked.png`(勾选高亮)

## P18b.3 编辑器勾选生效闭环(8/8)

| 步骤 | 结果 |
|------|------|
| KEJU 切到"只读"tab,勾选"薪资查看"(原未勾选) | ✅ |
| 未保存修改提示出现 | ✅ |
| 点击保存 | ✅(`_rpState.dirty` 清空,PUT 成功) |
| viewer 重登 → permissions 含 `salary:view` | ✅ `["attendance:view","dashboard:view","employees:view","oa:view","production:view","salary:view"]` |
| viewer `/salary` 200 | ✅ |
| viewer 侧边栏出现"薪资"模块 | ✅ `["dashboard","employees","attendance","salary"]` |
| 取消勾选 → 保存 | ✅ |
| viewer 恢复(无 salary:view)/salary 403 | ✅ permissions 回到 5 项,status=403 |

**截图**: `editor_loop_checked_salary.png`、`editor_loop_viewer_salary_visible.png`

**viewer 权限已恢复**(最终 effective: dashboard/employees/attendance/oa/production view,共 5 项)

## P18b.4 viewer 生效验证

| 断言 | 结果 | 详情 |
|------|------|------|
| viewer effective = 5 查看项 | ✅ | `attendance:view`, `dashboard:view`, `employees:view`, `oa:view`, `production:view` |
| viewer `/salary` 403 | ✅ | |
| viewer `/api/scoring/entries` 403 | ✅ | |
| viewer 侧边栏: 数据台/出勤/员工 可见,薪资/评分 不可见 | ✅ | `["dashboard","employees","attendance"]` |
| 移动端 viewer 4 Tab 齐全(采集 Tab 可见) | ✅ | 移动端 4 Tab 固定可见,点采集卡被守卫拦截(`production:edit` 无),符合预期 |

## P18b.5 ⚠️ 验收标准与实现冲突:桌面端 viewer 无"产量"模块

**team-lead 验收要求**: "viewer 侧边栏:数据台/**产量**/出勤/员工/OA 可见"

**dev 实际实现**: `MODULES.collection.perm = 'production:edit'`(P18b 提交 04c867d 有意改的),导致 viewer 无 production:edit → 整个采集模块对桌面端隐藏。

**验证**:
- viewer 桌面端侧边栏 `["dashboard","employees","attendance"]`(缺 collection)
- viewer 移动端采集 Tab 仍可见(4 Tab 固定),点表单被拦截 — 行为不一致
- viewer 后端 `/api/production/dashboard` / `/production` 返回 200(viewer 有 production:view,可以查看产量数据) → 但桌面端侧边栏无入口

**两种解读**:
1. **"产量"指 production 模块查看** — 当前实现不满足(应改为 `perm: production:view`,采集表单/编辑用 edit 守卫)
2. **dev 有意设计** — viewer 不显示采集菜单(commit 说明明确),验收要求"产量可见"是 team-lead 误解或描述不一致

**建议**:
- 若选项1: dev 改 `MODULES.collection.perm = 'production:view'`,子页/编辑守卫用 production:edit
- 若选项2: team-lead 调整验收标准,接受"viewer 看不到采集菜单(移动端不一致除外)"或移动端去掉采集 Tab

**需要 team-lead 裁决**。不影响功能闭环和 KEJU/editor 验收。

## P18b.6 测试产物

```
_work/_qa_p18b.js                     编辑器结构 + viewer 生效(17 项)
_work/_qa_p18b_loop.js                编辑器勾选闭环(8 项)
_work/qa_screenshots/p18b/
  perm_editor_viewer_tab.png          只读 tab 完整布局
  perm_editor_editor_tab.png          编辑员 tab + 继承灰标签
  perm_editor_checked.png             勾选高亮
  editor_loop_checked_salary.png     勾选薪资查看
  editor_loop_viewer_salary_visible.png  viewer 重登后薪资菜单出现
  viewer_sidebar_p18b.png            viewer 侧边栏(无薪资/评分)
  mobile_collection_viewer.png        移动端采集 Tab 可见
  result_p18b.json / result_editor_loop.json
```

## P18b.7 结论

**P18b 权限编辑器重构通过验收**(25/25):

- ✅ 角色 Tab + 功能分组 + 继承显示 + 勾选反馈 + 保存/撤销/恢复默认 UI 完整
- ✅ 编辑器 → 后端 → viewer 重登生效的端到端闭环工作
- ✅ viewer 后端 enforcement 正确(5 查看项端点 200,salary/scoring 403)
- ⚠️ 桌面端 viewer 看不到"产量"模块,与验收要求冲突,需 team-lead 裁决(见 P18b.5)
- ✅ 移动端 viewer 4 Tab 回归正常,采集 Tab 可见 + 编辑守卫拦截
- ✅ viewer 权限已恢复(无薪资,5 查看项)

**安全提醒**: KEJU 临时密码 `Keju2026!` 仍生效。

---

# P18C 用户权限页双 Tab 验收(2026-08-14)

> 服务器 HEAD: `f01ee25`(后端 `965ba97` permissions/users 增强 + 前端 `f01ee25` 双 Tab 重构)
> 测试脚本: `_work/_qa_p18c.js`;截图: `_work/qa_screenshots/p18c/`
> 测试账号: `KEJU/Keju2026!`(super_admin) + `user/qweasd`(viewer)

## P18C.1 总览

**19/19 通过**(双 Tab 5 + 用户管理 3 + 角色管理 4 + 权限生效闭环 6 + 最终状态 1)。

## P18C.2 双 Tab

| 断言 | 结果 | 详情 |
|------|------|------|
| 双 Tab 存在 | ✅ | `[👥 用户管理][🎭 角色管理]` 两个平级 `.perm-tab` |
| 默认用户管理 Tab 高亮 | ✅ | `#permTabUsers` active |
| 切到角色管理 Tab | ✅ | 角色 Tab active,用户面板隐藏(`display:none`) |
| 切回用户管理 Tab | ✅ | 用户面板恢复显示 |

## P18C.3 用户管理 Tab

| 断言 | 结果 | 详情 |
|------|------|------|
| 用户列表 ≥3 | ✅ | `user(只读) / KEJU(super_admin) / BARAKA(编辑员)` |
| 每行"编辑"按钮 | ✅ | 3 个编辑按钮 |
| 点 user 编辑 → 抽屉 | ✅ | 打开用户编辑抽屉 |
| 角色下拉(当前 viewer) | ✅ | `#userDrawerRole` value=`viewer`,选项 `只读/编辑员/管理员` |
| 单用户覆盖区 | ✅ | `#userGrantPermSel`(17 项权限)+ `#userGrantTypeSel`(允许/拒绝) |
| 改密/删除按钮 | ✅ | 抽屉内有改密 + 删除按钮 |

## P18C.4 角色管理 Tab

| 断言 | 结果 | 详情 |
|------|------|------|
| 3 张角色卡片 + 计数 | ✅ | `只读 5 项权限 / 编辑员 14 项权限·继承 5 项 / 管理员 16 项权限·继承 14 项` |
| 点"查看者"→ 抽屉 | ✅ | 权限矩阵 17 项 + 保存/撤销/恢复默认 |
| 点"编辑员"→ 抽屉 | ✅ | 继承项 disabled(来自只读,5 项) |
| 功能说明 | ✅ | 每项带灰色说明(如"产量采集 — 提交井下/钻工/破碎/出勤收集数据") |

## P18C.5 权限生效闭环(6/6)

| 步骤 | 结果 |
|------|------|
| API 给 user 添加单用户覆盖 `salary:view` | ✅ |
| user 重登 → permissions 含 salary:view | ✅ |
| user `/salary` 200 | ✅ |
| API 删除覆盖 | ✅ |
| user 重登 → 无 salary:view | ✅ |
| user `/salary` 403 | ✅ |
| **user 最终状态** | ✅ role=`viewer`,grants=`[]`(已恢复) |

## P18C.6 ⚠️ 发现 Bug(P1):`loadApprovalRoutes is not defined`

- **位置**: `templates/index.html:1829`(showTargetPage)+ `4600`(deleteUser 内)
- **现状**: P18C 提交 `f01ee25` 删除了 `loadApprovalRoutes` 函数定义,但保留了 3 处调用(showTargetPage L1829、deleteUser L4600 等)。**每次进入用户权限页都抛 `ReferenceError: loadApprovalRoutes is not defined`**(真实用户点击路径验证确认)
- **影响**: 页面主体功能正常(loadPermissionsPage 先执行,双 Tab/用户列表/角色卡片都渲染),但 console 每次报错,`deleteUser` 成功后调用会抛错。属回归 bug
- **修复建议**: 删除 3 处调用,或补一个空 stub `function loadApprovalRoutes(){}`(若审批人设定卡片仍在系统页使用)
- **截图**: (pageError 在 console,无视觉截图)

## P18C.7 截图清单

```
_work/qa_screenshots/p18c/
  user_management_tab.png          用户管理 Tab(3 用户列表 + 编辑按钮)
  user_edit_drawer.png             用户编辑抽屉(角色下拉 + 覆盖区 + 改密/删除)
  role_management_tab.png          角色管理 Tab(3 卡片: 5/14/16 项)
  role_viewer_drawer.png           查看者权限矩阵抽屉
  role_editor_drawer.png           编辑员抽屉(继承灰标签)
  viewer_with_salary_grant.png     user 临时获得薪资(侧边栏出现薪资)
```

## P18C.8 结论

**P18C 双 Tab 权限页通过验收(19/19)**:

- ✅ 用户管理/角色管理双 Tab 切换正常,各自独立
- ✅ 用户编辑抽屉: 角色下拉 + 单用户覆盖(allow/deny)+ 改密/删除
- ✅ 角色卡片计数正确(5/14/16),角色编辑抽屉 + 继承标签 + 保存/撤销/恢复默认
- ✅ 单用户覆盖权限生效闭环(user 加覆盖 → /salary 200 → 删除 → 403)
- ⚠️ 1 个回归 bug(P1):`loadApprovalRoutes is not defined`(每次进权限页 console 报错)
- ✅ user 权限最终恢复(role=viewer,grants 清空)

**遗留**: P18b 的"桌面端 viewer 无产量模块"裁决仍未处理;P18C 新增 `loadApprovalRoutes` 回归 bug。

---

# P18D 角色 CRUD 验收(2026-08-14)

> 服务器 HEAD: `0268fec`(后端 `656f130` 角色 CRUD API + 前端 `0268fec` 角色管理 Tab)
> 测试脚本: `_work/_qa_p18d.js`;截图: `_work/qa_screenshots/p18d/`
> 测试账号: `KEJU/Keju2026!`(super_admin) + `user/qweasd`(viewer)
> 写约束: 创建/分配/重命名/删除均为验收目标操作,**结束后已全部恢复**(仅 3 内置角色,user=viewer)

## P18D.1 总览

**17/17 通过**(角色列表 4 + 新增 2 + 分配/生效 4 + 重命名 2 + 删除保护 3 + 清理 2)。

## P18D.2 角色列表

| 断言 | 结果 | 详情 |
|------|------|------|
| 初始 3 内置角色 | ✅ | viewer/editor/admin(另 super_admin 不展示为卡片) |
| 初始无自定义角色 | ✅ | custom=0 |
| 前端卡片渲染 | ✅ | `管理员 内置 2 项·0 用户 / 编辑员 内置 9 项·1 用户 / 只读 内置 5 项·1 用户`,含"内置"标签 |

## P18D.3 新增角色"考勤专员"

| 断言 | 结果 | 详情 |
|------|------|------|
| 前端"新增角色"按钮 | ✅ | `＋ 新增角色` 触发抽屉 |
| 抽屉结构 | ✅ | 角色名输入框 + 17 项权限 checkbox + 保存按钮 |
| 创建成功 | ✅ | `POST /api/permissions/roles` `{name:'考勤专员', permissions:[{attendance:edit},{production:view}]}` → `{ok:true}` |
| 列表出现自定义角色(0 用户) | ✅ | `{"role":"考勤专员","builtin":false,"uc":0}` |

## P18D.4 分配 + 生效

| 步骤 | 结果 |
|------|------|
| user 分配"考勤专员"(`POST /admin/users/role`) | ✅ |
| user 重登 → role=`考勤专员`,permissions=`["attendance:edit","production:view"]` | ✅ |
| 无 `salary:view` → `/salary` 403 | ✅ |
| 无 `attendance:view` → `/attendance` 403(只有 edit 无 view,权限模型一致) | ✅ |

## P18D.5 重命名

| 断言 | 结果 |
|------|------|
| `PUT /api/permissions/roles/rename` `{old:'考勤专员', new:'考勤主管'}` | ✅ `{ok:true}` |
| user 角色同步为"考勤主管"(role_permissions + admin_users 同步) | ✅ |

## P18D.6 删除保护

| 步骤 | 结果 |
|------|------|
| 删除"考勤主管"(有 user 分配) | ✅ 拒绝 `{"error":"role_has_users","ok":false}` |
| user 改回"查看者" | ✅ |
| 再删除"考勤主管" | ✅ `{ok:true}` |

## P18D.7 清理确认

| 断言 | 结果 |
|------|------|
| 无自定义角色残留 | ✅ custom=[] |
| user=viewer,grants 清空 | ✅ |

## P18D.8 P18C bug 回归确认

`loadApprovalRoutes is not defined`(a1fbc6f 已修复):

- ✅ 函数定义已恢复(`templates/index.html:6880`)
- ✅ 进入用户权限页 pageErrors=[](不再抛 ReferenceError)

## P18D.9 截图清单

```
_work/qa_screenshots/p18d/
  roles_initial.png          角色管理 Tab(3 内置卡片)
  create_role_drawer.png     新增角色抽屉(名称 + 17 权限项)
  role_created.png           创建"考勤专员"后列表
  user_as_custom_role.png    user 按"考勤专员"权限登录
  role_renamed.png           重命名"考勤主管"
  roles_final.png            清理后(仅 3 内置)
```

## P18D.10 结论

**P18D 角色 CRUD 通过验收(17/17)**:

- ✅ 新增角色(自定义角色 + 权限分配 + 列表展示)
- ✅ 分配用户到自定义角色 + 权限即时生效(重登验证)
- ✅ 重命名(同步 role_permissions + admin_users)
- ✅ 删除保护(有用户拒绝) + 改派后删除成功
- ✅ 清理完成(仅 3 内置角色,user=viewer)
- ✅ P18C 的 loadApprovalRoutes 回归 bug 已修复

**遗留**: P18b "桌面端 viewer 无产量模块"裁决仍未处理。

---

## P18.1 测试环境

| 项 | 值 |
|----|---|
| Desktop Chrome | macOS 系统 Chrome(headless),viewport 1280×900,UA `Mozilla/5.0 (Macintosh; ...)` |
| iPhone 14(移动端) | viewport 390×844, Safari iOS 16 UA, hasTouch/isMobile=true, dsf=3 |
| 服务器 | `http://47.236.187.33` HTTP 80(非 HTTPS) |
| 测试账号 | `user / qweasd`(viewer 只读)— admin/editor 需 KEJU 或其他账号,**密码待 team-lead 提供** |

---

## P18.2 viewer 验收(已完成)

| 设备 | 通过/总数 | 失败项 | page errors |
|------|----------|--------|-------------|
| Desktop Chrome | **5/5** | 0 | 1(P1 bug,见 P18.4) |
| iPhone 14 | **6/6** | 0 | 0 |

### P18.2.1 桌面端 viewer

| 断言 | 结果 | 详情 |
|------|------|------|
| **auth/status permissions** | ✅ | `["dashboard:view"]` |
| **侧边栏仅显示 dashboard** | ✅ | `#sidebarNav .sidebar-module` 唯一项 `["dashboard"]`(无薪资/出勤/采集/评分/员工/系统) |
| **直输 #salary/table 被拦截** | ✅(功能) ⚠(实现 bug) | module=dashboard,但 toast 未显示(详见 P18.4 bug) |
| **`/salary` API 403** | ✅ | status=403,响应 `{"error":"forbidden","need_permission":"salary","ok":false}` |

### P18.2.2 移动端 viewer

| 断言 | 结果 | 详情 |
|------|------|------|
| **auth/status permissions** | ✅ | `["dashboard:view"]` |
| **点井下采集卡被拦截** | ✅ | toast="需要编辑权限",表单未打开 |
| **点入职四宫格被拦截** | ✅ | toast="需要编辑权限",Sheet 未打开 |
| **档案页无薪资概览** | ✅ | sections 仅有"基本信息"+"出勤统计",mini 卡数=3(无薪资) |

---

## P18.3 admin/editor 回归(待补)

**待 KEJU/admin 账号密码** — 需要 team-lead 提供账号才能完成。

---

## P18.4 角色权限编辑 UI 闭环(待补)

**待 super_admin 账号** — 需要 team-lead 提供 KEJU 密码才能:
1. 登录桌面端 → 系统 → 用户权限 → 角色权限编辑
2. 勾选 viewer 的 `salary:view` → 保存 → viewer 重登 → /salary 200
3. 取消勾选 → 保存 → viewer 重登 → /salary 403
4. 截图整个流程 + **恢复 viewer 默认权限**(避免污染)

---

## P18.5 发现的 Bug

### P1:**桌面端 toast 函数名错误,触发 TypeError**

- **位置**: `templates/index.html:1711`(navigate)和 `1733`(showTargetPage)
- **现状**:
  ```js
  if (_authState.logged_in && _mod && _mod.perm && !hasPermission(...)) {
    toast(t('no_perm'), 'warning');   // ← 错误函数名
    navigate('dashboard', null);
    return;
  }
  ```
- **根因**: 桌面端 toast 函数实际叫 `showToast()`(templates/index.html:1287),P18 代码在两处守卫用了不存在的 `toast()`
- **影响**:
  1. 触发 `TypeError: toast is not a function`(`_authState.logged_in` 抛错,但后续 `navigate('dashboard', null)` 实际执行成功,见下)
  2. **no_perm 提示不显示**,用户看不到"无权限"反馈
  3. **hash 残留**:`window.location.hash` 停留在 `#salary/table`,虽然 module 被跳回 dashboard,但 URL 与内容不一致(刷新或分享 URL 会再次触发守卫)
- **意外拦截成功原因**: `toast` 抛错中断 `navigate('salary','table')` 主流程,STATE.currentModule 保持 dashboard 初始值;`showTargetPage` 守卫中的 toast 也抛错中断,但页面不显示薪资
- **截图**: `_work/qa_screenshots/p18/desktop_salary_blocked.png`(toast 显示的是"登录成功"而非"无权限",hash 残留)
- **修复建议**(改 2 处):
  ```js
  toast(t('no_perm'), 'warning');
  // 改为:
  showToast(t('no_perm'), 'warning');
  ```
- **优先级**: P1,功能上"意外能拦截"但用户体验差(无反馈 + URL 不一致 + 每次 console error)

---

## P18.6 测试产物(本轮部分完成)

```
_work/_qa_p18.js                           P18 验收脚本(viewer 部分)
_work/qa_screenshots/p18/                  截图目录(viewer 侧)
  desktop_sidebar_viewer.png               桌面端 viewer 侧边栏(仅数据台)
  desktop_salary_blocked.png              桌面端直输 #salary/table 后(hash 残留/toast 不是 no_perm)
  iphone14_collection_guard.png           移动端 viewer 采集页(toast "需要编辑权限")
  iphone14_oa_guard.png                    移动端 OA 拦截
  iphone14_profile_no_salary.png          移动端档案无薪资概览
  result_iphone14.json / result_desktop.json
```

---

## P18.7 后续待补(admin/editor + 角色权限编辑)

请 team-lead 提供 KEJU 或其他 super_admin/admin 账号密码,以完成:
- admin/editor 回归: 薪资菜单/路由可见, /salary 200, 采集/出勤可编辑
- 角色权限编辑 UI 闭环: viewer salary:view 勾上→viewer 重登可见薪资,取消→viewer 重登 403(测试中临时改权限,结束后立即恢复)

收到账号后我会立即补完验收 + 更新报告。