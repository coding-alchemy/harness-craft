"""API 来源对象到交付目标；声明复用 source_record，不保存第二套导航注册表。"""
import json
import os
import re
from bisect import bisect_left
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

from _verification import fenced_line_numbers, heading_entries, image_references, scan_code_fences

ANCHOR = re.compile(r'^\s*<a id="([^"<>]+)"></a>\s*$')
SOURCE_ANCHOR = re.compile(r'^\s*<a id="src-[0-9a-f]+-(?:p|i-[0-9a-f]+)"></a>\s*$')
_INLINE = MarkdownIt('commonmark', {'html': True}).enable('table')


def _source_root(raw, section_id):
    soup = BeautifulSoup(raw, 'html.parser')
    root = soup.find(id=section_id) if section_id else (
        soup.find('article') or soup.find('main') or soup.find('body'))
    if root is None:
        raise ValueError('导航来源选区缺失: %r' % section_id)
    return root


def code_anchor_ids(node, pre_id, *, is_placeholder=None, root=None):
    """只有只含一个代码对象的清单包装可给该对象提供别名。"""
    if node.find_parent(['table', 'code', 'pre']):
        return []
    aliases = []
    for parent in node.parents:
        classes = parent.get('class', ())
        if parent is root or parent.name != 'div' or not any(
                cls in ('literal-block-wrapper', 'highlight') or cls.startswith('highlight-')
                for cls in classes):
            break
        blocks = (parent.find_all(string=is_placeholder, limit=2)
                  if is_placeholder else parent.find_all('pre', limit=2))
        if len(blocks) == 1 and parent.get('id'):
            aliases.insert(0, parent['id'])
    return aliases + ([pre_id] if pre_id else [])


def _paragraph(node):
    return (node.name == 'p' and not node.find_parent(
        ['pre', 'code', 'table', 'li', 'dt', 'dd', 'figcaption'])
        and 'admonition-title' not in node.get('class', ())
        and bool(node.get_text(strip=True) or node.find('img')))


def _admonition(node):
    return (node.name == 'div' and 'admonition' in node.get('class', ())
            and not node.find_parent(['pre', 'code', 'table', 'li', 'blockquote']))


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
    return _source_anchors(_source_root(raw, section_id))


def _source_anchors(root):
    visible=lambda node:node.find_parent(['pre','code']) is None
    headings = [node for node in root.find_all(re.compile(r'^h[1-6]$')) if visible(node)]
    tables = [node for node in root.find_all('table') if visible(node)]
    images = [img for img in root.find_all('img') if visible(img) and not ('only-dark' in (img.get('class') or []) or (img.get('data-dark') and not img.get('data-light')))]
    paragraphs = root.find_all(_paragraph)
    admonitions = root.find_all(_admonition)
    codes = [node for node in root.find_all('pre') if visible(node)]
    objects = {id(node): (kind, index) for kind, nodes in [
        ('heading', headings), ('table', tables), ('image', images),
        ('paragraph', paragraphs), ('code', codes), ('admonition', admonitions),
    ] for index, node in enumerate(nodes, 1)}
    code_ids = {name: objects[id(pre)] for pre in codes
                for name in code_anchor_ids(pre, pre.get('id'), root=root)}
    result, seen = {}, set()
    for node in [root,*root.find_all(id=True)]:
        if not visible(node):continue
        name=node.get('id')
        if not name:continue
        if name in seen:raise ValueError('源对象 ID 冲突: '+name)
        seen.add(name)
        if name in code_ids:
            result[name] = code_ids[name]
            continue
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
        role=objects.get(id(target)) if node.name != 'pre' else None
        if role:result[name]=role
    return result


def source_anchor_ids(node):
    """渲染端只在确定对象的块入口发出其自身原 ID。"""
    if (node.name in ('table','figure','img') or _paragraph(node) or _admonition(node)
            or re.fullmatch(r'h[1-6]',node.name or '')):
        return [node['id']] if node.get('id') else []
    if node.name == 'section':
        first,aliases=_section_head(node)
        if first is not None:
            return ([node['id']] if node.get('id') else [])+aliases
    return []


def _markdown_paragraphs(text):
    from _source_reconcile import _TABLE_CAPTION_LINE_RE
    lines = text.splitlines()
    prose = '\n'.join('' if ANCHOR.fullmatch(line) else line for line in lines)
    tokens = _INLINE.parse(prose)
    return [(token.map[0]+1, tokens[index+1].content)
            for index, token in enumerate(tokens)
            if token.type == 'paragraph_open' and token.level == 0
            and not _TABLE_CAPTION_LINE_RE.match(lines[token.map[0]])]


def _markdown_admonitions(text):
    label_pattern = re.compile(
        r'\s*>\s*\*\*(?:ADMONITION \[([^\]]+)\]|[^（(]+[（(](Note|Warning|Important|Tip)[）)])\*\*\s*')
    labels = {index: (label[1] or label[2]).strip().casefold()
              for index, line in enumerate(text.splitlines())
              if (label := label_pattern.fullmatch(line))}
    if not labels:
        return {}
    return {token.map[0]+1: labels[token.map[0]] for token in _INLINE.parse(text)
            if token.type == 'blockquote_open' and token.level == 0 and token.map[0] in labels}


def _following_list_code(text, paragraph_lines):
    """A short label can be identified by literal code in its adjacent list."""
    lines = text.splitlines()
    tokens = _INLINE.parse('\n'.join('' if ANCHOR.fullmatch(line) else line for line in lines))
    matches = {}
    for index, token in enumerate(tokens):
        if token.type != 'paragraph_open' or token.level or token.map[0]+1 not in paragraph_lines:
            continue
        title = tokens[index+1].content.rstrip()
        if '\n' in title or not title.endswith((':', '：')):
            continue
        cursor = index+3
        if cursor < len(tokens) and tokens[cursor].type == 'blockquote_open':
            cursor += 1
        if cursor+1 < len(tokens) and tokens[cursor].type == 'paragraph_open' and tokens[cursor+1].content == '[BLOCKQUOTE]':
            cursor += 3
        if cursor < len(tokens) and tokens[cursor].type == 'paragraph_open':
            cursor += 3
        if cursor >= len(tokens) or tokens[cursor].type not in ('bullet_list_open', 'ordered_list_open'):
            continue
        first_item = tokens[cursor+1]
        code = []
        for block in tokens[cursor+2:]:
            if block.type == 'list_item_close' and block.level == first_item.level:
                break
            code.extend(child.content for child in block.children or () if child.type == 'code_inline')
        if code:
            matches[token.map[0]+1] = tuple(code)
    return matches


def markdown_objects(text):
    from _source_reconcile import markdown_table_facts
    objects=[]
    objects.extend((line,'heading',index) for index,(line,_,_) in enumerate(heading_entries(text),1))
    objects.extend((table['start_line'],'table',index) for index,table in enumerate(markdown_table_facts(text),1))
    objects.extend((line,'image',index) for index,(line,_) in enumerate(image_references(text),1))
    objects.extend((block.start_line, 'code', index) for index, block in
                   enumerate(scan_code_fences(text).blocks, 1))
    objects.extend((line, 'paragraph', index) for index, (line, _) in
                   enumerate(_markdown_paragraphs(text), 1))
    objects.extend((line, 'admonition', index) for index, line in
                   enumerate(_markdown_admonitions(text), 1))
    order = ('heading', 'table', 'image', 'code', 'paragraph', 'admonition')
    return sorted(objects, key=lambda item: (item[0], order.index(item[1])))


def anchor_diffs(raw, text, *, section_id=None, names=None, source=None):
    """实际端从 Markdown 对象位置验证，拒绝锚点插入表格数据区。"""
    from _source_reconcile import _TABLE_CAPTION_LINE_RE, api_paragraph_positions
    root = _source_root(raw, section_id)
    expected = _source_anchors(root)
    if any(kind == 'paragraph' for kind, _ in expected.values()):
        positions = api_paragraph_positions(root, text if source is None else source)
        expected = {name: (kind, positions.get(index)) if kind == 'paragraph' else (kind, index)
                    for name, (kind, index) in expected.items()}
    if names is not None:expected={names(key):role for key,role in expected.items()}
    objects=markdown_objects(text)
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
        if following is None or (following[0], *role) not in objects:
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


def _navigation_href(href):
    parts = urlsplit(href)
    return not (parts.scheme or parts.netloc) and (
        (not parts.path and bool(parts.fragment))
        or Path(unquote(parts.path)).suffix.lower() in ('.html', '.htm'))


def _navigation_reference(raw, translated, section_id):
    root = _source_root(raw, section_id)
    for link in root.find_all('a', href=True):
        classes = link.get('class', ())
        if (link.find_parent(['pre', 'code', 'script', 'style', 'noscript'])
                or {'footnote-reference', 'fn-backref'} & set(classes)
                or link.get('role') in ('doc-noteref', 'doc-backlink')
                or ('headerlink' in classes and link.find_parent(re.compile(r'^h[1-6]$')))):
            continue
        href = link['href'].strip()
        if _navigation_href(href):
            return href, link.get_text(' ', strip=True), link.sourceline, 'HTML'
    for block in _link_blocks(translated):
        for index, token in enumerate(block.children):
            if token.type != 'link_open':
                continue
            href = token.attrGet('href')
            if _navigation_href(href):
                label = []
                for child in block.children[index+1:]:
                    if child.type == 'link_close':
                        break
                    label.append(child.content)
                return href, ''.join(label), block.map[0]+1, 'Markdown'
    return None


def requires_navigation(raw: str, translated: str, *, section_id: str | None = None) -> bool:
    """有交付选区内的来源导航时，删掉译文链接也不能省略来源记录。"""
    return _navigation_reference(raw, translated, section_id) is not None


def require_navigation_record(snapshot, translated):
    raw = Path(snapshot).read_text(encoding='utf-8')
    reference = _navigation_reference(raw, translated, None)
    if reference:
        href, label, line, kind = reference
        raise ValueError('%s %s L%s 链接 %r (%s) 缺少 --navigation-record'
                         % (snapshot, kind, line, label, href))


def compare_anchors(source, translated):
    """包内锚点 ID 和实际对象序号守恒；普通无锚点 Markdown 无新增要求。"""
    from _source_reconcile import _TABLE_CAPTION_LINE_RE
    def read(text):
        if not any(ANCHOR.fullmatch(line) for line in text.splitlines()):
            return []
        objects=markdown_objects(text)
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


def _link_edits(text, convert):
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
    return edits


def _apply_edits(text, edits):
    for lo, hi, value in reversed(edits):
        text = text[:lo] + value + text[hi:]
    return text


def replace_links(text, convert):
    return _apply_edits(text, _link_edits(text, convert))


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
    diffs=anchor_diffs(facts['raw'],text,section_id=facts['section_id'],source=facts['source'])
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
    diffs+=anchor_diffs(facts['raw'],translated,section_id=facts['section_id'],
                        names=lambda name:namespaced(page,name),source=source)
    expected=[target_for(pages,page,href,chapter) for href in links(source)]
    if links(translated)!=expected:diffs.append('链接目标对象或出现顺序改变: '+page)
    from _source_reconcile import compare_translation_tables
    mapped_source=replace_links(source,lambda href:target_for(pages,page,href,chapter))
    diffs+=compare_translation_tables(mapped_source,translated,header_cells=facts.get('header_cells',()))
    anchors=[ANCHOR.fullmatch(line)[1] for n,line in enumerate(translated.splitlines(),1) if ANCHOR.fullmatch(line) and n not in fenced_line_numbers(translated)]
    permitted={namespaced(page,name) for name in facts['anchors']}|{namespaced(page,'')}
    if set(anchors)!=permitted or len(anchors)!=len(permitted):diffs.append('最终锚点集合冲突或缺失: '+page)
    start=ANCHOR.fullmatch(translated.lstrip().split('\n', 1)[0])
    if start is None or start[1] != namespaced(page, ''):
        diffs.append('源页入口未绑定当前页首: '+page)
    return diffs


def split_page_ranges(text):
    """围栏外的页分隔只提供候选区间，原始行与换行字节均保留。"""
    fenced = fenced_line_numbers(text.replace('\r\n', '\n'))
    ranges = []
    start = offset = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        end = offset + len(line)
        if number not in fenced and line.strip() == '---':
            ranges.append((start, offset))
            start = end
        offset = end
    return [*ranges, (start, len(text))]


def _recovery_inputs(baseline_path, manifest_path, official_toc_path, site_root,
                     navigation_record, chapter_path):
    baseline, chapter = Path(baseline_path).resolve(), Path(chapter_path).resolve()
    if baseline == chapter or (chapter.exists() and baseline.samefile(chapter)):
        raise ValueError('导航恢复基准与输出章必须是不同文件')
    if baseline.parent != chapter.parent:
        raise ValueError('导航恢复基准与输出章必须使用同一资源基点')
    manifest_file, toc = Path(manifest_path), Path(official_toc_path)
    manifest = [line.strip() for line in manifest_file.read_text(encoding='utf-8').splitlines() if line.strip()]
    official = [line.strip() for line in toc.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not manifest or manifest != official or len(set(manifest)) != len(manifest) or manifest_file.samefile(toc):
        raise ValueError('恢复页面清单与独立官方 TOC 的集合或顺序不闭合')
    current = baseline.read_bytes().decode('utf-8')
    ranges = split_page_ranges(current)
    if len(ranges) != len(manifest) or any(not current[lo:hi].strip() for lo, hi in ranges):
        raise ValueError('当前合章分隔与官方 TOC 的页面范围不闭合')
    pages = load_navigation(navigation_record, site_root)
    for page in manifest:
        if page not in pages or pages[page]['chapter'] != chapter:
            raise ValueError('恢复源页无唯一最终章归属: ' + page)
    if {page for page, facts in pages.items() if facts['chapter'] == chapter} != set(manifest):
        raise ValueError('恢复源页集合与记录的最终章覆盖不闭合')
    return current, list(zip(manifest, ranges)), pages, chapter


def _recovery_object_lines(text, page, facts, chapter):
    from _source_reconcile import api_paragraph_positions, compare_translation_tables, markdown_table_facts
    from _verification import compare_headings, resolve_delivery_image, resource_identity_digest

    source = facts['source']
    normalized = text.replace('\r\n', '\n')
    source_heads, current_heads = heading_entries(source), heading_entries(normalized)
    diffs = compare_headings(source_heads, current_heads, '解析稿', '当前合章')
    if diffs or not source_heads:
        raise ValueError(page + ' 页身份无法由完整标题序列确认: ' + '；'.join(diffs))
    source_heads = [line for line, _, _ in source_heads]
    current_heads = [line for line, _, _ in current_heads]
    source_objects = {(kind, index): line for line, kind, index in markdown_objects(source)}
    current_objects = {(kind, index): line for line, kind, index in markdown_objects(normalized)}
    roles = {kind for kind, _ in facts['anchors'].values()}
    positions = {}
    if 'paragraph' in roles:
        root = _source_root(facts['raw'], facts['section_id'])
        positions = api_paragraph_positions(root, source)
    if 'admonition' in roles:
        source_admonitions = _markdown_admonitions(source)
        current_admonitions = _markdown_admonitions(normalized)
    if 'code' in roles:
        src_code = {block.start_line: (block.info, block.body) for block in scan_code_fences(source).blocks}
        dst_code = {block.start_line: (block.info, block.body) for block in scan_code_fences(normalized).blocks}
    if 'image' in roles:
        src_images = dict(image_references(source))
        dst_images = dict(image_references(normalized))
    if 'table' in roles:
        src_tables = {item['start_line']: item for item in markdown_table_facts(source)}
        dst_tables = {item['start_line']: item for item in markdown_table_facts(normalized)}

    def source_image(ref):
        path = unquote(urlsplit(ref).path)
        key = os.path.normpath(os.path.join(os.path.dirname(page), path)).replace(os.sep, '/')
        resource = facts['resources'].get(key)
        return resource_identity_digest(str(resource)) if resource else None

    def current_image(ref):
        path, reason = resolve_delivery_image(ref, str(chapter.parent))
        return None if reason else resource_identity_digest(path)

    def table_text(body, item):
        rows = body.splitlines(keepends=True)
        return replace_links(''.join(rows[item['start_line']-1:item['group_end_line']]),
                             lambda href: '#link' if _navigation_href(href) or '#src-' in href else href)

    first = next((number for number, line in enumerate(text.splitlines(), 1)
                  if line.strip() and not ANCHOR.fullmatch(line)), None)
    if first is None:
        raise ValueError(page + ' 找不到当前源页起点')
    result = {None: first}
    assigned = {}
    for name, (kind, ordinal) in facts['anchors'].items():
        source_role = kind, ordinal
        if kind == 'paragraph':
            ordinal = positions.get(ordinal)
        src_line = source_objects.get((kind, ordinal))
        if src_line is None:
            raise ValueError('%s #%s 缺解析稿对象依据' % (page, name))
        section = bisect_left(source_heads, src_line)
        possible = [line for (role, _), line in current_objects.items()
                    if role == kind and bisect_left(current_heads, line) == section]
        if kind == 'heading':
            possible = [current_objects[('heading', ordinal)]]
        elif kind == 'code':
            possible = [line for line in possible if dst_code[line] == src_code[src_line]]
        elif kind == 'image':
            identity = source_image(src_images[src_line])
            possible = [line for line in possible if identity and current_image(dst_images[line]) == identity]
        elif kind == 'table':
            src_table = src_tables[src_line]
            source_table = table_text(source, src_table)
            cell_roles = [(1, row, col) for table, row, col in facts['header_cells'] if table == ordinal]
            possible = [line for line in possible if not compare_translation_tables(
                source_table, table_text(normalized, dst_tables[line]), header_cells=cell_roles)]
        elif kind == 'paragraph':
            src_group = [line for (role, _), line in source_objects.items()
                         if role == kind and bisect_left(source_heads, line) == section]
            if len(src_group) == len(possible):
                possible = [possible[src_group.index(src_line)]]
            else:
                signature = _following_list_code(source, {src_line}).get(src_line)
                possible = [line for line, code in _following_list_code(normalized, set(possible)).items()
                            if signature and code == signature]
        elif kind == 'admonition':
            possible = [line for line in possible if current_admonitions[line] == source_admonitions[src_line]]
        if len(possible) != 1:
            raise ValueError('%s #%s 无法唯一对应 %s 对象，源 L%d / 当前候选 %s'
                             % (page, name, kind, src_line, possible))
        host = kind, possible[0]
        if host in assigned and assigned[host] != source_role:
            raise ValueError('%s #%s 多个源对象对应同一当前对象 L%d'
                             % (page, name, possible[0]))
        assigned[host] = source_role
        result[name] = possible[0]
    return result


def _recovery_href(pages, page, href, chapter):
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return href
    fragment = unquote(parts.fragment)
    if not parts.path and fragment in pages[page]['anchors']:
        return target_for(pages, page, href, chapter)
    if Path(unquote(parts.path)).suffix.lower() in ('.html', '.htm'):
        return target_for(pages, page, href, chapter)
    if fragment.startswith('src-'):
        # 已正规化的目标须能从同一来源反解，且章路径仍匹配。
        match = re.fullmatch(r'src-([0-9a-f]+)-(?:p|i-([0-9a-f]+))', fragment)
        if match:
            try:
                key = bytes.fromhex(match[1]).decode()
                name = bytes.fromhex(match[2]).decode() if match[2] else None
            except ValueError:
                raise ValueError('正规化链接编码无效: ' + href) from None
            if key not in pages or (name and name not in pages[key]['anchors']):
                raise ValueError('正规化链接缺来源目标: ' + href)
            destination = pages[key]['chapter']
            relative = os.path.relpath(destination, chapter.parent).replace(os.sep, '/')
            expected = '#' + namespaced(key, name)
            if destination != chapter:
                expected = quote(relative, safe='/') + expected
            if _INLINE.normalizeLink(expected) != href:
                raise ValueError('正规化链接与来源章归属不符: ' + href)
    return href


def _recovery_anchor_edits(text, page, targets, roles):
    from _source_reconcile import _TABLE_CAPTION_LINE_RE

    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1]+len(line))
    fenced = fenced_line_numbers(text.replace('\r\n', '\n'))
    canonical = {namespaced(page, name): name for name in targets}
    existing = {}
    for number, line in enumerate(lines, 1):
        match = ANCHOR.fullmatch(line)
        if number in fenced or not match:
            continue
        label = unescape(match[1])
        if label not in canonical and label not in targets:
            continue
        name = canonical.get(label, label)
        if name in existing:
            raise ValueError('%s 同一源锚点重复: %s' % (page, label))
        existing[name] = (number, label)

    replacements = {}
    insertions = {}
    retained = []
    for name, target in targets.items():
        label = namespaced(page, name)
        number, old_label = existing.get(name, (0, None))
        table = name is not None and roles[name][0] == 'table'
        if number and number < target and all(
                not line.strip() or ANCHOR.fullmatch(line)
                or (table and _TABLE_CAPTION_LINE_RE.match(line))
                for line in lines[number:target-1]):
            line = lines[number-1]
            if label != old_label:
                match = ANCHOR.fullmatch(line)
                replacements[number] = line[:match.start(1)] + label + line[match.end(1):]
            retained.append(number)
            continue
        if number:
            replacements[number] = ''
        insertions.setdefault(target, []).append(label)

    # A neighbouring source anchor may move away in this same edit. Use the
    # surviving lines when checking the boundaries of retained anchors.
    for number in retained:
        line = lines[number-1]
        eol = '\r\n' if line.endswith('\r\n') else '\n'
        before = next((lines[i-1] for i in range(number-1, 0, -1)
                       if replacements.get(i) != ''), '')
        after = next((lines[i-1] for i in range(number+1, len(lines)+1)
                      if replacements.get(i) != ''), '')
        replacement = replacements.get(number, line)
        if before.strip() and not ANCHOR.fullmatch(before):
            replacement = eol + replacement
        if after.strip() and not ANCHOR.fullmatch(after):
            replacement += eol
        if replacement != line:
            replacements[number] = replacement

    edits = [(offsets[number-1], offsets[number], replacement)
             for number, replacement in replacements.items()]
    for number, labels in insertions.items():
        eol = '\r\n' if lines[number-1].endswith('\r\n') else '\n'
        previous = next((replacements.get(line, lines[line-1]) for line in range(number-1, 0, -1)
                         if replacements.get(line, lines[line-1])), '')
        prefix = eol if previous.strip() and not ANCHOR.fullmatch(previous) else ''
        body = ''.join('<a id="%s"></a>%s' % (label, eol) for label in labels)
        edits.append((offsets[number-1], offsets[number-1], prefix+body+eol))
    return sorted(edits)


def recover_navigation(baseline_path: str, manifest_path: str, official_toc_path: str,
                       site_root: str, navigation_record: str, *, chapter_path: str) -> str:
    current, ranges, pages, chapter = _recovery_inputs(
        baseline_path, manifest_path, official_toc_path, site_root, navigation_record, chapter_path)
    edits = []
    for page, (start, end) in ranges:
        body = current[start:end]
        linked = replace_links(body, lambda href: _recovery_href(pages, page, href, chapter))
        targets = _recovery_object_lines(linked, page, pages[page], chapter)
        anchor_edits = _recovery_anchor_edits(linked, page, targets, pages[page]['anchors'])
        edits.append((start, end, _apply_edits(linked, anchor_edits)))
    return _apply_edits(current, edits)


def _reverse_edits(candidate, baseline, edits):
    offset = 0
    reversed_edits = []
    for lo, hi, value in edits:
        start = lo + offset
        end = start + len(value)
        if candidate[start:end] != value:
            raise ValueError('导航候选编辑不符合来源或当前基准')
        reversed_edits.append((start, end, baseline[lo:hi]))
        offset += len(value)-(hi-lo)
    return _apply_edits(candidate, reversed_edits)


def verify_recovery(baseline_path: str, candidate_path: str, manifest_path: str,
                    official_toc_path: str, site_root: str, navigation_record: str,
                    *, chapter_path: str) -> list[str]:
    try:
        baseline, ranges, pages, chapter = _recovery_inputs(
            baseline_path, manifest_path, official_toc_path, site_root, navigation_record, chapter_path)
        candidate = Path(candidate_path).read_bytes().decode('utf-8')
        current_ranges = split_page_ranges(candidate)
        if len(current_ranges) != len(ranges):
            raise ValueError('导航候选改变合章页分隔')
        restored = []
        for (page, (lo, hi)), (start, end) in zip(ranges, current_ranges):
            before, actual = baseline[lo:hi], candidate[start:end]
            expected_links = [_recovery_href(pages, page, href, chapter) for href in links(before)]
            if links(actual) != expected_links:
                raise ValueError(page + ' 导航候选链接目标、数量或顺序改变')
            actual_objects = _recovery_object_lines(actual, page, pages[page], chapter)
            roles = pages[page]['anchors']
            if _recovery_anchor_edits(actual, page, actual_objects, roles):
                raise ValueError(page + ' 导航候选缺正确归属的源对象锚点')
            href_edits = _link_edits(before, lambda href: _recovery_href(pages, page, href, chapter))
            linked = _apply_edits(before, href_edits)
            targets = _recovery_object_lines(linked, page, pages[page], chapter)
            anchor_edits = _recovery_anchor_edits(linked, page, targets, roles)
            unmapped = _reverse_edits(actual, linked, anchor_edits)
            restored.append((start, end, _reverse_edits(unmapped, before, href_edits)))
        if _apply_edits(candidate, restored) != baseline:
            raise ValueError('导航候选反投影与当前基准字节不一致')
    except (ValueError, OSError, KeyError) as exc:
        return [str(exc)]
    return []


def navigation_dependencies(record_path):
    """重读既有来源记录声明的文件依赖，不把页索引另存为真值。"""
    import verify_delivery as delivery
    from _verification import file_sha256

    path = Path(record_path).resolve()
    record = json.loads(path.read_text(encoding='utf-8'))
    problems = []
    # API 解析稿可与快照分目录存放。依赖以已准入的快照资源路径为准。
    dependencies = delivery.source_dependency_paths(
        record['delivery_root'], record, problems, include_parsed_resources=False)
    if problems:
        raise ValueError('导航依赖不可核对: ' + '；'.join(problems))
    return [[str(item), file_sha256(item)] for item in sorted(set(dependencies) | {path})]


def navigation_context(record_path, site_root):
    record = str(Path(record_path).resolve())
    site = str(Path(site_root).resolve())
    before = navigation_dependencies(record)
    pages = load_navigation(record, site)
    if navigation_dependencies(record) != before:
        raise ValueError('导航来源在准入期间变化: ' + record)
    return {'record': record, 'site_root': site, 'pages': pages, 'dependencies': before}


def navigation_identity(contexts):
    return [{key: context[key] for key in ('record', 'site_root', 'inputs', 'dependencies')}
            for context in contexts]


def navigation_pairs(records, site_roots, *, base_dir=None):
    if len(records) != len(site_roots):
        raise ValueError('--navigation-record 与 --site-root 必须逐一配对')
    base = Path(base_dir or os.getcwd())
    return [(str((base / record).resolve()), str((base / site).resolve()))
            for record, site in zip(records, site_roots)]


def load_pdf_navigation(input_paths: list[str], declarations: list[tuple[str, str]],
                        readiness_projection: dict | None = None) -> list[dict]:
    inputs = [str(Path(path).resolve()) for path in input_paths]
    explicit = [(str(Path(record).resolve()), str(Path(site).resolve()))
                for record, site in declarations]
    expected = {(item['record'], item['site_root']): item
                for item in (readiness_projection or {}).get('api_navigation', ())}
    if readiness_projection is not None and explicit and set(explicit) != set(expected):
        raise ValueError('显式 API 导航记录/站点根与翻译就绪检查不一致')
    pairs = explicit or list(expected)
    if len(set(pairs)) != len(pairs):
        raise ValueError('API 导航记录与站点根重复')
    owner = {}
    site_pages = {}
    contexts = []
    for record, site in pairs:
        context = navigation_context(record, site)
        if not context['pages']:
            raise ValueError('导航记录未声明 API 来源页: ' + record)
        pool = site_pages.setdefault(site, {})
        overlap = pool.keys() & context['pages'].keys()
        if overlap:
            raise ValueError('API 来源页归属冲突: ' + '、'.join(sorted(overlap)))
        pool.update(context['pages'])
        covers = {str(facts['chapter']) for facts in context['pages'].values()}
        for chapter in covers:
            if chapter in owner:
                raise ValueError('API 目标章归属冲突: ' + chapter)
            owner[chapter] = record
        context['inputs'] = [path for path in inputs if path in covers]
        contexts.append(context)
        if (record, site) in expected and navigation_identity([context])[0] != expected[(record, site)]:
            raise ValueError('API 导航来源依赖或 covers 与翻译就绪检查不一致: ' + record)
    for context in contexts:
        context['site_pages'] = site_pages[context['site_root']]
    return contexts


def _page_entry_names(text):
    fenced = fenced_line_numbers(text.replace('\r\n', '\n'))
    return [(line, match[1]) for line, value in enumerate(text.splitlines(), 1)
            if line not in fenced and (match := ANCHOR.fullmatch(value))
            and re.fullmatch(r'src-[0-9a-f]+-p', match[1])]


def verify_pdf_navigation(input_paths: list[str], contexts: list[dict]) -> list[dict]:
    """只读核对 API Markdown 已正规化且来源对象可证。"""
    by_chapter = {path: context for context in contexts for path in context['inputs']}
    diagnostics = []
    for path in map(Path, input_paths):
        chapter = path.resolve()
        context = by_chapter.get(str(chapter))
        try:
            text = chapter.read_bytes().decode('utf-8')
            entries = _page_entry_names(text)
            if context is None:
                if entries:
                    raise ValueError('API 源页入口缺少 --navigation-record 和 --site-root')
                continue
            own = {namespaced(page, None): page for page, facts in context['pages'].items()
                   if facts['chapter'] == chapter}
            pages = context['site_pages']
            if not entries and not any(requires_navigation(
                    pages[key]['raw'], text, section_id=pages[key]['section_id']) for key in own.values()):
                continue
            if {name for _, name in entries} != set(own) or len(entries) != len(own):
                raise ValueError('API 源页入口与导航记录 covers 不闭合')
            spans = split_page_ranges(text)
            if len(spans) != len(own):
                raise ValueError('API 当前章页面分隔与来源覆盖不闭合')
            for start, end in spans:
                body = text[start:end]
                (_, entry), = _page_entry_names(body)
                page = own[entry]
                roles = pages[page]['anchors']
                line_offset = text.count('\n', 0, start)
                for block in _link_blocks(body):
                    for index, token in enumerate(block.children):
                        if token.type != 'link_open':
                            continue
                        href = token.attrGet('href')
                        try:
                            if _recovery_href(pages, page, href, chapter) != href:
                                raise ValueError('仍含未正规化的来源链接')
                        except ValueError as exc:
                            label = []
                            for child in block.children[index+1:]:
                                if child.type == 'link_close':
                                    break
                                label.append(child.content)
                            diagnostics.append({'code': 'api-navigation-link', 'input': str(chapter),
                                'line': line_offset + block.map[0]+1, 'href': href,
                                'link_text': ''.join(label),
                                'message': '%s: 链接 %r（%s）%s' % (page, ''.join(label), href, exc)})
                targets = _recovery_object_lines(body, page, pages[page], chapter)
                if _recovery_anchor_edits(body, page, targets, roles):
                    raise ValueError('来源对象锚点缺失、错绑或未正规化: ' + page)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            diagnostics.append({'code': 'api-navigation-source', 'input': str(chapter),
                                'message': str(exc)})
    return diagnostics
