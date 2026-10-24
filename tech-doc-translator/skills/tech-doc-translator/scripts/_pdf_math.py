"""PDF confirmed-tex-v1 的原页事实与消费；输出映射不是核验预期。"""
import hashlib
import json
import re
from dataclasses import replace

from markdown_it import MarkdownIt
from markdown_it.rules_block.table import escapedSplit
from _pdf_source import load_fitz, norm_words
from _verification import (SourceMathContext, scan_math, heading_entries,
                           markdown_table_tokens, encode_table_math, decode_table_math)
from _source_reconcile import _md_inline_reading
from _html_fidelity import markdown_inline_code

CONTRACT = 'confirmed-tex-v1'


def read_document(path, exact=False):
    """确认PDF数学保持字节换行；普通来源保留既有通用换行视图。"""
    with open(path,encoding='utf-8',newline='') as handle:
        text=handle.read()
    if exact or metadata(text).get('pdf_formula_contract'):
        return text
    return text.replace('\r\n','\n').replace('\r','\n')


def metadata(text):
    match=re.match(r'^---\n(.*?)\n---\n',text,re.S)
    return ({k.strip():v.strip() for k,v in (line.split(':',1)
             for line in match[1].splitlines() if ':' in line)} if match else {})


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def enabled(checklist, text=''):
    declared = checklist.get('formula_contract')
    has_facts = any('content' in b or 'cells' in b for b in checklist.get('blocks', []))
    source_contract=metadata(text).get('pdf_formula_contract')
    if declared is None and not has_facts and source_contract is None:
        return False
    if declared != CONTRACT:
        raise ValueError('公式合同缺失或未知；新事实不得降级为旧路径')
    if source_contract is not None and source_contract!=CONTRACT:
        raise ValueError('源/包与清单公式合同冲突')
    return True


def contents(block):
    """同一块内的有限内容宿主；表格不另存一份展平权威。"""
    if 'cells' in block:
        return [(cell['id'],cell['content']) for cell in block['cells']]
    return [(None,block.get('content',[]))]


def occurrences(checklist):
    return [(block, i, item) for block in sorted(checklist.get('blocks', []),
                                               key=lambda b: b['order'])
            for _,content in ([(cell['id'],cell['content']) for _,cell in sorted(table_targets(block).items())]
                              if 'cells' in block else contents(block))
            for i,item in enumerate(content)
            if item.get('type') == 'math']


def groups(checklist):
    result={}
    for _,_,item in occurrences(checklist):
        if item.get('group') is not None:
            if not isinstance(item['group'],str) or not item['group'].strip():
                raise ValueError('公式组身份无效，须明确原页关系')
            result.setdefault(item['group'],[]).append(item['id'])
    return result


def footnote_dependencies(checklist,mapping):
    maps={b['id']:b for b in mapping};ranges=[]
    for note in checklist['blocks']:
        if note['type']!='footnote_def':continue
        members=[note]+[b for b in checklist['blocks'] if b.get('footnote')==note['id']]
        members.extend(b for b in checklist['blocks'] if any(
            i['type']=='footnote_ref' and i['label']==note['footnote_label'] for _,items in contents(b) for i in items))
        ranges.append((min(maps[b['id']]['md_start'] for b in members),max(maps[b['id']]['md_end'] for b in members)))
    return ranges


def dependency_ranges(view):
    locations={m['id']:m for block in view['mapping'] for m in block.get('math',[])}
    ranges=[(min(locations[i]['md_start'] for i in members),
             max(locations[i]['md_end'] for i in members))
            for members in groups(view['checklist']).values()]
    ranges.extend(footnote_dependencies(view['checklist'],view['mapping']))
    maps={b['id']:b for b in view['mapping']}
    for block in view['checklist']['blocks']:
        for resource in ('figure','table'):
            if block.get(resource) is not None:
                parent=maps[block[resource]];caption=maps[block['id']]
                ranges.append((min(parent['md_start'],caption['md_start']),max(parent['md_end'],caption['md_end'])))
        if 'cells' in block or any(item.get('type') in ('code','link') for item in block.get('content',[])):
            ranges.append((maps[block['id']]['md_start'],maps[block['id']]['md_end']))
        if block['type']!='algorithm':continue
        members=[block]+[b for b in view['checklist']['blocks'] if b.get('algorithm')==block['id']]
        ranges.append((maps[block['id']]['md_start'],max(maps[b['id']]['md_end'] for b in members)))
    return ranges


def context(checklist):
    return SourceMathContext([(value, '') for block, _, item in occurrences(checklist)
                              if item.get('kind') == 'inline'
                              for value in dict.fromkeys((item['tex'],item['tex'].replace('\n','\n    '))
                                  if block['type']=='footnote_def' or block.get('footnote') else (item['tex'],))])


def original_text(doc, origin):
    """重新定位原生字形序；不以框内同词或生成缓存替代。"""
    if not isinstance(origin, dict) or not origin.get('fragments'):
        raise ValueError('缺少原字形片段定位')
    fitz = load_fitz()
    page = doc[origin['page'] - 1]
    if origin.get('extraction') != {'pymupdf':fitz.VersionBind, 'view':'rawdict'}:
        raise ValueError('字形提取口径漂移，须实际回源重核')
    native = page.get_text('rawdict')['blocks']
    parts = []
    used = set()
    previous_line=None
    for fragment in origin['fragments']:
        chars = native[fragment['block']]['lines'][fragment['line']]['spans'][fragment['span']]['chars']
        a, z = fragment['start'], fragment['end']
        if not (isinstance(a,int) and isinstance(z,int) and 0 <= a < z <= len(chars)):
            raise ValueError('原字形区间越界')
        keys = [(fragment['block'],fragment['line'],fragment['span'],i) for i in range(a,z)]
        if used.intersection(keys):
            raise ValueError('重复来源字形片段')
        used.update(keys)
        text = ''.join(c['c'] for c in chars[a:z])
        if text != fragment.get('text'):
            raise ValueError('原字形与确认原值不符')
        if not all(fitz.Rect(origin['rect']).contains(fitz.Point(
                (c['bbox'][0]+c['bbox'][2])/2,(c['bbox'][1]+c['bbox'][3])/2))
                   for c in chars[a:z]):
            raise ValueError('字形片段不属于声明区域')
        current_line=(fragment['block'],fragment['line'])
        if previous_line is not None and current_line!=previous_line:
            parts.append('\n')
        parts.append(text)
        previous_line=current_line
    value = ''.join(parts)
    if value != origin.get('text'):
        raise ValueError('原片段内容与原提取值不符')
    return value


def table_targets(block):
    cells=block.get('cells');conversion=block.get('table_conversion',{})
    if block['type']!='table_region' or not isinstance(cells,list) or not cells or not conversion.get('basis'):
        raise ValueError('表格缺逐格原页事实或具体目标格转换')
    identities={};occupied=set()
    for cell in cells:
        identity=cell.get('id')
        if not identity or identity in identities or not isinstance(cell.get('content'),list):
            raise ValueError('表格源格身份/内容缺失或重复')
        if any(type(cell.get(k)) is not int or cell[k]<1 for k in ('row','column','rowspan','colspan')) or type(cell.get('header')) is not bool:
            raise ValueError('表格源格行列/跨度/表头未确认')
        area={(r,c) for r in range(cell['row'],cell['row']+cell['rowspan'])
              for c in range(cell['column'],cell['column']+cell['colspan'])}
        if occupied.intersection(area):raise ValueError('表格源格跨度重叠')
        occupied.update(area);identities[identity]=cell
        if not load_fitz().Rect(block['rect']).contains(load_fitz().Rect(cell['rect'])):
            raise ValueError('源格区域不属于表框')
    if occupied!={(r,c) for r in range(1,max(r for r,c in occupied)+1)
                   for c in range(1,max(c for r,c in occupied)+1)}:
        raise ValueError('原格网遗漏空格位')
    rows,columns=conversion.get('rows'),conversion.get('columns')
    if any(type(n) is not int or n<1 for n in (rows,columns)):
        raise ValueError('表格目标行列未确认')
    targets={};used=[]
    for target in conversion.get('cells',[]):
        position=(target.get('row'),target.get('column'))
        if position in targets or position not in {(r,c) for r in range(1,rows+1) for c in range(1,columns+1)}:
            raise ValueError('表格具体目标格重复/越界')
        identity=target.get('source')
        if identity not in identities:raise ValueError('表格目标缺已确认源格')
        targets[position]=identities[identity];used.append(identity)
    if set(used)!=set(identities) or len(targets)!=rows*columns:
        raise ValueError('表格目标映射漏格/重复，未知转换保持待处理')
    if any(used.count(identity)>1 and any(i['type']=='math' for i in cell['content'])
           for identity,cell in identities.items()):
        raise ValueError('具体表格跨度转换不得复制同次数学出现')
    return targets


def validate(checklist, doc):
    groups(checklist)
    source = checklist['source']['sha256']
    scope = checklist['scope']
    review = checklist.get('formula_review', {})
    if not review.get('basis') or review.get('source_sha256') != source or review.get('scope') != scope:
        raise ValueError('缺当前全范围数学原页复核依据')
    ids = set()
    original_glyphs = set()
    blocks=sorted(checklist['blocks'],key=lambda b:b['order'])
    notes={b.get('footnote_label'):b for b in blocks if b['type']=='footnote_def'}
    if len(notes)!=sum(b['type']=='footnote_def' for b in blocks):raise ValueError('脚注定义标签重复')
    for block in blocks:
        if block['type']=='footnote_def':
            label=block.get('footnote_label')
            if not isinstance(label,str) or not re.fullmatch(r'[^\]\s]+',label):raise ValueError('脚注缺有效原标签')
            origin=block.get('footnote_origin')
            if original_text(doc,origin)!=label or origin['page']!=block['page'] or not load_fitz().Rect(block['rect']).contains(load_fitz().Rect(origin['rect'])):
                raise ValueError('脚注原标签定位/所属损伤')
        if block.get('footnote') is not None:
            index=blocks.index(block);parents=[(i,b) for i,b in enumerate(blocks) if b['id']==block['footnote'] and b['type']=='footnote_def']
            if len(parents)!=1:raise ValueError('脚注子块缺当前定义')
            first,parent=parents[0]
            if first>=index or any(b.get('footnote')!=parent['id'] for b in blocks[first+1:index+1]) or block['page']!=parent['page'] or not load_fitz().Rect(parent['rect']).contains(load_fitz().Rect(block['rect'])):
                raise ValueError('脚注子块原序/原页区域不属于当前定义')
    for index,block in enumerate(blocks):
        if block.get('algorithm') is None:continue
        parents=[(i,b) for i,b in enumerate(blocks) if b['id']==block['algorithm'] and b['type']=='algorithm']
        if len(parents)!=1:raise ValueError('算法所属身份缺失或歧义')
        parent_index,parent=parents[0]
        if (parent_index>=index or any(b.get('algorithm')!=parent['id'] for b in blocks[parent_index+1:index+1])
                or block['page']!=parent['page'] or not load_fitz().Rect(parent['rect']).contains(load_fitz().Rect(block['rect']))):
            raise ValueError('算法子块顺序/原页区域与声明所属不符')
    for block in checklist['blocks']:
        if 'content' not in block and 'cells' not in block:
            if block['type']=='formula':
                raise ValueError('公式未确认；仍须回源处理，不能删除pending取得资格')
            continue
        if block['type'] not in ('paragraph','formula','heading','figure_caption','table_caption','algorithm','list_item','table_region','footnote_def'):
            raise ValueError('当前尚未支持该数学所属角色: '+block['type'])
        if block['type']=='heading' and (type(block.get('level')) is not int or not 1<=block['level']<=8):
            raise ValueError('确认数学标题缺合法层级')
        if block['type']=='list_item':
            if not block['content'] or block['content'][0].get('type')!='text':
                raise ValueError('说明条目缺已确认的原说明文字')
            if 'list_marker' in block or 'list_conversion' in block:
                marker=block.get('list_marker');conversion=block.get('list_conversion',{})
                if (not isinstance(marker,str) or not re.fullmatch(r'(?:[0-9]{1,9}[.)]|[-+*])',marker)
                        or conversion.get('source_role')!='paragraph' or conversion.get('target_role')!='list_item'
                        or conversion.get('marker')!=marker or not conversion.get('basis')):
                    raise ValueError('说明条目缺具体原段落→列表转换依据')
            elif not re.match(r'^ {0,3}(?:[0-9]+[.)]|[-+*])[ \t]+',block['content'][0]['origin']['text']):
                raise ValueError('说明条目缺原可见列表标记或具体转换；未知转换保持待处理')
        if 'cells' in block:table_targets(block)
        for cell_id,content in contents(block):
          for slot,item in enumerate(content):
              if item.get('type') not in ('text','math','code','link','footnote_ref'):
                  raise ValueError('未知有序内容角色')
              origin=item.get('origin',{})
              if origin.get('page') != block['page'] or origin['page'] not in scope:
                  raise ValueError('内容原页/范围与所属块不符')
              original_text(doc,origin)
              keys={(origin['page'],f['block'],f['line'],f['span'],i)
                    for f in origin['fragments'] for i in range(f['start'],f['end'])}
              if original_glyphs.intersection(keys):
                  raise ValueError('同一原字形被重复登记为不同内容出现')
              original_glyphs.update(keys)
              fitz=load_fitz()
              host_rect=next(cell['rect'] for cell in block['cells'] if cell['id']==cell_id) if cell_id is not None else block['rect']
              if not fitz.Rect(host_rect).contains(fitz.Rect(origin['rect'])):
                  raise ValueError('原字形区域不属于当前宿主块')
              if item['type']=='code' and ('\n' in origin['text'] or '\r' in origin['text']):
                  raise ValueError('多行代码须按现行golden代码块处理，不展平为行内代码')
              if item['type']=='footnote_ref' and (item.get('label') not in notes or origin['text']!=item['label']):
                  raise ValueError('脚注引用缺原可见标记或当前定义目标')
              if item['type']=='link':
                  target=item.get('target');page=doc[origin['page']-1]
                  links=[(fitz.Rect(link['from'])*page.derotation_matrix,link['uri'])
                         for link in page.get_links() if link.get('uri')]
                  raw=page.get_text('rawdict')['blocks']
                  for fragment in origin['fragments']:
                      chars=raw[fragment['block']]['lines'][fragment['line']]['spans'][fragment['span']]['chars']
                      for char in chars[fragment['start']:fragment['end']]:
                          box=char['bbox'];point=fitz.Point((box[0]+box[2])/2,(box[1]+box[3])/2)
                          if not target or {uri for rect,uri in links if rect.contains(point)}!={target}:
                              raise ValueError('链接目标或原页标签定位不符/歧义')
              if item['type']!='math':
                  continue
              identity=item.get('id')
              if not identity or identity in ids:
                  raise ValueError('数学出现缺ID或重复身份')
              ids.add(identity)
              owner={'block':block['id'],'role':block['type']}
              if cell_id is not None:owner['cell']=cell_id
              if item.get('owner') != owner or item.get('slot') != slot:
                  raise ValueError('数学所属或局部位置与内容序不符: '+identity)
              if item.get('kind') not in ('inline','block') or not isinstance(item.get('tex'),str) or not item['tex']:
                  raise ValueError('数学类型/确认TeX缺失')
              if 'label' not in item:
                  raise ValueError('式号须显式给出或为空')
              label=item['label']
              if label is not None:
                  if not label.get('text') or original_text(doc,label.get('origin')) != label['text']:
                      raise ValueError('式号原页定位/内容不符')
                  loc=label['origin']
                  if loc['page']!=block['page'] or not fitz.Rect(block['rect']).contains(fitz.Rect(loc['rect'])):
                      raise ValueError('式号原页区域不属于该次数学宿主')
                  label_keys={(loc['page'],f['block'],f['line'],f['span'],i)
                              for f in loc['fragments'] for i in range(f['start'],f['end'])}
                  if original_glyphs.intersection(label_keys):
                      raise ValueError('同一式号字形被重复登记为不同出现')
                  original_glyphs.update(label_keys)
              conversion=item.get('conversion',{})
              if (not conversion.get('basis') or conversion.get('source') != origin['text']
                      or conversion.get('target') != item['tex']):
                  raise ValueError('缺具体原字形→确认TeX转换')
              confirmation=item.get('confirmation',{})
              fact={k:v for k,v in item.items() if k!='confirmation'}
              if (not confirmation.get('basis') or confirmation.get('source_sha256')!=source
                      or confirmation.get('scope')!=scope or confirmation.get('fact_sha256')!=digest(fact)):
                  raise ValueError('数学确认未绑定当前来源/范围/内容；须实际回源重核: '+identity)


def render_content(block):
    """仅序列化人工事实；出现偏移随实际追加传递。"""
    text=''; maths=[]
    previous=None
    for slot,item in enumerate(block['content']):
        first=item['origin']['fragments'][0];last=item['origin']['fragments'][-1]
        current=(item['origin']['page'],first['block'],first['line'])
        if (previous is not None and previous!=current and text and not text[-1].isspace()
                and not item['origin']['text'][0].isspace()):
            text+=' '  # 沿用普通PDF块物理行间的阅读连接，不改TeX内部字符。
        previous=(item['origin']['page'],last['block'],last['line'])
        start=len(text)
        if item['type']=='footnote_ref':
            text+='[^'+item['label']+']'
            continue
        if item['type']=='text':
            # CommonMark字面文字，数学及代码不经过这条转义路径。
            value=item['origin']['text'];prefix=''
            if block['type']=='list_item' and slot==0 and 'list_marker' not in block:
                marker=re.match(r'^ {0,3}(?:[0-9]+[.)]|[-+*])[ \t]+',value)
                prefix=value[:marker.end()];value=value[marker.end():]
            text+=prefix+re.sub(r'([\\`*_$\[\]<>#&])',r'\\\1',value)
            continue
        if item['type']=='code':
            text+=markdown_inline_code(item['origin']['text'])
            continue
        if item['type']=='link':
            label=re.sub(r'([\\`*_$\[\]<>#&])',r'\\\1',item['origin']['text'])
            target=re.sub(r'([\\<>&])',r'\\\1',item['target'])
            text+='['+label+'](<'+target+'>)'
            continue
        tex=item['tex'];label=item['label']
        if label is not None and item['kind']=='block':
            escaped=re.sub(r'([\\{}%#$&_])',r'\\\1',label['text'])
            tex+=r'\tag*{\text{'+escaped+'}}'
        delim='$' if item['kind']=='inline' else '$$'
        text+=delim+tex+delim
        label_range=None
        if label is not None and item['kind']=='inline':
            a=len(text)+1
            text+=' '+re.sub(r'([\\`*_$\[\]<>#&])',r'\\\1',label['text'])
            label_range=[a,len(text)]
        maths.append({'id':item['id'],'owner':item['owner'],'slot':item['slot'],
                      'md_start':start,'md_end':start+len(delim+tex+delim)})
        if label_range is not None:maths[-1]['label_range']=label_range
    return text,maths


def render_table(block):
    targets=table_targets(block);text='';maths=[]
    conversion=block['table_conversion']
    for row in range(1,conversion['rows']+1):
        text+='| '
        for col in range(1,conversion['columns']+1):
            cell=targets[(row,col)]
            body,local=render_content({'type':'paragraph','content':cell['content']})
            represented='';offsets=[len(text)];positions=[];math_index=0
            for index,char in enumerate(body):
                while math_index<len(local) and index>=local[math_index]['md_end']:math_index+=1
                in_math=math_index<len(local) and local[math_index]['md_start']<=index<local[math_index]['md_end']
                represented+=(encode_table_math(char) if in_math else char.replace('|',r'\|').replace('\n',' '))
                offsets.append(len(text)+len(represented))
            for occurrence in local:
                where=dict(occurrence)
                where['md_start']=offsets[occurrence['md_start']];where['md_end']=offsets[occurrence['md_end']]
                if 'label_range' in occurrence:where['label_range']=[offsets[pos] for pos in occurrence['label_range']]
                positions.append(where)
            text+=represented+' |'+(' ' if col<conversion['columns'] else '\n')
            maths.extend(positions)
        if row==1:text+='| '+' | '.join('---' for _ in range(conversion['columns']))+' |\n'
    return text.rstrip('\n'),maths


def read_expression(span, labelled=False):
    """消费规定末尾包装；不调用生成器构造期待字符串。"""
    value=span.expr
    label=None
    if span.kind=='block' and labelled:
        marker=r'\tag*{\text{'
        index=value.rfind(marker)
        if index<0:
            raise ValueError('编号包装缺失')
        pos=index+len(marker);chars=[]
        while pos<len(value):
            ch=value[pos]
            if ch=='\\':
                pos+=1
                if pos>=len(value) or value[pos] not in '\\{}%#$&_':
                    raise ValueError('编号包装文本转义无效')
                chars.append(value[pos])
            elif ch=='}':
                if value[pos:]!='}}':
                    raise ValueError('编号包装括号不配对或存在额外内容')
                label=''.join(chars);break
            elif ch in '{%#$&_':
                raise ValueError('编号包装文本存在未转义字符')
            else:
                chars.append(ch)
            pos+=1
        if label is None:
            raise ValueError('编号包装不完整')
        value=value[:index]
    return value,label


def read_inline_label(text,span,label_text):
    """在该次数学结束处读取邻接文本号，不搜索同文或生成预期包装。"""
    pos=span.end
    if text[pos:pos+1]!=' ':
        raise ValueError('行内式号缺少邻接独立文本')
    pos+=1;start=pos;chars=[]
    for _ in label_text:
        if pos>=len(text):raise ValueError('行内式号文本缺失')
        if text[pos]=='\\':
            escaped=_md_inline_reading(text[pos:pos+2])
            if len(escaped)!=1:
                raise ValueError('行内式号文本转义无效')
            chars.append(escaped);pos+=2
        else:chars.append(text[pos]);pos+=1
    value=''.join(chars)
    if value!=label_text:raise ValueError('行内式号内容/位置损伤')
    return value,[start,pos]


def caption_identity(value):
    prefix=re.match(r'^\s*(Figure|Fig\.?|Table|图|表)',value)
    if prefix is None:return None
    label=re.match(r'\s*([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)(?=[:：.\s]|$)',value[prefix.end():])
    return ('figure' if prefix[1] in ('Figure','Fig','Fig.','图') else 'table',label[1]) if label else None


def actual_tables(text, starts, spans):
    """先由正式表格块规则确认，再定位实际格；不全局解码/裸管道分格。"""
    lines=text.splitlines();tables=[];current=None;row=0
    for token in markdown_table_tokens(text):
        if token.type=='table_open':
            a,z=token.map
            current={'role':'table_region','start':starts[a],
                     'end':starts[z]-1,'spans':[], 'level':None,'cells':[]}
            tables.append(current);row=0
        elif token.type=='table_close':current=None
        elif token.type=='tr_close' and current is not None:
            if column!=len(segments):raise ValueError('实际表格分隔损伤/额外格')
        elif token.type=='tr_open':
            row+=1;line_no=token.map[0];line=lines[line_no]
            # 跟随已采用解析器的转义语义，仅恢复它未提供的原字符范围。
            borders=[i for i,c in enumerate(line) if c=='|' and (i==0 or line[i-1]!='\\')]
            boundaries=[-1]+borders+[len(line)]
            segments=[(a+1,z) for a,z in zip(boundaries,boundaries[1:])]
            if borders and not line[:borders[0]].strip():segments=segments[1:]
            if borders and not line[borders[-1]+1:].strip():segments=segments[:-1]
            parsed=escapedSplit(line.strip())
            if parsed and not parsed[0].strip():parsed=parsed[1:]
            if parsed and not parsed[-1].strip():parsed=parsed[:-1]
            if len(parsed)!=len(segments):raise ValueError('实际表格格位定位歧义')
            column=0
        elif token.type=='inline' and current is not None:
            if column>=len(segments) or token.content!=parsed[column].strip():
                raise ValueError('实际表格分隔损伤/额外格')
            a,z=segments[column];column+=1
            a+=len(line[a:z])-len(line[a:z].lstrip());z-=len(line[a:z])-len(line[a:z].rstrip())
            start,end=starts[line_no]+a,starts[line_no]+z
            local=[s for s in spans if start<=s.start and s.end<=end]
            current['spans'].extend(local)
            current['cells'].append({'row':row,'column':column,'start':start,'end':end,'spans':local})
    return tables


def footnote_view(text, scan_context):
    """实际插件确认定义边界后，只撤去脚注语法，保留原偏移。"""
    from mdit_py_plugins.footnote import footnote_plugin
    masked=list(text)
    for span in scan_math(text,source_context=scan_context).spans:
        for i in range(span.start,span.end):
            if not masked[i].isspace():masked[i]='x'
    tokens=MarkdownIt('commonmark',{'html':False}).enable('table').use(footnote_plugin,move_to_end=False).parse(''.join(masked))
    lines=text.splitlines(keepends=True);starts=[0]
    for line in lines:starts.append(starts[-1]+len(line))
    definitions=[];removed=set()
    for token in tokens:
        if token.type!='footnote_reference_open':continue
        a,z=token.map;label=token.meta['label'];prefix=re.match(r'^ {0,3}\[\^[^\]]+\]:[ \t]*',lines[a])
        if prefix is None:raise ValueError('实际脚注定义首行定位失败')
        definitions.append({'label':label,'start':starts[a],'end':starts[z],
                            'content_start':starts[a]+prefix.end(),
                            'header_end':starts[a]+len(lines[a].rstrip('\r\n'))})
        removed.update(range(starts[a],starts[a]+prefix.end()))
        for line in range(a+1,z):
            columns=0;chars=0
            for char in lines[line]:
                if columns>=4 or char not in ' \t':break
                columns+=1 if char==' ' else 4-columns%4;chars+=1
            if columns==4:removed.update(range(starts[line],starts[line]+chars))
    offsets=[i for i in range(len(text)) if i not in removed]+[len(text)]
    return ''.join(text[i] for i in offsets[:-1]),offsets,definitions


def markdown_blocks(text, scan_context):
    """真实CommonMark块边界；先保护数学，保留实际字符偏移。"""
    if '[^' in text:
        projected,offsets,definitions=footnote_view(text,scan_context)
        if definitions:
            blocks,scan=_markdown_blocks(projected,scan_context)
            spans=tuple(replace(s,start=offsets[s.start],end=offsets[s.end-1]+1,
                                start_line=text.count('\n',0,offsets[s.start])+1) for s in scan.spans)
            for block in blocks:
                def shift(value):
                    for key in ('start','content_start','prose_start'):
                        if key in value:value[key]=offsets[value[key]]
                    for key in ('end','content_end'):
                        if key in value:value[key]=offsets[value[key]-1]+1
                    value['spans']=[s for s in spans if value['start']<=s.start and s.end<=value['end']]
                shift(block)
                for cell in block.get('cells',[]):shift(cell)
                note=next((d for d in definitions if d['start']<=block['start']<d['end']),None)
                if note is not None:
                    block['footnote_label']=note['label']
                    block.setdefault('content_start',block['start'])
                    first=not any(b.get('footnote_label')==note['label'] for b in blocks[:blocks.index(block)])
                    line_start=text.rfind('\n',0,block['start'])+1
                    block['start']=note['start'] if first else line_start
                    if first and block['role'] in ('paragraph','formula') and block['content_start']<note['header_end']:
                        block['role']='footnote_def'
            for note in definitions:
                if not any(b.get('footnote_label')==note['label'] and b['role']=='footnote_def' for b in blocks):
                    first=next((b for b in blocks if b.get('footnote_label')==note['label']),None)
                    if first is not None:
                        first['start']=max(note['content_start'],text.rfind('\n',0,first['content_start'])+1)
                    blocks.append({'role':'footnote_def','start':note['start'],'end':note['content_start'],
                                   'content_start':note['content_start'],'spans':[],
                                   'footnote_label':note['label'],'leaf_groups':((),),'prose':False})
            blocks.sort(key=lambda b:b['start'])
            return blocks,replace(scan,spans=spans)
    return _markdown_blocks(text,scan_context)


def _markdown_blocks(text, scan_context):
    scan_text=text
    head=re.match(r'^---\n.*?\n---\n',text,re.S)
    if head:
        scan_text=''.join('\n' if c=='\n' else ' ' for c in text[:head.end()])+text[head.end():]
    scan=scan_math(scan_text,source_context=scan_context)
    if scan.issues:
        raise ValueError('未闭合数学定界: '+str(scan.issues[0]))
    masked=list(text)
    for span in scan.spans:
        for i in range(span.start,span.end):
            if masked[i]!='\n':masked[i]='x'
    lines=text.splitlines(keepends=True);starts=[0]
    for line in lines:starts.append(starts[-1]+len(line))
    tables=actual_tables(text,starts,scan.spans)
    # 只在已确认的实际表格数学范围内解码，偏移仍指向原输出。
    scan=replace(scan,spans=tuple(replace(s,expr=decode_table_math(s.expr))
        if any(t['start']<=s.start and s.end<=t['end'] for t in tables) else s for s in scan.spans))
    for table in tables:
        table['spans']=[s for s in scan.spans if table['start']<=s.start and s.end<=table['end']]
        for cell in table['cells']:
            cell['spans']=[s for s in table['spans'] if cell['start']<=s.start and s.end<=cell['end']]
            cursor=cell['start'];facts=[]
            for span in cell['spans']:
                facts.append(inline_reading_facts(text[cursor:span.start].replace(r'\|','|')));cursor=span.end
            facts.append(inline_reading_facts(text[cursor:cell['end']].replace(r'\|','|')))
            cell['leaf_groups']=tuple(tuple(leaves) for leaves,_,_ in facts)
            cell['prose']=any(prose for _,prose,_ in facts)
        table['cell_facts']=tuple((c['row'],c['column'],len(c['spans']),c['leaf_groups'],c['prose']) for c in table['cells'])
        table['leaf_groups']=();table['prose']=any(c['prose'] for c in table['cells'])
    result=list(tables)
    body=''.join(masked)
    if text.startswith('---\n'):
        end=text.find('\n---\n',4)
        if end<0:raise ValueError('源元数据未闭合')
        body=''.join('\n' if c=='\n' else ' ' for c in body[:end+5])+body[end+5:]
    math_lines={i for span in scan.spans for i in range(
        text.count('\n',0,span.start),text.count('\n',0,span.end-1)+1)}
    # 仅解析占位文本补齐数学内部空行；真实行号和原字符区间保持。
    body=''.join(('x'+line if i in math_lines and not line.strip() else line)
                 for i,line in enumerate(body.splitlines(keepends=True)))
    heading_levels={line:level for line,level,_ in heading_entries(body)}
    tokens=MarkdownIt('commonmark').parse(body)
    lists=[]
    for token_index,token in enumerate(tokens):
        if token.type in ('ordered_list_open','bullet_list_open'):
            start=token.attrGet('start')
            lists.append({'kind':'ordered' if token.type=='ordered_list_open' else 'bullet',
                          'number':(1 if start is None else start)-1})
        elif token.type=='list_item_open':lists[-1]['number']+=1
        elif token.type in ('ordered_list_close','bullet_list_close'):lists.pop()
        if token.type not in ('paragraph_open','heading_open','fence','html_block') or token.map is None:
            continue
        a,z=token.map;start,end=starts[a],starts[z]
        if any(t['start']<=start and end-1<=t['end'] for t in tables):continue
        role='heading' if token.type=='heading_open' else 'code_region' if token.type=='fence' else 'paragraph'
        if role=='paragraph' and lists:role='list_item'
        level=heading_levels.get(a+1)
        if level is not None:role='heading'
        local=[s for s in scan.spans if start<=s.start and s.end<=end]
        raw=text[start:end].rstrip('\n')
        # 块规则已确定合法缩进；数学前的纯空白不改变展示角色。
        if (role=='paragraph' and len(local)==1 and local[0].kind=='block'
                and not text[start:local[0].start].strip()):role='formula'
        entry={'role':role,'start':start,'end':start+len(raw),'spans':local,'level':level}
        if lists:entry['list_path']=tuple((lst['kind'],lst['number']) for lst in lists)
        if role=='list_item':
            prefix=re.match(r'^ {0,3}([0-9]+[.)]|[-+*])[ \t]+',raw)
            if prefix is not None:
                entry['list_marker']=prefix[1];entry['prose_start']=start+prefix.end()
        if role=='heading':
            prefix=re.match(r'^ {0,3}#{1,8}[ \t]+',raw)
            if prefix is None:raise ValueError('确认数学标题须为现行ATX标题')
            entry['content_start']=start+prefix.end()
        if role=='paragraph':
            children=tokens[token_index+1].children if tokens[token_index+1].type=='inline' else []
            visible=[t for t in children if t.type!='text' or t.content.strip()]
            if raw.startswith('[ALGORITHM] '):
                entry['role']='algorithm';entry['content_start']=start+len('[ALGORITHM] ')
                label=re.match(r'^(?:Algorithm|算法)\s*([0-9A-Za-z]+)(?=[:.\s]|$)',_md_inline_reading(raw[len('[ALGORITHM] '):]))
                if label is None:raise ValueError('算法标记缺实际可见编号身份')
                entry['algorithm_label']=label[1]
            if len(visible)==1 and visible[0].type=='image':
                entry['role']='figure_region';entry['image_label']=caption_identity(visible[0].content)
            prefix=re.match(r'^ {0,3}(\*\*|__)(Figure|Table):[ \t]*',raw)
            if prefix is not None and raw.endswith(prefix[1]):
                inline=MarkdownIt('commonmark').parseInline(''.join(masked[start:start+len(raw)]))[0]
                children=[t for t in inline.children if t.type!='text' or t.content]
                if children and children[0].type=='strong_open' and children[-1].type=='strong_close':
                    entry['role']='figure_caption' if prefix[2]=='Figure' else 'table_caption'
                    entry['content_start']=start+prefix.end();entry['content_end']=entry['end']-len(prefix[1])
                    caption=text[entry['content_start']:entry['content_end']]
                    entry['caption_label']=caption_identity(_md_inline_reading(caption))
        if entry['role'] not in ('code_region','figure_region'):
            cursor=entry.get('prose_start',entry.get('content_start',entry['start']));pieces=[]
            for span in entry['spans']:
                pieces.append(text[cursor:span.start]);cursor=span.end
            pieces.append(text[cursor:entry.get('content_end',entry['end'])])
            facts=[inline_reading_facts(piece) for piece in pieces]
            entry['leaf_groups']=tuple(tuple(leaves) for leaves,_,_ in facts)
            entry['prose']=any(prose for _,prose,_ in facts)
        result.append(entry)
    result.sort(key=lambda b:b['start'])
    for index,entry in enumerate(result):
        if entry['role'] not in ('figure_caption','table_caption'):continue
        candidates=[i for i,image in enumerate(result) if image['role']=='figure_region'
                    and image.get('image_label')==entry.get('caption_label')]
        if len(candidates)==1:entry['image_distance']=index-candidates[0]
        if entry['role']=='table_caption':
            tables=[i for i,b in enumerate(result) if b['role']=='table_region']
            closest=[i for i in tables if abs(i-index)==min((abs(i-index) for i in tables),default=0)]
            if len(closest)==1:entry['table_distance']=index-closest[0]
    return result,scan


def math_hosts(text, blocks, items, spans):
    """实际块中的出现分区和正文存在性，不比较中英措辞或字符数。"""
    locations={};hosts={}
    for item,span in zip(items,spans):
        owners=[i for i,b in enumerate(blocks)
                if b['start']<=span.start and span.end<=b['end']]
        if len(owners)!=1:raise ValueError('数学实际宿主边界缺失或歧义: '+item['id'])
        index=owners[0];locations[item['id']]=index
        hosts.setdefault(index,[]).append((item,span))
    facts={}
    for index,members in hosts.items():
        block=blocks[index];cursor=block.get('prose_start',block.get('content_start',block['start']));prose=[]
        for item,span in members:
            prose.append(text[cursor:span.start]);cursor=span.end
            if item['kind']=='inline' and item['label'] is not None:
                _,label_range=read_inline_label(text,span,item['label']['text'])
                cursor=label_range[1]
        prose.append(text[cursor:block.get('content_end',block['end'])])
        if block['role']!='table_region':_,block['prose'],_=inline_reading_facts(''.join(prose))
        fact=(block['role'],block.get('level'),block.get('caption_label'),block.get('image_distance'),tuple(item['id'] for item,_ in members),
              block['prose'] if block['role']!='heading' else None,block.get('list_path'),block.get('cell_facts'),block.get('table_distance'),block.get('footnote_label'))
        for item,span in members:
            cell=next((c for c in block.get('cells',[]) if c['start']<=span.start and span.end<=c['end']),None)
            facts[item['id']]=fact+((cell['row'],cell['column']) if cell else None,)

    return locations,facts


def inline_reading_facts(text, labels=False):
    """真实叶子及普通正文；代码/链接标签不能冒充其宿主正文。"""
    from mdit_py_plugins.footnote import footnote_plugin
    parser=MarkdownIt('commonmark').use(footnote_plugin,always_match_refs=True,move_to_end=False)
    children=parser.parseInline(text)[0].children
    result=[];prose=[];reading=[];link_end=-1
    for index,token in enumerate(children):
        if token.type=='code_inline':result.append(('code',token.content))
        if token.type=='footnote_ref':result.append(('footnote_ref',token.meta['label']))
        if token.type in ('text','code_inline','softbreak','hardbreak'):
            reading.append('\n' if token.type in ('softbreak','hardbreak') else token.content)
        if token.type=='link_open':
            end=next(i for i in range(index+1,len(children)) if children[i].type=='link_close')
            label=''.join('\n' if t.type in ('softbreak','hardbreak') else t.content for t in children[index+1:end])
            if not label.strip():raise ValueError('链接叶子缺少实际标签')
            result.append(('link',token.attrGet('href'),norm_words(label)) if labels else ('link',token.attrGet('href')))
            link_end=end
        if index>link_end and token.type not in ('code_inline','image','footnote_ref'):
            prose.append(token.content)
    return result,any(char.isalnum() for char in ''.join(prose)),''.join(reading)


def leaf_hosts(blocks,spans):
    return [(block['role'],sum(span.end<=block['start'] for span in spans),block.get('leaf_groups',()),
             block.get('prose') if block['role']!='heading' else None,block.get('list_path'),block.get('cell_facts'),
             block.get('caption_label'),block.get('image_distance'),block.get('table_distance'),block.get('footnote_label'))
            for block in blocks if 'cells' in block or block['role'] in ('figure_caption','table_caption')
            or block.get('footnote_label') is not None or any(block.get('leaf_groups',()))]


def approved_extra_view(text, source_context, approved_extra_math=()):
    """只投影明确译注内逐次获准的数学；来源公式仍须完整独立对账。"""
    if not approved_extra_math:return text,[]
    from _verification import _math_scan_mask
    _,scan=markdown_blocks(text,source_context)
    masked=list(_math_scan_mask(text));starts=[0]
    for line in text.splitlines(keepends=True):starts.append(starts[-1]+len(line))
    for token in MarkdownIt('commonmark').parse(''.join(masked)):
        if token.type in ('fence','code_block','blockquote_open') and token.map:
            a,z=token.map
            masked[starts[a]:starts[z]]=[' ' if char not in '\r\n' else char
                                        for char in masked[starts[a]:starts[z]]]
    pending=list(approved_extra_math);result=list(text);notes=[]
    for match in re.finditer(r'【译注：[^】]*】',''.join(masked)):
        spans=[span for span in scan.spans if match.start()<=span.start and span.end<=match.end()]
        if not spans:continue
        remaining=list(pending)
        for span in spans:
            if span.expr not in remaining:break
            remaining.remove(span.expr)
        else:
            pending=remaining
            notes.append({'line':text.count('\n',0,match.start())+1,
                          'fragment':text[match.start():match.end()]})
            result[match.start():match.end()]=[' ' if char not in '\r\n' else char
                                             for char in text[match.start():match.end()]]
    return ''.join(result),notes


def verify(checklist,doc,text,mapping,translation=None,source_range=None,approved_extra_math=()):
    """原页+人工事实与实际Markdown独立配对，再核对派生定位。"""
    validate(checklist,doc)
    if metadata(text).get('pdf_formula_contract')!=CONTRACT:
        raise ValueError('正式源缺当前公式合同声明，不降级')
    actual,scan=markdown_blocks(text,context(checklist))
    blocks=sorted(checklist['blocks'],key=lambda b:b['order'])
    if len(actual)!=len(blocks):raise ValueError('实际块覆盖/阅读序不符')
    maps={b['id']:b for b in mapping}
    algorithms=[]
    for index,block in enumerate(blocks):
        if block['type']!='algorithm':continue
        children=[i for i,b in enumerate(blocks) if b.get('algorithm')==block['id']]
        end=(children[-1] if children else index)+1
        if actual[index]['role']!='algorithm':raise ValueError('算法实际标题标记损伤')
        if [b['type'] for b in blocks[index:end]]!=[b['role'] for b in actual[index:end]]:
            raise ValueError('算法实际子块角色/顺序损伤')
        algorithms.append((index,end))
    all_maths=[]
    member_blocks={}
    for block_index,(block,read) in enumerate(zip(blocks,actual)):
        entry=maps.get(block['id'],{})
        if (entry.get('md_start'),entry.get('md_end'))!=(read['start'],read['end']):
            raise ValueError('块精确区间/出现身份不符: '+block['id'])
        label=block.get('footnote_label') if block['type']=='footnote_def' else next((b['footnote_label'] for b in blocks if b['id']==block.get('footnote')),None)
        if label!=read.get('footnote_label'):raise ValueError('脚注定义/子块实际所属损伤: '+block['id'])
        if block.get('figure') is not None:
            linked=[i for i,b in enumerate(blocks) if b['id']==block['figure'] and b['type']=='figure_region']
            if len(linked)!=1 or read.get('image_distance')!=block_index-linked[0]:
                raise ValueError('题注与实际图资源所属不符或歧义: '+block['id'])
        if block.get('table') is not None:
            linked=[i for i,b in enumerate(blocks) if b['id']==block['table'] and b['type']=='table_region']
            if block['type']!='table_caption' or len(linked)!=1 or read.get('table_distance')!=block_index-linked[0]:
                raise ValueError('题注与实际表格所属不符或歧义: '+block['id'])
        if 'content' not in block and 'cells' not in block:continue
        if block['type']!=read['role']:raise ValueError('实际块角色损伤: '+block['id'])
        if block['type']=='heading' and block['level']!=read['level']:
            raise ValueError('实际标题层级损伤: '+block['id'])
        if block['type']=='list_item':
            if 'list_marker' in block:
                if read.get('list_marker')!=block['list_marker']:raise ValueError('列表具体转换的实际标记损伤')
                read['content_start']=read['prose_start']
                marker=re.match(r'(?:([0-9]+)[.)]|([-+*]))',block['list_marker'])
            else:
                marker=re.match(r'^ {0,3}(?:([0-9]+)[.)]|([-+*]))[ \t]+',original_text(doc,block['content'][0]['origin']))
            kind,number=read['list_path'][-1]
            if (marker[1] is not None and (kind!='ordered' or number!=int(marker[1]))) or (marker[2] is not None and kind!='bullet'):
                raise ValueError('原页说明条目标记与实际列表类型/序号损伤')
        whole_read=read
        if 'cells' in block:
            targets=table_targets(block)
            if [(c['row'],c['column']) for c in read['cells']]!=sorted(targets):
                raise ValueError('实际表格行列/空格位损伤')
            readings=[(targets[(c['row'],c['column'])]['id'],targets[(c['row'],c['column'])]['content'],c)
                      for c in read['cells']]
        else:readings=[(None,block['content'],read)]
        for cell_id,content,read in readings:
            maths=[x for x in content if x['type']=='math']
            if len(maths)!=len(read['spans']):raise ValueError('数学遗漏/额外出现: '+block['id'])
            recorded=[m for m in entry.get('math',[]) if m['owner'].get('cell')==cell_id]
            if len(recorded)!=len(maths):raise ValueError('数学输出定位不完整')
            for item,span,where in zip(maths,read['spans'],recorded):
                value,label=read_expression(span,item['label'] is not None)
                label_range=None
                if item['kind']=='inline' and item['label'] is not None:
                    label,label_range=read_inline_label(text,span,item['label']['text'])
                if value!=item['tex'] or span.kind!=item['kind'] or label!=(item['label'] or {}).get('text'):
                    raise ValueError('确认数学内容/类型/式号损伤: '+item['id'])
                expected={'id':item['id'],'owner':item['owner'],'slot':item['slot'],
                          'md_start':span.start,'md_end':span.end}
                if label_range is not None:expected['label_range']=label_range
                if where!=expected:raise ValueError('数学身份/精确区间/所属错绑: '+item['id'])
                all_maths.append(item)
                member_blocks[item['id']]=block_index
            # 按实际数学跨度切开文字，保持前后连接，不按首次表达式反查。
            cursor=read.get('content_start',read['start']);pieces=[];leaf_pieces=[]
            for span in read['spans']:
                fragment=text[cursor:span.start]
                if cell_id is not None:fragment=fragment.replace(r'\|','|')
                leaves,_,reading=inline_reading_facts(fragment,labels=True)
                pieces.append(reading);leaf_pieces.append(leaves);cursor=span.end
            fragment=text[cursor:read.get('content_end',read['end'])]
            if cell_id is not None:fragment=fragment.replace(r'\|','|')
            leaves,_,reading=inline_reading_facts(fragment,labels=True)
            pieces.append(reading);leaf_pieces.append(leaves)
            expected_pieces=[''];expected_leaves=[[]]
            previous_line=None
            for item in content:
                origin=item['origin'];first=origin['fragments'][0];last=origin['fragments'][-1]
                current_line=(origin['page'],first['block'],first['line'])
                if previous_line is not None and previous_line!=current_line:expected_pieces[-1]+='\n'
                previous_line=(origin['page'],last['block'],last['line'])
                if item['type']!='math':
                    value=original_text(doc,item['origin'])
                    if item['type']!='footnote_ref':expected_pieces[-1]+=value
                    else:expected_leaves[-1].append(('footnote_ref',item['label']))
                    if item['type']=='code':expected_leaves[-1].append(('code',value))
                    if item['type']=='link':expected_leaves[-1].append(('link',MarkdownIt('commonmark').normalizeLink(item['target']),norm_words(value)))
                else:
                    expected_pieces.append(' '+item['label']['text'] if item['kind']=='inline' and item['label'] is not None else '')
                    expected_leaves.append([])
            if leaf_pieces!=expected_leaves:raise ValueError('原页代码/链接实际叶子角色、内容或位置损伤: '+block['id'])
            if [norm_words(x) for x in pieces]!=[norm_words(x) for x in expected_pieces]:
                raise ValueError('数学前后正文边界/位置损伤: '+block['id'])
        read=whole_read
    if len(scan.spans)!=len(all_maths):raise ValueError('未消费额外数学')
    _,source_hosts=math_hosts(text,actual,all_maths,scan.spans)
    chosen_blocks=actual;chosen_spans=scan.spans
    if source_range is not None:
        ranges=source_range if isinstance(source_range[0],(tuple,list)) else [source_range]
        if not all(0<=a<=z<=len(text) for a,z in ranges):
            raise ValueError('包源字符范围越界')
        for first,last in footnote_dependencies(checklist,mapping):
            if any(first<z and last>a for a,z in ranges) and not any(a<=first and last<=z for a,z in ranges):
                raise ValueError('包范围切断脚注定义/子块及引用依赖')
        chosen_blocks=[block for block in actual if any(a<=block['start'] and block['end']<=z for a,z in ranges)]
        chosen_spans=[span for span in scan.spans if any(a<=span.start and span.end<=z for a,z in ranges)]
        selected_algorithms=[]
        for first,last in algorithms:
            start,end=actual[first]['start'],actual[last-1]['end']
            if any(start<z and end>a for a,z in ranges):
                if not any(a<=start and end<=z for a,z in ranges):raise ValueError('包范围切断算法标题及必要子块所属')
                selected_algorithms.append((first,last))
        algorithms=selected_algorithms
        for block in blocks:
            if ('cells' not in block and not any(block.get(resource) is not None for resource in ('figure','table'))
                    and not any(item.get('type') in ('math','code','link') for item in block.get('content',[]))):
                continue
            host=maps[block['id']]
            for resource in ('figure','table'):
                if block.get(resource) is not None:
                    resource_index=next(i for i,b in enumerate(blocks) if b['id']==block[resource])
                    asset=actual[resource_index]
                    if any(host['md_start']<z and host['md_end']>a
                           and not (a<=asset['start'] and asset['end']<=z) for a,z in ranges):
                        raise ValueError('包范围遗漏题注所需资源所属: '+block['id'])
            if any(host['md_start']<z and host['md_end']>a
                   and not (a<=host['md_start'] and host['md_end']<=z) for a,z in ranges):
                raise ValueError('包范围切断数学所属块及前后正文: '+block['id'])
        locations={m['id']:m for b in mapping for m in b.get('math',[])}
        for item in all_maths:
            location=locations[item['id']]
            if any(location['md_start']<z and location['md_end']>a and not (a<=location['md_start'] and location['md_end']<=z) for a,z in ranges):
                raise ValueError('包范围切断确认数学')
        all_maths=[item for item in all_maths if any(a<=locations[item['id']]['md_start'] and locations[item['id']]['md_end']<=z for a,z in ranges)]
        chosen={item['id'] for item in all_maths}
        for members in groups(checklist).values():
            if chosen.intersection(members) and not set(members).issubset(chosen):
                raise ValueError('包范围切断必要公式组，成员须逐次完整核验')
    if translation is not None:
        translation,_=approved_extra_view(translation,context(checklist),approved_extra_math)
        target_blocks,target_scan=markdown_blocks(translation,context(checklist))
        target_algorithms=[i for i,b in enumerate(target_blocks) if b['role']=='algorithm']
        if len(target_algorithms)!=len(algorithms):raise ValueError('译文算法身份遗漏/额外或标记损伤')
        for (first,last),index in zip(algorithms,target_algorithms):
            source_shape=[(b['role'],b.get('list_path')) for b in actual[first:last]]
            target_shape=[(b['role'],b.get('list_path')) for b in target_blocks[index:index+last-first]]
            if actual[first]['algorithm_label']!=target_blocks[index]['algorithm_label'] or source_shape!=target_shape:
                raise ValueError('译文算法编号/实际子块顺序或角色损伤')
        if target_scan.issues or len(target_scan.spans)!=len(all_maths):
            raise ValueError('译文数学遗漏/额外或定界未闭合')
        for item,span in zip(all_maths,target_scan.spans):
            tex,label=read_expression(span,item['label'] is not None)
            if item['kind']=='inline' and item['label'] is not None:
                label,_=read_inline_label(translation,span,item['label']['text'])
            if span.kind!=item['kind'] or tex!=item['tex'] or label!=(item['label'] or {}).get('text'):
                raise ValueError('译文数学内容/类型/式号损伤: '+item['id'])
        target_member_blocks,target_hosts=math_hosts(translation,target_blocks,all_maths,target_scan.spans)
        if leaf_hosts(chosen_blocks,chosen_spans)!=leaf_hosts(target_blocks,target_scan.spans):
            raise ValueError('译文代码/链接实际叶子宿主、正文边界、内容、目标或数学连接位置损伤')
        for item in all_maths:
            if source_hosts[item['id']]!=target_hosts[item['id']]:
                raise ValueError('译文数学实际角色/宿主分区或正文边界损伤: '+item['id'])
        source_locations,_=math_hosts(text,actual,[item for _,_,item in occurrences(checklist)],scan.spans)
        for (first,last),index in zip(algorithms,target_algorithms):
            for item in all_maths:
                if first<=source_locations[item['id']]<last and source_locations[item['id']]-first!=target_member_blocks[item['id']]-index:
                    raise ValueError('译文数学算法实际所属/子块位置损伤: '+item['id'])
        for members in groups(checklist).values():
            selected=[i for i in members if i in target_member_blocks]
            if not selected:continue
            src=[member_blocks[i]-member_blocks[selected[0]] for i in selected]
            dst=[target_member_blocks[i]-target_member_blocks[selected[0]] for i in selected]
            if src!=dst:
                raise ValueError('实际公式组成员关系/间隔损伤')
    return all_maths


def source_view(entry, root, source_path):
    """当前已准入pdf-source条目的只读视图，不另存权威事实。"""
    from pathlib import Path
    root=Path(root)
    path=root/entry['checklist']
    checklist=json.loads(path.read_text())
    text=read_document(source_path,exact=True)
    if not enabled(checklist,text):return None
    ref=metadata(text).get('pdf_checklist')
    if not ref or (Path(source_path).parent/json.loads(ref)).resolve()!=path.resolve():
        raise ValueError('源清单引用与project-context的pdf-source声明不符')
    mapping=json.loads((root/entry['block_map']).read_text())['blocks']
    return {'checklist':checklist,'mapping':mapping,'text':text,'pdf':str(root/entry['pdf'])}


def check_fragment(view,start,end,target,approved_extra_math=()):
    with load_fitz().open(view['pdf']) as doc:
        return verify(view['checklist'],doc,view['text'],view['mapping'],target,(start,end),approved_extra_math)


def translation_view(source_path, project_context, *, with_context=False):
    """从正式全源或机械源包准入；包头仅定位，不授予自身资格。"""
    from pathlib import Path
    import recover_work_packages as rwp
    text=read_document(source_path)
    meta=metadata(text)
    def result(view, span, current=None):
        return (view, span, current) if with_context else (view, span)
    if meta.get('pdf_formula_contract') and not project_context:
        raise ValueError('PDF确认数学核验需要显式 --project-context，不降级')
    if not project_context:
        return result(None,None)
    full_source=meta.get('source_file',source_path).strip('"')
    current=rwp.load_project_context(project_context,full_source)
    view=current.get('_pdf_view')
    table_view=current.get('_table_view')
    if view is None:
        if meta.get('pdf_formula_contract'):
            raise ValueError('声明确认数学但项目上下文不是对应PDF来源')
        if table_view is None:
            return result(None,None,current)
    if view is not None and meta.get('pdf_formula_contract')!=CONTRACT:
        raise ValueError('源/包缺少当前数学合同，不降级')
    source_text=(view if view is not None else table_view)['text']
    if 'source_file' in meta:
        if (view is not None or meta.get('project_context')) and (
                not meta.get('project_context') or Path(json.loads(meta['project_context'])).resolve()!=Path(project_context).resolve()):
            raise ValueError('包项目来源声明冲突')
        a,z=int(meta['source_char_start']),int(meta['source_char_end'])
        _,body=rwp._frontmatter(source_path)
        if not (0 <= a < z <= len(source_text)) or body!=source_text[a:z]:
            raise ValueError('实际源包与当前全源字符范围不符')
        if meta.get('fragment_digest')!=hashlib.sha256(body.encode()).hexdigest():
            raise ValueError('源包摘要未绑定实际正文')
        return result(view,(a,z),current)
    return result(view,(0,len(source_text)),current)


def policy(view,start,end):
    items=check_fragment(view,start,end,None)
    actual,scan=markdown_blocks(view['text'],context(view['checklist']))
    _,hosts=math_hosts(view['text'],actual,[item for _,_,item in occurrences(view['checklist'])],scan.spans)
    group_order={name:i for i,name in enumerate(dict.fromkeys(
        item['group'] for item in items if item.get('group') is not None))}
    blocks={block['id']:block for block in view['checklist']['blocks']}
    selected={b['id'] for b in view['mapping'] if start<=b['md_start'] and b['md_end']<=end}
    local=[b for b in sorted(blocks.values(),key=lambda b:b['order']) if b['id'] in selected]
    notes=[{'label':b['footnote_label'],
            'roles':[part['type'] for part in local if part['id']==b['id'] or part.get('footnote')==b['id']],
            'references':[[index,slot] for index,part in enumerate(local) for _,content in contents(part)
                          for slot,item in enumerate(content) if item['type']=='footnote_ref' and item['label']==b['footnote_label']]}
           for b in local if b['type']=='footnote_def']
    tables=[];table_conversions={};cell_positions={}
    for block in local:
        if 'cells' not in block:continue
        cells=sorted(block['cells'],key=lambda c:(c['row'],c['column']))
        aliases={cell['id']:index for index,cell in enumerate(cells)}
        conversion={**block['table_conversion'],'cells':[
            {**cell,'source':aliases[cell['source']]} for cell in block['table_conversion']['cells']]}
        table_conversions[block['id']]=conversion
        projected=[]
        for cell in cells:
            cell_positions[(block['id'],cell['id'])]=[cell['row'],cell['column']]
            content=[]
            for item in cell['content']:
                fact={'type':item['type'],'original':item['origin']['text']}
                if item['type']=='math':
                    fact.update(kind=item['kind'],tex=item['tex'],label=(item['label'] or {}).get('text'),
                                group=group_order.get(item.get('group')),conversion=item['conversion'])
                for key in ('target','label') if item['type']!='math' else ():
                    if key in item:fact[key]=item[key]
                content.append(fact)
            projected.append({key:cell[key] for key in ('row','column','rowspan','colspan','header')} | {'content':content})
        tables.append({'conversion':conversion,'cells':projected})
    return {'pdf_formula_contract':CONTRACT,'tables':tables,'footnotes':notes,'math':[{'kind':i['kind'],'tex':i['tex'],
             'label':(i['label'] or {}).get('text'),'role':i['owner']['role'],
             'group':group_order.get(i.get('group')),
             'host':{'level':hosts[i['id']][1],
                     'caption_label':list(hosts[i['id']][2]) if hosts[i['id']][2] else None,
                     'image_distance':hosts[i['id']][3],
                     'table_distance':hosts[i['id']][8],
                     'footnote_label':hosts[i['id']][9],
                     'list_path':[list(part) for part in hosts[i['id']][6]] if hosts[i['id']][6] else None,
                     'conversion':blocks[i['owner']['block']].get('list_conversion'),
                     'cell':cell_positions.get((i['owner']['block'],i['owner'].get('cell'))),
                     'table_conversion':table_conversions.get(i['owner']['block'])},
             'conversion':i['conversion']} for i in items]}
