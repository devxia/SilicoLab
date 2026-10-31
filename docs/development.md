# 开发与测试

所有命令从项目根目录执行。要求 Python 3.10+、Node.js 22.12+；打包需要 macOS 和桌面依赖。

## 环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "./backend[test]"
npm --prefix frontend ci
npm --prefix runtime ci --ignore-scripts --no-audit --no-fund
```

Python 的正式依赖和 desktop/test 可选依赖集中在 `backend/pyproject.toml`；requirements 文件是从根目录执行的便捷安装入口。前端配置与锁文件位于 `frontend/`。虚拟环境保留在根目录。

```bash
# 前端热更新（后端在另一个终端启动）
.venv/bin/python -m uvicorn silicolab.server:create_app --factory --host 127.0.0.1 --port 8765
npm --prefix frontend run dev

# 生产界面与浏览器启动
npm --prefix frontend run build
.venv/bin/python -m silicolab
.venv/bin/python -m silicolab --stop
```

## 项目与对话工作台

默认入口为项目工作台，浏览器可输入已有目录路径，macOS 源码应用也可通过本机目录选择器选择。创建后可新建多个对话、保存草稿并重开；目录需真实存在，打开已有项目不会创建空替代目录。项目记录位于选定目录 `.silicolab/session.sqlite`，应用索引位于应用数据库旁的 `projects.json`。只打开项目不调用模型。

正式 Node 宿主位于 `runtime/`，精确锁定 pi-durable/pi-ai/chord 1.4.0；要求 Node 24.16.0，使用同一 Node 的原生 TypeScript 擦除。源码安装支持 `SILICOLAB_NODE` 指定 Node 可执行文件，`SILICOLAB_RUNTIME` 指定运行时目录；分发包仍需独立验收，不能依赖开发机路径。手动专项入口为 `/#manual`，保留原有操作与接口。

```bash
npm --prefix runtime run typecheck
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench.py -v
# 临时工作台夹具与浏览器验收，两个终端运行
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench.py
```

浏览器验收覆盖真实项目持久化、多个对话、草稿、A+C 布局联动、窄窗口导航及手动专项入口。截图和 JSON 证据保存在被忽略的 `outputs/ui/workbench/`。领域语言见根 GLOSSARY，工程决定见 `docs/adr/`。

文件区还支持导入用户选定文件、真实预览和固定任务输入版本。导入副本可编辑，已有固定记录使用独立副本、版本号与 SHA-256，不受后续改动影响；失败不报告保存成功，同名文件不覆盖。参见 [项目输入契约](project-inputs.md)。验收入口为 `backend/tests/test_workbench_inputs.py` 和 `tests/e2e/browser_workbench_inputs.py`（同一 8767 临时夹具），浏览器证据在 `outputs/ui/workbench-inputs/`。

## 本机验证模型的真实循环

[主循环契约](agent-loop.md) 对应 #6。对话“运行本机验证”只授权人工文本计数，当前是明确标注的 pi-ai faux 模型驱动真实 pi-durable，不是浏览器假状态。任务、请求、工具、尝试和产物关联保存，SSE 只观察已提交历史/进度，不重发工作；原生后台及实际科学计算仍未交付。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_agent.py -v
# 与项目输入流程使用相同临时8767夹具
.venv/bin/python -B tests/e2e/browser_workbench_agent.py
```

前端构建会替换 `frontend/dist`，应先完成构建再运行后端全量测试/浏览器夹具，避免构建期间资源被暂时移除影响测试。

## 项目型本地科学任务

[#7 本地科学任务契约](local-scientific-tasks.md) 将固定 FASTA 与已授权 D2P 本地专项接入真实内核，Node 仅启动可信 Python 科学入口，复用原算法/独立校验/合成表导出。任务区可明确选择来源、终止符和避免位点并运行，查看逐条校验、取消本机任务及下载产物。普通请求不会自动进入专项，本地失败不上传。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_science.py -v
# 复用8767临时夹具
.venv/bin/python -B tests/e2e/browser_workbench_science.py
```

worker 的网络拒绝钩子只针对可信科学入口，不能代替不可信 Python 的系统隔离。正文中的真实来源、PID、网络尝试、产物 SHA-256 与逐项状态是实际执行证据，不宣称表达效果或载体校验已实现。

## 科研结果与完整记录

[#8 结果契约](scientific-results.md) 在右侧结果区检视真实序列表、完整 DNA/密码子、逐项错误和校验来源。成功、部分完成、失败与模型答复分开。单条/批量 FASTA、标准 Excel 和完整 ZIP 记录包来自同一次真实执行，记录包保留固定输入、原始响应和尝试身份；产物完整性不符时拒绝下载。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_results.py -v
# 复用8767临时夹具
.venv/bin/python -B tests/e2e/browser_workbench_results.py
```

浏览器证据在 `outputs/ui/scientific-results/`，包括部分失败、9003bp完整复制、逐项产物核对和窄窗口横向浏览，不进入 Git。

## 必要用户决定

[#9 决定契约](task-decisions.md) 将缺失终止符和不足工具权限保存为稳定待决定项；对话/任务面板可稍后答复，等待不循环调用模型，重复答复不重复执行。答复只作用于当前任务，不覆盖固定输入或原件；重开后不自动继续。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_decisions.py -v
# 复用8767临时夹具
.venv/bin/python -B tests/e2e/browser_workbench_decisions.py
```

## 暂停与逐项恢复

[#10 恢复契约](task-recovery.md) 提供对话/任务面板的真实暂停和明确选择恢复。暂停先关闭内核并回收受管科学进程，核对后再显示 paused；Node 强制退出时，应用持有的 socketpair 科学监督器回收其 worker。重开不自动执行，恢复核对固定输入与完成产物，复用完成项、重做未完成步骤。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_recovery.py -v
# 复用8767临时夹具
.venv/bin/python -B tests/e2e/browser_workbench_recovery.py
```

源码模式验证不代表 .app 关窗继续/完全退出和随包运行时已经通过；正式生命周期及分发仍有独立任务。

## 项目队列与有界并行

[#11 调度契约](project-scheduling.md) 持久保存项目FIFO，同项目最多1项主动执行、不同项目可并行；等待和暂停释放位置，答复/恢复明确继续后按当前队尾入场，重开只列出待恢复项。新任务运行存储位于项目内 `.silicolab/runs/<task>/`，避免第三方内核全局resume唤醒未选择任务；主项目仍保存对话/任务/输入/来源。备份需保留整个项目，不可只拷主SQLite。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_scheduling.py -v
# 复用8767临时夹具
.venv/bin/python -B tests/e2e/browser_workbench_scheduling.py
```

当前4打开项目host、每项目1active、100未完成任务、8缓存运行存储上限有明确拒绝/回收规则，详见契约和ADR0002，不承诺无限并发。

## 模拟独立外部作业

[#12 模拟执行器](simulated-external-jobs.md) 使用回环假服务和独立SQLite保存稳定请求/job身份。真实HTTP演练接受后回执丢失、Node中断后先对账、无查询能力等待决定、结果回队，以及本机暂停/退出不取消独立作业。仅人工文本，不连接真实科学远端。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_external.py -v
# 复用8767临时夹具
.venv/bin/python -B tests/e2e/browser_workbench_external.py
```

应用数据旁 `simulated-executor.sqlite3` 是独立验证服务的状态，不属于真实科研项目结果；它不会在退出时删除或自动取消作业。任务面板有明显模拟标记，公开请求不能指定任意端点。

## 显式 ProteinFactory 远端

[#13 远端科学契约](proteinfactory-remote.md) 区分模型 provider 与科学上传授权；专项远端复用原传输/校验/导出。超时/断线/中断保留结果未知，先核对本机记录，无已验证查询接口时等待明确决定；不自动回退或重提。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_remote.py -v
# 专用8767夹具，只有人工回环响应（不要与普通夹具同时运行）
.venv/bin/python -B tests/e2e/fixtures/remote_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_remote.py
```

专用夹具验证实际上传、产物、unknown和明确重试；普通工作台夹具把新科学传输指向回环拒绝端口，避免误触真实服务。`outputs/ui/remote-science/` 不提交。真实科学服务调用不在本次自动化授权中。

## 模型配置与安全凭据

[#14 模型配置契约](model-configuration.md) 提供应用级设置、明确 Responses/Messages 协议与自定义端点、SilicoLab 独立 Keychain 命名空间，以及对话模型选择。默认不联网、未检查端点标未验证，key不进入项目或提示词；不导入其他软件认证。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_model_configuration.py -v
# 专用8767双协议人工端点夹具
.venv/bin/python -B tests/e2e/fixtures/model_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_models.py
```

自动化仅使用人工key、临时注入库和回环服务；另有macOS Keychain随机人工条目的增删读写验证。不能据此宣称真实provider或完整分发已验收。

## 请求边界模型切换、用量与有限重试

[#15 请求契约](model-requests.md) 在当前请求/工具不中断的情况下为下一实际请求选择接收方，保留必要历史并按请求记录真实来源、用量及未知价格。断流/临时网络/429有限退避重试，失败停放且明确恢复不重复完成工具，无费用预算自动暂停。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_model_requests.py -v
.venv/bin/python -B tests/e2e/fixtures/model_requests_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_model_requests.py
```

## Skills 资源目录与按需读取

[#17 资源契约](skill-resources.md) 公开固定约定roots、frontmatter子集、同名优先级与不兼容规则。左侧技能资源与Node实际read_skill工具共用目录，初始只有描述、正文按需，加载记录包含真实来源/哈希；文字不增加任务权限。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_skill_resources.py -v
.venv/bin/python -B tests/e2e/fixtures/skills_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_skills.py
```

单测app_fixture与浏览器夹具显式注入空或人工skill roots，不能依赖个人资源；正式默认发现路径见契约，不读取其他agent认证或模型设置。

## 项目目录离线与重新定位

[#19 目录可用性契约](project-availability.md) 在移动、断开或不可写时停止受影响宿主，不创建替代项目；界面明确最新进度未确认保存。用户重新定位需核对UUID、固定输入和产物，仍逐项恢复；移除仅取消应用关联，保留目录。

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_project_availability.py -v
# 普通8767工作台夹具
.venv/bin/python -B tests/e2e/browser_workbench_availability.py
```

## 常规检查

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend test
npm --prefix frontend run build
```

后端 98 项检查包含人工表格、引擎离线运行、最少改动搜索、历史删除、队列取消、资源和产品身份验证。安装 desktop 依赖后可覆盖原生桥测试，否则仅该项跳过。人工回归样例放在 `backend/tests/fixtures/`，不需要 research 或用户表格。

## 智能体宿主的独立工程验证

[pi-durable 最小宿主与恢复实验](../tools/runtime-probe/README.md) 对应 GitHub #2，不接入正式应用，也不使用真实模型、科学远端或认证。它独立锁定 npm 依赖，测试通过实际子进程和临时 SQLite 验收，不依赖本地调研目录。

```bash
npm --prefix tools/runtime-probe ci --ignore-scripts --no-audit --no-fund
npm --prefix tools/runtime-probe run verify
```

该工具实际验证 Node 24.16.0、macOS 本地 POSIX owner lease 和 Python 3；更低 Node 版本、其他系统、后台和原生分发尚未验证。生成数据库/文件使用临时目录，依赖目录由 `node_modules/` 规则排除；源码、锁文件、人工测试与说明保留。版本差异、实验矩阵和后续限制详见工具文档。

## 受限 Python 的独立工程验证

[macOS Python 边界实验](../tools/python-probe/README.md) 对应 GitHub #3，使用系统 Seatbelt deny-default 策略运行人工分析，实际测试文件、网络、凭据、安装与停止行为。默认只允许单进程，禁止派生进程，不改动正式应用。

```bash
.venv/bin/python -B tools/python-probe/verify.py
```

需由宿主预装工具目录 requirements 中的固定库版本；实验不自行安装依赖、不继承模型认证、不联网外部服务，也不依赖调研目录。`sandbox-exec` 已被 Apple 弃用，本机通过不等于已完成签名、公证、随包 Python 和其他系统兼容；生产生成代码执行仍受分发验收门槛约束。全部临时输入、策略、日志和产物在系统临时目录，必要源码、人工测试及说明保留。

## 浏览器流程

使用 Playwright 和本机 Chrome；夹具仅监听 8766，使用临时数据库。每组测试启动一个全新的夹具，在另一个终端运行对应脚本，完成后停止夹具。

| 夹具 | 流程脚本 |
|---|---|
| `tests/e2e/fixtures/ui_fixture.py` | `tests/e2e/browser_states.py` |
| `tests/e2e/fixtures/ui_fixture.py` | `tests/e2e/browser_tables.py` |
| `tests/e2e/fixtures/ui_local_fixture.py` | `tests/e2e/browser_local_engine.py` |
| `tests/e2e/fixtures/ui_delete_fixture.py` | `tests/e2e/browser_history_delete.py` |

```bash
# 终端一
.venv/bin/python tests/e2e/fixtures/ui_local_fixture.py
# 终端二
.venv/bin/python tests/e2e/browser_local_engine.py
```

本地引擎夹具拦截并统计后端外部调用；其他夹具使用确定性的替代计算。浏览器产物写入 `outputs/ui/`。`browser_e2e.py` 面向生产服务，会向远端提交两条人工序列，不能当作离线检查自动运行。

## 代码入口

```bash
# 本地离线编码
.venv/bin/python -m silicolab.features.codon.local -i examples/proteins.fasta --avoid GAATTC,GGTCTC -o outputs/local.fasta
# 远端命令行帮助；实际优化会提交序列
.venv/bin/python -m silicolab.features.codon.client --help
```

也可使用虚拟环境中的 `silicolab`、`silicolab-codon`、`silicolab-codon-local` 命令。桌面源码入口为 `python -m silicolab.desktop`。

## 本地数据与调研

`data/` 是实际运行数据库；测试应使用临时数据库，不把它当缓存删除。`outputs/` 放日志和临时输出，`build/` 放构建中间文件；`release/` 放最终安装包。research 是本地材料，不参与正式运行和构建。`.gitignore` 已排除上述本地材料、本机环境、缓存、数据库和生成产物；正式源码、依赖配置与锁文件、测试、打包源资源和文档应提交。首次提交前仍需检查候选文件内容，忽略规则不能替代敏感信息审查。
