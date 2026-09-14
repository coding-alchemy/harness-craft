#!/usr/bin/env python3
"""Install a self-contained Skill without overwriting an existing installation."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description='安装 agent-token-audit；已存在且内容不同的目标拒绝覆盖')
    parser.add_argument('--harness',choices=['codex','zcode'],default='codex')
    parser.add_argument('--target',help='完整 Skill 目标目录；默认所选 Harness 的个人 skills/agent-token-audit')
    args=parser.parse_args()
    source=Path(__file__).resolve().parent/'skills/agent-token-audit'
    base=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))) if args.harness=='codex' else Path.home()/'.zcode'
    target=Path(args.target).expanduser().absolute() if args.target else base/'skills/agent-token-audit'
    files={}
    try:
        for path in source.rglob('*'):
            if '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):
                continue
            if path.is_symlink():
                raise ValueError('Skill 来源包含符号链接')
            if path.is_file():
                files[path.relative_to(source)]=path.read_bytes()
        if not files or Path('SKILL.md') not in files:
            raise ValueError('Skill 来源不完整')
        if target.is_symlink():
            raise ValueError('目标是符号链接，未写入')
        if target.exists():
            if not target.is_dir() or any(not (target/rel).is_file() or (target/rel).is_symlink() or (target/rel).read_bytes()!=content for rel,content in files.items()):
                raise ValueError('目标已有不同内容；请选择新目录，不自动覆盖')
            print('安装内容已一致：'+str(target));return 0
        target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.token-audit-install-',dir=target.parent) as tmp:
            staged=Path(tmp)/'agent-token-audit';staged.mkdir()
            for relative,content in files.items():
                dest=staged/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content)
            if target.exists():
                raise ValueError('目标在安装过程中已出现；未覆盖')
            shutil.move(str(staged),str(target))
        print('Skill 已安装：'+str(target));return 0
    except (OSError,ValueError) as exc:
        print('安装失败：'+str(exc),file=sys.stderr);return 1


if __name__=='__main__':
    sys.exit(main())
