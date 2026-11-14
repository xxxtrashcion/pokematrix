# PokeMatrix — Codex Project Handoff

This document captures the PokeMatrix project context established in the ChatGPT development conversation. It is intended to be placed in the repository root and supplied to Codex Desktop as project context.

**Important:** This is a handoff based on the state last confirmed in the conversation, not a live inspection of the current checkout. Codex should inspect the working tree, branch, files, and tests before changing anything. Do not overwrite newer local work with assumptions from this document.

---

## 1. Project purpose and guiding architecture

PokeMatrix is a Matrix-native port/adaptation of Pokétwo. The goal is to bring the full Pokétwo game experience into Matrix while reusing the original Pokétwo implementation wherever practical.

The long-term game scope includes:

- Pokémon spawning and catching
- Collection, Pokédex, selection, leveling, and evolution
- Items and inventory
- Trading
- Battles
- Market and auctions
- Economy
- Quests and events

**Core architectural preference:** reuse the original Pokétwo models, data, and game logic. Keep Matrix-specific behavior in an adapter layer for command parsing, room events, replies, and media delivery. Avoid creating a second simplified game engine or duplicating mechanics that already exist in Pokétwo.

The original Discord bot code remains in the repository. Be careful not to confuse the Matrix entry point `bot.py` with the original Discord cog `cogs/bot.py`.

## 2. Repository and development environment

- Local repository: `~/pokematrix`
- Most recently reported active branch: `feature/matrix-pokemon-command`
- Desktop OS: CachyOS / Arch-based Linux
- Shell: Fish
- Editor: Neovim
- Project Python: **3.10.22**, managed through `uv` and used by Poetry
- Do not use the system Python 3.14 for this project; legacy dependencies have failed under it.
- `matrix-nio` version used successfully: `0.25.2`
- Bot launch command:

```fish
cd ~/pokematrix
poetry run python bot.py
```

The original project is a legacy Python codebase with existing dependencies and models. Avoid broad modernization or dependency upgrades unless required and discussed.

### Development workflow preferences

- Work incrementally, one cohesive feature/fix at a time.
- Inspect the current files and `git status` before editing.
- Preserve existing user changes. Do not reset, clean, or overwrite the working tree.
- Prefer small, reviewable diffs over broad refactors.
- The user works in Fish and Neovim. Give Fish-compatible commands and do not give `nano` instructions.
- Do not include shell prompt glyphs in commands.
- Do not push to GitHub unless explicitly asked.
- Never drop, recreate, or delete the MongoDB database or its Docker volume as a troubleshooting shortcut.

## 3. Matrix setup

Known working Matrix configuration:

- Homeserver: `https://matrix.theeze.dev`
- Bot account: `@pokematrix:theeze.dev`
- A development room used successfully: `!K1g36PoBsd2eh7lNKouw8mNuXHMMCxM7_lSdKjxqAWg`
- The bot authenticated, joined the room, received room events, and sent replies successfully using `matrix-nio`.
- Matrix session files and local state are private/ignored: `.env`, `.matrix-session.json`, and `.matrix_store/`.

Do not ask the user to paste `.env`, session files, access tokens, or passwords into chat or logs. Keep secrets out of commits and generated patches.

## 4. MongoDB / persistence

The Matrix adapter connects to MongoDB running in Docker on the user's Arch server over Tailscale.

Known setup facts:

- Database used by Matrix: `pokematrix_matrix`
- Existing original database also present: `pokematrix_dev`
- Mongo application account: `pokematrix_app`
- That account was granted `readWrite` on `pokematrix_dev` and `pokematrix_matrix`.
- Mongo URI authentication uses `authSource=pokematrix_dev`.
- A password was exposed during an earlier troubleshooting conversation. **Do not reproduce or reuse it. Rotate it if that has not already been done.**
- Mongo persistence is working. `!matrix-ping` successfully ensures/creates a player profile.

The database adapter registers and uses the original Pokétwo model classes. Preserve existing data. Never suggest dropping the database, removing its volume, or recreating the Mongo service to fix normal application issues.

## 5. Original Pokétwo models and shared game logic

Relevant original code areas include:

- `cogs/mongo.py`: original model definitions such as `PokemonBase`, `Pokemon`, `Member`, and database/model behavior.
- `data/`: original Pokétwo species and game data, including local Pokémon sprites.
- `helpers/`: original helper modules.
- `cogs/`: original Discord cogs and commands.
- `game/`: shared game logic introduced for Matrix integration.

Important existing integration decisions:

- `MatrixMongo` registers and uses the same original model classes rather than maintaining separate Matrix-specific Pokémon/member models.
- The original `PokemonBase.species` property uses `self.bot.data`.
- The original formatter can require Discord sprite/emoji support for some format specs. Matrix uses a sprite-free format spec where appropriate.
- Original gender icons use Discord custom emoji. Matrix uses native Unicode symbols: `♂`, `♀`, and `⚪`.
- Pokémon generation has been factored into shared `game/pokemon.py` logic so the original Mongo adapter and `MatrixMongo` share generation mechanics.
- Shared generation includes the member shiny-charm / shiny-hunt chance behavior. Do not fork this logic in the Matrix adapter.

## 6. Matrix adapter status and working commands

The Matrix entry point is root-level `bot.py`. `MatrixMongo` is the Matrix persistence adapter.

Known `MatrixMongo` methods at the last confirmed project state:

- `fetch_member`
- `fetch_pokemon_list`
- `ensure_member`
- `start_player`
- `fetch_wild_spawn`
- `set_wild_spawn`
- `catch_wild_spawn`
- `select_pokemon`

### Commands and aliases

Case-insensitive aliases were added in `bot.py`:

| Alias | Command |
|---|---|
| `!p` | `!pokemon` |
| `!c` | `!catch` |
| `!h` | `!hint` |
| `!s` | `!select` |

Other confirmed commands/behavior:

- `!start` / `!pick`: starter selection works.
- `!pokemon` / `!p`: displays the user's collection using the original Pokémon model, with Matrix-native Unicode gender symbols. Supports page numbers, 20 Pokémon per page.
- `!select` / `!s`: selects by collection index or `latest`, `l`, or `0`. With no argument it reports the currently selected Pokémon. Updates the original `Member.selected_id`.
- `!hint` / `!h`: displays a half-masked species name using the shared spawn helper.
- `!catch` / `!c`: catches by normalized guess, persists the Pokémon, and updates Pokédex/reward/counter behavior.
- `!matrix-ping`: profile persistence smoke test.

### Shared spawning helpers

`game/spawning.py` contains shared helpers:

- `SPAWN_MESSAGE_THRESHOLD = 24`
- `normalize_guess`
- `is_correct_guess`
- `make_hint`
- `rolls_gigantamax`
- `pokedex_reward`

Spawning behavior last confirmed:

- A wild spawn is triggered after 24 ordinary user messages in a room.
- Activity counting is throttled to at most one increment per second.
- The current room's wild spawn is stored in MongoDB.
- Catching claims the current spawn atomically to prevent duplicate catches/races.
- The shared Pokémon generator is used to generate the caught Pokémon.
- The original Gmax 1% chance is applied.
- The caught Pokémon is persisted using the original model.
- Pokédex/reward, shiny/Gmax counters, and shiny-hunt streak behavior are handled.

### Live Matrix validation already achieved

The user personally tested the bot in Matrix and confirmed this flow end-to-end:

1. A wild Pokémon spawned in a room.
2. `!h` returned a masked hint (the example was `Fr＿＿＿is＿` for Frillish).
3. The user caught it with `!c`.
4. `!p` displayed the caught Frillish in their collection.

This is live runtime validation, not merely passing unit tests.

## 7. Spawn message and image behavior — latest confirmed state

The spawn message was iteratively adjusted and the user confirmed the latest layout patch worked.

### Desired presentation

The user wants the spawn to look like the original Pokétwo Discord message:

- Announcement text appears first.
- Pokémon image appears underneath the text.
- The Pokémon's actual name must not appear in the spawn announcement.
- Keep the `!h` hint command.
- Do not show a duplicate caption below the image.

The intended visible text is approximately:

> **A wild Pokémon has appeared!**
>
> Guess the Pokémon and type `!c <pokemon>` to catch it!
>
> Use `!h` for a hint.

Then the image is displayed below this text.

### Previous bug and resolution

An earlier Matrix event showed the image but not its text in the user's client. The spawn implementation was changed to send image and text as separate Matrix room messages. That made the text visible.

The first separate-message layout put the image before the text and the Pokémon's actual name leaked into the announcement. The user provided this example of the undesired message:

> The previous wild Pokémon fled! A wild Walking Wake appeared! Guess its name with `!c <name>` to catch it or use `!h` for a hint.

The user then applied an incremental spawn-layout patch. They confirmed: **"that worked."** The layout should now be text first, image second, no actual Pokémon name in the text, and retain `!h`.

Keep the previous-wild-Pokémon-fled notice when a spawn is replaced, but do not reveal the new Pokémon's name.

### Spawn images already implemented

- Local Pokémon sprite files are under `data/images/`.
- The user verified both `data/images/592.png` and `data/images/592F.png` exist.
- Original local asset naming convention:
  - Base image: `data/images/{species_id}.png`
  - Female-specific image: `data/images/{species_id}F.png` if the species has gender differences and the generated gender is female.
- `game/matrix_media.py` was introduced with a helper `pokemon_image_path(...)` that chooses the female variant when appropriate, falling back to the base PNG if the female image is missing.
- Matrix image upload uses `client.upload(...)`, reads `UploadResponse.content_uri`, and sends a Matrix `m.image` event with its `url` and `info` metadata.
- If image upload fails, the bot falls back to text.
- Spawn generation calculates gender once and uses that same gender both for the stored spawn and image selection.
- User confirmed the image is now visible in Matrix.

### Patch history relevant to current working tree

The user was given and applied these incremental patches in order:

1. `matrix-spawn-image.patch`: added Matrix image upload and species/gender-specific local sprite selection.
2. `matrix-spawn-text.patch`: separated text from image to make text visible in the user's Matrix client.
3. `matrix-spawn-layout.patch`: moved text above the image, removed the leaked Pokémon name from the announcement, avoided a duplicate caption, and retained `!h`.

The user confirmed that the last layout patch worked. These are historical patch filenames; Codex should inspect the actual current checkout rather than attempting to reapply them.

## 8. Automated test history and current verification status

Test-count history matters because a previous discussion briefly confused a correction to the test count with a live runtime success report.

- The user corrected the suite result to **51 passed** at the time of the spawn/catch work.
- The spawn/hint/catch/collection behavior was separately verified by the user in live Matrix testing.
- The image patch added 4 focused tests in `tests/test_matrix_media.py` for:
  - female-specific image selection
  - male/base image selection
  - fallback to base image if female-specific image is missing
  - species without gender differences
- The image patch was locally checked against the contemporaneous source snapshot: patch application, `git diff --check`, Python compilation, and the 4 focused media tests passed.
- The next layout patch was reported as having 6 focused media/announcement tests passing in its validation. That was not a full suite run.
- No full-suite result after the image/layout patches was established in the conversation. **Do not claim the current full test suite passes until it is run in the current checkout.**

Recommended verification commands in the project Poetry environment:

```fish
cd ~/pokematrix
git status --short --branch
git diff --check
poetry run pytest -v
```

## 9. Background spawn images — investigation and current unknown

The user wants the richer Pokétwo-style spawn images with scenic/background artwork, rather than only the plain local Pokémon sprites.

The important finding from inspecting the original Pokétwo spawn implementation (`cogs/spawning.py`):

- Pokétwo does not simply load a different static file from `data/images/` for the background scene.
- The original code builds an image endpoint URL with the equivalent of:

```python
url = urljoin(self.bot.config.SERVER_URL, "image")
```

- It sends request parameters corresponding to:
  - `species`: the Pokémon species ID, converted to a string
  - `time`: day/night setting
  - `gender`: generated gender
- The endpoint returns a rendered image. The original bot uses the local sprite as a fallback if rendering fails.
- The renderer is a separate image-rendering service. The actual server host is not hardcoded in `cogs/spawning.py`; it comes from `self.bot.config.SERVER_URL`.
- The actual deployed value of `SERVER_URL` was **not found/confirmed** in the source inspected during this conversation. It may be supplied through deployment/private runtime configuration.

### What remains unknown

- The real `SERVER_URL` value in Pokétwo's production deployment.
- Whether that production renderer is public, accessible without credentials, rate-limited, or intended for third-party clients.
- Whether its rendering service source code is present in another repository or private deployment project.
- Whether the background scene assets are publicly available or covered by any separate usage/licensing constraints.

### Suggested next investigation

Before hardcoding anything, search the local checkout and available original Pokétwo repository/configuration for:

- `SERVER_URL`
- `server_url`
- the `image` route/endpoint
- deployment configuration, environment variables, config templates, Docker/compose files, and README references
- any sibling service/repository that implements the `/image` endpoint

If the hostname is still not discoverable, explain that the source tells us the endpoint path and parameters but not the deployed host. Do not invent a URL or assume that a public endpoint exists.

### Preferred implementation direction

If a legitimate renderer endpoint/source can be found, implement a small configurable renderer client in PokeMatrix:

1. Read the renderer base URL from configuration/environment; do not hardcode deployment-only settings.
2. Request the rendered image with species ID, time-of-day, and gender.
3. Apply a sensible timeout and handle HTTP errors.
4. Upload the returned bytes to Matrix as an image.
5. Fall back to the current local sprite (`game/matrix_media.py`) when the service is unavailable.
6. Keep the existing hidden-name announcement and text-above-image layout unchanged.

If the original service cannot be reused, investigate whether the rendering code/assets can be recreated or self-hosted. Do not silently replace original Pokétwo mechanics/artwork with a simplistic approximation.

## 10. Git and patch workflow used previously

The user has preferred incremental patch files for code changes. The earlier workflow was:

```fish
cd ~/pokematrix
git apply --check ~/Downloads/<patchname>.patch
git apply ~/Downloads/<patchname>.patch
git diff --check
poetry run pytest -v
```

Patches were built against snapshots of the source at the time. Do not assume an old patch will apply to today's branch or reapply an already-applied patch. In Codex Desktop, it is usually better to inspect and edit the open local repository directly, then show the user a focused diff.

## 11. Guidance for Codex

When continuing this project:

1. Start by inspecting `git status --short --branch`, the repository structure, relevant current files, and the existing tests.
2. Treat this document as historical project context, not as a substitute for reading the source.
3. Preserve the currently working Matrix spawn/catch/image behavior.
4. Make the next change narrowly focused on discovering/reusing the Pokétwo image renderer or making the richer backgrounds work.
5. Keep the original game models/mechanics shared wherever possible.
6. Add focused tests for new behavior and run the complete test suite in the project Poetry environment.
7. Show the user exactly what changed and distinguish focused-test results from full-suite results.
8. Never expose `.env`, Matrix credentials, session tokens, Mongo passwords, or other secrets in outputs or commits.
9. Do not reset the repository, delete data, drop Mongo databases, remove Docker volumes, or push changes without explicit permission.

## 12. Follow-up requested during Matrix command work

- After polishing the `!pokemon` and `!dex` output, update the catch congratulations response to mention the catching player's Matrix display name/username, matching the Pokétwo-style example the user provided.
- The user has confirmed `!start`, `!pick`, `!pokemon`, spawning, `!h`, `!c`, `!s`, `!info`, and `!dex` work. Notify them when each change is ready for a bot reset and live test.

## 13. Ready-to-use Codex starting prompt

Paste this into Codex after opening `~/pokematrix`:

> Read `POKEMATRIX_CODEX_HANDOFF.md` first, then inspect the actual repository and current Git working tree. This document is historical context, so verify all paths and behavior against the current checkout. Do not reset or overwrite local changes. PokeMatrix is a Matrix adaptation of Pokétwo and should reuse the original Pokétwo models and game logic. The Matrix spawn/catch/hint/collection flow works, and the latest spawn layout has been confirmed: generic hidden-name announcement first, `!h` hint instructions, then the Pokémon image below the text. The current image implementation uses local sprites as a fallback. My next goal is to use the richer Pokétwo background spawn images. Investigate the original renderer configuration and `/image` endpoint first. The original `cogs/spawning.py` builds an endpoint from `self.bot.config.SERVER_URL` plus `image`, with `species`, `time`, and `gender` parameters, but the production hostname has not yet been identified. Do not guess a URL. Find the actual configuration or renderer implementation, report what you establish, and then propose the smallest safe implementation. Preserve current behavior, add tests, and run the full test suite. Do not push anything or touch database data.

---

*End of handoff.*
