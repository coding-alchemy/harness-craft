# Kimi-Codex 工作流：GitHub Actions + 本地双 Agent 闭环

> 状态：设计评审中
> 目标：只使用 GitHub 原生调度能力、OpenCode/Kimi 和本地 Codex CLI，实现最多 5 轮的代码修改与交叉评审。
>
> 使用指南：[Kimi-Codex 工作流使用指南](../docs/kimi-codex-workflow-usage.md)

## 1. 结论

GitHub Actions 负责排队、并发、状态、日志和通知；一台可信的本地电脑运行 GitHub self-hosted runner，并按任务调用已经登录的 OpenCode/Kimi 与 Codex CLI。

GitHub 只提供 Actions、PR、Checks/日志、Artifact、Label 和通知能力；方案不调用 GitHub Copilot，也不使用 Copilot 模型。

```text
GitHub workflow_dispatch
          │
          ▼
GitHub Actions / reusable workflow
          │
          ▼
本地 self-hosted runner
   ┌──────┴──────┐
   │             │
OpenCode/Kimi  Codex CLI
   │             │
   └── 修改 ⇄ 评审 ┘
          │
     最多 5 轮
          │
   ┌──────┴──────────┐
   │                 │
 通过             需要人工
   │                 │
PR 标记完成     Label + PR @通知
```

模型不直接建立 RPC 连接。中央编排器把修改结果、测试结果和结构化评审结果在两个 CLI 之间传递。这种“通过 GitHub Actions 交接”的方式比两个常驻 Agent 互相调用更简单，也更容易恢复和审计。

### 1.1 唯一常驻组件

唯一需要常驻的组件是 GitHub 官方 self-hosted runner。Runner 主动连接 GitHub 领取任务，因此不需要公网入口、反向代理或自建轮询服务。

OpenCode 和 Codex 不需要保持 TUI 打开。Runner 收到任务后分别调用：

```bash
opencode run "<task prompt>"
codex exec "<task prompt>"
```

### 1.2 组件边界

方案不包含以下运行组件：

- 海外常驻服务器
- 自建 HTTP/Webhook 服务
- 自建 GitHub App
- GitHub App JWT 与 installation token 管理
- PAT
- 仓库镜像目录和仓库路由表
- 数据库、Redis 或消息队列
- 自建日志服务器
- 自建 Skill Loader
- 飞书等外部通知组件
- 两个 Agent 各自轮询 GitHub 的双守护进程

## 2. 设计原则与非目标

### 2.1 设计原则

1. GitHub 是任务队列、状态存储、审计记录和通知中心。
2. 自建实现只有一个 Python 状态循环。
3. Codex 使用现有 ChatGPT/Codex 登录，不依赖 OpenAI API Key。
4. Kimi 使用本地 OpenCode 已配置的 API 凭据。
5. 修改者与评审者可以交换，但同一轮职责必须分离。
6. 默认最多 5 轮，达到上限必须停止并通知人。
7. 模型不负责 Git commit、push、PR 状态或 Label；这些操作统一由编排器完成。
8. 默认不自动合并、不 force-push。
9. 只支持可信仓库和可信触发者。
10. 日志优先可观测，同时必须脱敏。

### 2.2 非目标

方案不处理以下问题：

- 公共 Fork PR 的自动执行
- 无人监管的自动合并
- 跨组织的通用 SaaS 服务
- 任意模型提供商路由
- 模型费用统计平台
- Web 管理后台
- 原始、未公开的模型内部思维链

## 3. 最小仓库结构

### 3.1 中央工作流仓库

```text
agent-workflow/
├── .github/
│   └── workflows/
│       └── agent-loop.yml       # reusable workflow
└── agent/
    ├── action.yml               # composite action 入口
    ├── agent_loop.py            # 唯一的编排程序
    └── review.schema.json       # 统一评审输出结构
```

职责划分：

| 文件 | 唯一职责 |
|---|---|
| `agent-loop.yml` | 声明输入、权限、Runner、并发控制和 Artifact 上传 |
| `action.yml` | 把 reusable workflow 输入传给编排器 |
| `agent_loop.py` | 调用 CLI、执行轮次、测试、Git 和 PR 状态操作 |
| `review.schema.json` | 约束 Kimi 与 Codex 的评审输出 |

`agent_loop.py` 只使用 Python 标准库，通过 `subprocess` 调用 `git`、`gh`、`opencode` 和 `codex`。不引入 Flask、PyJWT、PyYAML 或 JSON Schema 第三方库；运行时字段校验由编排器直接完成。

### 3.2 目标仓库

```text
target-repo/
├── .github/
│   └── workflows/
│       └── agent-task.yml       # 只声明输入和中央 workflow 调用
├── AGENTS.md                    # 可选，仓库级共同规则
└── .plans/
    └── task-name.md             # 任务计划与验收标准
```

目标仓库无需额外的 `.workflow.yml`。配置来自 reusable workflow 的显式输入，默认值统一维护在中央仓库。

### 3.3 指令与 Skill

编排器不加载、合并或改写 Skill：

- 两个 Agent 都适用的仓库规则写入 `AGENTS.md`。
- 单次任务的需求和验收标准写入 `.plans/<task>.md`。
- Codex 专用 Skill 使用 Codex 原生 Skill。
- OpenCode 专用能力使用 OpenCode 原生 Agent/Skill。
- 编排器只传递计划、Diff、测试结果和上一轮评审。

这避免维护第二套与两个 CLI 原生能力重复的 Skill 系统。

## 4. 本地运行环境

### 4.1 Runner

在一台持续在线的本地电脑上安装 organization 级 self-hosted runner，并添加专用 Label：

```text
self-hosted
agent-loop
```

Runner 加入专用 Runner Group，只允许指定的可信仓库使用。中央 reusable workflow 固定使用：

```yaml
runs-on: [self-hosted, agent-loop]
```

建议为 Runner 创建专用操作系统用户。该用户不保存个人 SSH Key、云厂商凭据或其他与本工作流无关的秘密。

### 4.2 Codex 登录

使用运行 Runner 的同一操作系统用户完成一次：

```bash
codex login
codex login status
```

Codex CLI 复用本机缓存的 ChatGPT 登录状态，并在活跃使用期间刷新登录令牌。工作流不得复制、打印或上传 Codex 登录文件。

Codex 通过 `codex exec` 非交互运行：

- 修改角色：`--sandbox workspace-write`
- 评审角色：`--sandbox read-only`
- 自动化日志：`--json`
- 结构化评审：`--output-schema`
- 不保留会话：`--ephemeral`

### 4.3 OpenCode 登录

使用相同 Runner 用户预先配置 Kimi：

```bash
opencode auth login
opencode auth list
```

方案复用本地 OpenCode 凭据，不要求把 Kimi API Key 保存为 GitHub Secret。这样 GitHub Actions 工作流本身不持有模型密钥。

临时 Runner 和 GitHub Secret 注入模型凭据不在方案范围内。

### 4.4 本机工作目录

Runner 在 GitHub Actions 自己的 `_work` 目录中 checkout 仓库。模型不得直接使用用户日常开发目录。

每个任务结束后保留 Git 历史和 GitHub Artifact，但工作目录可以由 Runner 正常清理。任务约束为业务代码只能写入工作区；编排器一旦检测到越界修改，就按安全错误转人工。

这里的“工作区边界”指业务代码修改只能发生在 Actions checkout 中。CLI 自身的认证缓存、运行缓存和 Runner 临时目录不属于业务代码修改。方案通过 Agent 权限配置、Codex sandbox、独立 Runner 用户和执行后 Diff 校验降低越界风险；若没有 VM/容器隔离，则不声称能够从操作系统层面绝对阻止所有进程写入临时目录。

## 5. 目标仓库接入

### 5.1 调用入口

目标仓库只保留一个手动入口。示例使用中央仓库受保护的默认分支 `main`：

```yaml
name: Agent task

on:
  workflow_dispatch:
    inputs:
      plan:
        description: Path to the task plan
        required: true
        type: string
      implementer:
        description: Agent that modifies code
        required: true
        default: kimi
        type: choice
        options: [kimi, codex]
      reviewer:
        description: Agent that reviews code
        required: true
        default: codex
        type: choice
        options: [codex, kimi]
      max_rounds:
        description: Maximum rounds, hard capped at 5
        required: true
        default: 5
        type: number
      test_command:
        description: Project verification command
        required: false
        type: string
      resume_pr:
        description: Existing PR number to resume, or 0
        required: true
        default: 0
        type: number
      accept_head_sha:
        description: Exact current PR HEAD to accept after manual edits
        required: false
        type: string
      notify_user:
        description: GitHub username to notify; defaults to actor
        required: false
        type: string

permissions:
  contents: write
  pull-requests: write
  issues: write
  actions: read

jobs:
  agent:
    uses: my-org/agent-workflow/.github/workflows/agent-loop.yml@main
    with:
      plan: ${{ inputs.plan }}
      implementer: ${{ inputs.implementer }}
      reviewer: ${{ inputs.reviewer }}
      max_rounds: ${{ inputs.max_rounds }}
      test_command: ${{ inputs.test_command }}
      resume_pr: ${{ inputs.resume_pr }}
      accept_head_sha: ${{ inputs.accept_head_sha }}
      notify_user: ${{ inputs.notify_user }}
```

中央仓库的 `main` 分支必须启用保护规则，只允许经 PR 评审修改。若组织更重视供应链不可变性，可改为固定 commit SHA。

### 5.2 触发限制

唯一的任务触发方式是 `workflow_dispatch`：

- 不监听任意 Push。
- 不监听 Fork PR。
- 不解析 Issue 或 PR 中的斜杠命令。
- 不允许模型生成的 GitHub 事件递归触发新任务。

触发者必须对目标仓库具有 Write、Maintain 或 Admin 权限。编排器在执行模型前通过 GitHub API 再次验证权限。

目标仓库还必须在 Actions 设置中允许 `GITHUB_TOKEN` 创建 Pull Request。由 `GITHUB_TOKEN` 创建或更新 PR 时，GitHub 会把对应的 `pull_request` workflow run 置于等待批准状态；具有写权限的人需要在 PR 中选择 **Approve workflows to run**。自动循环以内置 `test_command` 作为验证依据，仓库原有 PR CI 可以在 `agent:done` 后由人批准并作为合并前检查。

方案不使用 GitHub App 或 PAT 绕过这项批准，因为这会增加凭据和组件。

## 6. 输入配置

### 6.1 必要输入

| 输入 | 默认值 | 约束 |
|---|---:|---|
| `plan` | 无 | 必须位于仓库内且文件存在 |
| `implementer` | `kimi` | `kimi` 或 `codex` |
| `reviewer` | `codex` | `kimi` 或 `codex` |
| `max_rounds` | `5` | 1–5，超过 5 强制按 5 处理 |
| `test_command` | 空 | 为空时记录“未配置项目测试” |
| `resume_pr` | `0` | 大于 0 时恢复已有 PR |
| `accept_head_sha` | 空 | PR 被人工修改后，必须显式填写当前完整 SHA |
| `notify_user` | 触发者 | GitHub 用户名 |

修改者和评审者必须不同。支持两个方向：

```yaml
# 默认
implementer: kimi
reviewer: codex
```

```yaml
# 交换角色
implementer: codex
reviewer: kimi
```

### 6.2 固定安全默认值

```yaml
max_rounds_hard_limit: 5
agent_timeout_minutes: 45
infrastructure_retry: 1
auto_merge: false
allow_fork: false
artifact_retention_days: 14
```

这些值由中央 workflow 控制，不允许目标任务放宽 `max_rounds_hard_limit`、`auto_merge` 或 `allow_fork`。

## 7. 执行流程

### 7.1 预检

在调用模型前依次检查：

1. 触发者具有写权限。
2. Job 已被 GitHub 调度到带 `agent-loop` Label 的专用 Runner；仓库允许列表由 Runner Group 在调度层强制执行。
3. `plan` 路径位于仓库内且存在。
4. `implementer` 与 `reviewer` 合法且不同。
5. `max_rounds` 位于 1–5。
6. `git`、`gh`、`opencode`、`codex` 和 Python 可执行。
7. 使用 Job 的短期 `GITHUB_TOKEN` 调用 GitHub API 成功，且 `codex login status` 和 `opencode auth list` 可用。
8. 工作目录没有上一个任务残留的未提交修改。
9. 当前执行来自默认分支中的工作流定义。

任何预检失败都不调用模型，直接创建清晰的 Job Summary 并通知人工。

### 7.2 创建任务

新任务：

1. 从仓库默认分支创建 `agent/<run-id>-<task-slug>`。
2. 创建并推送一个不改变文件树的启动提交，使任务在第一次模型调用前就有可恢复的远端分支。
3. 创建 Draft PR。
4. 自动确保三个状态 Label 存在。
5. 添加 `agent:running`。
6. 创建唯一的工作流状态评论。

启动提交消息固定为：

```text
[agent] <task-slug>: start run <run-id>
```

恢复任务：

1. 读取 `resume_pr` 对应的状态评论。
2. 校验评论中的 `head_sha` 与当前 PR HEAD 一致。
3. SHA 一致时从下一步安全状态继续。
4. SHA 不一致且 `accept_head_sha` 为空或不等于当前完整 SHA 时停止，避免覆盖人工修改。
5. SHA 不一致但具有写权限的触发者显式传入正确 `accept_head_sha` 时，把当前 HEAD 记录为新的恢复起点。

### 7.3 一轮的定义

一轮从修改者开始，到以下任一结果结束：

1. 测试失败；
2. 评审者返回 `approved`；
3. 评审者返回 `needs_work`；
4. 评审者返回 `disputed`；
5. 修改者没有产生有效 Diff。

测试失败属于有效的模型尝试，会消耗一轮；此时跳过评审，把测试日志直接交给下一轮修改者。CLI 超时、网络错误或输出解析错误属于基础设施错误，原地重试一次，不消耗新轮次。

### 7.4 修改阶段

编排器向修改者提供：

- 完整任务计划
- `AGENTS.md` 和 Agent 原生指令
- 当前轮次
- 上一轮结构化问题
- 上一轮测试错误
- 当前分支和目标分支
- 明确的工作区写入边界

修改者只负责修改工作区。它不执行：

- Git commit
- Git push
- 创建或修改 PR
- 修改 Labels
- 合并分支

修改结束后，编排器：

1. 检查 CLI 退出状态。
2. 获取 `git diff`。
3. 拒绝工作区外路径、Git 元数据和工作流权限修改。
4. 检查是否存在有效变更。
5. 运行 `test_command`。
6. 提交并推送本轮变更。

只要存在合法 Diff，本轮即使测试失败也会提交到任务分支，以便 Runner 中断后恢复。PR 保持 Draft，失败的中间提交不会自动合并。

提交消息格式：

```text
[agent] <task-slug>: round <N> by <implementer>
```

### 7.5 测试阶段

如果配置了测试命令：

- 测试通过：进入评审。
- 测试失败：保存日志并进入下一轮修改。
- 测试超时或 Runner 故障：按基础设施错误处理。

如果没有配置测试命令，评审结果不能表述为“测试通过”，PR Summary 必须明确标记“未配置项目测试”。

### 7.6 评审阶段

评审者获得：

- 任务计划与验收标准
- 默认分支到当前 HEAD 的 Diff
- 当前轮次提交
- 测试命令与测试结果
- 上一轮问题及处理状态
- 只读权限

评审者必须只返回符合 `review.schema.json` 的结果。评审者不得修改主工作区。

Codex 使用只读 sandbox。OpenCode 作为评审者时使用中央 Action 生成的只读配置，并在独立、可丢弃的审查目录中运行；任何修改均不进入任务分支。

### 7.7 评审输出

统一结构：

```json
{
  "verdict": "approved",
  "summary": "实现满足任务计划和验收标准。",
  "issues": []
}
```

需要修改：

```json
{
  "verdict": "needs_work",
  "summary": "仍有两个必须修复的问题。",
  "issues": [
    {
      "file": "src/example.ts",
      "line": 42,
      "severity": "major",
      "description": "错误路径没有释放资源。"
    }
  ]
}
```

Schema 约束：

```json
{
  "type": "object",
  "properties": {
    "verdict": {
      "type": "string",
      "enum": ["approved", "needs_work", "disputed"]
    },
    "summary": {
      "type": "string"
    },
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "file": {"type": "string"},
          "line": {"type": "integer", "minimum": 1},
          "severity": {
            "type": "string",
            "enum": ["critical", "major", "minor"]
          },
          "description": {"type": "string"}
        },
        "required": ["file", "line", "severity", "description"],
        "additionalProperties": false
      }
    }
  },
  "required": ["verdict", "summary", "issues"],
  "additionalProperties": false
}
```

编排器还必须验证：

- `approved` 时 `issues` 必须为空。
- Issue 文件路径必须位于仓库内。
- Issue 数量和单条描述长度不得无限增长。
- 输出大小不得超过中央 workflow 的固定上限。

### 7.8 Verdict 处理

| Verdict | 动作 |
|---|---|
| `approved` | 停止循环，设置 `agent:done`，把 Draft PR 标记 Ready for Review |
| `needs_work` | 将 Issues 交给下一轮修改者 |
| `disputed` | 立即设置 `agent:needs-human`，不继续自动尝试 |

达到第 5 轮仍未 `approved` 时，无条件转人工。

## 8. GitHub 状态模型

### 8.1 Labels

只使用三个 Label，并由编排器按需创建：

| Label | 含义 |
|---|---|
| `agent:running` | 自动循环进行中 |
| `agent:done` | 自动循环已通过，等待人工合并 |
| `agent:needs-human` | 达到上限、争议或无法恢复 |

同一 PR 同时只能存在一个 `agent:*` 状态 Label。

### 8.2 状态评论

每个 PR 只有一个可更新的状态评论。可见部分展示摘要，隐藏部分保存机器状态：

```html
<!-- agent-loop-state
{
  "schema_version": 1,
  "run_id": "123456",
  "plan": ".plans/task-name.md",
  "status": "reviewing",
  "round": 2,
  "implementer": "kimi",
  "reviewer": "codex",
  "base_sha": "abc123",
  "head_sha": "def456",
  "last_verdict": "needs_work"
}
-->
```

状态评论不是安全凭据，只是可恢复的协调状态。编排器恢复时必须同时校验 PR、分支和 SHA，不能盲目信任评论内容。

### 8.3 并发

使用 GitHub Actions `concurrency`：

```text
agent-loop:<repository>:<pr-or-plan>
```

`cancel-in-progress` 固定为 `false`，避免新触发静默终止正在执行的模型。重复任务保持排队，预检时再判断是否应退出。

## 9. Agent 适配

### 9.1 Codex

评审示意：

```bash
codex exec \
  --ephemeral \
  --sandbox read-only \
  --json \
  --output-schema review.schema.json \
  --output-last-message codex-review.json \
  -
```

修改示意：

```bash
codex exec \
  --ephemeral \
  --sandbox workspace-write \
  --json \
  -
```

Prompt 从 stdin 传入，避免超长命令行和 shell 转义问题。

### 9.2 OpenCode/Kimi

示意：

```bash
opencode run \
  --model "<configured-kimi-model>" \
  --format json \
  --thinking \
  --print-logs \
  --log-level INFO \
  --dir "$GITHUB_WORKSPACE" \
  "<prompt>"
```

实际调用由 Python `subprocess` 参数数组执行，不通过 shell 拼接。

中央 Action 为 OpenCode 生成最小权限配置：

- Implementer 允许仓库内 read/edit/search，默认不允许访问仓库外路径。
- Reviewer 禁止 edit，并在可丢弃目录中运行。
- 项目测试只由编排器运行，不把测试命令交给 OpenCode 的 Bash 工具。

OpenCode 评审结果从 JSON 事件流的最终 Agent 消息中提取，再由编排器校验。若最终消息不是合法 JSON，原地重试一次；仍不合法则转人工。

### 9.3 会话策略

每轮使用独立、短生命周期调用：

- 降低跨任务污染风险。
- 日志和计费边界清晰。
- Runner 中断后容易恢复。

方案不保存 Codex session ID 或 OpenCode session ID。

## 10. 日志与可观测性

### 10.1 可记录内容

工作流记录两个 CLI 对外暴露的：

- Agent 消息
- reasoning summary 或 thinking block
- 工具调用
- Shell 命令及结果
- 文件修改事件
- 测试输出
- MCP 调用
- Web 搜索事件
- Token 用量
- 最终输出
- 结构化评审结果

方案不承诺取得模型服务未返回的原始内部思维链。`--thinking` 和 Codex reasoning 事件只能展示提供商与客户端明确公开的内容。

### 10.2 日志目录

```text
agent-logs/
├── run.json
├── round-01/
│   ├── implementer-events.jsonl
│   ├── implementer-final.md
│   ├── tests.log
│   ├── review-diff.patch
│   ├── reviewer-events.jsonl
│   └── reviewer-final.json
├── round-02/
│   └── <same files as round-01>
└── summary.json
```

### 10.3 实时输出

编排器逐行读取两个 CLI 的 stdout/stderr：

1. 解析 JSON/JSONL 事件。
2. 对每行做脱敏。
3. 写入本地日志文件。
4. 同时输出到 GitHub Actions 控制台。
5. 使用 Round 和 Agent 分组，便于阅读。

不得先把未脱敏日志直接打印到 Actions。

### 10.4 Artifact 与 PR 评论

- Actions Artifact 保存脱敏后的完整事件日志，默认 14 天。
- PR 评论只展示轮次、测试结果、Verdict、问题摘要和 Artifact 链接。
- Job Summary 展示整个任务的时间线。
- 不把完整 JSONL 写入 PR 评论。
- 不上传未脱敏原始日志。

### 10.5 脱敏

脱敏至少覆盖：

- Kimi API Key
- Authorization Header
- Cookie
- GitHub Token
- Codex access token 和登录缓存内容
- OpenCode 凭据文件内容
- 本机用户目录绝对路径
- Prompt 或工具输出中命中的已知 Secret 值

如果日志脱敏器失败，宁可不上传日志，也不能上传原始内容。

## 11. 错误与恢复

### 11.1 处理矩阵

| 情况 | 自动处理 | 是否消耗轮次 |
|---|---|---:|
| CLI 网络错误、超时、异常退出 | 回滚到本轮开始 SHA，原地重试一次 | 否 |
| 评审 JSON 无法解析 | 使用纠错 Prompt 原地重试一次 | 否 |
| 测试失败 | 保存日志，进入下一轮修改 | 是 |
| 修改者没有产生 Diff | 再提示一次；仍无 Diff 则转人工 | 是 |
| 连续两轮没有有效进展 | 转人工 | 是 |
| `disputed` | 立即转人工 | 是 |
| 登录失效或鉴权失败 | 立即转人工 | 否 |
| Git 冲突或 HEAD 被改写 | 立即转人工 | 否 |
| 第 5 轮仍未通过 | 转人工 | 是 |
| Runner 离线 | 任务保持排队 | 否 |

### 11.2 人工介入

转人工时：

1. 移除 `agent:running`。
2. 添加 `agent:needs-human`。
3. 在 PR 中 `@notify_user`。
4. 写明停止原因、当前轮次、未解决问题和 Artifact 链接。
5. 保留 PR 和任务分支。
6. 不自动回滚已经提交的有效修改。

人工可以：

- 修改代码后重新触发并传入 `resume_pr`。
- 交换修改者和评审者。
- 调整测试命令。
- 关闭 PR 结束任务。

恢复前必须比较状态评论中的 `head_sha`。如果人工已经修改分支，编排器要求明确以新 HEAD 作为恢复起点，不能静默覆盖。

## 12. 安全边界

### 12.1 仓库与触发者

- 只支持 private/internal 或其他完全可信的仓库。
- 不在公共 Fork PR 上运行 self-hosted runner。
- Runner Group 只允许明确列出的仓库。
- 只允许默认分支中的固定 workflow 调用中央 workflow。
- 触发者必须拥有写权限。

### 12.2 本地电脑

- 推荐独立操作系统用户运行 Runner。
- Runner 用户只保存本工作流需要的 Codex/OpenCode 登录状态。
- 不让 Runner 访问个人开发目录、SSH Agent、浏览器 Profile 或云凭据。
- 模型只操作 Actions checkout 目录。
- 项目测试可能执行仓库代码，因此只允许运行可信仓库中的任务。

处理不可信代码必须增加一次性 VM/容器隔离，不在方案范围内。

### 12.3 Git 与 GitHub

- `actions/checkout` 使用 `persist-credentials: false`。
- Git push 由编排器使用当前 Job 的短期 `GITHUB_TOKEN` 完成。
- 编排器只在单个 `gh`/`git` 子进程中注入短期 GitHub Token。
- 调用模型和项目测试时显式移除 `GH_TOKEN`、`GITHUB_TOKEN` 等 GitHub 凭据环境变量。
- 禁止 force-push。
- 禁止直接写默认分支。
- 禁止自动合并。
- 禁止自动删除任务分支。
- 修改 `.github/workflows/**`、Runner 配置或权限文件默认转人工。

### 12.4 Agent 权限

- Codex Reviewer：read-only sandbox。
- Codex Implementer：workspace-write sandbox。
- OpenCode Reviewer：只读配置 + 可丢弃审查目录。
- OpenCode Implementer：仅当前 checkout 目录可写。
- 编排器在每次 Agent 返回后校验实际 Diff。

## 13. 多仓库复用

organization 级 Runner 可以服务多个目标仓库。每个目标仓库只做三件事：

1. 加入允许使用 Runner Group 的仓库列表。
2. 添加轻量 `agent-task.yml`。
3. 按需添加 `AGENTS.md` 和 `.plans/`。

中央仓库统一维护：

- 循环逻辑
- Prompt 模板
- Review Schema
- 日志格式
- 脱敏规则
- 错误策略
- 安全上限

目标仓库不复制 Python 实现。中央 `main` 更新后，所有引用该受保护分支的仓库使用同一份实现。

## 14. 测试方案

### 14.1 编排器单元测试

使用 Python 标准库 `unittest`，通过临时目录和假的 `opencode`、`codex`、`git`、`gh` 可执行文件测试：

1. 第一轮通过。
2. 三轮后通过。
3. Kimi 修改、Codex 评审。
4. Codex 修改、Kimi 评审。
5. 第 5 轮转人工。
6. `disputed` 转人工。
7. 非法 JSON 重试。
8. CLI 超时和异常退出。
9. 没有有效 Diff。
10. 测试失败进入下一轮。
11. SHA 不一致时拒绝恢复。
12. Runner 中断后按状态评论恢复。
13. 重复触发被 concurrency 串行化。
14. 日志脱敏。

假的 Agent 只输出预设事件、修改测试文件或模拟错误，不产生模型费用。

### 14.2 Contract 测试

对 `review.schema.json` 验证：

- 三种合法 Verdict。
- `approved` 时 Issues 为空。
- 必要字段缺失。
- 未知 Verdict 或 Severity。
- 非法和越界路径。
- 超大输出。
- 非 JSON 输出。

Codex 使用原生 `--output-schema`；OpenCode 最终消息由相同的编排器校验逻辑验证。

### 14.3 私有仓库集成测试

使用一个专用私有仓库和本地 Runner：

1. Kimi 修改一个简单文件。
2. Codex 评审并要求一次修改。
3. Kimi 修正。
4. Codex 通过。
5. 验证提交、PR、Labels、状态评论、Actions 日志和 Artifact。
6. 交换角色再执行一次。
7. 模拟第 5 轮失败。
8. 模拟 Runner 重启并恢复。
9. 确认日志中没有模型凭据、GitHub Token 或本机绝对路径。

## 15. 验收标准

实现完成必须满足：

- OpenCode/Kimi 和 Codex 都能承担修改者或评审者。
- Codex 可使用本地 ChatGPT 登录运行，不需要 OpenAI API Key。
- 单任务永远不超过 5 轮。
- 测试失败、评审问题和争议都能进入正确状态。
- 达到上限后自动通知指定 GitHub 用户。
- Actions 控制台实时展示脱敏后的 Agent 事件和输出。
- 每轮 JSONL、测试日志、Diff 和最终结果可从 Artifact 下载。
- 不声称或伪造未公开的模型内部思维链。
- Runner 重启后可从 PR 状态恢复。
- 业务代码修改只发生在 Actions checkout 中；CLI 自身缓存和 Runner 临时文件除外。
- 不自动合并、不 force-push。
- 不在公共 Fork PR 中执行。
- 同一中央工作流可被多个目标仓库复用。
- 目标仓库不需要 GitHub App、Webhook 服务或自建 Skill Loader。

## 16. 实施顺序

实施保持最小闭环，分三步：

1. **本地单仓库闭环**

   完成 Runner、两种 CLI 适配、五轮循环、测试和本地日志。

2. **GitHub 状态与恢复**

   加入 Draft PR、三个 Labels、状态评论、Artifact、通知、`resume_pr` 和显式 SHA 接受机制。

3. **中央复用**

   封装 composite action 与 reusable workflow，接入第二个目标仓库验证复用。

只有前一步验收通过后才进入下一步。方案不同时建设可选优化项。

## 17. 官方能力依据

- GitHub self-hosted runner 主动连接 GitHub 获取任务：

  <https://docs.github.com/en/actions/reference/runners/self-hosted-runners>
- GitHub 对 self-hosted runner 和不可信 PR 的安全警告：

  <https://docs.github.com/en/actions/reference/security/secure-use>
- GitHub 组织内共享 reusable workflow：

  <https://docs.github.com/en/actions/how-tos/reuse-automations/share-with-your-organization>
- `GITHUB_TOKEN` 创建或更新 PR 时的 workflow 触发与批准规则：

  <https://docs.github.com/en/actions/concepts/security/github_token>
- Codex CLI ChatGPT 登录与本地凭据缓存：

  <https://developers.openai.com/codex/auth>
- Codex `exec` 非交互、JSONL 与结构化输出：

  <https://developers.openai.com/codex/noninteractive>
- OpenCode `run`、JSON 事件与 thinking blocks：

  <https://opencode.ai/docs/cli/>
