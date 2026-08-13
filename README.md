# Harness Craft

Harness Craft 是一个 Harness 工具箱，用于沉淀可复用的 Agent Skills、连接器与工程辅助工具，帮助开发者扩展智能编码工具的项目分析和任务协作能力。

## 已集成工具

### [feishu-connector](./feishu-connector/README.md)

飞书消息连接器，可通过企业自建应用机器人发送纯文本、富文本和任务状态卡片。它支持分层配置、显式外发授权、按需自动通知、失败重试和敏感信息脱敏，适合将 Agent 的任务完成、失败或待确认状态同步到飞书。

### [analyzing-projects](./analyzing-projects/README.md)

面向中文用户的通用项目分析 Skill，可分析已有代码库并生成源码级的项目架构与实现文档，帮助开发者快速理解项目结构、核心模块和运行机制。它采用通用 Agent Skill 目录结构，可安装到多种支持 Skills 的智能编码工具中。
