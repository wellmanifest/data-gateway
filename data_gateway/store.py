"""SQLite event store for the reference gateway: domain events, resource projection, receipts and audit chain.

One writer per database file. Every effect of a command and its audit event commit in one transaction (ES-012).
"""
from __future__ import annotations
import sqlite3
import threading
from contextlib import contextmanager

from data_gateway.upstream import data_plane

ZERO='0'*64

class _Batch:
    """Commands sharing one SQLite transaction and one fsync; every member waits for its COMMIT."""
    def __init__(self): self.members=0;self.durable=False;self.error=None;self.done=threading.Event()
DDL='''
CREATE TABLE IF NOT EXISTS events (
 event_urn TEXT PRIMARY KEY, stream_urn TEXT NOT NULL, version INTEGER NOT NULL,
 hash TEXT NOT NULL, canonical BLOB NOT NULL, UNIQUE(stream_urn,version));
CREATE TABLE IF NOT EXISTS blobs (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS resources (
 urn TEXT PRIMARY KEY, sha256 TEXT NOT NULL REFERENCES blobs(sha256), media_type TEXT NOT NULL,
 byte_length INTEGER NOT NULL, version INTEGER NOT NULL,
 FOREIGN KEY(urn,version) REFERENCES events(stream_urn,version));
CREATE TABLE IF NOT EXISTS receipts (
 operation TEXT NOT NULL, key TEXT NOT NULL, input_hash TEXT NOT NULL, result BLOB NOT NULL,
 PRIMARY KEY(operation,key));
CREATE TABLE IF NOT EXISTS audit (sequence INTEGER PRIMARY KEY, hash TEXT NOT NULL, canonical BLOB NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
CREATE TRIGGER IF NOT EXISTS immutable_audit_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TRIGGER IF NOT EXISTS immutable_audit_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
'''

def _apply_pragma(db, pragma):
    db.execute('PRAGMA '+pragma)

class Store:
    def __init__(self,path,*,commit_window=0.002,max_batch=64):
        """commit_window: seconds a command waits for concurrent commands to share its COMMIT. A command that is
        alone commits at once, so single-client latency does not pay the window. 0 groups only commands that are
        already queued; None commits every command by itself inside the store lock (no grouping)."""
        _,_,events=data_plane()
        self.canonical=events.canonical;self.event_hash=events.event_hash
        self.db=sqlite3.connect(str(path),isolation_level=None,check_same_thread=False)
        # data-plane low-ram-v1 SQLite profile: durability over write speed, small cache.
        for pragma in ('foreign_keys = ON','journal_mode = WAL','synchronous = FULL','cache_size = -2048','busy_timeout = 5000'):
            _apply_pragma(self.db, pragma)
        self.db.executescript(DDL)
        self.lock=threading.Lock()
        self.state=threading.Lock();self.inflight=0;self.batch=None
        self.commit_window=commit_window;self.max_batch=max_batch;self.batches=[]

    def close(self): self.db.close()

    @contextmanager
    def transaction(self,durable=True):
        """Run one command in its own SAVEPOINT inside the current group transaction and return only after COMMIT.

        durable=False marks a query: a group made only of queries commits with WAL synchronous=NORMAL (its audit
        records survive a process crash); any command in the group makes the COMMIT synchronous=FULL.
        """
        with self.state: self.inflight+=1
        batch=None
        try:
            with self.lock:
                if self.batch is not None and durable and not self.batch.durable:
                    self._commit_locked(self.batch)  # a command never commits with a query group's weaker sync
                if self.batch is None:
                    # SQLite fixes the sync level outside a transaction, so the group's first member decides it.
                    self.db.execute('PRAGMA synchronous = '+('FULL' if durable else 'NORMAL'))
                    self.db.execute('BEGIN IMMEDIATE');self.batch=_Batch();self.batch.durable=durable
                batch=self.batch;batch.members+=1
                self.db.execute('SAVEPOINT command')
                try:
                    yield self
                except BaseException:
                    self.db.execute('ROLLBACK TO command');self.db.execute('RELEASE command');raise
                self.db.execute('RELEASE command')
                if self.commit_window is None: self._commit_locked(batch)
        finally:
            with self.state:
                self.inflight-=1;alone=self.inflight==0
            if batch is not None and (alone or batch.members>=self.max_batch or not batch.done.wait(self.commit_window)):
                self._commit(batch)
        if batch.error is not None: raise batch.error

    def _commit(self,batch):
        with self.lock: self._commit_locked(batch)

    def _commit_locked(self,batch):
        if self.batch is not batch: return  # another member already committed this group
        try:
            self.db.execute('COMMIT')
        except sqlite3.Error as error:
            batch.error=error
            if self.db.in_transaction: self.db.execute('ROLLBACK')
        finally:
            self.batch=None;self.batches.append(batch.members);batch.done.set()

    def append_event(self,event):
        raw=self.canonical(event)
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',(event['eventUrn'],event['streamUrn'],int(event['streamVersion']),event['eventHash'],raw))

    def stream_head(self,stream_urn):
        row=self.db.execute('SELECT version,hash FROM events WHERE stream_urn=? ORDER BY version DESC LIMIT 1',(stream_urn,)).fetchone()
        return row or (0,ZERO)

    def receipt(self,operation,key):
        return self.db.execute('SELECT input_hash,result FROM receipts WHERE operation=? AND key=?',(operation,key)).fetchone()

    def put_receipt(self,operation,key,input_hash,result):
        self.db.execute('INSERT INTO receipts VALUES (?,?,?,?)',(operation,key,input_hash,self.canonical(result)))

    def put_resource(self,urn,sha256,content,media_type,version):
        self.db.execute('INSERT OR IGNORE INTO blobs VALUES (?,?)',(sha256,content))
        self.db.execute('INSERT INTO resources VALUES (?,?,?,?,?)',(urn,sha256,media_type,len(content),version))

    def resource(self,urn):
        return self.db.execute('SELECT r.sha256,r.media_type,r.byte_length,b.content FROM resources r JOIN blobs b USING(sha256) WHERE r.urn=?',(urn,)).fetchone()

    def append_audit(self,build):
        """`build(sequence, previous_hash)` returns the complete event; the chain is assigned inside the transaction."""
        row=self.db.execute('SELECT sequence,hash FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()
        sequence,previous=(row[0]+1,row[1]) if row else (1,ZERO)
        event=build(sequence,previous);event['eventHash']=self.event_hash(event)
        self.db.execute('INSERT INTO audit VALUES (?,?,?)',(sequence,event['eventHash'],self.canonical(event)))
        return event

    def audit_jsonl(self):
        """Canonical wellmanifest/logs JSONL bytes of the audit stream."""
        rows=self.db.execute('SELECT canonical FROM audit ORDER BY sequence').fetchall()
        return b''.join(raw+b'\n' for (raw,) in rows)

    def domain_events(self):
        rows=self.db.execute('SELECT canonical FROM events ORDER BY rowid').fetchall()
        return [raw for (raw,) in rows]
