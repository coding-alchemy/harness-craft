# Harness Craft

Harness Craft 是一个 Harness 工具箱，用于沉淀可复用的 Agent Skills、连接器与工程辅助工具，帮助开发者扩展智能编码工具的项目分析和任务协作能力。

## 已集成工具

### [feishu-connector](./feishu-connector/README.md)

飞书消息连接器，可通过企业自建应用机器人发送纯文本、富文本和任务状态卡片。它支持分层配置、显式外发授权、按需自动通知、失败重试和敏感信息脱敏，适合将 Agent 的任务完成、失败或待确认状态同步到飞书。

### [analyzing-projects](./analyzing-projects/README.md)

面向中文用户的通用项目分析 Skill，可分析已有代码库并生成源码级的项目架构与实现文档，帮助开发者快速理解项目结构、核心模块和运行机制。它采用通用 Agent Skill 目录结构，可安装到多种支持 Skills 的智能编码工具中。

## 已集成模块

### [tech-doc-translator](./tech-doc-translator/README.md)

面向理工科英文技术文档的结构化翻译 Skill 与脚本集。Practice-first 执行计划 Tickets 01–07 已完成，覆盖单页 HTML、分页代码文档、数学/深层嵌套参考手册、多页面 API/DSL 文档以及工作包编排、术语合并与中断恢复，并已通过 cuSPARSE 官方文档前三章的真实试译终验。
