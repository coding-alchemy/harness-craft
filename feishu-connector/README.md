# 飞书消息连接器

## 能力边界

本连接器是一个自包含的 Codex Skill：它通过飞书企业自建应用机器人，向一个已配置的 Open ID 发送纯文本私聊。它支持用户明确发送消息，以及由仓库指令启用的任务结束自动通知。

它不接收消息，不支持群 Webhook、群聊、富文本、多接收人、动态接收人、常驻服务或通用 Python 包安装。通知失败只是附属告警，绝不改变原任务的成功、失败或失败原因。

## 飞书端准备

1. 在飞书开发者后台创建企业自建应用。
2. 开启机器人能力，并发布包含该能力的应用版本。
3. 申请最小权限 `im:message:send_as_bot`。
4. 将固定目标用户加入机器人的可用范围。
5. 记录 App ID、App Secret 和该用户在此应用下的 Open ID。

用户可在飞书客户端停止接收机器人消息；这种情况会被报告为不可重试的远程错误。真实验收只应使用测试应用和测试用户。

## 安装与更新

在仓库根目录运行：

```bash
python3 feishu-connector/install_skill.py
python3 feishu-connector/install_skill.py --force
```

安装器将 Skill 的六个受管文件复制到 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`。内容和权限相同的重复安装成功且不改动文件；受管文件冲突时默认拒绝，`--force` 才会替换受管文件。它不创建飞书配置、凭据、Token 或 Open ID，也不安装 launcher 或通用 package；目标目录中的未知文件会保留。

安装器采用普通单用户威胁模型，防止日常误覆盖，但不承诺防御同一用户的恶意并发篡改。旧版若曾安装到 `~/.local/share/feishu-connector` 或 `~/.local/bin/feishu-notify*`，确认不再需要后请自行一次性手动清理；安装器不会删除这些旧文件。

## 配置

配置按叶子字段合并，优先级为：**环境变量 > 项目 JSON > 全局 JSON**。高优先级未出现的字段继续继承低优先级值；`null`、未知字段、错误类型和空字符串都在联网前作为配置错误拒绝。

全局文件是 `~/.config/feishu-connector/config.json`：

```json
{
  "app": {"appId": "cli_example", "appSecret": "example-secret"},
  "recipient": {"openId": "ou_example"},
  "notification": {"autoNotify": false}
}
```

全局 JSON 含 `appSecret` 时，在 POSIX 系统上必须仅由当前用户读写，例如：

```bash
chmod 600 ~/.config/feishu-connector/config.json
```

项目文件为 `<项目根目录>/.config/feishu-connector/config.json`，可提交 Git，但不得出现 `appSecret`：

```json
{
  "recipient": {"openId": "ou_project_example"},
  "notification": {"autoNotify": true}
}
```

兼容环境变量是 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 与 `FEISHU_AUTO_NOTIFY`（后者只接受 `true` 或 `false`）。项目根目录依次取 `--project-root`、当前 Git 仓库顶层目录和当前工作目录。`appSecret` 只可来自全局 JSON 或 `FEISHU_APP_SECRET`；诊断和日志都会脱敏 Secret 与 Open ID。

历史说明：一期仓库内 `.env` 已废弃；当前版本既不读取也不检测它，也不会输出迁移提示。请将 Secret 放在全局 JSON 或进程环境变量中。

## Skill 入口与调用

路径约定（展示用途，不是可直接执行的 Shell 命令）：

```text
${CODEX_HOME:-~/.codex}/skills/feishu-notify/scripts/feishu_notify.py
```

支持 argv 的执行器先声明已安装入口，并将每个动态值作为独立 argv；不得拼接 Shell 字符串。四个子命令如下：

```bash
ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
python3 "$ENTRY" send --message "测试消息"
python3 "$ENTRY" task --status success --task "修复登录问题" --summary "测试通过" --repo "harness-craft" --branch "feishu"
python3 "$ENTRY" task --auto --status success --task "修复登录问题" --summary "测试通过" --repo "harness-craft" --branch "feishu"
python3 "$ENTRY" config
```

`send` 始终发送用户指定的纯文本。`task` 固定渲染状态、任务、摘要、仓库和分支，`--status` 只能是 `success` 或 `failure`，可选 `--source` 为 `Codex`（默认）或 `OpenCode`。`config` 不联网，只显示有效字段的来源，不显示值。

如果执行工具只接受 Shell 命令字符串但提供独立 stdin 通道，先声明上述 `ENTRY`，再使用固定命令 `python3 "$ENTRY" stdin`。以下 JSON 必须通过独立 stdin 通道传入，动态内容不得进入命令字符串：

```json
{"flow":"send","message":"用户指定的原文"}
```

```json
{"flow":"task-auto","status":"success","task":"简短任务名","summary":"简短摘要","repo":"仓库名","branch":"分支名"}
```

没有独立 stdin 通道时，不使用此回退路径，应改用支持 argv 的执行器。

## 自动通知门控

只有任务使用 `task --auto` 且合并后的 `notification.autoNotify` 为 `true` 时才会发送。关闭或未配置时，该命令以退出码 `0` 成功结束且不联网；显式 `send` 和未带 `--auto` 的 `task` 不受此开关影响。要在任务结束时使用自动通知，仓库指令必须明确启用该 Skill 工作流；它不是 Codex 的全局 Hook。

## 重试、幂等与排错

| 退出码 | 含义 |
| --- | --- |
| `0` | 已发送，或自动通知关闭时的 no-op |
| `2` | CLI 参数或 stdin JSON 无效 |
| `3` | 配置错误 |
| `4` | 不可重试的飞书/API 错误 |
| `5` | 网络、限流或服务端等可重试错误耗尽重试 |

Token 和消息请求在网络错误、HTTP 429、飞书限流或 HTTP 5xx 时，首次失败后最多额外重试两次。单次逻辑消息发送的所有重试复用同一个 UUID，避免响应丢失造成重复私聊。stderr 只输出脱敏的错误类别和尝试次数；不要输出 Secret、Token、Authorization、完整 Open ID、请求头或完整请求体。

## 测试与真实验收

运行离线测试：

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

测试使用 Mock，不访问真实飞书或真实凭据。真实发送须由操作者配置测试凭据并明确执行；建议先运行 `config` 确认来源与脱敏，再用测试用户运行一次 `send` 和一次 `task`。
