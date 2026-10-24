"""API 来源对象到交付目标；声明复用 source_record，不保存第二套导航注册表。"""
import json
import os
import re
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

from _verification import fenced_line_numbers, heading_entries, image_references

ANCHOR = re.compile(r'^\s*<a id="([^"<>]+)"></a>\s*$')
_INLINE = MarkdownIt('commonmark', {'html': True}).enable('table')


def _section_head(node):
    aliases=[]
    for child in node.children:
        if not isinstance(child,Tag):
            if str(child).strip():return None,[]
            continue
        if child.name=='span' and not child.get_text(strip=True) and not child.find(True):
            if child.get('id'):aliases.append(child['id'])
            continue
        return (child,aliases) if re.fullmatch(r'h[1-6]',child.name) else (None,[])
    return None,[]


def source_anchors(raw, section_id=None):
    """原 DOM 独立定位对象；行内 id 不提升到周围标题。"""
    soup = BeautifulSoup(raw, 'html.parser')
    root = soup.find(id=section_id) if section_id else (soup.find('article') or soup.find('main') or soup.find('body'))
    if root is None:raise ValueError('导航来源选区缺失: %r' % section_id)
    visible=lambda node:node.find_parent(['pre','code']) is None
    headings = [node for node in root.find_all(re.compile(r'^h[1-6]$')) if visible(node)]
    tables = [node for node in root.find_all('table') if visible(node)]
    images = [img for img in root.find_all('img') if visible(img) and not ('only-dark' in (img.get('class') or []) or (img.get('data-dark') and not img.get('data-light')))]
    objects = {id(node): (kind, index) for kind, nodes in [('heading',headings),('table',tables),('image',images)] for index,node in enumerate(nodes,1)}
    result, seen = {}, set()
    for node in [root,*root.find_all(id=True)]:
        if not visible(node):continue
        name=node.get('id')
        if not name:continue
        if name in seen:raise ValueError('源对象 ID 冲突: '+name)
        seen.add(name)
        target=node
        if node.name=='img' and any(p.name in ('p','table','a','li','dt','dd') for p in node.parents):
            continue  # 行内图片 ID 没有独立块边界，不伪造为块锚点。
        if node.name == 'section':
            target,_=_section_head(node)
        elif node.name=='span' and node.parent.name=='section':
            heading,aliases=_section_head(node.parent)
            target=heading if name in aliases else None
        elif node.name == 'figure':
            target=next((img for img in images if any(p is node for p in img.parents)),None)
        role=objects.get(id(target))
        if role:result[name]=role
    return result


def source_anchor_ids(node):
    """渲染端只在确定对象的块入口发出其自身原 ID。"""
    if node.name in ('table','figure','img') or re.fullmatch(r'h[1-6]',node.name or ''):
        return [node['id']] if node.get('id') else []
    if node.name == 'section':
        first,aliases=_section_head(node)
        if first is not None:
            return ([node['id']] if node.get('id') else [])+aliases
    return []


def anchor_diffs(raw, text, *, section_id=None, names=None):
    """实际端从 Markdown 对象位置验证，拒绝锚点插入表格数据区。"""
    from _source_reconcile import markdown_table_facts, _TABLE_CAPTION_LINE_RE
    expected=source_anchors(raw,section_id)
    if names is not None:expected={names(key):role for key,role in expected.items()}
    objects=[]
    objects.extend((line,'heading',index) for index,(line,_,_) in enumerate(heading_entries(text),1))
    objects.extend((table['start_line'],'table',index) for index,table in enumerate(markdown_table_facts(text),1))
    objects.extend((line,'image',index) for index,(line,_) in enumerate(image_references(text),1))
    objects.sort(key=lambda item:(item[0],{'heading':0,'table':1,'image':2}[item[1]]))
    lines=text.splitlines();fenced=fenced_line_numbers(text);actual={};diffs=[]
    for line_no,line in enumerate(lines,1):
        match=ANCHOR.fullmatch(line)
        if not match or line_no in fenced:continue
        name=unescape(match[1])
        if name in actual:diffs.append('重复 Markdown 锚点 '+name)
        actual[name]=line_no
    for name,role in expected.items():
        line=actual.get(name)
        if not line:
            diffs.append('缺来源对象锚点 '+name);continue
        following=next((obj for obj in objects if obj[0]>line),None)
        if following is None or following[1:] != role:
            diffs.append('锚点目标错绑: '+name);continue
        for value in lines[line:following[0]-1]:
            stripped=value.strip()
            if stripped and not ANCHOR.fullmatch(value) and not _TABLE_CAPTION_LINE_RE.match(value):
                diffs.append('锚点与对象间存在其他正文: '+name);break
        if line>1 and lines[line-2].strip() and not ANCHOR.fullmatch(lines[line-2]):
            diffs.append('锚点缺合法块前边界: '+name)
        if line<len(lines) and lines[line].strip() and not ANCHOR.fullmatch(lines[line]):
            diffs.append('锚点缺合法块后边界: '+name)
    return diffs


def _link_blocks(text):
    """沿用现有脚注定义读取，按原行号读取正文链接，不把脚注当引用链接。"""
    from _verification import footnote_definition_block
    lines=text.split('\n');main=list(lines);fenced=fenced_line_numbers(text)
    fragments=[];line=1
    while line<=len(lines):
        if line not in fenced and re.match(r'^\[\^[^\]]+\]:',lines[line-1]):
            body,last,cursor=footnote_definition_block(lines,line)
            fragments.append((body,line-1))
            for index in range(line-1,cursor-1):main[index]=''
            line=cursor
        else:line+=1
    fragments.insert(0,('\n'.join(main),0))
    blocks=[]
    for body,offset in fragments:
        # Parser container fences retain raw body indentation. Mask their
        # original line ranges before CommonMark can reinterpret outdented
        # code as prose; blank lines retain all rewrite offsets.
        body='\n'.join('' if number+offset+1 in fenced else value
                       for number,value in enumerate(body.split('\n')))
        for block in _INLINE.parse(body):
            if not block.children:continue
            if block.map:block.map=[number+offset for number in block.map]
            blocks.append(block)
    return sorted(blocks,key=lambda block:block.map[0] if block.map else 0)


def links(text):
    """实际 Markdown 链接出现；代码和图片不作为普通目标。"""
    return [token.attrGet('href') for block in _link_blocks(text) for token in (block.children or []) if token.type=='link_open']


def compare_anchors(source, translated):
    """包内锚点 ID 和实际对象序号守恒；普通无锚点 Markdown 无新增要求。"""
    from _source_reconcile import markdown_table_facts, _TABLE_CAPTION_LINE_RE
    def read(text):
        objects=[(line,'heading',index) for index,(line,_,_) in enumerate(heading_entries(text),1)]
        objects += [(table['start_line'],'table',index) for index,table in enumerate(markdown_table_facts(text),1)]
        objects += [(line,'image',index) for index,(line,_) in enumerate(image_references(text),1)]
        objects.sort(key=lambda item:(item[0],{'heading':0,'table':1,'image':2}[item[1]]))
        facts=[];fenced=fenced_line_numbers(text)
        lines=text.splitlines()
        for line,value in enumerate(lines,1):
            match=ANCHOR.fullmatch(value)
            if match and line not in fenced:
                following=next((item for item in objects if item[0]>line),None)
                obj=following[1:] if following else None
                allowed=lambda value:not value.strip() or ANCHOR.fullmatch(value) or _TABLE_CAPTION_LINE_RE.match(value)
                valid=bool(following) and all(allowed(value) for value in lines[line:following[0]-1])
                valid=valid and (line==1 or not lines[line-2].strip() or bool(ANCHOR.fullmatch(lines[line-2])))
                valid=valid and (line==len(lines) or not lines[line].strip() or bool(ANCHOR.fullmatch(lines[line])))
                facts.append((unescape(match[1]),obj,valid))
        return facts
    return [] if read(source)==read(translated) else ['来源锚点 ID、顺序或内容对象归属改变']


def replace_links(text, convert):
    """按实际 inline token 的目标重写语法；不触碰代码中的同形字符串。"""
    # markdown-it 没有 inline 绝对偏移；逐块只重写已确认的链接出现。
    edits=[];line_offsets=[0]
    for line in text.splitlines(keepends=True):line_offsets.append(line_offsets[-1]+len(line))
    from _verification import line_code_spans, in_code_span, image_reference_spans
    for block in _link_blocks(text):
        targets=[token.attrGet('href') for token in (block.children or []) if token.type=='link_open']
        if not targets:continue
        start,end=(line_offsets[n] for n in block.map)
        chunk=text[start:end];cursor=0
        for target in targets:
            converted=convert(target)
            if converted==target:continue
            candidates=list(re.finditer(r'\]\(([^\s()]*)\)',chunk[cursor:]))
            found=None
            for match in candidates:
                lo=cursor+match.start(1);hi=cursor+match.end(1)
                if _INLINE.normalizeLink(chunk[lo:hi]) != target:continue
                # Actual token already excludes code; skip code candidates sharing target.
                line_start=chunk.rfind('\n',0,lo)+1;line_end=chunk.find('\n',hi)
                if line_end<0:line_end=len(chunk)
                line=chunk[line_start:line_end]
                if in_code_span(line_code_spans(line),lo-line_start,hi-line_start):continue
                if any(start<=lo-line_start<end for _,start,end,_ in image_reference_spans(line)):continue
                found=(lo,hi);break
            if found is None:raise ValueError('导航链接语法无法可靠改写: '+target)
            lo,hi=found;edits.append((start+lo,start+hi,converted));cursor=hi
    for lo,hi,value in reversed(edits):text=text[:lo]+value+text[hi:]
    return text


def load_navigation(path, site_root):
    """源准入不要求成品存在；所有归属均由快照及 covers 声明确定。"""
    import verify_delivery as delivery
    record=json.loads(Path(path).read_text(encoding='utf-8'))
    root=Path(record['delivery_root']).resolve();site=Path(site_root).resolve()
    problems=[];entries=delivery.check_source_chains(str(root),record,problems,source_only=True)
    delivery.run_source_reconcile(str(root),record,entries,problems)
    if problems:raise ValueError('导航来源准入失败: '+'；'.join(problems))
    pages={}
    for entry in entries:
        if entry['family']!='api':continue
        covers=entry['covers']
        if len(covers)!=1:raise ValueError('源页章节归属不唯一: '+str(covers))
        chapter=(root/covers[0]).resolve()
        parsed=Path(entry['_parsed_abs']).read_text(encoding='utf-8').split('\n')
        for index,snap in enumerate(entry['snapshots']):
            snapshot=(root/snap['snapshot']).resolve()
            try:key=snapshot.relative_to(site).as_posix()
            except ValueError:raise ValueError('导航快照不在 site_root: '+str(snapshot))
            raw=snapshot.read_text(encoding='utf-8')
            facts=source_anchors(raw,snap.get('section_id'))
            if key in pages:raise ValueError('源页章节归属重复: '+key)
            span=entry['ranges'][index]
            source='\n'.join(parsed[span[0]-1:span[1]])
            errors=anchor_diffs(raw,source,section_id=snap.get('section_id'))
            if errors:raise ValueError('导航解析源缺对象证明: '+'；'.join(errors))
            resources={}
            for image in entry['_source_facts'][index]['images']:
                path=Path(image['path']).resolve()
                try:resource=path.relative_to(site).as_posix()
                except ValueError:raise ValueError('导航图片不在 site_root: '+str(path))
                resources[resource]=path
            from _source_reconcile import _SourceFacts, _mapped_table_headers
            info=snap.get('table_conversions')
            mapping=json.loads((root/info['path']).read_text(encoding='utf-8')) if info else None
            headers=_mapped_table_headers(_SourceFacts(raw,'api',snap.get('section_id')),mapping,snap.get('section_id'))
            pages[key]={'chapter':chapter,'anchors':facts,'raw':raw,'section_id':snap.get('section_id'),'source':source,'resources':resources,'header_cells':headers,
                        'role_source':delivery.table_role_source(entry,str(root))}
    return pages


def namespaced(page, fragment):
    # UTF-8 hex 双字段可逆；页本身另用 p，原 id 用 i，避免空原 id 碰撞。
    return 'src-'+page.encode().hex()+('-i-'+fragment.encode().hex() if fragment else '-p')


def target_for(pages, page, href, chapter):
    parsed=urlsplit(href)
    if parsed.scheme or parsed.netloc:return href
    if parsed.query:raise ValueError('来源查询链接无法确定对象: '+href)
    path=unquote(parsed.path);fragment=unquote(parsed.fragment)
    key=os.path.normpath(os.path.join(os.path.dirname(page),path)).replace(os.sep,'/') if path else page
    if key not in pages:
        resource=pages[page]['resources'].get(key)
        if resource is not None and not fragment:
            return 'images/'+quote(resource.name,safe='')  # 资产冲突仍由合并器拒绝。
        raise ValueError('来源目标页不在交付范围: %s → %s' % (page,href))
    target=pages[key]
    if fragment and fragment not in target['anchors']:raise ValueError('来源目标缺失或无法定位: %s → %s' % (page,href))
    suffix='#'+namespaced(key,fragment)
    return suffix if target['chapter']==Path(chapter).resolve() else quote(os.path.relpath(target['chapter'],Path(chapter).resolve().parent).replace(os.sep,'/'),safe='/')+suffix


def transform_page(text, page, pages, chapter):
    if page not in pages or pages[page]['chapter']!=Path(chapter).resolve():raise ValueError('当前源页未唯一归属输出章: '+page)
    facts=pages[page]
    diffs=anchor_diffs(facts['raw'],text,section_id=facts['section_id'])
    if diffs:raise ValueError('翻译页锚点无来源证明: '+'；'.join(diffs))
    if links(text)!=links(facts['source']):raise ValueError('翻译页改变原链接目标: '+page)
    from _source_reconcile import compare_translation_tables
    before=text
    text=replace_links(text,lambda href:target_for(pages,page,href,chapter))
    old_links=iter(links(before))
    restored=replace_links(text,lambda _href:next(old_links))
    table_problems=compare_translation_tables(before,restored,exact=True,header_cells=facts.get('header_cells',()))
    if table_problems:raise ValueError('导航转换损伤表格: '+page+'；'+'；'.join(table_problems))
    fenced=fenced_line_numbers(text)
    lines=text.splitlines()
    for n,line in enumerate(lines,1):
        match=ANCHOR.fullmatch(line)
        if not match or n in fenced:continue
        name=unescape(match[1])
        if name not in facts['anchors']:raise ValueError('无来源锚点: '+name)
        lines[n-1]='<a id="'+namespaced(page,name)+'"></a>'
    return '<a id="'+namespaced(page,'')+'"></a>\n\n'+'\n'.join(lines)


def verify_page(source, translated, page, pages, chapter):
    """从原 DOM 和实际源/译 token 关系重建预期，不接受改写器自报映射。"""
    facts=pages.get(page)
    if facts is None or facts['chapter']!=Path(chapter).resolve():return ['来源页章节归属不符: '+page]
    if source.strip()!=facts['source'].strip():return ['核验源与导航记录选区不符: '+page]
    diffs=anchor_diffs(facts['raw'],source,section_id=facts['section_id'])
    diffs+=anchor_diffs(facts['raw'],translated,section_id=facts['section_id'],names=lambda name:namespaced(page,name))
    expected=[target_for(pages,page,href,chapter) for href in links(source)]
    if links(translated)!=expected:diffs.append('链接目标对象或出现顺序改变: '+page)
    from _source_reconcile import compare_translation_tables
    mapped_source=replace_links(source,lambda href:target_for(pages,page,href,chapter))
    diffs+=compare_translation_tables(mapped_source,translated,header_cells=facts.get('header_cells',()))
    anchors=[ANCHOR.fullmatch(line)[1] for n,line in enumerate(translated.splitlines(),1) if ANCHOR.fullmatch(line) and n not in fenced_line_numbers(translated)]
    permitted={namespaced(page,name) for name in facts['anchors']}|{namespaced(page,'')}
    if set(anchors)!=permitted or len(anchors)!=len(permitted):diffs.append('最终锚点集合冲突或缺失: '+page)
    return diffs
