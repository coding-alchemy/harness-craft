# 工作包与交付辅助入口

这些入口消费当前来源和现有核验事实，不翻译、不裁决语义，也不授予自动完成资格。先按对应源家族完成原快照准入、独立对账及主 Agent 的来源/范围确认。运行产物放在项目既有证据位置或 Git 工作区外；旧源包、历史任务、复核记录与有效索引保留。

## 项目上下文

`--project-context <JSON>` 的 `project_root` 是相对引用基点；`source_record` 引用现有 `verify_delivery.py` 来源记录。准备阶段不要求尚未生成的译文、PDF 或交付级映射。`source_scope` 为 `"all"` 或明确的包顺序整数数组，不能从已收到包反推范围。`source_review` 必须有同一 `scope`、主 Agent 实际来源/范围裁决的 `basis` 及当前来源 `binding`，后者使用现有来源核对结果中的 `parsed_sha256`、`source_version`、`snapshots`；旧 PASS 或手填新摘要不代替实际确认。

显式声明 `instructions`、`rules`、`glossary`、`output_contract`、`examples`。引用可为文本路径，或 `{ "path": "rules.md", "start_line": 2, "end_line": 8, "packages": ["wp_002.md"] }`，行号闭区间；不指定选区则整份适用。术语没有配置时明确 `[]`，已选择项目词表/共享子集时保持原优先级。样例对象另含 `differences`，说明同构部分及不可仿照内容。`return_contract` 指定返回要求。`rule_conflicts` 非空时拒绝分派。

`skill_dir` 与可选 `python` 使用当前实际安装目录及解释器，保留 venv 入口。`check_args` 为现有核验参数数组，支持实际强 token、额外公式、来源适配和数字口径；相对文件参数从 `project_root` 解析。多来源适配仍重复 `--source-adaptation`，不创建另一份来源资格。具体转换可用 `structural_conversions` 的 `{ "package": "wp_002.md", "source": "可定位源文字", "target": "当前译文表示", "basis": "已确认的依据" }`；它不豁免硬检查，不能把整类结构设成免检。

PDF 确认数学按 [PDF 源工作流](pdf_source.md) 的 confirmed-tex-v1 合同执行。
拆包、任务、逐包复核、恢复和合并均显式使用同一 `--project-context`；源合同
元数据不属于包正文。实际片段核验从已准入全源的人工事实裁取，不以包中数学
产生确认集合。check_policy 绑定该包数学、所属和具体转换；全源身份与来源
人工复核仍在准入层消费：新PDF source_review.binding 另有 pdf_source，
内容复用现有 PDF 来源身份投影（PDF / 清单 / 双快照 / 块映射 / 素材）；
必须实际重核当前输入后登记，不用全篇版本变化使所有无关包失效。

## 强 token 候选

```bash
python <Skill>/scripts/extract_token_candidates.py --source <当前源.md> --preset ptx --output <候选.json>
```

`ptx` / `isa` 仅在明确代码围栏中提取有限指令、点修饰符和百分号寄存器，输出实际位置及支持边界。主 Agent 逐项采纳、拒绝或待定，保留候选与实际清单的对应依据；只有已采纳项进入 UTF-8 token 文件。文件每个非空行一个 token，裁首尾空白，`#` 是数据。核验入口显式使用可重复的 `--strong-token-file <文件>` 或逐项 `--strong-token`，不会自动启用候选或术语库。

## 自足任务与当前漂移

```bash
python <Skill>/scripts/build_work_package_tasks.py --source <源.md> --strategy h2 --source-packages <wps> --project-context <context.json> --package wp_002.md --output <任务.json>
```

JSON 的 `task` 为完整任务正文，含实际元数据、选中上下文、唯一源/目标、脚本计数、当前命令及四类返回；图片身份从独立当前源取得，资源由主 Agent 分派前准备。只准翻译 Agent 写其 `target`。未列出的结构不视为零；`[TABLE]` 重建真实 Markdown 表格，不保留残留标记。复杂表格的解析源格位与译文逻辑列位须分别回源核对，不能仅凭机器 PASS 决定分组。

补译或规则变化时指定 `--previous-task <旧任务.json>`，历史 JSON 和其只读旧源包必须保留实际正文、引用选区内容和转换；仅有摘要不足以重建前后变化。生成器给出精确差异与重验事项，不自动迁移或重派译文。旧回报不授予当前资格。

## 待复核、逐包登记与实际消费

```bash
python <Skill>/scripts/build_review_evidence.py prepare --source <源.md> --strategy h2 --source-packages <wps> --project-context <context.json> --output <新候选.json> [--review-evidence <旧证据.json>]
python <Skill>/scripts/build_review_evidence.py register-review --source <源.md> --strategy h2 --source-packages <wps> --project-context <context.json> --review-evidence <候选.json> --package wp_002.md --review-record <实际复核.json> --output <当前证据.json>
```

`prepare` 重新准入、独立拆包及检查两侧当前事实，只产生 `pending`；仍有效旧包原样复验复用。不得覆盖旧有效记录。主 Agent 亲自回源后，实际复核 JSON 包含 `package`、当前 `facts`（对应候选条目中除 `review` 外的事实）、`scope`、`basis`、`note`、`reviewed_at`、`items` 和 `unresolved: []`。启用数字辅助时 `disposed` 覆盖当前所有 `numeric.diff_ids`，每项根据实际原值/单位处置，不自动判换算。记录实际依据，不把字段齐全、自检或子 Agent 回报当复核。

登记复跑事实并检查漂移；可原子更新指定当前记录，原记录的内容摘要历史副本保留。失败保旧。全量输入保护不随局部复核范围缩小。恢复及合并显式增加 `--project-context <context.json>`，消费相同适用口径；未提供项目口径不能消费携带该口径的旧资格。合并局部交付仍用原 `--scope <order_csv>`，其余原 CLI 保持。合并后运行全量来源对账、翻译核验及当前 `verify_delivery.py`，逐包资格不替代成品语义/适用视觉复核。

## 官方目录

```bash
python <Skill>/scripts/build_toc.py --manifest <目录清单.json> --output <实际位置/00_目录.md>
```

清单显式给出 `project_root`、`scope`、`official_basis: { "path": "独立官方标题.txt", "confirmation": "主 Agent 当前范围依据" }`、有序 `official_lines` 和 `entries`。每条含 `official_line`、`original_title`、`level`、`translation`、`occurrence`，可声明原题已有的 `number` 和实际 `fragment`。官方文本逐行是独立原题，不能从生成结果反造依据；范围内每条均须关联正确标题出现。同名条目用实际目标区别，围栏伪标题不入目录。

目录复用现有消费者标题目标，保留连续连字符、重复标题编号和显式锚点；链接从输出父目录解析。固定不可见 CommonMark 定义管理生成区间，区间外用户内容保留，未划区间手写目录拒绝覆盖。生成成功后在实际阅读器及适用 PDF 核对目标、页码、点击。现有无目录 PDF 输入不强制补建目录。

## 显式批次与后续说明

```bash
python <Skill>/scripts/review_delivery_batch.py --manifest <批次.json> --output <核对报告.json> [--python <当前解释器>] [--skill-dir <实际Skill目录>]
```

批次 `projects` 每项为 `{ "project": "明确项目", "record": "当前交付记录.json", "evidence_dir": "既有证据目录", "mode": "translation", "scope": ["01_章.md"], "status_note": "可选辅助状态" }`；模式/范围须与记录一致。分别调用既有交付 CLI，保留真实命令、退出码、诊断、当前索引及身份。单项目失败保留其他结果；清单歧义、输出冲突或发布漂移仍拒绝。无产物且无可信调度依据为不明，不推断未分派或自动重派。三种模式只执行其适用合同。

后续补译在现有交付说明/证据位置记录日期、实际前后内容、依据与重验结果。相关旧证据失效，无关包复验复用；重新实际回源后恢复、合并和成品独立验收，当前引用指向最新有效证据。按既有归位/清理合同保护历史、源、恢复输入与依赖；批次不清理未完成、失败或暂停项目。
