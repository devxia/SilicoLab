# 独立模型配置与凭据边界

对应 [Issue #14](https://github.com/devxia/SilicoLab/issues/14)。本项用人工 key 和回环替代端点验证设置、应用配置、pi-ai、真实 pi-durable 工具循环贯通，不宣称真实 provider 或完整分发已验收。

## 应用配置，不是项目绑定

左侧「模型设置」在没有项目时也可使用。用户填写名称、明确协议、基础地址、模型 ID 和 API key；保存不会访问服务、获取模型目录或读取其他软件账号。元数据位于应用数据库旁 `model-configs.json`，权限0600，原子替换，损坏文件保留并明确报错。新增数据/临时文件已纳入 `.gitignore`；配置不随项目导出。

支持两个明确协议：

- `openai-responses`：pi-ai Responses adapter，标准基础地址 `https://api.openai.com/v1`，请求到 `/v1/responses`。
- `anthropic-messages`：pi-ai Messages adapter，标准基础地址 `https://api.anthropic.com`，SDK 添加 `/v1/messages`。

同协议的自定义端点必须明确选择协议；不从 URL 猜测。除回环 HTTP 外要求 HTTPS；拒绝 URL 认证、查询、片段，不跟随重定向，不静默切换接收方。模型 ID 手动输入，不扫描别的软件模型目录或配置。默认仍是显式本机验证模型，配置后由当前对话选择；项目本身没有 provider 绑定。对话只保存配置 UUID，不保存 key。草稿保存保持该对话选择。

保存后显示「端点未验证」。用户明确点击「检查连接（发送人工文本）」才向所选地址发送固定无科研内容的简短提示，通过 pi-ai 解析终态后记录连接/协议检查时间；这不代表真实 provider 工具循环或跨协议兼容性已全部验收。失败明确提示凭据、网络或协议问题且不切换服务。未经检查也可明确选择使用，但显示未验证。

## Keychain 与请求时数据流

正式密钥存储使用 macOS Security.framework 的 Keychain generic-password，服务命名空间为 `com.silicolab.model-credentials`、account为应用配置UUID。不通过shell或进程参数传key，不写明文key文件，不读取环境模型认证、OAuth、浏览器凭据、其他软件 Keychain 条目或认证文件。不支持的系统明确拒绝安全持久化，不退回明文。

应用在 Python 中读取自己的 Keychain 条目，通过每个Node宿主继承的匿名socketpair提供选定模型的临时凭据。环境只有FD号，普通JSONL宿主请求/响应、项目SQLite、提示词、来源产物不含key；科学监督器/worker不继承模型凭据通道。应用关闭/Node消失时回收通道。连接检查同样仅通过临时stdin传递，不使用命令行key，不保留原始stderr。

Node明确注册应用配置provider，禁用ambient auth lookup。Resolved key仅进入对应协议HTTP认证头，模型消息/工具参数不包含key。HTTP目标受所选origin/path约束，SDK自动重试关闭；异常文案固定，不持久化服务可能回显的认证原文。规范化流事件对当前key作递归脱敏（包含对象属性名、嵌套值及终态）后才交给内核保存。流式部分响应采用中性标签，不把远端标为本机。UI密码框保存即清空，不使用浏览器持久存储。

用户移除模型时删除该应用自己的 Keychain 条目及元数据。历史对话配置UUID保留来源；选择器显示“已移除或不可用（未切换）”并禁用发送，刷新重开保持此状态；应用接口调用同样明确显示缺少配置/凭据并停放，不回退faux或其他端点。当前运行的请求持有已解析凭据，删除不等于撤销该在途请求；停止任务仍走正常取消操作。

## 可验证接口

| 应用操作 | 行为 |
|---|---|
| GET `/api/workbench/model-configs` | 仅返回元数据、hasKey和验证标记，不返回key |
| POST `/api/workbench/model-configs` | 创建明确协议配置并写应用Keychain，默认不联网 |
| POST `/api/workbench/model-configs/<id>/verify` | 仅明确人工连接检查，不发送项目内容 |
| DELETE `/api/workbench/model-configs/<id>` | 删除该应用配置和密钥 |
| PUT `/api/workbench/projects/<p>/conversations/<c>/model` | 对话选配置UUID/null；不修改项目provider，也不触发请求 |

测试通过 `create_app(..., credential_store=...)` **显式注入**内存库；这不是环境开关或生产明文后备。macOS原生契约另外创建、读取、更新并删除 SilicoLab 自己命名空间下的随机人工条目，不检查用户已有凭据。

```bash
npm --prefix runtime run typecheck
.venv/bin/python -B -m unittest discover -s backend/tests -p test_model_configuration.py -v
npm --prefix frontend run build
# 人工两个回环协议服务，配套浏览器
.venv/bin/python -B tests/e2e/fixtures/model_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_models.py
```

应用契约覆盖metadata持久化/key不回传、非法协议/URL、两个协议各自真实HTTP认证头与内核工具调用、服务401回显、工具参数属性名/嵌套属性名回显和不兼容流不泄露、连接检查状态以及Keychain原生生命周期。浏览器覆盖设置保存/清空、未验证提示、显式检查、对话切换两协议、实际工具结果、刷新选择保留及移除当前所选模型后不可用状态；扫描项目目录全部文件（含SQLite）确保人工哨兵不出现。输出在忽略的 `outputs/ui/model-settings/`。

费用/usage展示、请求边界切换、有限重试归 #15；两类真实provider验收归 #22。本项不使用或要求用户提供真实API key，也不将假端点通过解释为真实调用授权。
