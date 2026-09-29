# Demo 变更请求

此文件明确记录计划，不把未来工作描述为现有能力。

## 计划增强流程结束判断
<!-- wiki: {"id":"exit-change","kind":"change","status":"planned","code_refs":["src/open_deep_research/workflow/graph.py::supervisor_tools","src/open_deep_research/workflow/graph.py::researcher_tools","src/open_deep_research/workflow/graph.py::compress_research","src/open_deep_research/workflow/state.py::ResearchResult"],"related":["research-exit","current-evidence"]} -->

目标：区分继续研究、证据充分结束、停滞结束和预算耗尽；输出理由与未解决问题。
候选变更范围：Supervisor 调度、Researcher 工具循环、状态字段、压缩结果和最终报告。
待决事项：具体 JEV 框架名称与接入方式尚未明确；本业务 Wiki 变更不包含其接入，也不修改已有循环策略。
验收问题：连续重复查询能否停止？停止后是否错误标记 completed？新会话会不会复用上一轮的退出状态？

演示提问：如果实现这项计划，哪些现有规则必须继续满足，哪些代码与测试需要检查？
