"""
Techem DE Mieterportal – Authentifizierungs-Test-Skript

Dieses Skript testet die Authentifizierung gegen das deutsche Techem Mieterportal
und ermittelt die API-Endpunkte für die Verbrauchsdaten.

Nutzung:
    python3 test_auth.py --email deine@email.de --password deinPasswort

Voraussetzungen:
    pip install requests
"""

import argparse
import hashlib
import base64
import os
import re
import json
import sys
from urllib.parse import urlencode, urlparse, parse_qs, unquote

import requests

# Azure AD B2C Configuration
B2C_TENANT = "techemtenantportal"
B2C_DOMAIN = f"{B2C_TENANT}.b2clogin.com"
B2C_TENANT_ID = f"{B2C_TENANT}.onmicrosoft.com"
B2C_POLICY = "b2c_1a_signin"
CLIENT_ID = "e2c8cff8-17bc-41c7-89b6-5bee13c7f556"
REDIRECT_URI = "https://mieter.techem.de/auth"
SCOPE = f"https://{B2C_TENANT_ID}/eedo-be-consumption-service/access_as_user openid profile offline_access"

BASE_URL = f"https://{B2C_DOMAIN}/{B2C_TENANT_ID}/{B2C_POLICY}"
AUTHORIZE_URL = f"{BASE_URL}/oauth2/v2.0/authorize"
TOKEN_URL = f"{BASE_URL}/oauth2/v2.0/token"
SELF_ASSERTED_URL = f"{BASE_URL}/SelfAsserted"
CONFIRMED_URL = f"{BASE_URL}/api/CombinedSigninAndSignup/confirmed"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return code_verifier, code_challenge


def extract_settings_json(html: str) -> dict:
    """Extract the SETTINGS JSON object from the B2C login page."""
    match = re.search(r"var\s+SETTINGS\s*=\s*(\{.*?\});\s*\n", html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def extract_csrf_token(html: str) -> str:
    """Extract CSRF token from the B2C login page."""
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'"csrf":"([^"]+)"', html)
    if match:
        return match.group(1)
    return ""


def extract_transid(html: str) -> str:
    """Extract transaction ID from the B2C page."""
    match = re.search(r'"transId":"([^"]+)"', html)
    if match:
        return match.group(1)
    match = re.search(r"transId=([^&\"]+)", html)
    if match:
        return match.group(1)
    return ""


def authenticate(email: str, password: str, verbose: bool = False) -> dict:
    """
    Perform the full Azure AD B2C authentication flow.
    Returns a dict with access_token, refresh_token, etc.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    })

    # Step 1: Generate PKCE
    code_verifier, code_challenge = generate_pkce()
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")
    nonce = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")

    if verbose:
        print(f"[1] PKCE generiert: challenge={code_challenge[:20]}...")

    # Step 2: Load the authorization page (login form)
    auth_params = {
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
        "response_mode": "fragment",
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "nonce": nonce,
        "state": state,
        "x-client-SKU": "msal.js.browser",
        "x-client-VER": "2.26.0",
        "client_info": "1",
    }

    if verbose:
        print(f"[2] Lade Login-Seite...")

    auth_response = session.get(
        AUTHORIZE_URL,
        params=auth_params,
        allow_redirects=True,
        timeout=30,
    )

    if auth_response.status_code != 200:
        raise RuntimeError(
            f"Login-Seite konnte nicht geladen werden: {auth_response.status_code}"
        )

    html = auth_response.text
    csrf_token = extract_csrf_token(html)
    trans_id = extract_transid(html)
    settings = extract_settings_json(html)

    if verbose:
        print(f"    CSRF: {csrf_token[:20]}..." if csrf_token else "    CSRF: NICHT GEFUNDEN")
        print(f"    TransID: {trans_id[:20]}..." if trans_id else "    TransID: NICHT GEFUNDEN")
        print(f"    Settings Keys: {list(settings.keys())[:5]}")

    if not csrf_token:
        # Try to find it in cookies
        for cookie in session.cookies:
            if "csrf" in cookie.name.lower():
                csrf_token = cookie.value
                if verbose:
                    print(f"    CSRF aus Cookie: {csrf_token[:20]}...")
                break

    if not trans_id:
        raise RuntimeError("Transaction ID konnte nicht ermittelt werden.")

    # Step 3: Submit credentials via SelfAsserted endpoint
    if verbose:
        print(f"[3] Sende Credentials...")

    self_asserted_params = {
        "tx": trans_id,
        "p": B2C_POLICY,
    }

    login_payload = {
        "signInName": email,
        "password": password,
        "request_type": "RESPONSE",
    }

    login_headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-TOKEN": csrf_token,
        "Referer": auth_response.url,
        "Origin": f"https://{B2C_DOMAIN}",
    }

    self_asserted_response = session.post(
        SELF_ASSERTED_URL,
        params=self_asserted_params,
        data=login_payload,
        headers=login_headers,
        allow_redirects=False,
        timeout=30,
    )

    if verbose:
        print(f"    Status: {self_asserted_response.status_code}")
        print(f"    Response: {self_asserted_response.text[:200]}")

    if self_asserted_response.status_code != 200:
        raise RuntimeError(
            f"SelfAsserted fehlgeschlagen: {self_asserted_response.status_code} - "
            f"{self_asserted_response.text[:200]}"
        )

    # Check for error in response
    try:
        sa_json = self_asserted_response.json()
        if sa_json.get("status") == "400" or sa_json.get("message"):
            raise RuntimeError(f"Login fehlgeschlagen: {sa_json.get('message', 'Unbekannter Fehler')}")
    except (json.JSONDecodeError, ValueError):
        pass

    # Step 4: Get the authorization code via confirmed endpoint
    if verbose:
        print(f"[4] Rufe confirmed Endpunkt auf...")

    confirmed_params = {
        "rememberMe": "false",
        "csrf_token": csrf_token,
        "tx": trans_id,
        "p": B2C_POLICY,
    }

    confirmed_response = session.get(
        CONFIRMED_URL,
        params=confirmed_params,
        headers={
            "Referer": auth_response.url,
            "X-Requested-With": "XMLHttpRequest",
        },
        allow_redirects=False,
        timeout=30,
    )

    if verbose:
        print(f"    Status: {confirmed_response.status_code}")
        if confirmed_response.headers.get("Location"):
            print(f"    Redirect: {confirmed_response.headers['Location'][:100]}...")

    # The redirect URL contains the authorization code in the fragment
    redirect_url = confirmed_response.headers.get("Location", "")

    if not redirect_url:
        raise RuntimeError(
            "Kein Redirect nach Bestätigung erhalten. "
            "Mögliche Ursache: falsche Credentials oder CAPTCHA."
        )

    # Parse the authorization code from fragment or query
    # Response mode is "fragment", so the code is after #
    if "#" in redirect_url:
        fragment = redirect_url.split("#", 1)[1]
        params = parse_qs(fragment)
    else:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)

    auth_code = params.get("code", [None])[0]

    if not auth_code:
        error = params.get("error", [None])[0]
        error_desc = params.get("error_description", [None])[0]
        raise RuntimeError(
            f"Kein Auth-Code erhalten. Error: {error}, Description: {error_desc}"
        )

    if verbose:
        print(f"    Auth-Code erhalten: {auth_code[:20]}...")

    # Step 5: Exchange authorization code for tokens
    if verbose:
        print(f"[5] Tausche Code gegen Token...")

    token_payload = {
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
        "scope": SCOPE,
    }

    token_response = session.post(
        TOKEN_URL,
        data=token_payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://mieter.techem.de",
        },
        timeout=30,
    )

    if token_response.status_code != 200:
        raise RuntimeError(
            f"Token-Abruf fehlgeschlagen: {token_response.status_code} - "
            f"{token_response.text[:300]}"
        )

    tokens = token_response.json()

    if verbose:
        print(f"    Access Token: {tokens.get('access_token', '')[:30]}...")
        print(f"    Token Type: {tokens.get('token_type')}")
        print(f"    Expires In: {tokens.get('expires_in')}s")
        print(f"    Scope: {tokens.get('scope')}")
        if tokens.get("refresh_token"):
            print(f"    Refresh Token: vorhanden")

    return tokens


def discover_api(access_token: str, verbose: bool = False) -> dict:
    """
    Try to discover the consumption API endpoints using the access token.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Accept-Language": "de-DE,de;q=0.9",
    })

    # Decode the JWT to find audience/issuer info
    token_parts = access_token.split(".")
    if len(token_parts) >= 2:
        # Decode payload (add padding)
        payload = token_parts[1]
        payload += "=" * (4 - len(payload) % 4)
        try:
            token_data = json.loads(base64.urlsafe_b64decode(payload))
            if verbose:
                print(f"\n[API Discovery] Token-Payload:")
                print(f"    aud: {token_data.get('aud')}")
                print(f"    iss: {token_data.get('iss')}")
                print(f"    sub: {token_data.get('sub')}")
                print(f"    scp: {token_data.get('scp')}")
                print(f"    exp: {token_data.get('exp')}")
        except Exception as e:
            if verbose:
                print(f"    Token decode error: {e}")
            token_data = {}

    # Common API base URLs to try
    api_candidates = [
        "https://eedo-be-consumption-service.techem.com",
        "https://api.mieter.techem.de",
        "https://mieter.techem.de/api",
        "https://eedo-be.techem.com",
        "https://consumption-api.techem.de",
    ]

    # Try common endpoints
    endpoints_to_try = [
        "/consumptions",
        "/api/consumptions",
        "/v1/consumptions",
        "/api/v1/consumptions",
        "/properties",
        "/api/properties",
        "/v1/properties",
        "/units",
        "/api/units",
    ]

    results = {}

    for base in api_candidates:
        for endpoint in endpoints_to_try:
            url = f"{base}{endpoint}"
            try:
                resp = session.get(url, timeout=10)
                if resp.status_code != 404:
                    results[url] = {
                        "status": resp.status_code,
                        "content_type": resp.headers.get("Content-Type", ""),
                        "body_preview": resp.text[:200],
                    }
                    if verbose:
                        print(f"    {url} -> {resp.status_code}")
            except requests.exceptions.RequestException:
                pass

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Techem DE Mieterportal – Auth Test"
    )
    parser.add_argument("--email", required=True, help="Techem Login E-Mail")
    parser.add_argument("--password", required=True, help="Techem Login Passwort")
    parser.add_argument("--verbose", "-v", action="store_true", help="Ausführliche Ausgabe")
    parser.add_argument(
        "--discover-api", action="store_true",
        help="API-Endpunkte nach Login erkunden"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Techem DE Mieterportal – Authentifizierungs-Test")
    print("=" * 60)

    try:
        tokens = authenticate(args.email, args.password, verbose=args.verbose)
        print("\n✅ Authentifizierung erfolgreich!")
        print(f"   Token Type: {tokens.get('token_type')}")
        print(f"   Expires In: {tokens.get('expires_in')}s")
        print(f"   Scopes: {tokens.get('scope')}")

        if args.discover_api and tokens.get("access_token"):
            print("\n" + "=" * 60)
            print("API-Discovery")
            print("=" * 60)
            api_results = discover_api(tokens["access_token"], verbose=args.verbose)
            if api_results:
                print("\nGefundene Endpunkte:")
                for url, info in api_results.items():
                    print(f"  {url}")
                    print(f"    Status: {info['status']}")
                    print(f"    Content-Type: {info['content_type']}")
                    print(f"    Body: {info['body_preview'][:100]}")
            else:
                print("\nKeine API-Endpunkte gefunden. Manuelle Untersuchung nötig.")
                print("Tipp: Öffne mieter.techem.de im Browser, logge dich ein,")
                print("      und prüfe in den Developer Tools (F12 → Network Tab)")
                print("      welche API-Calls gemacht werden.")

    except RuntimeError as e:
        print(f"\n❌ Fehler: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(0)


if __name__ == "__main__":
    main()
