"""第 2 批 R14：清理后只读核对——证据索引、交付根文件、发布副本与已删源文件。"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import build_toc
import verify_delivery as delivery
from test_delivery_toc_roles import toc_project  # noqa: F401 — 复用 pytest 夹具

SCRIPT = Path(delivery.__file__)


@pytest.fixture
def published(toc_project):
    """按现行门禁真实发布一次：复核闭合后 --evidence-dir 写出证据索引。"""
    root, toc, manifest, record = toc_project
    toc.write_text(build_toc.build(manifest, toc)[0])
    record = delivery.prepare_reviews(root, record)
    for review in record['reviews']:
        review.update(status='closed', note='测试人工处置记录')
    record_path = root / 'source/record.json'
    record_path.write_text(json.dumps(record, ensure_ascii=False))
    evidence = Path(tempfile.mkdtemp(prefix='tdt-after-cleanup-', dir=Path.home() / '.cache'))
    run = subprocess.run([sys.executable, str(SCRIPT), '--record', str(record_path),
                          '--evidence-dir', str(evidence)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    yield root, record_path, evidence
    shutil.rmtree(evidence, ignore_errors=True)


def after_cleanup(record_path, evidence, *published_roots):
    command = [sys.executable, str(SCRIPT), '--record', str(record_path),
               '--evidence-dir', str(evidence), '--after-cleanup']
    for base in published_roots:
        command += ['--published-root', str(base)]
    return subprocess.run(command, capture_output=True, text=True, timeout=60)


def test_untouched_delivery_passes(published):
    _root, record_path, evidence = published
    run = after_cleanup(record_path, evidence)
    assert run.returncode == 0, run.stderr
    assert '清理后核对通过' in run.stdout
    assert '在场一致（2）：00_目录.md、01_正文.md' in run.stdout
    assert '已删除、只存摘要（0）：无' in run.stdout


def test_published_copy_and_deleted_snapshot(published, tmp_path_factory):
    root, record_path, evidence = published
    copies = tmp_path_factory.mktemp('published')     # 交付根就是 tmp_path，副本另放
    shutil.copy(root / '01_正文.md', copies / '01_正文.md')
    (root / '01_正文.md').unlink()
    (root / 'source/page.html').unlink()
    run = after_cleanup(record_path, evidence, copies / 'missing', copies)
    assert run.returncode == 0, run.stderr
    assert '发布副本一致（1）：01_正文.md → %s' % (copies / '01_正文.md') in run.stdout
    assert 'source/page.html' in run.stdout.split('已删除、只存摘要')[1]


def test_modified_published_copy_fails(published, tmp_path_factory):
    # 路线图 §3 审查重点 5：发布副本被改过，清理后核对必须失败
    root, record_path, evidence = published
    copies = tmp_path_factory.mktemp('published')
    (copies / '01_正文.md').write_text((root / '01_正文.md').read_text() + '改动\n')
    (root / '01_正文.md').unlink()
    run = after_cleanup(record_path, evidence, copies)
    assert run.returncode == 1
    assert '01_正文.md 不在交付根，也没有摘要一致的发布副本' in run.stderr


def test_changed_root_file_or_batch_file_fails(published):
    root, record_path, evidence = published
    index = json.loads((evidence / 'delivery_index.json').read_text())
    (evidence / index['sources_report']).unlink()
    (root / '00_目录.md').write_text((root / '00_目录.md').read_text() + '\n')
    run = after_cleanup(record_path, evidence)
    assert run.returncode == 1
    assert '证据批次文件缺失: %s' % index['sources_report'] in run.stderr
    assert '交付根文件与索引摘要不符: 00_目录.md' in run.stderr


def test_record_changed_after_publish_fails(published):
    _root, record_path, evidence = published
    record = json.loads(record_path.read_text())
    record['reviews'][0]['note'] = '发布后改过'
    record_path.write_text(json.dumps(record, ensure_ascii=False))
    run = after_cleanup(record_path, evidence)
    assert run.returncode == 1
    assert '证据索引的 reviews 与交付记录不一致' in run.stderr


def test_after_cleanup_requires_evidence_dir(published):
    _root, record_path, _evidence = published
    run = subprocess.run([sys.executable, str(SCRIPT), '--record', str(record_path),
                          '--prepare-reviews', '/tmp/x.json', '--after-cleanup'],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 2 and '--after-cleanup 需要 --evidence-dir' in run.stderr


def test_published_root_requires_after_cleanup(tmp_path):
    run = subprocess.run([sys.executable, str(SCRIPT), '--record', str(tmp_path / 'record.json'),
                          '--evidence-dir', str(tmp_path / 'evidence'),
                          '--published-root', str(tmp_path)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 2, run.stderr
    assert '--published-root 只能和 --after-cleanup 一起用' in run.stderr
