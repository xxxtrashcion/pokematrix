import asyncio
import getpass
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from cogs.mongo import MatrixMongo
from data import DataManager
from helpers.constants import STARTER_GENERATION, STARTER_POKEMON
from nio import (
    AsyncClient,
    ClientConfig,
    JoinResponse,
    LoginResponse,
    MatrixRoom,
    RoomMessageText,
    RoomSendResponse,
    SyncResponse,
)

load_dotenv()

USER_ID = os.getenv("MATRIX_USER_ID", "@pokematrix:theeze.dev")
SESSION_PATH = Path(".matrix-session.json")
STORE_PATH = ".matrix_store"


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

    async def reply(room_id: str, text: str) -> None:
        response = await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
        )
        if not isinstance(response, RoomSendResponse):
            logging.error("Could not send Matrix reply: %s", response)

    async def on_message(room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == client.user_id or room.room_id != room_id:
            return

        logging.info("Message in %s from %s", room.room_id, event.sender)
        command, _, argument = event.body.strip().partition(" ")
        command = command.casefold()

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
            persistence = MatrixMongo.connect(database_uri, database_name)
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
