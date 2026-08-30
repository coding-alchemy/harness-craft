#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
SCRIPT="scripts/consolidate_glossaries.py"
SELECT="scripts/select_glossary.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/baseline.md" <<'EOF'
# NVIDIA 术语库

| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |
| --- | --- | --- | --- | --- |
| CUDA | CUDA | 英文 | | existing:1 |
EOF

cat > "$TMP/input.md" <<'EOF'
# 输入术语

| 指标 | 数值 |
| --- | --- |
| 术语数 | 4 |

## 第一组

| 英文原词 | 中文译法 | 处理方式 | 首现 |
| --- | --- | --- | --- |
| kernel | 内核 | 首现附英文 | 1.1 |
| CUDA | CUDA | 保留英文 | 1.2 |

## 第二组

| 英文原词 | 定稿译法 | 处理方式 | 本章首现 |
| --- | --- | --- | --- |
| `kernel` | 内核 | 首现附英文 | 2.1 |
| stream | 流 | 译 | 2.2 |
| stream | 流程 | 译 | 2.3 |
| SM | 流式多处理器（SM），后文 SM | 首现译后保留 | 2.4 |
EOF

before="$(shasum -a 256 "$TMP/input.md" | awk '{print $1}')"

echo "==> Ticket 01 术语整合基础回归"
python3 "$SCRIPT" --baseline "$TMP/baseline.md" --draft "$TMP/draft.md" \
  --report "$TMP/report.md" "$TMP/input.md"

after="$(shasum -a 256 "$TMP/input.md" | awk '{print $1}')"
test "$before" = "$after" || { echo "输入术语表被改写"; exit 1; }
grep -q 'kernel.*input.md:11 \[第一组\]; input.md:18 \[第二组\]' "$TMP/draft.md"
grep -q 'CUDA.*existing:1; input.md:12 \[第一组\]' "$TMP/draft.md"
grep -q 'SM.*首现中英，后文英文.*input.md:21 \[第二组\]' "$TMP/draft.md"
grep -q 'stream.*流.*首现中英，后文中文.*input.md:19 \[第二组\]' "$TMP/report.md"
grep -q 'stream.*流程.*首现中英，后文中文.*input.md:20 \[第二组\]' "$TMP/report.md"
grep -q '输入记录: 6 / 权威候选: 2 / 重复: 2 / 冲突: 2 / 错误: 0' "$TMP/report.md"

cp "$TMP/draft.md" "$TMP/draft-first.md"
python3 "$SCRIPT" --baseline "$TMP/baseline.md" --draft "$TMP/draft.md" \
  --report "$TMP/report.md" "$TMP/input.md"
cmp "$TMP/draft-first.md" "$TMP/draft.md"

python3 "$SCRIPT" --baseline "$TMP/draft-first.md" --draft "$TMP/roundtrip.md" \
  --report "$TMP/roundtrip-report.md" "$TMP/input.md"
cmp "$TMP/draft-first.md" "$TMP/roundtrip.md" || {
  echo "聚合来源列表再次回流后不应重复增长"
  exit 1
}

cat > "$TMP/broken.md" <<'EOF'
| 英文原词 | 中文译法 | 处理方式 |
| --- | --- | --- |
| orphan |  |  |
EOF

if python3 "$SCRIPT" --baseline "$TMP/baseline.md" --draft "$TMP/broken-draft.md" \
  --report "$TMP/broken-report.md" "$TMP/broken.md"; then
  echo "破损术语行应使整合失败"
  exit 1
fi
grep -q 'broken.md:3：中文译法/保留形式或处理方式不足' "$TMP/broken-report.md"
grep -q '输入记录: 1 / 权威候选: 0 / 重复: 0 / 冲突: 0 / 错误: 1' "$TMP/broken-report.md"

cat > "$TMP/unknown-columns.md" <<'EOF'
| 英文原词 | 中文名称 | 处理策略 |
| --- | --- | --- |
| opaque | 不透明 | 译 |
EOF
if python3 "$SCRIPT" --baseline "$TMP/baseline.md" --draft "$TMP/unknown-draft.md" \
  --report "$TMP/unknown-report.md" "$TMP/unknown-columns.md"; then
  echo "列含义不明的术语表应使整合失败"
  exit 1
fi
grep -q 'unknown-columns.md:3：术语表列含义无法识别' "$TMP/unknown-report.md"

cat > "$TMP/library-a.md" <<'EOF'
# 任意库 A

| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |
| --- | --- | --- | --- | --- |
| kernel | 内核 | 中文 | | a:1 |
| warp | warp | 英文 | | a:2 |
EOF

cat > "$TMP/library-b.md" <<'EOF'
# 任意库 B

| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 | 来源 |
| --- | --- | --- | --- | --- |
| kernel | 核函数 | 首现中英，后文中文 | | b:1 |
| stream | 流 | 中文 | CUDA | b:2 |
| stream | 流程 | 中文 | I/O | b:3 |
EOF

cat > "$TMP/project.md" <<'EOF'
# 项目术语表

| 英文原词 | 中文译法 | 处理方式 | 首现 |
| --- | --- | --- | --- |
| kernel | 核函数 | 首现附英文 | 1.1 |
EOF

cat > "$TMP/source.md" <<'EOF'
# Source

A kernel uses a warp. A stream is created.
EOF

if python3 "$SELECT" --source "$TMP/source.md" --output "$TMP/ambiguous.md" \
  --library "$TMP/library-a.md" --library "$TMP/library-b.md" \
  2>"$TMP/ambiguous-error.log"; then
  echo "未选择语境的多义术语应失败"
  exit 1
fi

python3 "$SELECT" --source "$TMP/source.md" --output "$TMP/subset-a.md" \
  --library "$TMP/library-a.md" --library "$TMP/library-b.md" \
  --project "$TMP/project.md" --context 'stream=CUDA'
grep -q '| kernel | 核函数 | 首现中英，后文中文 |' "$TMP/subset-a.md"
grep -q '| warp | warp | 英文 |' "$TMP/subset-a.md"
grep -q '| stream | 流 | 中文 | CUDA |' "$TMP/subset-a.md"
grep -q '共享库覆盖:.*library-a.md.*library-b.md.*kernel' "$TMP/subset-a.md"
grep -q '项目覆盖:.*project.md.*library-a.md.*kernel' "$TMP/subset-a.md"

cat > "$TMP/unknown-project.md" <<'EOF'
| 英文原词 | 中文名称 | 处理策略 |
| --- | --- | --- |
| kernel | 核函数 | 译 |
EOF
if python3 "$SELECT" --source "$TMP/source.md" --output "$TMP/unknown-subset.md" \
  --library "$TMP/library-a.md" --project "$TMP/unknown-project.md" \
  2>"$TMP/unknown-select-error.log"; then
  echo "选择工具不应静默跳过列含义不明的术语表"
  exit 1
fi
grep -q 'unknown-project.md:3.*术语表列含义无法识别' "$TMP/unknown-select-error.log"

python3 "$SELECT" --source "$TMP/source.md" --output "$TMP/subset-b.md" \
  --library "$TMP/library-b.md" --library "$TMP/library-a.md" --context 'stream=CUDA'
grep -q '| kernel | 核函数 | 首现中英，后文中文 |' "$TMP/subset-b.md"
grep -q '| warp | warp | 英文 |' "$TMP/subset-b.md"
grep -q '共享库覆盖:.*library-b.md.*library-a.md.*kernel' "$TMP/subset-b.md"

cat > "$TMP/leading-dimension-source.md" <<'EOF'
The leading dimension is the stride between matrix rows.
EOF
cat > "$TMP/leading-dimension-project.md" <<'EOF'
| 英文原词 | 中文译法 | 处理方式 | 首现 |
| --- | --- | --- | --- |
| leading dimension | leading dimension | 保留英文 | 3.3.1 |
EOF
python3 "$SELECT" --source "$TMP/leading-dimension-source.md" \
  --library glossaries/nvidia.md --project "$TMP/leading-dimension-project.md" \
  --output "$TMP/leading-dimension-subset.md"
grep -q '| leading dimension | leading dimension | 英文 |' "$TMP/leading-dimension-subset.md"
grep -q '项目覆盖:.*leading-dimension-project.md.*leading dimension.*nvidia.md' \
  "$TMP/leading-dimension-subset.md"

echo "==> Ticket 01 术语整合基础回归通过"
