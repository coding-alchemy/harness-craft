# 论文翻译与 PDF 交付遗留问题设计（第 1 批）

| 元数据 | 内容 |
| --- | --- |
| 文档版本 | V0.3 |
| 文档状态 | V0.3 于 2026-11-17 记录最终实施验收；V0.2 于同日按第 1 批实施评审修订 |
| 创建 / 修订日期 | 2026-11-16 / 2026-11-17 |
| 适用范围 | `tech-doc-translator` 的 LaTeXML 解析（`_latexml_source.py`、`parse_reference_html.py`）、源对账（`_source_reconcile.py`）、译文核验（`verify_reference_translation.py`、`_api_navigation.py`）、PDF 导出与核验（`export_pdf.py`、`verify_pdf.py`）、`SKILL.md` 与 `references/` |
| 权威需求 | [论文翻译与 PDF 交付遗留问题需求](./2026-11-16-paper-pdf-delivery-backlog-requirements.md) V0.2，2026-11-17 批准；本批为 R1、R2、R3、R5、R9、R16 |
| 基线 | 设计基线 `zn_dev` @ `436b015`，文中行号均指该提交；第 1 批实施与评审修复已合入（2026-11-17） |
| 既有设计 | [论文流程去重与稳定性优化设计](./2026-11-07-paper-workflow-optimization-design.md)（§100 逐阶段进度输出）、[CUDA 13.5 升级重译修复设计](./2026-11-14-cuda-upgrade-retranslation-fixes-design.md)（API 家族解析稿写锚点） |

## 1. 目标与边界

本批对应 ULTRA-HSTU 修导出的 2h39m（锚点 1h08m、链接目的地 38m、KaTeX 宏 53m）和读组件源码弄清约定的时间（需求 §1、W2）。完成后，合法译文不再因数学穿插、跨页、含数学的译注误报失败；执行者不再手工放锚点、不再改共享脚本适配 KaTeX 宏；失败第一屏给出根因。

不做：需求 R4、R6–R8、R10–R15（后续批次）；整体验收“agent 时间不超过 3 小时”要在本批实现并重装共享安装后才能做，不在本设计内。

## 2. 总览

| 需求 | 改动位置 | 性质 |
| --- | --- | --- |
| R1 | `verify_pdf.py` `check_blocks` 增加两段切分匹配 | 改现有检查 |
| R2 | `verify_pdf.py` `_note_remainders` 改用公式切段；`check_translator_notes` 按段核对 | 改现有检查，复用 `export_pdf.block_text_segments` |
| R3 | `_latexml_source.py` 解析时写锚点；`_source_reconcile.py` 把空锚点当零宽；`verify_reference_translation.py` 核对锚点；`verify_pdf.py` 窗口上界排除宿主字形 | 新增：解析写锚点；其余改现有 |
| R5 | `export_pdf.py` 新增 `--katex-macros`、`--check-math` | 新增两个参数 |
| R9 | `verify_pdf.py` 证据缺位只报根因；`export_pdf.py` work-dir 转绝对路径；`_latexml_source.py` 差异全量交给入口；`verify_reference_translation.py` 告警默认汇总；`SKILL.md` 一句 | 改现有输出 |
| R16 | `references/latexml_source.md`、`references/pdf_export.md` 各入口示例；`_verification.extract_source_adaptation` 拒绝把下一个参数当路径 | 文档 + 一处参数检查 |

## 3. 基线与机制重审

### 3.1 改动依赖的现有接口

| 接口 | 位置 | 本设计的用法 |
| --- | --- | --- |
| `subsequence_in_window`、`check_blocks` | `verify_pdf.py:2996`、`:3012` | R1 在两者都失败后追加一步 |
| `PdfFacts.page_offsets`、`page_of_offset` | `verify_pdf.py:1886`、`:1921` | R1 判断“前段所在页的下一页” |
| `block_text_segments` | `export_pdf.py:2985` | R2 按公式节点切段 |
| `_note_remainders`、`check_translator_notes` | `verify_pdf.py:1578`、`:1649` | R2 |
| `reference_anchor_targets` | `_source_reconcile.py:2033` | R3 已给出每个锚点的 id 与角色（段落、公式外的 paragraph、figure、table-cell、reference、heading） |
| `LatexmlAdapter` 的 `_paragraph_host`、`_math_group`、`_biblist`、`_figure`、`_footnote_def`、`_table_simple`、`_table_complex` | `_latexml_source.py:1677`、`:1709`、`:1870`、`:2203`、`:2030`、`:1798`、`:1813` | R3 在各自写出处加锚点 |
| `parse_anchor` | `export_pdf.py:2653` | 导出已识别行内与独占一行的空锚点，R3 不改导出 |
| 式号相邻检查 | `export_pdf.py:2856` | 比对 `get_text()`，空锚点不影响，R3 可把公式锚点写进式号行 |
| `compare_anchors` | `_api_navigation.py:420` | 只认独占一行的锚点；R3 扩展到行内写法 |
| `CHECK_SCRIPT` | `export_pdf.py:3831` | R5 宏表与只渲染公式都复用它 |
| `run_verification` | `verify_pdf.py:5418` | R9 第 1 条 |
| `export()` | `export_pdf.py:4114` | R9 第 2 条 |
| `source_view_payload` 前的切片对账 | `_latexml_source.py:2589` | R9 第 3 条 |

### 3.2 与需求的差异（核对源码后）

| 需求 | 核对结果 | 本设计的处理 |
| --- | --- | --- |
| R2 | 共享安装的补丁按 `MATH_SENTINEL` 切剩余文字，但剩余文字由 `get_text` 取得，不含哨兵，这一步实际不起作用；起作用的是回退整章页文本，约束过弱 | 不照搬补丁；用 `block_text_segments` 切段，回退范围缩到两页（§5） |
| R9 第 3 条 | `parse_reference_html.py:373` 已打印全部差异；截断只在 `_latexml_source.py:2594` | 只改这一处（§8.3） |
| R16 | `--image-map` 格式错误时已报期望格式（`_verification.py:1195`）；W2 缺的是“这个文件怎么得到”。需求里的 `build_*` 是项目脚本，不在组件内 | 文档写来源与可省略条件；报错只补 `--source-adaptation`（§9） |

以上差异只缩小实现范围，不改变需求的用户结果。

### 3.3 机制重审

R3 新增“解析时写锚点”，会改变 `source.md` 的内容，属于持久产物的契约变化，按 AGENTS.md §5 比较过三种做法：

| 方案 | 做法 | 结论 |
| --- | --- | --- |
| A 只写文档 | 执行者按文档手放锚点 | 拒绝：W2 正是有文档（`references/latexml_source.md:54`）、靠手放，用了 1h08m |
| B 译后插入工具 | 译文完成后由工具插锚点 | 拒绝：中文译文里找不到宿主文字，只能靠块序对应，等于再造一套映射 |
| C 解析时写入 | 锚点写进 `source.md`，译者像 `[IMG]` 一样原样保留，核验比对两侧 | 采用：与 API 家族做法一致（11-14 设计 §7），新增机制只有写出一步 |

R2 的译注页文本回退在实施中连续两轮出现问题，重审见 §5.3。

## 4. R1 两段切分匹配

### 4.1 现状（`verify_pdf.py:2996`，现有代码）

```python
def subsequence_in_window(needle, haystack, start, end):
    budget = len(needle) * 4 + 60
    j = 0
    for i in range(start, min(end, start + len(needle) + budget)):
        if haystack[i] == needle[j]:
            j += 1
            if j == len(needle):
                return i + 1
    return None
```

`check_blocks`（`:3012`）先 `pdf.find(needle, position)`，失败后调用上面的函数，再失败就记 `text-missing`。

### 4.2 改动（`verify_pdf.py`）

新函数放在 `subsequence_in_window` 之后，由 `check_blocks` 在两步都失败后调用：

```python
def split_match(needle, pdf, start, end):
    """片段切成前后两段，两段各自逐字连续、按序出现，后段整体落在前段
    所在页或下一页内。返回 (消费结束位置, 前段页序号, 后段页序号) 或 None。"""
    for k in range(1, len(needle)):
        head, tail = needle[:k], needle[k:]
        head_at = pdf.norm_text.find(head, start, end)
        if head_at < 0:
            break                      # 更长的前段同样找不到
        page = pdf.page_of_offset(head_at)
        last = min(page + 1, len(pdf.page_offsets) - 1)
        limit = min(end, pdf.page_offsets[last][1])
        tail_at = pdf.norm_text.find(tail, head_at + k, limit)
        if tail_at >= 0:
            return tail_at + len(tail), page, pdf.page_of_offset(tail_at)
    return None
```

`check_blocks` 命中时追加 relaxed，`reason` 为“片段被数学字形或页缝分为两段，各段逐字齐全且顺序一致”，并写前段与后段所在页码。页码用 `PdfFacts.page_of_offset`（`verify_pdf.py:1921`）。

### 4.3 为什么这样

- AutoInt 第 7/8 页、HSTU 第 34/35 页都是页缝：前段在页末，后段在下一页开头，中间夹着整页数学字形。同页内超预算的穿插也满足同一规则，不需要第二条。
- 不扩大窗口预算：预算越大越容易放过真实缺字。
- 前段从游标起找第一次出现，后段限定在两页内，缺字、换字、乱序都会让某一段找不到而失败；放行的情况一律进视觉复核。

## 5. R2 译注剩余文字按公式切段

### 5.1 现状（`verify_pdf.py:1621`、`:1715`，现有代码）

```python
        value = normalize(block.get_text(' ', strip=True)) if block else ''
        if len(value) >= 4:
            remainders[line] = (value, '/' + block.name.capitalize())
```

```python
        for text, where in candidates:
            if where["pdf_object"]["role"] != role:
                continue
            if remainder in text:
                break
```

剩余文字整串要求出现在同一 PDF 对象中；含行内数学时，KaTeX 字形插在句中，整串永远找不到。

### 5.2 改动（`verify_pdf.py`）

1. `_note_remainders` 改为保存 `[normalize(s) for s in exporter.block_text_segments(block) if normalize(s)]`（`export_pdf.py:2985`，已按 `data-tex` 节点切段），总长不足 4 字时仍跳过。
2. 核对时把各段按序在对象文本里查找（`str.find` 逐段推进起点）；全部找到即通过。
3. 同一对象内找不到时，在含首段的页及其下一页的页文本里按同样方式核对：
   - 段落等宿主：两页文本按序齐全，而且单页文本不能完整解释（剩余文字确实跨页）才通过。同一页内被拆成两段的仍然失败。
   - 表格宿主（`/Table`、`/Td`、`/Th`）：两页文本按序齐全即通过，不要求跨页。窄列会在标识符中间折行（cuSPARSE 的 `bsrEndPtrA`），单元格文字分散在多个文本对象里，单页内按序齐全是合法排版。

   仍找不到报 `translator-note-collateral`，定位信息不变。

表格单元格的译注宿主沿用现有归属（`verify_pdf.py:1608` 的表格 token）。限制：表格宿主按页核对时，同一页别处恰好有相同文字，可能掩盖单元格内的删改；整行删改由文本覆盖检查以 `text-missing` 拦住。

### 5.3 回退规则的机制重审

- **根因**：对象级核对用来确认译注删掉后，剩余文字还在同一个块里。页文本回退是对“同一对象”的近似，实施中的两轮问题都出在这个近似上：不加条件时，同一页内被拆成两段的损伤会被放过；对所有宿主都要求跨页时，表格单元格又会误报，因为单元格文字本来就分散在多个文本对象里。
- **场景**：段内有公式、表格窄列折行、没有公式的长段落跨页都通过（跨页一项在第 1→2 页实测，删去一个词即失败）；删词、换字失败；同一页内被拆成两段只能靠对象级核对加跨页条件查出。
- **方案比较**：
  - A：按宿主角色区分回退条件（§5.2 第 3 条）。
  - B：把表格单元格的对象取字修正确，让表格不再需要页文本回退。需要先弄清 Chromium 给表格打的结构标记，超出本批范围。
  - C：去掉对象级核对，只靠页文本和 `text-missing`。会丢掉“同一页内拆段”的检出。
- **结论**：采用 A。这一机制再出现问题时改做 B，不再在 A 上增加条件。

## 6. R3 锚点

### 6.1 解析时写锚点（`_latexml_source.py`）

`LatexmlAdapter.adapt` 开始时调用 `reference_anchor_targets(raw_html, section_id)`，只取其中的目标 id 集合；写法由写出该节点的方法决定，不用该函数给的角色（C2：公式目标被归为 `table`、节标题目标被归为 `paragraph`，见 §10）。各写出处在其节点或子孙节点的 id 命中时，按下表写锚点：

| 宿主 | 写出处 | 写法 | ULTRA-HSTU 实例 |
| --- | --- | --- | --- |
| 段落 | `_paragraph_host`（`:1677`） | 段首行内：`<a id="S1.p3.1"></a>然而……` | 26 |
| 公式（`ltx_equation` 表内的 `tbody` 等） | `_math_group`（`:1709`） | 并入式号行：`<a id="S3.E1"></a>(1)` | 4 |
| 图、作为浮动体的表 | `_figure`（`:2203`） | 独占一行，后接空行 | 19 |
| 节（`section.ltx_section` 等） | 节标题写出处 | 独占一行，后接空行再写标题 | 6 |
| 参考文献 | `_biblist`（`:1870`） | 条目行首行内 | 29 |
| 脚注 | `_footnote_def`（`:2030`） | 定义体内：`[^1]: <a id="…"></a>正文` | 0 |
| 表格单元格 | `_table_simple`、`_table_complex`（`:1798`、`:1813`） | 格内文字前 | 0 |

写法与 E1 A.1、D.2 以及 W2 修复后的实际形态一致，导出（`export_pdf.py:2653` 的 `parse_anchor`）不需改动。段落一律写行首：W2 中 24 个段锚写成独占一行也通过了，但跨页长段只有行首能通过（E2 R12 UH 补证），统一写法更简单。`reference_anchor_targets` 报为未解决的目标（重复 id、范围外）不写，仍按现状进入候选的 `unresolved`。脚注与单元格两类在 ULTRA-HSTU 中没有实例，实施时用 DIN（脚注）验证。

### 6.2 源对账把空锚点当零宽（`_source_reconcile.py`）

在 `reconcile_latexml_to_markdown`（`:3882`）入口处理，内部逻辑不改：

1. 先用原 Markdown 核对依据声明的 `markdown` 身份（sha256 与行数），不符直接报错。
2. 去掉全部空锚点：独占一行的连同其后的空行一起去掉，行内的只去掉锚点本身；同时得到旧偏移到新偏移的映射。
3. 把依据副本里的 `md_start`、`md_end` 按映射换算，`markdown` 身份换成去锚文本的值，交给原对账逻辑。

适配器写出的依据区间约定：行内锚点计入所在对象，独占一行的锚点不属于任何对象。§10 C1 已在副本上实测这一做法。

不改 `_latexml_md_stream` 的逐行扫描：在入口一次去锚，比在扫描和文字读取两处分别处理更少、也不影响其他调用方。

### 6.3 译文核对锚点（`_api_navigation.py`、`verify_reference_translation.py`）

`compare_anchors`（`_api_navigation.py:420`）现在只认 `ANCHOR`（独占一行），并被 API 家族的 `verify_api_translation.py:166`、`recover_work_packages.py:132` 和通用的 `verify_translation.py:102` 调用。加参数 `inline=False`，默认行为不变；`inline=True` 时同时读取行内空锚点（跳过代码围栏与行内代码），按序比较每个锚点的 `(id, 写法, 是否与前一个锚点在同一块)`，写法分独占一行、行首、行中、式号行、脚注定义、表格格内。块序号只写进差异消息帮助定位，不参与比较：译文块数和解析稿本来就不同（ULTRA-HSTU 译文 337 块、解析稿 291 块），按块序号比较会让合法译文失败。两侧任何差异报“来源锚点 ID、顺序或所属对象改变”，并给出首个差异锚点的期望、实际与源块、译块号。只有 `verify_reference_translation.verify` 以 `inline=True` 调用。源侧没有锚点时返回空，旧项目不受影响。

删除锚点、改写法、调换顺序、挪进其他锚点所在的块都会失败。限制：锚点被挪到相邻、原本没有锚点的块时查不出，链接会跳到相邻的块。

### 6.4 目的地窗口不计宿主字形（`verify_pdf.py:4976`）

现有代码：

```python
        preceding = [event["baseline_y_pt"] for event in pdf.drawn_events[page]
                     if event["text"].strip() and event["baseline_y_pt"] > y0+rounding]
```

改为：先 `own = {id(event) for _, event in runs}`（`runs` 为同函数入参 `expected` 中的宿主字形），列表推导加条件 `id(event) not in own`。

### 6.5 兼容

- 用新版重新解析的论文，`source.md` 多出锚点行；旧译文要补上同样的锚点才能通过 §6.3 的核对。旧 `source.md` 不含锚点，不触发核对。
- API 家族与通用核验的锚点比较不变：它们继续以默认的 `inline=False` 调用 `compare_anchors`。
- `references/latexml_source.md:54` 改为“解析稿已写锚点，译文原样保留”，删去手放说明。

## 7. R5 KaTeX 宏表与只渲染公式

### 7.1 现状（`export_pdf.py:3831`，现有代码）

```javascript
      katex.render(n.dataset.tex, n,
                   {displayMode: n.dataset.mode === 'display',
                    throwOnError: true, strict: false, output: 'htmlAndMathml'});
```

`CHECK_SCRIPT` 是 Python 字符串，没有宏选项。W2 为加 `\textsc` 改这段字符串，转义层数来回 17 步。

### 7.2 改动（`export_pdf.py`）

1. `--katex-macros <json>`：文件内容为 `{"\\textsc": "\\text"}` 形式的对象。`build_document` 用 `json.dumps` 把宏表写成页面里的 `window.__katexMacros = {...};`（`</` 转义为 `<\/`），`CHECK_SCRIPT` 渲染每个公式时传 `macros: Object.assign({}, window.__katexMacros || {})`；宏表不拼进脚本源码，不需要手写转义。`data-tex` 不变，`verify_pdf` 的公式对账不受影响。导出报告写入宏表内容与文件 sha256。
2. `--check-math`：按正式导出的同一口径解析各章。带 `--source-adaptation` 时，解析前先调用 `apply_source_math_context`（与 `export()` 相同），公式按来源依据的类型与原表达式渲染；不带依据时，`classify_math`（`export_pdf.py:2051`）会把含 `split` 等环境的行内公式提升为显示公式，结果与带依据的导出不同，所以 LaTeXML 论文要带上与导出相同的 `--source-adaptation`。然后只生成含全部 `data-tex` 节点的最小页面，跑同一个 `CHECK_SCRIPT`，打印全部失败公式（输入文件与行、节点 id、TeX 前 80 字、KaTeX 消息），末行给出公式总数与失败数，退出码 0/1；不排版、不出 PDF、不写导出报告，不需要 `--output`、`--work-dir`。可与 `--katex-macros` 同用。文字版 PDF 来源的确认数学随交付记录装配，不经本预检，以正式导出为准。
3. 失败消息匹配 `Undefined control sequence: \X` 时，追加一行“可在 `--katex-macros` 中把 `\X` 映射为 KaTeX 支持的命令”。

`verify_pdf` 不新增参数：它读取导出报告中的 `browser_checks.katex`（`verify_pdf.py:4651`），宏表已在导出时生效。

## 8. R9 诊断与输出

### 8.1 证据缺位只报根因（`verify_pdf.py:5440`）

现有代码在 `report_usable` 为假时记一条 `export-evidence-missing` 后继续执行，后续检查拿到空报告，再报十几类不符。改为：这一条的消息写明“`<work-dir>/export_report.json` 不存在或不可解析；请在同一 `--work-dir` 先运行 export_pdf，再核验”；后续检查照常执行，使核验报告保持 `verify_delivery` 读取的固定结构，构造报告前只保留这一条失败。work-dir 不存在时，`main` 先创建它再写核验证据。

### 8.2 work-dir 转绝对路径（`export_pdf.py:4114`）

`export()` 入口第一行 `work_dir = Path(work_dir).expanduser().absolute()`；`verify_pdf.py:5428` 同样处理，两侧口径一致。

### 8.3 差异全量交给入口（`_latexml_source.py:2589`）

现有代码：

```python
        if diffs:
            raise ValueError('%s切片 #%d 与原始快照完整对账失败（不降级）: '
                             '%s' % (label, index, '；'.join(diffs[:5])))
```

改为：抛 `ReconcileError(ValueError)`，属性 `diffs` 保存全部差异，消息为“共 N 处差异”加归类计数和每类前 3 条。归类方法：把差异文本中的数字与 `name[n]` 形式的节点 id 替换为占位符，相同模板计为一类。`export_pdf`、`verify_pdf` 捕获后把全部差异写到 `<work-dir>/reconcile_diffs.txt` 并打印路径。

### 8.4 告警默认汇总（`verify_reference_translation.py:490`）

失败项照常逐条打印；告警按 §8.3 的模板归类，打印每类计数和前 3 条。加 `--verbose` 时恢复逐条打印。退出码不变。

### 8.5 `SKILL.md`

在执行约束中加一句：核验、导出和对账的长输出先写文件，读摘要和失败项，不整段读回对话。

## 9. R16 参考文档与参数检查

1. `references/latexml_source.md` 与 `references/pdf_export.md` 为 `parse_reference_html`、`verify_reference_translation`、`export_pdf`、`verify_pdf` 各写一个论文场景的最小命令，并写明：图片身份映射是 `{"digests": [...]}`，按出现顺序列出资源身份摘要；源资源能从源 Markdown 目录解析时可以省略；`--source-adaptation` 必须紧跟依据 JSON 路径，可重复。
2. `_verification.extract_source_adaptation`（`:874`）：`--source-adaptation` 后面的值以 `--` 开头时报错“--source-adaptation 缺少依据路径”，不再把下一个参数当路径吞掉。

## 10. 设计期验证（2026-11-16 已完成）

探针脚本与运行环境在 Git 工作区外（会话临时目录），只读项目与组件文件；解释器为 `~/.venvs/tech-doc-translator/bin/python`。

| 编号 | 验证内容 | 结果 | 对设计的影响 |
| --- | --- | --- | --- |
| C1 | ULTRA-HSTU 的 `source.md` 写入 21 个空锚点（段首 10、图前独占一行 5、式号行 3、文献行首 3），依据区间按 §6.2 约定平移 | 现行对账报 294 处差异（段落文字不符等）；在组件副本的 `reconcile_latexml_to_markdown` 入口按 §6.2 去锚后为 0 处；带锚点文本里删一个词（`prominent`）仍报 2 处 | 成立。§6.2 由“逐行扫描与文字读取两处处理”改为“入口一次去锚” |
| C2 | `reference_anchor_targets` 在 ULTRA-HSTU 快照上的目标与角色，对照交付译文实际放的锚点 | 84 个目标、0 个未解决；全部能对上一个写出处。公式目标的角色是 `table`（节点为 `ltx_equation` 内的 `tbody`），6 个节目标的角色是 `paragraph`（节点为 `section`）；译文多出的 `S4.F5` 不是任何链接的目标 | 成立。§6.1 改为按写出方法决定写法，不用该函数的角色；脚注、单元格两类本篇没有实例 |
| C3 | 宏表 `{"\\textsc": "\\text"}` 作为 `page.evaluate` 参数传入，用组件的 `katex.min.js` 渲染 ULTRA-HSTU 与 Hiformer 的两个 `\textsc` 公式 | 无宏表时两式都报 `Undefined control sequence: \textsc`；参数传入后两式都渲染成功，普通公式不受影响；宏值写错（`\nosuchcmd`）时报错 | 成立。§7.2 的宏表对象与 KaTeX 调用与此相同 |

## 11. 直接验收与测试

沿用需求第 3 节各条验收。测试样本取自 ULTRA-HSTU、AutoInt、Hiformer、DIN、cuSPARSE 的真实片段，合法与损伤样本成对，放在 Git 工作区外。

| 需求 | 合法样本通过 | 损伤样本失败 |
| --- | --- | --- |
| R1 | AutoInt 第 7/8 页、HSTU 第 34/35 页，登记 relaxed | 删一个字、调换两段 |
| R2 | Hiformer 含数学的译注段、cuSPARSE 表格单元格译注 | 删掉剩余文字中一个词 |
| R3 | ULTRA-HSTU 重新解析后，译文保留锚点，导出内部链接检查一次通过；Hiformer 式号后释文段 | 删一个锚点、改锚点写法、调换两个锚点、把锚点挪进其他锚点所在的块 |
| R5 | 带 `--source-adaptation` 的 `--check-math` 一次列出 DIN 155 个公式中的全部失败，公式类型与正式导出一致；带宏表导出 ULTRA-HSTU 通过，公式对账不变 | 未登记的宏仍失败并给出建议；LaTeXML 行内 `split` 不带依据时预检通过，带依据时预检报错 |
| R9 | ULTRA-HSTU 缺 `export_report.json` 时只报一条；相对 work-dir 导出成功；STCA 表格失败出现在第一次运行的归类计数里 | — |
| R16 | 按文档第一次就给对 `--image-map`、`--source-adaptation` | `--source-adaptation --image-map x` 报缺少路径 |

另跑现有全量回归，失败集合与改动前相同。

## 12. 不做的事

- 不扩大 `subsequence_in_window` 的预算，不加跨页通用模糊匹配。
- 不提供译后插锚点的工具，不保留执行者手放锚点的流程说明。
- 不给 `verify_pdf` 加宏表参数，不把用到宏的公式额外列为复核项（视觉复核已覆盖全部公式）。
- 不改核验输出的退出码和报告文件格式；不新增阶段耗时汇总（11-07 设计 §100 已有逐阶段耗时）。

## 13. Karpathy 精简与自检

1. **基线**：第 3 节列出了改动依赖的现有接口与行号；读过需求、11-07 与 11-14 设计、上述源码，以及 W2 中 ULTRA-HSTU 项目的 `source.md`、译文锚点与项目脚本。第 1 批实施（`0bba2d6`）的评审补跑了执行方未能运行的回归，并做了三个探针：行内 `split` 在预检与带依据导出两条路径上的公式类型、组件 KaTeX 对行内 `split` 的报错、无公式长段落跨页时的译注核验。
2. **假设与差异**：§3.2 的三处差异只缩小实现范围；§10 的 C1–C3 已在副本上实测成立。§5.2 表格宿主的页文本回退与 §6.3 的同块核对是实施中按真实样本确定的规则，2026-11-17 批准，代价写在对应节；§7.2 的预检读取来源依据，使预检与正式导出的公式类型一致，不改变需求。脚注与单元格锚点在 ULTRA-HSTU 中没有样本。会改变的行为是 R3 的 `source.md` 多出锚点（§6.5）和 R9 的默认输出变短（`--verbose` 可恢复）。
3. **最小方案**：
   - R1 一条规则覆盖页缝与长穿插，拒绝扩大预算。
   - R2 复用已有切段函数，拒绝照搬无效的补丁；页文本回退按 §5.3 重审选方案 A。
   - R3 比较了三种方案（§3.3），选新增机制最少、且有先例的 C；核对口径用同块关系，不另建块对应映射。
   - R5 的宏表以 JSON 写入页面，消除转义问题本身，不给核验侧加参数；预检复用导出已有的 `apply_source_math_context`，不新增机制。
   - R9 用文本模板归类，不改产生差异的各处代码。
   - 没有比这更简单、又能满足需求的做法。
4. **删除审计**：每节对应一条需求；评审时删去了“`verify_pdf` 列宏公式为复核项”“阶段耗时汇总”“译后插锚点工具”三项；§12 列出不做的事，没有为显得完整加的内容。
5. **直接验收**：第 11 节每条用真实项目片段证明用户可观察的结果（合法译文一次通过、执行者不再手放锚点、预检与导出报出同一批公式失败、缺证据只报一条根因），损伤样本证明检出能力没有削弱。

## 14. 最终实施验收（2026-11-17）

第 1 批实施（tickets 01–06）完成真实样本最终验收，逐项结论见[需求 §7](./2026-11-16-paper-pdf-delivery-backlog-requirements.md#7-最终验收结论2026-11-17)。

- 实施与 V0.1 的三处差异已并入 V0.2：§5.2 页文本回退按宿主区分（段落真页缝、表格页粒度，含 §5.3 机制重审）；§6.3 锚点比较以“是否与前一个锚点同块”代替绝对块序号；§7.2 预检带 `--source-adaptation` 时经 `apply_source_math_context` 与正式导出同口径（评审修复）。
- 已知限制与待办同 CHANGELOG“未发布”：锚点挪到相邻、原本没有锚点的块时参考家族核验查不出；表格单元格译注按页核对时同页别处的相同文字可能掩盖单元格内的删改，整行删改仍报 `text-missing`；文字版 PDF 来源的确认数学不经 `--check-math`；需求 §6 整体验收（agent 时间不超过 3 小时）待共享安装重装后实测。
