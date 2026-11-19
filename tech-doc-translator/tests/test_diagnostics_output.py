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

    def test_singleton_category_printed_once(self):
        text = verification.summarize_messages(
            ["强 token 增加 'HSTU': 源 116 处 vs 译 125 处",
             "强 token 增加 'GEMM': 源 22 处 vs 译 31 处"])
        self.assertEqual(text.split('\n'), [
            '共 2 处，2 类：',
            "  [1] 强 token 增加 'GEMM': 源 22 处 vs 译 31 处",
            "  [1] 强 token 增加 'HSTU': 源 116 处 vs 译 125 处"])

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


class NumericSummaryTest(unittest.TestCase):
    """第 2 批 R9 遗留：数字提示汇总为一行，逐项提示只在 --verbose 时打印。"""

    def test_summary_warning_counts_categories(self):
        import verify_reference_translation as reference
        _fails, warns = reference.verify(
            '# CUDA 指南\n\n模型有 1040 亿参数。\n',
            '# CUDA 指南\n\nThe model has 104 billion parameters.\n',
            [], doc_label='d.md', src_label='s.md', numeric_review=True)
        self.assertIn('数字提示：共 2 处待复核（管理字段 0、标题或交叉引用 0、数量级或单位 2、'
                      '其余 0），逐项见 verify_delivery --prepare-reviews 候选', warns)

    def test_summarized_output_drops_item_hints(self):
        with tempfile.TemporaryDirectory(prefix='numeric-summary-') as temp:
            src, doc = Path(temp) / 's.md', Path(temp) / 'd.md'
            src.write_text('# CUDA 指南\n\nvalues %s.\n'
                           % ', '.join(str(n) for n in range(11, 23)), encoding='utf-8')
            doc.write_text('# CUDA 指南\n\n一组数值。\n', encoding='utf-8')
            command = [sys.executable, str(SCRIPTS / 'verify_reference_translation.py'),
                       str(doc), str(src), '--numeric-review']
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn('数字提示 NUM[', run.stdout)
            self.assertIn('数字提示：共 12 处待复核', run.stdout)
            verbose = subprocess.run(command + ['--verbose'], capture_output=True, text=True)
            self.assertEqual(verbose.stdout.count('数字提示 NUM['), 12)


class SourceAdaptationArgTest(unittest.TestCase):
    def test_flag_without_path_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            verification.extract_source_adaptation(
                ['a.md', 'b.md', '--source-adaptation', '--image-map', 'm.json'])
        self.assertIn('缺少依据路径', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
