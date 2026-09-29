# 项目 Wiki 与知识图谱

Wiki 是项目知识整理模块，融合 Python AST 和本地业务 Markdown，提取模块依赖、业务主题与源码关联，
再由可选大模型解释模块和对照业务要求。
它不是独立模型产品，也不依赖新的图数据库。

## 生成与阅读

```powershell
# 不请求模型服务
.\.venv\Scripts\python.exe -m open_deep_research.cli.wiki D:/path/to/project --no-llm
# 默认用 research_model，也可指定 wiki_model
.\.venv\Scripts\python.exe -m open_deep_research.cli.wiki D:/path/to/project --model openai:gpt-4.1
# 自定义共享库和导出父目录
.\.venv\Scripts\python.exe -m open_deep_research.cli.wiki . --no-llm --database .research-history/history.sqlite3 --output .repository-wiki
```

环境变量优先于命令参数。模型模式会向配置的服务发送每个模块的部分源码和关系；
纯静态模式不会发送。命令打印导出路径和各状态的页面数量，每次导出写入新目录。

- `README.md`：项目规模、模块导航、Mermaid 依赖图、语法诊断。
- `modules/*.md`：符号与行号、依赖及被依赖模块、可选模型解释、源码链接。
- `business/*.md`：业务要求或计划、文档段落引用、代码／测试关联、待核实差异。
- `graph.json`：完整节点、边、模块聚合关系、引用和未解析信息。

总览图最多展示 80 个模块、120 条关系，完整结构保留在 JSON 中。
模型失败或超出预算时，静态页面和关系图仍可使用。

## 提取与持久化

1. 显式重建 Python AST，保留 module/class/function/method 节点及 CONTAINS、IMPORTS、CALLS、INHERITS 边。
2. 将已解析的跨文件关系汇总为模块依赖；未解析和有歧义的关系不作为确定依赖。
3. 为符号和关系记录路径、行号、文件哈希及引用 ID。
4. 模型逐模块生成职责说明、带引用的判断、待核实事项，输入有字符预算。
5. 检查模型引用是否出现在输入中，写入前复查源码版本。
6. 保存到原 `repository_snapshots.data` JSON 的 `wiki` 字段，仍为一个数据库、两张业务表。

引用存在不等于解释语义正确。模型页面及 summary 均为待核实推断，状态为
`generated_unverified`。其他状态有 `static`、`generation_failed`、`skipped_budget`。
解析失败文件列在诊断中，不生成虚假的模块结构。

源码解析目前只支持 Python 静态结构。动态分派、反射、运行时注册和配置驱动流程可能无法解析，
不宣称还原完整运行时架构。业务来源目前只支持指定目录内的 Markdown，不接入外部企业平台。

## 研究工具

开启 `wiki_enabled` 且存在当前源码版本的 Wiki 时，Researcher 获得三个工具：

| 工具 | 用途 |
|---|---|
| `list_project_wiki` | 按路径或名称查找模块 ID，支持分页 |
| `read_project_wiki` | 分页阅读模块说明，作为源码核实的线索 |
| `query_wiki_graph` | 查直接依赖／被依赖关系，返回 AST 源码引用 |
| `list_business_topics` | 搜索业务要求、流程、计划变更 |
| `read_business_topic` | 阅读业务原文、关联和待核实差异 |
| `query_business_graph` | 追踪主题关联的源码、测试及直接模块依赖影响线索 |

研究流程不会自动生成 Wiki。未生成、关闭、损坏或过期时，原有源码工具继续工作。
业务工具仅在存在业务主题时提供。Wiki 工具每次调用重新核对 Python 源码和业务文档版本。
文档新增、修改、删除或配置的目录变化均使旧 Wiki 失效。单独运行 `cli.index` 会替换快照并清除旧 Wiki，
需再次运行 `cli.wiki`；历史报告与向量不受影响。

## 配置与实现

| 配置（对应同名大写环境变量） | 默认值 | 含义 |
|---|---|---|
| `wiki_enabled` | true | 允许研究工具读取已有 Wiki |
| `wiki_business_dir` | docs/business | 仓库内业务 Markdown 目录，可用 CLI `--business-dir` 指定 |
| `wiki_max_business_topics` | 30 | 每次最多进行模型对照的业务主题数，静态提取不受限制 |
| `wiki_model` | 未设置 | 未设置则使用 research_model |
| `wiki_max_modules` | 100 | 按路径排序，每次最多解释的模块数；静态提取不受限制 |
| `wiki_context_chars` | 24000 | 每个模块 JSON 输入预算，不含固定系统提示 |
| `wiki_max_tokens` | 3000 | 每个模块模型输出上限 |
| `wiki_timeout_seconds` | 90 | 单模块模型调用超时 |

默认导出目录 `.repository-wiki/` 被源码扫描和 Git 忽略。自定义导出目录建议放在
被分析仓库外，避免生成的 Markdown 被原有文本搜索和版本扫描收录。

源码在 `src/open_deep_research/wiki/`：`graph.py` 提取结构，`service.py` 生成与保存，
`render.py` 导出，`tools.py` 提供工具；入口是 `cli/wiki.py`。
`tests/unit/test_wiki.py` 使用模拟模型检查流程，不代表真实模型解释质量。

## 业务文档格式

按二级标题（`##`）划分主题；没有二级标题时整份文档作为一个主题。
普通 Markdown 无需元数据即可展示，默认为 reference，不自动声称它是强制规则。
在主题内添加一个 JSON 注释可声明稳定 ID、类型、要求状态、关联源码和测试：

```markdown
## 历史复用必须核实当前源码
<!-- wiki: {"id":"history-evidence","kind":"rule","status":"required","code_refs":["src/open_deep_research/history/service.py::retrieve_research_history"],"test_refs":[],"related":[]} -->
即使相似度高，也应验证当前问题的关键结论。
```

`kind` 为 feature/rule/process/change；`status` 为 required/planned/reference。
`code_refs` 和 `test_refs` 使用“仓库相对路径::限定符号名”，例如
`file.py::Class.method`；模块整体使用 `file.py::@module`。`related` 引用其他业务主题的 ID。
重复 ID 或错误元数据会明确报错；不存在或有歧义的符号标为 missing/ambiguous，不编造目标。

原文关联标记 document_declared，仅证明可定位。模型建议标记 model_inferred，必须同时提供
本次输入中的文档引用和对应符号引用。非 unknown 的差异判断也必须同时引用文档与代码。
所有模型结果均为 generated_unverified，potential_conflict 表示疑似冲突，appears_aligned 表示
初步符合，均不是验证结论。源码片段截断和动态行为需作为缺口保留。
候选代码由显式声明和符号名文本匹配选取，不保证自动找到所有相关实现。

模型模式会额外向配置的服务发送业务主题原文和候选源码。每个主题使用独立预算；
失败、超预算或缺少模型配置时仍保留静态主题和声明关联。

Wiki schema 已升级为 2：保留 source_revision（Python AST），revision 汇总源码版本、
文档内容哈希和目录配置。旧 schema 1 Wiki 需要重建，数据库结构与历史报告不变。
仍保存到 repository_snapshots 的 wiki 字段，不新增表。文档读取最多 200 个文件、共 5 MB，
沿用仓库路径边界、忽略目录和单文件大小限制。

## 本项目 Demo 的演示顺序

1. 运行 `cli.wiki . --no-llm`，先看业务主题、规则—代码—测试关系图和计划状态。
2. 用 `cli.research` 提问“历史报告复用是否符合证据规则？分别引用业务文档和代码”。
3. 查 history-evidence 的路由函数和主图连接，核实潜在的提前报告问题；不把文档中的审查疑问当作结论。
4. 提问“增强结束判断会影响哪里？”，追踪 exit-change 的关联与模块依赖。
5. 修改业务规则后调用已有 Wiki 工具，应提示过期；重建后新版本应可读取。

流程结束判断增强仍是计划，具体 JEV 框架未明确，本次 Wiki 扩展没有实现该框架或修复既有路由。
自动化测试覆盖静态关联、文档失效、模型双来源引用、未知引用拒绝、分页和工具装配；
测试入口是 `tests/unit/test_business_wiki.py`。
