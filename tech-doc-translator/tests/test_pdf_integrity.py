"""真实 PDF 固定验收：章节隔离、无标题章节、组合语法及损坏检测。"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter
import verify_pdf as verifier


class PdfIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='pdf-integrity-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.work = cls.root / 'work'
        cls.pdf = cls.root / 'book.pdf'
        image = Path(__file__).parent / 'fixtures/valid_1x1.png'
        sources = [
            '# A\n\nIntro.\n\n```text\nSame paragraph.\n```\n',
            'Same paragraph.\n',
            '```text\nSame paragraph.\n```\n',
            '$$x^2 + y^2 = 1$$\n',
            '![Diagram](%s)\n' % image,
            '####### <a id="custom"></a>Use [docs][r] and `foo` $x^2$[^n]\n\n'
            '[go](#custom)\n\n[r]: https://example.com/docs\n\n[^n]: Required note.\n',
        ]
        cls.inputs = []
        for index, source in enumerate(sources):
            path = cls.root / ('chapter%d.md' % index)
            path.write_text(source)
            cls.inputs.append(str(path))
        with contextlib.redirect_stdout(io.StringIO()):
            result = exporter.export(cls.inputs, cls.pdf, cls.work)
        if result:
            raise AssertionError((cls.work / exporter.REPORT_NAME).read_text())
        cls.evidence = (cls.work / exporter.REPORT_NAME).read_text()

    def verify(self, path, inputs=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = verifier.main(['--pdf', str(path), '--work-dir', str(self.work),
                                    *(inputs if inputs is not None else self.inputs)])
        report = json.loads((self.work / verifier.VERIFY_NAME).read_text())
        return result, {item['code'] for item in report['failures']}

    def setUp(self):
        (self.work / exporter.REPORT_NAME).write_text(self.evidence)

    def test_complete_book_and_exact_chapter_boundaries(self):
        result, codes = self.verify(self.pdf)
        self.assertEqual((result, codes), (0, set()))
        failures = []
        chapters = verifier.reparse_inputs(self.inputs, failures)
        bounds = verifier.chapter_bounds(chapters, verifier.PdfFacts(self.pdf), {}, failures)
        self.assertEqual(failures, [])
        self.assertEqual([(start, end) for _, start, end in bounds],
                         [(i, i + 1) for i in range(6)])

    def test_blank_chapter_cannot_borrow_previous_code_even_with_matching_digest(self):
        writer = PdfWriter(clone_from=self.pdf)
        stream = DecodedStreamObject()
        stream.set_data(b'')
        writer.pages[1][NameObject('/Contents')] = writer._add_object(stream)
        path = self.root / 'blank.pdf'
        writer.write(path)
        # 更新摘要以单独检验内容隔离，防止测试只依赖摘要拒绝损坏文件。
        report = json.loads(self.evidence)
        report['pdf_sha256'] = exporter.sha256_file(path)
        (self.work / exporter.REPORT_NAME).write_text(json.dumps(report))
        result, codes = self.verify(path)
        self.assertEqual(result, 1)
        self.assertIn('text-missing', codes)
        self.assertNotIn('pdf-evidence-mismatch', codes)

    def test_damage_and_old_render_evidence_rejected(self):
        for page_index in (2, 3, 4):
            with self.subTest(page=page_index):
                writer = PdfWriter(clone_from=self.pdf)
                stream = DecodedStreamObject()
                stream.set_data(b'')
                writer.pages[page_index][NameObject('/Contents')] = writer._add_object(stream)
                path = self.root / ('blank%d.pdf' % page_index)
                writer.write(path)
                result, codes = self.verify(path)
                self.assertEqual(result, 1)
                self.assertIn('pdf-evidence-mismatch', codes)

    def test_deleted_reordered_and_duplicated_pages_rejected(self):
        for order in ([0, 2, 3, 4, 5], [1, 0, 2, 3, 4, 5], [0, 0, 2, 3, 4, 5]):
            with self.subTest(order=order):
                writer = PdfWriter()
                reader = verifier.PdfFacts(self.pdf).reader
                for index in order:
                    writer.add_page(reader.pages[index])
                path = self.root / 'reordered.pdf'
                writer.write(path)
                result, codes = self.verify(path)
                self.assertEqual(result, 1)
                self.assertIn('chapter-structure', codes)

    def test_input_order_bound_to_evidence(self):
        result, codes = self.verify(self.pdf, list(reversed(self.inputs)))
        self.assertEqual(result, 1)
        self.assertIn('input-order-mismatch', codes)

    def test_subheading_same_as_next_chapter_title(self):
        paths = []
        for name, source in [('a', '# A\n\n## B\n\nFirst.'), ('b', '# B\n\nSecond.')]:
            path = self.root / (name + '.md')
            path.write_text(source)
            paths.append(str(path))
        work = self.root / 'outline-work'
        output = self.root / 'outline.pdf'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(exporter.export(paths, output, work), 0)
            self.assertEqual(verifier.main(['--pdf', str(output), '--work-dir', str(work),
                                            *paths]), 0)

    def test_titleless_book_needs_no_outline(self):
        work = self.root / 'titleless-work'
        output = self.root / 'titleless.pdf'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(exporter.export(self.inputs[1:3], output, work), 0)
            self.assertEqual(verifier.main(['--pdf', str(output), '--work-dir', str(work),
                                            *self.inputs[1:3]]), 0)


if __name__ == '__main__':
    unittest.main()
