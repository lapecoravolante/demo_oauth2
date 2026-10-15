import os

import httpx

KEYCLOAK_BASE_URL = os.getenv(
    "KEYCLOAK_BASE_URL",
    "http://keycloak:8080",
)

# URL pubblico di Keycloak per il redirect del browser (es. localhost:8080 con port-forward)
KEYCLOAK_PUBLIC_URL = os.getenv(
    "KEYCLOAK_PUBLIC_URL",
    "http://localhost:8080",
)

REALM = os.getenv(
    "KEYCLOAK_REALM",
    "oauth-lab",
)

CLIENT_ID = os.getenv(
    "OAUTH_CLIENT_ID",
    "demo-client",
)

CLIENT_SECRET = os.getenv(
    "OAUTH_CLIENT_SECRET",
    "demo-client-secret",
)

REDIRECT_URI = os.getenv(
    "OAUTH_REDIRECT_URI",
    "http://localhost:8000/callback",
)

# Scope richiesto dal client. Deve corrispondere a un client scope registrato in
# Keycloak, altrimenti l'Authorization Server lo ignora e il token che torna
# non lo contiene.
SCOPE = os.getenv(
    "OAUTH_SCOPE",
    "documents:read",
)


ISSUER = f"{KEYCLOAK_BASE_URL}/realms/{REALM}"

DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


async def get_discovery() -> dict:
    """Step 2 - Discovery: il client non deve conoscere a mano gli URL di
    Keycloak, li legge dal documento .well-known/openid-configuration. Da qui
    arrivano sia authorization_endpoint (usato in login) sia token_endpoint
    (usato in exchange_code).
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(DISCOVERY_URL)
        response.raise_for_status()
        return response.json()


async def exchange_code(code: str) -> dict:
    """Scambia l'Authorization Code con un Access Token.

    È il Token Request: avviene dal server del client al token_endpoint e non
    passa dal browser. Il code è monouso e viene invalidato da Keycloak dopo
    questo scambio.
    """
    discovery = await get_discovery()

    token_endpoint = discovery["token_endpoint"]

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": SCOPE,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_endpoint,
            data=data,
        )

        response.raise_for_status()

        return response.json()
