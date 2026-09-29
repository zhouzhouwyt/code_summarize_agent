# Demo 历史知识复用规则

本文件描述平台应遵守的历史复用要求，不是对当前实现的合规认证。

## 历史只能作为核实线索
<!-- wiki: {"id":"history-evidence","kind":"rule","status":"required","code_refs":["src/open_deep_research/history/service.py::retrieve_research_history","src/open_deep_research/workflow/graph.py::route_after_history","src/open_deep_research/workflow/graph.py::compress_research","src/open_deep_research/workflow/graph.py::@module"],"test_refs":["tests/integration/test_workflow.py::test_entire_graph_history_reaches_researcher_and_writer"],"related":["current-evidence"]} -->

要求：即使问题高度相似且源码版本相同，也应按本次问题核实关键结论，不能仅凭相似度把旧报告视为本次已验证结论。
待核对差异：检查 route_after_history 中通往 final_report_generation 的动态跳转，及主图从该节点通往 research_supervisor 的静态边。
审查问题：这两个出口是否同时生效，导致未完成本轮验证就额外生成报告？需分别引用本规则、路由函数和主图连接；不能把这里的疑问直接作为程序结论。

演示提问：当前历史报告复用是否符合这条规则？给出文档与代码依据，并解释不确定性。

## 用户与项目范围隔离
<!-- wiki: {"id":"history-scope","kind":"rule","status":"required","code_refs":["src/open_deep_research/history/service.py::_scope","src/open_deep_research/history/service.py::ResearchHistory.search","src/open_deep_research/history/service.py::history_tools"],"test_refs":["tests/unit/test_history.py::test_records_are_complete_idempotent_and_scoped","tests/unit/test_history.py::test_auth_owner_overrides_local_namespace","tests/integration/test_workflow.py::test_history_version_scope_and_paged_read"]} -->

要求：历史检索和报告读取遵守用户、namespace 和仓库范围，不能通过任意记录 ID 读取其他范围的内容。
版本已知时，应筛选相同版本；版本未知时只能将历史作为待验证线索。
边界：本地 namespace 是逻辑范围，不等于企业登录认证；当前 Demo 没有完整的组织角色权限设计。

## 源码与文档更新后知识失效
<!-- wiki: {"id":"knowledge-freshness","kind":"rule","status":"required","code_refs":["src/open_deep_research/repository/index.py::RepositoryKnowledge.load","src/open_deep_research/wiki/service.py::load_wiki","src/open_deep_research/wiki/business.py::wiki_revision"],"related":["current-evidence"]} -->

要求：Python 源码或纳入 Wiki 的业务文档新增、修改、删除后，旧 Wiki 不应继续作为当前知识提供。
文档变化不意味着所有源码关系改变，但需要重新生成融合后的知识版本。旧历史报告仍可保存，不因重建 Wiki 被删除。
