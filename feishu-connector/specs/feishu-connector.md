# 飞书消息连接器当前契约

## 目标与非目标

连接器以自包含 Codex Skill 的形式，通过飞书企业自建应用机器人向一个已配置 Open ID 发送纯文本私聊。它提供显式消息、固定格式的任务通知、可选的自动通知与配置来源诊断；运行时只依赖 Python 3.9 及以上版本标准库。

连接器不接收消息，不支持群 Webhook、群聊、富文本、多接收人、动态接收人、Web 服务、守护进程、通用 Python package、PATH launcher 或 OpenCode 专用安装器。通知失败不得改变 Agent 原任务结果。

历史说明：一期的仓库内 `.env` 配置已废弃；当前版本不读取或检测该文件。

## 飞书端前置条件

使用者必须创建并发布企业自建应用，开启机器人能力，申请最小权限 `im:message:send_as_bot`，并将固定目标用户加入机器人可用范围。使用者保存 App ID、App Secret 和该应用下目标用户的 Open ID。用户拒收机器人消息、无效 Open ID、权限不足和鉴权失败均为不可重试的远程错误。

## Skill 目录与调用

源码位于 `feishu-connector/skills/feishu-notify`，安装后目录为 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`。支持 argv 的执行器按以下方式声明并调用 Agent 入口：

```bash
ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
python3 "$ENTRY" send --message "显式纯文本"
```

CLI 子命令为 `send`、`task`、`config` 与 `stdin`。动态文本必须作为独立 argv，不经 Shell 拼接。`task` 要求 `--status`、`--task`、`--summary`、`--repo`、`--branch`，状态仅为 `success|failure`，可选来源为 `Codex|OpenCode`。

仅 Shell 的执行器只有在提供独立 stdin 通道时才可使用固定命令 `python3 "$ENTRY" stdin`。stdin 只能是 `{"flow":"send","message":"..."}` 或 `{"flow":"task-auto","status":"success","task":"...","summary":"...","repo":"...","branch":"..."}`，并且 JSON 必须通过独立 stdin 通道传入；没有独立 stdin 时必须使用 argv 执行器。

## 消息格式

显式消息按用户指定文本作为飞书 `text` 消息发送。任务消息固定格式为：

```text
[Codex] SUCCESS
任务：<任务>
摘要：<摘要>
仓库：<仓库>
分支：<分支>
```

`--source OpenCode` 只替换首行来源标签。所有内容作为不可信纯文本处理，不执行 Shell、模板或 Markdown。

## 配置来源和安全规则

字段逐项合并，优先级为进程环境变量、项目 `<项目根目录>/.config/feishu-connector/config.json`、全局 `~/.config/feishu-connector/config.json`。环境变量为 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID` 和 `FEISHU_AUTO_NOTIFY`。

项目 JSON 可包含 `app.appId`、`recipient.openId` 和 `notification.autoNotify`，但任何 `app.appSecret` 都必须拒绝。Secret 仅来自全局 JSON 或环境变量；POSIX 上含 Secret 的全局文件必须为私有权限。未知字段、`null`、错误类型、空字符串与非法布尔值均为配置错误。`config` 只显示四个字段的来源，Secret 与 Open ID 标记为脱敏，且不联网。

项目根目录依次取 `--project-root`、当前 Git 仓库顶层目录、当前工作目录。

## 自动通知门控

`task --auto` 仅在合并后的 `notification.autoNotify` 为 `true` 时发送；关闭或未配置时以成功 no-op 结束且不联网。显式 `send` 及未带 `--auto` 的 `task` 总会尝试发送。自动通知须由仓库指令明确启用，且每个最终任务结果最多发送一次；它不是 Codex 全局 Hook。

## 重试、幂等和错误分类

退出码：`0` 为发送成功或自动门控 no-op；`2` 为 CLI 或 stdin 输入无效；`3` 为配置错误；`4` 为不可重试飞书/API 错误；`5` 为可重试错误耗尽重试。

Token 与消息请求对网络错误、HTTP 429、飞书限流和 HTTP 5xx 首次失败后最多额外重试两次。单次逻辑消息发送在全部重试中复用同一 UUID。错误输出只给出脱敏类别、飞书错误码（如有）和尝试次数，不得泄露 Secret、Token、Authorization 或完整 Open ID。

## Skill-only 安装边界

运行 `python3 feishu-connector/install_skill.py` 将明确 manifest 中的六个 Skill 文件安装到 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`；`--force` 才允许替换冲突的受管文件。相同内容及权限的重复安装成功；未知文件保留。

安装器只服务普通单用户使用，使用同目录临时文件与原子替换写入受管文件，不创建或修改配置、凭据、Token、Open ID，不安装 launcher 或 package，也不自动删除旧版 `~/.local` 安装文件。

## 验收标准

1. 已安装 Skill 可在源码仓库移动或删除后运行，且目录外没有第二份运行模块。
2. `send`、`task`、`config` 和 `stdin` 的公开行为符合本契约；argv 与两种 stdin flow 使用同一内部发送路径。
3. 配置优先级、项目 Secret 禁止、全局 Secret 权限、自动门控、退出码、重试、UUID 幂等和结果隔离保持有效。
4. 安装只更新 manifest 受管文件；无 launcher、通用 package 或旧配置迁移行为。
5. 离线测试不使用真实飞书凭据或网络请求。
