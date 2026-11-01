# macOS 0.2.0 打包与分发

首版智能体应用为Intel x86_64，声明最低系统macOS13，实际验收环境为macOS15.7.7。包内包含后端Python、Node/pi-durable/pi-ai、受限分析Python、原生通知helper、前端、本地字体及许可证、证书、科学算法资源和空白Excel模板；无需用户另外安装Node或Python。

## 干净构建

从公开源码创建独立checkout，不复制研究目录、私人输入、凭据、旧venv、运行数据库或本机配置。在该目录运行：

```bash
bash packaging/macos/build.sh
```

构建主机需要Python3.12+（仅用于下载/安全解包启动，版本不足在写入前拒绝）、npm、macOS Command Line Tools及网络访问公开依赖；运行安装包不需要它们。

- `bootstrap.py` 从 `tools/python-runtime/runtime-lock.json` 固定URL和SHA下载公开CPython3.13.18，创建 `.desktop-venv`；已有venv若来自其他Python则明确拒绝，使用新checkout即可。开发者Conda libpython不进入产品。
- `requirements.lock` 固定桌面构建依赖；前端和智能体npm按各自package-lock安装，智能体只安装生产依赖。
- `runtime-lock.json` 固定Node24.16.0 darwin-x64来源及SHA。`prepare.py`准备Node、独立分析Python、通知helper与公开源码身份。
- `SilicoLab.spec` 收集Python模块、元数据、证书和正式资源。内部科学进程使用固定 `--science-supervisor`／`--science-worker local|remote` 入口，不开放通用shell或任意模块执行。
- `finalize.py`将独立运行时放入包内Resources，链接到PyInstaller的Frameworks资源根，分别核验嵌套运行时，再封装顶层签名。清单保存每个实际文件哈希和包内链接。
- 构建产物位于 `release/SilicoLab.app`、`SilicoLab-0.2.0-macOS-x86_64.dmg`、同名ZIP以及`SilicoLab-manifest.json`。

冻结应用忽略外部 `SILICOLAB_NODE`、`SILICOLAB_RUNTIME`、`SILICOLAB_FRONTEND_DIST` 开发覆盖，所有模型/科学执行使用随包运行时。应用配置默认在 `~/Library/Application Support/SilicoLab/`，科研状态在用户选择的项目目录；不会写入应用包。

## 验收与内容审计

安装测试驱动器在开发测试环境运行，目标是实际包内程序。仅使用人工数据、人工key及回环协议端点，真实provider结果引用[#22矩阵](provider-compatibility.md)。

```bash
.desktop-venv/bin/python -B packaging/macos/audit.py \
  --app release/SilicoLab.app --manifest release/SilicoLab-manifest.json \
  --source-root "$PWD" --output outputs/packaged/audit.json
.desktop-venv/bin/python -B tests/e2e/packaged_agent.py \
  --archive /path/to/independent-build/release/SilicoLab-0.2.0-macOS-x86_64.zip \
  --builder-root /path/to/independent-build --output outputs/packaged/agent.json
.desktop-venv/bin/python -B tests/e2e/smoke_bundle.py \
  --app release/SilicoLab.app --output outputs/packaged/manual.json
.desktop-venv/bin/python -B tests/e2e/packaged_ui.py \
  --app release/SilicoLab.app --output outputs/packaged/ui.json
.desktop-venv/bin/python -B tests/e2e/packaged_performance.py \
  --app release/SilicoLab.app --output outputs/packaged/performance.json
.desktop-venv/bin/python -B tests/e2e/packaged_dmg.py \
  --dmg release/SilicoLab-0.2.0-macOS-x86_64.dmg --manifest release/SilicoLab-manifest.json \
  --output outputs/packaged/dmg.json
```

`packaged_ui.py`需要测试环境安装Playwright及Chrome。真正的通知测试`packaged_notifications.py`仅在用户明确同意人工通知并已有系统权限后运行。构建本身不请求通知许可。

验证不只是启动窗口：检查项目/固定输入/本地科学产物/分析脚本、skills/MCP、模型切换、原决定、暂停/恢复、离线与备份，以及真实关窗继续、重开同owner、完全退出停止脚本和逐项恢复。ZIP独立性检查必须提供`--builder-root`指向独立构建目录，验证器会暂时重命名该目录并在finally恢复，从而证明安装程序不读取开发源码；勿将当前会话目录作为该参数。

审计遍历文件、包内链接及解压的冻结Python代码，检查私人目录、运行数据、凭据模式、本机源码/主目录路径、必要资源与模板内容。DMG只读挂载、比对复制后的应用清单、卸载镜像后实际执行；结果见[首版分发矩阵](distribution-acceptance.md)。

## 安装与签名状态

DMG包含应用和Applications链接，可拖入安装；ZIP解压后可移动应用目录。没有自动覆盖已安装应用或删除用户项目。发布产物只保存在本机，不自动上传GitHub Release。

当前为**ad-hoc签名，未Developer ID签名、未Apple公证**。Node、受限分析Python与通知helper各有Hardened Runtime设置，顶层PyInstaller应用不宣称完整Hardened Runtime。`codesign --verify`只证明本机包完整性，不等同Gatekeeper认可。用户安装遇到macOS来源限制时应依据自身系统策略处理；脚本不修改系统安全设置。
