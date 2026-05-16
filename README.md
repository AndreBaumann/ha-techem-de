# Techem DE Mieterportal – Home Assistant Integration

Custom Integration für das deutsche [Techem Mieterportal](https://mieter.techem.de) zur Abfrage von Heizungs- und Warmwasserverbrauchsdaten in Home Assistant.

## Voraussetzungen

- Home Assistant 2024.1.0 oder neuer
- HACS (für einfache Installation)
- Techem Mieterportal Zugangsdaten (E-Mail + Passwort)
- Property-ID wird **automatisch erkannt** (optional manuell konfigurierbar)

## Installation

### Option 1: HACS (empfohlen)

1. HACS öffnen → Integrationen → Benutzerdefinierte Repositories
2. Repository-URL eingeben: `https://github.com/andrebaumann/ha-techem-de`
3. Kategorie: `Integration`
4. Installieren und Home Assistant neu starten
5. Einstellungen → Geräte & Dienste → Integration hinzufügen → "Techem DE" suchen

### Option 2: Manuell

1. Den Ordner `custom_components/techem_de` nach `/config/custom_components/techem_de` kopieren
2. Home Assistant neu starten
3. Integration über die UI einrichten

## Einrichtung

### Integration konfigurieren

1. Home Assistant → Einstellungen → Geräte & Dienste
2. "Integration hinzufügen" → "Techem DE Mieterportal"
3. E-Mail und Passwort eingeben
4. Property-ID wird automatisch aus dem Login-Token erkannt – das Feld kann leer bleiben
5. Aktualisierungsintervall wählen (Standard: 360 Min / 6 Stunden)

### Property-ID manuell ermitteln (Fallback)

Falls die automatische Erkennung nicht funktioniert, findest du deine Property-ID in der URL nach dem Login auf mieter.techem.de:
```
https://mieter.techem.de/de/PRUN:HZ3:DEU01:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/consumptions
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                              Das ist deine Property-ID
```

## Sensoren

| Sensor | Beschreibung | Einheit |
|--------|-------------|---------|
| Techem Heizung | Aktueller Monatsverbrauch | kWh |
| Techem Heizung Energieverbrauch (Dashboard) | Kumulierter Gesamtverbrauch für das HA Energie-Dashboard | kWh |
| Techem Heizung Gebäudedurchschnitt | Gebäudedurchschnitt zum Vergleich | kWh |
| Techem Heizung HCU | Heizkostenverteiler-Einheiten | HCU |
| Techem Warmwasser Volumen | Warmwasserverbrauch (falls vorhanden) | m³ |

### Energie-Dashboard

Der Sensor **"Techem Heizung Energieverbrauch (Dashboard)"** ist speziell für das Home Assistant Energie-Dashboard konzipiert:

1. Einstellungen → Dashboards → Energie
2. **Gasverbrauch** → Sensor hinzufügen
3. Den Sensor `Techem Heizung Energieverbrauch (Dashboard)` auswählen

Dieser Sensor summiert alle historischen Monatsverbräuche zu einem stetig steigenden Zählerstand auf. So kann das Energie-Dashboard den Verbrauch korrekt darstellen. Beim ersten Start wird der Gesamtverbrauch aus den letzten 26 Monaten berechnet.

### Historische Daten importieren

Um die Verbrauchsdaten nachträglich ins Energie-Dashboard zu laden (alle bei Techem verfügbaren Monate):

1. Entwicklerwerkzeuge → Aktionen
2. Aktion `techem_de.import_history` auswählen
3. "Aktion ausführen" klicken

Die historischen Monatswerte werden als kumulative Statistik importiert. Danach zeigt das Energie-Dashboard auch den Verbrauch vergangener Monate an. Dieser Dienst muss nur **einmalig** aufgerufen werden.

> **Hinweis:** Wird der Import erneut ausgeführt, werden die bisherigen Statistikdaten automatisch gelöscht und sauber neu importiert.

### Historische Daten löschen

Um die importierten Langzeitstatistiken zu entfernen:

1. Entwicklerwerkzeuge → Aktionen
2. Aktion `techem_de.clear_history` auswählen
3. "Aktion ausführen" klicken

## Bekannte Einschränkungen

- **Azure AD B2C**: Die Authentifizierung nutzt den programmatischen Login-Flow. Falls Techem CAPTCHA aktiviert, kann der Login fehlschlagen.
- **Keine offizielle API**: Diese Integration basiert auf Reverse Engineering des Web-Portals. Endpunkte können sich bei Updates ändern.
- **Rate Limiting**: Das Aktualisierungsintervall sollte nicht unter 60 Minuten gesetzt werden.
- **Monatliche Auflösung**: Techem liefert Verbrauchsdaten nur monatlich. Der Dashboard-Sensor aktualisiert sich erst wenn ein neuer Monat in der API erscheint.

## Troubleshooting

### "Authentifizierung fehlgeschlagen"
- Prüfe E-Mail und Passwort
- Teste ob du dich manuell auf https://mieter.techem.de einloggen kannst
- Azure AD B2C könnte CAPTCHA erfordern → Logge dich erst manuell ein

### Logs aktivieren
```yaml
logger:
  default: warning
  logs:
    custom_components.techem_de: debug
```

## Projektstruktur

```
custom_components/techem_de/
├── __init__.py          # Integration Setup + DataUpdateCoordinator
├── config_flow.py       # UI-Konfiguration
├── const.py             # Konstanten (B2C Config, API Pfade)
├── manifest.json        # HA Manifest
├── sensor.py            # Sensor-Entitäten
├── techem_api.py        # API Client (Auth via requests + API via aiohttp)
└── translations/
    ├── de.json
    └── en.json

scripts/
├── test_auth.py             # Standalone Auth-Test
├── test_data_structure.py   # Datenstruktur-Test
└── test_integration.py      # End-to-End Integrationstest
```

## Lizenz

MIT
