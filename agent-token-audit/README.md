# Harness Token 用量统计

按需读取 Codex、ZCode 的现有本地记录，以任务或会话查看输入、输出、缓存读取及命中率。默认展示表格，只有明确导出才写报告；不估算缺口，不建设采集服务。

完整操作步骤见[使用指南](./docs/usage.md)，包含安装、自然语言调用、CLI、本地网页、离线查看器、报告复用和常见问题。

## 1. 安装与调用

需要 Python 3.9 或更新版本，仅使用标准库。安装时将完整 Skill 复制到所选 Harness 的目录，目标已有不同内容会拒绝覆盖：

```bash
python3 agent-token-audit/install_skill.py --harness codex
python3 agent-token-audit/install_skill.py --harness zcode
```

也可用 `--target /绝对路径/agent-token-audit` 安装到自选目录。重新加载 Harness 的 Skill 列表后，使用“统计当前会话的 token 用量”“统计这个任务，排除中间无关轮次”“按原范围重算上次报告”等请求。会话或任务边界有歧义时需要选择候选。

独立命令行入口为 `skills/agent-token-audit/scripts/audit.py`，安装后的同一相对位置也可运行。以模块目录为当前目录：

```bash
python3 skills/agent-token-audit/scripts/audit.py sessions --harness codex
python3 skills/agent-token-audit/scripts/audit.py turns --harness codex --session SESSION_ID
python3 skills/agent-token-audit/scripts/audit.py report --harness codex --session SESSION_ID --turn TURN_1 --turn TURN_3 --to 2026-09-13T20:00:00+08:00
```

`--current` 只使用 Harness 提供的会话环境标识；独立 Shell 中不存在该标识时，请从候选中选择。直接 CLI 默认截止于命令开始，自然语言入口使用请求 ID 或可信请求时间固定截止点。兼容空参数合同：`report --from ""` 的 JSON `scope.from` 为 `""`；保存范围更新 `--from ""` 或省略 `--from` 均沿用旧下界。全部参数及操作见 `--help`。

`--format json|csv|markdown` 改变标准输出格式；`--export json --output /目标/报告.json` 才写文件。单会话 JSON 报告为 `format_version=2`，同一结果保存模型/代理/轮次三个独立视图、定位证据与内部来源支持状态；整体查询 overview 生成 v3（日趋势、模型/会话排行与下钻），合法 v1/v2/v3 保存报告均可读。`show --saved` 展示旧结果，`recompute --saved` 使用旧范围读取当前来源生成新 v2/v3（与原单会话/整体范围对应），`recompute --saved --update` 显式更新范围。`--main-only` 排除另列的内部辅助；`--detail model|agent|turn` 是保存视图的投影，不再加入总量。

已保存报告可用随包附带的离线查看器查看：用浏览器直接打开安装目录（或源码目录）`viewer/index.html`，选择导出的 JSON 即可。页面完全离线，只读取所选文件，可切换分组/模型/代理/轮次维度与四项指标查看条形图、筛选行并展开明细；数值与 CLI 一致，未知不画为零。旧版本工具（仅支持 v1）无法读取 v2 报告。

也可以显式启动本地网页统计入口，在浏览器里浏览会话、稳定轮次并发起整个会话统计：

```bash
python3 skills/agent-token-audit/scripts/web.py            # 默认使用两端本地来源
python3 skills/agent-token-audit/scripts/web.py --codex-source <目录或文件> --zcode-database <数据库>
```

服务只监听本机回环地址，端口由系统分配；终端会显示带一次性凭据的访问链接、可用来源和停止方式（前台 Ctrl+C）。页面从空态起步，仅在明确点击浏览或统计时读取来源；“截至现在”的截止点在服务收到请求的入口固定，显式历史上界以带时区输入提交，结果与 CLI 同值。来源根目录、文件及 ZCode 相邻 log/rollout、WAL/SHM 都限制在启动配置内，越界符号链接被拒绝；关闭标签页不影响服务，重启后旧链接失效。

网页支持全部任务范围：轮次列表中点击选择单轮、Shift+点击按显示顺序展开连续区段（提交前显示完整稳定 ID 集合，留空即整个会话），带时区时间区间与代理策略可组合使用；浏览请求候选后可选用某请求自身时间作为截止点。启动链可用 `--context-harness/--context-session/--context-request-id` 转交可信会话与本次统计请求，页面显示“本次启动关联会话”，选择时同时恢复 Harness、会话与控件状态并清除切换前待提交选择，身份经来源唯一匹配验证，转交请求只在你点击对应动作后以该请求自身起点执行。报告可展开调用明细（分组、模型、轮次、指标状态与来源定位等白名单元数据）。

网页也可复用已保存报告：选择 JSON 只在浏览器内展示为基准（不发送服务、不读来源）；点击“按原范围重算”按保存的会话、轮次/时间、代理策略与截止点读取当前来源生成新 v2/v3（与原单会话/整体范围对应；不写回原文件，保存报告声明的来源必须属于本次启动的允许集合，越界明确拒绝）；“编辑新范围并明确更新”先显示原范围与新范围差异（新增/移除轮次、时间与截止点变化），提交完整集合后才读取。保存下界以完整带时区文本显示，未改动保留秒及小数秒，主动清空移除约束；重新选择文件使此前基准的重算/更新响应失效，加载失败不恢复旧结果或导出。基准与新结果同屏可对照、可分别导出：明确选择 JSON/CSV/Markdown 后由本地服务按同一结果生成内容，浏览器决定保存位置；旧 v1 再导出仍为 v1，大整数全程精确。

退出码：`0` 为展示/列举成功或确认零用量，`2` 为有效的部分结果、仅计数或仅工具报告，`3` 为不可统计，`4` 为参数/读取错误。部分报告仍应展示。

## 2. 数据来源和计量边界

- Codex：优先读取 `CODEX_HOME/sessions`（默认 `~/.codex/sessions`）的逐调用 `token_usage_record`；同源累计通知不重复加总。旧格式在可对应唯一回复时使用 `last_token_usage`，其余先对完整累计序列差分；混合记录择一计量，跨未选轮次或缺少基线时说明缺口。
- ZCode：默认优先读取现有 `~/.zcode/cli/db/db.sqlite` 中的原始 `model_usage.raw_usage_json`；活跃 WAL 且已有共享内存文件时，用 SQLite 只读事务备份取得一致快照；其他情况复制稳定 DB/WAL 后读取，临时文件用后删除，源数据库不打开为可写。稳定轮次候选合并同会话的 `turn_usage`、`model_usage.turn_id` 与明确轮次事件：只有 usage 时仍可选择和统计，但状态、轮次起止时间保持未知；后续轮次账本或结束事件只补充同一候选。请求以 `session_input.kind=sendText` 为真实输入来源；仅 `promoted_message_id` 能关联其提升后的 message，截止点使用入队接收时间。`synthetic=true` 的 message 会排除且 `--request-id` 明确拒绝；缺少分类或关联字段的旧记录仍单列为未知，不凭正文、时间或 ID 前缀合并。父子轮次关系结合相邻日志目录。没有数据库时读取 rollout 和结构化日志。
- `--source` 指定 JSONL 文件/目录，可重复；`--database` 指定 ZCode 现有数据库。两种 ZCode 计量来源不混合相加：经真实来源核查，rollout 的 requestId 与数据库 logical_request_id 不在同一身份空间、没有调用级桥接。`--database` 会核对同级 rollout 模型日志，其可读用量以“补充来源”独立展示并标注跨源重叠未知，不并入小计；显式 `--source` 仍表示以 rollout 为计量来源。

实现核查覆盖 Codex 0.153–0.159 与 ZCode 0.16.3–0.16.9 的代表性记录。ZCode 已核对 BigModel Coding Plan/Start Plan 及其 account 计费变体的字段语义（同一遥测写入器，全量真实行算术校验通过）；其他未验证供应商字段保留原值及未知状态。数据库数值列的默认零不替代缺失的 `raw_usage_json`；数据库仅保留逻辑请求最终结果，重试调用总数与失败用量如实标注缺口。

缓存读取已包含于输入；缓存写入的源报告零保留但标为语义未确认，推理输出已包含于输出时不再相加。缓存率基于成对已知字段加权；部分字段缺失时只报告已知子集，不推断完整覆盖率。数据库的逻辑请求行数不等于包含全部重试的模型调用数。

子代理按明确关系归属，不按文件名、时间邻近或模型角色判断。Codex 的 `compacted` 标记携带 `compaction_response_id`，与逐调用记录明确对应时该调用计入内部辅助，无可关联 usage 时说明缺口。ZCode 的 `workflow_child` 会话按 `task_type` 证据归为后台后代（不再当分叉），其调用归后代常规组；`session_title` 等会话辅助不摊入任务轮次。分叉有原始调用身份及祖先来源时排除继承副本：真实分叉（56 个样例）只复制对话历史、不复制逐调用记录，新调用正常计入。时间过滤以完整调用的结束/usage 时间为准，不按比例分割单次调用。

## 3. 开发与验收

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s agent-token-audit/tests -v
```

测试通过外部 CLI 验证统计、范围、去重、状态和文件副作用，构造输入及输出仅写工作区外临时目录。真实数据复算、两种 Harness 的自然语言交互与离线网页操作是独立验收要求，不能由自动测试数量替代。

现行合同与验收统一见[实现文档](./specs/2026-10-07-agent-token-audit-implementation.md)，源码导航见[整体架构](./docs/architecture.md)，可编辑架构图见[Kimi PPTD](./docs/architecture-diagram/architecture.pptd)。

| 阶段 | 范围 | 状态 |
| --- | --- | --- |
| 一期 | 初步构建两端只读适配、任务范围、计量、导出、报告复用和安装能力 | 基础能力已形成；收尾和接受差异由实现文档承接 |
| 二期 | 整体完善定位、内部消耗、离线可视化、本地网页、整体分析与消耗解释 | 功能代码已形成；部分真实验收仍待补齐 |

定位、内部消耗及离线展示按用户接受边界于2026-10-02闭合，本地网页于2026-10-04闭合。整体分析仍待离线文件加载、网页实际下载、两端真实自然语言整体查询及修复后安装补验；解释已完成记录/时间线/联动/下钻/安装和Codex自然语言补验，ZCode真实自然语言仍报 Model creation failed，原因未确认。局部验收不自动追认其他缺口，二期不能称整体验收通过。

[实现文档第10节](./specs/2026-10-07-agent-token-audit-implementation.md#10-直接验收接受差异与当前状态)保留原直接验收粒度、stat4失败处置、两端恢复/分叉接受差异、重验条件和旧ZCode桌面SQL证据。当前整理只改变组织和阶段称谓，不更新这些产品结论。计划状态见[索引](./specs/plans/README.md)。
