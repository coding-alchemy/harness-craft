#!/usr/bin/env python3
"""把译文草稿中独占一行的 ⟦CODE⟧ 占位符，按文档顺序替换为源文对应代码围栏（逐字节保真）。

用法：
    python3 splice_fences.py draft.md source.md out.md

占位行必须独占一行且内容恰为 ⟦CODE⟧。替换后校验：
- 围栏数量与源文一致；
- 每个围栏的开启行、正文、关闭行与源文逐一相等。
"""
import sys


def extract_fences(path):
    lines = open(path, encoding='utf-8').read().split('\n')
    fences, cur, infence = [], None, False
    for ln in lines:
        if ln.strip().startswith('```'):
            if not infence:
                cur = {'open': ln, 'body': []}
                infence = True
            else:
                cur['close'] = ln
                fences.append(cur)
                cur, infence = None, False
            continue
        if infence:
            cur['body'].append(ln)
    if infence:
        raise AssertionError('%s: 围栏不配对' % path)
    return fences


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    draft_p, src_p, out_p = sys.argv[1:4]

    fences = extract_fences(src_p)
    out, i = [], 0
    for ln in open(draft_p, encoding='utf-8').read().split('\n'):
        if ln.strip() == '⟦CODE⟧':
            if i >= len(fences):
                raise AssertionError('占位符数量超过源文围栏数')
            f = fences[i]
            out.append(f['open'])
            out.extend(f['body'])
            out.append(f['close'])
            i += 1
        else:
            out.append(ln)
    if i != len(fences):
        raise AssertionError('占位数 %d != 源围栏数 %d' % (i, len(fences)))

    open(out_p, 'w', encoding='utf-8').write('\n'.join(out))

    # 复核：输出文件的围栏内容与源文逐一比对
    got = extract_fences(out_p)
    if len(got) != len(fences):
        raise AssertionError('输出围栏数不符')
    for k, (a, b) in enumerate(zip(fences, got)):
        if (a['open'], a['body'], a['close']) != (b['open'], b['body'], b['close']):
            raise AssertionError('围栏 #%d 不一致' % k)

    print('OK: %s 拼接 %d 个围栏，逐字节一致' % (out_p, len(fences)))


if __name__ == '__main__':
    main()
