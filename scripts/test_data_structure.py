"""End-to-end test of the Techem API using requests (sync) to verify data structure."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from test_auth import authenticate

from urllib.parse import urlencode

API_BASE_URL = "https://mieter.techem.de/api"

import requests

email = os.environ.get("TECHEM_EMAIL")
password = os.environ.get("TECHEM_PASSWORD")
UNIT_ID = os.environ.get("TECHEM_PROPERTY_ID")

if not all([email, password, UNIT_ID]):
    print("Bitte Umgebungsvariablen setzen:")
    print("  export TECHEM_EMAIL='deine@email.de'")
    print("  export TECHEM_PASSWORD='deinPasswort'")
    print("  export TECHEM_PROPERTY_ID='PRUN:HZ3:...'")
    sys.exit(1)

print("=" * 70)
print("TECHEM API - FULL DATA STRUCTURE TEST")
print("=" * 70)

print("\n[1] Authentifizierung...")
tokens = authenticate(email, password, verbose=False)
token = tokens["access_token"]
print(f"    ✅ Token erhalten")

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

# Test 1: Get periods
print("\n[2] Verfügbare Perioden...")
url = f"{API_BASE_URL}/v1/consumptions/residential-units/{UNIT_ID}/consumptions/periods?limit=60"
resp = requests.get(url, headers=headers, timeout=30)
periods_data = resp.json()
periods = periods_data["data"]
print(f"    ✅ {len(periods)} Perioden (neueste: {periods[0]['period']}, älteste: {periods[-1]['period']})")

# Test 2: Get latest period consumption
latest = periods[0]["period"]
print(f"\n[3] Verbrauch für aktuelle Periode ({latest})...")
url = f"{API_BASE_URL}/v1/consumptions/residential-units/{UNIT_ID}/consumptions/{latest}"
resp = requests.get(url, headers=headers, timeout=30)
consumption = resp.json()
print(f"    ✅ {consumption['count']} Einträge:")
for item in consumption["data"]:
    print(f"      {item['service']} / {item['unitOfMeasure']}: {item['amount']} (Status: {item['status']})")

# Test 3: Get statistics
print(f"\n[4] Gebäudedurchschnitt für {latest}...")
url = f"{API_BASE_URL}/v1/consumptions/statistics/residential-units/{UNIT_ID}/consumptions/{latest}/average"
resp = requests.get(url, headers=headers, timeout=30)
if resp.status_code == 200:
    stats = resp.json()
    print(f"    ✅ {stats.get('count', 0)} Einträge:")
    for item in stats.get("data", []):
        print(f"      {item['service']} / {item['unitOfMeasure']}: {item['amount']}")
else:
    print(f"    ⚠️ Keine Statistik verfügbar (Status: {resp.status_code})")

# Test 4: Full history HEATING KWH
print(f"\n[5] Historie HEATING KWH (letzte 12 Monate)...")
params = urlencode({"service": "HEATING", "unitOfMeasure": "KWH", "limit": "12", "offset": "0"})
url = f"{API_BASE_URL}/v1/consumptions/residential-units/{UNIT_ID}/consumptions?{params}"
resp = requests.get(url, headers=headers, timeout=30)
history = resp.json()
print(f"    ✅ {history['count']} Einträge:")
for item in history["data"][:12]:
    print(f"      {item['period']}: {item['amount']:>8.1f} kWh")

# Test 5: Try HOT_WATER and COLD_WATER
print(f"\n[6] Prüfe weitere Services...")
for service in ["HOT_WATER", "COLD_WATER", "COOLING"]:
    for unit in ["KWH", "M3"]:
        params = urlencode({"service": service, "unitOfMeasure": unit, "limit": "3", "offset": "0"})
        url = f"{API_BASE_URL}/v1/consumptions/residential-units/{UNIT_ID}/consumptions?{params}"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0 or data.get("totalCount", 0) > 0:
                print(f"    ✅ {service}/{unit}: {data['count']} Einträge")
                for item in data["data"][:2]:
                    print(f"       {item['period']}: {item.get('amount')}")
            else:
                print(f"    ⚪ {service}/{unit}: Keine Daten")
        else:
            print(f"    ⚪ {service}/{unit}: Status {resp.status_code}")

# Structure the result the same way techem_api.py does
print(f"\n[7] Simuliere get_consumption_data() Ergebnis...")
url = f"{API_BASE_URL}/v1/consumptions/residential-units/{UNIT_ID}/consumptions/{latest}"
resp = requests.get(url, headers=headers, timeout=30)
consumption_raw = resp.json()["data"]

url = f"{API_BASE_URL}/v1/consumptions/statistics/residential-units/{UNIT_ID}/consumptions/{latest}/average"
resp = requests.get(url, headers=headers, timeout=30)
statistics_raw = resp.json()["data"] if resp.status_code == 200 else []

result = {"period": latest, "services": {}}
for item in consumption_raw:
    service = item["service"].lower()
    unit = item["unitOfMeasure"].lower()
    if service not in result["services"]:
        result["services"][service] = {}
    result["services"][service][unit] = {
        "value": item["amount"],
        "unit": item["unitOfMeasure"],
        "status": item["status"],
        "quality": item.get("quality"),
    }
for stat in statistics_raw:
    service = stat["service"].lower()
    unit = stat["unitOfMeasure"].lower()
    if service in result["services"]:
        result["services"][service][f"{unit}_average"] = {
            "value": stat["amount"],
            "unit": stat["unitOfMeasure"],
        }
# Flat keys
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

print(f"\n    Result structure:")
print(f"    {json.dumps(result, indent=2, ensure_ascii=False)}")

print("\n" + "=" * 70)
print("TEST ABGESCHLOSSEN ✅")
print("=" * 70)
