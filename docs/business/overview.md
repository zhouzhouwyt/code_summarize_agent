# 内部代码研究平台：Demo 业务背景

本目录是自有 Demo 的设计资料，不是某家企业的实际制度，也不证明当前代码已满足所有要求。
业务角色为研发人员、代码评审人员和维护人员；不假设已具备真实企业组织或权限平台。

## 平台提供什么价值
<!-- wiki: {"id":"platform-purpose","kind":"feature","status":"required","code_refs":["src/open_deep_research/workflow/graph.py::write_research_brief","src/open_deep_research/workflow/graph.py::final_report_generation"],"related":["research-process","history-evidence"]} -->

目标：帮助研发理解指定项目、追踪功能实现、核对规则与代码、分析变更影响。
输入包括用户问题、项目源码和本地业务文档；输出应包含结论、来源引用和仍未解决的问题。
边界：生成的回答是研究辅助，不替代测试、评审和业务负责人确认。没有依据时应明确未知。

## 一次研究的业务流程
<!-- wiki: {"id":"research-process","kind":"process","status":"required","code_refs":["src/open_deep_research/workflow/context.py::validate_repository","src/open_deep_research/workflow/graph.py::supervisor","src/open_deep_research/workflow/graph.py::researcher","src/open_deep_research/history/service.py::save_research_history"],"related":["history-evidence","research-exit"]} -->

用户提交问题 → 检查仓库 → 必要时澄清 → 形成任务 → 查历史与 Wiki 线索 → 研究当前源码 → 输出报告 → 保存成功生成的报告。
源码与文档是判断实现的依据，历史和模型 Wiki 解释是可检验的线索。
任何辅助索引不可用时，应尽量回退到源码搜索和读取，而不是阻断所有研究。

演示提问：这个平台如何从业务问题找到代码证据？哪些步骤是可降级的？
