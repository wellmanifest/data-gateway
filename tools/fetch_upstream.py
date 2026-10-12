#!/usr/bin/env python3
"""Fetch pinned data-plane and logs into build/upstream (or verify DATA_PLANE_ROOT / WELLLOGS_ROOT)."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data_gateway.upstream import LOCK,fetch

if __name__=='__main__':
    print(json.dumps({name:{'commit':LOCK[name]['commit'],'path':str(fetch(name))} for name in LOCK},indent=2))
