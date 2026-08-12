---
name: feishu-notify
description: 当用户明确要求发送飞书纯文本消息，或仓库指令要求在任务结果或待确认节点自动发送飞书通知时使用。
---

# 飞书通知

仅在用户明确要求发送消息，或仓库指令启用自动任务通知时使用本 Skill。入口相对当前 `SKILL.md`：`scripts/feishu_notify.py`。

## 调用合同

使用支持 argv 的执行器时，直接调用入口；每个动态值必须是独立 argv，不得拼接 Shell 字符串、插值或交给 Shell 解析。

显式 `send` 发送用户指定的纯文本：`python3 scripts/feishu_notify.py send --message "原文"`。不得添加完整日志、Diff、内部推理或其他上下文。

`task` 发送固定、自包含的 interactive Markdown 消息卡片，只接受 `--status success|failure|confirm`、非空 `--project`、非空 `--conversation`、非空 `--content` 及可选 `--auto`：

```bash
python3 scripts/feishu_notify.py task --auto --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择 A 或 B"
```

项目名和对话框名必须是非空、单行、有效 Unicode，拒绝换行和 NUL；正文必须非空且为有效 Unicode，可包含 Markdown 换行，并且原样传递，不解析、重组、截断或拆分，即使超过飞书限制。不得传入任意消息类型、卡片 JSON 或后台模板。

状态标题严格为 `<项目名>-<对话框名>-<状态中文>`：`success` 为“任务完成”（green），`failure` 为“任务失败”（red），`confirm` 为“待确认”（orange）。消息卡片固定只含 `config.wide_screen_mode`、`header.template`、`header.title`（`plain_text`）及一个正文 `div`（`lark_md`）。

```json
{"config":{"wide_screen_mode":true},"header":{"template":"orange","title":{"tag":"plain_text","content":"HETU-个股-二期-架构师-待确认"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"请选择 A 或 B"}}]}
```

自动通知仅用于仓库指令明确启用的任务结果或待确认节点；手动取消不调用连接器，每个节点最多执行一次。失败正文只能提供用户可见原因，不能包含内部推理、完整日志或敏感上下文；通知失败不得改变原任务结果。

## 仅 Shell 的回退

只有执行工具提供独立 stdin 通道时，才使用固定命令 `python3 scripts/feishu_notify.py stdin`。动态值绝不进入 Shell 命令字符串；stdin 仅接受以下白名单 JSON：

```json
{"flow": "send", "message": "用户指定的原文"}
```

```json
{"flow": "task-auto", "status": "confirm", "project": "HETU", "conversation": "个股-二期-架构师", "content": "请选择 A 或 B"}
```

没有独立 stdin 通道时，不得使用 Shell 回退；改用支持 argv 的执行器。不得读取配置文件、选择接收人或实现 HTTP 请求；这些职责均由入口脚本处理。
