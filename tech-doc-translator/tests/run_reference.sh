#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PARSE="../skills/tech-doc-translator/scripts/parse_reference_html.py"
VERIFY="../skills/tech-doc-translator/scripts/verify_reference_translation.py"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
mkdir -p "$TMPDIR/images"
cp fixtures/valid_1x1.png "$TMPDIR/images/thread_hierarchy.png"
cp fixtures/math_reference_translated.md fixtures/nested_reference_translated.md "$TMPDIR/"

echo "==> 解析数学密集参考手册样本"
python3 "$PARSE" fixtures/math_reference.html "$TMPDIR/math_source.md"

echo "==> 验证 math_reference 中文译文"
python3 "$VERIFY" "$TMPDIR/math_reference_translated.md" "$TMPDIR/math_source.md" \
  cuBLAS CUDA nvcc

echo "==> 解析深层嵌套参考手册样本"
python3 "$PARSE" fixtures/nested_reference.html "$TMPDIR/nested_source.md"

echo "==> 验证 nested_reference 中文译文"
python3 "$VERIFY" "$TMPDIR/nested_reference_translated.md" "$TMPDIR/nested_source.md" \
  __global__ threadIdx.x cudaMalloc

echo "==> 失败回归：漏块级公式必须判 FAIL"
export TECHDOC_TMPDIR="$TMPDIR"
python3 - "$TMPDIR/math_reference_translated.md" <<'PY'
import os, re
import sys
tmp = os.environ['TECHDOC_TMPDIR']
txt = open(sys.argv[1]).read()
txt = re.sub(r'\n\$\$.*?\n\$\$(?=\n)', '', txt, count=1, flags=re.S)
open(os.path.join(tmp, 'math_missing_block.md'), 'w').write(txt)
PY
if python3 "$VERIFY" "$TMPDIR/math_missing_block.md" "$TMPDIR/math_source.md" cuBLAS CUDA nvcc; then
  echo "错误：漏块级公式未被检测到"
  exit 1
else
  echo "漏块级公式已正确判 FAIL"
fi

echo "==> 失败回归：漏嵌套图片必须判 FAIL"
python3 - "$TMPDIR/nested_reference_translated.md" <<'PY'
import os, re
import sys
tmp = os.environ['TECHDOC_TMPDIR']
txt = open(sys.argv[1]).read()
txt = re.sub(r'\n!\[[^\]]*\]\([^)]*\)(?=\n)', '', txt, count=1)
open(os.path.join(tmp, 'nested_missing_img.md'), 'w').write(txt)
PY
if python3 "$VERIFY" "$TMPDIR/nested_missing_img.md" "$TMPDIR/nested_source.md" \
    __global__ threadIdx.x cudaMalloc; then
  echo "错误：漏嵌套图片未被检测到"
  exit 1
else
  echo "漏嵌套图片已正确判 FAIL"
fi

echo "==> 失败回归：漏强 token 必须判 FAIL"
python3 - "$TMPDIR/nested_reference_translated.md" <<'PY'
import os
import sys
tmp = os.environ['TECHDOC_TMPDIR']
txt = open(sys.argv[1]).read()
txt = txt.replace('threadIdx.x', '')
open(os.path.join(tmp, 'nested_missing_token.md'), 'w').write(txt)
PY
if python3 "$VERIFY" "$TMPDIR/nested_missing_token.md" "$TMPDIR/nested_source.md" \
    __global__ threadIdx.x cudaMalloc; then
  echo "错误：漏强 token 未被检测到"
  exit 1
else
  echo "漏强 token 已正确判 FAIL"
fi

echo "==> V0.2-02：嵌套结构（figure / dd 内图片）与百分比参照的显示尺寸登记"
cat > "$TMPDIR/widths_ref.html" <<'HTML'
<html><body><main>
<h1>R</h1>
<figure><img src="fig.png" style="width:600px"><figcaption>Cap</figcaption></figure>
<dl><dt>term</dt><dd><img src="dd.png" width="220"></dd></dl>
<div style="width:800px"><figure><img src="pct.png" style="width:50%"></figure></div>
<figure><img src="pct_noref.png" style="width:50%"></figure>
</main></body></html>
HTML
python3 "$PARSE" "$TMPDIR/widths_ref.html" "$TMPDIR/widths_ref.md"
python3 - "$TMPDIR/widths_ref.images_display.json" <<'PY'
import json, sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
entries = {e['occurrence']: e for e in payload['entries']}
assert entries[1]['image'] == 'images/fig.png', entries[1]
assert entries[1]['width']['value'] == 600, entries[1]
assert entries[2]['image'] == 'images/dd.png', entries[2]
assert entries[2]['width']['basis'] == 'html-width-attribute', entries[2]
assert entries[3]['image'] == 'images/pct.png', entries[3]
assert entries[3]['width']['unit'] == '%' and entries[3]['width']['value'] == 50, entries[3]
assert entries[3]['width']['reference'] == {
    'container': 'div', 'width_px': 800.0
}, entries[3]
reasons = [e['reason'] for e in payload['undetermined']]
assert reasons == ['百分比宽度缺少可确定的参照容器'], reasons
print('嵌套 figure / dd / 百分比带参照与无参照均按出现序号正确登记')
PY

echo "==> Ticket 03 回归全部通过"
