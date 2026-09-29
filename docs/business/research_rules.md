# Demo 研究质量规则

这些是设计要求，规则与实现需要分别引用。源码位置关联仅表示核对入口。

## 结论必须有当前证据
<!-- wiki: {"id":"current-evidence","kind":"rule","status":"required","code_refs":["src/open_deep_research/workflow/graph.py::compress_research","src/open_deep_research/workflow/graph.py::final_report_generation"],"test_refs":["tests/integration/test_workflow.py::test_budget_and_fabricated_history_evidence_stay_unverified","tests/integration/test_workflow.py::test_run_reset_and_repository_change_prevent_mixed_reports"],"related":["history-evidence"]} -->

要求：关于当前实现的结论必须能定位到当前源码；引用不存在、证据缺失或研究期间源码变化时，不得宣称已验证完成。
核对方式：阅读证据 ID 校验、报告生成前的版本复查，以及测试断言；测试存在不等于测试已执行或通过。
差异检查：引用 ID 存在只说明可定位，不能自动证明源代码支持模型的业务解释。

## 研究应有明确结束条件
<!-- wiki: {"id":"research-exit","kind":"rule","status":"required","code_refs":["src/open_deep_research/workflow/graph.py::supervisor_tools","src/open_deep_research/workflow/graph.py::researcher_tools"],"related":["exit-change","current-evidence"]} -->

要求：证据足够、无法继续推进或达到预算时，应结束研究并说明结束原因。未解决事项应保留在报告中。
核对方式：检查 ResearchComplete、无工具调用、研究轮数和工具调用预算对应的分支；检查是否能识别重复任务和没有新证据的循环。
此条并不声称已经接入独立 Judge/Evaluator/Verifier 或任何特定 JEV 框架。

演示提问：修改结束策略，会影响 Supervisor、Researcher、结果压缩和报告保存的哪些位置？
