"""解析期显示尺寸映射 → 交付级映射的通用绑定核心。

`merge_api.py`（自动合并绑定）与 `rebuild_images_display.py`（通用回补）
共用本核心：逐次出现按源出现顺序对账实际 Markdown 引用，以独立来源
资源身份核对（解析期记录的 resource_sha256），确定项与未确定项分开
保留并按目标文档重编号。任一出现无法核对即拒绝整份候选映射，不产生
部分成功的映射，也不覆盖既有交付映射。
"""
import json
import os

from _html_fidelity import DISPLAY_MAP_VERSION
from _verification import file_sha256, resource_identity_digest


class BindingError(ValueError):
    """绑定失败：出现数、顺序或任一身份核对不通过。"""


def validate_parse_map(payload, label='解析期映射'):
    """校验解析期映射结构与版本；未知主版本或字段类型非法即失败。"""
    if not isinstance(payload, dict):
        raise BindingError('%s: 顶层必须是 JSON 对象' % label)
    version = payload.get('version')
    if version != DISPLAY_MAP_VERSION:
        raise BindingError('%s: 未知映射版本 %r（当前支持 version=%d）'
                           % (label, version, DISPLAY_MAP_VERSION))
    for key in ('entries', 'undetermined'):
        value = payload.get(key)
        if not isinstance(value, list):
            raise BindingError('%s: %s 必须是数组' % (label, key))
        for item in value:
            if not isinstance(item, dict):
                raise BindingError('%s: %s 条目必须是对象' % (label, key))
            if not isinstance(item.get('occurrence'), int) \
                    or isinstance(item.get('occurrence'), bool):
                raise BindingError('%s: %s 条目缺少合法 occurrence' % (label, key))
            if not isinstance(item.get('image'), str):
                raise BindingError('%s: %s 条目缺少 image 引用' % (label, key))
    return payload


def load_parse_map(path):
    with open(path, encoding='utf-8') as handle:
        return validate_parse_map(json.load(handle), path)


def validate_delivery_map(payload, label='交付级映射'):
    """校验交付级映射：确定项与未确定项不得重叠且各自合法。"""
    validate_parse_map(payload, label)
    seen = {}
    for key in ('entries', 'undetermined'):
        for item in payload.get(key, []):
            occurrence = item['occurrence']
            markdown = item.get('markdown')
            token = (markdown, occurrence)
            if token in seen:
                raise BindingError(
                    '%s: 出现 %s#%d 被重复归类（%s 与 %s）'
                    % (label, markdown or '?', occurrence, seen[token], key))
            seen[token] = key
            if key == 'entries' and not isinstance(item.get('width'), dict):
                raise BindingError('%s: 确定项缺少 width（出现 #%d）'
                                   % (label, occurrence))
    return payload


def reason_code_of(undetermined_item):
    """未确定原因编码；旧映射无 reason_code 时按既有原因文本归类。"""
    code = undetermined_item.get('reason_code')
    if code in ('no-source-constraint', 'unresolved-size'):
        return code
    if undetermined_item.get('reason') == '源节点无宽度约束':
        return 'no-source-constraint'
    return 'unresolved-size'


def bind_page(markdown_label, page_map, occurrences, occurrence_offset=0):
    """把一页/一片解析期映射绑定为交付级条目，返回 (entries, undetermined)。

    occurrences 为按出现顺序的
    ``(交付引用, 交付文件绝对路径, 独立源文件绝对路径)`` 三元组。
    解析期记录 resource_sha256 时执行字节级身份核对，源图换字节、错引用
    与错序均在对应出现上失败。page_map 为 None 时返回空（该页无映射，
    不伪造条目）。
    """
    if page_map is None:
        return [], []
    validate_parse_map(page_map, markdown_label)
    known = {}
    for item in page_map.get('entries', []):
        previous = known.get(item['occurrence'])
        if previous is not None and previous[1] != item:
            # 同一出现号两条内容冲突的确定项：身份核验必须顺序无关，
            # 不能后写覆盖由输入顺序决定取舍（03-S2）；相同内容重复
            # 维持既有合同（幂等，视为同一记录）
            raise BindingError('%s: 出现 #%d 的确定项记录冲突'
                               % (markdown_label, item['occurrence']))
        known[item['occurrence']] = ('entries', item)
    for item in page_map.get('undetermined', []):
        if item['occurrence'] in known:
            raise BindingError('%s: 出现 #%d 同时属于确定与未确定项'
                               % (markdown_label, item['occurrence']))
        known[item['occurrence']] = ('undetermined', item)
    expected = max(known) if known else 0
    if len(occurrences) != expected:
        raise BindingError(
            '%s: 显示尺寸映射出现数 %d 与实际图片出现 %d 次不符'
            % (markdown_label, expected, len(occurrences)))

    entries = []
    undetermined = []
    for position, (ref, delivered_file, source_file) in enumerate(
            occurrences, start=1):
        kind, item = known[position]
        source_digest = None
        if source_file is not None:
            source_digest = resource_identity_digest(source_file)
            if source_digest is None:
                raise BindingError(
                    '%s: 第 %d 次出现源资源身份无法核验（依赖缺失或不可读）'
                    % (markdown_label, position))
        recorded = item.get('resource_sha256')
        if recorded is not None and recorded != source_digest:
            raise BindingError(
                '%s: 第 %d 次出现源资源身份不符: 解析期 %s vs 快照当前 %s'
                % (markdown_label, position, recorded[:12],
                   (source_digest or '')[:12]))
        delivered_identity = None
        if delivered_file is not None:
            delivered_identity = resource_identity_digest(delivered_file)
            if delivered_identity is None:
                raise BindingError(
                    '%s: 第 %d 次出现交付资源身份无法核验（依赖缺失或不可读）'
                    % (markdown_label, position))
            if source_digest is not None \
                    and delivered_identity != source_digest:
                raise BindingError(
                    '%s: 第 %d 次出现交付资源与源快照身份不符（错引用或换图）: '
                    '交付 %s vs 快照 %s'
                    % (markdown_label, position, delivered_identity[:12],
                       source_digest[:12]))
        source = {
            'snapshot': page_map.get('snapshot'),
            'snapshot_sha256': page_map.get('snapshot_sha256'),
            'node': item.get('source_node'),
            'resource_sha256': source_digest,
        }
        if page_map.get('resource_base'):
            # 资源解析上下文随记录透传：来源身份四元组的一部分（F3）
            source['resource_base'] = page_map['resource_base']
        entry = {
            'markdown': markdown_label,
            'occurrence': position + occurrence_offset,
            'image': ref,
            'sha256': file_sha256(delivered_file) if delivered_file else None,
            'source': source,
        }
        if kind == 'entries':
            entry['width'] = item['width']
            if 'derived' in item:
                entry['derived'] = item['derived']
            entries.append(entry)
        else:
            entry['reason_code'] = reason_code_of(item)
            entry['reason'] = item.get('reason')
            if 'height' in item:
                entry['height'] = item['height']
            undetermined.append(entry)
    return entries, undetermined


def check_full_coverage(markdown_label, items, total_occurrences):
    """按目标文档核对覆盖：每次真实出现恰归一类且序号连续无缺口。"""
    tokens = sorted((item['occurrence'], kind)
                    for kind, group in items.items() for item in group)
    occurrences = [t[0] for t in tokens]
    if occurrences != list(range(1, total_occurrences + 1)):
        raise BindingError(
            '%s: 交付出现覆盖不完整或有序号缺口: 覆盖 %s vs 实际 %d 次'
            % (markdown_label,
               occurrences[:8] or '无', total_occurrences))


def atomic_write_json(payload, output_path, work_dir):
    """候选写入 work_dir，重读校验后原子替换目标；失败不触碰旧文件。"""
    validate_delivery_map(payload, output_path)
    os.makedirs(work_dir, exist_ok=True)
    candidate = os.path.join(work_dir, 'candidate.images_display.json')
    with open(candidate, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    validate_delivery_map(load_parse_map(candidate), output_path)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    os.replace(candidate, output_path)
    return output_path
