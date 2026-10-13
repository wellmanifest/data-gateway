#!/usr/bin/env python3
"""A/B benchmark of the gateway against an ad-hoc SQLite baseline with the same workload.

Sides:
  baseline             mutable table + JSON log row per write; reads are not logged (typical small project)
  baseline_equivalent  the same, but every read also commits a log row (same audit duty as the gateway)
  gateway              data-gateway kernel: events, projection, idempotency receipt and hash-chained audit

Levels: write/read latency (wall and thread CPU, p50/p95), storage bytes per write, duplicate side effects
and binary guarantees. All sides use synchronous=FULL for writes (data-plane SQLite profile).
Run `python3 benchmarks/bench.py --dir <disk directory>`; tmpfs hides fsync cost. `--check` exits 1 on regression.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, shutil, statistics, sys, tempfile, time, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_gateway.kernel import Kernel  # noqa: E402

NS = uuid.UUID('6f1c2c1e-6c55-4a43-9a62-6a7c1b9e2a10')
MEDIA = 'text/plain; charset=utf-8'


def rid(i, salt='r'): return str(uuid.uuid5(NS, f'{salt}{i}'))
def payload(i, size): return (f'{i:08d}'.encode() * (size // 8 + 1))[:size]
def pct(values, q): values = sorted(values); return values[min(len(values) - 1, int(q * len(values)))]


def publish_line(request_id, key, content):
    body = {'contentBase64': base64.b64encode(content).decode(), 'idempotencyKey': key, 'mediaType': MEDIA, 'requestId': request_id}
    return 'resource.publish: process://data-gateway/resource.publish/v2 ' + json.dumps(body, sort_keys=True, separators=(',', ':'))


def read_line(request_id, urn):
    return f'resource.read: {urn} ' + json.dumps({'consistency': 'strong', 'requestId': request_id}, sort_keys=True, separators=(',', ':'))


class Baseline:
    def __init__(self, path, log_reads):
        import sqlite3
        self.log_reads = log_reads
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript('PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;'
                              'CREATE TABLE resources(urn TEXT PRIMARY KEY,sha256 TEXT,media_type TEXT,content BLOB);'
                              'CREATE TABLE log(id INTEGER PRIMARY KEY,at TEXT,entry TEXT);')

    def publish(self, request_id, key, content):
        urn = 'urn:uuid:' + str(uuid.uuid5(NS, key))
        self.db.execute('BEGIN')
        self.db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?,?)', (urn, hashlib.sha256(content).hexdigest(), MEDIA, content))
        self.db.execute('INSERT INTO log(at,entry) VALUES(?,?)', (time.strftime('%Y-%m-%dT%H:%M:%SZ'), json.dumps({'op': 'publish', 'requestId': request_id, 'urn': urn})))
        self.db.execute('COMMIT')
        return urn

    def read(self, request_id, urn):
        if self.log_reads: self.db.execute('BEGIN')
        row = self.db.execute('SELECT sha256,media_type,content FROM resources WHERE urn=?', (urn,)).fetchone()
        result = {'urn': urn, 'sha256': row[0], 'mediaType': row[1], 'contentBase64': base64.b64encode(row[2]).decode()}
        if self.log_reads:
            self.db.execute('INSERT INTO log(at,entry) VALUES(?,?)', (time.strftime('%Y-%m-%dT%H:%M:%SZ'), json.dumps({'op': 'read', 'requestId': request_id, 'urn': urn})))
            self.db.execute('COMMIT')
        return result

    def events(self): return self.db.execute('SELECT count(*) FROM log').fetchone()[0]
    def checkpoint(self): self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    def close(self): self.db.close()


class Gateway:
    def __init__(self, path): self.kernel = Kernel(path, clock=lambda: '2026-10-13T00:00:00Z')

    def publish(self, request_id, key, content):
        out = self.kernel.execute(publish_line(request_id, key, content))
        assert out.kind == 'result', out.line
        return json.loads(out.line.split(' ', 2)[2])['result']['urn']

    def read(self, request_id, urn):
        out = self.kernel.execute(read_line(request_id, urn)); assert out.kind == 'result', out.line

    def events(self): return len(self.kernel.store.domain_events())
    def checkpoint(self): self.kernel.store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    def close(self): self.kernel.close()


def run(side, n, size, directory):
    work = tempfile.mkdtemp(prefix=f'bench-{side}-', dir=directory)
    path = os.path.join(work, 'db.sqlite')
    impl = Gateway(path) if side == 'gateway' else Baseline(path, side == 'baseline_equivalent')
    w, wc, r, rc, urns = [], [], [], [], []
    try:
        for i in range(n):
            t, c = time.perf_counter(), time.thread_time(); urns.append(impl.publish(rid(i), f'k{i}', payload(i, size)))
            w.append(time.perf_counter() - t); wc.append(time.thread_time() - c)
        for i, urn in enumerate(urns):
            t, c = time.perf_counter(), time.thread_time(); impl.read(rid(i, 'q'), urn)
            r.append(time.perf_counter() - t); rc.append(time.thread_time() - c)
        impl.checkpoint()  # fold the WAL into the database so storage counts committed pages only
        storage = sum(os.path.getsize(p) for p in Path(work).iterdir()) / n
        before = impl.events()
        for i in range(max(1, n // 10)): impl.publish(rid(i), f'k{i}', payload(i, size))
        duplicates = impl.events() - before
        impl.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    us = lambda xs, q: pct(xs, q) * 1e6
    return {'write_wall_p50': us(w, .5), 'write_wall_p95': us(w, .95), 'write_cpu_p50': us(wc, .5),
            'read_wall_p50': us(r, .5), 'read_wall_p95': us(r, .95), 'read_cpu_p50': us(rc, .5),
            'storage_bytes_per_write': storage, 'duplicate_side_effects': duplicates}


def concurrent(side, clients, n, size, directory):
    """Write throughput with `clients` threads; each baseline thread has its own connection (SQLite serializes writers)."""
    import threading
    work = tempfile.mkdtemp(prefix=f'conc-{side}-', dir=directory)
    path = os.path.join(work, 'db.sqlite')
    try:
        if side == 'baseline':
            Baseline(path, False).close()
            impls = [Baseline.__new__(Baseline) for _ in range(clients)]
            import sqlite3
            for impl in impls:
                impl.log_reads = False; impl.db = sqlite3.connect(path, isolation_level=None, timeout=60, check_same_thread=False)
                impl.db.execute('PRAGMA synchronous=FULL'); impl.db.execute('PRAGMA busy_timeout=60000')
            publish = lambda c, i: impls[c].publish(rid(i), f'k{i}', payload(i, size))
        else:
            gateway = Gateway(path); gateway.kernel.store.commit_window = 0.002 if side == 'gateway_group' else None
            publish = lambda c, i: gateway.publish(rid(i), f'k{i}', payload(i, size))
        latencies, per, barrier = [], n // clients, threading.Barrier(clients)
        def worker(c):
            barrier.wait()
            for k in range(per):
                t = time.perf_counter(); publish(c, c * per + k); latencies.append(time.perf_counter() - t)
        threads = [threading.Thread(target=worker, args=(c,)) for c in range(clients)]
        start = time.perf_counter()
        for t in threads: t.start()
        for t in threads: t.join()
        elapsed = time.perf_counter() - start
        result = {'writes_per_s': per * clients / elapsed, 'write_wall_p50': pct(latencies, .5) * 1e6, 'write_wall_p95': pct(latencies, .95) * 1e6}
        if side != 'baseline':
            batches = gateway.kernel.store.batches; result['mean_group'] = sum(batches) / len(batches); gateway.close()
        else:
            for impl in impls: impl.close()
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Regression gates, evaluated on medians from the same run and machine.
CHECKS = [
    ('gateway write wall p50 <= 1.5 x baseline', lambda m: m['gateway']['write_wall_p50'] <= 1.5 * m['baseline']['write_wall_p50']),
    ('gateway read wall p50 <= equivalent baseline', lambda m: m['gateway']['read_wall_p50'] <= m['baseline_equivalent']['read_wall_p50']),
    ('gateway duplicate retries cause no effects', lambda m: m['gateway']['duplicate_side_effects'] == 0),
]
CONCURRENT_CHECKS = [
    ('concurrent gateway writes/s >= baseline', lambda c: c['gateway_group']['writes_per_s'] >= c['baseline']['writes_per_s']),
    ('group commit writes/s >= ungrouped gateway', lambda c: c['gateway_group']['writes_per_s'] >= c['gateway_single']['writes_per_s']),
]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--n', type=int, default=200); p.add_argument('--size', type=int, default=512)
    p.add_argument('--rounds', type=int, default=3); p.add_argument('--dir', default=None)
    p.add_argument('--check', action='store_true')
    p.add_argument('--clients', type=int, default=0, help='also measure concurrent write throughput with this many threads')
    a = p.parse_args()
    sides = ('baseline', 'baseline_equivalent', 'gateway'); rows = {s: [] for s in sides}
    for _ in range(a.rounds):  # interleave sides so host load affects all of them alike
        for side in sides: rows[side].append(run(side, a.n, a.size, a.dir))
    medians = {s: {k: round(statistics.median(r[k] for r in rs), 1) for k in rs[0]} for s, rs in rows.items()}
    checks = [{'check': name, 'passed': bool(fn(medians))} for name, fn in CHECKS]
    report = {'n': a.n, 'size': a.size, 'rounds': a.rounds, 'directory': a.dir or tempfile.gettempdir(),
              'python': sys.version.split()[0], 'medians': medians, 'checks': checks}
    if a.clients:
        csides = ('baseline', 'gateway_single', 'gateway_group'); crows = {s: [] for s in csides}
        for _ in range(a.rounds):
            for side in csides: crows[side].append(concurrent(side, a.clients, a.n, a.size, a.dir))
        cmed = {s: {k: round(statistics.median(r[k] for r in rs), 1) for k in rs[0]} for s, rs in crows.items()}
        report['concurrent'] = {'clients': a.clients, 'medians': cmed}
        checks += [{'check': name, 'passed': bool(fn(cmed))} for name, fn in CONCURRENT_CHECKS]
    print(json.dumps(report, indent=1))
    if a.check and not all(c['passed'] for c in checks): sys.exit(1)


if __name__ == '__main__':
    main()
