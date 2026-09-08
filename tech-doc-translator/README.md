# 技术文档翻译器

本模块提供一个面向理工科英文技术文档翻译的 Agent Skill，唯一 Skill 源目录为 [skills/tech-doc-translator/](./skills/tech-doc-translator/)：入口 [SKILL.md](./skills/tech-doc-translator/SKILL.md)、源家族解析/校验/合并/编排脚本（[scripts/](./skills/tech-doc-translator/scripts/)）、翻译约定与共享术语库（[references/](./skills/tech-doc-translator/references/)）以及 [requirements.txt](./skills/tech-doc-translator/requirements.txt) 都在该目录内，随 Skill 整体安装。README、规格、docs、测试和安装器留在模块根目录，不属于安装包。已支持单页 HTML、分页代码文档、数学/深层嵌套参考手册、多页面 API/DSL 文档、工作包拆分/恢复/术语合并，以及显式选择的共享术语库。

## 安装

```bash
# Codex：安装/更新到 ${CODEX_HOME:-~/.codex}/skills/tech-doc-translator
python3 tech-doc-translator/install_skill.py
# 受管文件冲突时默认拒绝；确认替换后使用：
python3 tech-doc-translator/install_skill.py --force
```

安装器只依赖 Python 标准库，把 Skill 源目录的全部发布文件复制到 `${CODEX_HOME:-~/.codex}/skills/tech-doc-translator`；相同内容与权限的重复安装成功且不重写文件，目标中的未知文件保留，不安装第三方依赖，也不创建翻译项目或配置。其他兼容 Agent Skills 的工具可直接把整个 `skills/tech-doc-translator/` 复制到目标 Skill 根目录（不要只复制 `SKILL.md`）。

安装后从安装目录内的 [requirements.txt](./skills/tech-doc-translator/requirements.txt) 显式安装依赖：`pip install -r "${CODEX_HOME:-$HOME/.codex}/skills/tech-doc-translator/requirements.txt"`。

## 使用

`<SKILL目录>` 指已安装或已复制的 `tech-doc-translator` Skill 目录（源码内即 `tech-doc-translator/skills/tech-doc-translator`）。Skill 指令、最小调用与回归入口见 [SKILL.md](./skills/tech-doc-translator/SKILL.md)；脚本均以 `<SKILL目录>/scripts/...` 调用，例如：

```bash
python3 <SKILL目录>/scripts/parse_single_page_html.py <html> [section_id] <out.md>
python3 <SKILL目录>/scripts/select_glossary.py --source <源Markdown> --library <SKILL目录>/references/glossaries/nvidia.md --output <子集.md>
```

离线回归入口：

```bash
bash tech-doc-translator/tests/run_single_page.sh   # 其余：run_*.sh 共六组
```

当前权威文档：

- [NVIDIA 术语库](./skills/tech-doc-translator/references/glossaries/nvidia.md)，作为需要由项目显式选择的默认口径

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
