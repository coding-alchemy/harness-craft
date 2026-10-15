#!/usr/bin/env python3
"""显式有限 PTX/ISA 候选；不裁决、不启动翻译核验。"""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from _verification import scan_code_fences


def candidates(text, preset):
    result = []
    # 只读取明确围栏代码。ISA 支持常见 ARM/RISC-V 指令语句形态，
    # 不解释伪指令、宏、标签、多行指令或架构语义。
    instructions = re.compile(r'(?:^|;)\s*(?:@!?%[\w.]+\s+)?'
                              r'([A-Za-z][\w]*(?:\.[A-Za-z][\w]*)*)\s+[^;\n]+(?=;|$)')
    isa_ops = {'add', 'sub', 'mov', 'ldr', 'str', 'ld', 'sd', 'lw', 'sw',
               'addi', 'mul', 'div', 'and', 'or', 'xor', 'cmp', 'beq', 'bne', 'ret'}
    for fence in scan_code_fences(text).blocks:
        # scan_code_fences 的真实行范围与原始正文是独立定位依据。
        for offset, line in enumerate(fence.body.splitlines()):
            for ins in instructions.finditer(line):
                opcode = ins.group(1)
                if preset == 'isa' and opcode.lower() not in isa_ops:
                    continue
                if preset == 'ptx' and (opcode != opcode.lower() or
                        opcode.split('.')[0] not in {'add', 'sub', 'mul', 'mad',
                            'fma', 'div', 'mov', 'cvt', 'ld', 'st', 'atom',
                            'red', 'setp', 'selp', 'and', 'or', 'xor', 'shl', 'shr'}):
                    continue
                segment = line[ins.start(1):ins.end()]
                matches = [(opcode.split('.')[0], 'instruction', ins.start(1))]
                matches += [(m.group(), 'modifier', ins.start(1)+m.start())
                            for m in re.finditer(r'\.[A-Za-z][A-Za-z0-9_]*', opcode)]
                matches += [(m.group(), 'register', ins.start(1)+m.start())
                            for m in re.finditer(r'%[A-Za-z][A-Za-z0-9_]*', segment)]
                for token, form, column in matches:
                    result.append({'token': token, 'form': form,
                                   'line': fence.start_line + 1 + offset,
                                   'column': column + 1, 'snippet': line,
                                   'decision': 'pending'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--preset', required=True, choices=['ptx', 'isa'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, output = Path(args.source).resolve(), Path(args.output).resolve()
    if source == output:
        parser.error('输出不得覆盖只读源')
    try:
        old = output.read_bytes() if output.exists() else None
        if old is not None:
            previous = json.loads(old)
            if not isinstance(previous, dict) or previous.get('source') != str(source) or not isinstance(previous.get('candidates'), list):
                raise ValueError('输出不是同一来源的候选产物，不能覆盖项目文件或有效记录')
        raw = source.read_bytes()
        text = raw.decode('utf-8')
        result = {'source': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                  'preset': args.preset,
                  'support': '仅明确围栏内的单行指令语句、点修饰符及百分号寄存器；不覆盖宏、标签、多行指令和架构语义。候选须主 Agent 逐项裁决，不能直接授予检查资格。',
                  'candidates': candidates(text, args.preset)}
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False, indent=2)
        try:
            if source.read_bytes() != raw:
                raise ValueError('源在发布前变化，候选依据已过期')
            if (output.read_bytes() if output.exists() else None) != old:
                raise ValueError('候选输出在发布前变化，保留当前内容')
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
