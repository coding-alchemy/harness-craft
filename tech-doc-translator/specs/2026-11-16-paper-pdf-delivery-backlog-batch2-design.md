# 论文翻译与 PDF 交付遗留问题设计（第 2 批）

| 元数据 | 内容 |
| --- | --- |
| 文档版本 | V0.10 |
| 文档状态 | 2026-11-17 批准（评审中确认 R8 采用导出时适配、R12 第 2 条只保护重导出）；R17 图片与图题居中（§19）、R18 SVG 插图清晰度（§20）于 2026-11-18 批准，R19（§21）于 2026-11-18 由用户选定增补，R20（§22）于 2026-11-19 由用户决定并入本批。最终实施验收与实施差异见 §18–§22，剩余缺口见 §18.3 |
| 创建 / 修订日期 | 2026-11-17 / 2026-11-19 |
| 适用范围 | `tech-doc-translator` 的交付校验（`verify_delivery.py`）、来源准入与对账（`_api_navigation.py`、`_source_reconcile.py`）、LaTeXML 解析（`_latexml_source.py`）、数字复核（`_numeric_review.py`）、PDF 导出与核验（`export_pdf.py`、`verify_pdf.py` 的外链尾斜杠等价比较（R19）、`assets/pdf/style.css`）、论文译文核验输出（`verify_reference_translation.py`）、工作包合并（`merge_work_packages.py`，R20）、新增 `render_delivery_notes.py`、`SKILL.md` 与 `references/` |
| 权威需求 | [论文翻译与 PDF 交付遗留问题需求](./2026-11-16-paper-pdf-delivery-backlog-requirements.md) V0.13；V0.4 于 2026-11-17 批准，R17、R18 与 D4、D5 及 R19 与 D6 于 2026-11-18 选定增补，R20 于 2026-11-19 决定并入本批。本批为 R4、R6–R8、R10–R15、R17–R20 与第 1 批遗留两项 |
| 基线 | `zn_dev` @ `735be08`（代码与 `b7d1418` 相同）。文中行号都指该提交；`scripts/` 下的文件只写文件名 |
| 既有设计 | [第 1 批设计](./2026-11-16-paper-pdf-delivery-backlog-design.md)、[CUDA 13.5 升级重译修复设计](./2026-11-14-cuda-upgrade-retranslation-fixes-design.md)（API 家族来源记录与导航）、[论文流程去重与稳定性优化设计](./2026-11-07-paper-workflow-optimization-design.md)（逐阶段进度输出） |

## 1. 目标与边界

本批对应的耗时与返工（需求 §1、W1 终版、E1–E3）：

- CUDA PG 13.5：修复轮加合章校验约 6.7h；一次 `verify_delivery` 1.5–2 小时，其中约 45 分钟没有输出，用户因此取消过一次校验，取消后的收尾回合（重验、记录定稿、视觉终检、交付说明）又用了 3h31m（R15）。
- MTGR 版面修复 2h07m，靠手改 3 处注册表和项目脚本里的常量（R8）。
- HSTU 只做了格式修复，165 项数字复核里 115 项要按新行号重新闭合（R11）。
- 交付说明与复核备注手写，每个项目约 1 小时，出过“41 vs 42”“83 vs 85”这类计数错（R12）。
- 一次性的误报和返工：标题带着长代码块移页被判失败（R4）、链接拆词与图注孤悬（R6）、列表双圆点（R7）、检查器变化后不知恢复顺序（R10）、漏传严格参数（R12）、无图像会话的复核写法各异（R13）、清理后无法验收（R14）。

完成后，CUDA 规模的交付校验单次不超过 20 分钟并持续输出进度；版面适配、数字复核、文书统计、清理后验收都有组件入口，不再手改注册表或手抄数字。

本批还包括第 1 批的两项遗留：R9 的“全绿复跑输出不超过一屏”没有达到；R3 的脚注定义与表格单元格锚点没有样本验证。

不做：增量校验（需求 §4 D3 决定不做）；需求 §6 的整体验收（共享安装重装后实测，不在本设计内）。

## 2. 总览

| 需求 | 改动位置 | 性质 |
| --- | --- | --- |
| R15 | `_source_reconcile._conversion_map_diffs` 表格只解析一次；`verify_delivery._check_facts` 取导航事实时不做准入，同一次计算内共用；身份计算和取事实进入进度阶段 | 改现有代码 |
| R4 | `verify_pdf.check_code_pagination` 判失败前看前一个元素是不是标题 | 改现有检查 |
| R6 | `style.css` 的链接断行规则；图片分页规则覆盖带链接的图片 | 样式 |
| R7 | `_latexml_source.enumerate_items` 去掉无序列表圆点；`translation_conventions.md` 加一条 | 改现有代码 + 文档 |
| R8 | `export_pdf` 新增 `--image-adaptations`：在显示尺寸绑定上覆盖宽度，SVG 派生时改 viewBox；`verify_pdf` 从导出报告读同一声明 | 新增一个导出参数 |
| R10 | `workflow_helpers.md` 写恢复顺序；`verify_delivery` 身份变化报错列出变化的键和文件 | 文档 + 改报错 |
| R11 | `_numeric_review` 差异 ID 去掉行号，改用数值加前后文；`--prepare-reviews` 列出新增项 | 改持久 ID 写法 |
| R12 | 新增 `render_delivery_notes.py`；`export_pdf` 导出前比对记录里 verify_pdf 检查的严格参数；`verify_delivery` 拒绝含待补占位的备注 | 新增脚本 + 两处检查 |
| R13 | `verify_pdf --visual-aid` 加页脚页码检查和关键页清单；`verify_delivery` 核对程序化目检备注；`SKILL.md`、`pdf_export.md` 写两档复核 | 改现有检查 + 文档 |
| R14 | `cleanup.md` 写清先后；`verify_delivery --after-cleanup` 清理后核对 | 文档 + 新增只读模式 |
| R17 | `style.css` 让单独成段的图片和紧跟图片的单行图题居中；`export_pdf` 给图题段加 `image-caption` 类；`verify_pdf._destination_matches` 对图片的独立锚点按版心左缘比对目的地（§19） | 样式 + 导出器标注 + 改现有检查 |
| R18 | `export_pdf.svg_print_dimensions` 在派生位图不足 2 倍显示宽度时宽高同乘整数倍，倍数写入导出报告；`verify_pdf.check_svg_renders` 按报告的倍数重建（§20） | 改现有代码 + 报告字段 |
| 遗留 | `verify_reference_translation` 数字提示汇总为一行；补表格单元格与脚注锚点的测试和样本 | 改输出 + 测试 |

## 3. 基线与机制重审

### 3.1 改动依赖的现有接口

| 接口 | 位置 | 本设计的用法 |
| --- | --- | --- |
| `load_navigation`、`navigation_dependencies`、`navigation_context`、`load_pdf_navigation` | `_api_navigation.py:597`、`:1047`、`:1063`、`:1086` | R15：全站准入只留在实际检查里 |
| `_check_facts` 的 API 分支 | `verify_delivery.py:2437`–`:2464` | R15：改用不做准入的导航事实 |
| `compute_delivery_identity`、`_rerun_checks`、`publish_evidence`、`_delivery_checks` | `verify_delivery.py:2017`、`:2579`、`:3488`、`:3936` | R15 共用导航事实与进度；R10 报错 |
| `source_dependency_paths(entries=...)`、`table_role_source` | `verify_delivery.py:1006`、`:2126` | R15 的轻量导航事实直接复用 |
| `progress_stage` | `verify_delivery.py:192` | R15 进度 |
| `_conversion_map_diffs`、`_MarkdownFacts.table_records` | `_source_reconcile.py:2250`、`:1649` | R15 |
| `check_code_pagination` | `verify_pdf.py:4541` | R4 |
| `enumerate_items` | `_latexml_source.py:746` | R7 |
| `load_display_maps`、`svg_print_dimensions`、`render_svg_payload`、`plan_svg_renders` | `export_pdf.py:100`、`:3618`、`:3650`、`:3713` | R8 |
| `check_svg_renders` | `verify_pdf.py:965` | R8：核验侧按同一绑定重渲染比对 |
| `diff_numeric_tokens`、`group_numeric_diffs`、`format_diff_hint` | `_numeric_review.py:404`、`:517`、`:571` | R11、R9 遗留 |
| `_prepare_reviews`、`_closed_review_covers` | `verify_delivery.py:3965`、`:4020` | R10、R11 |
| `check_reviews` | `verify_delivery.py:3155` | R12、R13 |
| 导出前的就绪检查 | `export_pdf.py:4222`–`:4239` | R12 严格参数比对的位置 |
| 严格参数的核验侧比对 | `verify_pdf.py:5605`–`:5621` | R12 |
| `collect_visual_aid`、辅助统计入口 | `verify_pdf.py:184`、`:5732` | R13 |

### 3.2 与需求的差异（核对源码后）

| 需求 | 核对结果 | 本设计的处理 |
| --- | --- | --- |
| R8 | 需求写“同步源侧和交付侧、注册表与记录”。导出器已有 SVG 派生：绑定了显示宽度的 SVG 在离线浏览器里渲染成 PNG 再嵌入（`export_pdf.py:4636`–`:4655`），核验侧按同一绑定重渲染比对像素（`verify_pdf.py:965`） | 适配只在导出时生效，交付图片、源快照和注册表都不改，所以不需要同步；还原就是删掉声明（§8）。不支持位图裁剪 |
| R10 第 2 条 | 工具判断不了一次运行是不是首跑 | 报错列出变化的身份键和文件，不声称首跑（§9.2） |
| R11 | 差异 ID 带行号（`_numeric_review.py:446`）；闭合复核还绑定译文摘要（`verify_delivery.py:4026`），译文一改就要重新闭合 | ID 去掉行号，重新闭合时只需判读新增项；升级后旧 ID 对不上，存量项目要重新闭合一次（§10） |
| R12 第 1 条 | `00_目录.md` 已由 `build_toc.py` 生成；外部文件记录是知识库的约定（知识库 `AGENTS.md:61`） | 不新增目录生成；外部文件记录只渲染文件清单（路径、sha256、大小）；交付根的说明文件没有登记时拒绝写入并打印要补的记录片段，不自动改记录（§11.1） |
| R12 第 2 条 | 现行流程在首次导出之后才把 verify_pdf 检查写进记录（`workflow_helpers.md:30`）；`translation` 模式的记录里预先登记 verify_pdf 检查会因没有绑定输出而被拒（`verify_delivery.py:2657`） | 只比对记录里已有的 verify_pdf 检查，即覆盖重导出；首次导出不比对（§11.2） |
| R14 第 2 条 | 删除源快照与成品 PDF 的是知识库规则，不是组件规则 | 组件规则写清先后；清理后核对的发布根目录由参数传入，组件不写死知识库路径（§13） |
| R15 | 剖析已在设计期完成（§4.1） | 采用用户确认的目标：CUDA PG 交付校验单次不超过 20 分钟 |
| R9 遗留 | 115 行里 76 行是数字提示：`summarize_messages`（`_verification.py:1913`）取前 60 字作类名，单位词和章节名留在类名里，同一种提示被拆成几十类 | 数字提示单独汇总为一行（§14.1） |

以上处理经 2026-11-17 对话确认，随本设计于同日批准；R8 改用比对话时更简单的做法，已在评审中确认。

### 3.3 机制重审

按 AGENTS.md §5，本批有四处要先比较方案：

- R15 改变 `_check_facts` 的职责（不再做准入），比较见 §4.6。
- R8 新增导出输入，三种做法的比较见 §8.1。
- R11 改变写进 `reviews[].items` 与包证据的数字差异 ID，属于持久记录契约变化，比较见 §10.1。
- R12、R13 给 `check_reviews` 增加备注规则，比较结构化字段与备注文字，见 §12.3。

## 4. R15 合章与交付校验的运行时间

### 4.1 设计期剖析

探针脚本放在 Git 工作区外的会话临时目录，只读项目文件（审计钩子拒绝向临时目录以外写入）；解释器为 `~/.venvs/tech-doc-translator/bin/python`。

| 编号 | 内容 | 结果 |
| --- | --- | --- |
| P0 | CUDA PG 13.5 最后一次 `verify_delivery` 的阶段输出（`/tmp/final_check.log`，2026-11-16 15:35Z–17:20Z，约 1 小时 45 分钟，通过） | 见下表 |
| P1 | 会话实际运行的代码（共享安装 V1.5 加项目补丁），cProfile 剖析一次 `load_navigation` | 剖析下 598 秒（不剖析约 220 秒）。`_MarkdownFacts.table_records` 被调 3892 次，累计 473 秒，占 79%；项目补丁 `fixed_table_records` 自身 0.8 秒 |
| P2 | 同一代码，`table_records()` 每份 Markdown 只算一次 | 一次准入从 221.9 秒降到 40.0 秒，53 页准入结果的摘要与改动前相同 |
| P3 | 仓库代码（无项目补丁），同 P2 两种方式 | 两种方式都停在同一处（unified-memory 页带 id 引用块的锚点，见 §4.6），到该处分别用了 243.0 秒和 29.1 秒，报错相同 |
| P4 | 仓库代码，剖析 `check_source_chains` 与 `navigation_dependencies` | 各约 12 秒，都花在为 53 个快照构建 `_SourceFacts`；`navigation_dependencies` 经 `source_dependency_paths` 在内部再调一次 `check_source_chains` |
| P5 | 仓库代码，把 `navigation_context` 换成 §4.4 第 2 条的轻量版，在 CUDA PG 交付记录上算一次 `compute_delivery_identity` | 依赖清单与现行完全相同；每条检查各算一次时 104.0 秒，同一次计算内共用时 39.7 秒；不含检查时 13.4 秒 |

P0 各阶段用时：

| 阶段 | 用时 |
| --- | --- |
| source-preflight | 12 秒 |
| 不在任何阶段内（算基线身份、复跑前逐条取检查事实） | 约 45 分钟，没有输出 |
| source-reconcile | 195 秒 |
| verify_api_translation × 6 | 每章 218–230 秒；`06_Notices.md` 只有 4.6 KB，也用了 218 秒 |
| verify_pdf | 487 秒 |
| reviews | 0.04 秒 |
| publish | 1509 秒 |

### 4.2 根因一：一次运行把全站来源准入重做 25 次

`load_navigation`（`_api_navigation.py:602`–`:603`，现有代码）每次都对整份来源记录重做源链核对和全站对账：

```python
    problems=[];entries=delivery.check_source_chains(str(root),record,problems,source_only=True)
    delivery.run_source_reconcile(str(root),record,entries,problems)
```

一次 `verify_delivery` 里调用它的地方（CUDA PG 的记录有 6 条 API 检查和 1 条 verify_pdf 检查）：

| 调用方 | 位置 | 次数 |
| --- | --- | --- |
| 算基线身份：`compute_delivery_identity` → `_check_facts` → `navigation_context` | `verify_delivery.py:3945` → `:2111` → `:2452` | 6 |
| 复跑前取事实：`_rerun_checks` → `_check_facts` | `verify_delivery.py:2646` | 6 |
| 章节检查子进程 | `verify_api_translation.py:115` | 6 |
| verify_pdf 进程内复验：`load_pdf_navigation` → `navigation_context` | `_api_navigation.py:1102` | 1 |
| 发布前重算身份 | `verify_delivery.py:3558` | 6 |

共 25 次，按每次约 220 秒约 92 分钟，与 P0 的 1 小时 45 分钟相符：约 45 分钟的无输出空档是前两行的 12 次；publish 的 1509 秒里约 1320 秒是最后一行的 6 次。

一轮合章加核验（`merge_api.py:259` 与 `verify_api_translation` 各 6 次）共 12 次，约 44 分钟，与复盘里“全量一轮 40 分钟起步”一致。带 `--translation-record` 的 API 家族导出按代码要做 31 次：就绪检查在导出前后各做一次（`export_pdf.py:4224`、`:4908`），每次都重算身份；CUDA PG 这次导出没有走这条路径。

### 4.3 根因二：逐格重复解析整页表格

`_conversion_map_diffs`（`_source_reconcile.py:2250`）在逐表、逐格循环里三次调用 `md.table_records()`（现有代码）：

```python
# :2328，逐表循环内
            output = next((r for r in md.table_records() if r['ordinal'] == record['ordinal']), None)
# :2385，逐格循环内
                        out = next((r for r in md.table_records() if r['ordinal'] == target['table']), None)
# :2409，逐格循环内
                    out_record = next(
                        (r for r in md.table_records()
                         if r['ordinal'] == out_ordinal), None)
```

`table_records()`（`:1649`）每调一次，都用 markdown-it 把整份 Markdown 的全部表格重新解析一遍。跨度表越大、表越多，调用越多，这就是 E1 B.2 记录的超线性（19K 字符的章 10.6 秒、7K 字符的章 0.2 秒）。同一函数后面已经建好按序号查表的字典（`:2497`，现有代码）：

```python
    md_records = {r['ordinal']: r for r in md.table_records()}
```

### 4.4 改动

1. **表格只解析一次**（`_source_reconcile.py`）：把 `:2497` 这一行移到函数开头、`:2289` 的 `src_by_ordinal` 之后；`:2328`、`:2385`、`:2409` 三处改为 `md_records.get(序号)`。函数内没有修改这些表格记录的语句；P2 的结果摘要相同、P3 停在同一处且报错相同，是结果不变的依据。
2. **取检查事实时不做准入**（`_api_navigation.py`、`verify_delivery.py`）：
   - `_api_navigation.py` 新增 `navigation_facts(record_path, site_root)`，放在 `navigation_context` 之前：对来源记录做一次 `check_source_chains(..., source_only=True)`；用这批 entries 调 `source_dependency_paths(..., entries=entries, include_parsed_resources=False)` 得到依赖文件并算摘要（与 `navigation_dependencies` 同一清单，P5 已核对相同）；按快照路径给出每页的所属章和 `table_role_source`。不做 `run_source_reconcile`、锚点证明和表头读取。
   - `_check_facts` 的 API 分支（`verify_delivery.py:2448`–`:2460`，现有代码）：

     ```python
                 if parsed.get('navigation_record'):
                     from _api_navigation import navigation_context
                     nav_path = _rooted(root_abs, parsed['navigation_record'])
                     try:
                         context = navigation_context(nav_path, facts['params']['site_root'])
                     except (OSError, ValueError, KeyError, TypeError) as exc:
                         local_problems.append(f"核验记录 #{order} 导航来源拒绝：{exc}")
                         return None, None
                     facts['files']['navigation_record'] = next(
                         item for item in context['dependencies'] if item[0] == context['record'])
                     facts['files']['navigation_sources'] = [
                         item for item in context['dependencies'] if item[0] != context['record']]
                     pages = context['pages']
     ```

     改为调用 `navigation_facts`，其后的赋值不变。写进检查事实的内容（依赖摘要、各页角色来源）与现在相同，已有复核的绑定不受影响。
   - `_check_facts` 加可选参数 `memo`（字典）。`compute_delivery_identity` 的检查循环（`:2111`）和 `_rerun_checks`（`:2646`）每次调用各建一个，传给本次的每条检查；同一份导航记录在一次计算里只算一次。verify_pdf 分支经 `resolve_navigation_declarations` 取的导航依赖（`:2323`–`:2328`）也走同一个 `memo`。
   - 准入仍由实际检查来做：`verify_api_translation`、`merge_api` 和 `load_pdf_navigation`（导出与 verify_pdf）不变。源链核对的问题照旧在取事实时报“导航来源拒绝”；对账与锚点证明失败原来也在这里报，改为由章节检查子进程报“导航来源: …”，同样阻断。
3. **身份计算与取事实输出进度**（`verify_delivery.py`）：`_delivery_checks`（`:3945`）与 `check_translation_readiness`（`:3695`）里的 `compute_delivery_identity` 包进 `progress_stage(run_context, "identity", root)`；`_rerun_checks` 里的 `_check_facts`（`:2646`）包进 `progress_stage(run_context, "check-facts", 目标, order)`；发布前的重算沿用已有的 publish 阶段。
4. **长阶段定时补 `running` 心跳**（`verify_delivery.py`，R15 第 2 条）：`progress_stage` 在阶段运行期间每隔 60 秒（常量 `PROGRESS_HEARTBEAT_SECONDS`）输出一条带已运行秒数的 `running` 进度，阶段结束即停。所有走 `progress_stage` 的阶段（含导出与 verify_pdf 的长阶段）不再长时间没有输出，核验结果不变。

### 4.5 预期耗时

按 P2、P3、P5 的分项估算 CUDA PG 一次 `verify_delivery`，以验收实测为准：

| 阶段 | 现状 | 改后（估） |
| --- | --- | --- |
| 预检 | 12 秒 | 12 秒 |
| 基线身份 + 复跑前取事实 | 约 45 分钟 | 约 80 秒（P5：每次约 40 秒） |
| source-reconcile | 195 秒 | 约 20 秒 |
| verify_api_translation × 6 | 约 22 分钟 | 约 4.5 分钟（每章一次准入，约 40 秒） |
| verify_pdf | 487 秒 | 约 5.5 分钟（一次准入加 PDF 检查约 270 秒） |
| publish | 1509 秒 | 约 3.5 分钟（重算身份约 40 秒，写批次与重读约 180 秒） |
| 合计 | 约 1 小时 45 分钟 | 约 15 分钟 |

一轮合章加核验约 10 分钟（12 次准入，每次约 40 秒，加合章与核验本身）。

### 4.6 不做的方案与限制

- **只改其中一条**：只做第 1 条，`_check_facts` 里的 18 次准入每次仍约 60 秒（含前后两次依赖重算），单次约 30 分钟；只做第 2 条，剩下的 7 次准入每次仍约 220 秒，单次约 35 分钟。两条都要做才能达到 20 分钟。
- **进程内缓存准入结果**：缓存键必须覆盖准入读过的每个文件，漏一个就会拿到过期结果；两条都做之后一次运行只剩 7 次准入，缓存最多再省约 4 分钟，不抵这个风险。第 2 条的 `memo` 只在一次身份计算或一次复跑内共用，存的是依赖摘要和页归属，不跨越“基线”和“发布前重算”，漂移检出不变。
- **单章入口只准入本章源页**：能再省约 3 分钟，但改变单章入口的检查范围。
- **增量校验**：需求 §4 D3 决定不做。
- **仓库代码过不了 CUDA PG 现有产物的准入**：现有解析稿由 V1.5 生成，没有 V1.7 新增的带 id 引用块锚点（CHANGELOG V1.7“兼容性”一条；P3 停在 unified-memory 页的 `um-legacy-memcpy-cit1/2`）。验收先在副本上按该条迁移（§15）。
- **cuSPARSE**：E1 B.2 的超线性多半是同一调用模式，跨度表走 v2 网格映射，会进入同一逐格循环（`:2385`、`:2409`）。原始快照已删，验收时按 cuSPARSE 的外部文件记录重新下载后实测。

## 5. R4 长代码块随标题移页

### 5.1 现状（`verify_pdf.py:4640`，现有代码）

```python
            if remaining_pt >= required_pt:
                block = chapter.code_blocks[bi]
                lines = logical_lines_of(block)
                failures.append(
                    {
                        "code": "code-page-gap",
```

前页剩余空间放得下“前导内容 + 至少一整行代码”时一律判 `code-page-gap`。标题带 `break-after: avoid`（`style.css:28`），Chromium 会把标题和紧随的长代码块一起移到下一页；这时前页的留白是标题不孤行的代价，检查却判失败。

共享安装的就地补丁（共享安装 `scripts/verify_pdf.py:4677`，项目适配代码）用 `y <= block_base + 2.0` 找“块上方的同页标题”。PDF 坐标的 y 轴向上，这个条件选中的是代码块自己的行，总为真，于是所有本该失败的整块移页都被记成不交复核的放宽项，检查等于关掉。本设计不照搬。

### 5.2 改动（`verify_pdf.py`）

1. 新增 `_code_follows_heading(chapter, index)`，放在 `check_code_pagination` 之前：取 `chapter.soup.find_all("pre")[index]`（与 `chapter.code_blocks` 同序，见 `export_pdf.py:4077`–`:4078`），找到外层的 `div.code-block`，向前跳过只含锚点的 `.anchor-only` 段落，看前一个兄弟元素是不是 `h1`–`h6`。
2. `check_code_pagination` 在上面的失败分支前加一个判断：本页块上方有内容（已有的 `leading`）且 `_code_follows_heading` 为真时，改记放宽项，`review=True`，写明块号、所在页、前页尾部剩余空间；否则照旧判 `code-page-gap`。

标题紧挨代码块、块上方本页又有内容，就说明标题与代码块同页：两者之间没有别的元素，块上方的内容只能是这个标题。“放不下才移页”的现有分支（记不交复核的放宽项）不变。

### 5.3 验收

cuSPARSE 对应页通过并登记放宽项；把标题换成普通段落的同构样本仍报 `code-page-gap`。

## 6. R6 链接断行与带链接图片的分页

### 6.1 现状（`assets/pdf/style.css`，现有代码）

```css
p:has(> img) { break-after: avoid-page; }                      /* :54 */
p:has(> img) + p { break-inside: avoid; }                      /* :55 */
p:has(> img) + .anchor-only + p { break-inside: avoid; }       /* :56 */
a { color: #0b5394; text-decoration: none; word-break: break-all; }   /* :61 */
.table-number a { word-break: normal; }                        /* :127 */
```

### 6.2 改动

1. `:61` 的 `word-break: break-all` 改为 `overflow-wrap: anywhere`：先按正常词边界断行，只有一个词单独放一行也放不下时才在词内断开，长 URL 仍不溢出。`:127` 相应改为 `.table-number a { overflow-wrap: normal; }`：`a` 不再设 `word-break`，表格里的数字要防的变成 `a` 自己的 `overflow-wrap: anywhere`。
2. `:54`–`:56` 三条规则都加上带链接图片的写法 `p:has(> a > img)`，与不带链接的图片受同一约束。共享安装的就地补丁只加了 `break-after`，且限定 `a[href^="images/"]`；本设计三条都补，不限定链接目标。

共享安装里另一条就地补丁 `table { table-layout: fixed; }` 处理的是超宽表撑破版心后整页缩印。仓库已用单元格的 `overflow-wrap: anywhere`（`style.css:121`，注释记的就是这本书的复现）处理，不带回，重装后实测确认。

### 6.3 验收

DIN 四处引文标签和 CUDA PG 第 121 页的英文链接不再拆词；含长 URL 的样本不溢出；CUDA PG 图 42 与图注同页（在 §15 的迁移副本上导出），另做一个“带链接图片 + 图注落在页尾”的最小样本。

## 7. R7 列表圆点与题注转义

### 7.1 现状（`_latexml_source.py:768`–`:771`，现有代码）

```python
        for label in body.find_all(class_='ltx_tag_item', recursive=False):
            if label.get_text(strip=True) in ('(%d)' % number, '%d.' % number,
                                              '%d)' % number, str(number)):
                label.extract()
```

只去掉与序号相同的有序列表标签；无序列表的 `•` 留在条目文字里，Markdown 变成 `- • `，PDF 出现双圆点。

### 7.2 改动

1. `enumerate_items`（`_latexml_source.py:746`）：无序列表的标签文字是 LaTeX 默认的 itemize 标记（第 1–4 层依次为 `•`、`–`、`∗`、`·`）时去掉；`\item[自定义标签]` 的标签保留。写出与独立读取消费的都是 `enumerate_items` 的结果（函数文档 `:747`），两侧一致。
2. `references/translation_conventions.md:15` 之后加一条：双语题注回显用 `**…**` 包裹时，英文回显里的 `*`、`^`、`_` 写成 `\*`、`\^`、`\_`，否则会与外层强调配对（E1 H.5 的 `r_\*`）。

### 7.3 验收

Hiformer 的 11 行列表重新解析后没有 `•`，源对账通过；含 `r_\*` 的加粗题注在 PDF 中强调完整。

## 8. R8 图片适配声明

### 8.1 方案比较

| 方案 | 做法 | 结论 |
| --- | --- | --- |
| A 导出时适配 | 声明只作导出输入：显示宽度覆盖到逐出现的尺寸绑定上，SVG 在已有的离线派生（`render_svg_payload`）里改 viewBox 后渲染；交付图片、源快照、注册表都不动 | 采用 |
| B 重放核对 | 交付图片换成裁剪后的字节；所有“交付图片对源资源”的身份核对改为把声明重新作用到原图、逐字节相同才接受（2026-11-17 对话时的推荐） | 拒绝：各家族的译文核验、显示尺寸绑定和交付身份都要加钩子 |
| C 两侧同步 | MTGR 的做法：交付图片与源快照都改字节，再改注册表、重建记录 | 拒绝：改了源证据，还原要重新下载 |

选 A 的依据：MTGR 的问题只出在 PDF 版面（图组整体跳页，留下近空白页），阅读版不需要裁剪；导出器已经在离线浏览器里把绑定了显示宽度的 SVG 渲染成 PNG 再嵌入（`export_pdf.py:4636`–`:4655`），核验侧也按同一绑定重渲染并逐次比对像素（`verify_pdf.py:965`），裁剪只要在这一步改 viewBox。

### 8.2 声明文件

项目级 `image_adaptations.json`，放在项目里，导出时显式传入：

```json
{"version": 1,
 "images": [{"image": "images/GR-workflow.svg",
             "sha256": "<当前文件的摘要>",
             "viewbox": "0 40 960 520",
             "display_width_px": 300,
             "basis": "2026-11-13 用户批准：裁去框内顶部空白，图 2 与题注回到第 6 页"}]}
```

- `image` 相对声明文件所在目录；`sha256` 必须等于当前文件，图片一换声明即失效。
- `viewbox` 只用于 SVG，且必须落在原 viewBox 之内（只能裁，不能扩）；位图带 `viewbox` 报“位图裁剪不支持”。
- `display_width_px` 大于 0，不超过版心宽（`export_pdf.py:80` 的 `CONTENT_WIDTH_PX`）。
- `viewbox` 与 `display_width_px` 至少一项；`basis` 必填。
- 一条声明作用于该图片的全部出现，每次出现都必须已有显示尺寸绑定（`images_display` 条目），否则报错。

### 8.3 改动

1. `export_pdf.py` 新增参数 `--image-adaptations <json>` 和加载函数 `load_image_adaptations(path, chapters)`，按 §8.2 校验。`load_display_maps`（`:100`）加可选参数 `adaptations`：在返回的逐出现绑定上，把声明图片的显示宽度改为 `display_width_px`，并附上 `viewbox`。
2. `svg_print_dimensions`（`:3618`）在绑定带 `viewbox` 时，用它的宽高比和宽度代替 `_svg_intrinsic_ratio` 的结果；`render_svg_payload`（`:3650`）的页面脚本现在只在缺 viewBox 时补设（`:3687`），改为有声明时设为声明值。派生证据（`svg_renders` 的行）加 `adaptation` 字段。文件字节不变，所以 `source` 身份核对（`:4646`）不变。
3. 导出报告写入 `image_adaptations`：声明文件路径、sha256 和内容。
4. `verify_pdf.py` 不加参数：从导出报告读声明路径，重读文件并核对 sha256 与报告一致，用同一个 `load_image_adaptations` 校验后，传给两处 `load_display_maps`（`:970`、`:5592`）。文件在导出后被改或校验不过，报 `image-adaptations-mismatch`。
5. `verify_delivery._check_facts` 的 verify_pdf 分支把声明文件加进 `files`（与导出报告同样处理）：声明一改，交付身份和复核绑定随之失效。
6. `references/images_display.md` 的“SVG 打印负载”一节写明声明格式与用法。

还原：删掉这条声明，重新导出、核验、复核。交付图片从未改动。

### 8.4 验收

MTGR：先按外部文件记录取回 `GR-workflow.svg` 的原字节，写一条声明（方案 A 的 viewBox 与 300px）后导出，`verify_pdf` 与 `verify_delivery` 通过，第 6 页不再大片空白；删掉声明重导出后版面回到原样，`images/` 与原字节一致。损伤样本：声明的 sha256 不符、viewBox 超出原范围、位图带 viewBox、导出后改动声明文件，分别失败。

## 9. R10 检查器变化后的恢复

### 9.1 恢复顺序（`references/workflow_helpers.md`）

在“单记录翻译与 PDF 交付”一节之后加“检查器变化后的恢复”。检查器（组件脚本）变化会同时让记录里的复核绑定和导出报告里的依赖摘要失效，只重建一边不会通过。顺序与各步的检查点（E2 §2.1 在 J 上验证过这条路径）：

1. 记录临时改为 `translation` 模式（去掉 PDF 输出与 verify_pdf 检查，原记录另存）：PDF 一侧的旧导出证据已经失效，`translation+pdf` 模式下准备候选会先在 verify_pdf 复验上失败。用 `verify_delivery --prepare-reviews` 取当前绑定，按当前检查实际重核，重新登记 source-reconcile 与 semantic 复核。检查点：带 `--translation-record` 的导出能通过就绪检查。
2. 导出到新临时目录，把报告复制到持久目录，运行 `verify_pdf`。检查点：`verify_pdf` 没有失败项。
3. 记录改回 `translation+pdf`，再用 `--prepare-reviews` 取视觉与链接复核的当前绑定；成品像素不变时按显式视觉复用登记 `reused`。检查点：候选里没有缺绑定的条目。
4. `verify_delivery --evidence-dir` 发布。检查点：输出“交付检查通过”。

### 9.2 身份变化报错（`verify_delivery.py`）

`_prepare_reviews`（`:4013`–`:4014`，现有代码）：

```python
    if compute_delivery_identity(root, record, checked["entries"]) != identity:
        raise DeliveryError("候选准备期间依赖身份变化，请重核当前输入")
```

新增 `_identity_changes(before, after)`：列出取值不同的顶层键，并在嵌套结构里找出摘要变了的 `[路径, 摘要]` 对。这里和 `publish_evidence`（`:3559`–`:3564`，现在只列键）都改用它，报错写成“依赖身份在运行期间变化：<键>；变化的文件：<至多 5 个路径>”。不判断是不是首跑。

### 9.3 验收

在改过检查器的项目副本上按文档一次恢复成功。在 STCA 副本上复现首跑报错：能复现时，按报错列出的文件定位来源并消除；不能复现时记为待定位，不改为常规重跑两次。

## 10. R11 数字复核候选的稳定定位键

### 10.1 机制重审

数字差异 ID 写进交付记录的 `reviews[].items`（`verify_delivery.py:2563`）和包证据的 `diff_ids`（`_numeric_review.py:548`），改写法属于持久记录契约变化。

| 方案 | 做法 | 结论 |
| --- | --- | --- |
| A 改 ID 写法 | ID 去掉行号，用数值加前后文定位；行号只在提示文字里显示 | 采用：只改生成 ID 的一处，所有比对逻辑不变 |
| B 保留行号 ID，另加映射 | `--prepare-reviews` 按前后文把旧 ID 映射到新 ID | 拒绝：多一套映射，映射本身也要能核对 |
| C 不改 | 格式修复后整列重锚 | 拒绝：就是 HSTU 的 115/165 返工 |

### 10.2 改动

1. `diff_numeric_tokens`（`_numeric_review.py:446`–`:448`，现有代码）：

   ```python
               diff_id = 'NUM[%s][%s]#%d %s @%s:L%d' % (
                   scope, role, occurrence[raw], raw,
                   token['label'], token['line'])
   ```

   改为 `NUM[scope][role] raw @label ‹前 6 字|后 6 字›#k`。前后文取自去掉 HTML 标签（锚点、分页 div）、并把连续空白（含换行）归一为一个空格后的全文；`k` 在角色、原值、前后文都相同的差异里按出现顺序编号。`extract_numeric_tokens` 扫描时为每个 token 记下前后文；行号移到 `format_diff_hint`（`:571`）的提示文字里。
2. `_prepare_reviews`（`verify_delivery.py:3965`）：当前没有可沿用的闭合复核时，找同一 kind、同一 target 最近一次闭合的复核，把当前 `items` 分成“与该复核相同”和“新增”两组；`main` 在现有数字候选汇总（`:4083`–`:4089`）之后打印两组的数目和新增项的 ID。候选的 `items` 仍列出全部当前项。
3. `references/numeric_review.md` 写明：格式修改后重新准备候选，只需判读新增项，再按原流程重新闭合。

内容没变的数字项 ID 不变，旧结论随 ID 沿用；数字本身或前后 6 字内的文字变了就是新 ID，不继承旧结论。限制：数字旁边的文字被改写时，即使数字没错也会作为新增项重审。

### 10.3 验收

HSTU 格式修复前后两版之间只剩真实新增或变化的数字项待审（找不到修复前的版本时，在副本上做同类修改：拆段、移锚点、加分页 div）；把一个数字改错后，该项作为新增项出现。

## 11. R12 交付文书统计段与严格参数前置比对

### 11.1 统计段渲染（新增 `scripts/render_delivery_notes.py`）

命令：`render_delivery_notes.py --record <交付记录> --kind <visual|link|delivery|files> [--evidence-dir <目录>] --output <路径>`。只读记录与证据，不改记录。

| kind | 读取 | 渲染内容 |
| --- | --- | --- |
| `visual` | 记录里 verify_pdf 检查的 `--work-dir` 下的 `verify_report.json` 与 `export_report.json` | 页数；放宽项与待复核项按 code 计数；图片恢复与未恢复的数目及原因；KaTeX 宏表；图片适配声明（R8）；报告有 `visual_aid` 时写 §12 的程序化目检段 |
| `link` | 同上 | 内部链接注解数、外部链接数、范围外链接按处置分组 |
| `delivery` | 记录与 `--evidence-dir` 下的 `delivery_index.json` | 输入顺序、输出路径与 sha256、各检查及退出码、各复核的状态与项数、依赖版本 |
| `files` | 记录的 `sources[].snapshots` 及其资源、`outputs` | JSON 清单（路径、sha256、字节数），供并入知识库的外部文件记录 |

- 需要人判断的位置写占位 `〔待补：…〕`，例如“〔待补：视觉检查结论〕”“〔待补：例外与未解决项〕”。
- `--output` 落在交付根一级时，文件名必须是 `verify_delivery.py:130` 的两份用户说明之一，且记录的 `files` 已把它登记为 `user-note`；否则拒绝写入，并打印要加进记录的 JSON 片段。
- 不生成 `00_目录.md`（`build_toc.py` 已有）。

### 11.2 严格参数前置比对（`export_pdf.py`）

核验侧在导出之后才比对（`verify_pdf.py:5614`–`:5621`，现有代码）：

```python
    exported_require = bool(report.get("require_display_map"))
    if exported_require != bool(args.require_display_map):
        failures.append(
            {
                "code": "images-display-require-mismatch",
```

改动：导出带 `--translation-record` 且就绪检查通过后（`export_pdf.py:4239` 之后），在记录的 checks 里找 `--pdf` 指向本次 `--output` 的 verify_pdf 检查，用 `verify_delivery._parse_tool_args` 解析它的参数，与本次导出参数逐项比对：`--require-display-map`、`--toc-sections`、`--images-display`、`--provenance`、`--view-declaration`、`--unlink-target`、`--navigation-record` 与 `--site-root`（路径按交付根规范化）。不一致时在渲染前失败，逐项列出记录值与本次值。记录里没有对应的 verify_pdf 检查时不比对。

限制：按现行流程，首次导出时记录里还没有 verify_pdf 检查（`workflow_helpers.md:30`），所以本条只保护重导出。J 漏传 `--require-display-map` 发生在首次导出，本条覆盖不到；首次导出仍依赖 `references/` 的命令示例写全参数。

### 11.3 占位阻止闭合（`verify_delivery.py`）

`check_reviews`（`:3206`–`:3207`，现有代码）只要求备注非空：

```python
        if not (review.get("note") or "").strip():
            problems.append("复核 %r 缺少实际记录内容（note 为空）" % review.get("target"))
```

增加：备注含 `〔待补` 时报“复核 %r 的备注仍有待补项”；交付根登记为 `user-note` 的说明文件含 `〔待补` 时同样报错。

### 11.4 验收

ULTRA-HSTU 与 CUDA PG 渲染出的数字与记录、报告逐项一致（含链接注解数和放宽项数）；交付根未登记的说明被拒并给出片段；记录登记了 `--require-display-map` 时，漏传该参数的重导出在渲染前失败、不产出候选；备注留有占位时交付校验不通过。

## 12. R13 无图像时的程序化目检

### 12.1 两档视觉复核

- 全页目检：现行合同不变。
- 程序化目检：只在会话和子代理都不能读图时使用。最少检查集全部完成后，把关键页清单交给用户；用户抽查后，把用户的结论写进复核备注，才能登记 `closed`。写入之前视觉复核保持 `pending`，交付校验按现有门禁不放行（`verify_delivery.py:3198`）。

### 12.2 最少检查集与关键页（`verify_pdf.py`）

`--visual-aid`（`collect_visual_aid`，`:184`）现在逐页给出渲染结果、墨迹覆盖率和疑似空白页。增加：

1. 页脚页码：用同一渲染器取页面底部边距带内的文字，应等于“页码 / 总页数”（`export_pdf.py:3980` 的页脚模板）；不符的页列为异常。
2. 关键页清单：在辅助统计入口（`:5732`）汇总，写入报告的 `visual_aid.key_pages`，每页附原因。包括首页、目录（`00_目录.md` 这一输入）所在页、各章首页（都来自 `chapter_bounds`）、末页、带页码的放宽项与待复核项所在页、疑似空白页、页脚异常页、渲染失败页。
3. 检查器已经算出页码的放宽项加 `page` 字段（R1 两段切分、R2 页文本回退、R4 标题粘连、代码块待复核）；其余项没有页码，在备注里按 items 列出，由用户按项抽查。

版心溢出不另查：导出的浏览器检查有溢出即不打印（`export_pdf.py:4670`），机器核验通过已包含这一项。

### 12.3 备注格式与核对（`render_delivery_notes.py --kind visual`、`verify_delivery.py`）

渲染出的备注以固定标注词开头：

```text
【程序化目检】会话与子代理均无读图能力，未做逐页人眼目检。
最少检查：<N> 页渲染成功；疑似空白页 <页码或“无”>；页脚页码 <“1/N 至 N/N 连续”或异常页>；导出与 PDF 机器核验通过。
关键页：p1（首页）、p2–p3（目录）……（每页附原因）
用户抽查：〔待补：用户抽查的页码、日期与结论〕
```

`check_reviews` 对以“【程序化目检】”开头的 visual 复核加两条核对：

- 绑定的 verify_pdf 检查带 `--visual-aid`。`_check_facts` 只在启用时写 `params.visual_aid = True`，与 `numeric_review`（`:2363`–`:2364`）同样处理，没启用的检查身份不变。
- 备注有非空的“用户抽查：”行。占位没替换时按 §11.3 拒绝。

工具只能确认抽查结论已经写入，确认不了用户真的看过；`SKILL.md` 写明这一行只能填用户实际回复的结论。

| 方案 | 结论 |
| --- | --- |
| 记录加结构化字段（如 `programmatic: {key_pages, user_check}`） | 拒绝：视觉复核已绑定 PDF 摘要，PDF 一变复核就失效，关键页随之重算，字段核对不增加保障，还要改记录格式 |
| 备注固定标注词加占位 | 采用：复用现有 note，只加文字核对 |

### 12.4 文档

改写 `SKILL.md:32` 与 `references/pdf_export.md:131`、`:242`、`:251`：写两档复核，以及程序化目检的步骤（带 `--visual-aid` 运行 verify_pdf → 渲染备注 → 把关键页交给用户 → 写入用户结论 → 登记 `closed`）。修改 `SKILL.md` 前按 AGENTS.md 读取 `writing-for-agents`。

### 12.5 验收

无图像会话在 HSTU 上产出上面格式的复核备注，最少检查的结果与 `verify_report.json` 一致；“用户抽查”一行还是占位时交付校验不通过；没带 `--visual-aid` 却写“【程序化目检】”时交付校验不通过。

## 13. R14 清理顺序与清理后核对

### 13.1 清理顺序（`references/cleanup.md`）

组件规则保留成品 PDF 与源快照（`cleanup.md:16`–`:17`）。知识库规则在交付验收之后删除源网页下载和已发布的 PDF（知识库 `AGENTS.md:17`、`:22`），而知识库的交付验收包含组件的清理与清理后验收（`AGENTS.md:15`），两者先后本不冲突。cuSPARSE 出问题，是把“删网页下载”提前到了组件清理里。

`cleanup.md` 资产保护表之后加一条：交付记录 `sources[].snapshots` 绑定的快照及其资源，在组件的清理后验收完成前一律保留；项目规则要删的源网页下载与成品，排在清理后验收之后，删除后用 §13.2 复核。

### 13.2 清理后核对（`verify_delivery.py --after-cleanup`）

命令：`verify_delivery.py --record <记录> --evidence-dir <证据目录> --after-cleanup [--published-root <目录> ...]`。只读，不复跑检查，不发布。单独给 `--published-root`（不带 `--after-cleanup`）报参数错误，退出码 2。

1. 证据索引与记录一致：`delivery_index.json` 的 inputs、outputs（路径与 sha256）、reviews 与记录相同；索引引用的批次文件存在，sha256 与索引一致。
2. 仍在交付根的输入、输出、目录与术语表，摘要等于索引 `identity` 里记录的值。
3. 不在交付根的输入与输出，必须能在某个 `--published-root` 的同一相对路径找到，sha256 与记录一致。
4. 不在场的源快照与资源只列出，不判失败（记录与索引保留了它们的摘要）。

全部通过时打印“清理后核对通过”，并按“在场一致”“发布副本一致”“已删除、只存摘要”三类列出文件。

### 13.3 验收

cuSPARSE 同构副本按新顺序清理，绑定的快照资源保留，重导出验收通过；MTGR 副本按知识库规则删除源快照与 PDF 后，`--after-cleanup` 通过；改动一份发布副本或证据批次文件时失败。

## 14. 第 1 批遗留

### 14.1 R9 全绿复跑输出一屏（`verify_reference_translation.py`）

ULTRA-HSTU 全绿复跑打印 115 行：116 条告警归成 44 类，其中 76 行是数字提示。`verify` 启用数字辅助时（`:408`–`:425`）逐项追加提示，`main` 在告警多于 10 条时调 `summarize_messages`（`:505`–`:507`，现有代码）：

```python
    elif warns:
        print('   ⚠ ' + summarize_messages(warns).replace('\n', '\n     '))
        print('   （逐条告警加 --verbose）')
```

改动：

1. `verify` 启用数字辅助时多加一条汇总告警：“数字提示：共 N 处待复核（管理字段 a、标题或交叉引用 b、数量级或单位 c、其余 d），逐项见 `verify_delivery --prepare-reviews` 候选”，分类用 `group_numeric_diffs`（`_numeric_review.py:517`）。
2. `main` 的汇总分支先去掉逐项数字提示（以“数字提示 NUM[”开头的行），再对其余告警调 `summarize_messages`；`--verbose` 时照旧逐条打印。

验收：ULTRA-HSTU 全绿复跑输出不超过 40 行。

### 14.2 R3 脚注与表格单元格锚点

- `tests/test_latexml_anchor_writing.py` 补两个用例：链接目标在表格单元格内（`_table_anchor_holders`、`_restore_table_anchors`，`_latexml_source.py:1855`、`:1870`）；链接目标在脚注定义体内。各配损伤样本（删锚点、把锚点挪进别的锚点所在块）。
- 真实样本：脚注用 DIN；表格单元格目标在实施时从已有论文项目里找，找不到时以单元测试为准，并在验收结论里写明。

## 15. 验收环境与测试

- 各节的验收用原项目的真实片段，合法与损伤样本成对；样本、报告和截图写在 Git 工作区外。
- CUDA PG：仓库代码过不了现有产物的准入（§4.6）。在工作区副本上按 CHANGELOG V1.7“兼容性”一条迁移：受影响源页用新版重新解析，在对应译文的引用块前补锚点。然后跑 R15 与 R6 的验收；`verify_delivery` 在改动前后各跑一次，比对结果（改动前一次约 1 小时 45 分钟，在后台运行）。迁移中出现与本批无关的失败时如实报告，不用分段计时代替整体验收。
- 每项改动配单元测试；全量回归的失败集合与改动前相同（已知预存失败见第 1 批需求 §7）。

## 16. 不做的事

- 不做增量校验，不跨阶段缓存准入结果（§4.6）。
- 不修改交付图片和源快照来适配版面，不支持位图裁剪（§8）。
- 不自动修改交付记录（§11.1）。
- 不给记录加程序化目检的结构化字段（§12.3）。
- 清理后核对不复跑检查，不替代交付校验（§13.2）。
- 不改图片显示宽度和图锚写法（§19.2）。
- 不按文字内容猜测普通段落是不是图题，不拆分图片与图题写在同一段的段落（§19.4）。
- 绑定了显示宽度的 SVG 不改为矢量嵌入，倍数不做成导出参数或逐图声明（§20.2）。

## 17. Karpathy 精简与自检

1. **基线**：读过需求、第 1 批设计、11-14 与 11-07 设计的相关节，以及 §3.1 所列源码；W1 终版、E1–E3 的对应条目；CUDA PG 的交付记录、阶段日志、项目包装脚本与补丁，MTGR 的记录构建脚本，知识库 `AGENTS.md`。设计期剖析 P0–P5 见 §4.1。R17 读过 `style.css`、导出器写图片宽度处与 `verify_pdf._destination_matches`，统计了 637 份 Markdown 里的图片位置，在工作区外做了原型（§19.1、§19.2）。D4 读过建 soup 时标出独立锚点段的循环（`export_pdf.py:2923`–`:2936`）和翻译约定的图题写法，按导出器同样的 Markdown 解析统计了图片之后的段落；R18 读过 `svg_print_dimensions`、`render_svg_payload`、`plan_svg_renders`、导出时的嵌入处、`verify_pdf.check_svg_renders` 和 `references/images_display.md` 的“SVG 打印负载”，统计了 21 份导出报告里的 SVG 派生位图。两项都在工作区外的 HSTU、AutoInt、Hiformer、MTGR、ULTRA-HSTU 副本与 CUDA PG cuda-graphs 页副本上做了原型（§19.4、§20）。四处改动（§18.2 第 12 条、§4.4 第 4 条、§21、§22）另读过 `enumerate_items`、`_latexml_src_stream`、`_reconcile_latexml_core`、`reconcile_latexml_to_markdown`、`verify_delivery.progress_stage`、`verify_pdf` 的外链注解比较处与共享安装同处修改、`split_work_packages.py` 的包头写入与 `merge_work_packages.py`、`recover_work_packages.py` 的源路径比对，以及 HSTU 知识库 `source/source.md:574` 等旧解析稿样本。
2. **假设与差异**：§3.2 列出与需求的差异和处理。会改变的行为：R4 部分 `code-page-gap` 改记放宽项；R6 改变链接断行；R7 重新解析后列表不再有圆点；R11 数字 ID 换写法，存量项目要重新闭合一次；R12 记录登记了严格参数时导出前就失败，含占位的备注被拒；R13 写“【程序化目检】”的备注要满足两条核对；R15 导航准入失败改由章节检查报出；R17 单独成段的图片居中，紧跟图片的单行图题与子图题随之居中（D4），图片与图题写在同一段时整段居中（已导出 PDF 的项目里只有 cuBLASXt 1 处）；R18 SVG 派生位图至少 2 倍显示宽度的像素（D5）、PDF 变大（HSTU +10.2%），没有倍数记录的旧报告按 1 倍核验；旧解析稿对账按现行读法不一致时按 R7 之前的读法整篇重比，混合写法被拒；`progress_stage` 运行期间每 60 秒补一条 `running`；外链核验把裸域名补的尾斜杠视为同一地址；工作包合并按真实路径认同一源文件，同一文件经符号链接或物理路径给出都算同源（§22）；单独给 `--published-root` 报参数错误（§13.2）。§4.5 的耗时是估算，以实测为准。
3. **最小方案**：
   - R15 只改调用方式：表格解析提到循环外，取事实时不做准入、同一次计算内共用；两条缺一不可（§4.6），拒绝跨阶段缓存与单章准入。
   - R8 复用已有的 SVG 派生，在导出时适配，拒绝改字节的两种做法（§8.1）。
   - R11 只改生成 ID 的一处（§10.1）。
   - R12 渲染只读记录与报告；严格参数比对复用 `_parse_tool_args`；一条占位规则同时服务 R12 与 R13。
   - R13 复用现有 note 与 `--visual-aid`，不加记录字段（§12.3）。
   - R14 的清理后核对只读索引与记录，不复跑。
   - R17 一条样式规则加一处核验规则；只加样式会让图前独立锚点的链接在导出时失败，改锚点写法要迁移全部已有译文（§19.2）。
   - D4 一条样式规则加一个导出器标注函数，核验不改：图题段首的行内锚点随文字一起移动，图片与图题之间隔着独立锚点段的情形在语料里没有（§19.4）。
   - R18 只改派生尺寸的计算并把倍数写进导出报告，渲染函数、证据字段和缓存键都不变；按目标像素取下限会让 HSTU 5 页的图片高度变化 0.7–0.8pt，用浏览器的设备像素比会让本来已够密的图再翻倍，矢量嵌入要重做宽度量测与像素证据，统一缩小显示宽度不提高清晰度（§20.2）。
   - 旧解析稿兼容不按文字剥除行首标记，改为旧读法整篇比对（用户 2026-11-18 选定，只在对账入口加一次重比；补文字规则分不清行中 `–` 是子列表标记还是原文破折号，原文破折号被删改会查不出，要求重新解析则要手工迁移译文）；R15 心跳只改 `progress_stage` 一处（拒绝拆 verify_pdf 内部进度与放宽阈值）；R19 把等价比较合入 `verify_pdf` 一处（拒绝项目级包装与导出时改写 href）；R20 只改合并的源路径比对一处（拒绝改包头写入与要求不经符号链接，§22.3）。
   - 没有比这更简单又满足需求的做法：R15 只改一条达不到 20 分钟；R11 不改 ID 就免不了整列重锚；R8 不加声明入口就还得手改注册表。
4. **删除审计**：每节对应一条需求。写作中删去了增量校验、自动登记说明文件、程序化目检的结构化字段、位图裁剪、外部文件记录的全量渲染（来源地址、版本、下载命令）、`00_目录.md` 生成，以及“首次导出前预登记 verify_pdf 检查”的流程调整（`translation` 模式会因没有绑定输出而拒绝该检查，要改交付校验的模式语义，收益只是首次导出）；R17 不给图片段加 class（`:has()` 已够用）；D4 删去了直接给“图片段后一段”加样式、独立锚点段之后的图题判定及其核验放宽、表题与算法题标号（紧跟图片的 0 处）；R18 删去了可配置倍数、逐图声明倍数、矢量嵌入与统一缩小显示宽度；验收只写在各节，§15 只写环境与回归，不重复列表。旧解析稿兼容不按文字剥除行首标记，改为旧读法整篇比对；不拆 verify_pdf 内部进度、不放宽 R15 阈值、不给导出加参数、不改 PDF 里的链接内容；R20 不改拆包包头写入，不新增路径表示约定。
5. **直接验收**：各节验收用原项目样本证明用户看得到的结果：CUDA PG 交付校验单次不超过 20 分钟且结果相同、MTGR 一条声明完成适配并可还原、HSTU 格式修复后只审新增项、渲染的数字与报告一致、用户没抽查就不能闭合、清理后仍能验收、每张图和一行放得下的图题偏离版心中线不超过 1pt 且内部链接照常通过、HSTU 图 3 为 858×986 px（2 倍）且每张图的位置与尺寸不变、旧的 1 倍导出照常核验；损伤样本证明检出能力没有变弱。直接验收（§18.1、§18.2 第 12 条、§21.4、§22.5）：知识库 DLRS 下现存的 12 篇旧解析稿对账与 HSTU 拆包、三个等长损伤各报 1 处差异指向被改条目；CUDA PG 四步恢复到达“交付检查通过”，总耗时 723.78 秒、相邻行最大间隔 60.06 秒；漏传 `--toc-sections` 渲染前被拒、work-dir 无候选 PDF、成品 sha256 不变；cuSPARSE/DIN 带 `--translation-record` 重导出核验 0 失败；HSTU 三版译文 CLI 对照“相同 165 项、新增 0 项/新增 2 项”；R19 重导出 262 页 0 失败、`https://fmt.dev` 尾斜杠外链消掉；R20 同一源文件经符号链接路径合并通过、内容相同的另一个文件仍报“异源包”；HSTU 关键页经用户 2026-11-19 抽查通过（p1、p35）后视觉复核闭合（§18.1 R13）。

## 18. 最终实施验收（2026-11-18）

第 2 批实施（tickets 01–10）于 2026-11-18 完成真实样本验收，知识库与工作区原件只读，验收全部在工作区外的副本上做。逐项结论与关键数字如下；摘要并见[需求 §7](./2026-11-16-paper-pdf-delivery-backlog-requirements.md)，最终行为见[CHANGELOG“未发布”](../CHANGELOG.md)。R17–R20 的实施与验收另见 §19–§22。

### 18.1 逐项结论

- **R15（§4）**：CUDA PG 13.5 迁移副本单次交付校验 11:11.87（BASE 1:48:41，约 9.7 倍，达“不超过 20 分钟”），两次均“交付检查通过”，输入、输出、复核对象与结论一致，差异仅检查器脚本摘要与批次目录名。verify_api_translation 各章 42–53 秒（BASE 各约 220–230 秒），publish 23.67 秒（BASE 1,508.33 秒）。带长阶段心跳的现行代码在同一副本完成四步恢复后，交付校验「交付检查通过」（exit 0），总耗时 723.78 秒（12 分 04 秒，不超过 20 分钟；改动前同一副本 1 小时 48 分 41 秒）；stderr 相邻两行最大间隔 60.06 秒（约 60 秒，不超过 5 分钟），`verify_pdf #7` 阶段全长 357.27 秒、每 60 秒输出一条 `running` 心跳（共 5 条），导出与独立核验侧同样有心跳（导出 11 条、核验 10 条 `running` 行）。cuSPARSE 原始快照全文对账 21.76 秒（项目规范化快照 10.51 秒的 2.07 倍，≤3×），剥骨架后解析与项目既有解析稿正文 9,239 行逐行相同、表格 4,435 格逐格相同，差异仅 2 处自引用链接形态与表格呈现形态两类已知项。
- **R4（§5）**：cuSPARSE 带 `--translation-record` 重导出通过就绪检查与机器检查（262 页、核验 0 失败），`code-page-gap` 0 项；两条“节标题 + 长签名块”整体移页记 `review:true` 放宽并带页码（p187、p190）；在标题与块之间插入普通段落（取消粘连）后放宽 2→0，证实放宽确由标题粘连触发；“无标题粘连且放得下仍 FAIL”由真实 Chromium 集成用例 `test_forced_long_block_move_blocked_before_replacing_output`（rc=1、旧成品不变）钉住。
- **R6（§6）**：DIN 带 `--translation-record` 重导出与核验通过（15 页、0 失败）；三类引文标签（Covington et al.、He and McAuley、Maaten and Hinton，共 12 处）全部无词内拆分，断行只落在词边界；200 字符无空格 URL 两行在版心内断开、无溢出；CUDA PG 第 121 页 19 个英文行尾均为完整词，全文档仅 6 处锚文本跨行且断点均在空白处（改动前的备份 PDF 同为 6 处无拆词）；图 42（第 249 页，链接包裹图片形态）与图注同页；两臂最小样本证明旧 CSS 下图片与图注分离、新 CSS 下同页。
- **R7（§7）**：Hiformer 重解析含 `•` 行 11→0（退出码 0、“LaTeXML 来源适配 354 对应”、内置独立对账通过），正文里的 `–`、`∗` 未误剥；题注转义在真实 PDF 上验证——写 `r_\*` 保星号且整行加粗（题注行与正文字体对象分立佐证），不转义丢 2 个 `*` 且英文回显中段变斜体。旧解析稿兼容（§18.2 第 12 条）实测：知识库 DLRS 下现存的 12 篇旧解析稿中快照在的 6 篇对账 0 差异（HSTU 由 1 变 0）、快照不在的 6 篇记「快照不在，未验证」；HSTU 副本拆包由拒绝（exit 1、指向 L574 行中 `–`）变为退出 0（17 个工作包）；三个等长损伤（`randomly`→`randomlx`、原文 `–`→`-`、行中子列表标记 `–`→`-`）各报 1 处差异且指向被改条目。
- **R8（§8）**：MTGR 一条声明（viewBox `16.2 103.6 661.8 936.1`、`display_width_px` 300、依据“2026-11-13 用户批准方案 A”）完成适配：总页数 15、第 6 页图 2 与题注同页（225×319pt），`verify_pdf` 与 `verify_delivery --prepare-reviews` 通过，声明进入导出报告与交付身份；删声明重导出还原 16 页、第 6 页恢复近空白、SVG 原字节逐字节相同；4 项损伤样本（sha256 改错一位、viewbox 越界、位图裁剪、导出后改声明）全部按预期失败。
- **R10（§9）**：身份变化报错列出变化的身份键和文件（三具名风险实测通过）；STCA 副本头两次 `--prepare-reviews` 都在硬检查阶段失败，没有走到身份比对；用第 2 批的代码，STCA、CUDA PG、cuSPARSE、DIN 与两份 HSTU 共 6 个副本上第一次走到身份比对的 `--prepare-reviews` 都通过，没有出现身份变化报错；根因未定位，记“待定位”；STCA 副本按 `workflow_helpers.md` 四步恢复依次到达各步检查点、第 4 步输出“交付检查通过”；CUDA PG 13.5 副本四步恢复同样依次到达全部检查点（R15 的计时跑），HSTU（R11）与 cuSPARSE、DIN（R4/R6）的记录按同一顺序完成第 1 步。
- **R11（§10）**：HSTU 真实副本 CLI 对照（`verify_delivery --prepare-reviews`）：知识库绝对路径改写为副本路径后源链硬检查通过；A 版（原样）产出 165 项数字候选（same_value_unit 52、other 36、management 34、cross_reference 43）并登记闭合；B 版（只改格式：拆段、分页 div、锚点并段）stderr「复核对照 semantic HSTU_中文译文.md：与上次闭合复核相同 165 项，新增 0 项」；C 版（把 §4.2 一句中的 15.2 改成 15.3）「新增 2 项」且都在被改错的句内（被改值本身与 6 字窗口内邻居），与模块层结果逐字一致；同一改动在旧写法（ID 含行号）下 66 项失效作对照。
- **R12（§11）**：ULTRA-HSTU visual/link/delivery 三段与 CUDA PG visual/link 的渲染数字与导出/核验报告、证据索引逐项一致；未登记的用户说明被拒（退出 1、不生成文件、打印要补的记录片段）；记录绑定的报告过期时渲染器拒绝（防过期守卫在真实样本上生效）；CUDA PG 13.5 副本（记录已登记 verify_pdf 检查）漏传 `--toc-sections` 的带 `--translation-record` 重导出在渲染前失败，stderr 逐字「FAIL: 导出参数与交付记录的 verify_pdf 检查不一致：--toc-sections：记录 启用 / 本次 未启用（本次导出停止，旧成品不变）」，work-dir 无候选 PDF、成品 sha256 前后不变；含 `〔待补` 的复核备注与用户说明使交付校验失败，两条占位问题同列。
- **R13（§12）**：HSTU 程序化目检备注与核验报告 `visual_aid` 逐项一致（35 页全部渲染、疑似空白页无、页脚 1/35–35/35 连续、关键页 p1/p35）；CUDA PG 650 页 16 条关键页（含 8 条 `code-page-gap-review` 的页码）与备注一致。两条否定核对——“用户抽查”留占位、检查未带 `--visual-aid`——都被交付校验拒绝。最终代码重导出的 HSTU 副本（35 页，关键页 p1、p35，核验 0 失败、待复核 0 项；解码估算 46.3 MiB，属 R18 2 倍光栅的正常结果）按四步恢复登记视觉复核 closed：用户 2026-11-19 抽查通过（p1、p35），结论原话写入备注“用户抽查：”一行；交付校验通过（exit 0，成品 sha256 eac8128b…）。
- **R14（§13）**：MTGR 按知识库规则删除源论文下载后 `--after-cleanup` 通过（在场一致 2、发布副本一致 1、已删除只存摘要 4）；发布副本追加一字节、证据批次文件追加一空格两个损伤样本分别按预期失败。cuSPARSE 同构副本按新顺序清理：绑定清单（源快照 + 30 张快照资源 + 成品）31+1 项全部保留、摘要一致；清理后重导出走通（262 页候选、6,215 项放宽逐项登记），外链尾斜杠一项见 §21；源快照与成品随后按知识库规则删除，属清理顺序的预期结果。
- **§14.1（R9 一屏输出）**：ULTRA-HSTU 全绿复跑 23 行（≤40）：数字提示汇总为一行（97 处待复核分四类），无逐项提示；`--verbose` 时逐项 97 行。
- **§14.2（R3 锚点测试）**：表格单元格与脚注定义体两个刻画用例落地并通过（单元格锚点按“格内文字前”允许空白；脚注定义体锚点按行首 `[^` 判形，同定义行内位移不算违背，删锚点或把锚点移出定义行仍报“来源锚点”），合入 `test_latexml_anchor_writing.py`；真实样本侧 DIN 快照的 4 个脚注定义节点均无 id、不存在定义体内链接目标，知识库与工作区 261 个 HTML 亦无 td/th 链接目标（按 §14.2 以单元测试为准）。

### 18.2 实施与设计的差异（逐条）

计划 §6 随计划批准的四处处理在此归档；其余为实施期经 controller 裁定或如实记录的偏差：

1. **计划 §6-1（已批准）**：R9 一屏输出在设计外增加“只有一条的告警类别只打印这一条”（ticket 05 任务 4），实测 23 行。
2. **计划 §6-2（已批准）**：R12 渲染器用法写入 `references/pdf_export.md` 完成合同第 3、4 条各一句；`--output` 要求新路径，不覆盖已补写判断的说明文件。
3. **计划 §6-3（已批准）**：R13 只给 `code-page-gap-review` 加页码，不给每个代码块都有的空白保真项加；R2 页文本回退在现行代码里不登记放宽项，无可加页码的项，不新增。
4. **计划 §6-4（已批准）**：R14 清理后核对只比对索引身份登记了摘要的交付根文件（输入、输出、术语表），只登记在 `files`、不在输入里的目录文件不核对。
5. **ticket 02（controller 裁定）**：`test_pdf_integrity.py` 的 H2 用例（`test_forced_move_with_leading_h2_still_blocked`）与批准需求冲突——其 Markdown 的 `## 小节标题` 紧邻 63 行代码块，票面括号描述与用例事实不符；按“测试随行为维护”改写为断言 R4 新契约（rc=0、登记 review 放宽、无 `code-page-gap` 失败），“无标题粘连仍失败”由本 ticket 新测试文件的段落变体承担；`check_code_pagination` 文档串中“增加一个 H2 不改变这一空间判断”一句同步更新。该文件列入“本批改了断言”清单，base 一侧照旧断言，不计入回归差异。
6. **ticket 02（controller 裁定）**：R4 损伤样本的字面形态（标题去掉 `#`）与 API 源页准入门禁结构性冲突（标题序列身份 260 对 259 不确认，不传导航参数同样被拒）；接受等价形态证据链——取消粘连（插入段落）后放宽 2→0、真实 Chromium 集成用例钉住 FAIL 形态。
7. **ticket 02**：cuSPARSE、DIN 均在恢复第 1 步（translation 模式取当前绑定、登记沿用原复核结论）后带 `--translation-record` 重导出并核验通过：cuSPARSE 262 页、核验 0 失败（`code-page-gap` 0 项、R4 放宽恰 2 条），DIN 15 页、核验 0 失败、12 处引文标签无词内拆分；副本内记录保持 translation 模式（恢复第 3、4 步不在 ticket 02 的验收范围）。
8. **ticket 03（controller 裁定）**：修复面扩大——票面指定改 `enumerate_items`，但顶层 `ul.ltx_itemize` 走 `_itemize`（写出）与 `_source_reconcile.py` 的 itemize 分支（独立读取）；两处同条件剥默认标记（`ITEMIZE_MARKERS`），保留 `enumerate_items` 原改动覆盖嵌套于 `ol` 的 `ul`。本设计适用范围相应增加 `_source_reconcile.py`（计划的事实性修正）。
9. **ticket 04（controller 裁定）**：声明位置约束写入 `references/images_display.md`——交付根一级没有可登记项目级 JSON 的角色（`check_root_layout`/`ROLE_PATTERNS` 拒绝），声明放 `export/` 等工作目录；§8.2“放在项目里”的字面歧义以文档收窄。
10. **ticket 05**：验收样本区域偏差——论文无 §5.3（第 5 节无小节），按 §10.3“同类修改”改在 §4 实验区（4.2/4.3）做相同的三类格式改动。
11. **R15 验收副本（controller 裁定/记录）**：复核登记 BASE/NEW 两侧各做一次（复核绑定投影检查器脚本摘要而 R15 恰改这三个文件，单侧登记会使对照运行必败，两侧登记保持“两次都通过 + 结果比对”的验收语义）；引文引用用 `>` 段落式而非 `> -` 列表式（列表式缩进 li 锚点宿主不被导出器 internal-link-target 支持，5 处链接全败）；证据目录因 `ensure_persistent` 拒绝临时根放 `/Users/nanzhang/workdir/.r15-accept-evidence/` 并以符号链接保持票面路径；cuSPARSE 原始页按项目 normalizer 同一清单与不变量仅剥站点骨架后解析。
12. **旧解析稿兼容（用户 2026-11-18 选定）**：根因是 R7 之前的写出器把“嵌套于无序列表条目内的子列表”拼进父条目同一行（`- • 外层 – 内层`），源对账按现行读法读不出这种形态，行中的 `–` 报差异、`split_work_packages.py` 拒绝拆包。三种做法：补文字规则——只看文字分不清行中 `–` 是子列表标记还是原文破折号（同一稿 `:628`、`:630`、`:632` 是原文），原文破折号被删改会查不出；要求重新解析——要手工迁移译文；按旧读法整篇比对——对账先按现行读法比，不一致时按 R7 之前的读法（快照里的默认标记保留）整篇重比，一致即通过，两次都不一致报差异较少的那次（选定）。行为：一份解析稿要么整篇是现行写法、要么整篇是旧写法，混合（如新稿单个条目多出默认标记）被拒。实现给 `enumerate_items`、`_latexml_src_stream`、`_reconcile_latexml_core` 加 `keep_itemize_markers` 参数（只供源对账按旧读法重读，写出侧不用），`reconcile_latexml_to_markdown` 做两次比对。

### 18.3 缺口（如实记录，不算完成）

1. **R10 首跑误报未定位**：6 个副本上第一次走到身份比对的 `--prepare-reviews` 都没有出现“候选准备期间依赖身份变化”，根因没有找到，按 R10 验收记“待定位”；身份变化报错会列出变化的键和文件，再出现时按报错定位。
2. **需求 §6 整体验收**：新共享安装下 agent 时间不超过 3 小时，仍待用户定重装时机后实测（第 1 批遗留，与本批无关）。

### 18.4 全量回归

改动前代码（git archive 解包、含仓库根 `tests/`）与 HEAD 各跑一次全量 pytest 与 7 个集成脚本（venv 的 bin 目录置于 PATH 首位，`TMPDIR=$(getconf DARWIN_USER_TEMP_DIR)`）。全量 pytest：两侧失败集合去掉 `test_document_title_v2.py::test_title_v1_literal_and_old_reader_rejection` 后相同，均为 7 例预存失败（`test_pdf_math_export.py` 5 例、`test_latexml_footnote_table_boundaries.py` 1 例、`test_pdf_confirmed_footnotes.py` 1 例），HEAD 侧 7 例失败、1530 例通过；该用例仅改动前解包树失败——用例内部执行 `git archive`，解包树无 `.git` 必败，属预先声明的运行方式差异。集成脚本：HEAD 侧 7/7 退出 0；改动前一侧 6/7——`run_work_packages` 在 /tmp→/private/tmp 符号链接路径下退出 1，是合并按字面比对包内 `source_file` 与当前源路径所致，属 R20 修复的问题（§22），不是回归差异。静态检查：对改动前基线的 `git diff --check` 无输出；改动脚本 `py_compile` 通过；改动的 Markdown 链接检查问题数 0。

## 19. R17 PDF 图片在版心内水平居中

本节行号指 `zn_dev` @ `a35a205`。

### 19.1 现状

Markdown 里单独成行的图片渲染为 `<p><img …></p>`，包在链接里的渲染为 `<p><a …><img …></a></p>`。导出器只给 `img` 写显示宽度（`export_pdf.py:347`–`:350`，现有代码）：

```python
        width_px = binding["px"]
        images[occurrence - 1]["style"] = (
            "width:%spx" % (int(width_px) if width_px == int(width_px) else width_px)
        )
```

样式表里与图片有关的规则只管分页和最大宽度；图片段落按普通段落两端对齐（`assets/pdf/style.css`，现有代码）：

```css
p { margin: 0.45em 0; orphans: 2; widows: 2;                    /* :39，:40–:45 为注释与 overflow-wrap */
    text-align: justify; }                                      /* :46 */
p:has(> img), p:has(> a > img) { break-after: avoid-page; }     /* :54 */
img, svg { max-width: 100%; height: auto; }                     /* :165 */
```

两端对齐的段落只有一行时从行首排，所以比版心窄的图贴着版心左缘。块公式已经居中（`.math-block` 的 `text-align: center`，`:173`–`:176`）。

实测（A4，版心宽 505pt，左边距 45pt）：HSTU 副本 PDF 第 2、3、6、11、12 页的图左距都是 45.0pt，右侧留白 228–375pt；MTGR 第 6 页图 2 宽 225pt，右侧留白 325pt。

图片在译文里的位置（按导出器同样的 Markdown 解析，统计工作区 DLRS、CUDA 项目与知识库 CUDA 下 637 份 Markdown，含 `translated/` 等过程副本，跳过 `source/`、`docs/` 等目录）：单独成段 443 处，包在链接里单独成段 230 处；与图题同在一段 493 处，都在 PTX ISA 译文里（`ptx_isa/` 263 处，`ptx_isa/translated/` 的副本 230 处），图片行下一行紧接图题、中间没有空行，PTX ISA 没有导出 PDF；与其他文字同在一段 4 处（nvcc 3 处、cuBLASXt 1 处）；列表项和表格单元格里 0 处。

### 19.2 方案比较

原型在工作区外的脚本副本上做。

| 方案 | 做法 | 结论 |
| --- | --- | --- |
| A 只加样式 | `p:has(> img), p:has(> a > img) { text-align: center; }` | 不成立。图锚按 R3 独立成段写在图前（`<a id="S1.F1"></a>`，空一行再写图片），居中后锚点仍在版心左缘，PDF 目的地的 x 是版心左缘；核验对图片目标按图片左缘比对 x（`verify_pdf.py:5116`、`:5159`–`:5160`）。最小样本的导出在候选门禁报 `internal-link-target` 停止 |
| B 样式 + 图片的独立锚点按版心左缘比对 | A 之外改核验一处：图片目标的锚点独立成段时，期望的目的地 x 取版心左缘，与整表锚点的现有处理相同（`:5139`–`:5140`） | 采用。HSTU 副本导出与核验通过，图片偏离版心中线不超过 0.2pt；页数 35、内部链接注解 352、放宽项 4，与改动前相同 |
| C 改图锚写法 | 把锚点挪进图片段，或让锚点段也居中 | 拒绝。要改第 1 批的锚点契约，已有译文都得迁移；锚点与图片同段的写法在现行代码下本来就报 `internal-link-target`（原型里改动前同样失败）；锚点段居中后 x 在版心中点，仍不等于图片左缘 |

导出器另给图片段加 class 再定样式也不需要：`:has()` 选择器已在 `:54`–`:56` 使用。

### 19.3 改动

1. `assets/pdf/style.css`：`:58`（`img { break-after: avoid-page; }`）之后加

   ```css
   /* 单独成段的图片（含带链接的图片）在版心内水平居中（R17）。 */
   p:has(> img), p:has(> a > img) { text-align: center; }
   ```

   与图片同段的文字随之整段居中，多行也逐行居中：已导出 PDF 的项目里只有 cuBLASXt 1 处；PTX ISA 有 263 处但没有导出 PDF，图片行与图题之间空一行就按 §19.4 的规则处理。`th p, td p { text-align: left; }`（`:50`）与这条规则优先级相同，这条写在后面，单元格里的图片也居中（现有译文 0 处）。

2. `verify_pdf.py` 的 `_destination_matches`（`:5074`），图片目标分支（`:5113`–`:5118`，现有代码）：

   ```python
       if name == "img" or not runs:
           if not images or offset:
               return False
           first_page, (x0, _bottom, _right, y0) = images[0]
           # 图像的块级引导锚点可位于图片所在行盒的起点。
           upper = y0 + (10.5 * (1.65+0.45) if standalone else 0)
   ```

   在 `upper = …` 之后加：

   ```python
           if standalone:
               # 图片在版心内居中绘制，独立锚点段在版心边界（R17，同整表锚点）。
               x0 = origin[0]
   ```

   纵向窗口不变。导出的候选门禁调用同一函数，导出与核验同时生效。图片靠左时图片左缘就是版心左缘，所以这条规则对靠左的图片判定不变，检出能力不变弱。

3. `references/pdf_export.md:174`（“正文两端对齐”一条）的不继承名单去掉“图题”（多行图题照旧两端对齐），其后加一条：

   ```markdown
   - **图片与图题居中**：单独成段的图片（含带链接的图片）在版心内水平居中，显示宽度不变；紧跟图片、以加粗的“图 N”“Figure N”“Fig. N”或子图标号开头的图题一行放得下时随图居中，多行时铺满版心、两端对齐；指向图片的独立锚点按版心左缘核对目的地。
   ```

4. 测试：`tests/test_pdf_style_rules.py` 断言这条规则存在。`tests/test_print_geometry.py` 的 `printed_links` 夹具已有“独立锚点段 + 图片”（`:51`），在它的导出结果上加一条断言：图片偏离版心中线不超过 1pt。只加样式不改核验时，这个夹具的导出会在候选门禁失败；现有的目的地对调用例（`:85`、`:102`）继续证明错误目的地被拒。

### 19.4 图题对齐（D4）

用户 2026-11-18 选 B：紧跟图片的图题一行放得下时随图居中，占多行时照旧铺满版心、两端对齐。

译文的图题是图片段之后的普通段落，翻译约定写成加粗的 `**图 N. 中文（English original）**`（`references/translation_conventions.md:33`），子图题写成 `**(a) …**`。现在图题按正文两端对齐：单行图题靠左，多行铺满版心。`references/pdf_export.md:174` 说“图题不继承两端对齐”，这只对 `figcaption` 成立（`style.css:50`），译文里没有 `figcaption`。

**判定规则**（`export_pdf.mark_figure_captions`）：

1. 从每个单独成段的图片段（含带链接的图片）看紧邻的下一段。
2. 这一段开头（不算行内的 `<a id>` 锚点）是加粗文字，并以“图 N”“Figure N”“Fig. N”开头时是图题，以 `(a)`、`（a）` 这类子图标号开头时是子图题，两种都加 `image-caption` 类。
3. 子图题之后接着看下一段，所以“子图、子图题、子图、子图题、总图题”整组都能标上；遇到独立锚点段或其他段落就停。

样式只有一条 `p.image-caption { width: fit-content; margin-inline: auto; }`：一行放得下的图题收缩到文字宽度，左右外边距均分，于是居中；放不下时宽度等于版心宽，两端对齐照旧。

**按加粗标号判定的原因**：图片之后紧邻的段落不都是图题。直接给“图片段之后一段”加样式时，cuSPARSE 里一行长的正文（如“且”“本函数有下列限制：”）和加粗小节名（如 `**稠密向量表示（Dense vector representation）** [#](…)`）也会被居中。按约定的图题形状判定就排除了它们，不用猜文字内容。不加粗的图题不标，语料里只有 CUDA PG 过程副本里的 6 处英文图题（如 `Figure 14 Matrix Transpose using Global memory`），交付译文里对应的都是加粗图题。

**实测**（637 份 Markdown，口径同 §19.1）：673 个单独成段的图片段之后，256 段标为图题，其中总图题 222 段、子图题 34 段；按字宽估算，一行放得下的 114 段会居中，其余 142 段占多行，版面不变。13 段在加粗图题之后还有文字（如 CUDA PG 图 14 的图题后接图例说明），都占多行。没标上的是正文、小节名、引用块、标题和锚点段。紧跟图片的段落里没有以“表”“Table”“算法”开头的题注，规则不含这些标号。

**链接与核验**：CUDA PG 有 31 个图题的段首是行内锚点（锚点行下一行紧接图题，如 `<a id="id5"></a>` 之后是 `**图 27. 条件 IF 节点（Figure 27 Conditional IF Node）** [#](#id5)`），锚点随文字一起居中，PDF 目的地与文字起点照旧对上。图片与图题之间隔着独立锚点段的 0 处，所以核验不改。

**原型**（工作区外的副本，规则与样式如上）：

| 样本 | 结果 |
| --- | --- |
| HSTU | 导出与核验通过，35 页不变；图 4、图 6 与 5 个子图题居中，偏离版心中线 0.1pt；多行图题首行从版心左缘起排 |
| AutoInt、Hiformer | 导出与核验通过，页数不变（23、17 页）；子图题与单行图题居中 |
| CUDA PG cuda-graphs 页 | 导出与核验通过，46 页不变；18 个带 `[#](#…)` 自链接的图题里，单行的 17 个居中 |
| MTGR | 导出通过，15 页不变；核验因副本缺原始快照失败，改动前同样失败 |

**限制**：图片与图题写在同一段（图片行下一行紧接图题、中间没有空行）时，按 §19.3 第 1 条整段居中，多行图题也逐行居中。已导出 PDF 的项目里只有 cuBLASXt 1 处；PTX ISA 有 263 处但没有导出 PDF，导出前在图片行与图题之间空一行即可。导出器不拆这种段落。

**改动**：

1. `assets/pdf/style.css`：§19.3 第 1 条之后加

   ```css
   /* 紧跟图片的图题：一行放得下时随图居中，多行时铺满版心（R17 D4）。 */
   p.image-caption { width: fit-content; margin-inline: auto; }
   ```

2. `export_pdf.py`：`soup_images`（`:385`）之前加 `mark_figure_captions(soup)` 和判断图片段的小函数（约 30 行）；`parse_chapter` 里标出独立锚点段的循环（`:2923`–`:2936`）之后调用一次。核验读同一个 `chapter.soup`，看到的类与导出相同。
3. 测试：判定规则的单元测试覆盖图片加图题、带链接的图片加图题、段首有行内锚点的图题、子图题接总图题，以及不标的情形（独立锚点段之后的图题、cuSPARSE 的加粗小节名与一行正文、图片与图题同段）；`tests/test_pdf_style_rules.py` 断言样式规则存在；`tests/test_print_geometry.py` 的导出夹具各加一个单行与多行图题，断言单行图题偏离版心中线不超过 1pt、多行图题首行从版心左缘起排。

### 19.5 影响

- 样式表和 `verify_pdf.py` 的摘要都在交付身份里（`verify_delivery.py:2128` 的 `style_policy`，以及检查器脚本摘要），所有 PDF 项目的视觉与链接复核绑定都会失效。第 2 批的 R6、R13 已经改了这两个文件，随同一次发布不多一轮重新复核。
- 图片与图题的位置变了，重导出后不能用显式视觉复用（要求像素相同），要做全页目检或程序化目检。
- 已发布的 PDF 不会变，重新导出才居中。

### 19.6 验收

- HSTU、MTGR（含 R8 声明的图 2）、CUDA PG 13.5 迁移副本重导出：用 PyMuPDF 量每张单独成段的图片和每个标为图题的段落，图片与一行放得下的图题偏离版心中线不超过 1pt，多行图题首行从版心左缘起排；导出与核验通过，没有 `internal-link-target`，CUDA PG 图题里的 `[#]` 自链接照常通过；页数、内部链接注解数、放宽项数与改动前相同；CUDA PG 图 42（带链接的图片）仍与图注同页。
- 损伤：只加样式、不改核验时，`printed_links` 夹具与 HSTU 副本的导出报 `internal-link-target`，证明 §19.3 第 2 条必需；`test_print_geometry.py` 的目的地对调用例仍被拒。

### 19.7 实施验收（2026-11-18）

ticket 11 于 2026-11-18 在三个真实样本副本（HSTU、MTGR、CUDA PG 13.5 迁移副本）上完成验收：改动前（`8780880` 解档副本）与改动后（`4b23fc9`）两侧各导出、核验一次，全部退出码 0；`verify_report.json` 的 `pages`、`internal_link_annots`、`len(relaxed_matches)` 两侧逐项相同。逐页量测（`figure_layout.py`，改动前 → 改动后）：

| 样本 | pages | internal_link_annots | relaxed_matches | 图片偏心（>1pt） | 图题 |
| --- | --- | --- | --- | --- | --- |
| HSTU | 35=35 | 352=352 | 4=4 | 23 → 0（改动前偏 -91.6 ～ -209.4pt） | 单行居中 0→7（图 4、图 6 与 5 个子图题）、多行首行铺满 9→9、异常 7→0 |
| MTGR | 15=15 | 60=60 | 0=0 | 3 → 0（改动前偏 -74.0/-140.0/-77.4pt） | 3 个多行图题首行铺满、异常 0；第 6 页图 2（R8 声明）宽 225.0pt、水平居中（页宽 594.96）、与题注同页 |
| CUDA PG 13.5 | 650=650 | 1248=1248 | 11764=11764 | 42 → 0 | 未标记图题（0/0/0，排版与改动前相同，见下缺口）；failures 0（含 `internal-link-target` 0 条，图题 `[#]` 自链接照常通过）；第 249 页图 42（带链接的全宽图）与图注同页 |

- 损伤（§19.6 第 2 条）：HSTU 只加新样式、核验器换回 `8780880` 版本时，导出退出码 1，报 27 条 `internal-link-target`（首条“链接 '图 1' (#S1.F1) 期望对象 ch01-S1.F1”），PDF 不产出，证明 §19.3 第 2 条必需。
- 对照图：`/tmp/r17-accept.JHEWkW/compare-hstu-p11.png`（HSTU 第 11 页三图，改动前贴版心左缘 x0=45.0 → 改动后居中）；`/tmp/r17-accept.JHEWkW/compare-pg-fig27.png`（CUDA PG 第 203 页图 27，左缘 → 居中，中线偏 -0.13pt）。

**缺口（CUDA PG 图题）**：CUDA PG 一侧“一行放得下的图题居中”不成立。CUDA PG 13.5 现行译文的全部 57 条图题（含 cuda-graphs 一章的图 24–41）都以字面 `[FIGCAPTION] ` 残留源文记号开头（如 `chapters/04_CUDA_Features.md:2036`），该记号是源页面解析占位符，导出器原样排版进 PDF；按 §19.4 判定规则（加粗 `图 N`/`Figure N`/`Fig. N` 开头、不猜文字内容）这些图题全部不标、不居中，两侧图题逐字节相同（例：图 24 第 188 页题注行中线偏 -100.1pt）。图片居中不受影响（70/70 偏离 0）。证据链：英文源文以 `[FIGCAPTION]` 标记图题；同族项目翻译约定要求消费该记号（cuSPARSE `docs/package_instructions.md:45`–`:47`：`[FIGCAPTION] English text [#](#anchor)` 译为加粗图题并保留尾部源链接）；知识库现行 `chapters/` 57 处带记号，而 2026-11-13 的 13.4 归档 0 处、pagesite 工作稿 0 处，记号是 13.5 重译引入的残留；`source-13.5/trans_*` 重译页同样携带记号；成品 PDF 里记号逐字可见（改动前后相同）。实测 `<p>[FIGCAPTION] <strong>图 27…</strong> …</p>` 的标记结果为空，去掉记号后同一结构即被标记。处理方式见[需求 §4 D6](./2026-11-16-paper-pdf-delivery-backlog-requirements.md#4-决定)：合并主分支、重装共享安装后重导出 CUDA PG 时，先删除这 57 处行首记号（图题文字与尾部 `[#](#…)` 不动）再导出交付；在此之前已交付的 PDF 保持原样；图题判定规则不改。

**实施与验收记录的差异**：

1. MTGR 核验按票面 OPTS 去掉 `--image-adaptations`：该旗标属导出器，`verify_pdf.py`（两侧同版）不识别（argparse 退出码 2），核验从 work-dir 的导出报告读适配声明；其余参数（含两个 `--unlink-target`）逐字相同，两侧对称执行、均通过。

R17 本体（单独成段图片居中、图片独立锚点按版心左缘核对）在三个样本上全部达成；D4 图题居中在 HSTU、MTGR 达成，在 CUDA PG 现行译文因上述记号不适用，重导出时的处理见需求 D6。

## 20. R18 SVG 插图在 PDF 中清晰

本节行号指 `zn_dev` @ `a35a205`。

### 20.1 现状与根因

绑定了显示宽度、或要载入本地子资源的 SVG，由导出器在离线浏览器里渲染成 PNG 再内联（`references/images_display.md:135`–`:139`）。派生位图的像素由 `svg_print_dimensions`（`export_pdf.py:3751`）决定（现有代码）：

```python
    physical = min(display, CONTENT_WIDTH_PX)
    pixels = min(max(physical, native), EMBED_MAX_EDGE, EMBED_MAX_EDGE * ratio)   # :3784
    ...
    return ceil(pixels), max(1, round(pixels / ratio)), display                   # :3787
```

`native` 是 SVG 自身的宽度（viewBox 宽或数值 `width` 属性），`EMBED_MAX_EDGE` 是位图长边上限 2600（`:3600`）。`render_svg_payload`（`:3790`）按这个宽高开浏览器视口、以 `device_scale_factor=1` 截图（`:3805`），截图像素就是视口像素。PDF 里的显示宽度来自显示尺寸绑定写的 `width:Npx`（`:347`–`:350`），显示高度由位图宽高比按 `height: auto` 算出（`style.css:165`）。

所以 SVG 自身不比显示宽度大时，位图像素等于显示宽度的 CSS 像素，在 PDF 里是 96 dpi。HSTU 图 3（`images/design_dlrms_vs_grs_model_v2.svg`，viewBox 宽 359.884）显示宽 429px（321.7pt），嵌入 429×493 px。

核对源码得到的几处细节：

- 位图宽度取显示宽度与 SVG 自身宽度中较大的一个，并不总等于显示宽度。HSTU 的 21 张 SVG 现有密度 1.0–3.7 倍，其中 5 张已超过 2 倍。
- 缓存键（`:3795`）已含派生宽高，倍数体现在宽高里，不用另加。
- 证据行的 `render.device_scale_factor` 一直写 1（`:3847`），是渲染条件，不是可调的倍数。

核验侧 `check_svg_renders`（`verify_pdf.py:1033`）调用导出器同一个 `plan_svg_renders` 重算宽高（`:1052`），用 `render_svg_payload` 重新渲染（`:1094`），再比证据（`:1099`）、PDF 里的显示宽度（`:1103`）和解码像素（`:1109`）。只改导出侧时，核验按 1 倍重算，新导出会报 `svg-render-drift` 与 `svg-pdf-pixels`（HSTU 原型 32 项）。

影响面（工作区 21 份导出报告与知识库 CUDA PG 13.5 的导出报告）：38 张 SVG 派生位图，在 HSTU（21 张）、ULTRA-HSTU（11）、MTGR（3）、STCA（2）、DIN（1），其中 26 张不到 1.5 倍。CUDA PG 13.5 的 817 张图都是 PNG，cuBLAS、cuSPARSE 也没有 SVG 派生位图，这三份的体积与版面不受影响。

### 20.2 方案比较

| 方案 | 做法 | 结论 |
| --- | --- | --- |
| A 整数倍放大派生位图 | 派生位图不足 2 倍显示宽度时，宽、高同乘最小的整数 k，使宽度达到 2 倍，长边不超过 2600；k=1 即现状。倍数写进导出报告，核验按报告的倍数重算 | 采用。宽高比与现在相同，`height: auto` 算出的显示高度不变。HSTU 副本：35 页、23 张图的位置与显示尺寸全部不变，16 张重新光栅化，图 3 为 858×986 px（192 dpi），导出与核验通过 |
| B 按目标像素取下限 | `pixels = max(2 × 显示宽度, native)` 后照旧取整 | 拒绝。宽、高分别取整后宽高比变了，HSTU 第 11、12、14、27、33 页 7 张图的高度或位置变化 0.7–0.8pt；图 3 为 858×985 px |
| C 浏览器设备像素比 | 视口仍按现有宽高，截图时把 `device_scale_factor` 设成倍数 | 拒绝。统一设倍数时，已超过 2 倍的图也再乘一次（HSTU 第 35 页 769 px 宽的图变成 1538 px）；按图选倍数时，像素结果与 A 相同，却要改渲染函数、缓存键和证据字段，并逐行记录倍数 |
| D 矢量嵌入 | 绑定显示宽度的 SVG 也像未绑定的一样直接嵌入，PDF 里保留矢量 | 拒绝。任意放大都清晰，但现有派生就是为了在 PDF 里逐次量宽（`images_display.md:135`）：矢量没有可独立量测的位图，`check_image_widths` 的宽度核对、`check_svg_renders` 的像素证据与绘制计数（`svg-pdf-draw-count`）、R17 依赖位图位置的图片锚点核对都要重做；“无法独立量测的矢量宽度”已列为已知限制（`CHANGELOG.md:85`）。受影响的只有 5 篇论文，代价远大于收益 |
| E 倍数做成导出参数或逐图声明 | `--svg-scale` 或在图片适配声明里写倍数 | 拒绝。没有按项目选倍数的需求；常量只在一处 |
| F 统一缩小显示宽度 | 所有图的显示宽度乘同一比例，原型试了 85% 与 70% | 拒绝。派生位图随显示宽度一起缩小，分辨率不变：HSTU 图 3 缩到 85% 时宽 274pt、365×419 px，仍是 96 dpi。分页点全部移动，图连同图题整体跳到下一页留下的大块空白（页底空出 100pt 以上）有增有减：ULTRA-HSTU 85% 时从 2 处共 658pt 增到 7 处共 1379pt，HSTU 85% 时从 2 处 518pt 减到 1 处 299pt、70% 时增到 4 处 630pt。图内文字同比变小，也违背“PDF 中逐次绘制宽度符合 min(显示宽度, 版心上限)”（[PDF 导出需求](./2026-09-09-markdown-pdf-export-requirements.md) A13）。个别图跳页用 R8 的逐图声明处理 |

### 20.3 改动

1. `export_pdf.py`：
   - `EMBED_MAX_EDGE`（`:3600`）旁加常量 `SVG_RASTER_SCALE = 2`（D5）。
   - `svg_print_dimensions(record, binding, scale=1)`：`:3787` 的返回改为按方案 A 取整数倍：

     ```python
         width, height = ceil(pixels), max(1, round(pixels / ratio))
         # 不足 scale 倍显示宽度时宽高同乘整数倍：宽高比不变，版面不动；不超过长边预算（R18）。
         factor = max(1, min(ceil(scale * physical / width), EMBED_MAX_EDGE // max(width, height)))
         return width * factor, height * factor, display
     ```

     `scale=1` 时 `factor` 为 1，结果与现状相同。
   - `plan_svg_renders(..., scale=1)` 把倍数传给上面的函数；`export`（`:4700`）传 `SVG_RASTER_SCALE`；导出报告在 `svg_renders`（`:5010`）旁写 `"svg_raster_scale": SVG_RASTER_SCALE`。
   - `render_svg_payload`、缓存键和证据行字段不改；解码预算按新的宽高计入（`:4701`–`:4712`）。
2. `verify_pdf.check_svg_renders`（`:1033`）在调用 `plan_svg_renders`（`:1052`）之前取倍数 `report.get("svg_raster_scale", 1)`，没有该字段的旧报告按 1 倍。值既不是 1 也不是 `SVG_RASTER_SCALE` 时只报一条 `svg-render-evidence`，并照常登记 SVG 出现（`pdf._svg_occurrences`，`:1055`），免得宽度检查把它们当成位图连带报错；然后按这个倍数调用 `plan_svg_renders`，其余比对不变。
3. `references/images_display.md` 的“SVG 打印负载”（`:135`–`:139`）补一句：派生位图至少是显示宽度的 2 倍像素，不足时宽高同乘整数倍、显示尺寸不变；倍数写入导出报告的 `svg_raster_scale`，核验按报告重建，没有该字段的旧报告按 1 倍核验。
4. CHANGELOG“未发布”的兼容性说明：SVG 插图的派生位图提高到 2 倍，PDF 变大；旧导出照常核验，重新导出才变清晰；重导出后像素不同，不能用显式视觉复用。
5. 测试（`tests/test_svg_print_payload.py`）：`svg_print_dimensions` 在 1 倍与 2 倍下的宽高（不足时同乘整数倍、已够密时不变、长边上限截住倍数）；`check_svg_renders` 对没有该字段的 1 倍导出通过，对字段改成 1 的 2 倍导出报 `svg-render-drift` 与 `svg-pdf-pixels`，对无效值只报一条 `svg-render-evidence`。现有断言随行为更新：`test_svg_print_payload.py` 的派生位图为 720×360，取色坐标按 2 倍换算；`test_image_adaptations.py:182` 的嵌入尺寸为 720×320；`:125`–`:128` 按默认 1 倍不变。

### 20.4 倍数（D5）

用户 2026-11-18 定为 2 倍，图片显示宽度不缩小。HSTU、ULTRA-HSTU 副本实测：导出与核验通过，页数与每张图的位置、尺寸不变。

| | 改动前（1 倍） | 2 倍 |
| --- | --- | --- |
| HSTU 图 3 嵌入像素与有效分辨率 | 429×493，96 dpi | 858×986，192 dpi |
| HSTU 重新光栅化的图（共 23 张） | — | 16 张 |
| HSTU PDF 体积 | 5,412,177 B | 5,962,308 B（+10.2%） |
| ULTRA-HSTU PDF 体积 | 4,401,978 B | 4,673,833 B（+6.2%） |
| HSTU 解码估算（告警阈值 512 MiB，只告警） | 20.3 MB | 48.6 MB |

导出耗时没有可测差别（HSTU 10.0 秒左右）。以 macOS“预览”为例，Retina 屏 100% 时每英寸 144 个屏幕像素，2 倍的位图放大到 133% 以内不必被拉伸；打印为 192 dpi。

其他文档的体积估算：从导出报告的 `svg_renders` 逐行算出 k 和新增像素 (k²−1)×宽×高，每个新增像素约 0.08 字节（HSTU 新增约 708 万像素、PDF 多 550 KB；ULTRA-HSTU 新增约 353 万像素、多 272 KB）。CUDA PG 13.5、cuBLAS、cuSPARSE 没有 SVG 派生位图，增量为 0。

### 20.5 影响

- PDF 体积见 §20.4。导出器与核验器的摘要在交付身份里，复核绑定的重新登记与 R17 在同一次发布里完成。
- 旧项目：没有 `svg_raster_scale` 的导出报告按 1 倍核验，原型里改动前的 HSTU 1 倍导出用新核验器复核通过；已发布的 PDF 不变，重新导出才变清晰。
- 重新导出后派生位图的像素不同，不能用显式视觉复用，要做全页目检或程序化目检（与 R17 相同）。
- 显示尺寸与分页不变：每张图的宽高比与现在相同，`height: auto` 算出的显示高度不变。

### 20.6 验收

- HSTU、ULTRA-HSTU 副本按 2 倍重导出：用 PyMuPDF 比对改动前后的页数和每页每张图的位置与尺寸（误差不超过 0.1pt）；图 3 显示宽 321.7pt，嵌入 858×986 px（192 dpi）；导出与核验通过；记录 PDF 体积变化，附图 3 的 400% 局部对照图。
- 兼容：改动前的 1 倍导出（报告没有 `svg_raster_scale`）用新核验器复核通过。
- 损伤：把 2 倍导出报告里的 `svg_raster_scale` 改成 1 时报 `svg-render-drift` 与 `svg-pdf-pixels`；改成无效值时只报一条 `svg-render-evidence`；核验器不改时新导出报 `svg-render-drift`，证明 §20.3 第 2 条必需。

### 20.7 实施验收（2026-11-18）

ticket 12 于 2026-11-18 在 HSTU、ULTRA-HSTU 副本上完成验收（改动前 `97f0e4e`、改动后 `8eefc3a`）：四份导出与核验全部退出码 0，新侧导出报告均含 `svg_raster_scale: 2`，改动前报告无该字段。

- 版面与分页不动：逐页逐图比对，两样本“pages with moved images”均 0（HSTU 35=35 页、ULTRA-HSTU 28=28 页）。HSTU 16 张 SVG 重光栅化（96–184 dpi → 192–367 dpi）、7 张不变（PNG 位图与已达 2 倍的 SVG）；ULTRA-HSTU 11 张全部由 96 dpi 变 192 dpi、12 张不变。图 3 为 `321.7pt 429x493 96 dpi -> 858x986 192 dpi`（第 6 页），与 §20.6 预期逐字符相同。
- PDF 字节数：HSTU 改动前 5,412,266 → 改动后 5,962,397，ULTRA-HSTU 改动前 4,402,077 → 改动后 4,673,932。
- 兼容（§20.6 第 2 条）：无 `svg_raster_scale` 的 1 倍旧导出用新核验器复核通过（按 1 倍重建核验）。
- 损伤（§20.6 第 3 条）：报告倍数改 1 → `svg-render-drift` 16 + `svg-pdf-pixels` 16；改 5 → 仅 1 条 `svg-render-evidence`（“导出报告的 SVG 光栅倍数无效：5”），无 `image-width-unmeasured`；核验器不改动（旧核验器核新导出）→ `svg-render-drift` 16 + `svg-pdf-pixels` 16，证明 §20.3 第 2 条必需。
- 对照图：`/tmp/r18-accept.Q9BXmK/hstu-fig3-400.png`（图 3 的 400% 局部，左 96 dpi / 右 192 dpi，两半像素不同已程序化确认）。

## 21. R19 外链核验接受裸域名补的尾斜杠

本节不引用行号：改动落在 `verify_pdf.py` 的外链注解比较处与新增函数上，按名字定位。

### 21.1 现状

外链核对按字面比较 PDF 外链注解与原文链接：`annot.get("uri") != link["href"]` 不等即报 `external-link-missing`。Chromium 把 `https://fmt.dev` 这类裸域名存成 `https://fmt.dev/`，cuSPARSE 重导出因此报 `external-link-missing`（R14 验收余 1 项）。共享安装 `~/.agents/skills/tech-doc-translator/scripts/verify_pdf.py` 有同一修正的就地修改，仓库没有，重装后依赖它的项目会重新失败。

### 21.2 改动

`verify_pdf.py` 在 `_link_instances` 之前新增 `_uri_equivalent(annotation_uri, href)`：用 `urlsplit` 拆两侧，路径为 `/` 时归一为空，比较协议、主机、路径、查询、片段五元组；任一侧无法解析即不等。外链注解与原文链接的比较改用它，其余核对不变。

### 21.3 取舍

- 项目级包装（每个含裸域名外链的项目各写一份）：拒绝——逐项目重复，漏写即失败，重装后仍丢。
- 导出时改写 href（把 PDF 里的链接统一写成带尾斜杠）：拒绝——改变 PDF 里的链接内容。
- 合入等价比较（用户 2026-11-18 选定）：只放宽“裸域名补的尾斜杠”这一种差异，协议、主机、其余路径、查询、片段不同照旧不等。

### 21.4 验收

含 `https://fmt.dev` 外链的 cuSPARSE 副本带 `--translation-record` 重导出核验 0 失败；路径、查询、协议或主机不同的样本仍报 `external-link-missing`。

### 21.5 实施验收

同一 cuSPARSE 项目的全量来源副本实测：带 `--translation-record` 重导出 262 页、核验退出 0、失败 0 项，报告中 `fmt.dev` 仅存于外链注解记录本体（`external_uri_annots` 的 `https://fmt.dev/`），尾斜杠等价比较接受该注解、无 `external-link-missing`（§18.1 R4）。等价与不等价两侧由 `tests/test_print_geometry.py::test_bare_host_external_link_verifies` 覆盖：含裸域名外链的最小章节导出并核验通过，且 `https://fmt.dev/a/` 对 `https://fmt.dev/a`、`https://fmt.dev/` 对 `https://fmt.dev/?q=1`、`http://fmt.dev`、`https://fmt.org` 及注解缺失均判不等。

## 22. R20 工作包合并按真实路径认同一源文件

### 22.1 现状

拆包把源路径做 `abspath` 后写进包头 `source_file`（`split_work_packages.py`），按进程的物理工作目录展开；合并按字面比对这个路径和当前源的 `abspath`（`merge_work_packages.py`）。同一文件一侧给出物理路径、一侧经符号链接给出时（如仓库经 /tmp 符号链接进入、拆包写 /private/tmp 物理路径），合并报“异源包”，合并失败。恢复入口 `recover_work_packages.py` 已按真实路径比对。

### 22.2 改动

合并的比较改为两侧各取 `os.path.realpath` 后比对真实路径，与恢复入口一致。包头写入的路径不变。

### 22.3 取舍

- 拆包时把真实路径写进包头：会改变包头内容和已有工作包证据，拒绝。
- 只在文档里要求不经符号链接：问题仍在，拒绝。
- 合并按真实路径比对：只改一处，与恢复一致，采用。

### 22.4 验收

经符号链接路径运行 `tests/run_work_packages.sh` 通过；同一源文件经符号链接路径合并通过，内容相同的另一个文件仍报“异源包”。

### 22.5 实施验收

单元测试两个：同一源文件经符号链接与物理路径两侧给出时照常合并——改动前该用例失败，报“异源包: …/trans/wp_001.md 的 source_file 为 …/src.md，与当前源 …-link/src.md 不符”；另一个目录里内容相同的文件不是同一个源，仍报“异源包”（改动前后都通过）。工作包家族 5 个测试文件 65 项通过。经指向仓库根的符号链接运行 `tests/run_work_packages.sh`（venv 的 bin 目录置于 PATH 首位）：改动后退出 0，脚本自带的异源包反例仍被拒；改动前的代码同法运行退出 1，报“异源包”——拆包写物理路径 /private/tmp、合并比较当前目录的逻辑路径 /tmp，正是本节修复的缺陷。
