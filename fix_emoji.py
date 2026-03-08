import json
import re

# Lade config.json
with open('config.json', 'r', encoding='utf-8-sig') as f:
    config = json.load(f)

# Ersetze in allen Vorlagen
for abteilung in config['abteilungen'].values():
    # Ersetze alle Varianten von "soll bitte mit [Leerzeichen] reagieren." mit "soll bitte mit ✅ reagieren."
    abteilung['vorlage'] = re.sub(r'soll bitte mit\s+reagieren\.', 'soll bitte mit ✅ reagieren.', abteilung['vorlage'])

# Speichere ohne BOM
with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print('Alle Emojis erfolgreich ersetzt!')
