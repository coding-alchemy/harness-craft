#!/usr/bin/env python3
"""从当前独立准入与机械包映射生成四要素自足任务，不分派或授予资格。"""
import argparse
import difflib
import json
import shlex
import sys
from pathlib import Path
import recover_work_packages as rwp
from build_review_evidence import atomic_write


def task(context, exp, source_path, output_path):
    name=exp['name'];refs={field:rwp.context_refs(context,field,name)
        for field in ('instructions','rules','glossary','output_contract','examples')}
    for field in ('instructions','rules','output_contract','examples'):
        if not refs[field]:raise ValueError('四要素缺少可读 '+field)
    if not context.get('return_contract'):
        raise ValueError('缺少返回合同')
    if context.get('rule_conflicts'):
        raise ValueError('已确认规则冲突未解决: '+str(context['rule_conflicts']))
    # 保留 venv 入口；realpath 会落到基础解释器并丢失已安装依赖。
    python=Path(context.get('python',sys.executable)).absolute()
    skill=Path(context['skill_dir']).resolve()
    script=skill/'scripts/verify_translation.py'
    if not python.is_file() or not script.is_file():
        raise ValueError('解释器/实际 Skill 检查入口不可访问')
    options=list(context.get('check_args',[]))
    for i,value in enumerate(options[:-1]):
        if value in ('--strong-token-file','--numeric-policy','--source-adaptation'):
            options[i+1]=str((Path(context['_root'])/options[i+1]).resolve())
    # 包源而不是全篇源；fragment 只免 H1，仍核对每个源实例及资源基点。
    from _verification import source_occurrence_digests
    digests=source_occurrence_digests(exp['body'], str(Path(source_path).resolve().parent))
    if digests is None:raise ValueError('当前源资源身份不可核验')
    command=[str(python),str(script),exp['target'],exp['path'],'--fragment',
             '--image-map',str(Path(output_path).resolve()),*options]
    if context.get('_pdf_view') or context.get('_table_view'):
        command+=['--project-context',context['_path']]
    meta=exp['meta']
    count_fields=('headings','paragraphs','list_items','tables','code_fences','inline_math','block_math','images','footnotes')
    counts={key:meta[key] for key in count_fields if key in meta}
    if not counts:raise ValueError('当前拆包脚本未提供可靠计数')
    conversions=[]
    table_policy = rwp.table_policy(context, exp)
    table_paths = context.get('_table_view',{}).get('paths', [])
    table_map = (table_paths[0] if len(table_paths)==1 else table_paths) or None
    for item in context.get('structural_conversions',[]):
        if item.get('package')!=name:continue
        if not item.get('basis') or not item.get('source') or not item.get('target') or item['source'] not in exp['body']:
            raise ValueError('当前包转换缺少可定位原文/目标合同/批准依据')
        conversions.append(item)
    # 指令文本引用当前内容，不重写全套规则。范围和计数保持机械元数据。
    lines=['# 工作包翻译任务：'+name,'','## 必读上下文','']
    for field,values in refs.items():
        if not values:
            lines.append('- glossary：本项目明确未配置术语；不得自行启用共享库。')
        for ref in values:
            lines.append('- %s：%s，第 %d–%d 行，sha256=%s' %
                (field,ref['path'],ref['start_line'],ref['end_line'],ref['sha256']))
    for example in context['examples']:
        if isinstance(example,dict):
            if not example.get('differences'):raise ValueError('样例须明确同构或不可仿照差异')
            lines.append('样例适用说明：'+example['differences'])
    lines+=['','## 唯一输入输出','',
        '唯一只读机械源包：'+exp['path'], '唯一可写目标：'+exp['target'],
        '当前全篇源（只读，资源基点）：'+str(Path(source_path).resolve()),
        '元数据：'+json.dumps(meta,ensure_ascii=False,sort_keys=True),
        '保留 frontmatter 映射；不得写源、其他包、术语表、目录、全局映射或交付说明。',
        '','## 输出合同','',
        '按上述模板翻译全部正文并保持官方原题。代码逐字保真；公式按原类型和表达式；图片按源身份落到目标目录内，资源由主 Agent 预先准备；保留脚注引用/定义关系。',
        '源中的 [TABLE] 等解析结构须重建为真实 Markdown 表格，保持各格内容、公式及关联。',
        ('当前为中间工作包：保留并核对 [TABLE-CODE r=R c=C#N] 与紧随围栏，不能删除归属；主 Agent 最终合并时转换为可读格位说明。'
         if rwp.table_code_stage(context) == 'intermediate' else
         '当前为最终阶段：实际 TABLE-CODE 标记须已转为可读格位说明，不能裸删标记或保留解析残留。'),
        '已获准额外公式、具体转换和所选术语只采用当前引用依据；遇不能适配的结构先报告，不自行豁免。',
        '保留来源对象的独立 <a id="…"></a> 锚点及其块边界，不能移入表格数据区。翻译页保留原链接目标（含题注 [#](#id)）；仅交付合章按明确 navigation-record 转换命名空间及跨章路径。PDF 裸 #id 只查当前章，缺失时回源处理，不能借外章同名对象通过。',
        '本包已批准的具体转换（空表示没有）：'+json.dumps(conversions,ensure_ascii=False,sort_keys=True),
        '本包原 DOM 表格及转换映射（只读，空表示不涉及）：'+json.dumps(table_policy,ensure_ascii=False,sort_keys=True),
        '完整表映射只读位置：'+str(table_map or '无'),
        '','## 完成合同','',
        '当前脚本计数：'+json.dumps(counts,ensure_ascii=False,sort_keys=True),
        '未列出的结构未由当前拆包脚本计数；不得当作零。实际公式、图片、脚注按源及当前检查核对，不能可靠识别则报告。',
        '计数不能覆盖源文；如识别不可靠或有差异，以源为准并报告具体位置。',
        '资源按目标文件父目录解析；任务 JSON 的 digests 来自独立当前源资源，复用既有 --image-map 图片身份合同；机械源包按 fragment 核验：',
        '```bash',shlex.join(command),'```',
        context['return_contract'],
        '返回四类信息：新术语及首现位置；原文或解析现象；已执行检查及结果；不确定项。',
        '检查通过和任务回报只供主 Agent 定位，不能授予语义复核/恢复/合并资格。主 Agent 分派前须再次核对当前事实。']
    return {'package':name,'source':exp['path'],'target':exp['target'],'digests':digests,
            'source_facts':{'meta':meta,'body':exp['body']},
            'context_refs':refs,'structural_conversions':conversions,'table_conversions':table_policy,
            'table_map':table_map,
            'command':command,'task':'\n'.join(lines)+'\n'}


def task_changes(previous, current):
    """只读历史包与任务中保留的实际口径文字，不能从摘要还原。"""
    source_facts = previous.get('source_facts')
    if not isinstance(source_facts, dict) or not isinstance(source_facts.get('body'), str):
        raise ValueError('历史任务仅有摘要/缺旧源正文，不能重建前后内容')
    _, old_body = rwp._frontmatter(previous['source'])
    if old_body != source_facts['body']:
        raise ValueError('只读旧源包与历史任务不符；请保留实际旧源包，不能猜测前文')
    changes = []
    def compare(label, before, after):
        if before != after:
            changes.append({'location': label, 'before': before, 'after': after,
                'diff': ''.join(difflib.unified_diff(before.splitlines(True),
                    after.splitlines(True), fromfile='旧 '+label, tofile='当前 '+label))})
    compare('源包正文', old_body, current['source_facts']['body'])
    compare('包顺序/实例/范围', json.dumps(source_facts['meta'], ensure_ascii=False, sort_keys=True),
            json.dumps(current['source_facts']['meta'], ensure_ascii=False, sort_keys=True))
    old_refs = previous.get('context_refs')
    if not isinstance(old_refs, dict):
        raise ValueError('历史任务未保留适用规则文字；须提供可回查的前后依据')
    for field, refs in current['context_refs'].items():
        if field not in old_refs or not isinstance(old_refs[field], list) or any(
                not isinstance(ref.get('content'), str) or rwp._sha256(ref['content']) != ref.get('sha256')
                for ref in old_refs[field]):
            raise ValueError('历史任务未保留可核对的 '+field+' 选区正文')
        compare(field+' 选区及内容', json.dumps(old_refs[field], ensure_ascii=False, sort_keys=True),
                json.dumps(refs, ensure_ascii=False, sort_keys=True))
    if 'structural_conversions' not in previous:
        raise ValueError('历史任务未保留具体转换合同，不能推测旧口径')
    compare('已批准具体转换', json.dumps(previous['structural_conversions'], ensure_ascii=False, sort_keys=True),
            json.dumps(current['structural_conversions'], ensure_ascii=False, sort_keys=True))
    compare('本包表格转换依据', json.dumps(previous.get('table_conversions'), ensure_ascii=False, sort_keys=True),
            json.dumps(current.get('table_conversions'), ensure_ascii=False, sort_keys=True))
    compare('完整表映射引用', str(previous.get('table_map')), str(current.get('table_map')))
    compare('当前核验命令', json.dumps(previous['command'], ensure_ascii=False),
            json.dumps(current['command'], ensure_ascii=False))
    return {'previous_package': previous['package'], 'current_package': current['package'],
            'changes': changes,
            'recheck': '主 Agent 核对上述前后依据及影响范围；执行当前任务，额外返回变化相关发现。旧任务回报/收件不授予资格；恢复/合并仍重读当前事实，受影响包须实际重新复核登记，合并后独立全量验收。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--strategy',required=True)
    parser.add_argument('--source-packages',required=True)
    parser.add_argument('--project-context',required=True)
    parser.add_argument('--package',required=True)
    parser.add_argument('--output',required=True,help='指定本包任务 JSON（task 为可直接读取的任务正文）')
    parser.add_argument('--previous-task',help='只读历史任务及其仍保留的旧源包，输出精确前后与重验事项')
    args=parser.parse_args()
    try:
        previous_path=Path(args.previous_task).resolve() if args.previous_task else None
        previous_bytes=previous_path.read_bytes() if previous_path else None
        previous=json.loads(previous_bytes) if previous_bytes else None
        def current():
            context=rwp.load_project_context(args.project_context,args.source)
            _,_,sources,_,_=rwp.check_options(context)
            adaptation=None
            if sources:
                _,adaptation,_=rwp._load_source_adaptation(sources,Path(args.source).read_text(encoding='utf-8'))
            scope=context['source_scope'];orders=None if scope=='all' else scope
            packages=rwp.current_packages(args.source,args.source_packages,args.strategy,orders,adaptation,args.project_context)
            exp=next((p for p in packages if p['name']==args.package),None)
            if exp is None:raise ValueError('任务不在已确认当前范围')
            result=task(context,exp,args.source,args.output)
            if previous is not None:
                result['drift']=task_changes(previous,result)
                result['task']+='\n## 本次变化与重验\n\n'+json.dumps(result['drift'],ensure_ascii=False,indent=2)+'\n'
            return context,exp,result
        context,exp,result=current();output=Path(args.output).resolve()
        protected=rwp.protected_inputs(context,[exp],args.source)
        if previous_path:
            protected.update((previous_path,Path(previous['source']).resolve(),Path(previous['target']).resolve()))
            historical_refs=[ref['path'] for refs in previous['context_refs'].values() for ref in refs]
            old_maps=previous.get('table_map') or []
            if isinstance(old_maps,str):old_maps=[old_maps]
            historical_refs+=old_maps
            old_command=previous['command']
            for i,flag in enumerate(old_command[:-1]):
                if flag in ('--strong-token-file','--numeric-policy','--source-adaptation','--image-map','--project-context'):
                    historical_refs.append(old_command[i+1])
            for ref in historical_refs:
                path=Path(ref)
                if not path.is_absolute():raise ValueError('历史输入基点不可确定')
                protected.add(path.resolve())
        if output in protected:raise ValueError('任务输出与受保护输入/译文冲突')
        old=output.read_bytes() if output.exists() else None
        def guard():
            if current()[2]!=result:raise ValueError('发布前任务事实变化')
            if previous_path and previous_path.read_bytes()!=previous_bytes:raise ValueError('历史任务在发布前变化')
            if (output.read_bytes() if output.exists() else None)!=old:raise ValueError('旧任务变化')
        atomic_write(output,result,guard)
        print('四要素与当前来源已核对；仅生成任务，不授予完成资格: '+str(output))
    except (OSError,ValueError,KeyError,TypeError,ImportError) as exc:
        parser.exit(1,'任务拒绝: %s\n'%exc)


if __name__=='__main__':
    main()
