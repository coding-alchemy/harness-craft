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

echo "==> 完整性-01 失败回归：参考手册代码内容/空白篡改必须判 FAIL"
python3 - "$TMPDIR/nested_reference_translated.md" "$TMPDIR/nested_bad_code.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
needle = '__global__ void listKernel() {}'
assert needle in text, '回归样本缺少目标代码行'
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace(needle, '__global__ void listKernel(int n) {}'))
PY
if python3 "$VERIFY" "$TMPDIR/nested_bad_code.md" "$TMPDIR/nested_source.md" \
    __global__ threadIdx.x cudaMalloc >"$TMPDIR/ref_bad_code_out.txt" 2>&1; then
  echo "错误：代码内容篡改未被检测到"
  exit 1
fi
grep -q '代码逐块核对' "$TMPDIR/ref_bad_code_out.txt" \
  || { echo "错误：缺少逐块核对诊断"; cat "$TMPDIR/ref_bad_code_out.txt"; exit 1; }
echo "参考手册代码内容篡改已正确判 FAIL"

python3 - "$TMPDIR/nested_reference_translated.md" "$TMPDIR/nested_bad_space.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
needle = '__global__ void defKernel() {}'
assert needle in text, '回归样本缺少目标代码行'
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace(needle, needle + '  '))
PY
if python3 "$VERIFY" "$TMPDIR/nested_bad_space.md" "$TMPDIR/nested_source.md" \
    __global__ threadIdx.x cudaMalloc; then
  echo "错误：代码空白篡改未被检测到"
  exit 1
fi
echo "参考手册代码空白篡改已正确判 FAIL"

echo "==> 完整性-01：源裸围栏补语言标签为固定转换（译文不得改动已有标签）"
python3 - "$TMPDIR/nested_reference_translated.md" "$TMPDIR/nested_source.md" <<'PY'
import sys

trans_path, src_path = sys.argv[1], sys.argv[2]
text = open(src_path, encoding='utf-8').read()
open(src_path + '.tagged.md', 'w', encoding='utf-8').write(
    text.replace('  ```\n', '  ```cuda\n', 1))
trans = open(trans_path, encoding='utf-8').read()
open(trans_path.replace('.md', '_bad_lang.md'), 'w', encoding='utf-8').write(
    trans.replace('```cuda\n', '```cpp\n', 1))
PY
python3 "$VERIFY" "$TMPDIR/nested_reference_translated.md" \
    "$TMPDIR/nested_source.md.tagged.md" __global__ threadIdx.x cudaMalloc
if python3 "$VERIFY" "$TMPDIR/nested_reference_translated_bad_lang.md" \
    "$TMPDIR/nested_source.md.tagged.md" __global__ threadIdx.x cudaMalloc \
    >"$TMPDIR/ref_bad_lang_out.txt" 2>&1; then
  echo "错误：语言标签篡改未被检测到"
  exit 1
fi
grep -q '开启行不一致' "$TMPDIR/ref_bad_lang_out.txt" \
  || { echo "错误：缺少开启行差异诊断"; cat "$TMPDIR/ref_bad_lang_out.txt"; exit 1; }
echo "裸围栏补标签保持通过；改动标签已正确判 FAIL"

echo "==> 完整性-02 失败回归：公式改运算符/类型变化/交换顺序必须判 FAIL"
python3 - "$TMPDIR/math_reference_translated.md" "$TMPDIR" <<'PY'
import sys

path, tmp = sys.argv[1], sys.argv[2]
text = open(path, encoding='utf-8').read()
assert '$a+b=c$' in text, '回归样本缺少目标公式'
open(tmp + '/math_bad_op.md', 'w', encoding='utf-8').write(
    text.replace('$a+b=c$', '$a-b=c$'))
open(tmp + '/math_bad_kind.md', 'w', encoding='utf-8').write(
    text.replace('$a+b=c$', '$$a+b=c$$'))
open(tmp + '/math_swapped.md', 'w', encoding='utf-8').write(
    text.replace('$E=mc^2$。内联美元公式：$a+b=c$',
                 '$a+b=c$。内联美元公式：$E=mc^2$'))
PY
if python3 "$VERIFY" "$TMPDIR/math_bad_op.md" "$TMPDIR/math_source.md" \
    cuBLAS CUDA nvcc >"$TMPDIR/math_op_err.txt" 2>&1; then
  echo "错误：公式运算符篡改未被检测到"
  exit 1
fi
grep -q '表达式不一致' "$TMPDIR/math_op_err.txt" \
  || { echo "错误：缺少公式表达式差异诊断"; cat "$TMPDIR/math_op_err.txt"; exit 1; }
echo "公式运算符篡改（A8 加号改减号）已正确判 FAIL"
if python3 "$VERIFY" "$TMPDIR/math_bad_kind.md" "$TMPDIR/math_source.md" \
    cuBLAS CUDA nvcc; then
  echo "错误：公式类型变化未被检测到"
  exit 1
fi
echo "行内改块级公式已正确判 FAIL"
if python3 "$VERIFY" "$TMPDIR/math_swapped.md" "$TMPDIR/math_source.md" \
    cuBLAS CUDA nvcc; then
  echo "错误：公式交换未被检测到"
  exit 1
fi
echo "公式交换已正确判 FAIL"

echo "==> 完整性-02：一致历史包装仅告警；新增包装与未获准译注公式失败"
python3 - "$TMPDIR/math_source.md" "$TMPDIR/math_reference_translated.md" "$TMPDIR" <<'PY'
import sys

src_path, trans_path, tmp = sys.argv[1:4]
src = open(src_path, encoding='utf-8').read()
trans = open(trans_path, encoding='utf-8').read()
open(src_path + '.legacy.md', 'w', encoding='utf-8').write(src + '\n$\\(N\\)$\n')
open(trans_path + '.legacy.md', 'w', encoding='utf-8').write(
    trans + '\n$\\(N\\)$\n')
open(trans_path + '.newwrap.md', 'w', encoding='utf-8').write(
    trans + '\n$\\(N\\)$\n')
open(src_path + '.newwrap.md', 'w', encoding='utf-8').write(src + '\n$N$\n')
open(trans_path + '.note.md', 'w', encoding='utf-8').write(
    trans + '\n译注 $n^{2}$ 说明。\n')
PY
python3 "$VERIFY" "$TMPDIR/math_reference_translated.md.legacy.md" \
    "$TMPDIR/math_source.md.legacy.md" cuBLAS CUDA nvcc
if python3 "$VERIFY" "$TMPDIR/math_reference_translated.md.newwrap.md" \
    "$TMPDIR/math_source.md.newwrap.md" cuBLAS CUDA nvcc \
    >"$TMPDIR/math_wrap_err.txt" 2>&1; then
  echo "错误：新增历史包装未被检测到"
  exit 1
fi
grep -q '历史数学包装变化' "$TMPDIR/math_wrap_err.txt" \
  || { echo "错误：缺少包装变化诊断"; cat "$TMPDIR/math_wrap_err.txt"; exit 1; }
echo "一致历史包装保持通过；新增包装已正确判 FAIL"
if python3 "$VERIFY" "$TMPDIR/math_reference_translated.md.note.md" \
    "$TMPDIR/math_source.md" cuBLAS CUDA nvcc; then
  echo "错误：未获准译注公式未被检测到"
  exit 1
fi
python3 "$VERIFY" "$TMPDIR/math_reference_translated.md.note.md" \
    "$TMPDIR/math_source.md" cuBLAS CUDA nvcc \
    --approved-extra-math 'n^{2}'
echo "获准译注公式按显式清单豁免；未获准译注已正确判 FAIL"

echo "==> 完整性-04：命名标签脚注整对删除必须判 FAIL"
python3 - "$TMPDIR" <<'PY'
import sys

tmp = sys.argv[1]
src = '# 3. FN Sample\n\n引用[^1]和[^note]。\n\n[^1]: 一\n[^note]: 说明\n'
open(tmp + '/fn_src.md', 'w', encoding='utf-8').write(src)
open(tmp + '/fn_ok.md', 'w', encoding='utf-8').write(
    '# 3. FN Sample（脚注样本）\n\n引用[^1]和[^note]。\n\n[^1]: 一\n[^note]: 说明\n')
open(tmp + '/fn_pair_del.md', 'w', encoding='utf-8').write(
    '# 3. FN Sample（脚注样本）\n\n引用和[^note]。\n\n[^note]: 说明\n')
PY
python3 "$VERIFY" "$TMPDIR/fn_ok.md" "$TMPDIR/fn_src.md"
if python3 "$VERIFY" "$TMPDIR/fn_pair_del.md" "$TMPDIR/fn_src.md" \
    >"$TMPDIR/fn_del_err.txt" 2>&1; then
  echo "错误：整对脚注删除未被检测到"
  exit 1
fi
grep -q '\[^1\]' "$TMPDIR/fn_del_err.txt" \
  || { echo "错误：缺少脚注整对删除诊断"; cat "$TMPDIR/fn_del_err.txt"; exit 1; }
echo "命名标签脚注整对删除已正确判 FAIL"

echo "==> 完整性-05：参考手册热链与交付缺失图片必须判 FAIL"
python3 - "$TMPDIR/nested_reference_translated.md" "$TMPDIR" <<'PY'
import sys

path, tmp = sys.argv[1:3]
text = open(path, encoding='utf-8').read()
needle = '![List figure](images/thread_hierarchy.png)'
assert needle in text
open(tmp + '/ref_hotlink.md', 'w', encoding='utf-8').write(
    text.replace(needle, '![List figure](https://cdn.example/x.png)'))
open(tmp + '/ref_missing.md', 'w', encoding='utf-8').write(
    text.replace(needle, '![List figure](images/not-delivered.png)'))
PY
if python3 "$VERIFY" "$TMPDIR/ref_hotlink.md" "$TMPDIR/nested_source.md" \
    __global__ threadIdx.x cudaMalloc >"$TMPDIR/hotlink_err.txt" 2>&1; then
  echo "错误：热链未被检测到"
  exit 1
fi
grep -q '外链' "$TMPDIR/hotlink_err.txt" \
  || { echo "错误：缺少热链诊断"; cat "$TMPDIR/hotlink_err.txt"; exit 1; }
if python3 "$VERIFY" "$TMPDIR/ref_missing.md" "$TMPDIR/nested_source.md" \
    __global__ threadIdx.x cudaMalloc; then
  echo "错误：交付缺失图片未被检测到"
  exit 1
fi
echo "热链与交付缺失图片已正确判 FAIL"

echo "==> Ticket 03 回归全部通过"
