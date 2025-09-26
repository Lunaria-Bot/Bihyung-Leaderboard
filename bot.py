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

# --- Environment variables ---
TOKEN = os.getenv("DISCORD_TOKEN_LEADERBOARD")
REDIS_URL = os.getenv("REDIS_URL")

# --- Constants ---
GUILD_ID = 1196690004852883507
MAZOKU_BOT_ID = 1242388858897956906

# Bonus roles
BONUS_ROLES = {1298320344037462177, 1200391843830055004}

# Points per rarity (Mazoku emoji IDs)
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
            log.info("✅ Redis connected")
        except Exception:
            log.exception("❌ Could not connect to Redis")
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
    discord.Activity(type=discord.ActivityType.watching, name="players climb the leaderboard."),
    discord.Activity(type=discord.ActivityType.playing, name="with the struggles of constellations."),
    discord.Activity(type=discord.ActivityType.listening, name="the void until the next scenario begins…")
]

async def cycle_status():
    for activity in itertools.cycle(STATUSES):
        await client.change_presence(activity=activity, status=discord.Status.online)
        await asyncio.sleep(300)  # change every 5 minutes

# ----------------
# Slash commands
# ----------------
@client.tree.command(name="leaderboard", description="View the current leaderboard (Top 10)")
async def leaderboard(interaction: discord.Interaction):
    if not client.redis:
        await interaction.response.send_message("❌ Redis not connected.", ephemeral=True)
        return

    scores = await client.redis.hgetall("leaderboard")
    if not scores:
        await interaction.response.send_message("📊 No points recorded yet.", ephemeral=True)
        return

    sorted_scores = sorted(scores.items(), key=lambda x: int(x[1]), reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    description_lines = []
    for i, (user_id, points) in enumerate(sorted_scores[:10], start=1):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        prefix = medals[i-1] if i <= 3 else f"#{i}"
        description_lines.append(f"{prefix} **{name}** ➔ {points} points")

    # User rank
    user_rank = None
    for i, (user_id, points) in enumerate(sorted_scores, start=1):
        if str(interaction.user.id) == user_id:
            user_rank = (i, points)
            break

    embed = discord.Embed(
        title="🏆 Server Leaderboard",
        description="\n".join(description_lines),
        color=discord.Color.gold()
    )
    if user_rank:
        embed.set_footer(text=f"Your rank: #{user_rank[0]} with {user_rank[1]} points")
    else:
        embed.set_footer(text="You don’t have any points yet. Participate to enter the leaderboard!")

    await interaction.response.send_message(embed=embed)

@client.tree.command(name="leaderboard-full", description="View the full leaderboard (Admin only)")
async def leaderboard_full(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    scores = await client.redis.hgetall("leaderboard")
    if not scores:
        await interaction.response.send_message("📊 No points recorded yet.", ephemeral=True)
        return

    sorted_scores = sorted(scores.items(), key=lambda x: int(x[1]), reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    description_lines = []
    for i, (user_id, points) in enumerate(sorted_scores, start=1):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        prefix = medals[i-1] if i <= 3 else f"#{i}"
        description_lines.append(f"{prefix} **{name}** ➔ {points} points")

    # Split into pages of 20 lines max
    chunks = [description_lines[i:i+20] for i in range(0, len(description_lines), 20)]
    first_embed = discord.Embed(
        title=f"📜 Full Leaderboard — Page 1/{len(chunks)}",
        description="\n".join(chunks[0]),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=first_embed, ephemeral=True)
    for idx in range(1, len(chunks)):
        embed = discord.Embed(
            title=f"📜 Full Leaderboard — Page {idx+1}/{len(chunks)}",
            description="\n".join(chunks[idx]),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# ----------------
# Admin commands
# ----------------
@client.tree.command(name="leaderboard-pause", description="Pause the leaderboard (Admin only)")
async def leaderboard_pause(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    client.paused = True
    await interaction.response.send_message("⏸️ Leaderboard paused.")

@client.tree.command(name="leaderboard-resume", description="Resume the leaderboard (Admin only)")
async def leaderboard_resume(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    client.paused = False
    await interaction.response.send_message("▶️ Leaderboard resumed.")

@client.tree.command(name="leaderboard-stop", description="Stop the leaderboard (Admin only)")
async def leaderboard_stop(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    client.stopped = True
    await interaction.response.send_message("⏹️ Leaderboard stopped.")

@client.tree.command(name="leaderboard-reset", description="Reset all scores (Admin only)")
async def leaderboard_reset(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    await client.redis.delete("leaderboard")
    await interaction.response.send_message("🔄 Leaderboard reset!")

@client.tree.command(name="debug-score", description="Check a player's score (Admin only)")
@app_commands.describe(member="The player whose score you want to check")
async def debug_score(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    score = await client.redis.hget("leaderboard", str(member.id))
    score = score if score else 0
    await interaction.response.send_message(f"🔍 Current score of {member.mention}: **{score} points**", ephemeral=True)

# ----------------
# Events
# ----------------
@client.event
async def on_ready():
    log.info("✅ Leaderboard bot connected as %s (%s)", client.user, client.user.id)
    client.loop.create_task(heartbeat())
    client.loop.create_task(cycle_status())

async def heartbeat():
    while True:
        log.info("💓 Heartbeat: bot alive, paused=%s, stopped=%s", client.paused, client.stopped)
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

    if not message.embeds:
        return

    embed = message.embeds[0]
    title = (embed.title or "").lower()

    # Case: plain Auto Summon announcement → no points
    if "auto summon" in title and "claimed" not in title:
        log.debug("Auto Summon announcement detected (no points).")
        return

@client.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if client.stopped or client.paused:
        return
    if not client.redis:
        return
    if after.author.id != MAZOKU_BOT_ID:
        return
    if after.guild and after.guild.id != GUILD_ID:
        return
    if not after.embeds:
        return

    embed = after.embeds[0]
    title = (embed.title or "").lower()
    desc = (embed.description or "").lower()

    log.debug("Message edited by Mazoku: title=%s desc=%s", embed.title, embed.description)

    # ✅ Case: Auto Summon edited into Auto Summon Claimed
    if "auto summon claimed" in title:
        log.debug("Detected an Auto Summon Claimed!")

        # Find the player (first check description)
        match = re.search(r"<@!?(\d+)>", embed.description or "")

        # If not found, check fields
        if not match and embed.fields:
            for field in embed.fields:
                match = re.search(r"<@!?(\d+)>", field.value or "")
                if match:
                    break

        # If still not found, check footer
        if not match and embed.footer and embed.footer.text:
            match = re.search(r"<@!?(\d+)>", embed.footer.text)

        if not match:
            log.warning("⚠️ No player detected in claim embed.")
            return

        user_id = int(match.group(1))
        member = after.guild.get_member(user_id)
        if not member:
            log.warning("⚠️ Player found (%s) but not in server.", user_id)
            return

        # 🔎 Log detected player
        log.info("👤 Player detected: %s (ID: %s)", member.display_name, member.id)

        # ✅ Anti-duplicate protection with Redis
        claim_key = f"claim:{after.id}:{user_id}"
        already = await client.redis.get(claim_key)
        if already:
            log.debug("⚠️ Claim already processed (%s). Ignored.", claim_key)
            return
        await client.redis.set(claim_key, "1", ex=86400)  # expire after 24h

        # Detect rarity via emojis
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
                    log.info("Rarity detected: %s → %s points", emote_id, rarity_points)
                    break
            if rarity_points:
                break

        if rarity_points:
            bonus = 1 if any(r.id in BONUS_ROLES for r in member.roles) else 0
            total_points = rarity_points + bonus
            await client.redis.hincrby("leaderboard", str(user_id), total_points)
            new_score = await client.redis.hget("leaderboard", str(user_id))
            log.info(
                "🏅 %s gains %s points (base %s + bonus %s) → New score: %s",
                member.display_name, total_points, rarity_points, bonus, new_score
            )
        else:
            log.warning("⚠️ No rarity emoji found in claim embed.")

# ----------------
# Entry point
# ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_LEADERBOARD missing")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL missing")

log.info("🚀 Attempting to connect to Discord...")
client.run(TOKEN)
