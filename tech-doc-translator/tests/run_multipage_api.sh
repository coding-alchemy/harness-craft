#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
FIXTURE_SITE="tests/fixtures/multipage_site"
DISCOVER="scripts/discover_pages.py"
PARSE="scripts/parse_api_html.py"
MERGE="scripts/merge_api.py"
VERIFY="scripts/verify_api_translation.py"
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

echo "==> 发现页面并闭合对账"
python3 "$DISCOVER" "$SITE/index.html" "$MANIFEST"
diff -u "$EXPECTED" "$MANIFEST"

echo "==> 解析各 API 页面为源 Markdown"
python3 "$PARSE" "$SITE/api_page1.html" "$SRC_DIR/api_page1.md"
python3 "$PARSE" "$SITE/index.html"     "$SRC_DIR/index.md"
python3 "$PARSE" "$SITE/subdir/api_page2.html" "$SRC_DIR/api_page2.md"

echo "==> 按清单顺序合并翻译文件"
python3 "$MERGE" "$MANIFEST" "$SITE" "$MERGED"

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

echo "==> Ticket 04 多页面 API 回归全部通过"
