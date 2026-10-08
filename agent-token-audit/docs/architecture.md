# Agent Token Audit 整体架构

本文面向维护者，说明当前代码怎样从本地记录生成可解释报告，以及各入口如何复用它。分析基线为 `zn_token` 原提交 `d62f820`；本次仅更改文案，执行逻辑保持。产品范围、指标口径、接受差异和验收状态统一由[实现文档](../specs/2026-10-07-agent-token-audit-implementation.md)维护。

## 1. 30 秒总览：一份计量结果，多个入口

系统有两条路径：明确统计时读取来源并生成报告；展示保存报告时只校验、渲染，不经过来源。自然语言 Skill、CLI、本地 HTTP 都调用同一 Python 操作层；离线查看器只消费 JSON。图源见[Kimi 可编辑架构图](./architecture-diagram/architecture.pptd)。

![Agent Token Audit 分层与内部流程图](./architecture-diagram/architecture.png)

这是逻辑视图：`operations` 会调用 `core`，并没有独立的报告消息总线；浏览器也没有 Python 模块桥接，服务页通过 HTTP，离线页通过 FileReader。图中保存节点表示用户明确导出的文件，系统没有永久报告库。

## 2. 目录、模块职责与依赖

```text
agent-token-audit/
├── install_skill.py                  完整目录安装与覆盖保护
├── specs/                           唯一实现合同与计划索引
├── docs/                            本文与 Kimi 图源
├── tests/                           外部 CLI、来源守卫、HTTP 行为
└── skills/agent-token-audit/
    ├── SKILL.md                     自然语言范围和调用规则
    ├── scripts/audit.py、web.py      独立运行入口
    ├── scripts/token_audit/          Python 操作、读取、归属、计量、输出
    └── viewer/                      离线与服务页、共用校验/渲染、无损 JSON
```

| 组件 | 源码及关键符号 | 输入→输出与职责 |
| --- | --- | --- |
| 自然语言入口 | [SKILL.md](../skills/agent-token-audit/SKILL.md) | 用户意图/可信上下文→明确范围和脚本调用；不心算、不替用户选歧义候选 |
| CLI | [cli.py](../skills/agent-token-audit/scripts/token_audit/cli.py)，`main/current_identities` | argparse→Query→候选JSON或报告文本、退出码；命令入口时间先固定 |
| 共同操作层 | [operations.py](../skills/agent-token-audit/scripts/token_audit/operations.py)，`run/read_input/run_overview` | Query→操作结果；来源描述、定位、保存范围三态合并、短路/分派 |
| Codex Adapter | [codex.py](../skills/agent-token-audit/scripts/token_audit/codex.py)，`discover/read` | JSONL→会话、请求、逐调用/唯一回复/累计区间和缺口；直接与累计择一 |
| ZCode Adapter | [zcode.py](../skills/agent-token-audit/scripts/token_audit/zcode.py)，`read/read_database` | rollout/log或只读DB快照→逻辑请求/attempt/轮次/请求证据；补充来源独立 |
| 关系绑定 | [relations.py](../skills/agent-token-audit/scripts/token_audit/relations.py)，`bind` | 来源data→owner_session/owner_turn、后代、继承排除、独立工具报告 |
| 计量与解释 | [core.py](../skills/agent-token-audit/scripts/token_audit/core.py)，`report/overview/aggregate/dimension_view` | 归属记录→范围selected→互斥组、独立视图、日桶、排行和解释；report/overview 不读源（读文件辅助函数 source_lines 也位于 core） |
| 报告边界与输出 | [formats.py](../skills/agent-token-audit/scripts/token_audit/formats.py)，`validate_report/render/export` | 不可信保存对象→校验投影；同一结果→JSON/CSV/Markdown或受保护文件写入 |
| HTTP 边界 | [webapp.py](../skills/agent-token-audit/scripts/token_audit/webapp.py)，`SourceGuard/Handler/serve` | 启动配置/HTTP→受限Query或纯导出；回环、凭据、Host/Origin及静态白名单 |
| 页面操作状态 | [web.js](../skills/agent-token-audit/viewer/web.js)，`call/loadSavedFile/runReport/runOverviewQuery` | 用户动作→HTTP/本地FileReader→对应结果区；单飞、文件及选择世代防陈旧响应 |
| 共用浏览器展示 | [shared.js](../skills/agent-token-audit/viewer/shared.js)，`validateReport/renderReport/renderOverviewReport` | 已保存报告→DOM/SVG、筛选、时间线/记录定位；不重建计量、日界或关系 |
| 安装 | [install_skill.py](../install_skill.py)，`main` | 完整Skill源→目标目录；相同内容幂等，不同内容/符号链接拒绝 |

Python产品只使用3.9+标准库：`argparse`解析，`json/csv`序列化，`datetime/zoneinfo`统一时间，`sqlite3`快照，`http.server`本地服务，`tempfile/pathlib/os/shutil`文件边界。模块无pip/npm构建清单。浏览器辅助依赖是随包[lossless-json](../skills/agent-token-audit/viewer/lossless-json.LICENSE.md)，为精确整数解析/序列化；仓库未提供该 UMD 的版本清单或 lockfile，精确库版本未经确认；许可证随包保留。SVG/DOM/FileReader/fetch均为浏览器能力。Kimi是文档图源工具，不是产品运行依赖。

## 3. 数据形态与权威边界

| 阶段 | 真实数据形态 | 下一消费者及所有权 |
| --- | --- | --- |
| 入口 | `Query(operation, started, harness, descriptor, session/sessions, turns, since/to, saved, update, guard…)` | `operations.run`；HTTP的null转换CLEAR，CLI的空from语义在入口处理 |
| 读取 | `data`含sessions、records、issues、source_files；可含requests、events、alternate_sources | Adapter解释源字段；`metrics`为value/state/reason/field；临时快照在读取作用域释放 |
| 归属 | 原始session/turn并存owner_session/owner_turn；inherited、tool_reports独立 | `relations.bind`；只能用明确证据建立关系 |
| 选集 | `family`闭包与`selected`，未归属/排除另列 | `core.report/overview`；固定scope作用于可信时间及稳定身份 |
| 报告 | v2单会话或v3整体，scope、summary、rows、views、records及可选explanation；v3另有days/rankings/session_index/unbucketed | 内核维护计量，格式层维护加载边界；行键引用同一records |
| 消费 | 终端/文件文本或HTTP报告；浏览器无损对象→DOM/SVG | 展示只消费保存值。JSON是用户可选持久化边界，其他状态只在当前进程/页面 |

`aggregate`只做同一选集上的字段小计与缓存配对子集；`dimension_view`只按一个维度分组。报告汇总、排行、解释成员必须回到这份集合，不能把不同视图累加。源字段语义、请求身份和生命周期不是同一证据，分别在Adapter、操作层、解释中保留。

## 4. 主要流程与实现全景

以下均已接线。`SOURCE/CALL-CHAIN`指当前静态代码；`TEST`只指实际外部合同覆盖，不据此宣称真实Harness或浏览器补验完成。每项能力的产品合同落点仍是实现文档，本节是唯一源码流程导航。

### 4.1 候选发现与选择

真实入口为CLI `sessions/turns/requests`，或web.js对应浏览按钮。`cli.main → run → default_descriptor/read_input → Adapter → bind → listing_sessions/turns/requests`，最终打印候选或由HTTP返回给`renderSessions/renderTurns/renderRequests`。输入是来源描述及必要会话，输出是稳定身份、已有时间/关系、证据计数及issues；标题/生命周期缺失不能合成。

`resolve_current`只验证传入/环境身份属于源；`resolve_request_cutoff`要求唯一可用请求。无会话、冲突、不属于所选会话的轮次拒绝操作；来源损坏可保留候选和缺口，不自动新建报告。列表筛选/排序/分页留在浏览器当前候选副本，用户下一次点击才读源。测试证据：`test_discovery_uses_metadata_and_output_does_not_copy_content`、`test_zcode_model_usage_turn_candidates_merge_and_fixed_cutoff`、`test_current_identity_and_appended_request_time`，见[CLI测试](../tests/test_cli.py)。

### 4.2 单会话与任务统计

`audit.py → cli.main → run → read_input → codex.read/zcode.read_database或read → bind → core.report → formats.render`。正常链把JSONL/SQL行转metrics cell，先去重/绑定，再校验会话及轮次、增长family、按owner及时间选selected；调用`aggregate/build_views`后生成v2，`explain_records/build_turn_explanations/build_activity_explanation`复用选集，不加新计量。

累计fallback发生在Codex读取阶段完整源序列，主代理筛选及区间全集判定在report。无法拆的区间、缺时间或不能归属分别诊断/排除/未归属，工具total另走通道；源不证明完整就有效partial，空记录不自动零。仅CPU/内存对象变更，除读取快照无持久副作用。TEST：CLI的`test_cumulative_filter_after_difference_and_boundary_gaps`、`test_codex_descendants_have_origin_turn_and_unique_calls`、`test_default_group_totals_and_independent_detail`覆盖集合/归属/视图。

### 4.3 整体分析与下钻

`cli.main(overview) → run → run_overview → core.overview`。默认本次全部来源会话，显式重复集合去重，保存scope集合；family闭包和selected一次生成，`day_bounds`建立本地日与原范围交集，`dimension_view`生成日分布和排行，输出v3。跨日累计进入unbucketed，缺时间只诊断；源中缺保存成员保scope并降级，新显式错ID报错。

`web.js.runOverviewQuery → call → Handler → run`消费同一结果；`onOverviewDayClick/refreshOverviewDrill`只读取保存days。`enterSessionFromDrill → applyBoundControls → runReport`是明确新查询，生成独立v2；使用day.from/to，不能前端另算日界。返回保留state.overview。TEST：`test_default_all_sessions_dedup_rankings_and_big_integer`、`test_day_intersection_unbucketed_and_timezone`、`test_day_row_ranges_cover_dst_transitions_and_intersections`，HTTP的`test_overview_duplicate_sessions_normalize_and_day_ranges_saved`；真实验收缺口见实现文档。

### 4.4 保存报告展示

CLI `show → read_decoded → validate_report → run(show早返回) → render`；版本分支校验v1/v2/v3，整个链没有`read_input`。离线[index.html](../skills/agent-token-audit/viewer/index.html)的`loadFile → FileReader.onload → LosslessJSON.parse → validateReport → renderReport/renderOverviewReport`；服务页`loadSavedFile`也本地加载，带baselineVersion约束异步完成。

保存JSON→经过验证的白名单对象→文本或DOM；未知旧维度明确不可用，缺解释仅有限定位。坏结构/引用/隐私字段拒绝并清失败展示，不能自动回源补字段。TEST：`test_export_show_recompute_preserves_scope_and_reports_missing_source`、`test_v1_report_reads_without_new_dimensions_and_recompute_makes_v2`、`test_large_integers_survive_roundtrip_exactly`；真实file://不是这些测试的覆盖。

### 4.5 原范围重算与明确更新

CLI `recompute`或网页重算/更新按钮→保存报告校验→`operations.run`合并scope→保存input或明确来源→`read_input/bind → report/overview`。原范围所有约束保持，update才替换集合/边界；HTTP缺失=保留、null=CLEAR、值=替换，CLI保存空from先映缺失。显式整体集合不支持null清空。

旧JSON是范围 authority，不是读权限，也不提供新数值fallback。允许来源已缺，构造缺失会话/诊断再计算未知/可靠部分；越界guard拒绝，不换默认源。新对象生成不写旧文件。网页基准和新结果分区；选择新文件立刻废弃旧复算/导出响应。TEST：`test_empty_from_preserves_new_report_and_saved_scope_cli_contracts`、HTTP的`test_update_keeps_fractional_lower_bound_and_combined_turns_until_cleared`、`test_recompute_rejects_sibling_database_before_reading`。

### 4.6 显式导出

CLI `main → formats.export → render → 临时文件写入 → os.replace`；目标resolve与source_files/input/已加载报告比较，`samefile`防硬链接/符号别名，finally清临时文件。JSON精确值和版本保留，CSV/Markdown从同一对象展开，普通format仅标准输出。

服务页`exportReport → prompt → call(export) → Handler._run_action → validate_report/render → content → Blob/anchor.click/revokeObjectURL`，不走run读源、不写服务器报告。下载属于真实浏览器所有权边界。TEST：`test_export_formats_and_source_collisions`、`test_v3_saved_show_recompute_update_and_source_protection`；实际下载历史结论按能力与版本见实现文档，不能从HTTP content返回推断成功下载。

### 4.7 本地网页操作与记录联动

`web.py.main → default_descriptor → serve/WebApp/guard_for → ThreadingHTTPServer → Handler.do_POST → _run_action → operations.run`。启动只配置来源、凭据，GET只静态/capabilities；POST入口先固定entry，再drain、传输检查、参数/报告校验。SourceGuard在Adapter发现/读取前限真实路径；DB sidecar精确到声明DB及wal/shm，相邻log/rollout范围显式建立。

`web.js.call`捕获seq和baselineVersion，候选再捕获selectionVersion；fetch返回、无损解析后、异常路径均判失效，finally解单飞。`showFreshResult/showOverviewResult`按自身scope渲染；`shared.js.buildRecordsDetail/buildTimelineCard`从保存键定位，render回调闭包绑定每区obj。选维度清定位，切指标保留，过滤只隐藏行；坏文件/结果失效清旧绑定。HTTP测试覆盖guard、参数转交、CLEAR、互斥及v3，浏览器状态/联动的实际证据独立见实现文档。服务关闭/重启不自动重发，页面已存报告仍可查看。

### 4.8 完整Skill安装

`install_skill.py.main`枚举自有Skill目录（跳pycache），拒来源/目标符号链接，验证SKILL.md；目标已有不同内容拒绝，相同内容返回成功。新目标在父目录TemporaryDirectory中暂存整树，写完整再`shutil.move`，退出清暂存；安装目标才是持久副作用。没有自动重载Harness。TEST：`test_installation_standalone_and_existing_target_protected`通过工作区外目标执行安装副本和拒覆盖。图源/架构文档不被安装进Skill运行目录。

## 5. 横切约束、扩展位置与阅读路线

计量只有Python内核一处；Python/浏览器两份报告校验分别保护跨环境输入，不能当重复计量删掉。Adapter决定源字段与identity作用域，relations决定明确归属，operations决定范围复用，core决定selected与指标，formats/浏览器消费结果；新增同源字段需先核查证据，不靠名字或算术关系启用。

无永久任务/报告DB、定时读取、前端聚合或跨端identity合并。来源JSONL有限快照、ZCode两种快照分支及临时清理由Adapter负责；HTTP只增加读权限，不取代源合同。并发在请求线程，页面单飞；结果一致性来自固定scope和归属版本，不来自缓存。源后补记录可改变重算结果。

5分钟路线：`cli.main → operations.run → read_input → relations.bind → core.report/overview → formats`。维护者查时间/日界读`timestamp/day_bounds`，查未知与缓存读`normalize/aggregate`，查解释读`build_record_explanation/build_turn_explanations/build_overview_turns`，查报告安全读`validate_report/check_explanation`，查页面归属读`call/loadSavedFile`，查联动读`buildRecordsDetail/renderReport/renderOverviewReport`。测试入口见[test_cli.py](../tests/test_cli.py)、[test_webapp.py](../tests/test_webapp.py)。

本次源码、调用链和文档机械核查不补做产品真实验收。初学者和维护者视角分别审阅，均由同一执行者完成，独立性有限；未把静态接线、现有测试或图源合法性写成全部运行环境已验证。

Kimi项目按“接入与编排层 → 计量分析层 → 输出与呈现层”组织源码职责，共同操作层归入接入与编排，外部数据源单列为计量分析的只读依赖，三层上下排列，每层用独立节点和箭头展开入口汇合、适配与归属、计量、输出及浏览器消费；保存报告从输出层左侧直接进入加载与呈现，绕过来源和计量内核。箭头表示主要处理关系，不展开全部函数调用。项目使用可编辑文本、矩形和连接线，自包含页面，无外部图片/字体资源。已核对YAML、字段、页面边界、主题与引用，并通过本机Canvas确定性导出为[可直接阅读的PNG](./architecture-diagram/architecture.png)，完成全图视觉检查；图源与图片均使用Arial/冬青黑体。当前环境无`kimi-slides` CLI，未进行官方渲染引擎或PPTX导出验证。
