#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PARSE="../skills/tech-doc-translator/scripts/parse_single_page_html.py"
VERIFY="../skills/tech-doc-translator/scripts/verify_translation.py"
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
python3 - "$TMP/sample_source.md" "$TMP/sample_translated.md" "$TMP/fc_source.md" "$TMP/sample_fenced_comment.md" <<'PY'
import sys

src_path, trans_path, fc_src_path, fc_trans_path = sys.argv[1:5]
block = '\n```python\n# 这是代码注释，不是 H1\nprint("ok")\n```\n'
# 源与译文同步追加同一代码块：注释必须在标题检测中被排除，且代码逐块一致
src = open(src_path, encoding='utf-8').read()
open(fc_src_path, 'w', encoding='utf-8').write(src + block)
text = open(trans_path, encoding='utf-8').read()
open(fc_trans_path, 'w', encoding='utf-8').write(text + block)
PY
python3 "$VERIFY" "$TMP/sample_fenced_comment.md" "$TMP/fc_source.md" \
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

echo "==> V0.2-02：解析期图片显示尺寸（内联 CSS / HTML 属性 / 未确定）"
cp fixtures/valid_1x1.png "$TMP/img_px.png" "$TMP/img_attr.png" 2>/dev/null || {
  cp fixtures/valid_1x1.png "$TMP/img_px.png"; cp fixtures/valid_1x1.png "$TMP/img_attr.png"; }
cat > "$TMP/widths.html" <<'HTML'
<html><body><article>
<h1>Widths</h1>
<img src="img_px.png" style="width:454px">
<img src="img_attr.png" width="300">
<img src="img_free.png">
</article></body></html>
HTML
python3 "$PARSE" "$TMP/widths.html" "$TMP/widths.md"
python3 - "$TMP/widths.images_display.json" <<'PY'
import json, sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
entries = {e['occurrence']: e for e in payload['entries']}
assert entries[1]['width'] == {
    'value': 454, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None
}, entries[1]
assert entries[2]['width']['basis'] == 'html-width-attribute', entries[2]
assert entries[2]['width']['value'] == 300, entries[2]
assert [e['reason'] for e in payload['undetermined']] == ['源节点无宽度约束'], payload
assert all('resource_sha256' in e for e in payload['entries']), \
    '确定尺寸条目缺少独立来源资源身份：' + repr(payload['entries'])
print('宽度提取：内联 px / HTML 属性正确；无约束单列未确定')
PY

echo "==> 完整性-01：外层长围栏包含短围栏/H2/美元/图片语法/分隔线的正确译文保持通过"
cp fixtures/valid_1x1.png "$TMP/images/nested.png"
python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
f3, f4 = '`' * 3, '`' * 4
src = (
    '# 6. Complex Fencing Guide\n'
    '\n'
    'This section shows nested fences.\n'
    '\n'
    '## 6.1. Nested Fences\n'
    '\n'
    + f4 + 'text\n'
    + f3 + 'python\n'
    'print("inner fence")\n'
    + f3 + '\n'
    '## not a heading\n'
    '---\n'
    '$x$\n'
    '![img](images/nested.png)\n'
    + f4 + '\n'
    '\n'
    '~~~\n'
    'tilde fenced\n'
    '~~~\n'
)
trans = (
    '# 6. Complex Fencing Guide（复杂围栏指南）\n'
    '\n'
    '本节展示嵌套围栏。\n'
    '\n'
    '## 6.1. Nested Fences（嵌套围栏）\n'
    '\n'
    + f4 + 'text\n'
    + f3 + 'python\n'
    'print("inner fence")\n'
    + f3 + '\n'
    '## not a heading\n'
    '---\n'
    '$x$\n'
    '![img](images/nested.png)\n'
    + f4 + '\n'
    '\n'
    '~~~\n'
    'tilde fenced\n'
    '~~~\n'
)
open(tmp + '/complex_src.md', 'w', encoding='utf-8').write(src)
open(tmp + '/complex_trans.md', 'w', encoding='utf-8').write(trans)
PY
python3 "$VERIFY" "$TMP/complex_trans.md" "$TMP/complex_src.md" \
  "6. Complex Fencing Guide" "6.1. Nested Fences"

echo "==> 完整性-01 失败回归：代码内容/空白/语言标签/顺序/围栏边界篡改必须判 FAIL"
python3 - "$TMP/complex_trans.md" "$TMP/complex_bad_body.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace('print("inner fence")', 'print("inner fence v2")'))
PY
if python3 "$VERIFY" "$TMP/complex_bad_body.md" "$TMP/complex_src.md" \
    "6. Complex Fencing Guide" "6.1. Nested Fences" \
    >"$TMP/complex_body_err.txt" 2>&1; then
  echo "错误：代码内容篡改未被检测到"
  exit 1
fi
grep -q '正文第 2 行不一致' "$TMP/complex_body_err.txt" \
  || { echo "错误：缺少代码正文差异诊断"; cat "$TMP/complex_body_err.txt"; exit 1; }
echo "代码内容篡改已正确判 FAIL（含逐块差异诊断）"

python3 - "$TMP/complex_trans.md" "$TMP/complex_bad_lang.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
f4 = '`' * 4
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace(f4 + 'text\n', f4 + 'md\n'))
PY
if python3 "$VERIFY" "$TMP/complex_bad_lang.md" "$TMP/complex_src.md" \
    "6. Complex Fencing Guide" "6.1. Nested Fences" \
    >"$TMP/complex_lang_err.txt" 2>&1; then
  echo "错误：语言标签篡改未被检测到"
  exit 1
fi
grep -q '开启行不一致' "$TMP/complex_lang_err.txt" \
  || { echo "错误：缺少开启行差异诊断"; cat "$TMP/complex_lang_err.txt"; exit 1; }
echo "语言标签篡改已正确判 FAIL"

python3 - "$TMP/complex_trans.md" "$TMP/complex_bad_space.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace('tilde fenced\n', 'tilde fenced  \n'))
PY
if python3 "$VERIFY" "$TMP/complex_bad_space.md" "$TMP/complex_src.md" \
    "6. Complex Fencing Guide" "6.1. Nested Fences"; then
  echo "错误：代码空白篡改未被检测到"
  exit 1
fi
echo "代码空白篡改已正确判 FAIL"

python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
f3 = '`' * 3
src = ('# 7. Order Sample\n\n' + f3 + 'c\nreturn 1;\n' + f3 + '\n\nmid text\n\n'
       + f3 + 'py\nreturn 2;\n' + f3 + '\n')
trans = ('# 7. Order Sample（顺序样本）\n\n' + f3 + 'py\nreturn 2;\n' + f3
         + '\n\n中段文本\n\n' + f3 + 'c\nreturn 1;\n' + f3 + '\n')
open(tmp + '/order_src.md', 'w', encoding='utf-8').write(src)
open(tmp + '/order_trans.md', 'w', encoding='utf-8').write(trans)
PY
if python3 "$VERIFY" "$TMP/order_trans.md" "$TMP/order_src.md" \
    "7. Order Sample" >"$TMP/order_err.txt" 2>&1; then
  echo "错误：代码块顺序交换未被检测到"
  exit 1
fi
grep -q '开启行不一致' "$TMP/order_err.txt" \
  || { echo "错误：缺少顺序差异诊断"; cat "$TMP/order_err.txt"; exit 1; }
echo "代码块顺序交换已正确判 FAIL"

python3 - "$TMP/order_src.md" "$TMP/order_trans.md" "$TMP/order_bad_ret.md" <<'PY'
import sys

trans_path, out_path = sys.argv[2:4]
trans = open(trans_path, encoding='utf-8').read()
assert 'return 1;' in trans, '回归样本缺少目标代码行'
# 顺序正确但改返回值：必须因正文差异失败
open(out_path, 'w', encoding='utf-8').write(
    trans.replace('return 1;', 'return 2;'))
PY
if python3 "$VERIFY" "$TMP/order_bad_ret.md" "$TMP/order_src.md" \
    "7. Order Sample" >"$TMP/order_ret_err.txt" 2>&1; then
  echo "错误：返回值篡改未被检测到"
  exit 1
fi
grep -q '正文第 1 行不一致' "$TMP/order_ret_err.txt" \
  || { echo "错误：缺少返回值差异诊断"; cat "$TMP/order_ret_err.txt"; exit 1; }
echo "返回值篡改已正确判 FAIL"

python3 - "$TMP/complex_trans.md" "$TMP/complex_bad_close.md" <<'PY'
import sys

text = open(sys.argv[1], encoding='utf-8').read()
f4 = '`' * 4
open(sys.argv[2], 'w', encoding='utf-8').write(
    text.replace(f4 + '\n', '`' * 3 + '\n'))
PY
if python3 "$VERIFY" "$TMP/complex_bad_close.md" "$TMP/complex_src.md" \
    "6. Complex Fencing Guide" "6.1. Nested Fences"; then
  echo "错误：围栏边界篡改未被检测到"
  exit 1
fi
echo "围栏边界篡改已正确判 FAIL"

echo "==> 完整性-01 失败回归：缺源必须报告输入不足，不得跳过检查"
if python3 "$VERIFY" "$TMP/sample_translated.md" "$TMP/missing_source.md" \
    "1. Compute Kernel Basics" \
    "1.1. Thread Hierarchy" \
    "1.1.1. Memory Model" >"$TMP/missing_src_err.txt" 2>&1; then
  echo "错误：缺源未被报为输入不足"
  exit 1
fi
grep -q '源文缺失' "$TMP/missing_src_err.txt" \
  || { echo "错误：缺源诊断缺失"; cat "$TMP/missing_src_err.txt"; exit 1; }
echo "缺源已正确判 FAIL"

echo "==> 完整性-02：货币/转义/行内代码不进入公式预期；获准译注公式豁免"
python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
f3 = '`' * 3
src = ('# 8. Math Adjacency\n\n'
       '价格为 $5 和 $10，成本 \\$3。代码 `$x$` 保持原样。\n\n'
       '真实公式 $a+b$ 在此。\n')
trans = ('# 8. Math Adjacency（数学邻接）\n\n'
         '价格为 $5 和 $10，成本 \\$3。代码 `$x$` 保持原样。\n\n'
         '真实公式 $a+b$ 在此。\n\n译注 $n^{2}$ 说明。\n')
open(tmp + '/mathadj_src.md', 'w', encoding='utf-8').write(src)
open(tmp + '/mathadj_trans.md', 'w', encoding='utf-8').write(trans)
open(tmp + '/mathadj_swap.md', 'w', encoding='utf-8').write(
    trans.replace('$a+b$', '$b+a$'))
PY
if python3 "$VERIFY" "$TMP/mathadj_trans.md" "$TMP/mathadj_src.md" \
    "8. Math Adjacency"; then
  echo "错误：未获准译注公式未被检测到"
  exit 1
fi
python3 "$VERIFY" "$TMP/mathadj_trans.md" "$TMP/mathadj_src.md" \
    "8. Math Adjacency" --approved-extra-math 'n^{2}'
if python3 "$VERIFY" "$TMP/mathadj_swap.md" "$TMP/mathadj_src.md" \
    "8. Math Adjacency"; then
  echo "错误：公式内容篡改未被检测到"
  exit 1
fi
echo "货币/转义/行内代码不误报；译注豁免与公式篡改检出均 PASS"

echo "==> 完整性-04：标题层级/弯引号/整对脚注/强 token/片段模式"
python3 - "$TMP/sample_translated.md" "$TMP" <<'PY'
import sys

src_path, tmp = sys.argv[1], sys.argv[2]
text = open(src_path, encoding='utf-8').read()
open(tmp + '/lvl_bad.md', 'w', encoding='utf-8').write(
    text.replace('## 1.1. Thread Hierarchy（线程层次结构）',
                 '### 1.1. Thread Hierarchy（线程层次结构）'))
PY
if python3 "$VERIFY" "$TMP/lvl_bad.md" "$TMP/sample_source.md" \
    "1. Compute Kernel Basics" >"$TMP/lvl_err.txt" 2>&1; then
  echo "错误：标题层级变化未被检测到"
  exit 1
fi
grep -q '层级不一致' "$TMP/lvl_err.txt" \
  || { echo "错误：缺少层级差异诊断"; cat "$TMP/lvl_err.txt"; exit 1; }
echo "标题层级变化已正确判 FAIL"

python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
src = '# 8. It’s Here\n\n正文含强 token cublasSgemm 与脚注[^1]。\n\n[^1]: 注\n'
trans = '# 8. It’s Here（在此）\n\n正文含强 token cublasSgemm 与脚注[^1]。译注[^n1]。\n\n[^1]: 注\n[^n1]: 译注\n'
open(tmp + '/t8_src.md', 'w', encoding='utf-8').write(src)
open(tmp + '/t8_ok.md', 'w', encoding='utf-8').write(trans)
open(tmp + '/t8_quote.md', 'w', encoding='utf-8').write(
    trans.replace('It’s Here', "It's Here"))
open(tmp + '/t8_token.md', 'w', encoding='utf-8').write(
    trans.replace('cublasSgemm', ''))
open(tmp + '/t8_fn.md', 'w', encoding='utf-8').write(
    trans.replace('与脚注[^1]', '').replace('[^1]: 注\n', ''))
PY
python3 "$VERIFY" "$TMP/t8_ok.md" "$TMP/t8_src.md" "8. It’s Here" \
    --strong-token cublasSgemm
if python3 "$VERIFY" "$TMP/t8_quote.md" "$TMP/t8_src.md" "8. It’s Here" \
    >"$TMP/quote_err.txt" 2>&1; then
  echo "错误：弯引号改变未被检测到"
  exit 1
fi
grep -q '标题核对' "$TMP/quote_err.txt" \
  || { echo "错误：缺少弯引号差异诊断"; cat "$TMP/quote_err.txt"; exit 1; }
echo "原题弯引号改变已正确判 FAIL"
if python3 "$VERIFY" "$TMP/t8_token.md" "$TMP/t8_src.md" "8. It’s Here" \
    --strong-token cublasSgemm >"$TMP/token_err.txt" 2>&1; then
  echo "错误：强 token 遗漏未被检测到"
  exit 1
fi
grep -q '强 token' "$TMP/token_err.txt" \
  || { echo "错误：缺少强 token 诊断"; cat "$TMP/token_err.txt"; exit 1; }
echo "强 token 遗漏已正确判 FAIL"
if python3 "$VERIFY" "$TMP/t8_fn.md" "$TMP/t8_src.md" "8. It’s Here" \
    >"$TMP/fn_err.txt" 2>&1; then
  echo "错误：整对脚注删除未被检测到"
  exit 1
fi
grep -q '整对\|引用缺失\|定义缺失' "$TMP/fn_err.txt" \
  || { echo "错误：缺少脚注差异诊断"; cat "$TMP/fn_err.txt"; exit 1; }
echo "整对脚注删除已正确判 FAIL"
python3 "$VERIFY" "$TMP/t8_ok.md" "$TMP/t8_src.md" 2>&1 | grep -q '未配置' \
  || { echo "错误：未配置强 token 未明示"; exit 1; }
echo "未配置强 token 明示未检查 PASS"

cat > "$TMP/frag_ok.md" <<'EOF'
## 1.1. Thread Hierarchy（线程层次结构）

片段正文，无 H1。
EOF
cat > "$TMP/frag_src.md" <<'EOF'
## 1.1. Thread Hierarchy

片段正文。
EOF
cat > "$TMP/frag_bad.md" <<'EOF'
## 1.2. Memory Model（内存模型）

片段正文。
EOF
python3 "$VERIFY" "$TMP/frag_ok.md" "$TMP/frag_src.md" \
    "1.1. Thread Hierarchy" --fragment
if python3 "$VERIFY" "$TMP/frag_bad.md" "$TMP/frag_src.md" \
    "1.1. Thread Hierarchy" --fragment >"$TMP/frag_err.txt" 2>&1; then
  echo "错误：片段缺失预期标题未被检测到"
  exit 1
fi
echo "片段模式：无 H1 合法片段通过；缺预期标题已正确判 FAIL"

echo "==> 完整性-04b：片段模式仍逐项对照源标题（层级/删除/改题均 FAIL）"
cat > "$TMP/frag_level.md" <<'EOF'
### 1.1. Thread Hierarchy（线程层次结构）

片段正文，无 H1。
EOF
cat > "$TMP/frag_del.md" <<'EOF'
片段正文，标题被删除。
EOF
cat > "$TMP/frag_wrong.md" <<'EOF'
### 1.1. Wrong（错）

片段正文，无 H1。
EOF
for case in frag_level frag_del frag_wrong; do
  if python3 "$VERIFY" "$TMP/$case.md" "$TMP/frag_src.md" \
      --fragment >"$TMP/$case.err" 2>&1; then
    echo "错误：片段模式 $case 场景未被检测到"
    exit 1
  fi
  grep -q '标题核对' "$TMP/$case.err" \
    || { echo "错误：$case 缺少标题核对诊断"; cat "$TMP/$case.err"; exit 1; }
done
python3 "$VERIFY" "$TMP/frag_ok.md" "$TMP/frag_src.md" --fragment
echo "片段模式免检路径已封堵：层级/删除/改题 FAIL；合法片段（无官方清单）PASS"

echo "==> 完整性-04c：深层标题 H7/H8 不被截断，删除即 FAIL"
cat > "$TMP/deep_src.md" <<'EOF'
# 1. Deep

## 1.1. Branch

####### 1.1.1. Deep Seven

内容七。

######## 1.1.2. Deep Eight

内容八。
EOF
cat > "$TMP/deep_ok.md" <<'EOF'
# 1. Deep（深层）

## 1.1. Branch（分支）

####### 1.1.1. Deep Seven（七级）

内容七。

######## 1.1.2. Deep Eight（八级）

内容八。
EOF
cat > "$TMP/deep_del.md" <<'EOF'
# 1. Deep（深层）

## 1.1. Branch（分支）

内容七。

内容八。
EOF
python3 "$VERIFY" "$TMP/deep_ok.md" "$TMP/deep_src.md" \
    "1. Deep" "1.1. Branch" "1.1.1. Deep Seven" "1.1.2. Deep Eight"
if python3 "$VERIFY" "$TMP/deep_del.md" "$TMP/deep_src.md" \
    "1. Deep" "1.1. Branch" >"$TMP/deep_err.txt" 2>&1; then
  echo "错误：删除 H7/H8 未被检测到"
  exit 1
fi
echo "H7/H8 合法双语标题 PASS；删除 H7/H8 已正确判 FAIL"

echo "==> 完整性-05：离线图片核验（外链/绝对路径/cwd 伪匹配/伪图/空文件/身份/搬迁）"
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
# 伪图与空文件
os.makedirs(tmp + '/images', exist_ok=True)
with open(tmp + '/images/fake.png', 'wb') as f:
    f.write(b'<html><body>404 not found</body></html>')
with open(tmp + '/images/empty.png', 'wb') as f:
    f.write(b'')
# SVG 有效版本与含外部依赖版本
with open(tmp + '/images/vec.svg', 'w', encoding='utf-8') as f:
    f.write('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')
with open(tmp + '/images/bad.svg', 'w', encoding='utf-8') as f:
    f.write('<svg><image href="https://cdn.example/x.png"/></svg>')
# 评审 P2-8：无效 XML / 缺失本地依赖 / 单引号命名空间
with open(tmp + '/images/notxml.svg', 'w', encoding='utf-8') as f:
    f.write('<svg this is not valid xml')
with open(tmp + '/images/depmissing.svg', 'w', encoding='utf-8') as f:
    f.write('<svg xmlns="http://www.w3.org/2000/svg">'
            '<image href="missing_local.png"/></svg>')
with open(tmp + '/images/sq.svg', 'w', encoding='utf-8') as f:
    f.write("<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>")
# 图片对账与混合语法样例图（内容不同，身份可区分）
with open(tmp + '/images/m1.png', 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n' + b'M' * 32)
with open(tmp + '/images/m2.png', 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n' + b'N' * 32)
# cwd 伪匹配：文档位于子目录，引用只在上层目录存在的图片
os.makedirs(tmp + '/sub/images', exist_ok=True)
text = open(tmp + '/sample_translated.md', encoding='utf-8').read()
open(tmp + '/sub/doc.md', 'w', encoding='utf-8').write(
    text.replace('images/thread_hierarchy.png', 'thread_hierarchy.png'))
src_text = open(tmp + '/sample_source.md', encoding='utf-8').read()
# 源同样改用 SVG 的基准源文件：本地化后源译逐项一致才可身份通过
open(tmp + '/svg_src.md', 'w', encoding='utf-8').write(src_text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/vec.svg)'))
open(tmp + '/svg_sq_src.md', 'w', encoding='utf-8').write(src_text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/sq.svg)'))
open(tmp + '/hotlink.md', 'w', encoding='utf-8').write(
    text.replace('images/thread_hierarchy.png',
                 'https://cdn.example/thread_hierarchy.png'))
open(tmp + '/abs.md', 'w', encoding='utf-8').write(
    text.replace('images/thread_hierarchy.png', '/etc/machine.png'))
open(tmp + '/fakeimg.md', 'w', encoding='utf-8').write(
    text.replace('images/thread_hierarchy.png', 'images/fake.png'))
open(tmp + '/emptyimg.md', 'w', encoding='utf-8').write(
    text.replace('images/thread_hierarchy.png', 'images/empty.png'))
open(tmp + '/svg_ok.md', 'w', encoding='utf-8').write(text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/vec.svg)'))
open(tmp + '/svg_bad.md', 'w', encoding='utf-8').write(text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/bad.svg)'))
open(tmp + '/svg_notxml.md', 'w', encoding='utf-8').write(text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/notxml.svg)'))
open(tmp + '/svg_depmissing.md', 'w', encoding='utf-8').write(text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/depmissing.svg)'))
open(tmp + '/svg_sq.md', 'w', encoding='utf-8').write(text.replace(
    '![Thread hierarchy diagram](images/thread_hierarchy.png)',
    '![Vector](images/sq.svg)'))
# 代码内图片语法示例：引用了不存在的文件也不计入真实图片
code_block = '\n```markdown\n![示例](images/not-a-real-file.png)\n```\n'
src_text = open(tmp + '/sample_source.md', encoding='utf-8').read()
open(tmp + '/codeimg_src.md', 'w', encoding='utf-8').write(src_text + code_block)
open(tmp + '/codeimg_ok.md', 'w', encoding='utf-8').write(text + code_block)
PY
OFFICIAL_TITLES=("1. Compute Kernel Basics" "1.1. Thread Hierarchy" "1.1.1. Memory Model")
for case in hotlink abs fakeimg emptyimg; do
  if python3 "$VERIFY" "$TMP/$case.md" "$TMP/sample_source.md" \
      "${OFFICIAL_TITLES[@]}" >"$TMP/$case.err" 2>&1; then
    echo "错误：$case 场景未被检测到"
    exit 1
  fi
done
if python3 "$VERIFY" "$TMP/sub/doc.md" "$TMP/sample_source.md" \
    "${OFFICIAL_TITLES[@]}"; then
  echo "错误：cwd 伪匹配未被检测到"
  exit 1
fi
python3 "$VERIFY" "$TMP/svg_ok.md" "$TMP/svg_src.md" "${OFFICIAL_TITLES[@]}"
python3 "$VERIFY" "$TMP/svg_sq.md" "$TMP/svg_sq_src.md" "${OFFICIAL_TITLES[@]}"
if python3 "$VERIFY" "$TMP/svg_ok.md" "$TMP/sample_source.md" \
    "${OFFICIAL_TITLES[@]}" >"$TMP/svg_swap.err" 2>&1; then
  echo "错误：源 PNG 被换成不同内容 SVG（同数量换图）未被身份核验检出"
  exit 1
fi
grep -q '来源身份不符' "$TMP/svg_swap.err" \
  || { echo "错误：缺少换图身份诊断"; cat "$TMP/svg_swap.err"; exit 1; }
for case in svg_bad svg_notxml svg_depmissing; do
  if python3 "$VERIFY" "$TMP/$case.md" "$TMP/sample_source.md" \
      "${OFFICIAL_TITLES[@]}" >"$TMP/$case.err" 2>&1; then
    echo "错误：$case 场景未被检测到"
    exit 1
  fi
done
python3 "$VERIFY" "$TMP/codeimg_ok.md" "$TMP/codeimg_src.md" "${OFFICIAL_TITLES[@]}"
echo "外链/绝对路径/伪图/空文件/SVG 依赖均判 FAIL；代码内示例与有效 SVG PASS"

echo "==> 完整性-05b：源译图片出现次数对账常开（漏图必 FAIL，不依赖身份映射）"
cat > "$TMP/count_src.md" <<'EOF'
# 1. Count

## 1.1. Pics

![one](images/m1.png)

![two](images/m2.png)
EOF
cat > "$TMP/count_none.md" <<'EOF'
# 1. Count（计数）

## 1.1. Pics（图）

正文，图片全部丢失。
EOF
cat > "$TMP/count_part.md" <<'EOF'
# 1. Count（计数）

## 1.1. Pics（图）

![one](images/m1.png)

正文，少一张图。
EOF
cat > "$TMP/count_ok.md" <<'EOF'
# 1. Count（计数）

## 1.1. Pics（图）

![one](images/m1.png)

![two](images/m2.png)
EOF
if python3 "$VERIFY" "$TMP/count_none.md" "$TMP/count_src.md" \
    "1. Count" "1.1. Pics" >"$TMP/count_none.err" 2>&1; then
  echo "错误：整张漏图未被检测到"
  exit 1
fi
grep -q '图片对账.*FAIL' "$TMP/count_none.err" \
  || { echo "错误：缺少图片对账诊断"; cat "$TMP/count_none.err"; exit 1; }
if python3 "$VERIFY" "$TMP/count_part.md" "$TMP/count_src.md" \
    "1. Count" "1.1. Pics" >"$TMP/count_part.err" 2>&1; then
  echo "错误：部分漏图未被检测到"
  exit 1
fi
grep -q '图片对账.*FAIL' "$TMP/count_part.err" \
  || { echo "错误：缺少部分漏图诊断"; cat "$TMP/count_part.err"; exit 1; }
python3 "$VERIFY" "$TMP/count_ok.md" "$TMP/count_src.md" \
    "1. Count" "1.1. Pics" | grep -q '出现次数一致' \
  || { echo "错误：合法图片未按出现次数通过"; exit 1; }
echo "整张漏图/部分漏图均 FAIL；合法未改名图片 PASS（未提供身份映射）"

echo "==> 完整性-05d：同数量交换图片必须被来源身份核验检出（不依赖 --image-map）"
cat > "$TMP/count_swap.md" <<'EOF'
# 1. Count（计数）

## 1.1. Pics（图）

![one](images/m2.png)

![two](images/m1.png)
EOF
if python3 "$VERIFY" "$TMP/count_swap.md" "$TMP/count_src.md" \
    "1. Count" "1.1. Pics" >"$TMP/count_swap.err" 2>&1; then
  echo "错误：同数量交换图片未被身份核验检出"
  exit 1
fi
grep -q '来源身份不符' "$TMP/count_swap.err" \
  || { echo "错误：缺少交换图片身份诊断"; cat "$TMP/count_swap.err"; exit 1; }
echo "同数量交换图片已被当前源资源身份核验判 FAIL"

echo "==> 完整性-05e：缺少必要身份依据时不得报告完整通过"
cat > "$TMP/orphan_src.md" <<'EOF'
# 1. Orphan

## 1.1. Pic

[IMG: snapshot/origin.png]
EOF
cat > "$TMP/orphan_ok.md" <<'EOF'
# 1. Orphan（孤图）

## 1.1. Pic（图）

![图](images/m1.png)
EOF
if python3 "$VERIFY" "$TMP/orphan_ok.md" "$TMP/orphan_src.md" \
    "1. Orphan" "1.1. Pic" >"$TMP/orphan_err.txt" 2>&1; then
  echo "错误：缺少身份依据仍报告完整通过"
  exit 1
fi
grep -q '来源身份未核验' "$TMP/orphan_err.txt" \
  || { echo "错误：缺少身份未核验阻断诊断"; cat "$TMP/orphan_err.txt"; exit 1; }
python3 - "$TMP" <<'PY'
import hashlib
import sys

tmp = sys.argv[1]
digest = hashlib.sha256(open(tmp + '/images/m1.png', 'rb').read()).hexdigest()
open(tmp + '/map_orphan.json', 'w').write('{"digests": ["%s"]}' % digest)
PY
python3 "$VERIFY" "$TMP/orphan_ok.md" "$TMP/orphan_src.md" \
    "1. Orphan" "1.1. Pic" --image-map "$TMP/map_orphan.json"
echo "无法证明身份时阻断完整通过；提供有效映射后 PASS"

echo "==> 完整性-05f：SVG 子资源纳入来源身份（换子资源必 FAIL，不依赖映射）"
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
ns = 'xmlns="http://www.w3.org/2000/svg"'
parent = '<svg %s><image href="child.svg"/></svg>' % ns
red = '<svg %s><rect fill="red"/></svg>' % ns
blue = '<svg %s><rect fill="blue"/></svg>' % ns
# 源目录与交付目录各自独立一份 parent→child 树
os.makedirs(tmp + '/svgdep_src/images', exist_ok=True)
open(tmp + '/svgdep_src/images/parent.svg', 'w').write(parent)
open(tmp + '/svgdep_src/images/child.svg', 'w').write(red)
open(tmp + '/images/parent.svg', 'w').write(parent)
open(tmp + '/images/child.svg', 'w').write(red)
needle = '![Thread hierarchy diagram](images/thread_hierarchy.png)'
src_text = open(tmp + '/sample_source.md', encoding='utf-8').read()
trans_text = open(tmp + '/sample_translated.md', encoding='utf-8').read()
open(tmp + '/svgdep_src/source.md', 'w', encoding='utf-8').write(
    src_text.replace(needle, '![Parent](images/parent.svg)'))
open(tmp + '/svgdep_ok.md', 'w', encoding='utf-8').write(
    trans_text.replace(needle, '![Parent](images/parent.svg)'))
PY
python3 "$VERIFY" "$TMP/svgdep_ok.md" "$TMP/svgdep_src/source.md" \
    "${OFFICIAL_TITLES[@]}"
# S2：切换 cwd 到不含图片资源的目录后用相对路径校验，依赖仍按文档目录
# 解析（不回退 cwd），结果与标准调用一致
VERIFY_ABS="$(cd "$(dirname "$VERIFY")" && pwd)/$(basename "$VERIFY")"
if (cd "$TMP/svgdep_src" && python3 "$VERIFY_ABS" ../svgdep_ok.md \
    source.md "${OFFICIAL_TITLES[@]}"); then
  echo "cwd 切换不影响依赖解析（按文档目录，不回退 cwd）PASS"
else
  echo "错误：外部 cwd 下校验失败，疑似 cwd 依赖"
  exit 1
fi
python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
blue = ('<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect fill="blue"/></svg>')
# 仅换译侧子资源，顶层 parent.svg 不变
open(tmp + '/images/child.svg', 'w').write(blue)
PY
if python3 "$VERIFY" "$TMP/svgdep_ok.md" "$TMP/svgdep_src/source.md" \
    "${OFFICIAL_TITLES[@]}" >"$TMP/svgdep_err.txt" 2>&1; then
  echo "错误：仅换译侧子资源未被来源身份核验检出"
  exit 1
fi
grep -q '来源身份不符' "$TMP/svgdep_err.txt" \
  || { echo "错误：缺少子资源身份诊断"; cat "$TMP/svgdep_err.txt"; exit 1; }
python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
red = ('<svg xmlns="http://www.w3.org/2000/svg">'
       '<rect fill="red"/></svg>')
open(tmp + '/images/child.svg', 'w').write(red)
PY
python3 "$VERIFY" "$TMP/svgdep_ok.md" "$TMP/svgdep_src/source.md" \
    "${OFFICIAL_TITLES[@]}"
echo "顶层 SVG 相同、子资源换图已被身份核验判 FAIL；源译依赖一致时 PASS"

echo "==> 完整性-05g：展示属性与 CSS 导入依赖纳入离线与身份核验"
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
ns = 'xmlns="http://www.w3.org/2000/svg"'
paint = '<svg %s><rect/></svg>' % ns
styled = ('<svg %s><style>@import "theme.css";</style>'
          '<rect fill="url(paint.svg#p)" stroke="url(paint.svg#p)"/></svg>'
          % ns)
for base in ('styled_src/', ''):
    os.makedirs(tmp + '/' + base + 'images', exist_ok=True)
    open(tmp + '/' + base + 'images/paint.svg', 'w').write(paint)
    open(tmp + '/' + base + 'images/theme.css', 'w').write(
        '.r { fill: url(paint.svg#p); }')
    open(tmp + '/' + base + 'images/styled.svg', 'w').write(styled)
needle = '![Thread hierarchy diagram](images/thread_hierarchy.png)'
src_text = open(tmp + '/sample_source.md', encoding='utf-8').read()
trans_text = open(tmp + '/sample_translated.md', encoding='utf-8').read()
open(tmp + '/styled_src/source.md', 'w', encoding='utf-8').write(
    src_text.replace(needle, '![Styled](images/styled.svg)'))
open(tmp + '/styled_ok.md', 'w', encoding='utf-8').write(
    trans_text.replace(needle, '![Styled](images/styled.svg)'))
PY
python3 "$VERIFY" "$TMP/styled_ok.md" "$TMP/styled_src/source.md" \
    "${OFFICIAL_TITLES[@]}"
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
os.remove(tmp + '/images/paint.svg')
PY
if python3 "$VERIFY" "$TMP/styled_ok.md" "$TMP/styled_src/source.md" \
    "${OFFICIAL_TITLES[@]}" >"$TMP/styled_err.txt" 2>&1; then
  echo "错误：展示属性/CSS 导入链上的缺失依赖未被检出"
  exit 1
fi
grep -q '本地依赖缺失' "$TMP/styled_err.txt" \
  || { echo "错误：缺少依赖缺失诊断"; cat "$TMP/styled_err.txt"; exit 1; }
echo "fill/stroke url(...) 与 @import 链上的缺失依赖均被拒绝（不联网）"

echo "==> 完整性-05h：合法伪 URL（CSS 字符串 / data-* 属性）源译一致时 CLI 通过"
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
ns = 'xmlns="http://www.w3.org/2000/svg"'
pseudo = ('<svg %s data-example="url(example.png)" '
          'aria-label="url(elsewhere.png)">'
          '<style>.a { content: "url(example.png)"; }</style>'
          '<desc>url(example.png) as text</desc>'
          '<rect fill="url(#local)"/></svg>' % ns)
for base in ('pseudo_src/', ''):
    os.makedirs(tmp + '/' + base + 'images', exist_ok=True)
    open(tmp + '/' + base + 'images/pseudo.svg', 'w').write(pseudo)
needle = '![Thread hierarchy diagram](images/thread_hierarchy.png)'
src_text = open(tmp + '/sample_source.md', encoding='utf-8').read()
trans_text = open(tmp + '/sample_translated.md', encoding='utf-8').read()
open(tmp + '/pseudo_src/source.md', 'w', encoding='utf-8').write(
    src_text.replace(needle, '![Pseudo](images/pseudo.svg)'))
open(tmp + '/pseudo_ok.md', 'w', encoding='utf-8').write(
    trans_text.replace(needle, '![Pseudo](images/pseudo.svg)'))
PY
python3 "$VERIFY" "$TMP/pseudo_ok.md" "$TMP/pseudo_src/source.md" \
    "${OFFICIAL_TITLES[@]}"
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
ns = 'xmlns="http://www.w3.org/2000/svg"'
# 同一伪 URL 样例加入真实缺失依赖后必须按具体原因失败
open(tmp + '/images/pseudo.svg', 'w').write(
    '<svg %s data-example="url(example.png)">'
    '<rect fill="url(really-missing.svg#p)"/></svg>' % ns)
PY
if python3 "$VERIFY" "$TMP/pseudo_ok.md" "$TMP/pseudo_src/source.md" \
    "${OFFICIAL_TITLES[@]}" >"$TMP/pseudo_err.txt" 2>&1; then
  echo "错误：加入真实缺失依赖后未被检出"
  exit 1
fi
grep -q '本地依赖缺失' "$TMP/pseudo_err.txt" \
  || { echo "错误：缺少真实依赖诊断"; cat "$TMP/pseudo_err.txt"; exit 1; }
echo "合法伪 URL 源译一致 CLI 通过；真实依赖缺失按所属引用 FAIL"

echo "==> 完整性-05c：同一行混合图片语法按源出现顺序核对身份"
cat > "$TMP/mix_src.md" <<'EOF'
# 1. Mix

## 1.1. Both

图示 ![A][a] 与 ![B](images/m2.png)。

[a]: images/m1.png
EOF
cat > "$TMP/mix_ok.md" <<'EOF'
# 1. Mix（混）

## 1.1. Both（两者）

图示 ![A](images/m1.png) 与 ![B](images/m2.png)。
EOF
cat > "$TMP/mix_swap.md" <<'EOF'
# 1. Mix（混）

## 1.1. Both（两者）

图示 ![A](images/m2.png) 与 ![B](images/m1.png)。
EOF
python3 - "$TMP" <<'PY'
import hashlib
import sys

tmp = sys.argv[1]
d1 = hashlib.sha256(open(tmp + '/images/m1.png', 'rb').read()).hexdigest()
d2 = hashlib.sha256(open(tmp + '/images/m2.png', 'rb').read()).hexdigest()
open(tmp + '/map_mix.json', 'w').write(
    '{"digests": ["%s", "%s"]}' % (d1, d2))
PY
python3 "$VERIFY" "$TMP/mix_ok.md" "$TMP/mix_src.md" \
    "1. Mix" "1.1. Both" --image-map "$TMP/map_mix.json"
if python3 "$VERIFY" "$TMP/mix_swap.md" "$TMP/mix_src.md" \
    "1. Mix" "1.1. Both" --image-map "$TMP/map_mix.json" \
    >"$TMP/mix_swap.err" 2>&1; then
  echo "错误：实际交换图片的译文未被身份顺序检出"
  exit 1
fi
grep -q '来源身份不符' "$TMP/mix_swap.err" \
  || { echo "错误：缺少身份顺序诊断"; cat "$TMP/mix_swap.err"; exit 1; }
echo "混合语法顺序：正确映射 PASS；交换图片 FAIL"

python3 - "$TMP" <<'PY'
import hashlib
import os
import sys

tmp = sys.argv[1]
digest = hashlib.sha256(
    open(tmp + '/images/thread_hierarchy.png', 'rb').read()).hexdigest()
open(tmp + '/map_ok.json', 'w').write(
    '{"digests": ["%s"]}' % digest)
open(tmp + '/map_bad.json', 'w').write(
    '{"digests": ["%s"]}' % ('0' * 64))
PY
python3 "$VERIFY" "$TMP/sample_translated.md" "$TMP/sample_source.md" \
    "${OFFICIAL_TITLES[@]}" --image-map "$TMP/map_ok.json"
if python3 "$VERIFY" "$TMP/sample_translated.md" "$TMP/sample_source.md" \
    "${OFFICIAL_TITLES[@]}" --image-map "$TMP/map_bad.json" \
    >"$TMP/map_err.txt" 2>&1; then
  echo "错误：来源身份不符未被检测到"
  exit 1
fi
grep -q '来源身份不符\|身份映射' "$TMP/map_err.txt" \
  || { echo "错误：缺少身份映射诊断"; cat "$TMP/map_err.txt"; exit 1; }
echo "图片身份映射：一致 PASS；不符已正确判 FAIL"

cp -R "$TMP" "$TMP/delivery2"
python3 - "$TMP" <<'PY'
import os
import subprocess
import sys

tmp = sys.argv[1]
verify = os.path.abspath('../skills/tech-doc-translator/scripts/verify_translation.py')
env = dict(os.environ, cwd=tmp + '/delivery2')
r = subprocess.run(
    ['python3', verify, 'sample_translated.md', 'sample_source.md',
     '1. Compute Kernel Basics', '1.1. Thread Hierarchy',
     '1.1.1. Memory Model'],
    cwd=tmp + '/delivery2', capture_output=True, text=True, env=env)
assert r.returncode == 0, r.stdout + r.stderr
print('交付树搬迁至第二目录并切换 cwd 后校验 PASS')
PY

echo "==> 翻译留痕 02/A1：临时输出准确告警、正常路径不误报、别名可解析"
NORMAL_BASE=$(mktemp -d "$HOME/.cache/tech-doc-a1-XXXXXX")
python3 "$PARSE" fixtures/rich_single_page.html "$NORMAL_BASE/normal.md" \
  2>"$TMP/a1_normal.err"
test -s "$TMP/a1_normal.err" \
  && { echo "错误：正常路径出现临时目录告警"; cat "$TMP/a1_normal.err"; exit 1; }
mkdir -p "$NORMAL_BASE/tmp_page"
python3 "$PARSE" fixtures/rich_single_page.html \
  "$NORMAL_BASE/tmp_page/normal.md" 2>>"$TMP/a1_normal.err"
test ! -s "$TMP/a1_normal.err" \
  || { echo "错误：名字相似的普通目录被误报"; cat "$TMP/a1_normal.err"; exit 1; }
python3 "$PARSE" fixtures/rich_single_page.html "$TMP/alias_target.md" \
  2>"$TMP/a1_temp.err"
test -s "$TMP/a1_temp.err" || { echo "错误：临时输出未告警"; exit 1; }
grep -q '系统临时目录' "$TMP/a1_temp.err" \
  || { echo "错误：告警未说明临时目录后果"; cat "$TMP/a1_temp.err"; exit 1; }
ln -s "$TMP" "$TMP/alias_link"
python3 "$PARSE" fixtures/rich_single_page.html "$TMP/alias_link/via.md" \
  2>>"$TMP/a1_temp.err"
grep -q 'via.md' "$TMP/a1_temp.err" \
  || { echo "错误：经符号链接别名落入临时目录未被解析识别"; cat "$TMP/a1_temp.err"; exit 1; }
rm -rf "$NORMAL_BASE"
echo "A1 临时/正常/别名对照 PASS（临时路径下调试仍成功退出）"

echo "==> 翻译留痕 01：富容器保真（高亮包装/行号/提示框/列表/details/定义项/含代码表格/脚注/C#）"
python3 "$PARSE" fixtures/rich_single_page.html "$TMP/rich_source.md"
python3 - "$TMP/rich_source.md" <<'PY'
import sys

sys.path.insert(0, '../skills/tech-doc-translator/scripts')
from _verification import scan_code_fences

text = open(sys.argv[1], encoding='utf-8').read()
bodies = [fence.body for fence in scan_code_fences(text).blocks]
expected = [
    'print("wrapped")',
    '#include <bar.h>\nint main() { return 10; }',
    'note_code()',
    'list_code()',
    'details_code()',
    'dd_code()',
    'table_code()',
]
assert bodies == expected, '代码块顺序或内容不符:\n%r\nvs\n%r' % (bodies, expected)
assert '<code>' not in text, '残留 <code> 包装'
assert 'linenos' not in text, '残留行号标记'
assert '## 1.1. C# Interop' in text, 'C# 标题被破坏或 headerlink 残留'
assert '¶' not in text, 'headerlink ¶ 残留'
assert 'literal <span> tag' in text, '行内字面 <span> 丢失'
assert 'C# style' in text, '行内代码 C# 丢失'
assert text.index('> note text before code') < text.index('note_code()') \
    < text.index('> note text after code'), '提示框内代码与说明乱序'
assert text.index('- item with code') < text.index('list_code()') \
    < text.index('item tail'), '列表项内代码与说明乱序'
assert '[DETAILS] expand me' in text and 'details_code()' in text, 'details 结构丢失'
assert '[TABLE-CODE r=2 c=2#1]' in text, '含代码表格缺少行列定位'
assert '[^1]' in text and '[[1]] footnote body text' in text, '脚注引用/定义丢失'
print('富容器保真正例 PASS')
PY

echo "==> 翻译留痕 01：独立对账损伤必须定位（漏代码/等数换内容/乱序/重复/删图）"
python3 - fixtures/rich_single_page.html "$TMP/rich_source.md" <<'PY'
import sys

sys.path.insert(0, '../skills/tech-doc-translator/scripts')
from _source_reconcile import reconcile_html_to_markdown

raw = open(sys.argv[1], encoding='utf-8').read()
md = open(sys.argv[2], encoding='utf-8').read()
assert reconcile_html_to_markdown(raw, md, 'single') == [], '正确解析被误判为损伤'

def damaged(name, transform, expect):
    diffs = reconcile_html_to_markdown(raw, transform(md), 'single')
    assert diffs, '%s 未被对账检出' % name
    assert any(expect in d for d in diffs), \
        '%s 诊断未定位（%r）' % (name, diffs[:3])
    print('对账损伤 %s: %s' % (name, diffs[0]))

damaged('漏代码',
        # 项内围栏按层级缩进
        lambda t: t.replace('  ```\nlist_code()\n  ```\n', ''),
        '数量不一致')
damaged('等数换内容',
        lambda t: t.replace('print("wrapped")', 'print("changed")'),
        '第 1 项不一致')
damaged('换标题', lambda t: t.replace('C# Interop', 'C Sharp Interop'),
        '第 2 项不一致')
damaged('乱序', lambda t: t.replace('note_code()', '@@TMP@@')
        .replace('list_code()', 'note_code()').replace('@@TMP@@', 'list_code()'),
        '第 3 项不一致')
damaged('重复块', lambda t: t.replace(
        # 项内围栏按层级缩进
        '  ```\nlist_code()\n  ```',
        '  ```\nlist_code()\n  ```\n\n  ```\nlist_code()\n  ```'),
    '数量不一致')
PY

echo "==> 翻译留痕 01：A28 草稿预检（工作区外候选回填 + 目标路径资源检查）"
python3 - "$TMP" <<'PY'
import hashlib
import os
import sys

sys.path.insert(0, '../skills/tech-doc-translator/scripts')
import splice_fences
from verify_translation import run_checks

tmp = sys.argv[1]
translated = open(tmp + '/sample_translated.md', encoding='utf-8').read()
source = open(tmp + '/sample_source.md', encoding='utf-8').read()

# 草稿：围栏替换为占位符；候选与最终图片目录分离
draft_lines = []
in_fence = False
for line in translated.split('\n'):
    stripped = line.strip()
    if not in_fence and stripped.startswith('```'):
        in_fence = True
        draft_lines.append('⟦CODE⟧')
        continue
    if in_fence:
        if stripped == '```':
            in_fence = False
        continue
    draft_lines.append(line)
assert not in_fence, '译文围栏不配对'
draft = '\n'.join(draft_lines)
os.makedirs(tmp + '/cand', exist_ok=True)
open(tmp + '/draft.md', 'w', encoding='utf-8').write(draft)
draft_digest = hashlib.sha256(draft.encode()).hexdigest()
assert '⟦CODE⟧' in draft, '草稿必须含占位符'

import contextlib
import io

def splice(draft_path, src_path, out_path):
    argv = sys.argv
    sys.argv = ['splice_fences.py', draft_path, src_path, out_path]
    try:
        splice_fences.main()
    finally:
        sys.argv = argv

with contextlib.redirect_stdout(io.StringIO()):
    splice(tmp + '/draft.md', tmp + '/sample_source.md',
           tmp + '/cand/candidate.md')
candidate = open(tmp + '/cand/candidate.md', encoding='utf-8').read()
from _verification import scan_code_fences
cand_bodies = [f.body for f in scan_code_fences(candidate).blocks]
src_bodies = [f.body for f in scan_code_fences(source).blocks]
assert cand_bodies == src_bodies, '回填候选围栏正文应与源逐字节一致'
assert '⟦CODE⟧' not in candidate, '回填后不得残留占位符'
assert hashlib.sha256(draft.encode()).hexdigest() == draft_digest, \
    '预检不得修改原草稿'

official = ['1. Compute Kernel Basics', '1.1. Thread Hierarchy',
            '1.1.1. Memory Model']
fail, lines = run_checks(
    candidate, source, official,
    doc_dir=os.path.abspath(tmp),  # 资源按最终目标目录定位
    doc_label='cand/candidate.md（临时候选）',
    src_label=tmp + '/sample_source.md')
assert fail == 0, '正确草稿候选预检应通过:\n%s' % '\n'.join(lines)
print('A28 正确草稿：候选回填一致、原草稿不变、按目标路径核验 PASS')

# 负例 1：占位数量错误 → splice 拒绝
open(tmp + '/draft_short.md', 'w', encoding='utf-8').write(
    draft.replace('⟦CODE⟧\n', '', 1))
try:
    with contextlib.redirect_stdout(io.StringIO()):
        splice(tmp + '/draft_short.md', tmp + '/sample_source.md',
               tmp + '/cand/bad.md')
    raise AssertionError('占位数量错误未被 splice 拒绝')
except AssertionError as exc:
    if '占位' not in str(exc) and '围栏' not in str(exc):
        raise
print('A28 负例：占位数量错误被 splice 拒绝 PASS')

# 负例 2：公式等数改符号
bad_math = candidate
if '$N$' in bad_math:
    bad_math = bad_math.replace('$N$', '$M$')
else:
    bad_math = bad_math.replace('GPU', 'GPU$')
fail, lines = run_checks(
    bad_math, source, official, doc_dir=os.path.abspath(tmp),
    doc_label='bad_math.md', src_label=tmp + '/sample_source.md')
assert fail > 0, '公式损伤未被拒绝'
print('A28 负例：公式等数改符号被拒绝 PASS')

# 负例 3：错误图片身份（候选引用同名目录中另一张真实图片）
imp1 = open('fixtures/valid_1x1.png', 'rb').read()
os.makedirs(tmp + '/images', exist_ok=True)
open(tmp + '/images/imposter.png', 'wb').write(imp1 + b'\x00')
bad_img = candidate.replace('images/thread_hierarchy.png',
                            'images/imposter.png')
fail, lines = run_checks(
    bad_img, source, official, doc_dir=os.path.abspath(tmp),
    doc_label='bad_img.md', src_label=tmp + '/sample_source.md')
assert fail > 0 and any('来源身份不符' in l for l in lines), \
    '错误图片身份未被拒绝:\n%s' % '\n'.join(lines)
print('A28 负例：错误图片身份被拒绝 PASS')

# 负例 4：残留解析标记
bad_mark = candidate + '\n[TABLE]\n'
fail, lines = run_checks(
    bad_mark, source, official, doc_dir=os.path.abspath(tmp),
    doc_label='bad_mark.md', src_label=tmp + '/sample_source.md')
assert fail > 0 and any('[TABLE]' in l for l in lines), '残留标记未被拒绝'
print('A28 负例：残留解析标记被拒绝 PASS')

# 四反引号/波浪线复杂围栏回填
quad_src = '''# T

intro

~~~~
code_tilde()
~~~~

````python
code_quad("with ~~~ inside")
````

tail [^1]

[^1]: note
'''
draft_quad = quad_src.replace('~~~~\ncode_tilde()\n~~~~', '⟦CODE⟧') \
    .replace('````python\ncode_quad("with ~~~ inside")\n````', '⟦CODE⟧')
open(tmp + '/quad_src.md', 'w', encoding='utf-8').write(quad_src)
open(tmp + '/quad_draft.md', 'w', encoding='utf-8').write(draft_quad)
with contextlib.redirect_stdout(io.StringIO()):
    splice(tmp + '/quad_draft.md', tmp + '/quad_src.md',
           tmp + '/cand/quad_candidate.md')
quad_candidate = open(tmp + '/cand/quad_candidate.md',
                      encoding='utf-8').read()
assert 'code_tilde()' in quad_candidate \
    and 'code_quad("with ~~~ inside")' in quad_candidate, '复杂围栏回填失败'
fail, lines = run_checks(
    quad_candidate, quad_src, [], fragment=True,
    doc_dir=os.path.abspath(tmp), doc_label='quad_candidate.md',
    src_label=tmp + '/quad_src.md')
assert fail == 0, '复杂围栏候选预检应通过:\n%s' % '\n'.join(lines)
print('A28 四反引号/波浪线围栏回填与预检 PASS')
PY

echo "==> Ticket 01 回归全部通过"
