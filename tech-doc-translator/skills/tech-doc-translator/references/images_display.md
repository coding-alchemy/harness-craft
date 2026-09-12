# 图片显示尺寸映射（images_display.json）

本文件是 `tech-doc-translator` 图片显示尺寸链路的契约；由 SKILL.md 在解析新翻译源或导出 PDF 时按需读取。普通 Markdown 预览器不消费该文件，PDF 尺寸恢复是旁路映射（已批准边界）。

## 链路与职责

```
源快照 HTML ──parse_*_html.py──> 源 Markdown + <页名>.images_display.json（解析期）
                                        │ 翻译（出现顺序与引用保持）
                                        ▼
                              交付 Markdown + 交付图片
                                        │ 绑定（merge_api.py 自动 / 主 Agent 手工）
                                        ▼
                              交付目录 images_display.json
                                        │ export_pdf.py / verify_pdf.py 消费
                                        ▼
                              PDF 按逐次显示宽度绘制并核验
```

- **解析期**：四类 `parse_*_html.py` 对每个进入输出的图片出现登记源显示宽度，写出 `<输出名>.images_display.json`。优先可解析的内联 CSS `width`，再 HTML `width` 属性（整数像素）；百分比必须找到祖先链中最近的内联像素宽度作参照才算确定。暗/亮图片对只登记选中版本。无宽度约束、不支持单位、百分比无参照分别列入 `undetermined`，不冒充已恢复。
- **绑定**：多页面 API 家族由 `merge_api.py --display-src <解析输出目录>` 自动绑定：按出现序号对账译文图片，资源身份（快照绝对路径）不一致直接失败，并把页内序号重编号为合并文档全局序号，写出交付目录 `images_display.json`（含资源 sha256）。其他家族由主 Agent 在下载图片、确定最终交付路径后手工绑定：沿用解析期条目的 `width` 与 `source`，把 `markdown`、`image` 改写为交付路径并补 `sha256`。工作包拆分/恢复不改写图片路径与出现顺序，映射条目对最终合并文档仍按全局出现序号绑定。
- **导出/核验**：`export_pdf.py` 读取各输入 Markdown 同目录的 `images_display.json`（或 `--images-display` 显式指定；跨目录共享映射须显式指定，不递归猜测项目根）。条目 `markdown` 按相对映射文件的完整路径归属；文件名兜底仅在输入中同名唯一且映射内无同名多条目时允许，否则判 FAIL 要求改用完整相对路径，不静默串用。命中条目先验证资源摘要与出现位置，再注入受限宽度（`width:Npx`，受样式表 `max-width:100%` 版心上限约束，保持宽高比）；导出与核验两侧参数必须一致。`verify_pdf.py` 从最终 PDF 内容流逐次量测实际绘制宽度并与期望对账（1 CSS px = 0.75 pt，容差 0.75 pt 仅吸收打印舍入）。

## 文件格式

解析期文件（每个源 Markdown 一个，`<输出名>.images_display.json`）：

```json
{
  "version": 1,
  "markdown": "page.md",
  "snapshot": "page.html",
  "entries": [
    {
      "occurrence": 1,
      "image": "_images/foo.png",
      "width": {"value": 454, "unit": "px", "basis": "inline-css-width", "reference": null},
      "source_node": "img[3]"
    },
    {
      "occurrence": 2,
      "image": "_images/bar.png",
      "width": {"value": 50, "unit": "%", "basis": "inline-css-width",
                "reference": {"container": "div.figure", "width_px": 800}},
      "source_node": "img[4]"
    }
  ],
  "undetermined": [
    {"occurrence": 3, "image": "_images/baz.png", "reason": "源节点无宽度约束", "source_node": "img[7]"}
  ]
}
```

交付级文件（交付目录 `images_display.json`，可含多个 Markdown 的条目）：

```json
{
  "version": 1,
  "entries": [
    {
      "markdown": "merged_api.md",
      "occurrence": 1,
      "image": "images/foo.png",
      "sha256": "…交付图片摘要…",
      "width": {"value": 454, "unit": "px", "basis": "inline-css-width", "reference": null},
      "source": {"snapshot": "page.html", "node": "img[3]"}
    }
  ]
}
```

字段口径：

- `occurrence`：该 Markdown 内图片出现的 1 起全局序号（合并文档跨页连续编号）；同一资源多次出现可各有不同宽度，禁止按 basename 合并。
- `image`：解析期文件写源 Markdown 中的原始引用；交付级文件写交付目录相对路径（相对映射文件目录解析）。
- `width.reference`：百分比参照容器及其像素宽度；`null` 表示像素值。无参照的百分比、em/rem/auto 等一律留在 `undetermined`。
- `source`：源快照与节点定位，供回源核对；导出器只消费宽度与身份，不改写该字段。

## 失败与回退

- 映射命中的条目：出现序号越界、资源路径不符、摘要不符、宽度非法（非正数、非数、未知单位且非 `null` 宽度字段）→ 导出与核验 FAIL；不得忽略损坏映射后宣称恢复成功。
- 无映射命中的图片：按自然尺寸与版心上限导出，交付说明记录“未恢复源尺寸”；旧译文无映射属正常路径。
- 版本或字段不符合本契约的映射文件：按无法解析 FAIL，不猜测兼容。
- 需要恢复旧译文尺寸时，优先用同版本源快照重新解析；缺失时先与用户确认同版本来源，不以最新版替代。
