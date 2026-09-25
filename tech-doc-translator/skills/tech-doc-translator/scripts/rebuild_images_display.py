#!/usr/bin/env python3
"""四类源家族共用的图片显示尺寸映射回补入口。

用法：
    python3 rebuild_images_display.py --manifest <manifest.json> \
        --output <images_display.json> [--work-dir <dir>] [--fetch-missing]

回补清单（manifest）声明本次明确范围，不是项目状态库：

    {
      "version": 1,
      "source_version": "13.4",
      "family": "single" | "paginated" | "reference" | "api",
      "pages": [
        {"snapshot": "source/page.html",        // 快照位置（相对清单目录）
         "section_id": null,                    // 可选选区（单页/参考手册）
         "markdown": "01_intro.md",             // 最终 Markdown 归属
         "image_range": [1, 4],                 // 可选出现区间（1 起闭区间）
         "parse_map": "display/page.images_display.json"}
                                              // 可选：该页既有解析期映射，
                                              // 声明后作为独立来源身份证明
      ],
      "missing": [                              // 可选：缺失快照的已确认同版本来源
        {"url": "https://...", "save": "source/page.html",
         "sha256": "…预期摘要…"}
      ]
    }

流程：验证清单 → 复用或补齐快照 → 按家族规则提取图片与尺寸（不做正文
渲染）→ 独立核对图片出现 → 绑定最终引用及独立身份 → 写候选映射 →
重读候选并原子替换目标。无关正文中的复杂表格等结构不阻断回补；全文
对账留在新翻译的解析入口。默认只读本地输入；完整快照不发网络请求。
`--fetch-missing` 只补清单声明的缺失项，重定向导致版本/来源不可确认即
停止，失败下载不覆盖旧文件。任何失败都不触碰 `--output` 旧映射，诊断
写入 --work-dir（默认系统临时目录，属工作区外）。
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile

from _html_fidelity import (
    DISPLAY_MAP_VERSION,
    HtmlFidelity,
    resolve_snapshot_resource,
    shaped_display_entries,
    warn_if_temp_output,
)
from _image_binding import (
    BindingError,
    atomic_write_json,
    bind_page,
    check_full_coverage,
    load_parse_map,
    validate_delivery_map,
)
from _verification import (
    file_sha256,
    image_marker_refs,
    image_references,
    resolve_delivery_image,
    resource_identity_digest,
)
from _source_reconcile import snapshot_image_stream

_FAMILIES = ('single', 'paginated', 'reference', 'api')


class RebuildError(ValueError):
    """回补失败：清单、快照、对账或绑定任一环节不通过。"""


def _load_manifest(path):
    try:
        with open(path, encoding='utf-8') as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RebuildError('回补清单不可读: %s（%s）' % (path, exc))
    if not isinstance(manifest, dict) or manifest.get('version') != 1:
        raise RebuildError('回补清单版本无效: %s（需 version=1）' % path)
    if manifest.get('family') not in _FAMILIES:
        raise RebuildError('回补清单 family 无效: %r（需 %s）'
                           % (manifest.get('family'), '/'.join(_FAMILIES)))
    if not isinstance(manifest.get('source_version'), str) \
            or not manifest['source_version'].strip():
        raise RebuildError('回补清单缺少 source_version，不能宣称同版本回补')
    pages = manifest.get('pages')
    if not isinstance(pages, list) or not pages:
        raise RebuildError('回补清单 pages 必须是非空数组')
    for page in pages:
        if not isinstance(page, dict) or not isinstance(
                page.get('snapshot'), str) \
                or not isinstance(page.get('markdown'), str):
            raise RebuildError('回补清单每页需要 snapshot 与 markdown 路径')
        if page.get('parse_map') is not None \
                and not isinstance(page.get('parse_map'), str):
            raise RebuildError('回补清单 parse_map 必须是字符串路径')
    missing = manifest.get('missing', [])
    if not isinstance(missing, list):
        raise RebuildError('回补清单 missing 必须是数组')
    for item in missing:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str) \
                or not isinstance(item.get('save'), str):
            raise RebuildError('missing 项需要 url 与 save 路径')
    return manifest


def _contained(base, relative):
    """解析清单内路径：相对路径以清单目录为基点且不得越界；
    绝对路径原样接受（清单是本次范围的显式声明）。"""
    if os.path.isabs(relative):
        return os.path.normpath(relative)
    target = os.path.normpath(os.path.join(base, relative))
    if target.startswith('..'):
        raise RebuildError('清单路径越出基点目录: %s' % relative)
    return target


def _fetch_missing(manifest, base_dir):
    """补齐清单声明的缺失快照；已保存项复用，不爬新范围。"""
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # 重定向导致版本/来源不可确认，直接拒绝

    # 直连目标主机（不走环境代理）：同版本来源确认必须对准清单声明的 URL 本身
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect)
    for item in manifest.get('missing', []):
        dest = _contained(base_dir, item['save'])
        if os.path.isfile(dest):
            continue  # 完整快照复用，不重复下载
        url = item['url']
        if not url.lower().startswith(('http://', 'https://')):
            raise RebuildError('missing 项 URL 只允许 http(s): %s' % url)
        try:
            response = opener.open(url, timeout=30)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RebuildError(
                    '补抓被拒绝（重定向导致版本/来源不可确认）: %s -> HTTP %s'
                    % (url, exc.code))
            raise RebuildError('补抓失败: %s -> HTTP %s' % (url, exc.code))
        except urllib.error.URLError as exc:
            raise RebuildError('补抓失败: %s（%s）' % (url, exc.reason))
        data = response.read()
        expected = item.get('sha256')
        if expected:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise RebuildError(
                    '补抓摘要不符: %s 期望 %s 实际 %s'
                    % (url, expected, actual))
        part = dest + '.part'
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(part, 'wb') as handle:
            handle.write(data)
        os.replace(part, dest)


def _snapshot_display_entries(raw, family, section_id, snapshot_dir):
    """从快照选区按家族规则登记进入输出的图片出现及显示尺寸。

    只做源选区定位与家族图片选择（api 取亮版、reference 改写为
    images/<basename>），复用 HtmlFidelity 的尺寸提取；`<pre>` 在解析时
    被保护为占位，代码示例中的图片语法不参与。不运行正文渲染，也不做
    全文对账——无关正文中的复杂表格等结构不决定回补成败；全文对账留在
    新翻译的解析入口。每次出现同时保留交付写法（image）与原始源引用
    （source_ref，相对快照目录解析）；reference 的改写只用于交付匹配，
    不覆盖源路径。
    """
    fidelity = HtmlFidelity(snapshot_dir=snapshot_dir)
    soup = fidelity.parse(raw)
    if section_id:
        root = soup.find(id=section_id)
        if root is None:
            raise RebuildError('快照选区不存在: %s' % section_id)
    else:
        root = (soup.find('article') or soup.find('main')
                or soup.find('body'))
    if root is None:
        raise RebuildError('快照缺少 article/main/body 根元素')
    for img in root.find_all('img'):
        if family == 'api':
            cls = ' '.join(img.get('class') or [])
            if 'only-dark' in cls or (img.get('data-dark')
                                      and not img.get('data-light')):
                continue
            src = img.get('data-light') or img.get('src', '')
        else:
            src = img.get('src', '')
        if not src:
            continue
        source_ref = src
        if family == 'reference':
            src = 'images/%s' % src.rsplit('/', 1)[-1]
        fidelity.note_image(img, src)
        fidelity.image_display[-1]['source_ref'] = source_ref
    return fidelity.image_display


def _snapshot_source_path(snapshot_dir, source_ref):
    """把出现的原始源引用解析为快照内独立资源文件。

    源资源相对快照目录解析；同名异图（如 left/plot.png 与
    right/plot.png）按各自显式路径直接命中，不做 basename 全树检索。
    """
    path, reason = resolve_snapshot_resource(source_ref, snapshot_dir)
    if path is None:
        raise RebuildError('快照资源不可解析: %s（%s）' % (source_ref, reason))
    return path


def _markdown_occurrences(text):
    """最终 Markdown 的图片出现序列（内联引用与 [IMG:] 标记按行序合并）。"""
    entries = [(line_no, 0, src) for line_no, src in image_references(text)]
    entries.extend((line_no, 1, path)
                   for line_no, path in image_marker_refs(text))
    entries.sort(key=lambda item: (item[0], item[1]))
    return [src for _, _, src in entries]


def _resolve_delivered(ref, markdown_dir):
    path, reason = resolve_delivery_image(ref, markdown_dir)
    if reason:
        raise RebuildError('交付引用不可解析: %s（%s）' % (ref, reason))
    if not os.path.isfile(path):
        raise RebuildError('交付图片缺失: %s' % ref)
    return path


def _merge_proof(history, key, digest):
    """把一份独立来源证明并入统一历史；同键不同摘要即证明冲突。

    多份既有证明（旧交付映射、声明的解析期映射）指向同一来源而资源
    摘要不一致时，不能按读取顺序或入口优先级消除冲突（F3）：按既有
    身份不符门禁停止并保旧；确需更换已确认来源，须人工确认后移除
    过时记录再回补。
    """
    previous = history.get(key)
    if previous is not None and previous != digest:
        raise BindingError(
            '独立来源证明冲突（快照 %s 资源基点 %s 节点 %s）: %s 与 %s '
            '对同一来源记录了不同资源摘要；需先人工确认同版本来源'
            '（确认更换后移除过时记录），旧映射未修改'
            % (key[0], key[2], key[3], previous[:12], digest[:12]))
    history[key] = digest


def _delivery_map_history(output_path):
    """既有交付映射中带独立来源身份的记录并入统一历史。

    持久映射的来源字段统一为写入端记录的解析后绝对路径（两端同义
    比较），来源身份为（HTML 文件身份＋快照摘要＋资源解析上下文＋
    源节点）四元组。存量旧版相对来源记录的记录基点不可确定：不能
    假定它相对清单、进程 cwd 或映射目录（F3）——按歧义明确失败并
    保旧，重新解析/合并即生成绝对来源记录，不静默降为无历史。含
    完整身份但缺 resource_base 的旧记录（第六/七轮格式）资源上下文
    同样不可确定——不猜快照目录或声明目录，明确失败保旧，重新解析/
    合并即生成含上下文记录（F3 第八轮）。旧映射缺失、不可读或条目
    source 缺 snapshot/snapshot_sha256/node/resource_sha256 任一字段
    时不构成可比对的历史事实，按兼容边界重建，不以当前字节补签（S05）。
    """
    if not os.path.isfile(output_path):
        return {}
    try:
        with open(output_path, encoding='utf-8') as handle:
            existing = json.load(handle)
    except (OSError, ValueError):
        return {}
    history = {}
    if isinstance(existing, dict):
        for item in (existing.get('entries', [])
                     + existing.get('undetermined', [])):
            if not isinstance(item, dict):
                continue
            source = item.get('source')
            if not isinstance(source, dict):
                continue
            digest = source.get('resource_sha256')
            if all(isinstance(part, str) and part
                   for part in (source.get('snapshot'),
                                source.get('snapshot_sha256'),
                                source.get('node'), digest)):
                recorded = source['snapshot']
                if not os.path.isabs(recorded):
                    raise RebuildError(
                        '既有交付映射含旧版相对来源记录（snapshot: %s），'
                        '其记录基点不可确定，不能假定相对清单、进程 cwd '
                        '或映射目录；请重新解析/合并生成绝对来源记录后'
                        '重试，旧映射未修改' % recorded)
                base = source.get('resource_base')
                if not (isinstance(base, str) and os.path.isabs(base)):
                    raise RebuildError(
                        '既有交付映射含旧版来源记录（快照 %s 节点 %s，缺 '
                        'resource_base），其资源解析上下文不可确定，不能'
                        '假定快照目录或声明路径目录；请重新解析/合并生成'
                        '含资源上下文的来源记录后重试，旧映射未修改'
                        % (recorded, source['node']))
                _merge_proof(history,
                             (os.path.realpath(recorded),
                              source['snapshot_sha256'],
                              os.path.realpath(base), source['node']),
                             digest)
    return history


def _declared_parse_history(parse_map_path, page_snapshot_ref,
                            snapshot_sha256, page_resource_base):
    """声明的解析期映射 → {来源身份四元组: 资源摘要}。

    来源字段两端同义：映射自身记录的必须是绝对路径（写入端归一），
    旧版相对记录基点不可确定——明确失败并保旧，重新解析即得绝对
    来源记录（F3）。记录的来源必须与清单页快照是同一文件：字节相同
    的不同目录快照不是同一来源，误指其他目录的证明不能重标为当前页
    历史。快照摘要不符同样拒绝——声明的是该页解析期事实，版本漂移
    不能宣称同版本回补。身份记录的资源解析上下文也必须与清单页一致：
    同一 HTML 经文件级符号链接从不同目录地址时相对资源指向不同文件，
    证明只对记录时的上下文有效（F3 第八轮）；含身份但缺 resource_base
    的旧记录上下文不可确定，明确失败保旧。文件内部每条记录逐条经统一
    _merge_proof 合并，同键不同摘要即冲突，与记录顺序无关。
    """
    payload = load_parse_map(parse_map_path)
    recorded = payload.get('snapshot_sha256')
    if isinstance(recorded, str) and recorded != snapshot_sha256:
        raise RebuildError(
            '声明的解析期映射与当前快照版本不符: %s 记录 %s vs 当前 %s；'
            '需先确认同版本来源（重新解析或核对快照），旧映射未修改'
            % (parse_map_path, recorded[:12], snapshot_sha256[:12]))
    declared_ref = payload.get('snapshot')
    if not isinstance(declared_ref, str) or not declared_ref:
        raise RebuildError(
            '声明的解析期映射缺少快照来源记录，无法核对所指来源: %s；'
            '旧映射未修改' % parse_map_path)
    if not os.path.isabs(declared_ref):
        raise RebuildError(
            '声明的解析期映射为旧版相对来源记录（snapshot: %s），来源'
            '基点不可确定，不能假定相对清单、进程 cwd 或映射目录；'
            '请重新解析生成绝对来源记录，旧映射未修改' % declared_ref)
    resolved_ref = os.path.realpath(declared_ref)
    if resolved_ref != page_snapshot_ref:
        raise RebuildError(
            '声明的解析期映射记录的快照与清单页不是同一来源: %s 记录 '
            '%s vs 清单页 %s；不能把其他来源的证明挂到当前页，旧映射'
            '未修改' % (parse_map_path, declared_ref, page_snapshot_ref))
    items = [item for item in payload.get('entries', [])
             + payload.get('undetermined', [])
             if isinstance(item.get('resource_sha256'), str)
             and item.get('resource_sha256')
             and isinstance(item.get('source_node'), str)
             and item.get('source_node')]
    if items:
        declared_base = payload.get('resource_base')
        if not (isinstance(declared_base, str)
                and os.path.isabs(declared_base)):
            raise RebuildError(
                '声明的解析期映射为旧版来源记录（缺 resource_base），'
                '其资源解析上下文不可确定；请重新解析生成含资源上下文'
                '的来源记录，旧映射未修改: %s' % parse_map_path)
        if os.path.realpath(declared_base) != page_resource_base:
            raise RebuildError(
                '声明的解析期映射来自其他资源解析上下文: %s 记录 %s vs '
                '清单页 %s；不能把其他资源上下文的证明当作本页历史，'
                '旧映射未修改'
                % (parse_map_path, declared_base, page_resource_base))
    history = {}
    for item in items:
        _merge_proof(history, (page_snapshot_ref, snapshot_sha256,
                               page_resource_base, item['source_node']),
                     item['resource_sha256'])
    return history


def _verify_source_history(history, current_identities):
    """当前每次出现的来源身份与既有独立记录核对；不符即拒绝。

    current_identities 为 (markdown, 出现序号, 来源身份四元组（HTML
    文件身份、快照摘要、资源解析上下文、源节点）, 当前资源摘要)。
    同一来源位置在历史记录与本次快照之间字节不一致即同路径换图
    （S05），不能用重算摘要覆盖既有独立证明，旧映射不变。
    """
    for markdown_label, occurrence, key, digest in current_identities:
        recorded = history.get(key)
        if recorded and digest != recorded:
            raise BindingError(
                '%s#%d 源资源身份与既有独立记录不符（快照 %s 节点 %s '
                '同路径换图？）: 既有 %s vs 本次快照 %s；需先确认同版本'
                '来源，旧映射未修改'
                % (markdown_label, occurrence, key[1][:12], key[3],
                   recorded[:12], (digest or '')[:12]))


def rebuild(manifest_path, output_path, work_dir, fetch=False):
    base_dir = os.path.dirname(os.path.abspath(manifest_path))
    manifest = _load_manifest(manifest_path)
    family = manifest['family']
    if fetch:
        _fetch_missing(manifest, base_dir)

    # 条目 markdown 按相对映射目录的完整路径登记，供导出/核验无歧义归属。
    map_dir = os.path.dirname(os.path.abspath(output_path))
    # 历史身份证明统一合并：旧交付映射与声明的解析期映射逐条经
    # _merge_proof 核对同键一致性（同键不同摘要即冲突，保旧）
    history = _delivery_map_history(output_path)
    entries = []
    undetermined = []
    coverage = {}
    current_identities = []
    for page in manifest['pages']:
        snapshot = _contained(base_dir, page['snapshot'])
        if not os.path.isfile(snapshot):
            raise RebuildError(
                '快照缺失且未获准补抓（或补抓后仍缺失）: %s。'
                '缺失项须先确认同版本来源并补齐，不用最新版替代。' % snapshot)
        # 两种含义分离：来源文件身份按 realpath 归一（历史键、声明
        # 核对与持久记录，与写入端 write_display_map 一致）；相对资源
        # 基点保持清单声明路径的目录——解析按输入路径的 dirname 解析
        # 图片，回补读取同一组资源，不因规范化 HTML 路径改变图片目录
        # （文件级符号链接下 alias/ 与 real/ 资源不同，F3）。资源解析
        # 上下文 resource_base = realpath(声明路径目录)：只归一目录
        # 自身的符号链接与平台别名（目录别名即同一上下文），是来源
        # 身份四元组的一部分，与写入端记录同义（F3 第八轮）
        snapshot_ref = os.path.realpath(snapshot)
        markdown = _contained(base_dir, page['markdown'])
        if not os.path.isfile(markdown):
            raise RebuildError('最终 Markdown 缺失: %s' % markdown)
        markdown_label = os.path.relpath(markdown, map_dir)
        snapshot_dir = os.path.dirname(snapshot)
        resource_base = os.path.realpath(snapshot_dir)
        with open(snapshot, encoding='utf-8') as handle:
            raw = handle.read()
        display_entries = _snapshot_display_entries(
            raw, family, page.get('section_id'), snapshot_dir)
        # 独立源核对：出现流从原快照独立重提（不同解析路径），不能由
        # 尺寸提取的结果自证漏图检查。
        stream = snapshot_image_stream(raw, family, page.get('section_id'))
        if stream is None:
            raise RebuildError('快照未找到 article/main/body 选区: %s'
                               % snapshot)
        selected = [entry['image'] for entry in display_entries]
        if selected != stream:
            raise RebuildError(
                '%s: 家族图片选择与独立源出现流不一致（选择 %r vs 独立 %r）'
                % (markdown, selected, stream))

        with open(markdown, encoding='utf-8') as handle:
            md_text = handle.read()
        refs = _markdown_occurrences(md_text)
        image_range = page.get('image_range')
        if image_range is None:
            start, end = 1, len(refs)
        else:
            start, end = int(image_range[0]), int(image_range[1])
            if start < 1 or end > len(refs) or start > end:
                raise RebuildError(
                    'image_range %r 越出 %s 实际出现 %d 次'
                    % (image_range, markdown, len(refs)))
        page_refs = refs[start - 1:end]
        expected_count = len(display_entries)
        if len(page_refs) != expected_count:
            raise RebuildError(
                '%s: 快照图片出现 %d 次与交付出现区间 %d 次不符'
                % (markdown, expected_count, len(page_refs)))
        occurrences = []
        for position, ref in enumerate(page_refs, start=1):
            entry = display_entries[position - 1]
            source_path = _snapshot_source_path(
                snapshot_dir, entry.get('source_ref') or entry['image'])
            delivered = _resolve_delivered(ref, os.path.dirname(markdown))
            # 交付级 image 以映射目录为基准的完整相对路径登记
            map_relative = os.path.relpath(delivered, map_dir)
            occurrences.append((map_relative, delivered, source_path))
        shaped_entries, shaped_undetermined = shaped_display_entries(
            display_entries)
        page_map = {
            'version': DISPLAY_MAP_VERSION,
            'snapshot': snapshot_ref,
            'snapshot_sha256': file_sha256(snapshot),
            'resource_base': resource_base,
            'entries': shaped_entries,
            'undetermined': shaped_undetermined,
        }
        page_entries, page_undetermined = bind_page(
            markdown_label, page_map, occurrences,
            occurrence_offset=start - 1)
        entries.extend(page_entries)
        undetermined.extend(page_undetermined)
        if page.get('parse_map') is not None:
            parse_map_path = _contained(base_dir, page['parse_map'])
            if not os.path.isfile(parse_map_path):
                raise RebuildError('声明的解析期映射缺失: %s' % parse_map_path)
            for key, digest in _declared_parse_history(
                    parse_map_path, snapshot_ref,
                    page_map['snapshot_sha256'], resource_base).items():
                _merge_proof(history, key, digest)
        for position, (ref, delivered, source_path) in enumerate(
                occurrences, start=1):
            current_identities.append((
                markdown_label, position + start - 1,
                (snapshot_ref, page_map['snapshot_sha256'], resource_base,
                 display_entries[position - 1].get('source_node')),
                resource_identity_digest(source_path)))
        group = coverage.setdefault(
            markdown_label, {'total': len(refs), 'items': []})
        group['items'].extend(
            [( 'entries', e) for e in page_entries]
            + [('undetermined', e) for e in page_undetermined])

    for markdown_label, group in coverage.items():
        check_full_coverage(markdown_label, {
            'entries': [i[1] for i in group['items'] if i[0] == 'entries'],
            'undetermined': [i[1] for i in group['items']
                             if i[0] == 'undetermined'],
        }, group['total'])

    entries.sort(key=lambda e: (e['markdown'], e['occurrence']))
    undetermined.sort(key=lambda e: (e['markdown'], e['occurrence']))
    # 历史身份核对在候选写盘前：证明来自既有独立来源事实（旧交付映射
    # 与声明的解析期映射），按来源身份关联，不由输出路径决定强度
    _verify_source_history(history, current_identities)
    payload = {
        'version': DISPLAY_MAP_VERSION,
        'source_version': manifest['source_version'],
        'family': family,
        'rebuild': {
            'manifest': os.path.basename(manifest_path),
            'manifest_sha256': file_sha256(manifest_path),
        },
        'entries': entries,
        'undetermined': undetermined,
    }
    if len(coverage) == 1:
        payload['markdown'] = next(iter(coverage))
    validate_delivery_map(payload, output_path)
    atomic_write_json(payload, output_path, work_dir)
    return payload


def main():
    parser = argparse.ArgumentParser(
        description='四类源家族共用的图片显示尺寸映射回补入口')
    parser.add_argument('--manifest', required=True,
                        help='回补清单（声明本次范围与同版本来源）')
    parser.add_argument('--output', required=True,
                        help='交付级 images_display.json 目标路径')
    parser.add_argument('--work-dir', default=None,
                        help='候选与诊断目录（默认系统临时目录，工作区外）')
    parser.add_argument('--fetch-missing', action='store_true',
                        help='显式获准补抓清单声明的缺失快照（默认只读本地）')
    args = parser.parse_args()

    work_dir = args.work_dir or tempfile.mkdtemp(prefix='rebuild-images-')
    try:
        payload = rebuild(args.manifest, args.output, work_dir,
                          fetch=args.fetch_missing)
    except (RebuildError, BindingError) as exc:
        diagnostics = os.path.join(work_dir, 'rebuild_error.txt')
        try:
            with open(diagnostics, 'w', encoding='utf-8') as handle:
                handle.write(str(exc) + '\n')
        except OSError:
            diagnostics = '（诊断不可写）'
        sys.exit('回补失败（旧映射未被修改；诊断: %s）:\n%s'
                 % (diagnostics, exc))
    warn_if_temp_output([args.output])
    print('回补完成: %d 确定项, %d 未确定项 -> %s' % (
        len(payload['entries']), len(payload['undetermined']), args.output))


if __name__ == '__main__':
    main()
