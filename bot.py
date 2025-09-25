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

    # Debug : voir si le bot capte bien les messages de Mazoku
    print(f"[DEBUG] Message reçu de Mazoku: {message.embeds[0].title if message.embeds else 'pas d’embed'}")

    if message.embeds:
        embed = message.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""

        if "summon claimed" in title:
            print("[DEBUG] Détection d’un claim !")

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
                    print("[DEBUG] Impossible de trouver le membre dans le serveur.")
                    return

                print(f"[DEBUG] Claim détecté par {member.display_name} ({member.id})")

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
                        print(f"[DEBUG] Emojis trouvés: {matches}")
                    for emote_id in matches:
                        if emote_id in RARITY_POINTS:
                            rarity_points = RARITY_POINTS[emote_id]
                            print(f"[DEBUG] Rareté détectée: {emote_id} → {rarity_points} points")
                            break
                    if rarity_points:
                        break

                if rarity_points:
                    # Bonus si rôle
                    bonus = 1 if any(r.id in BONUS_ROLES for r in member.roles) else 0
                    total_points = rarity_points + bonus
                    await client.redis.hincrby("leaderboard", str(user_id), total_points)
                    new_score = await client.redis.hget("leaderboard", str(user_id))
                    print(f"[DEBUG] {member.display_name} gagne {total_points} points (total {rarity_points}+{bonus}) → Nouveau score: {new_score}")
                else:
                    print("[DEBUG] Aucun emoji de rareté trouvé dans le message.")
