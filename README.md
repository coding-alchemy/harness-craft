# Harness Craft

Harness Craft 是一个 Harness 工具箱，用于沉淀可复用的 Agent Skills、连接器与工程辅助工具，帮助开发者扩展智能编码工具的项目分析和任务协作能力。

## 已集成工具

### [feishu-connector](./feishu-connector/README.md)

飞书消息连接器，可通过企业自建应用机器人发送纯文本、富文本和任务状态卡片。它支持分层配置、显式外发授权、按需自动通知、失败重试和敏感信息脱敏，适合将 Agent 的任务完成、失败或待确认状态同步到飞书。

### [analyzing-projects](./analyzing-projects/README.md)

面向中文用户的通用项目分析 Skill，可分析已有代码库并生成源码级的项目架构与实现文档，帮助开发者快速理解项目结构、核心模块和运行机制。它采用通用 Agent Skill 目录结构，可安装到多种支持 Skills 的智能编码工具中。

### [tech-doc-translator](./tech-doc-translator/README.md)

面向理工科英文技术文档的结构化翻译 Skill 与脚本集，覆盖单页 HTML、分页代码文档、数学/深层嵌套参考手册、多页面 API/DSL 文档以及工作包编排、术语合并与中断恢复，并已使用 12 套 NVIDIA 官方文档完成扩展验证，并构建了NVIDIA文档翻译的术语库。完整 Skill 位于 `tech-doc-translator/skills/tech-doc-translator/`，可用 `python3 tech-doc-translator/install_skill.py` 安装到 Codex。

### [online-media-reader](./online-media-reader/README.md)

在线媒体文字读取 Skill：从抖音、B站和小红书的公开单条链接自适应取得可靠字幕、语音转写或图片 OCR，生成标明来源的 Markdown，默认清理媒体与匿名 Cookie。完整 Skill 位于 `online-media-reader/skills/online-media-reader/`，可用 `python3 online-media-reader/install_skill.py` 安装到 Codex。

### [agent-token-audit](./agent-token-audit/README.md)

V0.3：按任务、会话或整体范围读取 Codex、ZCode 的本地 token 记录，展示输入、输出、缓存、费用估算和来源支持的性能指标。支持 Harness Skill、本地网页与 Python CLI，提供默认官网价格、明确更新、快捷时间范围、按需明细及 Markdown/CSV/JSON 导出；当前限制见模块说明。

### [frontend-design-workflow](./frontend-design-workflow/README.md)

前端设计工作流 Skill，支持已有页面优化、新页面设计、参考截图风格迁移与仅评估，按需读取视觉方法，并将实际使用、能力缺口和结果保存为独立任务记录。也可回顾历史记录，提出建议并关联获授权改进后的结果。完整 Skill 位于 `frontend-design-workflow/skills/frontend-design-workflow/`，可直接读取或完整复制使用。
