#!/usr/bin/env python3
"""Start the local web statistics UI; explicit start by the user, loopback only."""
import sys

sys.dont_write_bytecode = True

import argparse

from token_audit import operations, webapp


def main():
    parser = argparse.ArgumentParser(description='启动本地网页统计入口；仅绑定本机回环地址，不自动打开浏览器。')
    parser.add_argument('--codex-source', action='append', help='Codex JSONL 文件或目录；可重复，默认 CODEX_HOME/sessions')
    parser.add_argument('--zcode-database', help='只读 ZCode 遥测数据库；默认 ~/.zcode/cli/db/db.sqlite（存在时）')
    parser.add_argument('--zcode-source', action='append', help='ZCode rollout/log 文件或目录；显式给出时该端以 rollout 计量')
    parser.add_argument('--context-harness', choices=['codex', 'zcode'], help='启动链提供的可信会话所属 Harness')
    parser.add_argument('--context-session', help='启动链提供的可信会话身份；不来自最新记录或目录猜测')
    parser.add_argument('--context-request-id', help='启动链转交的本次统计请求 ID；页面点击对应动作后才执行')
    args = parser.parse_args()
    try:
        sources = {'codex': operations.default_descriptor('codex', args.codex_source, None),
                   'zcode': operations.default_descriptor('zcode', args.zcode_source, args.zcode_database)}
    except (ValueError, OSError) as exc:
        print('启动失败：' + str(exc), file=sys.stderr)
        return 2
    context = {}
    if args.context_session:
        if not args.context_harness:
            print('启动失败：--context-session 需要同时提供 --context-harness', file=sys.stderr)
            return 2
        context = {'harness': args.context_harness, 'session': args.context_session}
        if args.context_request_id:
            context['request_id'] = args.context_request_id
    return webapp.serve(sources, context)


if __name__ == '__main__':
    sys.exit(main())
