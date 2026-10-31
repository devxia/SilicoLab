# 两类真实 provider 的受控兼容验收

对应 [Issue #22](https://github.com/devxia/SilicoLab/issues/22)。本目录提供复现入口，**存在脚本或回环测试通过不表示真实 provider 已验收**。在用户提供应用配置并明确实际调用范围前，只生成计划，不创建任务或请求模型。

## 人工输入与范围

输入是脚本内固定的 `value\n1\n2\n6\n` CSV。只有受限 `python_analysis` 科学工具；预期真实产物是 `analysis.py`、`summary.json` 和一个工作表两行三列的 `summary.xlsx`，独立期望为 count=3、sum=9、mean=3。科学脚本不联网、不安装依赖，不使用真实科研输入或科学远端。

计划共8项任务：两种协议各做一次分析；各在原对话切换到另一协议引用已完成结果而不重跑Python；两种协议各取消一次正在流式输出的人工请求；两个所选端点各发送一次明确的无效测试key，核对安全认证错误处理。最后两项会向同一实际端点发送固定无效哨兵，临时配置在结束后移除，不删除用户配置。不通过购买额度、故意触发限流或服务故障进行验收。

每项有90秒观察期限，本机API和清理另有超时；观测到本轮20次模型请求即取消当前任务、停止后续任务。观察不是原子HTTP准入限制，不能承诺刚好不超过20次；应用已有瞬态错误最多3次尝试。这个有界人工验收不是产品费用预算或自动跨provider回退。失败或Ctrl-C后先取消活动任务并保存中断记录；创建请求发出前持久保存requestId，响应丢失时按原身份查询并取消，无法核对则明确标未确认，不重新提交。若工具已完成但后续模型请求因接收方变化或其他原因暂停，仍立即结束整轮，不再创建follow-up；产物与失败检查保留。失败后保留记录，不自动重新运行整轮验收。

## 准备应用与计划（不请求模型）

先完成项目常规安装、前端构建，以及 `tools/python-runtime/build.py` 的独立分析运行时。使用新的、无既有项目的人工验收应用目录启动桌面窗口：

```bash
mkdir -p outputs/provider-compatibility/app
SILICOLAB_APP_DATA="$PWD/outputs/provider-compatibility/app" \
  .desktop-venv/bin/python -B -m silicolab.desktop --isolated-resources
```

在该窗口的「模型设置」分别保存一个 OpenAI Responses 和一个 Anthropic Messages 配置。API key只在应用中输入，保存到SilicoLab自己的Keychain命名空间；不要粘贴到聊天、命令行或报告，也不要点击「验证连接」直到实际调用授权到位。脚本不读取环境模型key、其他agent的认证、OAuth或个人项目。若用户单独明确指示复用当前agent配置，可一次性由操作人员把指定provider配置存入专用应用Keychain；这不是产品自动导入功能，不扩展到其他provider、OAuth或任意认证文件，仍须另行确认实际调用范围。

从本应用 `GET /api/workbench/model-configs` 获取两个配置UUID（接口不返回key），随后生成接收方固定的计划：

```bash
.desktop-venv/bin/python -B tools/provider-compatibility/verify.py \
  --app-directory outputs/provider-compatibility/app \
  --responses-config RESPONSES_UUID --messages-config MESSAGES_UUID
```

仅在用户已选择真实本机网关时，为计划与执行两条命令同时添加`--allow-local-gateway`。

默认只输出计划、SHA-256摘要与依赖版本。必须确认两个实际端点、模型、人工数据及上述8项任务范围。协议、配置UUID、端点、模型、应用源码/前端构建、验收脚本或固定提示内容变更都会使原摘要失效。每项验收任务显式携带`acceptanceModel`期望，实际模型请求边界逐次核验；如果窗口同时切到其他配置，会在发送前保存暂停，保留已完成工具。普通产品任务不携带这个验收期望，仍按对话选择自由切换，不把模型绑定到项目或普通任务。默认真实模式拒绝HTTP和回环地址。用户明确选择连接真实上游的本机网关时，可加`--allow-local-gateway`；它进入计划摘要和报告限制，只允许回环HTTP例外，不接受普通远程HTTP。网关通过只证明该网关协议与路由模型，不证明上游供应商或实际模型身份；fixture证据类型不因该参数改变。

## 明确授权后执行

将已确认的计划摘要传入；输出目录必须尚不存在：

```bash
.desktop-venv/bin/python -B tools/provider-compatibility/verify.py \
  --app-directory outputs/provider-compatibility/app \
  --responses-config RESPONSES_UUID --messages-config MESSAGES_UUID \
  --workspace outputs/provider-compatibility/run-001 \
  --approve-plan-sha256 APPROVED_PLAN_SHA256
```

命令参数只是防误触机制，不替代用户实际授权。脚本使用与界面相同的配置、对话、任务、切换、取消、产物及SSE接口；不直写任务数据库。必须使用专用隔离后台和人工空项目索引，不附着用户既有科研项目。结果、脚本及失败现场保存在忽略的输出目录；不把该目录直接提交到公开仓库。

## 已完成前两项或四项后的人工继续

若首轮因报告格式检查误判而停止，先只读核对保存的真实回答与产物，原始报告不覆盖；纠正报告需注明原报告SHA、检查器版本、原因及新增模型请求为0。只有第一项Responses分析和第二项切到Messages都真实通过，才可用`--resume-prefix 纠正报告路径`生成剩余6项计划；若两种协议的分析和双向切换前四项均已完成，则只生成剩余4项控制／错误检查计划。

该参数要求两项或四项前缀具有完整的规定检查字段且每项严格为true（缺失、1、null或false均拒绝）；最终八项汇总使用相同规则并要求场景不缺失、不重复。该参数把完整前缀报告SHA纳入计划摘要；执行前要求专用应用只有原人工项目及对应的原两个或四个已完成任务，再逐项比较原请求来源/时间/用量/执行契约、原回答，并逐对检查同对话、无重复工具及下载产物哈希。任务列表、来源或应用源码变化则拒绝。在用户已授权的剩余范围内执行明确的继续计划，只执行尚未完成6项或4项，原已完成项不调用模型、不重跑Python。它不恢复任意失败任务，也不自动继续原失败验收。

## 如何解读结果

`compatibility-report.json`只导出选定配置的协议／端点／模型、请求身份与时间、真实上报的用量、检查状态、产物名与哈希，以及依赖／脚本版本、backend/runtime/frontend源码摘要和每项任务实际执行契约（含后台Python环境与应用代码身份）。未提交的应用源码变化也会改变摘要。不导出key、原始科研提示、完整对话或脚本正文。

- 流式通过要求同一taskId／modelRequestId仍为running时，从实际应用SSE看到至少两个不同的非空partial；不同请求各一个partial不合并计为流式。仅得到最终正文或声明transport=sse不足以通过。太快而未观测到则明确未通过，不伪装流式证据。
- 科学结果要求真实工具成功、独立数值核验、下载字节哈希、JSON与Excel数值一致，模型解释引用这些结果。解释中的数值按完整数字比较，包括小数和科学计数法，允许结尾Markdown粗体/代码标记；3.7不能因以3开头而通过。
- 切换要求下一任务请求来源准确、原历史条目完整、原工具执行／产物不变、新任务没有重复Python执行，且新模型引用真实历史结果。
- 取消要求已观测在途流式后，实际请求和任务变为cancelled。取消后的用量可能未知，仍原样保留，不填零。
- 认证错误要求实际所选端点拒绝无效key，任务保存暂停，无工具执行、无自动重试或换接收方。还检查任务、历史与观测到的SSE不包含固定无效哨兵或人工原始错误标记，报告只保存是否泄漏，不保存泄漏内容。匿名端点若接受哨兵，此项不会标通过。
- 顶层 `realCompatibilityPassed` 仅在8项全部通过且证据类型为real时为true；单个模型通过不能推广到同协议所有自定义端点。

首次实际运行及尚未通过的项目见[兼容验收状态](../../docs/provider-compatibility.md)。真实结果必须在Issue及后续公开矩阵中单独记录；对私有端点的公开信息需另行审查。缺少key、额度或调用许可时，#22保持未验收，#25依赖门槛保持未通过。

## 本机网关没有认证边界时的补充错误检查

若网关接受任意key，则原`invalid-key`检查保持未通过，不能伪称401/403处理已验证。Issue #22要求核对可安全触发的错误，并明确标注无法实测项；可在已有两类分析／双向切换／取消六项全部通过后，单独批准以下两条不存在模型ID的检查，不重跑科学任务：

```bash
.desktop-venv/bin/python -B tools/provider-compatibility/verify_errors.py \
  --app-directory outputs/provider-compatibility/app-002 \
  --source-report outputs/provider-compatibility/run-002-controls/compatibility-report.json
```

默认仅输出计划。明确实际调用范围后，添加新`--workspace`目录和匹配的`--approve-plan-sha256`。只向已选两个端点发送固定不存在模型ID、人工“只答OK”提示、固定无效key；不会读取真实key。正常应在路由层失败，但不承诺网关不会转发或产生用量，因此仍须明确授权。最多两个任务，各90秒，失败停止；临时配置清理，Ctrl-C／响应丢失按原requestId核对取消。

执行前重核原八个任务、来源、请求、执行契约、科学回答和产物；补充报告绑定原报告SHA和应用／检查器版本。最终兼容判定严格要求原六项全部通过及两类错误均保存paused、1–3次连续编号的error尝试（与应用有限重试契约一致）、零工具、接收方不变、无哨兵泄漏。若第一条已核验，`--resume-error`可绑定该记录摘要，重新核对原九个任务及错误来源后仅执行尚未执行的Messages一条，不重发原错误请求。原始报告不改写，401/403仍明确为未验证；该补充不代表上游服务认证或任意端点已兼容。

## 不联网的开发契约

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -p test_provider_acceptance.py -v
.venv/bin/python -B -m unittest discover -s backend/tests -p test_desktop_service.py -v
```

回环测试运行真实应用、pi-durable、受限Python及8项完整流程，覆盖未授权零副作用、计划接收方变化、报告字段筛选、产物／流式不足不得通过、跨协议复用、取消、回显认证错误、Ctrl-C清理、创建响应丢失后核对取消、接收方在首次/后续请求前变更的拒绝。其报告永久标 `fixture`，不能作为真实 provider 的通过证据。
