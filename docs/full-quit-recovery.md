# 完全退出、所有者回收与逐项恢复

对应 [Issue #21](https://github.com/devxia/SilicoLab/issues/21)。延续#20真实关窗与完全退出的区别，覆盖已授权模型、生成脚本、多项目排队/等待以及独立假作业；只用人工数据/模型/服务，不操作用户其他进程或重启机器。

## 确认退出不等于点击成功

完全退出走既有有令牌后台退出操作：后台停止模型/工具准入，关闭所有任务内核，科学监督器回收沙箱Python，项目SQLite保留未完成检查点。确认后台owner lease释放后才承认服务停止。源码`--quit`还等待GUI lease释放，重复发送真实NSWindow关闭指令直到结束；未释放返回失败，不按陈旧PID强杀或显示已确认完成。原生桥/菜单/应用终止仍走已确认服务停止后的窗口销毁路径。

关窗只销毁GUI，不停止独立后台；完全退出停止本机执行，不默认取消独立远端效果。原始完成项和固定输入/产物保留；无法停止/落盘不宣称完成，目录离线按#19显示最新保存未确认。

## 重新启动与重启恢复场景

新后台先列项目索引与持久任务，不submit/resume旧工作。主机、Node、科学监督器与脚本PID均结束后，由全新serviceId进程打开相同持久项目，作为**系统重启后恢复场景的进程/持久化演练**；本机未实际OS reboot，不声称OS启动项、睡眠/关机时序或断电零损失已全部验证。关机期间无主动轮询或运行保证。

- 同项目运行/排队任务重开先为paused；必要决定保持原decisionId/status，不自动答复或调用模型。
- 项目顶部「待处理或待选择恢复」列表跨该项目全部对话显示paused/needs_decision/result_unknown/waiting_external/admission_pending。查看按钮携带原conversationId/taskId，核对身份后退出设置/技能视图，待原对话加载后滚动并聚焦所点任务卡；同一对话多个恢复项也可分别定位。不恢复、不新建替代会话。
- 用户在原任务卡逐项选择恢复；同项目仍FIFO/单主动执行，不恢复未选其他任务。只重开界面/刷新/查看恢复列表不改变请求计数。
- 恢复先核对固定输入及登记完成产物。完成步骤按输入/完整参数身份和哈希复用，未完成本机工具整步重新执行脚本，不从任意行/内存继续。输入/版本/目录改变继续按既有契约阻断并等待。
- 科学外部效果未知先核对，恢复本机任务不产生重提许可。明确决定通过原身份提交，重复答复/恢复不重做完成效果。

## 独立作业的证据边界

`test_full_quit_recovery`显式启动第三个进程的回环`SimulatedExecutor`，测试专用后台工厂仅接入其已知人工地址，`close()`不拥有或停止它；不是把GUI内存假状态当作独立计算。

两个人工job各提交一次：暂停一个、完全退出后台，外部进程仍存活；短job之后实际核对为succeeded，长job仍running。重开新后台对账取回同jobId/内容，不增加submit_attempts；只有用户明确external/cancel才确认cancelled。产品未新增自动发现/启动任意外部命令入口，不凭该假服务的幂等语义推断实际服务。

## 可重复验证

前提：已构建#3独立分析运行时（不自动安装分析依赖）。

```bash
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_full_quit_recovery.py -v
.venv/bin/python -B tests/e2e/browser_workbench_full_quit.py
.desktop-venv/bin/python -B tests/e2e/native_full_quit.py
```

两项真实进程/HTTP契约覆盖：

1. A项目生成分析运行+队列、B项目等待用户；退出后真实sandbox/Node PID消失、模型计数停止；新service只读打开，原task/input/decision不变，选择一个队列任务只执行该项，分析与等待不动；再明确恢复原分析得到已核验summary，重复resume不重做。
2. 第三进程外部假job在暂停/退出后保持运行/完成，重开对账不重复提交，明确取消才改变状态。

真实Cocoa/Quartz/WKWebView原生流程在非首个对话运行脚本时，通过正常`--quit`完全退出，核对窗口/GUI/后台/Node/脚本回收；重开准确附着同对话和paused任务，无自动执行；只选队列任务继续，另一项目原决定保留。连续运行两次通过。浏览器另验证跨对话恢复列表、从设置/技能页查看原问题、同对话多个task分别聚焦、刷新及查看不增加请求、逐项恢复不唤醒他项，截图在忽略的`outputs/ui/full-quit/`；原生JSON在`outputs/native/full-quit/`。

测试创建的人工Keychain条目按精确UUID删除，空skill roots，无真实模型/科研/计费服务。最终签名公证安装包内同矩阵仍属#25；本票不扩大为任意进程树、其他CPU/系统或断电零丢失承诺。
