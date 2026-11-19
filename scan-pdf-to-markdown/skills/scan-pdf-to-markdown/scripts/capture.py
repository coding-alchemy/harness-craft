"""Capture one whole-document MinerU result and bind it to its source PDF."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

import pymupdf


class CaptureError(ValueError):
    """The PDF or raw engine result could not be captured or verified."""


def _digest(stream):
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    stream.seek(0)
    return digest


def _pdf_identity(pdf):
    try:
        with pdf.open('rb') as stream:
            digest = _digest(stream)
            size = os.fstat(stream.fileno()).st_size
        with pymupdf.open(pdf, filetype='pdf') as source:
            if not source.is_pdf or source.needs_pass or not len(source):
                raise ValueError('需要未加密且含至少一页的 PDF')
            pages = [
                {'page': page.number + 1, 'cropbox': list(page.cropbox), 'rotation': page.rotation}
                for page in source
            ]
    except (OSError, RuntimeError, ValueError) as exc:
        raise CaptureError(f'源 PDF {pdf} 无法读取：{exc}') from exc
    return {'pdf_sha256': digest, 'pdf_bytes': size, 'page_count': len(pages), 'pages': pages}


def check_source(pdf: Path, identity: dict) -> None:
    actual = _pdf_identity(pdf)
    for key, value in actual.items():
        if identity.get(key) != value:
            raise CaptureError(f'源 PDF {pdf} 与 raw/source.json 不符（{key}）')


def _read_object(read, label):
    try:
        value = json.loads(read())
    except (KeyError, OSError, ValueError, BadZipFile) as exc:
        raise CaptureError(f'{label} 无法读取：{exc}') from exc
    if not isinstance(value, dict):
        raise CaptureError(f'{label} 应为 JSON 对象')
    return value


def _read_pages(payload, member, count):
    pages = payload.get('pages')
    if payload.get('is_full_document') is not True:
        raise CaptureError(f'{member}: is_full_document 必须为 true')
    if not isinstance(pages, list) or len(pages) != count:
        raise CaptureError(f'{member}: 页覆盖不符，预期 {count} 个物理页')
    for index, page in enumerate(pages):
        location = f'{member} 第 {index + 1} 物理页'
        if not isinstance(page, dict) or type(page.get('page_idx')) is not int or page['page_idx'] != index:
            raise CaptureError(f'{location}: page_idx 应为 {index}')
        blocks = page.get('blocks')
        if not isinstance(blocks, list) or any(
            not isinstance(block, dict) or not isinstance(block.get('type'), str) for block in blocks
        ):
            raise CaptureError(f'{location}: blocks 或块类型无效')
    return pages


def _read_engine(path, count, expected_digest=None):
    middle_name = 'middle_json.json'
    structured_name = 'structured_content.json'
    try:
        with path.open('rb') as stream:
            digest = _digest(stream)
            if expected_digest is not None and digest != expected_digest:
                raise CaptureError(f'{path}: ZIP 摘要与 raw/source.json 不符')
            with ZipFile(stream) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise CaptureError(f'{path}: ZIP 成员名重复')
                middle = _read_object(lambda: archive.read(middle_name), middle_name)
                structured = _read_object(lambda: archive.read(structured_name), structured_name)
    except (OSError, BadZipFile) as exc:
        raise CaptureError(f'{path} 无法读取：{exc}') from exc
    if (middle.get('schema'), middle.get('schema_version')) != ('docvortex.middle', '2.0'):
        raise CaptureError(f'{middle_name}: 需要 docvortex.middle 2.0')
    middle_pages = _read_pages(middle, middle_name, count)
    structured_pages = _read_pages(structured, structured_name, count)
    for page, view in zip(middle_pages, structured_pages):
        blocks = page['blocks']
        indices = [block.get('index') for block in blocks]
        if any(type(index) is not int or index < 0 for index in indices) or indices != sorted(set(indices)):
            raise CaptureError(f'{middle_name} 第 {page["page_idx"] + 1} 物理页: 块 index 无效或乱序')
        if [block['type'] for block in blocks] != [block['type'] for block in view['blocks']]:
            raise CaptureError(f'{structured_name} 第 {page["page_idx"] + 1} 物理页: 块类型或顺序不一致')
        for original, block in zip(blocks, view['blocks']):
            index = original['index']
            if block.get('index', index) != index or block.get('bbox') != original.get('bbox'):
                raise CaptureError(
                    f'{structured_name} 第 {page["page_idx"] + 1} 物理页: 块 {index} 与原始记录不一致'
                )
    try:
        version = middle['metadata']['producer']['version']
        mineru = middle['extensions']['mineru']
        tier, mode = mineru['tier'], mineru['parse_mode']
        if not isinstance(version, str) or not version.startswith('4.') or (tier, mode) != ('basic', 'ocr'):
            raise ValueError('需要 MinerU 4.x、Basic 档、整页 OCR 模式')
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureError(f'{middle_name}: 引擎版本、档位或模式无效（{exc}）') from exc
    engine = {'version': version, 'tier': tier, 'parse_mode': mode}
    return middle, structured, digest, engine


def _ocr_environment():
    env = dict(os.environ, MINERU_MODEL_SOURCE='local', MINERU_TELEMETRY_DISABLED='1',
               MINERU_LLM_AIDED_FEATURES_TITLE_LEVELING='false',
               MINERU_LLM_AIDED_FEATURES_CROSS_PAGE_TABLE_CELL_MERGE='false')
    config_path = Path(env.get('MINERU_CONFIG') or
                       Path(env.get('MINERU_HOME') or '~/.mineru') / 'config.yaml').expanduser()
    model = {}
    if config_path.is_file():
        import yaml
        try:
            settings = yaml.safe_load(config_path.read_bytes())
        except yaml.YAMLError as exc:
            raise CaptureError(f'MinerU 配置 {config_path} 无法读取：{exc}') from exc
        if isinstance(settings, dict) and isinstance(settings.get('model'), dict):
            model = settings['model']
    for key, default in [('small_backend', 'onnx'), ('onnx_device', 'cpu')]:
        if key not in model:
            env.setdefault('MINERU_MODEL_' + key.upper(), default)
    return env


def capture_raw(pdf: Path, raw_dir: Path) -> None:
    """Read only the PDF, run local OCR on a snapshot, and save the validated raw pack."""
    with TemporaryDirectory(prefix='.capture-', dir=raw_dir.parent) as temporary:
        staging = Path(temporary)
        snapshot = staging / 'input.pdf'
        try:
            shutil.copyfile(pdf, snapshot)
            snapshot.chmod(0o400)
        except OSError as exc:
            raise CaptureError(f'无法创建源 PDF {pdf} 的快照：{exc}') from exc
        identity = _pdf_identity(snapshot)
        zip_path = staging / 'engine.zip'
        installed = Path(sys.executable).with_name('mineru-kit')
        exe = str(installed) if installed.is_file() else 'mineru-kit'
        command = [exe, 'parse', str(snapshot), '--pages', 'all', '--tier', 'basic',
                   '--ocr-mode', 'ocr', '--format', 'zip', '-o', str(zip_path)]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                env=_ocr_environment(),
            )
        except OSError as exc:
            raise CaptureError(f'无法启动本地 mineru-kit，请检查 OCR 环境：{exc}') from exc
        if result.returncode:
            detail = (result.stderr.strip() or result.stdout.strip())[-4000:]
            raise CaptureError(f'本地 MinerU 识别失败（退出码 {result.returncode}）：{detail}')
        _, _, digest, engine = _read_engine(zip_path, identity['page_count'])
        check_source(pdf, identity)
        identity.update(zip_sha256=digest, engine=engine)
        manifest = staging / 'source.json'
        manifest.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raw_dir.mkdir()
        try:
            zip_path.rename(raw_dir / zip_path.name)
            manifest.rename(raw_dir / manifest.name)
        except OSError:
            shutil.rmtree(raw_dir)
            raise


def read_raw(pdf: Path, raw_dir: Path) -> dict:
    """Check the original source and engine result without importing or launching OCR."""
    manifest = raw_dir / 'source.json'
    source = _read_object(manifest.read_bytes, str(manifest))
    check_source(pdf, source)
    expected_digest = source.get('zip_sha256')
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise CaptureError(f'{manifest}: zip_sha256 无效')
    middle, structured, _, engine = _read_engine(raw_dir / 'engine.zip', source['page_count'], expected_digest)
    if source.get('engine') != engine:
        raise CaptureError(f'{manifest}: 引擎元数据与 engine.zip 不符')
    return {'source': source, 'middle': middle, 'structured': structured}
