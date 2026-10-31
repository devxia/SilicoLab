# Skills 自动发现与渐进读取

对应 [Issue #17](https://github.com/devxia/SilicoLab/issues/17)。发现只限已公开的约定位置与文件格式，不扫描磁盘，不导入其他 agent 模型设置、端点、OAuth或认证，不执行插件代码或启动 MCP。本项不越过 #3/#16 的生成脚本隔离门槛。

## 约定位置与优先级

每个项目宿主按下列顺序检查直接子目录中的 `SKILL.md`，相同 `name` 第一个兼容来源可用，其余显示shadowed及来源，不合并内容：

1. `<项目>/.agents/skills/<目录>/SKILL.md`
2. `<项目>/.claude/skills/<目录>/SKILL.md`
3. `<项目>/.pi/skills/<目录>/SKILL.md`
4. `~/.agents/skills/<目录>/SKILL.md`
5. `~/.claude/skills/<目录>/SKILL.md`
6. `~/.pi/agent/skills/<目录>/SKILL.md`

同一root按目录名排序。只访问这一层，不递归寻找别的资源，不读取旁边的auth/models/MCP文件。每root最多200个候选目录，超过显式列出未扫描原因；单SKILL.md最多256KiB，frontmatter最多8KiB。目录/文件符号链接、非普通文件、不支持结构和不可读来源明确列为incompatible，不自动扩大扫描或执行其他格式。

支持UTF-8 Markdown + YAML frontmatter的**明确子集**：`name`为1–64位ASCII字母数字开头的标识（后续可含点、下划线、短横）；`description`为1–2000字符标量，支持普通、单双引号、`>`/`|`缩进多行。其他标量字段保留兼容但不解释为权限；数组/对象/tag/anchor及任意插件manifest不执行、不当作配置导入。缺少frontmatter、损坏引号、重复字段、无效name/description显示原因；不宣称支持所有agent方言。

缺少某个约定root属于无资源，不报失败。已有root不可读或含不支持链接会显示来源错误。UI的「技能资源」无需手工逐项添加；项目打开/刷新即可再次发现，不建立永久复制或用户路径绑定。公开测试通过 `create_app(..., skill_roots=[人工目录])` 明确替代用户目录；其余测试使用 `app_fixture` 注入空roots，避免依赖或读取维护者个人资源。

## 渐进上下文与来源

资源面板和实际Node工具使用同一 `SkillCatalog`，列表只返回名称、描述、来源路径、SHA-256与available/shadowed/incompatible状态，不返回正文。模型初始请求获得兼容来源的必要描述目录，不把完整技能一次性塞入上下文；目录与必要历史合计超限时按 #15 具体停放，不静默截断。

`read_skill` 是真实pi-durable工具，仅接受已发现资源id和期望SHA-256，不接受任意文件路径。读取时重做发现、同名优先级及哈希检查，内容或来源改变时拒绝旧选择，要求刷新；最终按UTF-8完整读取有界正文，不执行其中代码。运行记录 `skillLoads` 保存实际name/source/path/hash/loaded；任务卡展示已加载状态与来源，对话工具记录持久保留正文。重开可重新发现目录，历史已加载来源不丢失。

本机验证模型提供 `/skill <name>` 人工验收入口，真实配置模型则可根据目录描述自行选择 `read_skill`。知识工具不产生科学计算结论，模型文字不代替产物。当前技能不加载相对附属脚本/图片或执行其命令；需要文件访问/脚本执行时仍受相应工具与隔离契约约束。

## 权限不继承

技能可以给方法建议，但不能通过文字授予工具/目录/网络、读取Keychain、安装依赖、启动插件或将普通序列需求路由ProteinFactory。科学专项仍需明确workflow/范围与工具许可；generated Python仍由 #3/#16门槛阻断。`read_skill` 自身只有声明的已发现说明读取能力，不修改任务 `authorizedTools`。

实际对抗测试在技能正文要求远端专项/凭据/安装，再由假模型主动尝试未授权 `protein_factory_remote`：内核拒绝未知/未提供工具，没有外部作业或科学请求。用户普通序列负例只执行原计数工具。发现过程中未运行任何脚本或插件文件。

## 验证

```bash
npm --prefix runtime run typecheck
npm --prefix runtime test
.venv/bin/python -B -m unittest discover -s backend/tests -p test_skill_resources.py -v
npm --prefix frontend run build
.venv/bin/python -B tests/e2e/fixtures/skills_workbench_fixture.py
.venv/bin/python -B tests/e2e/browser_workbench_skills.py
```

应用契约以人工目录覆盖固定优先级、同名冲突、损坏/不支持结构、描述列表不含正文、真实read_skill调用/持久来源/重开、普通请求负例，以及实际模型先描述后正文并尝试越权遭拒。runtime目录契约覆盖多行描述、内容改变后的旧哈希拒绝、符号链接不读取范围外人工哨兵。浏览器检视目录、冲突与兼容状态、触发实际读取并核对task记录、刷新保持来源。输出位于忽略的 `outputs/ui/skills/`；无个人真实skills或研究资料参与公开自动化。
