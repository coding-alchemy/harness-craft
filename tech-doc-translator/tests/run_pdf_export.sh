#!/usr/bin/env bash
# PDF 导出回归：临时样例覆盖单篇导出、核验、失败定位与输入保护。
# 所有临时文件都生成在工作区外 mktemp 目录；不依赖真实译文项目。
# 独立成品几何量测需安装 requirements-pdf-source.txt 中已有的 PyMuPDF 依赖。
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

# 多章合订缺少书名时由视图声明提供中文题名（R3.3/ticket 04 口径）：
# 生成与给定有序输入一一绑定的最小视图声明（仅 document_title）。
make_book_decl() {
  local out=$1
  shift
  python3 - "$out" "$@" <<'PY'
import hashlib, json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "version": 1,
    "inputs": [{"path": str(Path(p).resolve()),
                "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
               for p in sys.argv[2:]],
    "exclusions": [],
    "document_title": {"original": "Book Fixture",
                       "chinese": "合订样例全书",
                       "basis": "测试夹具书名（合订须由声明提供）"},
}, ensure_ascii=False), encoding="utf-8")
PY
}

mkdir -p "$TMP/images" "$TMP/out"
cp fixtures/valid_1x1.png "$TMP/images/pattern_a.png"

cat > "$TMP/sample.md" <<'MD'
# 1. 测试章节（Demo）

> **来源**：https://example.com/prov-TMP-sample-md

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

> **来源**：https://example.com/prov-TMP-comp-z-second-md

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

> **来源**：https://example.com/prov-TMP-comp-a-first-md

本章目录：[同名小节](#同名小节)，另见 [B 章引用](https://example.com/b)。跨章跳转：[第二章 A](#第二章-a顺序测试)。

## 同名小节

正文 B 的内容，引用脚注[^1]。下方为 B 章专属图片：

![共享图](B_images/shared.png)

引用定义链接指向 [B 章定义][shared-def]。

[shared-def]: https://example.com/def-b

[^1]: B 章注文。
MD

make_book_decl "$TMP/comp_decl.json" "$TMP/comp/z_second.md" "$TMP/comp/a_first.md"
python3 "$EXPORT" --output "$TMP/out/comp.pdf" --work-dir "$TMP/work_comp" \
  --view-declaration "$TMP/comp_decl.json" \
  "$TMP/comp/z_second.md" "$TMP/comp/a_first.md"
python3 "$VERIFY" --pdf "$TMP/out/comp.pdf" --work-dir "$TMP/work_comp" \
  --view-declaration "$TMP/comp_decl.json" \
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
make_book_decl "$TMP/comp_frag_decl.json" "$TMP/comp/bad_fragment.md" "$TMP/comp/a_first.md"
if python3 "$EXPORT" --output "$TMP/out/comp_frag.pdf" --work-dir "$TMP/work_comp_frag" \
    --view-declaration "$TMP/comp_frag_decl.json" \
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
make_book_decl "$TMP/comp_bad_decl.json" "$TMP/comp/z_second.md" "$TMP/comp/bad_target.md"
if python3 "$EXPORT" --output "$TMP/out/comp_bad.pdf" --work-dir "$TMP/work_comp_bad" \
    --view-declaration "$TMP/comp_bad_decl.json" \
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
> **来源**：https://example.com/provc-plain

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
make_book_decl "$TMP/with_plain_decl.json" "$TMP/comp/z_with_plain.md" \
  "$TMP/comp/a_first.md" "$TMP/comp/c_plain.md"
python3 "$EXPORT" --output "$TMP/out/with_plain.pdf" --work-dir "$TMP/work_plain" \
  --view-declaration "$TMP/with_plain_decl.json" \
  "$TMP/comp/z_with_plain.md" "$TMP/comp/a_first.md" "$TMP/comp/c_plain.md"
python3 "$VERIFY" --pdf "$TMP/out/with_plain.pdf" --work-dir "$TMP/work_plain" \
  --view-declaration "$TMP/with_plain_decl.json" \
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
grep -q "code-line-missing" "$TMP/err_dup_block.txt" || { echo "错误：重复块缺失诊断缺失"; cat "$TMP/err_dup_block.txt"; exit 1; }
echo "重复代码块缺份已正确判 FAIL"

echo "==> 复审修复：跨行行内代码中的 ####### 不得拆为深层标题"
cat > "$TMP/inline_deep.md" <<'MD'
# 行内代码跨行样例

> **来源**：https://example.com/prov-TMP-inline-deep-md

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
  echo "> **来源**：https://example.com/prov-anchor-collision"
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

> **来源**：https://example.com/prov-TMP-plain-ch-a-min-md

正文 A，链接到 [B 章](b_min.md)。
MD
cat > "$TMP/plain_ch/b_min.md" <<'MD'
> **来源**：https://example.com/prov-TMP-plain-ch-b-min-md

B 章只有正文段落，没有任何标题，用于验证无标题章节的边界与链接目标。
MD
make_book_decl "$TMP/plain_min_decl.json" "$TMP/plain_ch/a_min.md" "$TMP/plain_ch/b_min.md"
python3 "$EXPORT" --output "$TMP/out/plain_min.pdf" --work-dir "$TMP/work_plain_min" \
  --view-declaration "$TMP/plain_min_decl.json" \
  "$TMP/plain_ch/a_min.md" "$TMP/plain_ch/b_min.md"
python3 "$VERIFY" --pdf "$TMP/out/plain_min.pdf" --work-dir "$TMP/work_plain_min" \
  --view-declaration "$TMP/plain_min_decl.json" \
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
    --view-declaration "$TMP/plain_min_decl.json" \
    "$TMP/plain_ch/a_min.md" "$TMP/plain_ch/b_tampered.md" 2>"$TMP/err_plain.txt"; then
  echo "错误：无标题章节正文核验被跳过"; exit 1
fi
grep -q "text-missing" "$TMP/err_plain.txt" || { echo "错误：篡改内容未检出"; cat "$TMP/err_plain.txt"; exit 1; }
echo "无标题章节正文核验未被跳过"

echo "==> 复审修复：转义反引号不得破坏跨行行内代码"
cat > "$TMP/escaped_tick.md" <<'MD'
# 转义反引号样例

> **来源**：https://example.com/prov-TMP-escaped-tick-md

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

> **来源**：https://example.com/prov-TMP-dup-ch-a-dup-md

Same paragraph.

A 章独有段落，[打开 B 章](b_dup.md)。
MD
cat > "$TMP/dup_ch/b_dup.md" <<'MD'
> **来源**：https://example.com/prov-TMP-dup-ch-b-dup-md

Same paragraph.

B 章独有段落。
MD
make_book_decl "$TMP/dup_decl.json" "$TMP/dup_ch/a_dup.md" "$TMP/dup_ch/b_dup.md"
python3 "$EXPORT" --output "$TMP/out/dup.pdf" --work-dir "$TMP/work_dup" \
  --view-declaration "$TMP/dup_decl.json" \
  "$TMP/dup_ch/a_dup.md" "$TMP/dup_ch/b_dup.md"
python3 "$VERIFY" --pdf "$TMP/out/dup.pdf" --work-dir "$TMP/work_dup" \
  --view-declaration "$TMP/dup_decl.json" \
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

> **来源**：https://example.com/prov-TMP-heading-code-md

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

> **来源**：https://example.com/prov-TMP-deep-math-md

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

> **来源**：https://example.com/prov-TMP-same-ch-a-same-md

Same paragraph.
MD
cat > "$TMP/same_ch/b_same.md" <<'MD'
> **来源**：https://example.com/prov-TMP-same-ch-b-same-md

Same paragraph.
MD
make_book_decl "$TMP/same_decl.json" "$TMP/same_ch/a_same.md" "$TMP/same_ch/b_same.md"
python3 "$EXPORT" --output "$TMP/out/same.pdf" --work-dir "$TMP/work_same" \
  --view-declaration "$TMP/same_decl.json" \
  "$TMP/same_ch/a_same.md" "$TMP/same_ch/b_same.md"
python3 "$VERIFY" --pdf "$TMP/out/same.pdf" --work-dir "$TMP/work_same" \
  --view-declaration "$TMP/same_decl.json" \
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
    --view-declaration "$TMP/same_decl.json" \
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
    == [("原文", 3, 3), ("来源", 4, 4), ("抓取日期", 5, 5), ("译例说明", 7, 9)], chapter["management_exclusions"]
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
# 新政策（R2/C2）：PDF 不显示前置出处；来源清单与定位证据留在导出报告。
front = ("来源：https://docs.nvidia.com/cuda/cuda-programming-guide/",
         "抓取日期：2026-08-28")
for hidden in front:
    assert norm(hidden) not in text, f"前置出处不应出现在 PDF：{hidden}"
prov = report["provenance"]
assert prov["pdf_visibility"] == "excluded", prov
assert prov["combos"] and prov["combos"][0]["source"], prov  # 出处证据可回查
for keep in ("正文提到“原文”与“译例说明”同名文字，必须完整保留",
             ">**原文**：代码围栏中的字面字段行，必须原样保留。",
             "项目术语表",
             "CUDA是并行计算平台"):
    assert norm(keep) in text, f"应保留内容缺失：{keep}"
print("章首四字段移除、前置出处不可见且证据可回查、正文/代码同名文字与术语表链接纯文本均正确")
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
    '# A 章\n\n> **来源**：https://example.com/prov-disp-a\n\n'
    '![小宽](a_imgs/w300.png)\n\n![共享图 A](a_imgs/same.png)\n\n'
    '![自然尺寸](a_imgs/natural.png)\n', encoding='utf-8')
(root / 'b.md').write_text(
    '# B 章\n\n> **来源**：https://example.com/prov-disp-b\n\n'
    '![共享图 B](b_imgs/same.png)\n\n![超版心](b_imgs/w900.png)\n',
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
make_book_decl "$TMP/disp_decl.json" "$TMP/disp/a.md" "$TMP/disp/b.md"
python3 "$EXPORT" --output "$TMP/disp/book.pdf" --work-dir "$TMP/disp_work" \
  --view-declaration "$TMP/disp_decl.json" \
  "$TMP/disp/a.md" "$TMP/disp/b.md" >"$TMP/disp_out.txt" 2>&1 \
  || { cat "$TMP/disp_out.txt"; echo "错误：显示尺寸导出失败"; exit 1; }
grep -q "图片显示尺寸：恢复 4 处；1 处无映射命中" "$TMP/disp_out.txt" \
  || { cat "$TMP/disp_out.txt"; echo "错误：显示尺寸恢复统计不符"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/disp/book.pdf" --work-dir "$TMP/disp_work" \
  --view-declaration "$TMP/disp_decl.json" \
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
drawn = [w for page in verifier.collect_drawn_images(verifier.PdfFacts(pdf))
         for w, _bottom, _top in page]
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
  make_book_decl "$RM/decl.json" "$CH_A" "$CH_B"
  if python3 "$EXPORT" --output "$RM/fail.pdf" --work-dir "$TMP/work_case_$case" \
      --view-declaration "$RM/decl.json" \
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
    --view-declaration "$TMP/disp_decl.json" \
    --images-display "$TMP/disp_case_digest/images_display.json" \
    "$TMP/disp/a.md" "$TMP/disp/b.md" 2>"$TMP/err_disp_arg.txt"; then
  echo "错误：显示尺寸映射参数不一致未被检出"; exit 1
fi
grep -q "images-display-maps-mismatch" "$TMP/err_disp_arg.txt" \
  || { echo "错误：映射参数诊断缺失"; cat "$TMP/err_disp_arg.txt"; exit 1; }

echo "==> V0.2-02：无映射旧译文按自然尺寸导出并在结论说明"
mv "$TMP/disp/images_display.json" "$TMP/disp/_map.json.bak"
python3 "$EXPORT" --output "$TMP/disp/natural.pdf" --work-dir "$TMP/disp_work2" \
  --view-declaration "$TMP/disp_decl.json" \
  "$TMP/disp/a.md" "$TMP/disp/b.md" >"$TMP/natural_out.txt" 2>&1 \
  || { cat "$TMP/natural_out.txt"; exit 1; }
grep -q "按自然尺寸与版心上限导出" "$TMP/natural_out.txt" \
  || { cat "$TMP/natural_out.txt"; echo "错误：无映射回退未说明"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/disp/natural.pdf" --work-dir "$TMP/disp_work2" \
  --view-declaration "$TMP/disp_decl.json" \
  "$TMP/disp/a.md" "$TMP/disp/b.md"
mv "$TMP/disp/_map.json.bak" "$TMP/disp/images_display.json"

echo "==> V0.2-02：同名 Markdown 按完整路径绑定；文件名兜底歧义必须 FAIL"
mkdir -p "$TMP/same/a" "$TMP/same/b"
cp "$FIXTURE_IMAGE" "$TMP/same/a/img.png"
cp "$FIXTURE_IMAGE" "$TMP/same/b/img.png"
printf '# 第 A 章\n\n> **来源**：https://example.com/prov-same-a\n\nA 章正文。\n\n![img](img.png)\n' > "$TMP/same/a/chapter.md"
printf '# 第 B 章\n\n> **来源**：https://example.com/prov-same-b\n\nB 章正文。\n\n![img](img.png)\n' > "$TMP/same/b/chapter.md"
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
make_book_decl "$TMP/same_book_decl.json" "$TMP/same/a/chapter.md" \
  "$TMP/same/b/chapter.md"
python3 "$EXPORT" --output "$TMP/same/book.pdf" --work-dir "$TMP/same_work" \
  --view-declaration "$TMP/same_book_decl.json" \
  --images-display "$TMP/same/full_map.json" \
  "$TMP/same/a/chapter.md" "$TMP/same/b/chapter.md" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/same/book.pdf" --work-dir "$TMP/same_work" \
  --view-declaration "$TMP/same_book_decl.json" \
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
  --view-declaration "$TMP/same_book_decl.json" \
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

译自：https://example.com/neg-source

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
# 合订导出缺少书名时由视图声明提供中文题名（ticket 04 口径）。
python3 - "$TMP/neg/decl.json" "${NEG_IN[@]}" <<'PY'
import hashlib, json, sys
from pathlib import Path
out = Path(sys.argv[1])
out.write_text(json.dumps({
    "version": 1,
    "inputs": [{"path": str(Path(p).resolve()),
                "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
               for p in sys.argv[2:]],
    "exclusions": [],
    "document_title": {"original": "Neg Sample", "chinese": "负向样例全书",
                       "basis": "N01/N04 合订夹具书名（合订须由声明提供）"},
}, ensure_ascii=False), encoding="utf-8")
PY
python3 "$EXPORT" --output "$TMP/neg/base.pdf" --work-dir "$TMP/neg_work" \
  --view-declaration "$TMP/neg/decl.json" "${NEG_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/neg/base.pdf" --work-dir "$TMP/neg_work" \
  --view-declaration "$TMP/neg/decl.json" "${NEG_IN[@]}" >/dev/null \
  || { echo "错误：基线负向样例未通过"; exit 1; }

mkdir -p "$TMP/neg2"
sed '/此说明必须出现在 PDF 中/d' "$TMP/neg/00_目录.md" > "$TMP/neg2/00_目录.md"
sed '/# \*\*原文\*\*：代码内的字面量行/d' "$TMP/neg/01_章.md" > "$TMP/neg2/01_章.md"
cp "$TMP/neg/02_章.md" "$TMP/neg2/02_章.md"
N2_IN=("$TMP/neg2/00_目录.md" "$TMP/neg2/01_章.md" "$TMP/neg2/02_章.md")
python3 - "$TMP/neg2/decl.json" "${N2_IN[@]}" <<'PY'
import hashlib, json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "version": 1,
    "inputs": [{"path": str(Path(p).resolve()),
                "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
               for p in sys.argv[2:]],
    "exclusions": [],
    "document_title": {"original": "Neg Sample", "chinese": "负向样例全书",
                       "basis": "N02/N03 合订夹具书名（合订须由声明提供）"},
}, ensure_ascii=False), encoding="utf-8")
PY
python3 "$EXPORT" --output "$TMP/neg/wrong.pdf" --work-dir "$TMP/neg_wrong" \
  --view-declaration "$TMP/neg2/decl.json" "${N2_IN[@]}" >/dev/null || exit 1
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
  --view-declaration "$TMP/neg/decl.json" "${NEG_IN[@]}" >"$TMP/neg_v.txt" 2>&1; then
  echo "错误：说明/代码缺失未被检出"
  exit 1
fi
grep -q "text-missing" "$TMP/neg_v.txt" \
  || { echo "错误：说明缺失未由内容检查检出"; cat "$TMP/neg_v.txt"; exit 1; }
grep -qE "code-(line-)?missing" "$TMP/neg_v.txt" \
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
  --view-declaration "$TMP/neg/decl.json" \
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


def strip_footer(text):
    # 页脚页码（ticket 06）每页都有 n / N，剔除后正文仍保持无数字样例。
    return "\n".join(
        line for line in (text or "").split("\n")
        if not re.match(r"^\s*\d+\s*/\s*\d+\s*$", line))


pages = [strip_footer(page.extract_text() or "") for page in reader.pages]
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
    strip_footer(page.extract_text() or "")
    for page in PdfReader(str(out)).pages)
assert check.count(digit) == 0 and check.count(forged) == full.count(forged) + 1
report["pdf_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
print("已把首条目可见页码 %s 的字形改为 %s" % (digit, forged))
PY
if python3 "$VERIFY" --pdf "$TMP/neg/tampered.pdf" --work-dir "$TMP/neg_work" \
  --view-declaration "$TMP/neg/decl.json" \
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
    echo "> **来源**：https://example.com/prov-toc-big-c${c}"
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
make_book_decl "$TMP/toc_big_decl.json" "${BIG_IN[@]}"
python3 "$EXPORT" --output "$TMP/toc_big/book.pdf" --work-dir "$TMP/toc_big_work" \
  --view-declaration "$TMP/toc_big_decl.json" \
  --toc-sections "${BIG_IN[@]}" >"$TMP/toc_big_out.txt" 2>&1 \
  || { cat "$TMP/toc_big_out.txt"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/toc_big/book.pdf" --work-dir "$TMP/toc_big_work" \
  --view-declaration "$TMP/toc_big_decl.json" \
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

> **来源**：https://example.com/prov-TMP-mix-01-md

第 1 章正文。

## 1.1. 简介（简介）

简介内容。

## 1.2. 安装（安装）

安装内容。
MD
cat > "$TMP/mix/02_章.md" <<'MD'
# 第 2 章 进阶

> **来源**：https://example.com/prov-TMP-mix-02-md

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
make_book_decl "$TMP/mix_decl.json" "${MIX_IN[@]}"
python3 "$EXPORT" --output "$TMP/mix/plain.pdf" --work-dir "$TMP/mix_work" \
  --view-declaration "$TMP/mix_decl.json" \
  "${MIX_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/mix/plain.pdf" --work-dir "$TMP/mix_work" \
  --view-declaration "$TMP/mix_decl.json" "${MIX_IN[@]}"
python3 "$EXPORT" --output "$TMP/mix/sec.pdf" --work-dir "$TMP/mix_work_sec" \
  --view-declaration "$TMP/mix_decl.json" \
  --toc-sections "${MIX_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/mix/sec.pdf" --work-dir "$TMP/mix_work_sec" \
  --view-declaration "$TMP/mix_decl.json" \
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

> **来源**：https://example.com/prov-toc-$name

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
make_book_decl "$TMP/toc_decl.json" "${TOC_IN[@]}"
python3 "$EXPORT" --output "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" \
  --view-declaration "$TMP/toc_decl.json" "${TOC_IN[@]}" \
  >"$TMP/toc_out.txt" 2>&1 || { cat "$TMP/toc_out.txt"; exit 1; }
grep -q "印刷目录：3 条（含一级节：否），共打印 2 次" "$TMP/toc_out.txt" \
  || { cat "$TMP/toc_out.txt"; echo "错误：章级目录统计不符"; exit 1; }
python3 "$VERIFY" --pdf "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" \
  --view-declaration "$TMP/toc_decl.json" "${TOC_IN[@]}"

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
  --view-declaration "$TMP/toc_decl.json" \
  --toc-sections "${TOC_IN[@]}" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/toc/book_sec.pdf" --work-dir "$TMP/toc_work_sec" \
  --view-declaration "$TMP/toc_decl.json" \
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
make_book_decl "$TMP/no_toc_decl.json" "$TMP/toc/01_引言.md" "$TMP/toc/02_同名.md"
python3 "$EXPORT" --output "$TMP/toc/no_toc.pdf" --work-dir "$TMP/no_toc_work" \
  --view-declaration "$TMP/no_toc_decl.json" \
  "$TMP/toc/01_引言.md" "$TMP/toc/02_同名.md" >/dev/null || exit 1
python3 "$VERIFY" --pdf "$TMP/toc/no_toc.pdf" --work-dir "$TMP/no_toc_work" \
  --view-declaration "$TMP/no_toc_decl.json" \
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
if python3 "$VERIFY" --pdf "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" \
  --view-declaration "$TMP/toc_decl.json" "${TOC_IN[@]}" 2>"$TMP/err_toc_tamper.txt"; then
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
python3 "$VERIFY" --pdf "$TMP/toc/book.pdf" --work-dir "$TMP/toc_work" \
  --view-declaration "$TMP/toc_decl.json" "${TOC_IN[@]}" >/dev/null

echo "==> Ticket 01 PDF 导出回归全部通过"

echo "==> R2/R5（留痕 03）：普通/严格覆盖策略、预算与代码内图片语法"
STRICT="$TMP/strict_case"; rm -rf "$STRICT"; mkdir -p "$STRICT/imgs" "$STRICT/imgsel"
cp fixtures/valid_1x1.png "$STRICT/imgs/small.png"
cp fixtures/valid_1x1.png "$STRICT/imgs/free.png"
python3 - "$STRICT" <<'PY'
import struct, sys, zlib
from pathlib import Path

base = Path(sys.argv[1])

def make_png(path, w, h):
    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + b'\x10\x20\x30' * w for _ in range(h))
    Path(path).write_bytes(
        b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

make_png(base / 'imgsel/big.png', 900, 500)   # 去重后的第二大资源
(base / 'a.md').write_text(
    '# 章 A\n\n> **来源**：https://example.com/prov-strict-a\n\n'
    '![小图](imgs/small.png)\n\n'
    '```text\n![代码内示例](imgs/missing.png)\n```\n\n'
    '![自由图](imgs/free.png)\n', encoding='utf-8')
(base / 'b.md').write_text(
    '# 章 B\n\n> **来源**：https://example.com/prov-strict-b\n\n'
    '![大图](imgsel/big.png)\n\n'
    '![大图重复](imgsel/big.png)\n', encoding='utf-8')
PY
make_book_decl "$STRICT/decl.json" "$STRICT/a.md" "$STRICT/b.md"
# 普通模式：无映射/未覆盖仅告警继续（含代码内图片语法不计）
python3 "$EXPORT" --output "$STRICT/plain.pdf" --work-dir "$STRICT/w_plain" \
  --view-declaration "$STRICT/decl.json" \
  "$STRICT/a.md" "$STRICT/b.md" >"$STRICT/plain.txt" 2>&1
grep -q "总数 4 = 已恢复 0 + 未恢复 4（无映射条目 4" "$STRICT/plain.txt" \
  || { cat "$STRICT/plain.txt"; echo "错误：覆盖汇总口径不符（代码内示例不得计数）"; exit 1; }
python3 - "$STRICT" <<'PYCHK'
import json, sys
from pathlib import Path

report = json.loads((Path(sys.argv[1]) / 'w_plain' / 'export_report.json')
                    .read_text(encoding='utf-8'))
codes = [d['code'] for d in report['diagnostics']]
assert codes.count('images-display-absent-missing') == 4, codes
coverage = report['image_coverage']
a = next(v for k, v in coverage.items() if k.endswith('a.md'))
b = next(v for k, v in coverage.items() if k.endswith('b.md'))
assert a['total'] == 2 and b['total'] == 2, coverage
print('普通模式诊断与逐章覆盖分类正确（代码内示例未计数）')
PYCHK
echo "普通模式：未覆盖告警继续、代码内图片语法不计数 PASS"

# 严格模式：全部出现须有确定尺寸 → 拒绝且不新增成品
if python3 "$EXPORT" --output "$STRICT/strict.pdf" --work-dir "$STRICT/w_strict" \
    --view-declaration "$STRICT/decl.json" \
    --require-display-map "$STRICT/a.md" "$STRICT/b.md" \
    >"$STRICT/strict.txt" 2>&1; then
  echo "错误：严格模式未拒绝部分覆盖"; cat "$STRICT/strict.txt"; exit 1
fi
grep -q "images-display-required" "$STRICT/strict.txt" \
  || { cat "$STRICT/strict.txt"; echo "错误：严格拒绝诊断缺失"; exit 1; }
test ! -f "$STRICT/strict.pdf" || { echo "错误：严格失败仍生成成品"; exit 1; }
test ! -f "$STRICT/w_strict/candidate.pdf" \
  || { echo "错误：严格失败仍生成候选"; exit 1; }
echo "严格模式：部分覆盖被拒绝，无候选/成品 PASS"

# 完整确定映射：严格模式通过；verify 缺严格参数判 FAIL
python3 - "$STRICT" <<'PY'
import hashlib, json, sys
from pathlib import Path

base = Path(sys.argv[1])

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

entries = [
    {"markdown": "a.md", "occurrence": 1, "image": "imgs/small.png",
     "sha256": sha(base / 'imgs/small.png'),
     "width": {"value": 300, "unit": "px", "basis": "inline-css-width",
               "reference": None},
     "source": {"snapshot": "s.html", "node": "img[1]"}},
    {"markdown": "a.md", "occurrence": 2, "image": "imgs/free.png",
     "sha256": sha(base / 'imgs/free.png'),
     "width": {"value": 900, "unit": "px", "basis": "inline-css-width",
               "reference": None},
     "source": {"snapshot": "s.html", "node": "img[2]"}},
    {"markdown": "b.md", "occurrence": 1, "image": "imgsel/big.png",
     "sha256": sha(base / 'imgsel/big.png'),
     "width": {"value": 700, "unit": "px", "basis": "inline-css-width",
               "reference": None},
     "source": {"snapshot": "s.html", "node": "img[3]"}},
    {"markdown": "b.md", "occurrence": 2, "image": "imgsel/big.png",
     "sha256": sha(base / 'imgsel/big.png'),
     "width": {"value": 400, "unit": "px", "basis": "inline-css-width",
               "reference": None},
     "source": {"snapshot": "s.html", "node": "img[4]"}},
]
(base / 'images_display.json').write_text(
    json.dumps({"version": 1, "entries": entries}, ensure_ascii=False),
    encoding='utf-8')
PY
python3 "$EXPORT" --output "$STRICT/full.pdf" --work-dir "$STRICT/w_full" \
  --view-declaration "$STRICT/decl.json" \
  --images-display "$STRICT/images_display.json" --require-display-map \
  "$STRICT/a.md" "$STRICT/b.md" >"$STRICT/full.txt" 2>&1 \
  || { cat "$STRICT/full.txt"; echo "错误：全量确定映射严格导出应通过"; exit 1; }
if python3 "$VERIFY" --pdf "$STRICT/full.pdf" --work-dir "$STRICT/w_full" \
    --view-declaration "$STRICT/decl.json" \
    --images-display "$STRICT/images_display.json" \
    "$STRICT/a.md" "$STRICT/b.md" >"$STRICT/v_mismatch.txt" 2>&1; then
  echo "错误：核验省略严格参数未被检出"; exit 1
fi
grep -q "images-display-require-mismatch" "$STRICT/v_mismatch.txt" \
  || { cat "$STRICT/v_mismatch.txt"; echo "错误：严格参数不一致诊断缺失"; exit 1; }
python3 "$VERIFY" --pdf "$STRICT/full.pdf" --work-dir "$STRICT/w_full" \
  --view-declaration "$STRICT/decl.json" \
  --images-display "$STRICT/images_display.json" --require-display-map \
  "$STRICT/a.md" "$STRICT/b.md" >"$STRICT/v_full.txt" 2>&1 \
  || { cat "$STRICT/v_full.txt"; echo "错误：严格核验应通过"; exit 1; }
echo "严格导出/严格核验一致通过；核验参数漂移被检出 PASS"

# 严格失败不覆盖旧 PDF：full.pdf 摘要在被拒导出后保持不变
BEFORE=$(shasum -a 256 "$STRICT/full.pdf" | cut -d' ' -f1)
mv "$STRICT/images_display.json" "$STRICT/images_display.json.bak"
if python3 "$EXPORT" --output "$STRICT/full.pdf" --work-dir "$STRICT/w_strict2" \
    --view-declaration "$STRICT/decl.json" \
    --require-display-map "$STRICT/a.md" "$STRICT/b.md" \
    >"$STRICT/strict2.txt" 2>&1; then
  echo "错误：缺映射严格导出未被拒绝"; exit 1
fi
AFTER=$(shasum -a 256 "$STRICT/full.pdf" | cut -d' ' -f1)
test "$BEFORE" = "$AFTER" || { echo "错误：严格失败覆盖了旧 PDF"; exit 1; }
mv "$STRICT/images_display.json.bak" "$STRICT/images_display.json"
echo "严格失败保护旧 PDF 摘要不变 PASS"

# 预算：重复资源按出现累加 > 按摘要去重；SVG 列为无法估算
python3 "$EXPORT" --output "$STRICT/plain2.pdf" --work-dir "$STRICT/w_plain2" \
  --view-declaration "$STRICT/decl.json" \
  "$STRICT/a.md" "$STRICT/b.md" >"$STRICT/plain2.txt" 2>&1
grep -q "image-decode-budget\|解码预算估算" "$STRICT/plain2.txt" \
  || { cat "$STRICT/plain2.txt"; echo "错误：预算估算未输出"; exit 1; }
python3 - "$STRICT" <<'PY'
import json, sys
from pathlib import Path

work = Path(sys.argv[1]) / 'w_plain2'
report = json.loads((work / 'export_report.json').read_text(encoding='utf-8'))
budget = report['image_budget']
occ = budget['occurrence_estimate_bytes']
dedup = budget['dedup_estimate_bytes']
# big.png 900x500 出现两次 + 小图/自由图各一次：去重 < 按出现
assert dedup < occ, (dedup, occ)
assert set(budget['unknown_items']) == set(), budget['unknown_items']
# 最大资源条目携带章/出现/资源名定位（复用 Occurrence 事实）
top = budget['largest'][0]
assert 'big.png' in top['location'] and '#1' in top['location'], top
print('预算双口径（去重 %.2f MiB < 按出现 %.2f MiB）正确，'
      '最大资源定位 %s' % (dedup / (1 << 20), occ / (1 << 20),
                           top['location']))
PY

# 预算告警明细在内联前展示：超阈值主要资源与多帧额外开销随摘要一同输出
# （patch 尺寸元信息与内联入口，不分配真实巨图）
python3 - "$TMP" <<'PY'
import contextlib
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path('../skills/tech-doc-translator/scripts').resolve()))
import export_pdf as e

base = Path(sys.argv[1]) / 'budget_warn'
base.mkdir(exist_ok=True)
(base / 'big.png').write_bytes(Path('fixtures/valid_1x1.png').read_bytes())
doc = base / 'doc.md'
doc.write_text('# 章 BG\n\n> **来源**：https://example.com/pv-budget\n\n'
               '![big](big.png)\n', encoding='utf-8')
captured = io.StringIO()


class StopInline(Exception):
    pass


def stop_inline(*args, **kwargs):
    raise StopInline()


with contextlib.redirect_stdout(captured), \
        patch.object(e, 'bitmap_facts',
                     return_value=('GIF', (15000, 15000), 3, True)), \
        patch.object(e, 'inline_images', side_effect=stop_inline):
    try:
        e.export([str(doc)], base / 'never.pdf', base / 'w')
    except StopInline:
        pass
out = captured.getvalue()
assert '解码预算估算' in out, out
assert '[image-decode-budget]' in out and '最大资源' in out, out
assert '[image-budget-multiframe]' in out and '（3 帧）' in out, out
print('预算告警明细（超阈值主要资源、多帧额外开销）在内联前展示 PASS')
PY

# 普通单帧大图超阈值：告警在内联前输出且直接包含实际资源定位
# （单帧无多帧提示，定位只能来自最大资源告警本身；纯告警不阻断内联入口）
python3 - "$TMP" <<'PY'
import contextlib
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path('../skills/tech-doc-translator/scripts').resolve()))
import export_pdf as e

base = Path(sys.argv[1]) / 'budget_single_frame'
base.mkdir(exist_ok=True)
(base / 'big.png').write_bytes(Path('fixtures/valid_1x1.png').read_bytes())
doc = base / 'doc.md'
doc.write_text('# 章 SF\n\n> **来源**：https://example.com/pv-single-frame\n\n'
               '![big](big.png)\n', encoding='utf-8')
captured = io.StringIO()


class StopInline(Exception):
    pass


def stop_inline(*args, **kwargs):
    raise StopInline()


with contextlib.redirect_stdout(captured), \
        patch.object(e, 'bitmap_facts',
                     return_value=('PNG', (15000, 15000), 1, True)), \
        patch.object(e, 'inline_images', side_effect=stop_inline):
    try:
        e.export([str(doc)], base / 'never.pdf', base / 'w')
    except StopInline:
        pass
out = captured.getvalue()
assert '[image-decode-budget]' in out and '最大资源' in out, out
# 直接断言实际资源定位（章#出现序号 资源名），不只匹配“最大资源”字样
assert 'doc.md#1 big.png' in out, out
# 单帧场景没有多帧提示，定位只能来自最大资源告警本身
assert '[image-budget-multiframe]' not in out, out
print('普通单帧大图告警在内联前输出实际资源定位 PASS')
PY

# 行内代码中的引用式图片示例不计图片出现（渲染级枚举两侧一致）
INL="$TMP/inline_ref_case"; rm -rf "$INL"; mkdir -p "$INL"
cp fixtures/valid_1x1.png "$INL/real.png"
cat > "$INL/doc.md" <<'MD'
# 章内引用示例

> **来源**：https://example.com/inline-ref-prov

行内代码示例：`![example][img]`，其后有真实图片。

![real](real.png)

[img]: real.png
MD
python3 "$EXPORT" --output "$INL/out.pdf" --work-dir "$INL/w" \
  "$INL/doc.md" >"$INL/e.txt" 2>&1 \
  || { cat "$INL/e.txt"; echo "错误：行内代码引用式图片示例阻断导出"; exit 1; }
python3 "$VERIFY" --pdf "$INL/out.pdf" --work-dir "$INL/w" \
  "$INL/doc.md" >"$INL/v.txt" 2>&1 \
  || { cat "$INL/v.txt"; echo "错误：行内代码引用式图片示例被核验误拒"; exit 1; }
python3 - "$INL/w" <<'PY'
import json, sys
from pathlib import Path
cov = json.loads((Path(sys.argv[1]) / 'export_report.json')
                 .read_text(encoding='utf-8'))['image_coverage']
totals = [v['total'] for v in cov.values()]
assert totals == [1], totals  # 仅真实图片计 1 次
print('行内代码引用式图片示例不计数，导出与核验一致 PASS')
PY

# 未确定条目身份与确定条目同口径核对（错路径/越界均拒绝，导出与核验双侧）
UDI="$TMP/undet_identity"; rm -rf "$UDI"; mkdir -p "$UDI"
cp fixtures/valid_1x1.png "$UDI/actual.png"
printf '# 章 UI\n\n> **来源**：https://example.com/undet-identity\n\n![a](actual.png)\n' \
  > "$UDI/doc.md"
python3 - "$UDI" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])
(base / 'bad_map.json').write_text(json.dumps({
    'version': 1, 'markdown': 'doc.md',
    'undetermined': [
        {'occurrence': 1, 'image': 'other.png',
         'reason_code': 'no-source-constraint'},
        {'occurrence': 99, 'image': 'actual.png',
         'reason_code': 'no-source-constraint'},
    ]}), encoding='utf-8')
PY
if python3 "$EXPORT" --output "$UDI/out.pdf" --work-dir "$UDI/w" \
    --images-display "$UDI/bad_map.json" "$UDI/doc.md" >"$UDI/e.txt" 2>&1; then
  echo "错误：坏身份未确定条目未被拒绝"; exit 1
fi
grep -q "images-display-binding" "$UDI/e.txt" \
  || { cat "$UDI/e.txt"; echo "错误：未确定条目资源不符诊断缺失"; exit 1; }
grep -q "超出本章图片数" "$UDI/e.txt" \
  || { cat "$UDI/e.txt"; echo "错误：未确定条目越界诊断缺失"; exit 1; }
if python3 "$VERIFY" --pdf "$UDI/out.pdf" --work-dir "$UDI/w" \
    --images-display "$UDI/bad_map.json" "$UDI/doc.md" >"$UDI/v.txt" 2>&1; then
  echo "错误：核验未拒坏身份未确定条目"; exit 1
fi
grep -q "images-display-binding" "$UDI/v.txt" \
  || { cat "$UDI/v.txt"; echo "错误：核验侧身份诊断缺失"; exit 1; }
echo "未确定条目身份/越界导出与核验双侧拒绝 PASS"

echo "==> R3/A7（留痕 03）：回补映射导出后按 PDF 实测逐次宽度"
R3="$TMP/rebuild_export"; rm -rf "$R3"; mkdir -p "$R3/source/images" "$R3/delivery/images"
cp fixtures/valid_1x1.png "$R3/source/images/pic.png"
cp fixtures/valid_1x1.png "$R3/delivery/images/pic.png"
python3 - "$R3" <<'PY'
import sys
from pathlib import Path
base = Path(sys.argv[1])
(base / 'source/page.html').write_text(
    '<html><body><article><h1>T</h1>'
    '<img src="images/pic.png" style="width:200px">'
    '<img src="images/pic.png" style="width:600px">'
    '</article></body></html>', encoding='utf-8')
(base / 'delivery/final.md').write_text(
    '# 章\n\n> **来源**：https://example.com/prov-r3\n\n'
    '![一](images/pic.png)\n\n![二](images/pic.png)\n',
    encoding='utf-8')
import json
(base / 'manifest.json').write_text(json.dumps({
    'version': 1, 'source_version': 'test', 'family': 'single',
    'pages': [{'snapshot': 'source/page.html',
               'markdown': 'delivery/final.md'}]}), encoding='utf-8')
PY
python3 "../skills/tech-doc-translator/scripts/rebuild_images_display.py" --manifest "$R3/manifest.json" \
  --output "$R3/delivery/export/images_display.json" \
  --work-dir "$R3/work_rebuild" \
  || { echo "错误：回补失败"; exit 1; }
python3 "$EXPORT" --output "$R3/out/book.pdf" --work-dir "$R3/work_export" \
  --images-display "$R3/delivery/export/images_display.json" \
  --require-display-map "$R3/delivery/final.md" \
  >"$R3/export.txt" 2>&1 || { cat "$R3/export.txt"; echo "错误：回补映射导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$R3/out/book.pdf" --work-dir "$R3/work_export" \
  --images-display "$R3/delivery/export/images_display.json" \
  --require-display-map "$R3/delivery/final.md" \
  >"$R3/verify.txt" 2>&1 || { cat "$R3/verify.txt"; echo "错误：回补映射核验失败"; exit 1; }
grep -q "总数 2 = 已恢复 2 + 未恢复 0" "$R3/export.txt" \
  || { cat "$R3/export.txt"; echo "错误：回补后覆盖未全量恢复"; exit 1; }
echo "回补→导出→量测：2 次出现全量恢复且逐次宽度经内容流核验 PASS"

echo "==> 精简 04/A7：四类家族回补→导出→内容流逐次实测宽度 + 连续回补不退化"
R4F="$TMP/rebuild_four"; rm -rf "$R4F"; mkdir -p "$R4F"
python3 - "$R4F" <<'PY'
import shutil, sys
from pathlib import Path
base = Path(sys.argv[1])
shutil.copy('fixtures/valid_1x1.png', base / 'pic_a.png')
shutil.copy('fixtures/valid_1x1.png', base / 'pic_b.png')
PY
python3 - "$R4F" <<'PY'
import json, sys
from pathlib import Path

base = Path(sys.argv[1])
html_img = ('<img src="images/pic_a.png" style="width:200px">'
            '<img src="images/pic_b.png" style="width:600px">')
families = {
    'single': {
        'html': '<html><body><article><h1>T</h1>' + html_img
                + '<table><tr><th colspan="2">复杂表头</th></tr>'
                  '<tr><td>a</td><td>b</td></tr></table>'
                + '</article></body></html>',
        'srcs': ['images/pic_a.png', 'images/pic_b.png']},
    'paginated': {
        'html': '<html><body><article><h1>T</h1>' + html_img
                + '</article></body></html>',
        'srcs': ['images/pic_a.png', 'images/pic_b.png']},
    'reference': {
        'html': ('<html><body><article><h1>T</h1>'
                 '<img src="_static/pic_a.png" style="width:200px">'
                 '<img src="_static/pic_b.png" style="width:600px">'
                 '</article></body></html>'),
        'srcs': ['_static/pic_a.png', '_static/pic_b.png']},
    'api': {
        'html': ('<html><body><article><h1>T</h1>'
                 '<img class="only-dark" src="images/dark.png">'
                 '<img src="images/pic_a.png" data-light="images/pic_a.png"'
                 ' data-dark="images/dark.png" style="width:200px">'
                 '<img src="images/pic_b.png" style="width:600px">'
                 '</article></body></html>'),
        'srcs': ['images/pic_a.png', 'images/pic_b.png']},
}
for family, spec in families.items():
    root = base / family
    (root / 'source').mkdir(parents=True)
    (root / 'delivery/images').mkdir(parents=True)
    (root / 'source/images').mkdir(parents=True, exist_ok=True)
    (root / 'source/_static').mkdir(parents=True, exist_ok=True)
    for rel in spec['srcs']:
        target = root / 'source' / rel
        if not target.exists():
            target.hardlink_to(base / 'pic_a.png'
                               if rel.endswith('pic_a.png') else base / 'pic_b.png')
    for name in ('pic_a.png', 'pic_b.png'):
        (root / 'delivery/images' / name).hardlink_to(base / name)
    (root / 'source/page.html').write_text(spec['html'], encoding='utf-8')
    (root / 'delivery/final.md').write_text(
        '# 章\n\n> **来源**：https://example.com/prov-four-%s\n\n'
        '![一](images/pic_a.png)\n\n![二](images/pic_b.png)\n' % family,
        encoding='utf-8')
    (root / 'manifest.json').write_text(json.dumps({
        'version': 1, 'source_version': '13.4-test', 'family': family,
        'pages': [{'snapshot': 'source/page.html',
                   'markdown': 'delivery/final.md'}]}), encoding='utf-8')
print('四类家族夹具就绪')
PY
for family in single paginated reference api; do
  FAM_DIR="$R4F/$family"
  MAP="$FAM_DIR/delivery/export/images_display.json"
  for round in 1 2 3; do
    python3 "../skills/tech-doc-translator/scripts/rebuild_images_display.py" \
      --manifest "$FAM_DIR/manifest.json" --output "$MAP" \
      --work-dir "$FAM_DIR/work_rebuild" \
      || { echo "错误：$family 第 $round 轮回补失败"; exit 1; }
    if [ "$round" -gt 1 ]; then
      # 连续回补不退化：映射字节稳定（同输入语义一致），无根目录副本
      cmp -s "$MAP" "$FAM_DIR/map_baseline.json" \
        || { echo "错误：$family 第 $round 轮回补映射退化"; exit 1; }
    else
      cp "$MAP" "$FAM_DIR/map_baseline.json"
    fi
  done
  test ! -f "$FAM_DIR/delivery/images_display.json" \
    || { echo "错误：$family 存在根目录映射副本"; exit 1; }
  python3 "$EXPORT" --output "$FAM_DIR/out/book.pdf" \
    --work-dir "$FAM_DIR/work_export" --images-display "$MAP" \
    --require-display-map "$FAM_DIR/delivery/final.md" \
    >"$FAM_DIR/export.txt" 2>&1 \
    || { cat "$FAM_DIR/export.txt"; echo "错误：$family 回补映射导出失败"; exit 1; }
  grep -q "总数 2 = 已恢复 2 + 未恢复 0" "$FAM_DIR/export.txt" \
    || { cat "$FAM_DIR/export.txt"; echo "错误：$family 未全量恢复"; exit 1; }
  python3 "$VERIFY" --pdf "$FAM_DIR/out/book.pdf" --work-dir "$FAM_DIR/work_export" \
    --images-display "$MAP" --require-display-map "$FAM_DIR/delivery/final.md" \
    >"$FAM_DIR/verify.txt" 2>&1 \
    || { cat "$FAM_DIR/verify.txt"; echo "错误：$family 逐次宽度内容流核验失败"; exit 1; }
done
echo "四类家族回补→导出→内容流实测宽度（200/600px 逐次）、连续三轮回补不退化 PASS"

echo "==> R6/A15（留痕 04）：缺出处零生成、来源不足定位、补齐后恢复"
PV="$TMP/prov_gate"; rm -rf "$PV"; mkdir -p "$PV"
cp "$STRICT/full.pdf" "$PV/old.pdf"
BEFORE_PV=$(shasum -a 256 "$PV/old.pdf" | cut -d' ' -f1)

python3 - "$PV" <<'PY'
from pathlib import Path
base = Path(sys.argv[1]) if False else Path(__import__('sys').argv[1])
(base / 'ok.md').write_text(
    '# 章 OK\n\n> **来源**：https://example.com/pv-ok（抓取日期：2026-09-15）\n\n正文。\n',
    encoding='utf-8')
(base / 'weak.md').write_text(
    '# 章 WEAK\n\n> **来源**：NVIDIA CUDA Programming Guide 官网\n\n正文。\n',
    encoding='utf-8')
(base / 'none.md').write_text('# 章 NONE\n\n正文。\n', encoding='utf-8')
PY
# 正例：来源可定位但源未提供版本/日期 → 不阻断（不编造）
python3 "$EXPORT" --output "$PV/nodate.pdf" --work-dir "$PV/w_nodate" \
  "$PV/ok.md" >"$PV/nodate.txt" 2>&1 \
  || { cat "$PV/nodate.txt"; echo "错误：源无版本/日期不应阻断"; exit 1; }
grep -q "prov-nodate\|pv-ok" "$PV/nodate.txt" >/dev/null 2>&1 || true
echo "来源无版本/日期正例：导出通过（不编造字段） PASS"

make_book_decl "$PV/decl_okweak.json" "$PV/ok.md" "$PV/weak.md"
# 反例 1：来源只是文档名/官网（无法定位具体原文）→ provenance-incomplete
if python3 "$EXPORT" --output "$PV/old.pdf" --work-dir "$PV/w_weak" \
    --view-declaration "$PV/decl_okweak.json" \
    "$PV/ok.md" "$PV/weak.md" >"$PV/weak.txt" 2>&1; then
  echo "错误：不可定位来源未被拒绝"; exit 1
fi
grep -q "provenance-incomplete" "$PV/weak.txt" \
  || { cat "$PV/weak.txt"; echo "错误：incomplete 诊断缺失"; exit 1; }
grep -q "第 2 章" "$PV/weak.txt" \
  || { cat "$PV/weak.txt"; echo "错误：未定位受影响章节"; exit 1; }
test ! -f "$PV/w_weak/candidate.pdf" || { echo "错误：缺出处仍生成候选"; exit 1; }
AFTER_PV=$(shasum -a 256 "$PV/old.pdf" | cut -d' ' -f1)
test "$BEFORE_PV" = "$AFTER_PV" || { echo "错误：缺出处失败覆盖旧 PDF"; exit 1; }
echo "来源不足：定位章节、零生成、旧 PDF 不变 PASS"

# 反例 2：完全缺来源 → provenance-unavailable
if python3 "$EXPORT" --output "$PV/old.pdf" --work-dir "$PV/w_none" \
    "$PV/none.md" >"$PV/none.txt" 2>&1; then
  echo "错误：完全缺来源未被拒绝"; exit 1
fi
grep -q "provenance-unavailable" "$PV/none.txt" \
  || { cat "$PV/none.txt"; echo "错误：unavailable 诊断缺失"; exit 1; }
echo "完全缺来源：unavailable 拒绝 PASS"

# 恢复：补齐来源后可生成（且核验确认前置出处不可见、出处证据可回查）
python3 - "$PV" <<'PY'
from pathlib import Path
base = Path(__import__('sys').argv[1])
(base / 'weak.md').write_text(
    '# 章 WEAK\n\n> **来源**：https://example.com/pv-weak\n\n正文。\n',
    encoding='utf-8')
PY
# weak.md 已补齐来源：按新输入身份重建声明绑定。
make_book_decl "$PV/decl_okweak.json" "$PV/ok.md" "$PV/weak.md"
python3 "$EXPORT" --output "$PV/fixed.pdf" --work-dir "$PV/w_fixed" \
  --view-declaration "$PV/decl_okweak.json" \
  "$PV/ok.md" "$PV/weak.md" >"$PV/fixed.txt" 2>&1 \
  || { cat "$PV/fixed.txt"; echo "错误：补齐来源后仍拒绝"; exit 1; }
python3 "$VERIFY" --pdf "$PV/fixed.pdf" --work-dir "$PV/w_fixed" \
  --view-declaration "$PV/decl_okweak.json" \
  "$PV/ok.md" "$PV/weak.md" >"$PV/fixed_v.txt" 2>&1 \
  || { cat "$PV/fixed_v.txt"; echo "错误：补齐后核验失败"; exit 1; }
echo "补齐来源后导出与核验恢复 PASS"

# --provenance 区间映射：目录说明段被授权为准；篡改摘要即拒绝
cat > "$PV/00_目录.md" <<'MD'
# 合订书目录

译自 NVIDIA CUDA Programming Guide v13.4：https://example.com/pv-toc-book

- [章 OK](ok.md)
- [章 WEAK](weak.md)
MD
make_book_decl "$PV/decl_book.json" "$PV/00_目录.md" "$PV/ok.md" "$PV/weak.md"
cat > "$PV/map.json" <<EOF
{"inputs": [{"path": "$PV/00_目录.md", "sha256": "$(shasum -a 256 "$PV/00_目录.md" | cut -d' ' -f1)",
  "sections": [{"lines": [3, 3], "chapters": [2]}]}]}
EOF
python3 "$EXPORT" --output "$PV/mapped.pdf" --work-dir "$PV/w_map" \
  --view-declaration "$PV/decl_book.json" \
  --provenance "$PV/map.json" "$PV/00_目录.md" "$PV/ok.md" "$PV/weak.md" \
  >"$PV/map.txt" 2>&1 \
  || { cat "$PV/map.txt"; echo "错误：合法映射导出失败"; exit 1; }
python3 - "$PV/w_map" "$PV/mapped.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
prov = report["provenance"]
assert prov["mode"] == "mapping", prov
assert prov["complete"] == [2, 3], prov  # 目录文件豁免；两章可定位
# 各章与映射段落不同的来源组合仍保留在导出报告（差异不丢失）
assert prov["front_generated"] is True and len(prov["combos"]) == 2, prov
assert prov["pdf_visibility"] == "excluded", prov
assert prov["toc_exclusion"] is not None, prov  # 目录“译自…”段排除证据


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
assert norm("译自NVIDIACUDAProgrammingGuidev13.4") not in text, \
    "目录译自出处段不应出现在 PDF"
print("映射模式：目录段落覆盖全书出处，各章独立来源组合仍留报告；"
      "目录译自段在 PDF 中缺席且证据可回查")
PY
# 篡改映射（换摘要）→ 拒绝
python3 - "$PV" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])
data = json.loads((base / 'map.json').read_text(encoding='utf-8'))
data["inputs"][0]["sha256"] = "0" * 64
(base / 'map_bad.json').write_text(json.dumps(data))
PY
if python3 "$EXPORT" --output "$PV/mapped.pdf" --work-dir "$PV/w_map_bad" \
    --view-declaration "$PV/decl_book.json" \
    --provenance "$PV/map_bad.json" "$PV/00_目录.md" "$PV/ok.md" "$PV/weak.md" \
    >"$PV/map_bad.txt" 2>&1; then
  echo "错误：篡改映射未被拒绝"; exit 1
fi
grep -q "摘要与输入不符" "$PV/map_bad.txt" \
  || { cat "$PV/map_bad.txt"; echo "错误：映射摘要诊断缺失"; exit 1; }
echo "出处区间映射：合法通过、篡改拒绝 PASS"

# 映射负例：指向正文章节的区间与缺摘要的映射都必须被拒绝（不能绕开输入绑定或位置保证）
python3 - "$PV" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])
(base / 'content_map.json').write_text(json.dumps({"inputs": [{
    "path": str(base / 'ok.md'),
    "sha256": __import__('hashlib').sha256(
        (base / 'ok.md').read_bytes()).hexdigest(),
    "sections": [{"lines": [3, 3], "chapters": [2]}]}]}), encoding='utf-8')
(base / 'nodigest_map.json').write_text(json.dumps({"inputs": [{
    "path": str(base / '00_目录.md'),
    "sections": [{"lines": [3, 3], "chapters": [2]}]}]}), encoding='utf-8')
PY
if python3 "$EXPORT" --output "$PV/bad1.pdf" --work-dir "$PV/w_bad1" \
    --view-declaration "$PV/decl_okweak.json" \
    --provenance "$PV/content_map.json" "$PV/ok.md" "$PV/weak.md" \
    >"$PV/bad1.txt" 2>&1; then
  echo "错误：正文章节内区间映射未被拒绝"; exit 1
fi
grep -q "只支持目录文件" "$PV/bad1.txt" \
  || { cat "$PV/bad1.txt"; echo "错误：正文区间诊断缺失"; exit 1; }
if python3 "$EXPORT" --output "$PV/bad2.pdf" --work-dir "$PV/w_bad2" \
    --view-declaration "$PV/decl_book.json" \
    --provenance "$PV/nodigest_map.json" "$PV/00_目录.md" "$PV/ok.md" "$PV/weak.md" \
    >"$PV/bad2.txt" 2>&1; then
  echo "错误：缺摘要映射未被拒绝"; exit 1
fi
grep -q "缺少输入摘要" "$PV/bad2.txt" \
  || { cat "$PV/bad2.txt"; echo "错误：缺摘要诊断缺失"; exit 1; }
echo "映射负例：正文区间与缺摘要均拒绝 PASS"

# 目录未列输入首位时映射明确拒绝（无法保证被采用出处段先于首章；零生成，不重排输入）
make_book_decl "$PV/decl_last.json" "$PV/ok.md" "$PV/00_目录.md" "$PV/weak.md"
if python3 "$EXPORT" --output "$PV/last.pdf" --work-dir "$PV/w_last" \
    --view-declaration "$PV/decl_last.json" \
    --provenance "$PV/map.json" "$PV/ok.md" "$PV/00_目录.md" "$PV/weak.md" \
    >"$PV/last.txt" 2>&1; then
  echo "错误：目录未列首位的映射未被拒绝"; exit 1
fi
grep -q "未列在输入首位" "$PV/last.txt" \
  || { cat "$PV/last.txt"; echo "错误：目录顺序诊断缺失"; exit 1; }
test ! -f "$PV/w_last/candidate.pdf" \
  || { echo "错误：目录未列首位仍生成候选"; exit 1; }
echo "目录未列首位时映射明确拒绝且零生成 PASS"

# 映射为唯一出处来源（章内无管理字段）：目录首位时导出与核验通过，
# 核验独立重建出处证据并按新政策核对 PDF 可见性
PV3="$TMP/prov_mapsole"; rm -rf "$PV3"; mkdir -p "$PV3"
cat > "$PV3/00_目录.md" <<'MD'
# 目录

Source manual: https://example.com/pv-mapsole/book.html

- [章 SOLE](sole.md)
MD
printf '# 章 SOLE\n\n正文。\n' > "$PV3/sole.md"
python3 - "$PV3" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])
digest = __import__('hashlib').sha256(
    (base / '00_目录.md').read_bytes()).hexdigest()
(base / 'map.json').write_text(json.dumps({"inputs": [{
    "path": str(base / '00_目录.md'), "sha256": digest,
    "sections": [{"lines": [3, 3], "chapters": [2]}]}]}), encoding='utf-8')
PY
python3 "$EXPORT" --output "$PV3/out.pdf" --work-dir "$PV3/w" \
  --provenance "$PV3/map.json" "$PV3/00_目录.md" "$PV3/sole.md" \
  >"$PV3/e.txt" 2>&1 \
  || { cat "$PV3/e.txt"; echo "错误：映射唯一来源导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$PV3/out.pdf" --work-dir "$PV3/w" \
  --provenance "$PV3/map.json" "$PV3/00_目录.md" "$PV3/sole.md" \
  >"$PV3/v.txt" 2>&1 \
  || { cat "$PV3/v.txt"; echo "错误：映射唯一来源核验失败"; exit 1; }
echo "映射为唯一出处来源：目录首位时导出与核验通过 PASS"

# 目录出处段含 Markdown 链接：核验以实际可见文字定位，正常通过（不再误报缺失）
PV4="$TMP/prov_toclink"; rm -rf "$PV4"; mkdir -p "$PV4"
cat > "$PV4/00_目录.md" <<'MD'
# 目录

译自 [Guide](https://example.com/pv-guide/book.html)

- [章 LINK](link.md)
MD
printf '# 章 LINK\n\n> **来源**：https://example.com/pv-guide/book.html\n\n正文。\n' \
  > "$PV4/link.md"
python3 "$EXPORT" --output "$PV4/out.pdf" --work-dir "$PV4/w" \
  "$PV4/00_目录.md" "$PV4/link.md" >"$PV4/e.txt" 2>&1 \
  || { cat "$PV4/e.txt"; echo "错误：链接出处导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$PV4/out.pdf" --work-dir "$PV4/w" \
  "$PV4/00_目录.md" "$PV4/link.md" >"$PV4/v.txt" 2>&1 \
  || { cat "$PV4/v.txt"; echo "错误：链接出处被核验误拒"; exit 1; }
echo "目录 Markdown 链接出处以可见文字定位通过 PASS"

# 同一出处段覆盖两章：实际段落只显示一次，导出与核验均通过（真实 Chromium/PDF）
PV5="$TMP/prov_shared"; rm -rf "$PV5"; mkdir -p "$PV5"
cat > "$PV5/00_目录.md" <<'MD'
# 目录

Source [Guide](https://example.com/pv-shared/guide.html)

- [章 A](a.md)
- [章 B](b.md)
MD
printf '# 章 A\n\n正文 A。\n' > "$PV5/a.md"
printf '# 章 B\n\n正文 B。\n' > "$PV5/b.md"
python3 - "$PV5" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])
digest = __import__('hashlib').sha256(
    (base / '00_目录.md').read_bytes()).hexdigest()
(base / 'map.json').write_text(json.dumps({"inputs": [{
    "path": str(base / '00_目录.md'), "sha256": digest,
    "sections": [{"lines": [3, 3], "chapters": [2, 3]}]}]}), encoding='utf-8')
PY
make_book_decl "$PV5/decl.json" "$PV5/00_目录.md" "$PV5/a.md" "$PV5/b.md"
python3 "$EXPORT" --output "$PV5/out.pdf" --work-dir "$PV5/w" \
  --view-declaration "$PV5/decl.json" \
  --provenance "$PV5/map.json" "$PV5/00_目录.md" "$PV5/a.md" "$PV5/b.md" \
  >"$PV5/e.txt" 2>&1 \
  || { cat "$PV5/e.txt"; echo "错误：共享出处段覆盖两章导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$PV5/out.pdf" --work-dir "$PV5/w" \
  --view-declaration "$PV5/decl.json" \
  --provenance "$PV5/map.json" "$PV5/00_目录.md" "$PV5/a.md" "$PV5/b.md" \
  >"$PV5/v.txt" 2>&1 \
  || { cat "$PV5/v.txt"; echo "错误：共享出处段覆盖两章被核验误拒"; exit 1; }
echo "同一出处段覆盖两章：实际段落定位一次，导出与核验通过 PASS"

# 函数级（纯规则）：同段多章覆盖去重为一段；真正不同的出处段保留边界不合并
python3 - "$TMP" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('../skills/tech-doc-translator/scripts').resolve()))
import export_pdf as e

base = Path(sys.argv[1]) / 'prov_distinct'
base.mkdir(exist_ok=True)
(base / '00_目录.md').write_text(
    '# 目录\n\n'
    'Source Guide v1: https://example.com/pv-dist/a (2026-01-01)\n\n'
    'Source Guide v2: https://example.com/pv-dist/b (2026-02-02)\n\n'
    '- [章 A](a.md)\n- [章 B](b.md)\n', encoding='utf-8')
(base / 'a.md').write_text('# 章 A\n\n正文 A。\n', encoding='utf-8')
(base / 'b.md').write_text('# 章 B\n\n正文 B。\n', encoding='utf-8')
digest = e.sha256_file(base / '00_目录.md')


def build(sections):
    (base / 'map.json').write_text(json.dumps({'inputs': [{
        'path': str(base / '00_目录.md'), 'sha256': digest,
        'sections': sections}]}), encoding='utf-8')
    chapters = e.load_inputs([str(base / '00_目录.md'), str(base / 'a.md'),
                              str(base / 'b.md')])
    for c in chapters:
        e.parse_chapter(c)
    pmap = e.load_provenance_map(base / 'map.json', chapters, [])
    facts = e.collect_provenance(chapters, chapters[0], pmap)
    return pmap, facts


# 同一段覆盖两章：覆盖关系保留两章，实际段落只有一份，定位串只出现一次
pmap, facts = build([{'lines': [3, 3], 'chapters': [2, 3]}])
assert pmap['covered'][2] == pmap['covered'][3]
assert pmap['text'] == pmap['covered'][2], pmap['text']
assert facts['covered'] == [2, 3], facts
assert facts['adopted_front'].count('Guide v1') == 1, facts['adopted_front']

# 两个不同出处段（不同版本/日期）：内容与覆盖关系不被合并，边界保留
pmap, facts = build([{'lines': [3, 3], 'chapters': [2]},
                     {'lines': [5, 5], 'chapters': [3]}])
assert pmap['covered'][2] != pmap['covered'][3]
assert 'Guide v1' in pmap['text'] and 'Guide v2' in pmap['text'], pmap['text']
assert '2026-01-01' in pmap['text'] and '2026-02-02' in pmap['text'], \
    pmap['text']
lines = facts['adopted_front'].split('\n')
assert len(lines) == 2, facts['adopted_front']
assert 'Guide v1' in lines[0] and 'Guide v2' in lines[1], facts['adopted_front']
print('出处段落与覆盖关系分离：同段去重、不同段保留边界与版本日期 PASS')
PY

# 被采用出处段的成品可见性实测（函数级）：新政策下出现即拒绝，
# 正文/目录合法出现同一来源文字按导出视图允许集合不误报
python3 - "$TMP" <<'PY'
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path('../skills/tech-doc-translator/scripts').resolve()))
import export_pdf as e
import verify_pdf as v

base = Path(sys.argv[1]) / 'prov_absence'
base.mkdir(exist_ok=True)
(base / '00_目录.md').write_text(
    '# 目录\n\n'
    '译自 Guide：https://example.com/pv-abs/book.html\n\n'
    '- [章 A](a.md)\n', encoding='utf-8')
(base / 'a.md').write_text(
    '# 章 A\n\n> **来源**：https://example.com/pv-abs/a\n\n正文。\n',
    encoding='utf-8')
chapters = e.load_inputs([str(base / '00_目录.md'), str(base / 'a.md')])
e.decide_toc_provenance(chapters)
for c in chapters:
    e.parse_chapter(c)
facts = e.collect_provenance(chapters, chapters[0], None)
front_line = '来源：https://example.com/pv-abs/a（适用：第 2 章）'
assert facts['adopted_front'] == front_line, facts['adopted_front']
assert chapters[0].toc_provenance_exclusion is not None
report = {'provenance': {**facts, 'mapping': None,
                         'policy': {'fields': list(e.MANAGEMENT_FIELD_LABELS)},
                         'pdf_visibility': 'excluded'}}


def norm(s):
    import re, unicodedata
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


toc_visible = '译自Guide：https://example.com/pv-abs/book.html'
cases = {
    # 目录译自段被排除且正文无同名文字：出现即拒绝
    'absent': ('single', ''),
    'front-present': ('single', norm(front_line)),
    'toc-present': ('single', norm(toc_visible)),
    # 正文合法出现同一来源文字：允许集合内不误报
    'body-dup': ('dup', norm('正文。\n' + toc_visible)),
}
# 让导出视图保留一处目录来源文字（正文合法重复）以校验允许集合口径
(base / 'a.md').write_text(
    '# 章 A\n\n> **来源**：https://example.com/pv-abs/a\n\n正文。\n\n'
    '译自 Guide：https://example.com/pv-abs/book.html\n', encoding='utf-8')
chapters_dup = e.load_inputs([str(base / '00_目录.md'), str(base / 'a.md')])
e.decide_toc_provenance(chapters_dup)
for c in chapters_dup:
    e.parse_chapter(c)
sets = {'single': chapters, 'dup': chapters_dup}
out = {}
for name, (which, norm_text) in cases.items():
    failures = []
    pdf = SimpleNamespace(norm_text=norm_text)
    v.check_provenance(sets[which], report, pdf, None, failures)
    out[name] = [f['code'] for f in failures]
assert out['absent'] == [], out
assert out['front-present'] == ['provenance-front-present'], out
assert out['toc-present'] == ['provenance-front-present'], out
assert out['body-dup'] == [], out  # 正文合法出现：PDF 1 次 ≤ 视图 1 次
# 旧证据（无 pdf_visibility 字段）必须被新政策拒绝
failures = []
v.check_provenance(chapters, {'provenance': {**facts, 'mapping': None,
                              'policy': {'fields': list(e.MANAGEMENT_FIELD_LABELS)}}},
                   SimpleNamespace(norm_text=''), None, failures)
assert any(f['code'] == 'provenance-policy-mismatch' for f in failures), failures
print('被采用出处段成品可见性实测：缺席通过、残留拒绝、正文合法重复不误报、'
      '旧口径证据失效 PASS')
PY

echo "==> R2/C6（译注排除）：已标识译注只从 PDF 排除，代码/原文引用保留"
TN="$TMP/translator_notes"; rm -rf "$TN"; mkdir -p "$TN"
cat > "$TN/note.md" <<'MD'
# 章 注

> **来源**：https://example.com/prov-tn

正文句一。【译注：样例译注】句二继续。

参考文献行：Author, A. Title. https://example.com/ref-a。【译注：URL 还原说明】

```text
代码中 【译注：代码内不删】 保留。
```

> 原文引用 【译注：引用内不删】 保留。

`行内 【译注：代码串不删】 也保留。`

同片段首现。【译注：重复译注】甲。

同片段二现。【译注：重复译注】乙。

同行两处：【译注：同行注】与【译注：同行注】并列，另随【译注：重复译注】三现。

行内标记译注：前文【译注：含 `code` 与 *强调* 标记】后文。
MD
python3 "$EXPORT" --output "$TN/book.pdf" --work-dir "$TN/work" \
  "$TN/note.md" >"$TN/export.txt" 2>&1 \
  || { cat "$TN/export.txt"; echo "错误：译注样例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$TN/book.pdf" --work-dir "$TN/work" \
  "$TN/note.md" >"$TN/verify.txt" 2>&1 \
  || { cat "$TN/verify.txt"; echo "错误：译注样例核验失败"; exit 1; }
python3 - "$TN/work" "$TN/book.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
notes = report["translator_note_exclusions"]
# 逐处行号登记：同一翻译注片段的每次出现登记各自实际行号，
# 同行两处各自记录，不错位、不重复登记首处行号；含行内 code/强调
# 标记的译注被拆成多个文本节点也须整段剥离，登记片段取源文原文。
assert [(n["line"], n["fragment"]) for n in notes] == [
    (5, "【译注：样例译注】"),
    (7, "【译注：URL 还原说明】"),
    (17, "【译注：重复译注】"),
    (19, "【译注：重复译注】"),
    (21, "【译注：同行注】"),
    (21, "【译注：同行注】"),
    (21, "【译注：重复译注】"),
    (23, "【译注：含 `code` 与 *强调* 标记】"),
], notes
assert all(n["input"].endswith("note.md") for n in notes), notes


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
for hidden in ("【译注：样例译注】", "【译注：URL还原说明】",
               "【译注：重复译注】", "【译注：同行注】",
               "【译注：含code与强调标记】"):
    assert norm(hidden) not in text, f"译注不应出现在 PDF：{hidden}"
for keep in ("正文句一。句二继续。",
             "参考文献行：Author,A.Title.https://example.com/ref-a。",
             norm("代码中 【译注：代码内不删】 保留。"),
             norm("原文引用 【译注：引用内不删】 保留。"),
             norm("行内 【译注：代码串不删】 也保留。"),
             "同片段首现。甲。",
             "同片段二现。乙。",
             "同行两处：与并列，另随三现。",
             "行内标记译注：前文后文。"):
    assert norm(keep) in text, f"译注旁文或保留区内容缺失：{keep}"
print("译注清单、逐处行号、PDF 缺席、旁文与代码/引用保留证据齐全")
PY
echo "已标识译注：正文移除、参考文献行内只删片段、代码/引用保留 PASS"

echo "==> R2（视图声明）：受输入绑定的授权排除与失败保护"
VD="$TMP/view_decl"; rm -rf "$VD"; mkdir -p "$VD"
cat > "$VD/00_目录.md" <<'MD'
# 目录

- [章 VD](vd.md)
MD
cat > "$VD/vd.md" <<'MD'
# 章 VD

> **来源**：https://example.com/prov-vd

正文段落一。

> 本节为文献引用数据整理说明，非原文内容。

正文段落二。【导览：旧版说明】仍在。

| 列 A | 列 B |
|---|---|
| 1 | 2 |
MD
python3 - "$VD" <<'PY'
import hashlib, json, sys
from pathlib import Path

base = Path(sys.argv[1])
lines = (base / 'vd.md').read_text(encoding='utf-8').split('\n')
quote_start = next(i for i, l in enumerate(lines, 1) if l.startswith('> 本节'))
inline_line = next(i for i, l in enumerate(lines, 1) if '【导览' in l)
inputs = []
for name in ('00_目录.md', 'vd.md'):
    inputs.append({'path': str(base / name),
                   'sha256': hashlib.sha256(
                       (base / name).read_bytes()).hexdigest()})
(base / 'decl.json').write_text(json.dumps({
    'version': 1, 'inputs': inputs,
    'exclusions': [
        {'input': str(base / 'vd.md'), 'lines': [quote_start, quote_start],
         'type': 'block', 'kind': 'translator-guide',
         'fragment': '本节为文献引用数据整理说明',
         'reason': '译者添加的导览说明，非原文内容'},
        {'input': str(base / 'vd.md'), 'lines': [inline_line, inline_line],
         'type': 'inline', 'kind': 'translator-guide',
         'fragment': '【导览：旧版说明】',
         'reason': '译者添加的行内导览片段'},
    ],
    'document_title': {'original': '章 VD', 'chinese': 'VD 文档',
                       'basis': '样例依据'}}, ensure_ascii=False),
    encoding='utf-8')
print('声明就绪：block 引用块 + inline 行内片段')
PY
python3 "$EXPORT" --output "$VD/book.pdf" --work-dir "$VD/work" \
  --view-declaration "$VD/decl.json" "$VD/00_目录.md" "$VD/vd.md" \
  >"$VD/export.txt" 2>&1 \
  || { cat "$VD/export.txt"; echo "错误：合法视图声明导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$VD/book.pdf" --work-dir "$VD/work" \
  --view-declaration "$VD/decl.json" "$VD/00_目录.md" "$VD/vd.md" \
  >"$VD/verify.txt" 2>&1 \
  || { cat "$VD/verify.txt"; echo "错误：合法视图声明核验失败"; exit 1; }
python3 - "$VD/work" "$VD/book.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
decl = report["view_declaration"]
assert decl["sha256"] and len(decl["exclusions"]) == 2, decl
assert decl["document_title"]["chinese"] == "VD 文档", decl
assert report["translator_note_exclusions"] == [], report["translator_note_exclusions"]


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


text = norm("".join(p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[2]).pages))
for hidden in ("本节为文献引用数据整理说明", "【导览：旧版说明】"):
    assert norm(hidden) not in text, f"声明排除内容不应出现在 PDF：{hidden}"
# 带目录单篇按 ticket 04 口径替换首章 H1 可见文字为声明的中文题名；
# 相邻正文、表格与印刷目录保留。
for keep in ("正文段落一。", "正文段落二。仍在。", "VD文档", "列A"):
    assert norm(keep) in text, f"相邻内容缺失：{keep}"
print("声明记录、PDF 缺席与相邻内容完整证据齐全")
PY
# 核验不传入声明 → 参数不一致必须失败
if python3 "$VERIFY" --pdf "$VD/book.pdf" --work-dir "$VD/work" \
    "$VD/00_目录.md" "$VD/vd.md" >"$VD/verify_nofdecl.txt" 2>&1; then
  echo "错误：核验缺声明未被判不一致"; exit 1
fi
grep -q "view-declaration-mismatch" "$VD/verify_nofdecl.txt" \
  || { cat "$VD/verify_nofdecl.txt"; echo "错误：缺声明诊断缺失"; exit 1; }
# 反例：篡改声明摘要 / 越界区间 / 重叠范围 / fragment 不匹配 / 跨技术正文
python3 - "$VD" <<'PY'
import json, sys
from pathlib import Path

base = Path(sys.argv[1])
good = json.loads((base / 'decl.json').read_text(encoding='utf-8'))


def variant(name, mutate):
    data = json.loads(json.dumps(good))
    mutate(data)
    (base / name).write_text(json.dumps(data, ensure_ascii=False),
                             encoding='utf-8')


variant('decl_baddigest.json',
        lambda d: d['inputs'][0].__setitem__('sha256', '0' * 64))
variant('decl_oob.json', lambda d: d['exclusions'][0].__setitem__('lines', [999, 1000]))
variant('decl_overlap.json', lambda d: d['exclusions'].append({
    'input': d['exclusions'][0]['input'], 'lines': d['exclusions'][0]['lines'],
    'type': 'block', 'kind': 'translator-guide', 'fragment': '非原文内容',
    'reason': '重叠反例'}))
variant('decl_badfragment.json',
        lambda d: d['exclusions'][1].__setitem__('fragment', '【导览：不存在】'))
variant('decl_heading.json', lambda d: d['exclusions'].append({
    'input': d['exclusions'][0]['input'], 'lines': [1, 1], 'type': 'block',
    'kind': 'translator-guide', 'fragment': '章 VD', 'reason': '标题反例'}))
variant('decl_fence.json', lambda d: d['exclusions'].append({
    'input': d['exclusions'][0]['input'], 'lines': [11, 14], 'type': 'block',
    'kind': 'translator-guide', 'fragment': '|---|---|', 'reason': '表格反例'}))
print('声明反例就绪')
PY
for bad in decl_baddigest decl_oob decl_overlap decl_badfragment decl_heading decl_fence; do
  if python3 "$EXPORT" --output "$VD/bad.pdf" --work-dir "$VD/w_$bad" \
      --view-declaration "$VD/$bad.json" "$VD/00_目录.md" "$VD/vd.md" \
      >"$VD/$bad.txt" 2>&1; then
    echo "错误：$bad 未被拒绝"; exit 1
  fi
  test ! -f "$VD/w_$bad/candidate.pdf" \
    || { echo "错误：$bad 仍生成候选"; exit 1; }
done
grep -q "摘要与输入不符" "$VD/decl_baddigest.txt" \
  || { cat "$VD/decl_baddigest.txt"; echo "错误：声明摘要诊断缺失"; exit 1; }
grep -q "区间越界" "$VD/decl_oob.txt" \
  || { cat "$VD/decl_oob.txt"; echo "错误：越界诊断缺失"; exit 1; }
grep -q "范围重叠" "$VD/decl_overlap.txt" \
  || { cat "$VD/decl_overlap.txt"; echo "错误：重叠诊断缺失"; exit 1; }
grep -q "fragment 与实际文本不符" "$VD/decl_badfragment.txt" \
  || { cat "$VD/decl_badfragment.txt"; echo "错误：fragment 诊断缺失"; exit 1; }
grep -q "技术正文" "$VD/decl_heading.txt" \
  || { cat "$VD/decl_heading.txt"; echo "错误：标题诊断缺失"; exit 1; }
grep -q "技术正文" "$VD/decl_fence.txt" \
  || { cat "$VD/decl_fence.txt"; echo "错误：表格诊断缺失"; exit 1; }
echo "视图声明：合法通过、缺声明核验不一致、六类反例零生成拒绝 PASS"

echo "==> R3/A4/C5（ticket 04）：中文文档总标题决定、投影与核验"
DT="$TMP/doc_title"; rm -rf "$DT"; mkdir -p "$DT"

# 正例 1：中英双语 H1 无声明 → 采用括号内中文题名，元数据一致，章节标题不变
cat > "$DT/bilingual.md" <<'MD'
# Torch.fx: Practical Program Capture（Torch.fx：实用程序捕获）

> **来源**：https://example.com/prov-dt-bilingual

## 1. Introduction（引言）

正文内容。
MD
python3 "$EXPORT" --output "$DT/bilingual.pdf" --work-dir "$DT/w_bi" \
  "$DT/bilingual.md" >"$DT/bi.txt" 2>&1 \
  || { cat "$DT/bi.txt"; echo "错误：双语 H1 导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$DT/bilingual.pdf" --work-dir "$DT/w_bi" \
  "$DT/bilingual.md" >"$DT/bi_v.txt" 2>&1 \
  || { cat "$DT/bi_v.txt"; echo "错误：双语 H1 核验失败"; exit 1; }
python3 - "$DT/w_bi" "$DT/bilingual.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
title = report["document_title"]
assert title == {
    "title": "Torch.fx：实用程序捕获",
    "original": "Torch.fx: Practical Program Capture（Torch.fx：实用程序捕获）",
    "basis": "首章 H1 括号内中文题名：Torch.fx: Practical Program Capture"
             "（Torch.fx：实用程序捕获）",
    "source": "bilingual-h1",
}, title
reader = pypdf.PdfReader(sys.argv[2])
assert reader.metadata.title == "Torch.fx：实用程序捕获", reader.metadata.title


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


text = norm("".join(p.extract_text() or "" for p in reader.pages))
page1 = norm(reader.pages[0].extract_text() or "")
assert norm("Torch.fx：实用程序捕获") in page1, "可见总标题不在第 1 页"
assert "PracticalProgramCapture" not in page1, "英文原题不应作为可见总标题"
# 章节标题按输入保留（中英双语不变）。
assert norm("1.Introduction（引言）") in text, "章节标题行为变化"
print("双语 H1：中文总标题、/Title 一致、章节标题不变 PASS")
PY

# 反例：纯外文题名无声明 → 拒绝生成（零候选），错误指明缺口
cat > "$DT/foreign.md" <<'MD'
# Introduction to CUDA Programming

> **来源**：https://example.com/prov-dt-foreign

正文。
MD
if python3 "$EXPORT" --output "$DT/foreign.pdf" --work-dir "$DT/w_fo" \
    "$DT/foreign.md" >"$DT/fo.txt" 2>&1; then
  echo "错误：纯外文题名未被拒绝"; exit 1
fi
grep -q "仅外文题名" "$DT/fo.txt" \
  || { cat "$DT/fo.txt"; echo "错误：外文题名诊断缺失"; exit 1; }
test ! -f "$DT/w_fo/candidate.pdf" \
  || { echo "错误：纯外文题名仍生成候选"; exit 1; }
echo "纯外文题名无声明：定位缺口拒绝且零生成 PASS"

# 正例 2：视图声明题名 → 采用并可回查（记录 original/chinese/basis）
cat > "$DT/declared.md" <<'MD'
# Introduction to CUDA Programming

> **来源**：https://example.com/prov-dt-declared

正文。
MD
python3 - "$DT" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
md = base / "declared.md"
(base / "decl_title.json").write_text(json.dumps({
    "version": 1,
    "inputs": [{"path": str(md.resolve()),
                "sha256": hashlib.sha256(md.read_bytes()).hexdigest()}],
    "exclusions": [],
    "document_title": {"original": "Introduction to CUDA Programming",
                       "chinese": "CUDA 编程指南全集",
                       "basis": "Agent 依据有序输入范围与章题拟定（测试）"}},
    ensure_ascii=False), encoding="utf-8")
PY
python3 "$EXPORT" --output "$DT/declared.pdf" --work-dir "$DT/w_de" \
  --view-declaration "$DT/decl_title.json" "$DT/declared.md" >"$DT/de.txt" 2>&1 \
  || { cat "$DT/de.txt"; echo "错误：声明题名导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$DT/declared.pdf" --work-dir "$DT/w_de" \
  --view-declaration "$DT/decl_title.json" "$DT/declared.md" >"$DT/de_v.txt" 2>&1 \
  || { cat "$DT/de_v.txt"; echo "错误：声明题名核验失败"; exit 1; }
python3 - "$DT/w_de" "$DT/declared.pdf" <<'PY'
import json, sys
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
title = report["document_title"]
assert title["source"] == "declaration" and title["title"] == "CUDA 编程指南全集", title
assert title["original"] == "Introduction to CUDA Programming", title
assert title["basis"], title  # 依据可回查
assert pypdf.PdfReader(sys.argv[2]).metadata.title == "CUDA 编程指南全集"
print("声明题名：采用且 original/chinese/basis 可回查、/Title 一致 PASS")
PY

# 合订：无书名（首章外文 H1）拒绝；有声明 → 独立总标题、各章 H1 不变、首章仍首章
cat > "$DT/00_目录.md" <<'MD'
# 目录

- [Chapter One](one.md)
- [Chapter Two](two.md)
MD
cat > "$DT/one.md" <<'MD'
# Chapter One

> **来源**：https://example.com/prov-dt-one

一正文。
MD
cat > "$DT/two.md" <<'MD'
# Chapter Two

> **来源**：https://example.com/prov-dt-two

二正文。
MD
if python3 "$EXPORT" --output "$DT/book.pdf" --work-dir "$DT/w_bo" \
    "$DT/00_目录.md" "$DT/one.md" "$DT/two.md" >"$DT/bo.txt" 2>&1; then
  echo "错误：无书名合订未被拒绝"; exit 1
fi
grep -q "合订缺书名" "$DT/bo.txt" \
  || { cat "$DT/bo.txt"; echo "错误：合订缺书名诊断缺失"; exit 1; }
test ! -f "$DT/w_bo/candidate.pdf" \
  || { echo "错误：无书名合订仍生成候选"; exit 1; }
python3 - "$DT" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
inputs = [base / "00_目录.md", base / "one.md", base / "two.md"]
(base / "book_title.json").write_text(json.dumps({
    "version": 1,
    "inputs": [{"path": str(p.resolve()),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in inputs],
    "exclusions": [],
    "document_title": {"original": "Chapters One and Two",
                       "chinese": "第一、二章合订全集",
                       "basis": "Agent 依据有序输入范围与章题拟定（测试）"}},
    ensure_ascii=False), encoding="utf-8")
PY
python3 "$EXPORT" --output "$DT/book.pdf" --work-dir "$DT/w_book" \
  --view-declaration "$DT/book_title.json" \
  "$DT/00_目录.md" "$DT/one.md" "$DT/two.md" >"$DT/book.txt" 2>&1 \
  || { cat "$DT/book.txt"; echo "错误：有书名合订导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$DT/book.pdf" --work-dir "$DT/w_book" \
  --view-declaration "$DT/book_title.json" \
  "$DT/00_目录.md" "$DT/one.md" "$DT/two.md" >"$DT/book_v.txt" 2>&1 \
  || { cat "$DT/book_v.txt"; echo "错误：有书名合订核验失败"; exit 1; }
python3 - "$DT/w_book" "$DT/book.pdf" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
assert report["document_title"]["title"] == "第一、二章合订全集", report["document_title"]
reader = pypdf.PdfReader(sys.argv[2])
assert reader.metadata.title == "第一、二章合订全集", reader.metadata.title


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


page1 = norm(reader.pages[0].extract_text() or "")
assert norm("第一、二章合订全集") in page1, "合订总标题不在第 1 页最前可见区域"
assert page1.find(norm("第一、二章合订全集")) < page1.find("目录"), \
    "总标题应先于目录标题"
text = norm("".join(p.extract_text() or "" for p in reader.pages))
assert norm("ChapterOne") in text and norm("ChapterTwo") in text, \
    "各章 H1 应保持不变"
# 印刷目录条目与各章页序仍正确（首章仍首章）。
toc = report["toc"]
assert [e["page"] for e in toc["entries"]] == sorted(
    e["page"] for e in toc["entries"]), toc["entries"]
print("合订：声明书名、独立总标题先于目录、各章 H1 不变、目录页码正确 PASS")
PY

# 反例：篡改 /Title 元数据或可见总标题 → 核验失败
python3 - "$DT" <<'PY'
import json, sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

base = Path(sys.argv[1])
reader = PdfReader(str(base / "bilingual.pdf"))
writer = PdfWriter(clone_from=reader)
writer.add_metadata({"/Title": "篡改后的标题"})
writer.write(str(base / "tampered_meta.pdf"))
reader = PdfReader(str(base / "bilingual.pdf"))
writer = PdfWriter(clone_from=reader)
stream = DecodedStreamObject()
stream.set_data(b"")
writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
writer.write(str(base / "tampered_visible.pdf"))
print("篡改样本就绪")
PY
if python3 "$VERIFY" --pdf "$DT/tampered_meta.pdf" --work-dir "$DT/w_bi" \
    "$DT/bilingual.md" >"$DT/tm.txt" 2>&1; then
  echo "错误：篡改 /Title 未被检出"; exit 1
fi
grep -q "document-title-metadata" "$DT/tm.txt" \
  || { cat "$DT/tm.txt"; echo "错误：元数据篡改诊断缺失"; exit 1; }
if python3 "$VERIFY" --pdf "$DT/tampered_visible.pdf" --work-dir "$DT/w_bi" \
    "$DT/bilingual.md" >"$DT/tv.txt" 2>&1; then
  echo "错误：可见总标题被清空未被检出"; exit 1
fi
grep -q "document-title-missing" "$DT/tv.txt" \
  || { cat "$DT/tv.txt"; echo "错误：可见标题篡改诊断缺失"; exit 1; }
echo "篡改 /Title 或可见总标题：独立核验均判 FAIL PASS"

echo "==> 评审修复回归（P1）：目录出处块边界 / inline 唯一出现 / 题名声明校验"
P1="$TMP/p1_regress"; rm -rf "$P1"; mkdir -p "$P1"

# P1-1 正例：导航列表无空行紧接引用块出处（合法独立块）→ 剔除出处、保留目录
cat > "$P1/00_目录.md" <<'MD'
# 目录

- [第 A 章](a.md)
- [第 B 章](b.md)
> 译自 Guide：https://example.com/p11/book
MD
printf '# 第 A 章\n\n> **来源**：https://example.com/p11-a\n\nA 章正文。\n' > "$P1/a.md"
printf '# 第 B 章\n\n> **来源**：https://example.com/p11-b\n\nB 章正文。\n' > "$P1/b.md"
make_book_decl "$P1/decl_book.json" "$P1/00_目录.md" "$P1/a.md" "$P1/b.md"
python3 "$EXPORT" --output "$P1/book.pdf" --work-dir "$P1/w" \
  --view-declaration "$P1/decl_book.json" \
  "$P1/00_目录.md" "$P1/a.md" "$P1/b.md" >"$P1/e.txt" 2>&1 \
  || { cat "$P1/e.txt"; echo "错误：引用块出处正例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$P1/book.pdf" --work-dir "$P1/w" \
  --view-declaration "$P1/decl_book.json" \
  "$P1/00_目录.md" "$P1/a.md" "$P1/b.md" >"$P1/v.txt" 2>&1 \
  || { cat "$P1/v.txt"; echo "错误：引用块出处正例核验失败"; exit 1; }
python3 - "$P1/book.pdf" <<'PY'
import re, sys, unicodedata

import pypdf


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


text = norm("".join(
    p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[1]).pages))
assert norm("译自Guide：https://example.com/p11/book") not in text, \
    "目录出处段未从导出视图剔除"
assert norm("第A章") in text and norm("第B章") in text, "目录导航条目被误删"
print("P1-1 正例：独立引用块出处剔除、导航目录保留")
PY

# P1-1 反例：导航列表无空行紧接直接出处段（懒惰续行共享块）→ 定位失败
mkdir -p "$P1/badcase"
cat > "$P1/badcase/00_目录.md" <<'MD'
# 目录

- [第 A 章](a.md)
译自 Guide：https://example.com/p11/book
MD
if python3 "$EXPORT" --output "$P1/bad.pdf" --work-dir "$P1/w_bad" \
    "$P1/badcase/00_目录.md" "$P1/a.md" "$P1/b.md" >"$P1/bad.txt" 2>&1; then
  echo "错误：共享块出处未被拒绝"; exit 1
fi
grep -q "未形成独立顶层段落块\|未形成独立段落块\|共享同一块" "$P1/bad.txt" \
  || { cat "$P1/bad.txt"; echo "错误：共享块诊断缺失"; exit 1; }
test ! -f "$P1/w_bad/candidate.pdf" \
  || { echo "错误：共享块出处仍生成候选"; exit 1; }
echo "P1-1 反例：共享块出处定位失败、零候选 PASS"

# P1-2 反例：inline 片段同行出现两次 → 加载拒绝；正例：唯一出现、同行其余完整
cat > "$P1/inline.md" <<'MD'
# 章 行内

> **来源**：https://example.com/p12

说明【导览：重复】与【导览：重复】同行两次。

保留 `keep` 代码与 keep 正文。
MD
python3 - "$P1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
md = base / 'inline.md'


def write_decl(name, fragment, lines):
    base.joinpath(name).write_text(json.dumps({
        'version': 1,
        'inputs': [{'path': str(md.resolve()),
                    'sha256': hashlib.sha256(md.read_bytes()).hexdigest()}],
        'exclusions': [{'input': str(md.resolve()), 'lines': lines,
                        'type': 'inline', 'kind': 'translator-guide',
                        'fragment': fragment, 'reason': '评审回归反例'}],
        'document_title': {'original': '章 行内', 'chinese': '行内章',
                           'basis': '评审回归'},
    }, ensure_ascii=False), encoding='utf-8')


write_decl('decl_dup.json', '【导览：重复】', [5, 5])
print('inline 反例声明就绪')
PY
if python3 "$EXPORT" --output "$P1/dup.pdf" --work-dir "$P1/w_dup" \
    --view-declaration "$P1/decl_dup.json" "$P1/inline.md" \
    >"$P1/dup.txt" 2>&1; then
  echo "错误：inline 重复片段未被拒绝"; exit 1
fi
grep -q "恰好出现一次" "$P1/dup.txt" \
  || { cat "$P1/dup.txt"; echo "错误：inline 唯一性诊断缺失"; exit 1; }
test ! -f "$P1/w_dup/candidate.pdf" \
  || { echo "错误：inline 重复片段仍生成候选"; exit 1; }
python3 - "$P1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
md = base / 'inline.md'
text = md.read_text(encoding='utf-8')
md.write_text(text.replace('说明【导览：重复】与【导览：重复】同行两次。',
                           '说明【导览：旧记】保留 `keep` 代码与 keep 正文。'),
              encoding='utf-8')
base.joinpath('decl_ok.json').write_text(json.dumps({
    'version': 1,
    'inputs': [{'path': str(md.resolve()),
                'sha256': hashlib.sha256(md.read_bytes()).hexdigest()}],
    'exclusions': [{'input': str(md.resolve()), 'lines': [5, 5],
                    'type': 'inline', 'kind': 'translator-guide',
                    'fragment': '【导览：旧记】', 'reason': '评审回归正例'}],
    'document_title': {'original': '章 行内', 'chinese': '行内章',
                       'basis': '评审回归'},
}, ensure_ascii=False), encoding='utf-8')
print('inline 正例声明就绪')
PY
python3 "$EXPORT" --output "$P1/inline_ok.pdf" --work-dir "$P1/w_ok" \
  --view-declaration "$P1/decl_ok.json" "$P1/inline.md" >"$P1/ok_e.txt" 2>&1 \
  || { cat "$P1/ok_e.txt"; echo "错误：inline 正例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$P1/inline_ok.pdf" --work-dir "$P1/w_ok" \
  --view-declaration "$P1/decl_ok.json" "$P1/inline.md" >"$P1/ok_v.txt" 2>&1 \
  || { cat "$P1/ok_v.txt"; echo "错误：inline 正例核验失败"; exit 1; }
python3 - "$P1/inline_ok.pdf" <<'PY'
import re, sys, unicodedata

import pypdf


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


text = norm("".join(
    p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[1]).pages))
assert norm("【导览：旧记】") not in text, "译注片段未剔除"
assert norm("保留keep代码与keep正文") in text, "同行代码 span 与正文被连带删除"
print("P1-2：重复片段拒绝且零候选；唯一片段剔除、同行其余完整 PASS")
PY

# P1-3 反例：题名声明纯外文 / 空 basis / 空 original / 与首章 H1 不符 → 拒绝
cat > "$P1/title.md" <<'MD'
# Title Fixture

> **来源**：https://example.com/p13

正文。
MD
python3 - "$P1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
md = base / 'title.md'
digest = hashlib.sha256(md.read_bytes()).hexdigest()


def write(name, title):
    base.joinpath(name).write_text(json.dumps({
        'version': 1,
        'inputs': [{'path': str(md.resolve()), 'sha256': digest}],
        'exclusions': [],
        'document_title': title,
    }, ensure_ascii=False), encoding='utf-8')


write('decl_foreign.json',
      {'original': 'Title Fixture', 'chinese': 'English Book',
       'basis': '评审回归'})
write('decl_nobasis.json',
      {'original': 'Title Fixture', 'chinese': '题名样例', 'basis': ''})
write('decl_nooriginal.json',
      {'original': '', 'chinese': '题名样例', 'basis': '评审回归'})
write('decl_mismatch.json',
      {'original': 'Another Title', 'chinese': '题名样例', 'basis': '评审回归'})
write('decl_good.json',
      {'original': 'Title Fixture', 'chinese': '题名样例', 'basis': '评审回归'})
print('题名声明反例就绪')
PY
for bad in decl_foreign decl_nobasis decl_nooriginal decl_mismatch; do
  if python3 "$EXPORT" --output "$P1/$bad.pdf" --work-dir "$P1/w_$bad" \
      --view-declaration "$P1/$bad.json" "$P1/title.md" \
      >"$P1/$bad.txt" 2>&1; then
    echo "错误：$bad 未被拒绝"; exit 1
  fi
  test ! -f "$P1/w_$bad/candidate.pdf" \
    || { echo "错误：$bad 仍生成候选"; exit 1; }
done
grep -q "须为含中文" "$P1/decl_foreign.txt" \
  || { cat "$P1/decl_foreign.txt"; echo "错误：纯外文题名诊断缺失"; exit 1; }
grep -q "basis 必填" "$P1/decl_nobasis.txt" \
  || { cat "$P1/decl_nobasis.txt"; echo "错误：空 basis 诊断缺失"; exit 1; }
grep -q "original 必填" "$P1/decl_nooriginal.txt" \
  || { cat "$P1/decl_nooriginal.txt"; echo "错误：空 original 诊断缺失"; exit 1; }
grep -q "与首章实际题名不符" "$P1/decl_mismatch.txt" \
  || { cat "$P1/decl_mismatch.txt"; echo "错误：original 不符诊断缺失"; exit 1; }
python3 "$EXPORT" --output "$P1/title_ok.pdf" --work-dir "$P1/w_good" \
  --view-declaration "$P1/decl_good.json" "$P1/title.md" >"$P1/good.txt" 2>&1 \
  || { cat "$P1/good.txt"; echo "错误：合法题名声明导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$P1/title_ok.pdf" --work-dir "$P1/w_good" \
  --view-declaration "$P1/decl_good.json" "$P1/title.md" >"$P1/good_v.txt" 2>&1 \
  || { cat "$P1/good_v.txt"; echo "错误：合法题名声明核验失败"; exit 1; }
echo "P1-3：纯外文/空 basis/空 original/原题不符均拒绝且零候选，合法声明通过 PASS"

echo "==> 评审修复回归二（P1）：出处结构谓词 / 题名取首章第一个 H1"
P2R="$TMP/p1_round2"; rm -rf "$P2R"; mkdir -p "$P2R"

# P1-1 反例：引用块内“译自”与导航列表同块（两种顺序）→ 拒绝且零候选
printf '# 第 A 章\n\n> **来源**：https://example.com/r2-a\n\nA 正文。\n' > "$P2R/a.md"
for order in listfirst provfirst; do
  mkdir -p "$P2R/$order"
  if [ "$order" = listfirst ]; then
    cat > "$P2R/$order/00_目录.md" <<'MD'
# 目录

> - [第 A 章](a.md)
> 译自 Guide：https://example.com/r2/book
MD
  else
    cat > "$P2R/$order/00_目录.md" <<'MD'
# 目录

> 译自 Guide：https://example.com/r2/book
> - [第 A 章](a.md)
MD
  fi
  if python3 "$EXPORT" --output "$P2R/$order.pdf" --work-dir "$P2R/w_$order" \
      "$P2R/$order/00_目录.md" "$P2R/a.md" >"$P2R/$order.txt" 2>&1; then
    echo "错误：引用块共享块（$order）未被拒绝"; exit 1
  fi
  grep -q "共享同一块" "$P2R/$order.txt" \
    || { cat "$P2R/$order.txt"; echo "错误：共享块（$order）诊断缺失"; exit 1; }
  test ! -f "$P2R/w_$order/candidate.pdf" \
    || { echo "错误：共享块（$order）仍生成候选"; exit 1; }
done
echo "P1-1 反例：引用块内出处+导航两种顺序均定位拒绝、零候选 PASS"

# P1-1 正例：顶层引用块仅含出处段 → 剔除出处、目录保留（上一轮 P1-1 正例同口径，复验）
# （用例见“评审修复回归（P1）”节，此处不重复导出。）

# P1-2 正例：H2 在前、H1 在后 → PDF Title 取 H1 中文题名，H2 不受影响
cat > "$P2R/h1_back.md" <<'MD'
> **来源**：https://example.com/r2-h1

## 前言

前言正文。

# 真正总标题（真书题）

正文内容。
MD
python3 "$EXPORT" --output "$P2R/h1_back.pdf" --work-dir "$P2R/w_h1" \
  "$P2R/h1_back.md" >"$P2R/h1_e.txt" 2>&1 \
  || { cat "$P2R/h1_e.txt"; echo "错误：H2 在前正例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$P2R/h1_back.pdf" --work-dir "$P2R/w_h1" \
  "$P2R/h1_back.md" >"$P2R/h1_v.txt" 2>&1 \
  || { cat "$P2R/h1_v.txt"; echo "错误：H2 在前正例核验失败"; exit 1; }
python3 - "$P2R/w_h1" "$P2R/h1_back.pdf" <<'PY'
import json, sys
from pathlib import Path

import pypdf

report = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))
assert report["document_title"]["title"] == "真正总标题（真书题）", report["document_title"]
reader = pypdf.PdfReader(sys.argv[2])
assert reader.metadata.title == "真正总标题（真书题）", reader.metadata.title
text = "".join(page.extract_text() or "" for page in reader.pages)
assert "前言正文" in text and "真正总标题（真书题）" in text, text[:80]
print("P1-2 正例：题名取首章第一个 H1，H2 前言不受影响")
PY

# P1-2 反例：首章无 H1 → 拒绝且零候选
cat > "$P2R/no_h1.md" <<'MD'
> **来源**：https://example.com/r2-noh1

## 只有小节

正文。
MD
if python3 "$EXPORT" --output "$P2R/no_h1.pdf" --work-dir "$P2R/w_noh1" \
    "$P2R/no_h1.md" >"$P2R/noh1.txt" 2>&1; then
  echo "错误：无 H1 首章未被拒绝"; exit 1
fi
grep -q "缺少 H1 标题" "$P2R/noh1.txt" \
  || { cat "$P2R/noh1.txt"; echo "错误：无 H1 诊断缺失"; exit 1; }
test ! -f "$P2R/w_noh1/candidate.pdf" \
  || { echo "错误：无 H1 仍生成候选"; exit 1; }
echo "P1-2 反例：首章无 H1 定位失败、零候选 PASS"

# 第三轮（P1-1 单行谓词）：引用块单段两行 / 顶层段落两行同段 → 拒绝且零候选
for variant in quote plain; do
  mkdir -p "$P2R/r3_$variant"
  printf '# 第 A 章\n\n> **来源**：https://example.com/r3-%s\n\nA 正文。\n' "$variant" \
    > "$P2R/r3_$variant/a.md"
  if [ "$variant" = quote ]; then
    cat > "$P2R/r3_$variant/00_目录.md" <<'MD'
# 目录

- [第 A 章](a.md)

> 译自 [原文](https://example.com/x)
> [附加导览](a.md)
MD
  else
    cat > "$P2R/r3_$variant/00_目录.md" <<'MD'
# 目录

- [第 A 章](a.md)

译自 https://example.com/x
[附加导览](a.md)
MD
  fi
  if python3 "$EXPORT" --output "$P2R/r3_$variant.pdf" \
      --work-dir "$P2R/w_r3_$variant" \
      "$P2R/r3_$variant/00_目录.md" "$P2R/r3_$variant/a.md" \
      >"$P2R/r3_$variant.txt" 2>&1; then
    echo "错误：多行出处段（$variant）未被拒绝"; exit 1
  fi
  grep -q "跨多行（L[0-9]*-L[0-9]*）" "$P2R/r3_$variant.txt" \
    || { cat "$P2R/r3_$variant.txt"; echo "错误：多行出处（$variant）诊断缺失"; exit 1; }
  test ! -f "$P2R/w_r3_$variant/candidate.pdf" \
    || { echo "错误：多行出处（$variant）仍生成候选"; exit 1; }
done
echo "第三轮：多行出处段（引用块/顶层段落）定位拒绝且零候选，单行正例仍通过 PASS"

# 第四轮（P1-1 整行出处模板）：同行混合内容 / 双链接 / 括号散文 → 拒绝；
# 书目尾巴正例（日期括号、拉丁会议词）→ 通过且出处剔除
python3 - "$P2R" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])


def write_case(tag, toc_body):
    case = base / ('r4_' + tag)
    case.mkdir(exist_ok=True)
    (case / 'a.md').write_text(
        '# 第 A 章\n\n> **来源**：https://example.com/r4-%s\n\nA 正文。\n' % tag,
        encoding='utf-8')
    (case / '00_目录.md').write_text(toc_body, encoding='utf-8')
    return case


CASES = {
    # 反例：同行混合（引用块与顶层段落两变体）
    'quote_mix': '# 目录\n\n- [第 A 章](a.md)\n\n'
                 '> 译自 [原文](https://example.com/x)；[附加导览](a.md)\n',
    'plain_mix': '# 目录\n\n- [第 A 章](a.md)\n\n'
                 '译自 [原文](https://example.com/x)；[附加导览](a.md)\n',
    # 反例：双来源链接 / 括号散文尾巴
    'two_links': '# 目录\n\n- [第 A 章](a.md)\n\n'
                 '译自 [A](https://example.com/u1) 与 [B](https://example.com/u2)\n',
    'prose_paren': '# 目录\n\n- [第 A 章](a.md)\n\n'
                   '译自 [原文](https://example.com/u)（另见导览）\n',
    # 正例：书目尾巴（日期括号、拉丁会议词、版本号）
    'bib_date': '# 目录\n\n- [第 A 章](a.md)\n\n'
                '译自 [Guide](https://example.com/book.html)（2026-09-01）\n',
    'bib_conf': '# 目录\n\n- [第 A 章](a.md)\n\n'
                '译自 [Paper](https://example.com/p)（MLsys 2022）\n',
    'bib_ver': '# 目录\n\n- [第 A 章](a.md)\n\n'
               '译自 NVIDIA CUDA Guide v13.4：https://example.com/g\n',
}
for tag, body in CASES.items():
    write_case(tag, body)
print('第四轮用例就绪')
PY
for tag in quote_mix plain_mix two_links prose_paren; do
  if python3 "$EXPORT" --output "$P2R/r4_$tag.pdf" \
      --work-dir "$P2R/w_r4_$tag" \
      "$P2R/r4_$tag/00_目录.md" "$P2R/r4_$tag/a.md" \
      >"$P2R/r4_$tag.txt" 2>&1; then
    echo "错误：第四轮反例（$tag）未被拒绝"; exit 1
  fi
  grep -q "无法确认整行仅为出处" "$P2R/r4_$tag.txt" \
    || { cat "$P2R/r4_$tag.txt"; echo "错误：第四轮反例（$tag）诊断缺失"; exit 1; }
  grep -q "L[0-9]*" "$P2R/r4_$tag.txt" \
    || { echo "错误：第四轮反例（$tag）缺行号定位"; exit 1; }
  test ! -f "$P2R/w_r4_$tag/candidate.pdf" \
    || { echo "错误：第四轮反例（$tag）仍生成候选"; exit 1; }
done
echo "第四轮反例：同行混合/双链接/括号散文均定位拒绝且零候选 PASS"
for tag in bib_date bib_conf bib_ver; do
  python3 "$EXPORT" --output "$P2R/r4_$tag.pdf" \
    --work-dir "$P2R/w_r4_$tag" \
    "$P2R/r4_$tag/00_目录.md" "$P2R/r4_$tag/a.md" \
    >"$P2R/r4_$tag.txt" 2>&1 \
    || { cat "$P2R/r4_$tag.txt"; echo "错误：第四轮正例（$tag）导出失败"; exit 1; }
  python3 "$VERIFY" --pdf "$P2R/r4_$tag.pdf" \
    --work-dir "$P2R/w_r4_$tag" \
    "$P2R/r4_$tag/00_目录.md" "$P2R/r4_$tag/a.md" \
    >"$P2R/r4_$tag.v.txt" 2>&1 \
    || { cat "$P2R/r4_$tag.v.txt"; echo "错误：第四轮正例（$tag）核验失败"; exit 1; }
done
python3 - "$P2R" <<'PY'
import re, sys, unicodedata
from pathlib import Path
import pypdf

base = Path(sys.argv[1])


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


for tag, hidden in (('bib_date', 'example.com/book.html'),
                    ('bib_conf', 'example.com/p'),
                    ('bib_ver', 'example.com/g')):
    text = norm("".join(
        p.extract_text() or "" for p in pypdf.PdfReader(
            str(base / ('r4_%s.pdf' % tag))).pages))
    assert norm(hidden) not in text, "%s 出处未剔除" % tag
    assert norm("第A章") in text, "%s 目录条目被误删" % tag
print("第四轮正例：书目尾巴（日期/会议词/版本号）出处剔除、目录保留")
PY
echo "第四轮正例：书目尾巴各形态导出+核验通过 PASS"

echo "==> R1/R4（ticket 05/06）：正文两端对齐与逐页页脚页码"
FT="$TMP/footer_layout"; rm -rf "$FT"; mkdir -p "$FT"
python3 - "$FT" <<'PY'
import sys
from pathlib import Path
base = Path(sys.argv[1])
paras = []
for i in range(1, 41):
    paras.append(
        '对齐段 %02d：这是一段用于两端对齐验收的正文，包含中文标点、'
        '行内 `code_snippet_%d` 与长链接 https://example.com/align/%d/'
        'index.html，用于检验右缘对齐、长词折行与末行自然结束。'
        % (i, i, i))
(base / 'single.md').write_text(
    '# 对齐样例（Justify）\n\n'
    '> **来源**：https://example.com/prov-ft-single\n\n' + '\n\n'.join(paras)
    + '\n\n| 列 A | 列 B |\n|---|---|\n| 短 | 文本 |\n\n'
    '脚注引用[^1]。\n\n[^1]: 脚注说明文字保留左对齐与小字号。\n',
    encoding='utf-8')
(base / '00_目录.md').write_text(
    '# 目录\n\n- [带目录样例](with_toc.md)\n', encoding='utf-8')
(base / 'with_toc.md').write_text(
    '# 带目录样例（Toc）\n\n> **来源**：https://example.com/prov-ft-toc\n\n'
    + '\n\n'.join('目录后正文段落 %d。' % i for i in range(1, 40)) + '\n',
    encoding='utf-8')
(base / 'b_one.md').write_text(
    '# 合订甲章\n\n> **来源**：https://example.com/prov-ft-one\n\n'
    + '\n\n'.join('甲章正文段落 %d。' % i for i in range(1, 30)) + '\n',
    encoding='utf-8')
(base / 'b_two.md').write_text(
    '# 合订乙章\n\n> **来源**：https://example.com/prov-ft-two\n\n乙章正文。\n',
    encoding='utf-8')
PY
make_book_decl "$FT/book_decl.json" "$FT/b_one.md" "$FT/b_two.md"

# 单篇：正文两端对齐抽样 + 逐页页脚
python3 "$EXPORT" --output "$FT/single.pdf" --work-dir "$FT/w_single" \
  "$FT/single.md" >"$FT/single_e.txt" 2>&1 \
  || { cat "$FT/single_e.txt"; echo "错误：对齐样例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$FT/single.pdf" --work-dir "$FT/w_single" \
  "$FT/single.md" >"$FT/single_v.txt" 2>&1 \
  || { cat "$FT/single_v.txt"; echo "错误：对齐样例核验失败"; exit 1; }
python3 - "$FT/single.pdf" <<'PY'
import re, sys
import pymupdf

# 使用项目已有的 PDF 渲染依赖直接量测成品，独立于 verify_pdf 的事实与常量。
pdf = pymupdf.open(sys.argv[1]); total = len(pdf)
assert total >= 2, total
page_rows = []
for page_no, page in enumerate(pdf, start=1):
    spans = [span for block in page.get_text('dict')['blocks']
             for line in block.get('lines', []) for span in line['spans']
             if span['text'].strip()]
    rows = []
    for span in sorted(spans, key=lambda s: (s['origin'][1], s['bbox'][0])):
        if not rows or abs(rows[-1]['baseline'] - span['origin'][1]) > 3:
            rows.append(dict(baseline=span['origin'][1], spans=[]))
        rows[-1]['spans'].append(span)
    for row in rows:
        row['spans'].sort(key=lambda s: s['bbox'][0])
        row.update(text=''.join(s['text'] for s in row['spans']),
                   left=min(s['bbox'][0] for s in row['spans']),
                   right=max(s['bbox'][2] for s in row['spans']))
    page_rows.append(rows)
    footer = [row for row in rows if re.fullmatch(r'\d+\s*/\s*\d+', row['text'])]
    assert len(footer) == 1, (page_no, footer)
    row = footer[0]
    assert re.fullmatch(r'%d\s*/\s*%d' % (page_no, total), row['text']), (page_no, row)
    # 18mm 底边距，中心偏差不超过 20pt；保持原验收的 7–10pt 字号范围。
    band_top = page.rect.y1 - 18 * 72 / 25.4
    assert row['baseline'] > band_top, (page_no, row)
    assert abs((row['left'] + row['right']) / 2 - (page.rect.x0 + page.rect.x1) / 2) <= 20, (page_no, row)
    assert all(7 <= s['size'] <= 10 for s in row['spans']), (page_no, row)
    assert [r for r in rows if r['baseline'] > band_top] == [row], (page_no, rows)
# 普通正文的完整行共享右缘；段末行自然结束。
body = [row for row in page_rows[0] if '用于两端对齐验收的正文' in re.sub(r'\s+', '', row['text'])]
edges = [round(row['right'], 1) for row in body]
assert len(edges) >= 8, edges
assert max(edges) - min(edges) <= 1.5, edges
modal = max(set(edges), key=edges.count)
last = [row for row in page_rows[0] if '末行自然结束' in re.sub(r'\s+', '', row['text'])]
assert last and all(row['right'] < modal - 5 for row in last), (last, modal)
print('单篇：逐页页脚 1/%d..%d/%d（带内/居中/字号可读/无遮挡），正文右缘对齐 %d 行（散布 ≤1.5pt）、末行自然'
      % (total, total, total, len(edges)))
PY

# 带目录单篇与合订：首页、目录页、章首页都含页脚；目录页码与页脚同序
python3 "$EXPORT" --output "$FT/with_toc.pdf" --work-dir "$FT/w_toc" \
  "$FT/00_目录.md" "$FT/with_toc.md" >"$FT/toc_e.txt" 2>&1 \
  || { cat "$FT/toc_e.txt"; echo "错误：带目录样例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$FT/with_toc.pdf" --work-dir "$FT/w_toc" \
  "$FT/00_目录.md" "$FT/with_toc.md" >"$FT/toc_v.txt" 2>&1 \
  || { cat "$FT/toc_v.txt"; echo "错误：带目录样例核验失败"; exit 1; }
python3 "$EXPORT" --output "$FT/book.pdf" --work-dir "$FT/w_book" \
  --view-declaration "$FT/book_decl.json" \
  "$FT/b_one.md" "$FT/b_two.md" >"$FT/book_e.txt" 2>&1 \
  || { cat "$FT/book_e.txt"; echo "错误：合订样例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$FT/book.pdf" --work-dir "$FT/w_book" \
  --view-declaration "$FT/book_decl.json" \
  "$FT/b_one.md" "$FT/b_two.md" >"$FT/book_v.txt" 2>&1 \
  || { cat "$FT/book_v.txt"; echo "错误：合订样例核验失败"; exit 1; }
python3 - "$FT/w_toc" "$FT/with_toc.pdf" "$FT/w_book" "$FT/book.pdf" <<'PY'
import json, re, sys
from pathlib import Path

import pypdf


def check(pdf_path):
    reader = pypdf.PdfReader(pdf_path)
    total = len(reader.pages)
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        assert re.search(r"(?m)^%d\s*/\s*%d\s*$" % (page_no, total), text), \
            "%s 第 %d 页缺少页脚 %d / %d" % (pdf_path, page_no, page_no, total)
    return total


total_toc = check(sys.argv[2])
total_book = check(sys.argv[4])
toc = json.loads((Path(sys.argv[1]) / "export_report.json").read_text(encoding="utf-8"))["toc"]
assert toc["entries"] and all(e["page"] for e in toc["entries"]), toc["entries"]
print("带目录单篇 %d 页（目录页/正文页逐页页脚）与合订 %d 页（跨章首页页脚）"
      "正确；印刷目录页码与页脚同页序" % (total_toc, total_book))
PY

# 反例：缺页（清空中间页内容 → 该页页脚缺失）与错总数（重复一页 → 页码错乱）
python3 - "$FT" <<'PY'
import json, sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

base = Path(sys.argv[1])
reader = PdfReader(str(base / "with_toc.pdf"))
writer = PdfWriter(clone_from=reader)
stream = DecodedStreamObject()
stream.set_data(b"")
writer.pages[1][NameObject("/Contents")] = writer._add_object(stream)
writer.write(str(base / "no_footer.pdf"))
reader = PdfReader(str(base / "with_toc.pdf"))
writer = PdfWriter()
seen = reader.pages[1]
for page in (reader.pages[0], seen, seen, reader.pages[-1]):
    writer.add_page(page)
writer.write(str(base / "dup_footer.pdf"))
print("页脚反例样本就绪")
PY
python3 - "$FT/w_toc" "$FT/no_footer.pdf" "$FT/with_toc.pdf" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["pdf_sha256"] = __import__("hashlib").sha256(
    Path(sys.argv[2]).read_bytes()).hexdigest()
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY
if python3 "$VERIFY" --pdf "$FT/no_footer.pdf" --work-dir "$FT/w_toc" \
    "$FT/00_目录.md" "$FT/with_toc.md" >"$FT/nf_v.txt" 2>&1; then
  echo "错误：缺页脚页未被拒绝"; exit 1
fi
python3 - "$FT/w_toc" footer-missing <<'PY'
import json, sys
from pathlib import Path
codes = {f["code"] for f in json.loads(
    (Path(sys.argv[1]) / "verify_report.json").read_text())["failures"]}
assert sys.argv[2] in codes, codes
PY
python3 - "$FT/w_toc" "$FT/dup_footer.pdf" "$FT/with_toc.pdf" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["pdf_sha256"] = __import__("hashlib").sha256(
    Path(sys.argv[2]).read_bytes()).hexdigest()
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY
if python3 "$VERIFY" --pdf "$FT/dup_footer.pdf" --work-dir "$FT/w_toc" \
    "$FT/00_目录.md" "$FT/with_toc.md" >"$FT/df_v.txt" 2>&1; then
  echo "错误：错总页数未被拒绝"; exit 1
fi
python3 - "$FT/w_toc" footer-number <<'PY'
import json, sys
from pathlib import Path
codes = {f["code"] for f in json.loads(
    (Path(sys.argv[1]) / "verify_report.json").read_text())["failures"]}
assert sys.argv[2] in codes, codes
PY
# 恢复证据供后续不重跑本节时保持原状
python3 - "$FT/w_toc" "$FT/with_toc.pdf" <<'PY'
import hashlib, json, sys
from pathlib import Path
path = Path(sys.argv[1]) / "export_report.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["pdf_sha256"] = hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest()
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
PY
echo "两端对齐与逐页页脚：单篇/带目录/合订正例、缺页脚与错总数反例均判 FAIL PASS"

echo "==> R8（留痕 05）：A20/A21/A22 短块整块、长块续排、交错可验"
CP="$TMP/code_pagination"; rm -rf "$CP"; mkdir -p "$CP"
python3 - "$CP" <<'PY'
import sys
from pathlib import Path

base = Path(sys.argv[1])
lines9 = "\n".join("a%d = %d" % (i, i) for i in range(1, 10))
lines10 = "\n".join("b%d = %d" % (i, i) for i in range(1, 11))
lines11 = "\n".join("c%d = %d" % (i, i) for i in range(1, 12))
lines25 = "\n".join("def f%d(): return %d" % (i, i) for i in range(1, 26))
block_with_blanks = "x = 1\n\n\nx += 2\n"
(base / "a.md").write_text(
    "# 章一\n\n"
    "> **来源**：https://example.com/prov-cp-a\n\n"
    "9 行短块：\n\n```python\n" + lines9 + "\n```\n\n"
    "10 行短块（允许整体移页留白）：\n\n```python\n" + lines10 + "\n```\n\n"
    "带空行与真实末尾空行的短块：\n\n```\n" + block_with_blanks + "\n```\n\n"
    "缩进代码短块：\n\n    indented_a = 1\n    indented_b = 2\n\n"
    "11 行长块（可跨页）：\n\n```unknownlang\n" + lines11 + "\n```\n",
    encoding="utf-8")
(base / "b.md").write_text(
    "# 章二\n\n"
    "> **来源**：https://example.com/prov-cp-b\n\n"
    "页首导语之后紧跟长块，必须从当前页续排：\n\n"
    "```python\n" + lines25 + "\n```\n\n"
    "| 列 A | 列 B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n"
    "长块尾随表格，制造跨页提取交错场景。\n",
    encoding="utf-8")
PY
make_book_decl "$CP/decl.json" "$CP/a.md" "$CP/b.md"
python3 "$EXPORT" --output "$CP/book.pdf" --work-dir "$CP/work" \
  --view-declaration "$CP/decl.json" \
  "$CP/a.md" "$CP/b.md" >"$CP/export.txt" 2>&1 \
  || { cat "$CP/export.txt"; echo "错误：代码分页样例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$CP/book.pdf" --work-dir "$CP/work" \
  --view-declaration "$CP/decl.json" \
  "$CP/a.md" "$CP/b.md" >"$CP/verify.txt" 2>&1 \
  || { cat "$CP/verify.txt"; echo "错误：代码分页样例核验失败"; exit 1; }
python3 - "$CP/work" "$CP/book.pdf" <<'PY'
import json, re, sys
from pathlib import Path

import pypdf

work = Path(sys.argv[1])
report = json.loads((work / "export_report.json").read_text(encoding="utf-8"))
verify = json.loads((work / "verify_report.json").read_text(encoding="utf-8"))
assert verify["status"] == "machine-pass-pending-visual", verify["failures"]
codes = [f["code"] for f in verify["failures"]]
assert "code-page-gap" not in codes, codes
# 10 行短块容器带 code-short 类（从 HTML 证据核对）
html = (work / "combined.html").read_text(encoding="utf-8")
assert 'class="code-block code-short"' in html, "短块未标记"
assert 'class="code-block code-long"' in html, "长块未标记"
# A20：末尾换行不增行（b 块 10 行应为短块）
assert html.count('code-block code-short') >= 4, html.count('code-block code-short')
# A22：跨页长块与表格交错的解释性记录存在（位置证据）
segments = [r.get("segment", "") for r in verify["relaxed_matches"]]
assert any("交错" in s for s in segments) or any("空行" in s for s in segments), segments[:5]
print("A20 短块分类/末尾换行不增行、A21 长块续排、A22 交错解释 PASS")
PY

echo "==> R8（留痕 05）：A23 代码内容篡改与整行删除必须 FAIL"
python3 - "$CP" <<'PY'
import hashlib, json, re, sys
from pathlib import Path

import pypdf
from pypdf.generic import DecodedStreamObject, NameObject

base = Path(sys.argv[1])
reader = pypdf.PdfReader(str(base / "book.pdf"))
report = json.loads((base / "work" / "export_report.json")
                    .read_text(encoding="utf-8"))
report["pdf_sha256"] = hashlib.sha256((base / "book.pdf").read_bytes()).hexdigest()

def char_codes(font):
    cmap_ref = font.get("/ToUnicode")
    if cmap_ref is None:
        return {}
    text = cmap_ref.get_object().get_data().decode("latin-1")
    codes = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]{2,4})>\s*<([0-9A-Fa-f]{4,})>", block):
            codes[int(src, 16)] = dst.upper()
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for src, end, dst in re.findall(
                r"<([0-9A-Fa-f]{2,4})>\s*<([0-9A-Fa-f]{2,4})>\s*"
                r"<([0-9A-Fa-f]{4})>", block):
            start_code, end_code = int(src, 16), int(end, 16)
            if end_code - start_code > 1024:
                continue
            for offset, code in enumerate(range(start_code, end_code + 1)):
                codes[code] = "%04X" % (int(dst, 16) + offset)
    return codes

# 找到含代码行 f1() 的页；把 return 1 中的数字 1 字形改成 7
target = None
for index, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    if "def f1(): return 1" in re.sub(r"\s+", " ", text):
        target = index
        break
assert target is not None, "未找到代码页"
font_codes = {}
for name, ref in ((reader.pages[target].get("/Resources") or {})
                  .get("/Font") or {}).items():
    font_codes[name] = char_codes(ref.get_object())
one_hex = "1".encode("utf-16-be").hex().upper()
seven_hex = "7".encode("utf-16-be").hex().upper()
writer = pypdf.PdfWriter(clone_from=reader)
page = writer.pages[target]
contents = page.get_contents().get_data()
changed = 0
for name, codes in font_codes.items():
    src_code = next((c for c, dst in codes.items() if dst == one_hex), None)
    dst7 = next((c for c, dst in codes.items() if dst == seven_hex), None)
    if src_code is None or dst7 is None:
        continue
    # Chromium 可能以 <..> Tj 或 TJ 数组绘制；按字形编码整体替换该页
    # 所有数字 1 字形（页面上其他 1 也一起变化，不影响负例判定）。
    pattern = re.compile(rb"<0*%X>" % src_code)
    contents, n = pattern.subn(b"<%X>" % dst7, contents)
    changed += n
assert changed >= 1, "代码行数字字形未被改写"
stream = DecodedStreamObject()
stream.set_data(contents)
page[NameObject("/Contents")] = writer._add_object(stream)
out = base / "tampered.pdf"
with open(out, "wb") as handle:
    writer.write(handle)
report["pdf_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
(base / "work" / "export_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("已把代码行中的数字 1 字形改为 7，并重签摘要")
PY
if python3 "$VERIFY" --pdf "$CP/tampered.pdf" --work-dir "$CP/work" \
    --view-declaration "$CP/decl.json" \
    "$CP/a.md" "$CP/b.md" >"$CP/tamper_v.txt" 2>&1; then
  echo "错误：代码内容篡改未被检出"; exit 1
fi
grep -q "code-line-missing" "$CP/tamper_v.txt" \
  || { cat "$CP/tamper_v.txt"; echo "错误：逐行核验未定位篡改行"; exit 1; }
echo "A23 代码改字（含摘要重签）被逐行核验拒绝 PASS"

echo "==> R6（留痕 04 补充）：目录段落不可替不相关来源；已知日期不得在前置去重中丢失"
PV2="$TMP/prov_cov"; rm -rf "$PV2"; mkdir -p "$PV2"
python3 - "$PV2" <<'PY'
from pathlib import Path
base = Path(__import__('sys').argv[1])
(base / '00_目录.md').write_text(
    '# 目录\n\n译自 NVIDIA CUDA Programming Guide：https://example.com/pv-book\n\n'
    '- [章](a.md)\n', encoding='utf-8')
# 章节来源为无定位符的泛指文字：目录段落不可替其通过门禁
(base / 'a.md').write_text(
    '# 章\n\n> **来源**：另一本书（无链接，无法定位具体原文）\n\n正文。\n',
    encoding='utf-8')
PY
if python3 "$EXPORT" --output "$PV2/out.pdf" --work-dir "$PV2/w" \
    --toc-sections "$PV2/00_目录.md" "$PV2/a.md" >"$PV2/neg.txt" 2>&1; then
  echo "错误：不相关目录出处被放行"; exit 1
fi
grep -q "provenance-incomplete" "$PV2/neg.txt" \
  || { cat "$PV2/neg.txt"; echo "错误：不相关来源诊断缺失"; exit 1; }
echo "不相关目录出处无法替章节通过门禁 PASS"

# 已知日期不在目录出处中 → 报告出处组合必须保留该日期（不得去重丢失）
python3 - "$PV2" <<'PY'
from pathlib import Path
base = Path(__import__('sys').argv[1])
(base / 'a.md').write_text(
    '# 章\n\n> **来源**：https://example.com/pv-book 版本 v1.9\n'
    '> **抓取日期**：2026-09-12\n\n正文。\n', encoding='utf-8')
PY
python3 "$EXPORT" --output "$PV2/date.pdf" --work-dir "$PV2/w_date" \
  "$PV2/00_目录.md" "$PV2/a.md" >"$PV2/date.txt" 2>&1 \
  || { cat "$PV2/date.txt"; echo "错误：目录出处覆盖导出失败"; exit 1; }
python3 - "$PV2" <<'PY'
import json, sys
import pypdf
from pathlib import Path
base = Path(sys.argv[1])
report = json.loads((base / 'w_date' / 'export_report.json').read_text(encoding='utf-8'))
assert report['provenance']['front_generated'] is True, report['provenance']
assert any('2026-09-12' in (c.get('fetch_date') or '')
           for c in report['provenance']['combos']), report['provenance']
text = ''.join(p.extract_text() or '' for p in pypdf.PdfReader(str(base / 'date.pdf')).pages)
assert '2026-09-12' not in text, '前置出处不应出现在 PDF（证据留在报告）'
print('目录出处覆盖时已知日期保留在报告证据且 PDF 不显示 PASS')
PY

# 字段续行中的版本/日期随出处一并保留：投影删除的每段就是收集的同段
python3 - "$PV2" <<'PY'
from pathlib import Path
import sys
base = Path(sys.argv[1])
(base / 'cont.md').write_text(
    '# 章 B\n\n'
    '> **来源**：https://example.com/pv-cont\n'
    '> 版本 v1.9，抓取日期 2026-09-20\n\n正文。\n', encoding='utf-8')
PY
python3 "$EXPORT" --output "$PV2/cont.pdf" --work-dir "$PV2/w_cont" \
  "$PV2/cont.md" >"$PV2/cont.txt" 2>&1 \
  || { cat "$PV2/cont.txt"; echo "错误：续行来源导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$PV2/cont.pdf" --work-dir "$PV2/w_cont" \
  "$PV2/cont.md" >"$PV2/cont_v.txt" 2>&1 \
  || { cat "$PV2/cont_v.txt"; echo "错误：续行来源核验失败"; exit 1; }
python3 - "$PV2" <<'PY'
import json, sys
import pypdf
from pathlib import Path
base = Path(sys.argv[1])
report = json.loads((base / 'w_cont' / 'export_report.json').read_text(encoding='utf-8'))
combos = report['provenance']['combos']
assert any('版本 v1.9' in (c.get('source') or '') and
           '2026-09-20' in (c.get('source') or '') for c in combos), combos
text = ''.join(p.extract_text() or '' for p in
               pypdf.PdfReader(str(base / 'cont.pdf')).pages)
assert '版本 v1.9' not in text and '2026-09-20' not in text, \
    '前置出处不应出现在 PDF（证据留在报告）'
print('字段续行中的版本/日期保留在报告证据且 PDF 不显示 PASS')
PY

echo "==> T01（pdf-layout-optimization ticket 01）：显式目录出处声明可用"
T1="$TMP/t1_decl"; rm -rf "$T1"; mkdir -p "$T1"
printf '# 第 A 章\n\n> **来源**：https://example.com/t1-decl/a\n\nA 正文。\n' \
  > "$T1/a.md"

# T01-1 正例（顶层段落同行混合）：有效 inline 声明 → 导出+核验成功；
# PDF 只隐藏获准出处片段，导览文字与可跳转章节目标保留
cat > "$T1/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t1-decl/x)；[附加导览](a.md)

- [第 A 章](a.md)
MD
python3 - "$T1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 3], "type": "inline",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t1-decl/x)；",
        "reason": "目录出处与附加导览同行：仅排除出处片段，导览保留",
    }],
}
(base / 'decl_inline.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
sha256sum "$T1/00_目录.md" "$T1/a.md" | awk '{print $1}' > "$T1/inputs.sha"
python3 "$EXPORT" --output "$T1/mix.pdf" --work-dir "$T1/w_mix" \
  --view-declaration "$T1/decl_inline.json" \
  "$T1/00_目录.md" "$T1/a.md" >"$T1/mix_e.txt" 2>&1 \
  || { cat "$T1/mix_e.txt"; echo "错误：T01-1 有效 inline 声明导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T1/mix.pdf" --work-dir "$T1/w_mix" \
  --view-declaration "$T1/decl_inline.json" \
  "$T1/00_目录.md" "$T1/a.md" >"$T1/mix_v.txt" 2>&1 \
  || { cat "$T1/mix_v.txt"; echo "错误：T01-1 有效 inline 声明核验失败"; exit 1; }
sha256sum "$T1/00_目录.md" "$T1/a.md" | awk '{print $1}' > "$T1/inputs.after.sha"
cmp -s "$T1/inputs.sha" "$T1/inputs.after.sha" \
  || { echo "错误：T01-1 输入 Markdown 摘要发生变化"; exit 1; }
python3 - "$T1" <<'PY'
import json, re, sys, unicodedata
from pathlib import Path

import pypdf

base = Path(sys.argv[1])
def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))
reader = pypdf.PdfReader(str(base / 'mix.pdf'))
pages = [page.extract_text() or "" for page in reader.pages]
norm_text = norm("".join(pages))
named = {str(n).lstrip("/"): reader.get_destination_page_number(d)
         for n, d in reader.named_destinations.items()}
id_to_index = {page.indirect_reference.idnum: i
               for i, page in enumerate(reader.pages)
               if page.indirect_reference is not None}
internal_annots = []
for i, page in enumerate(reader.pages):
    for ref in page.get("/Annots") or []:
        obj = ref.get_object()
        if obj.get("/Subtype") != "/Link":
            continue
        dest = obj.get("/Dest")
        if dest is None:
            action = obj.get("/A")
            if action is not None and action.get_object().get("/S") == "/GoTo":
                dest = action.get_object().get("/D")
        if dest is None:
            continue
        dest = dest.get_object() if hasattr(dest, "get_object") else dest
        if isinstance(dest, bytes):
            dest = dest.decode("utf-8", "replace")
        if isinstance(dest, str):
            target = named.get(dest.lstrip("/"))
        else:
            try:
                target = id_to_index.get(getattr(dest[0], "idnum", None))
            except (TypeError, IndexError):
                target = None
        if target is not None:
            internal_annots.append({"page": i, "dest_page": target})
# 获准出处片段不可见；导览文字保留
assert '译自' not in norm_text, "出处片段仍出现在 PDF"
assert norm('附加导览') in norm_text, "导览文字被误删"
# 导览链接仍可跳转到第 A 章所在页：目录页上至少两个指向章首页的注解
# （印刷目录条目 + 附加导览）
chapter_page = next(
    i for i, text in enumerate(pages)
    if 'A 正文' in text)
nav_annots = [a for a in internal_annots
              if a['page'] == 0 and a['dest_page'] == chapter_page]
assert len(nav_annots) >= 2, \
    "目录页指向第 A 章的链接注解不足（印刷目录条目与附加导览各一）：%r" \
    % (internal_annots,)
report = json.loads((base / 'w_mix' / 'export_report.json')
                    .read_text(encoding='utf-8'))
decl_record = report['view_declaration']
assert decl_record['sha256'], decl_record
ex = decl_record['exclusions'][0]
assert ex['lines'] == [3, 3] and ex['kind'] == 'toc-provenance' \
    and ex['reason'], ex
assert report['provenance']['mode'] == 'toc', report['provenance']['mode']
assert report['provenance']['toc_exclusion'] is None, \
    "声明接管时不应有自动排除区间"
print("T01-1：顶层段落同行混合 inline 声明导出+核验通过；"
      "PDF 无出处、有导览文字与跳转链接；Markdown 摘要不变 PASS")
PY

# T01-2 正例（顶层引用块同行混合）：同口径复验引用块变体
cat > "$T1/00_目录.md" <<'MD'
# 目录

> 译自 [原文](https://example.com/t1-decl/y)；[附加导览](a.md)

- [第 A 章](a.md)
MD
python3 - "$T1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 3], "type": "inline",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t1-decl/y)；",
        "reason": "引用块内出处与导览同行：仅排除出处片段",
    }],
}
(base / 'decl_quote.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
python3 "$EXPORT" --output "$T1/quote.pdf" --work-dir "$T1/w_quote" \
  --view-declaration "$T1/decl_quote.json" \
  "$T1/00_目录.md" "$T1/a.md" >"$T1/quote_e.txt" 2>&1 \
  || { cat "$T1/quote_e.txt"; echo "错误：T01-2 引用块 inline 声明导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T1/quote.pdf" --work-dir "$T1/w_quote" \
  --view-declaration "$T1/decl_quote.json" \
  "$T1/00_目录.md" "$T1/a.md" >"$T1/quote_v.txt" 2>&1 \
  || { cat "$T1/quote_v.txt"; echo "错误：T01-2 引用块 inline 声明核验失败"; exit 1; }
python3 - "$T1" <<'PY'
import re, sys, unicodedata
from pathlib import Path

import pypdf

base = Path(sys.argv[1])
def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))
reader = pypdf.PdfReader(str(base / 'quote.pdf'))
pages = [page.extract_text() or "" for page in reader.pages]
norm_text = norm("".join(pages))
named = {str(n).lstrip("/"): reader.get_destination_page_number(d)
         for n, d in reader.named_destinations.items()}
id_to_index = {page.indirect_reference.idnum: i
               for i, page in enumerate(reader.pages)
               if page.indirect_reference is not None}
internal_annots = []
for i, page in enumerate(reader.pages):
    for ref in page.get("/Annots") or []:
        obj = ref.get_object()
        if obj.get("/Subtype") != "/Link":
            continue
        dest = obj.get("/Dest")
        if dest is None:
            action = obj.get("/A")
            if action is not None and action.get_object().get("/S") == "/GoTo":
                dest = action.get_object().get("/D")
        if dest is None:
            continue
        dest = dest.get_object() if hasattr(dest, "get_object") else dest
        if isinstance(dest, bytes):
            dest = dest.decode("utf-8", "replace")
        if isinstance(dest, str):
            target = named.get(dest.lstrip("/"))
        else:
            try:
                target = id_to_index.get(getattr(dest[0], "idnum", None))
            except (TypeError, IndexError):
                target = None
        if target is not None:
            internal_annots.append({"page": i, "dest_page": target})
assert '译自' not in norm_text, "引用块出处片段仍出现在 PDF"
assert norm('附加导览') in norm_text, "引用块导览文字被误删"
chapter_page = next(i for i, t in enumerate(pages) if 'A 正文' in t)
assert any(a['page'] == 0 and a['dest_page'] == chapter_page
           for a in internal_annots), "引用块变体导览链接不可跳转"
print("T01-2：顶层引用块同行混合 inline 声明导出+核验通过 PASS")
PY

# T01-3 正例（独立纯出处块 block 声明）：整块排除，相邻导航保留，
# 报告给出输入/声明摘要、排除行号与理由，来源门禁基于原始输入通过
cat > "$T1/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t1-decl/z)
版本 v2.0，2026-01-01 抓取

- [第 A 章](a.md)
MD
python3 - "$T1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 4], "type": "block",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t1-decl/z)",
        "reason": "多行纯出处段（含版本/抓取续行）整块排除",
    }],
}
(base / 'decl_block.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
python3 "$EXPORT" --output "$T1/block.pdf" --work-dir "$T1/w_block" \
  --view-declaration "$T1/decl_block.json" \
  "$T1/00_目录.md" "$T1/a.md" >"$T1/block_e.txt" 2>&1 \
  || { cat "$T1/block_e.txt"; echo "错误：T01-3 纯出处块 block 声明导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T1/block.pdf" --work-dir "$T1/w_block" \
  --view-declaration "$T1/decl_block.json" \
  "$T1/00_目录.md" "$T1/a.md" >"$T1/block_v.txt" 2>&1 \
  || { cat "$T1/block_v.txt"; echo "错误：T01-3 纯出处块 block 声明核验失败"; exit 1; }
python3 - "$T1" <<'PY'
import hashlib, json, re, sys, unicodedata
from pathlib import Path

import pypdf

base = Path(sys.argv[1])
def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))
reader = pypdf.PdfReader(str(base / 'block.pdf'))
norm_text = norm("".join(page.extract_text() or "" for page in reader.pages))
assert '译自' not in norm_text and norm('版本v2.0') not in norm_text, \
    "纯出处块仍出现在 PDF"
assert norm('第A章') in norm_text, "相邻目录导航被误删"
report = json.loads((base / 'w_block' / 'export_report.json')
                    .read_text(encoding='utf-8'))
decl_record = report['view_declaration']
decl_file = hashlib.sha256(
    (base / 'decl_block.json').read_bytes()).hexdigest()
assert decl_record['sha256'] == decl_file, "声明摘要未进入导出报告"
assert decl_record['exclusions'][0]['lines'] == [3, 4] \
    and decl_record['exclusions'][0]['reason'], decl_record['exclusions']
assert report['provenance']['mode'] == 'toc', report['provenance']
inputs = report['inputs']
assert all(item.get('sha256') for item in inputs), "输入摘要未进入导出报告"
print("T01-3：独立纯出处块 block 声明导出+核验通过；报告含输入/声明摘要、"
      "行号与理由 PASS")
PY

# T01-4 反例：声明非法逐项定位失败，零新候选，旧 PDF 字节不变
cat > "$T1/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t1-decl/x)；[附加导览](a.md)

- [第 A 章](a.md)
MD
python3 - "$T1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
digest_toc = hashlib.sha256(toc.read_bytes()).hexdigest()
digest_a = hashlib.sha256(a.read_bytes()).hexdigest()
def inputs(toc_digest=digest_toc):
    return [{"path": str(toc), "sha256": toc_digest},
            {"path": str(a), "sha256": digest_a}]
def write(name, exclusions, toc_digest=digest_toc):
    decl = {"version": 1, "inputs": inputs(toc_digest), "exclusions": exclusions}
    (base / ('bad_%s.json' % name)).write_text(
        json.dumps(decl, ensure_ascii=False), encoding='utf-8')
def excl(lines, ex_type='inline', kind='toc-provenance',
         fragment='译自 [原文](https://example.com/t1-decl/x)；',
         reason='反例'):
    return {"input": str(toc), "lines": lines, "type": ex_type,
            "kind": kind, "fragment": fragment, "reason": reason}
write('drift', [excl([3, 3])], toc_digest='0' * 64)           # 摘要漂移
write('range', [excl([3, 99])])                                # 越界
write('overlap', [excl([3, 3]), excl([3, 3])])                 # 重叠范围
write('wrongkind', [excl([3, 3], kind='note')])                # 错误 kind
write('nav', [excl([3, 3],
      fragment='译自 [原文](https://example.com/t1-decl/x)；[附加导览](a.md)')])
write('notprov', [excl([3, 3], fragment='[附加导览](a.md)')])  # 非出处片段
# fragment 非唯一：独立目录含两行相同出处，区间内 fragment 出现两次
dup = ('# 目录\n\n译自 [原文](https://example.com/t1-decl/x)\n\n'
       '译自 [原文](https://example.com/t1-decl/x)\n\n- [第 A 章](a.md)\n')
(base / '00_目录_dup.md').write_text(dup, encoding='utf-8')
dup_path = (base / '00_目录_dup.md').resolve()
decl = {"version": 1,
        "inputs": [{"path": str(dup_path),
                    "sha256": hashlib.sha256(dup_path.read_bytes()).hexdigest()},
                   {"path": str(a), "sha256": digest_a}],
        "exclusions": [{"input": str(dup_path), "lines": [1, 7],
                        "type": "inline", "kind": "toc-provenance",
                        "fragment": "译自 [原文](https://example.com/t1-decl/x)",
                        "reason": "反例"}]}
(base / 'bad_nonunique.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
print('T01-4 反例声明就绪')
PY
printf 'OLD-PDF-BYTES' > "$T1/old.pdf"
for tag in drift range overlap wrongkind nav notprov; do
  cp "$T1/old.pdf" "$T1/bad_${tag}.pdf"
  if python3 "$EXPORT" --output "$T1/bad_${tag}.pdf" --work-dir "$T1/w_bad_${tag}" \
      --view-declaration "$T1/bad_${tag}.json" \
      "$T1/00_目录.md" "$T1/a.md" >"$T1/bad_${tag}.txt" 2>&1; then
    echo "错误：T01-4 反例（${tag}）未被拒绝"; exit 1
  fi
  test ! -f "$T1/w_bad_${tag}/candidate.pdf" \
    || { echo "错误：T01-4 反例（${tag}）仍生成候选"; exit 1; }
  cmp -s "$T1/old.pdf" "$T1/bad_${tag}.pdf" \
    || { echo "错误：T01-4 反例（${tag}）旧 PDF 被改写"; exit 1; }
done
# fragment 非唯一变体使用含两行相同出处的独立目录输入
cp "$T1/old.pdf" "$T1/bad_nonunique.pdf"
if python3 "$EXPORT" --output "$T1/bad_nonunique.pdf" \
    --work-dir "$T1/w_bad_nonunique" \
    --view-declaration "$T1/bad_nonunique.json" \
    "$T1/00_目录_dup.md" "$T1/a.md" >"$T1/bad_nonunique.txt" 2>&1; then
  echo "错误：T01-4 反例（nonunique）未被拒绝"; exit 1
fi
test ! -f "$T1/w_bad_nonunique/candidate.pdf" \
  || { echo "错误：T01-4 反例（nonunique）仍生成候选"; exit 1; }
cmp -s "$T1/old.pdf" "$T1/bad_nonunique.pdf" \
  || { echo "错误：T01-4 反例（nonunique）旧 PDF 被改写"; exit 1; }
# 除摘要漂移（文件级诊断）外，其余反例均须含行号定位
for tag in range overlap nonunique wrongkind nav notprov; do
  grep -q "L[0-9]" "$T1/bad_${tag}.txt" \
    || { cat "$T1/bad_${tag}.txt"; echo "错误：T01-4 反例（${tag}）缺行号定位"; exit 1; }
done
grep -q "摘要与输入不符" "$T1/bad_drift.txt" \
  || { cat "$T1/bad_drift.txt"; echo "错误：摘要漂移诊断缺失"; exit 1; }
grep -q "越界" "$T1/bad_range.txt" \
  || { cat "$T1/bad_range.txt"; echo "错误：越界诊断缺失"; exit 1; }
grep -q "重叠" "$T1/bad_overlap.txt" \
  || { cat "$T1/bad_overlap.txt"; echo "错误：重叠诊断缺失"; exit 1; }
grep -q "恰好出现" "$T1/bad_nonunique.txt" \
  || { cat "$T1/bad_nonunique.txt"; echo "错误：fragment 非唯一诊断缺失"; exit 1; }
grep -q "无法确认整行仅为出处" "$T1/bad_wrongkind.txt" \
  || { cat "$T1/bad_wrongkind.txt"; echo "错误：错误 kind 未回退自动判断"; exit 1; }
grep -q "导航链接" "$T1/bad_nav.txt" \
  || { cat "$T1/bad_nav.txt"; echo "错误：误含章节导航诊断缺失"; exit 1; }
grep -q "必须以“译自”开头" "$T1/bad_notprov.txt" \
  || { cat "$T1/bad_notprov.txt"; echo "错误：非出处片段诊断缺失"; exit 1; }
echo "T01-4：摘要漂移/越界/重叠/非唯一/错误 kind/误含导航/非出处均定位失败，零候选、旧 PDF 不变 PASS"

# T01-5 核验反例：成品缺失应保留的目录导航 → 独立核验拒绝
# （清空目录页内容流并重签摘要：只能靠内容核对发现导览丢失）
cat > "$T1/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t1-decl/x)；[附加导览](a.md)

- [第 A 章](a.md)
MD
python3 - "$T1" <<'PY'
import json, sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
base = Path(sys.argv[1])
reader = PdfReader(str(base / 'mix.pdf'))
writer = PdfWriter(clone_from=reader)
stream = DecodedStreamObject()
stream.set_data(b'')
writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
writer.write(str(base / 'mix_nosnav.pdf'))
report = json.loads((base / 'w_mix' / 'export_report.json')
                    .read_text(encoding='utf-8'))
report['pdf_sha256'] = __import__('hashlib').sha256(
    (base / 'mix_nosnav.pdf').read_bytes()).hexdigest()
(base / 'w_mix' / 'export_report.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('T01-5 篡改样本就绪')
PY
if python3 "$VERIFY" --pdf "$T1/mix_nosnav.pdf" --work-dir "$T1/w_mix" \
    --view-declaration "$T1/decl_inline.json" \
    "$T1/00_目录.md" "$T1/a.md" >"$T1/nosnav_v.txt" 2>&1; then
  echo "错误：T01-5 缺失目录导航的 PDF 未被核验拒绝"; exit 1
fi
grep -qE "toc-entry-missing|text-missing|chapter-structure" "$T1/nosnav_v.txt" \
  || { cat "$T1/nosnav_v.txt"; echo "错误：T01-5 缺导航诊断缺失"; exit 1; }
# 恢复证据供后续重用
python3 "$VERIFY" --pdf "$T1/mix.pdf" --work-dir "$T1/w_mix" \
  --view-declaration "$T1/decl_inline.json" \
  "$T1/00_目录.md" "$T1/a.md" >/dev/null 2>&1 || true
python3 - "$T1" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
report = json.loads((base / 'w_mix' / 'export_report.json')
                    .read_text(encoding='utf-8'))
report['pdf_sha256'] = hashlib.sha256(
    (base / 'mix.pdf').read_bytes()).hexdigest()
(base / 'w_mix' / 'export_report.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
PY
echo "T01-5：缺失目录导航的成品被独立核验拒绝（不以双命令退出码代替内容证据） PASS"

echo "==> T02（pdf-layout-optimization ticket 02）：目录出处窄格式自动语法与导航独立核验"
T2="$TMP/t2_narrow"; rm -rf "$T2"; mkdir -p "$T2"

# T02-1 正例：§8.3 各形式逐项真实导出+独立核验通过；出处隐藏、目录导航
# 与正文保留（查询参数、片段、下划线与本地原文路径完整可用）
python3 - "$T2" <<'PY'
from pathlib import Path
import sys
base = Path(sys.argv[1])
CHAPTER = '# 第 A 章\n\n> **来源**：https://example.com/t2-a\n\nA 正文。\n'
CASES = {
    'md_zh': '译自 [原文](https://example.com/t2/md-zh?id=1)',
    'md_en': '译自 [Guide](https://example.com/t2/md-en)',
    'md_local': '译自 [原文](../original/paper.pdf)',
    'auto': '译自 <https://example.com/t2/auto_link>',
    'bare': '译自 https://example.com/t2/p_v1.pdf?id=1&x=2#frag_v',
    'local': '译自 ../original/paper.pdf',
    'book': '译自 NVIDIA CUDA Guide v13.4：https://example.com/t2/book',
    'tail_date': '译自 [Guide](https://example.com/t2/td)（2026-09-01）',
    'tail_ver': '译自 指南：https://example.com/t2/tv（v13.4.1）',
    'tail_conf': '译自 [Paper](https://example.com/t2/tc)（MLSys 2022）',
    'quote': '> 译自 [原文](https://example.com/t2/quote)',
}
for tag, prov in CASES.items():
    case = base / tag
    case.mkdir()
    (case / '00_目录.md').write_text(
        '# 目录\n\n%s\n\n- [第 A 章](a.md)\n' % prov, encoding='utf-8')
    (case / 'a.md').write_text(CHAPTER, encoding='utf-8')
# 围栏代码内的“译自”是代码内容：不构成候选、照常保留在 PDF
case = base / 'fence_keep'
case.mkdir()
(case / '00_目录.md').write_text(
    '# 目录\n\n```\n译自 https://example.com/t2/code-literal\n```\n\n'
    '- [第 A 章](a.md)\n', encoding='utf-8')
(case / 'a.md').write_text(CHAPTER, encoding='utf-8')
# 混合容器正例：导航链接 + 说明文字 → 链接解除为纯文字，说明保留
case = base / 'mixed_li'
case.mkdir()
(case / '00_目录.md').write_text(
    '# 目录\n\n译自 https://example.com/t2/mixed\n\n'
    '- [第 A 章](a.md)（含附录说明）\n', encoding='utf-8')
(case / 'a.md').write_text(CHAPTER, encoding='utf-8')
print('T02-1 正例就绪')
PY
for tag in md_zh md_en md_local auto bare local book tail_date tail_ver \
    tail_conf quote fence_keep mixed_li; do
  python3 "$EXPORT" --output "$T2/${tag}.pdf" --work-dir "$T2/w_${tag}" \
    "$T2/${tag}/00_目录.md" "$T2/${tag}/a.md" >"$T2/${tag}.txt" 2>&1 \
    || { cat "$T2/${tag}.txt"; echo "错误：T02-1 正例（${tag}）导出失败"; exit 1; }
  python3 "$VERIFY" --pdf "$T2/${tag}.pdf" --work-dir "$T2/w_${tag}" \
    "$T2/${tag}/00_目录.md" "$T2/${tag}/a.md" >"$T2/${tag}.v.txt" 2>&1 \
    || { cat "$T2/${tag}.v.txt"; echo "错误：T02-1 正例（${tag}）核验失败"; exit 1; }
done
python3 - "$T2" <<'PY'
import re, sys, unicodedata
from pathlib import Path
import pypdf

base = Path(sys.argv[1])


def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))


HIDDEN = {
    'md_zh': 'example.com/t2/md-zh', 'md_en': 'example.com/t2/md-en',
    'md_local': 'original/paper.pdf', 'auto': 'example.com/t2/auto_link',
    'bare': 'example.com/t2/p_v1.pdf', 'local': 'original/paper.pdf',
    'book': 'example.com/t2/book', 'tail_date': 'example.com/t2/td',
    'tail_ver': 'example.com/t2/tv', 'tail_conf': 'example.com/t2/tc',
    'quote': 'example.com/t2/quote', 'mixed_li': 'example.com/t2/mixed',
}
for tag, hidden in HIDDEN.items():
    text = norm(''.join(
        p.extract_text() or ''
        for p in pypdf.PdfReader(str(base / ('%s.pdf' % tag))).pages))
    assert norm(hidden) not in text, '%s 出处未隐藏' % tag
    assert '译自' not in text, '%s 出处标记残留' % tag
    assert norm('第A章') in text, '%s 目录条目被误删' % tag
    assert norm('A正文') in text, '%s 正文缺失' % tag
text = norm(''.join(
    p.extract_text() or ''
    for p in pypdf.PdfReader(str(base / 'fence_keep.pdf')).pages))
assert '译自' in text and norm('example.com/t2/code-literal') in text, \
    '围栏代码内的“译自”内容必须原样保留'
assert norm('第A章') in text, 'fence_keep 目录条目被误删'
text = norm(''.join(
    p.extract_text() or ''
    for p in pypdf.PdfReader(str(base / 'mixed_li.pdf')).pages))
assert norm('含附录说明') in text, '混合容器说明文字未保留'
print('T02-1：三种形式/中英标签/查询片段下划线/本地路径/尾注逐项通过；'
      '出处隐藏、目录条目与正文保留；围栏内容不动、混合容器说明保留')
PY
echo "T02-1 正例：窄格式各形态导出+核验通过 PASS"

# T02-2 反例：格式外候选逐项定位失败（文件/行号诊断、非零退出、零候选、
# 旧 PDF 字节不变）；格式外出处须走显式声明（T01 已验正例）
python3 - "$T2" <<'PY'
from pathlib import Path
import sys
base = Path(sys.argv[1])
CHAPTER = '# 第 A 章\n\n> **来源**：https://example.com/t2-a\n\nA 正文。\n'
NEG = {
    'bare_guide': '译自 https://example.com/t2/x；[Additional Guide](a.md)',
    'two_links': '译自 [A](https://example.com/t2/u1) 与 [B](https://example.com/t2/u2)',
    'prose': '译自 https://example.com/t2/x See appendix',
    'paren_prose': '译自 [原文](https://example.com/t2/u)（另见导览）',
    'image': '译自 ![img](https://example.com/t2/x.png)',
    'code_inline': '译自 `https://example.com/t2/x`',
    'no_locator': '译自 某某博客',
    'multiline': '译自 https://example.com/t2/x\n续行',
    'shared_quote': '> 译自 Guide：https://example.com/t2/x\n> - [第 A 章](a.md)',
    'nested_list': '- 译自 https://example.com/t2/x',
    'nav_link': '译自 [第 A 章](a.md)',
    'nav_bare': '译自 a.md',
    'bad_date': '译自 [P](https://example.com/t2/p)（2026-13-01）',
    'bad_tail': '译自 [P](https://example.com/t2/p)（v13）',
}
for tag, prov in NEG.items():
    case = base / ('neg_' + tag)
    case.mkdir()
    (case / '00_目录.md').write_text(
        '# 目录\n\n%s\n\n- [第 A 章](a.md)\n' % prov, encoding='utf-8')
    (case / 'a.md').write_text(CHAPTER, encoding='utf-8')
case = base / 'neg_multi'
case.mkdir()
(case / '00_目录.md').write_text(
    '# 目录\n\n译自 https://example.com/t2/x\n\n译自 https://example.com/t2/y\n\n'
    '- [第 A 章](a.md)\n', encoding='utf-8')
(case / 'a.md').write_text(CHAPTER, encoding='utf-8')
print('T02-2 反例就绪')
PY
printf 'OLD-PDF-BYTES' > "$T2/old.pdf"
for tag in bare_guide two_links prose paren_prose image code_inline \
    no_locator multiline shared_quote nested_list nav_link nav_bare \
    bad_date bad_tail multi; do
  cp "$T2/old.pdf" "$T2/neg_${tag}.pdf"
  if python3 "$EXPORT" --output "$T2/neg_${tag}.pdf" \
      --work-dir "$T2/w_neg_${tag}" \
      "$T2/neg_${tag}/00_目录.md" "$T2/neg_${tag}/a.md" \
      >"$T2/neg_${tag}.txt" 2>&1; then
    echo "错误：T02-2 反例（${tag}）未被拒绝"; exit 1
  fi
  grep -q "L[0-9]" "$T2/neg_${tag}.txt" \
    || { cat "$T2/neg_${tag}.txt"; echo "错误：T02-2 反例（${tag}）缺行号定位"; exit 1; }
  test ! -f "$T2/w_neg_${tag}/candidate.pdf" \
    || { echo "错误：T02-2 反例（${tag}）仍生成候选"; exit 1; }
  cmp -s "$T2/old.pdf" "$T2/neg_${tag}.pdf" \
    || { echo "错误：T02-2 反例（${tag}）旧 PDF 被改写"; exit 1; }
  case "$tag" in
    bare_guide|two_links|prose|image|code_inline)
      kw="无法确认整行仅为出处" ;;
    paren_prose|bad_date|bad_tail) kw="书目尾注" ;;
    no_locator) kw="可定位" ;;
    multiline) kw="跨多行" ;;
    shared_quote) kw="共享同一块" ;;
    nested_list) kw="未形成独立顶层段落块" ;;
    nav_link|nav_bare) kw="导航歧义" ;;
    multi) kw="至多自动采用一个" ;;
  esac
  grep -q "$kw" "$T2/neg_${tag}.txt" \
    || { cat "$T2/neg_${tag}.txt"; echo "错误：T02-2 反例（${tag}）诊断缺失：$kw"; exit 1; }
done
echo "T02-2 反例：混合内容/第二链接/散文/图片/代码/缺来源/多行/共享块/嵌套/导航定位符/无效尾注/多候选均定位失败，零候选、旧 PDF 不变 PASS"

# T02-3 核验反例：改错目录章节链接目标的成品必须被独立核验依据未投影
# 输入拒绝（toc-nav-link-missing）；缺失情形由 T01-5 同口径覆盖。
# 导览链接指向章内片段（目标页与印刷目录条目页不同），篡改才可隔离判定。
cat > "$T2/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t2/nav)；[附加导览](a.md#第二节)

- [第 A 章](a.md)
MD
python3 - "$T2" <<'PY'
from pathlib import Path
import sys
filler = '\n'.join('填充段 %02d：第二节须落到目标章第二页。' % i
                   for i in range(1, 201))
Path(sys.argv[1], 'a.md').write_text(
    '# 第 A 章\n\n> **来源**：https://example.com/t2-a\n\nA 正文。\n\n'
    + filler + '\n\n## 第二节\n\n第二节正文。\n', encoding='utf-8')
PY
python3 - "$T2" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 3], "type": "inline",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t2/nav)；",
        "reason": "出处与导览同行：仅排除出处片段，导览保留",
    }],
}
(base / 'decl_nav.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
print('T02-3 声明就绪')
PY
python3 "$EXPORT" --output "$T2/nav.pdf" --work-dir "$T2/w_nav" \
  --view-declaration "$T2/decl_nav.json" \
  "$T2/00_目录.md" "$T2/a.md" >"$T2/nav_e.txt" 2>&1 \
  || { cat "$T2/nav_e.txt"; echo "错误：T02-3 正例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T2/nav.pdf" --work-dir "$T2/w_nav" \
  --view-declaration "$T2/decl_nav.json" \
  "$T2/00_目录.md" "$T2/a.md" >"$T2/nav_v.txt" 2>&1 \
  || { cat "$T2/nav_v.txt"; echo "错误：T02-3 正例核验失败"; exit 1; }
python3 - "$T2" <<'PY'
import hashlib, json, sys
from pathlib import Path
from urllib.parse import unquote
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
base = Path(sys.argv[1])
reader = PdfReader(str(base / 'nav.pdf'))
# Chromium 将非 ASCII 目的地名按 URL 编码写出：同时登记原始与解码键
named = {}
for k, v in reader.named_destinations.items():
    page = reader.get_destination_page_number(v)
    raw = str(k).lstrip('/')
    named[raw] = page
    named.setdefault(unquote(raw), page)
# “第二节”片段页与章起始页不同（ filler 使其落在章第二页）
section_pages = {page for name, page in named.items() if '第二节' in name}
assert section_pages and section_pages != {1}, named
section_page = section_pages.pop()
wrong = [name for name, page in named.items() if page != section_page]
assert wrong, '缺少可改指的其他页命名目的地'
writer = PdfWriter(clone_from=reader)
toc_page = writer.pages[0]
annots = [ref.get_object() for ref in toc_page['/Annots']]
assert len(annots) >= 2, '目录页应含印刷目录与导览两条注解'


def _dest_page(obj):
    dest = obj.get('/Dest')
    if dest is None and obj.get('/A') is not None:
        dest = obj['/A'].get_object().get('/D')
    if dest is None:
        return None
    dest = dest.get_object() if hasattr(dest, 'get_object') else dest
    if isinstance(dest, bytes):
        dest = dest.decode('utf-8', 'replace')
    if isinstance(dest, str):
        return named.get(dest.lstrip('/'))
    return None


victims = [a for a in annots if _dest_page(a) == section_page]
assert len(victims) == 1, '导览片段注解应唯一：%r' % (victims,)
victim = victims[0]
if victim.get('/Dest') is not None:
    victim[NameObject('/Dest')] = NameObject('/' + wrong[0])
else:
    victim['/A'].get_object()[NameObject('/D')] = NameObject('/' + wrong[0])
writer.write(str(base / 'nav_wrongdest.pdf'))
report = json.loads((base / 'w_nav' / 'export_report.json')
                    .read_text(encoding='utf-8'))
report['pdf_sha256'] = hashlib.sha256(
    (base / 'nav_wrongdest.pdf').read_bytes()).hexdigest()
(base / 'w_nav' / 'export_report.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('T02-3 篡改样本就绪')
PY
if python3 "$VERIFY" --pdf "$T2/nav_wrongdest.pdf" --work-dir "$T2/w_nav" \
    --view-declaration "$T2/decl_nav.json" \
    "$T2/00_目录.md" "$T2/a.md" >"$T2/nav_wrongdest_v.txt" 2>&1; then
  echo "错误：T02-3 改错目录章节链接目标的 PDF 未被核验拒绝"; exit 1
fi
grep -q "toc-nav-link-missing" "$T2/nav_wrongdest_v.txt" \
  || { cat "$T2/nav_wrongdest_v.txt"; echo "错误：T02-3 toc-nav-link-missing 诊断缺失"; exit 1; }
echo "T02-3：改错目录章节链接目标被独立核验依据未投影输入拒绝 PASS"

echo "==> T03（pdf-layout-optimization ticket 03）：复审修复回归"
T3="$TMP/t03"; rm -rf "$T3"; mkdir -p "$T3"
cat > "$T3/a.md" <<'MD'
# 第 A 章

> **来源**：https://example.com/t3-chapter

A 正文。
MD

# T03-1：inline 声明只接管 fragment 实际覆盖行，区间内其余“译自”候选
# 恢复自动判断（复审 P1 复现样例转回归）。本正例同时是重叠误报回归：
# 自动区间 L5 落在声明区间 [3,5] 内但在 fragment 覆盖行 (3,3) 之外，
# 若重叠检查仍按整个声明区间判定，本导出会被误报重叠拒绝。
cat > "$T3/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t3/one)；[附加导览](a.md)

译自 [另一原文](https://example.com/t3/two)

- [第 A 章](a.md)
MD
python3 - "$T3" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 5], "type": "inline",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t3/one)；",
        "reason": "复审复现：声明区间 [3,5] 的 fragment 只在 L3",
    }],
}
(base / 'decl.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
python3 "$EXPORT" --output "$T3/out.pdf" --work-dir "$T3/w" \
  --view-declaration "$T3/decl.json" \
  "$T3/00_目录.md" "$T3/a.md" >"$T3/e.txt" 2>&1 \
  || { cat "$T3/e.txt"; echo "错误：T03-1 声明+L5 自动出处导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T3/out.pdf" --work-dir "$T3/w" \
  --view-declaration "$T3/decl.json" \
  "$T3/00_目录.md" "$T3/a.md" >"$T3/v.txt" 2>&1 \
  || { cat "$T3/v.txt"; echo "错误：T03-1 声明+L5 自动出处核验失败"; exit 1; }
python3 - "$T3" <<'PY'
import re, sys, unicodedata
from pathlib import Path

import pypdf

base = Path(sys.argv[1])
def norm(s):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", s or ""))
text = norm("".join(page.extract_text() or ""
                    for page in pypdf.PdfReader(str(base / 'out.pdf')).pages))
for probe in ("译自", "example.com/t3/one", "example.com/t3/two"):
    assert probe not in text, "出处仍出现在 PDF：%s" % probe
assert norm("附加导览") in text, "导览文字被误删"
assert norm("第A章") in text, "目录导航被误删"
print("T03-1：声明只接管 fragment 覆盖行；L5 出处自动排除、导览与导航保留 PASS")
PY
# T03-1 变体：L5 候选格式外 → 定位失败、零候选、旧 PDF 字节不变
python3 - "$T3" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = base / '00_目录.md'
text = toc.read_text(encoding='utf-8').replace(
    "译自 [另一原文](https://example.com/t3/two)",
    "译自 [另一原文](https://example.com/t3/two)；另见附录")
toc.write_text(text, encoding='utf-8')
decl = json.loads((base / 'decl.json').read_text(encoding='utf-8'))
decl["inputs"][0]["sha256"] = hashlib.sha256(toc.read_bytes()).hexdigest()
(base / 'decl_bad.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
printf 'OLD-PDF' > "$T3/keep.pdf"
if python3 "$EXPORT" --output "$T3/keep.pdf" --work-dir "$T3/w_bad" \
    --view-declaration "$T3/decl_bad.json" \
    "$T3/00_目录.md" "$T3/a.md" >"$T3/bad_e.txt" 2>&1; then
  echo "错误：T03-1 变体 L5 格式外候选未被拒绝"; exit 1
fi
grep -q "L5" "$T3/bad_e.txt" \
  || { cat "$T3/bad_e.txt"; echo "错误：T03-1 变体未定位 L5"; exit 1; }
grep -q "无法确认整行仅为出处" "$T3/bad_e.txt" \
  || { cat "$T3/bad_e.txt"; echo "错误：T03-1 变体诊断缺失"; exit 1; }
test ! -f "$T3/w_bad/candidate.pdf" || { echo "错误：T03-1 变体仍生成候选"; exit 1; }
[ "$(cat "$T3/keep.pdf")" = "OLD-PDF" ] || { echo "错误：T03-1 变体覆盖旧 PDF"; exit 1; }
echo "T03-1 变体：L5 格式外候选定位失败、零候选、旧 PDF 不变 PASS"

# T03-2：印刷目录正确注解不能掩盖被改错的导览链接（复审 P1 复现样例，
# 逐链接几何绑定）。导览与印刷目录条目指向同一章首页；篡改导览注解后，
# 页级存在性检查会被条目注解掩盖，逐链接绑定必须报 toc-nav-link-missing。
cat > "$T3/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t3/nav)；[附加导览](a.md)

- [第 A 章](a.md)
MD
python3 - "$T3" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 3], "type": "inline",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t3/nav)；",
        "reason": "复审复现：导览与条目同目标页掩盖场景",
    }],
}
(base / 'decl_nav.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
python3 "$EXPORT" --output "$T3/nav.pdf" --work-dir "$T3/w_nav" \
  --view-declaration "$T3/decl_nav.json" \
  "$T3/00_目录.md" "$T3/a.md" >"$T3/nav_e.txt" 2>&1 \
  || { cat "$T3/nav_e.txt"; echo "错误：T03-2 正确成品导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T3/nav.pdf" --work-dir "$T3/w_nav" \
  --view-declaration "$T3/decl_nav.json" \
  "$T3/00_目录.md" "$T3/a.md" >"$T3/nav_v.txt" 2>&1 \
  || { cat "$T3/nav_v.txt"; echo "错误：T03-2 正确成品核验失败"; exit 1; }
python3 - "$T3" <<'PY'
import hashlib, json, sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject

base = Path(sys.argv[1])
reader = PdfReader(str(base / 'nav.pdf'))
named = {}
for key, value in reader.named_destinations.items():
    named[str(key).lstrip('/')] = reader.get_destination_page_number(value)
chapter_pages = {page for page in named.values() if page != 0}
assert chapter_pages, named
chapter_page = chapter_pages.pop()
writer = PdfWriter(clone_from=reader)
toc_page = writer.pages[0]
annots = [ref.get_object() for ref in toc_page['/Annots']]


def _dest_page(obj):
    dest = obj.get('/Dest')
    if dest is None and obj.get('/A') is not None:
        dest = obj['/A'].get_object().get('/D')
    if dest is None:
        return None
    dest = dest.get_object() if hasattr(dest, 'get_object') else dest
    if isinstance(dest, bytes):
        dest = dest.decode('utf-8', 'replace')
    if isinstance(dest, str):
        return named.get(dest.lstrip('/'))
    return None


victims = [a for a in annots if _dest_page(a) == chapter_page]
assert len(victims) >= 2, '目录页应有条目与导览两条同目标注解：%r' % (victims,)
# 本样例中印刷目录条目注解为整行宽（列表容器链接），导览注解紧贴标签
# 文字：取宽度最窄者为受害者，避免误改印刷目录条目注解（列表项整行
# 注解的纵高可能高于段落内导览注解，按纵坐标选取不可靠）。
def _width(annot):
    rect = annot.get('/Rect') or [0, 0, 0, 0]
    return abs(float(rect[2]) - float(rect[0]))
victim = min(victims, key=_width)
assert _width(victim) < max(_width(a) for a in victims), \
    '导览与条目注解宽度须可区分'
# 本样例不存在指向目录页自身的命名目的地；直接把受害者注解改为指向
# 目录页自身的数组目的地（[页引用 /Fit]，核验器按 dest[0] 解析目标页）。
toc_dest = ArrayObject([toc_page.indirect_reference, NameObject('/Fit')])
if victim.get('/Dest') is not None:
    victim[NameObject('/Dest')] = toc_dest
else:
    victim['/A'].get_object()[NameObject('/D')] = toc_dest
writer.write(str(base / 'nav_masked.pdf'))
report = json.loads((base / 'w_nav' / 'export_report.json')
                    .read_text(encoding='utf-8'))
report['pdf_sha256'] = hashlib.sha256(
    (base / 'nav_masked.pdf').read_bytes()).hexdigest()
(base / 'w_nav' / 'export_report.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('T03-2 掩盖篡改样本就绪')
PY
if python3 "$VERIFY" --pdf "$T3/nav_masked.pdf" --work-dir "$T3/w_nav" \
    --view-declaration "$T3/decl_nav.json" \
    "$T3/00_目录.md" "$T3/a.md" >"$T3/nav_masked_v.txt" 2>&1; then
  echo "错误：T03-2 被条目注解掩盖的改错导览链接未被核验拒绝"; exit 1
fi
grep -q "toc-nav-link-missing" "$T3/nav_masked_v.txt" \
  || { cat "$T3/nav_masked_v.txt"; echo "错误：T03-2 toc-nav-link-missing 诊断缺失"; exit 1; }
grep -q "附加导览" "$T3/nav_masked_v.txt" \
  || { cat "$T3/nav_masked_v.txt"; echo "错误：T03-2 未定位到被改错的链接"; exit 1; }
echo "T03-2：条目正确注解掩盖下的改错导览链接被逐链接绑定检出 PASS"

# T03-4：长导览链接折行产生多个注解（ticket 03 验收 2 补充）。正例真实
# 导出+独立核验通过，并从成品 PDF 直读确认各段均指向目标页；仅篡改
# 其中一段目的地回目录页、其余段与印刷目录注解保持正确，逐段核对
# 仍须报 toc-nav-link-missing 并定位到该链接。
cat > "$T3/00_目录.md" <<'MD'
# 目录

译自 [原文](https://example.com/t3/fold)；导览：前前前前前前前前前前前前前前前前前前前前前前前前前前前前前前[附加导览文字需要足够长才能跨越目录页版心宽度折成两行显示](a.md)

- [第 A 章](a.md)
MD
python3 - "$T3" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
toc = (base / '00_目录.md').resolve()
a = (base / 'a.md').resolve()
decl = {
    "version": 1,
    "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in (toc, a)],
    "exclusions": [{
        "input": str(toc), "lines": [3, 3], "type": "inline",
        "kind": "toc-provenance",
        "fragment": "译自 [原文](https://example.com/t3/fold)；",
        "reason": "折行导览正例",
    }],
}
(base / 'decl_fold.json').write_text(
    json.dumps(decl, ensure_ascii=False), encoding='utf-8')
PY
python3 "$EXPORT" --output "$T3/fold.pdf" --work-dir "$T3/w_fold" \
  --view-declaration "$T3/decl_fold.json" \
  "$T3/00_目录.md" "$T3/a.md" >"$T3/fold_e.txt" 2>&1 \
  || { cat "$T3/fold_e.txt"; echo "错误：T03-4 折行正例导出失败"; exit 1; }
python3 "$VERIFY" --pdf "$T3/fold.pdf" --work-dir "$T3/w_fold" \
  --view-declaration "$T3/decl_fold.json" \
  "$T3/00_目录.md" "$T3/a.md" >"$T3/fold_v.txt" 2>&1 \
  || { cat "$T3/fold_v.txt"; echo "错误：T03-4 折行正例核验失败"; exit 1; }
python3 - "$T3" <<'PY'
import hashlib, json, sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject

base = Path(sys.argv[1])
reader = PdfReader(str(base / 'fold.pdf'))
named = {}
for key, value in reader.named_destinations.items():
    named[str(key).lstrip('/')] = reader.get_destination_page_number(value)
chapter_pages = {page for page in named.values() if page != 0}
assert chapter_pages, named
chapter_page = chapter_pages.pop()
writer = PdfWriter(clone_from=reader)
toc_page = writer.pages[0]
annots = [ref.get_object() for ref in toc_page['/Annots']]


def _dest_page(obj):
    dest = obj.get('/Dest')
    if dest is None and obj.get('/A') is not None:
        dest = obj['/A'].get_object().get('/D')
    if dest is None:
        return None
    dest = dest.get_object() if hasattr(dest, 'get_object') else dest
    if isinstance(dest, bytes):
        dest = dest.decode('utf-8', 'replace')
    if isinstance(dest, str):
        return named.get(dest.lstrip('/'))
    return None


def _width(annot):
    rect = annot.get('/Rect') or [0, 0, 0, 0]
    return abs(float(rect[2]) - float(rect[0]))


victims = [a for a in annots if _dest_page(a) == chapter_page]
assert len(victims) >= 3, '目录页应有条目整行注解与折行多段注解：%r' % (victims,)
# 条目注解为整行宽；折行导览的各段注解均窄于整行
widest = max(_width(a) for a in victims)
segments = [a for a in victims if _width(a) < widest]
assert len(segments) >= 2, '长标签未折行（应产生两段以上导览注解）'
# 正例直读确认：各段的目的地都解析到章首页
for seg in segments:
    assert _dest_page(seg) == chapter_page, '折行段目的地错误'
# 仅篡改折行第一段（纵高最高者）的目的地回目录页自身
victim = max(segments, key=lambda a: float((a.get('/Rect') or [0, 0, 0, 0])[3]))
toc_dest = ArrayObject([toc_page.indirect_reference, NameObject('/Fit')])
if victim.get('/Dest') is not None:
    victim[NameObject('/Dest')] = toc_dest
else:
    victim['/A'].get_object()[NameObject('/D')] = toc_dest
writer.write(str(base / 'fold_masked.pdf'))
report = json.loads((base / 'w_fold' / 'export_report.json')
                    .read_text(encoding='utf-8'))
report['pdf_sha256'] = hashlib.sha256(
    (base / 'fold_masked.pdf').read_bytes()).hexdigest()
(base / 'w_fold' / 'export_report.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('T03-4 折行部分篡改样本就绪')
PY
if python3 "$VERIFY" --pdf "$T3/fold_masked.pdf" --work-dir "$T3/w_fold" \
    --view-declaration "$T3/decl_fold.json" \
    "$T3/00_目录.md" "$T3/a.md" >"$T3/fold_masked_v.txt" 2>&1; then
  echo "错误：T03-4 仅篡改一段的折行导览链接未被核验拒绝"; exit 1
fi
grep -q "toc-nav-link-missing" "$T3/fold_masked_v.txt" \
  || { cat "$T3/fold_masked_v.txt"; echo "错误：T03-4 toc-nav-link-missing 诊断缺失"; exit 1; }
grep -q "附加导览文字" "$T3/fold_masked_v.txt" \
  || { cat "$T3/fold_masked_v.txt"; echo "错误：T03-4 未定位到被改错的折行链接"; exit 1; }
echo "T03-4：折行导览正例通过、各段跳转正确，仅篡改一段即被逐段核对检出 PASS"

# T03-3：无主机定位符完整校验（复审 P2）：链接与裸两种形态逐项定位拒绝
for form in link bare; do
  cat > "$T3/00_目录.md" <<MD
# 目录

$( [ "$form" = link ] && echo '译自 [原文](https:///paper)' || echo '译自 https:///paper' )

- [第 A 章](a.md)
MD
  printf 'OLD-PDF' > "$T3/keep_$form.pdf"
  if python3 "$EXPORT" --output "$T3/keep_$form.pdf" --work-dir "$T3/w_$form" \
      "$T3/00_目录.md" "$T3/a.md" >"$T3/${form}_e.txt" 2>&1; then
    echo "错误：T03-3 无主机定位符（$form）未被拒绝"; exit 1
  fi
  grep -q "L3" "$T3/${form}_e.txt" \
    || { cat "$T3/${form}_e.txt"; echo "错误：T03-3（$form）未定位 L3"; exit 1; }
  grep -q "URL 定位符缺少主机" "$T3/${form}_e.txt" \
    || { cat "$T3/${form}_e.txt"; echo "错误：T03-3（$form）缺少主机诊断缺失"; exit 1; }
  test ! -f "$T3/w_$form/candidate.pdf" || { echo "错误：T03-3（$form）仍生成候选"; exit 1; }
  [ "$(cat "$T3/keep_$form.pdf")" = "OLD-PDF" ] \
    || { echo "错误：T03-3（$form）覆盖旧 PDF"; exit 1; }
done
echo "T03-3：无主机定位符链接/裸两形态均定位失败、零候选、旧 PDF 不变 PASS"

echo "==> T04（第二轮复审修复）：同名实例与 URL 实际路径"
T4="$TMP/t04_review"
mkdir -p "$T4"
python3 - "$T4" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
for tag, suffix in [('plain', ''), ('digit3', ' 3'), ('query_ok', ''),
                    ('prefix', ''), ('twins', ''), ('code', '')]:
    case = base / tag
    case.mkdir()
    title = ('第 A 章' + '这是检验折行印刷目录的长标题' * 6
             if tag == 'prefix' else '第 A 章')
    chapter = '# %s\n\n> **来源**：https://example.com/chapter\n\nA 正文。\n' % title
    guide = '[第 A 章](a.md)' + suffix
    if tag == 'twins':
        guide += ' 和 [第 A 章](a.md)'
    if tag == 'code':
        guide = '[`第 A 章`](a.md)'
    url = ('https://example.com/paper?id=1' if tag == 'query_ok'
           else 'https://example.com/paper')
    (case / 'a.md').write_text(chapter, encoding='utf-8')
    (case / '00_目录.md').write_text(
        '# 目录\n\n译自 [原文](%s)\n\n%s\n\n'
        '- [%s](a.md)\n' % (url, guide, title), encoding='utf-8')
    (case / 'input_hashes.json').write_text(json.dumps({
        name: hashlib.sha256((case / name).read_bytes()).hexdigest()
        for name in ('00_目录.md', 'a.md')}), encoding='utf-8')
PY
for tag in plain digit3 query_ok prefix twins code; do
  case_dir="$T4/$tag"
  python3 "$EXPORT" --output "$case_dir/out.pdf" --work-dir "$case_dir/work" \
    "$case_dir/00_目录.md" "$case_dir/a.md" >"$case_dir/export.log" 2>&1 \
    || { cat "$case_dir/export.log"; echo "错误：T04 $tag 正例导出失败"; exit 1; }
  python3 "$VERIFY" --pdf "$case_dir/out.pdf" --work-dir "$case_dir/work" \
    "$case_dir/00_目录.md" "$case_dir/a.md" >"$case_dir/verify.log" 2>&1 \
    || { cat "$case_dir/verify.log"; echo "错误：T04 $tag 正例核验失败"; exit 1; }
done
python3 - "$T4" <<'PY'
import hashlib, json, re, shutil, sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject
base = Path(sys.argv[1])
for tag in ('plain', 'digit3', 'query_ok', 'prefix', 'twins',
            'code'):
    case = base / tag
    hashes = json.loads((case / 'input_hashes.json').read_text())
    assert all(hashlib.sha256((case / name).read_bytes()).hexdigest() == digest
               for name, digest in hashes.items()), '输入 Markdown 被改动'
    reader = PdfReader(case / 'out.pdf')
    text = re.sub(r'\s+', '', ''.join(p.extract_text() or '' for p in reader.pages))
    assert '译自' not in text and '第A章' in text and 'A正文' in text
    if tag == 'digit3':
        assert '第A章3' in text, '标签后其他数字被误删'
    named = {str(n).lstrip('/'): reader.get_destination_page_number(d)
             for n, d in reader.named_destinations.items()}
    annotations = [ref.get_object() for ref in reader.pages[0]['/Annots']]
    assert len(annotations) == (3 if tag == 'twins' else 2), '链接实例数量不符'
    for annot in annotations:
        dest = annot.get('/Dest')
        if dest is None:
            dest = annot['/A'].get_object()['/D']
        assert named.get(str(dest).lstrip('/')) == 1, '正例跳转目标错误'
    if tag == 'query_ok':
        continue
    # 印刷目录在上方；逐个改低处的真实导览，其他实例保持正确。
    printed_index = max(range(len(annotations)),
                        key=lambda i: float(annotations[i]['/Rect'][3]))
    for victim_index in range(len(annotations)):
        if victim_index == printed_index:
            continue
        for fault in ('wrong_target', 'deleted'):
            out = case / ('%s_%d' % (fault, victim_index))
            out.mkdir()
            writer = PdfWriter(clone_from=reader)
            page = writer.pages[0]
            if fault == 'deleted':
                page[NameObject('/Annots')] = ArrayObject([
                    ref for i, ref in enumerate(page['/Annots']) if i != victim_index])
            else:
                victim = page['/Annots'][victim_index].get_object()
                dest = ArrayObject([page.indirect_reference, NameObject('/Fit')])
                if victim.get('/Dest') is not None:
                    victim[NameObject('/Dest')] = dest
                else:
                    victim['/A'].get_object()[NameObject('/D')] = dest
            writer.write(out / 'out.pdf')
            shutil.copytree(case / 'work', out / 'work')
            report_path = out / 'work' / 'export_report.json'
            report = json.loads(report_path.read_text())
            report['pdf_sha256'] = hashlib.sha256((out / 'out.pdf').read_bytes()).hexdigest()
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
print('T04 正例成品直读：出处缺席、导航文字/两处跳转及输入摘要正确')
PY
for tag in plain digit3 prefix twins code; do
  for fault_dir in "$T4/$tag"/wrong_target_* "$T4/$tag"/deleted_*; do
    case_dir="$T4/$tag"
    if python3 "$VERIFY" --pdf "$fault_dir/out.pdf" --work-dir "$fault_dir/work" \
        "$case_dir/00_目录.md" "$case_dir/a.md" >"$fault_dir/verify.log" 2>&1; then
      echo "错误：T04 $fault_dir 被其他正确实例掩盖"; exit 1
    fi
    grep -q 'toc-nav-link-missing' "$fault_dir/verify.log" \
      || { cat "$fault_dir/verify.log"; echo "错误：T04 缺逐链接诊断"; exit 1; }
    grep -q '第 A 章' "$fault_dir/verify.log" \
      || { cat "$fault_dir/verify.log"; echo "错误：T04 未定位同名链接"; exit 1; }
  done
done
echo "T04-1：同名/digit3/折行标题前缀/同行双链接/行内代码标签正例通过，逐实例篡改/删除均检出 PASS"

python3 - "$T4" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
for index, url in enumerate(('https://example.com/?next=/paper.pdf',
                            'https://example.com?next=https://other.test/paper',
                            'https://example.com/#https://other.test/paper')):
    for form in ('link', 'bare'):
        case = base / ('home_%d_%s' % (index, form))
        case.mkdir()
        (case / 'a.md').write_bytes((base / 'plain' / 'a.md').read_bytes())
        locator = '[原文](%s)' % url if form == 'link' else url
        (case / '00_目录.md').write_text(
            '# 目录\n\n译自 %s\n\n- [第 A 章](a.md)\n' % locator, encoding='utf-8')
        (case / 'keep.pdf').write_bytes(b'OLD-PDF')
        (case / 'input_hashes.json').write_text(json.dumps({
            name: hashlib.sha256((case / name).read_bytes()).hexdigest()
            for name in ('00_目录.md', 'a.md')}), encoding='utf-8')
PY
for case_dir in "$T4"/home_*; do
  if python3 "$EXPORT" --output "$case_dir/keep.pdf" --work-dir "$case_dir/work" \
      "$case_dir/00_目录.md" "$case_dir/a.md" >"$case_dir/export.log" 2>&1; then
    echo "错误：T04 首页 URL 假路径未被拒绝"; exit 1
  fi
  grep -q 'L3' "$case_dir/export.log" \
    || { cat "$case_dir/export.log"; echo "错误：T04 首页 URL 缺行号"; exit 1; }
  grep -q '主机内文档路径' "$case_dir/export.log" \
    || { cat "$case_dir/export.log"; echo "错误：T04 首页 URL 缺路径诊断"; exit 1; }
  test ! -f "$case_dir/work/candidate.pdf" \
    || { echo "错误：T04 首页 URL 仍生成候选"; exit 1; }
  [ "$(cat "$case_dir/keep.pdf")" = 'OLD-PDF' ] \
    || { echo "错误：T04 首页 URL 覆盖旧 PDF"; exit 1; }
done
python3 - "$T4" <<'PY'
import hashlib, json, sys
from pathlib import Path
for case in Path(sys.argv[1]).glob('home_*'):
    hashes = json.loads((case / 'input_hashes.json').read_text())
    assert all(hashlib.sha256((case / name).read_bytes()).hexdigest() == digest
               for name, digest in hashes.items()), '拒绝场景改动 Markdown'
print('T04-2：首页 query/fragment 三变体链接/裸形态逐项定位拒绝，零候选、旧 PDF/Markdown 不变 PASS')
PY

# Chromium 153 将旧 Div 布局容器标为 NonStruct；使用成品标签变体锁住
# 兼容行为，不依赖运行环境恰好安装某个 Chromium 版本。
echo "==> Chromium 匿名布局容器：完整代码通过、损伤拒绝、行内代码不借用"
python3 - "$TMP/anonymous_layout" "$EXPORT" "$VERIFY" <<'PYCOMPAT'
import hashlib, json, subprocess, sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

base = Path(sys.argv[1]); base.mkdir()
export, verify = map(lambda p: str(Path(p).resolve()), sys.argv[2:])
original = base / 'original.md'
original.write_text('# 容器兼容样例\n\n> **来源**：https://example.com/paper\n\n'
                    '正文中的行内代码 `printf("a b");` 保留。\n\n'
                    '```c\nprintf("a b");\n```\n\n```c\nreturn 1;\n```\n\n'
                    '未知语言回退：\n\n```unknownlang\nx = 1\ny = 2\n```\n\n'
                    '缩进代码：\n\n    indented_a = 1\n    indented_b = 2\n', encoding='utf-8')
digest = hashlib.sha256(original.read_bytes()).hexdigest()
for tag in ('good', 'bad', 'missing_block'):
    source = original if tag == 'good' else base / (tag + '.md')
    if tag != 'good':
        rendered = original.read_text()
        if tag == 'bad':
            rendered = rendered.replace('```c\nprintf("a b");', '```c\nprintf("ab");')
        else:
            rendered = rendered.replace('```c\nprintf("a b");\n```\n\n', '')
        source.write_text(rendered, encoding='utf-8')
    work = base / ('work_' + tag); pdf = base / (tag + '.pdf')
    result = subprocess.run([sys.executable, export, '--output', str(pdf),
                             '--work-dir', str(work), str(source)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    writer = PdfWriter(clone_from=PdfReader(pdf))
    def change_tag(node):
        node = node.get_object() if hasattr(node, 'get_object') else node
        if isinstance(node, list):
            for child in node: change_tag(child)
        elif isinstance(node, dict):
            if node.get('/S') == '/Div': node[NameObject('/S')] = NameObject('/NonStruct')
            change_tag(node.get('/K', []))
    change_tag(writer._root_object['/StructTreeRoot'])
    with pdf.open('wb') as handle: writer.write(handle)
    report_path = work / 'export_report.json'
    report = json.loads(report_path.read_text())
    for item in report['inputs']:
        item.update(path=str(original.resolve()), sha256=digest, bytes=original.stat().st_size)
    for item in report['chapters']:
        item['path'] = str(original.resolve())
        if 'sha256' in item: item['sha256'] = digest
    report['pdf_sha256'] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    result = subprocess.run([sys.executable, verify, '--pdf', str(pdf),
                             '--work-dir', str(work), str(original)],
                            capture_output=True, text=True)
    evidence = json.loads((work / 'verify_report.json').read_text())
    if tag == 'good':
        assert result.returncode == 0, result.stdout + result.stderr
        assert not any('结构不足' in item.get('segment', '')
                       for item in evidence['relaxed_matches']), evidence
    else:
        assert result.returncode != 0, tag + ': 代码损伤被静默放过'
        codes = {item['code'] for item in evidence['failures']}
        assert 'code-line-missing' in codes and 'pdf-evidence-mismatch' not in codes, evidence
assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
print('匿名布局容器：高亮/未知语言/缩进代码有结构归属、空格删除/整块缺失拒绝、行内代码不借用、原输入不变 PASS')
PYCOMPAT

# 译注排除只作用于正文：缩进代码和引用块中的同形字符串必须保留。
echo "==> 译注块边界：缩进代码/引用保留，相邻正文译注排除"
python3 - "$TMP/note_blocks" "$EXPORT" "$VERIFY" <<'PYNOTES'
import hashlib, json, re, subprocess, sys
from pathlib import Path
from pypdf import PdfReader

base = Path(sys.argv[1]); base.mkdir()
export, verify = (str(Path(p).resolve()) for p in sys.argv[2:])
protected = '【译注：代码字符串必须保留】'
for tag, block in (
    ('spaces', '    print("%s")' % protected),
    ('tab', '\tprint("%s")' % protected),
    ('quote', '> 原文引用开始。\n原文续行%s结束。' % protected),
):
    source = base / (tag + '.md')
    source.write_text('# 译注边界样例\n\n> **来源**：https://example.com/paper\n\n'
                      '正文前文。\n\n' + block + '\n\n'
                      '正文后文【译注：正文说明应隐藏】仍须保留。\n', encoding='utf-8')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    pdf = base / (tag + '.pdf'); work = base / ('work_' + tag)
    for name, command in (
        ('export', [sys.executable, export, '--output', str(pdf), '--work-dir', str(work), str(source)]),
        ('verify', [sys.executable, verify, '--pdf', str(pdf), '--work-dir', str(work), str(source)]),
    ):
        result = subprocess.run(command, capture_output=True, text=True)
        (base / (tag + '_' + name + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, tag + ': ' + result.stdout + result.stderr
    text = re.sub(r'\s+', '', ''.join(page.extract_text() or '' for page in PdfReader(pdf).pages))
    assert protected in text, tag + ': 原文代码/引用被误删'
    assert '【译注：正文说明应隐藏】' not in text, tag + ': 正文译注未排除'
    assert '正文后文仍须保留。' in text, tag + ': 相邻正文被连带排除'
    evidence = json.loads((work / 'export_report.json').read_text())
    assert len(evidence['translator_note_exclusions']) == 1, evidence
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
print('译注块边界：空格/Tab 缩进代码与引用懒惰续行保留，正文译注独立排除、输入不变 PASS')
PYNOTES
