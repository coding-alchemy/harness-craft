"""Build the ordered reading content and its links to the original evidence."""

import hashlib
import html
from html.parser import HTMLParser
from itertools import chain
import json
import math
from pathlib import Path, PurePosixPath
import re
from zipfile import BadZipFile, ZipFile

import pymupdf

from capture import read_raw


VISUAL = {'image', 'table', 'chart', 'code'}
CONTAINERS = VISUAL | {'list', 'index'}
PAGE_LABELS = {'blank': '原页空白', 'failed': '原页有内容，未识别出正文', 'unknown': '原页待核对，未识别出正文',
               'illustration_only': '已对照整页及配图，原页仅含插图'}


class TableParser(HTMLParser):
    """Read cell content and spans from the engine's table HTML."""

    INLINE = {'b', 'strong', 'i', 'em', 'u', 's', 'sup', 'sub', 'code'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.rows = []
        self.cell = None
        self.styled = False
        self.equation = None

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        if parent == 'eq':
            raise ValueError('表格公式含无法验证的嵌套元素')
        if tag == 'br' and self.cell is not None and not attrs:
            self.cell['text'] += '\n'
            self.cell['markup'] += '<br>'
            return
        if tag == 'table' and parent is None and not self.rows and not attrs:
            pass
        elif tag in {'thead', 'tbody', 'tfoot'} and parent == 'table' and not attrs:
            pass
        elif tag == 'tr' and parent in {'table', 'thead', 'tbody', 'tfoot'} and not attrs:
            self.rows.append([])
        elif tag in {'td', 'th'} and parent == 'tr':
            dimensions = dict(attrs)
            if len(dimensions) != len(attrs) or set(dimensions) - {'rowspan', 'colspan'}:
                raise ValueError('表格单元格属性无法验证')
            row_span = int(dimensions.get('rowspan', '1') or '0')
            col_span = int(dimensions.get('colspan', '1') or '0')
            if not (1 <= row_span <= 1000 and 1 <= col_span <= 1000):
                raise ValueError('表格跨行或跨列值无效')
            self.cell = dict(tag=tag, rowspan=row_span, colspan=col_span, text='', markup='')
            self.rows[-1].append(self.cell)
        elif tag == 'eq' and self.cell is not None and not attrs:
            self.styled = True
            self.equation = []
        elif tag in self.INLINE and self.cell is not None and not attrs:
            self.styled = True
            self.cell['markup'] += f'<{tag}>'
        else:
            raise ValueError(f'无法验证表格元素 {tag}')
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag != 'br':
            raise ValueError(f'无法验证表格元素 {tag}')
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError(f'表格标签 {tag} 未正确闭合')
        if tag in {'td', 'th'}:
            self.cell = None
        elif tag == 'eq':
            latex = ''.join(self.equation).strip()
            self.equation = None
            if not latex:
                raise ValueError('表格公式缺少 LaTeX')
            self.handle_data(f' ${latex}$ ')
        elif tag in self.INLINE:
            self.cell['markup'] += f'</{tag}>'

    def handle_data(self, data):
        if self.equation is not None:
            self.equation.append(data)
        elif self.cell is not None:
            self.cell['text'] += data
            self.cell['markup'] += html.escape(data, quote=False)
        elif data.strip():
            raise ValueError('表格含无单元格归属的文字')

    def finish(self):
        self.close()
        if self.stack or not self.rows or not any(cell['text'].strip() for row in self.rows for cell in row):
            raise ValueError('表格缺少完整的可读单元格')
        occupied = [set() for _ in self.rows]
        for y, row in enumerate(self.rows):
            x = 0
            for cell in row:
                while x in occupied[y]:
                    x += 1
                cell['column'] = x + 1
                span_rows = y + cell['rowspan']
                columns = set(range(x, x + cell['colspan']))
                if span_rows > len(self.rows) or any(occupied[i] & columns for i in range(y, span_rows)):
                    raise ValueError('表格跨列或跨行超出范围')
                for i in range(y, span_rows):
                    occupied[i].update(columns)
                x += cell['colspan']
        width = len(occupied[0])
        if not width or any(row != set(range(width)) for row in occupied):
            raise ValueError('表格各行列数不一致')
        return self.rows


def escape_literal(text, *, cell=False):
    literal = html.escape(text, quote=False)
    literal = re.sub(r'([\\|`*_\[\]~$])', r'\\\1', literal)
    if cell:
        return literal.replace('\n', '<br>')
    literal = re.sub(r'^( {0,3})([#+=\-])', r'\1\\\2', literal, flags=re.M)
    return re.sub(r'^( {0,3}\d{1,9})([.)])(?=\s|$)', r'\1\\\2', literal, flags=re.M)


def reviewed_list_text(block, new):
    # Review strings use the original inline representation. Retain explicit formatting
    # from that representation while quoting ordinary replacement text for the reader.
    original = block['list_markdown']
    formats = [rf'</?{tag}>' for tag in ('sub', 'sup') if f'<{tag}>' in original]
    if re.search(r'(?<!\\)\$', original):
        formats.append(r'\$[^$\n]+\$')
    parts = re.split('(' + '|'.join(formats) + ')', new) if formats else [new]
    return ''.join(part if i % 2 else escape_literal(html.unescape(part)) for i, part in enumerate(parts))


def _inline(content, *, literal=False):
    if isinstance(content, str):
        return escape_literal(content) if literal else content
    if not isinstance(content, list):
        return ''
    output = []
    for span in content:
        if not isinstance(span, dict):
            continue
        text = span.get('content', '')
        if span.get('type') == 'equation_inline' and isinstance(text, str):
            output.append(f'${text}$')
        elif isinstance(text, list):
            output.append(_inline(text, literal=literal))
        elif isinstance(text, str):
            escaped = escape_literal(text) if literal else html.escape(text, quote=False)
            styles = span.get('styles') or []
            if 'superscript' in styles:
                escaped = f'<sup>{escaped}</sup>'
            elif 'subscript' in styles:
                escaped = f'<sub>{escaped}</sub>'
            output.append(escaped)
    return ''.join(output)


def _location(page, size, raw, identity, path):
    box = raw.get('bbox')
    location = {
        'raw_refs': [{'member': 'middle_json.json', 'path': path}],
        'raw_bbox': box, 'bbox_unit': 'ratio', 'bbox_space': 'engine-page',
        'bbox': None, 'bbox_transform': None, 'bbox_reason': None,
    }
    if 'bbox' not in raw or box is None:
        location['bbox_reason'] = '原始块没有独立坐标'
        return location
    if (not isinstance(box, list) or len(box) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise ValueError(f'第 {identity["page"]} 物理页原始记录 {path}: bbox 无效 {box!r}')
    width, height = size.get('width_pt'), size.get('height_pt')
    if any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in (width, height)):
        location['bbox_reason'] = '缺少与原框同向的引擎页宽高'
        return location
    if not (math.isclose(width, page.rect.width, abs_tol=.5)
            and math.isclose(height, page.rect.height, abs_tol=.5)):
        location['bbox_reason'] = '引擎页宽高与源页可见范围不符'
        return location
    x0, y0, x1, y1 = box
    visible = pymupdf.Rect(x0 * width, y0 * height, x1 * width, y1 * height) & page.rect
    if visible.is_empty:
        raise ValueError(f'第 {identity["page"]} 物理页原始记录 {path}: bbox 越出可见页')
    point = page.cropbox_position
    canonical = visible * page.derotation_matrix + (point.x, point.y, point.x, point.y)
    location['bbox'] = list(canonical)
    location['bbox_transform'] = {
        'width_pt': width, 'height_pt': height, 'rotation': page.rotation,
        'cropbox_offset': list(point), 'space': 'pdf-unrotated-top-left-pt',
    }
    return location


def check_image(data):
    try:
        pymupdf.Pixmap(data)
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase) as exc:
        raise ValueError('图片无法解码') from exc


def _image_asset(archive, ref, page, block, assets, *, crop=False):
    if not ref and not (crop and block['bbox']):
        return
    if ref:
        if not isinstance(ref, str) or '\\' in ref:
            raise ValueError(f'{block["id"]}: 图片引用无效 {ref!r}')
        path = PurePosixPath(ref)
        if path.is_absolute() or '..' in path.parts or str(path) != ref or not path.suffix:
            raise ValueError(f'{block["id"]}: 图片引用无效 {ref!r}')
        try:
            data = archive.read(ref)
            check_image(data)
        except (KeyError, RuntimeError, ValueError, BadZipFile) as exc:
            raise ValueError(f'{block["id"]}: ZIP 图片 {ref} 缺失或无法解码') from exc
        suffix = path.suffix.lower()
        if suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}:
            raise ValueError(f'{block["id"]}: 图片格式无效 {ref}')
    else:
        offset = page.cropbox_position
        local = pymupdf.Rect(block['bbox']) - (offset.x, offset.y, offset.x, offset.y)
        visible = local * page.rotation_matrix
        data = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=visible, alpha=False).tobytes('png')
        suffix = '.png'
    name = f'assets/{block["id"]}{suffix}'
    binding = {'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'raw_asset': ref or None}
    assets[name] = {**binding, 'bytes': data}
    block['assets'].append(binding)


def _table(block, text):
    parser = TableParser()
    try:
        parser.feed(text)
        rows = parser.finish()
    except (ValueError, TypeError):
        block['issues'].append('表格行列无法可靠还原，请查看原区域或原页')
        return
    if parser.styled or any(cell['rowspan'] != 1 or cell['colspan'] != 1 for row in rows for cell in row):
        block['table'] = rows
        block['issues'].append('复杂表格含跨行、跨列或富文本，请对照原页核对表头与单元格')
    else:
        block['cells'] = [[cell['text'].strip() for cell in row] for row in rows]


def _block(raw, view, page, geometry, size, block_id, path, archive, assets):
    kind = raw['type']
    loc = _location(page, size, raw, geometry, path)
    block = dict(id=block_id, page=geometry['page'], type=kind, text='', children=[], issues=[], assets=[], **loc)
    content = raw.get('content')
    rendered = view.get('content')
    if kind in CONTAINERS:
        if not isinstance(content, list) or any(not isinstance(child, dict) or 'type' not in child for child in content):
            raise ValueError(f'{block_id}: 组合块缺少可定位的子块')
        for position, child in enumerate(content):
            built = _block(child, {}, page, geometry, size, f'{block_id}-c{position}',
                           f'{path}/content/{position}', archive, assets)
            if kind in {'list', 'index'} and child['type'] in {'text', 'ref_text'}:
                built['list_markdown'] = _inline(child.get('content'), literal=True)
            block['children'].append(built)
            block['raw_refs'].extend(built['raw_refs'])
    elif kind != 'table_body':
        block['text'] = rendered if isinstance(rendered, str) else _inline(content)
    if kind in {'doc_title', 'paragraph_title'}:
        level = raw.get('level', 1 if kind == 'doc_title' else 2)
        if type(level) is not int or not 1 <= level <= 6:
            raise ValueError(f'{block_id}: 标题层级无效')
        block['level'] = level
    if kind in VISUAL:
        bodies = [child for child in content if child['type'].endswith('_body')]
        if len(bodies) != 1:
            raise ValueError(f'{block_id}: 无法确定 {kind} 正文记录')
        body = bodies[0]
        ref = body.get('image_path') or view.get('image_source')
        if kind == 'table':
            _table(block, body.get('content', ''))
        elif kind == 'chart':
            block['issues'].append('复杂图表，请对照原页核对内容')
        _image_asset(archive, ref, page, block, assets, crop=kind in {'image', 'chart'} or bool(block['issues']))
        if kind == 'image' and not block['assets']:
            block['issues'].append('识别记录缺少原图，请查看物理页')
    if kind == 'equation':
        if not block['text'].strip():
            block['issues'].append('公式无法可靠还原，请查看原区域或原页')
        _image_asset(archive, raw.get('image_path'), page, block, assets, crop=bool(block['issues']))
    if raw.get('continues_prev'):
        block['issues'].append('与前段存在续接关系，请核对阅读顺序')
        block['continues_prev'] = True
    if raw.get('uncertain') or raw.get('status') in {'uncertain', 'failed'}:
        block['issues'].append('引擎标记为待核对')
    if kind not in CONTAINERS and not kind.endswith('_body') and kind != 'equation' and not block['text'].strip():
        block['issues'].append('识别块缺少可读文字，请查看物理页')
    return block


def descendants(block):
    yield block
    for child in block['children']:
        yield from descendants(child)


def readable(block):
    kind = block['type']
    own = block['cells'] if 'cells' in block else block.get('table') or block['text'].strip()
    return bool(own and kind not in {'image_body', 'chart_body', 'table_body'}) or any(
        readable(child) for child in block['children']
    )


def _page_status(page, blocks):
    if any(readable(block) for block in blocks):
        return 'readable'
    pixmap = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
    pixels = pixmap.samples
    if pixels and pixels.count(255) == len(pixels):
        return 'blank'
    return 'failed' if page.get_text().strip() else 'unknown'


def _paragraph_predecessor(block, preceding, list_types):
    kind = block['type']
    for candidate in preceding:
        other = candidate['type']
        if other in {'aside_text', 'page_footnote'} or (kind == 'text' and other in VISUAL):
            continue
        if kind == other and kind in {'text', 'ref_text'}:
            return candidate
        if other == 'list':
            subtype = list_types[candidate['id']]
            if kind == 'text' and subtype == 'text' and candidate['children']:
                tail = candidate['children'][-1]
                if tail['type'] == 'text':
                    return tail
            if kind == 'list' and subtype == list_types[block['id']] == 'ref_text':
                return candidate
        return None
    return None


def build_document(pdf: Path, raw_dir: Path) -> dict:
    result = read_raw(pdf, raw_dir)
    source = result['source']
    layout = result['middle'].get('extensions', {}).get('docvortex_layout', {})
    sizes = {item['page_idx']: item for item in layout.get('pages', [])} if layout.get('version') == 1 else {}
    document = dict(source=source, pages=[], blocks=[], assets={})
    previous_page = []
    previous_page_table = None
    list_types = {}
    with pymupdf.open(pdf) as original, ZipFile(raw_dir / 'engine.zip') as archive:
        for geometry, raw_page, view_page in zip(source['pages'], result['middle']['pages'], result['structured']['pages']):
            index = raw_page['page_idx']
            page = original[index]
            blocks, excluded = [], []
            for offset, (raw, view) in enumerate(zip(raw_page['blocks'], view_page['blocks'])):
                block = _block(raw, view, page, geometry, sizes.get(index, {}),
                               f'p{index+1:04d}-b{raw["index"]:04d}', f'/pages/{index}/blocks/{offset}',
                               archive, document['assets'])
                if block['type'] in {'header', 'footer', 'page_number'}:
                    excluded.append(dict(block, reason=f'原始记录标为 {block["type"]}，不计入正文'))
                else:
                    blocks.append(block)
                    if block['type'] == 'list':
                        list_types[block['id']] = raw.get('sub_type')
            status = _page_status(page, blocks)
            issues = [PAGE_LABELS[status]] if status in {'failed', 'unknown'} else []
            for position, block in enumerate(blocks):
                if not block.get('continues_prev'):
                    continue
                if block['type'] == 'table':
                    predecessor, kind = previous_page_table, '续表'
                else:
                    preceding = chain(reversed(blocks[:position]), reversed(previous_page))
                    predecessor, kind = _paragraph_predecessor(block, preceding, list_types), '续段'
                if predecessor is None:
                    issues.append(f'{block["id"]} 无法确定{kind}来源，请对照本页及前一物理页')
                else:
                    block['continues_from'] = predecessor['id']
            previous_page = blocks
            previous_page_table = next((block for block in reversed(blocks) if block['type'] == 'table'), None)
            document['pages'].append(dict(geometry, status=status, issues=issues, excluded=excluded,
                                          block_ids=[block['id'] for block in blocks]))
            document['blocks'].extend(blocks)
    return document


def table_markdown(block):
    if 'cells' in block:
        cells = block['cells']
        lines = ['| ' + ' | '.join(escape_literal(cell, cell=True) for cell in row) + ' |' for row in cells]
        lines.insert(1, '| ' + ' | '.join('---' for _ in cells[0]) + ' |')
        return '\n'.join(lines)
    if 'table' in block:
        rows = []
        for row in block['table']:
            cells = []
            for cell in row:
                tag = cell['tag']
                attrs = ''.join(f' {key}="{cell[key]}"' for key in ('rowspan', 'colspan') if cell[key] > 1)
                cells.append(f'<{tag}{attrs}>{cell["markup"]}</{tag}>')
            rows.append('<tr>' + ''.join(cells) + '</tr>')
        return '<table>' + ''.join(rows) + '</table>'
    return ''


def block_markdown(block):
    kind, text = block['type'], block['text']
    marker = f'<!-- block:{block["id"]} -->'
    body_notices = []
    if kind in {'list', 'index'}:
        lines = []
        for child in block['children']:
            child_lines = block_markdown(child).splitlines()
            lines.extend(['- ' + child_lines[0], *('  ' + line for line in child_lines[1:])])
        content = '\n'.join(lines)
    elif kind in VISUAL:
        children = [child for child in block['children'] if not child['type'].endswith('_body')]
        body_notices = [block_markdown(dict(child, text='')) for child in block['children']
                        if child['type'].endswith('_body') and child['issues']]
        content = table_markdown(block) if kind == 'table' else ''
        if kind == 'code':
            body = next(child for child in block['children'] if child['type'].endswith('_body'))
            fence = '`' * (max((len(part) for part in body['text'].split() if set(part) == {'`'}), default=2) + 1)
            content = f'{fence}\n{body["text"]}\n{fence}'
        suffix = '\n\n'.join(block_markdown(child) for child in children)
        content = '\n\n'.join(part for part in (content, suffix) if part)
    elif 'level' in block:
        content = f'{"#" * block["level"]} {text}'
    elif kind == 'equation' and text:
        content = f'$$\n{text}\n$$'
    else:
        content = block.get('list_markdown', text)
    images = '\n\n'.join(f'![物理页 {block["page"]} 原区域]({asset["path"]})' for asset in block['assets'])
    if kind == 'image':
        content, images = images, content
    notices = [f'> 待核对（物理页 {block["page"]}，{block["id"]}）{message}' for message in block['issues']]
    return '\n\n'.join(part for part in (marker, content, images, *body_notices, *notices) if part)


def reading_files(document):
    blocks = {block['id']: block for block in document['blocks']}
    markdown = []
    for page in document['pages']:
        markdown.append(f'<!-- page:{page["page"]} -->')
        if page['status'] in PAGE_LABELS:
            markdown.append(f'> 物理页 {page["page"]}　{PAGE_LABELS[page["status"]]}')
        markdown.extend(f'> 待核对（物理页 {page["page"]}）{issue}' for issue in page['issues']
                        if issue != PAGE_LABELS.get(page['status']))
        markdown.extend(block_markdown(blocks[ref]) for ref in page['block_ids'])
    locations = {
        block['id']: {key: block[key] for key in ('page', 'raw_refs', 'bbox', 'bbox_reason')}
        for root in document['blocks'] for block in descendants(root)
    }
    return {
        'document.md': '\n\n'.join(markdown) + '\n',
        'blocks.jsonl': ''.join(json.dumps(block, ensure_ascii=False, allow_nan=False) + '\n' for block in document['blocks']),
        'source-map.json': json.dumps(dict(source=document['source'], pages=document['pages'], blocks=locations),
                                      ensure_ascii=False, allow_nan=False, indent=2) + '\n',
    }


def write_reading(document: dict, out: Path) -> None:
    (out / 'assets').mkdir(exist_ok=True)
    for name, asset in document['assets'].items():
        (out / name).write_bytes(asset['bytes'])
    for name, content in reading_files(document).items():
        (out / name).write_text(content, encoding='utf-8')
