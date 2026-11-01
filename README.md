# SilicoLab 0.2.0

SilicoLab 是面向本地科研项目的 macOS 生物信息学智能体工作台。以 pi-durable 为唯一任务与会话内核、pi-ai 接入模型，复用已有Python科学工具，并在受限环境中运行临时分析。界面使用React／TypeScript和系统WKWebView，后台独立于窗口；模型解释、真实计算和独立校验分别保留。

## 使用

- 原生应用：打开`release/SilicoLab.app`，也可从同目录DMG或ZIP安装。当前为Intel macOS x86_64；ad-hoc签名、未Developer ID或公证，不能将本机完整性验证视为Gatekeeper认可。
- 浏览器方式：在项目根目录双击 [start.command](start.command)，打开 <http://127.0.0.1:8765>；双击 [stop.command](stop.command) 停止服务。首次运行需要 Python 3.10+，构建界面需要 Node.js 22.12+。
- 原生应用数据：`~/Library/Application Support/SilicoLab/`；导出目录：`~/Downloads/SilicoLab/`。同名导出自动加序号。
- 浏览器方式的数据位于项目根目录 `data/silicolab.sqlite3`。已有 SilicoLab 历史会保留；不读取或迁移其他产品的数据。

## 当前功能

- 项目工作台：用户选定目录、多个对话、草稿保存与重开；项目记录由真实 Node/pi-durable 宿主持久化，打开项目不触发模型。按需右侧工作区与可展开图标导航联动；原专项工作台从侧栏进入，或访问 `/#manual`。
- 应用级BYOK模型配置，API key独立存入SilicoLab Keychain；对话可随时切换模型，下一请求生效，历史和已完成工具保持，不自动换供应商。显示逐请求实际来源和已报告用量，缺失为未知，不按费用阈值自动暂停。[已实测配置及限制](docs/provider-compatibility.md)包含Responses和Messages的流式、工具闭环、切换、取消及安全错误。明确标注的本机验证模型仍可离线验证基础交互。
- 项目对话的本机验证模型可在明确授权后编排已有 D2P 本地 Python 工具，使用固定 FASTA、独立 DNA 校验和真实 FASTA/Excel 下载；普通目标不默认路由专项，本地失败不回退上传。详见 [本地科学任务](docs/local-scientific-tasks.md)。
- 项目结果区支持真实部分完成与逐条错误、完整 DNA/密码子和校验来源检视、完整序列复制、单条/批量 FASTA、标准合成表与含固定输入/原始响应/尝试身份的记录包；刷新和导航不重跑计算。
- 缺少末尾终止符或受控工具授权时，任务保存必要问题并等待；对话/任务面板答复后继续，重复答复不重复执行，原件和固定输入保持不变。
- 科研任务可真实暂停本机请求/计算，重开后明确逐项选择恢复；先核对固定输入和已完成产物，完成项复用、未完成本机步骤重做，保留尝试与暂停原因，不自动继续。
- 同项目任务按FIFO串行，多个项目可有界并行；等待和暂停释放执行位置，答复/恢复明确继续后重新排队，重开不自动启动队列。
- 模拟独立外部作业可展示稳定请求/job身份、结果未知与核对、等待释放位置、明确独立取消；只调用本机人工假服务，不连接真实集群或科学远端。
- 受限Python仅使用预装库和固定输入，默认无网络／安装／原件写入／模型凭据／子进程；数值CSV分析保留脚本、JSON、Excel与独立核验。自动发现约定位置skills/MCP，来源信任与任务授权分开，不自动安装或导入其他软件认证。
- 真实关窗保留独立后台，完全退出停止本机脚本并保留逐项恢复；必要决定可发送默认关闭的系统通知，点击原任务，不自动答复。项目升级先备份，恢复核对原身份／检查点／产物，执行契约不兼容时保留检视导出。
- 项目工作台源码运行需要Node24.16.0和`runtime/`锁定依赖；安装包随带Node、后端Python、分析Python和原生通知组件。分发检查与真实限制见[安装验收矩阵](docs/distribution-acceptance.md)。

- 单条蛋白、多条 FASTA、文件拖入与输入校验；末尾 `*` 提示和补充选项。
- XLSX / CSV / TSV 导入，支持工作表、表头、起始行和名称/序列列映射。
- ProteinFactory 远端计算，以及仅支持 D2P 默认体系的本地实验引擎。
- 目标宿主、避免位点、参数预设、串行队列、停止后续提交与失败重试。
- DNA、密码子对照、GC 含量、翻译与避免位点校验。
- 历史搜索与筛选、单条和批量删除、复制、FASTA / Excel / 记录包导出。

Excel 导出仅包含“基因合成”工作表，列为“序号、合成名、核酸序列”，沿用既定模板样式，不含单元格注释或额外记录页。

明确选择ProteinFactory专项时默认使用其远端服务，提交后序列发送至第三方ProteinFactory；普通密码子或反向翻译请求不会自动路由该专项。选择本地实验时不上传序列，失败和重试也不会自动回退到远端。本地约束处理可能产生与远端不同的 DNA；校验通过不代表表达效果已验证。当前远端请求不使用浏览器登录凭据。

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
| `tools/runtime-probe/` | 智能体宿主与恢复的独立机制验证 |
| `tools/python-probe/` | macOS 单进程Python边界回归；正式执行复用受限模块 |
| `docs/` | 架构、开发、打包、接口和功能说明 |
| `examples/` | 可公开的人工输入示例 |
| `research/` | 本地调研、原始证据、实验脚本与冻结快照；不作为发布源码 |
| `data/`、`outputs/` | 本地运行数据、日志与测试产物 |
| `build/`、`release/` | 构建中间文件与最终分发包 |

进一步阅读：[架构](docs/architecture.md) · [开发与测试](docs/development.md) · [密码子优化](docs/codon-optimization.md) · [远端接口](docs/remote-api.md) · [macOS 打包](docs/packaging.md) · [性能](docs/performance.md)。

正式代码、常规测试及打包不依赖 `research/` 或私人表格。它们所需的算法、密码子表、空白模板和人工回归样例已归入正式目录。完整本地调研资料仍保留；`.gitignore` 已排除调研资料、运行数据、本机环境和生成产物。正式源码、必要资源、人工测试与示例保留。
