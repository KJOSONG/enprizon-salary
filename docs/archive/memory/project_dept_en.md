---
name: 部门去中文改造
description: 2026-08-14 employees.department 122行去除中文只留英文,前端采集池改英文关键词,本地测试通过
type: project
---

2026-08-14 部门名称去中文改造(用户需求:系统部门名只保留英文字段)。

- 数据库: `employees.department` 122 行由 `中文[EN:英文]` 转为纯英文,9 种部门全部英文化,无中文残留;转换前已备份 `data/backups/kilwa_before_dept_en.db`;转换脚本 `_work/dept_to_english.py`(支持 --dry)
- 前端: `templates/index.html` `filterEmpByDept` + `templates/mobile.html` `deptPool`/`deptHas` 由中文关键词改为英文关键词(UNDERGROUND/DRILLER/CRUSH/SORT),采集四池人数与改前一致(28/15/31/56)
- 系统**没有**部门管理功能(无部门表/无增删部门/无子部门),部门只是员工档案文本字段,下拉选项从现有员工自动聚合
- 关联点: `ENPRIZON LINDI PROJECT` 顶层月薪判断(calculator/app.py)不受影响(该部门值未变);`core/addressbook.py` guess_pay_type 是 Excel 导入死代码不受影响

**Why:** 用户要求界面/数据只保留英文部门名,强调先全面评估关联再动;部署时要求服务器先备份再 pull。
**How to apply:** 已部署(main=491ba33):服务器先一致性备份 `data/backups/kilwa_before_dept_en_20260815_045236.db` 再 git pull,转换 125 行(服务器132人)残留 0,重启 active;历史归档保留旧值不动。前端采集池英文关键词判断与本地一致,四池人数 28/24/19... (服务器分布) 由浏览器端根据数据自动计算。
