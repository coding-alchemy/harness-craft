#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PARSE="../skills/tech-doc-translator/scripts/parse_paginated_html.py"
SPLICE="../skills/tech-doc-translator/scripts/splice_fences.py"
MERGE="../skills/tech-doc-translator/scripts/merge_sections.py"
VERIFY="../skills/tech-doc-translator/scripts/verify_paginated_translation.py"

# 路线项目强 token：由调用显式传入，替代旧的硬编码 CUDA 检查
verify_paginated() {
    python3 "$VERIFY" "$@" --strong-token '<<<' --strong-token '#include <'
}

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
mkdir -p "$TMPDIR/src_html"

cat > "$TMPDIR/header.md" <<'EOF'
# 第 1 章：CUDA 编程基础

> **来源** / NVIDIA CUDA C++ Programming Guide（本地测试样本）
> **译例说明** / 本章为分页、代码密集型 HTML 的最小回归样本，验证代码围栏保真与安全合并。

本章包含两节：编程模型与编程接口，重点验证 `<<<...>>>`、`#include <...>`、比较运算符及围栏内连续空行不被解析器损坏。
EOF

# 解析直接发生在临时目录，避免在 fixtures 中留下产物
cp fixtures/paginated_page1.html fixtures/paginated_page2.html "$TMPDIR/src_html/"

echo "==> 解析两页分页 HTML 到源 Markdown"
python3 "$PARSE" "$TMPDIR/src_html/paginated_page1.html" "$TMPDIR/src_html/paginated_page2.html"
mv "$TMPDIR/src_html/paginated_page1.md" "$TMPDIR/source_p1.md"
mv "$TMPDIR/src_html/paginated_page2.md" "$TMPDIR/source_p2.md"

echo "==> 失败回归：朴素标签剥离会破坏代码，parse_paginated_html.py 应逐字保留"
python3 - <<'PY'
import re
html = open('fixtures/paginated_page1.html', encoding='utf-8').read()
naive = re.sub(r'<[^>]+>', '', html)
if '<<<' in naive:
    raise AssertionError('朴素剥离未损坏 <<<，请检查回归样本')
if '#include <' in naive:
    raise AssertionError('朴素剥离未损坏 #include <，请检查回归样本')
PY
# 我们的解析器必须保留这些关键语法
grep -q '<<<' "$TMPDIR/source_p1.md" || { echo "FAIL: 源文丢失 <<<"; exit 1; }
grep -q '#include <cuda_runtime.h>' "$TMPDIR/source_p1.md" || { echo "FAIL: 源文丢失 #include"; exit 1; }
grep -q 'if (i < n)' "$TMPDIR/source_p1.md" || { echo "FAIL: 源文丢失比较运算符"; exit 1; }
grep -q '#include <iostream>' "$TMPDIR/source_p2.md" || { echo "FAIL: 源文丢失 #include <iostream>"; exit 1; }
# 检查页内连续空行：源 Markdown 中 main() 函数前后应保留空行
export TECHDOC_SOURCE_P1="$TMPDIR/source_p1.md"
python3 - <<'PY'
import os
import re
text = open(os.environ['TECHDOC_SOURCE_P1'], encoding='utf-8').read()
m = re.search(r'```\n(.*?)\n```', text, re.S)
assert m, '未找到代码围栏'
body = m.group(1)
# 原始 <pre> 中有空行（main 函数前后），应被保留
assert '\n\n' in body, '代码围栏内连续空行被破坏'
print('代码围栏内连续空行保留 PASS')
PY
echo "失败回归通过：关键 CUDA 语法与空行均未被损坏"

echo "==> 用 splice_fences.py 把译文草稿中的 ⟦CODE⟧ 替换为源文代码围栏"
python3 "$SPLICE" fixtures/paginated_translated_p1.md "$TMPDIR/source_p1.md" "$TMPDIR/draft_p1.md"
python3 "$SPLICE" fixtures/paginated_translated_p2.md "$TMPDIR/source_p2.md" "$TMPDIR/draft_p2.md"

echo "==> 合并章节头与各节译文"
python3 "$MERGE" -o "$TMPDIR/chapter.md" "$TMPDIR/header.md" "$TMPDIR/draft_p1.md" "$TMPDIR/draft_p2.md"

echo "==> 准备图片资源（相对合并产物目录）"
mkdir -p "$TMPDIR/images"
cp fixtures/valid_1x1.png "$TMPDIR/images/grid_blocks.png"
cp fixtures/valid_1x1.png "$TMPDIR/images/compilation_flow.png"

echo "==> 校验合并产物与源 Markdown"
verify_paginated "$TMPDIR/chapter.md" "$TMPDIR/source_p1.md" "$TMPDIR/source_p2.md"

echo "==> 完整性-01 失败回归：程序化回填后再篡改代码，最终校验必须检出"
python3 - "$TMPDIR/chapter.md" "$TMPDIR/chapter_bad_body.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
assert 'if (i < n)' in text, '回归样本缺少目标代码行'
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace('if (i < n)', 'if (i > n)'))
PY
if verify_paginated "$TMPDIR/chapter_bad_body.md" "$TMPDIR/source_p1.md" \
    "$TMPDIR/source_p2.md" >"$TMPDIR/bad_body_out.txt" 2>&1; then
  echo "错误：回填后代码内容篡改未被检测到"
  exit 1
fi
grep -q '代码逐块核对' "$TMPDIR/bad_body_out.txt" \
  || { echo "错误：缺少逐块核对诊断"; cat "$TMPDIR/bad_body_out.txt"; exit 1; }
grep -q 'if (i < n)' "$TMPDIR/bad_body_out.txt" \
  || { echo "错误：诊断缺少期望原文"; cat "$TMPDIR/bad_body_out.txt"; exit 1; }
echo "回填后代码内容篡改已正确判 FAIL（含期望/实际差异）"

echo "==> 完整性-01：带标签源围栏经回填/合并保持；改动标签必须判 FAIL"
python3 - "$TMPDIR/source_p1.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
assert '\n```\n' in text
open(sys.argv[1] + '.tagged.md', 'w', encoding='utf-8').write(
    text.replace('\n```\n', '\n```c\n', 1))
PY
python3 "$SPLICE" fixtures/paginated_translated_p1.md \
    "$TMPDIR/source_p1.md.tagged.md" "$TMPDIR/draft_p1_tagged.md"
python3 "$MERGE" -o "$TMPDIR/chapter_tagged.md" "$TMPDIR/header.md" \
    "$TMPDIR/draft_p1_tagged.md" "$TMPDIR/draft_p2.md"
verify_paginated "$TMPDIR/chapter_tagged.md" \
    "$TMPDIR/source_p1.md.tagged.md" "$TMPDIR/source_p2.md"
python3 - "$TMPDIR/chapter_tagged.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
assert '\n```c\n' in text, '回归样本缺少已回填的标签围栏'
open(path.replace('chapter_tagged.md', 'chapter_bad_lang.md'), 'w',
     encoding='utf-8').write(text.replace('\n```c\n', '\n```python\n', 1))
PY
if verify_paginated "$TMPDIR/chapter_bad_lang.md" \
    "$TMPDIR/source_p1.md.tagged.md" "$TMPDIR/source_p2.md" \
    >"$TMPDIR/bad_lang_out.txt" 2>&1; then
  echo "错误：语言标签篡改未被检测到"
  exit 1
fi
grep -q '开启行不一致' "$TMPDIR/bad_lang_out.txt" \
  || { echo "错误：缺少开启行差异诊断"; cat "$TMPDIR/bad_lang_out.txt"; exit 1; }
echo "带标签围栏经回填/合并保持通过；改动标签已正确判 FAIL"

python3 - "$TMPDIR/chapter.md" "$TMPDIR/chapter_bad_space.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
needle = '#include <cuda_runtime.h>'
assert needle in text, '回归样本缺少目标代码行'
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace(needle, needle + '  '))
PY
if verify_paginated "$TMPDIR/chapter_bad_space.md" "$TMPDIR/source_p1.md" \
    "$TMPDIR/source_p2.md"; then
  echo "错误：代码空白篡改未被检测到"
  exit 1
fi
echo "代码空白篡改已正确判 FAIL"

python3 - "$TMPDIR/chapter.md" "$TMPDIR/chapter_bad_blank.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
needle = '#include <cuda_runtime.h>\n\n__global__'
assert needle in text, '回归样本缺少含空行的代码段'
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace(needle, needle.replace('\n\n', '\n')))
PY
if verify_paginated "$TMPDIR/chapter_bad_blank.md" "$TMPDIR/source_p1.md" \
    "$TMPDIR/source_p2.md" >"$TMPDIR/bad_blank_out.txt" 2>&1; then
  echo "错误：代码空行删除未被检测到"
  exit 1
fi
grep -q '正文第 3 行不一致' "$TMPDIR/bad_blank_out.txt" \
  || { echo "错误：缺少空行差异诊断"; cat "$TMPDIR/bad_blank_out.txt"; exit 1; }
echo "代码空行删除已正确判 FAIL"

echo "==> 完整性-02：分页路线公式逐项核对（正确通过；篡改/交换判 FAIL）"
cat > "$TMPDIR/math_header.md" <<'EOF'
# 数学回归章（Math Regression）

说明文字，用于承载公式逐项核对回归。
EOF
cat > "$TMPDIR/math_s1.md" <<'EOF'
# 1. Math One

行内公式 $a+b$ 在段落中。

$$
E = mc^2
$$
EOF
cat > "$TMPDIR/math_s2.md" <<'EOF'
# 2. Math Two

块内 $$w$$ 与 $x$ 混合出现。
EOF
cat > "$TMPDIR/math_t1.md" <<'EOF'
# 1. Math One（数学一）

段落中含行内公式 $a+b$。

$$
E = mc^2
$$
EOF
cat > "$TMPDIR/math_t2.md" <<'EOF'
# 2. Math Two（数学二）

块内 $$w$$ 与 $x$ 混合出现。
EOF
python3 "$MERGE" -o "$TMPDIR/math_chapter.md" "$TMPDIR/math_header.md" \
    "$TMPDIR/math_t1.md" "$TMPDIR/math_t2.md"
verify_paginated "$TMPDIR/math_chapter.md" "$TMPDIR/math_s1.md" "$TMPDIR/math_s2.md"
python3 - "$TMPDIR/math_t1.md" "$TMPDIR/math_t2.md" <<'PY'
import sys

t1, t2 = sys.argv[1:3]
text1 = open(t1, encoding='utf-8').read()
open(t1 + '.bad.md', 'w', encoding='utf-8').write(
    text1.replace('$a+b$', '$a-b$'))
text2 = open(t2, encoding='utf-8').read()
open(t2 + '.bad.md', 'w', encoding='utf-8').write(
    text2.replace('块内 $$w$$ 与 $x$ 混合出现', '块内 $x$ 与 $$w$$ 混合出现'))
PY
python3 "$MERGE" -o "$TMPDIR/math_chapter_bad.md" "$TMPDIR/math_header.md" \
    "$TMPDIR/math_t1.md.bad.md" "$TMPDIR/math_t2.md"
if verify_paginated "$TMPDIR/math_chapter_bad.md" "$TMPDIR/math_s1.md" \
    "$TMPDIR/math_s2.md" >"$TMPDIR/math_bad_out.txt" 2>&1; then
  echo "错误：公式运算符篡改未被检测到"
  exit 1
fi
grep -q '表达式不一致' "$TMPDIR/math_bad_out.txt" \
  || { echo "错误：缺少公式差异诊断"; cat "$TMPDIR/math_bad_out.txt"; exit 1; }
echo "分页路线公式运算符篡改已正确判 FAIL"
python3 "$MERGE" -o "$TMPDIR/math_chapter_swap.md" "$TMPDIR/math_header.md" \
    "$TMPDIR/math_t1.md" "$TMPDIR/math_t2.md.bad.md"
if verify_paginated "$TMPDIR/math_chapter_swap.md" "$TMPDIR/math_s1.md" \
    "$TMPDIR/math_s2.md"; then
  echo "错误：公式交换/类型变化未被检测到"
  exit 1
fi
echo "分页路线公式交换与类型变化已正确判 FAIL"

echo "==> V0.2-02：分页解析输出携带显示尺寸映射"
cat > "$TMPDIR/src_html/widths.html" <<'HTML'
<html><body><article>
<h1>W</h1>
<img src="img_px.png" style="width:454px">
<img src="img_free.png">
</article></body></html>
HTML
python3 "$PARSE" "$TMPDIR/src_html/widths.html"
python3 - "$TMPDIR/src_html/widths.images_display.json" <<'PY'
import json, sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
assert payload['entries'][0]['width']['value'] == 454, payload
assert [e['reason'] for e in payload['undetermined']] == ['源节点无宽度约束'], payload
print('分页解析：显示尺寸映射与源 Markdown 同目录输出')
PY

echo "==> Ticket 02 分页、代码围栏保真与安全合并回归全部通过"
