import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re
from typing import Optional, List, Dict, Union
from dotenv import load_dotenv
from data_manager import DataManager
from datetime import datetime, timedelta, timezone

# Lade Umgebungsvariablen
load_dotenv()

# Bot-Setup
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Initialisiere DataManager
data_manager = DataManager()

# Cooldown-Tracking für Anfragen (User-ID -> datetime)
anfrage_cooldowns: Dict[int, datetime] = {}

# Lade Konfiguration
CONFIG_PATH = 'config.json'
with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
    config = json.load(f)


async def log_aktion(title: str, description: str, color: discord.Color = discord.Color.blue(), fields: List[tuple] = None) -> None:
    """
    Loggt eine Aktion in den Log-Kanal.
    
    Args:
        title: Titel des Log-Eintrags
        description: Beschreibung
        color: Farbe des Embeds (default: blau)
        fields: Liste von Tuples (name, value, inline)
    """
    try:
        log_kanal_id = config.get("log_kanal_id")
        if not log_kanal_id:
            return
        
        log_kanal = bot.get_channel(int(log_kanal_id))
        if not log_kanal:
            return
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        
        await log_kanal.send(embed=embed)
    except Exception as e:
        print(f"Fehler beim Logging: {e}")


def pruefe_anfrage_cooldown(user_id: int) -> Optional[timedelta]:
    """
    Prüft, ob der Benutzer noch im Cooldown ist.
    
    Args:
        user_id: Die Discord User ID
    
    Returns:
        Verbleibende Zeit wenn noch im Cooldown, None wenn nicht
    """
    if user_id not in anfrage_cooldowns:
        return None
    
    last_anfrage = anfrage_cooldowns[user_id]
    cooldown_duration = timedelta(minutes=10)
    remaining_time = last_anfrage + cooldown_duration - datetime.now(timezone.utc)
    
    if remaining_time.total_seconds() <= 0:
        # Cooldown ist abgelaufen
        del anfrage_cooldowns[user_id]
        return None
    
    return remaining_time


def setze_anfrage_cooldown(user_id: int) -> None:
    """
    Setzt den Cooldown für einen Benutzer auf jetzt (10 Minuten).
    
    Args:
        user_id: Die Discord User ID
    """
    anfrage_cooldowns[user_id] = datetime.now(timezone.utc)


# ==================== HILFFUNKTIONEN ====================


def hat_ausbilder_berechtigung(interaction: discord.Interaction) -> bool:
    """
    Prüft, ob der User eine der erforderlichen Ausbilder-Rollen hat.
    
    Args:
        interaction: Discord Interaction Objekt
    
    Returns:
        True wenn berechtigt, False sonst
    """
    erlaubte_rollen = [
        1430643916775882825,  # Rolle 1
        1420507539367264276,  # Rolle 2 
        1420507027985137877,   # Rolle 3
        1460673702516752487   # Rolle 4
    ]
    
    # Prüfe, ob der User eine der Rollen hat
    if interaction.user.guild_permissions.administrator:
        return True
    
    user_rollen_ids = [role.id for role in interaction.user.roles]
    return any(rolle_id in user_rollen_ids for rolle_id in erlaubte_rollen)


def hat_statistik_berechtigung(interaction: discord.Interaction) -> bool:
    """
    Prüft, ob der User die Berechtigung für Statistik-Commands hat.
    """
    statistik_rolle = 1420507026739429396
    
    if interaction.user.guild_permissions.administrator:
        return True
    
    user_rollen_ids = [role.id for role in interaction.user.roles]
    return statistik_rolle in user_rollen_ids


def hat_archiv_berechtigung(interaction: discord.Interaction) -> bool:
    """
    Prüft, ob der User die spezielle Rolle/ID zum Archivieren hat.
    Erlaubt außerdem Administratoren.
    """
    erlaubte_id = 1420507026739429396  # Rolle oder Benutzer-ID
    if interaction.user.guild_permissions.administrator:
        return True
    # Rolle vorhanden?
    user_rollen_ids = [role.id for role in interaction.user.roles]
    if erlaubte_id in user_rollen_ids:
        return True
    # Fallback: direkte User-ID erlaubt
    try:
        return interaction.user.id == erlaubte_id
    except Exception:
        return False


def hat_anfrage_berechtigung(interaction: discord.Interaction, bereich: str) -> bool:
    """
    Prüft, ob der User die Berechtigung hat, Ausbildungsanfragen zu akzeptieren.
    Erlaubt außerdem Administratoren.
    """
    if interaction.user.guild_permissions.administrator:
        return True

    abteilung_config = config["abteilungen"].get(bereich, {})
    rolle_ids_raw = abteilung_config.get("anfrage_ping_role_id")
    if not rolle_ids_raw or "PLACEHOLDER" in str(rolle_ids_raw):
        return False

    rolle_ids: List[int] = []
    if isinstance(rolle_ids_raw, list):
        rolle_ids = [int(r) for r in rolle_ids_raw if str(r).isdigit()]
    else:
        parts = [p.strip() for p in str(rolle_ids_raw).split(",") if p.strip()]
        for part in parts:
            if part.isdigit():
                rolle_ids.append(int(part))

    if not rolle_ids:
        return False

    user_rollen_ids = [role.id for role in interaction.user.roles]
    return any(rid in user_rollen_ids for rid in rolle_ids)


def parse_datum(datum_str: str) -> Optional[datetime]:
    """
    Parst ein Datum im Format DD.MM.YYYY zu einem datetime-Objekt.
    
    Args:
        datum_str: Datum als String (z.B. "20.01.2026")
    
    Returns:
        datetime-Objekt oder None bei Fehler
    """
    try:
        return datetime.strptime(datum_str, "%d.%m.%Y")
    except:
        return None


def sammle_statistiken(tage: int) -> Dict[str, Dict[str, int]]:
    """
    Sammelt Statistiken über alle Ausbildungen der letzten X Tage.
    
    Args:
        tage: Anzahl der Tage zurück
    
    Returns:
        Dictionary mit User-Mentions als Keys und Statistiken als Values
    """
    ausbildungen = data_manager.get_all_ausbildungen()
    stats = {}
    
    # Berechne das Start-Datum
    heute = datetime.now()
    start_datum = heute - timedelta(days=tage)
    
    for ausb_id, ausb_data in ausbildungen.items():
        if not ausb_data.get("ausgewertet", False):
            continue

        # Parse das Datum der Ausbildung
        ausb_datum = parse_datum(ausb_data.get('datum', ''))
        
        # Überspringe, wenn Datum nicht geparst werden kann oder außerhalb des Zeitraums liegt
        if not ausb_datum or ausb_datum < start_datum or ausb_datum > heute:
            continue
        
        # Zähle Host
        host = ausb_data.get('host', '')
        if host and host != "Nicht zugewiesen":
            if host not in stats:
                stats[host] = {'host': 0, 'cohost': 0, 'helfer': 0, 'gesamt': 0}
            stats[host]['host'] += 1
            stats[host]['gesamt'] += 1
        
        # Zähle Co-Host
        cohost = ausb_data.get('cohost', '')
        if cohost and cohost != "Nicht zugewiesen":
            if cohost not in stats:
                stats[cohost] = {'host': 0, 'cohost': 0, 'helfer': 0, 'gesamt': 0}
            stats[cohost]['cohost'] += 1
            stats[cohost]['gesamt'] += 1
        
        # Zähle Helfer
        helfer = ausb_data.get('helfer', '')
        if helfer and helfer != "Nicht zugewiesen":
            if helfer not in stats:
                stats[helfer] = {'host': 0, 'cohost': 0, 'helfer': 0, 'gesamt': 0}
            stats[helfer]['helfer'] += 1
            stats[helfer]['gesamt'] += 1
    
    return stats


def sammle_person_statistik(user_mention: str, tage: int) -> tuple[Dict[str, int], List[Dict]]:
    """
    Sammelt Statistiken für eine spezifische Person.
    
    Args:
        user_mention: Mention des Users (z.B. "<@123456789>")
        tage: Anzahl der Tage zurück
    
    Returns:
        Tuple aus (Statistik-Dictionary, Liste der Ausbildungen)
    """
    ausbildungen = data_manager.get_all_ausbildungen()
    stats = {'host': 0, 'cohost': 0, 'helfer': 0, 'gesamt': 0}
    ausbildungs_liste = []
    
    # Berechne das Start-Datum
    heute = datetime.now()
    start_datum = heute - timedelta(days=tage)
    
    for ausb_id, ausb_data in ausbildungen.items():
        if not ausb_data.get("ausgewertet", False):
            continue

        # Parse das Datum der Ausbildung
        ausb_datum = parse_datum(ausb_data.get('datum', ''))
        
        # Überspringe, wenn Datum nicht geparst werden kann oder außerhalb des Zeitraums liegt
        if not ausb_datum or ausb_datum < start_datum or ausb_datum > heute:
            continue
        
        # Prüfe Host
        if ausb_data.get('host', '') == user_mention:
            stats['host'] += 1
            stats['gesamt'] += 1
            ausbildungs_liste.append({
                'bereich': ausb_data['bereich'],
                'datum': ausb_data['datum'],
                'rolle': 'Host'
            })
        
        # Prüfe Co-Host
        if ausb_data.get('cohost', '') == user_mention:
            stats['cohost'] += 1
            stats['gesamt'] += 1
            ausbildungs_liste.append({
                'bereich': ausb_data['bereich'],
                'datum': ausb_data['datum'],
                'rolle': 'Co-Host'
            })
        
        # Prüfe Helfer
        if ausb_data.get('helfer', '') == user_mention:
            stats['helfer'] += 1
            stats['gesamt'] += 1
            ausbildungs_liste.append({
                'bereich': ausb_data['bereich'],
                'datum': ausb_data['datum'],
                'rolle': 'Helfer'
            })
    
    return stats, ausbildungs_liste


def berechne_note(punktzahl: int, maximalpunktzahl: int, mindestpunktzahl: int) -> str:
    """
    Berechnet die Note basierend auf erreichten Punkten und Maximalpunktzahl.
    
    Args:
        punktzahl: Erreichte Punktzahl
        maximalpunktzahl: Maximal erreichbare Punktzahl
        mindestpunktzahl: Erforderliche Mindestpunktzahl zum Bestehen
    
    Returns:
        Note als String ("1" bis "6")
    """
    if maximalpunktzahl <= 0:
        return "6"

    prozent = (punktzahl / maximalpunktzahl) * 100
    
    if prozent >= 90:
        return "1"
    elif prozent >= 75:
        return "2"
    elif punktzahl >= mindestpunktzahl:
        return "3"
    elif prozent >= 40:
        return "4"
    elif prozent >= 20:
        return "5"
    return "6"


def get_abteilungen_choices() -> List[app_commands.Choice[str]]:
    """
    Erstellt eine Liste von Choices für die Abteilungsauswahl.
    
    Returns:
        Liste von app_commands.Choice-Objekten für alle Abteilungen
    """
    return [
        app_commands.Choice(name=abteilung, value=abteilung)
        for abteilung in config["abteilungen"].keys()
    ]


def format_ausbildungs_nachricht(
    bereich: str,
    datum: str,
    uhrzeit: str,
    host: Union[discord.User, discord.Member, str],
    cohost: Optional[Union[discord.User, discord.Member, str]] = None,
    helfer: Optional[Union[discord.User, discord.Member, str]] = None,
    ausbildung_id: Optional[int] = None
) -> str:
    """
    Füllt die Textvorlage einer Abteilung mit den übergebenen Werten.
    
    Args:
        bereich: Name der Abteilung
        datum: Datum der Ausbildung
        uhrzeit: Uhrzeit der Ausbildung
        host: Host-User
        cohost: Optional Co-Host-User
        helfer: Optional Helfer-User
    
    Returns:
        Formatierte Nachricht basierend auf der Vorlage
    """
    vorlage = config["abteilungen"][bereich]["vorlage"]
    
    def mention_oder_text(user_value: Optional[Union[discord.User, discord.Member, str]]) -> str:
        if not user_value:
            return "Nicht zugewiesen"
        if isinstance(user_value, str):
            return user_value
        return user_value.mention

    # Ersetze Platzhalter
    nachricht = vorlage.format(
        datum=datum,
        uhrzeit=uhrzeit,
        host=mention_oder_text(host),
        cohost=mention_oder_text(cohost),
        helfer=mention_oder_text(helfer)
    )
    
    if ausbildung_id is not None:
        nachricht += f"\n\n-# Ausbildungs-ID: {ausbildung_id}"

    return nachricht




# ==================== ARCHIVIEREN & EXPORT ====================

# ==================== AUSBILDUNGSANFRAGEN ====================

def parse_anfragender_id_from_embed(embed: discord.Embed) -> Optional[int]:
    if embed.footer and embed.footer.text:
        match = re.search(r'(\d{5,})', embed.footer.text)
        if match:
            return int(match.group(1))
    return None


class AusbildungsAnfrageModal(discord.ui.Modal):
    def __init__(self, bereich: str):
        super().__init__(title=f"Anfrage: {bereich}")
        self.bereich = bereich

        self.datum = discord.ui.TextInput(
            label="Datum",
            placeholder="z. B. 20.01.2026",
            required=True,
            max_length=20
        )
        self.uhrzeit = discord.ui.TextInput(
            label="Uhrzeit",
            placeholder="z. B. 18:00 Uhr",
            required=True,
            max_length=20
        )
        self.notiz = discord.ui.TextInput(
            label="Notiz (optional)",
            placeholder="Zusätzliche Infos...",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1000
        )

        self.add_item(self.datum)
        self.add_item(self.uhrzeit)
        self.add_item(self.notiz)

    async def on_submit(self, interaction: discord.Interaction):
        # Cooldown prüfen
        remaining = pruefe_anfrage_cooldown(interaction.user.id)
        if remaining:
            minuten = int(remaining.total_seconds() // 60)
            sekunden = int(remaining.total_seconds() % 60)
            await interaction.response.send_message(
                f"⏳ Du hast noch einen **Cooldown** von `{minuten}:{sekunden:02d}` Minuten!\n"
                f"Du kannst in dieser Zeit keine weiteren Anfragen stellen.",
                ephemeral=True
            )
            return
        
        abteilung_config = config["abteilungen"].get(self.bereich)
        if not abteilung_config:
            await interaction.response.send_message(
                "❌ Fehler: Abteilung nicht gefunden!",
                ephemeral=True
            )
            return

        zielkanal_id = abteilung_config.get("anfrage_zielkanal_id")
        if not zielkanal_id or "PLACEHOLDER" in str(zielkanal_id):
            await interaction.response.send_message(
                "❌ Fehler: Kein Anfrage-Zielkanal für diese Ausbildung konfiguriert!",
                ephemeral=True
            )
            return

        try:
            zielkanal_id = int(zielkanal_id)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                "❌ Fehler: Anfrage-Zielkanal ID ist ungültig!",
                ephemeral=True
            )
            return

        kanal = bot.get_channel(zielkanal_id)
        if not kanal:
            await interaction.response.send_message(
                "❌ Fehler: Anfrage-Zielkanal nicht gefunden!",
                ephemeral=True
            )
            return

        ping_role_id = abteilung_config.get("anfrage_ping_role_id")
        ping_text = ""
        if ping_role_id and "PLACEHOLDER" not in str(ping_role_id):
            if isinstance(ping_role_id, list):
                role_ids = [str(r) for r in ping_role_id if str(r).isdigit()]
                ping_text = " ".join(f"<@&{rid}>" for rid in role_ids)
            else:
                parts = [p.strip() for p in str(ping_role_id).split(",") if p.strip()]
                role_ids = [p for p in parts if p.isdigit()]
                ping_text = " ".join(f"<@&{rid}>" for rid in role_ids)

        embed = discord.Embed(
            title=f"📌 Ausbildungsanfrage • {self.bereich}",
            description=(
                "Eine neue Anfrage ist eingegangen. "
                "Bitte prüft Datum/Uhrzeit und bestätigt bei Verfügbarkeit."
            ),
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="👤 Anfragender", value=interaction.user.mention, inline=True)
        embed.add_field(name="🗓️ Datum", value=self.datum.value, inline=True)
        embed.add_field(name="⏰ Uhrzeit", value=self.uhrzeit.value, inline=True)
        embed.add_field(
            name="📝 Notiz",
            value=self.notiz.value if self.notiz.value else "—",
            inline=False
        )
        embed.add_field(name="✅ Status", value="Offen", inline=True)
        embed.set_footer(text=f"Anfragender ID: {interaction.user.id} | Bereich: {self.bereich}")

        try:
            await kanal.send(
                content=ping_text,
                embed=embed,
                view=AnfrageAkzeptierenView()
            )
            await interaction.response.send_message(
                "✅ Anfrage wurde gesendet!",
                ephemeral=True
            )
            # Cooldown setzen
            setze_anfrage_cooldown(interaction.user.id)
            
            await log_aktion(
                "📬 Neue Ausbildungsanfrage eingereicht",
                f"Ein Mitglied möchte diese Ausbildung anfragen.",
                discord.Color.blue(),
                [
                    ("Ausbildung", self.bereich, True),
                    ("Anfragender", interaction.user.display_name, True),
                    ("Datum", self.datum.value, True),
                    ("Uhrzeit", self.uhrzeit.value, True)
                ]
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Fehler: Keine Berechtigung zum Senden im Anfrage-Kanal!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Senden der Anfrage: {str(e)}",
                ephemeral=True
            )


class AusbildungsAnfrageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AusbildungsAnfrageSelect())


class AusbildungsAnfrageSelect(discord.ui.Select):
    def __init__(self):
        deaktiviert = data_manager.get_deaktiviert()
        options = []
        for bereich in config.get("abteilungen", {}).keys():
            label = bereich
            description = "Anfrage senden"
            if bereich in deaktiviert:
                description = "Aktuell deaktiviert"
            options.append(
                discord.SelectOption(
                    label=label,
                    value=bereich,
                    description=description
                )
            )

        super().__init__(
            placeholder="Wähle eine Ausbildung",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        bereich = self.values[0]
        deaktiviert = data_manager.get_deaktiviert()
        if bereich in deaktiviert:
            await interaction.response.send_message(
                f"⚠️ Anfragen für **{bereich}** sind aktuell deaktiviert.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(AusbildungsAnfrageModal(bereich))


class AnfrageAkzeptierenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Akzeptieren", style=discord.ButtonStyle.success, custom_id="anfrage_akzeptieren")
    async def akzeptieren(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message or not interaction.message.embeds:
            await interaction.response.send_message(
                "❌ Fehler: Anfrage-Embed nicht gefunden.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        embed = interaction.message.embeds[0]
        bereich = None
        if embed.footer and embed.footer.text:
            match = re.search(r'Bereich:\s*(.+)$', embed.footer.text)
            if match:
                bereich = match.group(1).strip()

        if not bereich and embed.title:
            if "–" in embed.title:
                bereich = embed.title.split("–", 1)[1].strip()
            elif "•" in embed.title:
                bereich = embed.title.split("•", 1)[1].strip()

        if not bereich:
            await interaction.followup.send(
                "❌ Fehler: Abteilung konnte nicht erkannt werden.",
                ephemeral=True
            )
            return

        if not hat_anfrage_berechtigung(interaction, bereich):
            await interaction.followup.send(
                "❌ Du hast keine Berechtigung, diese Anfrage zu akzeptieren!",
                ephemeral=True
            )
            return

        requester_id = parse_anfragender_id_from_embed(embed)
        if not requester_id:
            await interaction.followup.send(
                "❌ Fehler: Anfragender konnte nicht erkannt werden.",
                ephemeral=True
            )
            return

        requester = interaction.guild.get_member(requester_id)
        if not requester:
            try:
                requester = await interaction.guild.fetch_member(requester_id)
            except (discord.NotFound, discord.Forbidden):
                requester = None

        if not requester:
            await interaction.followup.send(
                "❌ Fehler: Anfragender nicht mehr auf dem Server.",
                ephemeral=True
            )
            return

        # Update Embed Status
        new_embed = embed.copy()
        status_updated = False
        status_value = None
        for field in new_embed.fields:
            if field.name.lower() == "status":
                status_value = field.value
                break

        if status_value and "akzeptiert" in status_value.lower():
            await interaction.followup.send(
                "ℹ️ Diese Anfrage wurde bereits akzeptiert.",
                ephemeral=True
            )
            return

        updated_fields = []
        for field in new_embed.fields:
            if field.name.lower() == "status":
                updated_fields.append((field.name, "Akzeptiert", field.inline))
                status_updated = True
            else:
                updated_fields.append((field.name, field.value, field.inline))

        if not status_updated:
            updated_fields.append(("Status", "Akzeptiert", False))

        new_embed.clear_fields()
        for name, value, inline in updated_fields:
            new_embed.add_field(name=name, value=value, inline=inline)

        new_embed.add_field(name="Akzeptiert von", value=interaction.user.mention, inline=False)

        # Disable button
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        await interaction.message.edit(embed=new_embed, view=self)

        # DM requester
        datum_val = "-"
        uhrzeit_val = "-"
        for field in new_embed.fields:
            if field.name.lower() == "datum":
                datum_val = field.value
            elif field.name.lower() == "uhrzeit":
                uhrzeit_val = field.value

        try:
            dm_embed = discord.Embed(
                title="✅ Anfrage akzeptiert",
                description="Deine Ausbildungsanfrage wurde bestätigt.",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            dm_embed.add_field(name="Ausbildung", value=bereich, inline=False)
            dm_embed.add_field(name="Datum", value=datum_val, inline=True)
            dm_embed.add_field(name="Uhrzeit", value=uhrzeit_val, inline=True)
            dm_embed.add_field(
                name="Akzeptiert von",
                value=interaction.user.display_name,
                inline=False
            )
            dm_embed.set_footer(text="Akademie • Anfrage-Bestätigung")

            await requester.send(embed=dm_embed)
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Konnte dem Anfragenden keine DM senden (DMs deaktiviert).",
                ephemeral=True
            )

        await interaction.followup.send(
            "✅ Anfrage akzeptiert und bestätigt.",
            ephemeral=True
        )
        await log_aktion(
            "✅ Anfrage akzeptiert",
            f"Eine Ausbildungsanfrage wurde akzeptiert.",
            discord.Color.green(),
            [
                ("Ausbildung", bereich, True),
                ("Anfragender", requester.display_name, True),
                ("Akzeptiert von", interaction.user.display_name, True)
            ]
        )

@tree.command(name="export", description="Exportiert alle aktiven Ausbildungen als TXT-Datei")
async def export_command(
    interaction: discord.Interaction,
):
    """
    Exportiert alle nicht archivierten Ausbildungen in eine TXT-Datei
    und sendet diese Datei per DM an den ausführenden Nutzer.
    Es wird nichts automatisch archiviert.
    """
    # Berechtigungsprüfung
    if not hat_archiv_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    active = data_manager.get_non_archived_ausbildungen()
    if not active:
        await interaction.response.send_message(
            "Es gibt aktuell keine aktiven (nicht archivierten) Ausbildungen.",
            ephemeral=True
        )
        return

    # Baue TXT-Inhalt
    from io import StringIO, BytesIO
    buf = StringIO()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buf.write(f"Export erstellt am {timestamp}\n")
    buf.write("=" * 60 + "\n\n")

    sort_ids = sorted((int(k) for k in active.keys()))
    for key in sort_ids:
        ausb = active[str(key)]
        buf.write(f"ID: {ausb['id']} | Bereich: {ausb['bereich']} | Datum: {ausb.get('datum','')} {ausb.get('uhrzeit','')}\n")
        buf.write(f"Host: {ausb.get('host','')} | Co-Host: {ausb.get('cohost','Nicht zugewiesen')} | Helfer: {ausb.get('helfer','Nicht zugewiesen')}\n")
        buf.write("Teilnehmer:\n")
        teilnehmer = ausb.get('teilnehmer', [])
        if teilnehmer:
            for t in teilnehmer:
                buf.write(f" - {t.get('name','?')} — {t.get('punktzahl','?')} Punkte\n")
        else:
            buf.write(" - (keine Teilnehmer)\n")
        buf.write("\n")

    content_bytes = buf.getvalue().encode('utf-8')
    file_obj = BytesIO(content_bytes)
    file_obj.seek(0)
    filename = datetime.now().strftime("ausbildungen-export-%Y%m%d-%H%M%S.txt")

    # Versuche per DM zu senden
    try:
        await interaction.user.send(
            content="Hier ist dein Export (TXT).",
            file=discord.File(fp=file_obj, filename=filename)
        )
        await interaction.response.send_message(
            "✅ Export gesendet (DM).",
            ephemeral=True
        )
    except Exception:
        await interaction.response.send_message(
            "❌ Konnte keine DM senden (DMs evtl. deaktiviert).",
            ephemeral=True
        )

@tree.command(name="archiv", description="Archiviert Ausbildungen per ID-Liste")
@app_commands.describe(ids="Ausbildungs-IDs, getrennt durch Leerzeichen oder Komma, z. B. '12 15,18'")
async def archiv_command(
    interaction: discord.Interaction,
    ids: str
):
    """
    Markiert die angegebenen Ausbildungs-IDs als archiviert (archiviert=True).
    """
    if not hat_archiv_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    # IDs parsen
    rohteile = [t.strip() for t in ids.replace(',', ' ').split() if t.strip()]
    try:
        id_list = [int(t) for t in rohteile]
    except ValueError:
        await interaction.response.send_message(
            "❌ Ungültige Eingabe. Bitte nur Zahlen, getrennt durch Leerzeichen/Komma.",
            ephemeral=True
        )
        return

    if not id_list:
        await interaction.response.send_message(
            "Keine IDs angegeben.",
            ephemeral=True
        )
        return

    # Prüfe, welche existieren
    alle = data_manager.get_all_ausbildungen()
    existierende = [aid for aid in id_list if str(aid) in alle]
    nicht_gefunden = [aid for aid in id_list if str(aid) not in alle]

    count = data_manager.archive_ausbildungen(existierende)

    msg = f"✅ {count} Ausbildung(en) archiviert."
    if nicht_gefunden:
        msg += f" Nicht gefunden: {', '.join(map(str, nicht_gefunden))}."

    await interaction.response.send_message(msg, ephemeral=True)
    await log_aktion(
        "📦 Ausbildungen archiviert",
        f"{count} Ausbildung(en) wurde(n) archiviert.",
        discord.Color.greyple(),
        [("Benutzer", interaction.user.display_name, True)]
    )


@tree.command(name="archiv_alle", description="Archiviert alle aktiven Ausbildungen auf einmal")
async def archiv_alle_command(
    interaction: discord.Interaction,
):
    """
    Archiviert alle aktuell nicht archivierten Ausbildungen.
    """
    if not hat_archiv_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    active = data_manager.get_non_archived_ausbildungen()
    if not active:
        await interaction.response.send_message(
            "Es gibt keine aktiven (nicht archivierten) Ausbildungen.",
            ephemeral=True
        )
        return

    ids_to_archive = [int(k) for k in active.keys()]
    count = data_manager.archive_ausbildungen(ids_to_archive)

    await interaction.response.send_message(
        f"✅ {count} Ausbildung(en) archiviert.",
        ephemeral=True
    )
    await log_aktion(
        "📦 Alle aktiven Ausbildungen archiviert",
        f"Alle {count} aktiven Ausbildung(en) wurden archiviert.",
        discord.Color.greyple(),
        [("Benutzer", interaction.user.display_name, True)]
    )

# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    """
    Event-Handler für Bot-Start.
    Synchronisiert die Slash Commands.
    """
    print(f'{bot.user} ist online!')
    print(f'Bot läuft als: {bot.user.name} (ID: {bot.user.id})')
    print('------')
    
    try:
        synced = await tree.sync()
        print(f'{len(synced)} Slash Command(s) synchronisiert')
    except Exception as e:
        print(f'Fehler beim Synchronisieren der Commands: {e}')

    # Persistent View für Anfragen-Akzeptieren
    try:
        bot.add_view(AnfrageAkzeptierenView())
    except Exception as e:
        print(f'Fehler beim Registrieren der Anfrage-View: {e}')


# ==================== SLASH COMMANDS ====================

@tree.command(name="anfrage_panel", description="Poste das Anfrage-Panel für Ausbildungen")
async def anfrage_panel_command(
    interaction: discord.Interaction
):
    """
    Erstellt/posted das Anfrage-Panel mit Buttons für alle Ausbildungen.
    """
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    anfrage_kanal_id = config.get("anfrage_kanal_id")
    if not anfrage_kanal_id or "PLACEHOLDER" in str(anfrage_kanal_id):
        await interaction.response.send_message(
            "❌ Fehler: Anfrage-Kanal ist nicht konfiguriert!",
            ephemeral=True
        )
        return

    try:
        anfrage_kanal_id = int(anfrage_kanal_id)
    except (TypeError, ValueError):
        await interaction.response.send_message(
            "❌ Fehler: Anfrage-Kanal ID ist ungültig!",
            ephemeral=True
        )
        return

    kanal = bot.get_channel(anfrage_kanal_id)
    if not kanal:
        await interaction.response.send_message(
            "❌ Fehler: Anfrage-Kanal nicht gefunden!",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Willkommen bei der Akademie",
        description=(
            "Hier kannst du **zusätzliche Ausbildungen anfragen**.\n\n"
            "Bitte sende **nicht zu viele Anfragen** hintereinander. "
            "Ausbilder führen diese nur durch, **wenn sie Zeit haben**.\n\n"
            "Wähle unten die passende Ausbildung aus und trage Datum, Uhrzeit "
            "sowie optional eine Notiz ein."
        ),
        color=discord.Color.teal()
    )
    embed.set_footer(text="Akademie • Ausbildungsanfragen")

    try:
        await kanal.send(embed=embed, view=AusbildungsAnfrageView())
        await interaction.response.send_message(
            f"✅ Anfrage-Panel wurde im Kanal {kanal.mention} gepostet!",
            ephemeral=True
        )
        await log_aktion(
            "📋 Anfrage-Panel gepostet",
            f"Das Ausbildungsanfrage-Panel wurde in {kanal.mention} gepostet.",
            discord.Color.teal(),
            [("Nutzer", interaction.user.display_name, True)]
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Fehler: Keine Berechtigung zum Senden im Anfrage-Kanal!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Fehler beim Posten des Panels: {str(e)}",
            ephemeral=True
        )


@tree.command(name="anfrage_toggle", description="Aktiviere oder deaktiviere Ausbildungsanfragen")
@app_commands.describe(
    bereich="Wähle die Ausbildung",
    status="aktiv oder deaktiv"
)
@app_commands.choices(
    status=[
        app_commands.Choice(name="aktiv", value="aktiv"),
        app_commands.Choice(name="deaktiv", value="deaktiv")
    ]
)
async def anfrage_toggle_command(
    interaction: discord.Interaction,
    bereich: str,
    status: app_commands.Choice[str]
):
    """
    Aktiviert oder deaktiviert die Anfrage für eine Ausbildung.
    """
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    if bereich not in config.get("abteilungen", {}):
        await interaction.response.send_message(
            "❌ Unbekannte Ausbildung.",
            ephemeral=True
        )
        return

    deaktiviert = data_manager.get_deaktiviert()
    if status.value == "deaktiv":
        deaktiviert.add(bereich)
    else:
        deaktiviert.discard(bereich)

    data_manager.set_deaktiviert(deaktiviert)

    status_text = "aktiviert" if status.value == "aktiv" else "deaktiviert"
    await interaction.response.send_message(
        f"✅ Anfrage für **{bereich}** ist jetzt **{status.value}**.\n"
        "ℹ️ Poste das Panel neu mit `/anfrage_panel`, damit die Buttons aktualisiert werden.",
        ephemeral=True
    )
    await log_aktion(
        "🔄 Ausbildungsanfrage Status geändert",
        f"Status: {status_text}",
        discord.Color.gold(),
        [
            ("Ausbildung", bereich, True),
            ("Status", status_text, True),
            ("Geändert von", interaction.user.display_name, False)
        ]
    )


@tree.command(name="anfrage_debug", description="Zeigt die aktuellen Anfrage-Einstellungen für eine Ausbildung")
@app_commands.describe(bereich="Wähle die Ausbildung")
async def anfrage_debug_command(
    interaction: discord.Interaction,
    bereich: str
):
    """
    Debug-Ausgabe für Anfrage-Einstellungen (Ping-Rollen und Zielkanal).
    """
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    if bereich not in config.get("abteilungen", {}):
        await interaction.response.send_message(
            "❌ Unbekannte Ausbildung.",
            ephemeral=True
        )
        return

    abteilung_config = config["abteilungen"][bereich]
    raw_ping = abteilung_config.get("anfrage_ping_role_id")
    zielkanal = abteilung_config.get("anfrage_zielkanal_id")

    parsed_roles: List[str] = []
    if isinstance(raw_ping, list):
        parsed_roles = [str(r) for r in raw_ping if str(r).isdigit()]
    else:
        parts = [p.strip() for p in str(raw_ping).split(",") if p.strip()]
        parsed_roles = [p for p in parts if p.isdigit()]

    await interaction.response.send_message(
        "**Anfrage-Debug**\n"
        f"Ausbildung: **{bereich}**\n"
        f"Zielkanal-ID: `{zielkanal}`\n"
        f"Ping (raw): `{raw_ping}`\n"
        f"Ping (parsed): `{', '.join(parsed_roles) if parsed_roles else '—'}`",
        ephemeral=True
    )

@tree.command(name="ankuendigen", description="Kündige eine Ausbildung an")
@app_commands.describe(
    bereich="Wähle die Abteilung",
    datum="Datum der Ausbildung (z.B. 20.01.2026)",
    uhrzeit="Uhrzeit der Ausbildung (z.B. 18:00 Uhr)",
    host="Host der Ausbildung",
    cohost="Co-Host der Ausbildung (optional)",
    helfer="Helfer der Ausbildung (optional)"
)
async def ankuendigen_command(
    interaction: discord.Interaction,
    bereich: str,
    datum: str,
    uhrzeit: str,
    host: discord.User,
    cohost: Optional[discord.User] = None,
    helfer: Optional[discord.User] = None
):
    """
    Slash Command zum Ankündigen einer Ausbildung.
    Sendet die Ankündigung im konfigurierten Kanal und setzt automatisch die Emoji-Reaktion.
    """
    # Berechtigungsprüfung
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return
    
    await handle_ankuendigung(interaction, bereich, datum, uhrzeit, host, cohost, helfer)


async def handle_ankuendigung(
    interaction: discord.Interaction,
    bereich: Optional[str],
    datum: Optional[str],
    uhrzeit: Optional[str],
    host: Optional[discord.User],
    cohost: Optional[discord.User],
    helfer: Optional[discord.User]
):
    """
    Interne Funktion zur Verarbeitung einer Ausbildungsankündigung.
    """
    # Validierung
    if not all([bereich, datum, uhrzeit, host]):
        await interaction.response.send_message(
            "❌ Fehler: Bereich, Datum, Uhrzeit und Host sind Pflichtfelder!",
            ephemeral=True
        )
        return
    
    # Prüfe, ob die Abteilung existiert
    if bereich not in config["abteilungen"]:
        await interaction.response.send_message(
            f"❌ Fehler: Die Abteilung '{bereich}' existiert nicht!",
            ephemeral=True
        )
        return
    
    # Hole Abteilungskonfiguration
    abteilung_config = config["abteilungen"][bereich]
    kanal_id = int(abteilung_config["kanal_id"])
    emoji = abteilung_config["emoji"]
    
    # Hole den Zielkanal
    kanal = bot.get_channel(kanal_id)
    if not kanal:
        await interaction.response.send_message(
            f"❌ Fehler: Kanal mit ID {kanal_id} nicht gefunden! Bitte überprüfe die config.json.",
            ephemeral=True
        )
        return
    
    # Erstelle die Nachricht (erste Version ohne ID, diese wird nach Speicherung ergänzt)
    nachricht_text = format_ausbildungs_nachricht(
        bereich, datum, uhrzeit, host, cohost, helfer
    )
    
    # Sende die Nachricht im Zielkanal
    try:
        nachricht = await kanal.send(nachricht_text)
        
        # Setze die Emoji-Reaktion
        await nachricht.add_reaction(emoji)
        
        # Speichere die Ausbildung in der Datenbank
        ausbildung_id = data_manager.create_ausbildung(
            bereich=bereich,
            datum=datum,
            uhrzeit=uhrzeit,
            host=host.mention,
            channel_id=kanal_id,
            message_id=nachricht.id,
            cohost=cohost.mention if cohost else None,
            helfer=helfer.mention if helfer else None
        )

        # Ergänze die sichtbare Ausbildungs-ID in der Ankündigung
        nachricht_mit_id = format_ausbildungs_nachricht(
            bereich, datum, uhrzeit, host, cohost, helfer, ausbildung_id=ausbildung_id
        )
        await nachricht.edit(content=nachricht_mit_id)
        
        # Bestätigungsnachricht
        await interaction.response.send_message(
            f"✅ Ausbildung erfolgreich angekündigt!\n"
            f"📋 Ausbildungs-ID: {ausbildung_id}\n"
            f"📍 Kanal: {kanal.mention}\n"
            f"🏷️ Reaktion: {emoji}",
            ephemeral=True
        )
        await log_aktion(
            "📢 Ausbildung angekündigt",
            "Eine neue Ausbildung wurde ankündigt.",
            discord.Color.orange(),
            [
                ("Ausbildung", bereich, True),
                ("Datum", datum, True),
                ("Uhrzeit", uhrzeit, True),
                ("Host", host.display_name, True),
                ("Kanal", kanal.mention, True),
                ("ID", str(ausbildung_id), True)
            ]
        )
        
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Fehler: Keine Berechtigung zum Senden im Kanal {kanal.mention}!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Fehler beim Ankündigen der Ausbildung: {str(e)}",
            ephemeral=True
        )


def parse_mitarbeiter_mention(raw_value: str) -> str:
    """
    Parst eine Mitarbeiter-Eingabe für Host/Co-Host/Helfer.

    Unterstützt:
    - Discord Mention (<@123>, <@!123>)
    - Direkte User-ID (123456...)
    - "-" / "none" / "austragen" zum Entfernen
    """
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("Leere Eingabe")

    if value.lower() in {"-", "none", "kein", "keiner", "entfernen", "austragen", "nicht zugewiesen"}:
        return "Nicht zugewiesen"

    mention_match = re.fullmatch(r"<@!?(\d+)>", value)
    if mention_match:
        return f"<@{mention_match.group(1)}>"

    if value.isdigit():
        return f"<@{value}>"

    raise ValueError("Ungültiges Format")


@tree.command(name="bearbeiten", description="Bearbeite eine angekündigte Ausbildung")
@app_commands.describe(
    ausbildung="Wähle die angekündigte Ausbildung",
    datum="Neues Datum (optional)",
    uhrzeit="Neue Uhrzeit (optional)",
    host="Neuer Host (optional)",
    cohost="Neuer Co-Host als Mention/ID oder '-' zum Austragen (optional)",
    helfer="Neuer Helfer als Mention/ID oder '-' zum Austragen (optional)"
)
async def bearbeiten_command(
    interaction: discord.Interaction,
    ausbildung: str,
    datum: Optional[str] = None,
    uhrzeit: Optional[str] = None,
    host: Optional[discord.User] = None,
    cohost: Optional[str] = None,
    helfer: Optional[str] = None
):
    """
    Bearbeitet eine angekündigte Ausbildung und aktualisiert die ursprüngliche Nachricht.
    """
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    try:
        ausbildung_id = int(ausbildung)
    except ValueError:
        await interaction.response.send_message(
            "❌ Fehler: Ungültige Ausbildungs-ID!",
            ephemeral=True
        )
        return

    ausbildung_data = data_manager.get_ausbildung(ausbildung_id)
    if not ausbildung_data:
        await interaction.response.send_message(
            f"❌ Fehler: Ausbildung mit ID {ausbildung_id} nicht gefunden!",
            ephemeral=True
        )
        return

    if ausbildung_data.get("ausgewertet", False):
        await interaction.response.send_message(
            "❌ Diese Ausbildung wurde bereits ausgewertet.",
            ephemeral=True
        )
        return

    if ausbildung_data.get("archiviert", False):
        await interaction.response.send_message(
            "❌ Diese Ausbildung ist bereits archiviert und kann nicht mehr bearbeitet werden.",
            ephemeral=True
        )
        return

    bereich = ausbildung_data.get("bereich")
    if bereich not in config.get("abteilungen", {}):
        await interaction.response.send_message(
            f"❌ Fehler: Abteilung '{bereich}' nicht in der Konfiguration gefunden!",
            ephemeral=True
        )
        return

    neuer_host = host.mention if host else ausbildung_data.get("host", "Nicht zugewiesen")
    neuer_cohost = ausbildung_data.get("cohost", "Nicht zugewiesen")
    neuer_helfer = ausbildung_data.get("helfer", "Nicht zugewiesen")

    try:
        if cohost is not None:
            neuer_cohost = parse_mitarbeiter_mention(cohost)
        if helfer is not None:
            neuer_helfer = parse_mitarbeiter_mention(helfer)
    except ValueError:
        await interaction.response.send_message(
            "❌ Fehler: Co-Host/Helfer muss eine Mention, User-ID oder '-' zum Austragen sein.",
            ephemeral=True
        )
        return

    neues_datum = datum if datum else ausbildung_data.get("datum", "")
    neue_uhrzeit = uhrzeit if uhrzeit else ausbildung_data.get("uhrzeit", "")

    neue_nachricht = format_ausbildungs_nachricht(
        bereich,
        neues_datum,
        neue_uhrzeit,
        neuer_host,
        neuer_cohost,
        neuer_helfer,
        ausbildung_id=ausbildung_id
    )

    kanal_id = int(ausbildung_data.get("channel_id", 0))
    message_id = int(ausbildung_data.get("message_id", 0))
    kanal = bot.get_channel(kanal_id)

    nachricht_bearbeitet = False
    fehlerhinweis = ""

    if kanal:
        try:
            nachricht = await kanal.fetch_message(message_id)
            await nachricht.edit(content=neue_nachricht)
            nachricht_bearbeitet = True
        except discord.NotFound:
            fehlerhinweis = "⚠️ Die ursprüngliche Nachricht wurde nicht gefunden, Daten wurden trotzdem aktualisiert."
        except discord.Forbidden:
            fehlerhinweis = "⚠️ Keine Berechtigung zum Bearbeiten der ursprünglichen Nachricht, Daten wurden trotzdem aktualisiert."
        except Exception as e:
            fehlerhinweis = f"⚠️ Nachricht konnte nicht bearbeitet werden ({str(e)}), Daten wurden trotzdem aktualisiert."
    else:
        fehlerhinweis = "⚠️ Der ursprüngliche Kanal wurde nicht gefunden, Daten wurden trotzdem aktualisiert."

    updates = {
        "datum": neues_datum,
        "uhrzeit": neue_uhrzeit,
        "host": neuer_host,
        "cohost": neuer_cohost,
        "helfer": neuer_helfer
    }
    data_manager.update_ausbildung(ausbildung_id, updates)

    status_text = "✅ Ausbildung und Ankündigungsnachricht wurden aktualisiert." if nachricht_bearbeitet else "✅ Ausbildungsdaten wurden aktualisiert."
    if fehlerhinweis:
        status_text += f"\n{fehlerhinweis}"

    await interaction.response.send_message(
        status_text,
        ephemeral=True
    )

    await log_aktion(
        "✏️ Ausbildung bearbeitet",
        "Eine angekündigte Ausbildung wurde bearbeitet.",
        discord.Color.gold(),
        [
            ("ID", str(ausbildung_id), True),
            ("Ausbildung", bereich, True),
            ("Datum", neues_datum, True),
            ("Uhrzeit", neue_uhrzeit, True),
            ("Host", neuer_host, False),
            ("Co-Host", neuer_cohost, False),
            ("Helfer", neuer_helfer, False)
        ]
    )


# ==================== GEMEINSAME AUTOCOMPLETE-HANDLER ====================

async def offene_ausbildung_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Gemeinsamer Autocomplete für offene (nicht ausgewertete, nicht archivierte) Ausbildungen."""
    ausbildungen = data_manager.get_non_archived_ausbildungen()
    choices = []
    for ausb_id, ausb_data in ausbildungen.items():
        if ausb_data.get("ausgewertet", False):
            continue
        label = f"{ausb_data['bereich']} - {ausb_data['datum']} (ID: {ausb_id})"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=ausb_id))
    return choices[:25]


async def alle_ausbildung_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Gemeinsamer Autocomplete für alle nicht-archivierten Ausbildungen."""
    ausbildungen = data_manager.get_non_archived_ausbildungen()
    choices = []
    for ausb_id, ausb_data in ausbildungen.items():
        label = f"{ausb_data['bereich']} - {ausb_data['datum']} (ID: {ausb_id})"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label, value=ausb_id))
    return choices[:25]


# Autocomplete für Bereich bei ankuendigen
@ankuendigen_command.autocomplete('bereich')
async def bereich_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete-Handler für die Bereichsauswahl (gemeinsam genutzt)."""
    return [
        app_commands.Choice(name=abt, value=abt)
        for abt in config["abteilungen"]
        if current.lower() in abt.lower()
    ]


@anfrage_toggle_command.autocomplete('bereich')
async def anfrage_toggle_bereich_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await bereich_autocomplete(interaction, current)


@anfrage_debug_command.autocomplete('bereich')
async def anfrage_debug_bereich_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await bereich_autocomplete(interaction, current)


@bearbeiten_command.autocomplete('ausbildung')
async def bearbeiten_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await offene_ausbildung_autocomplete(interaction, current)


@tree.command(name="auswertung", description="Füge einen Teilnehmer zur Auswertung hinzu")
@app_commands.describe(
    ausbildung="Wähle die Ausbildung",
    teilnehmer="Teilnehmer der Ausbildung",
    punktzahl="Erreichte Punktzahl",
    datum="Datum der Teilnahme (z.B. 20.01.2026)"
)
async def auswertung_command(
    interaction: discord.Interaction,
    ausbildung: str,
    teilnehmer: discord.User,
    punktzahl: int,
    datum: str
):
    """
    Slash Command zum Hinzufügen von Teilnehmern zur Auswertung.
    """
    # Berechtigungsprüfung
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return
    
    try:
        ausbildung_id = int(ausbildung)
    except ValueError:
        await interaction.response.send_message(
            "❌ Fehler: Ungültige Ausbildungs-ID!",
            ephemeral=True
        )
        return
    
    # Prüfe, ob die Ausbildung existiert
    ausbildung_data = data_manager.get_ausbildung(ausbildung_id)
    if not ausbildung_data:
        await interaction.response.send_message(
            f"❌ Fehler: Ausbildung mit ID {ausbildung_id} nicht gefunden!",
            ephemeral=True
        )
        return
    
    # Füge Teilnehmer hinzu
    success = data_manager.add_teilnehmer(
        ausbildung_id, 
        teilnehmer.mention, 
        punktzahl,
        datum
    )
    
    if success:
        await interaction.response.send_message(
            f"✅ Teilnehmer {teilnehmer.mention} mit {punktzahl} Punkten hinzugefügt!",
            ephemeral=True
        )
        await log_aktion(
            "👤 Teilnehmer hinzugefügt",
            "Ein Teilnehmer wurde zur Auswertung hinzugefügt.",
            discord.Color.blue(),
            [
                ("Ausbildung ID", str(ausbildung_id), True),
                ("Teilnehmer", teilnehmer.display_name, True),
                ("Punkte", str(punktzahl), True)
            ]
        )
    else:
        await interaction.response.send_message(
            f"❌ Fehler beim Hinzufügen des Teilnehmers!",
            ephemeral=True
        )


# Autocomplete für Ausbildungsauswahl
@auswertung_command.autocomplete('ausbildung')
async def ausbildung_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await alle_ausbildung_autocomplete(interaction, current)


@tree.command(name="abschliessen", description="Schließe eine Auswertung ab und poste das Ergebnis")
@app_commands.describe(
    ausbildung="Wähle die Ausbildung"
)
async def abschliessen_command(
    interaction: discord.Interaction,
    ausbildung: str
):
    """
    Slash Command zum Abschließen und Posten einer Auswertung.
    """
    # Berechtigungsprüfung
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return
    
    try:
        ausbildung_id = int(ausbildung)
    except ValueError:
        await interaction.response.send_message(
            "❌ Fehler: Ungültige Ausbildungs-ID!",
            ephemeral=True
        )
        return
    
    # Prüfe, ob die Ausbildung existiert
    ausbildung_data = data_manager.get_ausbildung(ausbildung_id)
    if not ausbildung_data:
        await interaction.response.send_message(
            f"❌ Fehler: Ausbildung mit ID {ausbildung_id} nicht gefunden!",
            ephemeral=True
        )
        return
    
    # Hole Teilnehmer
    teilnehmer = data_manager.get_teilnehmer(ausbildung_id)
    if not teilnehmer:
        await interaction.response.send_message(
            "❌ Fehler: Keine Teilnehmer für diese Ausbildung vorhanden!",
            ephemeral=True
        )
        return
    
    # Hole die Mindestpunktzahl und Maximalpunktzahl für diese spezifische Abteilung
    bereich = ausbildung_data['bereich']
    if bereich not in config["abteilungen"]:
        await interaction.response.send_message(
            f"❌ Fehler: Abteilung '{bereich}' nicht in der Konfiguration gefunden!",
            ephemeral=True
        )
        return
    
    abteilung_config = config["abteilungen"][bereich]
    mindestpunktzahl = abteilung_config.get("mindestpunktzahl", 50)
    maximalpunktzahl = abteilung_config.get("maximalpunktzahl", 100)
    auswertungskanal_id = int(abteilung_config.get("auswertungskanal_id", 0))
    
    # Sortiere Teilnehmer nach Bestanden/Nicht bestanden
    bestanden = []
    nicht_bestanden = []
    
    for t in teilnehmer:
        note = berechne_note(t["punktzahl"], maximalpunktzahl, mindestpunktzahl)
        t["note"] = note
        
        if note in {"1", "2", "3"}:
            bestanden.append(t)
        else:
            nicht_bestanden.append(t)
    
    # Erstelle Auswertungsnachricht
    nachricht = f"# <:PolizeiLogo:1426569477738205287> __Auswertung der {bereich}__ <:PolizeiLogo:1426569477738205287>\n\n\n"
    
    nachricht += "**Bestanden haben:**\n\n"
    if bestanden:
        for t in bestanden:
            nachricht += f"> Name: {t['name']}\n"
            nachricht += f"> Punkte: {t['punktzahl']}/{maximalpunktzahl}\n"
            nachricht += f"> Note: {t['note']}\n"
            nachricht += f"> Datum: {t.get('datum', 'Nicht angegeben')}\n\n"
    else:
        nachricht += "> Keine Teilnehmer\n\n"
    
    nachricht += "**Nicht bestanden haben:**\n\n"
    if nicht_bestanden:
        for t in nicht_bestanden:
            nachricht += f"> Name: {t['name']}\n"
            nachricht += f"> Punkte: {t['punktzahl']}/{maximalpunktzahl}\n"
            nachricht += f"> Note: {t['note']}\n"
            nachricht += f"> Datum: {t.get('datum', 'Nicht angegeben')}\n\n"
    else:
        nachricht += "> Alle Teilnehmer haben bestanden!\n\n"
    
    feedback_link = config.get("feedback_link", "https://discord.com/channels/1420498529708806166/1420665010543263816")
    nachricht += f"\n\n\nEure Ausbilder wünschen euch alles gute!\n"
    nachricht += f"Über ein {feedback_link} würden wir uns dennoch freuen!\n\n\n"
    nachricht += f"**Hochachtungsvoll**\n\n{ausbildung_data['host']}"
    
    # Hole Auswertungskanal
    if not auswertungskanal_id:
        await interaction.response.send_message(
            f"❌ Fehler: Kein Auswertungskanal für '{bereich}' konfiguriert!",
            ephemeral=True
        )
        return
    
    kanal = bot.get_channel(auswertungskanal_id)
    
    if not kanal:
        await interaction.response.send_message(
            f"❌ Fehler: Auswertungskanal mit ID {auswertungskanal_id} nicht gefunden!",
            ephemeral=True
        )
        return
    
    # Sende Auswertung und verwalte Rollen
    rollen_warnung = ""
    try:
        await kanal.send(nachricht)
        data_manager.set_auswertung_abgeschlossen(ausbildung_id, True)
        
        # Verwalte Rollen basierend auf Ergebnis
        rolle_bestanden_id = abteilung_config.get("rolle_bestanden")
        rolle_nicht_bestanden_id = abteilung_config.get("rolle_nicht_bestanden")
        
        # Nur Rollen verwalten, wenn sie definiert sind (nicht PLACEHOLDER)
        hat_placeholder = (
            (rolle_bestanden_id and "PLACEHOLDER" in str(rolle_bestanden_id)) or
            (rolle_nicht_bestanden_id and "PLACEHOLDER" in str(rolle_nicht_bestanden_id))
        )
        if hat_placeholder:
            rollen_warnung = "\n⚠️ **Hinweis:** Rollen für diese Abteilung sind noch nicht konfiguriert (PLACEHOLDER). Rollenvergabe übersprungen."
        elif rolle_bestanden_id and "PLACEHOLDER" not in rolle_bestanden_id:
            rolle_bestanden = interaction.guild.get_role(int(rolle_bestanden_id))
            rolle_nicht_bestanden = None
            
            if rolle_nicht_bestanden_id and "PLACEHOLDER" not in rolle_nicht_bestanden_id:
                rolle_nicht_bestanden = interaction.guild.get_role(int(rolle_nicht_bestanden_id))
            
            # Verwalte Rollen nur für bestandene Teilnehmer
            for t in bestanden:
                try:
                    # Extrahiere User ID aus Mention (z.B. "<@123456789>" oder "<@!123456789>")
                    match = re.search(r'<@!?(\d+)>', t['name'])
                    if match:
                        user_id = int(match.group(1))
                        mitglied = interaction.guild.get_member(user_id)
                        if not mitglied:
                            try:
                                mitglied = await interaction.guild.fetch_member(user_id)
                            except (discord.NotFound, discord.Forbidden):
                                mitglied = None
                        
                        if mitglied:
                            # Gebe bestanden Rolle
                            if rolle_bestanden:
                                await mitglied.add_roles(rolle_bestanden)
                            
                            # Entferne nicht_bestanden Rolle
                            if rolle_nicht_bestanden:
                                await mitglied.remove_roles(rolle_nicht_bestanden)
                except (ValueError, AttributeError, discord.Forbidden):
                    # Fehler beim Parsen oder bei der Rollenänderung
                    pass
        
        await interaction.response.send_message(
            f"✅ Auswertung erfolgreich im Kanal {kanal.mention} gepostet!{rollen_warnung}",
            ephemeral=True
        )
        await log_aktion(
            "📊 Auswertung abgeschlossen",
            "Eine Ausbildungsauswertung wurde gepostet.",
            discord.Color.purple(),
            [
                ("Ausbildung", bereich, True),
                ("Bestanden", str(len(bestanden)), True),
                ("Nicht bestanden", str(len(nicht_bestanden)), True),
                ("Kanal", kanal.mention, False)
            ]
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Fehler: Keine Berechtigung zum Senden im Kanal {kanal.mention}!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Fehler beim Posten der Auswertung: {str(e)}",
            ephemeral=True
        )


# Autocomplete für Ausbildungsauswahl beim Abschließen
@abschliessen_command.autocomplete('ausbildung')
async def abschliessen_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await offene_ausbildung_autocomplete(interaction, current)


@tree.command(name="uebersicht", description="Zeigt alle aktiven Ausbildungen auf einen Blick")
async def uebersicht_command(interaction: discord.Interaction):
    """Übersicht aller nicht-archivierten Ausbildungen."""
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return

    active = data_manager.get_non_archived_ausbildungen()
    if not active:
        await interaction.response.send_message(
            "📋 Keine aktiven Ausbildungen vorhanden.",
            ephemeral=True
        )
        return

    offen = [a for a in active.values() if not a.get('ausgewertet')]
    ausgewertet = [a for a in active.values() if a.get('ausgewertet')]

    embed = discord.Embed(
        title="📋 Aktive Ausbildungen",
        description=(
            f"**{len(active)}** aktive Ausbildung(en) — "
            f"📝 {len(offen)} offen • 📊 {len(ausgewertet)} ausgewertet"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.now(timezone.utc)
    )

    for ausb_id, ausb in sorted(active.items(), key=lambda x: int(x[0])):
        status = "📊 Ausgewertet" if ausb.get('ausgewertet') else "📝 Offen"
        teilnehmer_count = len(ausb.get('teilnehmer', []))
        embed.add_field(
            name=f"#{ausb_id} • {ausb['bereich']}",
            value=(
                f"📅 {ausb['datum']} ⏰ {ausb['uhrzeit']}\n"
                f"👤 {ausb['host']}\n"
                f"👥 {teilnehmer_count} Teilnehmer | {status}"
            ),
            inline=True
        )

    embed.set_footer(text="Akademie • Übersicht")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="statistik_alle", description="Zeigt Statistiken aller Ausbilder")
@app_commands.describe(
    tage="Anzahl der Tage zurück (z.B. 7 für letzte Woche, 30 für letzten Monat)"
)
async def statistik_alle_command(
    interaction: discord.Interaction,
    tage: int = 30
):
    """
    Zeigt Statistiken aller Ausbilder für einen bestimmten Zeitraum.
    """
    # Berechtigungsprüfung
    if not hat_statistik_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return
    
    # Sammle Statistiken
    stats = sammle_statistiken(tage)
    
    if not stats:
        await interaction.response.send_message(
            f"Keine Ausbildungen in den letzten {tage} Tagen gefunden.",
            ephemeral=True
        )
        return
    
    # Sortiere nach Gesamt-Anzahl (absteigend)
    sortierte_stats = sorted(stats.items(), key=lambda x: x[1]['gesamt'], reverse=True)
    
    embed = discord.Embed(
        title="📈 Ausbilder-Statistik",
        description=f"Zeitraum: Letzte **{tage} Tage** • {len(sortierte_stats)} Ausbilder",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.now(timezone.utc)
    )

    for i, (user_mention, user_stats) in enumerate(sortierte_stats[:25], 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "▫️")
        gehalt = user_stats['host'] * 3000 + user_stats['cohost'] * 1500
        embed.add_field(
            name=f"{medal} Platz {i}",
            value=(
                f"{user_mention}\n"
                f"🎤 Host: **{user_stats['host']}x** • 🤝 Co-Host: **{user_stats['cohost']}x** • 🙋 Helfer: **{user_stats['helfer']}x**\n"
                f"📊 Gesamt: **{user_stats['gesamt']}** | 💰 Gehalt: **{gehalt:,}$**"
            ),
            inline=False
        )

    embed.set_footer(text="Akademie • Statistik")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="statistik_person", description="Zeigt Statistiken einer bestimmten Person")
@app_commands.describe(
    person="Die Person, deren Statistik angezeigt werden soll",
    tage="Anzahl der Tage zurück (z.B. 7 für letzte Woche, 30 für letzten Monat)"
)
async def statistik_person_command(
    interaction: discord.Interaction,
    person: discord.User,
    tage: int = 30
):
    """
    Zeigt detaillierte Statistiken einer bestimmten Person.
    """
    # Berechtigungsprüfung
    if not hat_statistik_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return
    
    # Sammle Statistiken
    stats, ausbildungs_liste = sammle_person_statistik(person.mention, tage)
    
    if stats['gesamt'] == 0:
        await interaction.response.send_message(
            f"{person.mention} hat in den letzten {tage} Tagen keine Ausbildungen durchgeführt.",
            ephemeral=True
        )
        return
    
    # Erstelle Embed
    gehalt = stats['host'] * 3000 + stats['cohost'] * 1500

    embed = discord.Embed(
        title=f"📈 Statistik — {person.display_name}",
        description=f"Zeitraum: Letzte **{tage} Tage**",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=person.display_avatar.url)
    embed.add_field(
        name="📊 Übersicht",
        value=(
            f"🎤 Host: **{stats['host']}x** • 🤝 Co-Host: **{stats['cohost']}x** • 🙋 Helfer: **{stats['helfer']}x**\n"
            f"📊 Gesamt: **{stats['gesamt']}** | 💰 Gehalt: **{gehalt:,}$**"
        ),
        inline=False
    )

    if ausbildungs_liste:
        liste_text = ""
        for ausb in ausbildungs_liste[:15]:
            rolle_emoji = {"Host": "🎤", "Co-Host": "🤝", "Helfer": "🙋"}.get(ausb['rolle'], "•")
            liste_text += f"{rolle_emoji} **{ausb['datum']}** — {ausb['bereich']}\n"
        if len(ausbildungs_liste) > 15:
            liste_text += f"*...und {len(ausbildungs_liste) - 15} weitere*"
        embed.add_field(name="📋 Durchgeführte Ausbildungen", value=liste_text, inline=False)

    embed.set_footer(text="Akademie • Personenstatistik")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== TEILNEHMER ENTFERNEN ====================

class TeilnehmerSelect(discord.ui.Select):
    """
    Select-Menu für die Auswahl von Teilnehmern zum Entfernen.
    """
    def __init__(self, ausbildung_id: int, teilnehmer_liste: List[Dict], guild: discord.Guild = None):
        self.ausbildung_id = ausbildung_id
        self.teilnehmer_liste = teilnehmer_liste
        
        # Erstelle Options aus Teilnehmern
        options = []
        for idx, teilnehmer in enumerate(teilnehmer_liste):
            # Zeige lesbaren Namen statt roher Mention
            display_name = teilnehmer["name"]
            if guild:
                match = re.search(r'<@!?(\d+)>', teilnehmer["name"])
                if match:
                    member = guild.get_member(int(match.group(1)))
                    if member:
                        display_name = member.display_name
            option = discord.SelectOption(
                label=display_name[:100],
                value=str(idx),
                description=f"{teilnehmer['punktzahl']} Punkte"
            )
            options.append(option)
        
        super().__init__(
            placeholder="Wähle einen Teilnehmer zum Entfernen...",
            min_values=1,
            max_values=len(options) if options else 1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        """
        Wird aufgerufen, wenn der User Teilnehmer auswählt.
        """
        # Entferne die ausgewählten Teilnehmer
        gelöschte_teilnehmer = []
        
        for selected_idx in self.values:
            idx = int(selected_idx)
            teilnehmer = self.teilnehmer_liste[idx]
            
            if data_manager.remove_teilnehmer(self.ausbildung_id, teilnehmer["name"]):
                gelöschte_teilnehmer.append(teilnehmer["name"])
        
        if gelöschte_teilnehmer:
            nachricht = "✅ Folgende Teilnehmer wurden entfernt:\n\n"
            for name in gelöschte_teilnehmer:
                nachricht += f"• {name}\n"
            
            await interaction.response.send_message(nachricht, ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Fehler beim Entfernen der Teilnehmer!",
                ephemeral=True
            )


class TeilnehmerView(discord.ui.View):
    """
    View mit Select-Menu für Teilnehmerauswahl.
    """
    def __init__(self, ausbildung_id: int, teilnehmer_liste: List[Dict], guild: discord.Guild = None):
        super().__init__()
        
        if teilnehmer_liste:
            self.add_item(TeilnehmerSelect(ausbildung_id, teilnehmer_liste, guild))


@tree.command(name="entfernen", description="Entferne Teilnehmer aus einer Auswertung")
@app_commands.describe(
    ausbildung="Wähle die Ausbildung"
)
async def entfernen_command(
    interaction: discord.Interaction,
    ausbildung: str
):
    """
    Slash Command zum Entfernen von Teilnehmern aus einer Ausbildung.
    """
    # Berechtigungsprüfung
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung, diesen Command zu nutzen!",
            ephemeral=True
        )
        return
    
    try:
        ausbildung_id = int(ausbildung)
    except ValueError:
        await interaction.response.send_message(
            "❌ Fehler: Ungültige Ausbildungs-ID!",
            ephemeral=True
        )
        return
    
    # Prüfe, ob die Ausbildung existiert
    ausbildung_data = data_manager.get_ausbildung(ausbildung_id)
    if not ausbildung_data:
        await interaction.response.send_message(
            f"❌ Fehler: Ausbildung mit ID {ausbildung_id} nicht gefunden!",
            ephemeral=True
        )
        return
    
    # Hole alle Teilnehmer
    teilnehmer = data_manager.get_teilnehmer(ausbildung_id)
    
    if not teilnehmer:
        await interaction.response.send_message(
            "❌ Diese Ausbildung hat noch keine Teilnehmer!",
            ephemeral=True
        )
        return
    
    # Erstelle die View mit Select-Menu
    view = TeilnehmerView(ausbildung_id, teilnehmer, interaction.guild)
    
    # Zeige aktuelle Teilnehmer
    nachricht = f"**Teilnehmer der Ausbildung {ausbildung_data['bereich']} ({ausbildung_data['datum']})**\n\n"
    
    for i, teilnehmer_data in enumerate(teilnehmer, 1):
        nachricht += f"{i}. {teilnehmer_data['name']} - {teilnehmer_data['punktzahl']} Punkte\n"
    
    nachricht += "\n**Wähle einen oder mehrere Teilnehmer zum Entfernen:**"
    
    await interaction.response.send_message(
        nachricht,
        view=view,
        ephemeral=True
    )


# Autocomplete für Ausbildungsauswahl beim Teilnehmer entfernen
@entfernen_command.autocomplete('ausbildung')
async def entfernen_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await offene_ausbildung_autocomplete(interaction, current)


# ==================== BULK AUSWERTUNG ====================

class BulkPunkteModal(discord.ui.Modal):
    """Modal das NUR nach der Punktzahl fragt — User wurde schon per Dropdown gewählt."""
    def __init__(self, ausbildung_id: int, bereich: str, datum: str, user: discord.Member, view_ref):
        super().__init__(title=f"Punkte für {user.display_name}")
        self.ausbildung_id = ausbildung_id
        self.bereich = bereich
        self.datum = datum
        self.user = user
        self.view_ref = view_ref

        self.punktzahl = discord.ui.TextInput(
            label="Punktzahl",
            placeholder="z.B. 45",
            required=True,
            max_length=5
        )
        self.add_item(self.punktzahl)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            punkte = int(self.punktzahl.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Bitte eine gültige Zahl eingeben.", ephemeral=True)
            return

        ok = data_manager.add_teilnehmer(
            self.ausbildung_id, self.user.mention, punkte, self.datum
        )
        if ok:
            self.view_ref.eingetragen.append(f"{self.user.mention} — **{punkte}** Punkte")
            await interaction.response.edit_message(
                content=self.view_ref.build_message(),
                view=self.view_ref
            )
        else:
            await interaction.response.send_message("❌ Fehler beim Speichern.", ephemeral=True)


class BulkUserSelect(discord.ui.UserSelect):
    """Dropdown zum Auswählen eines Server-Mitglieds."""
    def __init__(self):
        super().__init__(placeholder="Teilnehmer auswählen...", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        user = self.values[0]
        view = self.view
        await interaction.response.send_modal(
            BulkPunkteModal(
                view.ausbildung_id,
                view.bereich,
                view.datum,
                user,
                view
            )
        )


class BulkFertigButton(discord.ui.Button):
    """Button zum Abschließen der Bulk-Eingabe."""
    def __init__(self):
        super().__init__(label="✅ Fertig", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        for child in view.children:
            child.disabled = True
        count = len(view.eingetragen)
        await interaction.response.edit_message(
            content=f"✅ **{count} Teilnehmer eingetragen** für {view.bereich}.\n\n" +
                    "\n".join(f"• {e}" for e in view.eingetragen) if view.eingetragen else "Keine Teilnehmer eingetragen.",
            view=view
        )
        if view.eingetragen:
            await log_aktion(
                "👥 Bulk-Auswertung",
                f"{count} Teilnehmer für {view.bereich} eingetragen.",
                discord.Color.blue(),
                [
                    ("Ausbildung", f"{view.bereich} (ID: {view.ausbildung_id})", True),
                    ("Anzahl", str(count), True),
                    ("Von", interaction.user.display_name, True)
                ]
            )
        view.stop()


class BulkAuswertungView(discord.ui.View):
    """View mit User-Dropdown + Fertig-Button für einfache Bulk-Eingabe."""
    def __init__(self, ausbildung_id: int, bereich: str, datum: str):
        super().__init__(timeout=300)
        self.ausbildung_id = ausbildung_id
        self.bereich = bereich
        self.datum = datum
        self.eingetragen: List[str] = []
        self.add_item(BulkUserSelect())
        self.add_item(BulkFertigButton())

    def build_message(self) -> str:
        msg = f"**Teilnehmer eintragen — {self.bereich}**\n\n"
        msg += "Wähle unten einen Teilnehmer aus, gib die Punkte ein, und wiederhole das für jeden weiteren.\n"
        msg += "Wenn du fertig bist, drücke **✅ Fertig**.\n"
        if self.eingetragen:
            msg += f"\n📋 **Bereits eingetragen ({len(self.eingetragen)}):**\n"
            for e in self.eingetragen:
                msg += f"• {e}\n"
        return msg


@tree.command(name="bulk", description="Mehrere Teilnehmer einfach zur Auswertung hinzufügen")
@app_commands.describe(ausbildung="Wähle die Ausbildung")
async def bulk_command(
    interaction: discord.Interaction,
    ausbildung: str
):
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung!", ephemeral=True
        )
        return

    try:
        ausbildung_id = int(ausbildung)
    except ValueError:
        await interaction.response.send_message("❌ Ungültige Ausbildungs-ID!", ephemeral=True)
        return

    ausbildung_data = data_manager.get_ausbildung(ausbildung_id)
    if not ausbildung_data:
        await interaction.response.send_message(
            f"❌ Ausbildung mit ID {ausbildung_id} nicht gefunden!", ephemeral=True
        )
        return

    view = BulkAuswertungView(ausbildung_id, ausbildung_data['bereich'], ausbildung_data['datum'])
    await interaction.response.send_message(view.build_message(), view=view, ephemeral=True)


@bulk_command.autocomplete('ausbildung')
async def bulk_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await alle_ausbildung_autocomplete(interaction, current)


# ==================== INFO COMMAND ====================

@tree.command(name="info", description="Zeigt Details zu einer bestimmten Ausbildung")
@app_commands.describe(ausbildung="Wähle die Ausbildung")
async def info_command(
    interaction: discord.Interaction,
    ausbildung: str
):
    if not hat_ausbilder_berechtigung(interaction):
        await interaction.response.send_message(
            "❌ Du hast keine Berechtigung!", ephemeral=True
        )
        return

    try:
        ausbildung_id = int(ausbildung)
    except ValueError:
        await interaction.response.send_message("❌ Ungültige Ausbildungs-ID!", ephemeral=True)
        return

    data = data_manager.get_ausbildung(ausbildung_id)
    if not data:
        await interaction.response.send_message(
            f"❌ Ausbildung mit ID {ausbildung_id} nicht gefunden!", ephemeral=True
        )
        return

    # Status bestimmen
    if data.get('archiviert'):
        status = "📦 Archiviert"
    elif data.get('ausgewertet'):
        status = "📊 Ausgewertet"
    else:
        status = "📝 Offen"

    bereich = data['bereich']
    abt_config = config["abteilungen"].get(bereich, {})
    mindest = abt_config.get("mindestpunktzahl", "?")
    maximal = abt_config.get("maximalpunktzahl", "?")

    embed = discord.Embed(
        title=f"#{ausbildung_id} • {bereich}",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="📅 Datum", value=data['datum'], inline=True)
    embed.add_field(name="⏰ Uhrzeit", value=data['uhrzeit'], inline=True)
    embed.add_field(name="📌 Status", value=status, inline=True)
    embed.add_field(name="🎤 Host", value=data['host'], inline=True)
    embed.add_field(name="🤝 Co-Host", value=data.get('cohost', 'Nicht zugewiesen'), inline=True)
    embed.add_field(name="🙋 Helfer", value=data.get('helfer', 'Nicht zugewiesen'), inline=True)
    embed.add_field(name="📊 Punkteskala", value=f"Mindestens **{mindest}** / Max **{maximal}**", inline=False)

    teilnehmer = data.get('teilnehmer', [])
    if teilnehmer:
        tn_text = ""
        for i, t in enumerate(teilnehmer, 1):
            note = berechne_note(t['punktzahl'], int(maximal) if str(maximal).isdigit() else 100, int(mindest) if str(mindest).isdigit() else 0)
            bestanden = "✅" if note in {"1", "2", "3"} else "❌"
            tn_text += f"{bestanden} {t['name']} — **{t['punktzahl']}/{maximal}** (Note {note})\n"
        embed.add_field(
            name=f"👥 Teilnehmer ({len(teilnehmer)})",
            value=tn_text[:1024],
            inline=False
        )
    else:
        embed.add_field(name="👥 Teilnehmer", value="Noch keine Teilnehmer eingetragen.", inline=False)

    embed.set_footer(text="Akademie • Ausbildungsdetails")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@info_command.autocomplete('ausbildung')
async def info_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    return await alle_ausbildung_autocomplete(interaction, current)


# ==================== BOT STARTEN ====================

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ Fehler: DISCORD_TOKEN nicht in .env gefunden!")
        print("Bitte erstelle eine .env Datei mit deinem Bot-Token.")
        exit(1)
    
    bot.run(token)
