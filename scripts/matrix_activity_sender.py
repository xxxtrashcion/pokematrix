"""Send ordinary Matrix messages for local activity, XP, and spawn testing.

Configure MATRIX_HOMESERVER, MATRIX_TEST_USER_ID, MATRIX_TEST_PASSWORD, and
MATRIX_TEST_ROOM_ID in the local ignored .env file. Use a dedicated test
account that has already joined the development room.
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from nio import AsyncClient, LoginResponse, RoomSendResponse


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        default=".env",
        help="local env file to load over .env (for example: spam.env)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the configuration without logging in or sending messages",
    )
    parser.add_argument("--count", type=int, default=24, help="number of messages to send (1–200; default: 24)")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.6,
        help="seconds between messages (minimum: 1.5; default: 1.6)",
    )
    parser.add_argument("--prefix", default="[activity test]", help="text prefix added to each message")
    return parser.parse_args()


async def send_activity(homeserver: str, user_id: str, password: str, room_id: str, count: int, interval: float, prefix: str):
    client = AsyncClient(homeserver, user_id)
    try:
        login = await client.login(password, device_name="PokeMatrix activity test")
        if not isinstance(login, LoginResponse):
            raise RuntimeError(f"Matrix login failed: {login}")

        print(f"Sending {count} messages to {room_id} as {user_id} (one every {interval:g}s).")
        for index in range(1, count + 1):
            body = f"{prefix} message {index}/{count}"
            response = await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": body},
            )
            if not isinstance(response, RoomSendResponse):
                raise RuntimeError(f"Could not send message {index}/{count}: {response}")

            print(f"Sent {index}/{count}")
            if index < count:
                await asyncio.sleep(interval)
    finally:
        await client.close()


def main():
    args = parse_args()
    load_dotenv(".env")
    if not os.path.isfile(args.env_file):
        sys.exit(f"Environment file not found: {args.env_file}")
    load_dotenv(args.env_file, override=True)

    if not 1 <= args.count <= 200:
        sys.exit("--count must be between 1 and 200.")
    if args.interval < 1.5:
        sys.exit("--interval must be at least 1.5 seconds to respect the XP message cooldown.")

    required = {
        "MATRIX_HOMESERVER": os.getenv("MATRIX_HOMESERVER"),
        "MATRIX_TEST_USER_ID": os.getenv("MATRIX_TEST_USER_ID"),
        "MATRIX_TEST_PASSWORD": os.getenv("MATRIX_TEST_PASSWORD"),
        "MATRIX_TEST_ROOM_ID": os.getenv("MATRIX_TEST_ROOM_ID") or os.getenv("MATRIX_ROOM_ID"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        sys.exit("Set these local environment variables first: " + ", ".join(missing))

    if args.check:
        print("Configuration is ready. No login or messages were sent.")
        return

    asyncio.run(
        send_activity(
            required["MATRIX_HOMESERVER"],
            required["MATRIX_TEST_USER_ID"],
            required["MATRIX_TEST_PASSWORD"],
            required["MATRIX_TEST_ROOM_ID"],
            args.count,
            args.interval,
            args.prefix,
        )
    )


if __name__ == "__main__":
    main()
