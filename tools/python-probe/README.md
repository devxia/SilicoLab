# 受限 Python 的 macOS 边界实验（Issue #3）

对应 [Issue #3](https://github.com/devxia/SilicoLab/issues/3) 与 [首版规格 #1](https://github.com/devxia/SilicoLab/issues/1)。这是独立工程验证，**尚未接入正式应用的生成代码链路**。本票补充的[独立运行时分发验证](../python-runtime/README.md)构建含自带CPython/预装库的ad-hoc Hardened Runtime签名ZIP，删除构建目录后从含Unicode/空格/引号的安装目录重跑16项通过；不代表Developer ID、公证、Gatekeeper或最终产品包验收。所有输入、凭据与监听端均为临时人工夹具；不读取真实认证文件，不向外部服务发送数据。

## 可复现入口

本机已预装匹配版本的库，无需再次安装；从项目根运行：

```bash
.venv/bin/python -B tools/python-probe/verify.py
```

若在新的可信环境复现，先由宿主在沙箱外预装 [requirements.txt](requirements.txt)，再运行同一入口。工具只检查与复制预装库，**不自动安装，不为运行失败放宽策略，也不回退到无沙箱执行**。

入口检查 Python 源码语法、实际依赖版本，运行 16 项实验；任一失败返回非零。全部通过后输出测试数、系统/Python/包版本、解释器和实验源码 SHA-256，以及未验证边界。它只建立系统临时目录并在正常结束后清理，不向仓库写数据库、运行日志、输入或产物，不依赖本地调研目录。

实际验证：macOS **15.7.7 / x86_64**，CPython **3.13.13**（conda-forge 构建），`openpyxl==3.1.5`、`et-xmlfile==2.0.0`。仅这组系统/运行时组合通过，不将它推广为任意 Python、macOS、Apple Silicon 或分发环境已兼容。Python 使用 `Path.is_relative_to`、`dir_fd`、POSIX 资源限制等能力，最低要求 Python 3.10；最低版本未实测。

## 策略与外部接口

[execution.py](execution.py) 提供 `PythonProbe.start(code, inputs=[...])`，返回可 `status()`、`wait(timeout=...)`、`stop()` 和 `artifact(name)` 的分析对象；宿主 `close()` 停止受管运行并清理临时目录。测试使用这些接口，不查询内部进程对象或模拟系统拒绝结果。仅“启动失败”和“预装包符号链接”夹具在真正的 OS/依赖适配位置注入错误。

硬边界来自 macOS **Seatbelt**，通过 `/usr/bin/sandbox-exec` 的 deny-default 策略启动解释器。工作目录、提示词、Python monkeypatch 和环境变量不是隔离依据。

- 只读：选定输入的任务副本、该任务脚本、可信标准库和指定预装包副本、启动需要的系统动态库/设备与根目录本身。标准库内的宿主 `site-packages` 明确拒绝；不开放整个 Python 环境或用户目录。预装包副本在任务外，只读，不跟随包内符号链接。
- 可写：**仅当前任务输出目录的内容**。stdout/stderr 的继承描述符也指向该输出目录；宿主保存并读取原始描述符，不按脚本可替换的路径读取日志。profile、脚本、输入副本、解释器和预装库不能改写。
- 只为 Python 的 `uname` 开放特定系统标识 sysctl；允许全局文件元数据查询以支持动态加载，不宣称文件名、存在性和元数据完全保密。根目录允许读取其目录本身，不是根目录递归读取授权。
- 不授予网络、Mach 服务发现、向宿主发信号、创建硬链接或 fork 权限；只允许 exec 当前解释器。Python 自身 re-exec 可发生，仍是同一 PID 且继承内核策略；shell exec 被拒绝。不能据此运行 shell、pip 或多进程科学库。
- 子进程环境是白名单；HOME/TMPDIR 指向任务输出，PATH 固定为系统目录，启动参数 `-I -S -B` 不加载用户 site、宿主 PYTHONPATH 或启动脚本。`close_fds=True` 防止继承宿主打开的凭据描述符。分析进程不携带模型 key。
- `stop()` 用 SIGKILL 终止真实 PID 并 wait 回收，即使脚本忽略 SIGTERM 或变换进程组；fork/spawn 本身被系统拒绝，所以本策略没有允许的派生进程需要在组外追踪。**这不证明允许子进程时任意进程树能被回收**。
- 使用 10 秒 CPU、单文件 8 MiB、64 描述符限制并禁用 core dump。`wait` 有超时回收；不宣称总磁盘、内存、线程、系统调用或拒绝服务防护已经完整实现。
- 宿主只读出顶层、常规、最多 8 MiB 的产物；用目录 fd、`O_NOFOLLOW`、`O_NONBLOCK`、`fstat` 拒绝符号链接、FIFO、绝对路径和 `../`，避免脚本让未受限宿主代读私人文件。

脚本使用内置 MIME 类型表，避免 openpyxl 隐式读取系统 Apache MIME 配置。添加新的科学库需要重新识别最小文件/动态库/线程需求并执行拒绝实验；不能为导入便利直接允许整个宿主目录。

## 16 项实际验收与结果

| 检查 | 证据与结果 |
|---|---|
| 允许分析 | 固定输入 `[1,2,6]`，statistics + openpyxl 生成 JSON/Excel；宿主独立解码得到 count=3、mean=3，输入原件与副本哈希不变 |
| 原件、输入与凭据 | 直接尝试原件/输入副本写入、项目外文件与人工凭据读取，得到 EPERM/EACCES；人工 key/PYTHONPATH 不在脚本环境 |
| 路径别名 | 已存在的输出 symlink 不能越界读写；硬链接、相对路径、目录 fd、父目录写入均拒绝，范围外哨兵不变 |
| 网络 | 对活跃本机 TCP/UDP/Unix listener、IPv6 UDP 和本机 DNS 端口实际尝试；得到权限拒绝而非无服务的 connection refused，监听端未收到数据；不连接公网 |
| 原生调用 | ctypes 直接 libc.open/libc.connect 仍被拒绝，不依赖 Python 层拦截 |
| 派生进程 | os.fork、双重 fork 入口、subprocess、脱离 session、posix_spawn、libc.fork 均拒绝；可用 ctypes，所以 native fork 不是因导入失败而假通过 |
| 停止与关闭 | 忽略 SIGTERM 的 heartbeat 脚本经 stop 后 PID 不存在、输出停止增长；重复停止/关闭可调用；超时同样终止并 wait 回收 |
| 任务互隔 | 当前任务不能读取另一任务产物，不能改写自身脚本、profile、预装库、解释器或控制目录文件 |
| 凭据描述符 | 宿主主动标为可继承的人工凭据 fd 没有进入脚本；不试探真实宿主认证文件 |
| 依赖安装 | pip 不可导入，ensurepip bootstrap、pip 子进程被拒绝，不能写宿主包目录；不实际下载或安装任何包 |
| exec | shell 被拒绝；相同 Python re-exec 后文件、网络限制仍有效 |
| 宿主产物读取 | 脚本创建的 symlink/FIFO、绝对路径和父目录路径被拒绝，不成为宿主越界读取入口 |
| 失败拒绝 | 模拟 sandbox 启动失败直接抛错，无无沙箱回退；下次可重新启动；可信包 materialization 检测 symlink 后拒绝 |

这里“禁止安装依赖”指没有可用的宿主包管理/下载/环境修改路径，并非能分辨脚本输出的一段 Python 代码是不是复制的第三方模块。脚本本来就能写输出和执行 Python；**手写模块、内嵌代码或已有字节不应被误称为系统能够全面识别并阻断的“安装”**。依赖审计仍需正式执行适配层与预装发行环境负责。

## 兼容性、分发与阻断条件

本实验取得了本机内核拒绝证据，并以独立随包CPython 3.13.18取得当前macOS 15.7.7 x86_64手动ZIP/CLI分发运行证据，可以支撑 #16 接入设计；**正式应用仍需接入并验证受管执行后才能开放生成代码**。分发构建/哈希/签名及独立解包入口见 [python-runtime](../python-runtime/README.md)。

- `sandbox-exec` 的本机 man page 和 SDK `sandbox.h` 均明确标为 **DEPRECATED**，Apple 推荐应用使用 App Sandbox。Seatbelt profile 语言也不是稳定的跨版本接口；系统升级可能改变可用性。不能把命令存在或本机通过当作长期分发保证。
- 初始实验使用宿主已装CPython；新增独立分发路线使用公开固定哈希的python-build-standalone CPython 3.13.18与固定openpyxl/et-xmlfile wheel，不含开发机环境或凭据。Mach-O及app以ad-hoc Hardened Runtime签名、深度校验，ZIP解包后独立运行16项通过。没有Developer ID、公证或Gatekeeper认可证据；其他系统/CPU及最终应用集成仍未验，不能据此宣称任意安装方式已兼容。
- 正式 .app 的Developer ID/公证、目标CPU、沙箱权限及正式集成仍须按#25重跑允许/拒绝/停止实验；本票验证的是独立probe app的ad-hoc Hardened Runtime签名分发路径，不把既有产品app打包当作全部边界已验证。
- **缺少 sandbox、依赖版本不符、可信运行时无法按最小权限启动，均阻断执行**。不通过放开网络、扩大任意文件读取、允许 shell 或回退未隔离进程来补救。需要改变权限时须明确决定并重新验证。
- 禁止 fork 的策略有意不支持 multiprocessing、启动外部科学程序或其他可派生进程库；当前只验证单进程 statistics/openpyxl。未来需要进程树时另建经过验证的监督机制，不能仅 killpg 或声称自动继承本项结果。
- 正常 stop/close/timeout 已验，宿主 SIGKILL/系统重启后的自动回收和恢复、崩溃监督器、所有存储故障、线程/内存洪泛与内核漏洞未验。沙箱不是防御被攻陷内核的安全虚拟机。
- 全局元数据读取、必要系统/标准库只读和 stdio 是明确例外。更严格的存在性/元数据保密、完全隐藏 OS 标识或不可信 runtime 不在证据范围。

后续只在对应任务的验收范围内接入该结论；本任务不改变模型提供方规则、科学工具调用授权、现有应用功能或 GitHub 状态。

## 本机来源

- `man sandbox-exec`：弃用状态、`-p` profile 入口及 App Sandbox 建议。
- macOS SDK `sandbox.h`：弃用说明。
- 系统 `system.sb`、`bsd.sb`、`application.sb`：用于了解既有策略词汇，不直接导入宽泛系统 profile。
- [Python subprocess 文档](https://docs.python.org/3/library/subprocess.html)：环境、描述符、等待和超时语义。

实现与测试自身构成可复现实验；不要求其他维护者读取私人调研快照。
