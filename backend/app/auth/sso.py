from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import jwt

from app.core.config import get_settings


@dataclass(frozen=True)
class ExternalIdentity:
    subject: str
    username: str
    roles: list[str]
    organization_id: str | None = None


class IdentityProvider(ABC):
    @abstractmethod
    async def authenticate(self, token: str) -> ExternalIdentity:
        raise NotImplementedError


class OidcProvider(IdentityProvider):
    async def authenticate(self, token: str) -> ExternalIdentity:
        if not token:
            raise ValueError("OIDC token is required")
        settings = get_settings()
        if not settings.oidc_issuer_url or not settings.oidc_jwks_url:
            raise ValueError("OIDC provider is not configured")
        async with httpx.AsyncClient(timeout=10) as client:
            jwks = (await client.get(settings.oidc_jwks_url)).json()
        try:
            header = jwt.get_unverified_header(token)
            key = next(item for item in jwks["keys"] if item["kid"] == header["kid"])
            claims = jwt.decode(token, jwt.algorithms.RSAAlgorithm.from_jwk(key), algorithms=[header["alg"]], audience=settings.oidc_audience or None, issuer=settings.oidc_issuer_url)
        except (jwt.PyJWTError, KeyError, StopIteration) as exc:
            raise ValueError("OIDC token is invalid") from exc
        return ExternalIdentity(str(claims["sub"]), str(claims.get("preferred_username", claims.get("email", claims["sub"]))), list(claims.get("roles", ["planner"])), claims.get("organization_id"))


class LdapProvider(IdentityProvider):
    async def authenticate(self, token: str) -> ExternalIdentity:
        if not token:
            raise ValueError("LDAP identity is required")
        settings = get_settings()
        if not settings.ldap_url:
            raise ValueError("LDAP provider is not configured")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(settings.ldap_url, json={"identity": token, "base_dn": settings.ldap_base_dn})
            response.raise_for_status()
            claims = response.json()
        return ExternalIdentity(str(claims["subject"]), str(claims["username"]), list(claims.get("roles", ["planner"])), claims.get("organization_id"))


class CasProvider(IdentityProvider):
    async def authenticate(self, token: str) -> ExternalIdentity:
        if not token:
            raise ValueError("CAS ticket is required")
        settings = get_settings()
        if not settings.cas_validate_url:
            raise ValueError("CAS provider is not configured")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(settings.cas_validate_url, params={"ticket": token})
            response.raise_for_status()
            claims = response.json()
        return ExternalIdentity(str(claims["subject"]), str(claims["username"]), list(claims.get("roles", ["planner"])), claims.get("organization_id"))
