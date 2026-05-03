"""Techem DE Mieterportal API Client."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from functools import partial
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
import requests

from .const import (
    API_BASE_URL,
    API_CONSUMPTIONS_PATH,
    API_PERIODS_PATH,
    API_STATISTICS_PATH,
    AUTHORIZE_URL,
    B2C_DOMAIN,
    B2C_POLICY,
    CLIENT_ID,
    CONFIRMED_URL,
    REDIRECT_URI,
    SCOPE,
    SELF_ASSERTED_URL,
    TOKEN_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class TechemAuthError(Exception):
    """Authentication error."""


class TechemApiError(Exception):
    """API communication error."""


class TechemApiClient:
    """Client for the Techem DE Mieterportal."""

    def __init__(self, email: str, password: str, property_id: str = "") -> None:
        """Initialize the API client."""
        self._email = email
        self._password = password
        self._property_id = property_id
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    @property
    def property_id(self) -> str:
        """Return the property ID."""
        return self._property_id

    @property_id.setter
    def property_id(self, value: str) -> None:
        """Set the property ID."""
        self._property_id = value

    def _extract_property_id_from_token(self, token: str) -> str | None:
        """Extract the property ID from JWT token's rentalAgreements claim.

        The claim format is:
        {PropertyID};{PartyID};{StartDate};;{active}
        """
        try:
            payload_b64 = token.split(".")[1]
            # Add padding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            agreements = payload.get("rentalAgreements", [])
            if agreements:
                # Take the first active agreement
                for agreement in agreements:
                    parts = agreement.split(";")
                    if len(parts) >= 1 and parts[0]:
                        # Check if active (last field is "true")
                        if len(parts) >= 5 and parts[4].lower() == "true":
                            return parts[0]
                # Fallback: return first agreement's property_id regardless
                return agreements[0].split(";")[0]
        except (IndexError, json.JSONDecodeError, ValueError) as err:
            _LOGGER.debug("Could not extract property_id from token: %s", err)
        return None

    def _generate_pkce(self) -> tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge."""
        code_verifier = (
            base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
        )
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        return code_verifier, code_challenge

    def _authenticate_sync(self) -> dict:
        """
        Perform the full Azure AD B2C authentication flow synchronously.

        Uses the requests library which handles B2C's SelfAsserted endpoint
        correctly (aiohttp has incompatible HTTP behavior with this endpoint).

        Returns dict with access_token and refresh_token.
        """
        code_verifier, code_challenge = self._generate_pkce()

        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        })

        # Step 1: Load the authorization page
        auth_params = {
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "redirect_uri": REDIRECT_URI,
            "response_mode": "fragment",
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        resp = session.get(AUTHORIZE_URL, params=auth_params)
        if resp.status_code != 200:
            raise TechemAuthError(
                f"Login-Seite konnte nicht geladen werden: {resp.status_code}"
            )
        html = resp.text
        login_url = resp.url

        csrf_match = re.search(r'"csrf":"([^"]+)"', html)
        trans_match = re.search(r'"transId":"([^"]+)"', html)

        if not csrf_match or not trans_match:
            raise TechemAuthError(
                "CSRF/TransID konnte nicht ermittelt werden."
            )

        csrf_token = csrf_match.group(1)
        trans_id = trans_match.group(1)

        # Step 2: Submit credentials
        login_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf_token,
            "Referer": login_url,
            "Origin": f"https://{B2C_DOMAIN}",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        resp = session.post(
            SELF_ASSERTED_URL,
            params={"tx": trans_id, "p": B2C_POLICY},
            data={
                "signInName": self._email,
                "password": self._password,
                "request_type": "RESPONSE",
            },
            headers=login_headers,
            allow_redirects=False,
        )

        if resp.status_code != 200:
            raise TechemAuthError(
                f"Login fehlgeschlagen: Status {resp.status_code}"
            )

        # Check for B2C error in JSON response
        if resp.text.strip():
            try:
                sa_json = resp.json()
                if sa_json.get("status") == "400" or "error" in sa_json:
                    msg = sa_json.get("message", "Login fehlgeschlagen")
                    raise TechemAuthError(msg)
            except (json.JSONDecodeError, ValueError):
                pass

        # Step 3: Get the authorization code
        resp = session.get(
            CONFIRMED_URL,
            params={
                "rememberMe": "false",
                "csrf_token": csrf_token,
                "tx": trans_id,
                "p": B2C_POLICY,
            },
            headers={
                "Referer": login_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            allow_redirects=False,
        )

        redirect_url = resp.headers.get("Location", "")
        if not redirect_url:
            raise TechemAuthError(
                "Kein Redirect nach Login erhalten. "
                "Prüfe Credentials oder ob CAPTCHA aktiv ist."
            )

        # Parse authorization code from fragment
        if "#" in redirect_url:
            fragment = redirect_url.split("#", 1)[1]
            params = parse_qs(fragment)
        else:
            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)

        auth_code = params.get("code", [None])[0]
        if not auth_code:
            error = params.get("error", ["unknown"])[0]
            error_desc = params.get("error_description", [""])[0]
            raise TechemAuthError(
                f"Auth-Code nicht erhalten: {error} - {error_desc}"
            )

        # Step 4: Exchange code for tokens
        resp = session.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": code_verifier,
                "scope": SCOPE,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://mieter.techem.de",
                "Accept": "application/json",
            },
        )

        if resp.status_code != 200:
            raise TechemAuthError(
                f"Token-Abruf fehlgeschlagen: {resp.status_code} - {resp.text[:200]}"
            )

        tokens = resp.json()
        if not tokens.get("access_token"):
            raise TechemAuthError("Kein Access Token in der Response.")

        return tokens

    async def authenticate(self) -> str:
        """
        Perform the full Azure AD B2C authentication flow.

        Runs the synchronous requests-based auth in an executor to avoid
        blocking the event loop (standard HA pattern for complex OAuth).
        """
        _LOGGER.debug("Starting Techem B2C authentication")
        loop = asyncio.get_event_loop()
        tokens = await loop.run_in_executor(None, self._authenticate_sync)

        self._access_token = tokens["access_token"]
        self._refresh_token = tokens.get("refresh_token")

        # Auto-detect property_id from JWT if not manually configured
        if not self._property_id:
            detected_id = self._extract_property_id_from_token(self._access_token)
            if detected_id:
                self._property_id = detected_id
                _LOGGER.info(
                    "Auto-detected property_id from token: %s", detected_id
                )
            else:
                _LOGGER.warning("No property_id configured and could not detect from token")

        _LOGGER.info("Techem authentication successful")
        return self._access_token

    def _refresh_token_sync(self) -> dict:
        """Refresh the access token synchronously."""
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "scope": SCOPE,
            },
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://mieter.techem.de",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            raise TechemAuthError(f"Token refresh failed: {resp.status_code}")
        return resp.json()

    async def refresh_access_token(self) -> str:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            return await self.authenticate()

        try:
            loop = asyncio.get_event_loop()
            tokens = await loop.run_in_executor(None, self._refresh_token_sync)
            self._access_token = tokens["access_token"]
            if tokens.get("refresh_token"):
                self._refresh_token = tokens["refresh_token"]
            return self._access_token
        except (TechemAuthError, KeyError):
            _LOGGER.warning("Token refresh failed, re-authenticating")
            return await self.authenticate()

    async def get_consumption_data(self) -> dict:
        """
        Fetch consumption data from the Techem API.

        Returns a structured dict with consumption data per service type.
        """
        if not self._access_token:
            await self.authenticate()

        if not self._property_id:
            raise TechemApiError(
                "Property ID konnte nicht ermittelt werden. "
                "Bitte manuell in der Konfiguration angeben."
            )

        data = await self._fetch_current_period_data()
        return data

    async def _api_request(self, url: str) -> dict:
        """Make an authenticated API request."""
        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 401:
                    # Token expired, refresh and retry
                    await self.refresh_access_token()
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    async with session.get(
                        url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                    ) as retry_resp:
                        if retry_resp.status != 200:
                            raise TechemApiError(
                                f"API-Anfrage fehlgeschlagen nach Token-Refresh: {retry_resp.status}"
                            )
                        return await retry_resp.json()
                elif resp.status != 200:
                    raise TechemApiError(
                        f"API-Anfrage fehlgeschlagen: {resp.status}"
                    )
                return await resp.json()

    async def _fetch_periods(self) -> list[dict]:
        """Fetch available consumption periods."""
        url = (
            f"{API_BASE_URL}"
            f"{API_PERIODS_PATH.format(unit_id=self._property_id)}"
            f"?limit=60"
        )
        result = await self._api_request(url)
        return result.get("data", [])

    async def _fetch_period_consumption(self, period: str) -> list[dict]:
        """Fetch consumption data for a specific period (YYYY-MM)."""
        url = (
            f"{API_BASE_URL}"
            f"{API_CONSUMPTIONS_PATH.format(unit_id=self._property_id)}"
            f"/{period}"
        )
        result = await self._api_request(url)
        return result.get("data", [])

    async def _fetch_statistics(self, period: str) -> list[dict]:
        """Fetch building average statistics for a period."""
        url = (
            f"{API_BASE_URL}"
            f"{API_STATISTICS_PATH.format(unit_id=self._property_id, period=period)}"
        )
        result = await self._api_request(url)
        return result.get("data", [])

    async def _fetch_consumption_history(
        self, service: str, unit_of_measure: str, limit: int = 36
    ) -> list[dict]:
        """Fetch consumption history for a specific service and unit."""
        from urllib.parse import urlencode
        params = urlencode({
            "service": service,
            "unitOfMeasure": unit_of_measure,
            "limit": str(limit),
            "offset": "0",
        })
        url = (
            f"{API_BASE_URL}"
            f"{API_CONSUMPTIONS_PATH.format(unit_id=self._property_id)}"
            f"?{params}"
        )
        result = await self._api_request(url)
        return result.get("data", [])

    async def _fetch_current_period_data(self) -> dict:
        """Fetch consumption data for the most recent period."""
        # Get available periods
        periods = await self._fetch_periods()
        if not periods:
            raise TechemApiError("Keine Verbrauchsperioden verfügbar.")

        latest_period = periods[0]["period"]
        _LOGGER.debug("Latest period: %s", latest_period)

        # Get consumption for the latest period
        consumption = await self._fetch_period_consumption(latest_period)

        # Get building average for the latest period
        try:
            statistics = await self._fetch_statistics(latest_period)
        except TechemApiError:
            statistics = []

        # Fetch history for all available services/units
        history: dict[str, list[dict]] = {}
        try:
            for item in consumption:
                service = item.get("service", "")
                unit = item.get("unitOfMeasure", "")
                key = f"{service}_{unit}".lower()
                if key not in history:
                    hist_data = await self._fetch_consumption_history(
                        service, unit, limit=36
                    )
                    history[key] = hist_data
        except TechemApiError:
            _LOGGER.debug("History fetch failed, continuing without")

        # Structure the data
        result: dict = {
            "period": latest_period,
            "services": {},
        }

        for item in consumption:
            service = item.get("service", "").lower()
            unit = item.get("unitOfMeasure", "")
            amount = item.get("amount")
            status = item.get("status", "")

            if service not in result["services"]:
                result["services"][service] = {}

            result["services"][service][unit.lower()] = {
                "value": amount,
                "unit": unit,
                "status": status,
                "period": item.get("period"),
                "quality": item.get("quality"),
            }

        # Add statistics (building average)
        for stat in statistics:
            service = stat.get("service", "").lower()
            unit = stat.get("unitOfMeasure", "")
            if service in result["services"]:
                result["services"][service][f"{unit.lower()}_average"] = {
                    "value": stat.get("amount"),
                    "unit": unit,
                }

        # Add history per service/unit
        for key, hist_items in history.items():
            parts = key.split("_", 1)
            service = parts[0]
            unit = parts[1] if len(parts) > 1 else ""
            if service in result["services"]:
                hist_list = []
                for h in hist_items:
                    hist_list.append({
                        "period": h.get("period"),
                        "value": h.get("amount"),
                        "status": h.get("status"),
                    })
                result["services"][service][f"{unit}_history"] = hist_list

        # Add flat keys for easy access from sensors
        for service_name, service_data in result["services"].items():
            if "kwh" in service_data:
                result[service_name] = service_data["kwh"]["value"]
                result[f"{service_name}_unit"] = "kWh"
                result[f"{service_name}_status"] = service_data["kwh"]["status"]
            if "kwh_average" in service_data:
                result[f"{service_name}_average"] = service_data["kwh_average"]["value"]
            if "hcu" in service_data:
                result[f"{service_name}_hcu"] = service_data["hcu"]["value"]
            if "m3" in service_data:
                result[f"{service_name}_m3"] = service_data["m3"]["value"]

        return result

    async def test_connection(self) -> bool:
        """Test if authentication works."""
        try:
            await self.authenticate()
            return True
        except TechemAuthError:
            return False
