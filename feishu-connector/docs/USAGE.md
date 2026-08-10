# 飞书连接器快速使用指南

一句话说明：二期仍仅用企业自建应用机器人向固定 Open ID 发送纯文本私聊；不支持群 Webhook、群聊、富文本或动态接收人。

## 1. 开始前

请先完成企业自建应用创建、机器人能力启用、`im:message:send_as_bot` 权限申请，并将目标用户加入机器人的可用范围。飞书端的详细准备步骤见 [README](../README.md)。

## 2. 用户级安装

在 macOS/Linux 的仓库根目录运行 `python3 feishu-connector/install.py`。安装后的稳定命令是 `feishu-notify` 和 `feishu-notify-adapter`；若安装器提示 `~/.local/bin` 不在 `PATH`，按提示加入后重新打开 Shell。更新已安装的受管文件使用 `python3 feishu-connector/install.py --force`。

安装器不创建飞书配置。以下章节继续说明全局 JSON、项目 JSON 和环境变量。源码仓库内也可以继续使用 `python3 feishu-connector/scripts/feishu_notify.py`。

## 3. 配置与诊断

配置按叶子字段合并，优先级为 **环境变量 > 项目 JSON > 全局 JSON**。全局文件位于 `~/.config/feishu-connector/config.json`，可以包含 `app.appId`、`app.appSecret`、`recipient.openId` 和 `notification.autoNotify`；含 Secret 时在 POSIX 上执行：

```bash
chmod 600 ~/.config/feishu-connector/config.json
```

项目文件位于 `<项目根目录>/.config/feishu-connector/config.json`，允许提交并可覆盖 `app.appId`、`recipient.openId` 和 `notification.autoNotify`。项目 JSON 禁止出现 `appSecret`。环境变量 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 和 `FEISHU_AUTO_NOTIFY` 分别覆盖对应叶子字段。

项目根目录依次取 `--project-root`、当前 Git 仓库顶层目录、当前工作目录。检查有效来源且不联网：

```bash
python3 feishu-connector/scripts/feishu_notify.py config
```

二期不再读取 `feishu-connector/.env`。把 Secret 移到全局 JSON 或进程环境变量，把项目差异移到项目 JSON；确认 `config` 诊断正确后再删除旧 `.env`。检测和提示迁移时，CLI 不读取旧文件内容。

## 4. 发送一条手动消息

```bash
python3 feishu-connector/scripts/feishu_notify.py send --message "测试消息"
```

显式发送不受自动通知开关影响；内容会按纯文本原样发给固定接收人。

## 5. 发送任务通知

```bash
python3 feishu-connector/scripts/feishu_notify.py task \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "feishu"
```

`--status` 只能为 `success` 或 `failure`。任务消息固定包含五个字段：状态、任务名称、简短摘要、仓库和分支。

## 6. 开启自动任务通知

```bash
python3 feishu-connector/scripts/feishu_notify.py task --auto \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "feishu"
```

仅当合并后的 `notification.autoNotify` 为 `true` 时发送。关闭或未配置时，命令会以成功的 no-op 结束；门控会校验全局 JSON、项目 JSON 和相关环境变量，但不要求完整发送凭据，也不请求网络。通知失败时 CLI 返回相应非零退出码；Codex 或自动化调用方必须把通知作为捕获的次要结果处理，保持原任务结果隔离。

## 7. Codex 与 Shell-only 调用

安装后，Codex 读取 `${CODEX_HOME:-~/.codex}/skills/feishu-notify/SKILL.md`，并使用稳定命令 `feishu-notify` 执行显式或自动通知。对于只接受 shell 字符串的执行工具，使用安装后的静态命令：

```bash
feishu-notify-adapter
```

通过工具独立的 stdin/input-data 通道传入 JSON，禁止把消息或任务字段拼接进 shell 字符串；没有独立 stdin 时不使用该路径。

只有在源码仓库内直接运行时，才读取 [源码树 Skill](../skills/feishu-notify/SKILL.md)，并使用 `python3 feishu-connector/scripts/feishu_notify.py` 或 `python3 feishu-connector/scripts/feishu_notify_adapter.py`。

## 8. 常见结果与排错

| 退出码 | 含义 | 下一步 |
| --- | --- | --- |
| 0 | 成功；自动通知关闭时也可能是 no-op | 无需操作，按需要检查任务本身结果。 |
| 2 | CLI 参数或适配器 JSON 输入无效 | 检查必填字段、状态值和 stdin JSON。 |
| 3 | 配置错误 | 检查 App ID、App Secret、Open ID 和布尔开关。 |
| 4 | 不可重试的远程错误 | 检查权限、可用范围、Open ID 或用户是否拒收机器人消息。 |
| 5 | 临时性失败 | 稍后重试并检查网络、限流或飞书服务状态。 |

网络、限流和服务端错误在每个请求阶段最多额外重试两次。消息阶段的重试复用同一个幂等 UUID；CLI stderr 只显示脱敏的错误类别和尝试次数。非法 Unicode 文本在读取配置和联网前按参数错误返回退出码 `2`。完整排错说明和手动端到端验收步骤见 [README](../README.md)。

## 9. 验证安装

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

默认测试通过 Mock 运行，**不访问真实飞书**。真实发送只在用户配置测试凭据并明确执行时进行。
