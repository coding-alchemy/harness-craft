"""数字与单位复核闭环（二期 Ticket 06）的定向验收。

共享提取/差异职责（_numeric_review）的底层用例：数字写法、保护上下文、
宿主、差异多重集与定位 ID；verify_reference_translation 的 --numeric-review
显式启用/未检查明示；recover 证据 numeric 块核对（覆盖/失效/未处置）。
范围与消费正例见 /tmp 端到端报告（REPORT.md）。
"""
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _numeric_review as numeric
import recover_work_packages as rwp
import verify_reference_translation as vrt


def body_tokens(result):
    return [t for t in result['tokens'] if t['context'] == 'body']


def test_number_forms_preserved():
    text = ('values -12, 1,000,000, 3.5, -0.75, 2.5e-3, 1E6, 42% '
            'and +7 ms\n')
    result = numeric.extract_numeric_tokens(text, 's.md')
    raws = [t['raw'] for t in body_tokens(result)]
    assert raws == ['-12', '1,000,000', '3.5', '-0.75', '2.5e-3', '1E6',
                    '42%', '+7 ms']
    by_raw = {t['raw']: t for t in body_tokens(result)}
    assert by_raw['42%']['unit'] == '%'
    assert by_raw['+7 ms']['unit'] == 'ms'


def test_magnitude_words_chinese_and_english():
    text = '104 billion 参数、2.5 million 用户、250 万行、1.5万、3 亿条\n'
    result = numeric.extract_numeric_tokens(text, 's.md')
    raws = [t['raw'] for t in body_tokens(result)]
    assert raws == ['104 billion', '2.5 million', '250 万', '1.5万', '3 亿']
    magnitudes = {t['raw']: t['magnitude'] for t in body_tokens(result)}
    assert magnitudes['104 billion'] == 'billion'
    assert magnitudes['250 万'] == '万'


def test_protected_contexts_math_code_url_identifier():
    text = (
        '公式 $x = 3$ 与 `int v = 7;` 及块级\n\n'
        '$$E = mc^2$$\n\n'
        '```c\nint x = 42;\n```\n\n'
        '链接 [a](https://example.com/v2/p3) 版本 v2 与 1.2.3\n')
    result = numeric.extract_numeric_tokens(text, 's.md')
    by_context = {}
    for token in result['tokens']:
        by_context.setdefault(token['context'], []).append(token['raw'])
    assert by_context['math'] == ['3', '2']
    assert by_context['code'] == ['7', '42']
    assert by_context['url'] == ['2', '3']
    assert set(by_context['identifier']) == {'2', '1.2', '3'}
    assert '42' not in [t['raw'] for t in body_tokens(result)]


def test_hosts_section_table_caption_footnote():
    text = (
        '# 1. Intro\n\n'
        '正文 5 个。\n\n'
        '| A | B |\n| --- | --- |\n| x | 0.75 |\n\n'
        '**图 1. 曲线（Figure 1. Curve）**\n\n'
        '引用[^n1]。\n\n[^n1]: 脚注 12 字。\n')
    result = numeric.extract_numeric_tokens(text, 's.md')
    body = body_tokens(result)
    inline = next(t for t in body if t['raw'] == '5')
    assert inline['host']['section'] == '1. Intro'
    table = next(t for t in body if t['raw'] == '0.75')
    assert table['host']['table'] and table['host']['section'] == '1. Intro'
    captions = [t for t in body if t['host']['caption']]
    assert captions and all(t['line'] == 9 for t in captions)
    footnotes = [t for t in body if t['host']['footnote'] == 'n1']
    assert {t['raw'] for t in footnotes} == {'12'}


def test_unclassified_marks_unchecked():
    text = '上标 x^2 与 ×10^3，全角１２３，孤立数量级 亿\n'
    result = numeric.extract_numeric_tokens(text, 's.md')
    raws = [t['raw'] for t in result['unclassified']]
    assert '2' in raws and '10' in raws and '１２３' in raws
    assert '亿' in raws
    assert result['unclassified_total'] >= 4


def test_verbatim_zero_diff():
    text = '104 billion 参数，错误率 3.5%，延迟 5 ms。\n'
    review = numeric.compute_numeric_review(text, text, 's', 'd', 'full')
    assert review['diffs'] == []
    assert review['summary']['diffs_src_missing'] == 0


def test_legal_conversion_and_unit_change_diff():
    src = 'The model has 104 billion parameters. Latency 5 ms.\n'
    doc = '模型有 1040 亿参数。延迟 5 s。\n'
    review = numeric.compute_numeric_review(src, doc, 'src.md', 'doc.md',
                                            'full')
    roles = {(d['role'], d['raw']) for d in review['diffs']}
    assert ('src_missing', '104 billion') in roles
    assert ('doc_added', '1040 亿') in roles
    assert ('src_missing', '5 ms') in roles
    assert ('doc_added', '5 s') in roles
    unit_diff = next(d for d in review['diffs'] if d['raw'] == '5 ms')
    assert '同值异单位' in unit_diff['note']


def test_attached_unit_precedes_identifier_classification():
    # 已支持紧附单位优先于标识符判定；未命中整体单位的写法仍列 identifier
    text = '5ms 5s 100ns 1.5h 5m 10gb/s vs 3DES v2 1.2.3 10x 2nd 5msx\n'
    result = numeric.extract_numeric_tokens(text, 's.md')
    by_raw = {t['raw']: t['context'] for t in result['tokens']}
    for attached in ('5ms', '5s', '100ns', '1.5h', '5m', '10gb/s'):
        assert by_raw.get(attached) == 'body'
    body = {t['raw']: t for t in body_tokens(result)}
    assert body['5ms']['unit'] == 'ms'
    assert body['5m']['unit'] == 'm'
    assert body['10gb/s']['unit'] == 'gb/s'
    assert by_raw['3'] == 'identifier'  # 3DES
    assert by_raw['1.2'] == 'identifier'  # 1.2.3
    assert by_raw['10'] == 'identifier'  # 10x
    assert by_raw['2'] == 'identifier'  # 2nd
    assert by_raw['5'] == 'identifier'  # 5msx


def test_attached_unit_change_diff_and_counterpart():
    src = 'Latency 5ms.\n'
    doc = '延迟 5s。\n'
    review = numeric.compute_numeric_review(src, doc, 's.md', 'd.md', 'full')
    roles = {(d['role'], d['raw']) for d in review['diffs']}
    assert roles == {('src_missing', '5ms'), ('doc_added', '5s')}
    for diff in review['diffs']:
        assert '同值异单位' in diff['note']


def test_attached_unit_change_diff_reversed_direction():
    # 反向同值异单位（5s→5ms）同样检出，双向不遗漏
    src = '延迟 5s。\n'
    doc = 'Latency 5ms.\n'
    review = numeric.compute_numeric_review(src, doc, 's.md', 'd.md', 'full')
    roles = {(d['role'], d['raw']) for d in review['diffs']}
    assert roles == {('src_missing', '5s'), ('doc_added', '5ms')}
    for diff in review['diffs']:
        assert '同值异单位' in diff['note']


def test_left_adherent_identifier_not_body_quantity():
    # 左邻字母粘连（TPUv3s 的 3s、Model5ms 的 5ms）是标识符片段，不得
    # 判为正文单位数量；独立 token 5ms 仍是正文单位（第一轮修复成果）
    text = 'Cloud TPUv3s 与 Model5ms 及独立 5ms、100ns\n'
    result = numeric.extract_numeric_tokens(text, 's.md')
    by_raw = {}
    for token in result['tokens']:
        by_raw.setdefault(token['raw'], []).append(token['context'])
    assert by_raw['3'] == ['identifier']
    assert by_raw['5'] == ['identifier']
    assert by_raw['5ms'] == ['body']
    assert by_raw['100ns'] == ['body']
    body = {t['raw']: t for t in body_tokens(result)}
    assert body['5ms']['unit'] == 'ms'
    assert body['100ns']['unit'] == 'ns'


def test_left_adherent_identifier_produces_no_diff():
    # 源/译同名标识符中的数字不参与正文差异；同句独立 5ms→5s 仍检出
    src = 'Cloud TPUv3s and Model5ms, latency 5ms.\n'
    doc = 'Cloud TPUv3s 与 Model5ms，延迟 5s。\n'
    review = numeric.compute_numeric_review(src, doc, 's.md', 'd.md', 'full')
    roles = {(d['role'], d['raw']) for d in review['diffs']}
    assert roles == {('src_missing', '5ms'), ('doc_added', '5s')}
    assert all('TPUv3s' not in d['id'] and 'Model5ms' not in d['id']
               for d in review['diffs'])


def test_percent_omission_located():
    src = 'error rate 3.5% and recall 91.2%.\n'
    doc = '错误率 3.5%，召回率。\n'
    review = numeric.compute_numeric_review(src, doc, 's', 'd', 'full')
    missing = [d for d in review['diffs'] if d['role'] == 'src_missing']
    assert [d['raw'] for d in missing] == ['91.2%']
    assert missing[0]['line'] == 1


def test_same_number_rehosted_has_zero_statistical_diff():
    # 同数换归属：token 多重集不变 → 无统计差异（仍须独立语义复核）
    src = '# A\n\n5 ms\n\n# B\n\n仅文字\n'
    doc = '# A\n\n五\n\n# B\n\n5 ms\n'
    review = numeric.compute_numeric_review(src, doc, 's', 'd', 'full')
    assert review['diffs'] == []


def test_diff_ids_deterministic_and_content_rich():
    src = 'alpha 1.0 beta 1.0\n'
    doc = 'alpha beta\n'
    first = numeric.compute_numeric_review(src, doc, 's.md', 'd.md', 'full')
    second = numeric.compute_numeric_review(src, doc, 's.md', 'd.md', 'full')
    ids_a = [d['id'] for d in first['diffs']]
    assert ids_a == [d['id'] for d in second['diffs']]
    assert len(ids_a) == 2 and len(set(ids_a)) == 2
    for diff in first['diffs']:
        assert '[full][src_missing]' in diff['id']
        assert '1.0' in diff['id'] and '@s.md:L1' in diff['id']
    # 位置变化 → ID 从本次扫描重新生成（不承担跨版本稳定状态）
    moved = numeric.compute_numeric_review('alpha 1.0\n\nbeta 1.0\n',
                                           'alpha\n\nbeta\n',
                                           's.md', 'd.md', 'full')
    ids_moved = [d['id'] for d in moved['diffs']]
    assert ids_moved != ids_a


def test_policy_identity_default_and_file(tmp_path):
    default = numeric.policy_identity(None)
    assert default['path'] is None
    assert '不自动判换算' in default['posture']
    policy = tmp_path / 'policy.txt'
    policy.write_text('104 billion => 1040 亿\n', encoding='utf-8')
    ident = numeric.policy_identity(str(policy))
    assert ident['path'] == str(policy)
    assert ident['posture'] is None and len(ident['sha256']) == 64
    policy.write_text('别的口径\n', encoding='utf-8')
    assert numeric.policy_identity(str(policy))['sha256'] != ident['sha256']
    with pytest.raises(ValueError):
        numeric.policy_identity(str(tmp_path / 'missing.txt'))


def test_numeric_binding_multiset_and_checker():
    src = '104 billion\n'
    doc = '1040 亿\n'
    binding = numeric.numeric_binding(src, doc, 'package')
    assert binding['scope'] == 'package'
    assert binding['policy']['path'] is None
    assert binding['checker']['_numeric_review.py']
    assert len(binding['diff_ids']) == 2
    again = numeric.numeric_binding(src, doc, 'package')
    assert again == binding


# ---- verify_reference_translation 入口（显式启用 / 未检查明示） ----

def _verify(doc, src, **kwargs):
    return vrt.verify(doc, src, [], doc_label='d.md', src_label='s.md',
                      **kwargs)


def test_reference_verify_declares_unchecked_by_default():
    fails, warns = _verify('# CUDA 指南\n\n同样文字 3.5%。\n',
                           '# CUDA 指南\n\nsame text 3.5%.\n')
    assert not fails
    assert any('未启用 --numeric-review' in w for w in warns)


def test_reference_verify_reports_diffs_as_hints_not_fails():
    fails, warns = _verify('# CUDA 指南\n\n模型有 1040 亿参数。\n',
                           '# CUDA 指南\n\nThe model has 104 billion '
                           'parameters.\n', numeric_review=True)
    assert not fails
    hints = [w for w in warns if w.startswith('数字提示')]
    assert len(hints) == 2
    assert any('104 billion @s.md:L3' in w for w in hints)
    assert any('无统计差异' not in w for w in hints)


def test_reference_verify_zero_diff_still_requires_semantic_review():
    fails, warns = _verify('# CUDA 指南\n\n104 billion 参数。\n',
                           '# CUDA 指南\n\n104 billion parameters.\n',
                           numeric_review=True)
    assert not fails
    assert any('无统计差异' in w and '仍须独立语义复核' in w for w in warns)


def test_reference_verify_bad_policy_fails():
    fails, _warns = _verify('# CUDA 指南\n\nx 3.5%。\n',
                            '# CUDA 指南\n\nx 3.5%.\n', numeric_review=True,
                            numeric_policy='/nonexistent/policy.txt')
    assert any('数字辅助' in f for f in fails)


# ---- recover 证据 numeric 块核对 ----

def _entry(diff_ids, disposed, policy=None, checker=None):
    checker = checker or {'_numeric_review.py': 'x'}
    return {
        'source_digest': 's', 'target_digest': rwp._sha256('t'),
        'resource_digests': [],
        'source_resource_digests': [], 'checker': {}, 'strong_tokens': [],
        'review': {'semantic': 'done', 'unresolved': []},
        'numeric': {
            'enabled': True, 'scope': 'package',
            'policy': policy or {'path': None, 'sha256': None,
                                 'posture': numeric.DEFAULT_POSTURE},
            'checker': checker,
            'diff_ids': sorted(diff_ids),
            'disposed': disposed,
        },
    }


def _expected(diff_ids):
    return {
        'enabled': True, 'scope': 'package',
        'policy': {'path': None, 'sha256': None,
                   'posture': numeric.DEFAULT_POSTURE},
        'checker': {'_numeric_review.py': 'x'},
        'diff_ids': sorted(diff_ids),
    }


def test_evidence_numeric_full_disposition_passes():
    entry = _entry(['NUM[package][src_missing]#1 1 @s:L1'], ['NUM[package][src_missing]#1 1 @s:L1'])
    assert rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], [],
        numeric_expected=_expected(['NUM[package][src_missing]#1 1 @s:L1'])) == []


def test_evidence_numeric_missing_block_invalid():
    entry = _entry([], [])
    del entry['numeric']
    bad = rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], [], numeric_expected=_expected([]))
    assert any('numeric 块' in reason for reason in bad)


def test_evidence_numeric_stale_or_foreign_id_rejected():
    entry = _entry([], ['NUM[full][src_missing]#1 1 @s:L1'])
    bad = rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], [], numeric_expected=_expected([]))
    assert any('历史/其他目标 ID 无效' in reason for reason in bad)


def test_evidence_numeric_unresolved_blocks():
    entry = _entry(['NUM[package][src_missing]#1 1 @s:L1',
                    'NUM[package][doc_added]#1 2 @d:L1'], [])
    bad = rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], [],
        numeric_expected=_expected(['NUM[package][src_missing]#1 1 @s:L1',
                                    'NUM[package][doc_added]#1 2 @d:L1']))
    assert any('未处置数字差异项' in reason for reason in bad)


def test_evidence_numeric_policy_drift_invalidates():
    entry = _entry([], [], policy={'path': '/p', 'sha256': 'a',
                                    'posture': None})
    bad = rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], [], numeric_expected=_expected([]))
    assert any('数字复核绑定失效' in reason for reason in bad)


def test_evidence_numeric_checker_drift_invalidates():
    entry = _entry([], [], checker={'_numeric_review.py': 'old'})
    bad = rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], [], numeric_expected=_expected([]))
    assert any('数字复核绑定失效' in reason for reason in bad)


def test_evidence_without_numeric_still_valid_when_disabled():
    entry = {
        'source_digest': 's', 'target_digest': rwp._sha256('t'),
        'resource_digests': [], 'source_resource_digests': [],
        'checker': {}, 'strong_tokens': [],
        'review': {'semantic': 'done', 'unresolved': []},
    }
    assert rwp.evidence_binding_problems(
        entry, 's', 't', [], {}, [], []) == []
