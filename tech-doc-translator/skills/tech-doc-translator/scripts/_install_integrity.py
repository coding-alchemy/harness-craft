"""已安装副本与安装清单的比对：只提示，不阻断。

安装脚本在安装目录写 .install-manifest.json（受管文件的 sha256）。解析、合章、
核验等入口经 _verification 导入时调用一次 warn_if_modified()；不一致时在 stderr
列出被改或缺失的文件，退出码和结果不变。仓库检出没有清单，不比对。
"""
import hashlib
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_checked = False


def warn_if_modified():
    global _checked
    if _checked:
        return
    _checked = True
    path = os.path.join(_ROOT, '.install-manifest.json')
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding='utf-8') as handle:
            entries = sorted(json.load(handle)['files'].items())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print('警告: 安装清单读不出: %s' % path, file=sys.stderr)
        return
    changed = []
    for rel, digest in entries:
        try:
            with open(os.path.join(_ROOT, rel), 'rb') as handle:
                actual = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            changed.append(rel + '（缺失）')
            continue
        if actual != digest:
            changed.append(rel)
    if changed:
        print('警告: 已安装的 tech-doc-translator 与安装清单不符（可能被就地修改），'
              '结果照常产出: %s。从仓库重装可恢复。' % '、'.join(changed), file=sys.stderr)
