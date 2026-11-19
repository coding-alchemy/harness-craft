"""Recompute a reading package and compare it to the actual files on disk."""

import hashlib
from html.parser import HTMLParser
from itertools import zip_longest
import json
from pathlib import Path
import re
from zipfile import BadZipFile

import pymupdf
from markdown_it import MarkdownIt

from reading import build_document, check_image, reading_files
from review import apply_review, assess, report_markdown


class _ImageSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.sources.add(dict(attrs).get('src') or '')


def _image_references(markdown):
    # Use the reading dialect so code, escaped examples and HTML tables get their actual meaning.
    reader = MarkdownIt('commonmark', {'html': True}).enable('table')
    images = _ImageSources()
    images.feed(reader.render(markdown))
    images.close()
    return images.sources


def package_file(bundle, name):
    """Resolve a known package member without traversing a symlink within the bundle."""
    target = bundle
    for part in Path(name).parts:
        target = target / part
        if target.is_symlink():
            raise ValueError(f'{name} 含符号链接')
    if not target.is_file():
        raise ValueError(f'{name} 缺失或不是普通文件')
    return target


def read_review(bundle):
    path = bundle / 'review.json'
    if not path.exists() and not path.is_symlink():
        return None
    try:
        result = json.loads(package_file(bundle, 'review.json').read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError(f'review.json 无法读取：{exc}') from exc
    if not isinstance(result, dict):
        raise ValueError('review.json 应为 JSON 对象')
    return result


def _first_difference(name, expected, actual):
    if name == 'source-map.json':
        try:
            old, new = json.loads(expected), json.loads(actual)
            if isinstance(new, dict):
                if old['source'] != new.get('source'):
                    return 'source-map.json 的源身份与原始包不符'
                for page, recorded in zip_longest(old['pages'], new.get('pages', [])):
                    if page != recorded and page:
                        return f'source-map.json 物理页 {page["page"]} 的来源记录不符'
                mapped = new.get('blocks')
                if isinstance(mapped, dict):
                    for block_id, block in old['blocks'].items():
                        if block != mapped.get(block_id):
                            return f'source-map.json 块 {block_id} 的来源记录不符'
        except (ValueError, TypeError):
            pass
        return 'source-map.json 与原始包重算结果不符'
    page, block_id, line_number = '', '', 1
    for line_number, (left, right) in enumerate(zip_longest(expected.splitlines(), actual.splitlines()), 1):
        if left is not None:
            if name == 'document.md':
                mark = re.fullmatch(r'\s*(?:- )?<!-- (page|block):([^ ]+) -->', left)
                if mark and mark[1] == 'page':
                    page, block_id = mark[2], ''
                elif mark:
                    block_id = mark[2]
            elif left:
                record = json.loads(left)
                page, block_id = record['page'], record['id']
        if left != right:
            break
    location = f' 物理页 {page}' if page else ''
    if block_id:
        location += f' 块 {block_id}'
    return f'{name} 第 {line_number} 行{location}与原始包重算结果不符'


def verify_bundle(bundle: Path, pdf: Path, *, check_report: bool = True) -> dict:
    """Independently check a candidate or an already published package without writing to it."""
    try:
        package_file(bundle, 'raw/source.json')
        package_file(bundle, 'raw/engine.zip')
        effective = apply_review(build_document(pdf, bundle / 'raw'), read_review(bundle))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, BadZipFile, pymupdf.mupdf.FzErrorBase) as exc:
        return assess({'pages': [], 'blocks': []}, [str(exc)])
    errors = []
    for name, expected in reading_files(effective).items():
        try:
            actual = package_file(bundle, name).read_bytes().decode('utf-8')
            if name == 'document.md':
                for src in sorted(_image_references(actual) - effective['assets'].keys()):
                    errors.append(f'document.md 图片引用未登记：{src!r}')
            if actual != expected:
                errors.append(_first_difference(name, expected, actual))
        except (OSError, ValueError) as exc:
            errors.append(f'{name} 无法核验：{exc}')
    for name, asset in effective['assets'].items():
        try:
            data = package_file(bundle, name).read_bytes()
            check_image(data)
            if hashlib.sha256(data).hexdigest() != asset['sha256']:
                raise ValueError('实际图片摘要与来源记录不符')
        except (OSError, ValueError) as exc:
            errors.append(f'{name} 无法核验：{exc}')
    result = assess(effective, errors)
    if check_report:
        try:
            actual = package_file(bundle, 'qa-report.md').read_bytes()
            if actual != report_markdown(result).encode('utf-8'):
                raise ValueError('落盘报告与本次重算结果不符')
        except (OSError, ValueError) as exc:
            errors.append(f'qa-report.md 无法核验：{exc}')
            result = assess(effective, errors)
    return result
