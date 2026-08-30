# 技术文档翻译器

> 当前状态：Practice-first 执行计划 Tickets 01–07 已完成；模块已通过 cuSPARSE 官方文档前三章真实试译终验并转入已集成状态。

本模块提供一个面向理工科英文技术文档翻译的 Agent Skill（[skills/tech-doc-translator/SKILL.md](./skills/tech-doc-translator/SKILL.md)），以及由 Skill 调用的源家族解析、校验、合并与编排脚本。已支持单页 HTML、分页代码文档、数学/深层嵌套参考手册、多页面 API/DSL 文档、工作包拆分/恢复/术语合并，以及显式选择的共享术语库。

脚本依赖 `beautifulsoup4`，按 [requirements.txt](./requirements.txt) 安装；回归入口见 `tests/run_*.sh`。

当前权威文档：

- [Practice-first 规格](./specs/2026-08-29-tech-doc-translator-practice-first-design.md)，整合目标行为、Skill 工作流、脚本边界与验收要求；
- [可复用术语库需求](./specs/2026-08-30-reusable-glossaries-requirements.md)与[设计](./specs/2026-08-30-reusable-glossaries-design.md)，定义共享库、项目覆盖和验收后回流；
- [NVIDIA 术语库](./glossaries/nvidia.md)，作为需要由项目显式选择的默认口径；
- [英文技术文档结构化翻译完整方案](./docs/英文技术文档结构化翻译完整方案.md)，汇总当前实现、执行流程、验收标准与未来方向；它不是严格设计合同。

现行规格以 `/Users/nanzhang/workdir/HPC_Trans` 中的真实翻译经验、项目术语和源家族脚本为只读实践基线，已于 2026-08-29 获得明确批准；Skill 与脚本可脱离该绝对路径独立运行。Ticket 07 已使用 cuSPARSE 13.3 官方文档前三章完成真实试译终验。
