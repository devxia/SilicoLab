# macOS 必要决定系统提醒

对应 [Issue #24](https://github.com/devxia/SilicoLab/issues/24)。系统提醒只是持久待决定项的辅助入口，不是新问题、新对话、任务授权或模型调用。对话/任务卡/项目待处理列表始终使用原 taskId/decisionId。

## 权限与隐私

默认关闭，只有用户在桌面工作台点击「启用系统提醒」才请求macOS权限。关闭会清除本应用已投递/待投递提醒；macOS系统设置也可拒绝/关闭。系统拒绝、原生组件缺失或投递未确认时，原问题仍保存在应用，不循环询问模型，不因通知失败让任务丢失。

通知标题固定为「SilicoLab 需要你的决定」，正文固定为「一个任务已保存待处理问题。打开原任务查看并答复；任务没有自动继续。」仅userInfo包含四个受校验的定位身份(projectId/conversationId/taskId/decisionId)。不发送完整goal、序列、项目/对话名称、问题正文、产物、模型端点或凭据。Swift helper不接受调用方传入任意通知文案。

提醒只观察后台已拥有的项目，不能默默打开所有历史目录占满4个宿主位置。关闭窗口后已拥有的任务可以保存问题并被提醒；完全退出后不执行，重新打开项目仍从持久待处理项查看。来源为真实Node状态，通知不复制另一套决定状态机。

## 真原生边界

`tools/macos-notifications/main.swift` 是独立 `.app` bundle中的有界私有JSONL适配器，调用 `UNUserNotificationCenter`。无shell、模型key或项目路径，父stdin EOF时退出；只接受status/explicit enable/fixed notify/remove/disable/close。用户权限由系统掌握，不通过脚本改TCC/通知设置。

应用后台持有helper进程，退出时清除通知并关闭/等待PID，不留下独立无主执行者。传输EOF、断管或超时会回收失效helper；下次扫描重建连接，只查询既有系统权限，不重新请求授权，也不重复已准入决定。bundle由应用构建阶段预装，缺失或hash/签名不符不回退网页toast。当前构建为ad-hoc Hardened Runtime，**不是Developer ID/公证/Gatekeeper验收**；最终产品包整合归#25。

应用级0600 `notification-state.json` 保存启用与投递身份（不进项目备份）。每个决定先持久化投递准入，再向系统提交，同一decisionId在关窗/重连后不重复提交。崩溃发生在准入与投递之间可能没有提醒；它是advisory，不承诺系统exactly-once或每次送达，应用待处理项仍完整。答复后按至多200项分批清除旧通知；每批成功立即保存，后续批次失败仅重试未清除部分。禁用后重新启用只发送未曾准入的新问题。

## 点击与原任务

只有真实系统 `UNNotificationDefaultActionIdentifier` 回调可以触发选择：后台重核四个身份对应的原pending决定，保存待确认定位，用户点击后才显示/启动真实Cocoa窗口。UI忙碌或保存/读取临时失败时保留目标，每轮从后台读取最新点击，成功核对原项目/对话/任务/决定并切换后才确认删除；已核对为answered的旧决定只清除过期定位，不执行任务。读取失败仍保留后台记录；旧确认不会删除更新的点击目标。UI聚焦原任务卡，不新建会话；通知本身不答复、不grant、不resume。答复仍通过既有决定身份API，重复答复不重复执行，继续遵守原等待/调度接口。

同源本机API(`/api/workbench/notifications` GET/POST及POST `notifications/selection`、`notifications/selection/ack`)继承既有Host/Origin检查，只在独立桌面服务绑定原生控制器；浏览器源码服务不请求通知权限。网页提示不称为系统通知证据。

## 构建与验证

```bash
python3 -B tools/macos-notifications/build.py
.venv/bin/python -B -m unittest discover -s backend/tests -p test_decision_notifications.py -v
npm --prefix frontend run build
.venv/bin/python -B tests/e2e/browser_workbench_notifications.py
# 以下仅在用户明确同意人工通知，并允许SilicoLab系统权限后运行：
.desktop-venv/bin/python -B tests/e2e/native_notifications.py
# 用户手动点击真实系统通知，不答复问题；有180秒上限并自动清理：
.desktop-venv/bin/python -B tests/e2e/native_notification_click.py
```

确定性6项应用契约使用人工center：默认不请求、固定身份/隐私、相同决定不重发、重连、禁用、拒绝仍保留问题、原答复幂等、未知目标拒绝、跨Origin拒绝、不隐式打开历史项目、201项清理中途失败重试、失效连接重建与持久定位确认。浏览器验证忙碌保存、临时保存失败后的同一selection重试、旧决定答复后新点击仍可定位、过期定位清理及原task卡焦点，不代替系统交付。

真实macOS15.7.7 x86_64已在显式用户授权后验证：原生bundle权限granted、系统delivered=1、无自动开窗/焦点变化、等待零模型请求/决定未变、关闭清除/关闭期间新问题不投递/重启用不重发旧问题、helper异常退出后真实重连、去重与PID回收；用户真实点击后打开原非首个对话/同任务同决定，零自动答复与请求。另真实Cocoa UI观察原任务卡拥有焦点。`osascript`辅助功能被拒时没有更改系统权限或伪造点击，改由用户手动点击。系统拒绝的确定性边界测试与真实许可/投递证据分别记录，不将fake中心说成真实拒绝设置已修改。

公开复现脚本只用人工数据，详细本机输出/截图在忽略的 `outputs/native/notifications` 与 `outputs/ui/notifications`，不上传运行配置、任务内容或本机路径。通知横幅/列表是否显示还受系统聚焦模式和用户通知设置影响，不宣称应用能强制覆盖系统策略。
