#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PARSE="../scripts/parse_single_page_html.py"
VERIFY="../scripts/verify_translation.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/images"
cp fixtures/valid_1x1.png "$TMP/images/thread_hierarchy.png"
cp fixtures/sample_translated.md "$TMP/sample_translated.md"

echo "==> 解析单页 HTML 样本"
python3 "$PARSE" fixtures/sample_single_page.html "$TMP/sample_source.md"

echo "==> 验证通过的中文译文"
python3 "$VERIFY" "$TMP/sample_translated.md" "$TMP/sample_source.md" \
  "1. Compute Kernel Basics" \
  "1.1. Thread Hierarchy" \
  "1.1.1. Memory Model"

echo "==> 回归：围栏内 # 注释不得计入 Markdown 标题"
python3 - "$TMP/sample_translated.md" "$TMP/sample_fenced_comment.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
text += '\n```python\n# 这是代码注释，不是 H1\nprint("ok")\n```\n'
open(sys.argv[2], 'w', encoding='utf-8').write(text)
PY
python3 "$VERIFY" "$TMP/sample_fenced_comment.md" "$TMP/sample_source.md" \
  "1. Compute Kernel Basics" \
  "1.1. Thread Hierarchy" \
  "1.1.1. Memory Model"

echo "==> 回归：源译双方保留的历史嵌套数学定界符只告警"
python3 - "$TMP/sample_source.md" "$TMP/sample_translated.md" \
  "$TMP/legacy_math_source.md" "$TMP/legacy_math_translated.md" <<'PY'
import sys

source = open(sys.argv[1], encoding='utf-8').read()
translated = open(sys.argv[2], encoding='utf-8').read()
legacy = r'$\(N\)$'
open(sys.argv[3], 'w', encoding='utf-8').write(source + '\n' + legacy + '\n')
open(sys.argv[4], 'w', encoding='utf-8').write(translated + '\n' + legacy + '\n')
PY
python3 "$VERIFY" "$TMP/legacy_math_translated.md" "$TMP/legacy_math_source.md" \
  "1. Compute Kernel Basics" \
  "1.1. Thread Hierarchy" \
  "1.1.1. Memory Model"

echo "==> 失败回归：译文新增嵌套数学定界符必须判 FAIL"
python3 - "$TMP/legacy_math_translated.md" "$TMP/legacy_math_extra.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
open(sys.argv[2], 'w', encoding='utf-8').write(text + '\n' + r'$\(M\)$' + '\n')
PY
if python3 "$VERIFY" "$TMP/legacy_math_extra.md" "$TMP/legacy_math_source.md" \
  "1. Compute Kernel Basics" \
  "1.1. Thread Hierarchy" \
  "1.1.1. Memory Model"; then
  echo "错误：译文新增的嵌套数学定界符未被检测到"
  exit 1
else
  echo "新增嵌套数学定界符已正确报 FAIL"
fi

echo "==> 失败回归：同数量但内容改变的历史嵌套公式必须判 FAIL"
python3 - "$TMP/legacy_math_translated.md" "$TMP/legacy_math_changed.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
text = text.replace(r'$\(N\)$', r'$\(M\)$')
open(sys.argv[2], 'w', encoding='utf-8').write(text)
PY
if python3 "$VERIFY" "$TMP/legacy_math_changed.md" "$TMP/legacy_math_source.md" \
  "1. Compute Kernel Basics" \
  "1.1. Thread Hierarchy" \
  "1.1.1. Memory Model"; then
  echo "错误：内容改变的历史嵌套公式未被检测到"
  exit 1
else
  echo "内容改变的历史嵌套公式已正确报 FAIL"
fi

echo "==> 失败回归：链接目标丢失和嵌套公式定界符必须判 FAIL"
python3 - "$TMP/sample_translated.md" "$TMP/sample_bad_inline.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
text = text.replace(
    '[GPU](https://docs.nvidia.com/cuda/cuda-c-programming-guide/)', 'GPU')
text = text.replace('$N$', r'$\(N\)$')
open(sys.argv[2], 'w', encoding='utf-8').write(text)
PY
if python3 "$VERIFY" "$TMP/sample_bad_inline.md" "$TMP/sample_source.md" \
    "1. Compute Kernel Basics" \
    "1.1. Thread Hierarchy" \
    "1.1.1. Memory Model"; then
  echo "错误：链接或公式定界符损伤未被检测到"
  exit 1
else
  echo "链接与公式定界符损伤已正确报 FAIL"
fi

echo "==> 失败回归：未识别块级元素必须显式占位并报错"
python3 "$PARSE" fixtures/fail_regression.html "$TMP/fail_source.md"
if python3 "$VERIFY" "$TMP/fail_source.md" "$TMP/fail_source.md" "2. Unknown Block Test"; then
  echo "错误：未识别块级元素未被检测到"
  exit 1
else
  echo "未识别块级元素已正确报 FAIL"
fi

echo "==> 失败回归：嵌套 Sphinx 代码块与图题不得丢失或留下占位符"
python3 "$PARSE" fixtures/sphinx_nested_blocks.html "$TMP/sphinx_nested_source.md"
python3 - "$TMP/sphinx_nested_source.md" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding='utf-8').read()
blocks = re.findall(r'^```[^\n]*\n(.*?)\n```$', text, re.M | re.S)
assert blocks == ['nvcc demo.cu -lcusparse -o demo'], \
    'nvcc 必须且只能位于预期代码围栏正文中'
assert '<span' not in blocks[0], '代码围栏残留 Sphinx 高亮标签'
assert r'$\alpha + \beta$' in text, 'Sphinx 行内公式定界符未规范化'
assert r'$\(' not in text, '行内公式仍含嵌套定界符'
assert r'[figure \[DEPRECATED\]](#details)' in text, \
    '含方括号的行内链接未被安全保留'
PY
grep -q 'Dense vector representation' "$TMP/sphinx_nested_source.md" \
  || { echo "图题被丢失"; exit 1; }
if grep -q '\[FIGCAPTION\]' "$TMP/sphinx_nested_source.md"; then
  echo "图题残留占位符"
  exit 1
fi

echo "==> Ticket 01 回归全部通过"
