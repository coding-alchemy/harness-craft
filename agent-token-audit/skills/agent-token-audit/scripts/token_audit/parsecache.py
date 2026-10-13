"""Bounded in-process parse reuse for the local web service.

The cache unit is one adapter's complete finite snapshot of a source input plus its
companion file set. Every request runs ONE guarded discovery over every path the
parser will actually consume — including nested relation logs reached recursively —
resolving and source-guarding each path BEFORE any content read, on cache hits and
misses alike. Each file is then captured once into request memory; the content
signature and the parse consume that same captured content, so a source swapped
or relinked between the digest and the parse can never enter an entry. Rollout
captures are keyed by their entry filename, so a root-internal link keeps the
session association of the entry while the bytes come from the resolved real
path. The database keeps its existing consistent read-only snapshot plus a
table-level structure-and-row signature; the database itself is never read
wholesale into memory. Stored entries are pickled normalized adapter evidence
(no raw source text, no credentials) and every hit unpickles a fresh object
graph, so bind/explain/analysis in-place work can never leak back into the
cache; request-scoped source metadata (which -wal/-shm sidecars exist) is
rebuilt per hit from the current guarded input, never restored from the entry.

Bounds are internal (entry count plus total pickled bytes, sized against the
target large reports: ~57MB zcode / ~5MB codex pickles) and are not user
configuration. Misses, evictions and over-limit inserts fall back to the plain
read path. The CLI keeps its single-shot semantics: it never constructs a
cache, so cold behavior is the only behavior there.
"""
import hashlib
import pickle
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from .core import capture

# Bump when adapter parsing semantics change so old entries can never match.
PARSE_SEMANTICS = 'parse-v1'
_MAX_ENTRIES = 2
_MAX_BYTES = 1 << 30  # 1 GiB across pickled entries

# The tables the database parser actually reads; structure+rows of exactly these
# form the content signature (a DB/WAL stat proves nothing about read content).
_SIGNATURE_TABLES = ('session', 'model_usage', 'turn_usage', 'tool_usage', 'message', 'session_input')


def _captured_digest(*captures):
    """Content signature over one request's captured bytes; never re-reads the files."""
    digest = hashlib.sha256()
    for captured in captures:
        for path, content, error in captured:
            digest.update(path.encode('utf-8'))
            digest.update(b'\0')
            if content is None:
                digest.update(b'!unread:')
                digest.update((error or '').encode('utf-8'))
            else:
                digest.update(content)
    return digest.hexdigest()


def _database_signature(target):
    """Structure+row signature over the parser-read tables of the copied snapshot."""
    digest = hashlib.sha256()
    db = sqlite3.connect('file:' + str(target) + '?mode=ro', uri=True)
    try:
        for table in _SIGNATURE_TABLES:
            exists = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
                                (table,)).fetchone()[0]
            digest.update(table.encode('utf-8'))
            if not exists:
                digest.update(b':absent')
                continue
            columns = [row[1] for row in db.execute('PRAGMA table_info("%s")' % table)]
            digest.update(repr(columns).encode('utf-8'))
            count = db.execute('SELECT count(*) FROM "%s"' % table).fetchone()[0]
            digest.update((':rows=' + str(count) + ':').encode('utf-8'))
            for row in db.execute('SELECT * FROM "%s"' % table):
                digest.update(repr(row).encode('utf-8', 'backslashreplace'))
                digest.update(b'\0')
    finally:
        db.close()
    return digest.hexdigest()


class ParseCache:
    """Service-owned bounded cache; thread-safe because the web service serves
    requests on daemon threads and may run two of them concurrently."""

    def __init__(self, max_entries=_MAX_ENTRIES, max_bytes=_MAX_BYTES):
        self._entries = OrderedDict()  # key -> pickled adapter data
        self._bytes = 0
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    def _lookup(self, key):
        with self._lock:
            blob = self._entries.get(key)
            if blob is not None:
                self._entries.move_to_end(key)
            return blob

    def _store(self, key, blob):
        with self._lock:
            if key in self._entries:
                return
            self._entries[key] = blob
            self._bytes += len(blob)
            while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                if not self._entries:
                    break
                _, dropped = self._entries.popitem(last=False)
                self._bytes -= len(dropped)

    def cached_jsonl(self, harness, roots, guard, discover, parse_captured):
        """Reuse one JSONL adapter parse when the guarded, once-captured content is identical."""
        paths = discover(roots, guard)  # Guard-checked and ordered on every request.
        captured = capture(paths)  # One finite read per path; request memory only.
        key = (harness, 'jsonl', tuple(str(p) for p in paths), PARSE_SEMANTICS,
               _captured_digest(captured))
        blob = self._lookup(key)
        if blob is not None:
            return pickle.loads(blob)  # Fresh object graph; nothing is shared with the cache.
        data = parse_captured(captured)
        self._store(key, pickle.dumps(data, protocol=5))
        return data

    def cached_database(self, path, guard, snapshot, companions, parse):
        """Reuse one database parse when the copied snapshot's read tables and the
        guarded, once-captured companion set are identical to a previous request's."""
        with snapshot(path, guard) as (source, target):
            log_capture, rollout_capture = companions(source, guard)
            key = ('zcode', 'database', str(source), PARSE_SEMANTICS,
                   _database_signature(target), _captured_digest(log_capture, rollout_capture))
            blob = self._lookup(key)
            if blob is not None:
                data = pickle.loads(blob)
                # Which -wal/-shm sidecars exist is per-request evidence: the reused
                # parse proves table content, never this request's sidecar set, so the
                # volatile source prefix is rebuilt from the guarded snapshot input
                # (same existence check the fresh parse uses) instead of restoring the
                # previous request's list.
                sidecars = [p for p in (str(source) + '-wal', str(source) + '-shm') if Path(p).exists()]
                stale = {str(source), str(source) + '-wal', str(source) + '-shm'}
                data['source_files'] = ([str(source)] + sidecars
                                        + [p for p in data['source_files'] if p not in stale])
                return data
            data = parse(source, target, log_capture, rollout_capture)
            blob = pickle.dumps(data, protocol=5)
        self._store(key, blob)
        return data
