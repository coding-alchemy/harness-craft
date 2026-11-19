"""Apply source-bound review records and evaluate the effective reading package."""

from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import html
import json
from pathlib import Path
import re

from reading import PAGE_LABELS, block_markdown, descendants, readable, reviewed_list_text, table_markdown


def _without_notices(block):
    return dict(block, issues=[], children=[_without_notices(child) for child in block['children']])


def _block_content(block):
    return [block_markdown(_without_notices(block)),
            [asset['sha256'] for part in descendants(block) for asset in part['assets']]]


def content_digest(document: dict, *, page=None, block_id=None) -> str:
    """Bind visible content, rendered order, and referenced image bytes to a review target."""
    if (page is None) == (block_id is None):
        raise ValueError('需要选择一个物理页或块 ID')
    if page is None:
        match = next(((root, block) for root in document['blocks']
                      for block in descendants(root) if block['id'] == block_id), None)
        if match is None:
            raise ValueError(f'找不到 block_id {block_id!r}')
        root, block = match
        if root['type'] == 'table' and block['type'] == 'table_body':
            content = [table_markdown(root), [asset['sha256'] for asset in root['assets']]]
        else:
            content = _block_content(block)
        parts = [content]
    else:
        if not any(record['page'] == page for record in document['pages']):
            raise ValueError(f'找不到物理页 {page}')
        parts = [_block_content(block) for block in document['blocks'] if block['page'] == page]
    payload = [page, parts]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _replace_cell_run(old, new, markup, location):
    # The table parser already canonicalized tags and escaped literal angle brackets.
    # A replacement is unambiguous if exactly one rendering preserves every other run.
    start = 0
    candidates = set()
    for match in re.finditer(r'<[^>]+>|[^<]+', markup):
        part = match[0]
        if part == '<br>':
            start += 1
        elif not part.startswith('<'):
            end = start + len(html.unescape(part))
            prefix, suffix = old[:start], old[end:]
            if (len(new) >= len(prefix) + len(suffix)
                    and new.startswith(prefix) and new.endswith(suffix)):
                value = new[start:len(new) - len(suffix)]
                escaped = html.escape(value, quote=False).replace('\n', '<br>')
                candidates.add(markup[:match.start()] + escaped + markup[match.end():])
            start = end
    if len(candidates) != 1:
        raise ValueError(f'{location} 无法唯一定位更正并保留同格格式')
    return candidates.pop()


def _corrected_cell_markup(cell, new, location):
    old, markup = cell['text'], cell['markup']
    if markup == html.escape(old, quote=False).replace('\n', '<br>'):
        return html.escape(new, quote=False).replace('\n', '<br>')
    # Work backwards so offsets to the left still refer to the original text.
    for op, a, b, c, d in reversed(SequenceMatcher(None, old, new, autojunk=False).get_opcodes()):
        if op != 'equal':
            edited = old[:a] + new[c:d] + old[b:]
            markup = _replace_cell_run(old, edited, markup, location)
            old = edited
    return markup


def _change(item, block, label, destinations):
    old, new = item.get('old'), item.get('new')
    if not isinstance(old, str) or not isinstance(new, str) or old == new:
        raise ValueError(f'{label} 需要不同的字符串 old 和 new')
    if 'row' in item or 'column' in item:
        row, column = item.get('row'), item.get('column')
        rows = block.get('cells') or block.get('table') or []
        if type(row) is not int or type(column) is not int or not 1 <= row <= len(rows) or column < 1:
            raise ValueError(f'{label} 行列不存在或表格结构无法验证')
        if 'cells' in block and column <= len(rows[row - 1]):
            target, key = rows[row - 1], column - 1
        elif 'table' in block:
            target = next((cell for cell in rows[row - 1] if cell['column'] == column), None)
            if target is None:
                raise ValueError(f'{label} 行列无单元格起点，请按合并格左上角定位')
            key = 'text'
        else:
            raise ValueError(f'{label} 列不存在')
    else:
        if not block['text'].strip() or not new.strip():
            raise ValueError(f'{label} 需要可读的正文原值和替换值')
        row, column = None, None
        target, key = block, 'text'
    destination = (block['id'], row, column)
    if destination in destinations and destinations[destination] != new:
        raise ValueError(f'{label} 更正与先前记录冲突（{destination}）')
    if target[key] != old:
        raise ValueError(f'{label} old 与原始识别值不符（{target[key]!r}）')
    if destination in destinations:
        return []
    destinations[destination] = new
    changes = [(target, key, new)]
    if row is not None and 'table' in block:
        location = f'{label} {block["id"]} 第 {row} 行第 {column} 列'
        changes.append((target, 'markup', _corrected_cell_markup(target, new, location)))
    elif row is None and 'list_markdown' in block:
        changes.append((block, 'list_markdown', reviewed_list_text(block, new)))
    return changes


def apply_review(document: dict, review: dict | None) -> dict:
    effective = deepcopy(document)
    effective.update(reviewed=[], corrections=[])
    if review is None:
        return effective
    if not isinstance(review, dict):
        raise ValueError('review.json 应为对象')
    for identity in ('pdf_sha256', 'zip_sha256'):
        if review.get(identity) != document['source'][identity]:
            raise ValueError(f'review.json {identity} 与原始包不符')
    items = review.get('items')
    if not isinstance(items, list):
        raise ValueError('review.json items 应为数组')
    pages = {record['page']: record for record in effective['pages']}
    blocks = {block['id']: block for root in effective['blocks'] for block in descendants(root)}
    seen = {}
    destinations = {}
    changes, claims = [], []
    for number, item in enumerate(items, 1):
        label = f'review.json 第 {number} 项'
        if not isinstance(item, dict) or ('page' in item) == ('block_id' in item):
            raise ValueError(f'{label} 必须选择 page 或 block_id')
        page, block_id = item.get('page'), item.get('block_id')
        if 'page' in item:
            if type(page) is not int or page not in pages:
                raise ValueError(f'{label} 找不到物理页 {page!r}')
            target = pages[page]
        else:
            if not isinstance(block_id, str) or block_id not in blocks:
                raise ValueError(f'{label} 找不到 block_id {block_id!r}')
            target = blocks[block_id]
        outcome = item.get('outcome')
        evidence, digest = item.get('evidence'), item.get('content_sha256')
        if outcome not in ('confirmed', 'corrected', 'unresolved'):
            raise ValueError(f'{label} outcome 无效')
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f'{label} 缺少原页依据 evidence')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(f'{label} content_sha256 无效')
        state = item.get('page_state')
        if 'page_state' in item:
            if page is None or outcome != 'confirmed' or state not in ('blank', 'has_content', 'illustration_only'):
                raise ValueError(f'{label} page_state 需要已确认的页项')
            if (state == 'blank' and target['status'] in ('readable', 'failed')
                    or state == 'has_content' and target['status'] == 'blank'):
                raise ValueError(f'{label} page_state 与物理页现有证据冲突')
        if outcome == 'corrected':
            if block_id is None:
                raise ValueError(f'{label} 更正项必须有 block_id')
            changes.extend(_change(item, target, label, destinations))
        if outcome != 'corrected' and set(item) & {'old', 'new', 'row', 'column'}:
            raise ValueError(f'{label} 只有更正项可声明原值、替换值或行列')
        if 'row' not in item:
            key = (page, block_id)
            settled = outcome != 'unresolved'
            prior_settled, prior_state = seen.get(key, (settled, None))
            if prior_settled != settled or (state and prior_state and state != prior_state):
                raise ValueError(f'{label} 与同一位置的先前结论冲突')
            seen[key] = (settled, state or prior_state)
        claims.append((item, page, block_id, target))

    for target, key, replacement in changes:
        target[key] = replacement
    evaluations = [
        (item, page, block_id, target, item['content_sha256'] == content_digest(effective, page=page, block_id=block_id))
        for item, page, block_id, target in claims
    ]
    unsettled = {(page, block_id) for item, page, block_id, _, matches in evaluations
                 if 'row' not in item and (not matches or item['outcome'] == 'unresolved')}
    illustration_pages = set()
    for item, page, block_id, target, _ in evaluations:
        if 'row' in item or (page, block_id) in unsettled:
            continue
        target['issues'].clear()
        state = item.get('page_state')
        if state == 'blank':
            target['status'] = 'blank'
        elif state == 'has_content' and target['status'] == 'unknown':
            target['status'] = 'failed'
        elif state == 'illustration_only':
            illustration_pages.add(page)
    for item, page, block_id, target, matches in evaluations:
        outcome = item['outcome'] if matches else 'unresolved'
        location = {'page': target['page']}
        if block_id:
            location['block_id'] = block_id
        if outcome == 'unresolved':
            issue = '原页复核仍存疑：' + item['evidence'] if matches else '所核内容或顺序已变化，待复核'
            if issue not in target['issues']:
                target['issues'].append(issue)
        checked = dict(location, outcome=outcome, evidence=item['evidence'], content_sha256=item['content_sha256'])
        if item.get('page_state'):
            checked['page_state'] = item['page_state']
        if 'row' in item:
            checked.update(row=item['row'], column=item['column'])
        effective['reviewed'].append(checked)
        if item['outcome'] == 'corrected':
            effective['corrections'].append(dict(checked, **{
                key: item[key] for key in ('old', 'new')
            }))
    confirmed_images = {bid for item, _, bid, block, matches in evaluations
                        if matches and item['outcome'] == 'confirmed' and block.get('type') == 'image'
                        and block['assets'] and not any(part['issues'] for part in descendants(block))}
    for number in illustration_pages:
        page = pages[number]
        if page['status'] == 'unknown' and page['block_ids'] and confirmed_images.issuperset(page['block_ids']):
            page['status'] = 'illustration_only'
        else:
            page['issues'].append('仅插图的确认与页内容或图块复核结果不符，请核对整页')
    return effective


def assess(document: dict, integrity_errors: list[str]) -> dict:
    pages, blocks = document['pages'], document['blocks']
    reviewed = document.get('reviewed', [])
    confirmed_pages = {item['page'] for item in reviewed if item['outcome'] == 'confirmed' and 'block_id' not in item}
    confirmed_blocks = {item['block_id'] for item in reviewed
                        if item['outcome'] != 'unresolved' and 'block_id' in item and 'row' not in item}
    required_pages = {pages[index]['page'] for index in (0, (len(pages) - 1) // 2, len(pages) - 1)} if pages else set()
    missing = sorted(required_pages - confirmed_pages)
    pending = [f'物理页 {p} 尚未完成抽查' for p in missing]
    for page in pages:
        number, state = page['page'], page['status']
        if state in {'unknown', 'failed'}:
            pending.append(f'物理页 {number} {PAGE_LABELS[state]}')
        pending.extend(f'物理页 {number} {issue}' for issue in page['issues'] if issue != PAGE_LABELS.get(state))
    for root in blocks:
        for block in descendants(root):
            block_id, page = block['id'], block['page']
            pending.extend(f'物理页 {page} {block_id} {issue}' for issue in block['issues'])
            difficult = 'table' in block or block['type'] in {'equation', 'chart'}
            if difficult and not block['issues'] and block_id not in confirmed_blocks and page not in confirmed_pages:
                pending.append(f'物理页 {page} {block_id} 难辨版面尚未复核')
    fully_blank = bool(pages) and all(page['status'] == 'blank' for page in pages)
    if integrity_errors:
        status, reasons = '失败', list(integrity_errors)
    elif not any(readable(block) for block in blocks) and not fully_blank:
        status, reasons = '失败', ['整本没有可读正文，且存在有内容或尚未确认空白的物理页'] + pending
    elif pending:
        status, reasons = '降级', pending
    else:
        status, reasons = '通过', ['完整性检查通过，要求的原页复核与问题处理已完成']
    return dict(status=status, reasons=reasons, integrity_errors=list(integrity_errors),
                pages=pages, reviewed=reviewed, corrections=document.get('corrections', []))


def report_markdown(result: dict) -> str:
    lines = ['# 质量报告', '', f'**整体结论：{result["status"]}**', '', '## 判定原因', '']
    lines.extend(f'- {reason}' for reason in result['reasons'])
    lines.extend(['', '## 机器检查', ''])
    if result['integrity_errors']:
        lines.extend(f'- {error}' for error in result['integrity_errors'])
    else:
        lines.append('- 页覆盖、逐块来源、坐标与配图完整性通过。')
    lines.extend(['', '## 物理页与排除项', ''])
    for page in result['pages']:
        state = PAGE_LABELS.get(page['status'], '已识别正文')
        lines.append(f'- 物理页 {page["page"]}　{state}。')
        for block in page['excluded']:
            lines.append(f'  - {block["id"]}　{block["reason"]}。原文：{block["text"]}')
    lines.extend(['', '## 原页复核', ''])
    if not result['reviewed']:
        lines.append('- 尚无随包的原页复核记录。')
    for item in result['reviewed']:
        location = f'物理页 {item["page"]} {item.get("block_id", "")}'.rstrip()
        lines.append(f'- {location}　{item["outcome"]}。{item["evidence"]}')
    if result['corrections']:
        lines.extend(['', '## 更正', ''])
        for item in result['corrections']:
            cell = f'第 {item["row"]} 行第 {item["column"]} 列' if 'row' in item else '正文'
            lines.append(f'- 物理页 {item["page"]} {item["block_id"]} {cell}　'
                         f'{item["old"]!r} → {item["new"]!r}。{item["evidence"]}')
    return '\n'.join(lines) + '\n'


def write_report(result: dict, out: Path) -> None:
    (out / 'qa-report.md').write_text(report_markdown(result), encoding='utf-8')
