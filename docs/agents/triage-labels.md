# Triage 标签

Agent triage 状态与文档人工评审状态是两套不同信息：

- 文档状态记录需求、设计或计划是否已经人工批准；
- Agent triage 状态记录工作是否具备进一步处理条件；
- 文档未获必要批准时，不得使用 `ready-for-agent` 绕过人工门禁。

| Skill 标准角色 | 本仓库标签 | 含义 |
|---|---|---|
| `needs-triage` | `needs-triage` | 需要维护者评估范围、优先级或归属 |
| `needs-info` | `needs-info` | 缺少继续处理所需的信息或决定 |
| `ready-for-agent` | `ready-for-agent` | 已充分定义、已通过必要人工门禁，可由 Agent 执行 |
| `ready-for-human` | `ready-for-human` | 必须由人工执行或作出决定 |
| `wontfix` | `wontfix` | 已决定不处理 |

当 Skill 提到标准角色时，使用上表对应的本仓库标签字符串。
