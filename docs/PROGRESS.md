# PROGRESS.md — 开发进度编年史（P0 → 当前）

> 全项目批次/阶段的**唯一编年记录**。每条固定格式：**日期 · 标题（哈希，部署状态）→ 内容 / 验收 / 坑**。
> 新批次完成后在对应月份顶部追加一条，并同步更新 `docs/STATUS.md` 的 main 哈希。
> 不要再把进度写进记忆速查卡或 current_state（那两个已改为指针）。
> 各批次的方案/审查/QA 原件在 `.codebuddy/specs/<任务名>/`（索引见 specs/INDEX.md）；早期 P 阶段详设在 `docs/P*.md`；更细的历史记忆归档在 `docs/archive/memory/`。

---

## 2026-11

### 2026-11-07 · 审计 9 问题修复（`a424ac2` ← `78ed68c`，已部署，生产冒烟通过）
- 双重审查确认 9 个真实 bug 全修：①`/export/all` Sheet4 公式损坏（纯数字+`get_column_letter`，174 公式零非法）②PDF 工资单 GROSS 漏 bonus/driver/sick_subsidy ③Excel 加 Sick Subsidy 列（第 11 列，索引全同步）④采集编辑/OA 改期跨月关账闸门 409 + days 上限 365/366 双层 clamp（堵 OOM）⑤effective_month 口径四处统一 + `_invalidate_month_cache_from` ⑥`calculate_all` 日期集合镜像对齐（钻工-only 日 monthly 员工误入钻工池，沙盒实证 Σ 不守恒→修复守恒）⑦scoring 池 teams 分支 ⑧死常量删除。
- 验收：97 测试 / 双月逐分 0 差异（10 月 62,770,927）/ PDF 勾稽 3/3。备份 `kilwa_before_auditfix_20261107_1647`。
- 坑：共享 `_work` 目录整删事故再犯（删了队友 verify_exports.py）——"只删自己文件"须执行在 `rm` 之前。
- 报告：`.codebuddy/specs/audit-fixes-202611/`。

### 2026-11-04 · 井下出渣 MZIGO 备注必填（`d86397e`，已部署，生产冒烟通过）
- 新格式 teams 每班组 remark 必填；旧格式 day/night 有产量班次必填；提示语固定英文 "Please fill MZIGO from which driller team"。桌面/移动前端占位+红星+提交校验，后端 `_ug_mzigo_remark_error` 接入 submit/edit 双端 400 拦截。
- 验收：`tests/test_ug_mzigo_remark.py` 6 用例，全量 91/91。
- 注意：生产 2026-10 已关账，关账月闸门先于 MZIGO 校验（10 月提交仍 409）。

### 2026-11-01 · 月度关账（`22ea2a4`，已部署；生产 2026-10 已关账）
- `settings.closed_months` JSON 数组 + 18 个写端点 `_guard_months_closed` 409 闸门（采集提交/编辑/豁免/手动班次、出勤标记单个+批量、奖金罚款预支、改薪资类型、档案薪资直改、永久/临时覆盖、OA 申请/批准/驳回/撤销/修改）；`GET /api/months/closed`、`POST /api/months/close`（仅超管，审计 month_close/month_open）；前端薪资页关账/解锁按钮+橙色横幅+确认框，i18n 双语。
- 坑：哨兵值 9999-12-31 区间展开必须 clamp（`_month_span_months` cap=24 月）；OA 假期 days 跨月展开 clamp 62 天；**新增写端点记得同步加关账闸门**。
- 已知边界：关账期改 config 单价会连带改关账月，勿动。

### 2026-11-01 · Salary Summary 导出加 TIN/NSSF 列（`c06d4ca`，已部署）
- `/export` 与 `/export/all` 末尾加 R=TIN/S=NSSF 两列，从当月花名册（含离职者）按工号映射补齐；文本列不参与 Total 求和。生产实测 78 有 NSSF / 54 有 TIN。
- 坑：仓库里两个 MW 基线 xlsx 有并行会话遗留改动，提交只 `git add` 指定文件，勿 `git add -A`。

---

## 2026-10

### 2026-10-31 · 破碎计件同日多组 P57（`6f0770d`，已部署，移动端 E2E 通过）
- 破碎 payload 增 `slot`（组 1/2，缺省 1）+ 合并层按（日期, slot）独立成池（根治"第二组吞第一组钱"）+ 提交端点 ex 匹配含 slot（同组替换/异组独立池）+ 编辑组别占用校验 + 双端组别选择器（占用置灰/动态重算）+ 历史/详情/预览角标 + 数据台聚合；calc 零改动。
- 验收：4 单测含提交流端到端（66/66）。
- 坑：`/tmp/vcopy.db` 会被 `scp 2>/dev/null || fallback` 复用成陈旧副本，拉副本前必须先 `rm`。

### 2026-10-31 · MW 1.5× 增量奖金 P57（`af701e6`，已部署）
- `settings` 键 `mw_15x_bonus_2026-10` = 23 条确认清单 435 车×1500/车（SAKA218/LAMBA176/MIZOZO41，第二批 +37,500）；calculator `_load_mw15x_month` 读取，V2 班组池分摊后**平坦叠加**按当日 _valid 出勤均分（不乘加速倍数/不计入总车数）。生产 total_gross 70,809,202→71,424,200。
- 同批 `ecd0ab0` P56 同班组每日驾驶勾选≤2 校验（后端硬拦+双端实时回弹+i18n）。
- 同日数据修正：10-03 SAKA 取消 DAMAS(32)、10-06 LAMBA 取消 ALLY VENASI(26)、10-21 LAMBA 取消 AYUBU(38) 驾驶标志 + payload drivers 同步清洗；备份 `kilwa_before_driverfix_20261031_1832`。

### 2026-10-30 · LAMBA/SAKA 司机奖金取消 P55g（`6b7e11b`，已部署）
- 取消规则集 `DRIVER_ALLOWANCE_CANCELLED`：`_reapply_driver_flags_for_date` 跳过命中班组+直写防护+双端提交前英文确认弹窗。
- 坑：`init_db` 建表无 `collection_submissions.team_id` 懒迁移列，测试需自补 ALTER。

### 2026-10-31 · Sanare(67) 离职修正（`13c3f08`，已上生产）
- 错挂 dismiss #73 eff 2026-01-07→10-01 + 落库重放。
- 坑：`apply_approved_event` 参数是目录非文件路径；脚本自开连接与 apply 会 WAL 写锁冲突须先 commit。

### 2026-10 下旬 · 病假补贴豁免 P55e + 基数保护（`c41bb29`/`196a648`/`d8c08ea`/`5ea6219`，已部署）
- `sick_subsidy_exempt` 员工列 + super_admin 切换端点 + 档案页 UI + 计算豁免跳过三证（AMOSI 工伤 200,005 到账）；调岗生效前基数保护回填 12 人 +1,462,501。
- 坑：`load_employees_from_db` 显式列清单漏列致豁免静默失效。

### 2026-10 下旬 · 薪资总表搜索与筛选三修复（`d6af9d9`/`f3796f2`/`61e04a7`，已部署）
- ①重复 ID：调薪表单 #salarySearch 屏蔽表格筛选框，表格框独立 salaryTableSearch ②搜索空白归一 normQ（双空格名字单空格可搜中）③筛选下拉只认当前部门树（4 处接 filterTreeDepts，31 名离职员工旧部门名不入选项）。
- 坑：直接调函数验证会掩盖 UI 事件路径 bug，必须走真实输入路径；nginx 隧道 `ssh -L 18080:127.0.0.1:80` 复现生产（直连 gunicorn 因 /salary 前缀 404 掩盖）；`attendance_overrides.employee_id`(TEXT) 与 `employees.id`(INTEGER) 子查询亲和性漏行必须 CAST。

### 2026-10-27 · 核验卡 NH/NL/MW 分项列（`c747ca4`→`3b7a692`→`1bb13d7`，已部署）
- match=逐矿石相等；10-18 NH-19/NL+19、10-25 NL-32/MW+32 矿石录错待业务核对。

### 2026-10-27 · 采集历史直显队伍名（`736e090`，已部署）
- `/api/collection/history` 增 team_label+team_slot（出渣→employee_groups.name；钻工→driller_captains.name 回退 employees.name+slot），双端历史行直显+钻工"队伍 N"角标。纯展示层，薪资零影响。pytest 49/49。

### 2026-10-27 · 调岗事件遗留部门名归一（`5f424c4`，数据修复已上生产）
- `scripts/norm_event_dept_names.py` 归一 31 条 approved transfer payload（Mechanic Team→E&M 等，守卫非 UG 旧名绝不映射进 UG），修复 Halid(60)/JEREMIAH(170) 花名册错位。根因=部门重整只改 employees 表不改事件 payload，而 `_apply_transfer_day_view` 以事件链为按日归属权威。副本 8/9/10 月逐分 0 差异+16 花名册断言；备份 `kilwa_before_deptnorm_20261027_2140`。60/170 的 10-23~26 出勤缺口用户明令不补录。

### 2026-10-27 · 钻工明细每队独立 sheet（`1a2951a`，已部署）
- Driller Team Details → Driller Summary 概览页 + 每队独立 sheet（≤31 字符去非法字符去重、冻结表头、Subtotal）；延续 5 队长动态+slot 分队+config 单价。

### 2026-10-27 · 导出报表修复（`cc6f3bc`，已部署）
- ①Production Summary 班组化月空白根因=只读旧格式 day_prod/night_prod；新 helper `_write_production_summary_sheet`（/export Sheet2 与 /export/all Sheet5 共用）：新格式月按班组两行表头分组（NH/NL/MW×班组+Total 行），旧格式月原样 ②Driller Team Details 硬编码 4 队长致 FREDY 整队跳过→分组键（规范化队长, slot）+队长动态化+单价读 config.driller_prices。
- 坑：openpyxl MergedCell 无 column_letter，用 `get_column_letter`。

### 2026-10-26 · OA 调薪申请+档案调薪超管化（`6001a3b`，已部署，双冒烟通过）
- salary_change 全链路：申请端校验链（生效日≥本月 1 号硬 400/防重/同值拒绝/服务端固化旧值）、审批白名单+`apply_approved_event` 新分支（eff=1 号落生效月，月中落次月，历史月管线 0 差异沙盒验证）、档案直改端点 super_admin+前端门。测试 49/49。方案 `.codebuddy/specs/oa-salary-change/00-plan.md`。
- 坑：import app 会污染 `namematch._AB_INDEX`，测试末尾须 clear；Flask 非 debug 缓存模板，改模板须重启；agent-browser fill 到 option ref 会改写 option.value 毁坏 select。
- 遗留：移动端发起入口未做；批准后不支持撤销。

### 2026-10-26 · 调岗审批弹窗对比度修复（`6e407cd`，已部署，双主题实测）
- `_pickTransferType` 卡片 var(--bg-primary)→var(--card)+显式 foreground，批准按钮 var(--primary-foreground)。
- 铁律：动态弹窗勿用页面背景色当卡片底、按钮文字必用 --primary-foreground。

### 2026-10-26 · 班组色组第 4 色 + 数据台 NL 卡（`20620ba`/`e5d0c00`，已部署）
- TEAM_COLORS 增雾蓝 #5C7A8B 适配新班组 MAKUSANYO（首提后自动上数据台）；数据台第 2 卡 NH 日均→NL 车次总计（桌面/移动同口径同款），i18n 死键清理。移动端路由是 `/m` 非 `/mobile`。

### 2026-10-25 · M&L 主管叶子 + 部门重整收尾（`dc3e4ff` + `abda8d1`/`ef57674`/`25f68ad`/`5e9db5a`，已部署+迁移完成）
- GASPER(84)/MALIKI(90) 移入 Materials & Logistics Department 主管叶子（与 Mining Department 同构，team_id=0）；幂等脚本 `scripts/migrate_ml_supervisors.py`；2026-10 全库 157 人管线 0 差异；备份 `kilwa_before_mlsup_20261025_2330`。
- 部门两级化：`DEPT_TREE` 单一事实源（index/mobile 各一份，改部门结构须两处同步）；双名兼容是铁律（井下={'PRODUCTIONTEAM','PRODUCTIONTEAM(UNDERGROUND)'}、破碎={'CRUSHINGTEAM','SORTCRUSH/CRUSHPIECERATE'}），禁关键词判池、禁裸名比较。
- 离职者已从 UG 班组映射剔除（按 dismissed_at 月份过滤，离职当月保留）。
- ⚠️ 同日回滚事件：Trae 未提交直接部署的两修复（离职员工编辑软化+移动端花名册池强制刷新）经用户批准已回滚，本地未提交副本也已丢弃（2026-10-25 用户明令），如需须重写。
- ⚠️ 台账直改漂移隐患：档案页直改 team_id/department 不写 employee_base_history（176 SANING'O 案例已补 2026-11 基线），长期修法需立项。

### 2026-10-23 · oa-ux 审批中心优化（`763568d`，已部署，团队流程）
- G1 审批历史/我的申请分页（LIMIT/OFFSET，page_size clamp 1~100，响应结构 breaking 已同批适配）G2 驳回通知 body 改 JSON 六键双语 G3 casual/sick 驳回不分来源一律落旷工 A（保留已有状态跳过+手动标记保护）G4 批准假期覆盖收紧（A(source=0) 可被请假覆盖，手动标记/已批假期保护）H1-H4 双端分页控件/幽灵病假键删除/通知双语渲染+点击跳转/移动端补撤销入口。
- 验收：reviewer Pass with Risk→M1/M2 修复后终 Pass；tester 6/6；双月逐分 0 差异；驳回→A→重提事假批准→覆盖 L→撤销清空全链实证。备份 `kilwa_before_oaux_20261023_1100`。
- 遗留批次 4：按人按日重算/审批人下拉跨页聚合/distinct 端点/移动端 LAB 缺 skill_change 等 2 键/page 超界 clamp/失效-重建并发窗口。

### 2026-10-23 · perf-batch3 缓存正确性收尾（`0845604`，已部署）
- F1 oa_reject_event 落 A 后按日期所属月逐月失效 F2 新 helper `_invalidate_month_cache_from(eff_month)` 遍历现存缓存键清>=生效月（≤6 键有界），approve/revoke 换用、edit 叠加并集 F3 删死函数 `_invalidate_all_cache_base`/`_refresh_employees_cache`（全仓零引用），`__all__` 死缓存停写。
- 验收：tester 6/6，逐分 0 差异（10 月 52,183,978），跨月 reject 用例两月缓存均失效，OA 全操作 3-4ms。

### 2026-10-23 · perf-batch2（`63a204e`，已部署）
- C1 10 端点中 8 处 eager 全量重算改失效（OA approve 580ms→3.9ms ~148×；/reload 与 /set-month 保留 eager）C2 移除 8 处死缓存调用 D 新索引 idx_att_date + idx_events_status_type_date E index.html 10 处循环内 innerHTML+= 改 join + renderAttendance O(n²)find 改 Map。
- 验收：双月逐分 0 差异，OA 审批闭环 0 差异还原，DOM 快照 0 实质差异。

### 2026-10-22 · perf-batch1（`709745a`，已部署）
- /daily-wages 与导出 Sheet4 走 `_get_daily_breakdown` 月缓存（命中 0.005s/155×，deepcopy 防污染）；MONTH_CACHE_MAX 3→6（ΔRSS 仅 3.5MB）；sick_subsidy_eligible_batch 批量三证查询；save_config 全月清 breakdown。
- 验收：main 基线逐分 0 差异（191 人）；部署前用最新副本对账（旧快照差异是用户撤销 OA+新采集的数据漂移非算错）。

### 2026-10-15 · P54 钻工同队长同日多队伍独立结算（`f110ff6`（速查卡记 `817ceed`），已部署）
- 采集/rebuild/calc 分组键扩为 (date, captain, slot)，slot 缺省 0=旧行为逐分 0 差异（生产副本 09/10 两月 TOTAL_DIFFS=0）；双端"队伍 N"角标；8 项单测全量 29 passed。方案/审查/QA：`.codebuddy/specs/driller-subteam/`。
- 语义：两队须同一表单一次提交，分开提交仍覆盖（表单不预填当日已提）。
- 遗留 Minor：改选队长后角标不即时刷新；产量输入框重渲染清零（main 存量行为）。

### 2026-10-10 · P53 全批次（`fefa487`，已部署）
- ①B 类未调休加班——月薪覆盖日剔除生效加班日（加班不占 26 天配额，9 月 5 人补差 151,926）②日明细同日多条 hourly 累加+核对基准补病补 ③OA 入职显示名兜底 payload.name+工号防撞 ④切月统一 changeMonth ⑤改薪资弹窗去预填+必填校验 ⑥台账有效基线 `resolve_effective_base`（修"主档被 override 清零→历史基线写 0→7/8 月按 0 计薪"，SAITOTI 8 月恢复 310,000）。
- 遗留：134/63/73 各 1 天基数待用户补。

### 2026-10-09 · P52 合同管理 + P52-m 移动档案 + P52-c 年假资格（`93b619e`/`21e2250`/`66bf4a2`，已部署）
- P52：档案页合同区块（PDF≤10MB 魔数校验/签订+到期日期/多份历史/EAT 四态徽章）；新表 employee_contracts+5 端点，文件存 data/contracts/（不走 /static 无鉴权直出）；审计 contract_*。
- P52-m：移动端档案出勤统计上移/去银行/班组 team_id 正名/新增 TIN+假期余额+合同状态区块（纯展示）。
- P52-c：无合同或过期>30 天（EAT）阻断年假（≤30 天宽限），豁免开关跳过合同检查；豁免切换全改 super_admin 专属。⚠️ 生产合同表为空→未豁免者暂均不能请年假，待补录。
- 教训：动态 modal 勿用 var(--bg)（未定义→透明）改用标准 .modal 类；index.html 另有 14 处历史 var(--bg) 误用未清。

### 2026-10-09 · 员工 ID 体系归一（`fcbd745`/`0945d37`，已上生产）
- ①38 人姓名 id→数字工号全库迁移（13 表 2531 处，audit_log 不动，沙盒真实管线逐分 0 差异后上生产）②OA 入职自动分配 max(数字 id∪custom_number)+1，姓名格式 id 路径废除 ③年假三证格式校验（NSSF≥8/NIDA≥19/TIN≥9 位纯数字）+OA 批准复核（起因 maua 给 102 三证填 'A' 提 21 天年假）④101 钻工 team_id 历史脏值→1027+前端兼容 c.id ⑤FREDY id→161。
- 备份链：empid_migration38→fredy_id_fix→drillerteam_fix（只留最新）。

### 2026-10-08 · 员工 ID 单引号 bug（`3cecc8b`，已部署）
- 姓名含 `'` 截断内联 onclick JS → 档案保存/OA 选人失效；修复=escJsAttr 转义 5 处+make_employee_id 剔除引号；生产库同步改 id+hire_date。

### 2026-10-02 · P47~P51b 批次（`0db3937`，09-30~10-02 实施，已部署）
- P47 撤销/改期请假不再误删其他假期覆盖+手动标记；P48 病假补贴 SK=15,385/天三证齐全者发、V2 缩放后叠加；P50 OA 调岗当月基线类型落计件新类型；P51 月薪工年假并入月薪计数（26 天封顶按本人日薪），废除月薪≥40 万 NU 额外发 15,385 双重计薪（53/52/123 回溯）；P51-b 月薪满勤月不发病假补贴守卫。
- 运维：DAMAS 病假数据修复（撤销 5 条零散 sick→重提整段 14 天 #387）；Lari 9/1 出勤恢复（编辑端点对已调岗/离职者被 roster 过滤，须走超管 attendance_toggle）。
- 既有口径：班组对比"当日池≠Σ实发"是 V2 零和设计非 bug（月度精确守恒，±2 取整尾差）。

---

## 2026-09

### 2026-09-28 · 设备故障豁免管控（`d6ff304`，已部署）
- 其他会话交付；豁免管控验证见记忆 `feedback_ui_permission_control.md`（可点即回弹+toast 优于禁用/隐藏）。

### 2026-09-14 · P46 钻工按队长拆行提交（`826fadf`，已部署）
- driller 提交镜像 P39 UG 全套：同日不同队长可由不同用户分别提交（team_id 列=队长 employee_id），同队长跨用户冲突 400，本人/管理员重提为行内 patch（历史合并行其他队伍零丢失）；桌面默认 3 槽→1 槽。
- 验收：隔离副本库+Flask test client 全过，既有 82 行 merge 0 差异，pytest 19/19；生产 9/11-13 已各自提交单队。
- 注意：生产 victor 对 collection:driller 是 deny（真实业务配置）。

### 2026-09-12 · P45 OA 新审批提醒轮询（`b207f91`，已部署）
- 纯前端：桌面 `_startNotifWatch()`（60s+visibilitychange+pageshow→loadNotifCount(notify)，待审增加时 toast）、移动 `_startNotifWatchM()`；后端零改动（审批人分支已合并待审数+未读数，缺的只是驱动；写 DB 通知反而会错误渲染进"审批结果"红区）。

### 2026-09-08 · P42 未调休加班 B 类 daily2（`efc7658`+fix `3abfe92`，已部署）
- A 延时（1.5×小时公式不变）/B 未调休（整日，当日合计=2×日薪）；计件不可申请；硬校验当天出勤白名单；生效闸门=max(0, 当月核定出勤−26)，按日期升序取舍；**补差制**（月薪前 26 出勤日补 1×、第 27+ 天补 2×）；单一来源 `resolve_daily2_ot` 三处共用；config 新键 ot_daily2_multiplier/threshold。
- 生产修正 #259：ALKADO 9/6 补差 17,308。备份 `kilwa_before_P42_fix_20260908`。
- 设计行为：B 类按闸门月末核定，出勤超 26 天前当日不显示补差。
- 表单铁律（用户"说了无数次"）：涉及计算/金额的下拉一律禁止预填默认值（P42-fix 起因）。

### 2026-09-08 · P43 日明细三项修复（`d0c8898`，已部署）
- O1 日明细锚定总表取整+尾差归最后一日（calculate_all 一行不动=总表 0 变化硬验收）O2 日薪分摊 str(dict) bug（补 isinstance(e,dict) 分支）O3 删死代码 core/verification.py（-442 行）。
- 验收：总表逐分 0 差异；Σ日明细==总表轨道和 8 月 136/136（改前 67）、9 月 128/128（改前 59）；pytest 19/19。
- 比原方案多修三层：月薪循环迭代域对齐、NU 重定向复制（emp123 -134,616 案例）、V2 再分配基数改原始 ug_daily 累加。

### 2026-09-08 · P44 headless 月垃圾值修复（`1c661e3`，已部署）
- headless 日期生成从 calculate_all 之后前置到月过滤之后，消除 month_prefix='' 三洞（manual_p 全历史 P/final_dates 全历史 NU/ENPRIZON 补齐跳过）。emp1 垃圾值 184,615→600,000。
- 验收：8/9 真实月逐分 0 差异，headless 月 Σ日明细==总表 9/9。
- ⚠️ 事故：P43 收尾删 _work 时把本地库唯一备份一起删了，本地库不可恢复→以 9/8 生产副本重建。教训：换库前先把本地库备份移出待删目录。

### 2026-09-07 · P41 OA 审批 UX+破碎映射+加班编辑（`b02becf`，已部署）
- ①审批无反馈根因=前端 res.json() 无容错+无 loading 态→三态 catch+乐观移除 ②破碎自动映射 piece_crush（`SORTCRUSH/CRUSHPIECERATE`，`Sort Crush` 不映射）四处落库，生产修复事件 260/261/269 ③加班 edit 支持起止时间（待审+已批重算）④转出计件确认层聚焦日薪/月薪。
- 验收：审查 Pass with Risk（0 Critical/Major），QA 6/6。
- git 教训：86108b1 混交已软重置拆分+rebase 去重；**团队成员一律不得执行 git commit**。

### 2026-09-07 · P40-f/g/g2 入职生效日+移动端日期先行（`275cef6`→`0971364`→`ff6435f`，已部署）
- P40-f：`_hire_date_map`/`_filter_not_yet_hired` 四层共存（roster?date 与 employees?as_of 排除 hire_date>date；submit/edit 硬校验 400 col_not_hired_yet；fail-open）；生产验证 9/7=127 人排除两名新员工。
- P40-g/g2：移动端名单按日期归属取池 `mobDateViewPool(date)`；用户裁决"先选日期后选部门"——日期空→名单空+提示 col_need_date_first，废除回退全量员工口径。
- 教训：查"某员工有无某类事件"不得预设类型过滤，先全量再看；agent-browser fill 对 date input 不生效需 eval 设值+dispatchEvent。

### 2026-09-06 · P36 数据台改造系列（`ab15749`~`6fd64f4`，已部署）
- 产量趋势图改每日 NH/NL/MW 三线（Web+移动）；第 5 卡"日最高"→"本月总产量"；矿石三色二版（NH #EE892B/NL #3F81A6/MW #3F8356）；第 2 卡"NL 车次"→"NH 日均"（后于 10-26 改回 NL 车次）。
- 教训：跨端 i18n 键前缀不同（kpi_* vs dash_*），跨端同步必须两端各搜键名+中文文案。

### 2026-09-06 · P37 T 调休余额预检（`2f31990`，已部署）
- 提交前拉 /api/leave/balance，余额<1 天整单阻断；写循环扣减失败改跳过+t_failed 清单（原 return 400 会部分写入不一致）。

### 2026-09-06 · P38 薪资剔除离职 0 薪行+豁免强制备注+驳回落 A（`2f31990`+fix `f77c46e`，已部署，团队流程）
- ①`_filter_dismissed_empty_salary`（16 金额字段全集+当月无记录+fail-open），9 月 138 行、8 月剔 5 行后 153，基线逐分 0 差异 ②豁免强制备注双端+后端兜底+超管 exempt 端点防 true→true 清空 ③采集路由 casual/sick 驳回空位才写 A（手动标记跳过），审计 oa_reject_attendance_a。
- 坑：payload.source 有两个合法值，凡按来源判定必须 `in ('collection_routing','collection_edit_routing')`（Lari 9/6 案例）；存量驳回事件不会追溯落 A，经批准手动补（备份 kilwa_before_p38a_20260906214033）。
- 团队事故：impl-audit 误删 tester 的 _work/p38-test（本地原库备份丢失）→共享目录只删自建文件。
- 方案/审查/QA：`.codebuddy/specs/p38-salary-exempt/`。

### 2026-09-05 · P35 调岗日粒度+临时例外豁免+哨兵回收（`7eaf87d`，已部署）
- B1 日粒度时间线 `_build_transfer_day_map`+calculator `_dept_at/_team_at/_type_at`；调入 UG 无 team_id→None 继承先前班组（43/93 案例）；B2 ug_exc_intervals 豁免部门双条件；B3 调岗回收 9999-12-31 哨兵；B4 当月事件漏取修复（substr(effective_date,1,7)<=month）；B5 审批强制确认 400+双端确认弹层。
- 验收：2026-08 全员逐分 0 差异；Lari 9/1-3 计件 0→48,200；池逐日守恒。
- 既有口径：V2 月末系数缩放只缩放 salary_type==piece_underground 员工，eff_type 不同但参与池的人自身不缩放→Σpiece 与 Σ池天然不守恒（非 bug）。

### 2026-09-05 · OA 审批中心重设计 R1-R5（`a7f4bff`，已部署）
- 审批人查询/通知中心/详情员工信息/出勤概览/时间线筛选+8 个 bug 修复。详见归档记忆 `docs/archive/memory/project_oa_redesign_20260905.md`。
- 同批 P34：OA 审批后跨模块缓存失效+采集页花名册重拉+年假未满一年提示（Lari 案例：调岗月粒度致踢出计件+前端缓存永不失效+年假恒 28 天无折算）。

### 2026-09-04 · OOM 瘫痪事故+终修（`dc90ecf`，已部署）
- OA 调岗哨兵 end_date=9999-12-31 × calc_driller_piece 逐日展开无上限→单条 +932MB→894MB 服务器 OOM 循环瘫痪半天。终修=哨兵感知展开上界+captain 落库解析名字+qa F1-F7+数据修正（captain '9'→'BARAKA LAIZER'）。
- 沉淀三条铁律（写码+review 必过）：区间展开必 clamp（800 天）/哨兵值消费方必设防/落库形态=消费方期望。详见记忆 `project_oom_incident_20260904.md`。
- 同批部署：采集历史 created_by+only me 修复（`8bc1947`）、权限加固+排版重设计（`8864301`）、四项反馈（`3e273db`：移动端出勤网格整体只读/离职不回溯清史/调休提交端余额校验/豁免显示）。

### 2026-09-04 · 移动端白屏事故（已修复）
- 手改模板丢 `</div>`→浏览器容错把 #app 吞进 #login-screen→登录后整页白屏零 console 报错。沉淀：模板改动必须 DOM 结构校验+真机走查+`node --check`。详见记忆 `project_mobile_white_screen_20260904.md`。

### 2026-09-02 · P30 井下采集班组化 + P31/P32（`9abd4cc`+`adbf787`→`2d8228e`，已部署）
- 井下出渣改班组产量制（payload `{"teams":[...]}`，一日一条）；井下工人出勤并入出勤收集（upsert 键扩 form,date,department,team_id）；**格式分支原则**：rec 含 teams=新格式/含 day_prod=旧格式，旧 payload 逐字保留→8 月及更早零改动（验收=2026-08 全员逐分 0 差异）。
- 池分母=班组当日 P 人数，零出勤班组跳过+警告；驾驶白名单非空才校验；豁免二次编辑端点（仅超管，版本归档+审计）。
- P31 数据台班组预览（`docs/P31_DASHBOARD_TEAM_SPEC.md`）。

---

## 2026-08

### 2026-08-23 · P29 权限体系 V2.1（已部署）
- 需求文本冻结，接手必读 `docs/P29_PERMISSION_V2_SPEC.md`。

### 2026-08 中下旬 · P25 计件 V2 / P27 月逻辑 / P28 请假规则（已部署）
- P25：凸性加速+月末零和再分配，业务权威 `docs/P25_PIECEWORK_V2_SPEC.md`、工程权威 `docs/P25_PIECEWORK_V2_IMPLEMENTATION.md`。
- P27/P28：`docs/P27_MONTH_LOGIC_*.md`、`docs/P28_LEAVE_RULES_SPEC.md`。

### 2026-08-16 · P22+P22-FIX+P23+UI 壳层+时区统一（已部署）
- P22（`b33e4e0`）：自助改密全角色/OA 历史类型筛选/档案姓名上移/D-N 高对比色/移动端档案薪资规则。
- P22-FIX（`904246e`）：日明细 105→107，**override_type 优先判定**（ENPRIZON 8 人 default=day_rate 但 override=monthly）。
- P23（`985411c`）：照片放大压缩≤2MB/加班申请（overtime_records 表，400000/26/8×1.5 可配）/审计日志移权限页/缓存同步 bug 修复。QA 19/19。
- UI 壳层（`3342f96` 等 3 提交）：body 锁高+唯一滚动区+modal 居中缩放动画（fixed 定位 modal 的 transform 动画必须带 translate 组合）。
- 时区统一（`04b7867`）：全系统时间戳统一 UTC+3（EAT），SQLite `datetime('now','localtime')` 依赖服务器时区，业务时区需显式 '+3 hours'；存量 294 时间戳 -5h，audit_log 不动。
- 出勤收集改造（`979274a`）：留痕按部门×日期、部门下拉不预选、移动竞态修复。

### 2026-08-15 · P20/P21+部门英文化（`e2f6e2b`/`c56e528`/`491ba33`，已部署）
- P20 年假资格豁免开关；P21 年假计薪/请假撤销/NU 状态/TIN 字段/计件双条件/双语/改名；部门英文化。

### 2026-08-14 · git 历史重写（113 提交）
- 移除数据库文件，**旧哈希（8619c08/9e7a6b1/3d0de65 等）均已失效勿引用**；首部署 `a4c2189`。

### 2026-08-13 · 纯采集驱动改造（已部署）
- 移除 Excel 数据源：`_run_pipeline()` 纯 DB 模式，删 scan_source_files/parser.parse_all，employees 从 DB 读取，月份从采集生成，data/source 清空，8 月数据导入。

### 2026-08 上旬 · P0~P19 重构路线图（已部署）
- 按 `REFACTOR_SPEC.md` §11 推进：P0 数据模型+API 契约 → P1 员工档案+OA 事件化 → P2 考勤网格+请假+产量录入 → P3 评分模型 → P4 权限+表单引擎 → P5 归档+事件驱动 → P6-P11 交互清理/档案扩展/OA 合并/采集重设计/评分重设计/薪资新列 → P12-P14 v5~v7 反馈迭代 → P15 评分三层对齐手册 → P16/P17 移动端（`b8eb6f5`）→ P18/P19 权限重构（`505c27a`）。
- 各阶段详设：`docs/P0~P18_*.md`；历史记忆：`docs/archive/memory/`。

---

## 2026-07 及以前

- 旧系统时代（Excel 驱动、双路径核对），仅存档参考：`docs/archive/memory/project_session_20260701.md`。
- 单轨重构 `e6b9487`：根除"双重计薪"bug 的架构决策，详见 `ARCHITECTURE.md`。
