# 工作台生成脚本与受限临时分析

对应 [Issue #16](https://github.com/devxia/SilicoLab/issues/16)。采用 #3 已实测的同一Seatbelt single-process边界，非任意shell，不能由skill或模型文字解除限制。首个可独立核验的临时分析为单CSV的`value`列数值摘要；其他格式/算法没有校验器时明确拒绝，不以模型解释冒充完成。D2P/ProteinFactory仍走既有专项工具，不让模型重写已有科学算法。

## 执行链与来源

任务区明确选择固定CSV版本并授权临时分析 → 唯一pi-durable主循环调用`python_analysis(code)` → Node先保存`analysis.py`及SHA-256 → 应用持有的科学监督器直接拥有沙箱进程 → 受限独立CPython实际运行 → 应用按原固定CSV独立计算count/sum/mean并核对实际JSON/Excel → 保存产物/环境/参数/返回码/核验结果。完成、失败与模型答复区分。

`backend/src/silicolab/restricted_python.py`是唯一边界实现；`tools/python-probe/execution.py`仅兼容转发，分发probe直接复制该实现，原16项允许/拒绝/停止行为不另写一套。构建分发验证同样复制这一公开文件。

原生/源码应用只使用宿主预装的独立运行时 `release/PythonBoundaryProbe.app`（冻结包预留`analysis/`资源路径）；缺失时明确阻断，不自动下载、不回退宿主Python。每次执行先核manifest文件哈希、固定3.13.18版本和严格深度codesign。应用制作阶段按#3可信构建入口预装，分析运行时无安装能力：

```bash
python3 -B tools/python-runtime/build.py --output release/PythonBoundaryProbe.app
```

只有人工数据由默认假模型产生固定可检视脚本；已配置模型使用同一真实tool interface生成code，code上限100,000字符。脚本、输入版本、运行时/包版本、参数、执行尝试、stdout/stderr和独立核验记录及产物归属项目尝试目录，旧尝试不覆盖。临时工作目录只在系统临时范围，受限进程不直接写项目。

## 核验与失败

输入严格为一个UTF-8 CSV、仅`value`列、1–10,000个有限数值，不猜测字段。受限过程须写`summary.json`（count/sum/mean）与同头`summary.xlsx`；可信监督器从原固定输入独立核对数值、Excel实际行与输出完整性。sum明确定义为math.fsum，mean定义为statistics.mean；可信核验对原输入独立调用同一定义，避免大尺度抵消时错误判失败。摘要超出有限浮点范围时明确无法核验。浮点比较使用明确小误差容限，不把文件存在或退出码0当作计算正确。

脚本异常、缺文件、数值不符、Excel格式/解压越界、非普通文件、无效参数或运行时不可验证均失败；已经保存的脚本可检视，没有结果不会显示完成。仅允许顶层常规json/xlsx/txt/csv，单文件1MiB、最多20文件、总4MiB；不截断列表假称成功。宿主读取仍通过目录FD+O_NOFOLLOW/O_NONBLOCK/fstat拒绝symlink/FIFO、`../`或绝对路径。Excel先检查解压总8MiB/100entries、条目唯一、UTF-8 XML无DTD/实体/外部关系且总元素不超过10,000；唯一工作表维度、实际行及单元格坐标严格限制2行3列，不允许公式/合并/外部内容。ZIP部件严格限定预装openpyxl生成的九个标准XML/关系部件，内容类型、根关系、workbook关系与实际sheet身份逐项绑定已预检XML；非XML重定向、替代Target、不支持扩展、重复或异命名空间sheets容器均拒绝。同一窄格式XML校验器直接从唯一标准sheet1提取两行三列的标题/有限数值，严格核对标签及位置；样式表结构必须与可信本地生成的默认General模板一致（含隐式样式0），单元格只接受默认样式引用，行样式/隐藏属性也拒绝；日期、比例缩放及自定义数字格式不得把原始数值伪装成另一实际类型；宿主不再把原始不可信ZIP交给openpyxl二次解释，消除宽松命名空间/关系解析差异，且不物化稀疏行列。openpyxl仅用于受限脚本生成及测试方独立核对正常下载。可信record.json与analysis.py名称保留，脚本不得撞名；Node再次拒绝重复产物名。日志检查保留FD的fstat真实大小后再导出，不把status预览的截断值当完整文件，删除/替换日志路径也不能隐藏超限。

## 硬边界与进程回收

延续#3 deny-default：仅可信标准库/预装包、当前输入副本及当前输出可读取；只有当前输出可写；原件、固定输入、脚本、运行时、其他任务/宿主文件及凭据拒绝。默认任意网络、Mach服务、fork/spawn、shell、pip/ensurepip/宿主包修改拒绝。脚本环境白名单、空HOME/TMPDIR指向输出，`-I -S -B`和close_fds隔离模型认证、用户site及继承FD。

应用科学监督器本身持有每个`Analysis`，不是worker再产生无主孙进程；收到取消/Node socket EOF时直接停止沙箱PID并wait。单进程策略已内核拒绝派生进程，不声称任意允许进程树可追踪。25秒wall timeout、10秒CPU、单文件/FD/core限制沿用#3；不承诺内核漏洞、metadata保密或全面内存/磁盘洪泛保护。

暂停实际回收脚本，应用任务存为paused，已保存脚本/完成项不丢。重新打开不执行，用户选择恢复从该未完成工具步骤重新运行整个脚本，不从任意行继续；已完成工具按完整参数/固定输入指纹及产物哈希复用。Node强制终止或应用正常关闭同样回收，重开只列原身份恢复项。科学远端效果未知不受本地分析恢复许可影响。

## 实际验证

```bash
npm --prefix runtime run typecheck
python3 -B tools/python-runtime/build.py --output release/PythonBoundaryProbe.app
.venv/bin/python -B -m unittest discover -s backend/tests -p test_restricted_analysis.py -v
.venv/bin/python -B tools/python-probe/verify.py
.venv/bin/python -B tools/python-runtime/verify_distribution.py
npm --prefix frontend run build
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_analysis.py
```

15项应用契约实际覆盖假模型生成script→独立Python→JSON/Excel核验/下载，恶意脚本访问人工模型key同值范围外哨兵、写输入、活跃回环socket、fork/ensurepip拒绝且env无key，运行异常/无文件/错误数值失败，缺预装runtime阻断，以及pause/NodeSIGKILL/应用close实际PID回收与明确恢复；含超大工作表维度/实际行号（十亿行）、保留记录名冲突、2MiB日志及路径替换仍拒绝超限、关系重定向到未预检部件，以及命名空间别名改指styles仍被拒、显式日期样式与篡改隐式样式0拒绝、大尺度有限数值抵消仍正确核验的实际反例。独立CPython3.11.18可信侧另实测math.fsum/mean与六格提取，两个抵消样例与随包3.13结果一致，不依赖3.12前后内建sum实现差异。测试不读取真实认证或私人科研数据；边界原16项继续复用。运行时集成测试在未预装环境明确skip，**不能将skip视作通过**；发布门槛显式构建独立运行时后在干净源码副本运行这些测试。

浏览器覆盖任务范围说明、固定版本、真实运行、count/sum/mean、独立运行时、实际脚本检视与Excel下载/解析，输出位于忽略的`outputs/ui/restricted-analysis/`。最终产品签名/公证/CPU/安装包及原生全退出矩阵仍须#25/#21各自验收，不把源码集成通过扩大为任意Python/所有科学库或安装包安全保证。
