"""官方标题文件贯通检查与交付身份的固定验收（Ticket 05，设计 D5）。

文件语法、互斥角色、四家族独立基准与工作清单导出的底层行为测试。
独立原题 fixture 为逐字列出的权威内容，不由被测解析输出生成。
"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import verify_api_translation
import verify_delivery
import verify_paginated_translation
import verify_reference_translation
import verify_translation
from _official_headings import (
    SCOPE_BY_TOOL,
    extract_official_headings_option,
    load_official_headings,
    official_headings_identity,
    official_titles_diff,
)
from export_heading_list import export_heading_list


class OfficialHeadingsFileSyntaxTest(unittest.TestCase):
    """D5 文件语法：空行忽略、内容字符/#/重复/顺序保持，错误明确失败。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='oh-syntax-'))
        self.addCleanup(shutil.rmtree, self.base, True)

    def write(self, name, payload):
        path = self.base / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(payload, encoding='utf-8')
        return path

    def test_blank_lines_ignored_and_content_kept(self):
        path = self.write('titles.txt',
                          '  1. Alpha Title  \n'
                          '\n'
                          '# config\n'
                          '\t\n'
                          '1. Alpha Title\n'
                          'It’s “Quoted”（保留） 内 部\n')
        abs_path, titles = load_official_headings(str(path))
        self.assertEqual(abs_path, os.path.realpath(path))
        # 首尾排版空白移除、空行忽略；行首 #、重复原题、内部字符与顺序保持
        self.assertEqual(titles, [
            '1. Alpha Title',
            '# config',
            '1. Alpha Title',
            'It’s “Quoted”（保留） 内 部',
        ])

    def test_missing_file_unreadable_empty_and_bad_utf8_fail(self):
        with self.assertRaises(SystemExit):
            load_official_headings(str(self.base / 'absent.txt'))
        with self.assertRaises(SystemExit):
            load_official_headings(str(self.base))  # 目录不可读为清单
        with self.assertRaises(SystemExit):
            load_official_headings(str(self.write('empty.txt', '  \n\n\t\n')))
        with self.assertRaises(SystemExit):
            load_official_headings(str(self.write('bad.txt', b'\xff\xfe\x00')))

    def test_relative_path_resolves_against_explicit_base(self):
        path = self.write('titles.txt', '1. Alpha\n')
        abs_path, titles = load_official_headings('titles.txt',
                                                  base_dir=str(self.base))
        self.assertEqual(abs_path, os.path.realpath(path))
        self.assertEqual(titles, ['1. Alpha'])


class OfficialHeadingsOptionTest(unittest.TestCase):
    """共享选项提取：保留位置参数顺序，缺值与重复声明明确失败。"""

    def test_option_removed_and_positionals_kept(self):
        argv = ['doc.md', 'src.md', '--official-headings-file', 'titles.txt',
                'pos-token']
        rest, path = extract_official_headings_option(argv)
        self.assertEqual(path, 'titles.txt')
        self.assertEqual(rest, ['doc.md', 'src.md', 'pos-token'])

    def test_missing_value_and_duplicate_fail(self):
        with self.assertRaises(SystemExit):
            extract_official_headings_option(['doc.md', '--official-headings-file'])
        with self.assertRaises(SystemExit):
            extract_official_headings_option(
                ['doc.md', '--official-headings-file', 'a.txt',
                 '--official-headings-file', 'b.txt'])

    def test_empty_path_rejected_not_downgraded(self):
        # 显式空路径明确失败，不降级为未提供官方基准（提交前评审 R4）。
        with self.assertRaises(SystemExit):
            extract_official_headings_option(
                ['doc.md', 'src.md', '--official-headings-file', ''])
        # 与逐项官方原题并用同样在共享入口失败，绕不过互斥。
        with self.assertRaises(SystemExit):
            verify_translation.parse_args(
                ['doc.md', 'src.md', '1. A',
                 '--official-headings-file', ''])
        # 四族同一语义。
        for parse, argv in (
                (verify_reference_translation.parse_args,
                 ['ref.md', 'src.md', '--official-headings-file', '']),
                (verify_paginated_translation.parse_args,
                 ['merged.md', 'src.md', '--official-headings-file', '']),
                (verify_api_translation.parse_args,
                 ['m', 't', 's', 'src.md',
                  '--official-headings-file', ''])):
            with self.assertRaises(SystemExit):
                parse(argv)

    def test_absent_option_yields_none(self):
        rest, path = extract_official_headings_option(['a.md', 'b.md'])
        self.assertIsNone(path)
        self.assertEqual(rest, ['a.md', 'b.md'])


class OfficialTitlesDiffTest(unittest.TestCase):
    """官方原题按序逐项对照口径（与逐项官方原题输入一致）。"""

    def test_match_count_suffix_and_mismatch(self):
        self.assertIsNone(official_titles_diff(['1. A'], ['1. A']))
        self.assertIsNone(official_titles_diff(['1. A'], ['1. A（甲）']))
        self.assertIsNotNone(official_titles_diff(['1. A', '2. B'], ['1. A']))
        self.assertIsNotNone(official_titles_diff(['1. A'], ['2. B']))
        # 顺序不同即不一致
        self.assertIsNotNone(official_titles_diff(['1. A', '2. B'],
                                                  ['2. B', '1. A']))


class ParseArgsRoleTest(unittest.TestCase):
    """真实 parse_args 返回 official_headings_file 路径角色；互斥仅限同角色。"""

    def test_single_page_mutual_exclusion_with_positional_titles(self):
        parsed = verify_translation.parse_args(
            ['doc.md', 'src.md', '--official-headings-file', 'titles.txt'])
        self.assertEqual(parsed['official_headings_file'], 'titles.txt')
        self.assertEqual(parsed['official'], [])
        with self.assertRaises(SystemExit):
            verify_translation.parse_args(
                ['doc.md', 'src.md', '1. A',
                 '--official-headings-file', 'titles.txt'])

    def test_other_families_coexist_with_positional_roles(self):
        parsed = verify_reference_translation.parse_args(
            ['ref.md', 'src.md', 'kernel', '--official-headings-file', 't.txt'])
        self.assertEqual(parsed['strong_tokens'], ['kernel'])
        self.assertEqual(parsed['official_headings_file'], 't.txt')
        parsed = verify_paginated_translation.parse_args(
            ['merged.md', 'p1.md', 'p2.md',
             '--official-headings-file', 't.txt'])
        self.assertEqual(parsed['src_paths'], ['p1.md', 'p2.md'])
        self.assertEqual(parsed['official_headings_file'], 't.txt')
        parsed = verify_api_translation.parse_args(
            ['merged.md', 'manifest.txt', 'toc.txt', 'site/', 'p1.md',
             'p2.md', '--official-headings-file', 't.txt'])
        self.assertEqual(parsed['src_paths'], ['p1.md', 'p2.md'])
        self.assertEqual(parsed['manifest_path'], 'manifest.txt')
        self.assertEqual(parsed['toc_path'], 'toc.txt')
        self.assertEqual(parsed['site_root'], 'site/')
        self.assertEqual(parsed['official_headings_file'], 't.txt')


class IndependentOfficialBenchmarkTest(unittest.TestCase):
    """独立官方基准：解析源与译文同时删去的真实标题仍被发现。

    四家族分别核对源序与译文序；层级仍由原 HTML→解析及源→译文
    独立有序检查证明，官方文件是纯原题清单。
    """

    # 独立原题 fixture：逐字列出的确认范围权威内容
    OFFICIAL = ['1. Alpha', '1.1. Beta', '2. Gamma']

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='oh-bench-'))
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_single_page_deleted_from_both_sides_detected(self):
        src = '# 1. Alpha\n\n## 1.1. Beta\n\n## 2. Gamma\n\n正文。\n'
        src_both_deleted = '# 1. Alpha\n\n## 1.1. Beta\n\n正文。\n'
        doc_both_deleted = '# 1. Alpha（甲）\n\n## 1.1. Beta（乙）\n\n正文。\n'
        fail, lines = verify_translation.run_checks(
            doc_both_deleted, src_both_deleted, self.OFFICIAL,
            doc_dir=str(self.base), doc_label='doc.md', src_label='src.md')
        self.assertTrue(any('与官方清单不一致' in line for line in lines),
                        '\n'.join(lines))
        self.assertGreater(fail, 0)
        # 对照：未提供官方基准时双方同步删除不被发现（既有行为保持）
        fail, _lines = verify_translation.run_checks(
            doc_both_deleted, src_both_deleted, (),
            doc_dir=str(self.base), doc_label='doc.md', src_label='src.md')
        self.assertEqual(fail, 0)

    def test_single_page_equivalent_file_matches_positional(self):
        src = '# 1. Alpha\n\n## 1.1. Beta\n\n## 2. Gamma\n\n正文。\n'
        doc = ('# 1. Alpha（甲）\n\n## 1.1. Beta（乙）\n\n'
               '## 2. Gamma（丙）\n\n正文。\n')
        fail_pos, _ = verify_translation.run_checks(
            doc, src, self.OFFICIAL, doc_dir=str(self.base),
            doc_label='doc.md', src_label='src.md')
        fail_file, _ = verify_translation.run_checks(
            doc, src, list(self.OFFICIAL), doc_dir=str(self.base),
            doc_label='doc.md', src_label='src.md')
        self.assertEqual(fail_pos, 0)
        self.assertEqual(fail_file, 0)

    def test_reference_deleted_from_both_sides_detected(self):
        src = '# 1. Alpha\n\n## 1.1. Beta\n\n## 2. Gamma\n\nbody\n'
        src_both_deleted = '# 1. Alpha\n\n## 1.1. Beta\n\nbody\n'
        doc = ('# 1. Alpha（甲）\n\n## 1.1. Beta（乙）\n\nbody\n')
        fails, _warns = verify_reference_translation.verify(
            doc, src_both_deleted, (), official=self.OFFICIAL)
        self.assertTrue(any('与官方清单不一致' in f for f in fails), fails)
        fails, _warns = verify_reference_translation.verify(
            doc, src_both_deleted, (), official=())
        self.assertEqual(fails, [])

    def test_paginated_assembly_deleted_from_both_sides_detected(self):
        # 已批准装配：章节头 H1 由头部文件提供，源页标题统一降一级
        src_p1 = '# 1. Alpha\n\n## 1.1. Beta\n\nx\n'
        src_p2 = '# 2. Gamma\n\ny\n'
        merged = ('# 第 1 章（章）\n\n'
                  '## 1. Alpha（甲）\n\n### 1.1. Beta（乙）\n\nx\n\n'
                  '## 2. Gamma（丙）\n\ny\n')
        merged_deleted = merged.replace('## 2. Gamma（丙）\n\n', '')
        src_p2_deleted = 'y\n'
        fail, lines = verify_paginated_translation.run_checks(
            merged_deleted, [src_p1, src_p2_deleted],
            [str(self.base), str(self.base)],
            merged_dir=str(self.base), merged_label='merged.md',
            src_label='源文拼接(p1+p2)', official=self.OFFICIAL)
        self.assertTrue(any('与官方清单不一致' in line for line in lines),
                        '\n'.join(lines))
        self.assertGreater(fail, 0)
        # 对照：装配映射（跳过章节头 + 降一级）下双方同步删除不被发现
        fail, _lines = verify_paginated_translation.run_checks(
            merged_deleted, [src_p1, src_p2_deleted],
            [str(self.base), str(self.base)],
            merged_dir=str(self.base), merged_label='merged.md',
            src_label='源文拼接(p1+p2)', official=())
        self.assertEqual(fail, 0)
        # 装配映射合同保持：正确合并产物 + 完整官方清单通过
        fail, _lines = verify_paginated_translation.run_checks(
            merged, [src_p1, src_p2], [str(self.base), str(self.base)],
            merged_dir=str(self.base), merged_label='merged.md',
            src_label='源文拼接(p1+p2)', official=self.OFFICIAL)
        self.assertEqual(fail, 0)

    def test_api_manifest_order_deleted_from_both_sides_detected(self):
        site = self.base / 'site'
        site.mkdir()
        (site / 'p1.html').write_text(
            '<html><body><h1>1. Alpha</h1></body></html>', encoding='utf-8')
        (site / 'p2.html').write_text(
            '<html><body><h1>2. Gamma</h1></body></html>', encoding='utf-8')
        manifest = ['p1.html', 'p2.html']
        toc = ['p1.html', 'p2.html']
        src_pages = ['# 1. Alpha\n\n## 1.1. Beta\n\nx\n', '# 2. Gamma\n\ny\n']
        merged = ('# 1. Alpha（甲）\n\n## 1.1. Beta（乙）\n\nx\n\n---\n\n'
                  '# 2. Gamma（丙）\n\ny\n')
        fails, _warns = verify_api_translation.run_checks(
            merged, str(self.base), manifest, toc, str(site), src_pages,
            merged_label='merged.md', official_headings=self.OFFICIAL)
        self.assertEqual(fails, [])
        fails, _warns = verify_api_translation.run_checks(
            merged.replace('# 2. Gamma（丙）\n\n', ''),
            str(self.base), manifest, toc, str(site), ['# 1. Alpha\n\n## 1.1. Beta\n\nx\n', 'y\n'],
            merged_label='merged.md', official_headings=self.OFFICIAL)
        self.assertTrue(any('官方标题清单' in f for f in fails), fails)
        # TOC 页面缺项仍由原 TOC 拒绝（标题文件不替代 TOC）
        fails, _warns = verify_api_translation.run_checks(
            merged, str(self.base), ['p1.html'], toc, str(site), src_pages,
            merged_label='merged.md', official_headings=self.OFFICIAL)
        self.assertTrue(any('官方 TOC 不闭合' in f or 'TOC' in f for f in fails),
                        fails)


class DeliveryOfficialHeadingsIdentityTest(unittest.TestCase):
    """标题文件作为实际依赖进入检查事实与交付身份（D5/D7）。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='oh-delivery-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        (self.base / 'docs').mkdir()
        (self.base / '01_章.md').write_text('# 第 1 章\n\n正文。\n',
                                            encoding='utf-8')
        (self.base / 'docs' / 'src.md').write_text('# 1. Alpha\n\nbody\n',
                                                   encoding='utf-8')
        (self.base / 'titles.txt').write_text('1. Alpha\n', encoding='utf-8')

    def facts_for(self, tool, args):
        root_abs = os.path.realpath(self.base)
        facts, parsed = verify_delivery._check_facts(root_abs, tool,
                                                     list(args), 1)
        self.assertIsNotNone(facts)
        self.assertIsNotNone(parsed)
        return facts

    def test_facts_register_normalized_path_digest_titles_and_scope(self):
        facts = self.facts_for(
            'verify_translation',
            ['01_章.md', 'docs/src.md', '--official-headings-file',
             'titles.txt'])
        expected_real = os.path.realpath(self.base / 'titles.txt')
        # 相对路径按交付根解释；登记规范化路径 + 内容摘要
        self.assertEqual(facts['files']['official_headings'],
                         [expected_real, hashlib.sha256(
                             (self.base / 'titles.txt').read_bytes()
                         ).hexdigest()])
        oh = facts['params']['official_headings']
        self.assertEqual(oh['path'], expected_real)
        self.assertEqual(oh['titles'], ['1. Alpha'])
        self.assertEqual(oh['scope'], 'full-doc-order')
        # 只记录参数字符串不算数：摘要与有效原题来自实际文件内容
        self.assertTrue(verify_delivery._facts_complete(facts))

    def test_same_path_changed_content_invalidates_facts(self):
        args = ['01_章.md', 'docs/src.md', '--official-headings-file',
                'titles.txt']
        before = self.facts_for('verify_translation', args)
        (self.base / 'titles.txt').write_text('1. Alpha Changed\n',
                                              encoding='utf-8')
        after = self.facts_for('verify_translation', args)
        self.assertNotEqual(
            before['files']['official_headings'],
            after['files']['official_headings'])
        self.assertNotEqual(before['params']['official_headings']['titles'],
                            after['params']['official_headings']['titles'])

    def test_missing_file_binding_incomplete(self):
        (self.base / 'titles.txt').unlink()
        facts = self.facts_for(
            'verify_translation',
            ['01_章.md', 'docs/src.md', '--official-headings-file',
             'titles.txt'])
        self.assertFalse(verify_delivery._facts_complete(facts))

    def test_scope_per_family_and_shared_dep_registered(self):
        cases = {
            'verify_paginated_translation':
                (['01_章.md', 'docs/src.md', '--official-headings-file',
                  'titles.txt'], 'assembly:skip-head-1'),
            'verify_reference_translation':
                (['01_章.md', 'docs/src.md', '--official-headings-file',
                  'titles.txt'], 'full-doc-order'),
            'verify_api_translation':
                (['01_章.md', 'manifest.txt', 'toc.txt', 'site/', 'p1.md',
                  'p2.md', '--official-headings-file', 'titles.txt'],
                 'manifest-page-order'),
        }
        for tool, (args, scope) in cases.items():
            with self.subTest(tool=tool):
                facts = self.facts_for(tool, args)
                self.assertEqual(
                    facts['params']['official_headings']['scope'], scope)
                self.assertIn('_official_headings.py',
                              facts['shared_deps'])
        for tool in ('verify_translation', 'verify_paginated_translation',
                     'verify_reference_translation', 'verify_api_translation'):
            self.assertIn('_official_headings.py',
                          verify_delivery.CHECK_SHARED_DEPS[tool])


class DeliveryOfficialHeadingsBindingTest(unittest.TestCase):
    """verify_delivery 既有入口：标题文件进入复核绑定；同路径改内容使
    旧复核失效，重新按当前身份核对后恢复资格。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='oh-binding-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        (self.root / 'docs').mkdir(parents=True)
        (self.root / '01_章.md').write_text('# 第 1 章\n\n正文。\n',
                                            encoding='utf-8')
        (self.root / 'docs' / 'src.md').write_text('# 1. Alpha\n\nbody\n',
                                                   encoding='utf-8')
        (self.root / 'titles.txt').write_text('1. Alpha\n', encoding='utf-8')
        self.args = ['01_章.md', 'docs/src.md', '--official-headings-file',
                     'titles.txt']

    def record(self, reviews=None):
        return {'mode': 'translation', 'inputs': ['01_章.md'],
                'outputs': [],
                'checks': [{'tool': 'verify_translation',
                            'args': list(self.args)}],
                'reviews': reviews if reviews is not None else []}

    def contexts(self):
        root_abs = os.path.realpath(self.root)
        facts, _parsed = verify_delivery._check_facts(
            root_abs, 'verify_translation', list(self.args), 1)
        translated = str((self.root / '01_章.md').resolve())
        return {translated: [{
            'order': 1, 'tool': 'verify_translation',
            'script_sha256': facts['script_sha256'],
            'shared_deps': facts['shared_deps'], 'facts': facts}]}

    def reviews(self):
        identity = verify_delivery.compute_delivery_identity(
            self.root, self.record(), [])
        digest = hashlib.sha256(
            (self.root / '01_章.md').read_bytes()).hexdigest()
        result = []
        for kind, note in (('semantic', '语义复核闭合'),
                           ('source-reconcile', '源全量对账闭合')):
            binding = verify_delivery.expected_review_binding(
                kind, '01_章.md', str(self.root), self.record(),
                [], self.contexts(), {}, identity)
            self.assertIsNotNone(binding)
            result.append({'kind': kind, 'target': '01_章.md',
                           'status': 'closed', 'sha256': digest,
                           'binding': binding, 'note': note})
        return result

    def check(self, reviews):
        problems = []
        verify_delivery.check_reviews(
            self.record(reviews), problems, None, root=str(self.root),
            input_checks=self.contexts(), pdf_checks={},
            source_entries=[],
            identity=verify_delivery.compute_delivery_identity(
                self.root, self.record(), []))
        return problems

    def test_official_headings_content_change_invalidates_and_recovers(self):
        reviews = self.reviews()
        self.assertEqual(self.check(reviews), [])
        # 同路径修改标题文件内容：相关旧复核失效（相同参数字符串不算数）
        (self.root / 'titles.txt').write_text('1. Alpha Changed\n',
                                              encoding='utf-8')
        problems = self.check(reviews)
        self.assertTrue(problems, '标题文件内容变化后旧复核应失效')
        # 重新按当前身份核对后恢复资格
        self.assertEqual(self.check(self.reviews()), [])


class ExportHeadingListTest(unittest.TestCase):
    """工作清单导出：围栏感知、未闭合诊断、不覆盖源、源摘要不变。"""

    SOURCE = (
        '# 1. Real Heading\n'
        '\n'
        '````\n'
        '# fenced comment in quad backticks\n'
        '````\n'
        '\n'
        '~~~text\n'
        '# fenced comment in tilde\n'
        '~~~\n'
        '\n'
        '## 1.1. Second Heading\n'
    )

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='oh-export-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.src = self.base / 'source.md'
        self.src.write_text(self.SOURCE, encoding='utf-8')
        self.digest_before = hashlib.sha256(
            self.src.read_bytes()).hexdigest()

    def test_exports_only_real_headings(self):
        out = self.base / 'worklist.txt'
        titles = export_heading_list(str(self.src), str(out))
        self.assertEqual(titles, ['1. Real Heading', '1.1. Second Heading'])
        self.assertEqual(out.read_text(encoding='utf-8').splitlines(),
                         titles)
        # 源摘要不变（只读，不覆盖源）
        self.assertEqual(hashlib.sha256(self.src.read_bytes()).hexdigest(),
                         self.digest_before)

    def test_refuses_to_overwrite_source(self):
        with self.assertRaises(SystemExit):
            export_heading_list(str(self.src), str(self.src))

    def test_unclosed_fence_diagnosed_and_rejected(self):
        broken = self.base / 'broken.md'
        broken.write_text('# 1. A\n\n```\n# hidden\n', encoding='utf-8')
        out = self.base / 'broken_out.txt'
        with self.assertRaises(SystemExit) as ctx:
            export_heading_list(str(broken), str(out))
        self.assertIn('未闭合', str(ctx.exception))
        self.assertFalse(out.exists(), '未闭合围栏不得产出清单文件')


if __name__ == '__main__':
    unittest.main()
