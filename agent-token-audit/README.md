# Harness Token 用量统计

按需读取 Codex、ZCode 的现有本地记录，以任务或会话查看输入、输出、缓存读取及命中率。默认展示表格，只有明确导出才写报告；不估算缺口，不建设采集服务。

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

`--current` 只使用 Harness 提供的会话环境标识；独立 Shell 中不存在该标识时，请从候选中选择。直接 CLI 默认截止于命令开始，自然语言入口使用请求 ID 或可信请求时间固定截止点。全部参数及操作见 `--help`。

`--format json|csv|markdown` 改变标准输出格式；`--export json --output /目标/报告.json` 才写文件。JSON 报告为 `format_version=2`，同一结果保存模型/代理/轮次三个独立视图、定位证据与内部来源支持状态；合法 v1 旧报告仍可读。`show --saved` 展示旧结果，`recompute --saved` 使用旧范围读取当前来源生成新 v2，`recompute --saved --update` 显式更新范围。`--main-only` 排除另列的内部辅助；`--detail model|agent|turn` 是保存视图的投影，不再加入总量。

已保存报告可用随包附带的离线查看器查看：用浏览器直接打开安装目录（或源码目录）`viewer/index.html`，选择导出的 JSON 即可。页面完全离线，只读取所选文件，可切换分组/模型/代理/轮次维度与四项指标查看条形图、筛选行并展开明细；数值与 CLI 一致，未知不画为零。旧版本工具（仅支持 v1）无法读取 v2 报告。

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

权威行为见[需求](./specs/2026-09-13-agent-token-audit-requirements.md)和[设计](./specs/2026-09-13-agent-token-audit-design.md)。后续分期已于 2026-10-01 调整：[二期](./specs/2026-09-27-agent-token-audit-phase2-requirements.md)收尾并完善两端定位、内部消耗及只读报告可视化；[三期](./specs/2026-09-27-agent-token-audit-phase3-requirements.md)增强网页；[四期](./specs/2026-09-27-agent-token-audit-phase4-requirements.md)接入 OpenCode、Claude Code 并四端对齐；[五期](./specs/2026-10-01-agent-token-audit-phase5-requirements.md)统一适配器并输出规范与接入示例；[长期需求](./specs/2026-10-01-agent-token-audit-long-term-requirements.md)保留可选能力判断。分期确认不代表这些后续能力已实现。

验收状态（二期 2026-10-02 收尾）：一期 A1–A18、二期五项收尾及 P2-A1–P2-A10 原验收缺口已按用户接受的[验收边界与差异](specs/2026-09-27-agent-token-audit-phase2-requirements.md#10-验收边界与已批准差异)落定；新增规则已撤回，SKILL 恢复已验收基线，二期按批准边界闭合；P2-05 原 ZCode 对象的原材料已补齐，旧证据与修复后回归分开。Codex Desktop 0.159.0 与 Harness CLI 0.147.0 入口身份分别验证，结论限定已核查环境。保留限制：ZCode 桌面 3.14.4 的 `--current` 身份变量不可用，自然语言定位使用源内证据链；恢复验收覆盖 Codex CLI 与 ZCode 子代理路径；ZCode 未取得真实分叉样例，Codex 真实分叉样例不携带 usage 副本，两项差异已批准并保留来源变化后的重验条件；stat4 候选流程失败记录保留，新干净样例经用户本人选择验收，不宣称历史失败已修复；查看器缺浏览器能力分支仍缺真实缺失环境，仅经代码路径审查。
