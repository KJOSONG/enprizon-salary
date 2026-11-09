---
name: OA 审批中心重设计(R1-R5)交付归档
description: 2026-09-05 交付:审批历史按审批人查询/通知中心+我的申请/详情员工信息+跳档案/档案页出勤概览/时间线月份筛选。含关键设计决策与已修 8 个 bug
type: project
---

# OA 审批中心重设计 + 档案页增强（2026-09-05，已部署 main a7f4bff）

分支 feature/oa-redesign，7 commits / 7 文件 / +857-147。设计文档 _work/oa-redesign/DESIGN.md，验收 QA_REPORT.md + REVERIFY_REPORT.md。

## 用户确认的四项决策（后续改动勿偏离）
1. **历史可见性 = 两视角分离**：所有人有「我的申请」（只看自己提交的）；有审批权者另见「审批历史」（可按审批人筛选全部）
2. **提醒 = 站内通知中心**（铃铛+角标+列表，非轻量红点）
3. **出勤概览 = 月份可切换**（默认当前月，与时间线共享月份选择器）
4. **移动端范围**：R1/R2/R3 两端同步；R4/R5 仅桌面档案页

## 五个需求的实现要点
| 需求 | 实现 |
|------|------|
| R1 按审批人查询 | /api/oa/history?approver= 匹配 **approved_by ∪ rejected_by**（两列都要，单列漏驳回）；?mine=1 强制 operator_filter。mine 与 approver 互斥，同时传以 mine 为准 |
| R2 通知中心 | **复用 P13 已有铃铛**（index.html:123-135 / JS 7107-7185）改双段面板（待我审批+审批结果）。新表 notifications（懒迁移），审批成功后**旁路写入** try/except（失败不阻断主流程），仅 operator_id≠审批人时写（自审不发）。title 不持久化，前端按 type+i18n 渲染 |
| R3 详情员工信息 | 列表接口通过 _attach_employee_info() 附 employee_info。**关键：详情三处+移动端全用列表数据渲染，只改单事件接口无效——这就是 BUG-2 的成因**。薪资类型走 override_type or default_type 铁律 |
| R4 出勤概览 | GET /api/employees/<id>/attendance_summary?month=，聚合**复用权威网格 _build_attendance_grid**(app.py:4993-5140)，与 Excel 导出三方口径一致 |
| R5 时间线月份筛选 | 档案页顶部月份选择器同时驱动出勤概览+时间线，含「全部」 |

## 修掉的 8 个 bug（qa 发现，dev-fix 修复）
- BUG-2(高) 列表接口未附 employee_info → 信息条恒 '-'、档案按钮永不出现
- BUG-1(中) 我的申请缺 pending（history 走 get_processed_events 不含 pending）
- BUG-5(中) 移动端 revoked 误显「已驳回」（状态徽章只有两态）
- BUG-6/7 移动端通知缺待审分段 + 无审批权账号也渲染待审段
- BUG-3(低) 审批人下拉混入撤销人（**根因：revoke_event 只写 revoked_by 不写 rejected_by**，database.py:2694）
- BUG-4(低) 移动端 typeMap 缺请假类键显示英文 key
- BUG-8(低) 切语言通知头部不重渲染 → 最终为**无害化**（切语言触发页面重渲染致面板关闭，重开即正确英文）

## 遗留
- BUG-8 严格修复需把通知面板移出页面 DOM 改顶层 fixed 层（当前行为可接受）
- 出勤概览沿用报表口径：月薪制默认整月全勤（未过完的月份也显示全勤），用户确认保持现状

## 踩坑沉淀
- **「我的申请」必须是独立端点**，不能用 history+前端过滤（oa:view 账号会看到全量）
- 审批人下拉聚合须**排除 revoked 事件**，且 rejected_by 仅在 status=rejected 时取
- 桌面通知铃铛 P13 已存在，改动前先查有没有现成组件（本次差点重造）