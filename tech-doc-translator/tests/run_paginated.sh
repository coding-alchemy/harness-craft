#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PARSE="../scripts/parse_paginated_html.py"
SPLICE="../scripts/splice_fences.py"
MERGE="../scripts/merge_sections.py"
VERIFY="../scripts/verify_paginated_translation.py"

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
python3 "$VERIFY" "$TMPDIR/chapter.md" "$TMPDIR/source_p1.md" "$TMPDIR/source_p2.md"

echo "==> Ticket 02 分页、代码围栏保真与安全合并回归全部通过"
