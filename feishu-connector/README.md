# 飞书消息连接器

## 能力边界

一期通过飞书**企业自建应用**的机器人，向一个固定 Open ID 发送纯文本私聊。它不使用群机器人 Webhook，不接收消息，不支持群聊、富文本、多用户或动态接收人。

## 飞书端准备

1. 在飞书开发者后台创建企业自建应用。
2. 为应用开启**机器人能力**，并发布包含此能力的应用版本。
3. 申请最小发送权限 `im:message:send_as_bot`。
4. 将固定目标用户加入应用机器人的**可用范围**。
5. 发布后，记录 App ID、App Secret，以及该应用下目标用户的 Open ID。

用户可以在飞书客户端停止接收机器人消息；连接器会将此类错误报告为不可重试的业务错误。请只使用测试应用和测试用户完成验收。

## 本地配置

将 `.env.example` 复制为 `.env`，然后填写以下配置：

```dotenv
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_RECEIVE_OPEN_ID=
FEISHU_AUTO_NOTIFY=false
```

`.env` 已被 Git 忽略。App Secret 不得出现在命令行、日志或提交中；也不要打印 Token、Authorization 或完整 Open ID。进程环境变量会覆盖 `.env` 中的同名值，便于在安全的密钥管理环境中使用。

## 手动发送

用户明确需要发送时，在仓库根目录执行：

```bash
python3 feishu-connector/scripts/feishu_notify.py send --message "测试消息"
```

`send` 会将消息原样作为纯文本发给固定 Open ID，且显式发送不受 `FEISHU_AUTO_NOTIFY` 开关影响。

## 任务通知

任务通知需要五个字段：`--status`、`--task`、`--summary`、`--repo` 和 `--branch`。`--status` 只能为 `success|failure`；消息总是使用固定纯文本格式，包含状态、任务名称、简短摘要、仓库和分支。可选参数 `--source`（默认 `Codex`，可设为 `OpenCode`）为未来 OpenCode 复用预留。

```bash
python3 feishu-connector/scripts/feishu_notify.py task \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "feishu"
```

自动通知应使用安全开关：

```bash
python3 feishu-connector/scripts/feishu_notify.py task --auto \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "feishu"
```

当 `FEISHU_AUTO_NOTIFY=false` 或未配置时，`task --auto` 是成功但不发送的 no-op；不传 `--auto` 的 `task` 仍会发送。

## Codex Skill

让 Codex 读取 `feishu-connector/skills/feishu-notify/SKILL.md`，以便在用户明确要求时调用 `send`。若要使任务结束时默认执行自动通知，项目指令必须明确启用这一自动任务通知约定；它不是 Codex 平台级的全局 Hook。

通知失败时，Skill 只追加一条脱敏警告，**不会改变原任务结果**，也不覆盖原有失败原因。显式发送不依赖自动通知开关。

## 测试

运行默认离线测试：

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

测试默认通过 Mock 运行，**不访问真实飞书**，也不读取真实凭据。

## 手动端到端验收

使用测试应用和测试用户，在用户的行动时授权下手动验收：

1. 配置测试 `.env` 后测试 `send`，确认收到纯文本私聊。
2. 测试 `task` 的五个字段，确认消息展示正确。
3. 分别验证自动开关：关闭时任务结束不发送，开启时只发送一次。
4. 临时使用无效 Open ID，验证错误已脱敏且原任务状态与通知失败隔离。

## 排错

退出码 `2` 表示适配器输入无效（例如 JSON 解析失败、字段缺失或 payload 包含不可表示的字符），或 CLI 参数错误（如缺少 `--message`、空值、非法 `--status`）。适配器在 Shell-only 安全场景下使用，它从 STDIN 读取 JSON 并调用 CLI。

退出码 `3` 表示配置错误，例如缺少 App ID、App Secret 或 Open ID，或 `FEISHU_AUTO_NOTIFY` 不是 `true`/`false`。退出码 `4` 表示不可重试的远程错误，包括鉴权/权限不足、用户不在可用范围、无效 Open ID 或用户拒收机器人消息。

退出码 `5` 表示临时性失败，例如网络中断、限流、服务端错误。连接器会在首次失败后最多额外重试两次，因此单个请求阶段最多尝试三次。排错时不要打印 Secret、Token、Authorization 或完整 Open ID；只记录脱敏后的错误类别和飞书错误码（如有）。

## 二期

`~/.config/feishu-connector/config.json` 与项目 `.config/feishu-connector/config.json` 属于已批准的二期范围，**一期不读取任何 `config.json`**。一期仅使用本地 `.env` 及按字段覆盖它的进程环境变量，也不包含 OpenCode Skill。
