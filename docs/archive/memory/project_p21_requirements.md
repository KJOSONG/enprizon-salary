---
name: P21 多需求修复(年假计薪+计件双条件等)
description: 2026-08-16 用户提出的 6 项需求及已确认粒度:年假计薪/请假撤销/NU状态/TIN/计件双条件/错误双语/员工改名。方案由 keju-p21 团队制定
type: project
---

# P21 多需求修复(2026-08-16,实施+QA 完成,待合并部署)

用户一次性提出 6 项需求,经核对已确认全部粒度。团队 keju-p21 完成方案(`_work/P21_FIX_PLAN.md`)→ 实施 → QA 验收。

## 实施状态(2026-08-16)
- **分支**: `feature/p21-m1m3`,11 个 commit,未 push,待合并部署
- **QA 验收**: 34 项 31 PASS / 3 FAIL(前端 NU 适配缺项)→ dev 已修复(9366b05) + 补 collection_submit NU 保护(03d0da3,我代为提交)
- **已知存量**: 12/130 人日明细舍入差异 ±2~8 TZS(非 P21 引入,QA 容差记录)
- **P3 决策**: 撤销年假 DELETE 整行(覆盖时原标记已丢,无恢复源),维持现状,留 backlog

## TIN 数据填充
- Excel: `8月最新原始信息/JULY ----EMPLOYEES DETAILS NSSF, NIDA , TIN .xlsx`
- 脚本: `_work/p21_fill_tin.py`(按 SYSTEM_ID 匹配,幂等只填空)
- **本地已填 43 人**(5 人 PENDING 跳过: 25/42/26/62/24),**服务器部署时需执行**
- **员工38**: 服务器部门已是 Production TEAM （underground）无需修正;本地已补同部门(原来为空)

## 部署待办(需用户批准)
1. 合并 feature/p21-m1m3 → main, push
2. 服务器 `git pull && systemctl restart enprizon-salary`(幂等 ALTER 自动加列 tin_number/revoked_by/revoked_at)
3. 服务器执行 `_work/p21_fill_tin.py`(需先 scp 到服务器)填充 TIN
4. 服务器验证: schema 新列 / 员工列表 TIN 列 / 出勤网格 NU 显示
5. 服务器备份: 先一致性备份 kilwa.db

## R1. 年假计入工资 + 全部请假可撤销/修改
- 审批通过年假列入工资,**前提:日薪或月薪类型**
- 公式(已确认):按日薪/月薪正常计——日薪=天数×日薪基数;月薪=天数×(月薪/26);NU 在日薪/月薪轨道当作"出勤"
- 年假通过后可撤/改;所有请假(年假/调休/事假/病假)都可撤/改
- 权限(已确认):**已批仅 OA 审批人撤/改;待审申请人可撤/改;撤销后薪资/出勤自动回滚**
- 现状:`app.py:1879` 年假走 employee_events,审批仅置 status 不落出勤不影响薪资;无撤销端点;`deduct_annual_leave`(database.py:1839) 死代码

## R2. 出勤网格 NU 状态
- 审批后年假出勤网格显示 **NU**
- 语义(已确认):**计件排除(同L),日薪/月薪计入出勤天并发年假工资**
- 现状:全项目无 NU;颜色映射 `index.html:4385-4399`;L 计算语义 calculator.py:895

## R3. TIN 号码 + 年假资格加强
- 档案页 NSSF 下方新增 **TIN 号码**,编辑页也配
- 资格检查(已确认):**有 NIDA 号码 + 有 NSSF 号码 + 有 TIN 号码 + 入职日期**。NSSF 从 `nssf_enrolled` 布尔改查 `nssf_number` 有值
- 豁免者跳过以上但**入职日期仍必须**(当前已保持)
- 现状:employees 无 tin 字段;check_annual_leave_eligible `core/database.py:1941-1982`

## R4. 部门×薪资类型双条件(核心计件)
- 部门(Production TEAM （underground）,**全角括号**)与薪资类型(piece_underground)是两概念
- **计件模式**:部门+类型双条件才参与计件分配
- **月薪+奖金(scoring)模式**:同样双条件统一计算
- 部门匹配但类型为日薪 → 单纯日薪计算
- 现状:`calculator.py:772-793` 只按 default_type,department 未参与 → 其他部门 type=piece_underground 也会参与(偏差);scoring 模式井下改 monthly 在 `calculator.py:757-764`

## R5. 报警提示英文适配
- "年假资格不足: 未参加NSSF, NIDA证件号为空, 入职日期为空"(后端 app.py:1891 拼接)需双语
- 范围:仅年假资格类错误双语(含新增 TIN 项)

## R6. 员工改名 + 索引
- 档案可改 name(现状 `update_employee_fields` 白名单 database.py:1751-1755 不含 name)
- 改名后搜索按**新名字+别名+工号(custom_number)**;旧名自动入别名(采集/出勤反查兼容)
- 内部以 id 关联,改名不影响历史数据
- 用户原话:"搜索到这两个(姓名/别名)和工号就可以,系统内部联动不是不依靠名字的吗"

## 关键约束
- 单轨模式不变量:任一日期只归属一轨道;日工资明细与薪资页一致
- 总额守恒:A/L 排除后剩余平分
- 部署纪律:本地编辑→批准→push→服务器 git pull+restart
- 相关:current main=e2f6e2b+P20年假豁免开关(9c9a6fe 已部署)

## 决策点已确认(2026-08-15)
1. **comp_leave(调休)改审批制**:提交也创建 pending 事件,审批通过才生效(原免审即落 T)
2. **已批年假修改仅限同月**(M4 实施)
3. **NU 只读禁止手改**:后端 toggle_attendance 拒绝改 NU

## 切片进度(2026-08-15, keju-p21)
- **M1-M7 全部完成 + QA NU 前端修复 + collection NU 保护**:feature/p21-m1m3 分支 11 commit(fb759bf/ed9d435/13f43b1/f329126/c67f04c/d2ff2ee/549bd50/7aba8e7/6779ecf/9366b05/da50344),未 push
  - M1: tin_number 列 + 资格 codes + update_pending_event + restore_annual_leave
  - M2: apply_approved_event leave 分支(共享事务扣余额+落NU/T)+ oa_approve 先 apply 后 approve + comp_leave 改审批制
  - M3: 计算引擎 NU 语义(C4-C8,计件排除/日薪月薪计入/总额守恒)
  - M4: 撤销/修改(revoke_event/A4 revoke/A5 edit 同月限制/前端按钮 F11-F14)
  - M5: TIN 前端字段 + 员工改名(A3 旧名入 alias + 重建索引 + search_all custom_number) + 员工列表 TIN 列
  - M6: 计件双条件(部门×薪资类型, C2/C3 两处同步)
  - M7: 年假资格错误双语(_LEAVE_ERR_MSG + lang 参数)
  - FIX: 出勤网格 NU 前端(statusStyle #7C3AED/isEditable 排除/图例/i18n shift_nu_*)
  - FIX: collection_submit/edit NU 只读保护(检查前移+删除循环跳过 NU;注意主库 8/10 历史 attendance 提交会触发 merged_target 删除)
- **服务器员工 38 部门已正确**(Production TEAM （underground）),M6 上线无需数据修正;本地 38 部门空为本地/服务器差异
- **决策(已确认)**: revoke_event 维持 DELETE 整行(P3 评估,原标记覆盖时已丢失)
- **已知 backlog**: 存量 12/130 人日明细舍入差异(±2~8 TZS,非 P21 引入,建议单独排期)
