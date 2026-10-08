"""Loopback web entry: request-safety, transport and bundled page resources only.

Business decisions stay in operations; this layer fixes the per-start credential,
the Host/Origin checks, the static whitelist and the source restriction that the
adapters enforce before reading.
"""
import http.server
import json
import secrets
from pathlib import Path
from . import operations
from .core import now
from .formats import render, validate_report

VIEWER = Path(__file__).resolve().parents[2] / 'viewer'
STATIC = {
    '/': ('web.html', 'text/html; charset=utf-8'),
    '/web.js': ('web.js', 'text/javascript; charset=utf-8'),
    '/shared.js': ('shared.js', 'text/javascript; charset=utf-8'),
    '/shared.css': ('shared.css', 'text/css; charset=utf-8'),
    '/lossless-json.umd.js': ('lossless-json.umd.js', 'text/javascript; charset=utf-8'),
    '/lossless-json.LICENSE.md': ('lossless-json.LICENSE.md', 'text/plain; charset=utf-8'),
}
TOKEN_HEADER = 'X-Token-Audit-Token'


class SourceGuard:
    """Reject resolved paths outside the roots, files and database sidecars fixed at start."""

    def __init__(self, roots=(), files=(), sidecars=()):
        self.roots = [Path(r).resolve() for r in roots]
        self.files = {Path(f).resolve() for f in files}
        # Only SQLite's deterministic -wal/-shm siblings of each declared database count as
        # sidecars; a same-prefix name such as allowed.sqlite-extra.sqlite is a different
        # database and must not pass on a string-prefix match.
        self.sidecars = set()
        for database in sidecars:
            base = Path(database).resolve()
            self.sidecars |= {base, Path(str(base) + '-wal'), Path(str(base) + '-shm')}

    def __call__(self, path):
        real = Path(path).resolve()
        if real in self.files or real in self.sidecars:
            return
        for root in self.roots:
            if real == root or root in real.parents:
                return
        raise ValueError('来源路径越界，已拒绝读取：' + str(path) + '；请以对应本地来源重新启动本服务')


def guard_for(descriptors):
    """Declare every path each descriptor may read, including ZCode sidecars and neighbours."""
    roots, files, sidecars = [], set(), []
    for descriptor in descriptors:
        for raw in descriptor['paths']:
            path = Path(raw).expanduser().resolve()
            if descriptor['kind'] == 'jsonl':
                if path.is_dir():
                    roots.append(path)
                else:
                    files.add(path)
            else:
                files.add(path)
                sidecars.append(path)
                base = path.parent.parent if path.parent.name == 'db' else path.parent
                for neighbour in ('log', 'rollout'):
                    directory = base / neighbour
                    if directory.is_dir():
                        roots.append(directory)
    return SourceGuard(roots, files, sidecars)


class WebApp:
    def __init__(self, sources, context=None):
        self.credential = secrets.token_urlsafe(32)
        self.sources = sources
        self.guard = guard_for(sources.values())
        self.context = context or {}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    app = None

    def log_message(self, fmt, *args):
        pass  # No request logging: keep the terminal output to the startup banner only.

    def _reject(self, status, reason):
        body = json.dumps({'ok': False, 'error': reason}, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get('Host') or '').lower()
        port = self.server.server_address[1]
        return host in (f'127.0.0.1:{port}', f'localhost:{port}', f'[127.0.0.1]:{port}', f'[localhost]:{port}')

    def _origin_ok(self):
        origin = self.headers.get('Origin')
        if not origin:
            return True  # Non-browser callers still pass Host plus the credential header.
        port = self.server.server_address[1]
        return origin.lower() in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

    def _check_transport(self, need_token):
        if not self._host_ok():
            self._reject(403, 'Host 不属于本服务')
            return False
        if not self._origin_ok():
            self._reject(403, '跨域来源被拒绝')
            return False
        if need_token and self.headers.get(TOKEN_HEADER) != self.app.credential:
            self._reject(403, '凭据缺失或不匹配；请使用启动链接打开本页')
            return False
        return True

    def do_GET(self):
        if not self._check_transport('/api/' in self.path):
            return
        path = self.path.split('?', 1)[0]
        if path == '/api/capabilities':
            payload = {'ok': True, 'action': 'capabilities',
                       'sources': {harness: descriptor for harness, descriptor in self.app.sources.items()},
                       'context': self.app.context}
            self._send_json(payload)
            return
        if path not in STATIC:
            self._reject(404, '资源不在随包白名单内')
            return
        name, content_type = STATIC[path]
        try:
            content = (VIEWER / name).read_bytes()
        except OSError:
            self._reject(404, '资源不可用')
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        self.close_connection = True
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        entry = now()  # Fixed at request-entry, before body parsing and any source reading.
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        # Drain the body before any rejection so a kept-alive connection never carries
        # leftover request bytes into the next exchange.
        body = self.rfile.read(length) if length > 0 else b''
        if not self._check_transport(True):
            return
        if self.path != '/api/action':
            self._reject(404, '未知操作入口')
            return
        try:
            request = json.loads(body.decode('utf-8')) if body else {}
            if not isinstance(request, dict):
                raise ValueError('请求必须是 JSON 对象')
        except (ValueError, UnicodeError):
            self._reject(400, '请求体不是有效的 JSON 对象')
            return
        action = request.get('action')
        try:
            outcome = self._run_action(action, request, entry)
        except ValueError as exc:
            self._send_json({'ok': False, 'action': action, 'seq': request.get('seq'), 'error': str(exc)}, status=400)
            return
        except OSError as exc:
            self._send_json({'ok': False, 'action': action, 'seq': request.get('seq'), 'error': '读取失败：' + str(exc)}, status=500)
            return
        self._send_json(outcome)

    def _run_action(self, action, request, entry):
        saved_obj = None
        if action in ('recompute', 'export'):
            # The saved report text is the sole scope authority for these actions; its
            # contract problems must surface before any harness or source checks.
            saved_obj = validate_report(self._decoded_report(request.get('report_text')))
        harness = request.get('harness')
        if saved_obj is not None:
            saved_harness = saved_obj.get('harness') if isinstance(saved_obj, dict) else None
            if harness is not None and harness != saved_harness:
                raise ValueError('原范围重算不能切换 Harness 或会话；请新建查询')
            harness = saved_harness
        if action != 'export' and harness not in self.app.sources:
            raise ValueError('未知或本次启动未配置的 Harness：' + str(harness))
        context_session = self.app.context.get('session') if self.app.context.get('harness') == harness else None
        query = operations.Query(operation=action if action != 'export' else 'report',
                                 started=entry, started_source='web_request_start',
                                 harness=harness, descriptor=self.app.sources.get(harness),
                                 guard=self.app.guard, session=request.get('session'),
                                 saved=saved_obj if action == 'recompute' else None)
        if request.get('use_context'):
            # The startup chain declared this identity; operations re-verifies the unique source match.
            if not context_session:
                raise ValueError('本次启动未提供该 Harness 的可信会话关联')
            query.use_current = True
            query.current_identities = {harness: context_session}
        if action == 'sessions':
            pass
        elif action == 'turns':
            if not request.get('session'):
                raise ValueError('浏览轮次需要明确会话')
        elif action == 'requests':
            if not request.get('session'):
                raise ValueError('浏览请求候选需要明确会话')
        elif action == 'report':
            query.main_only = bool(request.get('main_only'))
            query.turns = self._turn_set(request.get('turns'))
            for field, name in (('from', '时间下界'), ('to', '显式截止点')):
                value = request.get(field)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(name + '必须是带时区的时间字符串')
                    setattr(query, 'since' if field == 'from' else 'to', value)
            request_id = request.get('request_id')
            if request_id is not None:
                if not isinstance(request_id, str) or not request_id:
                    raise ValueError('请求 ID 必须是非空字符串')
                query.request_id = request_id
        elif action == 'overview':
            query.main_only = bool(request.get('main_only'))
            sessions = request.get('sessions')
            if sessions is not None:
                if not isinstance(sessions, list) or not sessions or not all(isinstance(s, str) and s for s in sessions):
                    raise ValueError('会话集合必须是非空字符串数组（提交完整集合）')
                query.sessions = sessions
            tz = request.get('tz')
            if tz is not None:
                if not isinstance(tz, str) or not tz:
                    raise ValueError('显示时区必须是非空字符串')
                query.tz = tz
            for field, name in (('from', '时间下界'), ('to', '显式截止点')):
                value = request.get(field)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(name + '必须是带时区的时间字符串')
                    setattr(query, 'since' if field == 'from' else 'to', value)
        elif action == 'recompute':
            if request.get('update'):
                query.update = True
                # A supplied list is the full new set, an
                # explicit null clears the saved constraint (whole session / no lower bound),
                # and an absent field keeps it. The CLI never constructs CLEAR.
                if 'turns' in request:
                    query.turns = operations.CLEAR if request['turns'] is None else self._turn_set(request['turns'])
                if 'sessions' in request:
                    value = request['sessions']
                    if value is None:
                        raise ValueError('整体会话集合不支持清空；请提交完整新集合或省略沿用保存集合')
                    if not isinstance(value, list) or not value or not all(isinstance(s, str) and s for s in value):
                        raise ValueError('会话集合必须是非空字符串数组（提交完整集合）')
                    query.sessions = value
                if 'from' in request:
                    value = request['from']
                    if value is None:
                        query.since = operations.CLEAR
                    elif isinstance(value, str):
                        query.since = value
                    else:
                        raise ValueError('时间下界必须是带时区的时间字符串')
                if 'to' in request and request['to'] is not None:
                    if not isinstance(request['to'], str):
                        raise ValueError('显式截止点必须是带时区的时间字符串')
                    query.to = request['to']
                if 'tz' in request and request['tz'] is not None:
                    if not isinstance(request['tz'], str) or not request['tz']:
                        raise ValueError('显示时区必须是非空字符串')
                    query.tz = request['tz']
                if request.get('main_only') is not None:
                    query.main_only = bool(request.get('main_only'))
        elif action == 'export':
            report = validate_report(saved_obj)
            fmt = request.get('format')
            if fmt not in ('json', 'csv', 'markdown'):
                raise ValueError('导出格式必须是 json、csv 或 markdown')
            return {'ok': True, 'action': 'export', 'seq': request.get('seq'),
                    'format': fmt, 'format_version': report['format_version'],
                    'content': render(report, fmt)}
        else:
            raise ValueError('不支持的操作：' + str(action))
        outcome = operations.run(query)
        result = {'ok': True, 'action': action, 'seq': request.get('seq')}
        if outcome['kind'] == 'listing':
            result['listing'] = outcome['payload']
        else:
            result['report'] = outcome['report']
            result['status'] = outcome['report']['status']
            result['exit_code'] = outcome['exit']
        return result

    @staticmethod
    def _turn_set(turns):
        if turns is None:
            return None
        if not isinstance(turns, list) or not turns or not all(isinstance(t, str) and t for t in turns):
            raise ValueError('轮次集合必须是非空字符串数组（提交完整集合）')
        return turns

    @staticmethod
    def _decoded_report(text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('该操作需要明确提交保存报告文本')
        try:
            return json.loads(text)
        except ValueError:
            raise ValueError('提交的报告文本不是有效 JSON') from None

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        # One request per connection: embedded webviews can hang reusing kept-alive
        # sockets after large POST responses.
        self.send_header('Connection', 'close')
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self._reject(405, '不支持的方法')

    do_PUT = do_DELETE = do_PATCH = do_HEAD


def serve(sources, context=None):
    """Run until the user presses Ctrl+C; the port is assigned by the system."""
    app = WebApp(sources, context)
    Handler.app = app

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True

    httpd = Server(('127.0.0.1', 0), Handler)
    port = httpd.server_address[1]
    link = f'http://127.0.0.1:{port}/#token={app.credential}'
    print('本机网页统计入口已启动（仅监听 127.0.0.1，端口由系统分配）：', flush=True)
    print('  ' + link, flush=True)
    print('可用来源（只读；网页不能提交其他路径）：', flush=True)
    for harness, descriptor in sources.items():
        kind = 'JSONL 文件/目录' if descriptor['kind'] == 'jsonl' else 'ZCode 遥测数据库（相邻 log/rollout 及 WAL/SHM 一并受限）'
        print(f'  {harness}: {kind}', flush=True)
        for path in descriptor['paths']:
            print('    ' + path, flush=True)
    print('在终端按 Ctrl+C 停止服务；关闭浏览器标签页不会停止本服务。', flush=True)
    print('服务重启后旧链接失效，请使用新链接；凭据只经启动链接的 fragment 交给页面。', flush=True)
    if context:
        note = '本次启动关联会话：' + context['harness'] + ' ' + context['session']
        note += '（转交请求 ' + context['request_id'] + '；均为启动链提供，页面点击后执行）' if context.get('request_id') else '（启动链提供，不追踪前台会话）'
        print(note, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('正在停止服务并释放端口……')
    finally:
        httpd.server_close()
    return 0
