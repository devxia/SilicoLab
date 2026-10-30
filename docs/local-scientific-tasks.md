# 项目型 D2P 本地科学工具闭环

对应 #7，依赖已交付的项目、固定输入与真实内核循环。这里调用已有 `features/codon/engines.py` 的 `run_local`，再用 `client.validate_result` 独立检查；不复制算法、不写旧科学工作台数据库、不通过模型生成 DNA。

## 显式专项授权

任务区提供“D2P 专项 · 本地实验”，用户选择本对话的固定 FASTA 输入、终止符策略和避免位点，明确确认本地模式后发起。支持 `workflow=d2p_local`、`specialtyAcknowledged=true`、授权工具 `d2p_local`。仅写“优化密码子”“反向翻译”不会推断专项授权；普通验证任务只获得 `synthetic_count`，模型看不到专项工具。

工具描述与界面保留适用范围：D2P 无细胞体系、pD2P_1.08t、预设插入位置；**尚未实现载体或插入位置校验**。本地实验不是官方完整算法，不保证表达效果，也不替代其他宿主或载体的通用编码。明确使用 ProteinFactory 科学远端仍由后续单独任务接入，不从本地失败回退。

已有重复 requestId 还会核对专项确认值，确认缺失或与原请求不同也拒绝，不把返回旧任务当作接受不同权限的新请求。

## 结构化执行

1. 工作台任务关联 conversationId、requestId、固定 inputVersionId、参数与专项确认，真实 pi-durable 假模型发起已授权工具。
2. Node 从持久记录取得固定内容并校验完整性，以 JSON 启动当前可信 Python 解释器内的 `silicolab.science_worker`。只执行该固定入口，参数不拼接 shell；不执行模型生成脚本。
3. 科学 worker 清洁环境启动，不继承模型 key，使用 Python audit hook 拒绝 socket/DNS/HTTP 入口。先以实际 socket 创建确认钩子会阻断，再统计业务执行期间的网络尝试，结果记录 self-test=blocked 与 attempts=0。
4. 通过已有 FASTA 解析、输入标准化、终止符和避免位点规范、已有 D2P 本地算法与独立 DNA 校验运行。保留引擎版本、代码/映射指纹、参数、原蛋白、来源 fileId/hash、执行尝试与逐条结果。
5. Node 将通过校验结果的 FASTA、标准合成 Excel 和来源 JSON 写入任务所属项目 `.silicolab/outputs/<task>/<attempt>/`，sync 后保存路径、长度和 SHA-256。下载只接受已保存的 task/attempt/name，不接受任意文件路径，读取时重校验哈希。

支持每任务至多200条、总计200000氨基酸字符，沿用单蛋白10000字符及本地计算预算。无解或单条准备失败记录为失败而非伪造 DNA，保留先前成功条目和对应下载；总量限制在计算任何序列之前核对。终止符存在性记录为 `terminal_stop_present`，是否遵守所选策略记录为 `checks.stop_policy`，不能把 preserve 模式未加终止符误报成校验失败。成功项的独立校验涵盖 DNA 字符、长度、翻译、终止符和正反向避免位点。计算部分失败保留成功条目；更完整的结果工作区由 #8 交付。

Excel 继续只有“基因合成”工作表，“序号、合成名、核酸序列”三列且没有注释；使用原有导出模块。表达效果仍需实验验证。

## 取消与失败

`POST /api/workbench/projects/<project>/tasks/<task>/cancel` 明确取消当前本机任务；Node 的受管 Python 在 AbortSignal 或60秒执行超时时被 SIGKILL，等待进程关闭后返回，不把发送信号当作已回收。应用任务与执行尝试保存 cancelled，错误有持久失败和原因，不自动上传或重复提交。已完成任务取消是幂等观察，不删除产物。

可信科学 worker 本身不创建派生进程。此处不是任意脚本执行边界；**Python audit hook 不是对不可信代码的系统沙箱**。生成代码仍必须经过 #3/#16 的受限执行与分发验收，不能把本工具或其干净环境当作替代。宿主强制终止和多任务恢复仍由各自后续生命周期任务验收。

下载：`GET /api/workbench/projects/<project>/tasks/<task>/artifacts/<attempt>/<declared-name>`，支持 synthesis.fasta、synthesis.xlsx、record.json。列表来自真实任务 ledger；模型答复与科学工具/逐项结果分别显示，不因模型回答结束就自动声称科研完成。

## 可重复验证

```bash
npm --prefix runtime run typecheck
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_science.py -v
# 8767临时工作台服务器，配合 with_server 或两个终端
.venv/bin/python -B tests/e2e/fixtures/workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_science.py
```

人工 MK* / MEFEFK* 得到实际 DNA，独立读取下载验证；无解、未明确确认、普通目标、运行中取消均测试。实际取消观察 Python PID 消失；网络阻断自测、业务请求数0、旧科学队列为空，证明本切片没有远端回退。浏览器查看真实来源/记录/校验并下载解码 Excel/FASTA。测试数据、截图和产物只在临时或忽略的输出目录。