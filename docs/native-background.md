# 原生窗口与独立后台生命周期

对应 [Issue #20](https://github.com/devxia/SilicoLab/issues/20)。本阶段只声明已实测的 macOS 15.7.7 x86_64 源码 Cocoa/WKWebView 和人工任务；不将其当作签名公证安装包、实际 provider 或系统重启已验收。

## 两个进程职责

原生 `desktop.py` 是界面与窄本机桥；`desktop_service.py` 为独立后台进程，拥有 FastAPI/应用索引、项目Node宿主与科学监督器。GUI启动以应用自己的元数据/实际状态握手附着，后台启动使用脱离GUI session的子进程与空stdin，不继承模型key或其他软件认证。API不再依附窗口线程。

- `background.lock` 保证同应用数据目录单后台，`background.json` 包含 serviceId、PID、本机随机端口及本机退出令牌；状态握手核对app/serviceId/PID，不把端口存在当作原服务。
- `app.lock` 保证单GUI；重复打开读取应用自己的 `gui-session.json`，通过有令牌的本机控制连接显示现有原生窗口，不产生新API/项目写入者。
- 控制描述符及其`<name>.json.<uuid>.tmp`原子临时文件均有精确忽略规则，权限0600，令牌不暴露给页面或模型，不进入项目；相关文件、WebKit和日志由忽略规则覆盖。退出HTTP需令牌，状态接口不返回令牌。
- 所有工作数据仍在用户项目中；原生界面经窄桥将当前项目/对话UUID写入应用级`workbench-selection.json`（0600），不依赖origin端口；浏览器localStorage仅作浏览器模式偏好。两者不保存凭据或科研内容。重开在真实服务读取相同对话/任务，附着本身不submit、不resume、不创建空会话。

## 真正关闭与明确退出

关闭按钮或“工作台→关闭窗口（后台继续）”实际关闭NSWindow并移除WKWebView、结束GUI事件循环。**不是隐藏DOM、缩小窗口或留下不可见浏览器假装后台**。GUI清理只释放自己的窗口控制/lease，故已授权模型请求和工具在独立后台继续；关闭窗口不标取消。

重新启动同一应用即可开新窗口附着原后台。已有窗口时重复启动只显示原窗口。原生“工作台”菜单、可信页面中的“完全退出 SilicoLab”以及源码 `--quit` 保留明确停止入口；`--close-window` 仅发原生关闭指令，正常启动默认打开/显示界面。macOS Cmd+Q/应用终止委派到明确后台退出操作。退出必须等后台释放owner lease才算确认；握手失败但lease仍被占用代表存活/无响应，所有退出入口报错并保留窗口，不偷换成关窗，也不按陈旧PID任意杀进程。

完全退出与重启逐项恢复的完整矩阵继续由 #21 验收，本项只验证入口存在、服务收到授权退出可回收，以及窗口关闭与完全退出不同；不因入口存在就宣称所有脚本/独立作业/重启语义已通过。

## 失败与重连

原生启动URL的`silicolabDesktop=1`仅是UI等待bridge的非权限标记：在`pywebviewready`及bootstrap完成前只显示连接状态，不展示可选择/创建项目的工作台，不读取浏览器偏好锁定恢复状态；实际本机能力仍由窄桥origin检查保护。可信本机桥报告后台握手状态，原生界面每秒检查连接；丢失显示“任务继续状态未确认”，不是新建空项目。用户可明确“重新连接后台”或重新打开应用：已保存项目/对话UUID选择保持，后台重建后仍从实际项目记录列出恢复项，不自动驱动旧任务。

后台被强制终止时Node的应用owner stdin失去连接，宿主关闭并回收本机执行；新后台打开原项目后未完成任务为paused，需用户明确恢复。已完成任务/工具/产物保持，重连不重复请求。科学远端已发生效果仍按unknown/对账契约，不把本机退出当作远端取消。

## 可复现的真实进程证据

```bash
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_desktop_service.py -v
.desktop-venv/bin/python -B -m unittest discover -s backend/tests -p test_desktop_bridge.py -v
.desktop-venv/bin/python -B tests/e2e/native_window_lifecycle.py
# 常规源码启动/关闭/退出
.desktop-venv/bin/python -B -m silicolab.desktop
.desktop-venv/bin/python -B -m silicolab.desktop --close-window
.desktop-venv/bin/python -B -m silicolab.desktop --quit
```

原生验收建立临时人工应用目录与项目，以Quartz检查真实on-screen Cocoa窗口，测试专用WKWebView夹具只在 `tests/` 中首次准备选择项目及非首个对话；后续重开/后台重建只观察，不自动点击项目掩盖选择丢失，不增设生产任意JS/HTTP执行入口。实际断言：

1. GUI PID与后台PID不同；开始人工文本任务、实际关闭窗口并等待GUI退出，Quartz无其窗口，任务在关闭时间之后才完成。
2. 继续运行与重开均为同serviceId、同项目Node PID、同taskId，2次模型请求、1次工具；WKWebView附着同项目/对话并显示原任务。
3. 重复启动退出0、原GUI仍唯一，后台/Node/工具不重复。
4. 暂停人工后台进程（SIGSTOP）后完全退出返回未确认失败，真实Cocoa窗口仍在；SIGCONT后服务恢复。强制终止人工后台，实际原生界面显示连接丢失且状态未确认；关闭并明确重开后新serviceId/新端口下自动恢复原非首个对话和原任务/工具历史，无代点和重复请求。
5. 延迟bridge ready时，浏览器origin残留选择A、应用窄桥保存B，界面只附着B，原生模式不读写localStorage镜像；人工浏览器回归验证此时序。
6. 独立后台契约另外覆盖拒绝无令牌退出、重复附着身份、人工后台丢失后Node回收与paused恢复项、不自动调用模型。

证据输出位于忽略的 `outputs/native/window-lifecycle/`。全部空/人工技能目录、假模型与人工文本，无真实provider或科学远端，测试清理自己创建的窗口和进程，不操作用户其他应用/项目。正式冻结运行时与签名分发仍归 #25；#3/#16的生成代码门槛未因此放宽。
