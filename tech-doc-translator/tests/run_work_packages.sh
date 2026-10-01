#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT="../skills/tech-doc-translator"
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
sys.path.insert(0, '../skills/tech-doc-translator/scripts')
import recover_work_packages as recover
import split_work_packages as split

lines = ['**Figure caption**', '--- | --- | ---', '- real item']
assert split._count_blocks(lines)['list_items'] == 1
assert split._count_blocks('\n'.join(lines))['list_items'] == 1
print('列表项计数排除粗体与表格分隔行 PASS')
PY

# 1. split 源文件为工作包；译文目标是独立目录，不得覆写工作包源
echo "==> 拆分源文件为工作包"
python3 "$SPLIT" fixtures/work_package_source.md "$TMP/wps" "$TMP/trans" h2
ls "$TMP/wps"

echo "==> 检查 frontmatter target_file 指向独立译文目录"
grep -q "target_file: $TMP/trans/wp_001.md" "$TMP/wps/wp_001.md" \
  || { echo "target_file 未指向独立译文目录"; exit 1; }

echo "==> 检查 frontmatter rules_path 从任意 cwd 都可解析"
RULES_PATH=$(sed -n 's/^rules_path: //p' "$TMP/wps/wp_001.md" | head -1)
if [ -z "$RULES_PATH" ] || [ ! -f "$RULES_PATH" ]; then
    echo "rules_path 无法解析为已存在的翻译约定文件: $RULES_PATH"
    exit 1
fi

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

echo "==> 生成逐包复核证据（绑定当前源资源/源片段/译文/脚本身份）"
cat > "$TMP/gen_evidence.py" <<'PY'
import contextlib
import io
import json
import os
import re
import sys

sys.path.insert(0, '../skills/tech-doc-translator/scripts')
import recover_work_packages as rwp
import split_work_packages as swp

source, trans_dir, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
names = sys.argv[4:] or None
base = '../skills/tech-doc-translator/scripts'
checker = {
    name: rwp.file_sha256(os.path.join(base, name))
    for name in ('recover_work_packages.py', '_verification.py',
                 'split_work_packages.py')
}
tmp_dir = os.path.dirname(os.path.abspath(out_path))
with contextlib.redirect_stdout(io.StringIO()):
    expected = swp.split(source, os.path.join(tmp_dir, 'exp_wps'),
                         os.path.join(tmp_dir, 'exp_trans'), 'h2')


def body_of(path):
    text = open(path, encoding='utf-8').read()
    m = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.S)
    return text[m.end():] if m else text


def meta_of(path):
    text = open(path, encoding='utf-8').read()
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip()
    return meta


ev = {}
for p in expected:
    name = os.path.basename(p)
    if names and name not in names:
        continue
    trans_path = os.path.join(trans_dir, name)
    if not os.path.isfile(trans_path):
        continue
    tbody = body_of(trans_path)
    ev[name] = {
        'source_digest': meta_of(p)['fragment_digest'],
        'target_digest': rwp._sha256(tbody),
        'resource_digests': rwp._resource_digests(
            tbody, os.path.dirname(os.path.abspath(trans_path))),
        'source_resource_digests': rwp._source_resource_digests(
            body_of(p), os.path.dirname(os.path.abspath(source))),
        'checker': checker,
        'strong_tokens': [],
        'review': {'semantic': 'done', 'unresolved': []},
    }
json.dump(ev, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False)
PY
python3 "$TMP/gen_evidence.py" "$PWD/fixtures/work_package_source.md" \
    "$TMP/trans" "$TMP/evidence.json" wp_001.md wp_002.md wp_003.md

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

# 4. 合并工作包译文（全量依据：当前源 + 策略 + 源包映射 + 逐包复核证据）
echo "==> 合并工作包译文（带全量依据与复核证据）"
MERGE_BASIS="--source $PWD/fixtures/work_package_source.md --strategy h2 --source-packages $TMP/wps --review-evidence $TMP/evidence.json"
python3 "$MERGE_WP" "$TMP/merged_translation.md" "$TMP/trans" $MERGE_BASIS

echo "==> 检查合并文件按 source_order 排序且包含三个小节"
grep -q "线程层次结构" "$TMP/merged_translation.md" || { echo "合并文件缺少 1.1"; exit 1; }
grep -q "内存模型" "$TMP/merged_translation.md" || { echo "合并文件缺少 1.2"; exit 1; }
grep -q "warp 调度" "$TMP/merged_translation.md" || { echo "合并文件缺少 1.3"; exit 1; }

echo "==> 失败回归：无依据合并必须报告输入不足"
if python3 "$MERGE_WP" "$TMP/nobasis.md" "$TMP/trans" >"$TMP/nobasis.txt" 2>&1; then
    echo "错误：无全量依据的合并仍报告成功"
    exit 1
fi
grep -q "输入不足" "$TMP/nobasis.txt" || { echo "错误：缺少输入不足诊断"; cat "$TMP/nobasis.txt"; exit 1; }
echo "无依据合并已正确拒绝（D3）"

echo "==> 失败回归：缺少 --review-evidence 的合并必须报告输入不足"
if python3 "$MERGE_WP" "$TMP/noev.md" "$TMP/trans" \
    --source "$PWD/fixtures/work_package_source.md" --strategy h2 \
    --source-packages "$TMP/wps" >"$TMP/noev.txt" 2>&1; then
    echo "错误：缺少复核证据的合并仍报告成功"
    exit 1
fi
grep -q -- "--review-evidence" "$TMP/noev.txt" \
  || { echo "错误：缺少证据参数诊断"; cat "$TMP/noev.txt"; exit 1; }
echo "无复核证据的合并已正确拒绝（不能因省略参数绕过复核）"

echo "==> 失败回归：缺尾包/重复键/缺字段/额外包/异源包必须按原因失败"
python3 - "$TMP/trans/wp_001.md" "$TMP/trans/wp_002.md" "$TMP" <<'PY'
import os
import re
import sys

wp1, wp2, out_dir = sys.argv[1:]
text1 = open(wp1, encoding='utf-8').read()
text2 = open(wp2, encoding='utf-8').read()
text3 = open(os.path.join(out_dir, 'trans', 'wp_003.md'), encoding='utf-8').read()

cases = {
    'missing_order.md': re.sub(r'^source_order:.*\n', '', text1, flags=re.M),
    'duplicate_fragment.md': re.sub(
        r'^section_id:.*$', 'section_id: "1.1. Thread Hierarchy"', text2,
        flags=re.M),
    'foreign_source.md': re.sub(
        r'^source_file:.*$', 'source_file: /other/project/source.md', text3,
        flags=re.M),
    'extra_package.md': re.sub(
        r'^section_id:.*$', 'section_id: "9.9. Fake Section"', text3,
        flags=re.M),
}
for name, text in cases.items():
    with open(os.path.join(out_dir, name), 'w', encoding='utf-8') as f:
        f.write(text)
PY

if python3 "$MERGE_WP" "$TMP/bad-missing.md" "$TMP/missing_order.md" $MERGE_BASIS >"$TMP/bad1.txt" 2>&1; then
    echo "错误：缺少 source_order 的工作包仍被合并"
    exit 1
fi
if python3 "$MERGE_WP" "$TMP/bad-fragment.md" "$TMP/trans/wp_001.md" "$TMP/duplicate_fragment.md" $MERGE_BASIS >"$TMP/bad2.txt" 2>&1; then
    echo "错误：重复小节实例/片段键的工作包仍被合并"
    exit 1
fi
grep -q "重复包" "$TMP/bad2.txt" || { echo "错误：缺少重复包诊断"; cat "$TMP/bad2.txt"; exit 1; }
if python3 "$MERGE_WP" "$TMP/bad-foreign.md" "$TMP/trans/wp_001.md" "$TMP/trans/wp_002.md" "$TMP/foreign_source.md" $MERGE_BASIS >"$TMP/bad3.txt" 2>&1; then
    echo "错误：异源包仍被合并"
    exit 1
fi
grep -q "异源包" "$TMP/bad3.txt" || { echo "错误：缺少异源诊断"; cat "$TMP/bad3.txt"; exit 1; }
if python3 "$MERGE_WP" "$TMP/bad-extra.md" "$TMP/trans/wp_001.md" "$TMP/trans/wp_002.md" "$TMP/trans/wp_003.md" "$TMP/extra_package.md" $MERGE_BASIS >"$TMP/bad4.txt" 2>&1; then
    echo "错误：额外包仍被合并"
    exit 1
fi
grep -q "额外包" "$TMP/bad4.txt" || { echo "错误：缺少额外包诊断"; cat "$TMP/bad4.txt"; exit 1; }
echo "非法映射均已按对应原因 FAIL"

echo "==> 失败回归：错误顺序/错误目标/正文丢失的包不得进入全量成品"
python3 - "$TMP/trans/wp_002.md" "$TMP" <<'PY'
import os
import re
import sys

src_path, out_dir = sys.argv[1], sys.argv[2]
text = open(src_path, encoding='utf-8').read()
front = re.match(r'^(---\s*\n.*?\n---\s*\n)', text, re.S).group(1)
open(os.path.join(out_dir, 'wrong_order.md'), 'w', encoding='utf-8').write(
    text.replace('source_order: 2', 'source_order: 999'))
open(os.path.join(out_dir, 'wrong_target.md'), 'w', encoding='utf-8').write(
    re.sub(r'target_file: [^\n]+',
           'target_file: %s/nowhere.md' % out_dir, text))
open(os.path.join(out_dir, 'body_lost.md'), 'w', encoding='utf-8').write(
    front + '## 1.2. Memory Model（内存模型）\n')
PY
if python3 "$MERGE_WP" "$TMP/bad-order.md" "$TMP/trans/wp_001.md" \
    "$TMP/trans/wp_003.md" "$TMP/wrong_order.md" $MERGE_BASIS >"$TMP/bad5.txt" 2>&1; then
    echo "错误：错误顺序映射仍被合并"
    exit 1
fi
grep -q "错误顺序映射" "$TMP/bad5.txt" || { echo "错误：缺少顺序映射诊断"; cat "$TMP/bad5.txt"; exit 1; }
if python3 "$MERGE_WP" "$TMP/bad-target.md" "$TMP/trans/wp_001.md" \
    "$TMP/trans/wp_003.md" "$TMP/wrong_target.md" $MERGE_BASIS >"$TMP/bad6.txt" 2>&1; then
    echo "错误：不存在的目标路径仍被合并"
    exit 1
fi
grep -q "错误目标映射" "$TMP/bad6.txt" || { echo "错误：缺少目标映射诊断"; cat "$TMP/bad6.txt"; exit 1; }
if python3 "$MERGE_WP" "$TMP/bad-lost.md" "$TMP/trans/wp_001.md" \
    "$TMP/trans/wp_003.md" "$TMP/body_lost.md" $MERGE_BASIS >"$TMP/bad7.txt" 2>&1; then
    echo "错误：正文全部丢失且证据不符的包仍被合并为全量成品"
    exit 1
fi
grep -q "无有效复用资格" "$TMP/bad7.txt" \
  && grep -q "目标正文摘要与当前译文不符" "$TMP/bad7.txt" \
  || { echo "错误：缺少证据绑定诊断"; cat "$TMP/bad7.txt"; exit 1; }
for f in bad-order.md bad-target.md bad-lost.md; do
    test ! -e "$TMP/$f" || { echo "错误：拒绝合并仍写出成品 $f"; exit 1; }
done
echo "错误顺序/错误目标/正文丢失均已按对应原因拒绝，未产生成品"

echo "==> 失败回归：交换现存目标路径/指向无关现存文件必须按权威映射拒绝"
python3 - "$TMP" <<'PY'
import os
import re
import sys

tmp = sys.argv[1]
t1 = open(os.path.join(tmp, 'trans', 'wp_001.md'), encoding='utf-8').read()
t2 = open(os.path.join(tmp, 'trans', 'wp_002.md'), encoding='utf-8').read()
# 交换两个现存目标路径：文件都存在且唯一，但与源包权威映射不符
open(tmp + '/swap_a.md', 'w', encoding='utf-8').write(
    re.sub(r'^target_file:.*$', 'target_file: %s/trans/wp_002.md' % tmp,
           t1, flags=re.M))
open(tmp + '/swap_b.md', 'w', encoding='utf-8').write(
    re.sub(r'^target_file:.*$', 'target_file: %s/trans/wp_001.md' % tmp,
           t2, flags=re.M))
# 指向另一个现存但无关的文件
open(tmp + '/unrelated_target.md', 'w', encoding='utf-8').write(
    re.sub(r'^target_file:.*$', 'target_file: %s/merged_translation.md' % tmp,
           t2, flags=re.M))
PY
if python3 "$MERGE_WP" "$TMP/bad-swap.md" "$TMP/swap_a.md" "$TMP/swap_b.md" \
    "$TMP/trans/wp_003.md" $MERGE_BASIS >"$TMP/bad8.txt" 2>&1; then
    echo "错误：交换现存目标路径仍被合并"
    exit 1
fi
grep -q "错误目标映射" "$TMP/bad8.txt" \
  || { echo "错误：缺少交换目标诊断"; cat "$TMP/bad8.txt"; exit 1; }
if python3 "$MERGE_WP" "$TMP/bad-unrelated.md" "$TMP/trans/wp_001.md" \
    "$TMP/unrelated_target.md" "$TMP/trans/wp_003.md" $MERGE_BASIS >"$TMP/bad9.txt" 2>&1; then
    echo "错误：指向无关现存文件仍被合并"
    exit 1
fi
grep -q "错误目标映射" "$TMP/bad9.txt" \
  || { echo "错误：缺少无关目标诊断"; cat "$TMP/bad9.txt"; exit 1; }
for f in bad-swap.md bad-unrelated.md; do
    test ! -e "$TMP/$f" || { echo "错误：拒绝合并仍写出成品 $f"; exit 1; }
done
echo "交换现存目标与指向无关现存文件均按源包权威映射拒绝，未产生成品"

echo "==> 完整性-07：缺首/中/尾包与逆序/局部范围（A6/A7）"
if python3 "$MERGE_WP" "$TMP/incomplete_tail.md" "$TMP/trans/wp_001.md" "$TMP/trans/wp_002.md" $MERGE_BASIS >"$TMP/miss_tail.txt" 2>&1; then
    echo "错误：缺尾包仍被合并"
    exit 1
fi
grep -q "缺少工作包" "$TMP/miss_tail.txt" && grep -q "order=3" "$TMP/miss_tail.txt" \
  || { echo "错误：缺少缺尾包定位"; cat "$TMP/miss_tail.txt"; exit 1; }
if python3 "$MERGE_WP" "$TMP/incomplete_head.md" "$TMP/trans/wp_002.md" "$TMP/trans/wp_003.md" $MERGE_BASIS >"$TMP/miss_head.txt" 2>&1; then
    echo "错误：缺首包仍被合并"
    exit 1
fi
grep -q "order=1" "$TMP/miss_head.txt" \
  || { echo "错误：缺少缺首包定位"; cat "$TMP/miss_head.txt"; exit 1; }
echo "缺首/尾包均按当前源全量范围对照定位 FAIL"

python3 "$MERGE_WP" "$TMP/merged_reversed.md" "$TMP/trans/wp_003.md" \
    "$TMP/trans/wp_001.md" "$TMP/trans/wp_002.md" $MERGE_BASIS >/dev/null
python3 - "$TMP" <<'PY'
import sys

a = open(sys.argv[1] + '/merged_translation.md', encoding='utf-8').read()
b = open(sys.argv[1] + '/merged_reversed.md', encoding='utf-8').read()
assert a == b, '逆序实参的合并结果与源顺序不一致'
print('逆序实参按源顺序装配 PASS')
PY

python3 "$MERGE_WP" "$TMP/merged_local.md" "$TMP/trans/wp_001.md" \
    "$TMP/trans/wp_003.md" $MERGE_BASIS --scope 1,3 >/dev/null
grep -q "线程层次结构" "$TMP/merged_local.md" || { echo "局部合并缺少 1.1"; exit 1; }
grep -q "warp 调度" "$TMP/merged_local.md" || { echo "局部合并缺少 1.3"; exit 1; }
if grep -q "内存模型" "$TMP/merged_local.md"; then
    echo "错误：局部范围混入未声明内容"
    exit 1
fi
echo "显式局部范围恰好交付一次（A7 局部）"

echo "==> 完整性-07：A12 接缝注入被最终复验检出且原成品不变"
python3 "$MERGE_WP" "$TMP/final.md" "$TMP/trans" $MERGE_BASIS >/dev/null
BEFORE=$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$TMP/final.md")
python3 - "$TMP" <<'PY'
import sys

path = sys.argv[1] + '/trans/wp_002.md'
with open(path, 'a', encoding='utf-8') as f:
    f.write('\n```c\nint injected = 0;\n```\n')
PY
# 注入后重新生成逐包证据：模拟每个包单独验证通过的情形，接缝损伤
# 仍必须被合并候选的最终复验检出
python3 "$TMP/gen_evidence.py" "$PWD/fixtures/work_package_source.md" \
    "$TMP/trans" "$TMP/evidence.json" wp_001.md wp_002.md wp_003.md
if python3 "$MERGE_WP" "$TMP/final.md" "$TMP/trans" $MERGE_BASIS >"$TMP/seam_err.txt" 2>&1; then
    echo "错误：接缝注入的代码块未被最终复验检出"
    exit 1
fi
grep -q "代码逐块核对" "$TMP/seam_err.txt" \
  || { echo "错误：缺少接缝差异诊断"; cat "$TMP/seam_err.txt"; exit 1; }
AFTER=$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$TMP/final.md")
if [ "$BEFORE" != "$AFTER" ]; then
    echo "错误：复验失败后原成品被破坏"
    exit 1
fi
python3 - "$TMP" <<'PY'
import sys

# 还原 wp_002 译文正文（去掉注入段），保持后续用例可用
path = sys.argv[1] + '/trans/wp_002.md'
text = open(path, encoding='utf-8').read()
text = text.replace('\n```c\nint injected = 0;\n```\n', '')
open(path, 'w', encoding='utf-8').write(text)
print('接缝注入样本已还原')
PY
python3 "$TMP/gen_evidence.py" "$PWD/fixtures/work_package_source.md" \
    "$TMP/trans" "$TMP/evidence.json" wp_001.md wp_002.md wp_003.md
python3 "$MERGE_WP" "$TMP/final.md" "$TMP/trans" $MERGE_BASIS >/dev/null
echo "A12：接缝注入被检出，原成品保持不变，修复后重新合并成功"

# 5. 模拟中断：删除 wp_002 译文，运行恢复
echo "==> 模拟中断：删除 wp_002 译文"

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

echo "==> 完整性-03：安全拆包与无损还原"
cat > "$TMP/adv_src.md" <<'EOF'
# 1. Advanced Sample

## 1.1. Fences

外层说明。

````python
## 2. Not A Real Heading
```c
inner = 1
```
````

## 1.2. Notes

引用[^1]和[^2]。

## 1.2. Notes

B 内容（同名小节）。

![fig](images/adv.png)

**图 1. 示例图题（Caption）**

[^1]: 脚注一。
[^2]: 脚注二。
EOF
python3 "$SPLIT" "$TMP/adv_src.md" "$TMP/adv_wps" "$TMP/adv_trans" h2
python3 - "$TMP/adv_src.md" "$TMP/adv_wps" <<'PY'
import os
import re
import sys

src = open(sys.argv[1], encoding='utf-8').read()
wps = sys.argv[2]
packages = []
for name in sorted(os.listdir(wps)):
    if not name.endswith('.md'):
        continue
    text = open(os.path.join(wps, name), encoding='utf-8').read()
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip()
    packages.append((meta, text[m.end():]))

# 围栏内 H2 与内嵌围栏保持同一包，代码不被拆坏
fence_pkgs = [b for _, b in packages if '## 2. Not A Real Heading' in b]
assert len(fence_pkgs) == 1 and '```c' in fence_pkgs[0] \
    and 'inner = 1' in fence_pkgs[0], '围栏被拆坏或计为正文结构'
# 跨节脚注依赖：引用与定义合并进同一包
note_pkgs = [b for _, b in packages if '引用[^1]和[^2]' in b]
assert len(note_pkgs) == 1 and '[^1]: 脚注一。' in note_pkgs[0], \
    '脚注依赖未扩大连续范围'
# 图片与图题不被分离
for _, body in packages:
    has_image = '![fig]' in body
    has_caption = '**图 1.' in body
    assert not (has_image or has_caption) or (has_image and has_caption), \
        '图片与图题被切点分离'
# 按序还原与源逐字节一致
assert '\n'.join(b for _, b in packages) == src, '包正文还原与源不一致'
# 同名小节、各包有唯一行范围映射
assert len({m['source_line_start'] for m, _ in packages}) == len(packages)
print('安全拆包：围栏/脚注依赖/图题/还原检查 PASS')
PY

cat > "$TMP/dup_src.md" <<'EOF'
## Dup

A

## Dup

B
EOF
python3 "$SPLIT" "$TMP/dup_src.md" "$TMP/dup_wps" "$TMP/dup_trans" h2 >/dev/null
python3 - "$TMP/dup_wps" <<'PY'
import os
import re
import sys

wps = sys.argv[1]
instances = []
for name in sorted(os.listdir(wps)):
    if not name.endswith('.md'):
        continue
    text = open(os.path.join(wps, name), encoding='utf-8').read()
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    for line in m.group(1).splitlines():
        if line.startswith('section_instance:'):
            instances.append(line.split(':', 1)[1].strip())
assert sorted(instances) == ['1', '2'], '同名小节实例区分失败: %s' % instances
print('同名小节实例区分 PASS')
PY

cat > "$TMP/huge_src.md" <<'EOF'
## Huge

```c
LONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONG
LONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONGLONG
```

结尾段落。
EOF
python3 "$SPLIT" "$TMP/huge_src.md" "$TMP/huge_wps" "$TMP/huge_trans" chars:50 \
    >"$TMP/huge_out.txt" 2>&1
grep -q '超限保留整包' "$TMP/huge_out.txt" \
  || { echo "错误：缺少超限报告"; cat "$TMP/huge_out.txt"; exit 1; }
echo "单个不可拆块超限保留整包并报告 PASS"

if python3 "$SPLIT" "$TMP/dup_src.md" "$TMP/dup_same" "$TMP/dup_same" h2; then
  echo "错误：目标与工作包目录相同未拒绝"
  exit 1
fi
python3 - "$TMP" <<'PY'
import os
import sys

tmp = sys.argv[1]
target = os.path.join(tmp, 'dup_trans', 'wp_001.md')
with open(target, 'w', encoding='utf-8') as f:
    f.write('译文内容，重复拆包不得改写')
PY
python3 "$SPLIT" "$TMP/dup_src.md" "$TMP/dup_wps" "$TMP/dup_trans" h2 >/dev/null
python3 - "$TMP" <<'PY'
import os
import sys

target = os.path.join(sys.argv[1], 'dup_trans', 'wp_001.md')
assert open(target, encoding='utf-8').read() == '译文内容，重复拆包不得改写', \
    '重复拆包改写了既有译文'
print('目标与源分离校验、重复拆包不改写译文 PASS')
PY

echo "==> 完整性-06：源变更定位/证据复用/篡改后待复核"
# 重建 wp_002 译文（前序用例已删除），再生成源变更副本
write_translation "$TMP/wps/wp_002.md" "$TMP/trans/wp_002.md" "$TMP/body_002.md"
python3 - "$TMP" <<'PY'
import sys

tmp = sys.argv[1]
text = open('fixtures/work_package_source.md', encoding='utf-8').read()
assert 'A warp has 32 threads.' in text
open(tmp + '/changed_source.md', 'w', encoding='utf-8').write(
    text.replace('A warp has 32 threads.', 'A warp has 64 threads.'))
PY
if python3 "$RECOVER" "$TMP/changed_source.md" "$TMP/wps" "$TMP/trans" h2 \
    >"$TMP/recover3.txt" 2>&1; then
  echo "错误：源变更后仍整体通过"
  exit 1
fi
grep -q 'wp_001.md (order=1): 源片段已变化' "$TMP/recover3.txt" \
  || { echo "错误：源变更未定位到受影响包"; cat "$TMP/recover3.txt"; exit 1; }
grep -q '\[PENDING\] wp_002.md' "$TMP/recover3.txt" \
  || { echo "错误：无证据包应为待复核"; cat "$TMP/recover3.txt"; exit 1; }
echo "源变更定位到受影响包；无证据包输出待复核"

python3 "$TMP/gen_evidence.py" "$TMP/changed_source.md" \
    "$TMP/trans" "$TMP/evidence.json" wp_002.md wp_003.md
if python3 "$RECOVER" "$TMP/changed_source.md" "$TMP/wps" "$TMP/trans" h2 \
    --review-evidence "$TMP/evidence.json" >"$TMP/recover4.txt" 2>&1; then
  echo "错误：源已变化的 wp_001 不应整体通过"
  exit 1
fi
grep -q '\[OK\] wp_002.md' "$TMP/recover4.txt" \
  || { echo "错误：有效证据未使 wp_002 复用"; cat "$TMP/recover4.txt"; exit 1; }
grep -q '\[OK\] wp_003.md' "$TMP/recover4.txt" \
  || { echo "错误：有效证据未使 wp_003 复用"; cat "$TMP/recover4.txt"; exit 1; }
echo "有效证据使未受影响包可复验复用（A3）"

python3 - "$TMP" <<'PY'
import sys

path = sys.argv[1] + '/trans/wp_002.md'
with open(path, 'a', encoding='utf-8') as f:
    f.write('多出来的一个字')
PY
if python3 "$RECOVER" "$TMP/changed_source.md" "$TMP/wps" "$TMP/trans" h2 \
    --review-evidence "$TMP/evidence.json" >"$TMP/recover5.txt" 2>&1; then
  echo "错误：目标篡改后仍复用"
  exit 1
fi
grep -q 'wp_002.md (order=2): 证据失效' "$TMP/recover5.txt" \
  || { echo "错误：缺少证据失效诊断"; cat "$TMP/recover5.txt"; exit 1; }
echo "目标改一个字后旧证据失效，输出待复核"

echo "==> 完整性-08：源资源内容绑定（源图片字节变化使旧证据失效）"
mkdir -p "$TMP/img_src/images" "$TMP/img_trans/images"
cat > "$TMP/img_src/img_source.md" <<'EOF'
## Image Section

看图。

![示意](images/d.svg)
EOF
printf '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="red"/></svg>' \
  > "$TMP/img_src/images/d.svg"
python3 "$SPLIT" "$TMP/img_src/img_source.md" "$TMP/img_wps" "$TMP/img_trans" h2 \
  >/dev/null
cat > "$TMP/img_body.md" <<'EOF'
## Image Section（图示小节）

看图。

![示意](images/d.svg)
EOF
write_translation "$TMP/img_wps/wp_001.md" "$TMP/img_trans/wp_001.md" "$TMP/img_body.md"
printf '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="red"/></svg>' \
  > "$TMP/img_trans/images/d.svg"
python3 "$TMP/gen_evidence.py" "$TMP/img_src/img_source.md" \
    "$TMP/img_trans" "$TMP/img_evidence.json" wp_001.md
python3 "$RECOVER" "$TMP/img_src/img_source.md" "$TMP/img_wps" "$TMP/img_trans" h2 \
    --review-evidence "$TMP/img_evidence.json" >"$TMP/img_rec1.txt" 2>&1 \
  || { echo "错误：源资源未变化时有效证据应可复用"; cat "$TMP/img_rec1.txt"; exit 1; }
grep -q '\[OK\] wp_001.md' "$TMP/img_rec1.txt" \
  || { echo "错误：有效证据未使含图包复用"; cat "$TMP/img_rec1.txt"; exit 1; }
echo "源资源未变化且证据有效时含图包正常复用"
printf '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="blue"/></svg>' \
  > "$TMP/img_src/images/d.svg"
if python3 "$RECOVER" "$TMP/img_src/img_source.md" "$TMP/img_wps" "$TMP/img_trans" h2 \
    --review-evidence "$TMP/img_evidence.json" >"$TMP/img_rec2.txt" 2>&1; then
  echo "错误：仅改源图片字节后旧译文仍可复用"
  exit 1
fi
grep -q '\[PENDING\] wp_001.md' "$TMP/img_rec2.txt" \
  && grep -q '源资源摘要与当前源资源不符' "$TMP/img_rec2.txt" \
  || { echo "错误：缺少源资源失效诊断"; cat "$TMP/img_rec2.txt"; exit 1; }
echo "仅修改源图片字节（不改 Markdown）即令复用资格失效，输出待复核"
printf '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="red"/></svg>' \
  > "$TMP/img_src/images/d.svg"
python3 "$RECOVER" "$TMP/img_src/img_source.md" "$TMP/img_wps" "$TMP/img_trans" h2 \
    --review-evidence "$TMP/img_evidence.json" >"$TMP/img_rec3.txt" 2>&1 \
  || { echo "错误：源图恢复后应重新可复用"; cat "$TMP/img_rec3.txt"; exit 1; }
grep -q '\[OK\] wp_001.md' "$TMP/img_rec3.txt" \
  || { echo "错误：源图恢复后未恢复复用"; cat "$TMP/img_rec3.txt"; exit 1; }
echo "源图恢复原内容后同一证据重新可复用"

echo "==> Ticket 05 工作包、术语与恢复闭环回归全部通过"

echo "==> 翻译留痕 06：交付完成统一检查（目录允许清单/持久证据/复核闭合）"
PYTHONDONTWRITEBYTECODE=1 python3 test_delivery_evidence.py 2>&1 | tail -1
