# 真实内核与本机验证模型循环

对应任务 #6。工作台项目对话通过 HTTP → Python 应用模块 → 私有 JSONL → **真实 pi-durable 主循环**执行。Python 仅转发应用操作与状态，不运行另一套 agent loop。当前只注册 pi-ai faux provider，清楚显示“本机验证模型”；没有读取其他 agent 的认证、配置或资源，也不会连接真实模型或科学服务。

## 已交付行为

在对话编辑人工目标后，点击“运行本机验证”，明确授权 `synthetic_count` 受控工具。假模型发起工具，工具按实际 Unicode 字符计数、持久记录执行尝试和进度，写出 JSON 产物及 SHA-256，再由假模型答复。该工具不是通用密码子处理，不进行生物学推断；普通序列目标不会触发 ProteinFactory 或原专项队列。

项目、对话、科研任务 UUID、客户端 requestId、内核 submissionId、tool taskId/callId、执行尝试 UUID 分开保存。相同对话/requestId 重送返回原任务，不再次提交；同一请求身份用于不同目标或授权会拒绝。工具输入摘要、进度、实际结果、产物路径和哈希可检视。

通过应用构造的任务区请求显式专项授权后，可选择 d2p_local 工具调用已有 Python 科学模块；其实际计算、校验、来源和下载契约见 [local-scientific-tasks.md](local-scientific-tasks.md)。普通目标不由假模型关键词推断进入专项，受控科学工具与生成代码执行器分开。

模型答复结算为 `answered`，不是科研任务 `completed`：界面显示“模型已答复”并注明不代表科研计算完成，工具是否完成与实际产物分别展示。真实科学工具和独立校验由 #7/#8 接入。

未授权所需工具时保存 `needs_decision`，不发起模型或执行工具，不把目标文字当作扩大权限的许可。完整决定答复与继续工作流由任务 #9 实施；本切片不暗中猜测决定。

## 观察与重连

- GET `/api/workbench/projects/<id>/conversations/<conversation-id>` 返回全部已提交历史、LiveDoc 流式片段、当前应用任务、执行尝试和实际模型请求数。
- GET 同路径 `/events` 是 SSE，只观察已提交状态；事件 ID 为状态内容 SHA-256，支持 Last-Event-ID 和幂等完整快照。客户端替换状态，不追加重复记录。重连不会调用 submit/wait/resume。
- POST `/api/workbench/projects/<id>/tasks` 是唯一新工作入口，参数含 conversationId/requestId/goal/authorizedTools。当前工具集合仅支持 `synthetic_count`。
- 应用重开只读持久记录，调度器保持 paused；任务恢复与本机暂停在 #10 交付。存在未结算内核提交时拒绝新任务，不能借新输入带起未获选择的旧任务。项目排队/多项目并行由 #11 完成。

SSE 使用本机状态快照转发，持续等待仅针对可见 UI 连接，不循环请求模型；关闭界面会断开观察，不等于取消计算。此处不代表原生后台生命周期已通过，仍需相应任务验收。

## 测试入口

```bash
npm --prefix runtime run typecheck
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_agent.py -v
# 用8767临时夹具运行浏览器验收
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_agent.py
```

人工目标 `ABC` 的实际 JSON 产物为 characters=3；测试核对真实 transcript 工具结果、流式 partial、执行尝试、持久重开、重复 requestId、不足授权拒绝、历史重连和专项队列未被调用。输出目录被普通文件占用时，工具失败与错误会持久保存、内核保留错误结果；刷新/重开不继续显示执行中，也不生成成功产物。浏览器分别在执行中和完成后刷新，成功任务的 POST/执行次数仍为 1，模型调用为 2（工具轮与最终答复），另有独立产物失败用例。截图/结果 JSON 在忽略的 `outputs/ui/agent-loop/`。

不承诺模型请求/外部效果 exactly-once、任意存储故障零丢失，且本切片不是 Python 生成脚本执行器。真实 provider、授权科学远端、模型切换、用量、暂停/恢复、原生后台和分发继续按独立任务验收。