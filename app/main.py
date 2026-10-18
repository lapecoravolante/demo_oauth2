"""Client e Resource Server OAuth 2.0 di esempio (Authorization Code Flow).

FastAPI ricopre due ruoli:

  - OAuth Client: ottiene l'access token da Keycloak
  - Resource Server: verifica che il token consenta di accedere alla risorsa

Endpoint:

    GET /                  -> pagina iniziale
    GET /login             -> Authorization Request e redirect a Keycloak
    GET /callback          -> riceve il code, esegue il Token Request, apre la sessione
    GET /documents         -> risorsa protetta dallo scope documents:read
    GET /secret_documents  -> risorsa protetta dallo scope secret:read
    GET /profile           -> mostra il token ottenuto

Lo scambio di token con Keycloak vive in `oauth.py`; qui ci sono i passaggi
HTTP, la sessione e la verifica degli scope.

La telemetria è gestita dall'auto-instrumentazione
dell'OpenTelemetry Operator per Kubernetes (injection), senza
modifiche al codice: le trace e gli span vengono inviati
all'APM di Kibana tramite il gateway OTLP del cluster.
Le variabili OTEL_* si impostano nel deployment YAML.
"""

import base64
import json
import secrets

from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from oauth import (
    CLIENT_ID,
    REDIRECT_URI,
    SCOPE,
    exchange_code,
    get_discovery,
    KEYCLOAK_PUBLIC_URL,
    KEYCLOAK_BASE_URL,
)

app = FastAPI(
    title="OAuth 2.0 Lab Client",
    telemetry={"auto_configure": False},
)

templates = Jinja2Templates(
    directory="templates",
)


# Mappa scope -> risorsa. È la mappatura dei permessi: per ogni path, lo scope
# che l'access token deve contenere.
#
# La decisione "chi può accedere a cosa" spetta al server che espone l'API, non
# al client OAuth: in un laboratorio con un Resource Server separato questa
# tabella starebbe lì. Qui le due cose coincidono per scelta didattica, quindi
# FastAPI fa anche da Resource Server. La separazione in un servizio proprio
# non è previsto.
SCOPE_PER_RESOURCE = {
    "/documents": "documents:read",
    "/secret_documents": "secret:read",
}

# Sessioni in memoria: session_id -> access_token. L'access token resta sul
# server, il browser riceve solo l'id della sessione in un cookie.
#
# È una scelta voluta: nell'Authorization Code Flow l'access token non deve
# attraversare il browser, quindi la pagina non lo contiene e le richieste alle
# risorse protette non portano un header Authorization.
#
# Limite didattico: un dict in memoria è perduto a ogni riavvio e non è condiviso
# tra più istanze della pod.
SESSIONS = {}


def decode_access_token(token: str) -> dict:
    """Decodifica il payload di un JWT, senza verificarne la firma.

    Un JWT è fatto di tre segmenti base64url separati da punti; il secondo è il
    payload con i claim.

    Qui la firma NON viene verificata, ed è una scelta dichiarata: la verifica
    tramite JWKS non è prevista in questo laboratorio. Decodifichiamo solo per
    mostrare il contenuto del token e decidere sull'accesso a una risorsa di
    esempio, non per proteggere dati reali.
    """
    payload = token.split(".")[1]
    padding = "=" * (-len(payload) % 4)

    return json.loads(
        base64.urlsafe_b64decode(payload + padding)
    )


def token_scopes(token: str) -> list[str]:
    """Elenco degli scope che Keycloak ha concesso nell'access token."""
    claim = decode_access_token(token).get("scope", "")

    return claim.split()


def access_token_of(request: Request) -> str | None:
    """Recupera l'access token della sessione corrente, se esiste."""
    return SESSIONS.get(request.cookies.get("sid", ""))


# Step 1 - l'utente apre FastAPI.
# Non parte qui alcuna richiesta verso Keycloak: la pagina offre il link a
# /login. Essendo un Authorization Code Flow, l'utente non viene autenticato da
# FastAPI ma dall'Authorization Server, quindi non c'è ancora nessun token.
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "authenticated": access_token_of(request) is not None,
        },
    )


# Step 2 e 3 - il Browser chiama /login e FastAPI costruisce l'Authorization
# Request, ma non la esegue: risponde con un HTTP 302 perché sia il Browser
# (e non FastAPI) a raggiungere Keycloak e a mostrare la pagina di login.
# Le credenziali dell'utente passano quindi solo tra Browser e Keycloak.
# I numeri di step sono quelli del sequence diagram in "01 - intro.md".
@app.get("/login")
async def login():
    # Step 2 - Discovery: il client non deve conoscere a mano gli URL di
    # Keycloak, li legge dal documento .well-known/openid-configuration. Da qui
    # arrivano sia authorization_endpoint (usato qui) sia token_endpoint
    # (usato in exchange_code).
    discovery = await get_discovery()

    # Endpoint di Keycloak che mostra il form di login e rilascia il code.
    # Usa l'URL pubblico (es. localhost:8080 con port-forward) per il redirect del browser,
    # mentre il token_endpoint interno resta per le chiamate server-to-server.
    authorization_endpoint = discovery["authorization_endpoint"].replace(
        KEYCLOAK_BASE_URL, KEYCLOAK_PUBLIC_URL
    )

    # Step 3 - Parametri della Authorization Request. response_type=code
    # seleziona l'Authorization Code Flow; redirect_uri deve corrispondere
    # esattamente a quella registrata per il client, perché Keycloak la userà per
    # il redirect e per la validazione successiva; scope chiede il permesso su
    # documents:read, ed è quello che verrà verificato su /documents.
    # Da notare che il client_secret non compare qui: è un confidential client
    # e il secret non deve mai transitare dal Browser.
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }

    authorization_url = (
        f"{authorization_endpoint}?{urlencode(params)}"
    )

    # 302 verso Keycloak: il Browser esegue di persona l'Authorization Request.
    return RedirectResponse(
        url=authorization_url,
        status_code=302,
    )


# Step da 6 a 10 - Keycloak ha autenticato l'utente e redirizzato il Browser
# verso la redirect_uri con ?code=..., quindi FastAPI riceve l'Authorization
# Code. I numeri di step sono quelli del sequence diagram in "01 - intro.md".
@app.get("/callback", response_class=HTMLResponse)
async def callback(request: Request, code: str):
    # Step 6 - `code` è il parametro della query string valorizzato da Keycloak.
    # FastAPI lo dichiara come argomento della funzione, quindi lo legge
    # automaticamente; in una demo didattica si usa direttamente, in un'app
    # reale andrebbe validato insieme a `state`.
    #
    # Step 7 - Token Request: avviene qui, e non nel Browser. FastAPI scambia il
    # code con un Access Token chiamando direttamente il token_endpoint,
    # allegando grant_type=authorization_code, il code, la redirect_uri, lo scope
    # e le credenziali del client (client_id + client_secret).
    tokens = await exchange_code(code)

    # Step 8 e 9 - Keycloak verifica code, scadenza, client_secret e
    # corrispondenza della redirect_uri, poi emette i token e invalida il code,
    # che è monouso e non può essere riutilizzato. In caso di fallimento
    # risponde 400 invalid_grant e qui verrebbe sollevata un'eccezione.
    #
    # Step 10 - Token Response: qui finisce l'interazione con Keycloak. Da questo
    # momento in poi FastAPI fa anche da Resource Server: conserva il token in
    # una sessione lato server e apre al browser le risorse protette.
    access_token = tokens.get("access_token")

    session_id = secrets.token_urlsafe(16)
    SESSIONS[session_id] = access_token

    response = templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "access_token": access_token,
            "token_type": tokens.get("token_type"),
            "expires_in": tokens.get("expires_in"),
            "scopes": token_scopes(access_token),
            "resources": SCOPE_PER_RESOURCE,
        },
    )

    # Il cookie porta solo l'id della sessione, mai il token.
    response.set_cookie(
        key="sid",
        value=session_id,
        httponly=True,
        samesite="lax",
    )

    return response


# Autorizzazione: la risorsa è concessa solo se l'access token contiene lo scope
# che la mappa associa a quel path.
#
# I due casi sono distinti e la differenza è il punto della demo:
#   401 -> non c'è un token valido, quindi non sappiamo chi è l'utente
#   403 -> il token c'è ed è valido, ma non dà il permesso su questa risorsa
def render_resource(request: Request, path: str):
    access_token = access_token_of(request)

    if access_token is None:
        # In un'API questa sarebbe una risposta 401; qui si manda al login.
        return RedirectResponse(
            url="/login",
            status_code=302,
        )

    required = SCOPE_PER_RESOURCE[path]
    granted = token_scopes(access_token)

    response = templates.TemplateResponse(
        request=request,
        name="documents.html",
        context={
            "path": path,
            "required": required,
            "granted": granted,
            "allowed": required in granted,
        },
    )

    if required not in granted:
        # Token valido, permesso assente: l'utente è autenticato ma non
        # autorizzato su questa risorsa.
        response.status_code = 403

    return response


@app.get("/documents", response_class=HTMLResponse)
async def documents(request: Request):
    return render_resource(request, "/documents")


@app.get("/secret_documents", response_class=HTMLResponse)
async def secret_documents(request: Request):
    return render_resource(request, "/secret_documents")


# Endpoint di supporto: mostra il template del profilo con token vuoti.
@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    access_token = access_token_of(request)

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "access_token": access_token,
            "token_type": "Bearer" if access_token else None,
            "expires_in": None,
            "scopes": token_scopes(access_token) if access_token else [],
            "resources": SCOPE_PER_RESOURCE,
        },
    )
