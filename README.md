
# PokeMatrix

<p align="center">
  <img src="pokematrix-logo.png" alt="PokeMatrix Logo" width="450">
</p>

<p align="center">
  <strong>Gotta catch 'em all, on Matrix.</strong>
  <br>
  A community-driven Pokémon collecting game for the Matrix ecosystem.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge" alt="Python">
  <img src="https://img.shields.io/github/license/xxxtrashcion/poketwo-matrix?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/Platform-Matrix-green?style=for-the-badge" alt="Matrix">
  <img src="https://img.shields.io/badge/Status-Early%20Development-orange?style=for-the-badge" alt="Development Status">
</p>

---

PokeMatrix is an open-source Pokémon collecting game for the [Matrix](https://matrix.org/) ecosystem.

Inspired by the original [Pokécord](https://github.com/PokeCord/PokeCord) and built upon the open-source codebase of [Pokétwo](https://github.com/poketwo/poketwo), PokeMatrix aims to bring the complete Pokémon collecting experience to Matrix communities.

Catch Pokémon as they appear in chat rooms, build your collection, complete your Pokédex, level up, evolve, trade, battle, and compete with other players.

> **Development Status:** Early development. A basic Matrix client runner is available for testing; game commands and Pokémon spawning are not yet ported.

## Contributing

Contributions are welcome! Please open an issue before starting substantial work so proposed changes can be discussed and coordinated.

The original Pokétwo codebase contains tightly coupled Discord-specific components. Development will focus on separating game logic from platform-specific functionality while preserving the original gameplay experience.

## Matrix Development Runner

Use Python 3.10, then install the dependencies without trying to package this repository:

```sh
poetry env use python3.10
poetry install --no-root
```

Copy the tracked template to your local, Git-ignored `.env` file, then fill in its values:

```sh
cp .env.example .env
```

```dotenv
MATRIX_HOMESERVER=https://your-homeserver
MATRIX_ROOM_ID=!room-id:your-homeserver
# Optional; defaults to @pokematrix:theeze.dev
MATRIX_USER_ID=@pokematrix:theeze.dev
# Optional; use a separate database name for Matrix data
MATRIX_DATABASE_URI=mongodb://your-mongodb-host
MATRIX_DATABASE_NAME=pokematrix_matrix
```

Start the bot with `poetry run python bot.py`. On first start, it prompts for the account password and saves the session locally in `.matrix-session.json`. In the room, send `!matrix-ping` to check that the bot can receive and reply to messages. Send `!start` to see starter choices, then `!pick Bulbasaur` (or another listed starter) to choose one. Starter selection requires both database settings; it creates the player in the existing `member` collection and the starter in `pokemon`. Use an unencrypted room for now; end-to-end encryption is not enabled.

## Credits and Acknowledgements

PokeMatrix builds upon the work and ideas of projects that helped establish Pokémon collecting bots in online communities.

- **[Pokécord](https://github.com/PokeCord/PokeCord)** – The original Pokémon collecting bot that popularized the concept and inspired subsequent projects.
- **[Pokétwo](https://github.com/poketwo/poketwo)** – The open-source project whose codebase serves as the foundation for PokeMatrix. Special thanks to its developers and contributors for making their work available to the community.
- **[Matrix](https://matrix.org/)** – The open communication protocol and ecosystem that makes this adaptation possible.

PokeMatrix is an independent community project. It is not affiliated with or endorsed by Pokécord, Pokétwo, Discord, Nintendo, The Pokémon Company, or Game Freak.


