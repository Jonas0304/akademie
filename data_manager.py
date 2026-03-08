import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional


class DataManager:
    """
    Verwaltet die Datenhaltung für Ausbildungen via PostgreSQL.
    """

    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL ist nicht gesetzt! "
                "Bitte als Umgebungsvariable konfigurieren."
            )
        self._init_db()

    def _get_conn(self):
        return psycopg2.connect(self.database_url)

    def _init_db(self):
        """Erstellt die Tabellen, falls sie noch nicht existieren."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
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
        finally:
            conn.close()

    # ==================== AUSBILDUNGEN ====================

    def create_ausbildung(
        self,
        bereich: str,
        datum: str,
        uhrzeit: str,
        host: str,
        channel_id: int,
        message_id: int,
        cohost: str = None,
        helfer: str = None
    ) -> int:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ausbildungen
                        (bereich, datum, uhrzeit, host, cohost, helfer, channel_id, message_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    bereich, datum, uhrzeit, host,
                    cohost if cohost else 'Nicht zugewiesen',
                    helfer if helfer else 'Nicht zugewiesen',
                    channel_id, message_id
                ))
                ausbildung_id = cur.fetchone()[0]
            conn.commit()
            return ausbildung_id
        finally:
            conn.close()

    def get_ausbildung(self, ausbildung_id: int) -> Optional[Dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM ausbildungen WHERE id = %s",
                    (ausbildung_id,)
                )
                row = cur.fetchone()
                if not row:
                    return None
                result = dict(row)
                cur.execute(
                    "SELECT name, punktzahl, datum FROM teilnehmer WHERE ausbildung_id = %s",
                    (ausbildung_id,)
                )
                result['teilnehmer'] = [dict(t) for t in cur.fetchall()]
                return result
        finally:
            conn.close()

    def get_all_ausbildungen(self) -> Dict[str, Dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM ausbildungen ORDER BY id")
                rows = cur.fetchall()
                result = {}
                for row in rows:
                    entry = dict(row)
                    cur.execute(
                        "SELECT name, punktzahl, datum FROM teilnehmer WHERE ausbildung_id = %s",
                        (entry['id'],)
                    )
                    entry['teilnehmer'] = [dict(t) for t in cur.fetchall()]
                    result[str(entry['id'])] = entry
                return result
        finally:
            conn.close()

    def get_non_archived_ausbildungen(self) -> Dict[str, Dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM ausbildungen WHERE archiviert = FALSE ORDER BY id"
                )
                rows = cur.fetchall()
                result = {}
                for row in rows:
                    entry = dict(row)
                    cur.execute(
                        "SELECT name, punktzahl, datum FROM teilnehmer WHERE ausbildung_id = %s",
                        (entry['id'],)
                    )
                    entry['teilnehmer'] = [dict(t) for t in cur.fetchall()]
                    result[str(entry['id'])] = entry
                return result
        finally:
            conn.close()

    def update_ausbildung(self, ausbildung_id: int, updates: Dict) -> bool:
        if not updates:
            return False
        conn = self._get_conn()
        try:
            allowed_fields = {
                'bereich', 'datum', 'uhrzeit', 'host', 'cohost', 'helfer',
                'channel_id', 'message_id', 'archiviert', 'ausgewertet'
            }
            filtered = {k: v for k, v in updates.items() if k in allowed_fields}
            if not filtered:
                return False

            set_clause = ", ".join(f"{k} = %s" for k in filtered)
            values = list(filtered.values()) + [ausbildung_id]

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE ausbildungen SET {set_clause} WHERE id = %s",
                    values
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def set_auswertung_abgeschlossen(self, ausbildung_id: int, abgeschlossen: bool = True) -> bool:
        return self.update_ausbildung(ausbildung_id, {"ausgewertet": abgeschlossen})

    def delete_ausbildung(self, ausbildung_id: int) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ausbildungen WHERE id = %s",
                    (ausbildung_id,)
                )
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            conn.close()

    def archive_ausbildungen(self, ausbildung_ids: List[int]) -> int:
        if not ausbildung_ids:
            return 0
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ausbildungen SET archiviert = TRUE "
                    "WHERE id = ANY(%s) AND archiviert = FALSE",
                    (ausbildung_ids,)
                )
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            conn.close()

    # ==================== TEILNEHMER ====================

    def add_teilnehmer(
        self,
        ausbildung_id: int,
        teilnehmer_name: str,
        punktzahl: int,
        datum: str
    ) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM ausbildungen WHERE id = %s",
                    (ausbildung_id,)
                )
                if not cur.fetchone():
                    return False
                cur.execute("""
                    INSERT INTO teilnehmer (ausbildung_id, name, punktzahl, datum)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ausbildung_id, name) DO UPDATE
                    SET punktzahl = EXCLUDED.punktzahl, datum = EXCLUDED.datum
                """, (ausbildung_id, teilnehmer_name, punktzahl, datum))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_teilnehmer(self, ausbildung_id: int) -> List[Dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT name, punktzahl, datum FROM teilnehmer WHERE ausbildung_id = %s",
                    (ausbildung_id,)
                )
                return [dict(t) for t in cur.fetchall()]
        finally:
            conn.close()

    def remove_teilnehmer(self, ausbildung_id: int, teilnehmer_name: str) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM teilnehmer WHERE ausbildung_id = %s AND name = %s",
                    (ausbildung_id, teilnehmer_name)
                )
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            conn.close()

    # ==================== EINSTELLUNGEN ====================

    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM bot_settings WHERE key = %s",
                    (key,)
                )
                row = cur.fetchone()
                return row[0] if row else default
        finally:
            conn.close()

    def set_setting(self, key: str, value: str) -> None:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_settings (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """, (key, value))
            conn.commit()
        finally:
            conn.close()

    def get_deaktiviert(self) -> set:
        """Gibt das Set der deaktivierten Ausbildungen zurück."""
        raw = self.get_setting("anfrage_deaktiviert", "[]")
        try:
            return set(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return set()

    def set_deaktiviert(self, deaktiviert: set) -> None:
        """Speichert das Set der deaktivierten Ausbildungen."""
        self.set_setting("anfrage_deaktiviert", json.dumps(sorted(deaktiviert)))
