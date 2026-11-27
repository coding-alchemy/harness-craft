"""API 文档解析与源对账缺陷修复（R1–R8）：内联 HTML 夹具经真实 CLI 解析的正反例。"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
from _api_navigation import anchor_diffs
from _html_fidelity import HtmlFidelity
from _source_reconcile import (_MarkdownFacts, markdown_table_facts,
                               reconcile_html_to_markdown)
from _verification import SourceMathContext, scan_math

import test_latexml_source_loop


def api_html(body: str) -> str:
    return '<article><h1>T</h1>%s</article>' % body


# R7 完整文档统一样本；四个 HTML 家族入口共用
COMPLETE_PAGE = '<!DOCTYPE html><html><body><h1>T</h1><p>ok</p></body></html>'
FRAGMENT_PAGE = '<article><h1>T</h1><p>ok</p></article>'
ALL_ENTRIES = ('parse_api_html.py', 'parse_single_page_html.py',
               'parse_paginated_html.py', 'parse_reference_html.py')


class ApiParseReconcileFixesTest(unittest.TestCase):
    def run_parser(self, script_name: str, raw: str | bytes, *,
                   extra_args=()) -> tuple[subprocess.CompletedProcess, Path, Path]:
        """在 Git 工作区外运行解析入口，返回 (进程结果, 源文件路径, 解析稿路径)。"""
        root = Path(tempfile.mkdtemp(prefix='api-reconcile-'))
        self.addCleanup(shutil.rmtree, root)
        source = root / 'page.html'
        source.write_bytes(raw.encode('utf-8') if isinstance(raw, str) else raw)
        args = [sys.executable, str(SCRIPTS / script_name)]
        if script_name == 'parse_paginated_html.py':
            # 分页入口不接收输出路径，逐页写出同名 .md
            out = source.with_suffix('.md')
            args.append(str(source))
        else:
            out = root / 'source.md'
            args += [str(source), str(out)]
        args += list(extra_args)
        process = subprocess.run(args, capture_output=True, text=True)
        return process, source, out

    def parse_api(self, body: str) -> str:
        """运行 API 入口并要求对账通过，返回解析稿。"""
        process, _, out = self.run_parser('parse_api_html.py', api_html(body))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return out.read_text(encoding='utf-8')

    def assert_api_damage(self, body: str, damaged: str, expected: str) -> None:
        """对损伤后的解析稿同时做源对账与锚点核对，至少报一条含 expected 的差异。"""
        raw = api_html(body)
        diffs = reconcile_html_to_markdown(raw, damaged, 'api')
        diffs += anchor_diffs(raw, damaged)
        self.assertTrue(any(expected in diff for diff in diffs), diffs)

    def test_multiparagraph_dd_and_following_terms(self):
        body = ('<dl><dt>A</dt><dd><p>One.</p><p>Two.</p></dd>'
                '<dt>B</dt><dd><pre>x();</pre></dd>'
                '<dt>C</dt><dd><div class="admonition note">'
                '<p class="admonition-title">Note</p><p>N.</p></div></dd>'
                '<dt>D</dt><dd>End.</dd></dl>')
        text = self.parse_api(body)
        self.assertEqual([term for term, _ in _MarkdownFacts(text).terms()],
                         ['A', 'B', 'C', 'D'])
        self.assert_api_damage(body, text.replace('Two.', ''),
                               '定义列表')

    def test_dl_nested_in_list_keeps_sibling_paragraph(self):
        body = ('<ul><li><dl><dt>A</dt><dd><p>One.</p><p>Two.</p></dd></dl>'
                '<p>After.</p></li></ul>')
        text = self.parse_api(body)
        self.assertIn('After.', text)
        self.assertEqual([term for term, _ in _MarkdownFacts(text).terms()], ['A'])

    def test_nested_source_object_anchors_precede_blocks(self):
        body = ('<ul><li><table id="li-table"><tr><td>Cell</td></tr></table></li></ul>'
                '<p>Between.</p>'
                '<dl><dt>A</dt><dd><table id="dd-table"><tr><td>Cell2</td></tr>'
                '</table></dd></dl>'
                '<p>Between.</p>'
                '<ul><li><h3 id="li-heading">Nested</h3></li></ul>'
                '<p>Between.</p>'
                '<dl><dt>B</dt><dd><div class="admonition note" id="dd-note">'
                '<p class="admonition-title">Note</p><p>N.</p></div></dd></dl>')
        text = self.parse_api(body)
        for anchor, marker in (('li-table', '[TABLE]'),
                               ('dd-table', '[TABLE]'),
                               ('li-heading', '### Nested'),
                               ('dd-note', '> **ADMONITION')):
            anchor_at = text.index('<a id="%s"></a>' % anchor)
            self.assertLess(anchor_at, text.index(marker, anchor_at))
        # 锚点挪到表格数据区之后：锚点仍在，但紧随它的不再是该表格
        anchor = '  <a id="li-table"></a>\n'  # 随列表项缩进
        self.assertIn(anchor, text)
        start = text.index(anchor)
        without = text[:start] + text[start + len(anchor):]
        cell_end = without.index('Cell\n') + len('Cell\n')
        self.assert_api_damage(body, without[:cell_end] + anchor + without[cell_end:],
                               '锚点目标错绑')

    def test_direct_pre_id_in_list_still_rejects(self):
        process, _, out_path = self.run_parser(
            'parse_api_html.py',
            api_html('<ul><li><pre id="direct-code">x();</pre></li></ul>'))
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('缺来源对象锚点', process.stderr)
        self.assertFalse(out_path.exists())

    def test_table_cell_pipes_escape_and_read_back(self):
        body = ('<table><tr><th>Rule</th><th>Header</th></tr>'
                '<tr><td><code>&amp; | ^</code></td>'
                '<td>Oper 254 (ta | tb | tc)</td></tr></table>')
        text = self.parse_api(body)
        self.assertIn(r'`& \| ^`', text)
        self.assertIn(r'Oper 254 (ta \| tb \| tc)', text)
        rows = markdown_table_facts(text)[0]['raw_rows']
        self.assertEqual(rows[1], ['`& | ^`', 'Oper 254 (ta | tb | tc)'])
        # 行内代码损伤在对账差异里按事实类别 'inline-code' 命名
        self.assert_api_damage(body, text.replace(r'`& \| ^`', r'`& \| &`'),
                               'inline-code')
        self.assert_api_damage(body, text.replace('Oper 254', 'Oper 255'),
                               '表格')

    def test_single_column_pipe_read_back(self):
        body = ('<table><tr><td>a | b</td></tr><tr><td>plain</td></tr></table>')
        text = self.parse_api(body)  # 对账通过由 parse_api 的退出码断言
        self.assertIn(r'a \| b', text)
        rows = markdown_table_facts(text)[0]['raw_rows']
        self.assertEqual(rows, [['a | b'], ['plain']])

    def test_code_first_single_column_table_tracks_all_rows(self):
        body = ('<table><tr><td><pre>first();</pre></td></tr>'
                '<tr><td>T1</td></tr>'
                '<tr><td><pre>third();</pre></td></tr>'
                '<tr><td>T3</td></tr></table>')
        text = self.parse_api(body)
        record = markdown_table_facts(text)[0]
        self.assertEqual(len(record['rows']), 4)
        self.assertEqual(set(record['codes']), {(1, 1, 1), (3, 1, 1)})
        self.assert_api_damage(body,
                               text.replace('[TABLE-CODE r=3 c=1#1]',
                                            '[TABLE-CODE r=1 c=1#1]'),
                               '格内代码')

    def test_non_api_html_families_escape_table_pipes(self):
        raw = ('<html><body><article><h1>T</h1>'
               '<table><tr><th>Rule</th><th>Header</th></tr>'
               '<tr><td><code>&amp; | ^</code></td>'
               '<td>Oper 254 (ta | tb | tc)</td></tr></table>'
               '</article></body></html>')
        for script in ('parse_single_page_html.py', 'parse_paginated_html.py',
                       'parse_reference_html.py'):
            with self.subTest(script=script):
                process, _, out = self.run_parser(script, raw)
                self.assertEqual(process.returncode, 0,
                                 process.stdout + process.stderr)
                text = out.read_text(encoding='utf-8')
                self.assertIn(r'`& \| ^`', text)
                self.assertIn(r'Oper 254 (ta \| tb \| tc)', text)

    def test_default_table_writer_keeps_latexml_pipes_literal(self):
        fidelity = HtmlFidelity()
        soup = fidelity.parse(
            '<table><tr><td><code>a|b</code></td></tr></table>')
        text = '\n'.join(fidelity.table_block(soup.find('table')))
        self.assertIn('`a|b`', text)
        self.assertNotIn(r'a\|b', text)

    def test_table_cell_math_pipes_read_back(self):
        body = ('<table><tr><th>Name</th><th>Formula</th></tr>'
                '<tr><td>Abs</td><td><span class="math">\\(|x|\\)</span></td></tr>'
                '<tr><td>Prob</td><td><span class="math">\\(p(a | b)\\)</span></td></tr>'
                '<tr><td>Norm</td><td><span class="math">\\(\\|x\\|\\)</span></td></tr>'
                '</table>')
        text = self.parse_api(body)
        self.assertIn(r'$\|x\|$', text)
        self.assertIn(r'$p(a \| b)$', text)
        self.assertIn(r'$\\|x\\|$', text)
        self.assert_api_damage(body, text.replace(r'$\|x\|$', r'$\|y\|$'), '内容')

    def test_table_cell_image_pipe_read_back(self):
        body = ('<table><tr><th>Kind</th><th>Value</th></tr>'
                '<tr><td>Img</td><td><img src="img|a.png" alt="pic"></td></tr></table>')
        text = self.parse_api(body)
        self.assertIn(r'img\|a.png', text)
        self.assert_api_damage(body, text.replace(r'img\|a.png', r'img\|b.png'), '内容')

    def test_table_row_pipe_read_back_boundaries(self):
        # 读回只发生在 HTML 家族（无来源依据）的表格行上：行内与块级公式、
        # 图片地址都读回；表格外保持字面；带来源依据时一律不读回
        text = '\n'.join([
            '[TABLE]', 'Name | Value', '--- | ---',
            r'Abs | $\|x\|$ ![pic](img\|a.png)',
            r'Blk | $$\|y\|$$', '',
            r'Outside $\|v\|$ and ![q](img\|b.png).'])
        math = lambda facts: [(entry[3], entry[4]) for entry in facts.math]
        images = lambda facts: [entry[4] for entry in facts.images]
        facts = _MarkdownFacts(text)
        self.assertIn(('inline', '|x|'), math(facts))
        self.assertIn(('block', '|y|'), math(facts))
        self.assertIn(('inline', r'\|v\|'), math(facts))
        self.assertEqual(images(facts), ['img|a.png', r'img\|b.png'])
        # SourceMathContext 必须给出 entries；空上下文同样是“带来源依据”
        literal = _MarkdownFacts(text, source_context=SourceMathContext([]))
        self.assertIn(('inline', r'\|x\|'), math(literal))
        self.assertEqual(images(literal), [r'img\|a.png', r'img\|b.png'])

    def test_definition_list_item_continuations_and_following_paragraph(self):
        body = ('<dl><dt>Ops</dt><dd><ul>'
                '<li><p>First A.</p><p>Second A.</p>'
                '<ul><li>Nested A.</li></ul></li>'
                '<li><p>First B.</p><p>Second B.</p></li>'
                '</ul><p>After list.</p></dd></dl>')
        text = self.parse_api(body)
        records = _MarkdownFacts(text).list_records()
        contents = [value for record in records
                    for _, value in record['seq']]
        # dd 内列表项的续段与嵌套子列表归入原项
        for expected in ('Second A.', 'Second B.', 'Nested A.'):
            self.assertIn(expected, contents)
        # 列表结束后的 dd 段落仍是定义内容，不并入列表项
        self.assertNotIn('After list.', contents)
        second_a = [record for record in records
                    if 'Second A.' in [value for _, value in record['seq']]]
        self.assertIn(('list', None), second_a[0]['seq'])
        self.assert_api_damage(body, text.replace('Second A.', ''),
                               '列表项')
        # 判别样本（设计 §7.3）：dl 嵌在宿主 li 内。若在任意列表标记处
        # 提前结束定义区，列表后的 dd 段落会并入宿主项（多出 ('list',
        # None) 与 ('text', 'After list.')）而被对账阻断；正确做法退出 0
        host_body = ('<ul><li><dl><dt>Ops</dt><dd><ul>'
                     '<li><p>First A.</p><p>Second A.</p></li></ul>'
                     '<p>After list.</p></dd></dl></li></ul>')
        host_text = self.parse_api(host_body)
        host_records = _MarkdownFacts(host_text).list_records()
        host_contents = [value for record in host_records
                         for _, value in record['seq']]
        self.assertNotIn('After list.', host_contents)

    def test_literal_dollars_escape_in_paragraphs_and_links(self):
        body = ('<p>Uses $pointerType here.</p>'
                '<p>See <a href="#x">cuda_tile.preview$call</a> for details.</p>')
        text = self.parse_api(body)
        self.assertIn(r'\$pointerType', text)
        self.assertIn(r'cuda_tile.preview\$call', text)
        # 去掉任一反斜线：未配对美元回到扫描的未闭合 issue（Markdown 侧拒绝）
        for damaged in (text.replace(r'\$pointerType', '$pointerType'),
                        text.replace(r'preview\$call', 'preview$call')):
            issues = scan_math(damaged).issues
            self.assertTrue(issues, damaged)
            self.assertTrue(all(issue.raw == '$' for issue in issues))

    def test_short_unresolved_dollar_still_blocks(self):
        process, _, out_path = self.run_parser(
            'parse_api_html.py', api_html('<p>$x</p>'))
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(out_path.exists())

    def test_spaced_dollar_keeps_existing_noncandidate_behavior(self):
        text = self.parse_api('<p>$ 5</p>')
        self.assertIn('$ 5', text)
        self.assertNotIn(r'\$ 5', text)

    def test_tag_split_math_with_identifier_edges_still_blocks(self):
        for body in ('<p>Compute $QK<sup>T</sup>V$ here.</p>',
                     '<p>Sum $AB<em>1 + CD</em>2$ here.</p>',
                     '<p>Score $W_q<em>x W</em>k$ here.</p>'):
            with self.subTest(body=body):
                process, _, out_path = self.run_parser(
                    'parse_api_html.py', api_html(body))
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('未解决数学定界', process.stderr)
                self.assertFalse(out_path.exists())

    def test_non_api_html_families_escape_literal_dollars(self):
        raw = ('<html><body><article><h1>T</h1>'
               '<p>Uses $pointerType here.</p>'
               '</article></body></html>')
        for script in ('parse_single_page_html.py', 'parse_paginated_html.py',
                       'parse_reference_html.py'):
            with self.subTest(script=script):
                process, _, out = self.run_parser(script, raw)
                self.assertEqual(process.returncode, 0,
                                 process.stdout + process.stderr)
                self.assertIn(r'\$pointerType',
                              out.read_text(encoding='utf-8'))

    def test_same_text_node_dollar_pairing_unchanged(self):
        text = self.parse_api('<p>$pointerType and preview$call</p>'
                              '<p>Value $x$ costs $100.</p>')
        self.assertIn('$pointerType and preview$call', text)
        self.assertNotIn(r'\$pointerType', text)
        self.assertIn('$x$', text)
        self.assertIn('$100', text)

    def test_complete_documents_and_article_fragments_parse(self):
        for raw in (COMPLETE_PAGE, FRAGMENT_PAGE):
            for script in ALL_ENTRIES:
                with self.subTest(script=script, page=raw[:15]):
                    process, _, out = self.run_parser(script, raw)
                    self.assertEqual(process.returncode, 0,
                                     process.stdout + process.stderr)
                    self.assertTrue(out.exists(), out)

    def test_truncated_documents_rejected_without_output(self):
        data = COMPLETE_PAGE.encode('utf-8')[:-len('</html>')]
        for script in ALL_ENTRIES:
            with self.subTest(script=script):
                process, source, out = self.run_parser(script, data)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('HTML 快照截断', process.stderr)
                self.assertIn(str(source), process.stderr)
                self.assertIn('（%d 字节）' % len(data), process.stderr)
                self.assertFalse(out.exists())

    def test_reference_adapted_and_inspect_reject_truncated(self):
        raw, _md, payload = test_latexml_source_loop._adapt()
        root = Path(tempfile.mkdtemp(prefix='api-reconcile-r7-'))
        self.addCleanup(shutil.rmtree, root)
        snapshot = root / 'paper.html'
        data = raw.encode('utf-8').rstrip()[:-len('</html>')]
        snapshot.write_bytes(data)
        payload['snapshot']['path'] = str(snapshot)
        payload_path = root / 'adaptation.json'
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        # --source-adaptation/--adaptation-output 分支：读入前报截断，
        # 快照摘要核对（针对完整内容的声明）尚未开始
        out_path = root / 'paper.md'
        adapt_out = root / 'candidate.json'
        adapted = subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_reference_html.py'),
             str(snapshot), str(out_path),
             '--source-adaptation', str(payload_path),
             '--adaptation-output', str(adapt_out)],
            capture_output=True, text=True)
        self.assertNotEqual(adapted.returncode, 0)
        self.assertIn('HTML 快照截断', adapted.stderr)
        self.assertIn('（%d 字节）' % len(data), adapted.stderr)
        self.assertFalse(out_path.exists())
        self.assertFalse(adapt_out.exists())
        # --inspect-output 分支：检查候选不写出
        inspect_out = root / 'inspection.json'
        inspected = subprocess.run(
            [sys.executable, str(SCRIPTS / 'parse_reference_html.py'),
             str(snapshot), '--inspect-output', str(inspect_out)],
            capture_output=True, text=True)
        self.assertNotEqual(inspected.returncode, 0)
        self.assertIn('HTML 快照截断', inspected.stderr)
        self.assertIn('（%d 字节）' % len(data), inspected.stderr)
        self.assertFalse(inspect_out.exists())

    def test_truncation_inside_multibyte_character_reports_snapshot_error(self):
        full = ('<!DOCTYPE html><html><body><h1>T</h1><p>中</p></body></html>'
                ).encode('utf-8')
        # 截点取“中”最后一个字节：文件停在多字节字符中间
        data = full[:full.index('中'.encode('utf-8')) + 2]
        for script in ALL_ENTRIES:
            with self.subTest(script=script):
                process, _, out = self.run_parser(script, data)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('HTML 快照截断', process.stderr)
                self.assertNotIn('UnicodeDecodeError', process.stderr)
                self.assertFalse(out.exists())

    def test_closing_html_text_inside_pre_does_not_count_as_document_end(self):
        # 整页以 <pre>example </html></pre> 开头，物理文件没有最终 </html>：
        # 只搜“文中出现过 </html>”会放过它
        pre_page = ('<!DOCTYPE html><html><body><pre>example </html></pre>'
                    '</body>')
        for script in ALL_ENTRIES:
            with self.subTest(script=script):
                process, _, out = self.run_parser(script, pre_page)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('HTML 快照截断', process.stderr)
                self.assertFalse(out.exists())
        for script in ALL_ENTRIES:
            with self.subTest(script=script, complete=True):
                process, _, out = self.run_parser(script, pre_page + '</html>')
                self.assertEqual(process.returncode, 0,
                                 process.stdout + process.stderr)
                self.assertTrue(out.exists(), out)


    def test_rejected_candidate_is_byte_exact_and_original_absent(self):
        import parse_api_html
        root = Path(tempfile.mkdtemp(prefix='api-reconcile-r8-'))
        self.addCleanup(shutil.rmtree, root)
        source = root / 'page.html'
        source.write_text(
            api_html('<ul><li><pre id="direct-code">x();</pre></li></ul>'),
            encoding='utf-8')
        out_path = root / 'source.md'
        # 捕获入口实际传给 reconcile_html_to_markdown 的 md_text；包装不
        # 改变对账结果，后续锚点核对照常产生真实“缺来源对象锚点”失败
        captured = {}
        original = parse_api_html.reconcile_html_to_markdown
        def capture(raw, md_text, *args, **kwargs):
            captured['md_text'] = md_text
            return original(raw, md_text, *args, **kwargs)
        with mock.patch.object(parse_api_html, 'reconcile_html_to_markdown',
                               capture), \
                mock.patch.object(sys, 'argv',
                                  ['parse_api_html.py', str(source),
                                   str(out_path)]):
            with self.assertRaises(SystemExit) as caught:
                parse_api_html.main()
        self.assertLessEqual(len(str(caught.exception).splitlines()), 40)
        self.assertIn('全部差异与被拒解析稿：', str(caught.exception))
        # 临时目录取自报错末行；旁路稿与参与对账的文本逐字节相同
        side = Path(str(caught.exception).splitlines()[-1].rsplit('：', 1)[1])
        self.addCleanup(shutil.rmtree, side, True)
        self.assertEqual((side / 'source.rejected.md').read_bytes(),
                         captured['md_text'].encode('utf-8'))
        self.assertIn('缺来源对象锚点', (side / 'reconcile_diffs.txt').read_text())
        self.assertFalse(out_path.exists())
        # 旧输出 sentinel 子例：失败不触碰已存在的旧字节
        sentinel = b'OLD SOURCE BYTES\n'
        out_path.write_bytes(sentinel)
        with mock.patch.object(parse_api_html, 'reconcile_html_to_markdown',
                               capture), \
                mock.patch.object(sys, 'argv',
                                  ['parse_api_html.py', str(source),
                                   str(out_path)]):
            with self.assertRaises(SystemExit):
                parse_api_html.main()
        self.assertEqual(out_path.read_bytes(), sentinel)

    def test_rejected_suffix_refused_by_split_and_api_verification(self):
        root = Path(tempfile.mkdtemp(prefix='api-reconcile-r8-refuse-'))
        self.addCleanup(shutil.rmtree, root)
        rejected = root / 'source.rejected.md'
        rejected.write_text('# T\n\nbody\n', encoding='utf-8')
        import split_work_packages
        out_dir = root / 'wps'
        with self.assertRaises(SystemExit) as caught:
            split_work_packages.split(str(rejected), str(out_dir),
                                      str(root / 'trans'), 'h2')
        self.assertIn('这是源对账未通过的解析稿', str(caught.exception))
        self.assertFalse(out_dir.exists())
        # API 核验 CLI：空 manifest/TOC、最小 merged 与 site，同样拒收
        manifest = root / 'manifest.txt'
        manifest.write_text('', encoding='utf-8')
        toc = root / 'official_toc.txt'
        toc.write_text('', encoding='utf-8')
        merged = root / 'merged.md'
        merged.write_text('# T\n', encoding='utf-8')
        site = root / 'site'
        site.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'verify_api_translation.py'),
             str(merged), str(manifest), str(toc), str(site), str(rejected)],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('这是源对账未通过的解析稿', result.stderr)


if __name__ == '__main__':
    unittest.main()
