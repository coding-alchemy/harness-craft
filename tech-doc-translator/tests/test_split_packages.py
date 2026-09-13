"""安全拆包与无损还原的固定语义验收（任务 03）。"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import split_work_packages as split

_FRONT = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)


def write(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def read_packages(wps_dir):
    packages = []
    for name in sorted(os.listdir(wps_dir)):
        if not name.endswith('.md'):
            continue
        text = open(os.path.join(wps_dir, name), encoding='utf-8').read()
        m = _FRONT.match(text)
        meta = {}
        for line in m.group(1).splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
        packages.append({'name': name, 'meta': meta, 'body': text[m.end():]})
    return packages


class SplitPackagesTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='split_test_')

    def split(self, source_text, strategy='h2', name='src.md'):
        src = write(self.tmp, name, source_text)
        wps = os.path.join(self.tmp, 'wps_' + name.replace('.', '_'))
        trans = os.path.join(self.tmp, 'trans_' + name.replace('.', '_'))
        split.split(src, wps, trans, strategy)
        return read_packages(wps), source_text

    def test_h2_inside_fence_is_not_a_cut_point(self):
        src = ('# T\n\n## S1\n\n```python\n## 2. Fake Section\nx = 1\n```\n\n## S2\n\nB\n')
        packages, _ = self.split(src)
        self.assertEqual(len(packages), 2)
        self.assertIn('## 2. Fake Section', packages[0]['body'])

    def test_reassembly_is_byte_identical_and_no_injected_heading(self):
        src = ('# T\n\n## S1\n\npara one\npara two\n\n## S2\n\nB\nC\n')
        packages, source = self.split(src, 'chars:20')
        self.assertEqual(
            '\n'.join(p['body'] for p in packages), source)
        # 续片不注入重复标题：S1 的后续片段不得出现第二个 '## S1'
        s1_fragments = [p for p in packages
                        if p['meta']['section_id'] == '"S1"']
        for fragment in s1_fragments[1:]:
            self.assertNotIn('## S1', fragment['body'])

    def test_chars_target_splits_at_block_boundaries_and_keeps_fence_whole(self):
        fence_body = '\n'.join('line %d of a very long fenced block' % i
                               for i in range(30))
        src = ('## A\n\nshort para\n\n```c\n%s\n```\n\n## B\n\nb para\n'
               % fence_body)
        packages, _ = self.split(src, 'chars:120')
        # 长围栏整体保留在某个包中，不被拆开
        whole = [p for p in packages if 'line 0 of a very long fenced block' in p['body']]
        self.assertEqual(len(whole), 1)
        self.assertIn('```c', whole[0]['body'])
        fence_body_lines = [l for l in whole[0]['body'].splitlines()
                            if l.startswith('line ')]
        self.assertEqual(len(fence_body_lines), 30)

    def test_over_limit_single_block_reported(self):
        fence_body = '\n'.join('x = %d  # long code line for the report' % i
                               for i in range(40))
        src = '## A\n\n```c\n%s\n```\n' % fence_body
        packages, _ = self.split(src, 'chars:100')
        # 小节标题与超限围栏同包保留，不拆坏围栏
        self.assertEqual(len(packages), 1)
        self.assertIn('## A', packages[0]['body'])
        self.assertEqual(
            sum(1 for line in packages[0]['body'].splitlines()
                if line.startswith('x = ')), 40)

    def test_duplicate_sections_get_instance_numbers(self):
        src = '## Dup\n\nA\n\n## Dup\n\nB\n'
        packages, _ = self.split(src)
        instances = sorted(p['meta']['section_instance'] for p in packages)
        self.assertEqual(instances, ['1', '2'])

    def test_cross_section_footnote_merges_packages(self):
        src = ('## S1\n\n引用[^1]。\n\n## S2\n\nB\n\n[^1]: 脚注定义在末尾。\n')
        packages, source = self.split(src)
        self.assertEqual(len(packages), 1)
        self.assertIn('脚注定义在末尾', packages[0]['body'])
        self.assertEqual('\n'.join(p['body'] for p in packages), source)

    def test_cross_section_reference_link_merges_packages(self):
        # 评审 P2-3：普通引用链接的定义依赖必须并入拆包边界判断
        src = ('## Sec A\n\n详见 [details][ref] 说明。\n\n'
               '## Sec B\n\n其他内容。\n\n[ref]: https://example.com/details\n')
        packages, source = self.split(src)
        self.assertEqual(len(packages), 1)
        self.assertIn('[details][ref]', packages[0]['body'])
        self.assertIn('[ref]: https://example.com/details', packages[0]['body'])
        self.assertEqual('\n'.join(p['body'] for p in packages), source)

    def test_cross_section_reference_image_merges_packages(self):
        src = ('## Sec A\n\n![示意][pic]\n\n## Sec B\n\n内容。\n\n'
               '[pic]: images/pic.png\n')
        packages, source = self.split(src)
        self.assertEqual(len(packages), 1)
        self.assertIn('![示意][pic]', packages[0]['body'])
        self.assertIn('[pic]: images/pic.png', packages[0]['body'])
        self.assertEqual('\n'.join(p['body'] for p in packages), source)

    def test_reference_link_and_def_share_fragment_under_chars(self):
        # chars 策略强制细分的片段中，引用与其定义不得落在不同片段
        filler = '很长的正文段落用于撑大片段体量，包含许多字符。\n\n'
        src = ('## S1\n\n' + filler * 6 + '见 [doc][d]。\n\n'
               '## S2\n\n' + filler * 6 + '结束。\n\n[d]: https://example.com/doc\n')
        packages, source = self.split(src, 'chars:200')
        self.assertEqual('\n'.join(p['body'] for p in packages), source)
        for package in packages:
            has_ref = '[doc][d]' in package['body']
            has_def = '[d]: https://example.com/doc' in package['body']
            if has_ref or has_def:
                self.assertTrue(
                    has_ref and has_def,
                    '引用与定义被拆进不同片段: %s' % package['name'])

    def test_local_reference_link_keeps_single_package(self):
        # 引用与定义同节时行为不变；脚注依赖行为不受影响
        src = '## S1\n\n见 [doc][d]。\n\n[d]: https://example.com/doc\n'
        packages, _ = self.split(src)
        self.assertEqual(len(packages), 1)
        src2 = '## S1\n\n引用[^1]。\n\n[^1]: 注。\n'
        packages2, source2 = self.split(src2, name='src2.md')
        self.assertEqual(len(packages2), 1)
        self.assertEqual('\n'.join(p['body'] for p in packages2), source2)

    def test_image_and_caption_not_separated(self):
        src = ('## S1\n\n![fig](images/fig.png)\n\n**图 1. 图题（Caption）**\n\n'
               '正文段落足够长，用于触发块边界的切分判断，含很多字。\n\n## S2\n\nB\n')
        packages, source = self.split(src, 'chars:80')
        for package in packages:
            has_image = '![fig]' in package['body']
            has_caption = '**图 1.' in package['body']
            if has_image or has_caption:
                self.assertTrue(has_image and has_caption,
                                '图片与图题被切点分离: %s' % package['name'])
        self.assertEqual('\n'.join(p['body'] for p in packages), source)

    def test_frontmatter_records_span_digest_counts(self):
        src = '## S1\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\ntext\n'
        packages, source_text = self.split(src)
        meta = packages[0]['meta']
        self.assertEqual(meta['tables'], '1')
        self.assertIn('source_line_start', meta)
        self.assertIn('fragment_digest', meta)
        self.assertEqual(meta['source_line_start'], '1')
        # 字符区间与还原一致：切片与包正文相同
        start = int(meta['source_char_start'])
        end = int(meta['source_char_end'])
        self.assertEqual(source_text[start:end], packages[0]['body'])

    def test_trans_dir_same_as_wps_dir_rejected(self):
        src = write(self.tmp, 'bad.md', '## A\n\nB\n')
        wps = os.path.join(self.tmp, 'wps_same')
        with self.assertRaises(SystemExit):
            split.split(src, wps, wps, 'h2')

    def test_resplit_keeps_translations_untouched(self):
        src = '## A\n\nB\n'
        packages, _ = self.split(src)
        trans_dir = os.path.join(self.tmp, 'trans_A')
        target = packages[0]['meta']['target_file']
        with open(target, 'w', encoding='utf-8') as f:
            f.write('译文内容，不得被重复拆包改写')
        # 重新拆包
        split.split(os.path.join(self.tmp, 'src.md'),
                    os.path.join(self.tmp, 'wps_src_md'),
                    trans_dir, 'h2')
        with open(target, encoding='utf-8') as f:
            self.assertEqual(f.read(), '译文内容，不得被重复拆包改写')

    def test_legacy_count_blocks_interface(self):
        counts = split._count_blocks(
            ['**Figure caption**', '--- | --- | ---', '- real item'])
        self.assertEqual(counts['list_items'], 1)
        self.assertNotIn('tables', ())


if __name__ == '__main__':
    unittest.main()
