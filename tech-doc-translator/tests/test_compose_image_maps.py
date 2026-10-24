"""Cross-chapter composition uses each map's own base and source evidence."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
sys.path.insert(0, str(SCRIPTS))
import rebuild_images_display as rebuild
from PIL import Image


def make_project(root):
    maps, chapters = [], []
    for name, color, width in [('a', 'red', 40), ('b', 'blue', 90)]:
        chapter = root / name
        source = chapter / 'source'
        delivery = chapter / 'delivery'
        source.mkdir(parents=True)
        delivery.mkdir()
        for filename, shade in [('plot.png', color), ('shared.png', 'green'),
                                ('free.png', 'gray')]:
            Image.new('RGB', (160, 80), shade).save(source / filename)
            shutil.copyfile(source / filename, delivery / filename)
        html = source / 'page.html'
        html.write_text('<article><h1>Chapter</h1>'
                        '<img src="plot.png" width="%d">'
                        '<img src="shared.png" style="width:%dpx">'
                        '<img src="shared.png" height="30">'
                        '<img src="free.png"></article>' % (width, width * 2))
        md = delivery / 'chapter.md'
        md.write_text('# 章节 %s\n\n> **来源**：%s\n\n![图一](plot.png)\n\n![图二](shared.png)\n\n'
                      '![图三](shared.png)\n\n![图四](free.png)\n' % (name, html))
        manifest = chapter / 'manifest.json'
        manifest.write_text(json.dumps({
            'version': 1, 'source_version': 'test', 'family': 'single',
            'pages': [{'snapshot': str(html), 'markdown': str(md)}]}))
        output = delivery / 'export/images_display.json'
        rebuild.rebuild(str(manifest), str(output), str(chapter / 'work'))
        maps.append(output)
        chapters.append(md)
    return maps, chapters


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compose-images-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.maps, self.chapters = make_project(self.root)
        self.output = self.root / 'export/images_display.json'
        self.output.parent.mkdir()
        self.output.write_bytes(b'old map')
        self.before = [p.read_bytes() for p in self.maps]

    def compose(self, paths=None):
        return rebuild.compose_maps(paths or self.maps, str(self.output), str(self.root / 'work'))

    def assert_preserved(self):
        self.assertEqual(self.output.read_bytes(), b'old map')
        self.assertEqual([p.read_bytes() for p in self.maps], self.before)
        self.assertEqual(list(self.output.parent.glob('.compose-images-*')), [])

    def damage_map(self, callback):
        payload = json.loads(self.maps[0].read_text())
        callback(payload)
        self.maps[0].write_text(json.dumps(payload))
        self.before = [p.read_bytes() for p in self.maps]

    def test_cli_different_cwd_and_preserved_source_context(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'rebuild_images_display.py'),
                                 '--compose-map', str(self.maps[0]), '--compose-map', str(self.maps[1]),
                                 '--output', str(self.output)], cwd='/private/tmp', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(self.output.read_text())
        self.assertEqual(len(payload['entries']), 6)
        self.assertEqual(len(payload['undetermined']), 2)
        self.assertEqual([p.read_bytes() for p in self.maps], self.before)
        for kind, item, md, image in rebuild._checked_map_items(payload, self.output):
            self.assertEqual(Path(md).name, 'chapter.md')
            self.assertTrue(Path(image).is_file())
            self.assertTrue(os.path.isabs(item['source']['resource_base']))
            if item.get('derived'):
                self.assertEqual(item['derived']['resource'], 'shared.png')

    def test_duplicate_even_identical_and_output_input_collision(self):
        for paths in [self.maps + self.maps[:1], [self.maps[0], self.maps[0]]]:
            with self.assertRaisesRegex(rebuild.BindingError, '重复'):
                self.compose(paths)
            self.assert_preserved()
        with self.assertRaisesRegex(rebuild.RebuildError, '覆盖输入'):
            rebuild.compose_maps(self.maps, str(self.maps[0]), str(self.root))

    def test_missing_coverage_wrong_image_digest_width_and_source(self):
        original = json.loads(self.maps[0].read_text())
        for change in [lambda p: p['entries'].pop(),
                       lambda p: p['entries'][0].update(image=p['entries'][1]['image']),
                       lambda p: p['entries'][0].update(sha256='0' * 64),
                       lambda p: p['entries'][0]['width'].update(value=100),
                       lambda p: p['entries'][0]['source'].update(node='img[999]'),
                       lambda p: p['entries'][0]['source'].update(resource_base='source')]:
            self.maps[0].write_text(json.dumps(original))
            self.damage_map(change)
            with self.assertRaises((rebuild.RebuildError, rebuild.BindingError)):
                self.compose()
            self.assert_preserved()

    def test_moved_input_map_is_not_rebased_by_guessing(self):
        moved = self.root / 'moved.json'
        shutil.copyfile(self.maps[0], moved)
        with self.assertRaises((rebuild.RebuildError, OSError)):
            self.compose([moved, self.maps[1]])
        self.assert_preserved()

    def test_undetermined_cannot_be_promoted(self):
        def promote(payload):
            item = payload['undetermined'].pop()
            item['width'] = copy.deepcopy(payload['entries'][0]['width'])
            payload['entries'].append(item)
        self.damage_map(promote)
        with self.assertRaisesRegex(rebuild.RebuildError, '尺寸依据'):
            self.compose()
        self.assert_preserved()

    def test_candidate_rechecks_current_resources_before_replace(self):
        original = rebuild._checked_map_items
        calls = []
        def check(payload, path, protected_paths=None):
            calls.append(path)
            if len(calls) == 3:
                (self.chapters[0].parent / 'plot.png').write_bytes(b'changed')
            return original(payload, path, protected_paths)
        with patch.object(rebuild, '_checked_map_items', side_effect=check):
            with self.assertRaisesRegex(rebuild.RebuildError, '摘要不符'):
                self.compose()
        self.assert_preserved()

    def test_replace_failure_preserves_inputs_and_old_output(self):
        with patch('_image_binding.os.replace', side_effect=OSError('replace failed')):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                self.compose()
        self.assert_preserved()

    def test_cli_output_cannot_replace_referenced_files_or_aliases(self):
        payload = json.loads(self.maps[0].read_text())
        item = payload['entries'][0]
        snapshot = Path(item['source']['snapshot'])
        source_image = snapshot.parent / 'plot.png'
        delivered_image = self.chapters[0].parent / 'plot.png'
        symlink = self.root / 'snapshot-alias.html'
        symlink.symlink_to(snapshot)
        hardlink = self.root / 'snapshot-hardlink.html'
        os.link(snapshot, hardlink)
        targets = [snapshot, source_image, self.chapters[0], delivered_image,
                   self.maps[0], symlink, hardlink]
        before = {path: path.read_bytes() for path in targets}
        for target in targets:
            with self.subTest(target=target), self.assertRaisesRegex(
                    rebuild.RebuildError, '覆盖'):
                try:
                    result = subprocess.run([
                        sys.executable, str(SCRIPTS / 'rebuild_images_display.py'),
                        '--compose-map', str(self.maps[0]), '--compose-map', str(self.maps[1]),
                        '--output', str(target)], cwd='/private/tmp',
                        capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(target.read_bytes(), before[target])
                    self.assertEqual(snapshot.read_bytes(), before[snapshot])
                    # Check the function's refusal too; no CLI-only protection.
                    rebuild.compose_maps(self.maps, str(target), str(self.root))
                finally:
                    for path, data in before.items():
                        path.write_bytes(data)
        self.assert_preserved()

    def test_output_cannot_replace_recursive_svg_source_or_delivery_dependency(self):
        snapshot = self.root / 'a/source/page.html'
        for base in [snapshot.parent, self.chapters[0].parent]:
            shutil.copyfile(base / 'free.png', base / 'nested.png')
            (base / 'plot.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" '
                'width="160" height="80"><image href="nested.png" width="160" height="80"/></svg>')
        snapshot.write_text(snapshot.read_text().replace('plot.png', 'plot.svg'))
        self.chapters[0].write_text(self.chapters[0].read_text().replace('plot.png', 'plot.svg'))
        rebuild.rebuild(str(self.root / 'a/manifest.json'), str(self.maps[0]), str(self.root / 'work'))
        self.before = [p.read_bytes() for p in self.maps]
        for target in [snapshot.parent / 'nested.png', self.chapters[0].parent / 'nested.png']:
            before = target.read_bytes()
            with self.assertRaisesRegex(rebuild.RebuildError, '覆盖'):
                rebuild.compose_maps(self.maps, str(target), str(self.root))
            self.assertEqual(target.read_bytes(), before)
        self.assert_preserved()

    def test_empty_declared_chapter_is_not_dropped_from_coverage(self):
        self.damage_map(lambda p: p.update(entries=[], undetermined=[]))
        with self.assertRaisesRegex(rebuild.BindingError, '覆盖'):
            self.compose()
        self.assert_preserved()

    def test_declared_empty_document_with_no_images_remains_valid(self):
        empty = self.root / 'empty.md'
        empty.write_text('# Empty\n\nNo images.\n')
        mapping = self.root / 'empty.json'
        mapping.write_text(json.dumps({'version': 1, 'markdown': 'empty.md',
                                       'entries': [], 'undetermined': []}))
        self.compose([mapping, self.maps[1]])

    def test_top_level_declaration_is_checked_even_with_other_entry_documents(self):
        declared = self.chapters[0].parent / 'other.md'
        declared.write_text('![missing occurrence](plot.png)\n')
        self.damage_map(lambda p: p.update(markdown='../other.md'))
        with self.assertRaisesRegex(rebuild.BindingError, '覆盖'):
            self.compose()
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
