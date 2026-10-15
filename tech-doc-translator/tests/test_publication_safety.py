"""二期重审 F1：全产物路径冲突检查与同组原子发布。

覆盖评审缺口 F1a/F1b：派生的显示尺寸映射 <stem>.images_display.json
与 Markdown、候选依据在适配前一并计算路径并纳入同一组冲突检查；发布
泛化为同组备份+回滚（同目录暂存、已存在目标先改名备份、逐个替换、
失败按序恢复并如实诊断、非零退出）。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))

import _latexml_source as latexml
import parse_reference_html as parser
from _source_reconcile import reconcile_latexml_to_markdown

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'

IDENTITY = {
    'expected_title': 'Publication Safety Fixture',
    'actual_title': 'Publication Safety Fixture',
    'paper_id': '2101.00001',
    'version': 'v1',
    'final_url': 'https://example.org/abs/2101.00001v1',
    'retrieved_at': '2026-10-01T00:00:00Z',
    'confirmation': 'Independent synthetic review fixture',
}

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
       '<rect width="10" height="10"/></svg>')


def _write_snapshot(directory, with_image):
    text = ('Before <img src="pic.svg" alt="diagram" style="width:8px"/> '
            'After.' if with_image else 'Plain reconciled content.')
    raw = ('<html><body><article><h1>Publication Safety Fixture</h1>'
           '<p>%s</p></article></body></html>' % text)
    snap = os.path.join(directory, 'source.html')
    with open(snap, 'w', encoding='utf-8') as handle:
        handle.write(raw)
    if with_image:
        with open(os.path.join(directory, 'pic.svg'), 'w',
                  encoding='utf-8') as handle:
            handle.write(SVG)
    return raw, snap


def _write_input(path, raw, snap):
    payload = {
        'version': 1,
        'format': 'latexml',
        'snapshot': {'path': snap, 'sha256': latexml.sha256_text(raw)},
        'paper_identity': dict(IDENTITY),
        'decisions': [],
    }
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return path


def _run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / 'parse_reference_html.py')] + args,
        capture_output=True, text=True)


def _no_staging_left(directory):
    leftovers = [name for name in os.listdir(directory)
                 if name.startswith(('.publish_', '.displaymap_'))]
    return leftovers


class DisplayMapCollisionTest(unittest.TestCase):
    """F1a：派生尺寸映射路径纳入适配前冲突检查，冲突不写任何文件。"""

    def test_readonly_input_named_as_display_map_blocks_and_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, snap = _write_snapshot(tmp, with_image=True)
            out = os.path.join(tmp, 'source.md')
            inp = _write_input(os.path.join(
                tmp, 'source.images_display.json'), raw, snap)
            before = open(inp, 'rb').read()
            result = _run([snap, out,
                           '--source-adaptation', inp,
                           '--adaptation-output',
                           os.path.join(tmp, 'candidate.json')])
            self.assertEqual(result.returncode, 1)
            self.assertIn('禁止就地覆盖', result.stderr)
            self.assertIn('尺寸映射', result.stderr)
            self.assertEqual(open(inp, 'rb').read(), before)  # 输入字节不变
            self.assertFalse(os.path.exists(out))  # 未写任何产物
            self.assertFalse(os.path.exists(os.path.join(tmp, 'candidate.json')))
            self.assertEqual(_no_staging_left(tmp), [])

    def test_adaptation_output_named_as_display_map_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, snap = _write_snapshot(tmp, with_image=True)
            out = os.path.join(tmp, 'source.md')
            inp = _write_input(os.path.join(tmp, 'input.json'), raw, snap)
            result = _run([snap, out,
                           '--source-adaptation', inp,
                           '--adaptation-output',
                           os.path.join(tmp, 'source.images_display.json')])
            self.assertEqual(result.returncode, 1)
            self.assertIn('同一文件', result.stderr)
            self.assertFalse(os.path.exists(out))
            self.assertEqual(_no_staging_left(tmp), [])


class GroupPublishFailureTest(unittest.TestCase):
    """F1b：同组发布任一替换失败按序恢复备份、如实诊断、旧产物字节不动。"""

    def _patch_replace(self, fail_on):
        real_replace = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == fail_on:
                raise OSError('injected replacement failure')
            return real_replace(src, dst)

        return mock.patch.object(parser.os, 'replace', side_effect=flaky)

    def test_second_replace_failure_restores_old_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapt = os.path.join(tmp, 'adaptation.json')
            md = os.path.join(tmp, 'source.md')
            with open(adapt, 'w', encoding='utf-8') as handle:
                handle.write('OLD ADAPTATION')
            with open(md, 'w', encoding='utf-8') as handle:
                handle.write('OLD SOURCE')
            with self._patch_replace(fail_on=2):
                with self.assertRaises(SystemExit) as caught:
                    parser._publish_pair(adapt, 'NEW ADAPTATION',
                                         md, 'NEW SOURCE')
            message = str(caught.exception)
            self.assertIn('旧产物已按序恢复', message)
            self.assertNotIn('旧产物未改动', message)  # 诊断如实
            self.assertEqual(open(adapt, encoding='utf-8').read(),
                             'OLD ADAPTATION')
            self.assertEqual(open(md, encoding='utf-8').read(), 'OLD SOURCE')
            self.assertEqual(_no_staging_left(tmp), [])

    def test_third_replace_failure_restores_all_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets = [os.path.join(tmp, name) for name in
                       ('adaptation.json', 'source.md',
                        'source.images_display.json')]
            for target in targets:
                with open(target, 'w', encoding='utf-8') as handle:
                    handle.write('OLD ' + os.path.basename(target))
            old = {target: open(target, 'rb').read() for target in targets}
            items = [(targets[0], 'NEW ADAPTATION'), (targets[1], 'NEW SOURCE'),
                     (targets[2], 'NEW DISPLAY MAP')]
            with self._patch_replace(fail_on=3):
                with self.assertRaises(SystemExit) as caught:
                    parser._publish_group(items)
            self.assertIn('旧产物已按序恢复', str(caught.exception))
            for target in targets:
                self.assertEqual(open(target, 'rb').read(), old[target])
            self.assertEqual(_no_staging_left(tmp), [])

    def test_adaptation_output_is_directory_keeps_old_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, snap = _write_snapshot(tmp, with_image=True)
            out = os.path.join(tmp, 'source.md')
            display = os.path.join(tmp, 'source.images_display.json')
            inp = _write_input(os.path.join(tmp, 'input.json'), raw, snap)
            for path, content in ((out, 'OLD SOURCE\n'), (display, 'OLD MAP')):
                with open(path, 'w', encoding='utf-8') as handle:
                    handle.write(content)
            old_md, old_map = open(out, 'rb').read(), open(display, 'rb').read()
            cand_dir = os.path.join(tmp, 'candidate.json')
            os.mkdir(cand_dir)  # 真实失败目标：依据输出为已存在目录
            result = _run([snap, out,
                           '--source-adaptation', inp,
                           '--adaptation-output', cand_dir])
            self.assertEqual(result.returncode, 1)
            self.assertIn('整组发布失败', result.stderr)
            self.assertNotIn('旧产物未改动', result.stderr)  # 已替换的依据被恢复
            self.assertTrue(os.path.isdir(cand_dir))  # 目录目标不被改名备份
            self.assertEqual(open(out, 'rb').read(), old_md)
            self.assertEqual(open(display, 'rb').read(), old_map)
            self.assertEqual(_no_staging_left(tmp), [])


class ValidPublicationTest(unittest.TestCase):
    """正例：含图片三者均正确写出；无图片不回归（照旧不写空映射）。"""

    def test_parse_with_image_publishes_markdown_adaptation_display_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, snap = _write_snapshot(tmp, with_image=True)
            out = os.path.join(tmp, 'source.md')
            cand = os.path.join(tmp, 'candidate.json')
            inp = _write_input(os.path.join(tmp, 'input.json'), raw, snap)
            result = _run([snap, out,
                           '--source-adaptation', inp,
                           '--adaptation-output', cand])
            self.assertEqual(result.returncode, 0, result.stderr)
            md = open(out, encoding='utf-8').read()
            self.assertIn('[IMG: images/pic.svg]', md)
            candidate = json.load(open(cand, encoding='utf-8'))
            self.assertEqual(candidate['format'], 'latexml')
            self.assertTrue(any(c.get('content_type') == 'image'
                                for c in candidate['correspondences']))
            display = os.path.join(tmp, 'source.images_display.json')
            payload = json.load(open(display, encoding='utf-8'))
            self.assertEqual(payload['markdown'], 'source.md')
            self.assertEqual(payload['snapshot'], os.path.realpath(snap))
            self.assertTrue(payload['entries'])
            self.assertEqual(payload['entries'][0]['width']['value'], 8.0)
            self.assertEqual(reconcile_latexml_to_markdown(
                raw, md, None, candidate), [])
            self.assertEqual(_no_staging_left(tmp), [])

    def test_parse_without_image_writes_no_display_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, snap = _write_snapshot(tmp, with_image=False)
            out = os.path.join(tmp, 'source.md')
            cand = os.path.join(tmp, 'candidate.json')
            inp = _write_input(os.path.join(tmp, 'input.json'), raw, snap)
            result = _run([snap, out,
                           '--source-adaptation', inp,
                           '--adaptation-output', cand])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.isfile(out))
            candidate = json.load(open(cand, encoding='utf-8'))
            self.assertEqual(reconcile_latexml_to_markdown(
                raw, open(out, encoding='utf-8').read(), None, candidate), [])
            # 无图片保持现有行为：不写空尺寸映射
            self.assertFalse(os.path.exists(
                os.path.join(tmp, 'source.images_display.json')))
            self.assertEqual(_no_staging_left(tmp), [])


if __name__ == '__main__':
    unittest.main()
