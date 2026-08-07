# 飞书连接器精简使用指南设计

## 目标

为日常使用者提供一份可直接操作的快速指南，帮助其完成本地配置、发送纯文本消息、使用任务通知，并在不泄露敏感信息的前提下处理常见失败。

## 范围

- 新建 `feishu-connector/docs/USAGE.md`。
- 只描述 Phase 1 已实现能力：固定 Open ID 的纯文本私聊、`send`、`task`、`task --auto`、Codex Skill 以及 Shell-only 安全适配器。
- 以现有 `feishu-connector/README.md` 为详细参考来源，避免重复飞书后台配置和完整验收细节。

## 结构

1. 适用范围与开始前条件
2. 本地 `.env` 配置及环境变量覆盖规则
3. 手动发送的最短命令
4. 手动任务通知与自动通知开关
5. Codex Skill 与 Shell-only stdin 适配器的安全调用方式
6. 常见退出码、脱敏原则和完整测试命令
7. 指向 README 的详细配置、排错与真实端到端验收链接

## 内容原则

- 每个命令都以仓库根目录为工作目录，并使用明显的示例值。
- 不展示真实 App Secret、Token、Authorization 或完整 Open ID。
- 不将用户文本拼接进 Shell 命令；Shell-only 环境仅通过适配器的独立标准输入通道传值。
- 说明默认测试离线运行；真实飞书发送仅由用户在提供测试凭据后手动执行。

## 验证

- 添加 Markdown 文档后检查链接、命令和退出码与 `README.md`、`SKILL.md` 及 CLI 帮助保持一致。
- 运行现有离线 unittest 套件与 `git diff --check`；不发送真实飞书消息。
