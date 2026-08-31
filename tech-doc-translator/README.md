# 技术文档翻译器

本模块提供一个面向理工科英文技术文档翻译的 Agent Skill（[skills/tech-doc-translator/SKILL.md](./skills/tech-doc-translator/SKILL.md)），以及由 Skill 调用的源家族解析、校验、合并与编排脚本。已支持单页 HTML、分页代码文档、数学/深层嵌套参考手册、多页面 API/DSL 文档、工作包拆分/恢复/术语合并，以及显式选择的共享术语库。

脚本依赖 `beautifulsoup4`，按 [requirements.txt](./requirements.txt) 安装；回归入口见 `tests/run_*.sh`。

当前权威文档：

- [NVIDIA 术语库](./glossaries/nvidia.md)，作为需要由项目显式选择的默认口径

现行规格以真实 NVIDIA 文档的翻译经验、项目术语和源家族脚本为实践基线。

## NVIDIA 官方文档扩展验证（2026-08-31）

本次使用 Skill 翻译并复核了以下 12 套 NVIDIA 官方文档：

- cuSPARSE 13.3；
- cuBLAS 13.3；
- CUDA C++ Best Practices Guide 13.3；
- Blackwell Compatibility Guide 13.3；
- NVIDIA Blackwell Tuning Guide 13.3；
- NVIDIA CUDA Compiler Driver NVCC 13.3；
- CUDA Programming Guide 13.3；
- cuTile Python 1.5.0；
- Hopper Compatibility Guide for CUDA Applications 13.3；
- NVIDIA Hopper Tuning Guide 13.3；
- Parallel Thread Execution ISA（PTX ISA）9.3；
- Tile IR 0.16.1（CUDA 13.3）。
