import asyncio
import getpass
from html import escape
import io
import json
import logging
import os
import random
import time
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from cogs.mongo import MatrixMongo
from data import DataManager
from helpers.constants import STARTER_GENERATION, STARTER_POKEMON
from helpers.genders import generate_gender
from game.pokedex import get_pokedex_milestones
from game.spawning import SPAWN_MESSAGE_THRESHOLD, is_correct_guess, make_hint
from game.matrix_media import pokemon_image_path, pokemon_sprite_path, spawn_announcement
from nio import (
    AsyncClient,
    ClientConfig,
    JoinResponse,
    LoginResponse,
    MatrixRoom,
    RoomMessageText,
    ReactionEvent,
    RoomSendResponse,
    SyncResponse,
    UploadResponse,
)

load_dotenv()

USER_ID = os.getenv("MATRIX_USER_ID", "@pokematrix:theeze.dev")
SESSION_PATH = Path(".matrix-session.json")
STORE_PATH = ".matrix_store"

MATRIX_GENDER_SYMBOLS = {
    "male": "♂",
    "female": "♀",
    "unknown": "⚪",
}

# Keep the short aliases from the original Pokétwo command interface.
COMMAND_ALIASES = {
    "!p": "!pokemon",
    "!c": "!catch",
    "!h": "!hint",
    "!s": "!select",
    "!i": "!info",
    "!d": "!dex",
    "!bal": "!balance",
    "!evo": "!evolve",
}


def normalize_command(command: str) -> str:
    """Resolve Matrix command aliases to their canonical command names."""
    normalized = command.casefold()
    return COMMAND_ALIASES.get(normalized, normalized)


def format_matrix_pokemon(pokemon) -> str:
    """Render an original Pokémon model with Matrix-friendly gender symbols."""
    rendered = format(pokemon, "lnpfx!G")
    gender_symbol = MATRIX_GENDER_SYMBOLS.get(pokemon.gender.casefold())
    if gender_symbol is None:
        return rendered

    index_suffix = f" No. {pokemon.idx}"
    if rendered.endswith(index_suffix):
        return f"{rendered[:-len(index_suffix)]} {gender_symbol}{index_suffix}"

    return f"{rendered} {gender_symbol}"


def format_matrix_pokemon_info(pokemon) -> str:
    """Render useful collection details using the original Pokémon model."""
    ivs = (
        ("HP", pokemon.iv_hp),
        ("Attack", pokemon.iv_atk),
        ("Defense", pokemon.iv_defn),
        ("Sp. Atk", pokemon.iv_satk),
        ("Sp. Def", pokemon.iv_sdef),
        ("Speed", pokemon.iv_spd),
    )
    stats = (
        ("HP", pokemon.hp),
        ("Attack", pokemon.atk),
        ("Defense", pokemon.defn),
        ("Sp. Atk", pokemon.satk),
        ("Sp. Def", pokemon.sdef),
        ("Speed", pokemon.spd),
    )
    stat_text = "\n".join(
        f"{name}: {value} (IV {iv}/31)"
        for (name, value), (_, iv) in zip(stats, ivs)
    )
    total_iv = sum(value for _, value in ivs)
    iv_percent = total_iv / 186 * 100
    shiny = " · Shiny ✨" if pokemon.shiny else ""
    xp = getattr(pokemon, "xp", None)
    max_xp = getattr(pokemon, "max_xp", None)
    xp_progress = f" · XP {xp}/{max_xp}" if xp is not None and max_xp is not None else ""
    return (
        f"{format_matrix_pokemon(pokemon)}{shiny}\n"
        f"Level {pokemon.level} · {pokemon.nature} · {pokemon.gender}{xp_progress}\n\n"
        f"{stat_text}\n\n"
        f"Total IV: {total_iv}/186 ({iv_percent:.2f}%)"
    )


def format_matrix_pokedex(profile, game_data) -> str:
    """Summarize a player's caught species using Pokétwo's Pokédex data."""
    pokedex = profile.get("pokedex", {}) if profile else {}
    caught = sorted(
        (int(number), count)
        for number, count in pokedex.items()
        if count and game_data.species_by_number(int(number)) is not None
    )
    total_species = game_data.total_pokedex_count
    caught_count = len(caught)
    total_catches = sum(count for _, count in caught)
    percent = caught_count / total_species * 100 if total_species else 0
    filled = max(1, round(percent / 10)) if caught_count else 0
    progress = "█" * filled + "░" * (10 - filled)
    message = (
        f"Your Pokédex · {caught_count:,}/{total_species:,} species · {percent:.1f}%\n"
        f"{progress}\n"
        f"Total Pokémon caught: {total_catches:,}"
    )
    if caught:
        names = [
            f"#{number:03d} {game_data.species_by_number(number).name} · {count} caught"
            for number, count in caught[:20]
        ]
        message += "\n\nCaught species\n" + "\n".join(names)
        if caught_count > 20:
            message += f"\n…and {caught_count - 20:,} more."
    else:
        message += "\n\nYou haven't caught any Pokémon yet."
    return message


def matrix_pokedex_page(profile, game_data, page: int, sprite_uris: dict[int, str]):
    """Build the same summary, milestones, and three-column entries as Pokétwo."""
    species_list = sorted(
        (species for species in game_data.all_pokemon() if species.catchable and species.id < 10000),
        key=lambda species: species.id,
    )
    page_size = 21
    page_count = max(1, (len(species_list) + page_size - 1) // page_size)
    page = max(1, min(page, page_count))
    start = (page - 1) * page_size
    current = species_list[start : start + page_size]
    pokedex = profile.get("pokedex", {}) if profile else {}
    unique_caught = sum(1 for count in pokedex.values() if count)
    heading = "Your pokédex"
    summary = f"You've caught {unique_caught:,} out of {len(species_list):,} pokémon!"
    claimed = profile.get("claimed_pokedex_rewards", {}) if profile else {}
    milestone_lines = []
    milestone_html = []
    milestones = get_pokedex_milestones(pokedex, claimed)
    for index, progress in enumerate(milestones, start=1):
        milestone = progress.milestone
        marker = "🔒" if not progress.unlocked else "✅" if progress.claimed else "🏆" if progress.complete else "▫️"
        state = "Locked" if not progress.unlocked else f"{progress.entries_caught}/{milestone.total_entries}"
        milestone_title = (
            f"{index}. {marker} {milestone.title} "
            f"(#{milestone.first_entry}–#{milestone.last_entry}) — {state}"
        )
        milestone_lines.append(milestone_title)
        if not progress.claimed:
            reward_line = "┗ Reward: 1x 🎖️ Original Magearna"
            milestone_lines.append(reward_line)
            milestone_html.append(
                f"<strong>{escape(milestone_title)}</strong><br>"
                "┗ <strong>Reward</strong>: 1x 🎖️ Original Magearna"
            )
        else:
            milestone_html.append(f"<strong>{escape(milestone_title)}</strong>")
    if any(progress.unclaimed for progress in milestones):
        milestone_lines.append("You have unclaimed rewards. Use !dex claim to claim them!")
        milestone_html.append("You have unclaimed rewards. Use <strong>!dex claim</strong> to claim them!")
    html_cells = []
    plain_rows = []
    for species in current:
        count = pokedex.get(str(species.dex_number), 0)
        status = f"✅ {count} caught!" if count else "❌ Not caught yet!"
        sprite = sprite_uris.get(species.id)
        image = f'<img src="{escape(sprite, quote=True)}" width="20" height="20" alt=""/> ' if sprite else ""
        html_cells.append(
            f'{image}<strong>{escape(species.name)} #{species.dex_number}</strong> {escape(status)}'
        )
        plain_rows.append(f"{species.name} #{species.dex_number} · {status}")
    html_rows = [html_cells[index : index + 3] for index in range(0, len(html_cells), 3)]
    # Keep images and text outside table/list containers: some Matrix clients
    # discard unsupported container tags together with their child content.
    grid = "<br>".join("&nbsp; · &nbsp;".join(row) for row in html_rows)
    footer = f"Showing {start + 1}–{start + len(current)} out of {len(species_list):,}."
    plain_grid = "\n".join(" | ".join(plain_rows[index : index + 3]) for index in range(0, len(plain_rows), 3))
    milestones_title = "Pokédex Entry Milestones"
    plain = (
        f"{heading}\n{summary}\n\n{milestones_title}\n"
        + "\n".join(milestone_lines)
        + f"\n\n{plain_grid}\n\n{footer}"
    )
    formatted = (
        f"<strong>{escape(heading)}</strong><br>{escape(summary)}<br><br>"
        f"<strong>{milestones_title}</strong><br>{'<br>'.join(milestone_html)}"
        f"<br><br>{grid}<br>{escape(footer)}"
    )
    return plain, formatted, page, page_count


def matrix_pokemon_collection_page(pokemon, page: int, sprite_uris, *, bold_ids: bool = False):
    """Format one collection page using Pokétwo's item order and compact rows."""
    page_size = 20
    start = (page - 1) * page_size
    current = pokemon[start : start + page_size]
    heading = "Your pokémon"
    rows = []
    html_rows = []
    pad_width = len(str(current[-1].idx)) if current else 1
    for mon in current:
        name = mon.species.name
        gender = MATRIX_GENDER_SYMBOLS.get(mon.gender.casefold(), "")
        favorite = " ❤️" if mon.favorite else ""
        shiny = "✨ " if mon.shiny else ""
        nickname = f' "{mon.nickname}"' if mon.nickname is not None else ""
        detail = f"Lvl. {mon.level} · {mon.iv_percentage:.2%}"
        sprite = sprite_uris.get((mon.species.id, bool(mon.shiny)))
        image = (
            f'<img src="{escape(sprite, quote=True)}" width="20" height="20" '
            f'alt="{escape(name, quote=True)}"/> '
            if sprite
            else ""
        )
        number = str(mon.idx).rjust(pad_width)
        rows.append(f"{number} {shiny}{name} {gender}{nickname}{favorite} · {detail}")
        html_number = escape(number)
        if bold_ids:
            html_number = f"<strong>{html_number}</strong>"
        html_rows.append(
            f'{html_number} &nbsp; {image}<strong>{escape(shiny)}{escape(name)} {escape(gender)}'
            f'{escape(nickname)}{escape(favorite)}</strong> &nbsp; • &nbsp; {escape(detail)}'
        )
    footer = f"Showing entries {start + 1}–{start + len(current)} out of {len(pokemon):,}."
    plain = f"{heading}\n\n" + "\n".join(rows) + f"\n\n{footer}"
    formatted = (
        f"<strong>{escape(heading)}</strong><br><br>"
        + "<br>".join(html_rows)
        + f"<br><br>{escape(footer)}"
    )
    return plain, formatted


async def create_client(homeserver: str) -> AsyncClient:
    client = AsyncClient(
        homeserver,
        USER_ID,
        store_path=STORE_PATH,
        config=ClientConfig(store_sync_tokens=True),
    )

    if SESSION_PATH.exists():
        session = json.loads(SESSION_PATH.read_text())
        if session["homeserver"] != homeserver or session["user_id"] != USER_ID:
            await client.close()
            raise RuntimeError("The saved Matrix session does not match the configured account and homeserver.")

        client.restore_login(
            user_id=session["user_id"],
            device_id=session["device_id"],
            access_token=session["access_token"],
        )
        return client

    password = getpass.getpass(f"Password for {USER_ID}: ")
    response = await client.login(password, device_name="PokeMatrix development")
    if not isinstance(response, LoginResponse):
        await client.close()
        raise RuntimeError(f"Matrix login failed: {response}")

    SESSION_PATH.write_text(
        json.dumps(
            {
                "homeserver": homeserver,
                "user_id": response.user_id,
                "device_id": response.device_id,
                "access_token": response.access_token,
            }
        )
    )
    SESSION_PATH.chmod(0o600)
    return client


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    homeserver = os.getenv("MATRIX_HOMESERVER")
    room_id = os.getenv("MATRIX_ROOM_ID")
    if not homeserver or not room_id:
        raise RuntimeError("Set MATRIX_HOMESERVER and MATRIX_ROOM_ID before starting the bot.")

    game_data = DataManager()
    client = await create_client(homeserver)
    persistence = None
    room_activity = 0
    last_counted_message = 0.0
    last_xp_message_by_user: dict[str, float] = {}
    sprite_uri_cache: dict[tuple[int, bool], str] = {}
    active_paged_messages: dict[str, dict] = {}

    async def reply(
        room_id: str,
        text: str,
        formatted_body: str | None = None,
        mention_user_ids: list[str] | None = None,
    ) -> None:
        logging.info("Sending Matrix reply to %s: %r", room_id, text)

        content = {"msgtype": "m.text", "body": text}
        if formatted_body is not None:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted_body
        if mention_user_ids is not None:
            content["m.mentions"] = {"user_ids": mention_user_ids}
        response = await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )

        if isinstance(response, RoomSendResponse):
            logging.info("Matrix reply accepted by homeserver: %s", response.event_id)
        else:
            logging.error("Could not send Matrix reply: %r", response)

    async def reply_with_image(
        room_id: str,
        image_path: Path,
        announcement: str,
        formatted_announcement: str,
    ) -> None:
        """Send the spawn announcement first, followed by the Pokémon artwork."""
        try:
            text_response = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": announcement,
                    "format": "org.matrix.custom.html",
                    "formatted_body": formatted_announcement,
                },
            )
            if isinstance(text_response, RoomSendResponse):
                logging.info("Matrix spawn announcement accepted: %s", text_response.event_id)
            else:
                logging.error("Could not send Matrix spawn announcement: %r", text_response)
                await reply(room_id, announcement)
        except Exception:
            logging.exception("Failed to send Matrix spawn announcement")
            await reply(room_id, announcement)

        try:
            image_data = image_path.read_bytes()
            upload_response, _ = await client.upload(
                io.BytesIO(image_data),
                content_type="image/png",
                filename=image_path.name,
                filesize=len(image_data),
            )
            if not isinstance(upload_response, UploadResponse):
                logging.error("Could not upload Pokémon artwork %s: %r", image_path, upload_response)
                return

            response = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.image",
                    "body": "",
                    "url": upload_response.content_uri,
                    "info": {
                        "mimetype": "image/png",
                        "size": len(image_data),
                    },
                },
            )
            if isinstance(response, RoomSendResponse):
                logging.info("Matrix Pokémon image accepted by homeserver: %s", response.event_id)
            else:
                logging.error("Could not send Pokémon image to Matrix: %r", response)
        except Exception:
            logging.exception("Failed to upload or send Pokémon artwork %s", image_path)

    async def upload_sprite(species_id: int, *, shiny: bool = False, dex_number: int | None = None) -> str | None:
        key = (species_id, shiny)
        if key in sprite_uri_cache:
            return sprite_uri_cache[key]
        try:
            path = pokemon_sprite_path(species_id, shiny=shiny, dex_number=dex_number)
            data = path.read_bytes()
            upload, _ = await client.upload(
                io.BytesIO(data),
                content_type="image/png",
                filename=path.name,
                filesize=len(data),
            )
            if isinstance(upload, UploadResponse):
                sprite_uri_cache[key] = upload.content_uri
                return upload.content_uri
        except Exception:
            logging.exception("Could not upload Pokémon sprite for species %s", species_id)
        return None

    async def send_paged_content(
        room_id: str,
        matrix_user_id: str,
        page: int,
        page_count: int,
        body: str,
        formatted_body: str,
        *,
        page_kind: str,
        edit_event_id: str | None = None,
    ) -> None:
        new_content = {
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted_body,
        }
        if edit_event_id is None:
            response = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=new_content,
            )
        else:
            response = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    **new_content,
                    "body": f"* {body}",
                    "formatted_body": f"* {formatted_body}",
                    "m.new_content": new_content,
                    "m.relates_to": {"rel_type": "m.replace", "event_id": edit_event_id},
                },
            )
        if not isinstance(response, RoomSendResponse):
            logging.error("Could not send %s page: %r", page_kind, response)
            return

        page_event_id = edit_event_id or response.event_id
        view = active_paged_messages.setdefault(page_event_id, {"buttons": set()})
        view.update({
            "room_id": room_id,
            "user_id": matrix_user_id,
            "page": page,
            "page_count": page_count,
            "kind": page_kind,
        })
        if page_count > 1:
            for key in ("◀️", "▶️"):
                if key in view["buttons"]:
                    continue
                reaction = await client.room_send(
                    room_id,
                    "m.reaction",
                    {"m.relates_to": {"rel_type": "m.annotation", "event_id": page_event_id, "key": key}},
                )
                if isinstance(reaction, RoomSendResponse):
                    view["buttons"].add(key)

    async def send_dex_page(
        room_id: str,
        matrix_user_id: str,
        page: int,
        *,
        edit_event_id: str | None = None,
    ) -> None:
        if persistence is None:
            return
        profile = await persistence.fetch_member(matrix_user_id)
        species_list = sorted(
            (species for species in game_data.all_pokemon() if species.catchable and species.id < 10000),
            key=lambda species: species.id,
        )
        page_count = max(1, (len(species_list) + 20) // 21)
        page = max(1, min(page, page_count))
        start = (page - 1) * 21
        sprite_uris = {}
        for species in species_list[start : start + 21]:
            sprite = await upload_sprite(species.id, dex_number=species.dex_number)
            if sprite:
                sprite_uris[species.id] = sprite

        body, formatted_body, page, page_count = matrix_pokedex_page(
            profile,
            game_data,
            page,
            sprite_uris,
        )
        await send_paged_content(
            room_id,
            matrix_user_id,
            page,
            page_count,
            body,
            formatted_body,
            page_kind="dex",
            edit_event_id=edit_event_id,
        )

    async def send_pokemon_page(
        room_id: str,
        matrix_user_id: str,
        page: int,
        *,
        edit_event_id: str | None = None,
    ) -> None:
        if persistence is None:
            return
        pokemon = await persistence.fetch_pokemon_list(matrix_user_id)
        page_size = 20
        page_count = max(1, (len(pokemon) + page_size - 1) // page_size)
        page = max(1, min(page, page_count))
        page_pokemon = pokemon[(page - 1) * page_size : page * page_size]
        sprite_uris = {}
        for mon in page_pokemon:
            sprite = await upload_sprite(
                mon.species.id,
                shiny=bool(mon.shiny),
                dex_number=mon.species.dex_number,
            )
            if sprite:
                sprite_uris[(mon.species.id, bool(mon.shiny))] = sprite
        profile = await persistence.fetch_member(matrix_user_id)
        body, formatted_body = matrix_pokemon_collection_page(
            pokemon,
            page,
            sprite_uris,
            bold_ids=bool(profile and profile.get("bold_ids")),
        )
        await send_paged_content(
            room_id,
            matrix_user_id,
            page,
            page_count,
            body,
            formatted_body,
            page_kind="pokemon",
            edit_event_id=edit_event_id,
        )

    async def on_reaction(room: MatrixRoom, event: ReactionEvent) -> None:
        if event.sender == client.user_id:
            return
        view = active_paged_messages.get(event.reacts_to)
        if (
            view is None
            or room.room_id != view["room_id"]
            or event.sender != view["user_id"]
            or event.key not in {"◀️", "▶️"}
        ):
            return
        if view["page_count"] < 2:
            return
        if event.key == "▶️":
            page = view["page"] % view["page_count"] + 1
        else:
            page = (view["page"] - 2) % view["page_count"] + 1
        if view["kind"] == "dex":
            await send_dex_page(room.room_id, event.sender, page, edit_event_id=event.reacts_to)
        elif view["kind"] == "pokemon":
            await send_pokemon_page(room.room_id, event.sender, page, edit_event_id=event.reacts_to)

    async def award_chat_xp(room: MatrixRoom, event: RoomMessageText) -> None:
        now = time.monotonic()
        last_xp_message = last_xp_message_by_user.get(event.sender, 0.0)
        if last_xp_message and now - last_xp_message < 1.5:
            return
        last_xp_message_by_user[event.sender] = now

        member, pokemon = await persistence.fetch_selected_pokemon(event.sender)
        if member is None or pokemon is None or member.is_suspended or pokemon.held_item == 13002:
            return

        if pokemon.level == 100:
            if pokemon.xp < pokemon.max_xp:
                await persistence.update_pokemon(pokemon, {"$set": {"xp": pokemon.max_xp}})
            return

        if pokemon.xp < pokemon.max_xp:
            xp_gain = random.randint(10, 40)
            if member.boost_active:
                xp_gain *= 2
            await persistence.update_pokemon(pokemon, {"$inc": {"xp": xp_gain}})
            pokemon.xp += xp_gain

        if pokemon.xp < pokemon.max_xp:
            return

        old_species = pokemon.species
        new_level = pokemon.level + 1
        update = {"$set": {"xp": 0, "level": new_level}}
        pokemon.level = new_level
        guild = await persistence.fetch_guild(room.room_id)
        evolution = pokemon.get_next_evolution(guild.time)

        display_name = room.user_name(event.sender) or event.sender
        if evolution is not None:
            update["$set"]["species_id"] = evolution.id
            await persistence.update_pokemon(pokemon, update)
            reply_text = (
                f"Congratulations, {display_name}! Your {old_species.name} reached level {new_level} "
                f"and evolved into {evolution.name}!"
            )
        else:
            await persistence.update_pokemon(pokemon, update)
            reply_text = f"Congratulations, {display_name}! Your {old_species.name} reached level {new_level}!"
            new_moves = [
                move.move.name
                for move in old_species.moves
                if move.method.level == new_level
            ]
            if new_moves:
                reply_text += "\nNew move(s) available to learn: " + ", ".join(new_moves)
        await reply(room.room_id, reply_text)

    async def on_message(room: MatrixRoom, event: RoomMessageText) -> None:
        nonlocal room_activity, last_counted_message
        if event.sender == client.user_id or room.room_id != room_id:
            return

        logging.info("Message in %s from %s", room.room_id, event.sender)
        body = event.body.strip()
        if not body:
            return

        # The original game spawns wild Pokémon after room activity, not on a
        # dedicated spawn command. Matrix rooms use the same 24-message cadence.
        if not body.startswith("!"):
            if persistence is None:
                return
            await award_chat_xp(room, event)
            now = time.monotonic()
            if last_counted_message and now - last_counted_message < 1:
                return
            last_counted_message = now
            room_activity += 1
            if room_activity >= SPAWN_MESSAGE_THRESHOLD:
                room_activity = 0
                species = game_data.random_spawn()
                gender = generate_gender(species)
                previous = await persistence.set_wild_spawn(
                    room.room_id,
                    species.id,
                    gender,
                )
                announcement, formatted_announcement = spawn_announcement(bool(previous))
                image_path = pokemon_image_path(
                    species.id,
                    gender=gender,
                    has_gender_differences=species.has_gender_differences,
                )
                await reply_with_image(
                    room.room_id,
                    image_path,
                    announcement,
                    formatted_announcement,
                )
            return

        command, _, argument = body.partition(" ")
        command = normalize_command(command)

        if command == "!matrix-ping":
            if persistence is not None:
                await persistence.ensure_member(event.sender, room.user_name(event.sender))
                logging.info("Matrix player profile ready for %s", event.sender)
            await reply(room.room_id, "PokeMatrix is online.")
        elif command == "!start":
            if argument:
                await reply(room.room_id, "Choose a starter with `!pick <name>`; run `!start` to see the choices.")
                return

            choices = "\n".join(f"{generation}: {', '.join(names)}" for generation, names in STARTER_GENERATION.items())
            await reply(room.room_id, f"Choose your starter with `!pick <name>`:\n{choices}")
        elif command == "!hint":
            if persistence is None:
                await reply(room.room_id, "Wild Pokémon tracking needs MongoDB. Configure the Matrix database settings first.")
                return
            wild = await persistence.fetch_wild_spawn(room.room_id)
            if wild is None:
                await reply(room.room_id, "There isn't a wild Pokémon in this room right now.")
                return
            species = game_data.species_by_number(int(wild["species_id"]))
            await reply(room.room_id, f"The wild Pokémon is {make_hint(species)}.")
        elif command == "!catch":
            if not argument.strip():
                await reply(room.room_id, "Usage: `!c <Pokémon name>` (or `!catch <Pokémon name>`).")
                return
            if persistence is None:
                await reply(room.room_id, "Catching Pokémon needs MongoDB. Configure the Matrix database settings first.")
                return
            profile = await persistence.fetch_member(event.sender)
            if profile is None or profile.get("selected_id") is None:
                await reply(room.room_id, "Choose your starter with `!start` before catching Pokémon.")
                return
            wild = await persistence.fetch_wild_spawn(room.room_id)
            if wild is None:
                await reply(room.room_id, "There isn't a wild Pokémon in this room right now.")
                return
            species = game_data.species_by_number(int(wild["species_id"]))
            if not is_correct_guess(argument, species):
                await reply(room.room_id, "That is the wrong Pokémon!")
                return
            caught = await persistence.catch_wild_spawn(room.room_id, event.sender, species)
            if caught is None:
                await reply(room.room_id, "That wild Pokémon has already fled or been caught.")
                return
            pokemon = caught["pokemon"]
            catcher_name = room.user_name(event.sender) or event.sender
            pokemon_text = format_matrix_pokemon(pokemon)
            message = f"Congratulations, {catcher_name}! You caught {pokemon_text}!"
            reward = caught["pokedex_reward"]
            if reward == 35:
                message += "\nNew Pokédex entry! You received 35 Pokécoins."
            elif reward:
                message += f"\nPokédex milestone! You received {reward:,} Pokécoins."
            if caught["gmax"]:
                message += "\nIt has the Gigantamax Factor!"
            if pokemon.shiny:
                message += "\nThese colors seem unusual... ✨"
            if caught["shiny_hunt"]:
                message += "\nYour shiny-hunt chain has been updated."
            mention_link = (
                f'<a href="https://matrix.to/#/{quote(event.sender, safe="@:")}">'
                f"{escape(catcher_name)}</a>"
            )
            formatted_message = "<br>".join(escape(line) for line in message.splitlines())
            formatted_message = formatted_message.replace(escape(catcher_name), mention_link, 1)
            await reply(
                room.room_id,
                message,
                formatted_message,
                mention_user_ids=[event.sender],
            )
        elif command == "!pokemon":
            if persistence is None:
                await reply(
                    room.room_id,
                    "Viewing your collection needs MongoDB. Configure the Matrix database settings first.",
                )
                return

            try:
                page = int(argument) if argument else 1
            except ValueError:
                await reply(room.room_id, "Usage: `!p [page]` (or `!pokemon [page]`)")
                return

            if page < 1:
                await reply(room.room_id, "Page numbers must be 1 or greater.")
                return

            pokemon = await persistence.fetch_pokemon_list(event.sender)
            if not pokemon:
                await reply(room.room_id, "Your collection is empty. Use `!start` to choose your first Pokémon.")
                return

            page_size = 20
            page_count = (len(pokemon) + page_size - 1) // page_size
            if page > page_count:
                await reply(room.room_id, f"You only have {page_count} collection page(s). Use `!p [page]`.")
                return
            await send_pokemon_page(room.room_id, event.sender, page)
        elif command == "!select":
            if persistence is None:
                await reply(room.room_id, "Selecting a Pokémon needs MongoDB. Configure the Matrix database settings first.")
                return

            argument = argument.strip()
            if not argument:
                profile = await persistence.fetch_member(event.sender)
                selected_id = profile.get("selected_id") if profile else None
                pokemon = await persistence.fetch_pokemon_list(event.sender)
                selected = next((mon for mon in pokemon if mon.id == selected_id), None)
                if selected is None:
                    await reply(room.room_id, "You don't have a selected Pokémon. Use `!s <number>` to select one.")
                else:
                    await reply(room.room_id, f"Your selected Pokémon is {format_matrix_pokemon(selected)}.")
                return

            selected = await persistence.select_pokemon(event.sender, argument)
            if selected is None:
                await reply(room.room_id, "That Pokémon isn't in your collection. Use `!p` to view your Pokémon.")
            else:
                await reply(room.room_id, f"You selected {format_matrix_pokemon(selected)}!")
        elif command == "!info":
            if persistence is None:
                await reply(room.room_id, "Viewing Pokémon details needs MongoDB. Configure the Matrix database settings first.")
                return

            selection = argument.strip().casefold()
            if not selection:
                await reply(room.room_id, "Usage: `!i <number|latest>` (or `!info <number|latest>`).")
                return

            pokemon = await persistence.fetch_pokemon_list(event.sender)
            if not pokemon:
                await reply(room.room_id, "Your collection is empty. Use `!start` to choose your first Pokémon.")
                return

            if selection in {"latest", "l", "0"}:
                selected = pokemon[-1]
            else:
                try:
                    index = int(selection)
                except ValueError:
                    await reply(room.room_id, "Usage: `!i <number|latest>` (or `!info <number|latest>`).")
                    return
                selected = next((mon for mon in pokemon if mon.idx == index), None)

            if selected is None:
                await reply(room.room_id, "That number isn't in your collection. Use `!p` to view your Pokémon.")
                return

            await reply(room.room_id, format_matrix_pokemon_info(selected))
        elif command == "!balance":
            if persistence is None:
                await reply(room.room_id, "Viewing your balance needs MongoDB. Configure the Matrix database settings first.")
                return

            profile = await persistence.fetch_member(event.sender)
            if profile is None:
                await reply(room.room_id, "Choose your starter with `!start` before checking your balance.")
                return

            balance = profile.get("balance", 0)
            shards = profile.get("premium_balance", 0)
            display_name = room.user_name(event.sender) or event.sender
            await reply(
                room.room_id,
                f"{display_name}'s balance\nPokécoins: {balance:,}\nShards: {shards:,}",
                (
                    f"<strong>{escape(display_name)}'s balance</strong><br><br>"
                    f"<strong>Pokécoins:</strong> {balance:,}<br>"
                    f"<strong>Shards:</strong> {shards:,}"
                ),
            )
        elif command == "!evolve":
            if persistence is None:
                await reply(room.room_id, "Evolving Pokémon needs MongoDB. Configure the Matrix database settings first.")
                return

            pokemon_list = await persistence.fetch_pokemon_list(event.sender)
            if not pokemon_list:
                await reply(room.room_id, "Your collection is empty. Use `!start` to choose your first Pokémon.")
                return

            selections = argument.split()
            if len(selections) > 30:
                await reply(room.room_id, "You can't evolve more than 30 Pokémon at once!")
                return

            if not selections:
                profile = await persistence.fetch_member(event.sender)
                selected_id = profile.get("selected_id") if profile else None
                selected = next((mon for mon in pokemon_list if mon.id == selected_id), None)
                if selected is None:
                    await reply(room.room_id, "Choose a Pokémon first with `!s <number>`, then use `!evolve`.")
                    return
                pokemon_to_evolve = [selected]
            else:
                pokemon_by_index = {mon.idx: mon for mon in pokemon_list}
                pokemon_to_evolve = []
                seen_ids = set()
                for selection in selections:
                    if selection.casefold() in {"latest", "l", "0"}:
                        selected = pokemon_list[-1]
                    else:
                        try:
                            index = int(selection)
                        except ValueError:
                            await reply(room.room_id, "Usage: `!evolve [number|latest ...]`; choose Pokémon by collection number.")
                            return
                        selected = pokemon_by_index.get(index)

                    if selected is None:
                        await reply(room.room_id, "That Pokémon isn't in your collection. Use `!p` to view your Pokémon.")
                        return
                    if selected.id not in seen_ids:
                        pokemon_to_evolve.append(selected)
                        seen_ids.add(selected.id)

            guild = await persistence.fetch_guild(room.room_id)
            failures = []
            successes = []
            for pokemon in pokemon_to_evolve:
                evolution = pokemon.get_next_evolution(guild.time)
                if evolution is None:
                    failures.append(f"Your {format_matrix_pokemon(pokemon)} can't be evolved right now.")
                    continue

                await persistence.update_pokemon(pokemon, {"$set": {"species_id": evolution.id}})
                successes.append(f"Your {format_matrix_pokemon(pokemon)} evolved into {evolution.name}!")

            response_lines = []
            if successes:
                response_lines.append(f"Congratulations, {room.user_name(event.sender) or event.sender}!")
                response_lines.extend(successes)
            response_lines.extend(failures)
            await reply(room.room_id, "\n".join(response_lines))
        elif command == "!dex":
            if persistence is None:
                await reply(room.room_id, "Viewing your Pokédex needs MongoDB. Configure the Matrix database settings first.")
                return
            if argument.strip().casefold() == "claim":
                rewards = await persistence.claim_pokedex_milestones(event.sender)
                if not rewards:
                    await reply(
                        room.room_id,
                        "You have no unclaimed Pokédex milestone rewards that are unlocked at the moment!",
                    )
                    return

                count = len(rewards)
                milestone_word = "milestone" if count == 1 else "milestones"
                completed = "a" if count == 1 else str(count)
                message = f"Congratulations, you have completed {completed} Pokédex {milestone_word}! 🎉"
                for reward in rewards:
                    pokemon_names = ", ".join(
                        f"{pokemon.species.name} No. {pokemon.idx}"
                        for pokemon in reward["pokemon"]
                    )
                    message += f"\n{reward['milestone']}: You earned {pokemon_names}."
                await reply(room.room_id, message)
                return
            try:
                page = int(argument) if argument.strip() else 1
            except ValueError:
                await reply(room.room_id, "Usage: `!d [page]` or `!dex claim`.")
                return
            await send_dex_page(room.room_id, event.sender, page)
        elif command == "!pick":
            if not argument:
                await reply(room.room_id, "Usage: `!pick <starter name>`. Run `!start` to see the choices.")
                return
            if persistence is None:
                await reply(
                    room.room_id, "Starter selection needs MongoDB. Configure the Matrix database settings first."
                )
                return

            species = game_data.species_by_name(argument)
            if species is None or species.name.casefold() not in STARTER_POKEMON:
                await reply(room.room_id, "That isn't a starter. Run `!start` to see the available choices.")
                return

            selected = await persistence.start_player(event.sender, species, room.user_name(event.sender))
            if selected:
                await reply(room.room_id, f"You chose {species.name}! Your first Pokémon is saved to your collection.")
            else:
                await reply(room.room_id, "You already have a starter Pokémon. Use `!pokemon` to view your collection.")

    try:
        database_uri = os.getenv("MATRIX_DATABASE_URI")
        database_name = os.getenv("MATRIX_DATABASE_NAME")
        if bool(database_uri) != bool(database_name):
            raise RuntimeError("Set both MATRIX_DATABASE_URI and MATRIX_DATABASE_NAME to enable persistence.")
        if database_uri and database_name:
            persistence = MatrixMongo.connect(database_uri, database_name, game_data=game_data)
            await persistence.ping()
            logging.info("Connected to Matrix database %s", database_name)

        join_response = await client.join(room_id)
        if not isinstance(join_response, JoinResponse):
            raise RuntimeError(f"Could not join Matrix room {room_id}: {join_response}")

        sync_response = await client.sync(timeout=0, full_state=True)
        if not isinstance(sync_response, SyncResponse):
            raise RuntimeError(f"Could not sync with the Matrix homeserver: {sync_response}")

        matrix_room = client.rooms.get(room_id)
        if matrix_room is not None and matrix_room.encrypted:
            raise RuntimeError(
                f"Matrix room {room_id} is encrypted, but end-to-end encryption is not enabled. "
                "Create a new unencrypted room and update MATRIX_ROOM_ID."
            )

        client.add_event_callback(on_message, RoomMessageText)
        client.add_event_callback(on_reaction, ReactionEvent)
        logging.info("Listening in Matrix room %s as %s", room_id, client.user_id)
        await client.sync_forever(timeout=30000)
    finally:
        await client.close()
        if persistence is not None:
            persistence.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
