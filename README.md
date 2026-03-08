# Discord Akademie Bot

Ein Discord-Bot zur Verwaltung von Ausbildungsankündigungen und Auswertungen für verschiedene Abteilungen einer Akademie.

## Features

✅ **Ausbildungen ankündigen**
- Slash Command `/ankuendigen` mit allen wichtigen Parametern
- Automatische Emoji-Reaktionen auf Ankündigungen
- Individuelle Textvorlagen pro Abteilung
- Flexible Konfiguration von Zielkanälen

✅ **Auswertungen verwalten**
- Teilnehmer mit Punktzahlen erfassen
- Automatische Kategorisierung (Bestanden/Nicht bestanden)
- Übersichtliche Auswertungsnachrichten

✅ **Einfache Erweiterbarkeit**
- Neue Abteilungen ohne Code-Änderungen hinzufügen
- Alle Einstellungen zentral in `config.json`
- Gut strukturierter, kommentierter Code

## Installation

### 1. Voraussetzungen

- Python 3.8 oder höher
- pip (Python Package Manager)
- Ein Discord-Bot-Account mit Token ([Bot erstellen](https://discord.com/developers/applications))

### 2. Projekt einrichten

Klone oder lade das Projekt herunter und öffne ein Terminal im Projektordner:

```bash
cd "c:\Users\JinJonas\Discord Projekte\Akademie"
```

### 3. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

### 4. Umgebungsvariablen konfigurieren

Erstelle eine `.env` Datei im Projektordner:

```bash
copy .env.example .env
```

Öffne die `.env` Datei und trage deinen Bot-Token ein:

```
DISCORD_TOKEN=dein_bot_token_hier
```

### 5. Konfiguration anpassen

Öffne `config.json` und passe die Kanal-IDs an:

```json
{
  "abteilungen": {
    "Polizei": {
      "kanal_id": "DEINE_KANAL_ID_HIER",
      "emoji": "🚔",
      "vorlage": "..."
    }
  },
  "auswertungskanal_id": "DEINE_AUSWERTUNGSKANAL_ID",
  "mindestpunktzahl": 50
}
```

**So findest du Kanal-IDs:**
1. Aktiviere den Entwicklermodus in Discord (Einstellungen → Erweitert → Entwicklermodus)
2. Rechtsklick auf einen Kanal → "ID kopieren"

## Bot starten

```bash
python bot.py
```

Wenn alles korrekt konfiguriert ist, siehst du:

```
<BotName> ist online!
Bot läuft als: <BotName> (ID: ...)
------
3 Slash Command(s) synchronisiert
```

## Commands

### `/ankuendigen`

Kündigt eine neue Ausbildung an.

**Parameter:**
- `bereich` *(erforderlich)*: Abteilung (Polizei, Feuerwehr, etc.)
- `datum` *(erforderlich)*: Datum (z.B. "20.01.2026")
- `uhrzeit` *(erforderlich)*: Uhrzeit (z.B. "18:00 Uhr")
- `host` *(erforderlich)*: Host der Ausbildung (@User)
- `cohost` *(optional)*: Co-Host (@User)
- `helfer` *(optional)*: Helfer (@User)

**Beispiel:**
```
/ankuendigen bereich:Polizei datum:20.01.2026 uhrzeit:18:00 Uhr host:@Max
```

**Was passiert:**
1. Die Nachricht wird im konfigurierten Kanal der Abteilung gepostet
2. Der Bot setzt automatisch das Emoji als Reaktion
3. Die Ausbildung erhält eine eindeutige ID und wird gespeichert

### `/auswertung`

Fügt einen Teilnehmer zur Auswertung hinzu.

**Parameter:**
- `ausbildung_id` *(erforderlich)*: ID der Ausbildung
- `teilnehmer` *(erforderlich)*: Teilnehmer (@User)
- `punktzahl` *(erforderlich)*: Erreichte Punktzahl

**Beispiel:**
```
/auswertung ausbildung_id:1 teilnehmer:@Anna punktzahl:75
```

**Mehrere Teilnehmer:**
Wiederhole den Command einfach mit unterschiedlichen Teilnehmern.

### `/auswertung_abschliessen`

Schließt die Auswertung ab und postet sie im Auswertungskanal.

**Parameter:**
- `ausbildung_id` *(erforderlich)*: ID der Ausbildung

**Beispiel:**
```
/auswertung_abschliessen ausbildung_id:1
```

**Ausgabe:**
```
📊 Auswertung der Ausbildung

Bereich: Polizei
Datum: 20.01.2026
Uhrzeit: 18:00 Uhr

✅ Bestanden:
• @Anna - 75 Punkte
• @Max - 60 Punkte

❌ Nicht bestanden:
• @Tom - 45 Punkte

Hochachtungsvoll
@Host
```

## Konfiguration erweitern

### Neue Abteilung hinzufügen

Öffne `config.json` und füge eine neue Abteilung hinzu:

```json
"Marine": {
  "kanal_id": "123456789012345678",
  "emoji": "⚓",
  "vorlage": "📢 **Ausbildungsankündigung – Marine**\n\n📅 Datum: {datum}\n🕐 Uhrzeit: {uhrzeit}\n👤 Host: {host}\n👥 Co-Host: {cohost}\n🤝 Helfer: {helfer}\n\nBitte reagiert mit ⚓ wenn ihr teilnehmen möchtet!"
}
```

### Textvorlage anpassen

Die Vorlage kann beliebig formatiert werden. Verfügbare Platzhalter:
- `{datum}` - Datum der Ausbildung
- `{uhrzeit}` - Uhrzeit der Ausbildung
- `{host}` - Mention des Hosts
- `{cohost}` - Mention des Co-Hosts (oder "Nicht zugewiesen")
- `{helfer}` - Mention des Helfers (oder "Nicht zugewiesen")

### Mindestpunktzahl ändern

In `config.json`:

```json
"mindestpunktzahl": 50
```

## Datenspeicherung

Alle Ausbildungen werden in `ausbildungen.json` gespeichert. Diese Datei wird automatisch erstellt.

**Backup erstellen:**
```bash
copy ausbildungen.json ausbildungen_backup.json
```

## Troubleshooting

### Bot reagiert nicht auf Commands

1. Prüfe, ob die Commands synchronisiert wurden (siehe Konsolenausgabe)
2. Warte 1-2 Minuten nach dem Start
3. Stelle sicher, dass der Bot die nötigen Berechtigungen hat

### Kanal nicht gefunden

1. Überprüfe die Kanal-IDs in `config.json`
2. Stelle sicher, dass der Bot Zugriff auf die Kanäle hat
3. IDs müssen als Strings in Anführungszeichen stehen

### Keine Berechtigung zum Senden

Der Bot benötigt folgende Berechtigungen:
- Nachrichten senden
- Reaktionen hinzufügen
- Slash Commands verwenden

## Projektstruktur

```
Akademie/
├── bot.py                  # Haupt-Bot-Datei mit allen Commands
├── data_manager.py         # Datenverwaltung für Ausbildungen
├── config.json            # Konfiguration (Abteilungen, Kanäle, etc.)
├── requirements.txt       # Python-Abhängigkeiten
├── .env                   # Bot-Token (nicht committen!)
├── .env.example          # Beispiel für .env
├── ausbildungen.json     # Datenspeicher (wird automatisch erstellt)
└── README.md             # Diese Datei
```

## Technische Details

- **Discord.py Version:** 2.3.0+
- **Python Version:** 3.8+
- **Datenspeicherung:** JSON
- **Command-System:** app_commands (Slash Commands)

## Bot-Berechtigungen

Beim Einladen des Bots müssen folgende Berechtigungen aktiviert sein:

**Bot Permissions:**
- Read Messages/View Channels
- Send Messages
- Add Reactions
- Use Slash Commands

**OAuth2 Scopes:**
- `bot`
- `applications.commands`

## Support

Bei Fragen oder Problemen:
1. Überprüfe die Konsolenausgabe auf Fehlermeldungen
2. Stelle sicher, dass alle Kanal-IDs korrekt sind
3. Prüfe die Bot-Berechtigungen in Discord

## Lizenz

Dieses Projekt ist für den internen Gebrauch der Akademie bestimmt.

---

**Entwickelt für die Discord Akademie**
