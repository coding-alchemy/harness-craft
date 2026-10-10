# agent-token-audit 使用指南

agent-token-audit 读取 Codex、ZCode 已有的本地记录，按会话、任务或时间范围展示输入、输出、缓存读取、命中率和数据缺口。普通查询只展示，明确导出才保存。结果不估算缺失用量，也不换算费用或评价工作质量。当前支持与验收边界见[模块说明](../README.md#3-开发与验收)。

## 1. 快速开始

需要 Python 3.9+，无需额外 Python 包或前端构建。使用自然语言入口时，在仓库根目录选择对应 Harness 安装：

```bash
python3 --version

# 安装到 Codex
python3 agent-token-audit/install_skill.py --harness codex

# 或安装到 ZCode
python3 agent-token-audit/install_skill.py --harness zcode
```

重新加载 Harness 的 Skill 列表，然后发送：

> 使用 agent-token-audit，统计当前会话截至本条请求开始时的 token 用量。

按需要选择入口。CLI、网页和离线查看器可直接使用源码，无需安装 Skill；各入口计量口径相同：

| 使用方式 | 从哪里开始 |
| --- | --- |
| 自然语言 | [第 3 节](#3-在-agent-中用自然语言调用)的请求示例 |
| 独立终端 | [第 4 节](#4-使用命令行)的会话选择和统计命令 |
| 本地网页 | [第 6 节](#6-使用本地网页统计)的启动和操作步骤 |
| 查看已有 JSON | [第 7 节](#7-离线查看-json-报告)的离线查看器；不需要原始日志 |

安装命令在仓库根目录执行，统计和网页命令在 `agent-token-audit/` 目录执行。`SESSION_ID`、`TURN_1`、`REQUEST_ID` 等需要替换为候选列表的稳定 ID，示例时间需要改为实际范围。

## 2. 安装位置与升级

| Harness | 默认安装目录 |
| --- | --- |
| Codex | `~/.codex/skills/agent-token-audit`；设置了 `CODEX_HOME` 时使用其下的 `skills/agent-token-audit` |
| ZCode | `~/.zcode/skills/agent-token-audit` |

安装器复制完整的 `SKILL.md`、脚本和查看器，内容一致时可重复安装，不同则拒绝覆盖。升级可先安装到新目录核对；拒绝覆盖意味着旧安装仍未更新。

指定自选目标时，`--target` 必须指向完整 Skill 目录，而不是上一级 `skills/`：

```bash
python3 agent-token-audit/install_skill.py --harness codex \
  --target /tmp/token-audit-skill/agent-token-audit
```

自选目录不会自动加入 Skill 搜索路径，需让 Harness 能发现它，再重新加载 Skill 列表；刷新方式由 Harness 决定。

## 3. 在 Agent 中用自然语言调用

安装并加载后，直接描述统计对象和范围即可：

| 场景 | 示例请求 |
| --- | --- |
| 一个任务 | “统计本会话里实现登录功能这个任务的 token，包含子代理，排除中间讨论部署的轮次。” |
| 不连续轮次 | “只统计刚才确认的第 1、3、5 轮及其关联子代理。” |
| 仅主代理 | “只看这个任务的主代理常规调用。” |
| 整体用量 | “统计 Codex 从北京时间 2026 年 10 月 1 日零点到 8 日零点的整体用量，按日和模型展示。” |
| 保存 | “把这份结果导出为 JSON，保存到 `/tmp/token-audit/task.json`。” |
| 查看旧结果 | “展示 `/tmp/token-audit/task.json`，不要重算。” |
| 重算 | “按 `/tmp/token-audit/task.json` 的原范围和原截止点重新统计。” |
| 更新 | “保持原任务轮次，把截止点更新到本条请求开始，并另存新的 JSON。” |
| 解释 | “展示这份报告的轮次时间线，并定位消耗最高的模型对应明细。” |

Agent 优先使用可信的当前会话身份和已确认范围，通常无需手填 ID 或日志路径。缺少身份，或多个合理任务边界会影响结果时，需选择候选；任务名称不能唯一确定范围。

“截至现在”固定在本次统计请求自身的可信起点，后续消耗不追入结果；起点无法确认时，需选择可用截止点。再次统计同一任务沿用已确认范围，只有明确要求更新才扩展。

任务以执行轮次选择。一条追加消息可能仍属于同一轮次；排除无关轮次不会扣除所选调用实际携带的历史上下文 token。默认纳入有证据归属的后代子代理和内部调用，`仅主代理`的结果不能当作完整任务总量。

## 4. 使用命令行

在仓库根目录进入模块目录：

```bash
cd agent-token-audit
python3 skills/agent-token-audit/scripts/audit.py --help
```

安装后也可将脚本路径替换为安装目录下的 `scripts/audit.py`。全部操作和参数见 `--help`。

### 4.1 选择会话并统计

先用 `sessions` 查看会话及来源缺口，复制会话 ID，再按需列出轮次或统计整个会话：

```bash
python3 skills/agent-token-audit/scripts/audit.py sessions --harness codex

python3 skills/agent-token-audit/scripts/audit.py turns \
  --harness codex --session SESSION_ID

python3 skills/agent-token-audit/scripts/audit.py report \
  --harness codex --session SESSION_ID
```

使用 ZCode 时把 `--harness codex` 改为 `--harness zcode`。候选列表的 `id` 是稳定标识，序号、标题和任务名称不是。未指定截止点时，CLI 截止于命令开始。

Harness 提供当前身份时，可用 `--current` 替换 `--session SESSION_ID`。它只核对 `CODEX_THREAD_ID` 或 `ZCODE_SESSION_ID`，不按目录或最新日志猜会话，也不与显式会话或保存报告混用。独立终端通常没有这些身份，应使用候选 ID。

### 4.2 选择任务范围和展示方式

选择两个不连续轮次，并固定截止点：

```bash
python3 skills/agent-token-audit/scripts/audit.py report \
  --harness codex --session SESSION_ID \
  --turn TURN_1 --turn TURN_3 --label "登录功能" \
  --to "2026-10-08T00:00:00+08:00"
```

| 参数 | 作用 |
| --- | --- |
| `--turn ID` | 可重复指定连续或不连续轮次；不传为整个会话，重复 ID 不重复计量 |
| `--label "登录功能"` | 给范围命名，不自动选择轮次 |
| `--main-only` | 仅主代理常规调用，排除子代理及另列的内部辅助 |
| `--detail model`、`--detail agent`、`--detail turn` | 展示同一结果的独立明细视图，不再次加入总量 |
| `--format table`、`--format json`、`--format csv`、`--format markdown` | 改变标准输出，默认表格，不生成文件 |

比较不同查询时，使用相同固定截止点；保存文件见[第 5 节](#5-保存和复用报告)。

### 4.3 设置时间范围和截止点

时间必须带时区，区间为 `[from, to)`：包含下界，不包含上界。`from` 必须早于 `to`；可与 `--turn` 组合，按完整调用的结束或 usage 时间过滤，不按比例拆分跨边界调用。

例如，在上述命令中追加 `--from "2026-10-01T00:00:00+08:00"`，就限定为北京时间 1 日零点到 8 日零点内所选轮次的用量。

截止点有三种显式写法，互相排斥：

| 参数 | 使用条件 |
| --- | --- |
| `--to "2026-10-08T00:00:00+08:00"` | 指定历史上界 |
| `--request-id REQUEST_ID` | 已确认源中的本次统计请求，工具读取其自身创建或入队起点 |
| `--request-start "2026-10-08T09:30:00+08:00"` | 调用方已有可信请求时间；时间字符串本身不证明请求身份 |

使用源中的请求起点时，先列出候选 ID 和时间，确认后统计：

```bash
python3 skills/agent-token-audit/scripts/audit.py requests \
  --harness codex --session SESSION_ID

python3 skills/agent-token-audit/scripts/audit.py report \
  --harness codex --session SESSION_ID --request-id REQUEST_ID
```

Agent 稍后运行 CLI 的时间不等于用户发起统计的时间，不能据此声称已排除统计开销。已确认的系统注入或合成消息不能作为用户请求截止点。

### 4.4 查询整体用量

按北京时间查询一周内的 Codex 用量，展示日趋势和模型、会话排行：

```bash
python3 skills/agent-token-audit/scripts/audit.py overview \
  --harness codex \
  --from "2026-10-01T00:00:00+08:00" \
  --to "2026-10-08T00:00:00+08:00" --tz Asia/Shanghai
```

默认纳入来源全部会话，可追加 `--session SESSION_ID --session OTHER_SESSION_ID` 缩小集合。`overview` 不支持 `--current`；请求 ID 只确定截止点，不缩小会话集合。

`--tz` 控制日界，可用 IANA 名称或 `±HH:MM`（例如 `--tz "+08:00"`），省略时使用系统本地时区。无法可靠分日的跨日累计区间单列，日趋势之和可能小于总览。

整体查询在一份去重记录上汇总，不能用多个会话报告相加替代。会话排行只列自身小计；单会话报告默认含可靠后代，两者口径可能不同。

### 4.5 指定数据来源

| Harness | 默认来源 |
| --- | --- |
| Codex | `CODEX_HOME/sessions`，未设置时为 `~/.codex/sessions` |
| ZCode | 优先 `~/.zcode/cli/db/db.sqlite`；无数据库时读取 `~/.zcode/cli/rollout` 和 `~/.zcode/cli/log` |

读取指定的 Codex JSONL 文件或目录：

```bash
python3 skills/agent-token-audit/scripts/audit.py sessions \
  --harness codex --source /绝对路径/sessions
```

`--source` 可重复指定多个文件或目录。后续 `turns`、`requests`、`report`、`overview` 应使用同一来源，否则所选 ID 可能找不到。

ZCode 可选择数据库或 rollout 入口：

```bash
python3 skills/agent-token-audit/scripts/audit.py report \
  --harness zcode --database /绝对路径/db.sqlite --session SESSION_ID

python3 skills/agent-token-audit/scripts/audit.py report \
  --harness zcode --source /绝对路径/rollout --session SESSION_ID
```

`--database` 仅用于 ZCode，不能与 `--source` 同用。数据库入口会核对相邻 rollout，其可读用量以“补充来源”独立展示：跨源重叠未知、未并入小计，也未按报告范围筛选。不要把补充来源加到任务总量；显式 `--source` 则以 rollout 为计量来源。

## 5. 保存和复用报告

### 5.1 导出文件

保存时必须同时提供 `--export` 和 `--output`：

```bash
python3 skills/agent-token-audit/scripts/audit.py report \
  --harness codex --session SESSION_ID \
  --turn TURN_1 --turn TURN_3 --to "2026-10-08T00:00:00+08:00" \
  --export json --output /tmp/token-audit/task.json
```

JSON 保存范围、数值、状态、来源定位和可用解释，可重算及在浏览器查看。新单会话报告为 v2，整体为 v3；合法旧 v1 也可展示，缺失信息不补造。

从这份保存结果导出其他格式，无需重新读源：

```bash
python3 skills/agent-token-audit/scripts/audit.py show \
  --saved /tmp/token-audit/task.json \
  --export csv --output /tmp/token-audit/task.csv

python3 skills/agent-token-audit/scripts/audit.py show \
  --saved /tmp/token-audit/task.json \
  --export markdown --output /tmp/token-audit/task.md
```

导出目标不能是输入来源或已加载报告，包括它们的符号链接、硬链接别名。其他已有目标文件会被替换，需要保留时请使用新文件名。报告不导出提示词、回复正文或认证信息，但含会话标识和本地来源路径，分享前可检查这些元数据。

### 5.2 展示和按原范围重算

```bash
# 展示保存时的结果，不读当前来源
python3 skills/agent-token-audit/scripts/audit.py show \
  --saved /tmp/token-audit/task.json

# 读取当前来源，保持保存的范围和截止点
python3 skills/agent-token-audit/scripts/audit.py recompute \
  --saved /tmp/token-audit/task.json \
  --export json --output /tmp/token-audit/task-recomputed.json
```

重算保留来源、会话或集合、轮次、区间、截止点、代理策略及整体报告的显示时区，不修改原文件。后补记录可能改变同范围结果；来源缺失时报告缺口，不用旧值补齐。

### 5.3 明确更新范围

保留原轮次，把截止点更新到本次命令开始：

```bash
python3 skills/agent-token-audit/scripts/audit.py recompute \
  --saved /tmp/token-audit/task.json --update \
  --export json --output /tmp/token-audit/task-updated.json
```

替换为新的完整轮次集合，并指定上界：

```bash
python3 skills/agent-token-audit/scripts/audit.py recompute \
  --saved /tmp/token-audit/task.json --update \
  --turn TURN_1 --turn TURN_3 --turn TURN_5 \
  --to "2026-10-08T12:00:00+08:00"
```

`--turn` 完整替换轮次集合，整体 v3 更新的 `--session` 完整替换会话集合，省略则保留旧集合。更新未指定上界时使用命令开始；自然语言“更新到现在”需传本次请求起点。切换 Harness 或单会话对象要新建查询。

CLI 更新时省略 `--from` 或传 `--from ""` 都保留旧下界。移除下界或改为整个会话，需在网页更新表单明确清空对应字段，或新建 `report`。

## 6. 使用本地网页统计

页面分「整体用量 / 会话分析 / 已保存报告」三个标签，切换标签只改变显示，不发起统计或读取来源；查询结果先显示实际范围带、指标卡、日趋势与排行，证据区按需展开。

### 6.1 启动和停止

在模块目录运行：

```bash
python3 skills/agent-token-audit/scripts/web.py
```

复制终端输出的完整访问链接到浏览器，保留 `#token=…`。脚本不自动打开浏览器，只监听 `127.0.0.1`，端口由系统分配，终端同时列出可用来源。

指定来源时使用网页入口自己的参数：

```bash
python3 skills/agent-token-audit/scripts/web.py \
  --codex-source /绝对路径/sessions \
  --zcode-database /绝对路径/db.sqlite
```

`--codex-source` 可重复。ZCode rollout 使用可重复的 `--zcode-source /绝对路径/rollout`，不能与 `--zcode-database` 混用。来源在启动时限定，网页不能提交任意路径。

在启动终端按 `Ctrl+C` 停止。关闭标签页不会停止服务；重启后需要使用新链接，旧链接失效。刷新页面会回到空态。

### 6.2 选择会话和任务

1. 选择 Codex 或 ZCode，点击“浏览会话”，再点击一行选择会话。
2. 需要任务范围时点击“浏览轮次”。点击行切换选择，`Shift+点击` 按列表顺序选择连续区段；提交前核对显示的完整稳定 ID 集合。留空表示整个会话。
3. 设置时间下界、截止点及各自时区，选择代理范围。截止点留空表示本地服务收到本次统计请求的入口时间。
4. 点击“统计”，查看实际范围、截止点、已记录小计和来源缺口。

需要以源中某条请求为截止点时，点击“浏览请求候选”，再点击对应请求行；该动作会按请求自身起点统计。浏览和编辑不会自动统计，启动服务或加载页面也不会扫描来源。

由 Harness 启动网页时，可用 `--context-harness`、`--context-session` 和可选 `--context-request-id` 转交可信身份。经来源验证后显示“本次启动关联会话”，仍需点击使用；它不跟踪实时前台会话。

### 6.3 查询整体用量

在“整体用量”区设置时间范围、显示时区和代理策略，点击“查询整体用量”。默认查询该 Harness 的全部来源会话；也可在会话候选中勾选集合，再点击“用所选会话集合查询整体”。筛选、排序和翻页仅改变候选列表显示。

查询成功后，查询区折叠为“整体用量查询”单行入口；展开即可修改条件并重新查询。查询失败时自动展开，连接或请求失败保留已有结果；结果范围带始终表示该份报告实际采用的范围。

点日期只切换同一报告的当日分布，不读源；点当日会话行会发起新的单会话查询，使用原范围与该日的交集及固定上界。通过“整体总览”或日期按钮返回，保留原整体结果。

### 6.4 加载、重算和导出

选择已保存的 JSON 后，页面在浏览器内显示“保存结果（基准）”，不把文件发送服务，也不读取日志。

- “按原范围重算”才向服务提交保存范围，读取当前来源并生成新结果，原文件不变。
- “编辑新范围并明确更新”预填旧范围，显示增删与时间变化；核对差异后点击“提交更新”。轮次或会话使用完整集合，时间下界主动清空表示移除约束。
- 基准和新结果可分别点击“导出该结果…”，选择 JSON、CSV 或 Markdown，由浏览器决定保存位置。导出复用当前结果，不重新统计；服务页导出需要服务仍在运行。

重算来源必须属于本次启动允许的集合，否则按报告来源重新启动服务。重新选文件替换基准；加载失败会清除旧基准及其导出操作。

## 7. 离线查看 JSON 报告

用浏览器直接打开源码中的[离线查看器](../skills/agent-token-audit/viewer/index.html)，或安装目录下的 `viewer/index.html`，再选择导出的 JSON 文件。要在安装目录外使用，应复制整个 `viewer/` 目录，保留旁边的 JS 和 CSS 资源。

离线查看器只读所选文件，不联网、回源、统计或保存。日志已删除也能查看保存值；重算需使用 CLI 或本地网页。

单会话报告可切换分组、模型、代理、轮次及输入、输出、缓存读取、总量指标，筛选行、展开明细；整体报告展示日趋势和排行。旧报告缺失维度或解释会标明未保存，未知不画零。

新报告的“定位”操作可从图表行、轮次时间线或单条记录找到对应明细。`Esc` 或“返回全部明细”恢复；定位和筛选只改变展示，不改变统计范围、总量、缓存率分母，也不会打开源文件。

## 8. 理解结果

先核对 Harness、会话或会话集合、轮次、时间区间、代理策略和截止点，再读取表格。默认六列为分组、输入、输出、缓存读取、命中率、总量。

| 指标 | 含义 |
| --- | --- |
| 输入 | 源计量的完整输入，已包含缓存读取 |
| 输出 | 源报告的输出；已经包含的推理输出不再相加 |
| 缓存读取 | 输入中来自缓存的部分，不能再次加到输入或总量 |
| 命中率 | 输入和缓存读取均已知的记录子集：缓存读取之和 ÷ 输入之和 |
| 总量 | 字段和语义支持时为输入 + 输出；缺失或冲突会保留状态 |

分组互斥：主代理常规调用、可靠归属的子代理常规调用、有证据识别的内部辅助（如压缩、会话辅助），以及分类或归属不明的未分类记录。“已记录小计”聚合范围内可靠可计量记录，不保证全部调用都有记录。

缓存率按成对已知字段加权，不能平均每次调用的百分比。例如两次输入为 100、300，缓存为 90、0，合计命中率为 `90 / 400 = 22.5%`。其中一个缓存字段缺失时，只报告已知子集的命中率及覆盖，不能当作整体命中率。

| 结果状态 | 如何理解 |
| --- | --- |
| `partial` | 有可靠的部分结果，仍存在调用覆盖或字段缺口 |
| `count_only` | 只有可信调用计数，没有可计量 usage |
| `tool_only` | 只有独立工具累计报告，不能拆成输入、输出或加到直接小计 |
| `unstatisticable` | 当前没有可用计量证据，不等于零用量 |
| `confirmed_zero` | 有足够证据确认所选范围为零用量；空列表本身不足以证明零 |

CLI 退出码：`0` 表示列举、展示成功或确认零用量；`2` 表示有效的部分、仅计数或仅工具结果；`3` 表示不可统计；`4` 表示参数或读取错误。自动化调用应分别处理，不能把所有非零退出都当作没有结果。

调用明细保存来源定位、粒度、时间和分类依据，可用来核对异常消耗。Codex 逐调用记录可能只有 usage 时间点，没有调用起点；ZCode 数据库一行通常是逻辑请求结果，不能当作包含全部重试的独立模型调用。累计区间可能跨多轮，不能摊到每轮。

时间线中的轮次墙钟、原生轮次耗时、同粒度记录耗时之和各有口径；并行调用会重叠，耗时之和不等于墙钟。未知、冲突、截止点前未确认结束都有相应说明。内部来源的五类支持状态表示覆盖事实，不是额外 token 分组。

## 9. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到会话或轮次 | 核对 Harness、来源参数和稳定 ID；自定义来源要在列举和统计时保持一致 |
| 时间参数报错 | 补齐 `Z` 或 `+08:00` 等时区，保证 `from < to`，三个截止点参数只选一个 |
| IANA 时区名不可用 | 改用 `--tz "+08:00"` 等明确偏移；有夏令时的地区应选符合查询目标的时区 |
| 提示不支持报告格式版本 | 使用当前版本工具；只支持 v1 的旧工具不能读取 v2/v3 |
| 网页显示来源越界 | 按保存报告的来源配置重启服务，不在网页里任意替换路径 |
| 网页连接失败或旧链接失效 | 核对终端服务仍在运行；重启后使用终端新链接 |
| Harness 拒绝执行命令 | 按 Harness 的正常权限流程授权；不要换写法或委派代理绕过同一拒绝 |

更详细的计量合同、已核查来源版本和验收限制见[实现文档](../specs/2026-10-07-agent-token-audit-implementation.md)，源码导航见[整体架构](./architecture.md)。
