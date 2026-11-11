"""Bearer tokens for network transports. The file maps SHA-256(token) to scopes; raw tokens are never stored."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat

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


def _read_auth_mapping(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise ValueError(f"Cannot open auth file safely: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("Auth file must be a regular file")
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
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)


def _is_strict_loopback_ip(host):
    if not isinstance(host, str) or not host or "%" in host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and (
        addr.ipv4_mapped is not None or addr.sixtofour is not None or addr.teredo is not None
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
                raise ValueError("Token file must map 64-hex sha256 digests to non-empty string scope lists")
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
            raise ValueError("Without a token file the gateway only listens on loopback")

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
        digest = hashlib.sha256(authorization[7:].encode("utf-8")).hexdigest()
        matched = None
        for key, scope_set in self.tokens.items():
            if hmac.compare_digest(key, digest):
                matched = scope_set
        if matched is not None:
            return matched
        raise AuthError("Unknown credential")
