---
name: force-clean-restart-and-cache-bust
overview: 彻底清理并重启服务，添加 HTML 版本戳打破浏览器缓存，解决"代码已修改但前端显示未生效"的问题
todos:
  - id: clean-kill-server
    content: 先 kill 服务进程（PID 41171），然后删除所有 .pyc、__pycache__、.db-wal、.db-shm 缓存文件
    status: completed
  - id: add-version-stamp
    content: 在 app.py 中添加 APP_VERSION 时间戳变量并传入 render_template，在 index.html 的 style.css 链接加 ?v= 参数、head 中增加 meta 防缓存标签
    status: completed
    dependencies:
      - clean-kill-server
  - id: restart-and-verify
    content: 重启服务，用 curl 端到端验证 salary API、verify API、daily-wages API、HTML 模板的完整正确性
    status: completed
    dependencies:
      - add-version-stamp
  - id: browser-hard-refresh
    content: 指导用户执行浏览器硬刷新（Cmd+Shift+R），确认所有功能在页面上正确生效
    status: completed
    dependencies:
      - restart-and-verify
---

## 用户需求

用户报告所有之前声称已修改的代码在浏览器页面中均未生效——"你所谓的改的内容现在还是那个样子都没有生效"。需要根本解决浏览器顽固缓存导致页面不更新的问题。

## 产品概述

这是一个 Flask 单页面应用（SPA）薪资管理系统。服务端 Python 代码修改已正确写入磁盘且 API 返回正确数据，但浏览器缓存了旧版 HTML/CSS，导致用户看到的页面始终是修改前的状态。

## 核心功能

- 添加 HTML 版本戳和 CSS 版本查询参数，强制浏览器加载最新文件
- 彻底清理服务器所有缓存文件（.pyc、__pycache__、SQLite WAL/SHM）
- 完全重启服务进程，确保所有模块重新加载
- 端到端验证：API 数据、模板渲染、双路径核对、日工资联动

## 技术方案

### 根因分析

经过逐文件内容和时间戳验证（`python3 -c` 对比 .py vs .pyc 的 `os.path.getmtime()`），确认：

- 所有源文件修改已正确写入磁盘
- .pyc 缓存时间戳晚于 .py 源文件（Python 会正确重编译）
- API 端点 `/salary`、`/salary/verify`、`/daily-wages` 返回数据完全正确
- 模板 HTML 已包含所有新增函数（`deleteSingleOverride`、`toggleDateShift`、`await recalculate` 等）

**唯一根因**：浏览器顽固缓存。Chrome/Safari 即使收到 `Cache-Control: no-store` 头，仍可能在内存/Service Worker 中保留旧版页面，导致用户看到的一直是第一版。

### 修复策略

分三步彻底解决：

**第一步：服务端强制清理**

```
kill 进程 → rm __pycache__/**/*.pyc → rm data/kilwa.db-wal → rm data/kilwa.db-shm
```

**第二步：前端版本戳防缓存**

- `app.py` 中生成启动时间戳 `APP_VERSION = str(int(time.time()))`，通过 `render_template('index.html', version=APP_VERSION)` 传入模板
- `templates/index.html` 中 `<link href="/static/css/style.css?v={{ version }}">` 和 `<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">`
- 每次重启服务，CSS 链接的查询参数变化，浏览器视为全新资源

**第三步：端到端验证**
用 curl 顺序调用所有关键 API，确认返回数据与预期一致：

- `/salary` → NANE DAUDI `salary_type=piece_driller`、`temp_overrides` 有 3 条
- `/salary/verify` → 钻工 path1≈path2（差 <10）
- `/daily-wages` → ALLYABDALAH 每日 7000（不是 7500）
- `/` → HTML 包含 `style.css?v=`

### 实现目录结构

```
kilwa-system/
├── app.py                    # [MODIFY] 添加 APP_VERSION 时间戳，传入 render_template
├── templates/
│   └── index.html            # [MODIFY] style.css 加版本参数、Meta 防缓存标签
└── core/
    ├── __pycache__/          # [DELETE] 所有 .pyc 缓存
    └── data/
        ├── kilwa.db-wal      # [DELETE] SQLite WAL 文件
        └── kilwa.db-shm      # [DELETE] SQLite SHM 文件
```

### 关键技术点

- **版本戳机制**：`time.time()` 取整转字符串，作为 `render_template` 的上下文变量，注入 CSS link 的 `?v=` 参数
- **Meta 标签双保险**：`<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">` 在 HTML 内声明不缓存
- **清理脚本一体化**：先 kill 进程 → 清理所有缓存 → 重启服务，确保不留任何旧状态
- **WAL/SHM 文件**：SQLite 的 WAL 模式会产生 `-wal` 和 `-shm` 文件，如果数据库已修改但 WAL 未 checkpoint，新进程读取的数据库状态可能不一致，必须在进程关闭后删除