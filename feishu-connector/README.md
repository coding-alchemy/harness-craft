# 飞书消息连接器

## 当前版本

**V1.2**

当前版本主要提供以下功能：

- 通过飞书企业自建应用机器人向已配置用户发送纯文本和通用富文本消息；标题、分段、列表、链接或代码等格式化信息优先使用富文本。
- 发送任务完成、任务失败和待确认三种状态的 interactive Markdown 消息卡片，并明确区分显式任务通知与由仓库规则控制的自动通知。
- 用户明确要求发送飞书消息即授权向已配置的固定接收人进行一次显式外发；未指定正文时仅发送任务结果和必要的简短验证信息。
- 用户明确要求真实发送时，Agent 在首个 `send`、`rich` 或实际发送的 `task` 调用上直接申请受控的沙箱外联网权限；不得先在网络隔离沙箱试发；`config` 等离线诊断仍可在沙箱内执行。
- 支持安全的独立 argv 调用，以及 `send`、`rich`、`task`、`task-auto` 四种 stdin 输入流程。
- 支持环境变量、项目配置和全局配置的分层合并与严格校验。
- 支持由仓库指令控制的自动通知，在关闭时安全跳过联网请求，并明确报告已发送或已跳过状态。
- 对网络错误、限流和服务端错误执行有限重试，提供脱敏的网络错误分类，并通过 UUID 降低重复发送风险。
- 严格校验配置和 stdin JSON（包括拒绝重复键），提供日志脱敏、明确退出码、离线测试和可重复执行的 Skill 安装器。

[查看完整版本变更](./CHANGELOG.md)

## 能力边界

本连接器是自包含的 Codex Skill，通过飞书企业自建应用机器人向一个已配置的 Open ID 发送消息。Codex 与 OpenCode 共用相同的 argv/stdin 显式接口。显式 `send` 发送纯文本，`rich` 发送通用 Markdown 卡片，`task` 发送自包含 interactive Markdown 任务卡片。用户的明确发送请求只授权本次向固定接收人外发一次，不允许更换、推断或扩大接收人，也不自动延续到后续消息。它不接收消息，不支持群 Webhook、群聊、多接收人、动态接收人、常驻服务或通用 Python 包安装。通知失败只是附属告警，不得改变原任务结果。

## 飞书端准备

1. 在飞书开发者后台创建企业自建应用，开启机器人能力并发布应用版本。
2. 申请最小权限 `im:message:send_as_bot`，并将固定测试用户加入机器人的可用范围。
3. 保存 App ID、App Secret 和该用户在此应用下的 Open ID。

用户可停止接收机器人消息；该情形是不可重试的远程错误。真实验收只使用测试应用和测试用户。

## 安装与配置

```bash
python3 feishu-connector/install_skill.py
python3 feishu-connector/install_skill.py --force
```

安装器将 Skill 的六个受管文件复制到 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`；相同内容与权限的重复安装成功且不改动文件，受管文件冲突默认拒绝，`--force` 才替换。它不创建飞书配置、凭据、Token 或 Open ID，不安装 launcher 或通用 package，且保留未知文件。运行时要求 Python 3.9+。

配置按叶子字段合并，优先级为：**环境变量 > 项目 JSON > 全局 JSON**。全局文件为 `~/.config/feishu-connector/config.json`：

```json
{"app":{"appId":"cli_example","appSecret":"example-secret"},"recipient":{"openId":"ou_example"},"notification":{"autoNotify":false}}
```

项目文件为 `<项目根目录>/.config/feishu-connector/config.json`，可设置接收人和 `notification.autoNotify`，但不得包含 `appSecret`。`--project-root` 是全局选项；项目配置选择依次为显式路径、Git 项目根目录、当前工作目录。环境变量为 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 与 `FEISHU_AUTO_NOTIFY`（只接受 `true` 或 `false`）。全局文件含 Secret 时，在 POSIX 系统执行 `chmod 600 ~/.config/feishu-connector/config.json`。`null`、未知字段、错误类型、空字符串在联网前拒绝；诊断和日志脱敏 Secret 与 Open ID。

## Skill 入口与调用

### Agent 执行权限

`send`、`rich` 和实际发送的 `task` 都需要访问飞书网络。用户明确要求发送时，在首个真实发送子命令（`send`、`rich` 或实际发送的 `task`）调用上直接请求沙箱外联网权限。使用 Codex 执行器时，在该调用上设置 `sandbox_permissions=require_escalated`；执行器支持限制网络目标时，仅允许 `open.feishu.cn:443`。

不得先在网络隔离沙箱中使用发送子命令试发或探测连通性；`config` 等明确不联网的诊断不计入真实发送调用，可以在沙箱内执行。如果联网权限被拒绝或执行器不支持权限升级，停止调用并报告消息未发送，不得退回网络隔离沙箱试发或改用其他渠道绕过审批。

```bash
ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
python3 "$ENTRY" send --message "测试消息"
python3 "$ENTRY" rich --title "进度更新" --content $'**已完成**\n\n- 校验通过'
python3 "$ENTRY" task --status success --project "HETU" --conversation "个股-二期-架构师" --content "已完成"
python3 "$ENTRY" task --auto --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择 A 或 B"
python3 "$ENTRY" config
```

动态值必须作为独立 argv，禁止动态 Shell 拼接。`send` 始终发送用户指定的纯文本；`rich --title` 与 `--content` 固定生成蓝色标题的 `interactive` 卡片，标题为 `plain_text`，且仅有一个 `lark_md` 正文；不得传入任意消息类型、卡片 JSON 或后台模板。不带 `--auto` 的显式 `task` 始终尝试发送，`task --auto` 仅供仓库规则驱动的自动通知。`task` 仅接受 `--status success|failure|confirm`、非空 `--project`、非空 `--conversation`、非空 `--content` 和可选 `--auto`。

项目名和对话框名必须是非空、单行、有效 Unicode，拒绝换行和 NUL。正文必须是非空、有效 Unicode，允许 Markdown 换行且原样传递，不解析、重组、截断或拆分；超过飞书限制也不截断或拆分。不得传入任意消息类型、卡片 JSON 或后台模板。

任务消息卡片固定为自包含 `interactive`，只含 `config.wide_screen_mode`、`header.template`、`header.title`（`plain_text`）和一个正文 `div`（`lark_md`）：

```json
{"config":{"wide_screen_mode":true},"header":{"template":"orange","title":{"tag":"plain_text","content":"HETU-个股-二期-架构师-待确认"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"请选择 A 或 B"}}]}
```

标题严格是 `<项目名>-<对话框名>-<状态中文>`：`success` → “任务完成”/`green`，`failure` → “任务失败”/`red`，`confirm` → “待确认”/`orange`。

仅 Shell 执行器若提供独立 stdin 通道，使用固定命令 `python3 "$ENTRY" stdin`。stdin 仅接受 `send`、`rich`、显式 `task`、`task-auto` 四种精确字段白名单，动态值不得进入 Shell 命令字符串：

```json
{"flow":"send","message":"用户指定的原文"}
```

```json
{"flow":"rich","title":"进度更新","content":"**已完成**"}
```

```json
{"flow":"task","status":"success","project":"HETU","conversation":"个股-二期-架构师","content":"已完成"}
```

```json
{"flow":"task-auto","status":"confirm","project":"HETU","conversation":"个股-二期-架构师","content":"请选择 A 或 B"}
```

没有独立 stdin 时改用 argv 执行器。argv 与网络权限独立，stdin 只是传参，stdin 不提供网络能力。

## 自动通知、错误与重试

只有 `task --auto` 且合并后的 `notification.autoNotify` 为 `true` 才发送；关闭或未配置时输出 `Feishu notification skipped: autoNotify=false`，以退出码 `0` 成功 no-op 且不联网。显式 `send`、`rich` 与未带 `--auto` 的 `task` 不受该开关影响。`Feishu message sent` 才表示已发送；`skipped` 表示未发送。自动通知必须由仓库指令明确启用；手动取消不调用连接器，每个最终结果或待确认节点最多通知一次。失败内容只给用户可见原因，不能泄露内部推理、完整日志或敏感上下文；通知错误不得改变原任务结果。

| 退出码 | 含义 |
| --- | --- |
| `0` | 已发送，或自动通知关闭时的 no-op |
| `2` | CLI 参数或 stdin JSON 无效 |
| `3` | 配置错误 |
| `4` | 不可重试的飞书/API 错误 |
| `5` | 网络、限流或服务端等可重试错误耗尽重试 |

Token 和消息请求在网络错误、HTTP 429、飞书限流或 HTTP 5xx 时首次失败后最多额外重试两次。网络错误分类为 `network.dns`、`network.timeout`、`network.tls`、`network.connection`、`network.unreachable`。单次逻辑发送的全部重试复用同一 UUID，降低但不能消除重复私聊风险；退出码 `5` 表示投递状态可能不明，调用方不得跨进程重试。stderr 仅输出脱敏错误类别和尝试次数。

## 测试与真实验收

离线测试全用 Mock，不访问真实飞书或真实凭据：

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

真实发送仅由操作者配置测试凭据并明确执行：向测试用户分别发送完成、失败、待确认三张任务消息卡片，并保留一次纯文本 `send` 验收。
