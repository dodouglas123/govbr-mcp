import time
from types import SimpleNamespace

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from govbr.auth import Authorization
from govbr.settings import READ, Settings
from govbr.transport import SafeHTTP


async def test_oauth_signature_audience_expiration_and_subject():
    issuer, resource = "https://login.example/realms/govbr", "https://gov.example/mcp"
    config = Settings(
        environment="production",
        public_url="https://gov.example",
        oauth_issuer=issuer,
        oauth_jwks_url=f"{issuer}/jwks",
        oauth_audience=resource,
        oauth_allowed_subjects="allowed",
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update(kid="main", use="sig")
    calls = []

    def jwks(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"keys": [jwk]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(jwks)) as client:
        authorizer = Authorization(
            SimpleNamespace(settings=config), SafeHTTP(config, client=client, check_dns=False)
        )
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": resource,
            "sub": "allowed",
            "exp": now + 3600,
            "scope": "govbr:read govbr:admin",
        }

        async def verify(payload, sign=private):
            value = jwt.encode(payload, sign, algorithm="RS256", headers={"kid": "main"})
            return await authorizer.verify(f"Bearer {value}")

        access = await verify(claims)
        assert access and access.scopes == {READ}
        assert await verify({**claims, "aud": "https://other/mcp"}) is None
        assert await verify({**claims, "iss": "https://other/realms/govbr"}) is None
        assert await verify({**claims, "exp": now - 10}) is None
        assert await verify({**claims, "sub": "outside"}) is None
        assert (await verify({**claims, "scope": "openid"})).scopes == set()
        assert await verify(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048)) is None
        assert calls == [f"{issuer}/jwks"]
        assert authorizer.metadata()["resource"] == resource
        assert (
            'resource_metadata="https://gov.example/.well-known/oauth-protected-resource/mcp"'
            in authorizer.challenge()
        )
