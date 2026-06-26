# Kilwa System 项目长期记忆

## 项目概述
- **名称**：ENPRIZON LINDI PROJECT（Kilwa 矿区管理系统）
- **技术栈**：Python Flask + SQLite + 原生 HTML/CSS/JS
- **功能**：员工薪资计算、产量管理、出勤管理、审计日志
- **数据规模**：130 名员工，月应发工资约 5,000 万 TZS
- **启动方式**：`./start.sh start`（前台）= `./start.sh bg`（后台，日志写入 `.kilwa.log`）
- **端口**：8080（自动检测空闲端口）
- **语言**：支持中英文双语切换（i18n），偏好存 localStorage

## 关键文件
| 文件 | 用途 |
|------|------|
| `app.py` | Flask 主应用，路由和 API 入口 |
| `core/calculator.py` | 薪资计算核心逻辑（井下计件、日薪、月薪） |
| `core/database.py` | SQLite 数据库操作 |
| `templates/index.html` | 前端 SPA 页面（单页应用） |
| `static/js/i18n.js` | 中英双语翻译引擎 |
| `static/css/style.css` | 暗色科技风主题样式 |
| `start.sh` | 启动脚本 |

## 重要修复记录
- **2026-06-02**：修复日薪重复计薪 Bug（eid+date 去重），5 人多算 82,000 TZS
- **2026-06-02**：井下计件白班/夜班按 eid 去重（当前数据无重复，0 人受影响）
- **2026-06-06**：新增奖金/罚款功能（详见以下"奖金/罚款功能"）

## 奖金/罚款功能
- **存储**：SQLite 独立表 `bonus_penalties(employee_id, month, bonus, penalty)`，主键 `(employee_id, month)`
- **计算公式**：`实发 = 应发合计 + 奖金 - 罚款 - 预支 - NSSF + 司机津贴`
- **编辑入口**：员工页面表格中两个可编辑数字输入框（奖金/罚数列），失焦自动保存
- **审计日志**：操作类型 `bonus_penalty_update`，记录 `{month, bonus, penalty}`
- **联动**：保存后自动触发 recalculate → 更新薪资页 + 数据台 + 导出报表

## 约定与偏好
- 钻工跨队长不修复（设计如此）
- 语言偏好默认中文，切换后持久化
- Cloud Studio 部署时需显式指定 .xlsx 数据文件
- 司机津贴为企业级手工输入，不分摊到个人，仅影响最终实发合计
- 奖金/罚款按月独立，不影响应发合计（四轨计算），仅影响实发
