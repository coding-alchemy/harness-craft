"""第 2 批 R11：数字差异 ID 用数值加前后文定位，格式修改不改变 ID。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _numeric_review as numeric

ROW = '| a | 7 |'
SAME = 'NUM[full][doc_added] 7 @d.md ‹| a | | | | a›#%d'
LAST = 'NUM[full][doc_added] 7 @d.md ‹| a | | | ›#1'


def added_ids(doc):
    review = numeric.compute_numeric_review('x\n', doc, 's.md', 'd.md', 'full')
    return [d['id'] for d in review['diffs']]


def test_id_uses_context_not_line_number():
    review = numeric.compute_numeric_review(
        'The model has 104 billion parameters.\n', '模型参数。\n', 's.md', 'd.md', 'full')
    diff, = review['diffs']
    assert diff['id'] == 'NUM[full][src_missing] 104 billion @s.md ‹l has | param›#1'
    assert (diff['before'], diff['after']) == ('l has ', ' param')


def test_format_changes_keep_ids():
    src = 'alpha 1.0 beta 1.0\n'
    reformatted = ('<a id="x"></a>alpha 1.0\n\n'
                   '<div style="break-before: page"></div>\n\nbeta\n1.0\n')
    first = numeric.compute_numeric_review(src, 'alpha beta\n', 's.md', 'd.md', 'full')
    second = numeric.compute_numeric_review(reformatted, 'alpha beta\n', 's.md', 'd.md', 'full')
    ids = [d['id'] for d in first['diffs']]
    assert len(set(ids)) == 2
    assert [d['id'] for d in second['diffs']] == ids
    assert [d['line'] for d in second['diffs']] == [1, 6]


def test_repeated_number_in_same_context_numbered_in_order():
    ids = added_ids('\n'.join([ROW] * 4) + '\n')
    assert ids == [SAME % 1, SAME % 2, SAME % 3, LAST]
    # 前面插入无关段落：编号不变
    assert added_ids('# 标题\n\n引言。\n\n' + '\n'.join([ROW] * 4) + '\n') == ids
    # 删掉其中一个：只有后面的编号变化，其余 ID 不变
    assert added_ids('\n'.join([ROW] * 3) + '\n') == [SAME % 1, SAME % 2, LAST]


def test_changed_number_or_nearby_text_gets_new_id():
    base = added_ids('耗时 7 秒，单位不变。\n')
    assert added_ids('耗时 8 秒，单位不变。\n') != base
    assert added_ids('用时 7 秒，单位不变。\n') != base
    assert added_ids('耗时 7 秒，单位不变。\n\n另起一段。\n') == base


def test_hint_shows_line_number():
    review = numeric.compute_numeric_review('a\n\nb 5 ms\n', 'a\n\nb\n', 's.md', 'd.md', 'full')
    hint = numeric.format_diff_hint(review['diffs'][0])
    assert hint.startswith('数字提示 NUM[full][src_missing] 5 ms @s.md ‹')
    assert '（L3' in hint
