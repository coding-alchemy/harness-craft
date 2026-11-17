# coding: utf-8
"""R9/R16：诊断第一屏给根因与归类计数，全量差异落盘；参数漏写路径直接报错。"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import _latexml_source as latexml
import _verification as verification
import verify_pdf as verifier

SCRIPTS = Path(verifier.__file__).parent


class SummarizeTest(unittest.TestCase):
    def test_groups_by_template(self):
        messages = ['表格 table[%d] 第 %d 行不符' % (i, i + 2) for i in range(1, 7)]
        messages += ['段落 p[3] 候选内容被改写/删除']
        text = verification.summarize_messages(messages)
        self.assertIn('共 7 处，2 类', text)
        self.assertIn('[6]', text)
        self.assertEqual(text.count('表格 table['), 3)   # 每类只列 3 条样例

    def test_reconcile_error_keeps_all_diffs(self):
        diffs = ['表格 table[%d] 不符' % i for i in range(9)]
        exc = latexml.ReconcileError('切片 #1', diffs)
        self.assertEqual(exc.diffs, diffs)
        self.assertIn('共 9 处', str(exc))

    def test_write_reconcile_diffs_follows_cause(self):
        with tempfile.TemporaryDirectory(prefix='diffs-') as temp:
            inner = latexml.ReconcileError('切片 #1', ['a', 'b'])
            try:
                try:
                    raise inner
                except ValueError as exc:
                    raise RuntimeError('包装') from exc
            except RuntimeError as outer:
                path = verifier.write_reconcile_diffs(outer, temp)
            self.assertEqual(Path(path).read_text(encoding='utf-8'), 'a\nb\n')


class EvidenceMissingTest(unittest.TestCase):
    def test_single_root_cause_and_relative_work_dir(self):
        with tempfile.TemporaryDirectory(prefix='evidence-') as temp:
            root = Path(temp)
            doc = root / 'chapter.md'
            doc.write_text('# 证据\n\n> **来源**：https://example.org/evidence\n\n正文。\n',
                           encoding='utf-8')
            export = subprocess.run([sys.executable, str(SCRIPTS / 'export_pdf.py'), '--output',
                                     'c.pdf', '--work-dir', 'work', str(doc)],
                                    capture_output=True, text=True, cwd=root)
            self.assertEqual(export.returncode, 0, export.stdout + export.stderr)
            verify = subprocess.run([sys.executable, str(SCRIPTS / 'verify_pdf.py'), '--pdf',
                                     str(root / 'c.pdf'), '--work-dir', str(root / 'empty'),
                                     str(doc)], capture_output=True, text=True)
            self.assertNotEqual(verify.returncode, 0)
            codes = [line for line in verify.stderr.splitlines()
                     if re.match(r'\s+\[[a-z][a-z-]*\] ', line)]
            self.assertEqual(len(codes), 1, verify.stderr)
            self.assertIn('export-evidence-missing', codes[0])
            self.assertIn('同一 --work-dir', verify.stderr)


class SourceAdaptationArgTest(unittest.TestCase):
    def test_flag_without_path_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            verification.extract_source_adaptation(
                ['a.md', 'b.md', '--source-adaptation', '--image-map', 'm.json'])
        self.assertIn('缺少依据路径', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
