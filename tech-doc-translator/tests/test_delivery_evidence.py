"""交付完成统一检查的固定验收（留痕 06：目录允许清单与持久证据）。

纯规则测试（复核绑定、参数解释、发布失败）使用最小输入不启动浏览器；
真实集成测试复用同一只读 PDF 基样（setUpClass 导出一次，逐测试复制到
独立目录并改写导出证据内的绝对路径），各负例在独立副本上隔离，不共享
可变报告。旧“缺预存报告必须失败”按精简 03 改为“本次结果必须有效”：
不读取任何预存核验 JSON，伪造旧 JSON 不影响结果；导出证据与政策绑定
缺失仍必须拒绝。
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import export_pdf as exporter
import verify_delivery as delivery_verifier
import verify_pdf as pdf_verifier


SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'


def make_png(path, w, h, color=b'\x01\x02\x03'):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + color * w for _ in range(h))
    open(path, 'wb').write(
        b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_delivery(root: Path, require_strict=False):
    """构造最小合规交付：章（含图与可定位出处）+ export/ 映射 + 成品 PDF。

    解析 Markdown 与 per-stem 映射由真实解析入口从快照生成（源链可被
    verify_delivery 独立对账），快照含与译文一致的代码块。"""
    make_png(root / 'source/images/pic.png', 20, 10)
    make_png(root / 'images/pic.png', 20, 10)
    (root / '01_章.md').write_text(
        '# 第 1 章\n\n'
        '> **来源**：https://example.com/pv-delivery\n'
        '> **抓取日期**：2026-09-15\n\n'
        '![图](images/pic.png)\n\n正文。\n\n'
        '```text\nhello = 1;\n```\n', encoding='utf-8')
    (root / 'source/page.html').write_text(
        '<html><body><article><h1>第 1 章</h1>'
        '<img src="images/pic.png" style="width:300px">'
        '<div class="highlight"><pre><code>hello = 1;</code></pre></div>'
        '</article></body></html>', encoding='utf-8')
    docs = root / 'docs'
    docs.mkdir(exist_ok=True)
    manifest = docs / 'manifest.json'
    # 解析输出放在快照同目录：图片引用沿用快照相对路径，可独立解析
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / 'parse_single_page_html.py'),
         str(root / 'source/page.html'),
         str(root / 'source/source_en.md')],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (root / 'source/source_en.images_display.json').is_file()
    manifest.write_text(json.dumps({
        'version': 1, 'source_version': '13.4-test', 'family': 'single',
        'pages': [{'snapshot': str(root / 'source/page.html'),
                   'markdown': str(root / '01_章.md')}]}), encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / 'rebuild_images_display.py'),
         '--manifest', str(manifest),
         '--output', str(root / 'export/images_display.json')],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    work = root / 'work'
    work.mkdir(exist_ok=True)
    result = exporter.export(
        [str(root / '01_章.md')],
        Path(root / 'book.pdf'), work,
        images_display_paths=[str(root / 'export/images_display.json')],
        require_display_map=require_strict)
    assert result == 0, (root / 'book.pdf')
    return root / 'book.pdf'


def retarget_tree_json(tree: Path, old: Path, new: Path):
    """把副本内 JSON 字符串中的旧根绝对路径改写到新根（字节不变时摘要不变）。"""
    for path in tree.rglob('*.json'):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            continue

        def visit(node):
            if isinstance(node, str):
                return (node.replace(str(old), str(new))
                        .replace(str(old.resolve()), str(new.resolve())))
            if isinstance(node, list):
                return [visit(item) for item in node]
            if isinstance(node, dict):
                return {visit(key) if isinstance(key, str) else key:
                        visit(value) for key, value in node.items()}
            return node

        path.write_text(json.dumps(visit(payload), ensure_ascii=False,
                                   indent=2), encoding='utf-8')


def pending_review_items(root: Path, strict=False):
    """用同一核验计算取得本次报告的待复核定位标签（不读预存 JSON）。"""
    args = ['--pdf', str(root / 'book.pdf'), '--work-dir', str(root / 'work'),
            '--images-display', str(root / 'export/images_display.json')]
    if strict:
        args.append('--require-display-map')
    args.append(str(root / '01_章.md'))
    ns = pdf_verifier.parse_args(args)
    ok, report = pdf_verifier.run_verification(ns)
    assert ok, report['failures']
    return [delivery_verifier.review_item_label(item, 'relaxed_matches', index)
            for index, item in enumerate(report.get('relaxed_matches', []))
            if item.get('review', True)]


def delivery_contexts(root: Path, record):
    """用与 verify_delivery 相同的函数计算源链、完整身份与覆盖检查。"""
    problems = []
    entries = delivery_verifier.check_source_chains(root, record, problems)
    assert not problems, problems
    identity = delivery_verifier.compute_delivery_identity(
        root, record, entries)
    _c, _p, input_checks, pdf_checks = delivery_verifier.rerun_checks(
        root, record, problems)
    assert not problems, problems
    return entries, identity, input_checks, pdf_checks


def expected_binding(kind, target, root: Path, record, contexts):
    entries, identity, input_checks, pdf_checks = contexts
    binding = delivery_verifier.expected_review_binding(
        kind, target, str(root), record, entries, input_checks, pdf_checks,
        identity)
    assert binding is not None, (kind, target)
    return binding


def base_record(root: Path, pdf: Path, strict=False, check_mutator=None):
    record = {
        'version': 1,
        'mode': 'translation+pdf',
        'delivery_root': str(root),
        'inputs': ['01_章.md'],
        'outputs': [{'path': 'book.pdf', 'sha256': sha(pdf)}],
        'images_display': 'export/images_display.json',
        'files': {
            '00_目录.md': 'toc',
            '01_章.md': 'chapter',
            'book.pdf': 'pdf',
            '术语表.md': 'glossary',
            '导出前准备说明.md': 'user-note',
            'PDF导出交付说明.md': 'user-note',
        },
        'sources': [{
            'family': 'single', 'source_version': '13.4-test',
            'parsed_markdown': 'source/source_en.md',
            'snapshots': [{'snapshot': 'source/page.html',
                           'section_id': None}],
            'per_stem_map': 'source/source_en.images_display.json',
            'covers': ['01_章.md'],
        }],
        'checks': [
            {'tool': 'verify_pdf',
             'args': ['--pdf', 'book.pdf', '--work-dir', str(root / 'work'),
                      '--images-display', 'export/images_display.json',
                      '01_章.md']},
            {'tool': 'verify_translation',
             'args': ['01_章.md', 'source/source_en.md']},
        ],
    }
    if check_mutator is not None:
        check_mutator(record['checks'])
    # R4/4.7：复核除目标摘要外须携带完整 binding（按当前依赖身份计算），
    # visual 复核逐项列明报告中的待复核 segment。参数被故意改坏（负例）
    # 时无法构成绑定上下文，退化为无绑定记录，交付按缺绑定拒绝。
    try:
        contexts = delivery_contexts(root, record)
    except AssertionError:
        contexts = None
    if contexts is None:
        record['reviews'] = [
            {'kind': 'visual', 'target': 'book.pdf',
             'status': 'closed', 'sha256': sha(pdf),
             'items': pending_review_items(root, strict=strict),
             'note': '全页视觉复核闭合（逐项见 items）'},
            {'kind': 'semantic', 'target': '01_章.md',
             'status': 'closed', 'sha256': sha(root / '01_章.md'),
             'note': '语义复核闭合'},
            {'kind': 'source-reconcile', 'target': '01_章.md',
             'status': 'closed', 'sha256': sha(root / '01_章.md'),
             'note': '源全量对账闭合'}]
        return record
    record['reviews'] = [
        {'kind': 'visual', 'target': 'book.pdf',
         'status': 'closed', 'sha256': sha(pdf),
         'items': pending_review_items(root, strict=strict),
         'binding': expected_binding('visual', 'book.pdf', root, record,
                                     contexts),
         'note': '全页视觉复核闭合（逐项见 items）'},
        {'kind': 'semantic', 'target': '01_章.md',
         'status': 'closed', 'sha256': sha(root / '01_章.md'),
         'binding': expected_binding('semantic', '01_章.md', root, record,
                                     contexts),
         'note': '语义复核闭合'},
        {'kind': 'source-reconcile', 'target': '01_章.md',
         'status': 'closed', 'sha256': sha(root / '01_章.md'),
         'binding': expected_binding('source-reconcile', '01_章.md', root,
                                     record, contexts),
         'note': '源全量对账闭合'},
    ]
    return record


class ReviewBindingUnitTest(unittest.TestCase):
    """check_reviews 完整 binding 口径的单元验收（最小输入，无浏览器）。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='review-unit-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        (self.root / 'docs').mkdir(parents=True)
        (self.root / '01_章.md').write_text('# 第 1 章\n\n正文。\n',
                                            encoding='utf-8')
        (self.root / 'docs/source_en.md').write_text(
            '# Chapter 1\n\nBody. Access allowed.\n', encoding='utf-8')
        self.source_entries = []
        self.pdf_checks = {}

    def identity(self):
        return delivery_verifier.compute_delivery_identity(
            self.root, self.record(), self.source_entries)

    def record(self, reviews=None):
        return {'mode': 'translation', 'inputs': ['01_章.md'],
                'outputs': [], 'sources': [],
                'reviews': reviews if reviews is not None else []}

    def input_checks(self, semantic_args=None, script_sha=None,
                     sources=None):
        translated = str((self.root / '01_章.md').resolve())
        src = str((self.root / 'docs/source_en.md').resolve())
        facts = {
            'script_sha256': (script_sha
                              or sha(SCRIPTS / 'verify_translation.py')),
            'shared_deps': {
                name: sha(SCRIPTS / name)
                for name in delivery_verifier.CHECK_SHARED_DEPS[
                    'verify_translation']},
            'params': (semantic_args
                       or {'strong_tokens': [], 'official': [],
                           'approved_extra_math': [], 'fragment': False}),
            'files': {
                'translated': [translated, sha(self.root / '01_章.md')],
                'sources': ([[path, digest] for path, digest in sources]
                            if sources is not None
                            else [[src, sha(self.root /
                                            'docs/source_en.md')]]),
            },
        }
        return {translated: [{
            'order': 1,
            'tool': 'verify_translation',
            'script_sha256': facts['script_sha256'],
            'shared_deps': facts['shared_deps'],
            'facts': facts,
        }]}

    def binding(self, kind='semantic', input_checks='default',
                identity='default'):
        checks = (self.input_checks() if input_checks == 'default'
                  else input_checks)
        ident = self.identity() if identity == 'default' else identity
        return delivery_verifier.expected_review_binding(
            kind, '01_章.md', str(self.root), self.record(),
            self.source_entries, checks, self.pdf_checks, ident)

    def base_reviews(self, checks='default', identity='default'):
        binding = self.binding('semantic', checks, identity)
        reconcile = self.binding('source-reconcile', checks, identity)
        return [
            {'kind': 'semantic', 'target': '01_章.md', 'status': 'closed',
             'sha256': sha(self.root / '01_章.md'), 'binding': binding,
             'note': '语义复核闭合'},
            {'kind': 'source-reconcile', 'target': '01_章.md',
             'status': 'closed', 'sha256': sha(self.root / '01_章.md'),
             'binding': reconcile, 'note': '源全量对账闭合'}]

    def check(self, reviews, input_checks='default'):
        problems = []
        delivery_verifier.check_reviews(
            self.record(reviews), problems, None, root=str(self.root),
            input_checks=(self.input_checks() if input_checks == 'default'
                          else input_checks),
            pdf_checks=self.pdf_checks, source_entries=self.source_entries,
            identity=self.identity())
        return problems

    def test_valid_bindings_pass(self):
        self.assertEqual(self.check(self.base_reviews()), [])

    def test_source_changed_after_review_invalidates(self):
        # 英文源从“允许访问”改为“禁止访问”，保留译文与旧复核记录——
        # 覆盖检查绑定新源摘要，旧 binding 失效，不能靠旧记录通过。
        reviews = self.base_reviews()
        (self.root / 'docs/source_en.md').write_text(
            '# Chapter 1\n\nBody. Access forbidden.\n', encoding='utf-8')
        problems = self.check(reviews)
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p for p in problems),
            problems)

    def test_source_chain_resource_change_invalidates(self):
        # S5：源链解析侧图片（含 SVG/CSS 递归依赖）变化必须使语义/源对账
        # 复核的旧 binding 失效，不能只盯译文自身资源
        (self.root / 'docs/snap.html').write_text(
            '<html><body><article><h1>Chapter 1</h1>'
            '<img src="pic.svg"></article></body></html>', encoding='utf-8')
        (self.root / 'docs/pic.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
            '<rect width="20" height="10"/></svg>', encoding='utf-8')
        (self.root / 'docs/source_en.md').write_text(
            '# Chapter 1\n\n![pic](pic.svg)\n', encoding='utf-8')
        self.source_entries = [{
            'order': 1, 'family': 'single', 'source_version': '13.4-test',
            'parsed_markdown': 'docs/source_en.md',
            'snapshots': [{'snapshot': 'docs/snap.html', 'section_id': None,
                           'per_stem_map': None}],
            'covers': ['01_章.md'],
            'table_conversions': None,
        }]
        reviews = self.base_reviews()
        self.assertEqual(self.check(reviews), [])
        (self.root / 'docs/pic.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
            '<circle r="10"/></svg>', encoding='utf-8')
        problems = self.check(reviews)
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p for p in problems),
            problems)

    def test_missing_binding_requires_rereview(self):
        reviews = self.base_reviews()
        for review in reviews:
            review.pop('binding')
        problems = self.check(reviews)
        self.assertTrue(
            any('缺少完整 binding' in p for p in problems), problems)

    def test_checker_script_change_invalidates(self):
        # 共享检查脚本变化（script_sha256 或 shared_deps）即旧结论失效
        reviews = self.base_reviews()
        tampered = 'f' * 64
        problems = self.check(
            reviews, input_checks=self.input_checks(script_sha=tampered))
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p for p in problems),
            problems)

    def test_semantic_args_must_match_check(self):
        reviews = self.base_reviews()
        problems = self.check(
            reviews,
            input_checks=self.input_checks(
                semantic_args={'strong_tokens': ['kernel'], 'official': [],
                               'approved_extra_math': [], 'fragment': False}))
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p for p in problems),
            problems)

    def test_declared_source_set_must_cover_actual_sources(self):
        reviews = self.base_reviews()
        other = str((self.root / 'docs/other_en.md').resolve())
        Path(other).write_text('# Other\n', encoding='utf-8')
        problems = self.check(
            reviews,
            input_checks=self.input_checks(
                sources=[(other, sha(other))]))
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p for p in problems),
            problems)

    def test_multi_check_coverage_binds_all_checks(self):
        # 同一译文两条不同源的检查：完整 binding 收录全部覆盖检查，
        # 任一检查变化旧结论失效（§5.3 多检查覆盖）
        second = self.root / 'docs/source_alt.md'
        second.write_text('# Chapter 1 alt\n\nBody.\n', encoding='utf-8')
        key = str((self.root / '01_章.md').resolve())
        first_item = self.input_checks()[key][0]
        second_facts = dict(
            first_item['facts'],
            files=dict(first_item['facts']['files'],
                       sources=[[str(second.resolve()), sha(second)]]))
        checks = {key: [
            first_item,
            dict(first_item, order=2, facts=second_facts)]}
        binding = self.binding('semantic', checks)
        self.assertEqual(len(binding['checks']), 2)
        reconcile = self.binding('source-reconcile', checks)
        reviews = [{'kind': 'semantic', 'target': '01_章.md',
                    'status': 'closed',
                    'sha256': sha(self.root / '01_章.md'),
                    'binding': binding, 'note': '语义复核闭合'},
                   {'kind': 'source-reconcile', 'target': '01_章.md',
                    'status': 'closed',
                    'sha256': sha(self.root / '01_章.md'),
                    'binding': reconcile, 'note': '源全量对账闭合'}]
        self.assertEqual(self.check(reviews, input_checks=checks), [])
        # 第二条源变化后旧 binding 失效（覆盖检查按当前文件重算源摘要）
        second.write_text('# Chapter 1 alt\n\nBody changed.\n',
                          encoding='utf-8')

        def refreshed(item):
            sources = [[path, sha(path) if os.path.isfile(path) else None]
                       for path, _d in item['facts']['files']['sources']]
            return dict(item, facts=dict(
                item['facts'],
                files=dict(item['facts']['files'], sources=sources)))

        fresh = {key: [refreshed(item) for item in checks[key]]}
        problems = self.check(reviews, input_checks=fresh)
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p for p in problems),
            problems)

    def test_items_covered_per_artifact_not_global(self):
        # 二轮复审（P2-1）：visual 复核的 items 按产物归属——a.pdf 的复核
        # 列了 b.pdf 的 segment 不能替 b.pdf 闭合待复核项。
        record = {
            'mode': 'pdf',
            'inputs': [],
            'outputs': [{'path': 'a.pdf', 'sha256': 'x'},
                        {'path': 'b.pdf', 'sha256': 'y'}],
            'reviews': [
                {'kind': 'visual', 'target': 'a.pdf', 'status': 'closed',
                 'sha256': 'x', 'items': ['seg-b'], 'note': 'n'},
                {'kind': 'visual', 'target': 'b.pdf', 'status': 'closed',
                 'sha256': 'y', 'items': [], 'note': 'n'}],
        }
        problems = []
        segments = {'/r/a.pdf': {'visual': {'seg-a'}},
                    '/r/b.pdf': {'visual': {'seg-b'}}}
        delivery_verifier.check_reviews(record, problems, segments, root='/r')
        self.assertTrue(any('a.pdf' in p and '逐项闭合' in p for p in problems),
                        problems)
        self.assertTrue(any('b.pdf' in p and '逐项闭合' in p for p in problems),
                        problems)

    def test_unclosed_review_and_empty_note_rejected(self):
        binding = self.binding()
        problems = self.check([{'kind': 'semantic', 'target': '01_章.md',
                                'status': 'pending',
                                'binding': binding, 'note': ''}])
        self.assertTrue(any('复核未闭合' in p for p in problems), problems)
        problems = self.check([{'kind': 'semantic', 'target': '01_章.md',
                                'status': 'closed',
                                'sha256': sha(self.root / '01_章.md'),
                                'binding': binding, 'note': ''}])
        self.assertTrue(any('note 为空' in p for p in problems), problems)

    def test_stale_translation_digest_invalidates_review(self):
        reviews = self.base_reviews()
        for review in reviews:
            review['sha256'] = '0' * 64
        problems = self.check(reviews)
        self.assertTrue(
            any('复核摘要与当前输入不符' in p for p in problems), problems)


class CheckFactsUnitTest(unittest.TestCase):
    """检查身份事实（设计 §9.3 固定回归，无浏览器）。

    真实 CLI 参数指向的文件依赖（导出报告、provenance、image_map、
    有序输入/源）进入统一身份；等价参数写法不产生新口径；复核绑定
    按目标投影（无关目标独有依赖不混入）；缺文件/缺摘要不能得到有效
    binding。
    """

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='check-facts-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        for d in ('work', 'docs'):
            (self.root / d).mkdir(parents=True)
        (self.root / 'parsed.md').write_text('# T\n\n正文。\n',
                                             encoding='utf-8')
        (self.root / 'book.pdf').write_bytes(b'placeholder')
        (self.root / 'work/export_report.json').write_text(
            '{"policy": 1}', encoding='utf-8')
        (self.root / 'proof.json').write_text('{"range": 1}',
                                              encoding='utf-8')
        (self.root / 'docs/imgmap.json').write_text(
            '{"digests": []}', encoding='utf-8')
        (self.root / 'docs/src.md').write_text('# S\n', encoding='utf-8')
        self.record = {
            'mode': 'translation+pdf',
            'inputs': ['parsed.md'],
            'outputs': [{'path': 'book.pdf'}],
            'checks': [
                {'tool': 'verify_pdf',
                 'args': ['--pdf', 'book.pdf', '--work-dir', 'work',
                          '--provenance', 'proof.json', 'parsed.md']},
                {'tool': 'verify_translation',
                 'args': ['parsed.md', 'docs/src.md',
                          '--image-map', 'docs/imgmap.json']},
            ],
        }

    def identity(self, record=None):
        return delivery_verifier.compute_delivery_identity(
            str(self.root), record or self.record, [])

    def facts(self, check, order):
        result, _p = delivery_verifier._check_facts(
            str(self.root.resolve()), check['tool'], check['args'], order)
        assert result is not None
        return result

    def visual_binding(self, identity=None, check=None):
        check = check or self.record['checks'][0]
        facts = self.facts(check, 1)
        pdf_checks = {facts['files']['pdf'][0]: [{
            'order': 1, 'tool': 'verify_pdf',
            'script_sha256': facts['script_sha256'],
            'shared_deps': facts['shared_deps'], 'facts': facts}]}
        return delivery_verifier.expected_review_binding(
            'visual', 'book.pdf', str(self.root), self.record, [],
            {}, pdf_checks, identity or self.identity())

    def semantic_binding(self, identity=None):
        facts = self.facts(self.record['checks'][1], 2)
        input_checks = {facts['files']['translated'][0]: [{
            'order': 2, 'tool': 'verify_translation',
            'script_sha256': facts['script_sha256'],
            'shared_deps': facts['shared_deps'], 'facts': facts}]}
        return delivery_verifier.expected_review_binding(
            'semantic', 'parsed.md', str(self.root), self.record, [],
            input_checks, {}, identity or self.identity())

    def test_check_file_dependencies_enter_identity(self):
        baseline = self.identity()
        # 正常对照：未变输入身份稳定；无关文件变化不使身份变化
        self.assertEqual(baseline, self.identity())
        (self.root / 'docs/unrelated.txt').write_text('u', encoding='utf-8')
        self.assertEqual(baseline, self.identity())
        # 导出报告（即使在 work-dir 内）、provenance、image_map 的内容
        # 变化都必须改变检查身份
        for rel in ('work/export_report.json', 'proof.json',
                    'docs/imgmap.json'):
            path = self.root / rel
            backup = path.read_bytes()
            path.write_text('{"changed": 1}', encoding='utf-8')
            try:
                self.assertNotEqual(baseline, self.identity(),
                                    '%s 变化必须改变检查身份' % rel)
            finally:
                path.write_bytes(backup)
        self.assertEqual(baseline, self.identity())

    def test_delivery_entry_change_invalidates_bindings(self):
        # §9.6：交付入口摘要投影进两类绑定——入口口径变化必须使既有
        # 复核失效；摘要缺失即绑定不完整
        import copy
        baseline = self.identity()
        visual = self.visual_binding()
        semantic = self.semantic_binding()
        self.assertEqual(visual['delivery_entry'],
                         baseline['delivery_entry'])
        self.assertEqual(semantic['delivery_entry'],
                         baseline['delivery_entry'])
        tampered = copy.deepcopy(baseline)
        tampered['delivery_entry'] = {'script_sha256': 'f' * 64}
        self.assertNotEqual(visual, self.visual_binding(identity=tampered))
        self.assertNotEqual(semantic, self.semantic_binding(identity=tampered))
        broken = copy.deepcopy(baseline)
        broken['delivery_entry'] = {'script_sha256': None}
        self.assertIsNone(self.visual_binding(identity=broken))
        self.assertIsNone(self.semantic_binding(identity=broken))

    def test_equivalent_cli_spellings_same_identity(self):
        baseline = self.identity()
        import copy
        variant = copy.deepcopy(self.record)
        # --pdf= 等号写法、绝对路径等价写法、布尔开关紧接位置参数
        variant['checks'][0]['args'] = [
            '--pdf=%s' % (self.root / 'book.pdf'), '--work-dir',
            str(self.root / 'work'), '--provenance',
            str(self.root / 'proof.json'),
            '--toc-sections', 'parsed.md']
        # --toc-sections 是语义差异，先确认其确实改变身份（对照）
        self.assertNotEqual(baseline, self.identity(variant))
        variant['checks'][0]['args'] = [
            '--pdf=%s' % (self.root / 'book.pdf'), '--work-dir',
            str(self.root / 'work'), '--provenance',
            str(self.root / 'proof.json'), 'parsed.md']
        self.assertEqual(baseline, self.identity(variant))

    def test_visual_binding_projects_environment_and_style(self):
        binding = self.visual_binding()
        self.assertIsNotNone(binding)
        self.assertIn('environment', binding)
        self.assertIn('style_policy', binding)
        import copy
        altered = copy.deepcopy(self.identity())
        altered['environment']['uniseg'] = 'different'
        self.assertNotEqual(binding, self.visual_binding(identity=altered))
        altered = copy.deepcopy(self.identity())
        altered['style_policy']['pdf_style_css'] = 'different'
        self.assertNotEqual(binding, self.visual_binding(identity=altered))

    def test_unrelated_target_dependency_not_projected(self):
        # 语义复核不混入 PDF 独有依赖（样式政策/pypdf/uniseg），
        # 但包含翻译检查实际调用的图片资源处理环境（Pillow）
        binding = self.semantic_binding()
        self.assertIsNotNone(binding)
        self.assertNotIn('style_policy', binding)
        self.assertNotIn('pypdf', binding['environment'])
        self.assertNotIn('uniseg', binding['environment'])
        self.assertIn('beautifulsoup4', binding['environment'])
        self.assertIn('pillow', binding['environment'])
        import copy
        # 其他目标（PDF）独有依赖变化：本目标 binding 不变
        altered = copy.deepcopy(self.identity())
        altered['style_policy']['pdf_style_css'] = 'different'
        self.assertEqual(binding, self.semantic_binding(identity=altered))
        # 本目标检查依赖变化：image_map 内容变化使旧复核失效
        imgmap = self.root / 'docs/imgmap.json'
        imgmap.write_text('{"digests": []}\n', encoding='utf-8')
        self.assertNotEqual(binding, self.semantic_binding())
        imgmap.write_text('{"digests": []}', encoding='utf-8')
        self.assertEqual(binding, self.semantic_binding())

    def test_visual_binding_scopes_to_covering_inputs(self):
        # 多 PDF 交付：a.pdf 的 visual 绑定只投影其覆盖检查的实际输入，
        # 不混入 b.pdf 独有输入/资源（§9.3 按实际覆盖关系）
        import copy
        (self.root / 'b.md').write_text('# B\n\n正文乙。\n', encoding='utf-8')
        (self.root / 'b.pdf').write_bytes(b'placeholder-b')
        record = copy.deepcopy(self.record)
        record['inputs'] = ['parsed.md', 'b.md']
        record['outputs'] = [{'path': 'book.pdf'}, {'path': 'b.pdf'}]
        record['checks'] = [record['checks'][0],
                            {'tool': 'verify_pdf',
                             'args': ['--pdf', 'b.pdf', '--work-dir', 'work',
                                      'b.md']},
                            record['checks'][1]]
        identity = delivery_verifier.compute_delivery_identity(
            str(self.root), record, [])
        facts_a = self.facts(record['checks'][0], 1)
        facts_b = self.facts(record['checks'][1], 2)
        pdf_checks = {
            facts_a['files']['pdf'][0]: [{
                'order': 1, 'tool': 'verify_pdf',
                'script_sha256': facts_a['script_sha256'],
                'shared_deps': facts_a['shared_deps'], 'facts': facts_a}],
            facts_b['files']['pdf'][0]: [{
                'order': 2, 'tool': 'verify_pdf',
                'script_sha256': facts_b['script_sha256'],
                'shared_deps': facts_b['shared_deps'], 'facts': facts_b}],
        }
        binding_a = delivery_verifier.expected_review_binding(
            'visual', 'book.pdf', str(self.root), record, [], {},
            pdf_checks, identity)
        self.assertIsNotNone(binding_a)
        self.assertEqual(sorted(binding_a['ordered_inputs']), ['parsed.md'])
        self.assertEqual(len(binding_a['checks']), 1)
        # b.pdf 的输入内容变化：a.pdf 的绑定不变（身份变化不影响投影）
        (self.root / 'b.md').write_text('# B\n\n正文乙改。\n',
                                        encoding='utf-8')
        facts_b2 = self.facts(record['checks'][1], 2)
        pdf_checks[facts_b2['files']['pdf'][0]] = [{
            'order': 2, 'tool': 'verify_pdf',
            'script_sha256': facts_b2['script_sha256'],
            'shared_deps': facts_b2['shared_deps'], 'facts': facts_b2}]
        identity2 = delivery_verifier.compute_delivery_identity(
            str(self.root), record, [])
        self.assertNotEqual(identity, identity2)
        binding_a2 = delivery_verifier.expected_review_binding(
            'visual', 'book.pdf', str(self.root), record, [], {},
            pdf_checks, identity2)
        self.assertEqual(binding_a, binding_a2)
        # b.pdf 自身的绑定覆盖其输入（与 a 的投影不同）
        binding_b = delivery_verifier.expected_review_binding(
            'visual', 'b.pdf', str(self.root), record, [], {},
            pdf_checks, identity2)
        self.assertIsNotNone(binding_b)
        self.assertEqual(sorted(binding_b['ordered_inputs']), ['b.md'])

    def test_visual_binding_covers_all_checks_same_pdf(self):
        # 同一 PDF 多条 verify_pdf（不同语义参数）：投影全部覆盖检查，
        # 只投影一条的旧绑定不得被判等效
        import copy
        record = copy.deepcopy(self.record)
        record['checks'] = [record['checks'][0],
                            dict(record['checks'][0],
                                 args=['--pdf', 'book.pdf', '--work-dir',
                                       'work', '--toc-sections',
                                       'parsed.md']),
                            record['checks'][1]]
        identity = delivery_verifier.compute_delivery_identity(
            str(self.root), record, [])
        facts_1 = self.facts(record['checks'][0], 1)
        facts_2 = self.facts(record['checks'][1], 2)
        key = facts_1['files']['pdf'][0]
        pdf_checks = {key: [
            {'order': 1, 'tool': 'verify_pdf',
             'script_sha256': facts_1['script_sha256'],
             'shared_deps': facts_1['shared_deps'], 'facts': facts_1},
            {'order': 2, 'tool': 'verify_pdf',
             'script_sha256': facts_2['script_sha256'],
             'shared_deps': facts_2['shared_deps'], 'facts': facts_2}]}
        binding = delivery_verifier.expected_review_binding(
            'visual', 'book.pdf', str(self.root), record, [], {},
            pdf_checks, identity)
        self.assertIsNotNone(binding)
        self.assertEqual(len(binding['checks']), 2)
        single = dict(binding, checks=binding['checks'][:1])
        self.assertNotEqual(single, binding)

    def test_duplicate_sources_kept_in_facts(self):
        # 有序源按真实解析顺序登记（保留重复）：重复源不折叠
        facts = self.facts(
            {'tool': 'verify_paginated_translation',
             'args': ['parsed.md', 'docs/src.md', 'docs/src.md']}, 3)
        self.assertEqual(len(facts['files']['sources']), 2)

    def test_delivery_map_change_invalidates_visual_binding(self):
        # 已声明的交付级映射是 PDF 复核依赖：内容变化旧 binding 失效
        import copy
        (self.root / 'export').mkdir(exist_ok=True)
        (self.root / 'export/images_display.json').write_text(
            '{"version": 1, "entries": [], "undetermined": []}',
            encoding='utf-8')
        record = copy.deepcopy(self.record)
        record['images_display'] = 'export/images_display.json'
        identity = delivery_verifier.compute_delivery_identity(
            str(self.root), record, [])
        check = record['checks'][0]
        facts = self.facts(check, 1)
        pdf_checks = {facts['files']['pdf'][0]: [{
            'order': 1, 'tool': 'verify_pdf',
            'script_sha256': facts['script_sha256'],
            'shared_deps': facts['shared_deps'], 'facts': facts}]}
        binding = delivery_verifier.expected_review_binding(
            'visual', 'book.pdf', str(self.root), record, [], {},
            pdf_checks, identity)
        self.assertIsNotNone(binding)
        (self.root / 'export/images_display.json').write_text(
            '{"version": 1, "entries": [], "undetermined": []}\n',
            encoding='utf-8')
        fresh = delivery_verifier.expected_review_binding(
            'visual', 'book.pdf', str(self.root), record, [], {},
            pdf_checks,
            delivery_verifier.compute_delivery_identity(
                str(self.root), record, []))
        self.assertNotEqual(binding, fresh)

    def test_conversion_map_change_invalidates_chain_binding(self):
        # 已声明的逐表转换映射进入源链身份：内容变化旧复核失效
        (self.root / 'docs/snap.html').write_text(
            '<html><body><article><p>S</p></article></body></html>',
            encoding='utf-8')
        (self.root / 'docs/conversions.json').write_text(
            '{"version": 1, "tables": []}', encoding='utf-8')
        entry = {'order': 1, 'family': 'single',
                 'source_version': '13.4-test',
                 'parsed_markdown': 'docs/src.md',
                 'snapshots': [{'snapshot': 'docs/snap.html',
                                'section_id': None, 'per_stem_map': None}],
                 'covers': ['parsed.md'], 'table_conversions':
                 'docs/conversions.json'}
        record = dict(self.record, sources=[entry])
        binding = self.semantic_binding(
            identity=delivery_verifier.compute_delivery_identity(
                str(self.root), record, [entry]))
        # 语义 binding 需经带源链的记录计算
        facts = self.facts(record['checks'][1], 2)
        input_checks = {facts['files']['translated'][0]: [{
            'order': 2, 'tool': 'verify_translation',
            'script_sha256': facts['script_sha256'],
            'shared_deps': facts['shared_deps'], 'facts': facts}]}

        def semantic_with_chain():
            return delivery_verifier.expected_review_binding(
                'semantic', 'parsed.md', str(self.root), record, [entry],
                input_checks, {},
                delivery_verifier.compute_delivery_identity(
                    str(self.root), record, [entry]))

        binding = semantic_with_chain()
        self.assertIsNotNone(binding)
        (self.root / 'docs/conversions.json').write_text(
            '{"version": 1, "tables": [], "note": "changed"}',
            encoding='utf-8')
        self.assertNotEqual(binding, semantic_with_chain())

    def test_missing_declared_dependency_gives_no_binding(self):        # 缺文件/缺摘要不能得到有效 binding（None==None 不放行）
        imgmap = self.root / 'docs/imgmap.json'
        backup = imgmap.read_bytes()
        imgmap.unlink()
        try:
            self.assertIsNone(self.semantic_binding())
        finally:
            imgmap.write_bytes(backup)
        proof = self.root / 'proof.json'
        backup = proof.read_bytes()
        proof.unlink()
        try:
            self.assertIsNone(self.visual_binding())
        finally:
            proof.write_bytes(backup)
        self.assertIsNotNone(self.semantic_binding())
        self.assertIsNotNone(self.visual_binding())


class MergedSourceRangesTest(unittest.TestCase):
    """合并源快照行区间（S6/§8.4）：正确 A+B 通过，漏页/错序/缺声明拒绝。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='merged-ranges-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        (self.root / 'source').mkdir(parents=True)
        (self.root / 'source/a.html').write_text(
            '<html><body><main><h1>A</h1><p>one</p></main></body></html>',
            encoding='utf-8')
        (self.root / 'source/b.html').write_text(
            '<html><body><main><h1>B</h1><p>two</p></main></body></html>',
            encoding='utf-8')
        self.merged = self.root / 'source/merged.md'
        # 解析候选 = 两页真实解析输出的原文拼接
        parts = []
        for stem in ('a', 'b'):
            out = self.root / ('source/%s.md' % stem)
            subprocess.run(
                [sys.executable, str(SCRIPTS / 'parse_single_page_html.py'),
                 str(self.root / ('source/%s.html' % stem)), str(out)],
                capture_output=True, check=True)
            parts.append(out.read_text(encoding='utf-8'))
            out.unlink()
        self.merged.write_text(''.join(parts), encoding='utf-8')
        total = len(self.merged.read_text(encoding='utf-8').split('\n'))
        # 首段末尾换行是两段的行边界：A 占 1..first_lines，B 起于下一行
        self.first_lines = len(parts[0].split('\n')) - 1
        self.total_lines = total

    def entry(self, ranges):
        if ranges is None:
            snaps = [{'snapshot': 'source/a.html'},
                     {'snapshot': 'source/b.html'}]
        elif len(ranges) == 1:
            snaps = [{'snapshot': 'source/a.html', 'range': ranges[0]}]
        else:
            snaps = [{'snapshot': 'source/a.html', 'range': ranges[0]},
                     {'snapshot': 'source/b.html', 'range': ranges[1]}]
        return {'order': 1, 'family': 'single', 'source_version': '13.4-test',
                'parsed_markdown': 'source/merged.md', 'snapshots': snaps,
                'covers': [], 'table_conversions': None}

    def run_preflight(self, ranges):
        problems = []
        record = {'mode': 'translation', 'inputs': [],
                  'sources': [self.entry(ranges)]}
        delivery_verifier.check_source_chains(str(self.root), record, problems)
        return problems

    def run_reconcile(self, ranges):
        problems = []
        entries = [self.entry(ranges)]
        delivery_verifier.run_source_reconcile(
            str(self.root), {}, entries, problems)
        return problems

    def test_valid_merged_ranges_reconcile(self):
        ranges = [[1, self.first_lines],
                  [self.first_lines + 1, self.total_lines]]
        self.assertEqual(self.run_preflight(ranges), [])
        self.assertEqual(self.run_reconcile(ranges), [])

    def test_missing_ranges_rejected(self):
        problems = self.run_reconcile(None)
        self.assertTrue(
            any('缺少 range' in p for p in problems), problems)

    def test_gap_and_partial_rejected(self):
        problems = self.run_reconcile([[1, self.first_lines - 1],
                                       [self.first_lines + 1, self.total_lines]])
        self.assertTrue(
            any('按序无缝覆盖' in p for p in problems), problems)
        problems = self.run_reconcile([[1, 2]])
        self.assertTrue(
            any('未覆盖解析 Markdown 末行' in p for p in problems), problems)

    def test_out_of_order_rejected(self):
        problems = self.run_reconcile(
            [[1, self.first_lines], [self.first_lines + 1, self.total_lines]],
        )
        self.assertEqual(problems, [])
        # 交换两段内容（错序）：各自范围对账必须失败
        lines = self.merged.read_text(encoding='utf-8').split('\n')
        first = lines[:self.first_lines]
        second = lines[self.first_lines:]
        self.merged.write_text('\n'.join(second + first), encoding='utf-8')
        problems = self.run_reconcile(
            [[1, self.total_lines - self.first_lines],
             [self.total_lines - self.first_lines + 1, self.total_lines]])
        self.assertTrue(
            any('源全量对账失败' in p for p in problems), problems)


class PerSnapshotSourceIdentityTest(unittest.TestCase):
    """逐快照源资源身份与 per_stem_map 双层声明（R4 细化/设计 §9.3、§9.4）。

    正向对照：未变输入身份稳定、无图快照免映射、单快照旧声明通过；
    负向：首/中/末快照资源或 SVG/CSS 子资源变化、删资源、错源/错上下文/
    缺证明均检出，无关选区外资源与代码内图片字面量不误拒。
    纯规则测试，不启动浏览器。
    """

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='per-snapshot-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        (self.root / 'source').mkdir(parents=True)
        # 交付级映射（§8.3：有图即须声明）；本类测试无交付输入，空映射即可
        (self.root / 'export').mkdir()
        (self.root / 'export/images_display.json').write_text(
            '{"version": 1, "entries": [], "undetermined": []}',
            encoding='utf-8')

    def write_snapshot(self, rel, body, images=()):
        """写快照及其图片资源；body 中的引用相对快照目录。"""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<html><body><article>%s</article></body></html>'
                        % body, encoding='utf-8')
        for name, content in images:
            target = path.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def parse_page(self, html_rel, md_rel):
        """用真实解析入口生成解析 Markdown 与 per-stem 映射。"""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_single_page_html.py'),
             str(self.root / html_rel), str(self.root / md_rel)],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        map_path = self.root / md_rel.replace(
            '.md', '.images_display.json')
        return md_rel, (str(map_path.relative_to(self.root))
                        if map_path.is_file() else None)

    def entry(self, snapshots, parsed='source/merged.md', **extra):
        base = {'order': 1, 'family': 'single', 'source_version': '13.4-test',
                'parsed_markdown': parsed, 'snapshots': snapshots,
                'covers': [], 'table_conversions': None}
        base.update(extra)
        return base

    def record(self, entry):
        return {'mode': 'translation', 'inputs': [], 'outputs': [],
                'images_display': 'export/images_display.json',
                'sources': [entry]}

    def identity(self, entry):
        return delivery_verifier.compute_delivery_identity(
            str(self.root), {'mode': 'translation', 'inputs': [],
                             'outputs': []}, [entry])

    def preflight(self, entry):
        problems = []
        delivery_verifier.check_source_chains(
            str(self.root), self.record(entry), problems)
        return problems

    def build_two_snapshot_merged(self):
        """两份有图快照 + 真实解析产物拼接的合并 Markdown 与各自映射。"""
        self.write_snapshot('source/a/page.html',
                            '<h1>A</h1><img src="pic.png" width="20">',
                            images=[('pic.png', b'a-bytes')])
        self.write_snapshot('source/b/page.html',
                            '<h1>B</h1><img src="pic.png" width="20">',
                            images=[('pic.png', b'b-bytes')])
        parts = []
        maps = {}
        for stem in ('a', 'b'):
            md_rel = 'source/%s.md' % stem
            _, map_rel = self.parse_page('source/%s/page.html' % stem, md_rel)
            maps[stem] = map_rel
            parts.append((self.root / md_rel).read_text(encoding='utf-8'))
        merged = ''.join(parts)
        (self.root / 'source/merged.md').write_text(merged, encoding='utf-8')
        first = len(parts[0].split('\n')) - 1
        total = len(merged.split('\n'))
        snapshots = [
            {'snapshot': 'source/a/page.html', 'range': [1, first]},
            {'snapshot': 'source/b/page.html',
             'range': [first + 1, total]},
        ]
        return snapshots, maps

    def test_duplicate_identical_images_keep_distinct_nodes(self):
        # 第二轮复审 P2（§9.6.1）：同页完全相同的 img 标签不得因
        # 内容相等被判为同一节点；生产端按对象身份定位
        self.write_snapshot(
            'source/a/page.html',
            '<img src="pic.png" width="20">\n<img src="pic.png" width="20">',
            images=[('pic.png', b'dup')])
        md_rel, map_rel = self.parse_page('source/a/page.html',
                                          'source/a.md')
        payload = json.loads(
            (self.root / map_rel).read_text(encoding='utf-8'))
        nodes = [item['source_node'] for item in
                 payload['entries'] + payload['undetermined']]
        self.assertEqual(nodes, ['img[0]', 'img[1]'])
        entry = self.entry([{'snapshot': 'source/a/page.html',
                             'per_stem_map': map_rel}], parsed=md_rel)
        self.assertEqual(self.preflight(entry), [])

    # --- 解析期映射独立来源证明（§9.6 首轮复审 P2 固定回归） ---

    def test_map_without_valid_structure_or_version_rejected(self):
        # 复审探针：有效 JSON（{} 或 version=999）曾照常通过并发布；
        # 结构/版本校验复用 _image_binding.validate_parse_map
        snapshots, maps = self.build_two_snapshot_merged()
        snapshots[0]['per_stem_map'] = maps['a']
        snapshots[1]['per_stem_map'] = maps['b']
        entry = self.entry(snapshots)
        self.assertEqual(self.preflight(entry), [])  # 正常对照
        map_path = self.root / maps['a']
        backup = map_path.read_text(encoding='utf-8')
        for label, content in (
                ('空对象', '{}'),
                ('未知版本', '{"version": 999, "entries": [],'
                            ' "undetermined": []}')):
            map_path.write_text(content, encoding='utf-8')
            try:
                problems = self.preflight(entry)
                self.assertTrue(
                    any('未知映射版本' in p for p in problems),
                    '%s 必须被结构/版本校验拒绝: %s' % (label, problems))
            finally:
                map_path.write_text(backup, encoding='utf-8')
        self.assertEqual(self.preflight(entry), [])

    def test_map_missing_source_identity_rejected(self):
        # 来源字段“存在才核对”曾使缺证明的映射通过；现在缺 snapshot/
        # snapshot_sha256 任一即拒绝
        snapshots, maps = self.build_two_snapshot_merged()
        snapshots[0]['per_stem_map'] = maps['a']
        snapshots[1]['per_stem_map'] = maps['b']
        entry = self.entry(snapshots)
        self.assertEqual(self.preflight(entry), [])  # 正常对照
        map_path = self.root / maps['a']
        payload = json.loads(map_path.read_text(encoding='utf-8'))
        backup = map_path.read_text(encoding='utf-8')
        for key in ('snapshot', 'snapshot_sha256'):
            variant = {k: v for k, v in payload.items() if k != key}
            map_path.write_text(json.dumps(variant), encoding='utf-8')
            try:
                problems = self.preflight(entry)
                self.assertTrue(
                    any('不构成独立来源证明' in p for p in problems),
                    '缺 %s 必须按缺证明拒绝: %s' % (key, problems))
            finally:
                map_path.write_text(backup, encoding='utf-8')
        self.assertEqual(self.preflight(entry), [])

    def test_map_entries_must_match_snapshot_images(self):
        # 条目须按 source_node 与快照实际图片一一对应；资源身份不符或
        # 条目缺资源身份各自拒绝
        self.write_snapshot(
            'source/a/page.html',
            '<img src="p1.png" width="10"><img src="p2.png" width="20">',
            images=[('p1.png', b'1'), ('p2.png', b'2')])
        md_rel, map_rel = self.parse_page('source/a/page.html',
                                          'source/a.md')
        entry = self.entry([{'snapshot': 'source/a/page.html',
                             'per_stem_map': map_rel}], parsed=md_rel)
        self.assertEqual(self.preflight(entry), [])  # 正常对照
        map_path = self.root / map_rel
        payload = json.loads(map_path.read_text(encoding='utf-8'))
        backup = map_path.read_text(encoding='utf-8')
        try:
            variant = json.loads(backup)
            variant['entries'] = variant['entries'][:1]
            map_path.write_text(json.dumps(variant), encoding='utf-8')
            problems = self.preflight(entry)
            self.assertTrue(any('与快照实际图片出现不对应' in p
                                for p in problems), problems)

            variant = json.loads(backup)
            variant['entries'][0]['resource_sha256'] = 'f' * 64
            map_path.write_text(json.dumps(variant), encoding='utf-8')
            problems = self.preflight(entry)
            self.assertTrue(any('资源身份与快照实际资源不符' in p
                                for p in problems), problems)

            variant = json.loads(backup)
            variant['entries'][0].pop('resource_sha256', None)
            map_path.write_text(json.dumps(variant), encoding='utf-8')
            problems = self.preflight(entry)
            self.assertTrue(any('缺资源身份记录' in p for p in problems),
                            problems)
        finally:
            map_path.write_text(backup, encoding='utf-8')
        self.assertEqual(self.preflight(entry), [])

    # --- 逐快照资源身份（设计 §9.1 复现缺口的固定回归） ---

    def test_three_snapshot_resource_changes_detected(self):
        # 首/中/末三快照，各自目录同名 pic.png 内容不同
        for name in ('first', 'middle', 'last'):
            self.write_snapshot(
                'source/%s/page.html' % name,
                '<p>%s</p><img src="pic.png">' % name,
                images=[('pic.png', name.encode())])
        (self.root / 'source/merged.md').write_text(
            'first\n\n![a](pic.png)\n\nmiddle\n\n![b](pic.png)\n\n'
            'last\n\n![c](pic.png)\n', encoding='utf-8')
        entry = self.entry([
            {'snapshot': 'source/first/page.html', 'range': [1, 3]},
            {'snapshot': 'source/middle/page.html', 'range': [4, 6]},
            {'snapshot': 'source/last/page.html', 'range': [7, 9]}])
        baseline = self.identity(entry)
        # 正常对照：未变输入身份稳定
        self.assertEqual(baseline, self.identity(entry))
        for name in ('first', 'middle', 'last'):
            pic = self.root / 'source' / name / 'pic.png'
            backup = pic.read_bytes()
            pic.write_bytes(b'CHANGED')
            try:
                self.assertNotEqual(baseline, self.identity(entry),
                                    '%s 快照资源变化必须改变身份' % name)
            finally:
                pic.write_bytes(backup)
        # 选区外无关资源变化不误拒
        (self.root / 'source/last/unrelated.txt').write_text(
            'unrelated', encoding='utf-8')
        self.assertEqual(baseline, self.identity(entry))

    def test_deleted_middle_resource_is_explicit_problem(self):
        # 删除中间快照资源：预检定位明确错误，且身份不与原值相等
        # （None==None 不构成相等通过）
        self.write_snapshot('source/a/page.html',
                            '<img src="pic.png">', images=[('pic.png', b'a')])
        self.write_snapshot('source/b/page.html',
                            '<img src="pic.png">', images=[('pic.png', b'b')])
        (self.root / 'source/merged.md').write_text(
            '![a](pic.png)\n![b](pic.png)\n', encoding='utf-8')
        entry = self.entry([
            {'snapshot': 'source/a/page.html', 'range': [1, 1]},
            {'snapshot': 'source/b/page.html', 'range': [2, 2]}])
        baseline = self.identity(entry)
        (self.root / 'source/b/pic.png').unlink()
        problems = self.preflight(entry)
        self.assertTrue(any('无法确定身份' in p for p in problems), problems)
        self.assertNotEqual(baseline, self.identity(entry))

    def test_reference_same_basename_original_refs_kept(self):
        # reference 家族：不同目录同名图按各自声明目录解析，原始引用保留
        for name in ('left', 'right'):
            self.write_snapshot(
                'source/%s/page.html' % name, '<img src="plot.png">',
                images=[('plot.png', name.encode())])
        (self.root / 'source/merged.md').write_text(
            '![a](images/plot.png)\n![b](images/plot.png)\n',
            encoding='utf-8')
        entry = self.entry([
            {'snapshot': 'source/left/page.html', 'range': [1, 1]},
            {'snapshot': 'source/right/page.html', 'range': [2, 2]}],
        )
        entry['family'] = 'reference'
        identity = self.identity(entry)
        facts = identity['resources']['sources']['source/merged.md']
        self.assertEqual(
            [(fact['snapshot'], img['source_ref'], img['src'])
             for fact in facts for img in fact['images']],
            [('source/left/page.html', 'plot.png', 'images/plot.png'),
             ('source/right/page.html', 'plot.png', 'images/plot.png')])
        for name in ('left', 'right'):
            pic = self.root / 'source' / name / 'plot.png'
            backup = pic.read_bytes()
            pic.write_bytes(b'CHANGED')
            try:
                self.assertNotEqual(identity, self.identity(entry),
                                    '%s 源图变化必须改变身份' % name)
            finally:
                pic.write_bytes(backup)

    def test_svg_css_subresource_change_detected(self):
        # SVG → CSS → 位图 的递归依赖：改最内层子资源也改变身份
        self.write_snapshot(
            'source/a/page.html', '<img src="pic.svg">',
            images=[('pic.svg',
                     b'<svg xmlns="http://www.w3.org/2000/svg" '
                     b'width="20" height="10">'
                     b'<image href="pic.png"/></svg>'),
                    ('pic.png', b'png-bytes')])
        (self.root / 'source/merged.md').write_text(
            '![a](pic.svg)\n', encoding='utf-8')
        entry = self.entry([{'snapshot': 'source/a/page.html'}])
        baseline = self.identity(entry)
        (self.root / 'source/a/pic.png').write_bytes(b'png-changed')
        self.assertNotEqual(baseline, self.identity(entry))

    def test_code_block_image_literal_not_required(self):
        # pre 内图片语法不是实际图片出现：无图快照免映射，缺文件不误拒
        self.write_snapshot(
            'source/a/page.html',
            '<p>x</p><pre><code>&lt;img src="gone.png"&gt;</code></pre>')
        (self.root / 'source/merged.md').write_text('正文\n',
                                                    encoding='utf-8')
        entry = self.entry([{'snapshot': 'source/a/page.html'}])
        self.assertEqual(self.preflight(entry), [])

    def test_shared_image_and_dark_light_selection(self):
        # 共享图：两份快照引用同一文件，变化一次即被检出；
        # api 家族暗版不参与身份
        (self.root / 'source/shared').mkdir(parents=True)
        (self.root / 'source/shared/shared.png').write_bytes(b'shared')
        self.write_snapshot('source/a/page.html',
                            '<img src="../shared/shared.png">')
        self.write_snapshot(
            'source/b/page.html',
            '<img src="../shared/shared.png">'
            '<img src="dark.png" class="only-dark">',
            images=[('dark.png', b'dark')])
        (self.root / 'source/merged.md').write_text(
            '![a](../shared/shared.png)\n![b](../shared/shared.png)\n',
            encoding='utf-8')
        entry = self.entry([
            {'snapshot': 'source/a/page.html', 'range': [1, 1]},
            {'snapshot': 'source/b/page.html', 'range': [2, 2]}])
        entry['family'] = 'paginated'
        baseline = self.identity(entry)
        (self.root / 'source/shared/shared.png').write_bytes(b'changed')
        self.assertNotEqual(baseline, self.identity(entry))
        # api 家族暗版图不进入事实
        api_entry = self.entry([{'snapshot': 'source/b/page.html'}])
        api_entry['family'] = 'api'
        facts = delivery_verifier._snapshot_source_facts(
            'api', api_entry['snapshots'],
            lambda rel: str(self.root / rel))
        self.assertEqual([img['source_ref'] for img in facts[0]['images']],
                         ['../shared/shared.png'])

    def test_file_and_dir_alias_contexts(self):
        # 目录符号链接别名 = 同一资源上下文；文件级别名按声明目录区分
        self.write_snapshot('source/real/page.html',
                            '<img src="pic.png" width="20">',
                            images=[('pic.png', b'bytes')])
        md_rel, map_rel = self.parse_page('source/real/page.html',
                                          'source/real/page.md')
        (self.root / 'source/merged.md').write_text(
            (self.root / md_rel).read_text(encoding='utf-8'),
            encoding='utf-8')
        os.symlink(os.path.realpath(self.root / 'source/real'),
                   self.root / 'source/diralias')
        # 目录别名声明：同一上下文，映射核对通过
        alias_entry = self.entry([{'snapshot': 'source/diralias/page.html',
                                   'per_stem_map': map_rel}],
                                 parsed='source/merged.md')
        self.assertEqual(self.preflight(alias_entry), [])
        # 文件级别名从另一目录声明：上下文不同，映射核对拒绝（错上下文）
        (self.root / 'source/other').mkdir()
        os.symlink(os.path.realpath(self.root / 'source/real/page.html'),
                   self.root / 'source/other/page.html')
        file_alias = self.entry([{'snapshot': 'source/other/page.html',
                                  'per_stem_map': map_rel}],
                                parsed='source/merged.md')
        problems = self.preflight(file_alias)
        self.assertTrue(any('错上下文' in p for p in problems), problems)

    # --- per_stem_map 双层声明（§9.4.1） ---

    def test_single_snapshot_legacy_entry_declaration_passes(self):
        snapshots, maps = self.build_two_snapshot_merged()
        # 单快照旧 entry 级声明继续可用（单快照缺省全文，无需 range）
        single = self.entry(
            [{'snapshot': 'source/a/page.html'}],
            parsed='source/a.md', per_stem_map=maps['a'])
        self.assertEqual(self.preflight(single), [])

    def test_two_level_declaration_consistency(self):
        snapshots, maps = self.build_two_snapshot_merged()
        snap_a = {'snapshot': 'source/a/page.html'}
        # 两级指向同一映射：通过
        both_same = self.entry(
            [dict(snap_a, per_stem_map=maps['a'])],
            parsed='source/a.md', per_stem_map=maps['a'])
        self.assertEqual(self.preflight(both_same), [])
        # 两级指向不同映射：歧义拒绝。两份映射都必须各自对快照 a 有效
        # （同一快照重复解析到不同输出），避免被错源门禁先行偶然拒绝
        _, map_a2 = self.parse_page('source/a/page.html', 'source/a2.md')
        both_diff = self.entry(
            [dict(snap_a, per_stem_map=map_a2)],
            parsed='source/a.md', per_stem_map=maps['a'])
        problems = self.preflight(both_diff)
        self.assertTrue(any('两级 per_stem_map 声明不一致' in p
                            for p in problems), problems)

    def test_multi_snapshot_entry_map_binds_matching_snapshot_only(self):
        snapshots, maps = self.build_two_snapshot_merged()
        # entry 级旧声明（记录来源为 b）只归属 b；有图的 a 缺证明仍拒绝
        entry = self.entry(snapshots, per_stem_map=maps['b'])
        problems = self.preflight(entry)
        self.assertTrue(any('未关联解析期映射' in p and '快照 #1' in p
                            for p in problems), problems)
        # 补上 a 的快照级声明后通过
        entry['snapshots'][0] = dict(snapshots[0], per_stem_map=maps['a'])
        self.assertEqual(self.preflight(entry), [])

    def test_entry_map_matching_no_snapshot_rejected(self):
        snapshots, maps = self.build_two_snapshot_merged()
        # 把 b 的映射记录篡改为指向不存在的来源：无法归属任何声明快照
        map_path = self.root / maps['b']
        payload = json.loads(map_path.read_text(encoding='utf-8'))
        payload['snapshot'] = str(self.root / 'source/elsewhere/page.html')
        map_path.write_text(json.dumps(payload), encoding='utf-8')
        entry = self.entry(snapshots, per_stem_map=maps['b'])
        problems = self.preflight(entry)
        self.assertTrue(any('无法对应唯一声明快照' in p for p in problems),
                        problems)

    def test_wrong_snapshot_and_context_rejected(self):
        snapshots, maps = self.build_two_snapshot_merged()
        snap_a = {'snapshot': 'source/a/page.html'}
        # 错源：把 b 的映射声明到 a
        wrong_source = self.entry(
            [dict(snap_a, per_stem_map=maps['b']),
             dict(snapshots[1], per_stem_map=maps['b'])],
            per_stem_map=None)
        problems = self.preflight(wrong_source)
        self.assertTrue(any('不符（错源/版本错配）' in p for p in problems),
                        problems)
        # 错摘要：快照内容变化后映射记录版本错配
        page = self.root / 'source/a/page.html'
        backup = page.read_bytes()
        page.write_text('<html><body><article><h1>A</h1>'
                        '<img src="pic.png" width="24">'
                        '</article></body></html>', encoding='utf-8')
        try:
            stale = self.entry(
                [dict(snap_a, per_stem_map=maps['a'])],
                parsed='source/a.md')
            problems = self.preflight(stale)
            self.assertTrue(any('快照摘要与当前快照不符' in p
                                for p in problems), problems)
        finally:
            page.write_bytes(backup)
        # 错上下文：映射记录的资源上下文与声明快照目录不符
        map_path = self.root / maps['a']
        payload = json.loads(map_path.read_text(encoding='utf-8'))
        payload['resource_base'] = str(self.root / 'source/b')
        map_path.write_text(json.dumps(payload), encoding='utf-8')
        try:
            wrong_context = self.entry(
                [dict(snap_a, per_stem_map=maps['a'])],
                parsed='source/a.md')
            problems = self.preflight(wrong_context)
            self.assertTrue(any('错上下文' in p for p in problems), problems)
        finally:
            self.parse_page('source/a/page.html', 'source/a.md')

    def test_binding_invalidates_on_middle_snapshot_image_change(self):
        # 语义/源对账 binding 覆盖逐快照资源：中间快照换图旧复核失效
        snapshots, maps = self.build_two_snapshot_merged()
        chapter = self.root / '01_章.md'
        chapter.write_text('# 第 1 章\n\n正文。\n', encoding='utf-8')
        entry = self.entry(
            [dict(snapshots[0], per_stem_map=maps['a']),
             dict(snapshots[1], per_stem_map=maps['b'])],
            covers=['01_章.md'])
        problems = []
        entries = delivery_verifier.check_source_chains(
            str(self.root), self.record(entry), problems)
        self.assertEqual(problems, [])
        record = {'mode': 'translation', 'inputs': ['01_章.md'],
                  'outputs': [], 'sources': [entry], 'reviews': []}
        identity = delivery_verifier.compute_delivery_identity(
            str(self.root), record, entries)
        input_checks = {str(chapter.resolve()): [{
            'order': 1, 'tool': 'verify_translation',
            'script_sha256': sha(SCRIPTS / 'verify_translation.py'),
            'shared_deps': {
                name: sha(SCRIPTS / name)
                for name in delivery_verifier.CHECK_SHARED_DEPS[
                    'verify_translation']},
            'facts': {
                'script_sha256': sha(SCRIPTS / 'verify_translation.py'),
                'shared_deps': {
                    name: sha(SCRIPTS / name)
                    for name in delivery_verifier.CHECK_SHARED_DEPS[
                        'verify_translation']},
                'params': {'strong_tokens': [], 'official': [],
                           'approved_extra_math': [], 'fragment': False},
                'files': {'translated': [str(chapter.resolve()),
                                         sha(chapter)],
                          'sources': []},
            },
        }]}
        binding = delivery_verifier.expected_review_binding(
            'semantic', '01_章.md', str(self.root), record, entries,
            input_checks, {}, identity)
        self.assertIsNotNone(binding)
        pic = self.root / 'source/b/pic.png'
        backup = pic.read_bytes()
        pic.write_bytes(b'CHANGED')
        try:
            entries = delivery_verifier.check_source_chains(
                str(self.root), self.record(entry), [])
            fresh = delivery_verifier.compute_delivery_identity(
                str(self.root), record, entries)
            new_binding = delivery_verifier.expected_review_binding(
                'semantic', '01_章.md', str(self.root), record, entries,
                input_checks, {}, fresh)
            self.assertNotEqual(binding, new_binding)
        finally:
            pic.write_bytes(backup)
        # 正常对照：未变输入 binding 稳定
        entries = delivery_verifier.check_source_chains(
            str(self.root), self.record(entry), [])
        same = delivery_verifier.expected_review_binding(
            'semantic', '01_章.md', str(self.root), record, entries,
            input_checks, {},
            delivery_verifier.compute_delivery_identity(
                str(self.root), record, entries))
        self.assertEqual(binding, same)


class RootLayoutUnitTest(unittest.TestCase):
    """目录允许清单、映射布局与身份的单元验收（最小输入，无浏览器）。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='layout-unit-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        (self.root / 'export').mkdir(parents=True)
        (self.root / '01_章.md').write_text('# 第 1 章\n', encoding='utf-8')
        (self.root / 'export/images_display.json').write_text(
            '{"version": 1, "entries": [], "undetermined": []}',
            encoding='utf-8')
        self.record = {
            'version': 1,
            'mode': 'translation',
            'delivery_root': str(self.root),
            'inputs': ['01_章.md'], 'outputs': [],
            'images_display': 'export/images_display.json',
            'checks': [], 'reviews': [],
            'files': {'01_章.md': 'chapter'},
        }

    def run_layout(self, record=None):
        problems = []
        delivery_verifier.check_root_layout(
            self.root, record or self.record, problems)
        delivery_verifier.check_map_entries(
            self.root, record or self.record, problems)
        delivery_verifier.check_identities(
            self.root, record or self.record, problems)
        return problems

    def test_minimal_layout_passes(self):
        self.assertEqual(self.run_layout(), [])

    def test_extra_and_hidden_files_rejected(self):
        (self.root / 'notes.txt').write_text('额外\n', encoding='utf-8')
        problems = self.run_layout()
        self.assertTrue(any('未登记文件' in p and 'notes.txt' in p
                            for p in problems), problems)
        (self.root / '.secret.md').write_text('隐藏\n', encoding='utf-8')
        problems = self.run_layout()
        self.assertTrue(any('.secret.md' in p for p in problems), problems)

    def test_rename_impersonation_rejected(self):
        record = dict(self.record)
        record['files'] = {'01_章.md': 'chapter', '伪装说明.txt': 'user-note'}
        (self.root / '伪装说明.txt').write_text('x\n', encoding='utf-8')
        problems = self.run_layout(record)
        self.assertTrue(any('形态不符' in p for p in problems), problems)

    def test_chapter_not_in_inputs_rejected(self):
        (self.root / '内部笔记.md').write_text('内部\n', encoding='utf-8')
        record = dict(self.record)
        record['files'] = {'01_章.md': 'chapter', '内部笔记.md': 'chapter'}
        problems = self.run_layout(record)
        self.assertTrue(any('不属于本次输入清单' in p for p in problems),
                        problems)

    def test_map_entry_unresolvable_rejected(self):
        (self.root / 'export/images_display.json').write_text(
            '{"version": 1, "entries": ['
            '{"markdown": "../01_章.md", "occurrence": 1, '
            '"image": "../images/gone.png"}], "undetermined": []}',
            encoding='utf-8')
        problems = self.run_layout()
        self.assertTrue(any('无法按映射目录解析' in p for p in problems),
                        problems)

    def test_root_map_copy_rejected(self):
        (self.root / 'images_display.json').write_text('{}', encoding='utf-8')
        problems = self.run_layout()
        self.assertTrue(any('映射副本' in p for p in problems), problems)

    def test_map_location_contract(self):
        # R7/§9.3 位置合同：词法规范化后必须是 export/images_display.json；
        # ./ 等价写法与指向该位置的正确绝对路径允许
        record = dict(self.record)
        record['images_display'] = './export/images_display.json'
        self.assertEqual(self.run_layout(record), [])
        record = dict(self.record)
        record['images_display'] = str(
            self.root / 'export/images_display.json')
        self.assertEqual(self.run_layout(record), [])

    def test_map_wrong_locations_rejected(self):
        # 错位置案例本身的 JSON 有效、条目可解析，拒绝必须来自位置门禁
        valid = '{"version": 1, "entries": [], "undetermined": []}'
        for rel in ('other', 'docs/archive'):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
            (self.root / rel / 'images_display.json').write_text(
                valid, encoding='utf-8')
            record = dict(self.record)
            record['images_display'] = '%s/images_display.json' % rel
            problems = self.run_layout(record)
            self.assertTrue(
                any('必须位于 export/images_display.json' in p
                    for p in problems), (rel, problems))
        # 根目录副本声明为映射同样拒绝
        (self.root / 'images_display.json').write_text(valid,
                                                       encoding='utf-8')
        record = dict(self.record)
        record['images_display'] = 'images_display.json'
        problems = self.run_layout(record)
        self.assertTrue(
            any('必须位于 export/images_display.json' in p
                for p in problems), problems)

    def test_map_location_symlink_alias_rejected(self):
        # 其他位置指向同一 realpath 的目录别名不等于获准位置（词法合同）
        os.symlink(str(self.root / 'export'), self.root / 'alias')
        record = dict(self.record)
        record['images_display'] = 'alias/images_display.json'
        problems = self.run_layout(record)
        self.assertTrue(
            any('必须位于 export/images_display.json' in p
                for p in problems), problems)

    def test_no_image_no_map_declaration_passes(self):
        # 无图免映射：未声明映射且根目录无副本时不产生布局问题
        record = dict(self.record)
        del record['images_display']
        self.assertEqual(self.run_layout(record), [])

    def test_output_digest_tamper_rejected(self):
        (self.root / 'book.pdf').write_bytes(b'PDF')
        record = dict(self.record)
        record['outputs'] = [{'path': 'book.pdf', 'sha256': '0' * 64}]
        problems = self.run_layout(record)
        self.assertTrue(any('输出摘要不符' in p for p in problems), problems)

    def test_evidence_dir_under_temp_root_rejected(self):
        with tempfile.TemporaryDirectory(prefix='ev-') as tmp:
            with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
                delivery_verifier.ensure_persistent(tmp)
            self.assertIn('系统临时根', str(ctx.exception))

    def test_record_inside_delivery_root_rejected(self):
        (self.root / 'record.json').write_text('{}', encoding='utf-8')
        problems = self.run_layout()
        self.assertTrue(any('record.json' in p for p in problems), problems)

    def test_preflight_failure_skips_rerun(self):
        # 预检失败即停止：核验复跑不执行——记录里放一个必然失败的检查
        # （源缺失），若复跑被执行会追加“复验失败”；提前返回时不会出现。
        (self.root / 'notes.txt').write_text('额外\n', encoding='utf-8')
        record = dict(self.record)
        record['checks'] = [{'tool': 'verify_translation',
                             'args': ['01_章.md', 'docs/missing.md']}]
        record_path = self.base / 'record.json'
        record_path.write_text(json.dumps(record), encoding='utf-8')
        evidence = Path(os.path.expanduser(
            '~/.cache/tech-doc-evidence-unit-%s' % uuid.uuid4().hex[:8]))
        self.addCleanup(shutil.rmtree, evidence, True)
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            rc = delivery_verifier.main(
                ['--record', str(record_path), '--evidence-dir', str(evidence)])
        self.assertEqual(rc, 1)
        self.assertIn('未登记文件', err.getvalue())
        self.assertNotIn('复验失败', err.getvalue())
        self.assertFalse((evidence / 'delivery_index.json').exists())


class MapParamConsistencyTest(unittest.TestCase):
    """核验实际参数所用映射须为记录声明的同一交付映射（R7/§9.3）。

    负例纯规则：不一致在复验前拒绝（无浏览器）；正例由
    DeliveryEvidenceTest 的真实链路覆盖（记录与参数一致才通过）。
    """

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='map-param-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        for d in ('work', 'export', 'other'):
            (self.root / d).mkdir(parents=True)
        (self.root / 'parsed.md').write_text('# T\n', encoding='utf-8')
        (self.root / 'book.pdf').write_bytes(b'placeholder')
        (self.root / 'work/export_report.json').write_text(
            '{}', encoding='utf-8')
        valid = '{"version": 1, "entries": [], "undetermined": []}'
        (self.root / 'export/images_display.json').write_text(
            valid, encoding='utf-8')
        (self.root / 'other/images_display.json').write_text(
            valid, encoding='utf-8')

    def record(self, check_map='export/images_display.json',
               declared='export/images_display.json'):
        record = {
            'version': 1, 'mode': 'pdf', 'delivery_root': str(self.root),
            'inputs': ['parsed.md'],
            'outputs': [{'path': 'book.pdf'}],
            'checks': [{'tool': 'verify_pdf',
                        'args': ['--pdf', 'book.pdf', '--work-dir', 'work',
                                 'parsed.md']}],
            'reviews': [],
        }
        if declared:
            record['images_display'] = declared
        if check_map:
            self.map_args = ['--images-display', check_map]
            record['checks'][0]['args'] = (
                ['--pdf', 'book.pdf', '--work-dir', 'work']
                + self.map_args + ['parsed.md'])
        return record

    def rerun(self, record):
        problems = []
        delivery_verifier.rerun_checks(str(self.root), record, problems)
        return problems

    def test_check_binds_other_map_rejected(self):
        problems = self.rerun(self.record(
            check_map='other/images_display.json'))
        self.assertTrue(any('与交付记录声明的交付级映射不一致' in p
                            for p in problems), problems)
        # 拒绝发生在复验之前（不是核验门禁偶然失败）
        self.assertFalse(any('复验失败' in p for p in problems), problems)

    def test_check_not_binding_declared_map_rejected(self):
        problems = self.rerun(self.record(check_map=None))
        self.assertTrue(any('与交付记录声明的交付级映射不一致' in p
                            for p in problems), problems)

    def test_check_binds_undeclared_map_rejected(self):
        problems = self.rerun(self.record(declared=None))
        self.assertTrue(any('与交付记录声明的交付级映射不一致' in p
                            for p in problems), problems)

    def test_equivalent_absolute_spelling_same_facts(self):
        # 等价写法（相对/绝对）经真实 CLI 解析得到同一规范化文件依赖，
        # 一致性核对按语义事实比较，不制造字符串口径
        root_abs = str(self.root.resolve())
        relative, _p = delivery_verifier._check_facts(
            root_abs, 'verify_pdf',
            ['--pdf', 'book.pdf', '--work-dir', 'work',
             '--images-display', 'export/images_display.json', 'parsed.md'],
            1)
        absolute, _p = delivery_verifier._check_facts(
            root_abs, 'verify_pdf',
            ['--pdf', 'book.pdf', '--work-dir', 'work',
             '--images-display',
             str(self.root / 'export/images_display.json'), 'parsed.md'],
            1)
        self.assertEqual(relative['files']['images_display'],
                         absolute['files']['images_display'])
        declared_real = os.path.realpath(
            str(self.root / 'export/images_display.json'))
        self.assertEqual({p for p, _d in absolute['files']['images_display']},
                         {declared_real})


class ToolArgInterpretationTest(unittest.TestCase):
    """参数单源：真实 CLI 与交付入口对已支持写法作同一解释（纯规则）。"""

    def test_pdf_equals_form_and_bool_adjacent_positional(self):
        ns = pdf_verifier.parse_args(
            ['--pdf=book.pdf', '--work-dir', 'w', '--toc-sections', 'a.md'])
        self.assertEqual(ns.pdf, 'book.pdf')
        self.assertTrue(ns.toc_sections)
        self.assertEqual(ns.inputs, ['a.md'])

    def test_pdf_missing_value_is_parse_error(self):
        with self.assertRaises(SystemExit):
            pdf_verifier.parse_args(['--pdf'])

    def test_delivery_parse_dispatch_four_families(self):
        problems = []
        cases = {
            'verify_translation': (
                ['01_章.md', 'docs/src.md', '--strong-token', '第 1 章'],
                '01_章.md'),
            'verify_paginated_translation': (
                ['merged.md', 'p1.md', 'p2.md'], 'merged.md'),
            'verify_reference_translation': (
                ['ref.md', 'src.md', 'token with space'], 'ref.md'),
            'verify_api_translation': (
                ['merged.md', 'manifest.txt', 'toc.txt', 'site/',
                 'p1.md', 'p2.md'], 'merged.md'),
        }
        for tool, (args, translated) in cases.items():
            with self.subTest(tool=tool):
                parsed = delivery_verifier._parse_tool_args(
                    tool, args, problems, 1)
                self.assertEqual(problems, [])
                self.assertIsNotNone(parsed)
                key = delivery_verifier.TRANSLATED_PATH_KEYS[tool]
                self.assertEqual(parsed[key], translated)
        # 字面值保留原文语义：官方标题/含空格 token 不被改写
        parsed = delivery_verifier._parse_tool_args(
            'verify_translation',
            ['01_章.md', 'docs/src.md', '--strong-token', '第 1 章',
             '--approved-extra-math', 'a b'], problems, 1)
        self.assertEqual(parsed['strong_tokens'], ['第 1 章'])
        self.assertEqual(parsed['approved_extra_math'], ['a b'])
        self.assertEqual(parsed['official'], [])

    def test_delivery_parse_rejects_malformed_args(self):
        problems = []
        parsed = delivery_verifier._parse_tool_args(
            'verify_translation', ['only-one-path'], problems, 3)
        self.assertIsNone(parsed)
        self.assertTrue(any('真实 CLI 解析' in p for p in problems))
        problems.clear()
        parsed = delivery_verifier._parse_tool_args(
            'verify_pdf', ['--pdf'], problems, 4)
        self.assertIsNone(parsed)
        self.assertTrue(any('真实 CLI 解析' in p for p in problems))


class MultiPdfDeliveryTest(unittest.TestCase):
    """多 PDF 分篇交付（设计 §9.6 首轮复审 P2 固定回归，真实 Chromium）。

    每份 PDF 核验报告绑定自己实际核验的输入（逐检查范围一致），全体
    PDF 核验并集覆盖全部交付输入；漏覆盖与覆盖记录外输入各自拒绝；
    合法分篇交付端到端通过并发布。
    """

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='multi-pdf-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        self.root.mkdir()
        # 证据根放在系统临时根之外（$HOME/.cache 下），模拟持久位置
        self.evidence = Path(os.path.expanduser(
            '~/.cache/tech-doc-evidence-%s' % uuid.uuid4().hex[:8]))
        self.addCleanup(shutil.rmtree, self.evidence, True)
        for name in ('a', 'b'):
            (self.root / ('%s.md' % name)).write_text(
                '# %s 篇\n\n'
                '> **来源**：https://example.com/%s\n'
                '> **抓取日期**：2026-09-15\n\n'
                '%s 篇正文。\n' % (name, name, name), encoding='utf-8')
            work = self.root / ('work-%s' % name)
            work.mkdir()
            result = exporter.export(
                [str(self.root / ('%s.md' % name))],
                Path(self.root / ('%s.pdf' % name)), work)
            assert result == 0

    def checks(self, names=('a', 'b')):
        return [{'tool': 'verify_pdf',
                 'args': ['--pdf', '%s.pdf' % name,
                          '--work-dir', str(self.root / ('work-%s' % name)),
                          '%s.md' % name]}
                for name in names]

    def record(self, checks=None, inputs=('a.md', 'b.md')):
        return {
            'version': 1, 'mode': 'pdf',
            'delivery_root': str(self.root),
            'inputs': list(inputs),
            'outputs': [{'path': 'a.pdf',
                         'sha256': sha(self.root / 'a.pdf')},
                        {'path': 'b.pdf',
                         'sha256': sha(self.root / 'b.pdf')}],
            'files': {'a.md': 'chapter', 'b.md': 'chapter',
                      'a.pdf': 'pdf', 'b.pdf': 'pdf'},
            'sources': [],
            'checks': checks if checks is not None else self.checks(),
        }

    def visual_review(self, name, record, contexts):
        ns = pdf_verifier.parse_args(
            ['--pdf', str(self.root / ('%s.pdf' % name)),
             '--work-dir', str(self.root / ('work-%s' % name)),
             str(self.root / ('%s.md' % name))])
        ok, report = pdf_verifier.run_verification(ns)
        assert ok, report['failures']
        items = [delivery_verifier.review_item_label(
                     item, 'relaxed_matches', index)
                 for index, item in enumerate(
                     report.get('relaxed_matches', []))
                 if item.get('review', True)]
        return {'kind': 'visual', 'target': '%s.pdf' % name,
                'status': 'closed',
                'sha256': sha(self.root / ('%s.pdf' % name)),
                'items': items,
                'binding': expected_binding('visual', '%s.pdf' % name,
                                            self.root, record, contexts),
                'note': '%s 全页视觉复核闭合（逐项见 items）' % name}

    def run_delivery(self, record):
        record_path = self.base / 'record.json'  # 交付根之外
        record_path.write_text(json.dumps(record, ensure_ascii=False,
                                          indent=2), encoding='utf-8')
        return subprocess.run(
            [sys.executable, str(SCRIPTS / 'verify_delivery.py'),
             '--record', str(record_path),
             '--evidence-dir', str(self.evidence)],
            capture_output=True, text=True)

    def test_legitimate_split_delivery_publishes(self):
        # 复审探针：a.md→a.pdf、b.md→b.pdf 各自导出与独立核验均通过，
        # 联合交付曾被“报告输入必须等于整个记录输入”误拒
        record = self.record()
        contexts = delivery_contexts(str(self.root), record)
        record['reviews'] = [self.visual_review('a', record, contexts),
                             self.visual_review('b', record, contexts)]
        result = self.run_delivery(record)
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)
        index = json.loads((self.evidence / 'delivery_index.json')
                           .read_text(encoding='utf-8'))
        self.assertEqual(index['mode'], 'pdf')
        self.assertEqual([check['exit_code'] for check in index['checks']],
                         [0, 0])

    def test_uncovered_record_input_rejected(self):
        # 并集覆盖门禁：b.md 没有任何 PDF 核验实际覆盖
        record = self.record(checks=self.checks(('a',)))
        problems = []
        delivery_verifier.rerun_checks(str(self.root), record, problems)
        self.assertTrue(any('b.md' in p and '未被任何 PDF 核验覆盖' in p
                            for p in problems), problems)

    def test_out_of_record_coverage_rejected(self):
        # 检查覆盖交付记录之外的输入：不能以额外范围冒充本交付核验
        record = self.record(inputs=('a.md',))
        record['checks'] = self.checks(('a', 'b'))
        problems = []
        delivery_verifier.rerun_checks(str(self.root), record, problems)
        self.assertTrue(any('覆盖了交付记录之外的输入' in p
                            for p in problems), problems)


class MapMigrationAcceptanceTest(unittest.TestCase):
    """受控验收副本按设计 §4.8 做一次实际目录整理（真实 Chromium）。

    旧版交付（映射在交付根、独立导出沿用旧位置）迁移到
    export/images_display.json：整理前后逐次来源/交付身份、宽度与未
    确定原因相同；Markdown 与原图字节不变；原有归档不串用；连续两次
    回补写新位置且幂等；真实 Chromium 导出及独立 PDF 内容流核验显示
    宽度不退化。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='map-migration-'))
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        cls.root = cls.base / 'delivery'
        cls.root.mkdir(parents=True)
        cls.snapshot = cls.root / 'source/page.html'
        cls.snapshot.parent.mkdir(parents=True)
        cls.snapshot.write_text(
            '<html><body><article>'
            '<h1>Chapter 1</h1>'
            '<p>Example body.</p>'
            '<figure><img src="images/pic.png" style="width: 300px">'
            '</figure>'
            '<p>End.</p>'
            '</article></body></html>', encoding='utf-8')
        make_png(cls.root / 'source/images/pic.png', 400, 200)
        make_png(cls.root / 'images/pic.png', 400, 200)
        cls.chapter = cls.root / '01_章.md'
        cls.chapter.write_text(
            '# 第 1 章\n\n'
            '> **来源**：https://docs.nvidia.com/cuda/example.html\n'
            '> **抓取日期**：2026-09-20\n\n'
            '示例正文。\n\n![图](images/pic.png)\n\n正文结束。\n',
            encoding='utf-8')
        parse = subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_single_page_html.py'),
             str(cls.snapshot), str(cls.root / 'source/source_en.md')],
            capture_output=True, text=True)
        assert parse.returncode == 0, parse.stderr
        cls.manifest = cls.base / 'manifest.json'
        cls.manifest.write_text(json.dumps({
            'version': 1, 'source_version': '13.4-test', 'family': 'single',
            'pages': [{'snapshot': str(cls.snapshot),
                       'markdown': str(cls.chapter)}]}), encoding='utf-8')
        # 旧布局：映射在交付根（独立导出旧发现行为的既定用法）
        cls.rebuild(cls.root / 'images_display.json')
        cls.old_map = cls.root / 'images_display.json'
        # 原有归档副本：整理前后必须保持字节不变、不被串用
        cls.archive = cls.root / 'archive'
        cls.archive.mkdir()
        shutil.copyfile(cls.old_map, cls.archive / 'images_display.json')

    @classmethod
    def rebuild(cls, output):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'rebuild_images_display.py'),
             '--manifest', str(cls.manifest), '--output', str(output),
             '--work-dir', str(cls.base / ('rebuild-%s' % uuid.uuid4().hex[:6]))],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    def export_pdf(self, map_path, name, strict=True):
        pdf = self.base / ('%s.pdf' % name)
        work = self.base / ('work-%s' % name)
        work.mkdir(exist_ok=True)
        result = exporter.export(
            [str(self.chapter)], Path(pdf), Path(work),
            images_display_paths=[str(map_path)],
            require_display_map=strict)
        self.assertEqual(result, 0)
        report = json.loads(
            (work / pdf_verifier.REPORT_NAME).read_text(encoding='utf-8'))
        self.assertEqual(report.get('status'), exporter.STATUS_MACHINE_PASS,
                         json.dumps(report, ensure_ascii=False)[:800])
        return pdf, work, report

    def verify_pdf_ok(self, pdf, work, map_path):
        ns = pdf_verifier.parse_args(
            ['--pdf', str(pdf), '--work-dir', str(work),
             '--images-display', str(map_path),
             '--require-display-map', str(self.chapter)])
        ok, report = pdf_verifier.run_verification(ns)
        self.assertTrue(ok, json.dumps(report.get('failures'),
                                       ensure_ascii=False)[:800])
        return report

    def drawn_widths(self, pdf):
        facts = pdf_verifier.PdfFacts(pdf)
        return [width for page in pdf_verifier.collect_drawn_images(facts)
                for width, _bottom, _top in page]

    @staticmethod
    def entry_semantics(payload):
        """逐次来源/交付身份、宽度与未确定原因（不含位置路径）。"""
        determined = [
            (item['occurrence'], item['sha256'], item['width'],
             json.dumps(item.get('source'), sort_keys=True,
                        ensure_ascii=False))
            for item in payload.get('entries', [])]
        undetermined = [
            (item['occurrence'], item['reason'],
             json.dumps(item.get('source'), sort_keys=True,
                        ensure_ascii=False))
            for item in payload.get('undetermined', [])]
        return determined, undetermined

    def test_migration_preserves_identity_and_widths(self):
        payload_old = json.loads(self.old_map.read_text(encoding='utf-8'))
        semantics_old = self.entry_semantics(payload_old)
        self.assertTrue(semantics_old[0] or semantics_old[1],
                        '旧布局映射须有图片条目')
        markdown_sha = sha(self.chapter)
        image_sha = sha(self.root / 'images/pic.png')
        archive_sha = sha(self.archive / 'images_display.json')
        # 整理前基线：旧位置映射的真实导出与独立核验
        pdf_old, work_old, report_old = self.export_pdf(self.old_map,
                                                        'book-old')
        self.verify_pdf_ok(pdf_old, work_old, self.old_map)
        widths_old = self.drawn_widths(pdf_old)
        self.assertTrue(widths_old)
        # §4.8：先建候选（改写相对引用到新位置），验证候选后才移除旧映射
        export_dir = self.root / 'export'
        export_dir.mkdir()
        target = export_dir / 'images_display.json'
        self.assertFalse(target.exists(), '目标位置冲突必须停止')
        candidate = json.loads(json.dumps(payload_old))
        for item in (candidate.get('entries', [])
                     + candidate.get('undetermined', [])):
            item['markdown'] = os.path.relpath(
                self.root / item['markdown'], export_dir)
            if item.get('image'):
                item['image'] = os.path.relpath(
                    self.root / item['image'], export_dir)
        staging = export_dir / 'images_display.json.candidate'
        staging.write_text(json.dumps(candidate, ensure_ascii=False),
                           encoding='utf-8')
        # 候选验证：条目按新位置解析命中真实文件，语义与旧映射一致
        loaded = json.loads(staging.read_text(encoding='utf-8'))
        for item in (loaded.get('entries', [])
                     + loaded.get('undetermined', [])):
            for key in ('markdown', 'image'):
                if item.get(key):
                    self.assertTrue(
                        (export_dir / item[key]).is_file(), item[key])
        self.assertEqual(semantics_old, self.entry_semantics(loaded))
        os.replace(staging, target)
        self.old_map.unlink()
        self.assertFalse(self.old_map.exists())
        # Markdown、原图与原有归档字节不变；归档不被串用
        self.assertEqual(sha(self.chapter), markdown_sha)
        self.assertEqual(sha(self.root / 'images/pic.png'), image_sha)
        self.assertEqual(sha(self.archive / 'images_display.json'),
                         archive_sha)
        # 整理后：同一政策再导出，独立核验通过且内容流实测宽度不退化
        pdf_new, work_new, report_new = self.export_pdf(target, 'book-new')
        self.verify_pdf_ok(pdf_new, work_new, target)
        widths_new = self.drawn_widths(pdf_new)
        self.assertEqual(len(widths_old), len(widths_new))
        for before, after in zip(widths_old, widths_new):
            self.assertAlmostEqual(before, after, delta=0.75)
        chapter_key = os.path.realpath(str(self.chapter))
        applied_old = [item['applied_px'] for item in
                       report_old['image_display'][chapter_key]]
        applied_new = [item['applied_px'] for item in
                       report_new['image_display'][chapter_key]]
        self.assertEqual(applied_old, applied_new)
        # 连续两次回补仍写新位置且幂等
        self.rebuild(target)
        first = target.read_bytes()
        self.rebuild(target)
        self.assertEqual(first, target.read_bytes())
        # 交付根布局：新位置通过；旧位置/归档声明被拒；根副本已移除
        record = {
            'version': 1, 'mode': 'translation',
            'delivery_root': str(self.root),
            'inputs': ['01_章.md'], 'outputs': [],
            'images_display': 'export/images_display.json',
            'checks': [], 'reviews': [],
            'files': {'01_章.md': 'chapter'},
        }
        problems = []
        delivery_verifier.check_root_layout(self.root, record, problems)
        self.assertEqual(problems, [], problems)
        for rel in ('images_display.json', 'archive/images_display.json'):
            record['images_display'] = rel
            problems = []
            delivery_verifier.check_root_layout(self.root, record, problems)
            self.assertTrue(
                any('必须位于 export/images_display.json' in p
                    for p in problems), (rel, problems))


class PublishFailureUnitTest(unittest.TestCase):
    """发布只切换索引：失败路径的最小输入验收（不依赖完整交付）。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='publish-unit-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'delivery'
        (self.root / 'export').mkdir(parents=True)
        (self.root / '01_章.md').write_text('# 章\n', encoding='utf-8')
        self.record = {
            'version': 1, 'mode': 'translation',
            'delivery_root': str(self.root),
            'inputs': ['01_章.md'], 'outputs': [],
            'checks': [], 'reviews': [],
        }
        self.evidence = self.base / 'evidence'
        self.evidence.mkdir()
        self.candidates = [{
            'order': 1,
            'entry': {'tool': 'verify_translation', 'args': ['01_章.md'],
                      'exit_code': 0, 'stdout': '', 'stderr': ''},
            'verify_report': None, 'export_report_path': None}]
        self.record_file = self.base / 'record.json'

    def publish_kwargs(self):
        """发布必须提供交付记录路径与装载时摘要（按当前记录内容）。"""
        self.record_file.write_text(json.dumps(self.record), encoding='utf-8')
        return {'record_path': str(self.record_file),
                'record_digest': sha(self.record_file)}

    def test_record_rewrite_during_run_blocks_publish(self):
        # 设计 §4.7：口径身份含交付记录本身——装载时的摘要与发布时不一致
        # （运行中被改写）必须拒绝发布且不产生新索引。
        self.record_file.write_text(json.dumps(self.record), encoding='utf-8')
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
            delivery_verifier.publish_evidence(
                self.evidence, self.record, self.root, self.candidates,
                baseline, record_path=str(self.record_file),
                record_digest='0' * 64)  # 模拟装载时摘要与当前文件不符
        self.assertIn('运行期间被改写', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_identity_change_during_run_blocks_publish(self):
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        # 模拟运行期间输入被改写：发布前复查必须拒绝且不产生新索引
        (self.root / '01_章.md').write_text('# 章被改\n', encoding='utf-8')
        with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
            delivery_verifier.publish_evidence(
                self.evidence, self.record, self.root, self.candidates,
                baseline, **self.publish_kwargs())
        self.assertIn('运行期间变化', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_publish_requires_record_baseline(self):
        # 记录自身摘要检查不可跳过：缺少记录路径/装载摘要直接拒绝
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
            delivery_verifier.publish_evidence(
                self.evidence, self.record, self.root, self.candidates,
                baseline)
        self.assertIn('记录自身摘要检查', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_archived_report_without_baseline_rejected(self):
        # 要归档导出报告但核验前基线没有对应导出报告摘要：口径不一致
        source = self.base / 'export_report.json'
        source.write_text('{}', encoding='utf-8')
        self.candidates[0]['export_report_path'] = str(source)
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
            delivery_verifier.publish_evidence(
                self.evidence, self.record, self.root, self.candidates,
                baseline, **self.publish_kwargs())
        self.assertIn('核验前基线缺少', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_input_change_during_batch_write_blocks_publish(self):
        # 身份复查在批次写入并重读之后、切换索引之前：复制报告期间修改
        # 输入必须拒绝发布，只留下未引用新批次。
        import unittest.mock as mock
        (self.root / 'work').mkdir(exist_ok=True)
        (self.root / 'book.pdf').write_bytes(b'placeholder')
        report = self.root / 'work/export_report.json'
        report.write_text('{}', encoding='utf-8')
        self.record['mode'] = 'translation+pdf'
        self.record['outputs'] = [{'path': 'book.pdf'}]
        self.record['checks'] = [{
            'tool': 'verify_pdf',
            'args': ['--pdf', 'book.pdf', '--work-dir', 'work', '01_章.md']}]
        self.candidates = [{
            'order': 1,
            'entry': {'tool': 'verify_pdf', 'args': ['--pdf', 'book.pdf'],
                      'exit_code': 0},
            'verify_report': None,
            'export_report_path': str(report)}]
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        real_copy = shutil.copyfile

        def tamper(src, dst, *args, **kwargs):
            result = real_copy(src, dst, *args, **kwargs)
            (self.root / '01_章.md').write_text('# 章被改\n', encoding='utf-8')
            return result

        with mock.patch.object(delivery_verifier.shutil, 'copyfile', tamper):
            with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
                delivery_verifier.publish_evidence(
                    self.evidence, self.record, self.root, self.candidates,
                    baseline, **self.publish_kwargs())
        self.assertIn('运行期间变化', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_export_report_must_match_pre_verification_baseline(self):
        # 设计 §9.3：归档导出报告须与核验前基线版本一致——核验后、
        # 复制前替换导出报告（复制内容与当前文件一致不足以放行）。
        (self.root / 'work').mkdir(exist_ok=True)
        (self.root / 'book.pdf').write_bytes(b'placeholder')
        report = self.root / 'work/export_report.json'
        report.write_text('{"policy": 1}', encoding='utf-8')
        self.record['mode'] = 'translation+pdf'
        self.record['outputs'] = [{'path': 'book.pdf'}]
        self.record['checks'] = [{
            'tool': 'verify_pdf',
            'args': ['--pdf', 'book.pdf', '--work-dir', 'work', '01_章.md']}]
        self.candidates = [{
            'order': 1,
            'entry': {'tool': 'verify_pdf', 'args': ['--pdf', 'book.pdf'],
                      'exit_code': 0},
            'verify_report': None,
            'export_report_path': str(report)}]
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        # 正常对照：未篡改时发布成功并写入索引
        index = delivery_verifier.publish_evidence(
            self.evidence, self.record, self.root, self.candidates, baseline,
            **self.publish_kwargs())
        self.assertTrue(Path(index).is_file())
        # 核验后替换导出报告：归档副本与基线不一致，拒绝发布
        self.evidence.joinpath('delivery_index.json').unlink()
        report.write_text('{"policy": 2}', encoding='utf-8')
        with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
            delivery_verifier.publish_evidence(
                self.evidence, self.record, self.root, self.candidates,
                baseline, **self.publish_kwargs())
        self.assertIn('与核验前基线的导出报告版本不一致', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_missing_required_digest_blocks_publish(self):
        # 必需摘要不可得直接失败：不能以 None==None 判相等通过
        (self.root / '01_章.md').unlink()
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        with self.assertRaises(delivery_verifier.DeliveryError) as ctx:
            delivery_verifier.publish_evidence(
                self.evidence, self.record, self.root, self.candidates,
                baseline, **self.publish_kwargs())
        self.assertIn('必需依赖摘要不可得', str(ctx.exception))
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_write_failure_keeps_old_index_untouched(self):
        baseline = delivery_verifier.compute_delivery_identity(
            self.root, self.record, [])
        index = {'version': 1, 'batch': 'batch-old', 'checks': [
            {'report': 'batch-old/01_verify_report.json'}]}
        (self.evidence / 'batch-old').mkdir()
        (self.evidence / 'batch-old' / '01_verify_report.json').write_text(
            '{}', encoding='utf-8')
        (self.evidence / 'delivery_index.json').write_text(
            json.dumps(index), encoding='utf-8')
        before = {
            p.relative_to(self.evidence).as_posix(): sha(p)
            for p in self.evidence.rglob('*') if p.is_file()}
        # 批次写入失败：证据目录只读
        os.chmod(self.evidence, 0o500)
        try:
            with self.assertRaises((delivery_verifier.DeliveryError, OSError)):
                delivery_verifier.publish_evidence(
                    self.evidence, self.record, self.root, self.candidates,
                    baseline, **self.publish_kwargs())
        finally:
            os.chmod(self.evidence, 0o700)
        after = {
            p.relative_to(self.evidence).as_posix(): sha(p)
            for p in self.evidence.rglob('*') if p.is_file()}
        self.assertEqual(before, after)  # 旧索引与全部引用文件摘要不变


class DeliveryEvidenceTest(unittest.TestCase):
    """A11/A12/A17–A19 及 03 精简验收（复用只读基样，逐测试独立副本）。"""

    @classmethod
    def setUpClass(cls):
        cls.pristine = Path(tempfile.mkdtemp(prefix='delivery-pristine-'))
        cls.strict_pristine = Path(tempfile.mkdtemp(prefix='delivery-strict-'))
        build_delivery(cls.pristine)
        build_delivery(cls.strict_pristine, require_strict=True)
        for tree in (cls.pristine, cls.strict_pristine):
            (tree / '00_目录.md').write_text(
                '# 目录\n\n译自：https://example.com/pv-delivery\n\n'
                '- [第 1 章](01_章.md)\n', encoding='utf-8')
            (tree / '术语表.md').write_text(
                '# 术语表\n\n| k | v |\n|---|---|\n', encoding='utf-8')
            (tree / '导出前准备说明.md').write_text('说明\n', encoding='utf-8')
            (tree / 'PDF导出交付说明.md').write_text('说明\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.pristine, True)
        shutil.rmtree(cls.strict_pristine, True)

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='delivery-root-'))
        self.root = self.base / 'delivery'
        shutil.copytree(self.pristine, self.root)
        retarget_tree_json(self.root, self.pristine, self.root)
        # 证据根放在系统临时根之外（$HOME/.cache 下），模拟持久位置
        self.evidence = Path(os.path.expanduser(
            '~/.cache/tech-doc-evidence-%s' % uuid.uuid4().hex[:8]))
        self.pdf = self.root / 'book.pdf'
        self.addCleanup(shutil.rmtree, self.base, True)
        self.addCleanup(shutil.rmtree, self.evidence, True)

    def use_strict_fixture(self):
        shutil.rmtree(self.root)
        shutil.copytree(self.strict_pristine, self.root)
        retarget_tree_json(self.root, self.strict_pristine, self.root)

    def write_record(self, record):
        path = self.base / 'record.json'  # 交付根之外
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                        encoding='utf-8')
        return str(path)

    def run_delivery(self, record):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / 'verify_delivery.py'),
             '--record', self.write_record(record),
             '--evidence-dir', str(self.evidence)],
            capture_output=True, text=True)

    def test_compliant_delivery_publishes_batch_index(self):
        result = self.run_delivery(base_record(self.root, self.pdf))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        index = json.loads(
            (self.evidence / 'delivery_index.json').read_text(encoding='utf-8'))
        self.assertEqual(index['mode'], 'translation+pdf')
        self.assertEqual(index['outputs'][0]['sha256'], sha(self.pdf))
        self.assertEqual(index['checks'][0]['exit_code'], 0)
        # 索引引用相对证据目录的批次文件，逐一可读且摘要一致
        self.assertTrue(index['batch'])
        for check in index['checks']:
            for key in ('report', 'export_report'):
                rel = check.get(key)
                if not rel:
                    continue
                target = self.evidence / rel
                self.assertTrue(target.is_file(), rel)
                self.assertEqual(sha(target), check['%s_sha256' % key])

    def test_success_survives_candidate_workdir_cleanup(self):
        # 成功后清理临时候选（导出工作目录），索引引用仍可回查
        self.assertEqual(
            self.run_delivery(base_record(self.root, self.pdf)).returncode, 0)
        index = json.loads(
            (self.evidence / 'delivery_index.json').read_text(encoding='utf-8'))
        shutil.rmtree(self.root / 'work')
        for check in index['checks']:
            rel = check.get('report') or check.get('export_report')
            if rel:
                self.assertTrue((self.evidence / rel).is_file(), rel)
        self.assertEqual(sha(self.root / 'book.pdf'),
                         index['outputs'][0]['sha256'])

    def test_source_chain_preflight_rejections(self):
        """源链预检负例：缺快照、选区不存在、版本错配、有图缺两级映射。"""
        def run_with(mutate):
            record = base_record(self.root, self.pdf)
            mutate(record)
            return self.run_delivery(record)

        # 缺原 HTML：快照删除即拒绝，不用最新版替代
        snapshot = self.root / 'source/page.html'
        backup = snapshot.read_bytes()
        snapshot.unlink()
        result = run_with(lambda record: None)
        snapshot.write_bytes(backup)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('快照缺失', result.stderr)

        # 指定选区不存在
        def wrong_section(record):
            record['sources'][0]['snapshots'][0]['section_id'] = 'no-such-id'
        result = run_with(wrong_section)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('选区在快照中不存在', result.stderr)

        # per-stem 映射快照摘要与当前快照不符（版本错配）
        def stale_per_stem(record):
            payload = json.loads((self.root / 'source/source_en.images_display.json')
                                 .read_text(encoding='utf-8'))
            payload['snapshot_sha256'] = '0' * 64
            (self.root / 'source/source_en.images_display.json').write_text(
                json.dumps(payload), encoding='utf-8')
        result = run_with(stale_per_stem)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('快照摘要与当前快照不符', result.stderr)
        # 还原（重新解析生成一致映射）
        subprocess.run([sys.executable, str(SCRIPTS / 'parse_single_page_html.py'),
                        str(self.root / 'source/page.html'),
                        str(self.root / 'source/source_en.md')],
                       capture_output=True, check=True)

        # 有图译文未关联解析期映射（两级映射）
        def no_per_stem(record):
            record['sources'][0]['per_stem_map'] = None
        result = run_with(no_per_stem)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未关联解析期映射', result.stderr)

        # S4：实际图片存在而交付记录未声明交付级映射——两级映射要求由
        # 实际图片出现决定，不能因未声明而免检
        def no_delivery_map(record):
            record['images_display'] = None
        result = run_with(no_delivery_map)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未声明交付级映射', result.stderr)

        # S4：交付映射漏项——条目数少于实际图片出现数（预检口径）
        record = base_record(self.root, self.pdf)  # 映射完好时构建
        map_path = self.root / 'export/images_display.json'
        backup_map = map_path.read_bytes()
        payload = json.loads(map_path.read_text(encoding='utf-8'))
        payload['entries'] = []
        map_path.write_text(json.dumps(payload), encoding='utf-8')
        problems = []
        delivery_verifier.check_source_chains(str(self.root), record, problems)
        map_path.write_bytes(backup_map)
        self.assertTrue(any('映射漏项' in p for p in problems), problems)

        # 漏关联：covers 缺交付输入
        def missing_cover(record):
            record['sources'][0]['covers'] = []
        result = run_with(missing_cover)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('缺少源链关联', result.stderr)

    def test_empty_checks_clean_failure_not_crash(self):
        # 空 checks：清晰失败（同一返回合同），不抛解包异常
        record = base_record(self.root, self.pdf)
        record['checks'] = []
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checks 为空', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_binding_change_requires_rereview_integration(self):
        # 集成：源或译文变化后旧 binding 失效（完整身份含源链资源）
        record = base_record(self.root, self.pdf)
        self.assertEqual(self.run_delivery(record).returncode, 0)
        parsed = self.root / 'source/source_en.md'
        parsed.write_text(parsed.read_text(encoding='utf-8') + '\nmore\n',
                          encoding='utf-8')
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            any('binding 与当前完整上下文不符' in p
                or '源全量对账失败' in p for p in result.stderr.splitlines()),
            result.stderr)

    def test_unknown_tool_rejected(self):
        record = base_record(self.root, self.pdf)
        record['checks'].append({'tool': 'run_arbitrary',
                                 'args': ['whatever']})
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未知的核验入口', result.stderr)

    def test_same_basename_pdf_from_other_dir_cannot_substitute(self):
        # R4：--pdf 绑定规范化完整路径，其他目录同名 PDF 不能替验
        other = Path(tempfile.mkdtemp(prefix='other-dir-'))
        self.addCleanup(shutil.rmtree, other, True)
        (other / 'book.pdf').write_bytes(self.pdf.read_bytes())
        record = base_record(self.root, self.pdf)
        # 声明的 book.pdf 实际是普通文本（摘要同步伪造）
        fake = self.root / 'broken.pdf'
        fake.write_text('这不是 PDF', encoding='utf-8')
        (self.root / 'book.pdf').write_text('这不是 PDF', encoding='utf-8')
        record['outputs'][0]['sha256'] = sha(self.root / 'book.pdf')
        record['files']['broken.pdf'] = 'pdf'
        record['reviews'] = [{'kind': 'visual', 'target': 'book.pdf',
                              'status': 'closed', 'sha256': sha(self.root / 'book.pdf'),
                              'note': '伪造复核'}]
        # checks 指向其他目录的正常 book.pdf
        record['checks'] = [
            {'tool': 'verify_pdf',
             'args': ['--pdf', str(other / 'book.pdf'),
                      '--work-dir', str(self.root / 'work'),
                      '--images-display', 'export/images_display.json',
                      '01_章.md']},
            {'tool': 'verify_translation',
             'args': ['01_章.md', 'source/source_en.md']},
        ]
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            '未按规范化完整路径绑定' in result.stderr
            or '输出摘要不符' in result.stderr or '复验失败' in result.stderr,
            result.stderr)

    def test_prerestored_json_does_not_affect_result(self):
        # 精简 03：机器证据取自本次核验计算——缺预存核验 JSON 可通过，
        # 伪造/过期/残留的旧 JSON 不影响结果（check.report 亦不参与判断）。
        (self.root / 'work' / 'verify_report.json').unlink(
            missing_ok=True)
        result = self.run_delivery(base_record(self.root, self.pdf))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 伪造成功状态但残留 failures 的旧 JSON
        forged = {
            'status': 'machine-pass-pending-visual',
            'failures': [{'code': 'left-over', 'message': '残留失败项'}],
            'reviews': [], 'relaxed_matches': [],
            'management_exclusions': [
                {'input': str((self.root / '01_章.md').resolve()),
                 'exclusions': []}],
        }
        (self.root / 'work' / 'verify_report.json').write_text(
            json.dumps(forged), encoding='utf-8')
        result = self.run_delivery(base_record(self.root, self.pdf))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 绑定其他输入的过期报告同样不影响本次结论
        stale = dict(forged)
        stale['management_exclusions'] = [
            {'input': '/other/x.md', 'exclusions': []}]
        (self.root / 'work' / 'stale_report.json').write_text(
            json.dumps(stale), encoding='utf-8')
        record = base_record(self.root, self.pdf)
        record['checks'][0]['report'] = 'stale_report.json'  # 可保留不参与
        result = self.run_delivery(record)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_export_evidence_rejected(self):
        # 导出报告是必需输入：本次核验计算缺导出证据必须失败，不能发布
        record = base_record(self.root, self.pdf)  # 先取本次复核项基线
        (self.root / 'work' / exporter.REPORT_NAME).unlink()
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('复验失败', result.stderr)
        self.assertIn('export-evidence-missing', result.stderr)
        self.assertFalse((self.evidence / 'delivery_index.json').exists())

    def test_policy_mismatch_requires_reexport(self):
        # 旧导出证据缺严格政策时不能靠本次核验补写放行（参数口径必须一致）
        record = base_record(self.root, self.pdf)
        record['checks'][0]['args'].append('--require-display-map')
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('images-display-require-mismatch', result.stderr)

    def test_image_map_file_change_invalidates_semantic_binding(self):
        # 翻译检查的 --image-map 文件是检查依赖（§9.3）：字节变化即使
        # 语义等价、核验仍通过，也必须使旧复核 binding 失效，不能按旧
        # 记录发布
        from _verification import resource_identity_digest
        digest = resource_identity_digest(
            str(self.root / 'source/images/pic.png'))
        imgmap = self.root / 'docs/imgmap.json'
        imgmap.write_text(json.dumps({'digests': [digest]}),
                          encoding='utf-8')

        def with_image_map(checks):
            checks[1]['args'] = ['01_章.md', 'source/source_en.md',
                                 '--image-map', 'docs/imgmap.json']

        record = base_record(self.root, self.pdf,
                             check_mutator=with_image_map)
        result = self.run_delivery(record)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 同内容不同字节的映射文件：核验仍通过，但检查依赖身份已变化
        imgmap.write_text(json.dumps({'digests': [digest]}, indent=2),
                          encoding='utf-8')
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('binding 与当前完整上下文不符', result.stderr)

    def test_strict_export_with_equals_form_and_adjacent_bool_passes(self):
        # 真实 CLI 与交付入口解释一致：--pdf= 等号写法 + 布尔开关紧接
        # 路径位置参数，从交付根之外调用也正确（子进程/进程内均以交付根
        # 为基点）。
        self.use_strict_fixture()

        def strict_args(checks):
            checks[0]['args'] = [
                '--pdf=book.pdf', '--work-dir', str(self.root / 'work'),
                '--images-display', 'export/images_display.json',
                '--require-display-map', '01_章.md']

        record = base_record(self.root, self.pdf, strict=True,
                             check_mutator=strict_args)
        result = self.run_delivery(record)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_malformed_pdf_arg_is_clean_problem(self):
        # --pdf 缺值等畸形记录必须给出干净的问题条目（按真实 CLI 解析
        # 失败），不得抛异常崩溃。
        def break_pdf_arg(checks):
            for check in checks:
                if check['tool'] == 'verify_pdf':
                    check['args'] = ['--pdf']

        record = base_record(self.root, self.pdf,
                             check_mutator=break_pdf_arg)
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('真实 CLI 解析', result.stderr)

    def test_literal_cli_args_preserved_not_path_resolved(self):
        # P2-6：官方标题/strong token 等字面值参数按原语义传递，不能被
        # 当成路径拼到交付根下（正例：字面 token 通过核验）。
        def literal_args(checks):
            checks[1]['args'] = [
                '01_章.md', 'source/source_en.md', '--strong-token', '第 1 章',
                '第 1 章']

        record = base_record(self.root, self.pdf,
                             check_mutator=literal_args)
        result = self.run_delivery(record)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_translation_check_must_cover_declared_inputs(self):
        # P1-3：翻译检查范围必须与实际交付输入对应。检查参数指向另一
        # 目录里内容正常的源/译文、且本身通过，也不能替验交付输入。
        other = Path(tempfile.mkdtemp(prefix='other-check-'))
        self.addCleanup(shutil.rmtree, other, True)
        (other / 'src.md').write_text('# 第 1 章\n\n正文。\n', encoding='utf-8')
        (other / 'dst.md').write_text('# 第 1 章\n\n正文。\n', encoding='utf-8')
        record = base_record(self.root, self.pdf)
        record['checks'] = [
            {'tool': 'verify_pdf',
             'args': ['--pdf', 'book.pdf', '--work-dir', str(self.root / 'work'),
                      '--images-display', 'export/images_display.json',
                      '01_章.md']},
            {'tool': 'verify_translation',
             'args': [str(other / 'dst.md'), str(other / 'src.md')]},
        ]
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未被任何翻译家族检查覆盖', result.stderr)

    def test_visual_review_must_bind_each_pdf_not_merely_exist(self):
        # 三轮复审 P1-2：PDF 被 semantic 复核绑定、visual 却绑在
        # Markdown 时，PDF 本身没有 visual 记录，必须拒绝。先移除代码块
        # 使报告没有其他待复核项，确保负例只因目标绑定错误变红。
        chapter = self.root / '01_章.md'
        chapter.write_text(
            '# 第 1 章\n\n> **来源**：https://example.com/pv-delivery\n'
            '> **抓取日期**：2026-09-15\n\n'
            '![图](images/pic.png)\n\n正文。\n\n'
            '```text\nhello = 1;\n```\n', encoding='utf-8')
        result = exporter.export(
            [str(chapter)], self.pdf, self.root / 'work',
            images_display_paths=[str(self.root / 'export/images_display.json')])
        self.assertEqual(result, 0)
        record = base_record(self.root, self.pdf)
        record['mode'] = 'pdf'
        record['checks'] = [record['checks'][0]]
        record['reviews'] = [
            {'kind': 'semantic', 'target': 'book.pdf', 'status': 'closed',
             'sha256': sha(self.pdf), 'note': '语义复核绑定 PDF'},
            {'kind': 'visual', 'target': '01_章.md', 'status': 'closed',
             'items': [], 'note': '只看了 Markdown 排版'},
        ]
        result = self.run_delivery(record)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('缺少绑定其摘要的闭合视觉复核', result.stderr)

    def test_report_reviews_require_specific_disposition(self):
        # 三轮复审 P1-3：verify_pdf.reviews 是独立待处置通道，
        # 不在 relaxed_matches 中。缺少逐项 link 处置时交付必须失败；
        # 绑定同一 PDF 并引用具体事项的 link 记录是配对正例。
        chapter = self.root / '01_章.md'
        chapter.write_text(
            chapter.read_text(encoding='utf-8')
            + '\n[查看附录](docs/missing-appendix.md)\n'
              '[查看附录](docs/missing-appendix.md)\n', encoding='utf-8')
        result = exporter.export(
            [str(chapter)], self.pdf, self.root / 'work',
            images_display_paths=[str(self.root / 'export/images_display.json')])
        self.assertEqual(result, 0)
        ns = pdf_verifier.parse_args(
            ['--pdf', str(self.pdf), '--work-dir', str(self.root / 'work'),
             '--images-display', str(self.root / 'export/images_display.json'),
             str(chapter)])
        ok, report = pdf_verifier.run_verification(ns)
        self.assertTrue(ok, report['failures'])
        pending_links = [
            delivery_verifier.review_item_label(item, 'reviews', index)
            for index, item in enumerate(report.get('reviews', []))
            if item.get('code') == 'range-out-link']
        self.assertEqual(len(pending_links), 2, report.get('reviews'))
        record = base_record(self.root, self.pdf)
        record['mode'] = 'pdf'
        record['checks'] = [record['checks'][0]]
        contexts = delivery_contexts(self.root, record)
        record['reviews'] = [
            {'kind': 'visual', 'target': 'book.pdf', 'status': 'closed',
             'sha256': sha(self.pdf),
             'items': pending_review_items(self.root),
             'binding': expected_binding('visual', 'book.pdf', self.root,
                                         record, contexts),
             'note': '全页视觉复核闭合'},
        ]
        rejected = self.run_delivery(record)
        self.assertNotEqual(rejected.returncode, 0,
                            rejected.stdout + rejected.stderr)
        self.assertIn('待处置项未由绑定该成品的 link 复核逐项闭合',
                      rejected.stderr)
        # 同名链接出现两次时，只处置第一个报告位置仍必须
        # 失败；不得因 code/message 相同而被 set 折叠后代闭。
        record['reviews'].append(
            {'kind': 'link', 'target': 'book.pdf', 'status': 'closed',
             'sha256': sha(self.pdf), 'items': pending_links[:1],
             'binding': expected_binding('link', 'book.pdf', self.root,
                                         record, contexts),
             'note': '已确认第一个范围外链接不随本 PDF 交付'})
        partial = self.run_delivery(record)
        self.assertNotEqual(partial.returncode, 0,
                            partial.stdout + partial.stderr)
        self.assertIn('待处置项未由绑定该成品的 link 复核逐项闭合',
                      partial.stderr)
        record['reviews'][-1]['items'] = pending_links
        record['reviews'][-1]['note'] = '两个具体链接位置均已处置'
        accepted = self.run_delivery(record)
        self.assertEqual(accepted.returncode, 0,
                         accepted.stdout + accepted.stderr)

    def test_failure_battery_protects_whole_evidence_set(self):
        # 整套证据保护：先成功发布一次，再分别注入各类失败——旧索引与
        # 每个引用文件的摘要都必须保持不变。
        self.assertEqual(
            self.run_delivery(base_record(self.root, self.pdf)).returncode, 0)

        def snapshot_evidence():
            return {p.relative_to(self.evidence).as_posix(): sha(p)
                    for p in self.evidence.rglob('*') if p.is_file()}

        baseline = snapshot_evidence()
        index_before = (self.evidence / 'delivery_index.json').read_text(
            encoding='utf-8')

        def assert_protected(result):
            self.assertNotEqual(result.returncode, 0,
                                result.stdout + result.stderr)
            self.assertEqual(snapshot_evidence(), baseline)
            self.assertEqual(
                (self.evidence / 'delivery_index.json').read_text(
                    encoding='utf-8'),
                index_before)

        # 1) 预检失败：根目录出现未登记文件
        (self.root / 'extra.log').write_text('x\n', encoding='utf-8')
        assert_protected(self.run_delivery(base_record(self.root, self.pdf)))
        (self.root / 'extra.log').unlink()
        # 2) 核验失败：成品被篡改（摘要与记录不符 → 身份预检即拒绝）
        pristine_pdf = (self.root / 'book.pdf').read_bytes()
        tampered_record = base_record(self.root, self.pdf)  # 篡改前取复核项
        (self.root / 'book.pdf').write_bytes(pristine_pdf + b'\n')
        assert_protected(self.run_delivery(tampered_record))
        (self.root / 'book.pdf').write_bytes(pristine_pdf)
        # 3) 复核缺项：移除语义复核
        record = base_record(self.root, self.pdf)
        record['reviews'] = [r for r in record['reviews']
                             if r['kind'] != 'semantic']
        assert_protected(self.run_delivery(record))
        # 4) 索引替换前写入失败：证据目录只读
        os.chmod(self.evidence, 0o500)
        try:
            result = self.run_delivery(base_record(self.root, self.pdf))
        finally:
            os.chmod(self.evidence, 0o700)
        assert_protected(result)


if __name__ == '__main__':
    unittest.main()
