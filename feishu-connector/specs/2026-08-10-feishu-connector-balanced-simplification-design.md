# 飞书连接器平衡精简设计

## 1. 目标

在保留飞书消息发送、配置、通知和必要安全契约的前提下，将飞书连接器相对 `main` 的新增规模从 9,507 行降低到预计 2,600–3,200 行。

最终交付物是一个自包含的 Codex Skill。Python 代码是供 Agent 使用的内部运行时；不作为通用 Python 包安装，不加入 `PATH`，也不承诺供外部 Python 调用方兼容导入。

## 2. 范围

精简后的连接器继续支持：

- 使用飞书企业自建应用机器人；
- 向一个已配置的 Open ID 发送纯文本私聊消息；
- 显式消息和固定格式的任务通知；
- 使用 `Codex` 或 `OpenCode` 作为任务来源标签；
- 通过合并后的配置控制自动通知；
- 按叶子字段合并配置，优先级为环境变量 > 项目 JSON > 全局 JSON；
- 禁止在项目 JSON 中配置 `appSecret`，并检查包含 Secret 的全局 JSON 文件权限；
- 对网络、限流和服务端错误重试，并在同一次逻辑发送中复用消息 UUID；
- 通知失败不影响 Agent 原任务结果；
- 运行时仅依赖 Python 3.9 及以上版本的标准库。

本次精简删除：

- 通用用户级 Python package 和外部导入兼容要求；
- `site-packages`、pip 和 `~/.local/bin` 安装；
- 独立 Adapter 子进程；
- 旧 `.env` 检测与迁移提示；
- 包管理器级文件系统竞态防御；
- 已执行完成的实施计划及重复的文档测试；
- 本期范围内的 OpenCode 专用安装器或 Hook 集成。

## 3. 仓库结构

Skill 目录是运行时 Python 代码的唯一源码位置：

```text
feishu-connector/
├── install_skill.py
├── README.md
├── docs/
│   └── USAGE.md
├── specs/
│   ├── feishu-connector.md
│   ├── 2026-08-08-feishu-connector-installer-design.md
│   └── 2026-08-10-feishu-connector-balanced-simplification-design.md
├── skills/
│   └── feishu-notify/
│       ├── SKILL.md
│       └── scripts/
│           ├── feishu_notify.py
│           └── feishu_connector/
│               ├── __init__.py
│               ├── client.py
│               ├── config.py
│               └── cli.py
└── tests/
    ├── test_client.py
    ├── test_config.py
    ├── test_cli.py
    ├── test_skill.py
    └── test_installer.py
```

各文件职责如下：

- `client.py`：飞书 Token 获取、消息发送、响应分类、重试和 UUID 行为。
- `config.py`：配置文件、环境变量覆盖、校验、Secret 规则和配置来源诊断。
- `cli.py`：`send`、`task`、`config` 和安全 stdin JSON 分发。
- `feishu_notify.py`：调用 `feishu_connector.cli.main()` 的轻量可执行入口。
- `SKILL.md`：只描述 Agent 的决策和调用规则，不复制 HTTP 或配置逻辑。
- `install_skill.py`：只安装自包含 Skill。

仓库中不得在其他位置提交第二份 Python 运行模块。`${CODEX_HOME}/skills/feishu-notify` 是安装产物，不是另一份源码。

## 4. Skill 安装

安装命令为：

```bash
python3 feishu-connector/install_skill.py
python3 feishu-connector/install_skill.py --force
```

源目录是 `feishu-connector/skills/feishu-notify`，目标目录是 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`。

安装器必须：

- 只管理 `SKILL.md` 和 `scripts/` 下明确列出的 Python 文件；
- 创建缺失的目标目录；
- 内容和权限均一致时视为成功；
- 受管文件不一致时默认拒绝，只有传入 `--force` 才允许覆盖；
- 使用同目录临时文件和 `os.replace()` 写入单个文件；
- 设置约定的文件权限，并验证最终受管文件；
- 不创建飞书配置、凭据、Token 或 Open ID；
- 不安装 launcher，也不写入 `site-packages`；
- 不递归删除目标目录或目标中的未知文件；
- 不自动删除旧版 `~/.local` 安装布局中的文件。

安装器采用普通单用户威胁模型：防止一般误覆盖，但不承诺抵御同一用户下的恶意进程在安装窗口内替换目录、硬链接或临时文件。因此不再使用从根目录逐级打开的目录描述符、inode 链验证、`ctypes` rename 调用或 staging inode 恢复定位。

旧版 `~/.local/share/feishu-connector` 和 `~/.local/bin/feishu-notify*` 的一次性清理由文档说明，安装器不自动执行删除。

## 5. Agent 调用

安装后的固定入口为：

```text
${CODEX_HOME:-~/.codex}/skills/feishu-notify/scripts/feishu_notify.py
```

支持 argv 的 Agent 直接调用：

```text
python3 <入口> send --message <字面值>
python3 <入口> task [--auto] --status <值> --task <值> --summary <值> --repo <值> --branch <值>
python3 <入口> config
```

如果执行工具只接受 Shell 命令字符串，但提供独立 stdin 通道，Agent 使用一个固定命令：

```text
python3 <入口> stdin
```

并通过 stdin 传入且只传入一个 JSON 对象：

```json
{"flow":"send","message":"需要发送的原始消息"}
```

或：

```json
{"flow":"task-auto","status":"success","task":"简短任务名","summary":"简短摘要","repo":"仓库名","branch":"分支名"}
```

`stdin` 子命令在同一进程内完成校验和分发，不将动态数据拼接进 Shell 命令，也不启动第二个 Python 进程。直接 argv 和 stdin 两条路径必须调用同一套内部配置、渲染和发送函数。

## 6. 配置与错误

当前有效的配置优先级保持为：

1. 进程环境变量；
2. `<项目根目录>/.config/feishu-connector/config.json`；
3. `~/.config/feishu-connector/config.json`。

各字段独立合并。项目文件可以配置 `appId`、`recipient.openId` 和 `notification.autoNotify`，但出现任何 `appSecret` 都必须拒绝。在 POSIX 系统上，包含 `appSecret` 的全局文件必须具有私有权限。`config` 命令只显示字段来源，不显示配置值，也不访问网络。

旧的仓库内 `.env` 既不读取也不检测，不再输出迁移提示。

退出码保持为：

- `0`：发送成功，或自动通知处于关闭状态；
- `2`：CLI 或 stdin 输入无效；
- `3`：配置错误；
- `4`：不可重试的飞书/API 错误；
- `5`：可重试错误耗尽重试次数。

Token 请求和消息请求保留对网络失败、HTTP 429、飞书限流和 HTTP 5xx 的代表性重试处理。消息重试复用一个 UUID。诊断必须脱敏，不得暴露 Secret、Token、Authorization 或完整 Open ID。

## 7. 测试策略

测试验证公开行为，不再绑定私有系统调用顺序。目标规模约为 50–65 个离线测试、1,200–1,500 行测试代码。

保留以下覆盖：

- Token 和纯文本消息 payload；
- 消息重试期间复用一个 UUID；
- 代表性的网络、429、5xx 和不可重试错误；
- 按字段合并的配置优先级和 schema 校验；
- 项目 Secret 禁止和全局 Secret 权限；
- `send`、`task`、自动通知门控、`config` 和 stdin JSON；
- 退出码、脱敏和通知结果隔离；
- 全新 Skill 安装、幂等、冲突拒绝、`--force`，以及脱离源码仓库后的执行；
- Skill 中关于 argv 安全和 Shell-only stdin fallback 的关键约束。

删除或合并以下覆盖：

- 父目录、硬链接、临时文件名和 staging inode 竞态调度；
- 对所有 `http.client` 读取失败的穷举；
- 独立 Adapter 子进程行为；
- 旧 launcher 和 Python package 安装；
- 旧 `.env` 迁移；
- README 和 USAGE 的精确文案；
- 重复的任务参数 fixture 和重叠校验测试。

测试不得使用真实飞书凭据，也不得向飞书发起真实请求。

## 8. 文档清理

删除以下四份已执行完成的实施计划：

- `specs/plans/2026-08-05-feishu-connector-phase-1.md`；
- `specs/plans/2026-08-07-feishu-connector-phase-2.md`；
- `specs/plans/2026-08-08-feishu-connector-hardening.md`；
- `specs/plans/2026-08-08-feishu-connector-installer.md`。

同时删除已完成的使用指南设计。Git 历史继续保留这些过程文档。

`specs/feishu-connector.md` 改为简洁的当前契约，一期内容只保留简短历史背景。安装器设计改写为仅安装 Skill 的普通单用户模型。README 保留完整说明，USAGE 缩减为 30–40 行快速开始并链接 README。

## 9. 验收标准

1. 仓库中只有一份运行时 Python 模块，位于 `skills/feishu-notify/scripts`。
2. `install_skill.py` 安装出的自包含 Skill 在源码仓库移动或删除后仍能运行。
3. 不安装 PATH launcher、通用 Python package、`site-packages` 条目或独立 Adapter。
4. 直接 argv 和 stdin JSON 两条路径产生一致的显式通知与自动通知行为。
5. 配置优先级、Secret 规则、重试、UUID 幂等、退出码和结果隔离保持不变。
6. 不读取或修改旧 `.env` 迁移路径及旧 `~/.local` 安装文件。
7. 所有测试离线运行，并在 Python 3.9 及以上版本通过。
8. 删除已完成的实施计划和重复的文档契约测试。
9. 相对 `main` 的仓库新增规模目标为 2,600–3,200 行，其中运行代码约 700–900 行、测试约 1,200–1,500 行。行数目标用于指导精简，但不得覆盖必需行为。
