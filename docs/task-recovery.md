# 暂停、完成项核对与选择恢复

对应 #10。公开工作台操作暂停真实内核请求和受管科学 Python；暂停不是删除结果、不可恢复取消或科学远端作业取消。

## 状态和协议

- `POST /api/workbench/projects/<project>/tasks/<task>/pause`：先持久保存 `pausing`，关闭当前内核，传播 invocation AbortSignal，等待科学 worker 被终止并回收；应用等待 Node 与监督进程结束后再重开不调度宿主，核对后返回 `paused`。仅数据库改状态不算暂停成功。已结束或已暂停任务幂等返回，不再启动任务。
- `POST .../resume`：用户明确选择一个 paused 任务。核对项目身份、固定输入哈希、已有成功产物 SHA-256 和当前内核工作归属；恢复同一 task/request/submission，不创建另一个执行者。重复点击恢复/重复观察返回已有状态，不重跑完成项。
- 对话和任务面板显示相同持久任务状态、暂停原因和尝试。模型答复、工具完成、暂停和错误分开显示；SSE 可在宿主切换期间重连，观察不承担恢复许可。
- 项目打开/应用重开/Node 强制退出后，原 running/pausing 但未完成的任务列为 paused，原运行尝试保留为 paused；问题等待和已答复待准入各保留原语义。启动不调用 submit/wait/resume，不自动请求模型。

暂停使用内核正常 close 的持久恢复语义，不使用永久 abort 冒充暂停。取消操作仍是独立明确终结语义。当前同项目只准入一个内核运行；#11 将扩展排队和等待释放位置，不能通过全局resume带起未获选择的其他工作。

## 科学进程监督

应用持有独立可信 `science_supervisor`，与 Node 使用继承的本地 socketpair 通信，不开网络监听、不继承模型密钥。监督器启动固定 `science_worker` 入口（无 shell/模型代码），记录实际 PID；取消/Abort 或60秒超时终止 worker，线程 `communicate/wait` 回收后才返回终结响应。

Node 自身 SIGKILL 时连接 EOF，监督器终止并回收其全部受管科学 worker；Python 应用打开新 owner 前等待监督器退出。应用正常关闭也先关闭内核/通道并回收。启动前已经到达的取消有持久于监督器运行期的取消标记，不会再启动遗留请求。

这是可信科学模块的进程归属，不是生成代码沙箱；worker 不派生额外程序。应用进程自身 SIGKILL、系统重启、正式 .app 后台退出/重连与分发仍需后续生命周期验收，本切片不宣称任意崩溃条件完整进程树保证。

## 恢复证据和限制

内核保留已提交 transcript、工具结果、睡眠/等待检查点。已完成工具尝试/产物不改写；若内核在效果已保存但结果未提交的检查点重进受控工具，同一 toolTaskId 已有完成证据时核对产物并复用结果。未完成本机科学步骤恢复时新建 attempt，旧暂停 attempt 保留，不承诺任意 Python 从某行或内存续算。

仅现有无外部效果、任务独立输出的受控本地工具声明 replay-safe。不能以此替代科学远端 request_key/job_id 对账，未来外部效果不明必须先核对，不能直接扩大安全重放。

成功产物被篡改时拒绝恢复，模型请求数/完成尝试不增加；不以重算覆盖损坏来假装核对通过。模型在途请求被正常停止或强制结束后，用户选择恢复可能重新请求，不能保证计费请求只发生一次。达到内核崩溃上限可能停放；恢复前 inspect 发现 `restart_limit` 或其他 blocked 原因时，保留 paused、持久显示原因并返回明确错误，不改成运行中、不自动清除安全上限。

## 验证

```bash
npm --prefix runtime run typecheck
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_recovery.py -v
# 用8767临时夹具配合运行
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_recovery.py
```

六项真实应用/内核/进程测试：已完成工具后暂停在途假模型，恢复完成产物/尝试完全复用；正在执行科学 Python 时暂停并核验 PID 消失，关闭重开保持零新请求，明确恢复重做未完成步骤；Node SIGKILL 时监督器实际回收科学 PID，重开后不执行；整个应用正常关闭同样回收并待选择；已完成产物篡改阻断恢复；同一未完成科学步骤连续三次 Node SIGKILL 达到 restart_limit 后，重复恢复均拒绝、paused与原因保留、模型/尝试数不增。浏览器从对话暂停，在任务面板恢复，刷新保持暂停，确认同一任务与完成尝试无重复。

假模型在最终请求中模拟可取消延迟与流式输出，便于实际观察/暂停，不冒充真实 provider 故障或计费兼容；相应协议与原生分发仍按独立门槛验收。
