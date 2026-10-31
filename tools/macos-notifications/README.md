# SilicoLab 原生通知 helper

`main.swift` 为 #24 的受限原生适配器，不是第二套任务状态机。使用 Cocoa app bundle 身份调用 UserNotifications，只有父进程明确传 `explicitUserEnabled=true` 才请求系统权限。文案固定、userInfo只含校验后的四个身份；没有任意执行、网页toast或自动打开窗口逻辑。

```bash
python3 -B tools/macos-notifications/build.py
```

要求macOS及Command Line Tools的`xcrun swiftc`、`codesign`；不需要完整Xcode。默认创建忽略的`release/SilicoLabNotifications.app`与相邻hash manifest，已有输出拒绝覆盖，不在运行时自动下载/安装/编译。

当前是ad-hoc Hardened Runtime，不是Developer ID、公证或最终分发包验收。权限请求、真实投递和用户点击是另一个显式授权的人工验收步骤，构建本身不请求权限。详见 [通知契约](../../docs/decision-notifications.md)。
