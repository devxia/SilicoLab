# 显式 ProteinFactory 远端与结果未知

对应 [Issue #13](https://github.com/devxia/SilicoLab/issues/13)。这是 D2P 无细胞体系、pD2P_1.08t 与预设插入位置的专项，不是任意宿主/载体的通用反向翻译，也不声称实现载体校验或实验表达保证。

## 来源、授权与传输

任务区将「ProteinFactory · 远端专项」置于本地实验之前；使用 ProteinFactory 的入口明确指向远端，另有「D2P 专项 · 本地实验」。用户选定固定输入、终止符和避免位点，勾选科学上传授权后执行，不再次询问已明确的来源。普通验证消息不会触发专项；显式本地路径仍拒绝网络，不自动回退或升级到远端。

远端任务采用与 #12 相同的项目持久准入/回执路径，不伪造模型答复，也不引入第二个模型循环。`workflow=protein_factory_remote` 需要 `specialtyAcknowledged=true`、`authorizedTools=[protein_factory_remote]`、固定输入版本和明确 preserve/add 策略。缺少工具许可时保存任务级决定，只有明确授权并继续后才执行。模型 provider 的许可不构成科学服务许可。

Node 使用现有应用持有的 socketpair 科学监督器启动可信 Python worker；本地 worker 不继承科学端点，远端 worker 也不继承模型凭据、代理、Cookie 或其他软件配置。Python 复用原有 HTTP transport、FASTA 解析、独立 DNA 校验和 Excel 导出。真实默认地址来自现有 codon client；应用进程可注入 `SILICOLAB_SCIENCE_REMOTE` 和 `SILICOLAB_SCIENCE_REMOTE_TIMEOUT`，模型/HTTP任务参数不能指定端点。超时默认120秒/请求，整个受管 worker 最长300秒；源输入8MiB、响应16MiB、200条序列、总计200,000氨基酸字符有界。显式端点不跟随重定向。

实际上传内容仅包含每条所选蛋白序列、名称、D2P species及避免位点，不上传整个项目、未选择文件或模型认证。来源记录包含实际 endpoint、engine id/version、network_used、请求次数、输入哈希和尝试身份。仅 HTTP 200 不算科研成功：字符、长度、翻译、终止符及双链避免位点均须独立校验。失败项不导出 DNA；成功项导出 FASTA、固定单表「基因合成」三列无注释 Excel，以及含固定输入/原始响应/任务/尝试的 records.zip。

## 效果未知不是失败或未执行

发送前先保存本机尝试和工具执行记录；服务接受后断线、超时、本机暂停/取消、宿主被终止时，请求可能已有远端效果，保存 `result_unknown` 和 `unknown` 尝试，不自动重提。应用持有的监督器在 Node 消失时回收 worker；本机回收不意味着服务端取消。

重开只恢复记录，不执行任何远端请求。此路径没有已验证的 ProteinFactory 查询或取消接口，不臆造接口。用户点击「核对远端请求记录」时检查本机已保存尝试，记录 reconciledAt 和 queryAvailable=false，生成该次尝试的稳定 `science_retry` 决定：

- 保留未知：不请求；重复核对、答复、continue、resume不重提。
- 明确重试：提示**可能重复计算**；先持久保存答复，再由可重试的 continue 按项目队尾消费一次许可。新的未知尝试有自己的新问题，旧问题不能再次授权。尚未发送的已批准重试可暂停或撤回，保留旧请求unknown；重开后只有用户明确恢复才消费尚未使用的批准。重复核对不覆盖已保存的准入交接。

尝试身份只用于本机审计，不推断服务支持幂等，不能沿用 #12 假服务的 exactly-once 语义。若批次中已有成功记录，重试先校验原成功产物和固定输入，仅请求未完成项，旧尝试与产物原样保留，新输出位于独立尝试目录。已成功终态不能被 reconcile/continue 或旧答复重开。网络发送前确定失败（例如非法避免位点）保存failed及零请求依据，不制造可能重复计算的决定。结果区独立显示/计数成功、失败、未知与未发送，不把unknown批次误写为失败。

## 可重复验证与边界

```bash
npm --prefix runtime run typecheck
npm --prefix frontend run build
.venv/bin/python -B -m unittest discover -s backend/tests -p test_workbench_remote.py -v
# 两个终端：人工回环端点与实际浏览器
.venv/bin/python -B tests/e2e/fixtures/remote_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_remote.py
```

10项应用契约覆盖真实 HTTP 传输/独立校验/真实 Excel+FASTA+ZIP、HTTP错误与伪成功DNA、权限与普通请求隔离、接受后断线/真实超时、暂停/取消/重开不重提、SIGKILL回收/unknown恢复，以及保留成功项的明确重试和重复答复/continue幂等；还覆盖排队重试的暂停/撤回/重开后恢复批准、unknown批次成功产物篡改阻断，以及确定未发送的参数失败不误记unknown。浏览器检查上传说明/授权、真实下载、unknown核对/必要决定/明确重试和旧尝试保留。截图与人工输出保存在忽略的 `outputs/ui/remote-science/`。

本次验收只用人工数据与可注入回环端点，没有调用真实 ProteinFactory 或付费模型；不把任务发布当作真实服务调用授权。真实服务兼容性、实际 provider 和签名公证分发仍须各自门槛。
