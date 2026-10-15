"""四族数字复核覆盖（二期 Ticket 07）的定向验收。

只验证本族输入解释、范围与消费差异：各族 parse_args 的数字键、核验
核心的提示输出（共用 _numeric_review 的底层规则不在此重复）、
verify_delivery 检查事实的数字参数/口径投影。共享提取/差异、ID 规则
与语义待项消费的底层用例见 test_numeric_review.py；各族端到端正反例
见 /tmp/tdt-verify-07/REPORT.md。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import verify_api_translation as v_api
import verify_delivery as delivery
import verify_paginated_translation as v_paginated
import verify_pdf_source
import verify_translation as v_single

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'

SRC_SINGLE = ('# Guide\n\n## 1. Setup\n\n'
              'The model has 104 billion parameters.\n\n'
              'Error rate 3.5%, latency 5 ms.\n')
DOC_SINGLE = ('# Guide（指南）\n\n## 1. Setup（安装）\n\n'
              '模型有 1040 亿参数。\n\n错误率 3.5%，延迟 5 ms。\n')


# ---------- 单页 ----------

def test_single_parse_args_numeric_keys():
    parsed = v_single.parse_args(
        ['doc.md', 'src.md', '--numeric-review',
         '--numeric-policy', 'p.txt', '--fragment'])
    assert parsed['numeric_review'] is True
    assert parsed['numeric_policy'] == 'p.txt'
    assert parsed['fragment'] is True
    off = v_single.parse_args(['doc.md', 'src.md'])
    assert off['numeric_review'] is False
    assert off['numeric_policy'] is None


def test_single_hints_are_not_fails():
    fail, lines = v_single.run_checks(
        DOC_SINGLE, SRC_SINGLE, doc_dir='.', doc_label='d.md',
        src_label='s.md', numeric_review=True)
    assert fail == 0
    assert sum(1 for l in lines if l.startswith('数字提示 NUM')) == 2
    assert any('未提供 --numeric-policy' in l for l in lines)


def test_single_unchecked_notice_by_default():
    fail, lines = v_single.run_checks(
        DOC_SINGLE, SRC_SINGLE, doc_dir='.', doc_label='d.md',
        src_label='s.md')
    assert fail == 0
    assert any('未启用 --numeric-review' in l for l in lines)
    assert not any(l.startswith('数字提示 NUM') for l in lines)


def test_single_bad_policy_fails():
    fail, lines = v_single.run_checks(
        DOC_SINGLE, SRC_SINGLE, doc_dir='.', doc_label='d.md',
        src_label='s.md', numeric_review=True,
        numeric_policy='/nonexistent/policy.txt')
    assert fail == 1
    assert any('数字辅助' in l and 'FAIL' in l for l in lines)


# ---------- 分页 ----------

def test_paginated_parse_args_numeric_keys():
    parsed = v_paginated.parse_args(
        ['m.md', 'a.md', 'b.md', '--numeric-review'])
    assert parsed['numeric_review'] is True
    assert parsed['numeric_policy'] is None
    assert parsed['src_paths'] == ['a.md', 'b.md']


def test_paginated_ordered_sources_keep_occurrences():
    # 两页同 token：按确认顺序覆盖，出现序号不被集合去重吞掉
    src_pages = ['# A\n\n104 billion 参数。\n', '# B\n\n104 billion 参数。\n']
    merged = ('# 全书\n\n## A\n\n1040 亿参数。\n\n---\n\n'
              '## B\n\n1040 亿参数。\n')
    fail, msgs = v_paginated.run_checks(
        merged, src_pages, ['.', '.'], merged_dir='.',
        merged_label='m.md', src_label='源文拼接(a+b)',
        numeric_review=True)
    assert fail == 0
    hints = [m for m in msgs if m.startswith('数字提示 NUM')]
    assert len(hints) == 4
    assert any('[src_missing]#1' in h for h in hints)
    assert any('[src_missing]#2' in h for h in hints)
    assert any('[doc_added]#1' in h for h in hints)
    assert any('[doc_added]#2' in h for h in hints)


def test_paginated_unchecked_notice_by_default():
    fail, msgs = v_paginated.run_checks(
        'x', ['# A\n'], ['.'], merged_dir='.', merged_label='m.md',
        src_label='s')
    assert any('未启用 --numeric-review' in m for m in msgs)


# ---------- API/DSL ----------

def test_api_parse_args_numeric_keys():
    parsed = v_api.parse_args(
        ['m.md', 'manifest.txt', 'toc.txt', 'site', 's1.md', 's2.md',
         '--numeric-review', '--numeric-policy', 'p.txt'])
    assert parsed['numeric_review'] is True
    assert parsed['numeric_policy'] == 'p.txt'
    assert parsed['src_paths'] == ['s1.md', 's2.md']


def test_api_hints_use_manifest_order_label(tmp_path):
    (tmp_path / 'a.html').write_text('<html><body></body></html>',
                                     encoding='utf-8')
    (tmp_path / 'b.html').write_text('<html><body></body></html>',
                                     encoding='utf-8')
    src_pages = ['# A\n\n104 billion 参数。\n', '# B\n\n错误率 3.5%。\n']
    merged = '# A\n\n1040 亿参数。\n\n---\n\n# B\n\n错误率 3.5%。\n'
    fails, warns = v_api.run_checks(
        merged, str(tmp_path), ['a.html', 'b.html'], ['a.html', 'b.html'],
        str(tmp_path), src_pages, merged_label='m.md', numeric_review=True)
    assert fails == []
    assert any('数字提示 NUM' in w and '源页拼接(a.html+b.html)' in w
               for w in warns)


# ---------- 文本 PDF 源 ----------

def test_pdf_source_parse_args_numeric_flags():
    args = verify_pdf_source.parse_args(
        ['paper.pdf', '--checklist', 'c.json', '--source-md', 's.md',
         '--translation', 't.md', '--numeric-review',
         '--numeric-policy', 'p.txt'])
    assert args.numeric_review is True
    assert args.numeric_policy == 'p.txt'
    off = verify_pdf_source.parse_args(
        ['paper.pdf', '--checklist', 'c.json', '--source-md', 's.md'])
    assert off.numeric_review is False


def test_pdf_source_numeric_requires_translation(tmp_path):
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(b'%PDF-1.4 fake')
    checklist = tmp_path / 'c.json'
    checklist.write_text('{"version": 1}', encoding='utf-8')
    md = tmp_path / 's.md'
    md.write_text('# T\n', encoding='utf-8')
    with pytest.raises(SystemExit) as exc:
        verify_pdf_source.main(
            [str(pdf), '--checklist', str(checklist),
             '--source-md', str(md), '--numeric-review'])
    assert exc.value.code not in (0, None)


# ---------- verify_delivery 检查事实 ----------

def _facts_for(tool, args, root):
    facts, _parsed = delivery._check_facts(str(root), tool, list(args), 1)
    return facts


def test_delivery_facts_numeric_for_each_family(tmp_path):
    doc = tmp_path / 'doc.md'
    doc.write_text(DOC_SINGLE, encoding='utf-8')
    src = tmp_path / 'src.md'
    src.write_text(SRC_SINGLE, encoding='utf-8')
    policy = tmp_path / 'policy.txt'
    policy.write_text('口径\n', encoding='utf-8')
    manifest = tmp_path / 'manifest.txt'
    manifest.write_text('a.html\n', encoding='utf-8')
    toc = tmp_path / 'toc.txt'
    toc.write_text('a.html\n', encoding='utf-8')
    for tool, args in (
        ('verify_translation',
         [str(doc), str(src), '--numeric-review',
          '--numeric-policy', str(policy)]),
        ('verify_paginated_translation',
         [str(doc), str(src), str(src), '--numeric-review']),
        ('verify_reference_translation',
         [str(doc), str(src), '--numeric-review',
          '--numeric-policy', str(policy)]),
        ('verify_api_translation',
         [str(doc), str(manifest), str(toc), str(tmp_path), str(src),
          str(src), '--numeric-review']),
        ('verify_pdf_source',
         ['paper.pdf', '--checklist', 'c.json', '--source-md', str(src),
          '--translation', str(doc), '--numeric-review',
          '--numeric-policy', str(policy)]),
    ):
        facts = _facts_for(tool, args, tmp_path)
        assert facts['params'].get('numeric_review') is True, tool
        assert '_numeric_review.py' in facts['shared_deps'], tool
    # 口径文件进入检查事实（digest + 规范化路径）
    facts = _facts_for(
        'verify_translation',
        [str(doc), str(src), '--numeric-review',
         '--numeric-policy', str(policy)], tmp_path)
    assert facts['files']['numeric_policy'][1] is not None
    assert facts['params']['numeric_policy']['path'] == \
        str(policy.resolve())


def test_delivery_facts_unchanged_when_disabled(tmp_path):
    doc = tmp_path / 'doc.md'
    doc.write_text(DOC_SINGLE, encoding='utf-8')
    src = tmp_path / 'src.md'
    src.write_text(SRC_SINGLE, encoding='utf-8')
    for tool, args in (
        ('verify_translation', [str(doc), str(src)]),
        ('verify_paginated_translation', [str(doc), str(src)]),
        ('verify_reference_translation', [str(doc), str(src)]),
    ):
        facts = _facts_for(tool, args, tmp_path)
        assert 'numeric_review' not in facts['params'], tool
        assert 'numeric_policy' not in facts['files'], tool
