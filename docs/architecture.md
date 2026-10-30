# 项目架构

## 调用关系

React 项目工作台通过本机 HTTP 的 workbench 契约与 Python 应用模块通信，再以私有 JSONL 连接每项目单一 Node/pi-durable 宿主。项目对话和草稿保存在用户选定目录的 SQLite 中；打开和检视不启动模型调度。应用级项目索引只保留定位，不代替项目记录。

原手动专项工作台仍通过 HTTP 与 FastAPI 科学模块通信，任务队列显式选择 ProteinFactory 远端或本地实验引擎，其已有数据库不迁移到项目对话中。原生应用另提供目录选择、草稿、剪贴板、导出与打开下载目录的受信桥接方法。

## 正式代码

- `backend/src/silicolab/branding.py`：名称、版本与 Bundle ID。
- `workbench.py`：项目生命周期、跨进程所有者、Node 子进程和工作台契约。
- `runtime/src/host.ts`：真实持久化内核的项目与对话文档、草稿版本冲突检查；只经应用契约使用。
- `frontend/src/workbench/`：项目对话主界面及 A+C 导航与分析区联动。
- `server.py`：请求处理、任务状态、串行队列、事务存储、摘要索引与 SSE。
- `paths.py`：项目数据、原生应用数据和前端静态资源位置。
- `launcher.py` / `__main__.py`：浏览器启动和停止入口。
- `desktop.py`：Cocoa/WebKit 窗口、生命周期与原生桥。
- `features/codon/`：密码子客户端与校验、引擎分流、本地搜索、异步远端传输、表格导入导出。
- `features/codon/resources/`：运行时密码子表与空白 Excel 模板，随 Python 包和原生应用一起分发。
- `frontend/src/app/`：当前工作台和应用级状态。
- `frontend/src/features/codon/`：密码子优化、历史、表格映射界面及其逻辑与测试。
- `frontend/src/platform/`：原生桥；`styles/`：全局样式。

当前保留 server 和 App 的既有内部结构；本轮主要调整归属、导入和资源定位，未拆分任务状态机或重写界面。

## 路径与数据

源码方式默认从项目根目录读取 `frontend/dist/`，数据库使用 `data/silicolab.sqlite3`。已安装的独立 Python 包在没有源码项目时使用 Application Support 存储数据；可用 `SILICOLAB_DB` 和 `SILICOLAB_FRONTEND_DIST` 显式指定数据库与已构建界面。

原生应用从包内读取静态资源，将可写数据放入 `~/Library/Application Support/SilicoLab/`；`SILICOLAB_APP_DATA` 可用于隔离测试。导出写入 `~/Downloads/SilicoLab/`，避免覆盖同名文件。

## 新功能与调研

正式新功能放入前后端各自的 `features/<feature>/`；共用平台能力留在应用层。只在出现实际共用需求时提取公共逻辑。

本地 `research/<topic>/` 可存放资料、来源、探索脚本、原始数据和阶段报告。调研成熟后，将必要实现、资源、人工测试与使用说明提炼到正式目录。正式代码不得导入 research，也不得通过符号链接或绝对路径间接依赖它。

D2P 的研究冻结脚本与表原样保留在本地；正式引擎是独立代码副本。文件导入路径变化会改变代码指纹，旧任务重试仍遵循原有版本保护，可复制为新任务运行；算法输出和映射不因整理而改变。
