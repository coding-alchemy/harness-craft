# API 文档解析与源对账缺陷修复设计

| 元数据 | 内容 |
| --- | --- |
| 文档版本 | V0.5 |
| 文档状态 | 2026-11-22 批准（含 D5 与 R6 `$ 5` 现行行为澄清）；2026-11-23 完成除两项外的验收；2026-11-24 两项收束并按评审修正 §5；2026-11-26 验收完成（见 §15） |
| 创建 / 修订日期 | 2026-11-20 / 2026-11-26 |
| 适用范围 | `tech-doc-translator` 的 API 文档解析（`parse_api_html.py`、`_html_fidelity.py`）、源对账（`_source_reconcile.py` 与 `_api_navigation.py` 的锚点核对）、数学定界扫描（`_verification.py`）、四个 HTML 解析入口的快照完整性检查，以及拆包与 API 核验的输入检查 |
| 权威需求 | [API 文档解析与源对账缺陷修复需求](./2026-11-20-api-parse-reconcile-fixes-requirements.md) V0.6（2026-11-22 批准，D1–D4 与 R6 `$ 5` 现行行为澄清） |
| 基线 | `zn_dev` @ `3c8a4df`（与 main、共享安装相同）。文中行号都指该提交；`scripts/` 下的文件只写文件名 |

## 1. 改动总览

| 需求 | 改哪里 | 做法 | 规模 |
| --- | --- | --- | --- |
| R1 | `_source_reconcile.py` 的 `terms()` | 定义区里的空行不结束定义区；术语只认紧接上一行写出的 `**…**` 行 | 约 +5 行 |
| R2 | `_html_fidelity.py` 的 `rich_container_lines`；`parse_api_html.py` 的 `render` | API 家族把 `source_anchor_ids` 交给富容器，表格、标题、提示框分支先写锚点；直接嵌在列表里、带 id 的 `<pre>` 不写（D2） | 约 +10 行 |
| R3 | `_html_fidelity.py` 的 `HtmlFidelity`、`table_block`；四个 HTML 解析器的 `render`；`_source_reconcile.py` 的 `table_records` 与公式、行内代码、图片地址三条流的读回（`_tagged_math`、`_tagged_inline_code`、`_tagged_images`）；翻译约定 | HTML 家族的解析把格内的 `\|` 写成 `\\|`，对账在不带来源依据时按 GFM 表格语义把 `\\|` 读回 `\|`；LaTeXML 的写出与对账不变 | 约 +40 行 |
| R4 | `_source_reconcile.py` 的 `table_records` | 首行是空格位时也进入单列模式 | +1 行 |
| R5 | `_source_reconcile.py` 的 `list_records` | 记住 dd 内嵌列表最外层标记的列深，续段按列表续行归属 | 约 +14 行 |
| R6 | `_verification.py` 新增 `is_literal_dollar`；`_html_fidelity.py` 的 `render_inline`；`_source_reconcile.py` 的 `_literal_math_issues`、`_norm_text`；翻译约定 | 紧贴标识符、不配对的 `$` 在解析稿里写成 `\$`，源侧不算残缺公式（D3），但它在所在块里与别处的 `$` 配成公式时照旧阻断（§8.5）；阅读把 `\$` 还原为 `$` | 约 +45 行 |
| R7 | `_html_fidelity.py` 新增 `require_complete_html`；四个 HTML 解析入口的 6 处快照读入 | 整页快照必须以 `</html>` 结束，读入前按字节检查 | 约 +16 行 |
| R8 | `parse_api_html.py` 失败分支；`_verification.py` 的 `summarize_messages`；`split_work_packages.py`、`verify_api_translation.py`；`references/workflow_helpers.md` | 第一屏按差异类型归类；全部差异与被拒解析稿写到临时目录；拆包与 API 核验拒收 `.rejected.md` | 约 +30 行 |

只改组件，不加新命令、新参数或新文件格式。PTX 冻结副本与 Tile IR 运行时包装属于项目，组件修好、重装后不再需要，本设计不改它们。`table_block`、`render_inline` 与对账的 Markdown 读取被多个家族共用，各条改动在哪些家族生效见 §12.1。

## 2. 原型验证

在工作区外用 `git archive` 解出的基线代码（`3c8a4df`）副本上实现了 R1–R7 的拟改代码与 §8.5 的块级配对检查（第 3–9 节），R8 用同一批差异离线验证了归类口径。下表、本节的回归与 §11、§12.3 的结果都在这个最终原型上跑过。

| 样本 | 现行版本 | 原型 |
| --- | --- | --- |
| PTX `repro_add_section.html`（R1） | 3 条差异 | 通过 |
| PTX `changes-in-ptx-isa-version-8-8` 一节（R2） | 1 条 | 通过 |
| PTX 常量表达式规则表、lop3 表（R3） | 各 1 条 | 通过 |
| PTX `causality-axiom` 一节（R4） | 7 条 | 通过 |
| PTX `mma`、`sparse-mma` 两节（R5） | 5 条、4 条 | 通过 |
| PTX 全文派生快照 | 177 条 | 通过，写出 39,656 行解析稿，按 `chars:20000` 拆包得 93 个包；解析加对账 34 秒（现行版本 29 秒，见 §14 第 4 条） |
| Tile IR 13.5 `release_notes.html`（R6） | 6 条 | 通过 |
| Tile IR 13.4 截断的 `operations.html`（R7） | 退出 0 | 报截断 |
| 合成样本：两段 dd；dl 嵌在列表项里接同项段落；列表项里 dl 之后接选项卡；dd 以代码块、提示框、两段列表项结束后接术语；带 id 的表格嵌在 li、dd 里；dd 里列表后接段落；`<article>` 片段 | 两段 dd、dd 以代码块或提示框或两段列表项结束、两种嵌套表格、dd 列表样本失败，其余通过 | 全部通过 |
| 合成样本：被 `<sup>`、`<em>` 切开、两段都紧贴标识符的公式 3 个（§8.5） | 报未解决数学定界 | 照旧阻断（块级配对检查） |

原型上另做的检查：

- 损伤样本：§11 各条的损伤都被查出：R1 报“定义列表数量不一致”，R2 报“锚点目标错绑”，R3 报格内行内代码不一致，R4 报“格内代码坐标重复”，R5 报列表项内容不一致；Tile IR 13.5 `release_notes` 的解析稿含 3 处 `\$`，去掉其中一处的反斜线后扫描报未闭合；正文 `$x` 照旧阻断。
- 截断：单页、分页入口与参考手册入口的三种用法都报截断、不写解析稿，截在多字节字符中间的样本同样报截断（§9）。
- LaTeXML：简单表格格内的文字、代码、公式，以及段落、清单、列表里的 `$`，8 个样本两版结果相同（§5.3）。

现有 API 快照回归：知识库与 `machine-learning.local` 里 CUDA PG、Best Practices、cuBLAS、cuSPARSE、cuTile Python、PTX、Tile IR 的 218 个整页快照，两个版本各解析一次。现行版本通过 178 页，原型通过 184 页：

- 176 页两版都通过，解析稿逐字节相同。
- `cutile_python/source/generated/cuda.tile.mma.html` 两版都通过，解析稿只差一处：表格格内 `[u|i]8` 写成 `[u\|i]8`（R3）。
- 由失败变通过 7 页：PTX 全文，Tile IR 13.4 `types` 与 13.5 `appendix`、`operations`、`prog_model`、`release_notes`、`types`。
- 由通过变失败 1 页：截断的 Tile IR 13.4 `operations.html`（R7）。
- 两版都失败的 33 页，差异条数一页不差：8 页是含 `<nav>` 的目录与导航页，10 页含 `colspan`/`rowspan` 或嵌套表、需要 `--expand-tables grid` 或项目适配，15 页是对账差异（CUDA PG 搜索页 1 页，cuTile Python 14 页）。cuTile 的 14 页另有一份会话问题记录（`machine-learning.local/CUDA/cutile_python/docs/问题记录_解析对账阻断_20261120.md`），所列缺陷本批完成后另开一批处理（需求 §5）。

现有解析稿用新对账器重读、LaTeXML 论文重新解析的结果见 §12.3；全量 pytest 与集成脚本见 §11。

## 3. R1 定义条目有多段时不漏项

### 3.1 现状（现有代码，`_source_reconcile.py:1820-1844`）

```python
    def terms(self):
        pairs = []
        in_def = False
        for line_no, line in enumerate(self.lines, start=1):
            if line_no in self.fenced:
                continue
            if line.strip() == '[DEF-LIST]':
                in_def = True
                continue
            if not in_def:
                continue
            if not line.startswith(' '):     # 空行也走到这里，定义区提前结束
                in_def = False
                continue
            s = line.strip()
            if re.match(r'^\[[A-Z]', s) or s.startswith('#'):
                in_def = False
                continue
            m = re.match(r'^\*\*(.+?)\*\*\s*(.*)$', s)
            if m:
                pairs.append(...)
```

对账用 `terms()` 读解析稿的定义列表。解析端写 dd 时（`definition_list`，`_html_fidelity.py:1369-1394`，内容由 `rich_container_lines` 输出），术语行是首段写在 `  **术语** ` 前缀之后（`_html_fidelity.py:1048`、`:1064`），紧接上一行；dd 里的后续段落、选项卡标签、表格等块都以换行开头（如 `:1069`），前面是空行。

### 3.2 改动（拟改代码，同一函数）

```python
        in_def = False
        previous_blank = False
        for line_no, line in enumerate(self.lines, start=1):
            after_blank, previous_blank = previous_blank, not line.strip()
            if line_no in self.fenced:
                continue
            ...（[DEF-LIST] 与 in_def 判断不变）
            if not line.strip():
                continue  # dd 多段之间的空行属定义内容，不结束定义区
            if not line.startswith(' '):
                in_def = False
                continue
            ...（结构标记判断不变）
            m = re.match(r'^\*\*(.+?)\*\*\s*(.*)$', s)
            # 术语行紧接上一行写出；dd 里空行之后的 **…** 行是块内容（如选项卡标签）
            if m and not after_blank:
                pairs.append(...)
```

### 3.3 为什么不只跳过空行

PTX 冻结副本的补丁 A 只加了“空行跳过”。这会把空行之后的 `**[Tab: …]**` 选项卡标签读成术语，造出新的失败：

- 现有用例 `test_api_containers.py` 的 `test_nested_sd_tabs_list_and_definition`（dd 里有两个选项卡）报“定义列表数量不一致 1 项对 3 项”；
- 合成样本“列表项里 dl 之后、空一行接同项选项卡”报 1 项对 2 项，现行版本这两处都通过。

按 `[DEF-LIST]` 的缩进判定定义区结束也不行：选项卡在 dd 里时与术语行同缩进，上面的现有用例照样失败。“术语行前面没有空行”来自解析端的写法本身：上述三个样本、dd 以代码块或提示框结束后再接术语的样本（现行版本报 3 项对 1 项）与 PTX 全文都通过。现有的结构标记判定（`^\[[A-Z]` 结束定义区）不动：它会把 `[Dtypes](…)` 这种大写开头的链接误当结构标记，但随后的嵌套 `[DEF-LIST]` 会重新进入定义区，现有页面（如 cuTile `data.html`）都靠这条路径通过。

### 3.4 需求外的已知形态

下面两种形态，现行版本与原型的结果相同，本设计不处理：

- dd 里有表格，同一 dl 里其后还有术语：`[TABLE]` 是结构标记，照旧结束定义区（需求 R1 保留了这条），后面的术语漏读，报“定义列表数量不一致”；单列表格还会把后面的术语行读成表格行。218 页快照里没有这种形态。
- dd 里嵌着 dl，同一 dl 里其后还有术语：报定义列表逐项错位。218 页里只在 cuTile `data/array.html` 出现 2 处，属于 cuTile Python 会话问题记录的范围，本批完成后另开一批处理。

## 4. R2 列表项与定义条目里的带 id 表格写出锚点

### 4.1 现状（现有代码）

`parse_api_html.py:147-149`，顶层块入口写锚点：

```python
        name, cls = child.name, ' '.join(child.get('class') or [])
        for anchor in source_anchor_ids(child):
            out.append('\n<a id="%s"></a>\n' % escape(anchor, quote=True))
```

`_html_fidelity.py:1087-1095`，富容器（li、dd、details 等）的表格分支直接输出：

```python
            elif name == 'table':
                # 直接子级表格须按表格输出（同上，避免退化为单元格段落）
                if bullet and not first_text_done:
                    out.append(bullet.rstrip())
                    first_text_done = True
                before = len(out)
                out.extend(self.table_block(item))
                for idx in range(before, len(out)):
                    out[idx] = self._indented_block(out[idx], indent)
```

锚点核对要求的对象由 `_source_anchors` 认定（`_api_navigation.py:89-129`）：表格与标题不论嵌在哪里都要锚点；段落、行内图片嵌在 li/dt/dd 里时不要求（`:47-49`、`:116-117`）；提示框嵌在 li 里时不要求，嵌在 dd 里时要求（`:60-62`）。富容器里走 `render_block` 的块（figure、blockquote 等）会回到 `_render_children`，自己写锚点。缺锚点的是富容器的表格、标题、dd 里的提示框三个分支。

`rich_container_lines` 是各 HTML 家族共用的方法，单页、分页、参考手册三个解析器都不写 `<a id>` 锚点。

### 4.2 改动（拟改代码）

`_html_fidelity.py`，`HtmlFidelity.__init__`（`:696` 之后）：

```python
        self.block_anchor_ids = None  # API 家族提供：富容器内块对象的源 ID（缺省不写锚点）
```

`_html_fidelity.py`，`rich_container_lines`（`:1033` 之后）加一个局部函数，表格分支在 `before = len(out)` 之后、标题分支在输出标题之前、提示框分支在输出 `> **ADMONITION` 之前各调用一次；表格与提示框的锚点随分支已有的缩进循环一起缩进：

```python
        def emit_anchors(item):
            for name in (self.block_anchor_ids(item)
                         if self.block_anchor_ids is not None else ()):
                out.append('\n<a id="%s"></a>\n' % _html_escape(name, quote=True))
```

`parse_api_html.py:128-130`，`render` 与已有的 `inline_image` 同样注入：

```python
def render(node, out, fidelity):
    fidelity.inline_image = lambda img: _image_inline(img, fidelity)
    fidelity.block_anchor_ids = source_anchor_ids
    _render_children(node, out, fidelity)
```

用 `source_anchor_ids` 而不是 `item.get('id')`：它与顶层写锚点、与 `_source_anchors` 的认定是同一套判断（段落、提示框嵌在列表里时返回空），写出的锚点正好是核对要求的锚点。

### 4.3 为什么不照搬补丁 B

冻结副本的补丁 B 在表格分支里无条件写 `item['id']`。`rich_container_lines` 被四个 HTML 解析器共用，照搬会让单页、分页、参考手册家族的解析稿也多出锚点行，改变它们的输出与对账。本设计沿用 `inline_image` 的做法，由 API 入口注入，其他家族的输出不变。

### 4.4 直接嵌在列表里、带 id 的 `<pre>` 不写锚点（D2）

Sphinx 把代码块的 id 写在外层 `div.highlight-*` 上。富容器把这层 div 交给 `render_block`，`_render_children` 经 `pre_anchor_ids` 写出锚点（`parse_api_html.py:136-141`），这种代码块在列表项、定义条目里时现行版本已经写锚点、核对通过（原型实测）。

不写锚点的只有直接嵌在列表项或定义条目里、自身带 id 的 `<pre>`：`_block_sequence` 把它的占位换成围栏字符串时没有保留占位节点（`_html_fidelity.py:912-947`），要写就得改这个三处共用的序列格式。218 页 API 快照里没有这种 `<pre>`；遇到时解析照旧报“缺来源对象锚点”，不会静默通过（原型实测）。

## 5. R3 表格格内的 `|` 不破坏列界

### 5.1 现状（现有代码）

`_html_fidelity.py:1301` 与 `:1309`，普通 `[TABLE]` 行：

```python
                cells.append(self.render_inline(cell, escape_backslashes=True))
            ...
            line = ' | '.join(cells)
```

`_source_reconcile.py:1731`，对账按 ` | ` 切格；`:1744-1750` 单列行整行作一格；`:1352-1360` 行内代码事实逐行取代码跨度，表格行与正文同样处理。

显式网格模式已把格内 `|` 写成 `\|`（`_html_fidelity.py:1338`）。译文核验时，译文表格行内公式的 `\|` 由 `table_math_spans`（`_verification.py:707-714`）按真实表格行归一，译文表格的单元格由 markdown-it 读取，`\|` 读作 `|`；这两处只作用于译文核验，解析时的源对账不经过它们——解析稿 `[TABLE]` 行里的 `\|`（格内文字、行内代码、公式与图片地址）须由对账读取端自己读回（§5.2）。

### 5.2 改动（拟改代码）

`_html_fidelity.py`，`HtmlFidelity.__init__` 加一个开关，`table_block` 的格位（`:1301`）按开关转义：

```python
        self.escape_table_pipes = False  # HTML 家族解析入口开启：[TABLE] 格内 | 写成 \|
        ...
                cell_text = self.render_inline(cell, escape_backslashes=True)
                if self.escape_table_pipes:
                    cell_text = cell_text.replace('|', r'\|')  # 格内 | 写成 \|，不破坏列界
                cells.append(cell_text)
```

四个 HTML 解析器的 `render` 开头各加一行 `fidelity.escape_table_pipes = True`（`parse_api_html.py:128`、`parse_single_page_html.py:51`、`parse_paginated_html.py:52`、`parse_reference_html.py:91`），与 API 入口注入 `inline_image` 的位置相同。LaTeXML 适配器（`_latexml_source.py:1907`）与 LaTeXML 对账重建简单表格（`_source_reconcile.py:4011`）也调用 `table_block`，它们用各自的 `HtmlFidelity`，开关保持关闭。

`_source_reconcile.py`，`table_records` 的多列与单列两处：

```python
            # HTML 家族的 [TABLE] 格内 \| 按 GFM 表格语义读作 |（含行内代码）；
            # LaTeXML 写出器不转义格内 |，带来源依据时照旧按字面读
            cells = line.split(' | ')
            if self._source_context is None:
                cells = [cell.replace('\\|', '|') for cell in cells]
            ...
                current['single_column'] = True
                if self._source_context is None:
                    line = line.replace('\\|', '|')
                current['raw_rows'].append([line])
                current['rows'].append([cell_reading(line)])
```

`_source_reconcile.py`，`_MarkdownFacts.__init__` 在读公式流之前算一次表格行集合；`_tagged_math`（公式）、`_tagged_inline_code`（行内代码）与 `_tagged_images`（图片地址）对集合内的行做同一读回：

```python
        self._table_row_lines = (
            set().union(*(r['row_lines'] for r in self.table_records()))
            if self._source_context is None else set())
        ...
                if line_no in self._table_row_lines:
                    content = content.replace('\\|', '|')  # 表格行内的 \| 是 |
```

写出端转义的是整格里的每个 `|`，公式与图片地址里的也在内，所以读取端这三条流都要读回；只读回格内文字与行内代码时，含 `|` 的格内公式或图片地址会被报成内容不一致。读回是单次、从左到右的替换，与 GFM 读法一致：`\\|x\\|` 读作 `\|x\|`。

拆包、计数与译文表格比较（`compare_translation_tables`）都经 `markdown_table_facts` 调用同一个 `table_records`，源与译文两侧按同一口径读回。

`references/translation_conventions.md:15` 改为：“译文使用真实 Markdown 表格，格内的 `|`（文字、行内代码与公式）都写成 `\|`，否则破坏列界；核验按 GFM 表格语义把格内的 `\|` 读作 `|`，表格外不归一。HTML 家族解析稿的 `[TABLE]` 行格内已写成 `\|`，原样保留；LaTeXML 论文解析稿的 `[TABLE]` 行格内仍是未转义的 `|`。”现行这一条只要求转义公式里的 `|`。

### 5.3 为什么两端都改，又只在 HTML 家族生效

只改解析端时，格数对上了，但对账按字面读 `\|`，常量表达式规则表报行内代码 `& \| ^` 与源里的 `& | ^` 不一致（原型实测）。`\|` 读作 `|` 是 GFM 表格的语法规则，markdown-it 导出时也这样读，所以 PDF 里显示为 `|`。

读回只在不带来源依据（`_source_context is None`）时进行。LaTeXML 写出器的 `[TABLE]` 行按字面写出格内文字，源格 `<code>a\|b  c</code>` 写成 `` `a\|b  c` ``，对账按字面与声明源格比较。不分家族读回时，现有用例 `test_latexml_footnote_table_boundaries.py` 的 `test_mapped_cell_leaf_roles_and_exact_content` 报“输出表 #1 格 (r=1 c=1) 与声明源格不符”（原型实测）。

写出端的转义也只在 HTML 家族开启。`table_block` 无条件转义时，LaTeXML 简单表格格内的行内代码 `` `a|b` `` 写成 `` `a\|b` ``，LaTeXML 对账按字面读代码，报“表格第 1 张第 1 行不一致”，现行版本这里通过（原型实测）。用开关后，LaTeXML 简单表格的格内文字、代码、公式，以及段落、清单、列表里的 `$`，共 8 个样本的结果与现行版本相同。LaTeXML 简单表格格内的文字 `a | b` 照旧破坏列界，这是现行版本已有的问题，不在本需求范围内。

开关在四个 HTML 解析器里都开启，单页、分页、参考手册家族表格格内的 `|` 同样写成 `\|`（D4），见 §12.2。

## 6. R4 只含代码的单列表格按单列表格读

现有代码（`_source_reconcile.py:1710-1716`）：

```python
            if not stripped and line:
                # 单列全空单元格行（渲染端以单个空格输出，与零长空行区分）
                current['raw_rows'].append([''])
                current['rows'].append([_norm_text('',
                                                   decode_heading_escape=True)])
                current['row_lines'].add(line_no)
                continue
```

拟改：在 `continue` 前加一行 `current['single_column'] = True`。只有单列表格才会出现整行空格位（多列行即使格都为空也有 ` | `），所以这一行不影响多列表。

不改成“单列行也写 `|`”：对账端本来就支持不带竖线的单列表格（`:1744-1750`），改写法会改变解析稿与译文的表格形态。

## 7. R5 定义条目里的列表项有多段时不丢续段

### 7.1 现状（现有代码，`_source_reconcile.py:1558-1576`）

```python
            if stripped in ('[DEF-LIST]', '[FOOTNOTE-LIST]'):
                if line.startswith((' ', '\t')):
                    def_region = len(line) - len(line.lstrip(' '))
                    continue
                def_region = 0
                ...
            if def_region is not None and line_no in marker_lines \
                    and len(line)-len(line.lstrip(' ')) <= def_region+2:
                def_region=None
            if def_region is not None and line_no not in marker_lines:
                ...
                indent = len(line) - len(line.lstrip(' '))
                if indent > def_region:
                    continue          # dd 内嵌列表项的续段也在这里被跳过
                def_region = None
```

另有子列表边界（`:1610-1615`）只在 `def_region is None` 时记入，dd 内嵌列表项自己的子列表边界因此也不记。

### 7.2 改动（拟改代码，同一函数）

```python
        def_list_indent = None  # 定义区内嵌列表最外层标记的列深（:1502 之后）
        ...
            if stripped in ('[DEF-LIST]', '[FOOTNOTE-LIST]'):
                def_list_indent = None
                ...
            if def_region is not None and line_no in marker_lines \
                    and len(line)-len(line.lstrip(' ')) <= def_region+2:
                def_region=None
                def_list_indent = None
            if def_region is not None and line_no in marker_lines:
                marker_indent = len(line) - len(line.lstrip(' '))
                def_list_indent = (marker_indent if def_list_indent is None
                                   else min(def_list_indent, marker_indent))
            if def_region is not None and line_no not in marker_lines:
                ...
                indent = len(line) - len(line.lstrip(' '))
                if def_list_indent is not None and indent >= def_list_indent:
                    pass  # dd 内嵌列表项的续段：按列表续行归属
                elif indent > def_region:
                    def_list_indent = None  # dd 自身段落：内嵌列表到此结束
                    continue
                else:
                    def_region = None  # 缩进回到标记层：内容区结束
                    def_list_indent = None
            ...
                if stack and level > stack[-1]['level'] \
                        and (def_region is None
                             or (def_list_indent is not None
                                 and len(match.group(1)) > def_list_indent)):
                    stack[-1]['seq'].append(('list', None))
```

解析稿把列表项的续段写在标记的同一列（`rich_container_lines` 的段落分支，`_html_fidelity.py:1059-1069`），续行由现有的 `target_at(indent >> 1)` 归到对应层级的列表项。

### 7.3 为什么不在任意列表标记处结束定义区

那样 dd 里列表之后的段落会被当成列表项的续段并进去，违反需求 R5 的后半句。合成样本“dd 里两条两段列表项，之后一段 dd 段落”用来区分这两种写法。PTX `mma` 一节的 `.f64` 列表项里还嵌着一层舍入修饰符列表，源侧在该项里记有子列表边界；边界条件只放宽到“比 dd 内嵌列表最外层更深的标记”，dd 自己的列表照旧不记入宿主项。

## 8. R6 HTML 正文里不配对的 `$` 按字面文字处理

### 8.1 现状（现有代码）

`_html_fidelity.py:878-889`，`render_inline` 对每个文本节点扫描公式，配对的 `$…$` 按公式保护，不配对的 `$` 原样写出：

```python
            masked = raw.replace(r'\[', 'xx').replace(r'\]', 'xx')
            spans = scan_math(masked).spans
            for span in reversed(spans):
                code_spans.append(raw[span.start:span.end])
                raw = (raw[:span.start] + _CODE_TOKEN_FMT % (len(code_spans) - 1)
                       + raw[span.end:])
            node.replace_with(raw)
```

`_source_reconcile.py:524-528`，源侧把 HTML 文本节点里同样的扫描问题登记为阻断：

```python
def _literal_math_issues(text):
    serialized = re.sub(r'\s*\n\s*', ' ', text)
    stripped = serialized.replace('\\[', 'xx').replace('\\]', 'xx')
    return list(scan_math(stripped).issues)
```

现有用例把这条阻断当合同：`test_html_math_fidelity.py:65-66` 与 `test_structural_invariants.py:826-831` 断言 HTML 正文里的 `$x` 阻断分派。解析稿侧的扫描把 `\$` 当转义的字面字符（`_ESCAPABLE_PUNCT` 含 `$`，`_verification.py:29`），markdown-it 也把 `\$` 显示为 `$`（实测）。

### 8.2 改动（拟改代码）

`_verification.py`，`resolve_backslash_escapes`（`:48`）之前新增：

```python
def is_literal_dollar(issue, text):
    """HTML 文本里不配对、紧贴标识符的单个 `$`（如 `$pointerType`、`preview$call`）：源中字面文字。

    `$` 之后至少两个标识符字符，或 `$` 之前紧贴标识符字符时成立；`$x` 这类仍算残缺公式。
    `$ 5` 在现行扫描中不产生 issue，不进入本判定，继续保持原样。"""
    if issue.raw != '$' or not issue.reason.startswith('未闭合的行内公式定界'):
        return False
    return (re.match(r'[A-Za-z0-9_]{2}', text[issue.end:]) is not None
            or re.search(r'[A-Za-z0-9_]$', text[:issue.start]) is not None)
```

`_html_fidelity.py`，`render_inline` 的同一循环：扫描结果里符合 `is_literal_dollar` 的 `$` 前插入反斜线，与公式占位一起从后往前处理，偏移不乱：

```python
            scan = scan_math(masked)
            # 不配对、紧贴标识符的 $ 是字面文字：写成 \$，不再被读作公式定界
            literal = [(issue.start, None) for issue in scan.issues
                       if is_literal_dollar(issue, masked)]
            for start, span in sorted([(s.start, s) for s in scan.spans] + literal,
                                      key=lambda item: item[0], reverse=True):
                if span is None:
                    raw = raw[:start] + '\\' + raw[start:]
                    continue
                ...（公式占位同原代码）
```

`_source_reconcile.py:524-528`，`_literal_math_issues` 改为接收文本节点本身（唯一调用处 `:740` 相应改成 `_literal_math_issues(node)`）。紧贴标识符、不配对的 `$` 不算残缺公式；它在所在块的拼接文字里与别的文本节点的 `$` 配成公式时照旧算未解决定界（块级配对检查，见 §8.5）：

```python
def _math_scan_text(text):
    serialized = re.sub(r'\s*\n\s*', ' ', text)
    return serialized.replace('\\[', 'xx').replace('\\]', 'xx')


def _literal_math_issues(node):
    """文本节点字面公式扫描的未解决定界（原偏移在序列化后的文字上）。

    不配对、紧贴标识符的 $ 是源中字面文字（解析稿写成转义的 $），不算残缺公式；
    它在所在块的拼接文字里与别的文本节点的 $ 配成公式时（公式被 <em>、<sup>
    等标签切开），照旧算未解决定界。"""
    stripped = _math_scan_text(str(node))
    issues = scan_math(stripped).issues
    literal = [issue for issue in issues if is_literal_dollar(issue, stripped)]
    if not literal:
        return list(issues)
    block = (node.find_parent(['p', 'li', 'dt', 'dd', 'td', 'th', 'caption', 'figcaption'])
             or node.parent)
    whole, offset = '', 0
    for other in block.find_all(string=True):   # 与 _math_spans 的扫描范围相同
        if (_in_pre(other) or _in_heading(other)
                or other.find_parent(class_='math') is not None
                or other.find_parent('code') is not None):
            continue
        if other is node:
            offset = len(whole)
        whole += _math_scan_text(str(other))
    spans = scan_math(whole).spans
    return [issue for issue in issues if issue not in literal
            or any(s.start <= offset + issue.start < s.end for s in spans)]
```

解析端 `render_inline` 不做块级检查：块级配对时源侧照旧阻断，解析稿不会写出。

`_source_reconcile.py`，`_norm_text`（`:358` 的 `decode_heading_escape` 处理之后）加一行 `text = text.replace('\\$', '$')`：列表项、段落等文字事实按阅读语义把 `\$` 还原为 `$`，与源里的 `$` 比较。HTML 侧同样经过 `_norm_text`，两侧对称。

`references/translation_conventions.md` 加一条：解析稿里的 `\$` 是字面美元符号，译文原样保留。

### 8.3 为什么只转义扫描报出的那些 `$`

把文本里所有公式之外的 `$` 都转义，会改动现在已通过的页面（货币 `$100` 等），回归里 176 页逐字节相同就保不住。只转义扫描报“未闭合”、又紧贴标识符的那些，正好是今天会被阻断的 Tile IR 写法，其余页面的解析稿不变。

导出不用改：导出扫描译文，`\$` 本来就不算公式定界；不带反斜线又不配对的 `$` 照旧报“未解决数学定界，拒绝导出”（`export_pdf.py:2918-2921`），数学检查不放松。

同一文本节点里有两个字面 `$` 时（如 `$pointerType and cuda_tile.preview$call`），扫描把它们配成一个公式，解析稿照旧写成 `$…$`，导出后显示为公式。需求 R6 第 3 条要求配对规则不变，本设计不处理这种情况；Tile IR 两版快照的正文文本里，配成公式的 `$` 跨度为 0 处（原型实测）。

`render_inline` 与源侧的 `_literal_math_issues` 被四个 HTML 家族共用，`\$` 的写法与放行对单页、分页、参考手册家族同样生效，见 §12.2。

### 8.4 只放行紧贴标识符的 `$`（D3）

本设计只放行紧贴标识符的那些 `$`，`$x` 这类照旧阻断。`$ 5` 在现行 `scan_math` 中不产生 issue，不属于残缺公式候选；2026-11-22 用 Python 3.12 实测 API 入口退出 0 并写出原文，用户批准澄清为保持该现状，不新增阻断或转义：

- 原因：HTML 里被标签切开的公式（如 `$x<em>1 + y</em>1$`）在每个文本节点里都只剩一个 `$`，全部放行会把这类公式静默当成文字；现有两个用例保护的正是这条阻断。
- 覆盖：Tile IR 两个版本的快照正文里，扫描报“未闭合”的 `$` 共 19 处，全部紧贴标识符（`$value`、`$pointerType`、`preview$call` 等）；两版 28 页里，除截断的 13.4 `operations.html` 被 R7 拒绝外，其余 27 页都通过。
- 代价：将来若有文档用 `$` 接单个字母写字面文字，仍会阻断，需要回到组件处理。

### 8.5 已批准：源侧块级配对检查（D5，2026-11-22）

只按 D3 的规则判断时，被标签切开、两段都紧贴标识符的公式会静默通过。原型实测三个样本，现行版本都报“未解决数学定界”、不写解析稿；只按 D3 判断时都通过：

| 源 HTML | 只按 D3 写出的解析稿 |
| --- | --- |
| `Compute $QK<sup>T</sup>V$ here.` | `Compute \$QK T V$ here.` |
| `Sum $AB<em>1 + CD</em>2$ here.` | `Sum \$AB 1 + CD 2$ here.` |
| `Score $W_q<em>x W</em>k$ here.` | `Score \$W_q x W k$ here.` |

第一段的 `$` 紧贴 `QK`，按 D3 算字面；第二段的 `$` 后面是空格，扫描不报，也不转义。导出时这一段显示成带 `$` 的普通文字，不是公式。单页家族的现有用例本来就处理 HTML 文本里的 `$x$` 这类公式（`test_structural_invariants.py:818-824`），这种输入是实际会遇到的。

§8.2 的块级配对检查把它们照旧阻断：字面 `$` 放回所在块（p、li、dt、dd、td、th、caption、figcaption）的拼接文字里再扫描一次，与别的文本节点里的 `$` 配成公式时不算字面。原型实测：上面三个样本都照旧阻断；`$x<em>1 + y</em>1$` 两种判断都阻断；Tile IR 正文 15 处字面 `$` 放回所在块后都不与别处配对（另 4 处在标题里，源侧本来不扫描标题）。

代价：同一块里两个字面 `$` 分在不同文本节点、又恰好能配成一对时，照旧阻断，与现行版本相同。例如 `of type $pointerType and <a href="#x">cuda_tile.preview$call</a>`，两个 `$` 之间的文字首尾都不是空白，会被配成公式。Tile IR 两版快照里没有这种写法。代码多约 25 行，都在 `_literal_math_issues` 里。

2026-11-22 用户明确批准本节。执行计划只实现块级配对检查，不采用只按 D3 判断、会让上面三个样本静默通过的备选。

## 9. R7 截断的整页快照在解析时被拒

拟改代码，`_html_fidelity.py`，`class HtmlFidelity`（`:689`）之前新增：

```python
def require_complete_html(path):
    """以 <!DOCTYPE 或 <html 开头的整页快照必须以 </html> 结束；片段不检查。

    按字节判断，截在多字节字符中间的快照同样报截断，而不是报解码错误。"""
    data = open(path, 'rb').read()
    if data.lstrip(b'\xef\xbb\xbf \t\r\n')[:9].lower().startswith((b'<!doctype', b'<html')) \
            and not data.rstrip().lower().endswith(b'</html>'):
        raise SystemExit('HTML 快照截断：%s（%d 字节）缺少 </html>，已阻断解析'
                         % (path, len(data)))
```

四个入口共有 6 处读入快照，都在读入之前调用 `require_complete_html(html_path)`，并各自加上导入：

| 入口 | 读入位置 | 用途 |
| --- | --- | --- |
| `parse_api_html.py` | `:284` | API 解析 |
| `parse_single_page_html.py` | `:176` | 单页解析 |
| `parse_paginated_html.py` | `:147` | 分页解析 |
| `parse_reference_html.py` | `:558` | 参考手册 HTML 解析 |
| `parse_reference_html.py` | `:342`（`_adapted_main`） | `--source-adaptation` 的 LaTeXML 论文解析 |
| `parse_reference_html.py` | `:416`（`inspect_reference`） | `--inspect-output` 的论文检查，来源依据从这一步开始建 |

`parse_api_html.py:317` 在发布前重读同一快照做候选复核，前面已经查过，不再加。

判据要求文档以 `</html>` 结束，而不是“文中出现过 `</html>`”：截断的页如果在 `<pre>` 示例里含有 `</html>`，后者会放过它。按字节判断是因为截断可能落在多字节字符中间，先解码的话只会报 `UnicodeDecodeError`（原型实测）。知识库与 `machine-learning.local` 里以 `<!DOCTYPE` 或 `<html` 开头的 342 个完整文档中，除这一页外的 341 个去掉尾部空白后都以 `</html>` 结束（按字节判据复查）；CUDA PG `pagesite/` 的 52 个 `<article>` 片段与 cuTile 缺陷盘点里的 3 个片段样本不以这两种标记开头，不检查。

原型实测：单页、分页入口与参考手册入口的三种用法，用截断的整页样本或截掉一半的 AutoInt 论文快照（121,777 字节），都报截断、不写解析稿；截在多字节字符中间的样本同样报截断；片段样本与完整论文的 `--inspect-output` 照常通过。

## 10. R8 API 解析对账失败时第一屏能看到根因

### 10.1 现状（现有代码）

`parse_api_html.py:299-302`：

```python
    if diffs:
        sys.exit('源对账失败: %s 与 %s 不一致，已阻断分派\n%s' % (
            html_path, out_path,
            '\n'.join('  - ' + d for d in diffs)))
```

已有的归类函数 `summarize_messages`（`_verification.py:1909-1922`，LaTeXML 对账失败在用）把数字换成 `N` 后取前 60 字作类别。差异里带着文件路径和差异内容，路径较短时 60 字里混进了各条不同的内容：PTX 全文 177 条用相对路径时被分成 78 类、138 行；用绝对路径时恰好 8 类、23 行。

### 10.2 改动（拟改代码）

`_verification.py`，`summarize_messages(messages, samples=3, key=None)`：`key` 缺省仍是现有模板，LaTeXML 的输出不变。

`parse_api_html.py`，失败分支：

```python
    if diffs:
        side = tempfile.mkdtemp(prefix='parse_api_rejected_')
        stem = os.path.splitext(os.path.basename(out_path))[0]
        with open(os.path.join(side, stem + '.rejected.md'), 'w',
                  encoding='utf-8', newline='') as handle:
            handle.write(md_text)          # 与参与对账的文本逐字节相同
        with open(os.path.join(side, 'reconcile_diffs.txt'), 'w', encoding='utf-8') as handle:
            handle.write(''.join(d + '\n' for d in diffs))
        kind = lambda m: re.sub(r'\d+', 'N', m.split(': ', 1)[0])  # 冒号前是差异类型
        sys.exit('源对账失败: %s 与 %s 不一致，已阻断分派\n%s\n全部差异与被拒解析稿：%s'
                 % (html_path, out_path, summarize_messages(diffs, samples=1, key=kind), side))
```

按冒号前的类型归类后，PTX 全文 177 条为 8 类，第一屏 14 行，定义列表一类的第一条是第 41 项 `sm_1x`（用同一批差异离线实测）。

`split_work_packages.py` 的 `split()`（`:545` 检查源文件存在之后）与 `verify_api_translation.py`（`:381` 读源文件之前）各加一个判断：源路径以 `.rejected.md` 结尾时退出，报“这是源对账未通过的解析稿”。合章（`merge_api.py`）只读译文页、清单与 HTML 快照，不读解析稿，不用改。

`references/workflow_helpers.md`“单页 API 与标题工作清单”一节补一句：对账失败时第一屏按差异类型列出条数和每类第一条，全部差异与被拒解析稿写到报错末行给出的临时目录，被拒解析稿以 `.rejected.md` 结尾，拆包与 API 核验拒收。

### 10.3 为什么写到临时目录

写在解析稿旁边最好找，但项目的 `source/` 往往就在交付根里，交付校验按目录允许清单检查交付根（`verify_delivery.py:4313-4314`），多出的未登记文件会被拒；临时目录不碰项目目录。被拒解析稿不加任何标记行，保证行号与报错一致，所以靠文件名后缀让拆包与核验拒收。改名后再用仍能绕过，这一点与现有的“对账失败不写成品”一样，靠 `SKILL.md` 的门禁规则约束。

## 11. 测试

新增 `tech-doc-translator/tests/test_api_parse_reconcile_fixes.py`，沿用 `test_api_native_container_regressions.py` 的写法（临时目录里写 `<article>` 页面，子进程运行 `parse_api_html.py`），每条需求一组正反例，夹具都内联在测试里，不依赖知识库文件：

| 需求 | 正例 | 损伤 |
| --- | --- | --- |
| R1 | 两段 dd；dl 嵌在列表项里接同项段落；dl 之后接选项卡；dd 以代码块、提示框结束后接术语 | 删掉 dd 第二段报定义列表差异 |
| R2 | 带 id 的表格嵌在 li、dd 里，带 id 的标题嵌在 li 里 | 锚点挪到表格之后报锚点错绑；直接嵌在 li 里、带 id 的 `<pre>` 报缺来源对象锚点 |
| R3 | 格内行内代码 `` `& \| ^` ``、文字 `a \| b`、公式（`\(\|x\|\)`、`\(p(a \| b)\)`、`\(\\|x\\|\)`）与图片地址 `img\|a.png` | 改格内一个字符报表格差异；改格内公式内容或图片地址报内容差异 |
| R4 | 1 列 4 行、首行只有代码的表格 | 改一个格内代码标记的行号报归属差异 |
| R5 | dd 里两段列表项；列表后接 dd 段落；列表项里再嵌一层列表 | 删掉一个续段报列表项差异 |
| R6 | 分处两段的 `$pointerType` 与 `preview$call` 写成 `\$`；配对的 `$x$` 与 `$100` 不变 | 译文里去掉 `\$` 的反斜线，`scan_math` 报未闭合；正文 `$x` 仍阻断（现有两个用例），`$ 5` 保持非候选且不新增转义；`$QK<sup>T</sup>V$` 等被标签切开的公式仍阻断（D5） |
| R7 | `<article>` 片段、完整页、完整论文的 `--inspect-output` 照常解析 | 截断整页经四个入口（参考手册入口的三种用法）都报截断、不写解析稿；截在多字节字符中间同样报截断 |
| R8 | 失败时第一屏为类型归类，旁路解析稿与对账文本逐字节相同 | 把 `.rejected.md` 交给拆包与 API 核验被拒 |

`test_math_scan.py` 加 `is_literal_dollar` 的判定用例；`summarize_messages` 的 `key` 用例并入同一文件。

原型副本上的全量 pytest：8 条失败、1529 条通过、283 个子测试通过。其中 7 条是现行版本已有的失败（`test_pdf_math_export.py` 5 条、`test_latexml_footnote_table_boundaries.py` 的 `test_multiline_mapped_cell_real_pdf_and_damage`、`test_pdf_confirmed_footnotes.py` 的 `test_code_first_definition_keeps_empty_container_and_code_bytes`），与 11-19 在 `268e1f9` 上跑出的失败集合相同，`268e1f9` 与 `3c8a4df` 的代码和测试没有差异；另 1 条是 `test_document_title_v2.py` 的 `test_title_v1_literal_and_old_reader_rejection`，它要在 Git 仓库里运行 `git archive`，副本没有 `.git`。7 个集成脚本（`tests/run_*.sh`）在原型副本上都退出 0。

## 12. 生效范围与兼容性

### 12.1 各改动生效的家族

| 改动 | API | 单页、分页、参考手册 HTML | LaTeXML 论文 |
| --- | --- | --- | --- |
| R1、R4、R5 对账读法 | 生效 | 生效 | 生效，共用 `_MarkdownFacts` |
| R2 富容器锚点 | 生效 | 不生效，只有 API 入口注入 | 不生效 |
| R3 解析写 `\\|` | 生效 | 生效，各自的 `render` 开启开关 | 不生效，开关关闭 |
| R3 对账读回 `\\|` | 生效 | 生效 | 不生效，带来源依据 |
| R6 解析写 `\$`、源侧放行 | 生效 | 生效，共用 `render_inline` 与 `_literal_math_issues` | 结果不变：适配器对正文里不配对的 `$` 先按自己的规则报“字面数学定界未解决” |
| R6 阅读时 `\$` 读作 `$` | 生效 | 生效 | 生效，共用 `_norm_text` |
| R7 截断检查 | 生效 | 生效 | 生效，`parse_reference_html` 的三种用法 |
| R8 第一屏与旁路文件 | 生效 | 不生效 | 不生效 |

知识库交付记录里有 55 条 API 来源（CUDA PG 53 条，cuBLAS、cuSPARSE 各 1 条）和 9 篇 LaTeXML 论文，没有单页、分页或参考手册 HTML 家族的项目。

### 12.2 单页、分页、参考手册 HTML 家族同样写 `\|` 与 `\$`（D4）

- 原因：对账读回 `\|`、放行字面 `$` 的代码在 `_MarkdownFacts` 与 `_literal_math_issues` 里，四个 HTML 家族共用，不区分家族；写出 `\$` 的 `render_inline` 同样共用。只让 API 写 `\|` 时，其他家族格内的源文字 `a\|b` 照旧写成 `a\\|b`，新对账器把它读成 `a|b`，报格值不一致（原型实测）。另外三个家族格内的 `|` 今天同样破坏列界，与 R3 是同一缺陷。
- 影响：知识库没有这三个家族的项目。以后用它们解析时，格内的 `|` 与紧贴标识符的字面 `$` 写成 `\|`、`\$`，译文按同一翻译约定保留。三个家族的集成脚本在原型上通过（§11）。

### 12.3 兼容与迁移

- 重新解析的 API 项目：解析稿里，列表项与定义条目中的带 id 表格、标题、dd 里的提示框前多出锚点行；表格格内的 `|` 写成 `\|`；正文里紧贴标识符、不配对的 `$` 写成 `\$`。旧译文要补同样的锚点与转义才能通过核验。218 页回归里，现在已通过的页只有 cuTile `cuda.tile.mma.html` 一处 `[u\|i]8` 不同。
- 未重新解析的项目：55 条 API 来源的现有解析稿用原型重新对账（源对账加锚点核对），结果与现行版本逐条相同：53 条通过；CUDA PG 13.5 的 `unified-memory`、`async-copies` 两版都报同样的“缺来源对象锚点”（2 条、3 条），是项目解析稿的现状。9 篇 LaTeXML 论文的现有解析稿重新对账，两版结果也逐条相同；其中 6 篇的快照文件已不在，只报快照不可读，实际比到内容的是 AutoInt、Bending the Scaling Law Curve（都通过）与 fastai（两版都报同样的 413 条）。
- 重新解析的 LaTeXML 论文：快照与来源依据都还在的 AutoInt、Bending the Scaling Law Curve 两篇，两版都通过，解析稿逐字节相同；其余 7 篇两版同样失败（6 篇的快照文件已不在，fastai 两版都报同一处字面数学定界未解决）。
- `_source_reconcile.py`、`_html_fidelity.py`、`_verification.py` 计入各核验入口的检查器身份（`verify_delivery.py:482-513`），重装后已闭合的复核要重新闭合。
- 知识库现有 Tile IR 译文有 11 处不带反斜线的 `$`（`06_Type_System.md` 1 处、`09_Operations.md` 10 处），重新导出前要补成 `\$`。
- 重装后，PTX 会话可以改用共享安装、不再需要冻结副本；Tile IR 的 `parse_literal_dollar.py` 包装成为空操作。

## 13. 直接验收

各条按需求第 3 节验收；整体验收按需求第 6 节，实现后在重装的共享安装上实测：

1. PTX ISA 9.5 派生快照用重装后的共享安装解析一次通过，写出解析稿并拆包通过，不复制组件、不加包装。
2. Tile IR 13.5 全部 14 页、13.4 补下完整 operations 页后的全部 14 页，不加包装解析通过。
3. 知识库交付记录里快照与解析稿都还在的 55 条 API 来源，现有解析稿用实现版本重新对账，结果与改动前逐条相同；§2 的 218 页回归同时复跑：现在已通过的页仍通过，解析稿除 §12.3 列出的写法变化外逐字节相同，两版都失败的页差异条数不变。
4. 全量回归失败集合与改动前相同。

原型上已按同样口径跑过第 1、3、4 条，以及第 2 条里 13.5 的 14 页与 13.4 除 operations 外的 13 页；补齐 13.4 operations 页后的结果见 §15。样本、日志与临时副本都写在 Git 工作区外；证据目录只读。

## 14. Karpathy 精简与自检

1. **基线**：读了需求 V0.4、问题记录与两个证据目录，以及 `_source_reconcile.py` 的 `terms`、`list_records`、`table_records`、`_tagged_inline_code`、`_SourceFacts._math_spans` 与 `_literal_math_issues`、`_norm_text`、`markdown_table_facts` 与 `compare_translation_tables`，`_html_fidelity.py` 的 `render_inline`、`rich_container_lines`、`_block_sequence`、`table_block`、`definition_list`，`_latexml_source.py` 对 `table_block`、`render_inline` 的调用，`_api_navigation.py` 的 `_source_anchors`、`source_anchor_ids`、`anchor_diffs`，`parse_api_html._render_children` 的代码块锚点，`_verification.py` 的 `scan_math` 货币与转义口径、`table_math_spans`、`summarize_messages`，四个解析入口的 6 处快照读入与失败分支，`split_work_packages.split` 与 `verify_api_translation` 的源输入。影响方案的既有约束：对账是分派前的唯一门禁，失败不写成品；`rich_container_lines`、`table_block` 与 `render_inline` 被四个 HTML 家族和 LaTeXML 适配器共用，只有 API 家族写锚点；LaTeXML 对账按字面读格内代码；源侧逐个文本节点扫描字面公式；三个改动文件属检查器身份；导出与对账共用 `scan_math`；HTML 正文里的 `$x` 阻断分派是有用例保护的现有合同；`$ 5` 经 `scan_math` 与 Python 3.12 API 入口实测为非候选，现行行为是原样通过。
2. **假设与差异**：假设完整的 Sphinx 整页快照都以 `</html>` 结束（341/341 个实测）；假设解析端写 dd 时术语行总紧接上一行（`definition_list` 与 `rich_container_lines` 的写法，原型与 218 页回归一致）。D2–D4 已写进需求 V0.4。§8.5 源侧块级配对检查（D5）于 2026-11-22 获批，它在 D3 的放行之上再收窄，同一块里能与别处 `$` 配成公式的字面 `$` 照旧阻断。需求外、本设计不处理的已知形态都列明了：dd 里的表格或嵌套 dl 之后还有术语（§3.4），同一文本节点里的两个字面 `$`（§8.3），LaTeXML 简单表格格内的文字 `a | b`（§5.3），三者现行版本与原型结果相同。`$ 5` 的原规格“照旧阻断”与实测不符，2026-11-22 用户明确批准澄清为保持非候选现状；这不是实现行为变化，也不新增扫描规则。没有其他未经批准的行为变化。
3. **最小方案**：每条都比较了更简单的做法并说明了拒绝原因——R1 只跳空行会把选项卡标签读成术语（§3.3）；R2 照搬补丁 B 会改变其他三个家族的输出（§4.3）；R3 只改解析端会让格内代码对不上，不分家族读回或写出会让 LaTeXML 的现有用例与简单表格格内代码失败（§5.3）；R4 改单列写法会改变解析稿与译文形态（§6）；R5 在任意标记处结束定义区会把 dd 段落并进列表项（§7.3）；R6 转义所有 `$` 会改动已通过的页（§8.3），无条件放行会让被标签切开的公式静默通过（§8.4），只按 D3 判断仍会放过两段都紧贴标识符的切开公式（§8.5）；块级检查只放在源侧，因为源侧阻断时解析稿不会写出，解析端不必重复；按所在块而不是整页配对，避免把不同段落的 `$` 配在一起；R7 只查“出现过 `</html>`”会放过含示例代码的截断页，解码后再查会把截在多字节字符中间的快照报成解码错误（§9）；R8 写在解析稿旁边会碰到交付根的目录清单（§10.3）。新增的只有三个函数（`is_literal_dollar`、`require_complete_html`、`_math_scan_text`）、两个属性（`block_anchor_ids`、`escape_table_pipes`）、一个可选参数（`key`）和一个只算一次的实例属性 `_table_row_lines`（`_MarkdownFacts` 的表格行集合，公式、行内代码、图片地址三条流共用），各自对应一条需求，其中 `escape_table_pipes` 用来把 R3 的写法限在 HTML 家族；没有新命令、新参数或新格式。
4. **删除审计**：各节都对应一条需求或其验收。写作中删去了：按 `[DEF-LIST]` 缩进判定定义区结束的改法（dd 里的选项卡与术语同缩进，挡不住）、单列表格写 `|` 的改法、在任意列表标记处结束定义区的改法、转义所有 `$` 的改法、`table_block` 无条件转义 `|` 的改法、读入解码后再查截断的改法、给被拒解析稿加标记行的做法（会打乱行号）、D2–D4 各自的“不批准时”替代做法、D5 获批后不再采用的只按 D3 判断备选、与实测不符的 `$ 5` 阻断描述，以及给 PTX 冻结副本与 Tile IR 包装写迁移步骤（属项目）。性能：R3 让每次构建不带来源依据的 Markdown 事实多算一次 `table_records()`——`_MarkdownFacts.__init__` 算一次表格行集合 `_table_row_lines`，公式、行内代码、图片地址三条流共用，不各算。PTX 全文解析稿做一次 API 源对账，`table_records()` 共调用 6 次、累计约 3 秒，整次对账约 14 秒（2026-11-24 实测；读回收敛到同一个集合前后调用次数相同）。需求 §5 已说明耗时不是瓶颈，本设计不为此加缓存。
5. **直接验收**：§13 第 1、2 条直接证明用户看到的核心结果——同样的 PTX 与 Tile IR 快照不改组件、不加包装就能解析、写出解析稿并拆包；第 3 条证明现有项目不受影响；各条损伤样本证明检查没有放松。测试通过与回归本身不能代替这两条实测。

## 15. 最终实施验收（2026-11-23）

八条实现 ticket 全部完成并通过评审与整分支终审后，在重装的共享安装（`~/.agents/skills/tech-doc-translator`）上做最终验收。命令口径：共享安装目录的脚本直接调用（不复制组件、不加包装）；兼容回归用工作区外的临时驱动器分别调用基线 clone（`3c8a4df`，`git clone` 后 `checkout --detach`，非 `git archive` 副本）与当前仓库的入口/对账器；解释器统一为项目 venv（Python 3.12.7）。

**直接验收（§13 逐条）**

1. **通过**：PTX ISA 9.5 派生快照经共享 `parse_api_html.py` 一次通过，写出 39,656 行解析稿（与 §2 原型一致），共享 `split_work_packages.py chars:20000` 拆出 93 个包；解析约 31 秒、拆包约 6 分 48 秒；原快照 SHA-256 不变。
2. **通过（2026-11-24 补齐）**：Tile IR 13.5 全部 14 页、13.4 全部 14 页经共享安装解析均退出 0。13.4 `operations.html` 在 2026-11-23 仍是 81,920 字节截断件（尾字节停在 `<span class="c1">// Device-only,` 中间、无 `</html>`），共享安装解析退出 1，报“HTML 快照截断……已阻断解析”，不写解析稿（R7 拒绝证据保留）；2026-11-24 经用户同意从文档站仍发布的 13.4 版取回完整页替换后解析退出 0（详见需求 §7）。
3. **通过**：55 条 API 来源现有解析稿双版本重对账逐条相同（53 通过；`unified-memory` 缺锚点 2 条、`async-copies` 3 条两版一致）；9 篇 LaTeXML 现有解析稿双版本逐条相同（AutoInt、Bending 通过并重解析两版逐字节相同，fastai 413 条两版一致，6 篇快照缺失两版同报）；218 个整页快照双版本分布 176 字节相同 / 1 页仅 `[u\|i]8` / 7 页失败变通过 / 1 页截断通过变失败 / 33 页两版失败且每页差异条数相同，与 §2 记录逐项一致。
4. **通过**：全量 pytest 基线 7 failed/1530 passed、当前 7 failed/1555 passed，排序失败集合逐条相同（既有 7 条 PDF 用例），无新增 collection/internal error；七个 `tests/run_*.sh` 全部退出 0；R3/R6 样本 PDF 用 PyMuPDF 抽取实测：正例含 `& | ^`、`Oper 254 (ta | tb | tc)`、`$pointerType` 且无转义反斜线，去 `\$` 反斜线与去 `$x$` 闭合定界两个损伤例均报“未解决数学定界，拒绝导出”、不生成 PDF。

**检查器身份与复核（§12.3）**：六类核验入口的共享依赖都含三个改动检查器；知识库 36 份含已闭合复核的交付记录（24 个项目，另含重命名目录里的 12 份副本记录）绑定全部因此失效（其中多数在此前批次已因导出器/核验器变化失效），按绑定摘要比对证实不会被误当当前有效。逐项目重闭合按 `references/workflow_helpers.md`“检查器变化后的恢复”四步流程执行；本批未重闭合任何项目，全部登记为未完成项（含 6 篇快照已不在的 LaTeXML 项目：输入失效，须先补快照或按项目规则处理）。对 24 份记录实跑当前 `verify_delivery.py --evidence-dir`：旧闭合均不被接受，其中 9 份明确报“复核 binding 与当前完整上下文不符……旧结论失效，须重新复核”，其余在更早阶段因既有状态失败（成品 PDF 已按项目清理删除、快照缺失、交付根已迁移或视图声明与实际输入不符），逐记录日志在证据目录。2026-11-24 用户决定：不在本主题重做复核重闭合（成本过高）；旧闭合不会被当成有效已实测，各项目交付时由交付检查按现行恢复流程处理。

**与设计的实施差异（均经裁定，行为不变）**：设计 §4 示例里的 `_html_escape` 在代码中不存在，实现用标准库 `html.escape`；R3 表格差异断言子串为 `inline-code`；R4 单列样本的格内代码标记为 3 个；R7 的 `--inspect-output` 用法以直接调用脚本刻画；R5 判别样本补充宿主 `li` 变体。验收枚举与设计记录的两处口径出入如实记录：§14.2 的“341 个完整文档”按现行枚举为七家族 283 个（全知识库 355 个），原清单不在磁盘、无法复现，完整性结论不受影响（283 个全过、55 个片段全过、唯一被拒的是截断件）；§2 的 218 页集合由实测分布唯一确定，等于七家族整页快照全集 284 个排除 CUDA PG `source-13.5/`（57 页）与 PTX 证据切片 `docs/evidence/repro*`（9 个）。

**评审后修正（2026-11-24）**：§5.1 原写“表格行内公式的 `\|` 已按真实表格行归一”。该归一（`table_math_spans`）与 markdown-it 的读法只作用于译文核验，解析时的源对账不经过它们；实现又只给格内文字与行内代码加了读回，公式流和图片流没有读回。结果是含 `|` 的格内公式与图片地址在改动前能通过、在本版被报成内容不一致（R3 第 2 条不完整）。修正：`_MarkdownFacts.__init__` 算一次表格行集合，`_tagged_math`、`_tagged_images`、`_tagged_inline_code` 在集合内的行上读回（§5.2）；§1 总览行、§5.1、§5.2 与 §11 的测试表已按修正后的设计改正。用例、回归与实测数字见需求 §7。修正不新增机制（沿用行内代码已有的集合与读回口径）；LaTeXML 路径与表格外内容的行为经代码和实测确认不变。

无其他未经批准的行为差异。证据与回归产物在 Git 工作区外（`~/api-reconcile-task09-20261123/`，共享安装备份 `~/api-reconcile-install-backup-20261123/`；2026-11-24 修正的样本在 `~/api-reconcile-fix-20261124/`，重装前备份 `~/api-reconcile-install-backup-20261124/`；补齐 13.4 页后的最终复验产物在 `~/api-reconcile-fix-20261124/final-accept/`，结果见需求 §7）。
