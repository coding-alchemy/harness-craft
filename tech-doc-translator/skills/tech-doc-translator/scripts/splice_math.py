#!/usr/bin/env python3
"""按原出现顺序回填完整数学切片，生成一个新译文候选。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from _verification import scan_math


PLACEHOLDER = re.compile(r'⟦m[^⟦⟧\r\n]*⟧|⟦m')


def splice_math(source_text: str, draft_text: str, *, source_context=None) -> str:
    source = scan_math(source_text, source_context=source_context)
    if source.issues:
        raise ValueError(f'源文数学定界未解决: {source.issues[0]}')

    pieces = []
    expected = []
    cursor = offset = 0
    for number, match in enumerate(PLACEHOLDER.finditer(draft_text), start=1):
        token = f'⟦m{number}⟧'
        if number > len(source.spans) or match[0] != token:
            line = draft_text.count('\n', 0, match.start()) + 1
            raise ValueError(f'草稿 L{line} 占位未知、重复或乱序: {match[0]!r}（预期 {token}）')
        span = source.spans[number - 1]
        preceding = draft_text[cursor:match.start()]
        offset += len(preceding)
        expected.append((offset, offset + len(span.raw), span.kind, span.raw))
        pieces.extend((preceding, span.raw))
        offset += len(span.raw)
        cursor = match.end()

    if len(expected) != len(source.spans):
        raise ValueError(f'草稿占位缺失: 源 {len(source.spans)} 处，草稿 {len(expected)} 处')
    pieces.append(draft_text[cursor:])
    result = ''.join(pieces)
    assembled = scan_math(result, source_context=source_context)
    if assembled.issues:
        raise ValueError(f'候选数学定界未解决: {assembled.issues[0]}')
    actual = [(span.start, span.end, span.kind, span.raw) for span in assembled.spans]
    if actual != expected:
        raise ValueError('候选数学位置、类型或原切片不符（核对额外数学和占位的实际宿主）')
    return result


def _source_context(args, source_text):
    import _pdf_math

    meta = _pdf_math.metadata(source_text)
    declaration = meta.get('source_adaptations')
    declared = json.loads(declaration) if declaration is not None else []
    if 'source_adaptation' in meta:
        if declaration is not None:
            raise ValueError('源包的来源依据声明冲突')
        declared = [meta['source_adaptation'].strip('"')]
    if declared and not args.source_adaptation:
        raise ValueError('源包声明 LaTeXML 来源依据，须提供 --source-adaptation')
    if args.project_context or 'pdf_formula_contract' in meta:
        view, source_range, _ = _pdf_math.translation_view(
            str(args.source), args.project_context, with_context=True)
        if view is None:
            raise ValueError('--project-context 未准入对应的 PDF 确认数学')
        if 'source_file' in meta:
            _pdf_math.check_fragment(view, *source_range, None)
        return _pdf_math.context(view['checklist'])
    if not args.source_adaptation:
        return None

    import _latexml_source as latexml
    from recover_work_packages import _frontmatter, _load_source_adaptation

    provided = [Path(path).resolve() for path in args.source_adaptation]
    if declared and [Path(path).resolve() for path in declared] != provided:
        raise ValueError('源包声明的来源依据和实际 --source-adaptation 不一致')
    full_text = source_text
    if 'source_file' in meta:
        if not declared:
            raise ValueError('源包缺少 LaTeXML 来源依据声明，须从已准入的全源重新拆包')
        full_text = Path(meta['source_file'].strip('"')).read_bytes().decode('utf-8')
        start, end = int(meta['source_char_start']), int(meta['source_char_end'])
        _, body = _frontmatter(args.source)
        if not 0 <= start < end <= len(full_text) or full_text[start:end] != body:
            raise ValueError('实际源包与当前全源字符范围不符')
        if hashlib.sha256(body.encode()).hexdigest() != meta.get('fragment_digest'):
            raise ValueError('源包摘要未绑定实际正文')
    payload, _, _ = _load_source_adaptation([str(path) for path in provided], full_text)
    return latexml.scan_context_from_payload(payload)


def _write_candidate(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.splice-math-',
                                         delete=False) as handle:
            temporary = handle.name
            handle.write(text.encode('utf-8'))
        os.link(temporary, path)
    finally:
        if temporary is not None:
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--draft', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    basis = parser.add_mutually_exclusive_group()
    basis.add_argument('--source-adaptation', action='append', default=[])
    basis.add_argument('--project-context')
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError(f'候选输出已存在或与受保护输入同址: {args.output}')
        source = args.source.read_bytes().decode('utf-8')
        draft = args.draft.read_bytes().decode('utf-8')
        source_context = _source_context(args, source)
        result = splice_math(source, draft, source_context=source_context)
        _write_candidate(args.output, result)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f'数学装配拒绝: {exc}', file=sys.stderr)
        return 2
    print(f'数学装配候选: {args.output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
