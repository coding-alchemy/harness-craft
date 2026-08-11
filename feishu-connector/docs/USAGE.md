# 飞书连接器快速开始

仅向一个已配置 Open ID 发送纯文本私聊；不支持群 Webhook、群聊、富文本或动态接收人。
## 安装

```bash
python3 feishu-connector/install_skill.py
python3 feishu-connector/install_skill.py --force
```

首次配置前，请先阅读[飞书应用参数获取指南](FEISHU_APP_SETUP.md)，取得 App ID、App Secret 和目标用户 Open ID。

## 最小配置

全局 `~/.config/feishu-connector/config.json`：

```json
{"app":{"appId":"cli_example","appSecret":"example-secret"},"recipient":{"openId":"ou_example"}}
```
项目 `<项目根目录>/.config/feishu-connector/config.json`：

```json
{"recipient":{"openId":"ou_project_example"},"notification":{"autoNotify":true}}
```
项目 JSON 不得含 `appSecret`；优先级是环境变量 > 项目 JSON > 全局 JSON。全局文件含 Secret 时执行 `chmod 600 ~/.config/feishu-connector/config.json`。
## 调用与诊断

```bash
ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
python3 "$ENTRY" config
python3 "$ENTRY" send --message "测试消息"
python3 "$ENTRY" task --auto --status success --task "任务" --summary "完成" --repo "仓库" --branch "分支"
```
支持 argv 时每个动态值必须是独立参数。仅 Shell 的执行器若有独立 stdin 通道，使用固定命令 `python3 "$ENTRY" stdin`；JSON 必须通过独立 stdin 通道传入：`{"flow":"send","message":"原文"}` 或 `{"flow":"task-auto","status":"success","task":"任务","summary":"完成","repo":"仓库","branch":"分支"}`。没有独立 stdin 时改用 argv。
## 验证

```bash
python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v
```
完整的飞书端准备、配置安全、退出码、重试、自动通知和旧安装清理说明见 [README](../README.md)。
