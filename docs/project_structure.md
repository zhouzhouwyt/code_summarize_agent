# 代码阅读指南

项目按“入口 → 工作流 → 业务能力 → 数据存储”组织。以下路径除特别标注外，
均相对于 `src/open_deep_research/`。

## 建议阅读顺序

1. `workflow/graph.py` 末尾的 `deep_researcher_builder`：看主图节点怎样连接。
2. `workflow/state.py`：看会话状态、子任务状态、结构化结果。
3. `workflow/context.py`：看仓库检查、版本检测和可选索引加载。
4. `workflow/graph.py` 中的 `clarify_with_user`、`write_research_brief`：看需求如何变成研究任务。
5. 同文件的 `supervisor` / `supervisor_tools`：看任务如何拆分；
   `researcher` / `researcher_tools`：看工具如何调用；`compress_research`：看证据如何整理。
6. 按实际工具进入 `repository/`、`history/` 或 `integrations/`。
7. 回到 `final_report_generation`，再看 `history/service.py` 的 `save_research_history`。

## 文件职责

| 文件 | 职责 |
|---|---|
| `configuration.py` | 参数默认值、环境变量解析、旧数据库配置兼容 |
| `cli/research.py` | 解析研究命令、加载环境、调用主图、输出结果 |
| `cli/index.py` | 解析建库命令、显式构建 AST 快照 |
| `workflow/graph.py` | 主图、Supervisor / Researcher 循环、路由、报告生成 |
| `workflow/context.py` | 仓库可用性、版本与索引准备、上下文裁剪 |
| `workflow/state.py` | 工作流状态与结构化结果类型 |
| `workflow/prompts.py` | 澄清、研究、压缩、报告和网页摘要提示词 |
| `repository/index.py` | Python 扫描、AST 符号和关系、快照保存与过期检查 |
| `repository/tools.py` | 目录、文本搜索、源码读取、符号和关系工具 |
| `history/service.py` | 历史存取、相似度检索、范围隔离、工作流节点和分页工具 |
| `history/embeddings.py` | 本地缓存模型加载、历史问题向量生成 |
| `wiki/graph.py` | AST 模块依赖提取与源码引用 |
| `wiki/business.py` | 本地业务文档分节、要求与代码／测试关联、模型差异引用校验 |
| `wiki/service.py` | 模型解释、版本检测、Wiki 保存与加载 |
| `wiki/render.py` / `wiki/tools.py` | Markdown / JSON 导出、研究工具读取 |
| `cli/wiki.py` | 显式生成 Wiki，支持纯静态模式 |
| `storage/database.py` | SQLite 连接、两张表初始化、历史字段升级 |
| `integrations/tools.py` | 按配置装配源码、历史、网页、MCP 和反思工具 |
| `integrations/web_search.py` | Tavily 搜索、网页摘要 |
| `integrations/mcp.py` | MCP 工具发现、OAuth 交换、鉴权错误处理 |
| `integrations/models.py` | 模型配置、消息处理、原生搜索检测、token 限制辅助 |
| `src/security/auth.py`（项目根目录起） | LangGraph 部署鉴权 |

## 调用关系

```text
cli/research → workflow/graph → integrations/tools
                   │                  ├→ repository/tools → repository/index
                   │                  ├→ history/service
                   │                  ├→ integrations/web_search
                   │                  └→ integrations/mcp
                   └→ history/service → history/embeddings
cli/index → repository/index

repository/index ──┐
                  ├→ storage/database → 一个 SQLite 文件
history/service ──┘
```

`repository_snapshots` 按仓库路径保存 AST 快照，`research_history` 保存历史研究。
数据库默认仍位于 `.research-history/history.sqlite3`。移动源码会让旧 AST 快照过期，
应使用建库命令重建；重建不删除历史报告。

## 测试与启动

- `tests/unit/`：历史存取、共享库、多仓库隔离和兼容性。
- `tests/integration/`：图编排和工具测试，使用模拟 LLM。
- `tests/manual/`：依赖本地模型缓存的人工检查，不随 pytest 自动执行。

```powershell
.\.venv\Scripts\python.exe -m open_deep_research.cli.research "研究问题" --repository .
.\.venv\Scripts\python.exe -m open_deep_research.cli.index .
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m tests.manual.check_local_history
```

`langgraph.json` 指向 `workflow/graph.py:deep_researcher`，打包配置自动发现 `src/` 下的子包。
旧命令 `open_deep_research.code_workflow`、`open_deep_research.repository_knowledge`
和旧图入口 `open_deep_research.deep_researcher:deep_researcher` 保留兼容。
其他内部模块导入应使用上表的新路径。

## 根目录说明

- `README.md`、`docs/`：概览、设计与阅读指南。
- `pyproject.toml`、`uv.lock`：依赖和打包；`langgraph.json`：服务入口。
- `.env.example`：配置样例；本地 `.env`：实际配置。
- `.research-history/`：业务数据库；`.langgraph_api/`：本地服务状态。
- `.venv/`、`*.egg-info/`、`__pycache__/`：运行环境、安装元数据和缓存，无需作为业务源码阅读。
- `.benchmarks/`、`.idea/`：已有本地评测产物和编辑器配置，本次保留原位。

目录整理保留原有业务行为。现有高相似度历史路由包含动态报告跳转和静态研究边，
可能额外触发报告生成；相关流程测试失败需单独处理。
