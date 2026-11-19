"""第 2 批 R10：身份变化报错列出变化的键与文件，不判断是不是首跑。"""
import copy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import build_toc
import verify_delivery as delivery
from test_delivery_toc_roles import toc_project  # noqa: F401 — 复用 pytest 夹具

A, B, C = 'a' * 64, 'b' * 64, 'c' * 64
BASE = {
    'inputs': {'01_章.md': A},
    'outputs': {'book.pdf': A},
    'resources': {'inputs': {'01_章.md': [['images/f.svg', A]]}},
    'sources': [{'parsed_markdown': 'source/source.md', 'parsed_sha256': A,
                 'snapshots': [{'snapshot': 'source/page.html', 'snapshot_sha256': A,
                                'per_stem_map': {'path': 'source/map.json', 'sha256': A}}]}],
    'checks': [{'order': 1, 'tool': 'verify_pdf',
                'facts': {'script_sha256': A, 'shared_deps': {'_verification.py': A},
                          'files': {'export_report': ['/w/export_report.json', A]}}}],
    'environment': {'python': '3.12.7'},
    'delivery_entry': {'script_sha256': A},
}


def changed(**edits):
    after = copy.deepcopy(BASE)
    for path, value in edits.items():
        node = after
        *parents, last = path.split('/')
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(last) if last.isdigit() else last] = value
    return delivery._identity_changes(BASE, after)


def test_unchanged_identity_has_no_changes():
    assert delivery._identity_changes(BASE, copy.deepcopy(BASE)) == ([], [], 0)


@pytest.mark.parametrize('edit, key, name', [
    ({'inputs/01_章.md': B}, 'inputs', '01_章.md'),
    ({'resources/inputs/01_章.md/0/1': B}, 'resources', 'images/f.svg'),
    ({'sources/0/parsed_sha256': B}, 'sources', 'source/source.md'),
    ({'sources/0/snapshots/0/snapshot_sha256': B}, 'sources', 'source/page.html'),
    ({'sources/0/snapshots/0/per_stem_map/sha256': B}, 'sources', 'source/map.json'),
    ({'checks/0/facts/files/export_report/1': B}, 'checks', '/w/export_report.json'),
    ({'checks/0/facts/shared_deps/_verification.py': B}, 'checks', '_verification.py'),
    ({'checks/0/facts/script_sha256': B}, 'checks', 'verify_pdf'),
    ({'delivery_entry/script_sha256': B}, 'delivery_entry', 'delivery_entry'),
])
def test_changed_file_is_named(edit, key, name):
    keys, files, total = changed(**edit)
    assert keys == [key] and files == [name] and total == 1


def test_added_resource_and_version_change():
    keys, files, _ = changed(**{'resources/inputs/01_章.md': [['images/f.svg', A], ['images/g.png', C]],
                                'environment/python': '3.12.8'})
    assert keys == ['environment', 'resources'] and files == ['images/g.png']


def test_file_list_is_bounded():
    after = copy.deepcopy(BASE)
    after['inputs'] = {'%02d.md' % n: B for n in range(8)}
    _, files, total = delivery._identity_changes(BASE, after)
    assert len(files) == 5 and total == 9          # 8 个新输入 + 被删的 01_章.md
    text = delivery._identity_change_text(BASE, after)
    assert text.startswith('依赖身份在运行期间变化：inputs；变化的文件：') and text.endswith(' 等 9 个')
    assert '首' not in text


def test_prepare_reviews_names_file_changed_during_run(toc_project):
    root, toc, manifest, record = toc_project
    toc.write_text(build_toc.build(manifest, toc)[0])
    snapshot = root / 'source/page.html'
    original = delivery.expected_review_binding

    def touch_then_bind(*args, **kwargs):
        if 'changed' not in snapshot.read_text():
            snapshot.write_text(snapshot.read_text() + '<!-- changed -->')
        return original(*args, **kwargs)

    with patch.object(delivery, 'expected_review_binding', side_effect=touch_then_bind):
        with pytest.raises(delivery.DeliveryError) as caught:
            delivery.prepare_reviews(root, record)
    message = str(caught.value)
    assert message.startswith('准备候选时依赖身份在运行期间变化：sources；变化的文件：source/page.html')
