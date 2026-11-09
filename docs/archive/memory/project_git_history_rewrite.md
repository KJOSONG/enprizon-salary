---
name: Git 历史重写 + 首次部署
description: 2026-08-14 数据库防覆盖（重写全部113提交移除敏感文件）+ refactor 合并 main + 服务器首次部署
type: project
---

# Git 历史重写 + 首次部署（2026-08-14）

**决策**: 用户要求"确保日后部署时本地数据库不被提交覆盖"，选择彻底重写历史而非仅靠 gitignore。同日完成 refactor→main 合并与服务器首次部署。

**Why**: 历史提交 `89dc5c0`(初始)/`e6b3e9a` 曾跟踪 `data/kilwa.db`(274KB 旧库)、`kilwa.db-wal/shm`，`git checkout` 到这些旧提交会在工作区恢复旧库覆盖当前真实数据库。`f514f81` 起才 gitignore。仅靠 .gitignore 无法防 checkout 旧提交。

**How to apply**:
- 历史已重写，**切勿再引用旧哈希**（如 9e7a6b1、8619c08 等均为重写前哈希，GitHub 上已不存在）。所有分支现指向新哈希。
- 日后 `git pull` 部署**不会触碰** `data/kilwa.db`（gitignore 完整 + main 树 data/ 条目=0 + 历史已清）
- **绝不要用 `git add -f` 强制添加数据库文件**（可绕过 gitignore）
- 服务器与远程均已同步重写后历史

## 关键事实（以 2026-08-14 为准）

- 重写后 main = refactor = `a4c2189`（"feat: 移动端适配..."，原 9e7a6b1 重写版）
- 全部 113 提交重写，移除 4 文件：`data/kilwa.db`、`data/kilwa.db-wal`、`data/kilwa.db-shm`、`data/source/ATT.xlsx.bak.20260628_163347`
- 本地/远程/服务器三方已同步；服务器运行 main 分支，active
- 服务器部署：130 员工，8月应发 21,555,864 TZS（本地=服务器一致）
- 服务器备份：`data/kilwa.db.bak_20260814_pre_refactor`（旧库）、`kilwa.db.old_202608132031`；首启自动 `archived_kilwa.db`

## 首次部署记录（2026-08-14）

- refactor→main fast-forward 合并（40 提交零冲突），push main
- 服务器切 main + pull + restart（stash 保护 backup.sh 7 天清理改动，恢复保留）
- **数据库整体替换（仅本次）**：本地库(476K, 130员工) → 服务器，日后不再上传
- 服务器 admin_users：KEJU(super_admin)、user(viewer)；原服务器 maua 账号未保留（用户确认删除）
- KEJU 密码哈希恢复为原始值 c4e7b1e6...（测试用 test1234 已还原，切勿再改）

## 8月数据更新（2026-08-13 导入，随本次部署上服务器）

- 破碎 8/13 新增（163 bags, 7人）；出勤 8/13 新增（22人 P）
- 8/11 删除出勤 67/71（保留 79）；8/12 删除出勤 71/79（保留 67）——按 Excel 对齐，8/12 缺 JASTINE 组 12 人未补（用户确认）
- 来源：`/Users/osong/AI专用分析文件/8月最新原始信息/Attendance+data+daily+and+piece+rate.xlsx` + `Crush+team+data.xlsx`
