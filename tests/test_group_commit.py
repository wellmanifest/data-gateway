"""Group commit: concurrent commands share a COMMIT, keep per-command rollback, and answer only after durability."""
import base64
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from data_gateway.kernel import Kernel

NS = uuid.UUID('0b3f3c4e-7d1a-4c55-9e1f-3a2b1c0d9e8f')


def publish(i, content=b'x'):
    body = {'contentBase64': base64.b64encode(content).decode(), 'idempotencyKey': f'k{i}', 'mediaType': 'text/plain',
            'requestId': str(uuid.uuid5(NS, str(i)))}
    return 'resource.publish: process://data-gateway/resource.publish/v2 ' + json.dumps(body, sort_keys=True, separators=(',', ':'))


class FailingCommit:
    """Connection proxy whose next COMMIT fails like a full disk would."""
    def __init__(self, db): self.db, self.fail = db, True
    def execute(self, statement, *args):
        if statement == 'COMMIT' and self.fail:
            self.fail = False; raise sqlite3.OperationalError('database or disk is full')
        return self.db.execute(statement, *args)
    def __getattr__(self, name): return getattr(self.db, name)


class GroupCommit(unittest.TestCase):
    def kernel(self, **store):
        k = Kernel(Path(tempfile.mkdtemp()) / 'db.sqlite', clock=lambda: '2026-10-13T00:00:00Z')
        for key, value in store.items(): setattr(k.store, key, value)
        self.addCleanup(k.close)
        return k

    def run_concurrently(self, k, lines):
        results, start = [None] * len(lines), threading.Barrier(len(lines))
        def worker(n):
            start.wait(); results[n] = k.execute(lines[n])
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(len(lines))]
        for t in threads: t.start()
        for t in threads: t.join()
        return results

    def audit_chain_ok(self, k):
        previous = '0' * 64
        for raw in k.store.audit_jsonl().splitlines():
            record = json.loads(raw)
            if record['previousHash'] != previous: return False
            previous = record['eventHash']
        return True

    def test_concurrent_commands_share_commits_and_keep_one_audit_chain(self):
        k = self.kernel(commit_window=0.05)
        results = self.run_concurrently(k, [publish(i) for i in range(16)])
        self.assertTrue(all(r.kind == 'result' for r in results))
        self.assertEqual(len(k.store.domain_events()), 16)
        self.assertTrue(self.audit_chain_ok(k))
        self.assertGreater(max(k.store.batches), 1)
        self.assertEqual(sum(k.store.batches), 16)

    def test_a_failing_command_rolls_back_alone(self):
        k = self.kernel(commit_window=0.05)
        bad = publish(99).replace('"contentBase64":"eA=="', '"contentBase64":"!!"')
        results = self.run_concurrently(k, [publish(i) for i in range(7)] + [bad])
        self.assertEqual(sorted(r.kind for r in results), ['error'] + ['result'] * 7)
        self.assertEqual(len(k.store.domain_events()), 7)
        self.assertEqual(len(k.store.audit_jsonl().splitlines()), 8)  # the rejection is audited too
        self.assertTrue(self.audit_chain_ok(k))

    def test_commit_failure_reaches_every_member_and_leaves_no_effects(self):
        k = self.kernel(commit_window=0.2)
        k.store.db = FailingCommit(k.store.db)
        failures = []
        def worker(i):
            try: k.execute(publish(i))
            except sqlite3.OperationalError as error: failures.append(str(error))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(failures)
        self.assertEqual(len(k.store.domain_events()), 4 - len(failures))  # only later groups committed
        self.assertTrue(self.audit_chain_ok(k))

    def test_a_lone_command_does_not_wait_for_the_window(self):
        k = self.kernel(commit_window=1.0)
        started = time.perf_counter()
        self.assertEqual(k.execute(publish(1)).kind, 'result')
        self.assertLess(time.perf_counter() - started, 0.5)


if __name__ == '__main__':
    unittest.main()
