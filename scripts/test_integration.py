"""End-to-end test of the Techem API client (TechemApiClient)."""
import asyncio
import importlib.util
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

# Load modules without triggering homeassistant imports
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

spec = importlib.util.spec_from_file_location(
    "custom_components.techem_de.const",
    os.path.join(_base, "custom_components", "techem_de", "const.py"),
)
const_mod = importlib.util.module_from_spec(spec)
sys.modules["custom_components.techem_de.const"] = const_mod
spec.loader.exec_module(const_mod)

spec = importlib.util.spec_from_file_location(
    "custom_components.techem_de.techem_api",
    os.path.join(_base, "custom_components", "techem_de", "techem_api.py"),
)
api_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api_mod)

TechemApiClient = api_mod.TechemApiClient


async def main():
    email = os.environ.get("TECHEM_EMAIL")
    password = os.environ.get("TECHEM_PASSWORD")
    property_id = os.environ.get("TECHEM_PROPERTY_ID")

    if not all([email, password, property_id]):
        print("Bitte Umgebungsvariablen setzen:")
        print("  export TECHEM_EMAIL='deine@email.de'")
        print("  export TECHEM_PASSWORD='deinPasswort'")
        print("  export TECHEM_PROPERTY_ID='PRUN:HZ3:...'")
        sys.exit(1)

    print("=" * 60)
    print("TECHEM API CLIENT - END-TO-END TEST")
    print("=" * 60)

    client = TechemApiClient(email, password, property_id)

    # Test authentication
    print("\n[1] Authentifizierung...")
    try:
        token = await client.authenticate()
        print(f"    ✅ Token erhalten (len={len(token)})")
    except Exception as e:
        print(f"    ❌ Fehler: {e}")
        return

    # Test token refresh
    print("\n[2] Token-Refresh...")
    try:
        new_token = await client.refresh_access_token()
        print(f"    ✅ Token refreshed (len={len(new_token)})")
    except Exception as e:
        print(f"    ❌ Fehler: {e}")

    # Test get_consumption_data
    print("\n[3] Verbrauchsdaten abrufen...")
    try:
        data = await client.get_consumption_data()
        print(f"    ✅ Daten erhalten!")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"    ❌ Fehler: {e}")

    # Test bad credentials
    print("\n[4] Falsche Credentials testen...")
    bad_client = TechemApiClient("bad@example.com", "wrong", "")
    result = await bad_client.test_connection()
    print(f"    ✅ test_connection returned: {result} (expected: False)")

    print("\n" + "=" * 60)
    print("ALLE TESTS ABGESCHLOSSEN")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
