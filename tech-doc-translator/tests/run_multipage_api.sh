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
payload = json.loads((out / 'images_display.json').read_text(encoding='utf-8'))
assert payload['markdown'] == 'merged_api.md', payload['markdown']
entries = {e['occurrence']: e for e in payload['entries']}
assert set(entries) == {1, 2}, payload['entries']
assert entries[1]['image'] == 'images/diagram.png', entries[1]
assert entries[1]['width']['value'] == 454, entries[1]
assert entries[2]['image'] == 'images/light.png', entries[2]
assert entries[2]['width']['value'] == 300, entries[2]
for occurrence in (1, 2):
    actual = hashlib.sha256(
        (out / entries[occurrence]['image']).read_bytes()).hexdigest()
    assert entries[occurrence]['sha256'] == actual, entries[occurrence]
print('交付级映射：跨页全局出现序号、资源摘要与宽度均正确')
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

echo "==> Ticket 04 多页面 API 回归全部通过"
