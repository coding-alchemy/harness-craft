# 飞书连接器快速开始

本连接器向一个已配置 Open ID 发送消息：显式 `send` 为纯文本，`rich` 为通用 Markdown 卡片，`task` 为自包含 interactive Markdown 任务卡片。直接 argv 与非 Codex stdin 兼容，Codex Shell 发送使用审批可见命令。运行时仅需 Python 3.9+。

> **当前限制：** V1.4 的审批可见命令只展示正文，Skill 尚未实现每个对话的首次收件测试和持久 `task` 前缀建议。Auto-review 若因接收人归属或具体 payload 授权不足而拒绝，消息不会发送；重新安装 Skill、压缩正文或重试不能替代目标授权。

## 安装和最小配置

```bash
python3 feishu-connector/install_skill.py
python3 feishu-connector/install_skill.py --force
```

首次配置请阅读[飞书应用参数获取指南](FEISHU_APP_SETUP.md)。全局 `~/.config/feishu-connector/config.json` 可为：

```json
{"app":{"appId":"cli_example","appSecret":"example-secret"},"recipient":{"openId":"ou_example"}}
```

项目 `<项目根目录>/.config/feishu-connector/config.json` 可设置接收人和 `notification.autoNotify`，不得含 `appSecret`。`--project-root` 是全局选项；项目配置选择依次为显式路径、Git 项目根目录、当前工作目录。优先级为环境变量 > 项目 JSON > 全局 JSON；全局文件含 Secret 时执行 `chmod 600 ~/.config/feishu-connector/config.json`。

## 调用

```bash
ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
python3 "$ENTRY" config
python3 "$ENTRY" send --message "测试消息"
python3 "$ENTRY" rich --title "进度更新" --content $'**已完成**\n\n- 校验通过'
python3 "$ENTRY" task --status success --project "HETU" --conversation "个股-二期-架构师" --content "已完成"
python3 "$ENTRY" task --auto --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择 A 或 B"
```

每个动态值必须是独立 argv，禁止动态 Shell 拼接。`rich --title` 和 `--content` 固定生成蓝色标题的 `interactive` 卡片，标题为 `plain_text`，且仅有一个 `lark_md` 正文；不得传入任意消息类型、卡片 JSON 或后台模板。显式 `task` 不添加 `--auto`，`task --auto` 只用于仓库规则驱动的自动通知。`task` 只接受 `--status success|failure|confirm`、非空 `--project`、非空 `--conversation`、非空 `--content` 与可选 `--auto`。项目名和对话框名必须是单行有效 Unicode，拒绝空值、换行和 NUL；正文必须是非空有效 Unicode，允许 Markdown 换行，并原样传递、不解析、重组、截断或拆分，即使超过飞书限制。

任务消息卡片固定是自包含 `interactive`，只含 `config.wide_screen_mode`、`header.template`、`header.title`（`plain_text`）和一个正文 `div`（`lark_md`）；不得提供任意消息类型、卡片 JSON 或后台模板。标题为 `<项目名>-<对话框名>-<状态中文>`：`success` → “任务完成”/`green`，`failure` → “任务失败”/`red`，`confirm` → “待确认”/`orange`。

用户要求结果通知但未指定正文时，使用显式 `task` 发送任务标识、状态和执行结果：成功包含核心结果及相关验证或产物位置，失败包含具体的非敏感原因及安全下一步，待确认包含需要决定的事项及选项或影响。密码、API key、访问 Token、Cookie、私钥、验证码、凭据和个人信息的具体值在首次发送前替换为短脱敏标记；普通项目、提交和测试信息保留。仅在工具明确发送进程尚未创建、拒绝指向隐私或目的地信任、允许更安全替代且本通知未重写过时，才可生成一次仍有信息量的脱敏替代正文；网络错误或投递状态不明不跨进程重试。

```json
{"config":{"wide_screen_mode":true},"header":{"template":"orange","title":{"tag":"plain_text","content":"HETU-个股-二期-架构师-待确认"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"请选择 A 或 B"}}]}
```

仅 Shell 执行器若有独立 stdin 通道，使用固定命令 `python3 "$ENTRY" stdin`。stdin 只允许以下四种白名单 JSON，动态值不能进入 Shell 命令字符串：

```json
{"flow":"send","message":"原文"}
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

无独立 stdin 时改用 argv。argv 与网络权限独立，stdin 只是传参，stdin 不提供网络能力。

### Codex 审批可见调用

Codex 先在网络隔离沙箱中把现有四种白名单 JSON 写入 `prepare-shell` 的 stdin，取得完整命令；只移除 stdout 最后的一个换行，再把其余命令原样作为设置 `sandbox_permissions=require_escalated` 的真实发送调用。真实审批命令因此包含消息类型和全部动态字段，不再使用审批后才写入正文的 `stdin` 发送路径。

`prepare-shell` 成功只证明命令可安全展示，不证明接收人已经获得用户或组织授权，也不保证 Auto-review 会批准。当前版本不能把“执行完飞书通知我”视为可验证的离席送达承诺。

该路径要求 POSIX 操作系统和 POSIX Shell，已在 macOS/Linux 验证；PowerShell 与 `cmd.exe` 不受支持。生成的完整命令按 UTF-8 计上限为 96 KiB（98,304 字节），包含解释器和入口路径、选项和引用开销，以及项目根与动态字段，不是正文字数限制。超限、平台不支持、准备失败、命令无法提交或审批拒绝时均不发送、不截断、不拆分、不回退 stdin、文件或环境变量；仅满足上述一次隐私脱敏重写条件时，才可重新准备并重新申请审批。

### 非 Codex stdin 兼容入口

不存在审批前 payload 可见性要求的非 Codex 环境仍可使用现有 `stdin` 四种白名单；该兼容入口不得用于 Codex 的真实发送。

## 离席无人值守通知

当前版本尚未提供无人值守授权能力；以下是后续版本的目标流程，不是当前可执行命令：

1. 当前对话第一次出现飞书发送意图时，Skill 在原任务开始前立即暂停原任务并进入测试流程。
2. 当前审批模式不展示持久规则选项时，Agent 先要求切换到可人工保存规则的模式；随后发送固定、非敏感的 `task` 测试卡片，并建议持久允许只匹配绝对解释器、已安装入口、当前项目根和 `task` 的命令前缀。不得允许整个 `python3`、`send` 或 `rich`。
3. 用户选择持久允许并在飞书收到测试卡片后，回当前对话明确确认两件事；Agent 收到确认后才开始原任务或发送最初要求的消息。
4. 同一对话后续发送不再测试或要求确认；新对话第一次使用时重新测试，已有持久规则时不重复申请。
5. 离席期间保持 Codex 任务、电脑和网络运行；休眠、进程退出或断网仍无法送达。

安装器不会自动改写 `~/.codex/config.toml`、命令规则、网络 allowlist 或组织策略，也不要求用户手工合并完整 Auto-review policy。精确规则由用户在首次平台审批中选择持久保存；固定接收人配置在同一对话期间须保持不变，若用户修改接收人，应明确要求重新测试。组织策略禁止该规则时不能绕过。详见[无人值守授权设计](../specs/2026-08-30-feishu-unattended-notification-authorization-design.md)和[OpenAI Rules 文档](https://learn.chatgpt.com/docs/agent-configuration/rules)。

## 自动通知与验证

自动通知只有在 `task --auto` 和 `notification.autoNotify=true` 时发送；`autoNotify=false` 时输出 `skipped` 并不联网，只有 `sent` 才表示实际发送。显式 `send`、`rich` 与未带 `--auto` 的 `task` 不受开关影响。手动取消不调用连接器，每个最终结果或待确认节点最多通知一次。失败内容只能给用户可见原因，不能包含内部推理、完整日志或敏感上下文；通知错误不得改变原任务结果。网络类别为 `network.dns`、`network.timeout`、`network.tls`、`network.connection`、`network.unreachable`；退出码 `5` 的投递状态可能不明，调用方不得跨进程重试。保留配置、环境变量、退出码、重试与 UUID 合同；完整说明见 [README](../README.md)。

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

离线测试全用 Mock，不访问真实飞书。真实验收使用测试用户，分别发送完成、失败、待确认三张消息卡片，并发送一次纯文本 `send`。
