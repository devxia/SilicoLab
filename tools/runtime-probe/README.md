# pi-durable 最小宿主与恢复验证（Issue #2）

这是 **独立的工程验证工具，不是已接入应用的智能体**。运行真实 pi-durable、pi-ai 假模型、文件型 SQLite 和独立 worker 进程；所有输入与效果都是人工构造。现有 Python 科学工具、React 界面和 macOS 应用未被接入或更改。

规格：[任务 #2](https://github.com/devxia/SilicoLab/issues/2) · [父规格 #1](https://github.com/devxia/SilicoLab/issues/1)。不需要本地调研目录、API key、其他 agent 配置、科学远端或私人输入。

## 一条验证入口

在项目根目录，先安装锁定依赖（仅此步访问 npm registry）：

```bash
npm --prefix tools/runtime-probe ci --ignore-scripts --no-audit --no-fund
```

然后：

```bash
npm --prefix tools/runtime-probe run verify
```

`verify` 先做 TypeScript 类型检查，再串行运行 14 项独立进程实验；任一步失败返回非零状态，只在全部通过后输出 JSON 摘要，包含实际 Node、SQLite、平台、依赖完整性和锁文件 SHA-256。测试使用系统临时目录，结束后清理；不要给此入口传真实项目目录。默认不写报告或状态到仓库。

测试 worker 只继承 PATH、临时目录和语言设置，不继承 HOME、模型 key 或其他宿主认证变量；仅注册 faux provider，不读取认证存储，不安装通用文件/shell/codemode 工具。**这不是对任意生成代码的隔离证明**，受限 Python 仍需任务 #3 独立验证。

## 已验证环境与依赖

| 项目 | 实际验证 / 限制 |
|---|---|
| OS / CPU | macOS 15.7.7，x86_64 |
| Node / npm | Node 24.16.0 / npm 12.2.0 |
| 本工具 Node 要求 | `>=24.16.0 <25`；由 Node 直接执行可擦除类型的 `.ts`，不依赖全局 TypeScript 或 tsx |
| 发布包声明的 Node 下限 | pi-durable、pi-ai、chord 均声明 `>=22.19.0`；未在该下限版本运行本工具，不将声明当作测试通过 |
| Python | 本机 Python 3.13.13；验证工具的 POSIX owner lease 需要 PATH 中的 Python 3 和 `fcntl`，不是科学计算适配 |
| 核心版本 | `@earendil-works/pi-durable`、`@earendil-works/pi-ai`、`@earendil-works/chord` 均精确固定为 `1.4.0` |
| 类型检查 | TypeScript `5.7.3`、`@types/node` `24.10.0` |
| SQLite | Node 内置 SQLite 3.53.0，经 chord Node adapter 使用；`WAL`、`synchronous=NORMAL` |
| 依赖分发 | npm 正式 tarball，`package-lock.json` 锁定完整传递依赖和 integrity；没有从全局 Pi 安装、源码快照或软链接加载依赖 |

完整依赖和 tarball 完整性见本目录锁文件，不提交 `node_modules/`。单进程正常关闭和 `SIGKILL` 恢复通过，**不代表断电、主机故障、损坏磁盘或任意文件系统零丢失**。仅本机文件系统上的协作宿主受测，不把本地 POSIX advisory lock 推广为网络盘或敌对进程的互斥保证。

## 验收矩阵与实际观察

`test/*.test.mjs` 通过 worker 的同一 JSONL 操作接口提交输入、读取状态和产物；不会直接查询数据库或 mock 内核/存储。人工效果收据与执行尝试由该接口呈现，数据库提交与文件效果仍是两件事。

| 实验 | 正常关闭 | 强制终止 | 实际结果 |
|---|---|---|---|
| 已完成输入、工具结果及人工文件 | 通过 | `SIGKILL` 通过 | 对话身份、提交、transcript 和文件内容保留，重开不请求模型 |
| safe 工具：效果已发生、结果尚未提交 | 通过 | `SIGKILL` 通过 | 重开先暂停；重复 requestId 不启动调度；选择后按原 task/call 身份重做，人工幂等文件不增加 |
| unsafe 工具：效果已发生、结果尚未提交 | 通过 | `SIGKILL` 通过 | 选择恢复后不重跑，写入 `interrupted` 错误结果；文件存在不等于工具成功 |
| 已提交 durable sleep | 通过 | `SIGKILL` 通过 | 重开后即使超过原期限也不执行，选择后同一任务写出一次 wake 记录 |
| 已提交 waiting（等待 durable 子任务） | 通过 | `SIGKILL` 通过 | waiting/checkpoint 持续存在，恢复不新建第二个子任务 |
| 同库第二宿主（包括目录软链接别名） | 通过 | 旧宿主被杀后可重新取得所有权 | 第二宿主在打开 SQLite 前拒绝；原宿主仍可观察；OS lease 随父管道关闭释放 |
| 已完成第一步、后续 unsafe 步骤中断 | — | `SIGKILL` 通过 | 已保存的第一步结果复用，没有再次执行；后续中断保留可检查错误 |
| 在途模型请求中断与 admission 身份 | — | `SIGKILL` 通过 | 重开和重送相同 requestId 都不执行；明确恢复后可能重新发起该请求，输入不重复 |
| 连续 safe 工具崩溃 | — | 3 次 `SIGKILL` 通过 | `restartLimit=3` 到达后可观察到 `restart_limit`，执行尝试停止增加，不自动解锁重试 |

“等待”在这里是内核 waiting/join，不是完整的用户决定工作流（任务 #9）。“done”是内核对模型回答的结算，**不代表科研任务成功**：unsafe 中断后假模型会解释结果未知，但内核回答仍可结算 done。科学任务完成和独立校验由后续切片实现。

## 发布包与同版本源码快照的差异

不能仅凭 `1.4.0` 字样套用此前阅读过的源码接口。实际 tarball 的类型检查和运行实验证实：

- 回调是 `onReport(error, info)`，分类字段为 `info.type`，不是单对象 `onReport(report)`。
- 本包没有 newer source 示例中的 `readOnly` 宿主选项；本实验通过“不调用调度入口 + owner lease”实现可观察的重开暂停，不宣称只读查看器已交付。
- `resume()` **启用整个宿主的调度器**。提交、等待等部分操作也能启动它；观察使用 `inspect()`、transcript 和 `submission.status()`，不调用 `wait()`。已存在的 requestId 先查询并直接返回，避免重复提交顺便启动恢复。
- 被杀死的在途模型请求在选择恢复后可能被重新发起，即使 `retry.maxRetries=0`。这与本次实测 tarball 的恢复机制一致；它不保证模型请求只发生一次，也不证明计费请求幂等。
- 连续崩溃到达 restartLimit 后是 **parked/blocked**，可观察到 `restart_limit`；不是新版源码描述的自动写终结错误。工具不暴露绕过上限的重试命令。

## 宿主操作接口

最小宿主限定 **一个根对话、每库至多一个未结算输入**。这是验证范围，不是正式项目模型；因此选择一个 pending submission 后启动内核调度器不会带起其他未获选择的用户任务。后续多对话工作台需要另外满足逐项恢复，不能直接把全局 `resume()` 暴露给每个恢复按钮。

手工实验仅使用新建临时目录：

```bash
probe_dir="$(mktemp -d)"
node tools/runtime-probe/src/worker.ts "$probe_dir"
```

stdin/stdout 为一行一个 JSON；每次请求带 `id`，返回同一 id 的 `result` 或 `error`；初始输出 `{"ready":true}`。

| `op` | 参数 / 行为 |
|---|---|
| `create` | 取得根对话的持久身份；重开复用 |
| `submit` | `requestId` + `scenario`；只接受人工场景，首次新请求授权本次执行；相同 requestId 返回原提交、不启动恢复 |
| `status` | 返回 scheduling、未完成任务/提交、transcript、人工文件/尝试收据和本进程模型请求数；不执行任务 |
| `resume` | 必须传 `status` 列出的 pending `submissionId`；错误/空选择拒绝，不启动调度 |
| `release` | 传 `scenario`，释放人工阻塞点；本身不启动调度，仅用于实验 |
| `close` | 等待内核正常关闭后释放 owner lease；不 abort/delete 已保存工作 |

scenario：`complete`（直接完成）、`safe`/`unsafe`（效果前后检查点间阻塞）、`sleep`、`waiting`、`sequence`（完成一步后中断下一步）、`model`（模型在途阻塞）。`safe`/`unsafe`/`model` 可通过 release 继续；重开后释放标记不保留。

例如输入：

```json
{"id":1,"op":"submit","requestId":"manual-1","scenario":"safe"}
{"id":2,"op":"status"}
```

取得 response 中的真实 submissionId 后，正常 close 或从另一终端终止该 Node 进程。重新用同一临时目录启动，先 status；明确选择恢复时传回该 submissionId，release 可在其前后发出。自动化测试覆盖这些步骤，不需要手工猜内部数字。

## 后续仍未验证

- Node/Python 科学工具协作、真实 provider/协议、外部作业对账、受限执行和资源发现。
- 用户决定、项目内排队、多对话逐项恢复及多项目调度。
- .app 关窗/退出/后台、打包 Node 与 Python lease helper、升级迁移和备份。
- 存储故障、断电、硬链接/敌对写入者、远程或非 POSIX 文件系统。
- 任意 Python 中途续算、所有外部效果 exactly-once、科学计算真实性或表达效果。

本工具只提供 #2 的可复现实验与版本约束；这些限制不能被后续功能或发布说明写成已经验证。
