# STATUS.md — 当前状态（唯一权威）

> **本文件是全项目"当前状态"的唯一事实源**（main 哈希 / 部署 / 账号 / 数据 / 挂起 / 待办）。
> 每次部署或状态变化后**只改本文件**，不要再写进 AGENTS.md 或记忆速查卡。
> 历史编年 → `docs/PROGRESS.md`；路线图与遗留 → `docs/ROADMAP.md`；文档导航 → `docs/INDEX.md`。

最后更新：2026-11-09

## 一、仓库与部署

| 项 | 值 |
|----|-----|
| 本地克隆 | `/Users/osong/AI专用分析文件/enprizon-salary` |
| 远程 | `github.com/KJOSONG/enprizon-salary` |
| 分支模型 | 一切最终合并 `main`；大改动走 feature 分支 + 团队并行 |
| **当前 main** | **`a424ac2`**（2026-11-07 审计 9 问题修复，已部署，生产冒烟通过） |
| 服务器 | 阿里云新加坡 `47.236.187.33`，894MB 内存（红线见 `.codebuddy/rules/project-core.md`） |
| 服务器路径 | `/root/enprizon-salary`，gunicorn `127.0.0.1:8081`，服务 active |
| 后端直连 | `http://127.0.0.1:8081/api/...`（**不加 `/salary` 前缀**，前缀由 nginx 处理） |
| SSH | `ssh -p 22222 -i ~/.ssh/new.pem root@47.236.187.33`（旧 `~/new.pem` 路径已失效） |
| 部署别名 | `save-salary` = 服务器 `git pull && systemctl restart enprizon-salary` |
| GitHub 连不上时 | bundle 通道：`git bundle create /tmp/x.bundle <base>..main` → scp → 服务器 `git pull /tmp/x.bundle main` |

## 二、账号（AI 验证专用，勿动生产密码）

| 环境 | 账号 | 密码 | 角色 |
|------|------|------|------|
| 本地 + 服务器（首选） | `keju_check` | `000000` | super_admin |
| 本地 | `KEJU` | 为生产侧密码（本地库 10-28 被生产副本覆盖，原 `0000` 已失效，需要时重建） | super_admin |
| 服务器 | `KEJU` | 密码已失效，勿用 | super_admin |
| 服务器 | `user` | `qweasd` | viewer |

🔒 绝不 UPDATE 生产任何用户的 `admin_users.password_hash`。

## 三、数据状态

- **生产 2026-10 已关账**（月度关账功能 22ea2a4）：该月所有薪资相关写操作 409；KEJU 可在薪资页解锁。查看/导出/重算不受影响。
- 本地 `data/kilwa.db` 是生产副本的**滞后快照**，任何员工/部门/薪资事实核查必须 SSH 只读查生产库（`sqlite3 'file:...?mode=ro'`），禁止以本地库为事实来源。
- 需要生产数据测试 → 拉副本到本地（服务器 `sqlite3 ".backup"` → scp → 删临时文件），测完即弃，绝不回写生产。
- 手动备份：`data/backups/kilwa_before_<版本>_<时间戳>.db`（只留最新 1 个）；每日自动 `/root/salary-backup/`（留 7 天）；`archived_kilwa.db` 永久保留。

## 四、挂起分支（未合并未部署）

- **`feature/absence-double-penalty`（`172b10b`）旷工双倍罚扣**：普通月薪工当月 A 前 4 天每日额外扣 1×日均（含自然无薪=2×），第 5 天起仅自然无薪；ENPRIZON 排除；独立扣项 absence_penalty 不进 gross。本地库+生产副本双版本逐分回归全绿（08 月 726,922 / 09 月 284,616 / 10 月 180,770）。**用户明令暂停**：等待是否叠加"普通月薪工 T 日改带薪"决策后一起部署。

## 五、当前待办（详见 ROADMAP.md §遗留清单）

1. 挂起分支的用户决策（见上）。
2. oa-ux 批次 4 遗留 6 项（按人按日重算、审批人下拉跨页聚合、page 超界 clamp 等）。
3. 台账直改 dept/team 不写 `employee_base_history` 的漂移隐患（长期修法需立项）。
4. P53 遗留：134/63/73 各 1 天基数待用户补。
5. 生产合同表补录（P52-c 年假资格依赖合同，未豁免者暂不能请年假）。
6. 服务器 894MB 内存中期治理（管线峰值贴线）。

## 六、新会话读取路径

1. `AGENTS.md`（自动加载：架构 + 计算不变量 + 协作纪律）
2. 本文件（现在怎样）
3. `docs/INDEX.md`（细节去哪找）
4. 改计算逻辑前必读记忆 `salary_calc_logic.md` + `.codebuddy/rules/code-invariants.md`
