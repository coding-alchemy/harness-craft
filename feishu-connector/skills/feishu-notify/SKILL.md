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

## 仅 Shell 的回退

只有执行工具提供独立 stdin 通道时，才使用固定命令 `python3 scripts/feishu_notify.py stdin`。动态值绝不进入 Shell 命令字符串；stdin 仅接受以下四种白名单 JSON：

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

没有独立 stdin 通道时，不得使用 Shell 回退；改用支持 argv 的执行器。不得读取配置文件、选择接收人或实现 HTTP 请求；这些职责均由入口脚本处理。

## 联网结果与重复风险

网络错误仅以脱敏类别报告：`network.dns`、`network.timeout`、`network.tls`、`network.connection`、`network.unreachable`。它们、限流和服务端错误耗尽进程内重试时返回退出码 `5`；投递状态可能不明，调用方不得跨进程重试，以免重复发送。连接器只在单次逻辑发送内复用 UUID 并最多额外重试两次。
