#!/usr/bin/env python3
"""按已确认官方清单与实际标题实例生成独立目录，不修改章节。"""
import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from export_pdf import (heading_targets, build_markdown, scan_math,
                        BeautifulSoup, ExportError, TOC_FILE_NAME)
from _html_fidelity import escape_text_backslashes
from _verification import heading_title_matches, link_targets

START = '[tdt-toc-start]: #'
END = '[tdt-toc-end]: #'


def build(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
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
    files, tables, rendered, seen, positions, labels = {}, {}, [], set(), [], []
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
        labels.append(label)
        rendered.append('  '*(entry['level']-1)+'- ['+(number+' ' if number and not heading['text'].startswith(number) else '')+text+']('+href+')')
    if positions != sorted(set(positions)):
        raise ValueError('清单顺序与官方顺序不符/重复')
    declared = manifest.get('official_lines')
    if not isinstance(declared,list) or declared != positions:
        raise ValueError('已确认范围必须逐条声明，漏关联/范围外条目拒绝')
    generated = '# 目录\n\n范围：'+str(manifest['scope'])+'\n\n'+'\n'.join(rendered)+'\n'
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
        if manifest_path.read_bytes()!=manifest_bytes or basis_path.read_bytes()!=basis_raw or any(p.read_bytes()!=v for p,v in files.items()):
            raise ValueError('发布前官方依据或译文变化，目录已过期')
        actual = generated if actual_text is None else actual_text.split(START,1)[1].split(END,1)[0]
        scan = scan_math(actual)
        if scan.issues:
            raise ValueError('实际目录标签存在未解决数学定界')
        markdown, _ = build_markdown([], '', scan.spans, actual, highlight=False)
        links = BeautifulSoup(markdown.render(actual), 'html.parser').find_all('a', href=True)
        if [link.get_text() for link in links] != labels:
            raise ValueError('实际目录阅读文字与已确认标题不符')
        hrefs = link_targets(actual)
        if len(hrefs) != len(entries):
            raise ValueError('实际目录链接数量与官方范围不符')
        for href in hrefs:
            parts=urlsplit(href)
            path=(output.parent/unquote(parts.path)).resolve()
            if (path,unquote(parts.fragment)) not in seen:
                raise ValueError('实际目录路径/片段不对应已确认目标')
        # 相对链接从实际目录父位置再次解析；预期来自独立官方清单。
        for entry in entries:
            p=(root/entry['translation']).resolve()
            current,_=heading_targets(p.read_text(encoding='utf-8'))
            matches=[h for h in current if heading_title_matches(entry['original_title'],h['text'])]
            if (p,matches[entry['occurrence']-1]['slug']) not in seen:
                raise ValueError('目录目标在写后不再对应')
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
