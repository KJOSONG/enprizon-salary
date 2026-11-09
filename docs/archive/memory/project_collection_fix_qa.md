---
name: collection-fix QA 验收（已通过）
description: feature/collection-fix 8 项改动 QA 验收 31/31 全通过;R1 曾误报 FAIL 实为调试脚本污染;2 个范围外遗留 bug
type: project
---

# feature/collection-fix 验收(2026-08-15,最终通过)

## 验收结果:8 项全通过(31/31 PASS)
- B1 采集编辑去重(含 B1c 3e2d49d 夜班不污染)/R1 档案基数/R2 i18n/R3 日薪按天/R4 姓名链接/R5 历史筛选/R6 预览先编辑/R2b 入职必填
- 报告:`_work/qa_report.md`;脚本:`_work/qa_acceptance.py`(支持 `ONLY=xxx` 参数,测试前自动备份 DB、结束后恢复)

## ⚠️ R1 曾误报 FAIL,已澄清(勿再引用旧结论)
- 首次跑显示档案页基数 0 → 根因是**调试脚本污染本地库**(提交了 2026-08-28/29 采集 + R3 残留临时例外 id=208),且 `backup_db()` 每次覆盖备份为污染态
- 清理数据库后 R1 稳定 PASS:`api_employee_profile`(app.py:1460)已正确合并 override 基数(96→13000, 80→700000)
- 教训:验收脚本写库测试后,`backup_db()` 覆盖备份会把污染态当基准,应确保起始库干净

## 范围外历史遗留 bug(本次未修,记入 backlog)
1. **井下编辑表单夜班渲染污染**:`templates/index.html` ~5839 `prodRow(prefix, data)` 之前误读 day 值 → **已修(3e2d49d)** 传 day/night 数据源
2. **档案页"添加临时例外"按钮失效**:`saveTempOverride` 同名函数(档案页版 ~3418 vs 员工列表版 ~3681)后者覆盖前者 → 档案页模态框保存报 null id。R3 测试改走 API 操作临时例外
3. **档案页 pfSalaryType 等 setTextContent 字段**:切换语言后需重进页面才刷新,dev 记为后续优化

**Why**: R1 误报可能导致未来会话误判为产品 bug。
**How to apply**: 本地验收前先确认 `data/kilwa.db` 干净(可对比 `data/backups/kilwa_before_dept_en.db`);写库测试用备份/恢复机制时注意备份基准。
