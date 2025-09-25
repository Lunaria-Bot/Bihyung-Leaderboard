import discord
from discord import app_commands
import asyncio
import os
import re
import redis.asyncio as aioredis

TOKEN = os.getenv("DISCORD_TOKEN_LEADERBOARD")
REDIS_URL = os.getenv("REDIS_URL")

GUILD_ID = 1196690004852883507
MAZOKU_BOT_ID = 1242388858897956906

# Point bonus ranks
BONUS_ROLES = {1298320344037462177, 1200391843830055004}

# Points per Rarity 
RARITY_POINTS = {
    "1342202221558763571": 1,   #C
    "1342202219574857788": 3,   #R
    "1342202597389373530": 7,   #SR
    "1342202212948115510": 13,  #SSR
    "1342202203515125801": 17   #UR
}

EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

class LeaderboardBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.redis = None
        self.tree = app_commands.CommandTree(self)
        self.paused = False
        self.stopped = False

    async def setup_hook(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = LeaderboardBot()

# ----------------
# Slash commands
# ----------------
@client.tree.command(name="leaderboard", description="Voir le classement actuel")
async def leaderboard(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis non connecté.", ephemeral=True)
        return

    scores = await client.redis.hgetall("leaderboard")
    if not scores:
        await interaction.response.send_message("📊 Aucun point enregistré pour l'instant.", ephemeral=True)
        return

    sorted_scores = sorted(scores.items(), key=lambda x: int(x[1]), reverse=True)
    embed = discord.Embed(title="🌻 Leaderboard", color=discord.Color.gold())
    for i, (user_id, points) in enumerate(sorted_scores[:10], start=1):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        embed.add_field(name=f"#{i} {name}", value=f"{points} points", inline=False)

    await interaction.response.send_message(embed=embed)

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

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    print(f"✅ Leaderboard bot connecté en tant que {client.user}")

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

    # Détection claim via embed
    if message.embeds:
        embed = message.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""

        if "summon claimed" in title:
            # Trouver le joueur
            match = re.search(r"Claimed By\s+<@!?(\d+)>", desc)
            if not match and embed.fields:
                for field in embed.fields:
                    match = re.search(r"<@!?(\d+)>", field.value)
                    if match:
                        break
            if not match and embed.footer and embed.footer.text:
                match = re.search(r"<@!?(\d+)>", embed.footer.text)

            if match:
                user_id = int(match.group(1))
                member = message.guild.get_member(user_id)
                if not member:
                    return

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
                    for emote_id in matches:
                        if emote_id in RARITY_POINTS:
                            rarity_points = RARITY_POINTS[emote_id]
                            break
                    if rarity_points:
                        break

                if rarity_points:
                    # Bonus si rôle
                    bonus = 1 if any(r.id in BONUS_ROLES for r in member.roles) else 0
                    total_points = rarity_points + bonus
                    await client.redis.hincrby("leaderboard", str(user_id), total_points)
                    print(f"✅ {member.display_name} gagne {total_points} points (total {rarity_points}+{bonus})")

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_LEADERBOARD manquant")
client.run(TOKEN)
