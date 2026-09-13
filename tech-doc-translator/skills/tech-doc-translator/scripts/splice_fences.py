#!/usr/bin/env python3
"""把译文草稿中独占一行的 ⟦CODE⟧ 占位符，按文档顺序替换为源文对应代码围栏（逐字节保真）。

用法：
    python3 splice_fences.py draft.md source.md out.md

占位行必须独占一行且内容恰为 ⟦CODE⟧。替换后按共享围栏扫描器校验：
- 围栏数量与源文一致；
- 每个围栏的开启行、正文、关闭行与源文逐一相等。
"""
import sys

from _verification import scan_code_fences


def extract_fences(path):
    scan = scan_code_fences(open(path, encoding='utf-8').read())
    if not scan.balanced:
        raise AssertionError('%s: 围栏不配对（第 %d 行开启的代码块未闭合）'
                             % (path, scan.unclosed_line))
    return scan.blocks


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
            out.append(f.opener)
            out.extend(f.body.split('\n'))
            out.append(f.closer)
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
        if (a.opener, a.body, a.closer) != (b.opener, b.body, b.closer):
            raise AssertionError('围栏 #%d 不一致' % k)

    print('OK: %s 拼接 %d 个围栏，逐字节一致' % (out_p, len(fences)))


if __name__ == '__main__':
    main()
