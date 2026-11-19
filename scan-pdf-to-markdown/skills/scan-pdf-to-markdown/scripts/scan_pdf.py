#!/usr/bin/env python3
"""Capture, rebuild, or verify a local scanned PDF reading package."""

import argparse
import ctypes
import os
from pathlib import Path
import shutil
import sys
from tempfile import mkdtemp
from zipfile import BadZipFile

sys.dont_write_bytecode = True

try:
    import pymupdf
    from verify import package_file, read_review, verify_bundle
except ModuleNotFoundError as exc:
    if __name__ != '__main__' or exc.name not in {'pymupdf', 'markdown_it', 'mdurl'}:
        raise
    print(f'结论：失败\n- 缺少 {exc.name}，请安装 Skill 内 requirements.txt 的读取依赖。')
    raise SystemExit(1) from None

from capture import capture_raw, check_source
from reading import build_document, write_reading
from review import apply_review, write_report


def publish_new(candidate: Path, target: Path) -> None:
    """Publish with an exclusive directory rename in the target filesystem."""
    try:
        rename = ctypes.CDLL(None, use_errno=True).renamex_np
    except AttributeError as exc:
        raise OSError('当前平台没有可用的排他目录重命名操作') from exc
    rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    rename_excl = 0x00000004  # macOS <sys/stdio.h> RENAME_EXCL
    if rename(os.fsencode(candidate), os.fsencode(target), rename_excl) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def _copy_raw(source, candidate, explicit_review):
    raw = candidate / 'raw'
    raw.mkdir()
    for name in ('source.json', 'engine.zip'):
        shutil.copyfile(package_file(source, f'raw/{name}'), raw / name)
    if explicit_review is not None:
        shutil.copyfile(explicit_review, candidate / 'review.json')
    elif (source / 'review.json').exists() or (source / 'review.json').is_symlink():
        shutil.copyfile(package_file(source, 'review.json'), candidate / 'review.json')


def _show(result, *, output=None, candidate=None):
    print(f'结论：{result["status"]}')
    for reason in result['reasons']:
        print(f'- {reason}')
    if output is not None:
        print(f'正文：{output / "document.md"}')
        print(f'报告：{output / "qa-report.md"}')
    if candidate is not None:
        print(f'候选目录：{candidate}')
        print(f'诊断报告：{candidate / "qa-report.md"}')
    return 1 if result['status'] == '失败' else 0


def _generate(args):
    target = args.output.expanduser().absolute()
    if os.path.lexists(target):
        raise FileExistsError(f'目标已存在：{target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(mkdtemp(prefix='.scan-pdf-candidate-', dir=target.parent))
    cleanup = True
    try:
        if args.command == 'parse':
            pdf = args.pdf.expanduser().absolute()
            capture_raw(pdf, candidate / 'raw')
        else:
            pdf = args.source_pdf.expanduser().absolute()
            _copy_raw(args.bundle.expanduser(), candidate, args.review.expanduser() if args.review else None)
        document = build_document(pdf, candidate / 'raw')
        write_reading(apply_review(document, read_review(candidate)), candidate)
        result = verify_bundle(candidate, pdf, check_report=False)
        write_report(result, candidate)
        if result['status'] == '失败':
            cleanup = bool(result['integrity_errors'])
            return _show(result, candidate=None if cleanup else candidate)
        check_source(pdf, document['source'])
        publish_new(candidate, target)
        cleanup = False
        return _show(result, output=target)
    finally:
        if cleanup:
            shutil.rmtree(candidate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='生成可逐块查回原页的扫描 PDF 阅读包。')
    commands = parser.add_subparsers(dest='command', required=True)
    parse = commands.add_parser('parse', help='整本本地 OCR 并生成阅读包')
    parse.add_argument('pdf', type=Path)
    parse.add_argument('--output', type=Path, required=True)
    render = commands.add_parser('render', help='使用原始包免 OCR 重建')
    render.add_argument('bundle', type=Path)
    render.add_argument('--source-pdf', type=Path, required=True)
    render.add_argument('--output', type=Path, required=True)
    render.add_argument('--review', type=Path)
    verify = commands.add_parser('verify', help='只读核验落盘结果')
    verify.add_argument('bundle', type=Path)
    verify.add_argument('--source-pdf', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            return _show(verify_bundle(args.bundle.expanduser(), args.source_pdf.expanduser()))
        return _generate(args)
    except KeyboardInterrupt:
        return _show({'status': '失败', 'reasons': ['操作已中断']})
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, BadZipFile, pymupdf.mupdf.FzErrorBase) as exc:
        return _show({'status': '失败', 'reasons': [str(exc)]})


if __name__ == '__main__':
    raise SystemExit(main())
