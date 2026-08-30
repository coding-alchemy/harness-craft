#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PARSE="../scripts/parse_reference_html.py"
VERIFY="../scripts/verify_reference_translation.py"

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

echo "==> Ticket 03 回归全部通过"
