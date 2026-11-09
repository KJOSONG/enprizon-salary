---
name: P4-P5 Completion
description: 2026-08-12 P4(8 commits) + P5(3 commits) 全部交付, 本地 refactor 分支已就绪
type: project
---

# P4-P5 完成记录

**日期**: 2026-08-12
**分支**: `refactor`(历史,已并入 main 作废;旧哈希已因历史重写失效)

> 历史记录。P4(权限/移动端打磨/搜索/表单引擎)、P5(归档/计薪切换/清理)均已并入 main 并部署。当前状态见项目内 `docs/STATUS.md`（原 project_current_state.md 已改为指针）。

## P4 交付 (5 commits)

| Commit | 内容 |
|--------|------|
| `6208a11` | 角色细化: permissions/user_grants表 + require_permission装饰器 + 28端点@login_required + system/users权限矩阵UI |
| `d0f7778` | 手机端打磨: 44px触摸目标 + 16px防iOS缩放 + 侧边栏滑动手势 + 底部导航 |
| `e14c692` | 全局搜索: search_all()跨表LIKE + /api/search端点 + scope选择器 + 防抖300ms |
| `4c15840` | 表单自定义: form_schemas/form_fields表 + schema驱动渲染器 + page-system-forms管理UI |
| `27f4ccc` | 审查修正: DELETE参数BUG + require_permission接入2端点 + 6表单全补 + renderer接档案页 |

## P5 交付 (3 commits)

| Commit | 内容 |
|--------|------|
| `04ab6ac` | 归档+种子: ATTACH归档只读查询 + seed_new_tables_from_excel() + leave_requests表 + page-system-archive |
| `46a2906` | 计薪重构: underground_mode切换(计件↔评分) + scoring模式月薪+津贴+奖金 + 事件驱动桥接 |
| `42193cc` | 清理: /api/employees数据补全(overrides+bonus) + 9处前端调用全切换 + 旧端点标记deprecated |

## 关键架构决策

- **计薪模式**: 井下工人支持整组切换 piecework/scoring，通过 settings['underground_mode'] 配置
- **事件驱动**: transfer/salary_change/resign 审批自动生成 overrides，优先级高于手动覆盖
- **角色**: 仅4角色(super_admin/admin/editor/viewer)，通过 user_grants 表单独授权
- **归档**: 旧 kilwa.db → archived_kilwa.db (ATTACH只读)，启动时自动备份
- **种子**: 从 data/source/*.xlsx 重建 employees + hire 事件 (仅首次)

## 下一步

1. **本地验证**: 启动 python3 app.py，检查所有页面、验证计薪模式切换
2. **推送部署**: 本地通过后 push refactor → 服务器 git pull + restart
3. **旧端点**: /employees 标记 deprecated 但保留兼容

## 遗留

- P1遗留 #1: 事件驱动计薪 _apply_events_for_month() — 已通过桥接机制实现
- P0遗留 #4: 旧API端点清理 — /employees 已迁移但保留兼容
