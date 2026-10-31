# MCP 独立资源、来源信任与受控工具

对应 [Issue #18](https://github.com/devxia/SilicoLab/issues/18)。只自动发现独立MCP配置，不读取其他agent的模型/端点/认证，不执行插件或安装依赖。所有验收为人工配置、受限本地脚本和回环HTTP服务，不启动本机已有真实MCP或计费服务。

## 配置方言与优先级

首版只支持独立JSON对象 `{"mcpServers": {"name": {...}}}`。固定来源：项目根`.mcp.json`优先于`~/.config/silicolab/mcp.json`；同一文件按名称排序，首个兼容同名来源胜出，其余shadowed。配置最多256KiB/50项，名称仅ASCII字母数字、下划线、短横1–64字符；符号链接、FIFO/设备等非普通文件、损坏JSON或混合模型认证顶层不兼容；配置/脚本/信任记录均使用NOFOLLOW/NONBLOCK描述符、fstat和有界读取，发现不能被信任前的FIFO阻塞。自动化通过显式`mcp_roots=[]`或人工目录替代用户位置。

支持两种明确transport：

- `{"type":"http","url":"https://example.invalid/mcp"}`：Streamable HTTP MCP端点，回环可HTTP；拒绝URL认证、query/fragment、重定向、代理环境。首版不导入headers/env/apiKey/token，发现此类字段显示needs_configuration，不偷读别的软件凭据。需要认证的资源在本版本不连接，用户需采用已支持、具有明确无凭据边界的端点，不以缺key改接其他服务。
- `{"type":"stdio","command":"silicolab-restricted-python","args":["relative-server.py"]}`：应用保留命令标识，仅指向配置文件目录内一个普通.py文件；脚本上限100,000字符、无路径越界/链接。实际由#3/#16同一独立Python/Seatbelt边界执行，不把字符串传shell。任意node/npx/bash、复杂参数、子进程、安装或环境注入均标不兼容，未执行。

发现只列来源、规范配置、hash和兼容状态，不连接HTTP、不启动进程。信任身份包含规范配置、绝对来源、配置文件内容hash及本地脚本hash；配置/脚本/来源变化后旧信任失效，不把同名等同可信。

## 信任、连接与授权是不同状态

资源面板区分discovered（待信任）、trusted（已确认但未连接）、connecting、callable（已核schema的连接就绪证据）、failed、needs_configuration、shadowed/incompatible。用户确认后，应用级0600 `mcp-trust.json`保存该精确身份，同配置重开仍信任，不逐次普通调用批准。信任文件必须是仅含唯一id/64位小写SHA-256 fingerprint记录的数组；损坏结构与JSON错误统一返回409、保留原件，不覆盖为新信任。

连接及每次工具调用各自是有界MCP会话，结束即关闭；callable表示该来源已成功握手/schema校验，可按任务调用，不代表后台永久持有无限连接。初始化实际发送initialize/协议2025-06-18/空client capabilities，核服务tools能力后notifications/initialized、tools/list；仅支持有界标量对象schema及文本content结果，不接受sampling、roots、elicitation或任意server请求授权。

来源信任不等于任务工具权限。调用必须明确任务`authorizedTools=[mcp_call]`、固定resourceId/fingerprint/tool/arguments；真实pi-durable工具只执行该记录中的来源和参数，不让模型临时改服务地址/工具。列举的schema重新核对，参数按实际schema类型/枚举/限值验证（JSON布尔与数字的enum相等语义严格区分，true不等于1；integer按数值无小数部分判断，1.0可接受，1.5/布尔/非有限值拒绝）；未授权不会启动。首版只接纳声明readOnlyHint的工具，不开放科学提交或副作用工具；**hint不是安全证明**，真实服务仍可能不诚实，来源确认须显示实际数据去向并由用户承担其服务信任，本机硬限制不靠hint。

MCP传输/远端效果不能冒充ProteinFactory专项授权；普通序列任务不进入MCP或科学专项，不自动跨工具回退。工具replay=unsafe，未知断线/取消不自动重提副作用。HTTP取消实际发送notifications/cancelled，但服务可忽略，界面只保证本机等待/连接停止，不宣称独立远端效果已撤销。

## 本地权限与回收实效

本地stdio复用受限Python`interactive=True`：只开有界JSONL stdin，不继承模型FD或key；stdout/stderr是受控临时目录中的保留描述符，单消息64KiB、输出1MiB、请求10秒，stdin非阻塞2秒上限。只读可信stdlib/预装包及脚本，只有当前临时输出可写；任意网络、原件/项目外、宿主凭据、fork/spawn、shell和安装继续Seatbelt拒绝。这里不推断该边界自动保护任意MCP命令，因此不支持的命令一律未执行。

应用科学监督器直接持有该Analysis，调用取消/NodeEOF/应用关闭会kill/wait回收；连接测试同样会关闭本地进程。HTTP不启动本地服务进程，只向已信任URL传初始化与明确工具参数，无模型key/项目目录隐式上传；session header按实际协商，关闭时DELETE（服务不支持时不伪造成功）。SSE增量识别CR/LF/CRLF（含跨chunk CRLF），按空行组装完整事件、合并同事件data字段后解析，匹配响应出现即关闭本次流；HTTP401/403明确标needs_configuration而非笼统失败。超时不自动重试，工具取消通知不取消initialize。同步连接的宿主IPC等待70秒，覆盖本次会话60秒监督上限；若IPC期限或身份校验失败，回收该Node及监督器，不能让迟到回复污染下一操作。

## 应用接口与验证

项目路径基于`/api/workbench/projects/<project>`：GET `resources/mcp`只发现；POST `resources/mcp/<id>/trust`保存来源确认；POST `.../connect`真实握手/schema并记录结果；POST `tasks` workflow=mcp_tool形成可追溯原任务工具调用，结果包含source/fingerprint/tool/arguments/content。本地PID/任务取消与进度来自真实监督器，不是页面假状态。

```bash
npm --prefix runtime run typecheck
# stdio验收前显式预装已验证runtime；不由模型下载安装
python3 -B tools/python-runtime/build.py --output release/PythonBoundaryProbe.app
.venv/bin/python -B -m unittest discover -s backend/tests -p test_mcp_resources.py -v
npm --prefix frontend run build
.venv/bin/python -B tests/e2e/fixtures/mcp_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_mcp.py
```

15项契约覆盖：确认前无连接/启动、同配置信任复用/脚本变化失效、真实stdio schema/结果、HTTP初始化/call/cancel通知、未授权任务拒绝、不兼容command/嵌入认证不导入、同名优先级/重开、schema不符不发tools/call；stdio实际访问存在的范围外人工key同值哨兵、写人工原件、活跃回环listener、fork/ensurepip均拒绝，env无模型key，取消后PID不存在。新增实际反例还覆盖FIFO、布尔/数字枚举、integer数值语义、多行/单独CR/逐字节CRLF的SSE、损坏信任结构保留原件并返回409、两次6秒响应的慢连接、IPC期限失败回收、HTTP401缺配置，以及连接前后同requestId幂等不受瞬态tools/status影响。任务持久化只包含稳定MCP配置字段；连接状态/schema目录属于观察，不进入请求身份比较。浏览器验证状态分离（请求前立即显示connecting）/来源hash/信任后schema/任务授权后实际结果/刷新信任保留，截图在忽略的`outputs/ui/mcp/`。

配置/信任及运行资料不提交Git；公开源码测试不依赖个人MCP目录。其他配置方言、认证流程、复杂schema/资源/prompts/长连接/SSE重放、任意本地二进制进程或所有服务兼容性未宣称实现；不能满足边界的资源明确不兼容，不静默扩大权限。
