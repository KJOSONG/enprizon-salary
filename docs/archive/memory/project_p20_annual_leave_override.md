---
name: P20 年假资格豁免开关
description: 员工档案增加 annual_leave_override 字段与编辑权限隔离,允许 OA 审批人绕过 NSSF/NIDA 资格限制让员工申请年假
type: project
---

# P20 年假资格豁免开关(2026-08-15 开发,2026-08-16 已部署)

## 需求来源
用户截图 YUSUPH HAMISI #52 请假申请页显示红字"年假资格不足: 未参加NSSF, NIDA证件号为空"。要求:
1. 员工档案加豁免开关,开启后可绕过这两项检查
2. 仅 OA 审批人(具有 `oa:approve` 权限)可编辑
3. 设计仅豁免 NSSF+NIDA,**保留入职年限检查**

## 数据模型
- `employees.annual_leave_override INTEGER DEFAULT 0`(新增列)
- `_emp_new_cols` 列表追加(`core/database.py:112`),通过 `init_db()` 幂等 ALTER 自动应用,无需手动迁移

## 后端
- **`check_annual_leave_eligible()`**(`core/database.py:1941-1983`)改为:
  - SELECT 增加 `annual_leave_override` 字段
  - 开启时:**只校验 hire_date**(保留入职年限 + 入职日期空检查),跳过 NSSF/NIDA
  - 关闭时:走原逻辑(全部 4 项)
- **新端点** `POST /api/employees/<id>/annual-leave-override`(`app.py:1517` 之前):
  - `@editor_required + @require_permission('oa','approve')` 与 `oa_approve_event` 同级
  - 入参 `{override: 0|1}`,严格白名单 + log_audit(`action='annual_leave_override_toggle'`)
- **薪资计算零影响**(`core/calculator.py`):年假本就只通过出勤 L 状态间接影响(详见 AGENTS.md)

## 前端(`templates/index.html`)
- **档案展示页**(`index.html:511`):NSSF 行下新增"年假资格豁免"行,✓ / ○ 双色标识
- **编辑模态框**(`index.html:3213-3219`):NSSF 输入行下加 checkbox
  - 权限判定:`hasPermission('oa','approve')`(与全局 `_authState.permissions` 数组一致)
  - 无权限者:checkbox `disabled`,提示文案"仅 OA 审批人可修改"
  - 有权限者:提示文案"豁免 NSSF/NIDA 资格检查"
- **`saveEmployeeProfile`**(`index.html:3303-3317`)末尾:仅 `canOAApprove` 才提交,独立 POST 新端点,失败回滚
- **i18n**(`static/js/i18n.js:77-79, 1123-1125`):3 个键 × 中英双语
  - `emp_annual_leave_override` / `emp_annual_leave_override_can_edit` / `emp_annual_leave_override_no_perm`

## 本地验证
- `data/kilwa.db` 模拟 ALTER 添加列成功(130 行 employees 默认 0)
- 找到一名员工 id=8 同时 `nssf_enrolled=0` 且 `nida_number=''`,开启 override=1 后:
  - 原返回:`['未参加NSSF', 'NIDA证件号为空']`
  - 现返回:`['入职日期为空']` ← NSSF+NIDA 已被豁免
- 测试后已重置所有行 override=0,数据无污染

## 部署状态(2026-08-16 01:30)
- commit `e2f6e2b`,已 push + 服务器部署,服务 active
- 备份:`/root/enprizon-salary/data/backups/kilwa_before_p20_20260816_012936.db`(606KB)
- 服务器验证:`annual_leave_override` 列存在 / 133 员工 / override=1 数量 0 / 抽查 YUSUPH HAMISI #52(0, '', 0)符合截图预期
- **下一步**:KEJU(OA 审批人)登录后在 YUSUPH HAMISI #52 等员工档案编辑页勾选豁免,即可正常提交年假申请

## 风险
- 新列对历史数据无影响(默认 0 = 旧行为)
- 移动端 `mobile.html` 无员工档案编辑功能,跳过(下次有人提移动端编辑再加)
- 权限判定依赖 `_authState.permissions` 数组,需用户登录后才会加载 — 未登录用户看到 disabled 是预期行为

## 关联
- 当前 main: `e2f6e2b`(2026-08-16)
- 用户确认的设计选择(单一豁免开关 + 独立端点)原记录于 `/Users/osong/.codebuddy/plans/quantum-thunder-darwin-kF1Jvkkj.md`（**该 plans 文件已清理失效**，设计结论以本文件为准）
