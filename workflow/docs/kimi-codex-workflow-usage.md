# Kimi-Codex 工作流使用指南

> 状态：设计评审稿，工作流尚未实现
>
> 设计规范：[Kimi-Codex 工作流](../specs/kimi-codex-workflow.md)

本文从使用者视角说明完成一次任务需要做什么。示例假设中央工作流仓库为 `my-org/agent-workflow`，实际使用时需要替换为真实组织和仓库名。

## 1. 使用体验概览

配置完成后，普通任务只需要：

1. 在目标仓库提交一份 `.plans/<task>.md`。
2. 在 GitHub Actions 页面选择该计划并点击 **Run workflow**。
3. 查看自动创建的 Draft PR，等待通过或人工介入通知。
4. 人工批准仓库原有 PR CI、检查结果并合并 PR。

不需要手动打开 Codex 或 OpenCode，也不需要在两个模型之间复制 Prompt、Diff 或评审意见。本地电脑只需保持 GitHub self-hosted runner 在线。

| 场景 | 使用者需要做的事 |
|---|---|
| 新任务 | 提交计划并触发一次 workflow |
| 自动通过 | 检查并合并 Ready for Review 的 PR |
| 五轮未通过或发生争议 | 根据 PR 中的问题人工修改或结束任务 |
| Runner 或 CLI 中断 | 恢复 Runner 后，使用 PR 编号续跑 |
| 人工修改了任务分支 | 续跑时额外确认当前完整 HEAD SHA |

## 2. 角色

### 2.1 一次性管理员

负责：

- 创建中央工作流仓库。
- 配置 organization 级 self-hosted runner 和 Runner Group。
- 保护中央仓库的 `main` 分支。
- 决定哪些可信仓库可以使用 Runner。

### 2.2 本地 Runner 维护者

负责：

- 保持本地电脑和 Runner 在线。
- 安装并更新 `git`、GitHub CLI、Python、Codex CLI 和 OpenCode。
- 使用 Runner 的操作系统账号登录 Codex 和 OpenCode/Kimi。
- 在登录失效时重新认证。

### 2.3 任务使用者

负责：

- 编写任务计划。
- 从 GitHub Actions 手动触发任务。
- 查看 PR、日志和 Artifact。
- 决定是否合并，或在自动循环停止后人工处理。

同一个人可以同时承担以上角色。

## 3. 一次性本地配置

### 3.1 准备专用账号

推荐使用一个专用操作系统账号运行 Runner。该账号应当：

- 可以访问 Runner 的工作目录。
- 不使用个人开发目录作为 Actions checkout。
- 不持有个人 SSH Key、浏览器 Profile、云凭据等无关秘密。
- 是执行 Codex 和 OpenCode 登录的同一个账号。

### 3.2 安装 Runner

在 GitHub organization 的：

```text
Settings → Actions → Runners → New self-hosted runner
```

按 GitHub 页面给出的当前操作系统命令安装 Runner，并添加：

```text
self-hosted
agent-loop
```

两个 Label。然后把 Runner 加入专用 Runner Group，只允许明确选中的可信仓库使用。

将 Runner 安装为系统服务，确保电脑重启后自动恢复。GitHub 页面显示 Runner 为 **Idle** 即表示可以领取任务。

### 3.3 安装命令行工具

使用 Runner 账号确认以下命令可用：

```bash
git --version
gh --version
python3 --version
codex --version
opencode --version
```

工作流的 Python 编排器只使用标准库，不需要创建虚拟环境或安装额外 Python 包。

### 3.4 登录两个 Agent

仍然使用 Runner 账号执行：

```bash
codex login
codex login status
```

Codex 使用现有 ChatGPT/Codex 登录，不需要 OpenAI API Key。

为 OpenCode 配置 Kimi：

```bash
opencode auth login
opencode auth list
```

模型凭据保存在本机 CLI 的认证目录中，不放入目标仓库或 GitHub Actions Secret。

### 3.5 本地配置完成标准

以下条件全部满足后，本地电脑才算准备完成：

- GitHub 中 Runner 状态为 **Idle**。
- Runner 带有 `self-hosted` 和 `agent-loop` Label。
- `codex login status` 成功。
- `opencode auth list` 能看到 Kimi 配置。
- Runner Group 只开放给预期的可信仓库。

Codex App、Codex TUI 和 OpenCode TUI 均不需要保持打开。

## 4. 一次性 GitHub 配置

### 4.1 中央工作流仓库

中央仓库包含：

```text
.github/workflows/agent-loop.yml
agent/action.yml
agent/agent_loop.py
agent/review.schema.json
```

需要完成：

1. 为 `main` 启用分支保护。
2. 在仓库 Actions 设置中允许组织内目标仓库调用 reusable workflow。
3. 在 organization 的 Runner Group 设置中允许目标仓库使用本地 Runner。

中央 workflow 使用以下最小权限：

```yaml
permissions:
  contents: write
  pull-requests: write
  issues: write
  actions: read
```

### 4.2 目标仓库

每个目标仓库添加 `.github/workflows/agent-task.yml`。以下内容可直接作为模板，先替换 `my-org/agent-workflow`：

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

在目标仓库打开：

```text
Settings → Actions → General → Workflow permissions
```

启用 **Allow GitHub Actions to create and approve pull requests**，否则短期 `GITHUB_TOKEN` 无法创建 Draft PR。

为了减少日常输入，建议直接在该文件中为 `test_command` 设置仓库级默认值，例如：

```yaml
      test_command:
        description: Project verification command
        required: true
        default: make test
        type: string
```

目标仓库还可以添加：

- `AGENTS.md`：两个 Agent 都要遵守的长期仓库规则。
- `.plans/`：每次任务的计划和验收标准。

工作流文件必须先进入默认分支，GitHub Actions 页面才会显示手动运行入口。

## 5. 编写任务计划

计划必须已经存在于触发 workflow 的默认分支中。推荐模板：

```markdown
# 任务名称

## 目标

说明要实现的结果以及用户可观察到的行为。

## 范围

- 允许修改的目录或模块
- 明确不处理的内容

## 验收标准

- [ ] 可验证结果一
- [ ] 可验证结果二
- [ ] 现有行为没有回归

## 特别约束

- 兼容性、安全性或性能要求
- 禁止使用的方法
```

示例路径：

```text
.plans/add-health-endpoint.md
```

计划越明确，两个 Agent 往返讨论的轮数越少。验收标准应当描述结果，不要只写“优化代码”或“修复问题”。

## 6. 启动新任务

### 6.1 使用 GitHub 网页

1. 打开目标仓库的 **Actions**。
2. 选择 **Agent task**。
3. 点击 **Run workflow**。
4. 确认运行分支是默认分支。
5. 填写输入并启动。

普通任务推荐输入：

| 输入 | 推荐值 | 说明 |
|---|---|---|
| `plan` | `.plans/add-health-endpoint.md` | 本次任务计划 |
| `implementer` | `kimi` | 负责修改代码 |
| `reviewer` | `codex` | 负责独立评审 |
| `max_rounds` | `5` | 可调低，不可超过 5 |
| `test_command` | 仓库测试命令 | 已设置默认值时无需修改 |
| `resume_pr` | `0` | 新任务固定为 0 |
| `accept_head_sha` | 留空 | 新任务不使用 |
| `notify_user` | 留空 | 默认通知触发者 |

如果希望 Codex 修改、Kimi 评审，只需交换 `implementer` 和 `reviewer`。

### 6.2 使用 GitHub CLI

已在个人电脑登录 GitHub CLI 时，也可以执行：

```bash
gh workflow run agent-task.yml \
  -f plan=.plans/add-health-endpoint.md \
  -f implementer=kimi \
  -f reviewer=codex \
  -f max_rounds=5 \
  -f resume_pr=0
```

GitHub CLI 只是网页触发入口的替代方式，不是工作流必需组件。

该命令默认从目标仓库的默认分支运行；如果要显式指定其他已受信任的分支，再添加 `--ref <branch>`。

## 7. 观察执行过程

Workflow 启动后会：

1. 在本地 Runner 上完成预检。
2. 创建任务分支和 Draft PR。
3. 让修改者修改代码并运行测试。
4. 让评审者检查计划、Diff 和测试结果。
5. 在需要时把问题交给下一轮修改者。
6. 最多执行 5 轮。

可以从三个位置查看进度：

### 7.1 Actions 日志

适合实时观察：

- 当前轮次和当前 Agent。
- CLI 对外提供的 Agent 消息。
- 公开的 reasoning summary 或 thinking block。
- 工具调用、测试结果和最终输出。

控制台只输出经过脱敏的内容。

### 7.2 Draft PR

适合查看任务状态：

- 当前轮次。
- 最近一次测试结果。
- 最新 Verdict 和待解决问题。
- Artifact 链接。
- `agent:running`、`agent:done` 或 `agent:needs-human` Label。

状态更新在同一条 PR 评论中，不会每轮新增大量评论。

### 7.3 Artifact

适合排查完整过程，包含每轮经过脱敏的：

- 修改者 JSONL 事件。
- 修改者最终消息。
- 测试日志。
- 评审 Diff。
- 评审者 JSONL 事件。
- 结构化评审结果。

Artifact 默认保留 14 天。

## 8. 处理运行结果

### 8.1 自动通过

评审者返回 `approved` 后：

- PR Label 变为 `agent:done`。
- Draft PR 变为 Ready for Review。
- 自动循环停止。
- 工作流不会自动合并。

使用者检查代码和 CI 后，按普通 PR 流程合并。

如果目标仓库已有由 `pull_request` 触发的 CI，GitHub 会把这个自动创建或更新的 PR 所产生的 workflow run 置于等待批准状态。建议在 `agent:done` 后，从 PR 合并框选择 **Approve workflows to run**，运行最终分支上的仓库 CI，再决定是否合并。自动循环本身使用 `test_command`，不依赖这些等待批准的 workflow。

### 8.2 需要人工

以下情况会设置 `agent:needs-human` 并 @通知指定用户：

- 第 5 轮仍未通过。
- 评审结论为 `disputed`。
- 登录失效。
- 输出无法解析。
- 没有有效代码变更。
- Git 冲突或检测到分支状态异常。
- 检测到越界或禁止的文件修改。

PR 评论会写明停止原因、当前轮次、未解决问题和日志入口。

### 8.3 结束任务

不准备继续时，直接关闭 PR。工作流不会自动删除分支，便于需要时保留审计记录。

## 9. 恢复任务

### 9.1 未人工修改代码

Runner 重启、临时网络错误或其他中断后：

1. 再次打开 **Run workflow**。
2. 使用原计划和原角色配置。
3. 把 `resume_pr` 设置为已有 PR 编号。
4. 保持 `accept_head_sha` 为空。

编排器验证状态评论、PR 分支和 HEAD 后，从安全状态继续。

### 9.2 已人工修改代码

如果人工已经向任务分支提交代码：

1. 获取 PR 当前完整 HEAD SHA。
2. 再次运行 workflow。
3. 把 `resume_pr` 设置为已有 PR 编号。
4. 把 `accept_head_sha` 设置为该完整 SHA。

使用 GitHub CLI 获取 SHA：

```bash
gh pr view 123 --json headRefOid --jq .headRefOid
```

也可以在 PR 的 **Commits** 页面打开最新提交并复制完整 SHA。

要求精确 SHA 是为了防止 workflow 在用户不知情时接受并覆盖刚发生的人工修改。

## 10. 常见问题

| 现象 | 检查方式 | 处理 |
|---|---|---|
| Job 一直 Queued | GitHub Runner 页面 | 启动本地电脑和 Runner 服务 |
| Codex 鉴权失败 | Runner 账号执行 `codex login status` | 重新执行 `codex login` |
| Kimi 鉴权失败 | Runner 账号执行 `opencode auth list` | 重新执行 `opencode auth login` |
| 看不到 Run workflow | 检查 workflow 是否在默认分支 | 合并 workflow 文件后刷新 Actions |
| 找不到计划 | 检查路径和默认分支 | 先提交 `.plans/<task>.md` |
| 没有项目测试结果 | 检查 `test_command` | 在目标 workflow 中设置默认测试命令 |
| Draft PR 创建失败 | 检查 Actions 的 Workflow permissions | 启用允许 GitHub Actions 创建 PR |
| PR CI 显示 Waiting for approval | 查看 PR 合并框 | 在 `agent:done` 后选择 Approve workflows to run |
| 恢复时 SHA 不一致 | 查看 PR 最新提交 | 人工确认后填写完整 `accept_head_sha` |
| Artifact 中没有内部思维链 | 检查 CLI 实际公开事件 | 只能记录提供商明确返回的 reasoning/thinking 内容 |

## 11. 使用边界

- 只用于可信的 private/internal 仓库。
- 不响应公共 Fork PR。
- 不使用 GitHub Copilot 或 Copilot 模型。
- 不需要 OpenAI API Key。
- 不自动合并、不 force-push。
- 不把模型凭据保存到 GitHub。
- 不保证获得模型未公开的内部思维链。
- 本地电脑离线时，任务会留在 GitHub 队列中等待 Runner。

## 12. 建议的首次验收

第一次接入不要直接运行真实任务。建议在专用私有测试仓库验证：

1. 创建一个只需修改单个文件的计划。
2. 让 Kimi 修改、Codex 评审并至少往返一次。
3. 确认测试、提交、Draft PR、Labels 和状态评论正确。
4. 下载 Artifact，检查事件和输出是否完整且已脱敏。
5. 交换角色再运行一次。
6. 模拟人工提交，然后使用 `resume_pr` 和 `accept_head_sha` 恢复。
7. 确认整个日常流程只需要“提交计划、运行 workflow、审查 PR”。

完成这组验收后，再把 Runner Group 开放给其他可信目标仓库。
