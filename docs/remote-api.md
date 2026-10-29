# API 提取记录

## 1. 证据来源

目标页面：[Customize](https://www.ourproteinfactory.com/Customize)，Amino Acid (Codon to optimize) 选项卡。

直接读取已打开页面的脚本地址及不含身份信息的内联逻辑，随后通过普通 HTTPS 获取公开 JavaScript。未导出登录会话。

| 来源 | 本次获取版本中的定位 | 结论 |
|---|---|---|
| [`/js/mmz_condon.js`](https://www.ourproteinfactory.com/js/mmz_condon.js) | `mmzGetData()`，约 601–651 行 | `axios.post('/toDnaAjaxCodon', {...})`，6 个请求字段 |
| 同一文件 | 约 617–640 行 | 避免位点取当前行，默认物种 `D2P(default)`；特殊位点展开 |
| 同一文件 | 约 645–730 行 | 结果字段 `seq`、`data`、`log_id`、`success`、`msg` |
| Customize 内联 `jumpajs()` | `const jumpName='pep'` | 氨基酸模式的类型标识 |
| Customize 内联 `jump1()` | `const jumpName='nucl'` | DNA 模式的类型标识；本客户端不提供 DNA 输入 |
| 同一公开脚本 `getSecies()` | 约 3–15 行 | `GET /getSpeciesName` |

行号仅定位本次获取的前端文件，网站更新后可能漂移。源码同时存在旧的 `$.post('toDnaAjaxCodon', {fn, sequenceAmino, ...})` 分支；本实现采用当前优化按钮路径的 JSON 版本，并已在线验证，不混用旧字段。

## 2. 氨基酸 → 优化 DNA

```http
POST /toDnaAjaxCodon HTTP/1.1
Host: www.ourproteinfactory.com
Content-Type: application/json
Accept: application/json
```

```json
{
  "fileName": "my_protein",
  "jumpName": "pep",
  "sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ",
  "ignoreCodonQueue": "GAATTC,GGTCTC,CGTCTC",
  "speciesName": "D2P(default)"
}
```

| 字段 | 作用 | 已确认行为 |
|---|---|---|
| `fileName` | 序列名称 | 客户端显式发送，不测试省略行为 |
| `jumpName` | 输入序列类型 | 此选项卡使用 `"pep"` |
| `sequence` | 氨基酸序列 | 实测标准氨基酸和末尾 `*`；不自动增加终止符 |
| `ignoreCodonQueue` | 要避免的核酸位点 | 无约束用空字符串；多个序列用英文逗号分隔 |
| `speciesName` | 目标物种 | 默认 `"D2P(default)"`；其他值从列表接口获取 |
| `userVal` | 前端另行附带的用户标识 | 网页从 localStorage 或邮箱输入读取；本次先传空字符串、再完全省略，均成功。客户端不发送 |

### 响应

首条默认物种实测返回（`data` 在此缩短展示）：

```json
{
  "msg": "Optimization succeeded",
  "log_id": "example-record-id",
  "data": [
    ["ATG", 1.0, "M", true, {"value": ""}],
    ["AAG", 0.46329113924050636, "K", true, {"value": ""}]
  ],
  "success": "1",
  "seq": "ATGAAGACCGCTTACATCGCTAAGCAAAGACAAATCTCTTTCGTTAAGTCTCACTTCTCTAGACAATTGGAAGAAAGATTGGGTTTGATCGAAGTTCAA"
}
```

- `seq`：优化 DNA，客户端使用的主要结果。
- `success`：实测为字符串 `"1"`。网页使用 `== 1` 判断；客户端兼容整数 `1` 和字符串 `"1"`。
- `msg`：服务端提示。
- `log_id`：服务端生成的记录标识；不是 API key。
- `data`：逐密码子明细。根据前端渲染逻辑，各项依次用于密码子文本、柱形图高度比例、氨基酸、位点提示标记及额外信息。**这些语义由 UI 使用方式推断，不应把第二列直接解释为 CAI 或跨宿主可比的科学指标。** 客户端不依赖这些明细做翻译验证。

HTTP 200 但 `success != 1` 应视为未成功。即使成功，仍应独立验证翻译及位点要求，不能只凭返回文案判断。

## 3. 物种列表

```http
GET https://www.ourproteinfactory.com/getSpeciesName
```

响应：

```json
[
  {"speciesName": "Escherichia_coli"},
  {"speciesName": "Chinsese_hamster_ovary(CHO)_cells"},
  {"speciesName": "Pichia_pastoris"},
  {"speciesName": "Saccharomyces_cerevisiae"},
  {"speciesName": "Bacillus_subtilis"},
  {"speciesName": "Clostridium_acetobutylicum"},
  {"speciesName": "Kluyveromyces_lactis"},
  {"speciesName": "Pseudomonas_fluorescens"},
  {"speciesName": "D2P(default)"}
]
```

仅在线测试了默认物种和 `Escherichia_coli` 的优化，不声称其他物种已验证。

## 4. 相关接口：只定位源码，未调用验证

这些不是基本优化所必需，也未集成到客户端。

| 方法与路径 | 前端用途 | 源码中的参数 |
|---|---|---|
| `GET /getReplaceSeq` | 手动替换时获取同义密码子 | `seq`：当前氨基酸；`speciesName` |
| `POST /dnaReoptimize` | 已编辑 DNA 的再次优化 | `jumpName`, `dnaString`, `siteList`, `fileName`, `ignoreCodonQueue`, `sequence`, `speciesName` |
| `GET /saveUserSeq` | 点击复制按钮时保存序列 | `sequence`, `logId`；会写入服务端，不是必要的计算步骤 |
| `GET /condon_api/api/v1/optimize/get_pdf_by_seq` | 导出优化报告 | `seq`, `name`；路径中的 `condon` 是网站原始拼写 |

报告接口将序列放在 URL 中，可能进入访问日志及浏览器历史；长序列也可能触及 URL 长度限制，因此没有将它作为默认输出方式。

尝试获取 `/condon_api/openapi.json` 返回 HTTP 404，本次未找到可用的 OpenAPI 定义；这不证明站点不存在其他文档。

## 5. 在线验证

2026-10-29，本机使用普通 curl / Python urllib，未发送 Cookie 或 Authorization：

| 测试 | 条件 | 结果 |
|---|---|---|
| 第一次匿名优化 | `userVal: ""`，默认物种，33 aa | HTTP 200，`success: "1"`，99 bp |
| 第二次匿名优化 | 完全省略 `userVal`，不带 Referer；大肠杆菌，33 aa + `*`，三个避免位点 | HTTP 200，`success: "1"`，102 bp，末尾终止密码子 `TAA` |
| Python GET | `--list-species` | 获取 9 个物种名称 |
| Python 多 FASTA 第 1 条 | 33 aa，大肠杆菌，`GAATTC,GGTCTC,CGTCTC` | 99 bp，翻译一致，两个方向均无指定位点 |
| Python 多 FASTA 第 2 条 | 22 aa + `*`，大肠杆菌，相同避免位点 | 69 bp，翻译一致，保留终止符，两个方向均无指定位点 |

在线调用均为短测试序列，没有使用用户的科研输入，也没有压力测试。原始响应归档在本地调研区，不作为公开运行依赖；上面的记录标识已替换为示例值。命令行现使用 `python -m silicolab.features.codon.client`，用法见开发文档。

### 离线测试

原独立客户端的 21 项测试已纳入 `backend/tests/test_codon_optimize.py`。从根目录执行 `.venv/bin/python -m unittest discover -s backend/tests -p 'test_codon_optimize.py' -v`，覆盖参数构造、无鉴权请求、输入规范化、FASTA、多条输出、原始响应留存、失败标记、DNA 长度/翻译检查、正向/反向互补位点检查、HTTP/网络失败及非 JSON 响应。

## 6. 未确认事项

- 官方批量调用许可、配额、并发上限、是否计费、服务条款及数据保留策略。
- 匿名调用是否会长期保持可用，或何时可能要求登录。
- 更长序列、所有支持物种、复杂/冲突约束的可靠性与失败响应全貌。
- 优化算法细节、随机性、目标函数与实际表达效果。
- 登录用户的记录归档方式；由于客户端不传身份，不保证结果出现在账号历史中。
