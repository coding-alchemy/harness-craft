# 飞书连接器快速开始

本连接器向一个已配置 Open ID 发送消息：显式 `send` 为纯文本，`rich` 为通用 Markdown 卡片，`task` 为自包含 interactive Markdown 任务卡片。Codex 与 OpenCode 共用相同的 argv/stdin 显式接口。运行时仅需 Python 3.9+。

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

## 自动通知与验证

自动通知只有在 `task --auto` 和 `notification.autoNotify=true` 时发送；`autoNotify=false` 时输出 `skipped` 并不联网，只有 `sent` 才表示实际发送。显式 `send`、`rich` 与未带 `--auto` 的 `task` 不受开关影响。手动取消不调用连接器，每个最终结果或待确认节点最多通知一次。失败内容只能给用户可见原因，不能包含内部推理、完整日志或敏感上下文；通知错误不得改变原任务结果。网络类别为 `network.dns`、`network.timeout`、`network.tls`、`network.connection`、`network.unreachable`；退出码 `5` 的投递状态可能不明，调用方不得跨进程重试。保留配置、环境变量、退出码、重试与 UUID 合同；完整说明见 [README](../README.md)。

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```

离线测试全用 Mock，不访问真实飞书。真实验收使用测试用户，分别发送完成、失败、待确认三张消息卡片，并发送一次纯文本 `send`。
