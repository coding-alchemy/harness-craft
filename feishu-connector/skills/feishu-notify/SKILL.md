---
name: feishu-notify
description: 当用户明确要求发送飞书纯文本消息，或仓库指令要求在任务完成时自动发送飞书通知时使用。
---

# 飞书通知

仅在用户明确要求发送消息，或仓库指令启用自动任务通知时使用本 Skill。入口相对当前 `SKILL.md`：`scripts/feishu_notify.py`。

## 调用契约

使用支持 argv 的执行器时，直接调用入口；将每个动态值作为独立 argv 传递，不得拼接 Shell 字符串、插值或交给 Shell 解析。

发送用户指定原文时，调用 `python3 scripts/feishu_notify.py send --message`，并将原文作为独立 argv。只发送用户指定的原文，不附加完整日志、Diff、内部推理或其他上下文。

自动任务通知时，调用 `python3 scripts/feishu_notify.py task --auto`，并将 `--status`、`--task`、`--summary`、`--repo`、`--branch` 及其值分别作为独立 argv。只发送简短任务摘要；每个最终任务结果最多执行一次自动通知，通知失败不得改变原任务结果。

## 仅 Shell 的回退

只有执行工具提供独立 stdin 通道时，才使用固定命令 `python3 scripts/feishu_notify.py stdin`。不得把动态值放入命令字符串；仅通过 stdin 传入以下白名单 JSON 之一：

```json
{"flow": "send", "message": "用户指定的原文"}
```

```json
{"flow": "task-auto", "status": "success", "task": "简短任务名", "summary": "简短结果", "repo": "仓库名", "branch": "分支名"}
```

没有独立 stdin 通道时，不得使用 Shell 回退；改用支持 argv 的执行器。

不得读取配置文件、选择接收人或实现 HTTP 请求；这些职责均由入口脚本处理。
