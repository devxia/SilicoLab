# 项目状态版本、完整备份与恢复

对应 [Issue #23](https://github.com/devxia/SilicoLab/issues/23)。操作入口为左侧「项目恢复」，同一应用接口用于自动验收。仅人工项目与回环替代端点，不需要私人项目或真实凭据。

## 格式与升级

项目 `.silicolab/project-format.json` 使用 `format=silicolab-project`、整数 `version=2` 和原项目 UUID。新项目写格式2；没有标记的既有项目按格式1读取。未知新版本、损坏标记或身份不符在启动 Node 前拒绝，不清库、不新建替代项目。

格式1→2是**应用兼容封装升级**，不改写已锁定 pi-durable 1.4.0 的内部 SQLite schema，也不另建存储/智能体内核。升级须用户选择新 ZIP 路径；先取得完整一致的旧状态备份，再原子写格式2标记。标记写入失败保留旧状态和已经成功的回滚 ZIP，可诊断后重试。用户仍能查看旧记录，无需仅为读取被迫升级。

回滚策略：用升级前 ZIP 恢复到现有空目录，再用对应旧版应用重新关联；**不提供原地降级或新版本数据向任意旧版写入的保证**。旧应用本身不了解新封装，不应直接写格式2目录。工具/依赖变化引起的执行不兼容不会靠改标记规避。

## 一致备份

POST `/api/workbench/projects/<id>/backup` 的 `path` 是现有目录中的新 ZIP 文件，拒绝覆盖。活动、排队、等待准入或正在提交的任务须先明确暂停；备份操作不自行取消独立远端作业。应用持有项目 UUID/路径生命周期锁和跨进程 owner lease，关闭 Node、科学监督器及检查点句柄后复制状态，随后释放 lease。界面观察可重开，但不能在快照写入期间创建第二写入者。

备份仅包含工作台管理的 `.silicolab/session.sqlite`、任务 `runs/*/session.sqlite`、导入副本 files、固定 inputs、outputs（脚本、真实结果、来源记录）与版本标记。SQLite 通过只读完整性检查和 backup API 生成已提交快照；不逐个拼接活跃 WAL，不复制 owner.lock/WAL/SHM。无关状态文件或链接/设备/FIFO拒绝，不静默省略未知状态。

ZIP 自带 manifest.json：原UUID、格式版本、每个条目的大小与 SHA-256。上限：10,000个文件、每个128MiB、总512MiB；超限明确拒绝。备份先临时文件、落盘，再无覆盖原子发布。应用 Keychain、模型设置、资源信任、后台令牌与应用索引不属于项目备份；模型选择保存配置ID、实际请求保留来源，不导出key。仅明确内部 `session.sqlite` 与 `runs/<task>/session.sqlite` 做SQLite快照，用户导入/产物即使命名.sqlite仍原字节归档。项目根的用户原件与其他任意文件不在受管理快照中，应另行归档。

## 恢复与位置

POST `/api/workbench/projects/restore`：`archivePath` 为备份 ZIP，`path` 为现有空目录。解析前确认普通文件，验证条目集合/路径、大小/哈希、SQLite完整性和版本，在同父目录临时暂存。启动前核对持久任务UUID，所有目录创建拒绝绝对路径、点段与越界；数据库内的任务字段也不能借合法ZIP文件名越出暂存区。实际 Node 宿主以禁止创建方式核对已提交任务的独立运行库、ExecutionOwner与submission关联，并核对UUID、固定输入与登记产物后才发布 `.silicolab` 并更新关联。坏 ZIP、路径越界、符号链接、内容篡改不覆盖目标或原项目。

恢复保留原项目 UUID；原项目还关联时拒绝另一份同身份副本，须明确停止并移除旧关联。移除保留原目录；恢复不会复制应用凭据。恢复后仍是同一项目、对话、任务与尝试身份，不自动发起模型/工具请求，待决定项原样保留，暂停任务必须逐项选择。

迟到的恢复响应只刷新项目列表与完成提示；用户已切换视图/项目/对话时不抢回焦点或覆盖未存草稿。

## 执行来源兼容

新任务保存 executionContract：实际后端Python实现/完整版本/平台及openpyxl、et-xmlfile、httpx、fastapi、uvicorn已安装版本，以及随包公开 backend/runtime 源码、精确依赖锁与已预装独立分析运行时 inventory 的内容哈希集合，不含本机路径/凭据。工具参数指纹包括该身份；恢复、准入与实际工具执行前核对，工具/脚本环境变更或旧任务来源未知时明确拒绝继续混用旧结果。已完成产物仍可验证、检视、导出；用户须明确建立新任务，不重写旧尝试。该保守门槛也可能在不影响算法的代码变化后要求新任务，不假称所有版本可无损续算。

## 验证

```bash
# 预装独立运行时，不能把缺失时的skip视为验收
python3 -B tools/python-runtime/build.py --output release/PythonBoundaryProbe.app
.venv/bin/python -B -m unittest discover -s backend/tests -p test_project_archives.py -v
npm --prefix runtime run typecheck
npm --prefix frontend run build
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_archives.py
```

`tests/e2e/fixtures/project_archive_previous.py` 从固定公开提交 c6052b4 导出真实旧源码、离线安装锁定npm依赖，使用人工 Responses 端点、D2P本地、实际受限Python构造含对话/已保存草稿/模型选择及来源/固定输入/尝试/脚本环境/科学与分析产物/暂停和待决定项的项目。新版本升级后备份/恢复核对完整条目、关联与原始哈希；旧任务不自动执行，未知环境的明确恢复仍被阻断。独立旧源码夹具需要公开Git历史与预先填充的npm缓存，不依赖research。

13项项目契约另覆盖损坏DB内任务路径、删除运行库/错误owner/submission（即使重算manifest仍拒绝）、用户.sqlite原字节往返、仅实际backend依赖变化时拒绝恢复，以及持有lease期间第二进程打开受拒。浏览器包含延迟恢复响应→选择B并输入未存草稿→释放响应不覆盖的实际反例。

已提交检查点的 `submissionRequestId` 与待准入的 `recoveryRequestId` 分开保存，替换submission时原子更新前者；排队恢复尚未提交新请求时仍核对旧检查点，重开/暂停后备份不误拒合法状态。旧版缺该字段时只接受原请求或已登记恢复请求的实际submission关联，不省略owner/历史核验。

不承诺任意外部进程篡改、远端卷原子性、断电零丢失、任意大小项目、任意未来schema转换或跨版本任意Python中途续算。最后产品包内的路径与独立安装仍归 #25 验收。
