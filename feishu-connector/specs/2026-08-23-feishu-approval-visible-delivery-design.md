# 飞书审批可见外发设计

| 元数据 | 内容 |
| --- | --- |
| 文档版本 | V1.2 |
| 文档状态 | 待评审 |
| 创建日期 | 2026-08-23 |
| 修订日期 | 2026-08-23 |
| 适用范围 | `feishu-connector` 的 Codex 消息外发调用链 |
| 权威基线 | [飞书消息连接器当前合同](feishu-connector.md) |

## 1. 问题与根因

当前 Codex 可能先申请执行 `python3 .../feishu_notify.py stdin`，审批通过并创建进程后，再通过独立 stdin 写入消息正文。自动审批发生在进程创建前，因此审批器只能看到 `... stdin`，看不到之后才写入的正文，无法判断实际外发内容。

现有验证已证明两点：

- 使用 `stdin` 申请真实发送时，审批因实际 payload 不可见而拒绝；
- 将完整正文放入初始 `task --content ...` 命令后，审批通过并成功发送。

根因是审批时序与动态 stdin 不兼容，不是飞书客户端、JSON 白名单或网络重试错误。彻底解决必须让真实发送正文出现在初始审批命令中，并保证审批后执行的参数与该命令一致。

## 2. 目标、约束与范围

### 2.1 核心目标

Codex 发送飞书消息时，初始审批请求包含实际消息类型和全部动态字段；审批器不再因“stdin 中消息正文不可见”而拒绝。审批通过后，测试接收人收到的内容与审批命令还原出的 argv 逐字符一致。

直接验收证据是：一条包含引号、Shell 元字符、换行和 Unicode 的测试消息，审批记录展示完整动态字段，发送 stdout 出现 `Feishu message sent`，测试接收人只收到一条且正文一致。

### 2.2 硬约束

- 不引入 MCP Server、Codex Plugin、第三方 SDK、新运行时文件或新依赖。
- 只新增一个外部接口 `prepare-shell`；真实外发仍由现有 `send`、`rich` 和 `task` 完成。
- 固定接收人、授权规则、配置优先级、Secret 规则、卡片结构、自动通知、进程内重试、UUID、退出码和通知失败隔离保持不变。
- 保留现有 stdin 白名单入口，供不存在审批前 payload 可见性要求的非 Codex 环境使用。
- Codex 审批可见路径要求 POSIX 操作系统和 POSIX Shell，验证环境为 macOS/Linux。`prepare-shell` 在 `os.name != "posix"` 时失败；Skill 只在执行器使用 POSIX Shell 时选择该路径。
- `shlex.join()` 生成的完整命令以 UTF-8 计不得超过 96 KiB（98,304 字节），不计 stdout 追加的最后一个换行。限制包含解释器、入口、项目根目录、固定选项、动态字段和引用开销，不是正文字数限制。
- 超限、平台不支持、准备失败、命令无法提交或审批拒绝时均不发送，不截断、不拆分、不回退 stdin、文件或环境变量传参。
- 完整正文会出现在 Codex 工具调用、审批记录和可能的会话记录中；Skill 继续禁止附加凭据、Token、配置值、完整日志、Diff、内部推理或其他未要求上下文。

### 2.3 不在范围内

- PowerShell、`cmd.exe` 或其他非 POSIX Shell 的命令序列化；
- 多接收人、动态接收人、任意 URL、任意消息类型或任意卡片 JSON；
- 修改飞书 HTTP 请求、鉴权、接收人选择、卡片渲染或重试策略；
- 通过关闭审批、扩大网络权限或增加宽泛命令规则绕过审核。

## 3. 方案决策

| 方案 | 优点 | 不采用原因 |
| --- | --- | --- |
| Agent 直接拼写 Shell 命令 | 改动最少 | 引用正确性分散在每次调用，无法用仓库测试锁定 |
| 本地 `prepare-shell` | 一个小接口集中白名单、路径、引用和长度处理，可离线测试 | 采用 |
| 结构化 MCP 工具 | 参数天然结构化 | 为一个固定接收人的本地连接器增加协议、进程和安装复杂度 |

采用本地 `prepare-shell`。删除该模块后，白名单解析、参数规范化、Shell 引用和长度处理会重新分散到调用方，因此该模块提供了实际深度；它不是对现有发送命令的浅层别名。

## 4. 模块与接口

### 4.1 外部接口

新增离线子命令：

```bash
python3 scripts/feishu_notify.py prepare-shell
python3 scripts/feishu_notify.py --project-root /absolute/project/path prepare-shell
```

第二种形式中的全局 `--project-root` 可选。

它通过 stdin 接受现有四种精确字段白名单，不增加第二套消息 schema：

| `flow` | 必需字段 | 生成的发送接口 |
| --- | --- | --- |
| `send` | `message` | `send` |
| `rich` | `title`、`content` | `rich` |
| `task` | `status`、`project`、`conversation`、`content` | 显式 `task` |
| `task-auto` | `status`、`project`、`conversation`、`content` | `task --auto` |

例如：

```json
{"flow":"task","status":"success","project":"HETU","conversation":"阶段5评审","content":"已完成"}
```

成功时 stdout 严格为 `<完整 POSIX Shell 命令>\n`，退出码为 `0`。命令正文可以包含被单引号保护的换行；调用方只移除 stdout 最后追加的一个换行，其余字符不得修改。

失败时退出码为 `2`，stdout 为空，stderr 只输出固定、简短的准备错误。`prepare-shell` 不读取飞书 JSON 配置、不构造 `FeishuClient`、不访问网络、不发送消息。

### 4.2 内部职责

命令准备逻辑留在现有 `feishu_connector.cli` 模块，按以下顺序完成：

1. 使用现有重复键拒绝和四种 flow 白名单读取 JSON。
2. 复用现有 CLI parser 校验状态、空值、单行字段、Unicode 和 NUL；不得维护另一套字段校验。
3. 复用现有 stdin-to-argv 映射，再仅为生成命令将带值选项规范化为单个 `--name=value` argv 元素，确保以 `-` 开头的合法正文不会被 `argparse` 误判为选项。现有 stdin 的 argv 表示和解析行为不变。
4. 使用现有项目根目录解析规则，将显式 `--project-root`、Git 根目录或当前目录解析为绝对路径；最终命令始终包含 `--project-root=<绝对路径>`，避免准备与发送工作目录不同而改变项目配置选择。该步骤允许调用现有本地 Git 根目录探测，但不读取配置内容。
5. 使用 `sys.executable`、当前 launcher 的绝对路径、解析后的项目根目录和规范化发送 argv 构造完整 argv。解释器、launcher 或项目根目录不能解析时失败。
6. 使用标准库 `shlex.join()` 序列化完整 argv；不自行实现引用算法，也不生成 `stdin`、Python 代码、管道、重定向、环境变量赋值、命令替换或第二层 Shell。
7. 检查命令字符串的 UTF-8 长度。恰好 98,304 字节允许；超过时退出 `2`，stderr 输出 `Prepared command exceeds 96 KiB limit`，stdout 为空。

`--name=value` 只存在于 `prepare-shell` 生成的发送命令中。动态值仍只占一个 argv 元素且不经过 Shell 插值；现有直接 argv 和 stdin 接口不改为该表示。

### 4.3 Codex 调用合同

1. Agent 以任务工作区为 workdir，在网络隔离沙箱内调用 `prepare-shell`，通过独立 stdin 写入白名单 JSON；显式传入 `--project-root` 时仍按现有优先级覆盖 workdir 推断。
2. 准备成功后，Agent 只移除 stdout 最后的换行，将其余命令原样作为新的 `exec_command`。
3. 真实命令设置 `sandbox_permissions=require_escalated`，审批理由仅说明向已配置固定接收人发送本次可见正文。
4. 审批拒绝或命令无法提交时停止，不重试、不重建命令、不切换传参渠道。
5. 审批通过后沿用现有发送、自动 no-op、进程内重试和结果判断；只有 stdout 出现 `Feishu message sent` 才报告已发送。

```text
白名单 JSON → prepare-shell（离线）→ 完整发送命令 → Codex 审批 → send/rich/task → 固定接收人
```

## 5. 安全与失败行为

### 5.1 安全性质

- **审批可见：** 消息类型和动态字段位于真实发送命令中，不依赖审批后 stdin。
- **防命令注入：** 所有动态字段先成为固定位置的 argv 元素，再由 `shlex.join()` 引用；引号、`$()`、反引号、换行、管道符和重定向符只能还原为参数内容。
- **审批与执行绑定：** Agent 不得重建或补充命令；正文变化会改变审批请求并触发新审批。
- **配置选择稳定：** 生成命令携带解析后的绝对项目根目录，不依赖第二次执行时的工作目录。
- **失败关闭：** 任何准备或审批失败都不会转入不透明传参路径。

### 5.2 错误结果

| 条件 | 结果 |
| --- | --- |
| JSON、白名单或字段校验失败 | 退出 `2`，`Invalid stdin input`，stdout 为空 |
| 非 POSIX 平台、解释器、launcher 或项目根目录不可解析 | 退出 `2`，准备失败，stdout 为空 |
| 完整命令超过 98,304 字节 | 退出 `2`，`Prepared command exceeds 96 KiB limit`，stdout 为空 |
| 执行器无法提交命令或审批拒绝 | 报告未发送，不跨路径重试 |
| 真实发送失败 | 沿用现有退出码 `3`、`4`、`5` 和投递状态语义 |
| `task --auto` 且 `autoNotify=false` | 沿用退出 `0` 的 `skipped`，不联网 |

通知失败继续不得改变 Agent 原任务结果。

## 6. 验证设计

### 6.1 离线测试

1. **白名单复用：** 四种 flow 经 stdin 和 `prepare-shell` 使用同一字段映射与 parser 校验；生成命令只改变选项的 argv 表示，不改变解析后的字段值。未知字段、重复键、错误类型、非法状态、空值、非法 Unicode 和 NUL 均失败。
2. **参数往返：** 使用单引号、双引号、`$()`、反引号、反斜杠、换行、前导 `-`、中文、Emoji 和 Markdown 代码块，验证 `shlex.split(command)` 得到的动态值逐字符一致。
3. **命令封闭：** 解析结果只含当前解释器、固定 launcher、绝对 `--project-root`、`send|rich|task` 和允许选项；不得出现 `stdin`、额外命令、管道、重定向或环境变量赋值。
4. **配置根目录：** 显式项目根目录、Git 根目录和非 Git 当前目录分别生成正确绝对路径；在不同工作目录解析生成命令时，项目配置选择仍不变。
5. **长度边界：** 按完整命令 UTF-8 字节数覆盖小于、等于和大于 98,304；同时覆盖中文和大量单引号，证明统计包含编码与引用开销。超限时 stdout 为空且不读取配置、不构造客户端。
6. **离线与安装：** 准备过程无 HTTP、无飞书配置读取；安装后的自包含 Skill 可脱离源码仓库运行 `prepare-shell`。
7. **行为合同：** Skill、README 和快速使用文档明确 Codex 路由、POSIX、96 KiB、失败关闭和禁止 stdin 回退；现有完整测试套件继续通过。

往返测试必须在删除正文参数、改回不透明 stdin 或移除 `shlex.join()` 时失败，不能只检查关键词或命令前缀。

### 6.2 真实验收

真实验收只使用测试应用和测试用户，并由用户明确授权一次：

1. 发送一条同时包含 `'`、`"`、`$()`、反引号、反斜杠、Markdown 换行、中文和 Emoji 的消息。
2. 保留审批记录，确认初始请求展示 `send|rich|task` 及全部动态字段，不是 `... stdin`。
3. 确认 stdout 出现 `Feishu message sent`，测试用户只收到一条消息，正文和卡片字段与 `shlex.split(command)` 还原值逐字符一致。
4. 另执行一次拒绝路径，确认真实发送进程未创建；不向飞书重复发送负向测试消息。

## 7. 文档与兼容性

实施时只修改与本设计直接相关的现有文件：

- `feishu-connector/skills/feishu-notify/scripts/feishu_connector/cli.py`；
- `feishu-connector/skills/feishu-notify/SKILL.md`；
- `feishu-connector/README.md`；
- `feishu-connector/docs/USAGE.md`；
- `feishu-connector/specs/feishu-connector.md`；
- `feishu-connector/CHANGELOG.md`；
- 对应 CLI、Skill 和安装器测试。

README 和 `docs/USAGE.md` 必须在 Codex 调用说明附近直接写明：

- 审批可见路径要求 POSIX 操作系统和 POSIX Shell，并已在 macOS/Linux 验证；
- 完整生成命令按 UTF-8 计上限为 96 KiB，且包含路径、选项和引用开销；
- 超限时不发送、不截断、不拆分、不回退 stdin；
- PowerShell 和 `cmd.exe` 不受支持。

不得只在 CHANGELOG、规格或错误信息中间接说明这些边界。

兼容性结论：现有直接 argv 和非 Codex stdin 入口继续存在；四种 flow、配置、发送、argv 表示和错误语义不变。`--name=value` 只用于新生成的审批命令。安装清单不增加文件。

## 8. 成功标准

1. Codex 的真实发送审批命令包含完整消息类型和动态字段，不再是 `feishu_notify.py stdin`。
2. 在 96 KiB 上限内，合法正文经 JSON、命令准备、POSIX Shell 解析和飞书发送后逐字符一致，且不能改变命令结构。
3. 非 POSIX、超限、准备失败和审批拒绝均无真实发送，并且没有不透明回退。
4. 解析后的项目根目录被写入生成命令；准备和发送工作目录不同也不会改变项目配置选择。
5. README 和快速使用文档明确 POSIX 与 96 KiB 边界；全部离线测试、`git diff --check` 和相对链接检查通过，并完成一次真实审批可见验收。

## 9. 基线守恒映射

| 权威基线要求 | 设计位置 | 直接验证 |
| --- | --- | --- |
| 固定接收人和一次外发授权 | 2.2、4.3、5.1 | Skill 合同；真实测试用户只收到一条 |
| `send`、`rich`、`task`、`task --auto` 语义 | 2.2、4.1、4.2 | 四种 flow 映射；现有 CLI 测试 |
| 正文原样、不截断、不拆分 | 2.2、5、6 | argv 往返；真实逐字符比对；失败关闭测试 |
| 配置优先级与 `--project-root` | 2.2、4.2、5.1 | 三种根目录测试；跨工作目录测试 |
| 配置 Secret、固定卡片、重试、UUID 和退出码 | 2.2、5.2 | 现有配置、渲染、客户端和 CLI 测试 |
| 审批拒绝即停止 | 2.2、4.3、5 | 拒绝路径无发送进程 |
| stdin 白名单与非 Codex 兼容 | 2.2、4.1、7 | 现有 stdin 测试；共享映射测试 |
| Python 3.9+ 标准库和自包含安装 | 2.2、3、6.1、7 | 无新依赖；安装后 smoke test |
| 用户接受的 POSIX 与 96 KiB 限制 | 2.2、5、6、7、8 | 平台与字节边界测试；文档合同 |

负向差异审计：本设计不删除或弱化权威基线。用户已接受 POSIX 和 96 KiB 限制，两者只约束 Codex 审批可见路径。现有直接 argv 和非 Codex stdin 接口不改变；`--name=value` 是新接口内部生成的表示，不扩大现有接口范围。

## 10. 假设与参考

假设 Codex 在目标 macOS/Linux 环境中把 `exec_command` 交给 POSIX Shell；程序只能检查 POSIX 操作系统，不能可靠识别执行器最终选择的 Shell。96 KiB 是本连接器定义的稳定产品上限，不等同于操作系统、Codex 或飞书的理论上限；未超限的请求仍可能被后续执行器、审批策略或飞书拒绝，并按失败关闭处理。

参考资料：

- [OpenAI Docs：Auto-review — What the reviewer sees](https://learn.chatgpt.com/docs/sandboxing/auto-review#what-the-reviewer-sees)
- [飞书消息连接器当前合同](feishu-connector.md)
- [飞书连接器平衡精简设计](2026-08-10-feishu-connector-balanced-simplification-design.md)
