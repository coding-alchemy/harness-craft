# Issue tracker：Specs 原生本地 Markdown

本仓库使用按所属范围就近的 `specs/` 和 `specs/plans/` 作为规格与执行任务的唯一事实源。

## 归属范围

`<scope>` 表示文档所属范围：只属于单个模块时为模块根目录，同时约束两个以上模块或仓库整体时为项目根目录。无法确定所属范围时，先按根目录 `AGENTS.md` 的规则询问用户。

## 规范位置

- 需求文档：`<scope>/specs/YYYY-MM-DD-<topic>-requirements.md`
- 设计文档：`<scope>/specs/YYYY-MM-DD-<topic>-design.md`
- 执行路线图：`<scope>/specs/plans/<topic>/README.md`
- 执行 ticket：`<scope>/specs/plans/<topic>/YYYY-MM-DD-NN-<ticket-slug>.md`
- 所属范围的计划索引：`<scope>/specs/plans/README.md`

所有文档必须遵守根目录 `AGENTS.md` 的语言、命名、人工评审、核心目标守恒和验证要求。

## 发布规则

当 Skill 要求发布规格时：

1. 将需求或设计写入所属范围的 `specs/`；
2. 按人工评审门禁设置文档状态；
3. 同一主题已有权威文档时更新原文，保持单一事实源。

当 Skill 要求发布 tickets 时：

1. 每张 ticket 使用独立编号文件；
2. 按依赖顺序连续编号；
3. 在主题路线图中维护执行顺序、阻塞关系和整体完成标准；
4. 同步维护所属范围的 `specs/plans/README.md`。

## Ticket 约定

每张 ticket 至少包含：

- 用户可观察的交付结果；
- `Blocked by`，使用相对链接指向阻塞 ticket，或明确写“无”；
- 文档状态；
- Agent triage 状态；
- 可直接验证的验收标准；
- 明确非目标。

阻塞关系决定可执行前沿：只有阻塞 ticket 全部完成的 ticket 才能开始。

## 人工门禁

- 需求和设计未获用户明确批准时，不得编写执行计划；
- 执行计划未获用户明确批准时，ticket 不得标记为 `ready-for-agent`，也不得修改实现代码；
- 用户确认拆分粒度或阻塞关系，不自动等同于批准整个执行计划；
- 获得执行计划批准后，已完整定义的 tickets 可以标记为 `ready-for-agent`；
- 被阻塞的 ticket 即使已完整定义，也必须等待阻塞关系解除后才能执行。

## 获取 ticket

读取用户指定的路线图或编号 ticket，并同时读取其阻塞项、上游规格和相关模块上下文。
