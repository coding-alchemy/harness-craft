"""Report serialization and explicit export; loading never reads telemetry."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
from .core import METRICS, aggregate, markdown, timestamp


def load_report(path):
    try:
        obj = json.loads(Path(path).read_text())
        if not isinstance(obj,dict) or type(obj.get('format_version')) is not int or obj['format_version'] != 1:
            raise ValueError('不支持的报告格式版本')
        scope = obj['scope']
        if obj['harness'] not in ('codex','zcode') or not isinstance(scope['session'],str):
            raise ValueError('无效的 Harness 或会话')
        timestamp(scope['to'])
        if scope['from']:
            timestamp(scope['from'])
        if scope['turns'] is not None and (not isinstance(scope['turns'],list) or not all(isinstance(t,str) for t in scope['turns'])):
            raise ValueError('无效的轮次集合')
        if type(scope['main_only']) is not bool or type(scope['include_children']) is not bool or scope['main_only'] == scope['include_children']:
            raise ValueError('不一致的子代理策略')
        for row in obj['rows'] + [obj['summary']] + obj.get('details', []):
            for name in METRICS:
                metric = row['metrics'][name]
                if metric['value'] is not None and (type(metric['value']) is not int or metric['value'] < 0):
                    raise ValueError('报告中的 token 必须为非负整数或 null')
                if metric['state'] not in ('known','partial','unknown'):
                    raise ValueError('未知的指标状态')
                if not isinstance(metric['reasons'],list) or not all(isinstance(r, str) for r in metric['reasons']):
                    raise ValueError('缺失指标原因')
            rate = row['cache_hit_rate']
            if not isinstance(rate, dict):
                raise ValueError('缺失缓存覆盖状态')
            if rate['value'] is not None and (type(rate['value']) not in (int, float) or not 0 <= rate['value'] <= 1):
                raise ValueError('缓存命中率必须为 0 到 1 的数值或 null')
            if rate['state'] not in ('known', 'partial', 'unknown', 'not_applicable'):
                raise ValueError('未知的缓存覆盖状态')
            if any(type(rate[k]) is not int or rate[k] < 0 for k in ('paired_records', 'input', 'cache_read')):
                raise ValueError('无效的缓存覆盖量')
            if row['call_count'] is not None and (type(row['call_count']) is not int or row['call_count'] < 0):
                raise ValueError('无效的调用数')
        for key in ('records','source_files','issues','tool_reports'):
            if not isinstance(obj[key],list):
                raise ValueError('缺失报告结构：' + key)
        for key in ('read_at','status','coverage'):
            if not isinstance(obj[key],str):
                raise ValueError('缺失报告元数据：' + key)
        descriptor = obj['input']
        if descriptor['kind'] not in ('jsonl','zcode_database') or not isinstance(descriptor['paths'],list) or not descriptor['paths'] or not all(isinstance(p,str) for p in descriptor['paths']):
            raise ValueError('无效的来源描述')
        if not isinstance(scope.get('cutoff_source'),str):
            raise ValueError('缺少截止点来源')
        def check_private_keys(value):
            if isinstance(value,dict):
                if any(k.lower() in ('request','response','headers','authorization','cookie','prompt','text','content','api_key','password') for k in value):
                    raise ValueError('报告包含合同以外的正文或认证字段')
                for child in value.values():
                    check_private_keys(child)
            elif isinstance(value,list):
                for child in value:
                    check_private_keys(child)
        check_private_keys(obj)
        # Ignore unrelated top-level additions: only the report contract is exported.
        allowed = {'format_version','harness','scope','input','read_at','status','scope_note','rows','summary','records',
                   'unassigned_records','inherited_records','issues','source_files','coverage','coverage_state','tool_reports','activity','details'}
        return {k:v for k,v in obj.items() if k in allowed}
    except (KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('报告缺少必需结构或 JSON 无效') from exc


def csv_text(result):
    rows = [dict(category='group',label=r['group'],**r) for r in result['rows']]
    rows.append(dict(category='summary',label='已记录小计',**result['summary']))
    rows += [dict(category='detail',label=r['name'],**r) for r in result.get('details',[])]
    if result.get('unassigned_records'):
        rows.append(dict(category='unassigned',label='会话辅助/未归属',**aggregate(result['unassigned_records'])))
    columns = ['category','label','scope','status','read_at','sources','issues','call_count',
               'cache_hit_rate','cache_rate_state','paired_records','paired_input','paired_cache_read','tool_report_total']
    for m in METRICS:
        columns += [m,m+'_state',m+'_known_records',m+'_records',m+'_reasons']
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    common = {'scope': json.dumps(result['scope'],ensure_ascii=False), 'status': result['status'], 'read_at':result['read_at'],
              'sources':json.dumps([s for r in result['records'] for s in r['sources']],ensure_ascii=False),
              'issues':json.dumps(result['issues'],ensure_ascii=False)}
    for row in rows:
        rate = row['cache_hit_rate']
        flat = dict(common,category=row['category'],label=row['label'],call_count=row['call_count'],
                    cache_hit_rate=rate['value'],cache_rate_state=rate['state'],paired_records=rate['paired_records'],
                    paired_input=rate['input'],paired_cache_read=rate['cache_read'])
        for name,metric in row['metrics'].items():
            flat[name]=metric['value']
            for suffix in ('state','known_records','records'):
                flat[name+'_'+suffix]=metric[suffix]
            flat[name+'_reasons']=json.dumps(metric['reasons'],ensure_ascii=False)
        writer.writerow(flat)
    for row in result['tool_reports']:
        writer.writerow(dict(common,category='tool_report',label=row['agent'],tool_report_total=row['total'],sources=json.dumps(row['source'],ensure_ascii=False)))
    return output.getvalue()


def render(result, format_name):
    if format_name == 'json':
        return json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if format_name == 'csv':
        return csv_text(result)
    return markdown(result)


def export(result, format_name, destination, extra_sources=()):
    target=Path(destination).expanduser().resolve()
    sources=set(result['source_files']) | set(extra_sources) | set(result.get('input',{}).get('paths',[]))
    for name in sources:
        source=Path(name).expanduser().resolve()
        if target == source or target.exists() and source.exists() and os.path.samefile(target,source):
            raise ValueError('导出目标与输入来源冲突；源文件保持不变')
    content=render(result,format_name)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.token-audit-',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:
            stream.write(content)
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
