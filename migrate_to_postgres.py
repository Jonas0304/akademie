"""
Einmaliges Migrations-Skript: JSON-Backup → PostgreSQL (Railway)

Verwendung:
    1. Setze DATABASE_URL als Umgebungsvariable (aus Railway kopieren)
    2. python migrate_to_postgres.py
"""
import json
import os
import sys
import psycopg2

DATABASE_URL = os.getenv('DATABASE_URL')
BACKUP_FILE = os.path.join("discloud", "backup", "1768943042880", "ausbildungen.json")

if not DATABASE_URL:
    print("❌ DATABASE_URL ist nicht gesetzt!")
    print("Setze sie so (PowerShell):")
    print('  $env:DATABASE_URL = "postgresql://user:pass@host:port/dbname"')
    print("Die URL findest du in Railway → PostgreSQL → Variables → DATABASE_URL")
    sys.exit(1)

# JSON laden
with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

ausbildungen = data.get("ausbildungen", {})
print(f"📂 {len(ausbildungen)} Ausbildungen gefunden im Backup.")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Tabellen sicherstellen
cur.execute("""
    CREATE TABLE IF NOT EXISTS ausbildungen (
        id SERIAL PRIMARY KEY,
        bereich TEXT NOT NULL,
        datum TEXT NOT NULL,
        uhrzeit TEXT NOT NULL,
        host TEXT NOT NULL,
        cohost TEXT DEFAULT 'Nicht zugewiesen',
        helfer TEXT DEFAULT 'Nicht zugewiesen',
        channel_id BIGINT NOT NULL,
        message_id BIGINT NOT NULL,
        archiviert BOOLEAN DEFAULT FALSE,
        ausgewertet BOOLEAN DEFAULT FALSE,
        erstellt_am TIMESTAMP DEFAULT NOW()
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS teilnehmer (
        id SERIAL PRIMARY KEY,
        ausbildung_id INTEGER REFERENCES ausbildungen(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        punktzahl INTEGER NOT NULL,
        datum TEXT NOT NULL,
        UNIQUE(ausbildung_id, name)
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
""")
conn.commit()

# Migration
eingefuegt = 0
teilnehmer_count = 0

for key in sorted(ausbildungen.keys(), key=int):
    ausb = ausbildungen[key]

    cur.execute("""
        INSERT INTO ausbildungen (id, bereich, datum, uhrzeit, host, cohost, helfer,
                                  channel_id, message_id, archiviert, ausgewertet, erstellt_am)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    """, (
        ausb['id'],
        ausb['bereich'],
        ausb['datum'],
        ausb['uhrzeit'],
        ausb['host'],
        ausb.get('cohost', 'Nicht zugewiesen'),
        ausb.get('helfer', 'Nicht zugewiesen'),
        ausb['channel_id'],
        ausb['message_id'],
        ausb.get('archiviert', False),
        ausb.get('ausgewertet', False),
        ausb.get('erstellt_am')
    ))
    eingefuegt += 1

    for t in ausb.get('teilnehmer', []):
        cur.execute("""
            INSERT INTO teilnehmer (ausbildung_id, name, punktzahl, datum)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ausbildung_id, name) DO NOTHING
        """, (
            ausb['id'],
            t['name'],
            t['punktzahl'],
            t['datum']
        ))
        teilnehmer_count += 1

# Setze die Sequence auf den nächsten freien Wert
next_id = data.get("next_id", max(int(k) for k in ausbildungen.keys()) + 1)
cur.execute(f"SELECT setval('ausbildungen_id_seq', %s, true)", (next_id - 1,))

conn.commit()
cur.close()
conn.close()

print(f"✅ {eingefuegt} Ausbildungen migriert.")
print(f"✅ {teilnehmer_count} Teilnehmer migriert.")
print(f"✅ Nächste ID wird: {next_id}")
print("🎉 Migration abgeschlossen!")
