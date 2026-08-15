# analyzing-projects

`analyzing-projects` 是一个面向中文用户的通用 Agent Skill，用于分析已有代码库，并产出帮助开发者理解项目整体架构与实现机制的源码级项目文档。

## 当前版本

**V1.1**

### V1.1 更新内容

- 将项目级架构发现与函数级实现追踪整合为一条完整工作流：先建立全仓能力地图，再逐一深入所有主要流程。
- 新增独立的 `references/implementation-tracing.md`，集中承载源码深度追踪的强制规范，并要求每个主要流程完整执行。
- 为每个主要流程强制提供四层输出：端到端执行栈、关键符号总表、函数级源码深度分析和跨节点系统行为总结。
- 引入 P0/P1/P2 分级和 P0 深度闭包；每个 P0 语义步骤必须附连续实际源码与紧邻解释，重要项目自有下游必须递归使用同一完整模板。
- 完善同步、异步、动态分派和跨语言调用链追踪，并将项目自有 CPU/GPU/native 实现下钻至 binding、operator、launcher、kernel 或经过证据确认的所有权边界。
- 强化证据、真实性和完成门：明确 `SOURCE`、`TEST`、`CALL-CHAIN`、`UNVERIFIED`，禁止用调用栈、符号表或字段摘要替代源码深度分析。
- 收紧适用范围：完整源码级项目架构与实现文档适用；单个 bug、函数、调用链、代码审查或实现计划不适用。

### 当前能力

当前版本主要提供以下功能：

- 分析已有代码库的目录结构、核心模块、关键流程及其实现机制。
- 面向中文开发者产出完整的源码级项目架构与实现介绍。
- 通过明确的适用范围和执行规则约束分析过程，避免偏离到单点问题或专项手册。
- 采用通用 Agent Skill 目录结构，便于完整分发、安装和后续扩展。
- 支持在 Codex、Claude Code、OpenCode、Kiro 等兼容 Agent Skills 的工具中安装或显式加载。

本 Skill 采用开放的目录结构：一个包含 YAML 元数据和执行指令的 `SKILL.md`，以及可选的 `scripts/`、`references/` 和 `assets/`。它不依赖某个特定 agent 的私有命令或配置，可用于支持这种 Skill 结构的 Codex、Claude Code、OpenCode、Kiro 等工具。

[`skills/analyzing-projects/SKILL.md`](./skills/analyzing-projects/SKILL.md) 是 agent 实际加载和执行的唯一权威入口。分析每一个已识别的主要流程时，都必须完整读取并执行 [`references/implementation-tracing.md`](./skills/analyzing-projects/references/implementation-tracing.md)。本 README 只说明分发、安装和使用，不复述执行逻辑。

## 适用范围

适用于为已有仓库编写、重组或审计完整的源码级项目架构与实现介绍。不适用于单个 bug、函数、调用链、代码审查问题、重构建议、实现计划，或安装、部署、API 等专项手册。

## Skill 目录

待安装的完整 Skill 位于：

```text
analyzing-projects/
└── skills/
    └── analyzing-projects/
        ├── SKILL.md
        └── references/
            └── implementation-tracing.md
```

以后如果增加 `scripts/`、`references/` 或 `assets/`，它们也应放在 `skills/analyzing-projects/` 中，并随整个目录一起安装。

## 通用安装

先从所用 agent 的当前文档中确认其项目级或用户级 Skill 根目录，用实际路径替换下面的 `/path/to/agent/skills`，然后复制完整目录：

```bash
SKILLS_ROOT="/path/to/agent/skills"
mkdir -p "${SKILLS_ROOT:?}/analyzing-projects"
cp -R analyzing-projects/skills/analyzing-projects/. "${SKILLS_ROOT:?}/analyzing-projects/"
```

安装结果必须是：

```text
<SKILLS_ROOT>/
└── analyzing-projects/
    ├── SKILL.md
    └── references/
        └── implementation-tracing.md
```

不要只复制 `SKILL.md`；必须复制整个 `analyzing-projects` Skill 目录，确保 `references/implementation-tracing.md` 等资料随包安装，未来新增的脚本、参考资料和资源也不会遗漏。安装或更新后，启动新会话或按所用 agent 的方式重新加载 Skills。

## 平台说明

各工具的目录约定和加载方式可能随版本变化，应以其当前官方文档为准。

### Codex

Codex 当前采用 Agent Skills 目录结构：

- 项目级：`.agents/skills`
- 用户级：`~/.agents/skills`

安装到当前项目：

```bash
mkdir -p .agents/skills/analyzing-projects
cp -R analyzing-projects/skills/analyzing-projects/. .agents/skills/analyzing-projects/
```

安装后可显式调用 `$analyzing-projects`，也可以让 Codex 根据 `description` 自动选择。

参考：[Codex Skills 官方文档](https://learn.chatgpt.com/docs/customization/overview#skills)。

### Claude Code

Claude Code 当前使用：

- 项目级：`.claude/skills`
- 用户级：`~/.claude/skills`

安装后可使用 `/analyzing-projects` 显式调用；具体加载行为以当前版本的 Claude Code 文档为准。

### OpenCode

OpenCode 当前使用：

- 项目级：`.opencode/skills`
- 用户级：`~/.config/opencode/skills`

OpenCode 也会自动加载 `~/.agents/skills` 中的 Skills，因此可以与 Codex 共用一份用户级安装。具体加载行为以当前版本的 OpenCode 文档为准。

### Kiro

Kiro 的 Skill 根目录、项目级与用户级作用域以及重新加载方式可能随版本调整。使用前查阅当前版本的 Kiro 文档，将其 Skill 根目录代入上面的通用安装命令。

无论使用哪一个工具，都应满足两个条件：

1. `analyzing-projects` 是 Skill 根目录下的直接子目录；
2. `SKILL.md` 位于该子目录的顶层。

如果所用工具或版本不能自动发现这种目录结构，可使用下面的显式加载方式。

## 不安装，直接使用

支持读取仓库文件的 agent 可以直接加载源文件：

```text
请先完整读取 analyzing-projects/skills/analyzing-projects/SKILL.md，并将它作为本次源码级项目架构与实现文档任务的强制工作流执行。
```

任务示例：

```text
请使用 analyzing-projects Skill 分析当前代码库，并交付一份向开发者解释项目整体架构与实现机制的源码级项目介绍。
```

## 更新

重新执行对应平台的复制命令，覆盖已安装的 Skill 内容，然后重新加载 Skills 或启动新会话。复制整个目录，不要分别维护源文件和安装副本。

## 排查

- 确认实际路径是 `<SKILLS_ROOT>/analyzing-projects/SKILL.md`，没有多嵌套或少一层目录。
- 确认 `SKILL.md` 文件名大小写正确，YAML frontmatter 包含 `name` 和 `description`。
- 确认所用 agent 和版本支持 Agent Skills，并核对其项目级、用户级目录及加载方式。
- 更新后重新加载 Skills 或启动新会话。
- 自动触发不稳定时，显式指定 `analyzing-projects`，或直接要求 agent 完整读取源文件。
