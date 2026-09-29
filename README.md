# Code Research Agent

基于 Open Deep Research 的代码研究系统。保留 Supervisor / Researcher 两个循环，所有问题统一经过 Supervisor。源码搜索与读取始终可用；AST 索引、源码版本和历史 RAG 都是可降级的辅助能力。

## 流程

```text
START → validate_repository → clarify_with_user → write_research_brief
      → prepare_repository_context → retrieve_research_history
      → research_supervisor → final_report_generation → save_research_history → END
```

路径无效时提示并结束；需要澄清时由 `clarify_with_user` 输出问题并结束本轮。没有索引、版本未知、历史未命中或不可用时，继续进入 Supervisor。

完整设计、工具、数据存储与评测说明见 [当前工作流](docs/code_research_workflow.md)。

## 运行

沿用当前 `.venv`，在 `.env` 中配置模型提供商凭据。命令行会加载 `.env`：

```powershell
.\.venv\Scripts\python.exe -m open_deep_research.cli.research "历史报告保存流程是如何实现的？" --repository .
```

不使用历史模型时可加 `--no-history`；网页工具默认关闭，按需加 `--allow-web`。MCP 按 `mcp_config` 配置装配，不会因代码模式而排除。

AST 索引不要求事先建立。需要静态图查询时手动构建（当前仅 Python，无需 embedding）：

```powershell
.\.venv\Scripts\python.exe -m open_deep_research.cli.index .
```

源码变化后重建；旧索引不会继续提供过期关系，研究会回退到目录、搜索和源码读取。

AST 和历史对话共用一个 SQLite 文件，默认沿用 `.research-history/history.sqlite3`：
`repository_snapshots` 表按仓库绝对路径保存 AST 快照，`research_history` 表保存历史问题与报告。
通过 `RESEARCH_DATABASE` 环境变量、API 的 `research_database` 或两个 CLI 的 `--database` 指定共享路径；
环境变量优先于 CLI/API。旧 `HISTORY_DATABASE` / `history_database` 仍兼容，但新配置优先。
现有历史记录直接保留，无需重新生成向量。旧 `.repository-knowledge/*.sqlite3` 不再读取；
执行上面的 AST 构建命令即可将当前仓库索引写入共享库，旧文件保留。
原 `--index-dir` / `repository_index_dir` 请改为共享数据库路径配置；自定义路径时两种入口需使用同一文件。

全新环境可用 `uv sync --extra research-history --extra dev`。历史 embedding 使用本地缓存的 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，或通过 `HISTORY_EMBEDDING_MODEL` 指向本地模型目录；运行时不自动下载模型，模型不可用时历史检索降级。无需 GPU。

## 项目 Wiki 与知识图谱

Wiki 从 AST 提取模块依赖、调用和继承关系，提供 Markdown 总览、模块页和完整关系 JSON，
可选择用大模型补充职责解释，并让研究工具按需读取。
同时读取 `docs/business/` 的本地 Markdown，关联业务要求、计划变更、真实代码和测试，
生成业务主题页与关系图；模型可对照文档与源码提出待核实的差异。

```powershell
# 纯静态提取，不调用大模型
.\.venv\Scripts\python.exe -m open_deep_research.cli.wiki . --no-llm
# 通过配置的研究模型生成说明，可用 --model 或 WIKI_MODEL 指定模型
.\.venv\Scripts\python.exe -m open_deep_research.cli.wiki .
```

生成会重建 AST，把 Wiki 存入共享库的 `repository_snapshots.data`，不新增库或业务表。
文件导出到 `.repository-wiki/` 下独立版本目录；源码或业务文档变化后须重新生成。
模型说明是待核实线索。配置、限制与源码入口见 [Wiki 使用与设计](docs/project_wiki.md)。

本项目的 [Demo 业务背景](docs/business/overview.md)、[研究规则](docs/business/research_rules.md)、
[历史复用规则](docs/business/history_rules.md) 和 [计划变更](docs/business/change_requests.md)
是设计资料，不是实现保证。可演示：“历史复用是否符合证据规则？”、“修改结束策略会影响哪里？”、
“用户隔离在哪些代码和测试中体现？”。

## LangGraph Studio / API

`langgraph.json` 仅注册当前主图；保留 `src/security/auth.py` 的部署鉴权。启动已有环境中的开发服务：

```powershell
.\.venv\Scripts\langgraph.exe dev
```

调用时配置：

```python
config = {"configurable": {
    "repository_path": "D:/path/to/repository",
    "repository_allow_web": False,
    "history_enabled": True,
}}
```

澄清回复应使用同一会话的对话状态。CLI 每次启动是独立调用；需要 CLI 继续研究时，在新问题中写明完整需求与补充条件。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m tests.manual.check_local_history
```

第一条测试真实图编排、工具与数据库，LLM 使用模拟输出；第二条使用缓存的真实 embedding 模型。它们不代表真实 LLM 的代码理解准确率。

## 目录与阅读顺序

详细文件说明和调用关系见 [代码阅读指南](docs/project_structure.md)。
整体分层、主图、两层研究循环、退出条件与存储关系见 [完整架构与 LangGraph 编排图](docs/architecture.md)。

```text
src/open_deep_research/
├── configuration.py     # 运行参数与环境变量
├── cli/                 # 研究、AST 建库命令
├── workflow/            # 主图、研究循环、状态、提示词、上下文准备
├── repository/          # 源码读取、搜索、AST 索引
├── history/             # 历史报告检索、保存、本地 embedding
├── wiki/                # 知识图谱提取、模型解释、Wiki 导出和读取
├── storage/             # 一个 SQLite 文件、两张业务表
└── integrations/        # 工具装配、网页搜索、MCP、模型辅助
src/security/            # 部署鉴权
tests/
├── unit/                # 历史存储与共享数据库测试
├── integration/         # 完整工作流与工具测试
└── manual/              # 真实本地 embedding 检查
```

建议先读 `workflow/graph.py` 末尾的主图连接，再读 `workflow/state.py` 和
`workflow/context.py`；随后按需要进入源码工具、历史检索和外部集成。
包顶层的 `deep_researcher.py`、`code_workflow.py`、`repository_knowledge.py`
只保留旧图入口或命令兼容，业务实现以新目录为准。

源码位于 `src/open_deep_research/`。旧 legacy 图、三路直答、模块向量检索、旧研究样例和旧基准评测已移除。保留原项目 MIT 许可证和作者信息。
