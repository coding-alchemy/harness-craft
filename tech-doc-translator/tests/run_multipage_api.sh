#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
FIXTURE_SITE="tests/fixtures/multipage_site"
DISCOVER="skills/tech-doc-translator/scripts/discover_pages.py"
PARSE="skills/tech-doc-translator/scripts/parse_api_html.py"
MERGE="skills/tech-doc-translator/scripts/merge_api.py"
VERIFY="skills/tech-doc-translator/scripts/verify_api_translation.py"
FIXTURE_IMAGE="tests/fixtures/valid_1x1.png"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
SITE="$TMP/site"
OUT_DIR="$TMP/delivery"
SRC_DIR="$OUT_DIR/src"
MANIFEST="$OUT_DIR/manifest.txt"
MERGED="$OUT_DIR/merged_api.md"
EXPECTED="$OUT_DIR/expected_manifest.txt"

mkdir -p "$SITE" "$SRC_DIR"
cp -R "$FIXTURE_SITE"/. "$SITE"/

cat > "$EXPECTED" <<'EOF'
api_page1.html
index.html
subdir/api_page2.html
EOF

cat > "$SITE/trans_index.md" <<'EOF'
# API Docs（API 文档）

这是多页面 API 文档的入口。
EOF

mkdir -p "$SITE/images" "$SITE/subdir/images"
cp "$FIXTURE_IMAGE" "$SITE/images/diagram.png"
cp "$FIXTURE_IMAGE" "$SITE/subdir/images/light.png"
cp "$FIXTURE_IMAGE" "$SITE/subdir/images/dark.png"

# V0.2-02：给样例图片加上源显示宽度（内联 CSS / HTML width 属性 / 暗亮对）。
python3 - "$SITE" <<'PY'
import sys
from pathlib import Path

site = Path(sys.argv[1])
page1 = site / 'api_page1.html'
text = page1.read_text(encoding='utf-8')
text = text.replace('<img src="images/diagram.png" alt="diagram">',
                    '<img src="images/diagram.png" alt="diagram" style="width:454px">')
page1.write_text(text, encoding='utf-8')
page2 = site / 'subdir/api_page2.html'
text = page2.read_text(encoding='utf-8')
text = text.replace('<img src="images/light.png" class="only-light" alt="mode">',
                    '<img src="images/light.png" class="only-light" alt="mode" width="300">')
text = text.replace('<img src="images/dark.png" class="only-dark" alt="mode">',
                    '<img src="images/dark.png" class="only-dark" alt="mode" width="150">')
page2.write_text(text, encoding='utf-8')
PY

echo "==> 发现页面并闭合对账"
python3 "$DISCOVER" "$SITE/index.html" "$MANIFEST"
diff -u "$EXPECTED" "$MANIFEST"

echo "==> 解析各 API 页面为源 Markdown"
python3 "$PARSE" "$SITE/api_page1.html" "$SRC_DIR/api_page1.md"
python3 "$PARSE" "$SITE/index.html"     "$SRC_DIR/index.md"
python3 "$PARSE" "$SITE/subdir/api_page2.html" "$SRC_DIR/api_page2.md"

echo "==> V0.2-02：解析期显示尺寸映射（内联 CSS、HTML 属性与暗亮选择）"
python3 - "$SRC_DIR" <<'PY'
import json, sys
from pathlib import Path

src = Path(sys.argv[1])
map1 = json.loads((src / 'api_page1.images_display.json').read_text(encoding='utf-8'))
assert map1['entries'] and map1['entries'][0]['width'] == {
    'value': 454, 'unit': 'px', 'basis': 'inline-css-width', 'reference': None
}, map1['entries']
map2 = json.loads((src / 'api_page2.images_display.json').read_text(encoding='utf-8'))
assert map2['entries'][0]['image'] == 'images/light.png', map2
assert map2['entries'][0]['width']['value'] == 300, map2
assert map2['entries'][0]['width']['basis'] == 'html-width-attribute', map2
print('解析期映射：内联 CSS 454px、暗亮选中 light 300px 均正确登记')
PY

echo "==> 按清单顺序合并翻译文件（含显示尺寸绑定）"
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"

echo "==> V0.2-02：交付级映射已按全局出现序号绑定"
python3 - "$OUT_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path

out = Path(sys.argv[1])
payload = json.loads((out / 'export' / 'images_display.json')
                     .read_text(encoding='utf-8'))
assert payload['markdown'] == 'merged_api.md', payload['markdown']
entries = {e['occurrence']: e for e in payload['entries']}
assert set(entries) == {1, 2}, payload['entries']
assert entries[1]['markdown'] == '../merged_api.md', entries[1]
assert entries[1]['image'] == '../images/diagram.png', entries[1]
assert entries[1]['width']['value'] == 454, entries[1]
assert entries[2]['image'] == '../images/light.png', entries[2]
assert entries[2]['width']['value'] == 300, entries[2]
map_dir = out / 'export'
for occurrence in (1, 2):
    delivered = map_dir / entries[occurrence]['image']
    actual = hashlib.sha256(delivered.read_bytes()).hexdigest()
    assert entries[occurrence]['sha256'] == actual, entries[occurrence]
assert not (out / 'images_display.json').exists(), '根目录不得残留映射副本'
print('交付级映射：export/ 布局、跨页全局出现序号、资源摘要与宽度均正确')
PY

echo "==> 检查图片已本地化到最终交付目录"
test -f "$OUT_DIR/images/diagram.png" || { echo "FAIL: 交付目录缺少 diagram.png"; exit 1; }
test -f "$OUT_DIR/images/light.png" || { echo "FAIL: 交付目录缺少 light.png"; exit 1; }

echo "==> 校验合并后译文（manifest 与独立官方 TOC 快照对账）"
python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
  "$SRC_DIR/api_page1.md" \
  "$SRC_DIR/index.md" \
  "$SRC_DIR/api_page2.md"

echo "==> 失败回归：最终交付目录缺图必须判 FAIL"
mv "$OUT_DIR/images/light.png" "$TMP/light.png"
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md"; then
  echo "错误：验证器从源站目录找到图片，未发现交付目录缺图"
  exit 1
else
  echo "交付目录缺图已正确判 FAIL"
fi
mv "$TMP/light.png" "$OUT_DIR/images/light.png"

echo "==> 失败回归：从 index.html 删除一个范围内链接"
BROKEN_SITE="$TMP/broken-site"
mkdir -p "$BROKEN_SITE"
cp -R "$SITE"/. "$BROKEN_SITE"/
python3 - "$BROKEN_SITE/index.html" <<'PY'
import sys, re
p = sys.argv[1]
html = open(p, encoding='utf-8').read()
html = re.sub(r'<a[^>]+href=["\']api_page1\.html(?:#[^"\'\s>]+)?["\'][^>]*>.*?</a>', '', html, flags=re.S)
open(p, 'w', encoding='utf-8').write(html)
PY
python3 "$DISCOVER" "$BROKEN_SITE/index.html" "$BROKEN_SITE/manifest.txt"
if diff -u "$EXPECTED" "$BROKEN_SITE/manifest.txt" >/dev/null 2>&1; then
  echo "错误：闭合校验没有检测到缺失页面"
  exit 1
fi
echo "==> 失败回归：缺页 manifest 与官方 TOC 对账必须判 FAIL"
python3 "$PARSE" "$BROKEN_SITE/subdir/api_page2.html" "$BROKEN_SITE/api_page2.md"
python3 "$PARSE" "$BROKEN_SITE/index.html" "$BROKEN_SITE/index.md"
python3 "$MERGE" "$BROKEN_SITE/manifest.txt" "$BROKEN_SITE" "$BROKEN_SITE/merged.md"
if python3 "$VERIFY" "$BROKEN_SITE/merged.md" "$BROKEN_SITE/manifest.txt" "$EXPECTED" "$BROKEN_SITE" \
    "$BROKEN_SITE/index.md" "$BROKEN_SITE/api_page2.md"; then
  echo "错误：缺页 manifest 通过了官方 TOC 对账"
  exit 1
else
  echo "缺页 manifest 已正确判 FAIL（官方 TOC 独立基准生效）"
fi

echo "==> V0.2-02 失败回归：绑定资源身份不符必须 FAIL"
FAILSITE="$TMP/bind-fail-site"
rm -rf "$FAILSITE"; mkdir -p "$FAILSITE"
cp -R "$SITE"/. "$FAILSITE"/
python3 - "$SRC_DIR/api_page2.images_display.json" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding='utf-8'))
data['entries'][0]['image'] = 'images/dark.png'  # 与译文第 1 次出现资源不符
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY
if python3 "$MERGE" "$MANIFEST" "$FAILSITE" "$TMP/bind_fail.md" \
    --display-src "$SRC_DIR" 2>"$TMP/bind_err.txt"; then
  echo "错误：资源身份不符未被检出"; exit 1
fi
grep -q "与译文资源不符" "$TMP/bind_err.txt" \
  || { echo "错误：资源不符诊断缺失"; cat "$TMP/bind_err.txt"; exit 1; }
# 还原映射，供后续步骤复用
python3 - "$SRC_DIR/api_page2.images_display.json" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding='utf-8'))
data['entries'][0]['image'] = 'images/light.png'
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY

echo "==> V0.2-02 失败回归：出现序号与译文图片数不符必须 FAIL"
FAILSITE2="$TMP/count-fail-site"
rm -rf "$FAILSITE2"; mkdir -p "$FAILSITE2"
cp -R "$SITE"/. "$FAILSITE2"/
python3 - "$FAILSITE2/subdir/trans_api_page2.md" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8').replace('![mode](images/light.png)\n', '')
path.write_text(text, encoding='utf-8')
PY
if python3 "$MERGE" "$MANIFEST" "$FAILSITE2" "$TMP/count_fail.md" \
    --display-src "$SRC_DIR" 2>"$TMP/count_err.txt"; then
  echo "错误：出现数不符未被检出"; exit 1
fi
grep -q "出现数 .* 与译文图片数 .* 不符" "$TMP/count_err.txt" \
  || { echo "错误：出现数诊断缺失"; cat "$TMP/count_err.txt"; exit 1; }

echo "==> 完整性-01：代码内独立 --- 行不得拆页（源译一致的含 --- 代码块保持通过）"
python3 - "$SRC_DIR/api_page1.md" "$SITE/trans_api_page1.md" <<'PY'
import sys

block = '\n```text\nsection one\n---\nsection two\n```\n'
for path in sys.argv[1:3]:
    with open(path, 'a', encoding='utf-8') as f:
        f.write(block)
PY
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
  "$SRC_DIR/api_page1.md" \
  "$SRC_DIR/index.md" \
  "$SRC_DIR/api_page2.md"
echo "代码内 --- 未被误拆页，含 --- 的正确产物保持 PASS"

echo "==> 完整性-01 失败回归：含 --- 代码块的内容篡改必须判 FAIL"
python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
assert 'section two' in text, '回归样本缺少目标代码行'
open(path, 'w', encoding='utf-8').write(
    text.replace('section two', 'section 2'))
PY
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md" >"$TMP/code_diff_err.txt" 2>&1; then
  echo "错误：代码内容篡改未被检测到"
  exit 1
fi
grep -q '代码逐块核对' "$TMP/code_diff_err.txt" \
  || { echo "错误：缺少逐块核对诊断"; cat "$TMP/code_diff_err.txt"; exit 1; }
echo "含 --- 代码块的内容篡改已正确判 FAIL"

echo "==> 完整性-02：API 路线公式逐项核对（正确通过；篡改判 FAIL）"
python3 - "$SRC_DIR/api_page1.md" "$SITE/trans_api_page1.md" <<'PY'
import sys

src_path, trans_path = sys.argv[1:3]
math_block = '\n行内公式 $a_1+b_2$ 与块级：\n\n$$\nF = G\n$$\n'
src = open(src_path, encoding='utf-8').read().replace('section 2', 'section two')
open(src_path, 'w', encoding='utf-8').write(src + math_block)
trans = open(trans_path, encoding='utf-8').read().replace('section 2', 'section two')
open(trans_path, 'w', encoding='utf-8').write(trans + math_block)
PY
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
  "$SRC_DIR/api_page1.md" \
  "$SRC_DIR/index.md" \
  "$SRC_DIR/api_page2.md"
python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
assert '$a_1+b_2$' in text
open(path, 'w', encoding='utf-8').write(text.replace('$a_1+b_2$', '$a_1-b_2$'))
PY
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md" >"$TMP/math_diff_err.txt" 2>&1; then
  echo "错误：公式运算符篡改未被检测到"
  exit 1
fi
grep -q '公式逐项核对' "$TMP/math_diff_err.txt" \
  || { echo "错误：缺少公式差异诊断"; cat "$TMP/math_diff_err.txt"; exit 1; }
python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
open(path, 'w', encoding='utf-8').write(text.replace('$a_1-b_2$', '$a_1+b_2$'))
PY
echo "API 路线公式篡改已正确判 FAIL（已还原样本）"

echo "==> 完整性-04：标题层级变化与强 token 遗漏必须判 FAIL"
python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
assert '## Parameters（参数）' in text
open(path, 'w', encoding='utf-8').write(
    text.replace('## Parameters（参数）', '### Parameters（参数）'))
PY
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md" >"$TMP/lvl_err.txt" 2>&1; then
  echo "错误：标题层级变化未被检测到"
  exit 1
fi
grep -q '层级不一致' "$TMP/lvl_err.txt" \
  || { echo "错误：缺少层级差异诊断"; cat "$TMP/lvl_err.txt"; exit 1; }
python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
open(path, 'w', encoding='utf-8').write(
    text.replace('### Parameters（参数）', '## Parameters（参数）'))
PY
echo "API 路线标题层级变化已正确判 FAIL"

python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
assert '**handle** cuBLAS handle。' in text
open(path, 'w', encoding='utf-8').write(
    text.replace('**handle** cuBLAS handle。', '**handle** handle。'))
PY
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md" --strong-token cuBLAS >"$TMP/tok_err.txt" 2>&1; then
  echo "错误：强 token 遗漏未被检测到"
  exit 1
fi
grep -q '强 token' "$TMP/tok_err.txt" \
  || { echo "错误：缺少强 token 诊断"; cat "$TMP/tok_err.txt"; exit 1; }
python3 - "$SITE/trans_api_page1.md" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
open(path, 'w', encoding='utf-8').write(
    text.replace('**handle** handle。', '**handle** cuBLAS handle。'))
PY
echo "API 路线强 token 遗漏已正确判 FAIL（样本已还原）"

echo "==> 完整性-05：同名换图/身份映射/搬迁后离线校验"
python3 - "$SITE" <<'PY'
import sys

site = sys.argv[1]
# 使两图内容不同（魔数合法），否则同名换图/错序无法用摘要区分
data = open(site + '/subdir/images/light.png', 'rb').read()
open(site + '/subdir/images/light.png', 'wb').write(data[:8] + b'L' + data[9:])
PY
# A28：源图在解析后被换字节 → 合并绑定必须拒绝（不采用新图摘要冒充）
if python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR" \
    >"$TMP/bind_stale_err.txt" 2>&1; then
  echo "错误：解析后换源图未被合并绑定拒绝"; exit 1
fi
grep -q "源资源身份不符" "$TMP/bind_stale_err.txt" \
  || { cat "$TMP/bind_stale_err.txt"; echo "错误：缺少源资源身份诊断"; exit 1; }
echo "解析后换源图被合并绑定拒绝 PASS"
# 重新解析刷新解析期映射（同版本源已重新解析），合并恢复正常
python3 "$PARSE" "$SITE/subdir/api_page2.html" "$SRC_DIR/api_page2.md"
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED" --display-src "$SRC_DIR"
python3 - "$OUT_DIR" <<'PY'
import sys

out = sys.argv[1]
# 交付副本被篡改为内容不同、魔数不变的同名文件
data = open(out + '/images/diagram.png', 'rb').read()
open(out + '/images/diagram.png', 'wb').write(data[:8] + b'F' + data[9:])
PY
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md" >"$TMP/swap_err.txt" 2>&1; then
  echo "错误：同名换图未被检测到"
  exit 1
fi
grep -q '来源身份不符' "$TMP/swap_err.txt" \
  || { echo "错误：缺少来源身份诊断"; cat "$TMP/swap_err.txt"; exit 1; }
cp "$SITE/images/diagram.png" "$OUT_DIR/images/diagram.png"
echo "同名换图已正确判 FAIL（已还原原文件）"

python3 - "$OUT_DIR" "$TMP" <<'PY'
import hashlib
import json
import sys

out, tmp = sys.argv[1:3]
def digest(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()
json.dump({'digests': [digest(out + '/images/diagram.png'),
                       digest(out + '/images/light.png')]},
          open(tmp + '/map_ok.json', 'w'))
json.dump({'digests': [digest(out + '/images/light.png'),
                       digest(out + '/images/diagram.png')]},
          open(tmp + '/map_swap.json', 'w'))
PY
python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
  "$SRC_DIR/api_page1.md" \
  "$SRC_DIR/index.md" \
  "$SRC_DIR/api_page2.md" --image-map "$TMP/map_ok.json"
if python3 "$VERIFY" "$MERGED" "$MANIFEST" "$EXPECTED" "$SITE" \
    "$SRC_DIR/api_page1.md" \
    "$SRC_DIR/index.md" \
    "$SRC_DIR/api_page2.md" --image-map "$TMP/map_swap.json" \
    >"$TMP/map_err.txt" 2>&1; then
  echo "错误：身份映射错序未被检测到"
  exit 1
fi
grep -q '来源身份不符' "$TMP/map_err.txt" \
  || { echo "错误：缺少映射差异诊断"; cat "$TMP/map_err.txt"; exit 1; }
echo "图片身份映射：一致 PASS；错序已正确判 FAIL"

cp -R "$OUT_DIR" "$TMP/delivery2"
python3 "$VERIFY" "$TMP/delivery2/merged_api.md" "$MANIFEST" "$EXPECTED" "$SITE" \
  "$SRC_DIR/api_page1.md" \
  "$SRC_DIR/index.md" \
  "$SRC_DIR/api_page2.md"
echo "交付树搬迁至第二目录后按新路径校验 PASS"

echo "==> Ticket 04 多页面 API 回归全部通过"

echo "==> 翻译留痕 01：富容器保真与独立对账（多页 API 家族）"
python3 "$PARSE" tests/fixtures/rich_single_page.html "$TMP/rich_source.md"
python3 - "$TMP/rich_source.md" <<'PY'
import sys

sys.path.insert(0, 'skills/tech-doc-translator/scripts')
from _source_reconcile import reconcile_html_to_markdown
from _verification import scan_code_fences

text = open(sys.argv[1], encoding='utf-8').read()
bodies = [f.body for f in scan_code_fences(text).blocks]
expected = [
    'print("wrapped")',
    '#include <bar.h>\nint main() { return 10; }',
    'note_code()',
    'list_code()',
    'details_code()',
    'dd_code()',
    'table_code()',
]
assert bodies == expected, '代码块顺序或内容不符: %r' % (bodies,)
assert '## 1.1. C# Interop' in text and '¶' not in text, 'C# 标题/headerlink 异常'
assert '[TABLE-CODE r=2 c=2#1]' in text, '含代码表格缺少行列定位'
raw = open('tests/fixtures/rich_single_page.html', encoding='utf-8').read()
assert reconcile_html_to_markdown(raw, text, 'api') == [], \
    '正确解析被对账误判'
for name, mutate in [
    ('漏代码', lambda t: t.replace('```\ndetails_code()\n```\n', '')),
    ('等数换内容', lambda t: t.replace('note_code()', 'note_coded()')),
    # 项内围栏按层级缩进（列表项内代码），突变使用缩进形式
    ('重复块', lambda t: t.replace('  ```\ndd_code()\n  ```',
                                   '  ```\ndd_code()\n  ```\n\n  ```\ndd_code()\n  ```')),
]:
    diffs = reconcile_html_to_markdown(raw, mutate(text), 'api')
    assert diffs, '%s 未被对账检出' % name
    print('API 家族对账损伤 %s: %s' % (name, diffs[0]))
print('API 家族富容器保真与独立对账 PASS')
PY

echo "==> 翻译留痕 02/A1：临时输出告警存在且退出 0"
python3 "$PARSE" tests/fixtures/rich_single_page.html "$TMP/rich_a1.md" \
  2>"$TMP/a1.err"
grep -q '系统临时目录' "$TMP/a1.err" \
  || { echo "错误：临时目录解析未告警"; cat "$TMP/a1.err"; exit 1; }
echo "A1 临时路径告警 PASS"
