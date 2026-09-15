import httpx
import pytest

from app.auth.sso import CasProvider, LdapProvider, OidcProvider
from app.im import WeComWebhookProvider, ImMessage


@pytest.mark.asyncio
async def test_ldap_and_cas_validate_remote_identity(monkeypatch) -> None:
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return httpx.Response(200, request=httpx.Request("POST", "http://ldap.test"), json={"subject": "s", "username": "u", "roles": ["planner"]})

        async def get(self, *args, **kwargs):
            return httpx.Response(200, request=httpx.Request("GET", "http://cas.test"), json={"subject": "s", "username": "u", "roles": ["planner"]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: Client())
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    settings.ldap_url = "http://ldap.test"
    settings.cas_validate_url = "http://cas.test"
    assert (await LdapProvider().authenticate("token")).username == "u"
    assert (await CasProvider().authenticate("ticket")).username == "u"


@pytest.mark.asyncio
async def test_webhook_provider_posts_message(monkeypatch) -> None:
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, json, headers):
            assert endpoint == "http://im.test"
            assert json["content"] == "body"
            return httpx.Response(200, request=httpx.Request("POST", endpoint))

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: Client())
    provider = WeComWebhookProvider("http://im.test")
    assert (await provider.send_text("u", ImMessage("text", "title", "body")))["status"] == "sent"
