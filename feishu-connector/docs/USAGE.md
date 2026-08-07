# 飞书连接器快速使用指南

一句话说明：一期仅用企业自建应用机器人向固定 Open ID 发送纯文本私聊；不支持群 Webhook、群聊、富文本或动态接收人。

## 1. 开始前

请先完成企业自建应用创建、机器人能力启用、`im:message:send_as_bot` 权限申请，并将目标用户加入机器人的可用范围。飞书端的详细准备步骤见 [README](../README.md)。

## 2. 配置

从示例复制本地配置文件：

```bash
cp feishu-connector/.env.example feishu-connector/.env
```

在 `.env` 中填写以下四项：

```dotenv
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_RECEIVE_OPEN_ID=
FEISHU_AUTO_NOTIFY=false
```

进程环境变量会逐字段覆盖 `.env` 中的同名值。`.env` 不提交；Secret、Token、Authorization 和完整 Open ID 都不得进入命令行或日志。

## 3. 发送一条手动消息

```bash
python3 feishu-connector/scripts/feishu_notify.py send --message "测试消息"
```

显式发送不受自动通知开关影响；内容会按纯文本原样发给固定接收人。

## 4. 发送任务通知

```bash
python3 feishu-connector/scripts/feishu_notify.py task \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "feishu"
```

`--status` 只能为 `success` 或 `failure`。任务消息固定包含五个字段：状态、任务名称、简短摘要、仓库和分支。

## 5. 开启自动任务通知

```bash
python3 feishu-connector/scripts/feishu_notify.py task --auto \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "feishu"
```

仅当 `FEISHU_AUTO_NOTIFY=true` 时发送。关闭或未配置时，命令会以成功的 no-op 结束；此门控仍会读取并解析 `.env` 获取 `FEISHU_AUTO_NOTIFY`，但不要求或验证完整凭据，也不请求网络。通知失败时 CLI 返回相应非零退出码；若 Codex/自动化调用方把通知作为捕获的次要结果处理，原任务结果可保持隔离。

## 6. Codex 与 Shell-only 调用

Codex 读取 [feishu-notify Skill](../skills/feishu-notify/SKILL.md)（仓库根目录下 `feishu-connector/skills/feishu-notify/SKILL.md`）后，可按项目指令执行显式或自动通知。对于只接受 shell 字符串的执行工具，使用以下静态命令：

```bash
python3 feishu-connector/scripts/feishu_notify_adapter.py
```

通过工具独立的 stdin/input-data 通道传入 JSON，禁止把消息或任务字段拼接进 shell 字符串；没有独立 stdin 时不使用该路径。

## 7. 常见结果与排错

| 退出码 | 含义 | 下一步 |
| --- | --- | --- |
| 0 | 成功；自动通知关闭时也可能是 no-op | 无需操作，按需要检查任务本身结果。 |
| 2 | CLI 参数或适配器 JSON 输入无效 | 检查必填字段、状态值和 stdin JSON。 |
| 3 | 配置错误 | 检查 App ID、App Secret、Open ID 和布尔开关。 |
| 4 | 不可重试的远程错误 | 检查权限、可用范围、Open ID 或用户是否拒收机器人消息。 |
| 5 | 临时性失败 | 稍后重试并检查网络、限流或飞书服务状态。 |

网络、限流和服务端错误在每个请求阶段最多额外重试两次。完整排错说明和手动端到端验收步骤见 [README](../README.md)。

## 8. 验证安装

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

默认测试通过 Mock 运行，**不访问真实飞书**。真实发送只在用户配置测试凭据并明确执行时进行。
