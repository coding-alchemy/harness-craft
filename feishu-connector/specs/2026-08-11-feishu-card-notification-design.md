# 飞书任务通知消息卡片设计

## 目标

将自动通知和任务通知改为飞书消息卡片，让用户从标题识别项目、对话框和状态，在正文阅读 Agent 提供的结构化 Markdown 输出。

显式 `send --message` 继续发送用户指定的纯文本。本次只替换任务通知。

## 已确认决策

- 标题格式为 `<项目名>-<对话框名>-<状态中文>`。
- 项目名、对话框名和正文由 Agent 显式传入，不自动读取 Codex 或 OpenCode 元数据。
- 状态只有任务完成、任务失败和待确认；手动取消不通知。
- 正文直接使用飞书 Markdown，不定义任务名、仓库、分支或来源等重复字段。
- 使用自包含 `interactive` 卡片，不依赖飞书后台模板。
- 不保留旧任务参数的兼容层。

## 接口

任务命令替换为：

```bash
python3 "$ENTRY" task \
  --status success \
  --project "HETU" \
  --conversation "个股-二期-架构师" \
  --content "- 完成架构设计"
```

参数：

- `--status`：只接受 `success`、`failure`、`confirm`。
- `--project`：标题中的项目名。
- `--conversation`：标题中的对话框名。
- `--content`：飞书 Markdown 正文。
- `--auto`：继续受 `notification.autoNotify` 门控。

状态映射：

| CLI 状态 | 标题文字 | 标题颜色 |
| --- | --- | --- |
| `success` | `任务完成` | `green` |
| `failure` | `任务失败` | `red` |
| `confirm` | `待确认` | `orange` |

安全 stdin 白名单同步改为：

```json
{
  "flow": "task-auto",
  "status": "success",
  "project": "HETU",
  "conversation": "个股-二期-架构师",
  "content": "- 完成架构设计\n- 评审通过"
}
```

旧字段 `--task`、`--summary`、`--repo`、`--branch` 和 `--source` 直接移除。显式纯文本 `send --message`、配置、环境变量和退出码不变。

## 卡片格式

标题示例：

```text
HETU-个股-二期-架构师-任务完成
HETU-个股-二期-架构师-待确认
```

卡片结构固定为一个标题区和一个 Markdown 正文区：

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "template": "green",
    "title": {
      "tag": "plain_text",
      "content": "HETU-个股-二期-架构师-任务完成"
    }
  },
  "elements": [
    {
      "tag": "div",
      "text": {
        "tag": "lark_md",
        "content": "- 完成架构设计\n- 评审通过"
      }
    }
  ]
}
```

连接器不解析或重组正文。Agent 可使用简单结构：

```markdown
**结果**

- 完成架构设计
- 评审通过

**下一步**

- 等待合并
```

待确认正文应直接说明需要用户处理的事项和选择。

## 行为与安全边界

- 项目名和对话框名必须非空且为单行有效 Unicode；拒绝换行和 NUL。
- 正文必须非空且为有效 Unicode；允许 Markdown 换行。
- 标题使用 `plain_text`，正文使用 `lark_md`；两者都不经过 Shell、模板或代码求值。
- stdin 仍由 Python 直接解析，动态值不得进入 Shell 命令字符串。
- `task --auto` 关闭时成功 no-op，不构造客户端、不联网。
- 用户手动取消任务时，Skill 不调用连接器。
- 任务失败只发送用户可见原因，不附内部推理、完整日志或敏感上下文。
- 通知失败不改变原任务结果；每个任务结果或待确认节点最多通知一次。
- 网络重试继续复用同一个 UUID；不同逻辑发送使用不同 UUID。
- 超出飞书卡片大小限制时返回现有远程错误，不截断或拆分正文。

## 实现边界

现有 `render_task_message()` 替换为 `render_task_card()`，负责输入校验、标题拼接、状态映射和固定卡片结构。

保留 `FeishuClient.send_text()`，新增 `FeishuClient.send_card()`。两者复用私有发送流程中的 Token、固定 Open ID、UUID、重试和错误分类。`send_card()` 固定发送 `msg_type=interactive`，不扩展为任意消息类型客户端。

Skill 目录仍是唯一 Python 运行时源码；Python 3.9+ 标准库、安装文件清单和用户级安装方式不变。Codex 与 OpenCode 使用相同的显式参数接口，不增加平台 Adapter。

升级命令：

```bash
python3 feishu-connector/install_skill.py --force
```

## 验证标准

离线测试必须证明：

- 三种状态生成正确的中文标题和颜色；
- 标题严格使用 `<项目>-<对话框>-<状态>`；
- Markdown 正文原样进入精确的 `interactive` 卡片结构；
- 项目名、对话框名和正文的空值、换行、NUL 与 Unicode 边界正确；
- stdin 只接受新的白名单字段，且不经过 Shell；
- 自动通知关闭、手动取消和通知失败保持既有附属通知语义；
- 卡片重试复用 UUID；
- `send --message` 仍发送纯文本。

测试使用 Mock，不访问真实飞书。真实验收仅向测试用户分别发送完成、失败和待确认卡片。

同步更新：

- `feishu-connector/skills/feishu-notify/SKILL.md`
- `feishu-connector/README.md`
- `feishu-connector/docs/USAGE.md`
- `feishu-connector/specs/feishu-connector.md`

所有用户审阅文档使用中文。

## 非目标

- 群 Webhook、群聊、多接收人或动态接收人；
- 按钮回调、表单、图片或附件；
- 自动获取对话框名；
- 自定义颜色、任意卡片 JSON 或后台模板 ID；
- 自动拆分、截断或汇总正文。
