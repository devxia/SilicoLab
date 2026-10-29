# macOS 打包与分发

当前构建为 Intel x86_64，最低系统版本 macOS 13。内置 Python、FastAPI、React、证书、D2P 本地引擎和空白 Excel 模板，使用系统 WebKit。

## 构建

从项目根目录运行：

```bash
bash packaging/macos/build.sh
```

脚本建立或复用 `.desktop-venv/`，安装 `backend[desktop]`，用前端锁文件安装并构建界面，运行 PyInstaller，验证临时签名，再生成 DMG 和 ZIP。依赖来源统一在 `backend/pyproject.toml`。

- 原生入口：`packaging/macos/desktop-entry.py`。
- PyInstaller：`packaging/macos/SilicoLab.spec`。
- 构建中间文件：`build/pyinstaller/`。
- DMG 背景生成文件：`build/dmg/`；图标源文件：`packaging/macos/assets/`。
- 最终产物：`release/SilicoLab.app`、`SilicoLab-0.1.3-macOS-x86_64.dmg` 与同名 ZIP。

只重新生成 DMG：

```bash
bash packaging/macos/create-dmg.sh
```

DMG 保持两个正方圆角框，“图标＋名称”整体居中，箭头提示拖入 Applications；不附加安装说明文件。

分发应用不包含 research、用户输入、数据库、测试结果或个人历史。原生数据写入 Application Support，导出写入 Downloads/SilicoLab；不向应用包内写入数据。正式 Python 资源通过包数据收集，前端构建单独嵌入。

## 验证

```bash
codesign --verify --deep --strict release/SilicoLab.app
.desktop-venv/bin/python tests/e2e/smoke_bundle.py --app release/SilicoLab.app --output outputs/smoke-bundle.json
```

smoke 使用临时工作空间，从项目目录外启动，验证本地计算、单页无注释 Excel、重启保存与删除；不提交远端序列。构建目前只有临时签名，没有 Apple 开发者证书或公证。

安装包留在本机 release；后续可作为 GitHub Release 附件发布，源码提交无需包含它们。本轮目录整理不更改现有已安装应用的位置。
