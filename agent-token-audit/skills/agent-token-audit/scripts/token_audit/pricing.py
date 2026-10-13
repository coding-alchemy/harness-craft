"""Bundled official price snapshots: pointer resolution, snapshot reads and updates.

The analysis module stays I/O-free; this module owns the pricing resource
directory shipped with the skill (pricing/default.json pointing at
pricing/snapshots/<id>.json). The default snapshot is read and validated at
operation entry, before any telemetry source read, so an update landing
mid-request can never leak into a query that already started. A missing or
damaged resource is an explicit configuration error that names the escape
hatch (token-only mode), never a silent fallback to unpriced results.

`pricing-update` finishes the loop the Skill workflow drives: the caller reads
the fixed official sources with its own web capability, forms a schema-v2
candidate with real fetch times, and this module deterministically validates it
(whitelisted sources, fixed catalog coverage), preserves it as a snapshot and —
only for a complete catalog — atomically switches the default reference. The
tool never fetches URLs itself, so a missing read stays missing instead of
becoming a guessed price.
"""
import json
import os
import re
import tempfile
from pathlib import Path
from . import analysis

RESOURCE_ROOT = Path(__file__).resolve().parents[2] / 'pricing'
SNAPSHOT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z')
# The design pins these official documents. The OpenAI pages are read through their
# `.md` renditions because direct HTTP on the HTML pages returns 403 for tooling.
SOURCE_WHITELIST = frozenset((
    'https://developers.openai.com/api/docs/pricing',
    'https://developers.openai.com/api/docs/pricing.md',
    'https://developers.openai.com/api/docs/models/gpt-6.1-sol',
    'https://developers.openai.com/api/docs/models/gpt-6.1-sol.md',
    'https://developers.openai.com/api/docs/guides/prompt-caching',
    'https://developers.openai.com/api/docs/guides/prompt-caching.md',
    'https://docs.bigmodel.cn/cn/guide/start/pricing',
    'https://docs.bigmodel.cn/cn/guide/start/pricing.md',
))
# The fixed first-batch catalog: every target needs a rule or a checked no-price
# reason in a complete candidate; extending it is a deliberate catalog decision.
TARGET_CATALOG = (
    ('openai', 'gpt-6.1-sol'), ('openai', 'gpt-5.6-terra'), ('openai', 'gpt-5.6-sol'),
    ('openai', 'gpt-6-astra'), ('openai', 'gpt-6-sol'),
    ('bigmodel', 'GLM-5.3'), ('bigmodel', 'GLM-5.3-Flash'), ('bigmodel', 'GLM-5.2'),
)


def _inside_resource_root(path):
    """Real-path containment shared by every pricing read and write target.

    Resolution follows directory and file symlinks, so a `snapshots` directory or
    `default.json` linked outside the shipped resource root is rejected outright:
    the actual landing point of a read or write must sit inside this copy's
    pricing directory. Nothing is rewritten or removed by the check itself.
    """
    root = RESOURCE_ROOT.resolve()
    real = Path(os.path.realpath(Path(path)))
    if real != root and root not in real.parents:
        raise ValueError('价格资源路径越界，已拒绝：' + str(path)
                         + '；请检查随包 pricing 目录及其符号链接后修复或更新资源')


def snapshot_path(snapshot_id):
    """Resolve one snapshot id to its real file inside the resource directory."""
    if not isinstance(snapshot_id, str) or not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError('默认价格快照标识无效：' + repr(snapshot_id))
    path = RESOURCE_ROOT / 'snapshots' / (snapshot_id + '.json')
    _inside_resource_root(path)
    return Path(os.path.realpath(path))


def _default_pointer_path():
    path = RESOURCE_ROOT / 'default.json'
    _inside_resource_root(path)
    return Path(os.path.realpath(path))


def read_snapshot(snapshot_id):
    """Read and validate one bundled snapshot file by id."""
    path = snapshot_path(snapshot_id)
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise ValueError('默认价格快照读取失败（' + str(path) + '）：' + str(exc)
                         + '；可显式选择仅 token 性能继续，或修复/更新随包价格资源') from None
    try:
        return analysis.validate_pricing_config(raw)
    except ValueError as exc:
        raise ValueError('默认价格快照损坏（' + snapshot_id + '）：' + str(exc)
                         + '；可显式选择仅 token 性能继续，或修复/更新随包价格资源') from None


def load_default():
    """The bundled default snapshot named by pricing/default.json, validated."""
    try:
        pointer = json.loads(_default_pointer_path().read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('随包默认价格缺失或损坏（pricing/default.json）：' + str(exc)
                         + '；可显式选择仅 token 性能继续，或修复/更新随包价格资源') from None
    if not isinstance(pointer, dict) or set(pointer) != {'snapshot'} or not isinstance(pointer['snapshot'], str) \
            or not pointer['snapshot'].strip():
        raise ValueError('随包默认价格指针无效（pricing/default.json 须为 {"snapshot": "<快照id>"}）；'
                         '可显式选择仅 token 性能继续，或修复/更新随包价格资源')
    return read_snapshot(pointer['snapshot'])


def _current_default_id():
    try:
        pointer = json.loads(_default_pointer_path().read_text(encoding='utf-8'))
        return pointer.get('snapshot') if isinstance(pointer, dict) else None
    except (OSError, ValueError):
        return None


def _write_atomic(path, text):
    """Write via a same-directory temp file and atomic replace; clean up on failure."""
    _inside_resource_root(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix='.pricing-', dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def update_from_candidate(value):
    """Validate one read-formed schema-v2 candidate and preserve/enable it.

    Returns a report dict; 'enabled' is true only when every catalog target has a
    rule or a checked no-price reason AND the default reference switched. Writes
    stay inside the pricing resource root of the loaded skill copy; the snapshot
    is persisted before the pointer moves, and any failure keeps the old default
    and its time, removing temporary writes.
    """
    candidate = analysis.validate_pricing_config(value)
    if candidate['schema_version'] != 2:
        raise ValueError('pricing-update 只接受 schema v2 官网估值候选（当前 schema '
                         + str(candidate['schema_version']) + '）；v1 历史规则请继续经 --pricing 使用')
    bad_sources = sorted({source['url'] for source in candidate['sources']} - SOURCE_WHITELIST)
    bad_refs = sorted({item['source']['reference'] for item in candidate['rules'] + candidate['mappings']}
                      - SOURCE_WHITELIST)
    if bad_sources or bad_refs:
        raise ValueError('候选含固定白名单以外的来源：' + '、'.join(sorted(set(bad_sources + bad_refs)))
                         + '；pricing-update 不接受任意 URL，来源以设计固定清单为准')
    rules_by_identity = {(rule['provider'], rule['model']) for rule in candidate['rules']}
    uncovered_by_identity = {(item['provider'], item['model']) for item in candidate['uncovered']}
    missing = [f'{provider}/{model}' for provider, model in TARGET_CATALOG
               if (provider, model) not in rules_by_identity
               and (provider, model) not in uncovered_by_identity]
    old_id = _current_default_id()
    old = read_snapshot(old_id) if old_id is not None else None
    revision = candidate['revision']
    snapshot_file = snapshot_path(revision)
    body = json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if snapshot_file.exists():
        if analysis.validate_pricing_config(snapshot_file.read_text(encoding='utf-8')) != candidate:
            raise ValueError('快照身份 ' + revision + ' 已存在且内容不同；一次读取必须生成新身份（同价重读也是新快照）')
    else:
        _write_atomic(snapshot_file, body)
    enabled = not missing
    if enabled:
        _write_atomic(_default_pointer_path(), json.dumps({'snapshot': revision}) + '\n')
    changes = None
    if old is not None and old['revision'] != revision:
        new_rules = {rule['id']: rule for rule in candidate['rules']}
        old_rules = {rule['id']: rule for rule in old['rules']}
        changes = {'added': sorted(set(new_rules) - set(old_rules)),
                   'removed': sorted(set(old_rules) - set(new_rules)),
                   'changed': sorted(rule_id for rule_id in set(new_rules) & set(old_rules)
                                     if new_rules[rule_id] != old_rules[rule_id])}
    return {'enabled': enabled, 'revision': revision, 'previous': old_id,
            'target_root': str(RESOURCE_ROOT),
            'sources': [{'url': source['url'], 'fetched_at': source['fetched_at']} for source in candidate['sources']],
            'rule_changes': changes, 'missing_targets': missing,
            'uncovered': [f"{item['provider'] or '（无供应商）'}/{item['model']}" for item in candidate['uncovered']]}
