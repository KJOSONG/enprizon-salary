---
name: P18 权限管理框架重构
description: 2026-08-14 权限框架重构(角色+单用户双重模型)+P18E UI重构(矩阵表/表格/来源对比)全部上线
type: project
---

## 2026-08-14 P18 权限管理框架重构(已上线,main=0268fec)+P18E(已上线,main=371e7dd)

### P19 三批上线(登录页语言+别名搜索+P1权限修复,main=505c27a)
- **移动端登录页语言切换**(00a58a1):登录页右上角加 #login-lang-btn(点按 toggleLang),applyLang 同步按钮文字;登录页文案本就 data-i18n 且英文键齐全;localStorage m_lang 持久化,登录后顶栏一致,退出保持
- **全系统搜索支持别名 alias**(cc9faeb 后端+b968c09 前端):`search_all` 员工 SQL 加 `OR alias LIKE ?`;`_build_db_ab_index` SELECT 加 alias 并建索引键(setdefault 不覆盖姓名主键)→ make_employee_id(别名) 反查新 ID;前端桌面 6 函数(initEmpTypeahead/renderEmpCheckRows/filterDrMemberList/renderEmployeeTable/filterSalaryTable/renderDailyWages/renderAttendance)+移动 renderAttGrid 统一追加 alias 匹配;薪资/日工资/出勤数据无 alias 字段需从 _empAll/STATE.employees 关联
- **P1 grant 值归一化**(a4a215c 后端+7c47667 前端):`get_user_permissions_summary` grants 覆盖把 grant_type 原值(allow/deny)写入 summary,但契约是 grant/deny → 前端审批人过滤和来源对比 tagMap 不认 'allow' → 被单用户授权的用户进不了审批人下拉、来源对比显示 undefined。修复:后端归一化 `'grant' if allow else 'deny'`;前端 renderPermSources 的 grantMap 同步归一化。**教训:权限 summary 的取值契约(role/grant/deny/none)前后端必须一致,user_grants 表的 grant_type 原值(allow/deny)是另一套**
- QA 最终验收 16/16 + 补充验证通过(审批人下拉含被授权 viewer、来源对比绿/红正常、别名搜索全链路、无回归)

### P18F 登出/登录页面停留 bug 修复(用户反馈"退出后登录页面停留在当前页",已上线,main=f05b173)
- **根因**(两端同):登出只刷新登录按钮状态,不重置路由/不清 STATE 缓存;登录成功后不 navigate 回首页
  - 桌面端 `doLogout()`(index.html):登出后不重置 hash,当前页内容(如薪资页)残留;`submitLogin()` 登录后无 navigate('dashboard')
  - 移动端 `doMobileLogout()`(mobile.html):activeTab 残留;`showApp()` 登录后不重置 tab
- **修复**(8731135,合并 f05b173):桌面端登出=清数据缓存+replaceState hash=#dashboard+navigate('dashboard')+openLoginModal(),登录后 navigate('dashboard');移动端登出清 STATE 数据缓存、showApp 用 switchTab('dashboard') 重置 tab
- **安全点**:登出必须清 STATE 数据缓存,否则下个低权限用户登录后切到有缓存的页面直接看旧数据(数据泄露)
- QA 独立验收 18/18 通过

### P18E 权限管理 UI 重构(用户反馈"已拥有权限无清晰标识"后,参照 stock 用户组/用户管理交互)
- **问题**:P18c 角色编辑打开后,当前角色已拥有权限没有清晰标识(viewer 只读角色看不出拥有什么);继承项 disabled 像"不可用";无汇总统计;用户管理侧 summary 字段未消费;关闭抽屉丢未保存修改
- **方案**(用户 4 决策确认):角色列表改表格、权限编辑改矩阵表、用户抽屉加权限来源对比、角色 CRUD 全部改模态框;参照 enprizon-stock GroupTable+RoleTable 交互,不搬风格
- **交付**(4adf6ab+d34bbeb+2d44fee+930bc2c,feature/mobile-p17 合并 main=371e7dd,后端零改动):
  - 角色表格:角色/已拥有 x/17(effective 展开计数)/用户数/操作,点击行开抽屉
  - 矩阵表:8 分组 × 5 动作(查看/编辑/导出/审批/管理),三态视觉 绿=已拥有(浅绿+左色条)/灰 disabled+chip"来自XX"=继承/黄底+星号=脏;分组标题"已拥有 x/y";底部"已拥有 N/17 · 未保存 M 项";保存/撤销 dirty>0 激活;closeRoleDrawer dirty confirm
  - CRUD 模态框:新增(名称+矩阵)/删除(内置禁删)/恢复默认模态框,重命名抽屉内内联,原生 prompt/confirm 全清
  - 用户管理:表格"权限"列(+N 覆盖徽章);抽屉"权限来源对比"17 行(消费 permissions summary+grants+角色 effective 三重来源,标签 角色默认蓝灰/允许绿/拒绝红/无灰),继承修正(editor dashboard:view 显示"角色默认"非"无")
  - i18n 19 新键双语;dev QA 自验 + qa 独立验收 30/30 无产品 bug;截图 _work/p18e_qa/、_work/p18e_perm_ui.png
- **QA 教训**:验收用临时实例(复制项目到 _work/p18e_tmp/+生产 DB 备份 _work/p18e_backup/),生产 data 未动;权限页写操作必须在隔离 DB 上做
- **经验**:PERMISSION_CATALOG 是 8 分组×动作(非统一 view/add/change/delete),矩阵列用通用动作+灰"—"处理缺失动作;stock RoleTable 的"行首星号脏标记+Save/Reset 按钮 disabled 联动"交互值得沿用

### P18D 角色 CRUD(用户要求角色管理像 stock 组管理支持增删改)
- **决策**:支持自定义角色新增/删除/重命名;内置 3 角色(查看者/编辑员/管理员)保护不可删、可重命名
- **交付**(656f130+0268fec):角色 CRUD API(POST 新增/PUT rename 同步 role_permissions+admin_users/DELETE 内置+有用户保护)+ sync 保护自定义角色 + 前端角色管理动态列表/新增/重命名/删除 + 用户分配自定义角色
- QA 验收 17/17,环境已恢复
- 自定义角色无继承链(仅自身权限);重命名/删除用原生 prompt/confirm(朴素但功能完整)

### P18C 用户权限页双 Tab 重构(参考 enprizon-stock 用户组管理,用户反馈两板块逻辑混乱后)
- **问题**:旧 UI 同屏堆叠"用户管理"+"角色权限编辑",用户不知在改谁、概念不清
- **方案**(用户确认):两个平级 Tab + 单选角色 + 抽屉式编辑
- **交付**(965ba97+f01ee25+a1fbc6f):
  - 用户管理 Tab:用户列表 + 用户编辑抽屉(分配角色下拉/单用户覆盖 allow-deny 增删/改密/删除)
  - 角色管理 Tab:角色卡片(权限计数含继承)+ 角色编辑抽屉(权限矩阵/继承灰标签/未保存计数/保存/撤销/恢复默认)
  - 后端:permissions/users 增加 role+grants 明细;grant deny 已支持
- QA 验收 19/19 + 1 个回归 bug(loadApprovalRoutes 被误删已从 04c867d 恢复,commit a1fbc6f)
- **经验**:enprizon-stock 的信息架构(用户/组独立实体+抽屉式编辑)值得借鉴;P18C 删函数时误删了 P13 审批人设定相关函数导致 ReferenceError

### P18b 权限编辑器 UI 重构(用户反馈 UI 不清晰后重做)
- **问题**:旧 UI 三角色混 120 格大表,不知在改谁、勾选无反馈、无效组合多、权限与功能不对应
- **方案**(用户确认):角色中心 Tab + 功能分组 + 有效权限项(17项)+ 功能说明 + 继承显示 + 强反馈
- **交付**(012ee7b+04c867d):
  - 后端:权限项收敛(viewer=5查看项/editor/admin继承)+ 查看类端点 enforcement(attendance/employees/production/scoring/oa 查看端点挂权限)+ roles API(?role=过滤+reset)+ PERMISSION_CATALOG(17项中文元数据,8分组)
  - 前端:权限编辑器重写(角色 Tab/功能分组/继承灰标签/勾选高亮/未保存计数/保存撤销恢复默认)
- QA 验收 25/25 通过
- **裁决**:桌面端无独立"产量查看"模块,viewer 产量通过数据台(dashboard:view)看;采集模块(production:edit)对 viewer 隐藏(提交是编辑功能)。用户确认接受现状
- **遗留**:PERMISSION_CATALOG 中文硬编码(英文 UI fallback 中文);KEJU 临时密码 Keju2026! 待用户改回

### viewer 默认权限(查看类全开放,用户确认)
`dashboard:view, production:view, attendance:view, employees:view, oa:view`(无薪资/评分/编辑/导出)
editor = viewer + production/attendance/employees edit + export + oa:approve + scoring + salary:view
admin = editor + salary:export + system:view

### 桌面端 MODULES 权限标注(重要)
dashboard→dashboard:view;employees→employees:view;attendance→attendance:view;salary→salary:view;collection→production:edit;scoring→scoring:view;system→system:view。OA 是员工模块子页(非独立模块)。无独立"产量"模块。

### 背景问题
用户反映:在某角色设置中取消"薪资查看"权限,但该角色用户登录后仍能看到薪资页。

### 根因(四层叠加)
1. `/salary`、`/daily-wages`、`/salary/verify`、`/export` 等端点只挂 `@login_required`,任何登录用户可读(app.py)
2. 细粒度 `@require_permission` 只挂 2 端点(OA 审批 + export/all),形同虚设
3. 角色默认权限硬编码 Python 字典 `ROLE_DEFAULT_PERMISSIONS`,viewer 默认含 salary:view;`check_permission` 读字典不读表,permissions 表无 role 列
4. 前端菜单只判登录态,薪资菜单全量渲染,hash 可直达;权限 UI 的 toggleUserGrant 点击 role 来源=添加 allow grant,无 deny 路径,永远取消不掉

### 重构方案(用户确认 4 决策)
1. 权限模型:角色默认权限(DB role_permissions 表可编辑)+ 单用户 user_grants allow/deny 覆盖
2. viewer 默认**去掉** salary:view(仅 dashboard.view)
3. 角色继承:super_admin 全权限;admin 继承 editor+viewer;editor 继承 viewer
4. 分阶段实施

### 判定优先级(has_permission)
super_admin → user_grants.deny → user_grants.allow → role_permissions(继承展开)→ False

### 阶段交付
- **阶段 1**(7e3e57c):role_permissions 表 + sync_role_permissions 迁移 + check_permission 重写(DB+继承+deny 优先)+ 敏感端点挂权限(/salary 等 → salary:view, /export → salary:export, /config → system:view)+ GET/PUT /api/permissions/roles
- **阶段 2**(270aa49+644cb8d):auth/status 返回 permissions 摘要;桌面端 renderSidebar/navigate 按权限过滤、登录按权限拉数据、角色权限编辑 UI(module×action×role 矩阵);移动端 hasPermission + 采集/出勤/oa 守卫
- **bug 修复**(f30317d):桌面端 no_perm 提示 `toast()` 未定义 → 改 `showToast()`(QA 发现)
- QA 完整验收通过(见 docs/P18_PERMISSION_QA.md)

### 服务器账号(重要)
- KEJU → super_admin,**密码 2026-08-14 被重置为临时值 `Keju2026!`**(原密码丢失,用户批准重置,QA 验收用)。用户需改回
- user → viewer(qweasd 默认)
- BARAKA → editor(密码未知)

### 遗留(阶段 3 可选)
- /export/employees、/export/attendance 未挂细粒度权限
- 双端口径统一(桌面 editor-only vs 移动 admin-only → hasPermission)
- 自动化权限测试
- role_permissions 表残留 viewer salary/view allow=0 记录(功能等价无影响)
- session 角色快照,改权限后需重新登录

### 经验
- 前端 hasPermission 需与后端 get_user_permissions 口径一致(`*:*` 通配)
- 权限 UI 必须支持"取消"(deny/allow=0),否则永远加权限无法撤销(原 bug 根源之一)
- 改权限后 auth/status 实时计算(permissions 每次算),但 role 是 session 快照,角色变更需重登
