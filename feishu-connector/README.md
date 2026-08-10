# 飞书消息连接器

## 能力边界

连接器通过飞书**企业自建应用**的机器人，向一个固定 Open ID 发送纯文本私聊。它不使用群机器人 Webhook，不接收消息，不支持群聊、富文本、多用户或动态接收人。

## 飞书端准备

1. 在飞书开发者后台创建企业自建应用。
2. 为应用开启**机器人能力**，并发布包含此能力的应用版本。
3. 申请最小发送权限 `im:message:send_as_bot`。
4. 将固定目标用户加入应用机器人的**可用范围**。
5. 发布后，记录 App ID、App Secret，以及该应用下目标用户的 Open ID。

用户可以在飞书客户端停止接收机器人消息；连接器会将此类错误报告为不可重试的业务错误。请只使用测试应用和测试用户完成验收。

## 用户级安装

第一版安装器支持 macOS/Linux，只依赖 Python 3 标准库。在仓库根目录运行：

```bash
python3 feishu-connector/install.py
```

安装器把运行文件复制到 `~/.local/share/feishu-connector`，把 `feishu-notify` 和 `feishu-notify-adapter` 放到 `~/.local/bin`，并把 Skill 安装到 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`。如果 `~/.local/bin` 不在 `PATH`，安装器会输出设置提示，但不会修改 Shell 配置。

重复安装相同内容且权限正确时是安全的。内容或权限不同时，安装器默认拒绝覆盖；确认要更新受管文件或修复权限后运行：

```bash
python3 feishu-connector/install.py --force
```

安装器不会创建或修改飞书配置、`.env`、Secret、Token 或 Open ID。安装后可以从任意项目目录运行 `feishu-notify`；下文的 `python3 feishu-connector/scripts/feishu_notify.py` 命令保留为源码仓库内的直接运行方式。

## 配置

连接器按叶子字段合并三层配置，优先级固定为：**环境变量 > 项目 JSON > 全局 JSON**。高优先级没有出现的字段继续继承低优先级值；显式 `null`、未知字段、错误类型和空字符串都会在联网前报配置错误。

全局兜底路径是 `~/.config/feishu-connector/config.json`：

```json
{
  "app": {
    "appId": "cli_example",
    "appSecret": "example-secret"
  },
  "recipient": {
    "openId": "ou_example"
  },
  "notification": {
    "autoNotify": false
  }
}
```

在 POSIX 系统上，只要全局 JSON 含 `appSecret`，就必须执行 `chmod 600 ~/.config/feishu-connector/config.json`，不得授予 group 或 other 读写权限。

项目覆盖路径是 `<项目根目录>/.config/feishu-connector/config.json`，允许提交 Git：

```json
{
  "recipient": {
    "openId": "ou_project_example"
  },
  "notification": {
    "autoNotify": true
  }
}
```

项目 JSON 中禁止出现 `appSecret`，即使为空或假值也会被拒绝。Secret 只能来自全局 JSON 或 `FEISHU_APP_SECRET`；Open ID 可以按仓库访问控制提交，但日志和诊断仍会脱敏。四个兼容环境变量是 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 和 `FEISHU_AUTO_NOTIFY`。

项目根目录依次取 CLI `--project-root`、当前 Git 仓库顶层目录、当前工作目录。需要显式指定时，把选项放在子命令前：

```bash
python3 feishu-connector/scripts/feishu_notify.py \
  --project-root /path/to/project send --message "测试消息"
```

## 配置诊断

以下命令只显示每个有效字段的来源，不显示配置值，也不发起网络请求：

```bash
python3 feishu-connector/scripts/feishu_notify.py config
```

示例输出：

```text
app.appId: project
app.appSecret: global (redacted)
recipient.openId: environment (redacted)
notification.autoNotify: project
```

## 从一期 `.env` 迁移

二期不再读取 `feishu-connector/.env`。把 App Secret 移至全局 JSON 或进程环境变量，把可提交的项目差异移至项目 JSON；原 `.env` 即使保留也不会生效。CLI 只在二期配置不完整或无效时检查旧文件是否存在并打印迁移提示，不读取或输出旧文件内容。验证新配置并完成迁移后删除旧文件；`.gitignore` 继续保护迁移期间遗留的真实 `.env`。

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

`task --auto` 是否发送由合并后的 `notification.autoNotify` 决定，优先级为 **环境变量 > 项目 JSON > 全局 JSON**：只有合并结果为 `true` 才发送；关闭或未配置时是成功但不发送的 no-op。`FEISHU_AUTO_NOTIFY=false` 会覆盖较低优先级的 `true`，因此不能被项目或全局 JSON 绕过；不传 `--auto` 的 `task` 仍会发送。

## Codex Skill

安装后让 Codex 读取 `${CODEX_HOME:-~/.codex}/skills/feishu-notify/SKILL.md`，以便在用户明确要求时调用稳定命令 `feishu-notify`。只有在源码仓库内直接运行时，才使用 `feishu-connector/skills/feishu-notify/SKILL.md` 和 `python3 feishu-connector/scripts/...` 路径。若要使任务结束时默认执行自动通知，项目指令必须明确启用这一自动任务通知约定；它不是 Codex 平台级的全局 Hook。

通知失败时，Skill 只追加一条脱敏警告，**不会改变原任务结果**，也不覆盖原有失败原因。显式发送不依赖自动通知开关。

## 测试

运行默认离线测试：

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

测试默认通过 Mock 运行，**不访问真实飞书**，也不读取真实凭据。

## 手动端到端验收

只使用测试应用和测试用户，并在操作者明确授权真实发送后执行：

1. 创建权限为 `0600` 的全局 JSON，并创建只覆盖 `recipient.openId` 的项目 JSON。
2. 运行 `config`，确认四个字段来源正确且 Secret/Open ID 不出现在输出中。
3. 临时在项目 JSON 加入空的 `appSecret`，确认 CLI 以退出码 `3` 在联网前拒绝；随后删除该字段。
4. 运行 `send`，确认测试用户收到纯文本私聊。
5. 运行 `task`，确认状态、任务、摘要、仓库和分支正确展示。
6. 分别验证自动开关：关闭时任务结束不发送，开启时只发送一次。
7. 临时使用无效 Open ID，确认错误脱敏且通知失败不改变原任务结果。

## 排错

退出码 `2` 表示适配器输入无效（例如 JSON 解析失败、字段缺失或 payload 包含不可表示的字符），或 CLI 参数错误（如缺少 `--message`、空值、非法 `--status`）。适配器在 Shell-only 安全场景下使用，它从 STDIN 读取 JSON 并调用 CLI。

退出码 `3` 表示配置错误，例如缺少 App ID、App Secret 或 Open ID，或 `FEISHU_AUTO_NOTIFY` 不是 `true`/`false`。退出码 `4` 表示不可重试的远程错误，包括鉴权/权限不足、用户不在可用范围、无效 Open ID 或用户拒收机器人消息。

退出码 `5` 表示临时性失败，例如网络中断、限流、服务端错误。连接器会在首次失败后最多额外重试两次，因此单个请求阶段最多尝试三次。消息请求在一次逻辑发送的所有重试中复用同一个幂等 UUID，避免响应丢失造成重复私聊。

CLI 会把每次重试的脱敏错误类别和尝试次数写到 stderr。排错时不要打印 Secret、Token、Authorization、完整 Open ID、请求头或完整请求体。

无法编码为 UTF-8 的消息或任务字段属于参数错误，CLI 会在读取配置和联网前以退出码 `2` 拒绝。
