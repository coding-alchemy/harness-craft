"""二期第二轮复评 F4/F5/F8：宿主逐字口径、分段事实比较与多行脚注。

F4：标题/题注/列表项/表格格（与段落同款）的已确认行内公式统一哨兵
分段 + math_wrap 逐字序列化，独立对账端镜像同一事实口径；F5：pm
片段比较按（种类, 归一内容）逐段进行（位置盲拼接与纯空白片段计数
漂移同时消除）；F8：脚注定义内跨行公式的输出端贯通重建。
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
from _source_reconcile import reconcile_latexml_to_markdown

IDENTITY = {
    'expected_title': 'Hosts Fixture', 'actual_title': 'Hosts Fixture',
    'paper_id': '2203.00009', 'version': 'v1',
    'final_url': 'https://example.org/abs/2203.00009v1',
    'retrieved_at': '2026-10-09T00:00:00Z',
    'confirmation': '独立合成复评探针固定装置（测试样例）。',
}

MATH_WS = '<math display="inline" alttext=" x "><mi>x</mi></math>'
MATH_NL = ('<math display="inline" alttext=" \nx + y\n ">'
           '<mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow></math>')


def _adapt(body, tmp_path='/tmp'):
    raw = ('<html><body><article><h1>Hosts Fixture</h1>'
           + body + '</article></body></html>')
    md, corrs, unres, _fidelity, adapter = latexml.adapt_latexml_snapshot(
        raw, None, [], tmp_path)
    payload = {
        'version': 1, 'format': 'latexml',
        'snapshot': {'path': '/tmp/hosts.html',
                     'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': [],
        'correspondences': corrs,
        'unresolved': unres,
    }
    if adapter.groups:
        payload['groups'] = adapter.groups
    return raw, md, payload


def _diffs(raw, md, payload):
    return reconcile_latexml_to_markdown(raw, md, None, payload)


class HostVerbatimTest(unittest.TestCase):
    """F4：五宿主（含段落对照）边界空白公式逐字，对账干净。"""

    def _check_host(self, body, expected):
        raw, md, payload = _adapt(body)
        self.assertIn(expected, md)
        self.assertEqual(_diffs(raw, md, payload), [])

    def test_paragraph_boundary_verbatim(self):
        self._check_host('<p>Value ' + MATH_WS + '.</p>', 'Value $ x $.')

    def test_heading_boundary_verbatim(self):
        self._check_host('<h2>Value ' + MATH_WS + '</h2>', '## Value $ x $')

    def test_caption_boundary_verbatim(self):
        self._check_host(
            '<figure><figcaption>Figure 1 ' + MATH_WS + '</figcaption>'
            '</figure>', '[FIGURE] Figure 1 $ x $')

    def test_list_item_boundary_verbatim(self):
        self._check_host('<ul><li>Value ' + MATH_WS + '.</li></ul>',
                         '- Value $ x $.')

    def test_table_cell_boundary_verbatim(self):
        self._check_host(
            '<table><tr><td>Value ' + MATH_WS + '</td><td>Tail</td></tr>'
            '</table>', 'Value $ x $ | Tail')

    def test_table_cell_multiline_verbatim(self):
        raw, md, payload = _adapt(
            '<table><tr><td>Value ' + MATH_NL + '</td><td>Tail</td></tr>'
            '</table>')
        self.assertIn('Value $ \nx + y\n $ | Tail', md)
        self.assertEqual(_diffs(raw, md, payload), [])


class FragmentOrderTest(unittest.TestCase):
    """F5：公式移位被拒（次序差异）；图片紧邻公式三种空白组合合法。"""

    def test_img_math_combinations_clean(self):
        img = '<img src="pic.svg"/>'
        math = '<math display="inline" alttext="x"><mi>x</mi></math>'
        cases = (
            '<p>Before ' + math + ' ' + img + ' After.</p>',
            '<p>Before ' + math + img + ' After.</p>',
            '<p>Before ' + img + ' ' + math + ' After.</p>',
        )
        for body in cases:
            raw, md, payload = _adapt(body)
            self.assertEqual(_diffs(raw, md, payload), [])

    def test_math_reorder_rejected(self):
        raw = ('<html><body><article><h1>Order Fixture</h1>'
               '<p>alpha beta <math display="inline" alttext="x">'
               '<mi>x</mi></math> gamma<img src="pic.svg"/> tail'
               '</p></article></body></html>')
        md, corrs, unres, _f, _a = latexml.adapt_latexml_snapshot(
            raw, None, [], '/tmp')
        self.assertEqual(unres, [])
        damaged = md.replace('alpha beta $x$ gamma', 'alpha $x$ beta gamma')
        self.assertNotEqual(damaged, md)
        payload = {
            'version': 1, 'format': 'latexml',
            'snapshot': {'path': '/tmp/order.html',
                         'sha256': latexml.sha256_text(raw)},
            'paper_identity': dict(IDENTITY),
            'decisions': [],
            'correspondences': copy.deepcopy(corrs),
            'unresolved': unres,
        }
        delta = damaged.index('$x$') - md.index('$x$')
        for corr in payload['correspondences']:
            if corr.get('content_type') == 'math':
                for key in ('md_start', 'md_end', 'expr_start', 'expr_end'):
                    if key in corr:
                        corr[key] += delta
        diffs = _diffs(raw, damaged, payload)
        self.assertTrue(any('正文流' in d for d in diffs), diffs)


class FootnoteMultilineTest(unittest.TestCase):
    """F8：脚注定义内跨行公式正例通过；篡改反例因目标原因被拒。"""

    def _note(self, body):
        return ('<p>Note<sup><a class="ltx_note_ref" href="#fn:one">one'
                '</a></sup>.</p><div class="ltx_notes">'
                '<div class="ltx_note" id="fn:one">'
                '<div class="ltx_note_content"><p>Value ' + body
                + '.</p></div></div></div>')

    def test_multiline_footnote_clean(self):
        math = ('<math display="inline" alttext="x\n+y">'
                '<mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow></math>')
        raw, md, payload = _adapt(self._note(math))
        self.assertIn('[^fn:one]: Value $x\n+y$.', md)
        self.assertEqual(_diffs(raw, md, payload), [])

    def test_multiline_footnote_damaged_rejected(self):
        math = ('<math display="inline" alttext="x\n+y">'
                '<mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow></math>')
        raw, md, payload = _adapt(self._note(math))
        damaged = md.replace('$x\n+y$', '$x\n+z$')
        self.assertNotEqual(damaged, md)
        diffs = _diffs(raw, damaged, payload)
        self.assertTrue(diffs)
        self.assertTrue(any('脚注定义' in d or '公式' in d or '正文流' in d
                            for d in diffs), diffs)


if __name__ == '__main__':
    unittest.main()
