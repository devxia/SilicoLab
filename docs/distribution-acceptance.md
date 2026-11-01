# 0.2.0 首版安装包验收矩阵

对应 [Issue #25](https://github.com/devxia/SilicoLab/issues/25) 与父规格 #1。以下为最终0.2.0同一份应用及其ZIP/DMG的实际运行结果，不是仅源码测试或UI原型结论。真实provider协议证据来自[#22矩阵](provider-compatibility.md)；本轮没有追加真实付费模型或科学远端调用。

## 包身份

| 产物 | SHA-256 |
|---|---|
| `SilicoLab-0.2.0-macOS-x86_64.zip`（114,378,376字节） | `ba9a51d2f2d4f161e60bce01bd0755ca666b83a8e903de83b3c369f4076e1a19` |
| `SilicoLab-0.2.0-macOS-x86_64.dmg`（119,788,094字节） | `0707b6bacce5e5bdc66523d6e4be13b660ac5ec40e1ddc11c1d07662ceecb8bc` |
| `SilicoLab-manifest.json` | `7bf71c91be2808e6d1da24fd59f98603455408f201ac7765a064c25951eb3325` |
| App文件清单规范JSON内容摘要（有序键、紧凑JSON） | `46daa1594139dce7faddb77cb40c0b278a9e97d87d9d54c943a500883722e0f4` |

包内含14,762个实际文件、65个内部链接。审计扫描文件、压缩归档和1,190个解压的冻结Python模块，未发现项目运行状态、密钥模式、本机源码或主目录路径；空白模板仅一个“基因合成”工作表、三列表头，无数据或注释。ZIP与DMG复制出来的文件哈希均与同一应用清单对应。

## 安装包组成与隔离

使用公开固定哈希的CPython3.13.18建立打包环境，固定桌面依赖版本；不把开发者Conda或venv直接收入产品。应用随包包含Node24.16.0及生产锁定依赖、pi-durable/pi-ai1.4.0、独立受限Python及核验清单、Swift通知helper及清单、后端源码身份、证书、本地DM Sans及许可证、空白Excel模板。分析运行时的独立分发ZIP留在构建产物中，不重复嵌入主应用。

PyInstaller应用资源通过包内Frameworks→Resources链接定位，冻结运行时忽略外部SILICOLAB_NODE/RUNTIME/FRONTEND_DIST覆盖，不回退开发环境。科学监督器和可信科学worker使用固定内部子命令，不将应用可执行文件误当通用Python解释器。生成脚本只进入独立Seatbelt运行时；没有任意模块或`-c`入口。loopback执行器启动不调用主机名／DNS反查。

构建启动要求Python3.12+，不支持时在下载／写入前拒绝；后续子构建统一使用固定公开Python。其余构建依赖、命令与安装步骤见[打包说明](packaging.md)。

## 实际安装矩阵

| 要求 | 复现入口 | 最终0.2.0结果 |
|---|---|---|
| 干净公开源码独立构建、签名完整性、清单审计 | `packaging/macos/build.sh`、`audit.py` | 通过；公开CPython，源码无research/private/config/旧venv |
| ZIP解压后移开构建目录、最小PATH、实际项目与Node | `tests/e2e/packaged_agent.py --builder-root …` | 通过；目录初始化／执行异常均由外层上下文恢复 |
| 本地D2P／独立DNA／单表三列无注释Excel | 同上及`smoke_bundle.py` | 通过；人工MK*→ATGAAGTAA；原手动MEF*→ATGGAATTTTAA |
| 实际受限Python／JSON／Excel／完成证据 | `packaged_agent.py` | 通过；count=3、sum=9、mean=3，独立Python3.13.18 |
| skills渐进读取、受限stdio MCP信任／调用 | `packaged_agent.py` | 通过；真实包内内核和Seatbelt执行人工资源 |
| 两协议选择及切换（安装路径人工端点） | `packaged_agent.py` | 通过；实际provider证据另见#22，不将fixture当实测 |
| 原决定幂等、待决定项跨全退保留 | `packaged_agent.py` | 通过；未选择问题和任务不会自动执行 |
| 真实Cocoa关窗后台继续、重开同owner、重复启动 | `packaged_agent.py` | 通过；确认窗口消失且任务仍running后才释放人工屏障并完成 |
| 完全退出停止Node／脚本、重启零自动执行 | `packaged_agent.py` | 通过；检查原PID消失、服务释放、队列逐项恢复 |
| 原中断脚本明确恢复至完成 | `packaged_agent.py` | 通过；保留旧尝试，新尝试生成正确产物，未选决定仍等待 |
| 完成Python后暂停／恢复，不重复完成步骤 | `packaged_agent.py` | 通过；重复工具请求复用同execution，逐个产物SHA保持 |
| 项目移动离线、核验重定位、非破坏移除、备份恢复 | `packaged_agent.py` | 通过；UUID、任务、固定输入／产物、暂停选择保持 |
| 系统提醒、无自动开窗抢焦点、禁用清除 | `packaged_notifications.py` | 通过；启用前仅status查询已有权限，未授权直接退出；不改变系统设置 |
| A主体+C导航、草稿、键盘、150%缩放、620px窗口 | `packaged_ui.py` | 通过；缩放时实际聚焦/编辑/保存且无页面横向溢出 |
| 80条长序列表格、本地字体及许可证 | `packaged_ui.py` | 通过；仅导入预览不提交，窄窗口不溢出，外部资源请求0 |
| 手动专项、本地计算、结果和删除重启保持 | `smoke_bundle.py` | 通过；真实冻结程序，开发环境覆盖不生效 |
| DMG只读挂载、复制安装、卸载镜像后实际运行 | `packaged_dmg.py` | 通过；复制后应用完整清单相同，手动本地闭环通过 |
| 3次启动／关闭、空闲RSS与CPU | `packaged_performance.py` | 中位启动1.490秒、关闭0.350秒；稳定后GUI约98.5MiB、后台约61MiB，CPU约0.3–0.9% |

包级测试驱动器在包外运行，应用进程只有`/usr/bin:/bin`的PATH，工作目录在项目外，资源覆盖值故意指向不存在位置；ZIP任务验收期间构建目录确实不可访问。测试数据均在临时目录，不触碰用户历史。真实Cocoa另通过可访问性观察选择原项目、非首对话，关闭／重开后原标题及taskId仍可见，模型请求／工具次数不增加；该人工观察与自动API断言分开保留。

历史单进程手动版窗口1.122秒、关闭0.147秒；新版独立后台握手／退出确认增加约0.37秒／0.20秒。RSS为ps指标，不是物理footprint，不把共享映射简单相加。3次短期本机测量不是所有硬件性能保证；没有观察到持续空闲高占用，原历史索引/延迟Excel等性能回归也保留在后端测试。

## 干净源码回归

同一公开CPython构建目录安装独立测试环境后，后端265项OK；标准环境跳过的3项原生桥在桌面环境全部通过。runtime类型检查及5项测试、前端23项测试和生产构建通过。安装矩阵、通知、DMG以及深度审计在最终同一包上执行；静态审查剩余0。开发阶段失败记录保留，未将缺失运行时导致的skip计为功能通过。

## 已修复的构建与验收问题

旧打包缺Node、独立分析Python和通知helper；科学子进程假定通用Python启动。真实安装进一步暴露HTTPServer的DNS反查阻塞、PyInstaller资源根链接及受信任资源规范路径问题，均以失败和对应回归修复。审计检出开发者Conda libpython中的本机路径，因此改为固定公开CPython；没有分发那个早期候选包。

只读双轴审查推动补齐原中断任务resume闭环、完成项复用、关窗在途屏障、缩放真实操作、构建目录必移开、通知已有权限预检、重复ZIP移除及异常清理。测试故障均先复现再修复；审查属于静态证据，不声称reviewer独立重跑了所有检查。

## 分发边界

Intel x86_64、macOS15.7.7实测，声明最低系统13.0但尚未在13.x执行。应用ad-hoc签名；独立分析Python、Node与通知helper另有Hardened Runtime策略。没有Developer ID或Apple公证，不宣称Gatekeeper认可。系统重启恢复以全部管理进程退出后新服务重开验证，没有擅自重启操作系统。

安装产物留在本地release／outputs，不自动创建GitHub Release、部署或追加真实模型/科学远端调用。科研目录、应用配置与Keychain不进入源码或分发包。父规格68条故事与未扩大范围见[逐项映射](agent-v1-acceptance.md)。
