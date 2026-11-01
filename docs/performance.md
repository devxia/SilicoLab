# 性能与复测

既有基线来自 Intel x86_64、macOS 15.7.7 上的人工测量，原始记录保留在本地 research/performance。以下为历史结果，不表示目录整理后重新执行了完整性能比较。

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| 打包应用可见窗口出现 | 1.536 秒 | 1.122 秒 |
| 源码原生工作台就绪 | 1.830 秒 | 1.376 秒 |
| 红色关闭按钮后退出 | 2.153 秒 | 0.147 秒 |
| 打包应用主进程 RSS | 124.05 MiB | 118.60 MiB |
| 80 条合成大历史的列表读取 | 301.8 ms | 28.4 ms |
| 列表请求 Python 临时分配峰值 | 34.02 MiB | 0.455 MiB |

主要改动是先结束 SSE 再退出、Excel 延迟导入、SQL 摘要索引、收窄原生桥、可取消远端传输及长序列分段渲染。先显示窗口的权衡是打包 API 就绪从 0.882 秒增至 1.066 秒。

这些是本机有限次测量，受缓存和负载影响；RSS 不是物理 footprint，也不应直接累加 WebKit 共享映射。原始报告保留更多方法细节。

0.2.0最终公开CPython安装包在同一机器完成3次新测量：启动窗口与独立后台中位1.490秒，关窗退出GUI中位0.350秒，稳定后GUI约98.5MiB RSS、后台约61MiB，CPU约0.3–0.9%。相较旧单进程手动版，增加独立后台握手及退出确认；未观察到持续空闲高占用。结果限本机3次，RSS仍不是物理footprint；[分发矩阵](distribution-acceptance.md)记录完整方法和边界。

从根目录复测（均使用人工数据，不修改个人历史）。旧工具保留历史测量用途；0.2.0使用`tests/e2e/packaged_performance.py --app release/SilicoLab.app --output outputs/packaged/performance.json`检查新版独立后台生命周期：

```bash
.desktop-venv/bin/python tools/benchmarks/perf_desktop.py --output outputs/perf-native.json --runs 3 --assert-close-below 0.8
.desktop-venv/bin/python tools/benchmarks/perf_bundle.py --app release/SilicoLab.app --output outputs/perf-bundle.json --runs 3
.desktop-venv/bin/python tools/benchmarks/perf_store.py --output outputs/perf-store.json
```

常规回归同时检查列表热路径不解析完整历史、XLSX 按需加载和原生桥的五方法公开面。性能工具不会嵌入分发应用。
