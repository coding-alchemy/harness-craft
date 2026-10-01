"""块级数学环境显示模式验收（迁移 C 及评审修正）。

历史行内包装 `$\\(...\\)$` 内含 KaTeX 仅在 display 模式接受的环境时，按
数学含义提升为显示模式渲染；否则 KaTeX 报 "can be used only in
display mode" 且导出 FAIL。普通行内、块级与其他历史包装行为不变。

当前随附 KaTeX 资产的实际支持范围（display 模式，实测）：`equation(/\\*)`、
`align(/\\*)`、`gather(/\\*)`、`alignat(/\\*)`、`split`；不支持
`flalign(/\\*)`、`multline(/\\*)`、`split*`（KaTeX "No such environment"），
分类仍按 LaTeX 语义提升，实际渲染由既有 katex-error 门禁明确失败。

KaTeX 的编号槽（`.katex-tag`，absolute + right:0）内，vlist 的 `.vlist-s`
支柱列（2px 宽、无字形）与其补偿 `.vlist-t2 { margin-right: -2px }` 是成对
机制：槽位收缩盒只包住补偿后的宽度，支柱列向右逃逸出文档 2px，会使
scrollWidth 超过视口触发溢出门禁（空槽与真实编号同样发生）；打印样式在
槽内成对撤销该机制（支柱零宽、补偿归零），真实编号位置与渲染不变，不裁切
任何内容——编号纵向本就画在槽位元素盒外（vlist 行高为 0 的正常绘制），
整槽 overflow:hidden 曾因此裁掉较高编号的分子/分母与求和上下限（由
`test_real_tag_content_not_clipped` 的 paint 级反例覆盖）。溢出门禁本身
不放宽。
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter   # noqa: E402
import verify_pdf as verifier   # noqa: E402

DISPLAY_ONLY_ENVS = ('equation', 'align', 'gather', 'flalign',
                     'multline', 'alignat', 'split')


class ClassifyMathTest(unittest.TestCase):

    def test_plain_inline_and_block_unchanged(self):
        self.assertEqual(exporter.classify_math('x^2', False),
                         ('x^2', 'inline', 'dollar_inline'))
        self.assertEqual(exporter.classify_math('E = m c^2', True),
                         ('E = m c^2', 'display', 'dollar_block'))

    def test_legacy_bracket_still_display(self):
        latex, mode, form = exporter.classify_math(r'\[ z = \frac{1}{2} \]', False)
        self.assertEqual((latex, mode, form),
                         ('z = \\frac{1}{2}', 'display', 'legacy_bracket'))

    def test_legacy_paren_without_display_env_stays_inline(self):
        self.assertEqual(exporter.classify_math(r'\(\text{rate} = 5\)', False),
                         ('\\text{rate} = 5', 'inline', 'legacy_paren'))

    def test_display_only_envs_promoted_from_legacy_paren(self):
        for env in DISPLAY_ONLY_ENVS:
            for starred in ('', '*'):
                with self.subTest(env=env + starred):
                    content = r'\(\begin{%s} x &= 1 \end{%s}\)' % (env + starred,
                                                                   env + starred)
                    latex, mode, form = exporter.classify_math(content, False)
                    self.assertEqual(mode, 'display', content)
                    self.assertEqual(form, 'legacy_paren')
                    self.assertEqual(latex,
                                     r'\begin{%s} x &= 1 \end{%s}' % (env + starred,
                                                                      env + starred))

    def test_display_only_env_promoted_from_plain_inline(self):
        latex, mode, form = exporter.classify_math(
            r'\begin{split} a &= 1 \end{split}', False)
        self.assertEqual((latex, mode, form),
                         (r'\begin{split} a &= 1 \end{split}',
                          'display', 'dollar_inline'))

    def test_non_display_env_not_promoted(self):
        latex, mode, form = exporter.classify_math(
            r'\(\begin{aligned} x \end{aligned}\)', False)
        self.assertEqual(mode, 'inline')
        self.assertEqual(form, 'legacy_paren')


class MathDisplayPdfTest(unittest.TestCase):
    """真实 Chromium PDF：提升显示模式的各形态一次导出验证。

    全部环境共用一次导出（不为每个分类组合重复启动完整导出）；
    不支持环境的负向行为由独立负例覆盖。
    """

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='math-display-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        doc = '\n'.join([
            '# 块级数学环境显示模式回归',
            '',
            '> **来源**：https://example.invalid/math-display（合成测试）',
            '',
            '普通行内 $a+b$、$x^2$ 与块级：',
            '',
            '$$E = m c^2$$',
            '',
            '历史行内包装的各显示环境（align/equation 曾因编号槽支柱溢出'
            '被门禁拦截，现为修复样例）：',
            '',
            '$' + r'\(\begin{align} x &= 1 \\ y &= 2 \end{align}\)' + '$',
            '',
            '$' + r'\(\begin{align*} u &= v \\ w &= z \end{align*}\)' + '$',
            '',
            '$' + r'\(\begin{equation} c = d \end{equation}\)' + '$',
            '',
            '$' + r'\(\begin{equation*} e = f \end{equation*}\)' + '$',
            '',
            '$' + r'\(\begin{split} a &= 3 \\ b &= 4 \end{split}\)' + '$',
            '',
            '带真实编号的 align（编号必须保留且不被裁切）：',
            '',
            '$' + r'\(\begin{align} p &= q \tag{1.1} \\ r &= s \tag{1.2} \end{align}\)' + '$',
            '',
            '较高真实编号（纵向画在槽位元素盒外，曾编号槽整槽裁切反例）：',
            '',
            '$$' + r'\begin{equation} a = b \tag{$\dfrac{1}{2}$} \end{equation}' + '$$',
            '',
            '$$' + r'\begin{equation} c = d \tag{$\displaystyle\sum_{i=1}^{n} i$} \end{equation}' + '$$',
            '',
            '历史块级包装 bracket：',
            '',
            '$' + r'\[ z = \frac{1}{2} \]' + '$',
            '',
            '普通行内包装（非 display-only 环境，保持行内）：',
            '',
            '$' + r'\(\text{rate} = 5\)' + '$',
            '',
            '结尾段落。',
        ])
        (cls.root / 'doc.md').write_text(doc, encoding='utf-8')
        cls.work = cls.root / 'work'
        with contextlib.redirect_stdout(io.StringIO()):
            result = exporter.export([str(cls.root / 'doc.md')],
                                     cls.root / 'book.pdf', cls.work)
        if result:
            raise AssertionError((cls.work / exporter.REPORT_NAME).read_text(
                encoding='utf-8'))
        cls.report = json.loads(
            (cls.work / exporter.REPORT_NAME).read_text(encoding='utf-8'))

    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return verifier.main(
                ['--pdf', str(self.root / 'book.pdf'),
                 '--work-dir', str(self.work), str(self.root / 'doc.md')])

    def test_export_renders_without_katex_errors_or_overflow(self):
        self.assertEqual(self.report['browser_checks']['katex'], [])
        self.assertEqual(self.report['browser_checks']['overflow'], [])
        self.assertLessEqual(self.report['browser_checks']['scrollWidth'],
                             self.report['browser_checks']['clientWidth'] + 1)

    def test_math_checklist_modes_and_forms(self):
        math = [(m['mode'], m['original_form'], m['latex'])
                for m in self.report['chapters'][0]['math']]
        self.assertEqual(math, [
            ('inline', 'dollar_inline', 'a+b'),
            ('inline', 'dollar_inline', 'x^2'),
            ('display', 'dollar_block', 'E = m c^2'),
            ('display', 'legacy_paren',
             '\\begin{align} x &= 1 \\\\ y &= 2 \\end{align}'),
            ('display', 'legacy_paren',
             '\\begin{align*} u &= v \\\\ w &= z \\end{align*}'),
            ('display', 'legacy_paren', '\\begin{equation} c = d \\end{equation}'),
            ('display', 'legacy_paren',
             '\\begin{equation*} e = f \\end{equation*}'),
            ('display', 'legacy_paren',
             '\\begin{split} a &= 3 \\\\ b &= 4 \\end{split}'),
            ('display', 'legacy_paren',
             '\\begin{align} p &= q \\tag{1.1} \\\\ r &= s \\tag{1.2} \\end{align}'),
            ('display', 'dollar_block',
             '\\begin{equation} a = b \\tag{$\\dfrac{1}{2}$} \\end{equation}'),
            ('display', 'dollar_block',
             '\\begin{equation} c = d \\tag{$\\displaystyle\\sum_{i=1}^{n} i$}'
             ' \\end{equation}'),
            ('display', 'legacy_bracket', 'z = \\frac{1}{2}'),
            ('inline', 'legacy_paren', '\\text{rate} = 5'),
        ])

    def test_pdf_text_and_real_tags_preserved(self):
        import pypdf
        reader = pypdf.PdfReader(str(self.root / 'book.pdf'))
        text = ''.join(p.extract_text() or '' for p in reader.pages)
        # 真实编号保留在成品中（未被编号槽裁切）
        self.assertIn('(1.1)', text)
        self.assertIn('(1.2)', text)
        for marker in ('\\begin{split}', '\\(', '\\)', '\\frac', '$$'):
            self.assertNotIn(marker, text, '公式原始标记泄漏进成品：%s' % marker)

    def test_real_tag_content_not_clipped(self):
        """较高真实编号不被裁切（paint 级反例回归，复用本类唯一一次导出）。

        编号纵向内容按 KaTeX vlist 设计画在槽位元素盒外（行高为 0）；
        曾对 `.katex-tag` 整槽 overflow:hidden，分子/分母与求和上下限被
        裁掉，而导出、独立核验与文本提取全部静默通过。Chromium 命中测试
        遵循 overflow 裁切，字形中心能被命中即未被裁——该断言在整槽裁切
        下变红（盒外真实字形全部不可命中）。零宽空格支柱无字形，不参与。
        """
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 3000})
            page.goto((self.work / exporter.HTML_NAME).as_uri())
            page.wait_for_function('window.__pdfExportDone === true')
            probe = page.evaluate('''() => {
              const out = {misses: [], tallOutOfBox: 0};
              document.querySelectorAll('.katex-tag').forEach(t => {
                const box = t.getBoundingClientRect();
                t.querySelectorAll('.katex-html span').forEach(s => {
                  if (s.children.length || !s.textContent.trim()) return;
                  const r = s.getBoundingClientRect();
                  if (!r.width || !r.height) return;
                  const outside = r.top < box.top - 0.5
                    || r.bottom > box.bottom + 0.5
                    || r.left < box.left - 0.5 || r.right > box.right + 0.5;
                  if (outside) out.tallOutOfBox++;
                  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                  if (!document.elementsFromPoint(cx, cy).includes(s)) {
                    out.misses.push({tag: t.textContent, ch: s.textContent,
                                     x: r.left, y: r.top});
                  }
                });
              });
              return out;
            }''')
            browser.close()
        # 反例确实在绘制盒外字形（防止 KaTeX 结构变化使断言失效为空转）
        self.assertGreater(probe['tallOutOfBox'], 0,
                           '较高编号应有画在槽位盒外的字形，否则本断言空转')
        self.assertEqual(probe['misses'], [],
                         '编号真实字形被裁切（中心点不可命中）：%r' % probe)

    def test_independent_verify_passes(self):
        self.assertEqual(self.verify(), 0)


class UnsupportedMathEnvTest(unittest.TestCase):
    """当前 KaTeX 不支持的环境（flalign 等）必须明确失败，不静默降级。"""

    def test_flalign_rejected_with_katex_error(self):
        with tempfile.TemporaryDirectory(prefix='math-unsupported-') as tmp:
            root = Path(tmp)
            (root / 'doc.md').write_text(
                '# 不支持环境回归\n\n'
                '> **来源**：https://example.invalid/math-unsupported（合成测试）\n\n'
                '$' + r'\(\begin{flalign} a &= 1 \\ b &= 2 \end{flalign}\)' + '$\n',
                encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                result = exporter.export([str(root / 'doc.md')],
                                         root / 'book.pdf', root / 'work')
            self.assertNotEqual(result, 0)
            report = json.loads(
                (root / 'work' / exporter.REPORT_NAME).read_text(encoding='utf-8'))
            errors = [e['message'] for e in report['browser_checks']['katex']]
            self.assertTrue(
                any('No such environment: flalign' in m for m in errors),
                errors)
            self.assertFalse((root / 'book.pdf').exists(),
                             '失败导出不得留下成品')


if __name__ == '__main__':
    unittest.main()
