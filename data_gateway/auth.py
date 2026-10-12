"""Bearer tokens for network transports. The file maps SHA-256(token) to scopes; raw tokens are never stored."""
from __future__ import annotations
import hashlib
import hmac
import ipaddress
import json

class AuthError(Exception): pass

class Authenticator:
    def __init__(self,tokens_path=None):
        self.tokens=None
        if tokens_path:
            with open(tokens_path,encoding="utf-8") as source: data=json.load(source)
            if not isinstance(data,dict) or not all(isinstance(v,list) for v in data.values()): raise ValueError('Token file must map sha256 to scope lists')
            self.tokens={key.lower():frozenset(value) for key,value in data.items()}

    def require_safe_bind(self,host):
        if self.tokens is None and not ipaddress.ip_address(host).is_loopback:
            raise ValueError('Without a token file the gateway only listens on loopback')

    def scopes(self,authorization):
        """Return scopes for an Authorization header value; None means the unauthenticated local operator."""
        if self.tokens is None: return None
        if not authorization or not authorization.startswith('Bearer '): raise AuthError('Bearer token required')
        digest=hashlib.sha256(authorization[7:].encode('utf-8')).hexdigest()
        for key,scopes in self.tokens.items():
            if hmac.compare_digest(key,digest): return scopes
        raise AuthError('Unknown token')
