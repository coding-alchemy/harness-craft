"""原生 PDF 测试输入与确认记录准备；预期和损伤断言留在各测试中。"""
import hashlib
import json
import sys
import unittest

from translator_test_support import SCRIPTS

try:
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf
        HAVE_PYMUPDF = True
    except ImportError:
        HAVE_PYMUPDF = False

if not HAVE_PYMUPDF:
    raise unittest.SkipTest("PyMuPDF 不可用，整组 PDF 源图形测试跳过")


CHART_A = (40, 40, 220, 190)


def draw_chart(page, labels, offset=0):
    """画一个无大面积外框的小矢量图（柱 + 轴 + 标签 + 图例）。"""
    base = pymupdf.Point(60, 160)
    for i, label in enumerate(labels[:2]):
        rect = pymupdf.Rect(base.x + i * 45, base.y - 60 - i * 20 + offset,
                            base.x + i * 45 + 30, base.y + offset)
        page.draw_rect(rect, fill=(0.7, 0.7, 0.9))
        page.insert_text((rect.x0 + 8, base.y + 12 + offset), label,
                         fontsize=8)
    page.draw_line(pymupdf.Point(50, base.y + offset),
                   pymupdf.Point(200, base.y + offset), color=(0,))
    page.draw_line(pymupdf.Point(50, 70 + offset),
                   pymupdf.Point(50, base.y + offset), color=(0,))
    page.insert_text((70, 60 + offset), labels[2], fontsize=8)  # 图例
    page.insert_text((120, 60 + offset), "Normalized Runtime", fontsize=8)


def draw_table(page):
    """同页表格边框与单元格（不属于任何图）。"""
    x0, y0 = 260, 60
    for r in range(4):
        for c in range(3):
            rect = pymupdf.Rect(x0 + c * 60, y0 + r * 20,
                                x0 + (c + 1) * 60, y0 + (r + 1) * 20)
            page.draw_rect(rect, color=(0,))
            page.insert_text((rect.x0 + 4, rect.y1 - 6),
                             "H%d%d" % (r, c), fontsize=8)


def fact_digest(item):
    fact = {key: value for key, value in item.items() if key != 'confirmation'}
    return hashlib.sha256(json.dumps(fact, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def original(page, text, occurrence=0):
    """测试输入的原生字形定位；不调用物化器或核验器造预期。"""
    for bi, block in enumerate(page.get_text('rawdict')['blocks']):
        for li, line in enumerate(block.get('lines', [])):
            for si, span in enumerate(line['spans']):
                chars = span['chars']
                value = ''.join(c['c'] for c in chars)
                if text not in value:
                    continue
                if occurrence:
                    occurrence-=1
                    continue
                start = value.index(text)
                bounds = [c['bbox'] for c in chars[start:start+len(text)]]
                return {'page': page.number + 1,
                        'rect': [min(r[0] for r in bounds), min(r[1] for r in bounds),
                                 max(r[2] for r in bounds), max(r[3] for r in bounds)],
                        'text': text,
                        'extraction': {'pymupdf': pymupdf.VersionBind, 'view': 'rawdict'},
                        'fragments': [{'block': bi, 'line': li, 'span': si,
                                       'start': start, 'end': start+len(text), 'text': text}]}
    raise AssertionError('fixture original not found: ' + text)


def pdf_project_context(root):
    """当前CLI来源裁决输入；仅计算身份绑定，不造数学预期。"""
    sys.path.insert(0,str(SCRIPTS))
    import verify_delivery as delivery
    record={'version':1,'mode':'translation','delivery_root':str(root),'inputs':['translation.md'],
            'outputs':[],'files':{'paper.pdf':'pdf','translation.md':'chapter'},
            'sources':[{'family':'pdf-source','source_version':'explicit structural fixture',
                        'pdf':'paper.pdf','checklist':'source/adjudication_checklist.json',
                        'source_markdown':'source/source.md','layout_snapshot':'source/snapshots_layout.txt',
                        'reading_snapshot':'source/snapshots_reading.txt','covers':['translation.md']}],
            'checks':[{'tool':'verify_pdf_source','args':['paper.pdf','--checklist',
                       'source/adjudication_checklist.json','--source-md','source/source.md']}],'reviews':[]}
    (root/'record.json').write_text(json.dumps(record))
    problems=[];entries=delivery.check_source_chains(str(root),record,problems,source_only=True)
    if problems:raise AssertionError(problems)
    binding={k:entries[0][k] for k in ('parsed_sha256','source_version','snapshots')}
    binding['pdf_source']=delivery._source_identity(entries[0],lambda rel:str(root/rel))
    context={'project_root':str(root),'source_record':'record.json','source_scope':'all',
             'source_review':{'scope':'all','binding':binding,'basis':'explicit original fixture facts'},
             'instructions':[],'rules':[],'glossary':[],'output_contract':[],'examples':[],
             'return_contract':'fixture','rule_conflicts':[],'skill_dir':str(SCRIPTS.parent),
             'python':sys.executable,'check_args':[]}
    path=root/'context.json';path.write_text(json.dumps(context));return path
