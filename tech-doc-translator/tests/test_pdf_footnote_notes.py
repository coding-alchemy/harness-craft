# coding: utf-8
"""译注剩余文字独立取自原 Markdown，使用整章脚注语义。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        values = [''.join(segments) for segments, _role in verifier._note_remainders(chapter).values()]
        self.assertIn('第一段[1]正文保留123。再次引用[1:1]。', values)
        self.assertIn('第二段先引用[2]再引用[3],正文继续。', values)
        self.assertTrue(any('[^named]' in value and '[3:1]' in value for value in values))
        self.assertIn('命名定义其余保留。', values)
        offsets = verifier.scan_translator_notes(TEXT, with_offsets=True)
        self.assertTrue(all(TEXT[a:z] == fragment for _, fragment, a, z in offsets))

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
                TEXT.replace('命名定义', '错误定义'),
                TEXT.replace('命名定义【译注：定义内说明】其余保留。', ''))):
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

    def test_note_projection_normal_wrap_and_body_damage(self):
        # RankMixer v3 §1, where the source has "range.Moreover".
        before = ('从历史上看，推荐中排序模型的架构由 CPU 时代的设计原则塑造。'
                  '这类模型通常依赖组合异构的、多样的手工交叉特征模块来提取特征交叉，'
                  '但它们的许多核心算子在当代 GPU 上是访存受限（memory-bound）'
                  '而非计算受限（compute-bound），导致 GPU 并行度差、'
                  'MFU（Model Flops Utilization，模型算力利用率）极低，往往只有个位数百分比。')
        note = '【译注：原文此处为 "range.Moreover"，缺空格，译文按句读处理】'
        after = ('此外，由于 CPU 时代模型的计算开销大致与参数数量成正比，'
                 '依据扩展律本可获得的激进扩展收益在实践中难以实现。')
        prefix = ('# RankMixer 排序模型\n\n'
                  '> **来源**：https://arxiv.org/html/2507.15551v3\n\n')
        self.doc.write_text(prefix + before + note + after + '\n', encoding='utf-8')
        chapter = exporter.Chapter(1, self.doc)
        exporter.parse_chapter(chapter)
        notes = []
        exporter.strip_translator_notes(chapter, notes)
        report = {'translator_note_exclusions': notes}
        for name, body in (('wrap', before + note + after),
                           ('deleted', before + after.replace('依据扩展律', '')),
                           ('changed', before + after.replace('成正比', '成反比')),
                           ('crossed', before + '\n\n' + after)):
            with self.subTest(case=name):
                path = self.root / (name + '.md')
                path.write_text(prefix + body + '\n', encoding='utf-8')
                pdf = path.with_suffix('.pdf')
                result = subprocess.run([sys.executable, str(SCRIPTS / 'export_pdf.py'),
                    '--output', str(pdf), '--work-dir', str(self.root / ('work-' + name)),
                    str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                facts = verifier.PdfFacts(pdf)
                failures = []
                verifier.check_translator_notes([chapter], report, facts, failures)
                if name == 'wrap':
                    self.assertGreater(len(facts.pages[0].splitlines()), 3)
                    self.assertEqual(failures, [])
                    continue
                if name == 'crossed':
                    self.assertIn(verifier.normalize(before + after), facts.norm_text)
                self.assertTrue(failures)
                self.assertEqual(failures[0]['code'], 'translator-note-collateral')
                self.assertEqual(failures[0]['input'], str(self.doc))
                self.assertEqual(failures[0]['line'], 5)
                self.assertEqual(failures[0]['page'], 1)
                self.assertTrue(failures[0]['pdf_object'])

    def test_note_in_paragraph_with_inline_math(self):
        prefix = '# 数学译注\n\n> **来源**：https://example.org/math-notes\n\n'
        body = ('其中 $\\phi^{h}$ 是第 $h$ 个头的投影，【译注：原文此处缺下标】'
                '而 $\\hat{K}^{h}$ 为对应键矩阵，二者共同决定注意力权重。')
        self.doc.write_text(prefix + body + '\n', encoding='utf-8')
        chapter = exporter.Chapter(1, self.doc)
        exporter.parse_chapter(chapter)
        notes = []
        exporter.strip_translator_notes(chapter, notes)
        report = {'translator_note_exclusions': notes}
        for name, text in (('ok', body), ('deleted', body.replace('二者共同', ''))):
            with self.subTest(case=name):
                path = self.root / (name + '.md')
                path.write_text(prefix + text + '\n', encoding='utf-8')
                pdf = path.with_suffix('.pdf')
                result = subprocess.run([sys.executable, str(SCRIPTS / 'export_pdf.py'),
                    '--output', str(pdf), '--work-dir', str(self.root / ('work-math-' + name)),
                    str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                failures = []
                verifier.check_translator_notes([chapter], report, verifier.PdfFacts(pdf), failures)
                if name == 'ok':
                    self.assertEqual(failures, [])
                else:
                    self.assertEqual(failures[0]['code'], 'translator-note-collateral')

    def test_note_in_narrow_table_cell_wrapped_identifier(self):
        # V2 cuSPARSE：窄列按 overflow-wrap:anywhere 在词中折行，标识符拆成两个文本块。
        prefix = '# 表格译注\n\n> **来源**：https://example.org/table-note\n\n'
        head = '| `参数名` | `内存` | `输入/输出` | `含义` |\n| --- | --- | --- | --- |\n'
        rows = ''.join(
            '| `%s` | DEVICE | OUT | 指向长度为 `mb` 的整数数组的下标表；宽列的说明文字'
            '用于把首列挤窄到在标识符词中折行，同 cuSPARSE 交付样本的窄列形态。 |\n' % name
            for name in ('csrValA', 'csrRowPtrA', 'csrEndPtrA', 'csrColIndA'))
        body = (head + rows
                + '| `bsrEndPtrA`【译注：原文如此，疑为笔误】 | DEVICE | OUT | 宽列说明保持首列窄。 |\n')
        self.doc.write_text(prefix + body + '\n', encoding='utf-8')
        chapter = exporter.Chapter(1, self.doc)
        exporter.parse_chapter(chapter)
        notes = []
        exporter.strip_translator_notes(chapter, notes)
        report = {'translator_note_exclusions': notes}
        remainders = verifier._note_remainders(chapter)
        self.assertIn('bsrEndPtrA', [''.join(segments) for segments, _role in remainders.values()])
        self.assertTrue(any(role in ('/Table', '/Td', '/Th') for _segments, role in remainders.values()))
        for name, text in (('ok', body),
                           ('deleted', body.replace('`bsrEndPtrA`', '`bsrPtrA`'))):
            with self.subTest(case=name):
                path = self.root / (name + '.md')
                path.write_text(prefix + text + '\n', encoding='utf-8')
                pdf = path.with_suffix('.pdf')
                result = subprocess.run([sys.executable, str(SCRIPTS / 'export_pdf.py'),
                    '--output', str(pdf), '--work-dir', str(self.root / ('work-table-' + name)),
                    str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                facts = verifier.PdfFacts(pdf)
                failures = []
                verifier.check_translator_notes([chapter], report, facts, failures)
                if name == 'ok':
                    # 窄列确在词中折行：原始页文本无完整标识符，规范化页文本按序齐全。
                    self.assertNotIn('bsrEndPtrA', facts.pages[0])
                    self.assertIn('bsrEndPtrA', verifier.normalize(facts.pages[0]))
                    self.assertEqual(failures, [])
                else:
                    self.assertEqual(failures[0]['code'], 'translator-note-collateral')


if __name__ == '__main__':
    unittest.main()
