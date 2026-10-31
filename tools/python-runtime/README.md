# 独立随包 Python 的边界分发验证（#3）

此目录是 #3 的独立运行时/分发跟进，不是已开放的产品生成代码功能。复用 [python-probe](../python-probe/README.md) 的16项真实Seatbelt实验，在不含开发环境的ZIP副本中运行，不改agent内核、不回退无沙箱、不扩大权限。

## 精确已验证范围

- 目标：macOS **15.7.7 x86_64**；仅此组合取得证据，非Apple Silicon/任意系统版本。
- 执行器：CPython **3.13.18**，python-build-standalone release **20261026** 的 `x86_64-apple-darwin-install_only`；URL及SHA-256由公开GitHub release asset digest核对后写入 `runtime-lock.json`。
- 预装库：openpyxl **3.1.5** 与 et-xmlfile **2.0.0**，纯Python wheels直接解包到随包site-packages，固定公开PyPI SHA-256；保留runtime LICENSE与wheel dist-info许可/元数据。分析沙箱内依旧不能导入宿主site-packages、安装包或联网。
- 签名：逐个Mach-O + probe `.app` **ad-hoc + Hardened Runtime**，`codesign --verify --deep --strict`通过。**不是Developer ID签名，不公证、不宣称Gatekeeper批准**；验证手动ZIP解包后直接CLI启动，未修改系统Gatekeeper设置。
- 原生C launcher只 `execve` 同bundle CPython与可信验证脚本，固定 `-I -B`、env白名单、无shell。运行时不依赖开发机Python/venv/源码目录。分析子进程仍由Seatbelt和原single-process策略约束。

## 构建和可复现验收

可信构建宿主需macOS x86_64、Python **3.12+**（archive data filter）、Apple Command Line Tools的clang/codesign/ditto、HTTPS访问固定公开资源。构建时下载和解包明确属于应用制作者的预装阶段，**不授予运行中的模型/脚本联网或安装权限**。本机已有依赖不替代固定下载哈希检查。

```bash
# 推荐：从只包含公开源码的临时树重建、签名、ZIP、解包并实际运行
python3 -B tools/python-runtime/verify_distribution.py
# 可选：构建自己的新输出（已存在时拒绝覆盖）
python3 -B tools/python-runtime/build.py --output release/PythonBoundaryProbe.app
release/PythonBoundaryProbe.app/Contents/MacOS/PythonBoundaryProbe
```

`verify_distribution.py`：

1. 只复制 `tools/python-runtime/` 与 `tools/python-probe/` 源码到临时树，不复制research、私有输入、认证、venv或node_modules。
2. 使用hash-pinned公开资源构建，wheel/tar路径检查拒绝绝对路径和`..`，tar使用data filter；下载hash不符直接阻断，不静默换URL/版本。
3. 签名并生成ZIP/外部哈希manifest；解包到含**中文、空格和引号**的目录，深度校验签名后删除整个builder/source/cache。
4. `cwd=/`、空临时HOME、固定env直接启动随包Mach-O launcher，CPython独立执行16项实际实验。初次在中文项目路径下失败的原因是profile的JSON `\u`路径转义，已仅改为UTF-8 literal（`ensure_ascii=False`）；权限未增加，原件/哨兵/网络仍被拒绝。
5. 输出无本机路径的JSON证据到忽略的 `outputs/python-runtime/distribution.json`；包含archive/executable/source SHA-256、OS/CPU/Python/包版本、签名真实状态与限制。任一实验失败非零。

默认构建缓存位于忽略的 `build/python-runtime-downloads/`，签名app、ZIP及manifest位于 `release/`。必要源码、锁文件与人工测试保留Git，不上传25MB运行时或实验输出。zip是此实验的分发证据，不自动发布GitHub Release或最终安装包。

## 16项结果与门槛

独立解包副本完整运行：statistics/openpyxl允许分析并独立读取JSON/Excel；原件/任务输入/项目外/人工凭据拒绝；符号链接、硬链接、dirfd、跨任务产物拒绝；活跃回环IPv4/IPv6/UDP/DNS/Unix及ctypes libc.connect拒绝；fork/spawn/native fork/shell exec/ensurepip拒绝；Python re-exec保限制；忽略SIGTERM脚本经stop/timeout/close回收；宿主安全读取拒绝symlink/FIFO；依赖symlink/沙箱启动失败阻断，无fallback。

通过的是受控单进程hard boundary与可移动分发运行路径，**不承诺**总磁盘/内存/线程洪泛、内核漏洞、metadata存在性保密、任意进程树、其他CPU/系统或任意存储故障。OS/可信stdlib、指定包与输入的只读、全局metadata和输出stdio是原实验已公开例外。

下一步 #16 将边界接到工作台生成脚本任务，必须另验应用监督器、宿主崩溃回收、输入/脚本/依赖/参数来源及暂停选择恢复；#18对任意MCP进程的权限不能自动沿用该Python结果。#25最终产品包独立运行、签名/公证真实状态仍须自己的证据。缺失sandbox、运行时hash/版本不符或新环境无法最小权限启动时仍阻断，不恢复宿主任意shell。
