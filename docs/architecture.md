# Techem DE Mieterportal – Home Assistant Integration

## Architektur-Übersicht

### Authentifizierung

Das deutsche Techem Mieterportal (mieter.techem.de) verwendet Azure AD B2C für die Benutzerauthentifizierung:

- **B2C Tenant**: `techemtenantportal.b2clogin.com`
- **Policy**: `b2c_1a_signin`
- **Client ID**: `e2c8cff8-17bc-41c7-89b6-5bee13c7f556`
- **Scope**: `https://techemtenantportal.onmicrosoft.com/eedo-be-consumption-service/access_as_user openid profile offline_access`
- **Response Type**: `code` (Authorization Code + PKCE)
- **Redirect URI**: `https://mieter.techem.de/auth`

### Auth Flow (programmatisch)

```
1. GET  /authorize          → Login-Seite laden, CSRF + TransID extrahieren
2. POST /SelfAsserted       → Credentials senden (Form-POST)
3. GET  /confirmed          → Auth Code im Redirect-Fragment erhalten
4. POST /oauth2/v2.0/token  → Access Token + Refresh Token erhalten
```

**Hinweis**: Die Authentifizierung läuft synchron via `requests` in einem Thread-Executor,
da aiohttp mit dem B2C SelfAsserted-Endpoint inkompatibel ist (HTTP 400 bei POST).
Dies ist ein übliches Muster in HA-Integrationen mit komplexem OAuth.

### Consumption API

Base URL: `https://mieter.techem.de/api`

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /v1/consumptions/residential-units/{id}/consumptions/periods?limit=60` | Verfügbare Abrechnungsperioden |
| `GET /v1/consumptions/residential-units/{id}/consumptions/{YYYY-MM}` | Verbrauchsdaten einer Periode |
| `GET /v1/consumptions/statistics/residential-units/{id}/consumptions/{period}/average` | Gebäudedurchschnitt |
| `GET /v1/consumptions/residential-units/{id}/consumptions?service=HEATING&unitOfMeasure=KWH&limit=36` | Verbrauchshistorie |

- Property-ID Format: `PRUN:HZ3:DEU01:<GUID>`
- Services: `HEATING`, `HOT_WATER`, `COLD_WATER`, `COOLING`
- Einheiten: `KWH`, `HCU`, `M3`

### Sensoren

Die Integration erstellt folgende Sensoren (je nach verfügbaren Daten):

| Sensor | Beschreibung | Einheit |
|--------|-------------|---------|
| `sensor.techem_heizung` | Heizungsverbrauch | kWh |
| `sensor.techem_heizung_durchschnitt` | Gebäudedurchschnitt Heizung | kWh |
| `sensor.techem_heizung_hcu` | Heizkostenverteiler-Einheiten | HCU |
| `sensor.techem_warmwasser` | Warmwasserverbrauch (falls vorhanden) | m³ |
| `sensor.techem_*_status` | Ablesstatus | – |

### Technologie-Stack

- Python 3.9+
- `requests` für Auth (Azure AD B2C, via Executor)
- `aiohttp` für API-Datenabrufe (async)
- HACS-kompatible Custom Integration
- Config Flow für Einrichtung über die HA-UI
