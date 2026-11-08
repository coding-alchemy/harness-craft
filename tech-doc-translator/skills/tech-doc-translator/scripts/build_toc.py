#!/usr/bin/env python3
"""按已确认官方清单与实际标题实例生成独立目录，不修改章节。"""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from export_pdf import (heading_targets, build_markdown, scan_math,
                        BeautifulSoup, Chapter, ExportError, TOC_FILE_NAME,
                        decide_toc_provenance, load_view_declaration,
                        project_view_declared)
from _html_fidelity import escape_text_backslashes
from _verification import heading_title_matches

START = '[tdt-toc-start]: #'
END = '[tdt-toc-end]: #'


def _read_basis(manifest_path, output):
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError('目录依据清单必须是对象')
    root = Path(manifest.get('project_root',manifest_path.parent)).resolve()
    if output.name != TOC_FILE_NAME:
        raise ValueError('输出必须保留目录角色文件名 '+TOC_FILE_NAME)
    basis = manifest.get('official_basis')
    if not isinstance(basis,dict) or not basis.get('confirmation') or not manifest.get('scope'):
        raise ValueError('缺少独立官方依据及已确认范围')
    basis_path = (root/basis['path']).resolve()
    if output in (manifest_path,basis_path):
        raise ValueError('输出不得覆盖官方依据/清单')
    basis_raw = basis_path.read_bytes()
    official = basis_raw.decode('utf-8').splitlines()
    entries = manifest.get('entries')
    if not isinstance(entries,list) or not entries:
        raise ValueError('官方条目未关联')
    files, tables, rendered, seen, positions, expected = {}, {}, [], set(), [], []
    for entry in entries:
        position = entry['official_line']
        if not isinstance(position,int) or not 1 <= position <= len(official):
            raise ValueError('官方条目位置越界')
        if official[position-1].strip() != entry['original_title']:
            raise ValueError('原题与独立官方依据不符')
        positions.append(position)
        path = (root/entry['translation']).resolve()
        if path == output or path in (manifest_path,basis_path):
            raise ValueError('目录/只读输入与章节路径冲突')
        if path not in files:
            files[path] = path.read_bytes()
            tables[path] = heading_targets(files[path].decode('utf-8'))
        headings, targets = tables[path]
        matches = [h for h in headings if heading_title_matches(entry['original_title'],h['text'])]
        occurrence = entry.get('occurrence')
        if not isinstance(occurrence,int) or not 1 <= occurrence <= len(matches):
            raise ValueError('标题出现必须明确对应，不能借第一个同名标题: '+entry['original_title'])
        heading = matches[occurrence-1]
        identity = (path,heading['slug'])
        if identity in seen:
            raise ValueError('官方条目重复关联同一标题出现')
        seen.add(identity)
        if entry['level'] != (heading['source_level'] or heading['level']):
            raise ValueError('官方/译文章节层级不符')
        fragment = entry.get('fragment',heading['slug'])
        if fragment != heading['slug'] or fragment not in targets:
            raise ValueError('条目片段不对应实际标题出现')
        relative = quote(os.path.relpath(path,output.parent).replace(os.sep,'/'),safe='/')
        href = relative+'#'+quote(fragment,safe='')
        text = escape_text_backslashes(heading['text'], literal=True)
        number = str(entry.get('number',''))
        if number and not entry['original_title'].startswith(number):
            raise ValueError('编号与独立官方原题不符: '+entry['original_title'])
        label = (number+' ' if number and not heading['text'].startswith(number) else '')+heading['text']
        first_h1 = next((h for h in headings if h["level"] == 1), None)
        expected.append({"label": label, "target_path": str(path),
                         "fragment": fragment, "official_line": position,
                         "original": entry["original_title"], "heading": heading["text"],
                         "implicit_h1": first_h1 == heading})
        rendered.append('  '*(entry['level']-1)+'- ['+(number+' ' if number and not heading['text'].startswith(number) else '')+text+']('+href+')')
    if positions != sorted(set(positions)):
        raise ValueError('清单顺序与官方顺序不符/重复')
    declared = manifest.get('official_lines')
    if not isinstance(declared,list) or declared != positions:
        raise ValueError('已确认范围必须逐条声明，漏关联/范围外条目拒绝')
    return str(manifest["scope"]), expected, rendered, files, {
        manifest_path: manifest_bytes, basis_path: basis_raw, **files,
    }


def _target_of(href, toc_path):
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or parts.query or not parts.path:
        raise ValueError('目录链接必须定位本地章节: ' + href)
    return str((toc_path.parent / unquote(parts.path)).resolve()), unquote(parts.fragment)


def _table_entries(table, line):
    rows = table.find_all('tr')
    header = ['官方原题', '译文标题', '位置']
    if not rows or [cell.get_text().strip() for cell in rows[0].find_all('th')] != header:
        raise ValueError('目录 L%d 的表头须能区分官方原题、译文标题和位置' % line)
    for offset, row in enumerate(rows[1:], 2):
        row_line = int(row.get('data-toc-line', line + offset))
        cells = row.find_all('td', recursive=False)
        if len(cells) != 3 or any(cell.find('img') for cell in cells):
            raise ValueError('目录 L%d 的表格数据行须含三个导航字段' % row_line)
        if any(cell.find('a') for cell in cells[:2]):
            raise ValueError('目录 L%d 的表格标签列含非导航链接' % row_line)
        yield _only_link(str(cells[2]), row_line), row_line, tuple(
            cell.get_text().strip() for cell in cells[:2])


def _only_link(markup, line):
    fragment = BeautifulSoup(markup, 'html.parser')
    links = fragment.find_all('a', href=True)
    if len(links) != 1 or fragment.find('img'):
        raise ValueError('目录 L%d 的每个导航项须对应一条链接' % line)
    anchor = links[0].extract()
    if fragment.get_text(strip=True) or any(tag.name not in ('p', 'td')
                                            for tag in fragment.find_all()):
        raise ValueError('目录 L%d 的导航项夹带未核验文字' % line)
    return anchor


def _navigation(text, scope, region=None):
    scan = scan_math(text)
    if scan.issues:
        raise ValueError('实际目录标签存在未解决数学定界')
    md, _ = build_markdown([], '', scan.spans, text, highlight=False)
    env = {}
    tokens = md.parse(text, env)
    for token in tokens:
        if token.map:
            token.attrSet('data-toc-line', str(token.map[0] + 1))
    tree = BeautifulSoup(md.renderer.render(tokens, md.options, env), 'html.parser')
    for block in tree.find_all(recursive=False):
        line = int(block.get('data-toc-line', 1))
        if block.name in ('h1', 'h2') and block.get_text(strip=True) == '目录':
            if not block.find('a'):
                continue
        if block.name == 'p' and not block.find(['a', 'img']):
            label = block.get_text().strip()
            if label in ('范围：' + scope, '交付范围：' + scope):
                continue
        if region is not None and not region[0] < line < region[1]:
            raise ValueError('目录 L%d 的生成区间外存在未核验内容' % line)
        if block.name == 'table':
            yield from _table_entries(block, line)
        elif block.name in ('ul', 'ol'):
            for item in block.find_all('li'):
                item_line = int(item.get('data-toc-line', line))
                own = ''.join(str(child) for child in item.contents
                              if getattr(child, 'name', None) not in ('ul', 'ol'))
                yield _only_link(own, item_line), item_line, None
        else:
            raise ValueError('目录 L%d 存在未核验内容' % line)


def _verify_navigation(actual, output, scope, expected, region=None):
    links = list(_navigation(actual, scope, region))
    if len(links) != len(expected):
        raise ValueError('实际目录链接数量与官方范围不符')
    for (anchor, line, table_labels), entry in zip(links, expected):
        target, fragment = _target_of(anchor['href'], output)
        if target != entry["target_path"] or (
                fragment != entry["fragment"] and (fragment or not entry["implicit_h1"])):
            raise ValueError('目录 L%d 的路径/片段不对应官方条目 #%d'
                             % (line, entry["official_line"]))
        if table_labels is None:
            if anchor.get_text() not in (entry["label"], entry["original"]):
                raise ValueError('目录 L%d 的阅读标签与官方条目 #%d 不符'
                                 % (line, entry["official_line"]))
        else:
            original, translated = table_labels
            heading = entry["heading"]
            suffix = heading.removeprefix(entry["original"]).strip()
            if original != entry["original"] or translated not in (
                    heading, suffix.removeprefix('（').removesuffix('）')):
                raise ValueError('目录 L%d 的表格标签与官方条目 #%d 不符'
                                 % (line, entry["official_line"]))


def _toc_region(text):
    lines = text.splitlines()
    starts = [number for number, line in enumerate(lines, 1) if line == START]
    ends = [number for number, line in enumerate(lines, 1) if line == END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError('目录生成区间须有唯一且按序的 START/END')
    return starts[0], ends[0]


def _project_toc(output, sources, view_declaration_path):
    files = [output, *sources]
    declaration = None
    if view_declaration_path:
        view_path = Path(view_declaration_path).resolve()
        raw = view_path.read_bytes()
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("inputs"), list):
            raise ValueError('目录视图声明缺少有序输入')
        files = [Path(item["path"]).expanduser().resolve() for item in payload["inputs"]]
        if output not in files or not set(sources) <= set(files):
            raise ValueError('目录视图声明遗漏实际目录或章节')
        sources[view_path] = raw
    for path in files:
        if path != output and path not in sources:
            sources[path] = path.read_bytes()
    chapters = [Chapter(index, path) for index, path in enumerate(files, 1)]
    if view_declaration_path:
        declaration = load_view_declaration(view_declaration_path, chapters)
    decide_toc_provenance(chapters, declaration)
    toc = next(chapter for chapter in chapters if chapter.is_toc)
    own = [ex for ex in (declaration or {}).get('exclusions', [])
           if ex["chapter"] is toc]
    inline = [ex for ex in own if ex["type"] == "inline"]
    projected = project_view_declared(toc.text, [], inline)
    spans = [ex["lines"] for ex in own if ex["type"] == "block"]
    for span in [*toc.exclusions, toc.toc_provenance_exclusion]:
        if span:
            spans.append((span["start_line"], span["end_line"]))
    # 掩码保持原文行号，供目录范围和失败诊断消费。
    lines = projected.split('\n')
    for start, end in spans:
        lines[start - 1:end] = [''] * (end - start + 1)
    return '\n'.join(lines)


def verify_toc(manifest_path, toc_path, *, view_declaration_path=None):
    """从原清单及现存目录独立核验有序导航；只读返回事实与依赖。"""
    manifest_path, output = Path(manifest_path).resolve(), Path(toc_path).resolve()
    try:
        scope, expected, _, chapters, dependencies = _read_basis(manifest_path, output)
        raw = output.read_bytes()
        text = raw.decode('utf-8')
        region = _toc_region(text)
        actual = _project_toc(output, chapters, view_declaration_path)
        _verify_navigation(actual, output, scope, expected, region)
        dependencies.update(chapters)
        dependencies[output] = raw
        if any(path.read_bytes() != value for path, value in dependencies.items()):
            raise ValueError('核验期间目录或官方依据变化')
        return {
            "entries": [{key: entry[key] for key in
                         ("label", "target_path", "fragment", "official_line")}
                        for entry in expected],
            "dependencies": {str(path): hashlib.sha256(value).hexdigest()
                             for path, value in dependencies.items()},
        }
    except (OSError, KeyError, TypeError, ExportError) as exc:
        raise ValueError('目录 %s 的依据不可用: %s' % (output, exc)) from exc


def build(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    scope, expected, rendered, files, dependencies = _read_basis(manifest_path, output)
    generated = '# 目录\n\n范围：'+str(scope)+'\n\n'+'\n'.join(rendered)+'\n'
    old = output.read_bytes() if output.exists() else None
    if old is None:
        result = START+'\n\n'+generated+'\n'+END+'\n'
    else:
        text = old.decode('utf-8')
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START)>text.index(END):
            raise ValueError('已有目录包含未划定的用户内容，无法无损替换；请保留说明并明确生成区间')
        a,b=text.index(START),text.index(END)+len(END)
        result=text[:a]+START+'\n\n'+generated+'\n'+END+text[b:]
    def verify(actual_text=None):
        if any(path.read_bytes() != value for path, value in dependencies.items()):
            raise ValueError('发布前官方依据或译文变化，目录已过期')
        actual = generated
        if actual_text is not None:
            region = _toc_region(actual_text)
            if region is None:
                raise ValueError('实际生成目录缺少 START/END')
            actual = '\n'.join(actual_text.splitlines()[region[0]:region[1] - 1])
        _verify_navigation(actual, output, scope, expected)

    return result, old, verify, files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    output=Path(args.output).resolve()
    try:
        result,old,verify,_=build(args.manifest,output)
        if output==Path(args.manifest).resolve():
            raise ValueError('输出不得覆盖清单')
        verify()
        rwp_tmp=None
        output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,delete=False) as f:
            rwp_tmp=Path(f.name);f.write(result)
        try:
            verify()
            if (output.read_bytes() if output.exists() else None)!=old:
                raise ValueError('旧目录在发布前变化')
            os.replace(rwp_tmp,output)
            try:
                if output.read_text(encoding='utf-8')!=result:
                    raise ValueError('实际目录写后不符')
                verify(output.read_text(encoding='utf-8'))
            except Exception:
                if old is None: output.unlink()
                else: output.write_bytes(old)
                raise
        finally:
            rwp_tmp.unlink(missing_ok=True)
        print('已生成并从实际目录位置核对: '+str(output))
    except (OSError,ValueError,KeyError,TypeError,ImportError,ExportError) as exc:
        parser.exit(1,'目录拒绝: %s\n'%exc)


if __name__=='__main__':
    main()
