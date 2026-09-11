#!/usr/bin/env bash
# PDF 导出回归：临时样例覆盖单篇导出、核验、失败定位与输入保护。
# 所有临时文件都生成在工作区外 mktemp 目录；不依赖真实译文项目。
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

cd "$(dirname "$0")"
python3 test_pdf_structure.py
python3 test_pdf_integrity.py
EXPORT="../skills/tech-doc-translator/scripts/export_pdf.py"
VERIFY="../skills/tech-doc-translator/scripts/verify_pdf.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/images" "$TMP/out"
cp fixtures/valid_1x1.png "$TMP/images/pattern_a.png"

cat > "$TMP/sample.md" <<'MD'
# 1. 测试章节（Demo）

> **注（Note）**：这是一个提示块，包含 $\(x^2 + y^2 = r^2\)$ 行内公式与 [外部链接](https://example.com/docs)。

目录：见 [1.2 节](#12-第二个子节)。

正文中还有货币符号 $5 和裸美元 $ 符号，以及转义 \$3，见 `代码中 $x=1$ 不算公式`。

## 1.1. 子节：General 演示（含中文）

- 列表项二，参见脚注[^1]。

| 列 A | 列 B（宽列） |
|---|---|
| 值 $\(a_1\)$ | 很长的单元格内容用来测试自动换行是否保持文本完整可读不裁切很长的单元格内容用来测试自动换行是否保持文本完整可读不裁切很长的单元格内容用来测试自动换行是否保持文本完整可读不裁切很长的单元格内容用来测试自动换行是否保持文本完整可读不裁切 |

$$E = m c^2$$

$$
G(x) = \int_a^b f(t)\,dt + \lim_{n \to \infty} r_n
$$

<a id="custom-spot"></a>

标准三行块公式之后是显式锚点，[跳到自定义锚点](#custom-spot) 继续阅读。

行内代码中的锚点写法 `<a id="code-sample-anchor"></a>` 只是字面示例，不得当作真实锚点。

````python
```python
<a id="nested-anchor"></a>
```
````

####### 深层A紧接正文
紧随深层A的正文段落，验证占位不吞并后继文本。
####### 深层B紧接深层A
####### 深层C独立成段

$\[D = \alpha \cdot \begin{split} x &= 1 \\ y &= 2 \end{split}\]$

$\[F(s) = \int_0^\infty f(t) e^{-st} \, dt = \lim_{n \to \infty} \sum_{k=0}^{n} \frac{(-1)^k s^{2k+1}}{(2k+1)!} + \underbrace{\sqrt{\frac{a^2+b^2}{c^2+d^2}}}_{\text{长公式分式叠加}}\]$

```python
def hello(name):
    # 中文注释：code with $dollars$ stays
    print(f"hi {name}")
```

![演示图片](images/pattern_a.png)

**图 1. 演示插图**

## 1.2. 第二个子节

结尾段落，引用脚注[^2]。

[^1]: 第一个注文，含 $\(m\)$ 公式。
[^2]: 第二个注文。
MD

echo "==> 正常单篇导出"
python3 "$EXPORT" --output "$TMP/out/demo.pdf" --work-dir "$TMP/work" "$TMP/sample.md"

echo "==> 独立核验（机器层）"
python3 "$VERIFY" --pdf "$TMP/out/demo.pdf" --work-dir "$TMP/work" "$TMP/sample.md"

echo "==> 回归：输入与资源摘要导出前后一致（A6）"
python3 - "$TMP/sample.md" "$TMP/images/pattern_a.png" <<'PY'
import hashlib, json, sys
from pathlib import Path

work = Path(sys.argv[1]).parent / "work"
report = json.loads((work / "export_report.json").read_text(encoding="utf-8"))
verify = json.loads((work / "verify_report.json").read_text(encoding="utf-8"))
assert verify["status"] == "machine-pass-pending-visual", verify["status"]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

recorded = {item["path"]: item["sha256"] for item in report["inputs"]}
for path, sha in recorded.items():
    assert digest(path) == sha, f"输入摘要变化：{path}"
for resource in report["resources"]:
    assert digest(resource["path"]) == resource["sha256"], resource["path"]
print("输入与资源摘要一致")
PY

echo "==> 回归：多行块公式、显式锚点与深层标题映射"
python3 - "$TMP/work" <<'PY'
import json, sys
from pathlib import Path

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
chapter = report["chapters"][0]
forms = [m["original_form"] for m in chapter["math"]]
assert forms.count("dollar_block") >= 2, f"多行 $$ 块公式未被识别：{forms}"
assert chapter.get("anchors") == ["custom-spot"], \
    f"代码中的锚点被误注册：{chapter.get('anchors')}"
deep = [h for h in chapter["headings"] if h["text"].startswith("深层")]
assert len(deep) == 3 and all(h["level"] == 6 for h in deep), f"深层标题数量/层级错误：{deep}"
assert [h["source_level"] for h in deep] == [7, 7, 7], deep
codes = [d["code"] for d in report["diagnostics"]]
assert codes.count("deep-heading-mapped") == 3, f"深层标题映射未全部报告：{codes}"
print("多行块公式、代码内锚点排除与深层标题映射均生效")
PY
python3 - "$TMP/out/demo.pdf" <<'PY'
import sys
import pypdf

text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[1]).pages)
for probe in ("PDFANCHORPLACEHOLDER", "PDFDEEPHEADINGPLACEHOLDER"):
    assert probe not in text, f"占位符泄漏为正文：{probe}"
assert "code-sample-anchor" in text, "行内代码中的锚点字面文本丢失"
assert "nested-anchor" in text, "嵌套围栏中的锚点字面文本丢失"
assert "紧随深层A的正文段落" in text, "深层标题后继正文丢失"
for probe in ("深层A紧接正文", "深层B紧接深层A", "深层C独立成段"):
    assert probe in text, f"深层标题文本丢失：{probe}"
print("占位符未泄漏，代码字面与深层标题文本均在 PDF 中")
PY

echo "==> 回归：离线路由拦截记录（A6，导出器始终禁外网）"
python3 - "$TMP/work" <<'PY'
import json, sys
from pathlib import Path

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
assert report["status"] == "machine-pass-pending-visual"
assert report["browser_checks"]["katex"] == [], "存在公式渲染错误"
assert report["browser_checks"]["images"] == [], "存在图片解码失败"
assert report["browser_checks"]["overflow"] == [], "存在溢出内容"
fonts = report["browser_checks"]["fonts"]
assert any(fonts.values()), f"未检测到可用中文字体：{fonts}"
print("浏览器层检查通过：公式、图片、溢出、字体")
PY

echo "==> 失败回归：缺图必须定位到文件与行且不覆盖已有成功 PDF"
cp "$TMP/sample.md" "$TMP/missing_image.md"
python3 - "$TMP/missing_image.md" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read().replace(
    "![演示图片](images/pattern_a.png)", "![演示图片](images/not_exist.png)")
open(path, "w", encoding="utf-8").write(text)
PY
printf 'PREEXISTING-SUCCESSFUL-PDF' > "$TMP/out/keep.pdf"
if python3 "$EXPORT" --output "$TMP/out/keep.pdf" --work-dir "$TMP/work_fail1" "$TMP/missing_image.md" 2>"$TMP/err1.txt"; then
  echo "错误：缺图未被检出"; exit 1
fi
grep -q "missing-image" "$TMP/err1.txt" || { echo "错误：缺图诊断缺失"; cat "$TMP/err1.txt"; exit 1; }
grep -q "not_exist.png" "$TMP/err1.txt" || { echo "错误：缺图未定位到资源"; cat "$TMP/err1.txt"; exit 1; }
grep -q "missing_image.md" "$TMP/err1.txt" || { echo "错误：缺图未定位到输入文件"; cat "$TMP/err1.txt"; exit 1; }
[ "$(cat "$TMP/out/keep.pdf")" = "PREEXISTING-SUCCESSFUL-PDF" ] \
  || { echo "错误：失败导出覆盖了已有成功 PDF"; exit 1; }
[ ! -f "$TMP/out/demo.pdf" ] && { echo "错误：成功 PDF 被删除"; exit 1; }
echo "缺图已定位且既有成功 PDF 保持不变"

echo "==> 失败回归：坏内部目标必须报 FAIL"
cp "$TMP/sample.md" "$TMP/broken_anchor.md"
python3 - "$TMP/broken_anchor.md" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read().replace(
    "](#12-第二个子节)", "](#不存在的锚点)")
open(path, "w", encoding="utf-8").write(text)
PY
if python3 "$EXPORT" --output "$TMP/out/broken.pdf" --work-dir "$TMP/work_fail2" "$TMP/broken_anchor.md" 2>"$TMP/err2.txt"; then
  echo "错误：坏内部目标未被检出"; exit 1
fi
grep -q "broken-internal-link" "$TMP/err2.txt" || { echo "错误：坏目标诊断缺失"; cat "$TMP/err2.txt"; exit 1; }
echo "坏内部目标已正确报 FAIL"

echo "==> 失败回归：不支持的公式必须报 FAIL"
cp "$TMP/sample.md" "$TMP/bad_math.md"
python3 - "$TMP/bad_math.md" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read().replace(
    "$$E = m c^2$$", "$$E = \\notacommand{$x}$$")
open(path, "w", encoding="utf-8").write(text)
PY
if python3 "$EXPORT" --output "$TMP/out/badmath.pdf" --work-dir "$TMP/work_fail3" "$TMP/bad_math.md" 2>"$TMP/err3.txt"; then
  echo "错误：不支持的公式未被检出"; exit 1
fi
grep -q "katex-error" "$TMP/err3.txt" || { echo "错误：公式失败诊断缺失"; cat "$TMP/err3.txt"; exit 1; }
echo "不支持的公式已正确报 FAIL"

echo "==> 失败回归：重复输入路径必须拒绝"
if python3 "$EXPORT" --output "$TMP/out/dup.pdf" --work-dir "$TMP/work_fail4" \
    "$TMP/sample.md" "$TMP/missing_image.md" "$TMP/sample.md" 2>"$TMP/err4.txt"; then
  echo "错误：重复输入未被拒绝"; exit 1
fi
grep -q "重复" "$TMP/err4.txt" || { echo "错误：重复输入诊断缺失"; cat "$TMP/err4.txt"; exit 1; }
echo "重复输入已拒绝"

echo "==> 失败回归：输出路径不得指向输入文件"
if python3 "$EXPORT" --output "$TMP/sample.md" --work-dir "$TMP/work_fail5" "$TMP/sample.md" 2>"$TMP/err5.txt"; then
  echo "错误：输出指向输入未被拒绝"; exit 1
fi
grep -q "不得指向输入" "$TMP/err5.txt" || { echo "错误：输出保护诊断缺失"; cat "$TMP/err5.txt"; exit 1; }
echo "输出路径保护生效"

echo "==> 阶段02：有序两章合订（给定顺序不同于文件名字典序）"
mkdir -p "$TMP/comp/A_images" "$TMP/comp/B_images"
python3 - "$TMP" <<'PY'
import struct, sys, zlib

def chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

def png(path, rgb):
    w = h = 24
    raw = b"".join(b"\x00" + bytes(rgb * w) for _ in range(h))
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    open(path, "wb").write(data)

png(sys.argv[1] + "/_comp_a.png", (200, 40, 40))
png(sys.argv[1] + "/_comp_b.png", (40, 40, 200))
PY
cp "$TMP/_comp_a.png" "$TMP/comp/A_images/shared.png"
cp "$TMP/_comp_b.png" "$TMP/comp/B_images/shared.png"

cat > "$TMP/comp/z_second.md" <<'MD'
# 第二章 A（顺序测试）

本章目录：[同名小节](#同名小节)，另见 [A 章引用](https://example.com/a)。跨章文件链接：[打开第一章 B](a_first.md)，跨章小节链接：[第一章 B 的同名小节](a_first.md#同名小节)。

## 同名小节

正文 A 的内容，引用脚注[^1]。下方为 A 章专属图片：

![共享图](A_images/shared.png)

引用定义链接指向 [A 章定义][shared-def]。

[shared-def]: https://example.com/def-a

[^1]: A 章注文。
MD

cat > "$TMP/comp/a_first.md" <<'MD'
# 第一章 B（顺序测试）

本章目录：[同名小节](#同名小节)，另见 [B 章引用](https://example.com/b)。跨章跳转：[第二章 A](#第二章-a顺序测试)。

## 同名小节

正文 B 的内容，引用脚注[^1]。下方为 B 章专属图片：

![共享图](B_images/shared.png)

引用定义链接指向 [B 章定义][shared-def]。

[shared-def]: https://example.com/def-b

[^1]: B 章注文。
MD

python3 "$EXPORT" --output "$TMP/out/comp.pdf" --work-dir "$TMP/work_comp" \
  "$TMP/comp/z_second.md" "$TMP/comp/a_first.md"
python3 "$VERIFY" --pdf "$TMP/out/comp.pdf" --work-dir "$TMP/work_comp" \
  "$TMP/comp/z_second.md" "$TMP/comp/a_first.md"

python3 - "$TMP/work_comp" <<'PY'
import json, sys
from pathlib import Path

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
chapters = report["chapters"]
assert len(chapters) == 2
imgs = {c["index"]: c["images"][0]["sha256"] for c in chapters}
assert imgs[1] != imgs[2], "同名不同内容图片被串用"
assert report["chapters"][0]["path"].endswith("z_second.md")
print("合订：图片按来源身份区分，输入顺序保持")
PY

python3 - "$TMP/out/comp.pdf" <<'PY'
import re
import sys
import unicodedata

import pypdf

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

reader = pypdf.PdfReader(sys.argv[1])
full = norm("".join(p.extract_text() or "" for p in reader.pages))
pos_a = full.find("第二章A")
pos_b = full.find("第一章B")
body_a = full.find("正文A的内容")
body_b = full.find("正文B的内容")
note_a = full.find("A章注文")
note_b = full.find("B章注文")
assert 0 <= pos_a < pos_b, "章节顺序未遵循参数顺序"
assert 0 <= body_a < body_b, "正文顺序错误"
assert 0 <= note_a < note_b, "脚注注文串章"
assert pos_a >= 0 and reader.pages, "首页缺失"
first_page_text = norm(reader.pages[0].extract_text())
assert "第二章A" in first_page_text, "首章未从首页开始"
print("合订：顺序、正文与注文各归各章，首章无空白首页")
PY

echo "==> 阶段02：跨章小节链接（b.md#target）必须转内部跳转"
python3 - "$TMP/work_comp" <<'PY'
import json, sys
from pathlib import Path

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
links = report["chapters"][0]["internal_links"]
section = [l for l in links if l["fragment"] == "同名小节" and l["resolved"].startswith("ch02-")]
assert section, f"b.md#同名小节 未转为第二章内部目标：{links}"
range_out = report["range_out_links"]
assert not any("a_first.md" in r["href"] for r in range_out), "已纳入章节被误报范围外"
print("跨章小节链接已转为内部目标，未误报范围外")
PY

echo "==> 阶段02：跨章链接片段缺失必须报 FAIL"
cp "$TMP/comp/z_second.md" "$TMP/comp/bad_fragment.md"
python3 - "$TMP/comp/bad_fragment.md" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read().replace(
    "](a_first.md#同名小节)", "](a_first.md#不存在的片段)")
open(path, "w", encoding="utf-8").write(text)
PY
if python3 "$EXPORT" --output "$TMP/out/comp_frag.pdf" --work-dir "$TMP/work_comp_frag" \
    "$TMP/comp/bad_fragment.md" "$TMP/comp/a_first.md" 2>"$TMP/err_frag.txt"; then
  echo "错误：跨章片段缺失未被检出"; exit 1
fi
grep -q "broken-internal-link" "$TMP/err_frag.txt" || { echo "错误：跨章片段诊断缺失"; cat "$TMP/err_frag.txt"; exit 1; }
echo "跨章片段缺失已正确报 FAIL"

echo "==> 阶段02：合订中坏内部目标必须报 FAIL"
cp "$TMP/comp/a_first.md" "$TMP/comp/bad_target.md"
python3 - "$TMP/comp/bad_target.md" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read().replace("](#同名小节)", "](#不存在的锚点)")
open(path, "w", encoding="utf-8").write(text)
PY
if python3 "$EXPORT" --output "$TMP/out/comp_bad.pdf" --work-dir "$TMP/work_comp_bad" \
    "$TMP/comp/z_second.md" "$TMP/comp/bad_target.md" 2>"$TMP/err_comp.txt"; then
  echo "错误：合订坏目标未被检出"; exit 1
fi
grep -q "broken-internal-link" "$TMP/err_comp.txt" || { echo "错误：合订坏目标诊断缺失"; cat "$TMP/err_comp.txt"; exit 1; }
echo "合订坏目标已正确报 FAIL"

echo "==> 阶段02：同一路径不同拼写必须拒绝"
if python3 "$EXPORT" --output "$TMP/out/dup2.pdf" --work-dir "$TMP/work_dup2" \
    "$TMP/comp/z_second.md" "$TMP/comp/./z_second.md" 2>"$TMP/err_dup2.txt"; then
  echo "错误：不同拼写的重复输入未被拒绝"; exit 1
fi
grep -q "重复" "$TMP/err_dup2.txt" || { echo "错误：重复拼写诊断缺失"; cat "$TMP/err_dup2.txt"; exit 1; }
echo "不同拼写的重复输入已拒绝"

echo "==> 阶段02：缺失输入文件必须拒绝"
if python3 "$EXPORT" --output "$TMP/out/miss.pdf" --work-dir "$TMP/work_miss" \
    "$TMP/comp/z_second.md" "$TMP/comp/not_exist.md" 2>"$TMP/err_miss.txt"; then
  echo "错误：缺失输入未被拒绝"; exit 1
fi
grep -q "不存在" "$TMP/err_miss.txt" || { echo "错误：缺失输入诊断缺失"; cat "$TMP/err_miss.txt"; exit 1; }
echo "缺失输入文件已拒绝"

echo "==> 阶段02：链接到无标题章节不崩溃且转为章容器目标"
cat > "$TMP/comp/c_plain.md" <<'MD'
这一章只有正文段落，没有任何标题。
MD
cp "$TMP/comp/z_second.md" "$TMP/comp/z_with_plain.md"
python3 - "$TMP/comp/z_with_plain.md" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text += "再链接无标题章节：[只有正文的章](c_plain.md)。\n"
open(path, "w", encoding="utf-8").write(text)
PY
python3 "$EXPORT" --output "$TMP/out/with_plain.pdf" --work-dir "$TMP/work_plain" \
  "$TMP/comp/z_with_plain.md" "$TMP/comp/a_first.md" "$TMP/comp/c_plain.md"
python3 "$VERIFY" --pdf "$TMP/out/with_plain.pdf" --work-dir "$TMP/work_plain" \
  "$TMP/comp/z_with_plain.md" "$TMP/comp/a_first.md" "$TMP/comp/c_plain.md"
python3 - "$TMP/work_plain" <<'PY'
import json, sys
from pathlib import Path

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
links = report["chapters"][0]["internal_links"]
plain = [l for l in links if l["resolved"] == "ch03-body"]
assert plain, f"无标题章节链接未转为章容器目标：{links}"
print("无标题章节链接转为章容器目标，导出无崩溃")
PY

echo "==> 失败回归：宽松（数学穿插）匹配也必须单调消费，重复内容缺份判 FAIL"
python3 - <<'PY'
import sys

sys.path.insert(0, "../skills/tech-doc-translator/scripts")
import verify_pdf


class FakePdf:
    norm_text = "AxB"
    page_offsets = [(0, 3)]

    def find(self, needle, start=0):
        return -1


class FakeChapter:
    path = "fake.md"
    blocks = [{"segments": ["AB"]}, {"segments": ["AB"]}]


failures = []
relaxed = []
verify_pdf.check_blocks(
    [FakeChapter()], FakePdf(), [(FakeChapter(), 0, 1)], failures, relaxed, "text"
)
assert len(relaxed) == 1 and len(failures) == 1, (failures, relaxed)
assert failures[0]["code"] == "text-missing", failures
print("宽松匹配游标单调推进，第二段缺失已判 FAIL")
PY

echo "==> 失败回归：核验输入重复代码块而 PDF 缺一份必须判 FAIL（单调消费）"
python3 - "$TMP/sample.md" "$TMP/sample_single.md" "$TMP/sample_dup.md" <<'PY'
import sys

text = open(sys.argv[1], encoding="utf-8").read()
block = "```python\ndef hello(name):\n    # 中文注释：code with $dollars$ stays\n    print(f\"hi {name}\")\n```\n"
open(sys.argv[2], "w", encoding="utf-8").write(
    text.replace(block, "```python\nprint(1)\n```\n"))
open(sys.argv[3], "w", encoding="utf-8").write(
    text.replace(block, "```python\nprint(1)\n```\n```python\nprint(1)\n```\n"))
PY
python3 "$EXPORT" --output "$TMP/out/single.pdf" --work-dir "$TMP/work_single" "$TMP/sample_single.md" >/dev/null
if python3 "$VERIFY" --pdf "$TMP/out/single.pdf" --work-dir "$TMP/work_single" \
    "$TMP/sample_dup.md" 2>"$TMP/err_dup_block.txt"; then
  echo "错误：重复代码块缺份未被检出"; exit 1
fi
grep -q "code-missing" "$TMP/err_dup_block.txt" || { echo "错误：重复块缺失诊断缺失"; cat "$TMP/err_dup_block.txt"; exit 1; }
echo "重复代码块缺份已正确判 FAIL"

echo "==> 复审修复：跨行行内代码中的 ####### 不得拆为深层标题"
cat > "$TMP/inline_deep.md" <<'MD'
# 行内代码跨行样例

Example: `begin
####### literal
end`

####### 真深层标题

结尾段落。
MD
python3 "$EXPORT" --output "$TMP/out/inline_deep.pdf" --work-dir "$TMP/work_inline_deep" "$TMP/inline_deep.md"
python3 "$VERIFY" --pdf "$TMP/out/inline_deep.pdf" --work-dir "$TMP/work_inline_deep" "$TMP/inline_deep.md"
python3 - "$TMP/work_inline_deep" "$TMP/out/inline_deep.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
chapter = report["chapters"][0]
texts = [h["text"] for h in chapter["headings"]]
assert texts == ["行内代码跨行样例", "真深层标题"], \
    f"####### 行被误判为标题或真深层标题丢失：{texts}"
deep = [h for h in chapter["headings"] if h.get("source_level")]
assert len(deep) == 1 and deep[0]["text"] == "真深层标题", deep
codes = [d["code"] for d in report["diagnostics"]]
assert codes.count("deep-heading-mapped") == 1, f"深层标题映射报告数错误：{codes}"

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
assert "begin#######literalend" in text, "跨行行内代码内容（含 #######）在 PDF 中丢失"
assert "PDFDEEPHEADINGPLACEHOLDER" not in text and "PDFANCHORPLACEHOLDER" not in text
print("跨行行内代码保留 #######，未被拆为深层标题；真深层标题仍正常映射")
PY

echo "==> 复审修复：第 11 个显式锚点不得发生占位符碰撞"
{
  echo "# 锚点碰撞回归"
  echo
  for i in $(seq 0 10); do
    printf '<a id="a%d"></a> 标记 %d，[跳到 a%d](#a%d)。\n\n' "$i" "$i" "$i" "$i"
  done
} > "$TMP/anchor_collision.md"
python3 "$EXPORT" --output "$TMP/out/anchors.pdf" --work-dir "$TMP/work_anchors" "$TMP/anchor_collision.md"
python3 "$VERIFY" --pdf "$TMP/out/anchors.pdf" --work-dir "$TMP/work_anchors" "$TMP/anchor_collision.md"
python3 - "$TMP/work_anchors" "$TMP/out/anchors.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
chapter = report["chapters"][0]
assert chapter["anchors"] == ["a%d" % i for i in range(11)], \
    f"锚点身份不唯一或丢失：{chapter['anchors']}"
links = {l["fragment"]: l["resolved"] for l in chapter["internal_links"]}
assert links == {"a%d" % i: "ch01-a%d" % i for i in range(11)}, links

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
assert "PDFANCHORPLACEHOLDER" not in text, "占位符泄漏为正文"
for i in range(11):
    assert norm("标记%d，跳到a%d。" % (i, i)) in text, f"标记 {i} 正文异常（可能有残留数字）"
print("11 个显式锚点身份唯一，跳转消解正确，正文无占位符残留")
PY

echo "==> 复审修复：无标题章节必须通过导出与独立核验全流程"
mkdir -p "$TMP/plain_ch"
cat > "$TMP/plain_ch/a_min.md" <<'MD'
# 有标题章

正文 A，链接到 [B 章](b_min.md)。
MD
cat > "$TMP/plain_ch/b_min.md" <<'MD'
B 章只有正文段落，没有任何标题，用于验证无标题章节的边界与链接目标。
MD
python3 "$EXPORT" --output "$TMP/out/plain_min.pdf" --work-dir "$TMP/work_plain_min" \
  "$TMP/plain_ch/a_min.md" "$TMP/plain_ch/b_min.md"
python3 "$VERIFY" --pdf "$TMP/out/plain_min.pdf" --work-dir "$TMP/work_plain_min" \
  "$TMP/plain_ch/a_min.md" "$TMP/plain_ch/b_min.md"
python3 - "$TMP/work_plain_min" <<'PY'
import json, sys
from pathlib import Path

verify = json.loads((Path(sys.argv[1]) / "verify_report.json").read_text(encoding="utf-8"))
assert verify["status"] == "machine-pass-pending-visual", verify["failures"]
report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
links = report["chapters"][0]["internal_links"]
assert any(l["resolved"] == "ch02-body" for l in links), links
print("无标题章节：导出与核验全流程通过，链接指向章容器目标")
PY

echo "==> 复审修复：无标题章节正文核验不得被跳过（篡改输入必须报 FAIL）"
cp "$TMP/plain_ch/b_min.md" "$TMP/plain_ch/b_tampered.md"
python3 - "$TMP/plain_ch/b_tampered.md" <<'PY'
import sys
path = sys.argv[1]
with open(path, "a", encoding="utf-8") as handle:
    handle.write("\n被篡改后新增的段落，PDF 中并不存在。\n")
PY
if python3 "$VERIFY" --pdf "$TMP/out/plain_min.pdf" --work-dir "$TMP/work_plain_min" \
    "$TMP/plain_ch/a_min.md" "$TMP/plain_ch/b_tampered.md" 2>"$TMP/err_plain.txt"; then
  echo "错误：无标题章节正文核验被跳过"; exit 1
fi
grep -q "text-missing" "$TMP/err_plain.txt" || { echo "错误：篡改内容未检出"; cat "$TMP/err_plain.txt"; exit 1; }
echo "无标题章节正文核验未被跳过"

echo "==> 复审修复：转义反引号不得破坏跨行行内代码"
cat > "$TMP/escaped_tick.md" <<'MD'
# 转义反引号样例

Example: \`ignored `begin
####### literal
end`

####### 真深层标题

结尾段落。
MD
python3 "$EXPORT" --output "$TMP/out/escaped_tick.pdf" --work-dir "$TMP/work_escaped" "$TMP/escaped_tick.md"
python3 "$VERIFY" --pdf "$TMP/out/escaped_tick.pdf" --work-dir "$TMP/work_escaped" "$TMP/escaped_tick.md"
python3 - "$TMP/work_escaped" "$TMP/out/escaped_tick.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
texts = [h["text"] for h in report["chapters"][0]["headings"]]
assert texts == ["转义反引号样例", "真深层标题"], \
    f"转义反引号使 ####### 行被误判为标题：{texts}"

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
assert norm("Example: `ignored") in text, "转义反引号的字面文本丢失"
assert "begin#######literalend" in text, "跨行行内代码内容（含 #######）丢失"
assert norm("真深层标题") in text, "真深层标题丢失"
assert "PDFDEEPHEADINGPLACEHOLDER" not in text and "PDFANCHORPLACEHOLDER" not in text
print("转义反引号保持字面，跨行行内代码保留 #######，深层标题仍正常映射")
PY

echo "==> 复审修复：两章正文重复时无标题章节不得定位到上一章"
mkdir -p "$TMP/dup_ch"
cat > "$TMP/dup_ch/a_dup.md" <<'MD'
# A 章标题

Same paragraph.

A 章独有段落，[打开 B 章](b_dup.md)。
MD
cat > "$TMP/dup_ch/b_dup.md" <<'MD'
Same paragraph.

B 章独有段落。
MD
python3 "$EXPORT" --output "$TMP/out/dup.pdf" --work-dir "$TMP/work_dup" \
  "$TMP/dup_ch/a_dup.md" "$TMP/dup_ch/b_dup.md"
python3 "$VERIFY" --pdf "$TMP/out/dup.pdf" --work-dir "$TMP/work_dup" \
  "$TMP/dup_ch/a_dup.md" "$TMP/dup_ch/b_dup.md"
python3 - "$TMP/work_dup" <<'PY'
import json, sys
from pathlib import Path

verify = json.loads((Path(sys.argv[1]) / "verify_report.json").read_text(encoding="utf-8"))
assert verify["status"] == "machine-pass-pending-visual", verify["failures"]
report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
links = report["chapters"][0]["internal_links"]
assert any(l["resolved"] == "ch02-body" for l in links), links
print("重复正文下无标题章节按章容器定位，链接目标不再误报")
PY

echo "==> 复审修复：标题行内含代码不得整行误判为代码内容"
cat > "$TMP/heading_code.md" <<'MD'
# 标题内代码样例

####### Use ``foo`` and bar

结尾段落。
MD
python3 "$EXPORT" --output "$TMP/out/heading_code.pdf" --work-dir "$TMP/work_hcode" "$TMP/heading_code.md"
python3 "$VERIFY" --pdf "$TMP/out/heading_code.pdf" --work-dir "$TMP/work_hcode" "$TMP/heading_code.md"
python3 - "$TMP/work_hcode" "$TMP/out/heading_code.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

headings = [norm(h["text"]) for h in report["chapters"][0]["headings"]]
assert norm("Use foo and bar") in headings, \
    f"含行内代码的深层标题丢失或文本错误：{headings}"

text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
assert "Usefooandbar" in text, "标题文字在 PDF 中不完整"
print("标题前缀不在代码内：标题被计数并转换，行内代码按代码渲染")
PY

echo "==> 复审修复：深层标题中的公式必须渲染"
cat > "$TMP/deep_math.md" <<'MD'
# 深层公式样例

####### The $x^2$ norm

结尾段落 $a+b$。
MD
python3 "$EXPORT" --output "$TMP/out/deep_math.pdf" --work-dir "$TMP/work_dmath" "$TMP/deep_math.md"
python3 "$VERIFY" --pdf "$TMP/out/deep_math.pdf" --work-dir "$TMP/work_dmath" "$TMP/deep_math.md"
python3 - "$TMP/work_dmath" "$TMP/out/deep_math.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
chapter = report["chapters"][0]
latex = sorted(m["latex"] for m in chapter["math"])
assert latex == ["a+b", "x^2"], f"深层标题公式未进入渲染清单：{latex}"
assert report["browser_checks"]["katex"] == [], "公式渲染失败"

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

recorded = [norm(h["text"]) for h in chapter["headings"] if h["text"].startswith("The")]
assert recorded == [norm("The norm")], f"含公式的标题文本记录异常：{recorded}"
text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
assert "$x^2$" not in text, "公式原始标记泄漏进成品"
print("深层标题公式已渲染：进入公式清单、KaTeX 无错误、无标记泄漏")
PY

echo "==> 复审修复：无入链的无标题章节在重复正文下独立定位"
mkdir -p "$TMP/same_ch"
cat > "$TMP/same_ch/a_same.md" <<'MD'
# A 章标题

Same paragraph.
MD
cat > "$TMP/same_ch/b_same.md" <<'MD'
Same paragraph.
MD
python3 "$EXPORT" --output "$TMP/out/same.pdf" --work-dir "$TMP/work_same" \
  "$TMP/same_ch/a_same.md" "$TMP/same_ch/b_same.md"
python3 "$VERIFY" --pdf "$TMP/out/same.pdf" --work-dir "$TMP/work_same" \
  "$TMP/same_ch/a_same.md" "$TMP/same_ch/b_same.md"

echo "==> 复审修复：无入链章节整页清空后必须报 FAIL（不得复用上一章正文）"
python3 - "$TMP/out/same.pdf" "$TMP/out/same_blank.pdf" <<'PY'
import sys

import pypdf

reader = pypdf.PdfReader(sys.argv[1])
writer = pypdf.PdfWriter(clone_from=reader)
# 清空第二章所在页的内容、保留总页数：正文完全缺失但文档结构仍在。
writer.pages[1].replace_contents(None)
with open(sys.argv[2], "wb") as handle:
    writer.write(handle)
PY
if python3 "$VERIFY" --pdf "$TMP/out/same_blank.pdf" --work-dir "$TMP/work_same" \
    "$TMP/same_ch/a_same.md" "$TMP/same_ch/b_same.md" 2>"$TMP/err_same.txt"; then
  echo "错误：整章正文丢失未被检出（复用了上一章正文）"; exit 1
fi
grep -q "text-missing" "$TMP/err_same.txt" || { echo "错误：缺少 text-missing 诊断"; cat "$TMP/err_same.txt"; exit 1; }
echo "无入链章节整页清空已检出，未复用上一章正文"

echo "==> Ticket 01 PDF 导出回归全部通过"
