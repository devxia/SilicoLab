# SilicoLab 0.1.3

SilicoLab 是面向多种科研功能的本地软件，当前已实现密码子优化。界面使用 React + TypeScript，后端使用 FastAPI + SQLite；macOS 应用使用系统 WKWebView，并内嵌 Python 运行环境。

## 使用

- 原生应用：打开 `release/SilicoLab.app`，也可使用同目录的 DMG 或 ZIP 安装包。当前构建为 Intel macOS x86_64。
- 浏览器方式：在项目根目录双击 [start.command](start.command)，打开 <http://127.0.0.1:8765>；双击 [stop.command](stop.command) 停止服务。首次运行需要 Python 3.10+，构建界面需要 Node.js 22.12+。
- 原生应用数据：`~/Library/Application Support/SilicoLab/`；导出目录：`~/Downloads/SilicoLab/`。同名导出自动加序号。
- 浏览器方式的数据位于项目根目录 `data/silicolab.sqlite3`。已有 SilicoLab 历史会保留；不读取或迁移其他产品的数据。

## 当前功能

- 项目工作台：用户选定目录、多个对话、草稿保存与重开；项目记录由真实 Node/pi-durable 宿主持久化，打开项目不触发模型。按需右侧工作区与可展开图标导航联动；原专项工作台从侧栏进入，或访问 `/#manual`。
- 项目对话支持明确标注的本机验证模型：真实内核调用受控文本计数工具，流式显示历史、进度、执行身份和可核对产物；刷新不重新提交。尚不连接真实 provider 或科学远端。
- 项目工作台源码运行需要 Node 24.16.0 和 `runtime/` 锁定依赖；真实模型、科学工具智能体闭环及新版后台分发仍有独立验收任务。

- 单条蛋白、多条 FASTA、文件拖入与输入校验；末尾 `*` 提示和补充选项。
- XLSX / CSV / TSV 导入，支持工作表、表头、起始行和名称/序列列映射。
- ProteinFactory 远端计算，以及仅支持 D2P 默认体系的本地实验引擎。
- 目标宿主、避免位点、参数预设、串行队列、停止后续提交与失败重试。
- DNA、密码子对照、GC 含量、翻译与避免位点校验。
- 历史搜索与筛选、单条和批量删除、复制、FASTA / Excel / 记录包导出。

Excel 导出仅包含“基因合成”工作表，列为“序号、合成名、核酸序列”，沿用既定模板样式，不含单元格注释或额外记录页。

默认使用远端服务，提交后序列发送至第三方 ProteinFactory。选择本地实验时不上传序列，失败和重试也不会自动回退到远端。本地约束处理可能产生与远端不同的 DNA；校验通过不代表表达效果已验证。当前远端请求不使用浏览器登录凭据。

## 开发

以下命令均从项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "./backend[test]"
npm --prefix frontend ci
npm --prefix runtime ci --ignore-scripts --no-audit --no-fund
npm --prefix frontend run build
.venv/bin/python -m silicolab
```

前后端分别开发：

```bash
# 终端一
.venv/bin/python -m uvicorn silicolab.server:create_app --factory --host 127.0.0.1 --port 8765
# 终端二
npm --prefix frontend run dev
```

测试：

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend test
```

桌面桥接测试需在安装了 desktop 依赖的环境运行。构建分发包：

```bash
bash packaging/macos/build.sh
```

## 目录与文档

| 目录 | 职责 |
|---|---|
| `backend/` | Python 包、应用契约、科学功能、后端测试与必要资源 |
| `runtime/` | 项目持有的 Node/pi-durable 宿主与固定依赖 |
| `frontend/` | React 界面、前端测试、字体和构建配置 |
| `packaging/macos/` | 原生入口、打包脚本、图标与 DMG 布局 |
| `tests/e2e/` | 浏览器与打包应用的端到端验证 |
| `tools/benchmarks/` | 可重复运行的性能工具 |
| `tools/runtime-probe/` | 独立的智能体宿主与恢复验证；未接入正式应用 |
| `tools/python-probe/` | macOS 单进程 Python 文件、网络与停止边界实验；未开放产品执行 |
| `docs/` | 架构、开发、打包、接口和功能说明 |
| `examples/` | 可公开的人工输入示例 |
| `research/` | 本地调研、原始证据、实验脚本与冻结快照；不作为发布源码 |
| `data/`、`outputs/` | 本地运行数据、日志与测试产物 |
| `build/`、`release/` | 构建中间文件与最终分发包 |

进一步阅读：[架构](docs/architecture.md) · [开发与测试](docs/development.md) · [密码子优化](docs/codon-optimization.md) · [远端接口](docs/remote-api.md) · [macOS 打包](docs/packaging.md) · [性能](docs/performance.md)。

正式代码、常规测试及打包不依赖 `research/` 或私人表格。它们所需的算法、密码子表、空白模板和人工回归样例已归入正式目录。完整本地调研资料仍保留；`.gitignore` 已排除调研资料、运行数据、本机环境和生成产物。正式源码、必要资源、人工测试与示例保留。
