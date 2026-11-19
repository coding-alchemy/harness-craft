# 原页复核与更正

1. 在 `document.md` 找到 `<!-- block:… -->`，用 `source-map.json` 和 `blocks.jsonl` 查物理页与块。物理页从 1 起。原始路径是 ZIP 内 `middle_json.json` 的 JSON Pointer，数组位置从 0 起。规范框是未旋转、左上为原点的点坐标。框缺失时，按物理页和原记录核对。
2. 打开同一份 PDF 的物理页或渲染页图。数字定位同时核对表头、行名和单元格。整包复核覆盖首、中、末页、难辨版面，以及每个未知、失败或存疑项。页级确认和块级存疑各有独立记录。
3. 复制已有 `review.json` 的完整记录，按下表加入或更新已经核实的项。生成内容摘要后把记录交给 `render --review 文件`。检查新目录的正文、块记录、配图和报告，随后可运行 `verify`。

## 复核记录

顶层 `pdf_sha256`、`zip_sha256` 取自 `raw/source.json`，`items` 是复核项数组。

| 字段 | 填法 |
| --- | --- |
| `page` 或 `block_id` | 每项只填一个，分别表示整页或一个正文块。 |
| `outcome` | `confirmed` 为确认，`corrected` 为更正，`unresolved` 为存疑。 |
| `evidence` | 写明实际查看的物理页和原文位置，例如表头 B 下的首格印为 `13`。 |
| `content_sha256` | 绑定更正后该页或块的可见内容、顺序和图片摘要，按下方方法计算。`table_body` 绑定父表实际呈现的行列和区域图。内容变化时相关结论转为待复核。 |
| `old`、`new` | 更正项必填，均为字符串。段落更正填写完整原值和替换值。 |
| `row`、`column` | 表格更正项填写含表头的 1 起行列。合并格以左上角为定位，无法验证行列时保留原区域图和存疑。 |
| `page_state` | 页级 `confirmed` 可填 `blank`（原页空白）、`has_content`（原页有内容）或 `illustration_only`（整页仅含已交付插图）。 |

遇到正文中的纯插图页，打开**整张物理页**，逐一对照交付图片，核对图内、图旁及页边是否还有漏识别的文字。确认整页仅含这些图时，页项填写 `illustration_only` 并记录所见，每个对应的父图块另作 `confirmed`。发现缺字时保留 `has_content` 或存疑，写明位置。旧记录中的 `has_content` 只确认有内容。一般页确认、过期确认和单独的区域图都不足以确认整页已交付。

## 一格更正示例

原件物理页 1 的表格 B 列首格印为 `13`，识别为 `18`，且同一行的 A 列也为 `18`。记录指向 B 列位置。把脚本目录设为安装包的 `scripts/`，使用读取环境执行下列 Python 片段。把示例位置、依据和路径替换为实际值。

```python
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path('/已安装的 Skill/scripts')))
from reading import build_document
from review import apply_review, content_digest

bundle = Path('/旧结果目录')
base = build_document(Path('/原件.pdf'), bundle / 'raw')
prior = bundle / 'review.json'
review = json.loads(prior.read_bytes()) if prior.is_file() else {
    'pdf_sha256': base['source']['pdf_sha256'],
    'zip_sha256': base['source']['zip_sha256'],
    'items': [],
}
item = {
    'block_id': 'p0001-b0000',
    'outcome': 'corrected',
    'row': 2,
    'column': 2,
    'old': '18',
    'new': '13',
    'evidence': '物理页 1，表头 B 下的首格为 13。',
    'content_sha256': '0' * 64,
}
review['items'].append(item)
preview = apply_review(base, review)
item['content_sha256'] = content_digest(preview, block_id=item['block_id'])
Path('/新复核记录.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
```

页级确认使用 `content_digest(preview, page=物理页号)`。暂用全零摘要只为取得更正后的预览。单格更正只处理该格。整表仍有待核对内容时，另记同一 `block_id` 的 `unresolved` 项并写明位置。核实整表后，可将该项更新为 `confirmed`，摘要按更正后的整表计算。仅重新计算实际看过的范围。摘要旧但原值仍匹配的更正会进入新正文，同时保留相关待复核提示。
