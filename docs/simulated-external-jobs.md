# 模拟独立外部作业与结果未知

对应 [Issue #12](https://github.com/devxia/SilicoLab/issues/12)。只运行本机假作业服务和人工文本，不连接真实集群、GPU、ProteinFactory 或科学计算程序。模拟文本计数不能宣传为科研计算或真实外部系统的 exactly-once 保证。

## 独立持久身份

服务只监听宿主配置的127.0.0.1随机端口，用应用索引旁的 `simulated-executor.sqlite3` 独立保存 serviceId、requestKey、jobId、输入字节SHA-256、提交次数、状态和到期时间。Node不能由模型/客户端任意指定端点，校验服务、请求、作业和内容身份。服务关闭不删除作业，重开仍可核对。

项目任务先保存稳定requestKey（由任务UUID生成）、serviceId、payloadHash，再通过真实本机HTTP提交。假服务的唯一requestKey与payloadHash约束使显式相同身份重试返回同一业务作业；这仅是该夹具已验证的幂等能力，不推断真实科学服务具有相同接口或语义。

## 提交、等待与队列

模拟提交按项目FIFO准入。回执保存后任务进入 `waiting_external` 并释放主动位置，没有模型调用或循环轮询。查回成功产物后，结果回到项目队尾，核对requestKey/jobId/serviceId/payloadHash及实际输入，再落盘到任务/尝试独立输出目录。下载再次核验登记哈希。

模拟模式支持正常回执、接受后丢失回执、接受后延迟回执。服务已持久接受而agent尚无jobId时终止Node，重开必须保存 `result_unknown`，外部状态也为 `unknown` 并保留原因/稳定身份，不自动重提或臆断未执行。明确对账能找回同一作业，提交计数不增加。

已知 `not_submitted` 的排队请求在暂停/应用重开后明确恢复，直接回到队尾首次准入，不查询不存在的回执或产生虚假结果未知。排队但尚未发送的请求独立取消，会撤销准入且不创建外部作业。

## 未知状态与必要决定

对账HTTP失败、无查询能力、无法找到作业或取消无法确认时，保留已知jobId/requestKey/serviceId/hash，保存 `externalJob.state=unknown` 与原因；任务显示结果未知或持久待决定问题，不继续显示旧确定状态。

无查询能力时保存一个稳定 `external_retry` 决定：

- **保留结果未知**：不重提、不增加业务作业；重复核对/答复保持已有记录。
- **明确按同一身份重试模拟回执**：只对该已验证支持幂等的假服务开放。答复持久保存，再由明确continue消费一次重试许可；重复答复/continue不重复业务作业。不取得真实科学远端或任意工具权限。

科学真实服务没有查询能力时不可照搬这个重试保证。效果/回执保存不是跨系统原子事务，未知必须如实显示。

## 暂停、取消和终态

本机pause/cancel/应用关闭不会默认取消独立作业。pause仅暂停跟踪/本机继续；本机cancel是本任务终结，后续对账不会复活它或重新入队。界面不再提供本机已取消任务的继续核对按钮，但仍可明确独立取消远端作业。

独立 `external/cancel` 调用服务并核验实际状态：确认cancelled才显示取消；已成功则保留succeeded和本机已完成结果，不能改写为撤销或重复生成产物。请求异常/known=false则提交持久unknown及错误，不能只显示点击成功或原running状态。独立作业的不确定性与本机生命周期分开：原本已取消或已完成的本机任务保留终态，仅更新外部unknown及原因，不重新开放准入或丢弃成功结果。

## 应用interface

路径基于 `/api/workbench/projects/<project>`：

| 操作 | 契约 |
|---|---|
| POST `tasks` | workflow=simulated_external、authorizedTools=[simulated_external]及人工simulation参数 |
| POST `tasks/<task>/external/reconcile` | 明确查找并核对同一作业，保存等待/未知/结果队列，不自动提交 |
| POST `tasks/<task>/external/cancel` | 明确独立取消，核验cancelled/succeeded/unknown |
| POST普通pause/cancel/resume/continue | 保留本机任务意义，不自动取消外部效果 |
| GET `/api/workbench/simulated-executor` | 仅本机夹具的服务身份/job/提交计数，供验收核对，不是生产远端能力 |

任务UI清楚标注模拟，显示稳定请求、jobId（缺失明确未确认）、服务身份、输入哈希、核对原因及下载。原始夹具输入/数据库/产物与浏览器输出不提交Git。

## 可重复验证

```bash
npm --prefix runtime run typecheck
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_external.py -v
# 8767临时工作台夹具，配合浏览器流程
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_external.py
```

11项真实应用/服务SQLite/HTTP/Node契约覆盖接受与回执之间SIGKILL、同一作业找回且提交一次、等待释放位置/结果回队、应用关闭不取消、显式独立取消、无查询决定/幂等重试/保留未知、未发送项暂停/重开恢复与取消、已成功作业终态不重开、取消/查找服务故障持久unknown并保留身份、本机已取消任务不可复活，以及本机终态→独立取消异常/known=false→作业完成→再次对账仍无执行的组合回归。故障注入在外部假服务适配位置，HTTP和持久化仍实际运行，不删除私人数据或实际凭据。

浏览器验证模拟身份、暂停跟踪不取消、实际结果下载、无查询决定、独立取消确认和刷新记录不丢失；模型请求数保持0。全量科学流程、项目队列、暂停恢复另行回归，模拟通过不能替代真实provider、科学远端和分发门槛。
