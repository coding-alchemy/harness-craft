#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT=".."
SPLIT="$ROOT/scripts/split_work_packages.py"
MERGE_WP="$ROOT/scripts/merge_work_packages.py"
MERGE_GLOSSARY="$ROOT/scripts/merge_glossary.py"
RECOVER="$ROOT/scripts/recover_work_packages.py"
VERIFY="$ROOT/scripts/verify_translation.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> 工作目录: $TMP"

cat > "$TMP/glossary_initial.md" <<'EOF'
# 术语表

| 英文原词 | 中文译法 | 处理方式 | 首现 |
|---|---|---|---|
| kernel | 内核 | 首现附英文 | 1.1. Thread Hierarchy |
| thread block | 线程块 | 首现附英文 | 1.1. Thread Hierarchy |
EOF

cat > "$TMP/term_candidates_a.md" <<'EOF'
# Agent A 新术语候选

| 英文原词 | 中文译法 | 处理方式 | 首现 |
|---|---|---|---|
| kernel | 内核 | 首现附英文 | 1.1. Thread Hierarchy |
| warp | warp | 保留英文 | 1.1. Thread Hierarchy |
| grid | 网格 | 首现附英文 | 1.1. Thread Hierarchy |
EOF

cat > "$TMP/term_candidates_b.md" <<'EOF'
# Agent B 新术语候选

| 英文原词 | 中文译法 | 处理方式 | 首现 |
|---|---|---|---|
| warp | 线程束 | 首现附英文 | 1.3. Warp Scheduling |
| SM | 流式多处理器 | 首现附英文 | 1.3. Warp Scheduling |
| tile | tile | 保留英文 | 1.2. Memory Model |
EOF

echo "==> 失败回归：粗体和表格分隔行不得误计为列表项"
python3 - <<'PY'
import sys
sys.path.insert(0, '../scripts')
import recover_work_packages as recover
import split_work_packages as split

lines = ['**Figure caption**', '--- | --- | ---', '- real item']
assert split._count_blocks(lines)['list_items'] == 1
assert recover._count_blocks('\n'.join(lines))[1] == 1
print('列表项计数排除粗体与表格分隔行 PASS')
PY

# 1. split 源文件为工作包；译文目标是独立目录，不得覆写工作包源
echo "==> 拆分源文件为工作包"
python3 "$SPLIT" fixtures/work_package_source.md "$TMP/wps" "$TMP/trans" h2
ls "$TMP/wps"

echo "==> 检查 frontmatter target_file 指向独立译文目录"
grep -q "target_file: $TMP/trans/wp_001.md" "$TMP/wps/wp_001.md" \
  || { echo "target_file 未指向独立译文目录"; exit 1; }

# 辅助函数：保留原 frontmatter，将 body_file 写入独立译文目标
write_translation() {
    local src="$1"
    local dst="$2"
    local body_file="$3"
    python3 - "$src" "$dst" "$body_file" <<'PY'
import sys, re
src, dst, body_file = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src, encoding='utf-8').read()
m = re.search(r'^(---\s*\n.*?\n---\s*\n)', text, re.S)
front = m.group(1) if m else ''
body = open(body_file, encoding='utf-8').read()
with open(dst, 'w', encoding='utf-8') as f:
    f.write(front)
    f.write(body)
PY
}

# 2. 模拟两个 Agent 分别翻译工作包，写入各自唯一目标
cat > "$TMP/body_001.md" <<'EOF'
# 1. Compute Kernel Basics

## 1.1. Thread Hierarchy（线程层次结构）

CUDA kernel 由一个线程块网格执行。
每个线程块包含多个线程。

- 同一 warp 内的线程按锁步执行。
- 一个 warp 有 32 个线程。

```c
__global__ void kernel(int* data) {
    int tid = threadIdx.x;
}
```
EOF

cat > "$TMP/body_002.md" <<'EOF'
## 1.2. Memory Model（内存模型）

CUDA 向程序员暴露多种内存空间。

1. 全局内存可被所有线程访问。
2. 共享内存在线程块内共享。
3. 寄存器对每个线程私有。

> **注（Note）**
> 内存模型对性能调优至关重要。
EOF

cat > "$TMP/body_003.md" <<'EOF'
## 1.3. Warp Scheduling（warp 调度）

warp 调度器每周期选择活跃的 warp。

| 术语 | 含义 |
| --- | --- |
| warp | 32 个线程组成的一组 |
| kernel | 在 GPU 上启动的函数 |
EOF

echo "==> Agent A 翻译 wp_001 -> 独立目标"
write_translation "$TMP/wps/wp_001.md" "$TMP/trans/wp_001.md" "$TMP/body_001.md"

echo "==> Agent A 翻译 wp_002 -> 独立目标"
write_translation "$TMP/wps/wp_002.md" "$TMP/trans/wp_002.md" "$TMP/body_002.md"

echo "==> Agent B 翻译 wp_003 -> 独立目标"
write_translation "$TMP/wps/wp_003.md" "$TMP/trans/wp_003.md" "$TMP/body_003.md"

echo "==> 检查工作包源文件未被译文覆写"
grep -q "A kernel is" "$TMP/wps/wp_001.md" \
  || { echo "工作包源文件被覆写"; exit 1; }

# 3. 合并术语候选：只有主 Agent 批准的词才入库，其余进入待定
cat > "$TMP/approved.txt" <<'EOF'
# 主 Agent 逐条裁决后批准的术语
# warp 采用 Agent A 的“保留英文”口径；Agent B 的“线程束”应被判为冲突
grid
SM
tile
warp
EOF

echo "==> 合并术语候选"
python3 "$MERGE_GLOSSARY" \
    "$TMP/glossary_initial.md" \
    "$TMP/glossary_merged.md" \
    "$TMP/glossary_conflicts.md" \
    --approve "$TMP/approved.txt" \
    --pending "$TMP/glossary_pending.md" \
    "$TMP/term_candidates_a.md" \
    "$TMP/term_candidates_b.md"

echo "==> 检查冲突文件存在且包含 warp 冲突"
grep -i "warp" "$TMP/glossary_conflicts.md" || { echo "未检测到 warp 术语冲突"; exit 1; }

echo "==> 检查合并后的术语表包含已批准新增术语 grid / SM / tile"
grep -i "grid" "$TMP/glossary_merged.md" || { echo "未找到 grid"; exit 1; }
grep -i "SM" "$TMP/glossary_merged.md" || { echo "未找到 SM"; exit 1; }
grep -i "tile" "$TMP/glossary_merged.md" || { echo "未找到 tile"; exit 1; }

echo "==> 检查 kernel 保留现有译法（内核）"
python3 - "$TMP/glossary_merged.md" <<'PY'
import sys
text = open(sys.argv[1], encoding='utf-8').read()
for line in text.splitlines():
    cells = [c.strip() for c in line.split('|')]
    cells = [c for c in cells if c]
    if cells and cells[0].lower() == 'kernel':
        assert cells[1] == '内核', 'kernel 译法被错误覆盖: %r' % cells[1]
print('kernel 现有译法保留正确')
PY

# 4. 合并工作包译文（从独立译文目录）
echo "==> 合并工作包译文"
python3 "$MERGE_WP" "$TMP/merged_translation.md" "$TMP/trans"

echo "==> 检查合并文件按 source_order 排序且包含三个小节"
grep -q "线程层次结构" "$TMP/merged_translation.md" || { echo "合并文件缺少 1.1"; exit 1; }
grep -q "内存模型" "$TMP/merged_translation.md" || { echo "合并文件缺少 1.2"; exit 1; }
grep -q "warp 调度" "$TMP/merged_translation.md" || { echo "合并文件缺少 1.3"; exit 1; }

echo "==> 失败回归：工作包映射缺失、重复或不连续必须判 FAIL"
python3 - "$TMP/trans/wp_001.md" "$TMP/trans/wp_002.md" "$TMP" <<'PY'
import os
import re
import sys

wp1, wp2, out_dir = sys.argv[1:]
text1 = open(wp1, encoding='utf-8').read()
text2 = open(wp2, encoding='utf-8').read()

cases = {
    'missing_order.md': re.sub(r'^source_order:.*\n', '', text1, flags=re.M),
    'duplicate_order.md': re.sub(r'^source_order:.*$', 'source_order: 1', text2, flags=re.M),
    'gap_order.md': re.sub(r'^source_order:.*$', 'source_order: 3', text2, flags=re.M),
    'duplicate_fragment.md': re.sub(
        r'^section_id:.*$', 'section_id: "1.1. Thread Hierarchy"', text2,
        flags=re.M),
}
for name, text in cases.items():
    with open(os.path.join(out_dir, name), 'w', encoding='utf-8') as f:
        f.write(text)
PY

if python3 "$MERGE_WP" "$TMP/bad-missing.md" "$TMP/missing_order.md"; then
    echo "错误：缺少 source_order 的工作包仍被合并"
    exit 1
fi
if python3 "$MERGE_WP" "$TMP/bad-duplicate.md" "$TMP/trans/wp_001.md" "$TMP/duplicate_order.md"; then
    echo "错误：重复 source_order 的工作包仍被合并"
    exit 1
fi
if python3 "$MERGE_WP" "$TMP/bad-gap.md" "$TMP/trans/wp_001.md" "$TMP/gap_order.md"; then
    echo "错误：不连续 source_order 的工作包仍被合并"
    exit 1
fi
if python3 "$MERGE_WP" "$TMP/bad-fragment.md" "$TMP/trans/wp_001.md" "$TMP/duplicate_fragment.md"; then
    echo "错误：重复 section_id/fragment_index 的工作包仍被合并"
    exit 1
fi
echo "非法工作包映射均已正确判 FAIL"

# 5. 模拟中断：删除 wp_002 译文，运行恢复
echo "==> 模拟中断：删除 wp_002 译文"
rm "$TMP/trans/wp_002.md"
echo "==> 运行 recover_work_packages.py"
if python3 "$RECOVER" fixtures/work_package_source.md "$TMP/wps" "$TMP/trans" h2; then
    echo "错误：恢复脚本未报告缺失工作包"
    exit 1
fi
echo "恢复脚本已正确报告缺失与可复用状态"

# 5b. 模拟内容截断的译文不得被复用
echo "==> 模拟截断译文：恢复脚本应判为校验失败而非复用"
cat > "$TMP/trans/wp_002.md" <<'EOF'
## 1.2. Memory Model（内存模型）

（内容截断）
EOF
if python3 "$RECOVER" fixtures/work_package_source.md "$TMP/wps" "$TMP/trans" h2 2>&1 | tee "$TMP/recover2.txt"; then
    echo "错误：截断译文被错误复用"
    exit 1
fi
grep -q "FAIL.*wp_002" "$TMP/recover2.txt" || { echo "截断译文未被判为校验失败"; exit 1; }
echo "截断译文已正确判为需重做"
rm "$TMP/trans/wp_002.md"

# 6. 模拟模型升级：翻译后产生新术语，合并术语表并验证
echo "==> 模拟模型升级：Agent 上报新术语"
cat > "$TMP/upgrade_candidates.md" <<'EOF'
# 模型升级后新术语候选

| 英文原词 | 中文译法 | 处理方式 | 首现 |
|---|---|---|---|
| cooperative groups | 协作组 | 首现附英文 | 1.3. Warp Scheduling |
| memory coalescing | 内存合并访问 | 首现附英文 | 1.2. Memory Model |
EOF

cat > "$TMP/approved_upgrade.txt" <<'EOF'
cooperative groups
memory coalescing
EOF

python3 "$MERGE_GLOSSARY" \
    "$TMP/glossary_merged.md" \
    "$TMP/glossary_upgraded.md" \
    "$TMP/glossary_conflicts_upgrade.md" \
    --approve "$TMP/approved_upgrade.txt" \
    "$TMP/upgrade_candidates.md"

echo "==> 验证升级后术语表包含新术语"
grep -i "cooperative groups" "$TMP/glossary_upgraded.md" || { echo "未找到 cooperative groups"; exit 1; }
grep -i "memory coalescing" "$TMP/glossary_upgraded.md" || { echo "未找到 memory coalescing"; exit 1; }

echo "==> Ticket 05 工作包、术语与恢复闭环回归全部通过"
