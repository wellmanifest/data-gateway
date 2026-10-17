"""Locate and verify pinned upstream checkouts. Fetching is explicit (tools/fetch_upstream.py); runtime never downloads."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LOCK=json.loads((ROOT/'upstream.lock.json').read_text())
ENV={'dataPlane':'DATA_PLANE_ROOT','logs':'WELLLOGS_ROOT','docs':'DOCS_STANDARD_ROOT'}

class UpstreamError(RuntimeError): pass

def location(name):
    configured=os.environ.get(ENV[name])
    return Path(configured).resolve() if configured else ROOT/'build/upstream'/name

def verify(name,path=None):
    pin=LOCK[name];path=path or location(name)
    if not path.exists(): raise UpstreamError(f'{name} checkout missing at {path}; run `make upstream`')
    head=subprocess.run(['git','-C',str(path),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    if head!=pin['commit']: raise UpstreamError(f'{name} checkout is not at the pinned commit')
    for relative,digest in pin['files'].items():
        if hashlib.sha256((path/relative).read_bytes()).hexdigest()!=digest: raise UpstreamError(f'{name} digest mismatch: {relative}')
    return path

def _run_git(path, args):
    subprocess.run(['git','-C',str(path),*args],check=True)

def fetch(name):
    """Create the ignored build checkout at the pinned commit; an existing checkout is only verified."""
    pin=LOCK[name];path=location(name)
    if not path.exists():
        if os.environ.get(ENV[name]): raise UpstreamError(f'{ENV[name]} does not exist')
        path.mkdir(parents=True)
        for args in (['init','-q'],['fetch','--quiet','--depth','1',pin['repository'],pin['commit']],['checkout','--quiet','--detach','FETCH_HEAD']):
            _run_git(path,args)
    return verify(name,path)

_data_plane=None
def data_plane():
    """Import the pinned data-plane line and event modules without copying their code."""
    global _data_plane
    if _data_plane is None:
        path=verify('dataPlane')
        if str(path) not in sys.path: sys.path.insert(0,str(path))
        from conformance import line,event_store
        _data_plane=(path,line,event_store)
    return _data_plane
