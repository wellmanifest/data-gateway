"""Bearer tokens for network transports. The file maps SHA-256(token) to scopes; raw tokens are never stored."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
from pathlib import Path

MAX_AUTH_FILE_BYTES = 1_048_576
MAX_AUTH_HEADER_CHARS = 4096
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AuthError(Exception):
    pass


def _reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"Duplicate digest entry in auth file: {key}")
        out[key] = value
    return out


def _reject_nonfinite(constant):
    raise ValueError(f"Non-finite JSON constant in auth file: {constant}")


def _check_no_symlink_path(path):
    raw_path = os.fspath(path)
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise ValueError("Invalid auth file path")
    path_obj = Path(raw_path)
    if path_obj.is_absolute():
        cur = Path(path_obj.anchor)
        walk_parts = path_obj.parts[1:]
    else:
        cwd = Path.cwd()
        if len(cwd.parts) > 2 and cwd.is_symlink():
            raise ValueError(f"Symlink ancestor is forbidden: {cwd}")
        for anc in cwd.parents:
            if len(anc.parts) > 2 and anc.is_symlink():
                raise ValueError(f"Symlink ancestor is forbidden: {anc}")
        cur = cwd
        walk_parts = path_obj.parts
    for part in walk_parts:
        if part in ("", "."):
            continue
        if part == "..":
            cur = cur.parent
            continue
        cur = cur / part
        if len(cur.parts) > 2 and cur.is_symlink():
            raise ValueError(f"Symlink path component is forbidden: {cur}")
    abs_path = Path(os.path.abspath(raw_path))
    if abs_path.is_symlink():
        raise ValueError(f"Symlink auth file is forbidden: {path_obj}")
    for anc in abs_path.parents:
        if len(anc.parts) > 2 and anc.is_symlink():
            raise ValueError(f"Symlink ancestor is forbidden: {anc}")
    return abs_path


def _read_auth_mapping(path):
    abs_path = _check_no_symlink_path(path)
    try:
        before = os.lstat(abs_path)
    except OSError as exc:
        raise ValueError(f"Cannot stat auth file safely: {exc}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Auth file must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(os.fspath(abs_path), flags)
    except OSError as exc:
        raise ValueError(f"Cannot open auth file safely: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("Auth file must be a regular file")
        if (before.st_dev, before.st_ino) != (st.st_dev, st.st_ino):
            raise ValueError("Auth file inode changed during open")
        if st.st_size > MAX_AUTH_FILE_BYTES:
            raise ValueError("Auth file exceeds 1 MiB byte budget")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_AUTH_FILE_BYTES:
                raise ValueError("Auth file exceeds 1 MiB byte budget")
            chunks.append(chunk)
    finally:
        os.close(fd)
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Auth file must be valid UTF-8") from exc
    return json.loads(
        text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite
    )


def _is_strict_loopback_ip(host):
    if not isinstance(host, str) or not host or "%" in host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and (
        addr.ipv4_mapped is not None
        or addr.sixtofour is not None
        or addr.teredo is not None
    ):
        return False
    return addr.is_loopback


class Authenticator:
    def __init__(self, tokens_path=None):
        self.tokens = None
        if tokens_path:
            data = _read_auth_mapping(tokens_path)
            if not isinstance(data, dict) or not all(
                isinstance(k, str)
                and _SHA256_RE.fullmatch(k)
                and isinstance(v, list)
                and all(isinstance(s, str) and s.strip() == s and bool(s) for s in v)
                for k, v in data.items()
            ):
                raise ValueError(
                    "Token file must map 64-hex sha256 digests to non-empty string scope lists"
                )
            normalized = {}
            for key, value in data.items():
                lowered = key.lower()
                if lowered in normalized:
                    raise ValueError("Duplicate case-folded digest in auth file")
                normalized[lowered] = frozenset(value)
            self.tokens = normalized

    def require_safe_bind(self, host):
        if not isinstance(host, str) or not host.strip():
            raise ValueError("Bind host must be a non-empty string")
        if self.tokens is None and not _is_strict_loopback_ip(host):
            raise ValueError(
                "Without a token file the gateway only listens on loopback"
            )

    def scopes(self, authorization):
        """Return scopes for an Authorization header value; None means the unauthenticated local operator."""
        if self.tokens is None:
            return None
        if (
            not isinstance(authorization, str)
            or not authorization.startswith("Bearer ")
            or len(authorization) <= 7
            or len(authorization) > MAX_AUTH_HEADER_CHARS
        ):
            raise AuthError("Bearer credential required")
        try:
            raw_token = authorization[7:].encode("utf-8")
        except UnicodeEncodeError as exc:
            raise AuthError("Invalid credential encoding") from exc
        digest = hashlib.sha256(raw_token).hexdigest()
        matched = None
        for key, scope_set in self.tokens.items():
            if hmac.compare_digest(key, digest):
                matched = scope_set
        if matched is not None:
            return matched
        raise AuthError("Unknown credential")
