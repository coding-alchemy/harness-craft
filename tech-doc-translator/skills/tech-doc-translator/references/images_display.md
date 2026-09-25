# 图片显示尺寸映射（images_display.json）

本文件是 `tech-doc-translator` 图片显示尺寸链路的契约；由 SKILL.md 在解析新翻译源、回补存量映射或导出 PDF 时按需读取。普通 Markdown 预览器不消费该文件，PDF 尺寸恢复是旁路映射（已批准边界）。

## 链路与职责

```
源快照 HTML ──parse_*_html.py──> 源 Markdown + <页名>.images_display.json（解析期）
                                        │ 翻译（出现顺序与引用保持）
                                        ▼
                              交付 Markdown + 交付图片
                                        │ 绑定（merge_api.py 自动 / rebuild_images_display.py 回补 / 主 Agent 手工）
                                        ▼
                              交付目录 export/images_display.json
                                        │ export_pdf.py / verify_pdf.py 消费
                                        ▼
                              PDF 按逐次显示宽度绘制并核验
```

- **解析期**：四类 `parse_*_html.py` 对每个进入输出的图片出现登记源显示宽度，写出 `<输出名>.images_display.json`。优先可解析的内联 CSS `width`，再 HTML `width` 属性（整数像素）；百分比必须找到祖先链中最近的内联像素宽度作参照才算确定。暗/亮图片对只登记选中版本。无宽度但有可用高度（内联 CSS px/pt 高度或 HTML height 属性）时，按源资源固有宽高比推导宽度（pt 按 4/3 换算），记录高度值/单位、比例来源（`pillow-size` / `svg-intrinsic-size` / `svg-viewBox`）与换算依据；比例未知、资源缺失、约束冲突与不支持单位一律列入 `undetermined`，不冒充已恢复。解析输出落入系统临时目录时醒目告警（真实路径与符号链接别名都识别，名字相似的普通目录不误报），调试仍可成功。
- **绑定**：多页面 API 家族由 `merge_api.py --display-src <解析输出目录>` 自动绑定；存量译文由 `rebuild_images_display.py` 按清单回补（四类家族共用）；两者复用同一绑定核心（`_image_binding.py`）：逐次出现按源出现顺序对账实际 Markdown 引用，以独立来源资源身份核对（解析期记录的 `resource_sha256` 字节级比对；旧映射回退到快照路径一致性），任一出现失败即拒绝整份候选，不产生部分成功映射，也不覆盖旧映射。出现枚举按代码语义排除：代码围栏与行内代码内的图片字面量不是真实出现（与导出/核验渲染级枚举同一代码口径），不改写、不计数、不要求其目标文件存在；同一出现号内容冲突的重复确定项拒绝（与输入顺序无关），相同内容重复幂等。API 合并保留 `undetermined` 并跨页重编号。工作包拆分/恢复不改写图片路径与出现顺序，映射条目对最终合并文档仍按全局出现序号绑定。
- **回补**：`rebuild_images_display.py --manifest <清单> --output <映射路径> [--work-dir <dir>] [--fetch-missing]`。清单声明本次范围（版本、家族、快照、最终 Markdown 与可选出现区间，以及可选 `parse_map` 解析期映射声明），不是项目状态库；完整快照复用不发网络请求，缺失项只在显式 `--fetch-missing` 时按清单 URL 直连补抓并校验预期摘要，重定向导致版本/来源不可确认即停止，失败下载不覆盖旧文件。回补只按家族规则提取快照选区内的图片出现与显示尺寸（api 取亮版、reference 改写为 `images/<basename>`、`<pre>` 内图片不参与），不运行正文渲染、不做全文对账——无关正文中的复杂表格等结构不阻断回补；图片出现另由独立源流核对（不同解析路径重提），不能由尺寸提取结果自证完整。每次出现同时保留原始源引用与交付写法：源资源相对快照目录解析，reference 的 `images/<basename>` 改写只用于交付匹配，同名异图（如 `left/plot.png` 与 `right/plot.png`）按各自显式路径直接命中，不做 basename 全树检索。历史身份核对在候选写盘前：每次出现的来源身份四元组（见 `resource_base` 字段口径）与既有独立证明比对——证明来自旧交付映射带身份条目和清单 `parse_map` 声明的该页解析期映射（声明文件须存在，其快照摘要、来源文件与资源上下文均须与清单页一致，逐条合并、同键不同摘要即冲突拒绝、与记录顺序无关）；同一来源位置字节不一致即同路径换图，整单拒绝且旧映射不变，不以当前字节补签历史。旧版相对来源记录（基点不可确定）与含身份但缺 `resource_base` 的旧记录（上下文不可确定）明确失败保旧，重新解析/合并即得合规记录；旧映射缺失、不可读或条目无身份字段时不构成历史事实，按兼容边界重建。候选写入 `--work-dir`（默认系统临时目录），重读校验后原子替换目标；失败不触碰旧映射，诊断留在工作目录。回补成功只证明映射有效，不代替新翻译解析入口的全文对账。
- **导出/核验**：`export_pdf.py` 读取各输入 Markdown 同目录的 `images_display.json`（或 `--images-display` 显式指定；跨目录共享映射须显式指定，不递归猜测项目根）。条目 `markdown` 按相对映射文件的完整路径归属；文件名兜底仅在输入中同名唯一且映射内无同名多条目时允许，否则判 FAIL 要求改用完整相对路径，不静默串用。命中条目先验证资源摘要与出现位置，再注入受限宽度（`width:Npx`，受样式表 `max-width:100%` 版心上限约束，保持宽高比）；导出与核验两侧参数必须一致。`verify_pdf.py` 从最终 PDF 内容流逐次量测实际绘制宽度并与期望对账（1 CSS px = 0.75 pt，容差 0.75 pt 仅吸收打印舍入）。覆盖分类的真实图片出现由导出与核验共用的同一渲染级枚举重建（核验独立重读输入）：代码围栏、行内代码与缩进代码中的图片语法及未定义引用式图片不产生 `<img>`，两侧一致不计出现。未确定条目与确定条目同口径核对出现序号、声明资源路径与摘要：越界、错路径或错摘要判 FAIL，不因未确定降级为回退告警。导出层位图重采样（边界见 `pdf_export.md`）只改变嵌入负载：无映射图片按原图自然显示宽度钉住呈现，映射注入的宽度照旧优先，宽度对账口径不变。

## 文件格式

解析期文件（每个源 Markdown 一个，`<输出名>.images_display.json`）：

```json
{
  "version": 1,
  "markdown": "page.md",
  "snapshot": "/abs/path/to/page.html",
  "snapshot_sha256": "…快照字节摘要…",
  "resource_base": "/abs/path/to",
  "entries": [
    {
      "occurrence": 1,
      "image": "_images/foo.png",
      "width": {"value": 454, "unit": "px", "basis": "inline-css-width", "reference": null},
      "source_node": "img[3]",
      "resource_sha256": "…源资源身份摘要（含 SVG/CSS 依赖）…"
    },
    {
      "occurrence": 2,
      "image": "_images/bar.png",
      "width": {"value": 100, "unit": "px", "basis": "height-derived-width", "reference": null},
      "derived": {"height": {"value": 50, "unit": "px", "origin": "inline-css-height"},
                  "aspect_ratio": 2.0, "aspect_source": "pillow-size",
                  "resource": "_images/bar.png"},
      "source_node": "img[4]"
    }
  ],
  "undetermined": [
    {"occurrence": 3, "image": "_images/baz.png",
     "reason_code": "no-source-constraint", "reason": "源节点无宽度约束",
     "source_node": "img[7]"}
  ]
}
```

交付级文件（新交付固定写入 `export/images_display.json`，条目路径相对映射目录解析）：

```json
{
  "version": 1,
  "markdown": "merged_api.md",
  "entries": [
    {
      "markdown": "merged_api.md",
      "occurrence": 1,
      "image": "../images/foo.png",
      "sha256": "…交付图片字节摘要…",
      "width": {"value": 454, "unit": "px", "basis": "inline-css-width", "reference": null},
      "source": {"snapshot": "/abs/path/to/page.html", "snapshot_sha256": "…",
                 "resource_base": "/abs/path/to", "node": "img[3]",
                 "resource_sha256": "…独立来源资源身份…"}
    }
  ],
  "undetermined": [
    {"markdown": "merged_api.md", "occurrence": 4, "image": "../images/free.png",
     "sha256": "…", "reason_code": "no-source-constraint", "reason": "源节点无宽度约束",
     "source": {"snapshot": "/abs/path/to/page.html", "snapshot_sha256": "…",
                "resource_base": "/abs/path/to", "node": "img[7]",
                "resource_sha256": "…"}}
  ]
}
```

字段口径：

- `occurrence`：该 Markdown 内图片出现的 1 起全局序号（合并文档跨页连续编号）；同一资源多次出现可各有不同宽度，禁止按 basename 合并。
- `image`：解析期文件写源 Markdown 中的原始引用；交付级文件写相对映射目录的完整路径（如映射在 `export/` 时为 `../章节图片`）。
- `width.basis`：`inline-css-width` / `html-width-attribute` / `height-derived-width`；`width.reference` 为百分比参照容器及其像素宽度，`null` 表示像素值。无参照的百分比、em/rem/auto 等一律留在 `undetermined`。
- `derived`：高度推导依据（原高度值/单位、固有比例、比例来源与资源引用），可回查换算过程。
- `reason_code`：`no-source-constraint`（源无任何尺寸约束）或 `unresolved-size`（有约束但无法确定，如比例未知、约束冲突、单位不支持）；`reason` 保留可读原因。
- `sha256`：交付文件字节摘要。
- `resource_sha256`：独立来源资源身份（`resource_identity_digest`，含 SVG/CSS 依赖内容）；与交付字节摘要 `sha256` 职责不同，不能用交付字节摘要代替来源证明。
- `snapshot`：来源快照 HTML 的文件身份——写入端统一记录 realpath 归一的绝对路径（文件级符号链接别名归一为同一文件，不随解析执行目录或 CLI 参数形式变化）；与 `resource_base` 职责不同：文件身份回答"是否同一份源"，资源解析上下文回答"相对引用当时解析到哪组资源"。读取端按同一 realpath 口径同义比较；旧版相对来源记录基点不可确定，明确失败保旧。
- `snapshot_sha256`：解析期快照 HTML 字节摘要，绑定与证据用它确认"同一版本快照"。
- `resource_base`：资源解析上下文（相对图片引用所相对解析的目录，即解析/声明时快照路径的目录经 realpath 归一；目录符号链接别名归一为同一上下文，文件级符号链接按声明目录区分）。来源身份由（`snapshot`、`snapshot_sha256`、`resource_base`、节点）共同确定；含完整身份但缺该字段的旧记录上下文不可确定，回补明确失败保旧，重新解析/合并即生成含上下文记录。
- `source`：源快照、资源解析上下文与节点定位，供回源核对；导出器只消费宽度与身份，不改写该字段。

## 失败与回退

- 映射命中的条目：出现序号越界、资源路径不符、摘要不符、宽度非法（非正数、非数、未知单位且非 `null` 宽度字段）→ 导出与核验 FAIL；不得忽略损坏映射后宣称恢复成功。
- 无映射命中的图片：按自然尺寸与版心上限导出，交付说明记录"未恢复源尺寸"；旧译文无映射属正常路径。
- 版本或字段不符合本契约的映射文件：按无法解析 FAIL，不猜测兼容。
- 回补绑定中任一出现身份不符、出现计数不符或覆盖不完整：整份候选拒绝，旧映射保持原样；"源图换字节、错引用、某章计数错"均不产生部分成功映射。
- 需要恢复旧译文尺寸时，优先用同版本源快照重新解析（`rebuild_images_display.py`）；缺失时先与用户确认同版本来源并经 `--fetch-missing` 显式补抓，不以最新版替代。
