"""Constants for the Techem DE integration."""

DOMAIN = "techem_de"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_PROPERTY_ID = "property_id"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 360  # 6 hours in minutes

# Azure AD B2C Configuration
B2C_TENANT = "techemtenantportal"
B2C_DOMAIN = f"{B2C_TENANT}.b2clogin.com"
B2C_TENANT_ID = f"{B2C_TENANT}.onmicrosoft.com"
B2C_POLICY = "b2c_1a_signin"
CLIENT_ID = "e2c8cff8-17bc-41c7-89b6-5bee13c7f556"
REDIRECT_URI = "https://mieter.techem.de/auth"
SCOPE = f"https://{B2C_TENANT_ID}/eedo-be-consumption-service/access_as_user openid profile offline_access"

BASE_B2C_URL = f"https://{B2C_DOMAIN}/{B2C_TENANT_ID}/{B2C_POLICY}"
AUTHORIZE_URL = f"{BASE_B2C_URL}/oauth2/v2.0/authorize"
TOKEN_URL = f"{BASE_B2C_URL}/oauth2/v2.0/token"
SELF_ASSERTED_URL = f"{BASE_B2C_URL}/SelfAsserted"
CONFIRMED_URL = f"{BASE_B2C_URL}/api/CombinedSigninAndSignup/confirmed"

# Techem Consumption API
API_BASE_URL = "https://mieter.techem.de/api"
API_CONSUMPTIONS_PATH = "/v1/consumptions/residential-units/{unit_id}/consumptions"
API_PERIODS_PATH = "/v1/consumptions/residential-units/{unit_id}/consumptions/periods"
API_STATISTICS_PATH = "/v1/consumptions/statistics/residential-units/{unit_id}/consumptions/{period}/average"

# Service types returned by the API
SERVICE_HEATING = "HEATING"
SERVICE_HOT_WATER = "HOT_WATER"
SERVICE_COLD_WATER = "COLD_WATER"
SERVICE_COOLING = "COOLING"

# Unit of measure types
UNIT_KWH = "KWH"
UNIT_HCU = "HCU"
UNIT_M3 = "M3"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
