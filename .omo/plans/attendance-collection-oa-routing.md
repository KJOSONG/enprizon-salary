# 方案：出勤采集 P/A 收口 + L/SK/T 自动转 OA pending（审批人 maua）

> 分支：`feature/attendance-collection-oa-routing` | 基座 `main@8e31fd8` | 作者 Sisyphus 2026-09-01

## 1. 背景与目标
- 矛盾：出勤采集 `COL_ATT_STATUS=[P,A,L,SK,T,E]` 直接写 `attendance_overrides`，绕过 `OA` 审批与 `leave_balances` 余额校验（`NU` 已有只读保护，`L/SK/T` 没有）。
- 混淆：`E` 在采集页被误为「设备故障豁免」，实际应只在「井下出渣产量」`teams[].exempt` / `day.exempt` 出现（`calculator` 凸性倍率），与「出勤码 E」正交。
- 目标：**采集页 P/A 直写，L/SK/T 转 OA pending 定向 maua（KEJU 超管兜底），产量豁免不动，E 从采集摘除**。单一可信源，防分母攻击（`26-exempt_days`）。

## 2. 范围与非目标
- **在内**：`app.py` 采集提交/编辑分流、`core/database` 辅助、`templates/index.html` + `templates/mobile.html` 前端、`i18n` 文案、`audit_log`。
- **不在内**：`calculator.py` 计薪、`verification` 核对、产量采集 `teams[].exempt` 逻辑、`grid` 出勤网格的手动 `E` 入口（保留给 `attendance:edit`）。
- **兼容**：历史 `collection_submissions` payload 含 `L/SK/T/E` 的旧行不迁移，展示层只读。

## 3. 设计
### 3.1 后端分流（`POST /api/collection/submit` 与 `POST /api/collection/edit/<id>`）
```
marks[] 遍历
 ├─ status in ('P','A')      → save_attendance_override(eid,date,status)  // 现有直写
 ├─ status in ('L','SK','T')  → create_event( employee_id=eid,
 │                                              event_type= {L→casual, SK→sick, T→comp_leave}[status],
 │                                              effective_date=date,
 │                                              days=1,
 │                                              operator_id=session.username,
 │                                              approver= get_approver_for_event(type) or 'maua',
 │                                              status='pending')
 │                               // 不写 attendance_overrides，待 OA 批准后 apply_approved_event 逐日落 L/SK/T
 ├─ status == 'E'             → 400 "E 已从采集摘除，请在出勤网格由管理员标记或走 OA"
 ├─ status == 'NU'/'Y'        → 已有 403
 └─ 其他                      → 400 非法状态
```
- 批量提交：同一请求内混合 `P/A` + `L/SK/T` 均合法，`P/A` 落库，`L/SK/T` 建事件；返回体增 `oa_created: [{employee_id,status,event_id,type}]` 与 `attendance_written: n` 供前端 toast 区分展示。
- 去重：同一 `date` 对同一 `eid` 只建一个 pending 事件；若当日已存在同类型 pending 事件（同 eid+date+type pending），跳过并返回 `oa_skipped`。
- `drivers` 与 `_reapply_driver_flags_for_date` 仅对 `P/A` 集合生效（`L/SK/T` 当日非出勤，不应标记驾驶）。
- 编辑路径同逻辑：旧 `marks` 删除仅删 `P/A` 对应的 `attendance_overrides`，`L/SK/T` 旧事件不自动撤销（由 OA 撤销流程处理），避免误撤销他人待审单。
- 审批人：`approver = get_approver_for_event(event_type) or 'maua'`；若 `maua` 账号不存在则回退 `''`（所有 `oa:approve` 可见，KEJU 超管必见）。启动时若 `approval_routes` 三类为空则 `INSERT OR IGNORE` 种子 `('casual','maua'),('sick','maua'),('comp_leave','maua')`（`init_db` 幂等）。
- 权限：采集提交仍校验 `collection:attendance`，OA 事件创建不额外校验 `oa:apply`（采集员已有 `collection:attendance` 即被视为可发起 OA pending；审批仍需 `oa:approve`）。
- 审计：`collection_submit` 增加 `oa_created` 明细；新建事件同时 `log_audit('oa_create_event', eid, {source:'collection_routing'})`。

### 3.2 前端（`index.html` / `mobile.html`）
- `COL_ATT_STATUS` 保留 5 项视觉选项：`P(出勤) / A(旷工) / L(事假→待审批) / SK(病假→待审批) / T(调休→待审批)`，文案后缀 `· 待审批`（i18n: `att_status_l_pending` 等），`E` 删除。
- `renderAttCollectionForm` 下拉 `attStatusOpts` 标注 `L/SK/T` 为橙色 `· 待审批`；`submitAttCollection` 前端按状态分桶统计，提交后按返回 `oa_created` 弹 `toast("已提交 X 条待审批 (maua)")`，`P/A` 弹「已标记」。
- 历史详情：`payload.marks` 中 `L/SK/T` 行旁显 `⏳ 待审批` 徽标。
- `mobile.html` 同步 `COL_ATT_STATUS` 与 `attSt` select。
- i18n 新增 `col_att_routed_to_oa`, `col_att_oa_created`, `col_att_e_removed`。

### 3.3 边界与异常
- `NU`/`E` 在采集提交：前端不提供，後端 400/403 双保险。
- `L/SK/T` 连续多日：采集为单日提交，1 行=1 天；跨日请假请走 OA 表单（不扩展多日）。
- `maua` 离职/改名：`rename_user` 已同步 `approval_routes.approver`，删除用户时路由清零回退 `''`。
- 并发：`create_event` 插入前查 `SELECT ... WHERE status='pending' AND employee_id=? AND effective_date=? AND event_type=?` 去重。

## 4. 数据与迁移
- 无表结构变更，`team_id` 列已有。
- 种子迁移：`ensure_default_oa_approver()` 在 `init_db()` 尾部调用，`INSERT OR IGNORE INTO approval_routes(event_type,approver)` 三行。
- 存量 `attendance_overrides` 中由采集写入的 `L/SK/T` 不回溯（历史薪资为法律事实），仅新提交走新链路。

## 5. 验收
- 采集页：选 `P/A` → 出勤网格立即变色，薪资重算生效；选 `L`/`SK`/`T` → 不落 `attendance_overrides`，OA 待审列表出现对应 `casual/sick/comp_leave` 事件，审批人 `maua`，KEJU 登录可见并可批/驳，批准后网格落 `L/SK/T` 且 `leave_balances` 扣减。
- 采集页无 `E` 选项，产量页 `exempt` checkbox 仍在且仅 super_admin 可二次编辑。
- `collector` 账号提交 `L` 不再直接改出勤，需等待审批；`collector` 提交 `P/A` 仍直通。
- 审计：`collection_submit` 与 `oa_create_event` 双条日志可关联 `eid+date`。
- 双月核对：`verify_salary` 在 V2/piecework 下 0 偏差（`L/SK/T` 待审期间不计 exempt，分母不变）。

## 6. 风险与回滚
- 风险：采集员误选 `L` 以为已请假，实际 pending；通过 toast + 待审徽标缓解。
- 回滚：`git revert` 单分支，前後端白名单移除即回旧直写；`approval_routes` 种子行保留无害。

## 7. 实施切片
1. 后端分流 + 去重 + 种子（`app.py`+`core/database.py`）
2. 桌面前端（`index.html`+`i18n.js`）
3. 移动端同步 + 端到端自测

## 8. 文件清单
- `app.py` ~3019/3226/3409
- `core/database.py` ~1040/2067/2080
- `templates/index.html` ~7858/7873/8004
- `templates/mobile.html` ~1818
- `static/js/i18n.js` ~col_att_*
