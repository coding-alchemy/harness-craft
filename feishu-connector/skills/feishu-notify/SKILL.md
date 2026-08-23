---
name: feishu-notify
description: 当用户明确要求发送飞书纯文本、富文本或任务通知，或仓库指令要求在任务结果或待确认节点发送仓库自动通知时使用。
---

# 飞书通知

仅在用户明确要求发送消息，或仓库指令启用自动任务通知时使用本 Skill。入口相对当前 `SKILL.md`：`scripts/feishu_notify.py`。

## 调用合同

使用支持 argv 的执行器时，直接调用入口；每个动态值必须是独立 argv，不得拼接 Shell 字符串、插值或交给 Shell 解析。

### 外发授权

用户明确要求“发送飞书消息”“完成后发飞书”或表达同等含义，即构成本次联网与外发授权：向连接器已配置的固定接收人执行一次显式发送，无需再次向用户确认。用户指定正文时只发送用户指定的正文；未指定正文时，只发送任务结果和必要的简短验证信息，例如提交号、测试通过数或产物位置。

本次授权不允许更换、推断或扩大接收人，不得附加完整日志、Diff、凭据、Token、配置值、内部推理或其他未要求上下文，也不自动延续到后续消息。平台安全审批与网络限制仍然有效，不能绕过；投递状态不明时仍不得跨进程重试。

### 执行权限

`send`、`rich` 和实际发送的 `task` 都需要访问飞书网络。用户明确要求发送时，在首个真实发送子命令（`send`、`rich` 或实际发送的 `task`）调用上直接请求执行器提供的沙箱外联网权限；不得以发送子命令先在网络隔离沙箱中试发或探测飞书连通性。`config` 等明确不联网的诊断不计入真实发送调用，可以在沙箱内执行。

使用 Codex 执行器时，在上述首个真实发送子命令调用上设置 `sandbox_permissions=require_escalated`，并说明权限仅用于固定连接器向已配置接收人发送本次消息；执行器支持限制网络目标时，仅允许 `open.feishu.cn:443`。用户的明确发送请求已经构成外发授权，无需再次通过对话确认，但仍须正常发起并接受平台的工具级权限审批，不得绕过审批。

如果联网权限被拒绝或执行器不支持权限升级，停止调用并明确报告消息未发送；不得退回网络隔离沙箱试发，也不得改用其他渠道绕过审批。

路由按下表选择；argv 与网络权限独立：使用独立 argv 或 stdin 只是安全传参方式，绝不授予网络能力。只有连接器在配置允许且实际调用飞书时才联网，stdin 不提供网络能力。

| 场景 | 调用 |
| --- | --- |
| 用户明确要求任务通知 | 显式 `task`，不得添加 `--auto` |
| 仓库规则要求任务结果或待确认自动通知 | `task --auto` |
| 标题、分段、列表、链接或代码等格式信息 | 格式信息优先 `rich` |
| 简单短句 | `send` |

显式 `send` 发送用户指定的纯文本：`python3 scripts/feishu_notify.py send --message "原文"`。不得添加完整日志、Diff、内部推理或其他上下文。

显式 `rich` 发送通用 Markdown 卡片：`python3 scripts/feishu_notify.py rich --title "标题" --content "**正文**"`。它固定为蓝色标题和一个 `lark_md` 正文，不使用任务状态标题。

`task` 发送固定、自包含的 interactive Markdown 消息卡片，只接受 `--status success|failure|confirm`、非空 `--project`、非空 `--conversation`、非空 `--content` 及可选 `--auto`：

```bash
python3 scripts/feishu_notify.py task --auto --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择 A 或 B"
```

项目名和对话框名必须是非空、单行、有效 Unicode，拒绝换行和 NUL；正文必须非空且为有效 Unicode，可包含 Markdown 换行，并且原样传递，不解析、重组、截断或拆分，即使超过飞书限制。不得传入任意消息类型、卡片 JSON 或后台模板。

状态标题严格为 `<项目名>-<对话框名>-<状态中文>`：`success` 为“任务完成”（green），`failure` 为“任务失败”（red），`confirm` 为“待确认”（orange）。消息卡片固定只含 `config.wide_screen_mode`、`header.template`、`header.title`（`plain_text`）及一个正文 `div`（`lark_md`）。

```json
{"config":{"wide_screen_mode":true},"header":{"template":"orange","title":{"tag":"plain_text","content":"HETU-个股-二期-架构师-待确认"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"请选择 A 或 B"}}]}
```

自动通知仅用于仓库指令明确启用的任务结果或待确认节点；手动取消不调用连接器，每个节点最多执行一次。失败正文只能提供用户可见原因，不能包含内部推理、完整日志或敏感上下文；通知失败不得改变原任务结果。stdout 出现 `Feishu message sent` 才表示 `sent`（已发送）；`Feishu notification skipped: autoNotify=false` 表示 `skipped`（未发送）。

## Shell 执行器调用

### Codex 审批可见调用

Codex 使用 POSIX Shell 执行器时，先在任务工作区、网络隔离沙箱内调用 `python3 scripts/feishu_notify.py prepare-shell`；若需要覆盖项目根，在子命令前传入 `--project-root /absolute/project/path`。通过独立 stdin 写入与下文相同的四种白名单 JSON。`prepare-shell` 不读飞书配置、不构造客户端、不联网，也不发送消息。

准备成功后，只移除 stdout 最后的一个换行，将其余命令原样作为新的执行调用，不得重建、补充或重新引用。真实命令设置 `sandbox_permissions=require_escalated`，审批理由只说明连接器向已配置固定接收人发送本次可见正文。正文或其他动态字段变化时必须重新准备并触发新的审批。

命令无法提交、审批拒绝或联网权限被拒绝时，立即报告未发送；不重试、不重建命令，也不回退 stdin、文件或环境变量传参。审批通过后沿用现有发送、自动 no-op、进程内重试和结果判断；只有 stdout 出现 `Feishu message sent` 才报告已发送。

完整正文会出现在 Codex 工具调用、审批记录和可能的会话记录中。继续禁止附加凭据、Token、配置值、完整日志、Diff、内部推理或其他未要求上下文。

### 非 Codex stdin 兼容入口

在不存在审批前 payload 可见性要求的非 Codex 环境中，执行工具有独立 `stdin` 通道时可继续调用 `python3 scripts/feishu_notify.py stdin`。该入口保持 `send`、`rich`、`task`、`task-auto` 四种白名单和现有行为，但不得用于 Codex 的真实发送。

```json
{"flow": "send", "message": "用户指定的原文"}
```

```json
{"flow": "rich", "title": "标题", "content": "**正文**"}
```

```json
{"flow": "task", "status": "success", "project": "HETU", "conversation": "个股-二期-架构师", "content": "已完成"}
```

```json
{"flow": "task-auto", "status": "confirm", "project": "HETU", "conversation": "个股-二期-架构师", "content": "请选择 A 或 B"}
```

## 联网结果与重复风险

网络错误仅以脱敏类别报告：`network.dns`、`network.timeout`、`network.tls`、`network.connection`、`network.unreachable`。它们、限流和服务端错误耗尽进程内重试时返回退出码 `5`；投递状态可能不明，调用方不得跨进程重试，以免重复发送。连接器只在单次逻辑发送内复用 UUID 并最多额外重试两次。
