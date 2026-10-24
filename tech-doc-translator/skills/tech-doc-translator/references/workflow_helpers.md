# 工作包与交付辅助入口

这些入口消费当前来源和现有核验事实，不翻译、不裁决语义，也不授予自动完成资格。先按对应源家族完成原快照准入、独立对账及主 Agent 的来源/范围确认。运行产物放在项目既有证据位置或 Git 工作区外；旧源包、历史任务、复核记录与有效索引保留。

## 项目上下文

`--project-context <JSON>` 的 `project_root` 是相对引用基点；`source_record` 引用现有 `verify_delivery.py` 来源记录。准备阶段不要求尚未生成的译文、PDF 或交付级映射。`source_scope` 为 `"all"` 或明确的包顺序整数数组，不能从已收到包反推范围。`source_review` 必须有同一 `scope`、主 Agent 实际来源/范围裁决的 `basis` 及当前来源 `binding`，后者使用现有来源核对结果中的 `parsed_sha256`、`source_version`、`snapshots`；旧 PASS 或手填新摘要不代替实际确认。

显式声明 `instructions`、`rules`、`glossary`、`output_contract`、`examples`。引用可为文本路径，或 `{ "path": "rules.md", "start_line": 2, "end_line": 8, "packages": ["wp_002.md"] }`，行号闭区间；不指定选区则整份适用。术语没有配置时明确 `[]`，已选择项目词表/共享子集时保持原优先级。样例对象另含 `differences`，说明同构部分及不可仿照内容。`return_contract` 指定返回要求。`rule_conflicts` 非空时拒绝分派。

`skill_dir` 与可选 `python` 使用当前实际安装目录及解释器，保留 venv 入口。`check_args` 为现有核验参数数组，支持实际强 token、额外公式、来源适配和数字口径；相对文件参数从 `project_root` 解析。多来源适配仍重复 `--source-adaptation`，不创建另一份来源资格。具体转换可用 `structural_conversions` 的 `{ "package": "wp_002.md", "source": "可定位源文字", "target": "当前译文表示", "basis": "已确认的依据" }`；它不豁免硬检查，不能把整类结构设成免检。

单快照表转换在 `source_record.sources[].table_conversions` 声明 v1 人工映射或 v2 网格映射。来源全量准入核对快照和全部表；`source_review.binding` 另有 `table_conversions: {"path": "相对交付根的映射.json", "sha256": "当前完整映射摘要"}`，必须由实际回源确认产生。拆包、任务、逐包证据、恢复和合并均传同一 `--project-context`；生成任务给出当前只读映射位置、相关原 DOM 格事实与局部映射。`structural_conversions` 的文字说明不能替代此机器映射。

v2 网格的非首行 `th` 由原DOM和已准入映射确定，其输出格通过整格加粗保留角色；表头文字照常翻译。片段/包/确定性转换沿用 `--project-context` 的来源及字符范围，API合章沿用导航来源，核对同一组实际角色。不能从普通Markdown整格加粗推断th；v1人工表示、td强调及其他正文格式保留原合同。未提供来源角色时不声称已核验表头层次。正式交付声明v2时，verify_delivery要求检查实际消费与当前来源、快照、映射及范围一致的 --project-context 或 --navigation-record；只写参数名或提供另一份合法上下文不授予资格。

多快照在每个 `sources[].snapshots[]` 中以 `table_conversions` 路径字符串声明自己的映射，仍相对 `delivery_root`；各自 `range: [起行, 止行]` 按合并英文 Markdown 的 1 起闭区间、按序无缝覆盖，遵守既有行域（末尾换行形成的空末行也在范围内）。每份映射的表号只在该快照片段内计算，不能改成全书累计序号。条目级旧写法在单快照继续有效；多快照只在所记录摘要唯一匹配一个快照时归属。两级同时声明须指向同一物理映射；摘要漂移、歧义或同一映射跨快照重复消费均拒绝。v1 / v2 可分属不同快照，保持各自代码投影语义。

当前 `binding.snapshots` 从来源核对结果取得各快照映射的路径 / 摘要；原条目级声明仍同时进入 `binding.table_conversions`。来源声明中的字段始终为路径字符串，不把 binding 内的摘要对象反抄到来源声明。任务只携带本包相关表事实和版本；修订一份快照映射、重新确认全源后，其他快照的健康包仍按相同局部资格复验复用。

修订映射写新文件、保留旧任务及旧依据，完整重核后再更新来源记录和当前来源裁决。包级 check_policy 只绑定该包相关表、来源格位 / 代码 / 表头事实、映射版本及读取器，不绑定整份映射路径 / 摘要；新文件中未变的表经当前硬检查及局部事实复验可复用，变更表所在包须实际重核登记。完整映射仍由准入层绑定，不能省略准入或只换摘要沿用旧 done。

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

## 单页 API 与标题工作清单

单个 API 页面同样使用家族核验：

```bash
python <Skill>/scripts/parse_api_html.py <site/page.html> <source.md>
python <Skill>/scripts/export_heading_list.py <source.md> <任务标题.txt>
python <Skill>/scripts/verify_api_translation.py <译文.md> <manifest.txt> <official_toc.txt> <site> <source.md>
```

`manifest.txt` 和独立官方 `official_toc.txt` 各按实际范围列出 `page.html`；不能把发现结果复制成官方依据。将标题工作清单作为任务的标题顺序提示，逐项保留源层级，不能把它作为 `--official-headings-file` 的独立官方基准。导出器排除代码中的伪标题；列表覆盖率按真实有序 / 无序项读取，两侧同口径，差值仅供回源复核。

## 自足任务与当前漂移

```bash
python <Skill>/scripts/build_work_package_tasks.py --source <源.md> --strategy h2 --source-packages <wps> --project-context <context.json> --package wp_002.md --output <任务.json>
```

JSON 的 `task` 为完整任务正文，含实际元数据、选中上下文、唯一源/目标、脚本计数、当前命令及四类返回；图片身份从独立当前源取得，资源由主 Agent 分派前准备。只准翻译 Agent 写其 `target`。未列出的结构不视为零；`[TABLE]` 重建真实 Markdown 表格，不保留残留标记。复杂表格的解析源格位与译文逻辑列位须分别回源核对，不能仅凭机器 PASS 决定分组。

补译或规则变化时指定 `--previous-task <旧任务.json>`，历史 JSON 和其只读旧源包必须保留实际正文、引用选区内容和转换；仅有摘要不足以重建前后变化。生成器给出精确差异与重验事项，不自动迁移或重派译文。旧回报不授予当前资格。

## 待复核、逐包登记与实际消费

含格内围栏代码时，项目 `check_args` 显式加入 `["--table-code-stage", "intermediate"]`，当前规则和样例要求中间译包保留坐标标记及紧随围栏；表格与代码组一起拆包。任务命令使用 `verify_translation.py <译包> <源包> --fragment --table-code-stage intermediate`，恢复 / 逐包复核消费同一参数与 check_policy。省略阶段参数按最终规则检查。

经当前实际复核后，用 `merge_work_packages.py <最终.md> <译包>... --source <源.md> --strategy h2 --source-packages <wps> --review-evidence <当前证据.json> --project-context <context.json> --finalize-table-code` 合并；单页亦可指定 `--scope 1`。合并只把独立标记行转为 `本表第 2 行、第 3 列的代码 1：` 之类的说明，包含表头、不含分隔行，紧接原代码；中间译包与代码字节不变。正文、标题和下一表终止代码组，重复 / 越界 / 缺围栏 / 孤儿说明拒绝。最终家族核验、PDF 与交付记录均不能选择中间阶段。旧合法中间包必须按当前身份重核；代码中的同形字面示例保留。

```bash
python <Skill>/scripts/build_review_evidence.py prepare --source <源.md> --strategy h2 --source-packages <wps> --project-context <context.json> --output <新候选.json> [--review-evidence <旧证据.json>]
python <Skill>/scripts/build_review_evidence.py register-review --source <源.md> --strategy h2 --source-packages <wps> --project-context <context.json> --review-evidence <候选.json> --package wp_002.md --review-record <实际复核.json> --output <当前证据.json>
```

`prepare` 重新准入、独立拆包及检查两侧当前事实，只产生 `pending`；仍有效旧包原样复验复用。不得覆盖旧有效记录。主 Agent 亲自回源后，实际复核 JSON 包含 `package`、当前 `facts`（对应候选条目中除 `review` 外的事实）、`scope`、`basis`、`note`、`reviewed_at`、`items` 和 `unresolved: []`。启用数字辅助时 `disposed` 覆盖当前所有 `numeric.diff_ids`，每项根据实际原值/单位处置，不自动判换算。记录实际依据，不把字段齐全、自检或子 Agent 回报当复核。

登记复跑事实并检查漂移；可原子更新指定当前记录，原记录的内容摘要历史副本保留。失败保旧。全量输入保护不随局部复核范围缩小。恢复及合并显式增加 `--project-context <context.json>`，消费相同适用口径；未提供项目口径不能消费携带该口径的旧资格。合并局部交付仍用原 `--scope <order_csv>`，其余原 CLI 保持。合并后运行全量来源对账、翻译核验及当前 `verify_delivery.py`，逐包资格不替代成品语义/适用视觉复核。

合并候选按最终目录解析资源；通过硬检查后写入该目录的暂存文件，flush/fsync 后独立重读核验，再原子替换最终 Markdown。候选拒绝、写入或替换失败均保持旧成品，首次失败不留最终文件。表格检查器变化使旧 checker 资格失效，须用当前实际检查和回源记录重新登记，不能仅改旧摘要。

## 官方目录

```bash
python <Skill>/scripts/build_toc.py --manifest <目录清单.json> --output <实际位置/00_目录.md>
```

目录清单字段如下；官方原题及范围须独立核对，生成标题工作清单不构成官方依据。

| 字段 | 必填与类型 | 含义 / 基点 |
| --- | --- | --- |
| `project_root` | 可选路径字符串 | 缺省为清单父目录；显式相对路径按调用 cwd 解释，推荐绝对路径或先切换项目目录 |
| `scope` | 必填非空范围说明 | 示例用字符串说明已确认章 / 节，不由实收译文反推 |
| `official_basis.path` | 必填路径字符串 | 独立 UTF-8 原题文本，相对 `project_root` |
| `official_basis.confirmation` | 必填非空确认说明 | 主 Agent 实际核对来源与范围的依据 |
| `official_lines` | 必填整数数组 | 官方文件中 1 起行号，严格递增且唯一，与 entries 的 official_line 序列完全一致；不是行号字符串或标题数组 |
| `entries` | 必填非空对象数组 | 按官方顺序关联每个真实标题实例 |
| `entries[].official_line` / `original_title` | 必填整数 / 字符串 | 指定行与该行裁首尾空白后的原题逐字相同 |
| `entries[].level` | 必填整数 | 对应真实原题层级（H1 为 1）；不能只为显示缩进改变层级 |
| `entries[].translation` | 必填路径字符串 | 译文 Markdown 文件，相对 `project_root`，不是译文标题 |
| `entries[].occurrence` | 必填正整数 | 该译文中与原题匹配的标题出现序号，从 1 起；同名标题不能默认取第一个 |
| `entries[].fragment` | 可选字符串 | 缺省为该标题实际 slug；显式值也必须对应该标题，不能借任意同名锚点 |
| `entries[].number` | 可选编号，建议字符串 | 必须已是官方原题前缀；只用于保留原编号，不创造新编号 |

最小完整示例：在工作区外示例目录中准备独立的 `official.txt`：

```text
1. Introduction
1.1. Scope
```

以及 `01_示例.md`：

```markdown
# 1. Introduction（引言）

第一章正文。

## 1.1. Scope（范围）

范围正文。
```

从该目录运行，保存 `toc.json`：

```json
{
  "project_root": ".",
  "scope": "示例原文第 1 章及 1.1 节",
  "official_basis": {
    "path": "official.txt",
    "confirmation": "已独立核对演示原题与范围，未从生成目录反造。"
  },
  "official_lines": [1, 2],
  "entries": [
    {"official_line": 1, "original_title": "1. Introduction", "level": 1,
     "translation": "01_示例.md", "occurrence": 1, "fragment": "1-introduction引言"},
    {"official_line": 2, "original_title": "1.1. Scope", "level": 2,
     "translation": "01_示例.md", "occurrence": 1, "fragment": "11-scope范围"}
  ]
}
```

```bash
<环境>/bin/python <Skill>/scripts/build_toc.py --manifest toc.json --output 00_目录.md
```

消费者从实际输出目录解释链接，保留连续连字符、重复标题编号与已支持的标题目标；代码伪标题不入目录。生成器只替换 `[tdt-toc-start]: #` 与 `[tdt-toc-end]: #` 之间的区间，区间外说明保留；已有手写目录未划区间时拒绝覆盖。实际阅读 / PDF 还须核对点击与页码。

错误示例：`official_lines: "1,2"` 类型错误；`official_line: 99` 越界；本例 `occurrence: 2` 没有对应实例；`fragment: "missing"` 不属于该标题，均拒绝且不覆盖旧目录。不能把导出的标题清单复制成独立官方依据。

需要出处覆盖映射时，在生成区间外的文件开头加一段 `译自：https://example.org/guide/introduction.html。` 并空一行，使它为实际第 1 行；完整 JSON 及摘要口径见 [出处映射示例](pdf_export.md#出处映射完整示例)。题注尾部 `[#](#anchor)` 是源链接：翻译阶段保留，最终目标在相应图 / 表外且保持来源对象身份；不把它塞进目录 JSON，也不删除链接求通过。

## 显式批次与后续说明

```bash
python <Skill>/scripts/review_delivery_batch.py --manifest <批次.json> --output <核对报告.json> [--python <当前解释器>] [--skill-dir <实际Skill目录>]
```

批次 `projects` 每项为 `{ "project": "明确项目", "record": "当前交付记录.json", "evidence_dir": "既有证据目录", "mode": "translation", "scope": ["01_章.md"], "status_note": "可选辅助状态" }`；模式/范围须与记录一致。分别调用既有交付 CLI，保留真实命令、退出码、诊断、当前索引及身份。单项目失败保留其他结果；清单歧义、输出冲突或发布漂移仍拒绝。无产物且无可信调度依据为不明，不推断未分派或自动重派。三种模式只执行其适用合同。

后续补译在现有交付说明/证据位置记录日期、实际前后内容、依据与重验结果。相关旧证据失效，无关包复验复用；重新实际回源后恢复、合并和成品独立验收，当前引用指向最新有效证据。按既有归位/清理合同保护历史、源、恢复输入与依赖；批次不清理未完成、失败或暂停项目。

### 来源对象导航

API 解析生成的对象锚点随对象进入同一工作包。任务与片段核验保留 ID、顺序和内容对象归属，表格数据区不得插入锚点。新规则进入原有上下文选区及 checker 身份；历史资格须按当前规则复验，不能重新签名追认。翻译任务保留源目标；主 Agent 最终合章才执行有依据的路径转换：

```bash
python3 "$SCRIPTS/merge_api.py" source/chapter-pages.txt source/site 01_章节.md --navigation-record source_record.json
python3 "$SCRIPTS/verify_api_translation.py" 01_章节.md source/chapter-pages.txt source/official-pages.txt source/site source/a.md source/b.md --navigation-record source_record.json
```

`source_record.json` 使用上文相同的 delivery_root 与 sources 声明；a / b 快照的 covers 都须唯一为 `01_章节.md`，其他章的目标页也在记录中以自身 covers 声明。多快照按 range 全量无缝覆盖；不同源页同名 ID 保持不同身份，不改变原始翻译页。记录、快照、解析源、映射及检查器进入最终检查依赖，变化后实际重核。

### 规则—任务—检查的接续

规则/模板改变时，先由主 Agent 对照实际源及检查命令裁决冲突，未解决项保留在 `rule_conflicts`，此时不生成任务。规则、词表和模板用已有 `packages` 或行选区限定适用包；新文档单独保存，旧任务及其引用文件不覆写。`--previous-task` 读取实际旧源包和任务中保存的选区正文，展示路径/内容/命令/转换的精确差异；缺正文直接报告，不能由摘要猜前文。当前上下文不是历史正文的替代。

确认目标没有旧写者（或宿主已确认终止/撤销写权）后，执行新任务、当前片段检查并实际回源。prepare 仅取当前事实，不授予 done；受影响包经 register-review 登记当前复核再恢复/合并，无关包使用同一局部 check_policy 复验复用。新旧任务、规则和证据输出分别使用新路径，最终整章检查仍须重跑。生成器保护已知历史只读引用；没有显式声明的历史文件仍由主 Agent 保留，不扫描目录猜身份。

CUDA 同构项目样例（仅用于该项目，不升级为所有领域默认）：

| 对象 | 当前约定及验证依据 |
| --- | --- |
| 选项卡 | 使用加粗 `**[Tab: C++]**` 标签并保持面板相邻与父属；对应源标签与代码/内容顺序，不只核对标签集合。 |
| 引导词 | `**提交（Commit）**。`、`**等待（Wait）**。`；保留英文以便回查 pipelines 的原引导词，代码/API 原样。 |
| 空格位 | 保留原空格与题注；例如 Table 5 已用题注明示空格是不支持的源—目标组合，仍可保持空格；纯排版空格不能自动补 `—`。 |
| 译注 | 只有可能误导技术理解的已回源疑误加注，例如原 `__CUDA_ARCH_` 仍照录，注中指出疑为附录所用 `__CUDA_ARCH__`；重复 clusters 或大小写排版问题不自动加注。 |
| 术语 | localized 在 locality domain 内存/计算语境沿用“局部化”，日志未做语言本地化属于另一语境；async barrier / asynchronous barrier 为“异步屏障”，tile 数据移动 gather/scatter（含 gathered/scattered）为“聚集/散射”，模块 eager 为“立即加载”，代码 `EAGER` 不译。保留原句、来源/首现及项目裁决，不推及其他技术语境。 |

共享库经 `select_glossary.py --library ...` 显式选择，项目词表用 `--project ...` 覆盖同一英文及语境键；多语境须 `--context 'localized=locality domain'` 等明确选择。未裁决的其他语境只回报，不自动加入项目表。生成有效子集后，以当前 `glossary` 选区传到所有相关任务；新增术语不能只更新磁盘词表而沿用旧资格。

### 授权后的并发与接续

已授权使用子 Agent 的任务，按 [Skill 的并发与升级复核](../SKILL.md#并发与升级复核) 读取宿主真实进展/失败/限流，记录事件去重、C、冷却期限、在途目标与所有权。事件记录放既有任务记录或工作区外；受控测试输入、实际调度动作与自然宿主事件分开记录；按项目批准的验收口径核对，未发生的自然限流/停滞明确记为未实测，不制造故障耗尽额度；取消未确认不能释放写权。确认退出/撤销后按上文当前源、规则和恢复资格接续，不重建调度服务。
