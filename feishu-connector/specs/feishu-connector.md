# 飞书消息连接器需求与设计

> 状态：书面规格待评审
>
> 目标：提供一个由 Codex 调用、未来可被 OpenCode 复用的轻量飞书消息连接器，通过企业自建应用机器人向固定用户发送纯文本私聊消息。

## 1. 背景与结论

最初方案考虑使用飞书群自定义机器人 Webhook。根据飞书官方能力边界，自定义机器人只能向其所在群聊发送消息，不能直接向用户发起私聊；在群内 `@` 用户也不等同于私聊。

本项目因此采用飞书企业自建应用机器人和发送消息 API。第一版以最少组件完成固定用户私聊，同时把飞书协议实现与 Agent 适配解耦：通用 Python CLI 负责鉴权和发送，Codex Skill 只负责判断何时调用 CLI。未来 OpenCode 通过自己的薄适配层调用同一 CLI，不复制飞书逻辑。

```text
Codex Skill ─┐
             ├──> Python CLI ──> tenant_access_token ──> 飞书消息 API ──> 固定用户
手动命令 ────┤
             │
OpenCode ────┘（二期或后续）
```

## 2. 目标与非目标

### 2.1 第一期目标

1. 通过飞书企业自建应用机器人向一个固定用户发送纯文本私聊消息。
2. 提供可人工执行的通用 Python CLI。
3. 提供调用该 CLI 的 Codex Skill。
4. 支持用户显式要求发送消息。
5. 支持通过配置开启 Codex 任务结束自动通知。
6. 自动通知包含状态、任务名称、简短摘要、仓库和分支。
7. 通知失败不得改变 Codex 或 OpenCode 原任务的最终状态。
8. 只使用 Python 3 标准库，不要求安装第三方依赖或运行常驻服务。
9. 为未来 OpenCode 复用保留稳定的 CLI 接口。

### 2.2 第二期目标

1. 支持全局兜底配置和项目级覆盖配置。
2. 配置按字段合并，项目可以只覆盖接收人或自动通知开关。
3. 支持环境变量作为最高优先级覆盖来源。
4. 项目配置可以提交到 Git，但不得包含 `appSecret`。
5. 提供不泄露敏感值的配置来源诊断能力。
6. 增加 OpenCode 薄适配层时，不修改飞书鉴权和发送核心逻辑。

### 2.3 非目标

以下能力不在第一期范围内；除多级配置外，也不作为第二期的默认承诺：

- 接收或处理飞书消息、事件和回调。
- 群聊发送、群内 `@`、多接收人或动态选择接收人。
- 富文本、Markdown、图片、文件、音视频或交互卡片。
- 消息撤回、更新、回复或会话管理。
- 飞书商店应用、多租户 SaaS 或跨租户私聊。
- Web 服务、守护进程、数据库、消息队列或 Web 管理后台。
- 自动申请飞书权限、自动发布应用或自动查询目标用户 Open ID。
- 在第一期实现 OpenCode Skill。

## 3. 用户与使用场景

### 3.1 角色

| 角色 | 职责 |
|---|---|
| 飞书应用管理员 | 创建企业自建应用、开启机器人能力、授予最小消息权限、配置可用范围并发布应用 |
| 本地使用者 | 保存凭据和固定接收者 Open ID，决定是否开启自动通知 |
| Codex | 按 Skill 约定执行显式发送或任务结束通知 |
| OpenCode | 后续通过自己的适配层调用相同 CLI |

### 3.2 核心场景

#### 场景 A：手动发送

用户明确要求 Codex 将指定文本发送到飞书，或者用户直接运行 CLI。该场景不受自动通知开关影响。

#### 场景 B：自动任务通知

Codex Skill 在任务结束时读取自动通知开关。开启时，它收集任务结果并调用 CLI；关闭或未配置时不发送。

这里的“自动通知”属于 Skill 工作流约定，不是 Codex 平台级全局 Hook。要让一个仓库中的任务默认执行该约定，需要在该仓库的 Agent 指令中启用相应 Skill 工作流。

#### 场景 C：OpenCode 复用

OpenCode 适配层以相同参数调用通用 CLI。飞书 Token、消息请求、重试、脱敏和错误分类不在适配层重复实现。

## 4. 飞书前提条件

使用者必须在飞书开发者后台完成：

1. 创建企业自建应用。
2. 开启机器人能力，并发布包含该能力的应用版本。
3. 申请以应用身份发送消息所需的最小权限，例如 `im:message:send_as_bot`。
4. 将固定接收用户加入应用机器人可用范围。
5. 获取应用的 App ID、App Secret，以及该应用下目标用户的 Open ID。

目标用户可以在客户端停止接收机器人消息。连接器需要把此类飞书业务错误作为不可重试错误报告，而不能假定应用拥有永久送达权。

## 5. 第一期架构

### 5.1 建议目录

```text
feishu-connector/
├── specs/
│   └── feishu-connector.md
├── scripts/
│   └── feishu_notify.py
├── skills/
│   └── feishu-notify/
│       └── SKILL.md
├── tests/
├── .env.example
└── README.md
```

### 5.2 组件职责

| 组件 | 唯一职责 |
|---|---|
| `scripts/feishu_notify.py` | 读取配置、校验参数、获取 Token、构造纯文本消息、调用飞书 API、重试、脱敏并返回结果 |
| `skills/feishu-notify/SKILL.md` | 约束显式发送和自动通知的触发条件，采集任务字段并调用 CLI |
| `.env.example` | 描述第一期本地配置键，不包含真实值 |
| `README.md` | 说明飞书端准备、本地配置、手动命令、Codex 接入和排错 |
| `tests/` | 使用标准库测试 CLI、HTTP 调用、重试、配置和脱敏行为 |

Skill 不实现飞书协议，不读取或输出 App Secret，也不自行构造 Token 请求。

## 6. 第一期配置

### 6.1 配置文件

第一期从 `feishu-connector/.env` 读取以下配置：

```dotenv
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_RECEIVE_OPEN_ID=
FEISHU_AUTO_NOTIFY=false
```

约束如下：

- `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和 `FEISHU_RECEIVE_OPEN_ID` 是发送消息的必填项。
- `FEISHU_AUTO_NOTIFY` 只接受明确的布尔值；默认值为 `false`。
- 进程环境变量按字段覆盖 `.env` 中的同名值。
- 仓库只提交 `.env.example`；`feishu-connector/.env` 必须由 `.gitignore` 排除。
- CLI 不提供通过命令行参数传入 App Secret 的能力，避免 Secret 进入 Shell 历史或进程列表。
- `.env` 解析只需支持 `KEY=VALUE`、空行和以 `#` 开头的注释；不实现 Shell 求值、变量展开或命令替换。

### 6.2 Token 策略

第一期每次 CLI 调用都使用 App ID 和 App Secret 获取新的 `tenant_access_token`。Token 仅存在于当前进程内存，不写入磁盘，也不输出到日志。第一期不引入跨进程 Token 缓存，以减少失效、并发和缓存文件权限处理。

## 7. CLI 接口

CLI 提供两个子命令。

### 7.1 手动消息

```bash
python3 feishu-connector/scripts/feishu_notify.py send \
  --message "部署已经完成"
```

`--message` 必填且不能为空。CLI 将内容作为纯文本原样发送给固定 Open ID，不解析 Markdown 或模板语法。

### 7.2 任务通知

```bash
python3 feishu-connector/scripts/feishu_notify.py task \
  --status success \
  --task "修复登录问题" \
  --summary "修复 Token 刷新并通过测试" \
  --repo "harness-craft" \
  --branch "codex/fix-login"
```

参数约束：

- `--status` 必填，第一期允许 `success` 和 `failure`。
- `--task`、`--summary`、`--repo`、`--branch` 必填且不能为空。
- 所有字段都作为不可信纯文本处理，不执行 Shell 或模板求值。

Codex 任务消息固定渲染为：

```text
[Codex] SUCCESS
任务：修复登录问题
摘要：修复 Token 刷新并通过测试
仓库：harness-craft
分支：codex/fix-login
```

未来 OpenCode 适配层可以把首行来源改为 `[OpenCode]`，但不得改变其余字段语义。实现时可以为 CLI 增加一个有固定枚举值的来源参数，默认值为 `Codex`，以避免 OpenCode 通过拼接自由格式消息绕过统一模板。

### 7.3 退出行为

- 发送成功时退出码为 `0`。
- 输入、配置、鉴权、权限、网络或飞书业务错误使用非零退出码。
- 错误输出必须包含可排查的错误类别和飞书错误码（如有），但不得包含 Secret、Token 或完整 Open ID。
- Codex Skill 捕获非零退出码后只报告通知警告，保留原任务结果。
- 直接运行 CLI 时，非零退出码仍可被 Shell、CI 或未来 OpenCode 适配层检测。

## 8. 数据流

### 8.1 手动发送

```text
用户明确要求或直接执行 CLI
        │
        ▼
读取并合并 .env 与进程环境变量
        │
        ▼
校验配置和 --message
        │
        ▼
获取 tenant_access_token
        │
        ▼
POST /open-apis/im/v1/messages?receive_id_type=open_id
        │
        ▼
校验 HTTP 状态与飞书业务码，输出脱敏结果
```

### 8.2 自动通知

```text
Codex 任务结束
      │
      ▼
Skill 检查 FEISHU_AUTO_NOTIFY
      │
  ┌───┴────┐
 false    true
  │         │
不发送    收集状态、任务、摘要、仓库、分支
            │
            ▼
       调用 task 子命令
            │
       ┌────┴────┐
     成功       失败
      │           │
正常结束     警告但保留原任务结果
```

### 8.3 飞书请求

连接器使用应用身份调用消息 API：

```text
POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id
Authorization: Bearer <tenant_access_token>
Content-Type: application/json; charset=utf-8
```

消息请求体语义为：

```json
{
  "receive_id": "目标用户 Open ID",
  "msg_type": "text",
  "content": "序列化后的纯文本 JSON 字符串"
}
```

实现必须使用 JSON 编码器完成内层和外层序列化，不能手工拼接 JSON。

## 9. 可靠性与错误处理

### 9.1 错误分类

| 错误类别 | 示例 | 是否重试 |
|---|---|---|
| 输入错误 | 空消息、缺少任务字段、非法状态 | 否 |
| 配置错误 | 缺少 App ID、Secret 或 Open ID | 否 |
| 鉴权与权限错误 | 凭据无效、未授权、用户不在可用范围 | 否 |
| 接收人错误 | Open ID 无效、用户离职、用户拒收机器人消息 | 否 |
| 临时网络错误 | 超时、连接中断、DNS 临时失败 | 是 |
| 限流 | HTTP 429 或飞书限流业务错误 | 是 |
| 服务端错误 | HTTP 5xx | 是 |
| 未知业务错误 | 非零飞书业务码且不属于临时错误 | 否 |

### 9.2 重试规则

- 首次请求失败后最多额外重试两次，即单个阶段最多尝试三次。
- 使用有上限的指数退避，避免紧密循环。
- Token 请求和消息请求分别应用错误分类，不因消息权限错误重新获取 Token。
- 每次重试记录错误类别和尝试次数，但不记录敏感请求头或完整请求体。
- 达到重试上限后返回非零退出码。

### 9.3 原任务状态隔离

自动通知是附属动作。无论原任务成功或失败，通知失败都不能：

- 把成功任务改成失败；
- 覆盖原任务的失败原因；
- 触发新的实现或评审轮次；
- 阻止 Codex 返回原任务结果。

Skill 应在最终结果中追加一条简短的脱敏警告，说明飞书通知未送达以及可排查的错误类别。

## 10. 安全与隐私

1. App Secret 和 Token 是不得提交、不得输出的秘密；Open ID 是需要谨慎处理并在日志中脱敏的用户标识。
2. 日志、异常和测试快照不得出现 Secret、Token 或完整 Open ID；示例只能使用明显的假值。
3. 脱敏 Open ID 最多显示足以区分配置的首尾少量字符。
4. HTTP 调试信息不得输出 `Authorization` 请求头。
5. `.env` 不得提交 Git；`.env.example` 只能包含空值或明显的假值。
6. 只申请发送消息所需的最小飞书权限。
7. 固定用户必须明确位于应用可用范围内，不扩大为全员，除非使用者主动调整。
8. CLI 不读取与连接器无关的环境变量、文件、浏览器数据或系统凭据。
9. 消息内容由用户显式提供或由已确认的自动通知模板生成，Skill 不擅自附加源代码、日志、Diff 或其他可能敏感的上下文。

## 11. Codex Skill 行为

### 11.1 显式发送

当用户明确要求把某段内容发送到飞书时，Skill：

1. 确认待发送内容是用户指定文本。
2. 调用 `send --message`。
3. 根据 CLI 退出码报告送达或脱敏错误。

用户的显式发送请求不受 `FEISHU_AUTO_NOTIFY` 影响。

### 11.2 自动通知

自动通知仅在以下条件同时满足时执行：

- 项目指令启用了该 Skill 工作流；
- `FEISHU_AUTO_NOTIFY=true`；
- 当前任务即将返回最终结果；
- 尚未为同一任务结果发送通知。

Skill 必须把长结果压缩为简短摘要，不发送完整最终回复、完整日志或内部推理。Skill 不把通知失败当成原任务失败。

## 12. 测试策略

测试使用 Python 标准库 `unittest` 和 HTTP Mock，不访问真实飞书服务。

### 12.1 单元测试

- `.env` 的基础语法、注释、空行和非法行。
- 环境变量对 `.env` 的逐字段覆盖。
- 必填配置与布尔值校验。
- `send` 和 `task` 参数校验。
- 中文、换行、引号和反斜杠的 UTF-8 与 JSON 序列化。
- Token 请求的 URL、方法、请求头和请求体。
- 消息请求的 URL、查询参数、Bearer Token、固定 Open ID 和纯文本内容。
- 自动通知开启与关闭的调用决策。
- 两次额外重试的次数与退避调用。
- 不可重试错误不会重复请求。
- Secret、Token 和 Open ID 脱敏。
- CLI 成功与各类失败退出码。

### 12.2 手动端到端验收

真实端到端测试需要使用者提供飞书应用凭据，不进入默认自动测试。手动验收步骤必须：

1. 使用测试应用和测试用户配置本地 `.env`。
2. 运行 `send` 并确认用户收到纯文本私聊。
3. 运行 `task` 并确认五个任务字段正确展示。
4. 关闭自动通知并确认任务结束不发送。
5. 开启自动通知并确认任务结束发送一次。
6. 临时使用无效 Open ID，确认错误脱敏且不改变原任务结果。

## 13. 第一期验收标准

以下条件全部满足后，第一期才算完成：

1. 飞书端配置完成且 `.env` 有效时，CLI 能向固定 Open ID 发送纯文本私聊。
2. `send` 和 `task` 两个子命令均有稳定、文档化的参数接口。
3. Codex 可在用户明确要求时通过 Skill 发送消息。
4. 自动通知开启时，任务结束发送状态、任务名称、简短摘要、仓库和分支。
5. 自动通知关闭时，任务结束不发送消息。
6. 通知失败只产生脱敏警告，不改变原任务结果。
7. 项目不含真实凭据或 Token。
8. 所有默认测试离线运行并通过。
9. Python 实现只依赖标准库。
10. OpenCode 后续可以调用相同 CLI，不需要复制或修改飞书协议逻辑。

## 14. 第二期：多级 JSON 配置

### 14.1 配置路径

```text
全局兜底配置：
~/.config/feishu-connector/config.json

项目配置：
<项目根目录>/.config/feishu-connector/config.json
```

项目根目录按以下顺序确定：

1. CLI 显式传入的 `--project-root`。
2. 当前工作目录所属 Git 仓库的顶层目录。
3. 当前工作目录。

### 14.2 JSON 结构

完整的全局配置示例：

```json
{
  "app": {
    "appId": "cli_example",
    "appSecret": "example-secret"
  },
  "recipient": {
    "openId": "ou_example"
  },
  "notification": {
    "autoNotify": false
  }
}
```

可提交的项目配置示例：

```json
{
  "recipient": {
    "openId": "ou_project_user"
  },
  "notification": {
    "autoNotify": true
  }
}
```

### 14.3 合并优先级

二期配置优先级从高到低固定为：

```text
进程环境变量
    > 项目 JSON
    > 全局 JSON
```

合并规则：

- 按叶子字段合并，而不是整份文件或整个分组替换。
- 高优先级来源中未出现的字段继承低优先级值。
- 显式 `null` 不表示删除继承值，而是配置错误。
- 未识别字段是配置错误，避免拼写错误被静默忽略。
- 读取、解析或校验失败时，在发送任何网络请求前退出。

环境变量映射：

| 环境变量 | JSON 字段 |
|---|---|
| `FEISHU_APP_ID` | `app.appId` |
| `FEISHU_APP_SECRET` | `app.appSecret` |
| `FEISHU_RECEIVE_OPEN_ID` | `recipient.openId` |
| `FEISHU_AUTO_NOTIFY` | `notification.autoNotify` |

### 14.4 `.env` 迁移

二期不再读取一期 `feishu-connector/.env`。升级文档必须说明：

- App Secret 移至全局 JSON 或进程环境变量；
- 可提交的项目差异移至项目 JSON；
- 原 `.env` 在完成迁移后保留也不会生效；
- CLI 应在检测到旧 `.env` 且缺少有效二期配置时给出迁移提示，但不得读取或输出旧文件中的值。

### 14.5 项目配置安全规则

- 项目 JSON 允许提交 Git。
- 项目 JSON 中禁止出现 `appSecret` 字段，即使值为空或假值也必须拒绝。
- `appSecret` 只能来自环境变量或全局 JSON。
- 全局 JSON 包含 `appSecret` 时，CLI 必须检查文件权限；在支持 POSIX 权限的平台上，权限不得允许 group 或 other 读取或写入。
- 项目 JSON 可以覆盖 `appId`、`recipient.openId` 和 `notification.autoNotify`。
- 项目 JSON 可以按项目需要提交真实 Open ID；该标识受仓库访问控制保护，并且在 CLI 日志和诊断中仍须脱敏。
- 示例项目配置不得包含真实 Open ID。

### 14.6 配置诊断

二期 CLI 提供只读的配置诊断能力，至少显示每个有效字段的来源：

```text
app.appId: project
app.appSecret: global (redacted)
recipient.openId: environment (redacted)
notification.autoNotify: project
```

诊断输出不得显示 Secret、Token 或完整 Open ID，也不得发起网络请求。

### 14.7 二期验收标准

1. 三种来源按字段和固定优先级正确合并。
2. 项目配置可以只覆盖单个字段，其余值来自全局配置。
3. 环境变量只覆盖对应字段，不清除其他来源的值。
4. 项目 JSON 出现 `appSecret` 时，在网络请求前拒绝运行。
5. 全局配置缺失时，只要环境变量和项目配置共同提供所有必填项，仍可发送。
6. 全局配置权限过宽时，在支持权限检查的平台上拒绝使用其中的 Secret，并给出修复提示。
7. 配置来源诊断准确且不泄露敏感值。
8. 二期实现不读取一期 `.env`，并提供清晰迁移文档。
9. 增加 OpenCode 适配层时，飞书核心 CLI 无需修改。

## 15. 官方参考

- [飞书：发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)
- [飞书：自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)
- [飞书：应用可用范围](https://open.feishu.cn/document/home/introduction-to-scope-and-authorization/availability)
