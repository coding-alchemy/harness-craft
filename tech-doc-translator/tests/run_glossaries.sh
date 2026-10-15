#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
SCRIPT="skills/tech-doc-translator/scripts/consolidate_glossaries.py"
SELECT="skills/tech-doc-translator/scripts/select_glossary.py"
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
  --library skills/tech-doc-translator/references/glossaries/nvidia.md --project "$TMP/leading-dimension-project.md" \
  --output "$TMP/leading-dimension-subset.md"
grep -q '| leading dimension | leading dimension | 英文 |' "$TMP/leading-dimension-subset.md"
grep -q '项目覆盖:.*leading-dimension-project.md.*leading dimension.*nvidia.md' \
  "$TMP/leading-dimension-subset.md"

echo "==> Ticket 01 术语整合基础回归通过"

echo "==> Ticket 06 术语表别名只读复用回归"

cat > "$TMP/source-alias.md" <<'EOF'
# Source

A kernel schedules a warp on the padded device.
EOF

# 规范表头 vs 两个别名表头：同一路径依次写入，选择输出应除映射说明外一致。
# padded 行尾空单元格须保留（宽 4），不因吞掉首尾盘符而错列。
cat > "$TMP/project.md" <<'EOF'
# 项目术语表

| 英文原词 | 中文译法/保留形式 | 处理方式 | 语境/备注 |
| --- | --- | --- | --- |
| kernel | 内核 | 首现附英文 | 计算 |
| warp | warp | 保留英文 | 计算 |
| padded |  | 英文 | |
EOF
before="$(shasum -a 256 "$TMP/project.md" | awk '{print $1}')"
python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/project.md" \
  --output "$TMP/subset-canonical.md"
after="$(shasum -a 256 "$TMP/project.md" | awk '{print $1}')"
test "$before" = "$after" || { echo "别名输入术语表被改写"; exit 1; }
grep -q '| padded | padded | 英文 |  |' "$TMP/subset-canonical.md"
grep -q 'padded ← “中文译法/保留形式”（project.md 表头行 3，第 2 列）' \
  "$TMP/subset-canonical.md"

cat > "$TMP/project.md" <<'EOF'
# 项目术语表

| 英文原词 | 中文译法/保留 | 处理方式 | 语境/备注 |
| --- | --- | --- | --- |
| kernel | 内核 | 首现附英文 | 计算 |
| warp | warp | 保留英文 | 计算 |
| padded |  | 英文 | |
EOF
before="$(shasum -a 256 "$TMP/project.md" | awk '{print $1}')"
python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/project.md" \
  --output "$TMP/subset-alias-keep.md"
after="$(shasum -a 256 "$TMP/project.md" | awk '{print $1}')"
test "$before" = "$after" || { echo "别名输入术语表被改写"; exit 1; }
grep -q 'kernel ← “中文译法/保留”（project.md 表头行 3，第 2 列）' \
  "$TMP/subset-alias-keep.md"

cat > "$TMP/project.md" <<'EOF'
# 项目术语表

| 英文原词 | 直译 | 处理方式 | 语境/备注 |
| --- | --- | --- | --- |
| kernel | 内核 | 首现附英文 | 计算 |
| warp | warp | 保留英文 | 计算 |
| padded |  | 英文 | |
EOF
python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/project.md" \
  --output "$TMP/subset-literal.md"
grep -q 'kernel ← “直译”（project.md 表头行 3，第 2 列）' "$TMP/subset-literal.md"

# 词条表部分（映射说明之前）三份输出逐字一致；`直译` 不推导处理方式。
sed -n '1,/^## 目标列映射/p' "$TMP/subset-canonical.md" | sed '$d' > "$TMP/table-canonical.txt"
sed -n '1,/^## 目标列映射/p' "$TMP/subset-alias-keep.md" | sed '$d' > "$TMP/table-alias-keep.txt"
sed -n '1,/^## 目标列映射/p' "$TMP/subset-literal.md" | sed '$d' > "$TMP/table-literal.txt"
cmp "$TMP/table-canonical.txt" "$TMP/table-alias-keep.txt"
cmp "$TMP/table-canonical.txt" "$TMP/table-literal.txt"
grep -q '| kernel | 内核 | 首现中英，后文中文 | 计算 |' "$TMP/subset-literal.md"
grep -q '| warp | warp | 英文 | 计算 |' "$TMP/subset-literal.md"

# 重复目标列（即使值相同）即表头歧义，不猜首列；坏表头下数据行也有去向。
cat > "$TMP/duplicate-target.md" <<'EOF'
| 英文原词 | 中文译法 | 中文译法 | 处理方式 |
| --- | --- | --- | --- |
| kernel | 内核 | 内核 | 中文 |
EOF
if python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/duplicate-target.md" \
  --output "$TMP/dup-subset.md" 2>"$TMP/dup-error.log"; then
  echo "重复目标列应使选择失败"
  exit 1
fi
grep -q 'duplicate-target.md:1.*表头歧义：目标译法列匹配多列' "$TMP/dup-error.log"
grep -q 'duplicate-target.md:3.*表头歧义' "$TMP/dup-error.log"

# 重复英文原词列（即使值相同）同样是表头歧义，不能按“无英文列”静默
# 吞表；已识别术语表的可识别数据行逐行有去向（提交前评审 R9 反例）。
cat > "$TMP/duplicate-english.md" <<'EOF'
| 英文原词 | 英文原词 | 中文译法 | 处理方式 |
| --- | --- | --- | --- |
| kernel | kernel | 内核 | 中文 |
EOF
if python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/duplicate-english.md" \
  --output "$TMP/dup-en-subset.md" 2>"$TMP/dup-en-error.log"; then
  echo "重复英文原词列应使选择失败"
  exit 1
fi
grep -q 'duplicate-english.md:1.*表头歧义：英文原词列匹配多列' "$TMP/dup-en-error.log"
grep -q 'duplicate-english.md:3.*表头歧义' "$TMP/dup-en-error.log"

# 无英文原词角色的普通表：其他角色列重复（ambiguous）也不误收、不报错，
# 按非术语表跳过（R9.3）；表头歧义报错只适用于含英文原词角色的术语表。
cat > "$TMP/plain-table.md" <<'EOF'
# 指标

| 指标 | 中文译法/保留 | 中文译法/保留 |
| --- | --- | --- |
| 术语数 | 4 | 4 |
EOF
python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/plain-table.md" \
  --output "$TMP/plain-subset.md"
if grep -q '^| kernel |' "$TMP/plain-subset.md"; then
  echo "普通表不应产出术语行"
  exit 1
fi
grep -q '^## 目标列映射' "$TMP/plain-subset.md"

# 缺目标译法列、行宽损伤、首尾空单元格不错列。
cat > "$TMP/damaged.md" <<'EOF'
# 损伤表

| 英文原词 | 处理策略 | 语境/备注 |
| --- | --- | --- |
| kernel | 首现附英文 | 计算 |

| 英文原词 | 中文译法/保留 | 处理方式 | 语境/备注 |
| --- | --- | --- | --- |
| sparse |
EOF
if python3 "$SELECT" --source "$TMP/source-alias.md" --project "$TMP/damaged.md" \
  --output "$TMP/damaged-subset.md" 2>"$TMP/damaged-error.log"; then
  echo "缺目标译法列与行宽损伤应使选择失败"
  exit 1
fi
grep -q 'damaged.md:3.*术语表列含义无法识别' "$TMP/damaged-error.log"
grep -q 'damaged.md:5.*术语表列含义无法识别' "$TMP/damaged-error.log"
grep -q 'damaged.md:9.*列数（1）与表头列数（4）不符' "$TMP/damaged-error.log"

# 多表逐行核算：有效记录、歧义行、窄行各有着落，总数对账。
cat > "$TMP/multi.md" <<'EOF'
# 多表

| 英文原词 | 中文译法/保留 | 处理方式 |
| --- | --- | --- |
| good | 好 | 中文 |

| 英文原词 | 中文译法 | 中文译法 |
| --- | --- | --- |
| dup | 甲 | 甲 |

| 英文原词 | 中文译法/保留 | 处理方式 |
| --- | --- | --- |
| sparse |
EOF
if python3 "$SCRIPT" --baseline "$TMP/baseline.md" --draft "$TMP/multi-draft.md" \
  --report "$TMP/multi-report.md" "$TMP/multi.md"; then
  echo "多表损伤应使整合失败"
  exit 1
fi
grep -q '| good | 好 | 中文 |' "$TMP/multi-draft.md"
grep -q 'multi.md:7.*表头歧义' "$TMP/multi-report.md"
grep -q 'multi.md:9.*表头歧义' "$TMP/multi-report.md"
grep -q 'multi.md:13.*列数（1）与表头列数（3）不符' "$TMP/multi-report.md"
grep -q '输入记录: 3 / 权威候选: 1 / 重复: 0 / 冲突: 0 / 错误: 3' "$TMP/multi-report.md"

# 整合同样接受别名表头并回查映射。
cat > "$TMP/alias-input.md" <<'EOF'
# 别名输入

| 英文原词 | 直译 | 处理方式 | 首现 |
| --- | --- | --- | --- |
| alias term | 别名词条 | 译 | 1.1 |
EOF
python3 "$SCRIPT" --baseline "$TMP/baseline.md" --draft "$TMP/alias-draft.md" \
  --report "$TMP/alias-report.md" "$TMP/alias-input.md"
grep -q 'alias term.*首现中英，后文中文' "$TMP/alias-draft.md"
grep -q 'alias term ← “直译”（alias-input.md 表头行 3，第 2 列）' "$TMP/alias-report.md"

echo "==> Ticket 06 术语表别名只读复用回归通过"
