# 飞书消息连接器当前合同

## 目标与边界

连接器以自包含 Codex Skill 形式，通过飞书企业自建应用机器人向一个已配置 Open ID 发送消息，运行时只依赖 Python 3.9+ 标准库。Codex 与 OpenCode 共用相同的 argv/stdin 显式接口。显式 `send` 发送纯文本，`rich` 发送通用 Markdown 卡片；`task` 发送固定的自包含 interactive Markdown 任务卡片。它不接收消息，也不支持群 Webhook、群聊、多接收人、动态接收人、Web 服务、守护进程、通用 Python package、PATH launcher 或任意消息/卡片模板输入。通知失败不得改变 Agent 原任务结果。

使用者创建并发布企业自建应用、开启机器人能力、申请最小权限 `im:message:send_as_bot`，并将固定测试用户加入可用范围。用户拒收机器人消息、无效 Open ID、权限不足和鉴权失败均为不可重试远程错误。

## CLI 与 stdin 合同

源码入口是 `feishu-connector/skills/feishu-notify/scripts/feishu_notify.py`，安装后入口是 `${CODEX_HOME:-~/.codex}/skills/feishu-notify/scripts/feishu_notify.py`：

```bash
ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
python3 "$ENTRY" send --message "显式纯文本"
python3 "$ENTRY" rich --title "进度更新" --content "**已完成**"
python3 "$ENTRY" task --status success --project "HETU" --conversation "个股-二期-架构师" --content "已完成"
python3 "$ENTRY" task --auto --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择 A 或 B"
```

CLI 子命令为 `send`、`rich`、`task`、`config` 与 `stdin`。动态值必须是独立 argv，禁止动态 Shell 拼接。`rich --title` 和 `--content` 固定生成蓝色标题的 `interactive` 卡片，标题为 `plain_text`，且仅有一个 `lark_md` 正文；不得传入任意消息类型、卡片 JSON 或后台模板。显式 `task` 不添加 `--auto`，`task --auto` 只供仓库规则驱动的自动通知。`task` 只接受 `--status success|failure|confirm`、非空 `--project`、非空 `--conversation`、非空 `--content` 和可选 `--auto`。

项目名和对话框名须为非空、单行、有效 Unicode，拒绝换行与 NUL。正文须非空且有效 Unicode，允许 Markdown 换行，原样传递、不解析、不重组、不截断、不拆分，即使超过飞书限制。不得传入任意消息类型、卡片 JSON 或后台模板。

仅 Shell 执行器有独立 stdin 通道时才能调用固定命令 `python3 "$ENTRY" stdin`；动态值不进入 Shell 命令字符串。stdin 仅可为 `send`、`rich`、显式 `task`、`task-auto` 四种精确字段白名单：

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

没有独立 stdin 时必须使用 argv 执行器。argv 与网络权限独立，stdin 只是传参，stdin 不提供网络能力。

## 任务卡片格式

任务卡片固定仅含 `config.wide_screen_mode`、`header.template`、`header.title`（`plain_text`）和一个正文 `div`（`lark_md`）：

```json
{"config":{"wide_screen_mode":true},"header":{"template":"orange","title":{"tag":"plain_text","content":"HETU-个股-二期-架构师-待确认"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"请选择 A 或 B"}}]}
```

标题严格为 `<项目名>-<对话框名>-<状态中文>`。状态映射为：`success` → “任务完成”/`green`，`failure` → “任务失败”/`red`，`confirm` → “待确认”/`orange`。

## 配置、自动通知与错误

字段逐项合并，优先级为环境变量、项目 `<项目根目录>/.config/feishu-connector/config.json`、全局 `~/.config/feishu-connector/config.json`。`--project-root` 是全局选项；项目配置选择依次为显式路径、Git 项目根目录、当前工作目录。环境变量为 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_OPEN_ID`、`FEISHU_AUTO_NOTIFY`。项目 JSON 不得有 `app.appSecret`；Secret 只来自全局 JSON 或环境变量，POSIX 上含 Secret 的全局文件必须私有权限。未知字段、`null`、错误类型、空字符串和非法布尔值都是配置错误；`config` 仅显示来源且脱敏，不联网。

`task --auto` 仅在 `notification.autoNotify=true` 时发送；`autoNotify=false` 时以 `skipped` 成功 no-op 结束且不联网，只有 `sent` 才表示实际发送。显式 `send`、`rich` 与未带 `--auto` 的 `task` 总会尝试发送。自动通知由仓库指令明确启用；手动取消不调用连接器，每个最终结果或待确认节点最多通知一次。失败内容只给用户可见原因，绝不包含内部推理、完整日志或敏感上下文；通知错误不得改变原任务结果。

退出码：`0` 为成功或自动 no-op，`2` 为 CLI/stdin 无效，`3` 为配置错误，`4` 为不可重试飞书/API 错误，`5` 为可重试错误耗尽重试。网络错误分类为 `network.dns`、`network.timeout`、`network.tls`、`network.connection`、`network.unreachable`。网络错误、HTTP 429、飞书限流和 HTTP 5xx 首次失败后最多额外重试两次；单次逻辑消息发送的重试复用同一 UUID。退出码 `5` 的投递状态可能不明，调用方不得跨进程重试，以免重复发送。错误输出仅给脱敏类别、飞书错误码（如有）及尝试次数。

## 安装与验收

`python3 feishu-connector/install_skill.py` 将 manifest 明确的六个 Skill 文件安装到 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`，`--force` 才替换冲突受管文件。相同内容与权限的重复安装成功，未知文件保留。安装器不创建或修改配置、凭据、Token、Open ID，不安装 launcher 或 package，也不自动删除旧版安装文件。

离线测试全用 Mock，不访问真实飞书凭据或网络。真实验收必须只用测试用户：分别发送完成、失败、待确认三张消息卡片，并保留一次纯文本 `send` 验收。
