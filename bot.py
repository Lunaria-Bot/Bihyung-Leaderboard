import discord
from discord import app_commands
import asyncio
import os
import re
import redis.asyncio as aioredis
import logging
import itertools

# --- Logging configuration ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True
)
log = logging.getLogger("leaderboard-bot")

# --- Env variables ---
TOKEN = os.getenv("DISCORD_TOKEN_LEADERBOARD")
REDIS_URL = os.getenv("REDIS_URL")

# --- Constants ---
GUILD_ID = 1196690004852883507
MAZOKU_BOT_ID = 1242388858897956906

# Rôles bonus
BONUS_ROLES = {1298320344037462177, 1200391843830055004}

# Points par rareté (IDs d'emojis Mazoku)
RARITY_POINTS = {
    "1342202221558763571": 1,   # Common
    "1342202219574857788": 3,   # Rare
    "1342202597389373530": 7,   # Super Rare
    "1342202203515125801": 17   # Ultra Rare
}

EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

# --- Discord intents ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

# --- Client class ---
class LeaderboardBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.redis = None
        self.tree = app_commands.CommandTree(self)
        self.paused = False
        self.stopped = False

    async def setup_hook(self):
        # Connect Redis
        try:
            self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
            log.info("✅ Redis connecté")
        except Exception:
            log.exception("❌ Impossible de se connecter à Redis")
            self.redis = None

        # Sync slash commands for the guild
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = LeaderboardBot()

# ----------------
# Status rotation
# ----------------
STATUSES = [
    discord.Activity(type=discord.ActivityType.watching, name="challengers climb the leaderboard of this scenario."),
    discord.Activity(type=discord.ActivityType.playing, name="with the struggles of constellations."),
    discord.Activity(type=discord.ActivityType.listening, name="the void until the next scenario begins…")
]

async def cycle_status():
    for activity in itertools.cycle(STATUSES):
        await client.change_presence(activity=activity, status=discord.Status.online)
        await asyncio.sleep(300)  # change toutes les 5 minutes

# ----------------
# Slash commands
# ----------------
@client.tree.command(name="leaderboard", description="Voir le classement actuel (Top 10)")
async def leaderboard(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis non connecté.", ephemeral=True)
        return

    scores = await client.redis.hgetall("leaderboard")
    if not scores:
        await interaction.response.send_message("📊 Aucun point enregistré pour l'instant.", ephemeral=True)
        return

    sorted_scores = sorted(scores.items(), key=lambda x: int(x[1]), reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    description_lines = []
    for i, (user_id, points) in enumerate(sorted_scores[:10], start=1):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        prefix = medals[i-1] if i <= 3 else f"#{i}"
        description_lines.append(f"{prefix} **{name}** ➔ {points} points")

    # Rang de l’utilisateur qui tape la commande
    user_rank = None
    for i, (user_id, points) in enumerate(sorted_scores, start=1):
        if str(interaction.user.id) == user_id:
            user_rank = (i, points)
            break

    embed = discord.Embed(
        title="🏆 Leaderboard du serveur",
        description="\n".join(description_lines),
        color=discord.Color.gold()
    )
    if user_rank:
        embed.set_footer(text=f"Ton rang : #{user_rank[0]} avec {user_rank[1]} points")
    else:
        embed.set_footer(text="Tu n’as pas encore de points, participe pour entrer dans le classement !")

    await interaction.response.send_message(embed=embed)

@client.tree.command(name="leaderboard-full", description="Voir le classement complet (Admin only)")
async def leaderboard_full(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    scores = await client.redis.hgetall("leaderboard")
    if not scores:
        await interaction.response.send_message("📊 Aucun point enregistré pour l'instant.", ephemeral=True)
        return

    sorted_scores = sorted(scores.items(), key=lambda x: int(x[1]), reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    description_lines = []
    for i, (user_id, points) in enumerate(sorted_scores, start=1):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        prefix = medals[i-1] if i <= 3 else f"#{i}"
        description_lines.append(f"{prefix} **{name}** ➔ {points} points")

    # Découpage en pages de 20 lignes max
    chunks = [description_lines[i:i+20] for i in range(0, len(description_lines), 20)]
    first_embed = discord.Embed(
        title=f"📜 Classement complet — Page 1/{len(chunks)}",
        description="\n".join(chunks[0]),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=first_embed, ephemeral=True)
    for idx in range(1, len(chunks)):
        embed = discord.Embed(
            title=f"📜 Classement complet — Page {idx+1}/{len(chunks)}",
            description="\n".join(chunks[idx]),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# ----------------
# Admin commands
# ----------------
@client.tree.command(name="leaderboard-pause", description="Met le leaderboard en pause (Admin only)")
async def leaderboard_pause(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    client.paused = True
    await interaction.response.send_message("⏸️ Leaderboard mis en pause.")

@client.tree.command(name="leaderboard-resume", description="Relance le leaderboard (Admin only)")
async def leaderboard_resume(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    client.paused = False
    await interaction.response.send_message("▶️ Leaderboard relancé.")

@client.tree.command(name="leaderboard-stop", description="Stoppe le leaderboard (Admin only)")
async def leaderboard_stop(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    client.stopped = True
    await interaction.response.send_message("⏹️ Leaderboard stoppé.")

@client.tree.command(name="leaderboard-reset", description="Réinitialise tous les scores (Admin only)")
async def leaderboard_reset(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    await client.redis.delete("leaderboard")
    await interaction.response.send_message("🔄 Leaderboard réinitialisé !")

@client.tree.command(name="debug-score", description="Voir le score d’un joueur (Admin only)")
@app_commands.describe(member="Le joueur dont tu veux voir le score")
async def debug_score(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    score = await client.redis.hget("leaderboard", str(member.id))
    score = score if score else 0
    await interaction.response.send_message(f"🔍 Score actuel de {member.mention} : **{score} points**", ephemeral=True)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    log.info("✅ Leaderboard bot connecté en tant que %s (%s)", client.user, client.user.id)
    client.loop.create_task(heartbeat())
    client.loop.create_task(cycle_status())  # lancement du cycle de statuts

async def heartbeat():
    while True:
        log.info("💓 Heartbeat: bot vivant, paused=%s, stopped=%s", client.paused, client.stopped)
        await asyncio.sleep(60)

@client.event
async def on_message(message: discord.Message):
    if client.stopped or client.paused:
        return
    if not client.redis:
        return
    if message.author.id == client.user.id:
        return
    if message.guild and message.guild.id != GUILD_ID:
        return
    if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
        return

    log.debug("Message reçu de Mazoku: %s", message.embeds[0].title if message.embeds else "pas d’embed")

    if not message.embeds:
        return

    embed = message.embeds[0]
    title = (embed.title or "").lower()
    desc = embed.description or ""

    # ✅ Désormais seuls les Auto Summon comptent
    if "auto summon claimed" in title:
        log.debug("Détection d’un claim (Auto Summon uniquement) !")

        # Trouver le joueur (dans description, champs ou footer)
        match = re.search(r"Claimed By\s+<@!?(\d+)>", desc)
        if not match and embed.fields:
            for field in embed.fields:
                match = re.search(r"<@!?(\d+)>", (field.value or ""))
                if match:
                    break
        if not match and embed.footer and embed.footer.text:
            match = re.search(r"<@!?(\d+)>", embed.footer.text)

        if match:
            user_id = int(match.group(1))
            member = message.guild.get_member(user_id)
            if not member:
                log.warning("⚠️ Joueur trouvé (%s) mais pas présent dans le serveur.", user_id)
                return

            log.info("Claim détecté par %s (%s)", member.display_name, member.id)

            # Détection rareté via emojis
            rarity_points = 0
            text_to_scan = [embed.title or "", embed.description or ""]
            if embed.fields:
                for field in embed.fields:
                    text_to_scan.append(field.name or "")
                    text_to_scan.append(field.value or "")
            if embed.footer and embed.footer.text:
                text_to_scan.append(embed.footer.text)

            for text in text_to_scan:
                matches = EMOJI_REGEX.findall(text)
                if matches:
                    log.debug("Emojis trouvés: %s", matches)
                for emote_id in matches:
                    if emote_id in RARITY_POINTS:
                        rarity_points = RARITY_POINTS[emote_id]
                        log.info("Rareté détectée: %s → %s points", emote_id, rarity_points)
                        break
                if rarity_points:
                    break

            if rarity_points:
                bonus = 1 if any(r.id in BONUS_ROLES for r in member.roles) else 0
                total_points = rarity_points + bonus
                await client.redis.hincrby("leaderboard", str(user_id), total_points)
                new_score = await client.redis.hget("leaderboard", str(user_id))
                log.info(
                    "%s gagne %s points (base %s + bonus %s) → Nouveau score: %s",
                    member.display_name, total_points, rarity_points, bonus, new_score
                )
            else:
                log.warning("⚠️ Aucun emoji de rareté trouvé dans l’embed de claim.")
        else:
            log.warning("⚠️ Aucun joueur détecté dans l’embed de claim.")

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_LEADERBOARD manquant")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL manquant")

log.info("🚀 Tentative de connexion avec Discord...")
client.run(TOKEN)
