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
FIXTURE_IMAGE="fixtures/valid_1x1.png"
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

echo "==> V0.2-01：章首管理字段投影与术语表默认排除（真实模板结构）"
cat > "$TMP/head_chapter.md" <<'MD'
# CUDA Programming Guide 中文翻译 —— 第 1 章 Introduction to CUDA

> **原文**：CUDA Programming Guide，版本 v13.3
> **来源**：https://docs.nvidia.com/cuda/cuda-programming-guide/
> **抓取日期**：2026-08-28
>
> **译例说明**：
> - 本文档为第 1 章 *Introduction to CUDA* 的中文翻译；
> - 术语译法遵循本项目 [术语表](术语表.md)；

---

# 1. Introduction to CUDA（CUDA 导论）

正文提到“原文”与“译例说明”同名文字，必须完整保留。术语登记见 [项目术语表](术语表.md)；工作流程见 [流程说明](flow.md)。

```text
> **原文**：代码围栏中的字面字段行，必须原样保留。
```

结尾段落：CUDA 是并行计算平台。
MD
cat > "$TMP/术语表.md" <<'MD'
# 术语表

| 英文 | 中文 |
|---|---|
| kernel | 核函数 |
MD
cat > "$TMP/flow.md" <<'MD'
# 流程说明

范围外但存在的本地文档。
MD
BEFORE_SHA=$(python3 - "$TMP/head_chapter.md" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())
PY
)
python3 "$EXPORT" --output "$TMP/out/head.pdf" --work-dir "$TMP/work_head" \
  --unlink-target "$TMP/术语表.md" "$TMP/head_chapter.md" >"$TMP/out_head.txt" 2>&1 \
  || { cat "$TMP/out_head.txt"; echo "错误：章首投影导出失败"; exit 1; }
grep -q "已按默认排除目标转为纯文本的链接" "$TMP/out_head.txt" \
  || { cat "$TMP/out_head.txt"; echo "错误：术语表链接纯文本投影未在输出中记录"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/out/head.pdf" --work-dir "$TMP/work_head" \
  --unlink-target "$TMP/术语表.md" "$TMP/head_chapter.md"
python3 - "$TMP/work_head" "$TMP/out/head.pdf" "$TMP/head_chapter.md" "$BEFORE_SHA" <<'PY'
import hashlib, json, re, sys, unicodedata
from pathlib import Path

import pypdf

work, pdf_path, md_path, before = sys.argv[1:]
report = json.loads((Path(work) / "export_report.json").read_text(encoding="utf-8"))
chapter = report["chapters"][0]
assert [(s["label"], s["start_line"], s["end_line"]) for s in chapter["management_exclusions"]] \
    == [("原文", 3, 3), ("译例说明", 7, 9)], chapter["management_exclusions"]
unlinked = chapter["unlinked_links"]
# 头部字段内的 [术语表](术语表.md) 已随授权投影移除；只有正文链接转纯文本。
assert [u["text"] for u in unlinked] == ["项目术语表"], unlinked
assert not any(u["href"] == "flow.md" for u in unlinked), "范围外链接被误转为纯文本"
assert all("术语表" not in l["href"] for l in chapter["internal_links"]), "术语表链接仍为内部链接"
range_out = [r["href"] for r in report["range_out_links"]]
assert "flow.md" in range_out, "范围外本地链接未显式报告"

assert hashlib.sha256(open(md_path, 'rb').read()).hexdigest() == before, "输入 Markdown 被修改"

def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))

text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(pdf_path).pages))
for probe in ("原文：CUDAProgrammingGuide，版本v13.3",
              "术语译法遵循本项目",
              "本文档为第1章"):
    assert probe not in text, f"被排除字段内容泄漏进 PDF：{probe}"
for keep in ("来源：https://docs.nvidia.com/cuda/cuda-programming-guide/",
             "抓取日期：2026-08-28",
             "正文提到“原文”与“译例说明”同名文字，必须完整保留",
             ">**原文**：代码围栏中的字面字段行，必须原样保留。",
             "项目术语表",
             "CUDA是并行计算平台"):
    assert norm(keep) in text, f"应保留内容缺失：{keep}"
print("章首字段排除、来源保留、正文/代码同名文字与术语表链接纯文本均正确")
PY

echo "==> V0.2-01：伪造排除证据必须 FAIL（核验器不信任导出清单）"
python3 - "$TMP/work_head" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
# 伪造：把正文首段行区间也宣称为授权排除。
report["chapters"][0]["management_exclusions"].append(
    {"label": "原文", "start_line": 15, "end_line": 16,
     "reason": "章首管理字段默认排除（获准投影，Markdown 保留）"})
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY
if python3 "$VERIFY" --pdf "$TMP/out/head.pdf" --work-dir "$TMP/work_head" \
  --unlink-target "$TMP/术语表.md" "$TMP/head_chapter.md" 2>"$TMP/err_forge.txt"; then
  echo "错误：伪造排除证据未被检出"; exit 1
fi
grep -q "exclusion-evidence-mismatch\|exclusion-unauthorized" "$TMP/err_forge.txt" \
  || { echo "错误：伪造排除诊断缺失"; cat "$TMP/err_forge.txt"; exit 1; }

echo "==> V0.2-01：核验侧 --unlink-target 与导出侧不一致必须 FAIL"
if python3 "$VERIFY" --pdf "$TMP/out/head.pdf" --work-dir "$TMP/work_head" \
  "$TMP/head_chapter.md" 2>"$TMP/err_unlink.txt"; then
  echo "错误：unlink 参数不一致未被检出"; exit 1
fi
grep -q "unlink-targets-mismatch\|unlink-projection-mismatch\|unlinked-text-missing" "$TMP/err_unlink.txt" \
  || { echo "错误：unlink 不一致诊断缺失"; cat "$TMP/err_unlink.txt"; exit 1; }
# 还原证据，供后续复用
python3 - "$TMP/work_head" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["chapters"][0]["management_exclusions"] = [
    s for s in report["chapters"][0]["management_exclusions"] if s["start_line"] < 10]
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "==> V0.2-02：图片显示尺寸链路（高像素小宽、超版心、同名不同图、同图不同宽度、无映射回退）"
mkdir -p "$TMP/disp/a_imgs" "$TMP/disp/b_imgs"
python3 - "$TMP/disp" <<'PY'
import hashlib, struct, sys, zlib
from pathlib import Path

root = Path(sys.argv[1])

def chunk(tag, data):
    c = struct.pack('>I', len(data)) + tag + data
    return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

def png(path, rgb, w=1200, h=800):
    raw = b''.join(b'\x00' + bytes(rgb * w) for _ in range(h))
    data = (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()

digests = {}
digests['a/w300'] = png(root / 'a_imgs/w300.png', (200, 30, 30))
digests['a/same'] = png(root / 'a_imgs/same.png', (30, 200, 30))
digests['a/natural'] = png(root / 'a_imgs/natural.png', (30, 30, 200))
digests['b/same'] = png(root / 'b_imgs/same.png', (200, 120, 30))   # 同名不同内容
digests['b/w900'] = png(root / 'b_imgs/w900.png', (120, 30, 200))

(root / 'a.md').write_text(
    '# A 章\n\n![小宽](a_imgs/w300.png)\n\n![共享图 A](a_imgs/same.png)\n\n'
    '![自然尺寸](a_imgs/natural.png)\n', encoding='utf-8')
(root / 'b.md').write_text(
    '# B 章\n\n![共享图 B](b_imgs/same.png)\n\n![超版心](b_imgs/w900.png)\n',
    encoding='utf-8')

entries = [
    {'markdown': 'a.md', 'occurrence': 1, 'image': 'a_imgs/w300.png',
     'sha256': digests['a/w300'],
     'width': {'value': 300, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None},
     'source': {'snapshot': 'a.html', 'node': 'img[0]'}},
    {'markdown': 'a.md', 'occurrence': 2, 'image': 'a_imgs/same.png',
     'sha256': digests['a/same'],
     'width': {'value': 454, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None},
     'source': {'snapshot': 'a.html', 'node': 'img[1]'}},
    # 同一 basename 在 B 章是另一资源、另一宽度：按出现与身份绑定，不按名字。
    {'markdown': 'b.md', 'occurrence': 1, 'image': 'b_imgs/same.png',
     'sha256': digests['b/same'],
     'width': {'value': 250, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None},
     'source': {'snapshot': 'b.html', 'node': 'img[0]'}},
    {'markdown': 'b.md', 'occurrence': 2, 'image': 'b_imgs/w900.png',
     'sha256': digests['b/w900'],
     'width': {'value': 900, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None},
     'source': {'snapshot': 'b.html', 'node': 'img[1]'}},
]
(root / 'images_display.json').write_text(
    __import__('json').dumps({'version': 1, 'entries': entries},
                             ensure_ascii=False, indent=2), encoding='utf-8')
PY
python3 "$EXPORT" --output "$TMP/disp/book.pdf" --work-dir "$TMP/disp_work" \
  "$TMP/disp/a.md" "$TMP/disp/b.md" >"$TMP/disp_out.txt" 2>&1 \
  || { cat "$TMP/disp_out.txt"; echo "错误：显示尺寸导出失败"; exit 1; }
grep -q "图片显示尺寸：恢复 4 处；1 处无映射命中" "$TMP/disp_out.txt" \
  || { cat "$TMP/disp_out.txt"; echo "错误：显示尺寸恢复统计不符"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/disp/book.pdf" --work-dir "$TMP/disp_work" \
  "$TMP/disp/a.md" "$TMP/disp/b.md"
python3 - "$TMP/disp_work" "$TMP/disp/book.pdf" <<'PY'
import json, sys
from pathlib import Path

sys.path.insert(0, "../skills/tech-doc-translator/scripts")
import verify_pdf as verifier

work, pdf = sys.argv[1:]
report = json.loads((Path(work) / "export_report.json").read_text(encoding="utf-8"))
a_dir = Path(report["chapters"][0]["path"]).parent
a = {r["occurrence"]: r["applied_px"] for r in report["image_display"][str(a_dir / "a.md")]}
assert a == {1: 300.0, 2: 454.0}, a
b = {r["occurrence"]: r["applied_px"] for r in report["image_display"][str(a_dir / "b.md")]}
assert b == {1: 250.0, 2: 900.0}, b
natural = report["images_natural_fallback"]
assert natural[str(a_dir / "a.md")] == 1 and natural[str(a_dir / "b.md")] == 0, natural
capped = [r for records in report["image_display"].values() for r in records if r.get("capped")]
assert len(capped) == 1 and capped[0]["occurrence"] == 2, capped  # B 章 900px 受版心上限

# 独立量测：逐次绘制宽度与期望一致（1 CSS px = 0.75 pt，容差 0.75pt）。
# 文档顺序：A[300, 454, 自然(无映射)] + B[250, 900→封顶]。
drawn = [w for page in verifier.collect_drawn_images(verifier.PdfFacts(pdf)) for w in page]
checks = [(0, 300 * 0.75), (1, 454 * 0.75), (3, 250 * 0.75),
          (4, min(900, verifier.exporter.CONTENT_WIDTH_PX) * 0.75)]
for position, want in checks:
    assert abs(drawn[position] - want) <= 0.75, (position, drawn[position], want)
print("同图不同宽度、同名不同图按出现与身份绑定；封顶与自然回退正确")
PY

echo "==> V0.2-02：损坏映射（摘要不符/出现越界/资源错绑/非法宽度）必须 FAIL"
for case in digest occurrence binding width; do
  RM="$TMP/disp_case_$case"; rm -rf "$RM"; cp -R "$TMP/disp" "$RM"
  python3 - "$RM/images_display.json" "$case" <<'PY'
import json, sys
from pathlib import Path

path, case = sys.argv[1:]
data = json.loads(Path(path).read_text(encoding="utf-8"))
if case == 'digest':
    data['entries'][0]['sha256'] = '0' * 64
elif case == 'occurrence':
    data['entries'][0]['occurrence'] = 9
elif case == 'binding':
    data['entries'][2]['image'] = 'a_imgs/same.png'  # B 章条目指向 A 章资源
elif case == 'width':
    data['entries'][0]['width']['value'] = 0
Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY
  CH_A="$RM/a.md"; CH_B="$RM/b.md"
  if python3 "$EXPORT" --output "$RM/fail.pdf" --work-dir "$TMP/work_case_$case" \
      "$CH_A" "$CH_B" >"$TMP/case_$case.txt" 2>&1; then
    echo "错误：损坏映射（$case）未被检出"; cat "$TMP/case_$case.txt"; exit 1
  fi
done
grep -q "images-display-digest" "$TMP/case_digest.txt" || { echo "错误：摘要诊断缺失"; exit 1; }
grep -q "images-display-binding" "$TMP/case_occurrence.txt" || { echo "错误：越界诊断缺失"; exit 1; }
grep -q "images-display-binding" "$TMP/case_binding.txt" || { echo "错误：错绑诊断缺失"; exit 1; }
grep -q "images-display-invalid-width" "$TMP/case_width.txt" || { echo "错误：非法宽度诊断缺失"; exit 1; }
echo "损坏映射四类均已正确 FAIL"

echo "==> V0.2-02：核验侧映射参数与导出侧不一致必须 FAIL"
# 导出走同目录自动发现；核验显式指向另一个内容等价但路径不同的映射文件，
# 映射集合不一致本身必须被判 FAIL（不能因为内容相同而放过参数漂移）。
if python3 "$VERIFY" --pdf "$TMP/disp/book.pdf" --work-dir "$TMP/disp_work" \
    --images-display "$TMP/disp_case_digest/images_display.json" \
    "$TMP/disp/a.md" "$TMP/disp/b.md" 2>"$TMP/err_disp_arg.txt"; then
  echo "错误：显示尺寸映射参数不一致未被检出"; exit 1
fi
grep -q "images-display-maps-mismatch" "$TMP/err_disp_arg.txt" \
  || { echo "错误：映射参数诊断缺失"; cat "$TMP/err_disp_arg.txt"; exit 1; }

echo "==> V0.2-02：无映射旧译文按自然尺寸导出并在结论说明"
mv "$TMP/disp/images_display.json" "$TMP/disp/_map.json.bak"
python3 "$EXPORT" --output "$TMP/disp/natural.pdf" --work-dir "$TMP/disp_work2" \
  "$TMP/disp/a.md" "$TMP/disp/b.md" >"$TMP/natural_out.txt" 2>&1 \
  || { cat "$TMP/natural_out.txt"; exit 1; }
grep -q "按自然尺寸与版心上限导出" "$TMP/natural_out.txt" \
  || { cat "$TMP/natural_out.txt"; echo "错误：无映射回退未说明"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/disp/natural.pdf" --work-dir "$TMP/disp_work2" \
  "$TMP/disp/a.md" "$TMP/disp/b.md"
mv "$TMP/disp/_map.json.bak" "$TMP/disp/images_display.json"

echo "==> V0.2-02：同名 Markdown 按完整路径绑定；文件名兜底歧义必须 FAIL"
mkdir -p "$TMP/same/a" "$TMP/same/b"
cp "$FIXTURE_IMAGE" "$TMP/same/a/img.png"
cp "$FIXTURE_IMAGE" "$TMP/same/b/img.png"
printf '# 第 A 章\n\nA 章正文。\n\n![img](img.png)\n' > "$TMP/same/a/chapter.md"
printf '# 第 B 章\n\nB 章正文。\n\n![img](img.png)\n' > "$TMP/same/b/chapter.md"
python3 - "$TMP/same" "$FIXTURE_IMAGE" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
image = Path(sys.argv[2])
sha = hashlib.sha256(image.read_bytes()).hexdigest()
entries = []
for sub, width in (("a", 100), ("b", 200)):
    entries.append({
        "markdown": "%s/chapter.md" % sub,
        "occurrence": 1,
        "image": "%s/img.png" % sub,
        "sha256": sha,
        "width": {"value": width, "unit": "px",
                  "basis": "inline-css-width", "reference": None},
    })
(root / "full_map.json").write_text(json.dumps(
    {"version": 1, "entries": entries}, ensure_ascii=False))
(root / "base_map.json").write_text(json.dumps({"version": 1, "entries": [
    dict(entries[0], markdown="chapter.md")]}, ensure_ascii=False))
PY
python3 "$EXPORT" --output "$TMP/same/book.pdf" --work-dir "$TMP/same_work" \
  --images-display "$TMP/same/full_map.json" \
  "$TMP/same/a/chapter.md" "$TMP/same/b/chapter.md" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/same/book.pdf" --work-dir "$TMP/same_work" \
  --images-display "$TMP/same/full_map.json" \
  "$TMP/same/a/chapter.md" "$TMP/same/b/chapter.md"
python3 - "$TMP/same_work" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(
    (Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
applied = {}
for path, records in report["image_display"].items():
    applied[Path(path).parent.name] = records[0]["applied_px"]
assert applied == {"a": 100.0, "b": 200.0}, "同名章宽度串用：%s" % applied
print("同名 Markdown 按完整路径分别绑定 100px / 200px")
PY
if python3 "$EXPORT" --output "$TMP/same/amb.pdf" --work-dir "$TMP/same_amb" \
  --images-display "$TMP/same/base_map.json" \
  "$TMP/same/a/chapter.md" "$TMP/same/b/chapter.md" >"$TMP/same_amb.txt" 2>&1; then
  echo "错误：文件名兜底同名歧义未被拒绝"
  exit 1
fi
grep -q "images-display-ambiguous-markdown" "$TMP/same_amb.txt" \
  || { cat "$TMP/same_amb.txt"; echo "错误：同名歧义诊断缺失"; exit 1; }
echo "文件名兜底遇同名双章已正确 FAIL"

echo "==> 收尾 N01/N04：非导航说明与代码字面量缺失必须由内容核验检出"
mkdir -p "$TMP/neg"
cat > "$TMP/neg/00_目录.md" <<'MD'
# 负向目录

各章译文：

| 章 | 标题 | 译文文件 |
|---|---|---|
| 1 | 样例 | [01_章.md](01_章.md) |
| 2 | 再样例 | [02_章.md](02_章.md) |

维护说明（不是导航）：

- 目录重建后需要人工复核
- 此说明必须出现在 PDF 中
MD
for n in 01 02; do
  # 正文与标题不含任何数字：全文可提取文本中唯一的数字是印刷目录页码
  # 本身，N03 据此对成品可见页码做精准篡改。
  TITLE=$([ "$n" = "01" ] && echo 样例 || echo 再样例)
  cat > "$TMP/neg/${n}_章.md" <<MD
# $TITLE

> **来源**：https://example.com
>
> \`\`\`python
> print("示例")
> # **原文**：代码内的字面量行
> \`\`\`

${TITLE}章正文段落一。

## 小节

小节正文。
MD
done
NEG_IN=("$TMP/neg/00_目录.md" "$TMP/neg/01_章.md" "$TMP/neg/02_章.md")
python3 "$EXPORT" --output "$TMP/neg/base.pdf" --work-dir "$TMP/neg_work" \
  "${NEG_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/neg/base.pdf" --work-dir "$TMP/neg_work" \
  "${NEG_IN[@]}" >/dev/null || { echo "错误：基线负向样例未通过"; exit 1; }

mkdir -p "$TMP/neg2"
sed '/此说明必须出现在 PDF 中/d' "$TMP/neg/00_目录.md" > "$TMP/neg2/00_目录.md"
sed '/# \*\*原文\*\*：代码内的字面量行/d' "$TMP/neg/01_章.md" > "$TMP/neg2/01_章.md"
cp "$TMP/neg/02_章.md" "$TMP/neg2/02_章.md"
N2_IN=("$TMP/neg2/00_目录.md" "$TMP/neg2/01_章.md" "$TMP/neg2/02_章.md")
python3 "$EXPORT" --output "$TMP/neg/wrong.pdf" --work-dir "$TMP/neg_wrong" \
  "${N2_IN[@]}" >/dev/null || exit 1
python3 - "$TMP/neg_wrong" "$TMP/neg" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

work = Path(sys.argv[1])
originals = Path(sys.argv[2])
report = json.loads((work / "export_report.json").read_text(encoding="utf-8"))
# 把证据中的输入与摘要替换为原始输入：让证据一致性检查全部通过，
# 迫使核验只能靠内容/代码语义检查发现真实缺失。
digest = {}
for name in ("00_目录.md", "01_章.md", "02_章.md"):
    digest[name] = hashlib.sha256(
        (originals / name).read_bytes()).hexdigest()
for item in report.get("inputs", []):
    name = Path(item["path"]).name
    if name in digest:
        item["path"] = str(originals / name)
        item["sha256"] = digest[name]
for item in report.get("chapters", []):
    name = Path(item.get("path", "")).name
    if name in digest:
        item["path"] = str(originals / name)
        if "sha256" in item:
            item["sha256"] = digest[name]
(work / "export_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("证据已对齐原始输入")
PY
if python3 "$VERIFY" --pdf "$TMP/neg/wrong.pdf" --work-dir "$TMP/neg_wrong" \
  "${NEG_IN[@]}" >"$TMP/neg_v.txt" 2>&1; then
  echo "错误：说明/代码缺失未被检出"
  exit 1
fi
grep -q "text-missing" "$TMP/neg_v.txt" \
  || { echo "错误：说明缺失未由内容检查检出"; cat "$TMP/neg_v.txt"; exit 1; }
grep -q "code-missing" "$TMP/neg_v.txt" \
  || { echo "错误：代码字面量缺失未由代码检查检出"; cat "$TMP/neg_v.txt"; exit 1; }
echo "N01/N04：非导航说明与代码字面量缺失均由内容核验检出"

echo "==> 收尾 N02/N03：目的地交换与可见页码篡改必须由条目关联检查检出"
python3 - "$TMP/neg" "$TMP/neg_work" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

base = Path(sys.argv[1])
work = Path(sys.argv[2])
reader = PdfReader(str(base / "base.pdf"))
writer = PdfWriter(clone_from=reader)
page = writer.pages[0]
dests = []
for ref in page.get("/Annots") or []:
    annot = ref.get_object()
    if annot.get("/Subtype") == "/Link" and annot.get("/Dest") is not None:
        dests.append(annot)
assert len(dests) >= 2, dests
dests[0][NameObject("/Dest")], dests[1][NameObject("/Dest")] = (
    dests[1]["/Dest"], dests[0]["/Dest"])
out = base / "swapped.pdf"
with open(out, "wb") as handle:
    writer.write(handle)
report_path = work / "export_report.json"
report = json.loads(report_path.read_text(encoding="utf-8"))
report["pdf_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
print("已交换前两条目录链接目的地并重签 PDF 摘要")
PY
if python3 "$VERIFY" --pdf "$TMP/neg/swapped.pdf" --work-dir "$TMP/neg_work" \
  "${NEG_IN[@]}" >"$TMP/neg2_v.txt" 2>&1; then
  echo "错误：目的地交换未被检出"
  exit 1
fi
grep -q "toc-link-target\|toc-target-page" "$TMP/neg2_v.txt" \
  || { echo "错误：条目关联检查未命中目的地交换"; cat "$TMP/neg2_v.txt"; exit 1; }
echo "N02：目录链接目的地交换由条目关联检查检出"

python3 - "$TMP/neg" "$TMP/neg_work" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

base = Path(sys.argv[1])
work = Path(sys.argv[2])
report_path = work / "export_report.json"
report = json.loads(report_path.read_text(encoding="utf-8"))
# 直接篡改成品可见页码：把首条目页码数字的字形换成同字体的另一个数字
# 字形（改写目录页内容流中的 Tj 操作符），纸面与可提取文本同时显示错
# 误页码；导出记录保持诚实，摘要重签为篡改成品，只允许页码关联检查
# 失败。
printed = str(report["toc"]["entries"][0]["page"])
digit = printed[-1]
reader = PdfReader(str(base / "base.pdf"))
pages = [(page.extract_text() or "") for page in reader.pages]
full = "\n".join(pages)
occurrences = full.count(digit)
# 固定样例正文无数字：该数字在全文只应是首条目的可见页码本身。
assert occurrences == 1, "数字 %s 出现 %d 次，样例不再无数字" % (
    digit, occurrences)
target_index = next(i for i, text in enumerate(pages) if digit in text)


def char_codes(font):
    """从字体 ToUnicode 展开 code -> UTF-16BE 十六进制映射。"""
    cmap_ref = font.get("/ToUnicode")
    if cmap_ref is None:
        return {}
    text = cmap_ref.get_object().get_data().decode("latin-1")
    codes = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(
                r"<([0-9A-Fa-f]{2,4})>\s*<([0-9A-Fa-f]{4,})>", block):
            codes[int(src, 16)] = dst.upper()
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for src, end, dst in re.findall(
                r"<([0-9A-Fa-f]{2,4})>\s*<([0-9A-Fa-f]{2,4})>\s*"
                r"<([0-9A-Fa-f]{4})>", block):
            start_code, end_code = int(src, 16), int(end, 16)
            if end_code - start_code > 1024:
                continue
            for offset, code in enumerate(
                    range(start_code, end_code + 1)):
                codes[code] = "%04X" % (int(dst, 16) + offset)
    return codes


font_codes = {}
for name, ref in ((reader.pages[target_index].get("/Resources") or {})
                  .get("/Font") or {}).items():
    font_codes[name] = char_codes(ref.get_object())
digit_hex = digit.encode("utf-16-be").hex().upper()
candidates = {
    name: codes for name, codes in font_codes.items()
    if digit_hex in codes.values()
}
assert candidates, "目录页没有映射到数字 %s 的字体" % digit
codes = next(iter(candidates.values()))
src_code = next(code for code, dst in codes.items() if dst == digit_hex)
digit_set = {chr(n).encode("utf-16-be").hex().upper(): n for n in range(48, 58)}
alternatives = sorted(
    code for code, dst in codes.items()
    if dst in digit_set and code != src_code)
assert alternatives, "同字体没有其他数字字形可换"
forged_code = alternatives[0]
forged = chr(digit_set[codes[forged_code]])

writer = PdfWriter(clone_from=reader)
needle = b"<%X> Tj" % src_code
replacement = b"<%X> Tj" % forged_code
page = writer.pages[target_index]
contents = page.get_contents().get_data()
count = contents.count(needle)
assert count == 1, "页码字形操作符出现 %d 次" % count
stream = DecodedStreamObject()
stream.set_data(contents.replace(needle, replacement))
page[NameObject("/Contents")] = writer._add_object(stream)
out = base / "tampered.pdf"
with open(out, "wb") as handle:
    writer.write(handle)
check = "\n".join(
    page.extract_text() or "" for page in PdfReader(str(out)).pages)
assert check.count(digit) == 0 and check.count(forged) == full.count(forged) + 1
report["pdf_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
print("已把首条目可见页码 %s 的字形改为 %s" % (digit, forged))
PY
if python3 "$VERIFY" --pdf "$TMP/neg/tampered.pdf" --work-dir "$TMP/neg_work" \
  "${NEG_IN[@]}" >"$TMP/neg3_v.txt" 2>&1; then
  echo "错误：成品可见页码篡改未被检出"
  exit 1
fi
grep -q "toc-page-number" "$TMP/neg3_v.txt" \
  || { echo "错误：页码关联检查未命中"; cat "$TMP/neg3_v.txt"; exit 1; }
echo "N03：成品可见页码篡改由页码关联检查检出"

echo "==> 收尾 T16（PDF 级）：分篇导出的印刷目录不含范围外章节条目"
python3 "$EXPORT" --output "$TMP/neg/partial.pdf" --work-dir "$TMP/neg_partial" \
  "$TMP/neg/00_目录.md" "$TMP/neg/01_章.md" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/neg/partial.pdf" --work-dir "$TMP/neg_partial" \
  "$TMP/neg/00_目录.md" "$TMP/neg/01_章.md" \
  || { echo "错误：分篇导出未通过核验"; exit 1; }
python3 - "$TMP/neg/partial.pdf" "$TMP/neg_partial" <<'PY'
import json
import sys
from pathlib import Path

from pypdf import PdfReader

text = "\n".join(
    page.extract_text() or "" for page in PdfReader(sys.argv[1]).pages)
assert "再样例" not in text, "范围外章节条目仍出现在 PDF 中：%s" % text
report = json.loads(
    (Path(sys.argv[2]) / "export_report.json").read_text(encoding="utf-8"))
titles = [e["title"] for e in report["toc"]["entries"]]
assert titles == ["样例"], titles
print("分篇印刷目录仅含已纳入章，范围外导航行已移除且核验通过")
PY

echo "==> V0.2-03：多页印刷目录两遍打印收敛（目录占 2 页）"
mkdir -p "$TMP/toc_big"
{
  echo "# 大目录书 —— 全书目录"
  echo
  echo "各章译文："
  echo
  echo "| 章 | 标题 | 译文文件 |"
  echo "|---|---|---|"
  for c in 1 2 3; do
    echo "| $c | 第 $c 章 | [0${c}_章.md](0${c}_章.md) |"
  done
  echo
  echo "官方完整目录（供对照）："
  echo
  for c in 1 2 3; do
    echo "- $c. 第 ${c} 章"
    for s in $(seq 1 20); do
      echo "  - ${c}.${s}. 小节${s}"
    done
  done
} > "$TMP/toc_big/00_目录.md"
for c in 1 2 3; do
  {
    echo "# 第 ${c} 章"
    echo
    echo "第 ${c} 章正文。"
    for s in $(seq 1 20); do
      echo
      echo "## ${c}.${s}. 小节${s}"
      echo
      echo "小节 ${c}.${s} 正文。"
    done
  } > "$TMP/toc_big/0${c}_章.md"
done
BIG_IN=("$TMP/toc_big/00_目录.md" "$TMP/toc_big/01_章.md" "$TMP/toc_big/02_章.md" "$TMP/toc_big/03_章.md")
python3 "$EXPORT" --output "$TMP/toc_big/book.pdf" --work-dir "$TMP/toc_big_work" \
  --toc-sections "${BIG_IN[@]}" >"$TMP/toc_big_out.txt" 2>&1 \
  || { cat "$TMP/toc_big_out.txt"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/toc_big/book.pdf" --work-dir "$TMP/toc_big_work" \
  --toc-sections "${BIG_IN[@]}"
python3 - "$TMP/toc_big_work" "$TMP/toc_big/book.pdf" <<'PY'
import json
import sys
from pathlib import Path

from pypdf import PdfReader

toc = json.loads(
    (Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))["toc"]
levels = [e["level"] for e in toc["entries"]]
assert levels.count(1) == 3 and levels.count(2) == 60, levels
assert toc["prints"] == 2, "多页目录未在两次打印内收敛：%d" % toc["prints"]
reader = PdfReader(sys.argv[2])
p1 = reader.pages[0].extract_text() or ""
p2 = reader.pages[1].extract_text() or ""
assert "小节" in p2, "目录未延伸到第 2 页"
first = toc["entries"][0]["page"]
assert first >= 3, "目录占 2 页时首章应从第 3 页起：%d" % first
assert "第 1 章" in reader.pages[first - 1].extract_text(), "首章页码与实际不符"
print("63 条目录跨 2 页两遍收敛，页码含目录偏移（首章第 %d 页）" % first)
PY

echo "==> V0.2-03：混合层级列表只消费导航条目；节链接并入一级节"
mkdir -p "$TMP/mix"
cat > "$TMP/mix/01_章.md" <<'MD'
# 第 1 章 基础

第 1 章正文。

## 1.1. 简介（简介）

简介内容。

## 1.2. 安装（安装）

安装内容。
MD
cat > "$TMP/mix/02_章.md" <<'MD'
# 第 2 章 进阶

第 2 章正文。

## 2.1. 高级用法（高级用法）

高级内容。
MD
python3 - "$TMP/mix" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "../skills/tech-doc-translator/scripts")
import export_pdf as ex  # noqa: E402

book = Path(sys.argv[1])

def fragments(md_name):
    chapter = ex.Chapter(1, book / md_name)
    ex.parse_chapter(chapter)
    return {h["text"]: h["id"][len(chapter.prefix):] for h in chapter.headings}

f1 = fragments("01_章.md")
f2 = fragments("02_章.md")
lines = [
    "# 混合目录书 —— 全书目录",
    "",
    "各章译文：",
    "",
    "| 章 | 标题 | 译文文件 |",
    "|---|---|---|",
    "| 1 | 基础 | [01_章.md](01_章.md) |",
    "| 2 | 进阶 | [02_章.md](02_章.md) |",
    "",
    "- [1.1. 简介](01_章.md#%s)" % f1["1.1. 简介（简介）"],
    "- [2.1. 高级用法](02_章.md#%s)" % f2["2.1. 高级用法（高级用法）"],
    "",
    "官方完整目录（供对照）：",
    "",
    "- 1. 基础",
    "  - 1.1. 简介",
    "  - 此章示例需要 Python 3.11",
    "  - 1.2. 安装",
    "- 2. 进阶",
    "  - 2.1. 高级用法",
    "",
    "维护提示：",
    "",
    "- 1. 先运行脚本",
    "- 2. 再检查输出",
    "- 3. 最后归档",
    "- 4. 版本号加一",
]
(book / "00_目录.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
MIX_IN=("$TMP/mix/00_目录.md" "$TMP/mix/01_章.md" "$TMP/mix/02_章.md")
python3 "$EXPORT" --output "$TMP/mix/plain.pdf" --work-dir "$TMP/mix_work" \
  "${MIX_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/mix/plain.pdf" --work-dir "$TMP/mix_work" "${MIX_IN[@]}"
python3 "$EXPORT" --output "$TMP/mix/sec.pdf" --work-dir "$TMP/mix_work_sec" \
  --toc-sections "${MIX_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/mix/sec.pdf" --work-dir "$TMP/mix_work_sec" \
  --toc-sections "${MIX_IN[@]}"
python3 - "$TMP/mix_work" "$TMP/mix_work_sec" "$TMP/mix/plain.pdf" <<'PY'
import json
import sys
from pathlib import Path

from pypdf import PdfReader

plain = json.loads(
    (Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))["toc"]
sec = json.loads(
    (Path(sys.argv[2]) / "export_report.json").read_text(encoding="utf-8"))["toc"]
assert [(e["level"], e["title"]) for e in plain["entries"]] == [
    (1, "第 1 章 基础"), (1, "第 2 章 进阶")], plain["entries"]
assert [e["level"] for e in sec["entries"]] == [1, 2, 2, 1, 2], sec["entries"]
titles = [e["title"] for e in sec["entries"]]
assert "2.1. 高级用法（高级用法）" in titles, "节链接未并入一级节"
text = PdfReader(sys.argv[3]).pages[0].extract_text() or ""
assert "此章示例需要 Python 3.11" in text, "混合列表说明条目被误删：%s" % text
assert "官方完整目录（供对照）：" in text, "列表未清空时引导句应保留"
for note in ("先运行脚本", "再检查输出", "最后归档", "版本号加一"):
    assert note in text, "少数导航样式说明列表被误删：%s" % note
assert "1.2. 安装" not in text, "层级导航条目未消费"
print("混合列表只消费导航条目；节链接并入一级节；说明条目/引导句/少数列表保留")
PY

echo "==> V0.2-03：印刷目录（章级默认、一级节可选、重复章名、无目录不强制）"
mkdir -p "$TMP/toc"
cat > "$TMP/toc/00_目录.md" <<'MD'
# 测试书中文翻译 —— 全书目录

**全书 3 章已全部翻译完成**（合成样例，v1.0），各章译文：

| 章 | 标题 | 译文文件 |
|---|---|---|
| 1 | Introduction | [01_引言.md](01_引言.md) |
| 2 | Same Name | [02_同名.md](02_同名.md) |
| 3 | Same Name | [03_同名二.md](03_同名二.md) |

- [1.1. Basics（基础）](01_引言.md#11-basics基础)
- [2.1. Advanced（进阶）](02_同名.md#21-advanced进阶)
- [3.1. More（更多）](03_同名二.md#31-more更多)

注意：本目录由翻译流程生成，维护规则：

- 目录文件不手工编辑
- 章节完成后按交付清单重建

官方完整目录（供对照）：

- 1. Introduction
  - 1.1. Basics
- 2. Same Name
  - 2.1. Advanced
- 3. Same Name
  - 3.1. More
MD
for name in 01_引言 02_同名 03_同名二; do
  cat > "$TMP/toc/$name.md" <<MD
# $name 章标题

第 ${name} 章正文。

## 节标题

小节正文足够长以验证章节锚点跳转正确性。
MD
done
sed -i '' '1s/.*/# 1. Introduction（导论）/; s/第 01_引言 章正文。/第一章正文。/' "$TMP/toc/01_引言.md"
sed -i '' '1s/.*/# 2. Same Name（同名章 A）/; s/第 02_同名 章正文。/第二章正文，与第三章同名。/; s/## 节标题/## 2.1. Advanced（进阶）/' "$TMP/toc/02_同名.md"
sed -i '' '1s/.*/# 第 3 章 Same Name（同名章 B）/; s/第 03_同名二 章正文。/第三章正文。/; s/## 节标题/## 3.1. More（更多）/' "$TMP/toc/03_同名二.md"
sed -i '' 's/## 节标题/## 1.1. Basics（基础）/' "$TMP/toc/01_引言.md"

TOC_IN=("$TMP/toc/00_目录.md" "$TMP/toc/01_引言.md" "$TMP/toc/02_同名.md" "$TMP/toc/03_同名二.md")
python3 "$EXPORT" --output "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" "${TOC_IN[@]}" \
  >"$TMP/toc_out.txt" 2>&1 || { cat "$TMP/toc_out.txt"; exit 1; }
grep -q "印刷目录：3 条（含一级节：否），共打印 2 次" "$TMP/toc_out.txt" \
  || { cat "$TMP/toc_out.txt"; echo "错误：章级目录统计不符"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" "${TOC_IN[@]}"

python3 - "$TMP/toc/book.pdf" <<'PY'
import sys

from pypdf import PdfReader

text = PdfReader(sys.argv[1]).pages[0].extract_text() or ""
assert "译文文件" not in text, "目录页残留被消费表格的表头壳：%s" % text
assert "供对照" not in text and "各章译文" not in text, "目录页残留悬空引导句：%s" % text
assert "全书目录" in text and "1. Introduction（导论）" in text, text
for keep in ("目录文件不手工编辑", "章节完成后按交付清单重建"):
    assert keep in text, "目录说明列表被误删：%s" % keep
print("目录页无脚手架残留（表头壳/引导句已清理），说明列表保留")
PY

python3 "$EXPORT" --output "$TMP/toc/book_sec.pdf" --work-dir "$TMP/toc_work_sec" \
  --toc-sections "${TOC_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/toc/book_sec.pdf" --work-dir "$TMP/toc_work_sec" \
  --toc-sections "${TOC_IN[@]}"

python3 - "$TMP/toc_work" "$TMP/toc_work_sec" <<'PY'
import json, sys
from pathlib import Path

plain = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))["toc"]
sections = json.loads((Path(sys.argv[2]) / "export_report.json").read_text(encoding="utf-8"))["toc"]
assert [(e["level"], e["title"], e["page"]) for e in plain["entries"]] == [
    (1, "1. Introduction（导论）", 2),
    (1, "2. Same Name（同名章 A）", 3),
    (1, "第 3 章 Same Name（同名章 B）", 4),
], plain["entries"]
assert [e["level"] for e in sections["entries"]] == [1, 2, 1, 2, 1, 2]
# “第 N 章”式章名（非编号前缀）下的一级节也必须并入所属章之后。
sec_titles = [e["title"] for e in sections["entries"]]
assert "3.1. More（更多）" in sec_titles, sec_titles
assert sec_titles.index("3.1. More（更多）") > sec_titles.index(
    "第 3 章 Same Name（同名章 B）"
), sec_titles
assert plain["entries"][1]["page"] != plain["entries"][2]["page"], "同名章页码未消歧"
assert plain["prints"] == 2 and sections["prints"] == 2
# 页码包含目录页自身偏移：第 1 章在第 2 页（目录占第 1 页）。
assert plain["entries"][0]["page"] == 2
print("章级/一级节目录页码、目录偏移与重复章名消歧均正确")
PY

echo "==> V0.2-03：无目录输入保持无印刷目录"
python3 "$EXPORT" --output "$TMP/toc/no_toc.pdf" --work-dir "$TMP/no_toc_work" \
  "$TMP/toc/01_引言.md" "$TMP/toc/02_同名.md" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/toc/no_toc.pdf" --work-dir "$TMP/no_toc_work" \
  "$TMP/toc/01_引言.md" "$TMP/toc/02_同名.md"
python3 - "$TMP/no_toc_work" <<'PY'
import json, sys
from pathlib import Path
report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
assert report["toc"] == {"enabled": False, "file": None, "sections": False,
                         "prints": 1, "entries": [], "out_links": []}, report["toc"]
print("无目录输入：单次打印且无印刷目录")
PY

echo "==> V0.2-03：目录页码/目的地被篡改必须 FAIL 且不覆盖已有成品"
printf 'PREEXISTING' > "$TMP/toc/keep.pdf"
python3 - "$TMP/toc_work" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["toc"]["entries"][0]["page"] = 99  # 伪造页码
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY
if python3 "$VERIFY" --pdf "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" "${TOC_IN[@]}" 2>"$TMP/err_toc_tamper.txt"; then
  echo "错误：篡改目录页码未被检出"; exit 1
fi
grep -q "toc-page-number\|toc-target-page\|toc-link-target" "$TMP/err_toc_tamper.txt" \
  || { echo "错误：目录篡改诊断缺失"; cat "$TMP/err_toc_tamper.txt"; exit 1; }
[ "$(cat "$TMP/toc/keep.pdf")" = "PREEXISTING" ] || { echo "错误：已有成品被覆盖"; exit 1; }
# 还原证据
python3 - "$TMP/toc_work" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["toc"]["entries"][0]["page"] = 2
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY
python3 "$VERIFY" --pdf "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" "${TOC_IN[@]}" >/dev/null

echo "==> Ticket 01 PDF 导出回归全部通过"
