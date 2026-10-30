# 开发与测试

所有命令从项目根目录执行。要求 Python 3.10+、Node.js 22.12+；打包需要 macOS 和桌面依赖。

## 环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "./backend[test]"
npm --prefix frontend ci
```

Python 的正式依赖和 desktop/test 可选依赖集中在 `backend/pyproject.toml`；requirements 文件是从根目录执行的便捷安装入口。前端配置与锁文件位于 `frontend/`。虚拟环境保留在根目录。

```bash
# 前端热更新（后端在另一个终端启动）
.venv/bin/python -m uvicorn silicolab.server:create_app --factory --host 127.0.0.1 --port 8765
npm --prefix frontend run dev

# 生产界面与浏览器启动
npm --prefix frontend run build
.venv/bin/python -m silicolab
.venv/bin/python -m silicolab --stop
```

## 常规检查

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend test
npm --prefix frontend run build
```

后端 98 项检查包含人工表格、引擎离线运行、最少改动搜索、历史删除、队列取消、资源和产品身份验证。安装 desktop 依赖后可覆盖原生桥测试，否则仅该项跳过。人工回归样例放在 `backend/tests/fixtures/`，不需要 research 或用户表格。

## 智能体宿主的独立工程验证

[pi-durable 最小宿主与恢复实验](../tools/runtime-probe/README.md) 对应 GitHub #2，不接入正式应用，也不使用真实模型、科学远端或认证。它独立锁定 npm 依赖，测试通过实际子进程和临时 SQLite 验收，不依赖本地调研目录。

```bash
npm --prefix tools/runtime-probe ci --ignore-scripts --no-audit --no-fund
npm --prefix tools/runtime-probe run verify
```

该工具实际验证 Node 24.16.0、macOS 本地 POSIX owner lease 和 Python 3；更低 Node 版本、其他系统、后台和原生分发尚未验证。生成数据库/文件使用临时目录，依赖目录由 `node_modules/` 规则排除；源码、锁文件、人工测试与说明保留。版本差异、实验矩阵和后续限制详见工具文档。

## 浏览器流程

使用 Playwright 和本机 Chrome；夹具仅监听 8766，使用临时数据库。每组测试启动一个全新的夹具，在另一个终端运行对应脚本，完成后停止夹具。

| 夹具 | 流程脚本 |
|---|---|
| `tests/e2e/fixtures/ui_fixture.py` | `tests/e2e/browser_states.py` |
| `tests/e2e/fixtures/ui_fixture.py` | `tests/e2e/browser_tables.py` |
| `tests/e2e/fixtures/ui_local_fixture.py` | `tests/e2e/browser_local_engine.py` |
| `tests/e2e/fixtures/ui_delete_fixture.py` | `tests/e2e/browser_history_delete.py` |

```bash
# 终端一
.venv/bin/python tests/e2e/fixtures/ui_local_fixture.py
# 终端二
.venv/bin/python tests/e2e/browser_local_engine.py
```

本地引擎夹具拦截并统计后端外部调用；其他夹具使用确定性的替代计算。浏览器产物写入 `outputs/ui/`。`browser_e2e.py` 面向生产服务，会向远端提交两条人工序列，不能当作离线检查自动运行。

## 代码入口

```bash
# 本地离线编码
.venv/bin/python -m silicolab.features.codon.local -i examples/proteins.fasta --avoid GAATTC,GGTCTC -o outputs/local.fasta
# 远端命令行帮助；实际优化会提交序列
.venv/bin/python -m silicolab.features.codon.client --help
```

也可使用虚拟环境中的 `silicolab`、`silicolab-codon`、`silicolab-codon-local` 命令。桌面源码入口为 `python -m silicolab.desktop`。

## 本地数据与调研

`data/` 是实际运行数据库；测试应使用临时数据库，不把它当缓存删除。`outputs/` 放日志和临时输出，`build/` 放构建中间文件；`release/` 放最终安装包。research 是本地材料，不参与正式运行和构建。`.gitignore` 已排除上述本地材料、本机环境、缓存、数据库和生成产物；正式源码、依赖配置与锁文件、测试、打包源资源和文档应提交。首次提交前仍需检查候选文件内容，忽略规则不能替代敏感信息审查。
