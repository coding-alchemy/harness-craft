# coding: utf-8
"""译注剩余文字独立取自原 Markdown，使用整章脚注语义。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter
import verify_pdf as verifier

SCRIPTS = Path(exporter.__file__).parent
TEXT = ('# 脚注核验\n\n> **来源**：https://example.org/footnote-notes\n\n'
        '第一段[^named]【译注：此说明排除】正文保留 123。再次引用[^named]。\n\n'
        '第二段先引用[^99]【译注：说明】再引用[^7]，正文继续。\n\n'
        '字面代码 `[^named]` 保留，引用[^7]【译注：同行说明】继续。\n\n'
        '混合行内脚注^[行内定义]【译注：行内说明】正文。\n\n'
        '[^7]: 七号标签的定义。\n'
        '[^named]: 命名定义【译注：定义内说明】其余保留。\n'
        '[^99]: 九十九号标签的定义。\n')


class PdfFootnoteNotesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pdf-footnote-notes-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.doc = self.root / 'chapter.md'
        self.doc.write_text(TEXT)

    def test_original_context_controls_named_numeric_and_repeated_refs(self):
        chapter = exporter.Chapter(1, self.doc)
        values = list(verifier._note_remainders(chapter).values())
        self.assertIn('第一段[1]正文保留123。再次引用[1:1]。', values)
        self.assertIn('第二段先引用[2]再引用[3],正文继续。', values)
        self.assertTrue(any('[^named]' in value and '[3:1]' in value for value in values))
        self.assertIn('命名定义其余保留。', values)
        offsets = verifier.scan_translator_notes(TEXT, with_offsets=True)
        self.assertTrue(all(TEXT[a:z] == fragment for _, fragment, a, z in offsets))

    def test_collateral_deletion_not_derived_from_modified_dom(self):
        chapter = exporter.Chapter(1, self.doc)
        exporter.parse_chapter(chapter)
        notes = []
        exporter.strip_translator_notes(chapter, notes)
        good = ''.join(verifier._note_remainders(chapter).values())
        for broken in (good.replace('正文保留123。', ''),
                       good.replace('再次引用[1:1]', '再次引用'),
                       good.replace('命名定义其余保留。', '')):
            with self.subTest(broken=broken):
                failures = []
                verifier.check_translator_notes([chapter],
                    {'translator_note_exclusions': notes},
                    SimpleNamespace(norm_text=broken), failures)
                self.assertTrue(any(f['code'] == 'translator-note-collateral' for f in failures), failures)

    def test_real_pdf_preserves_body_footnotes_and_literal_code(self):
        pdf = self.root / 'chapter.pdf'
        work = self.root / 'work'
        for script, flag in (('export_pdf.py', '--output'), ('verify_pdf.py', '--pdf')):
            result = subprocess.run([sys.executable, str(SCRIPTS / script), flag,
                str(pdf), '--work-dir', str(work), str(self.doc)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_pdf_body_reference_and_definition_damage_rejected(self):
        chapter = exporter.Chapter(1, self.doc)
        exporter.parse_chapter(chapter)
        notes = []
        exporter.strip_translator_notes(chapter, notes)
        for index, broken in enumerate((
                TEXT.replace('正文保留 123。', ''),
                TEXT.replace('再次引用[^named]', '再次引用'),
                TEXT.replace('命名定义', '错误定义'))):
            with self.subTest(index=index):
                path = self.root / ('bad-%d.md' % index)
                path.write_text(broken)
                pdf = path.with_suffix('.pdf')
                result = subprocess.run([sys.executable, str(SCRIPTS / 'export_pdf.py'),
                    '--output', str(pdf), '--work-dir', str(self.root / ('work-%d' % index)),
                    str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                failures = []
                verifier.check_translator_notes([chapter], {'translator_note_exclusions': notes},
                                                 verifier.PdfFacts(pdf), failures)
                self.assertTrue(any(f['code'] == 'translator-note-collateral' for f in failures), failures)


if __name__ == '__main__':
    unittest.main()
