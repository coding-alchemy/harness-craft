# 飞书应用参数获取指南

## 用途与边界

本指南只适用于**企业自建应用机器人**向固定的单个用户发送纯文本私聊。完成后可取得 App ID、App Secret 和该目标用户的 `ou_...` Open ID；不适用于群 Webhook、群聊或第三方应用。

## 常用入口

- [飞书开放平台首页](https://open.feishu.cn/)：找不到功能入口时，从首页导航进入。
- [开发者后台（应用列表）](https://open.feishu.cn/app)：创建或选择企业自建应用。
- [API 调试台](https://open.feishu.cn/api-explorer)：查询目标用户的 Open ID。

## 准备企业自建应用

1. 打开[开发者后台（应用列表）](https://open.feishu.cn/app)，创建企业自建应用。
2. 开启机器人能力，申请最小权限 `im:message:send_as_bot`，并发布包含该能力的应用版本。
3. 将固定目标用户加入机器人的可用范围。

## 配置权限与范围

从[开发者后台（应用列表）](https://open.feishu.cn/app)进入目标应用，再打开「权限管理」，按显示名或权限标识搜索并申请以下最小权限：

- [以应用的身份发消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)：`im:message:send_as_bot`，用于机器人以应用身份发送私聊。
- [通过手机号或邮箱获取用户 ID](https://open.feishu.cn/document/server-docs/contact-v3/user/batch_get_id)：`contact:user.id:readonly`，用于取得 Open ID。

这两项之外，还需分别配置[应用数据权限](https://open.feishu.cn/document/home/introduction-to-scope-and-authorization/configure-app-data-permissions)覆盖目标用户，以及[应用可用范围](https://open.feishu.cn/document/home/introduction-to-scope-and-authorization/availability)包含目标用户。前者用于查询 Open ID，后者用于机器人向用户发送私聊；两者不是同一项配置。权限、机器人能力或范围变更后，创建并发布应用版本使其生效。

## 获取 App ID/App Secret

从[开发者后台（应用列表）](https://open.feishu.cn/app)进入目标企业自建应用，再打开「凭证与基础信息」复制 App ID 和 App Secret。App Secret 是敏感信息：只写入全局配置或作为进程环境变量提供，切勿提交到仓库、项目 JSON、日志或截图。

## 通过 API 调试台获取 Open ID

1. 打开[飞书开放平台 API 调试台](https://open.feishu.cn/api-explorer)。若找不到入口，先打开[飞书开放平台首页](https://open.feishu.cn/)，再从首页导航进入 API 调试台。
2. 搜索「通过手机号或邮箱获取用户 ID」，并选择当前企业自建应用；若调试台提示缺少权限，先回「权限管理」开通 `contact:user.id:readonly` 并发布应用版本。
3. 将 `user_id_type` 设为 `open_id`，填写目标用户的手机号或邮箱后发起请求。
4. 从响应的 `data.user_list[].user_id` 复制以 `ou_` 开头的值，作为该用户的 Open ID。

## 写入配置

全局配置文件为 `~/.config/feishu-connector/config.json`，用于保存 App ID、App Secret 和默认接收人：

```json
{
  "app": {"appId": "cli_example", "appSecret": "example-secret"},
  "recipient": {"openId": "ou_example"}
}
```

全局配置含 Secret 时，执行以下命令限制为当前用户读写：

```bash
chmod 600 ~/.config/feishu-connector/config.json
```

项目配置文件为 `<项目根目录>/.config/feishu-connector/config.json`，可只覆盖接收人和通知开关：

```json
{
  "recipient": {"openId": "ou_project_example"},
  "notification": {"autoNotify": true}
}
```

项目 JSON **禁止**包含 `appSecret`。配置优先级为环境变量 > 项目 JSON > 全局 JSON。

## Codex 离席通知的额外条件

取得 Open ID 只完成飞书目标配置，不代表 Codex 已验证该目标归属，也不授予无人值守外发权限。当前 V1.4 的 Skill 尚未实现对话级首次测试和持久 `task` 前缀建议；配置继续只使用现有 `recipient.openId`，不要添加未知字段，严格配置校验会拒绝它们。

后续版本实现[无人值守授权设计](../specs/2026-08-30-feishu-unattended-notification-authorization-design.md)后，当前对话第一次出现飞书发送意图时，Skill 会在原任务开始前进入测试流程。当前 Auto-review 不展示持久规则选项时，须先切换到可人工保存规则的审批模式；测试调用建议用户持久允许只覆盖绝对解释器、已安装入口、当前项目根和 `task` 的精确前缀。用户确认已持久允许且真实收件后，同一对话不再测试，新对话第一次使用时重新测试。

安装器和连接器不会自动修改 Codex policy、命令规则、网络 allowlist 或组织配置，也不要求用户手工合并完整 Auto-review policy。固定接收人配置在同一对话期间须保持不变；修改接收人后应明确要求重新测试。若组织策略禁止精确允许规则、规则没有持久保存或测试仍被拒绝，该环境不支持无人值守通知。参见[OpenAI Rules](https://learn.chatgpt.com/docs/agent-configuration/rules)。

## 常见问题

- 找不到目标用户或查询缺少权限：确认已申请 `contact:user.id:readonly`、数据权限覆盖目标用户，并在 API 调试台中选择了同一个企业自建应用；变更后需发布应用版本。
- Open ID 不是 `ou_...`：确认 `user_id_type` 为 `open_id`，并从 `data.user_list[].user_id` 复制值。
- 机器人无法发送：确认已开启机器人能力、申请 `im:message:send_as_bot`、目标用户在应用可用范围内，并发布应用版本。
- 不要将 App Secret 或完整 Open ID 粘贴到仓库、日志、工单或截图中；排查时优先使用连接器的脱敏 `config` 输出。
