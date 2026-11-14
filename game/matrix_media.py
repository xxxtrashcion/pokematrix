"""Matrix media helpers for rendering original Pokétwo artwork."""

from pathlib import Path


DEFAULT_IMAGE_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "images"
DEFAULT_SPRITE_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "sprites"


def pokemon_image_path(
    species_id: int,
    *,
    gender: str | None,
    has_gender_differences: bool,
    image_directory: Path = DEFAULT_IMAGE_DIRECTORY,
) -> Path:
    """Return the original Pokétwo image asset for a species and its gender."""
    if has_gender_differences and (gender or "").casefold() == "female":
        female_path = image_directory / f"{species_id}F.png"
        if female_path.is_file():
            return female_path

    return image_directory / f"{species_id}.png"


def pokemon_sprite_path(
    species_id: int,
    *,
    shiny: bool = False,
    dex_number: int | None = None,
    sprite_directory: Path = DEFAULT_SPRITE_DIRECTORY,
) -> Path:
    """Return the small front sprite used in Pokétwo's collection and dex lists."""
    candidate_ids = [species_id]
    if dex_number is not None and dex_number != species_id:
        candidate_ids.append(dex_number)

    if shiny:
        for candidate_id in candidate_ids:
            shiny_path = sprite_directory / "front-shiny" / f"{candidate_id}.png"
            if shiny_path.is_file():
                return shiny_path

    for candidate_id in candidate_ids:
        regular_path = sprite_directory / "front" / f"{candidate_id}.png"
        if regular_path.is_file():
            return regular_path

    # Preserve the familiar species path for useful logging if an asset is missing.
    folder = "front-shiny" if shiny else "front"
    return sprite_directory / folder / f"{species_id}.png"



def spawn_announcement(previous_spawn: bool) -> tuple[str, str]:
    """Build the name-free Matrix spawn announcement in plain and HTML forms."""
    prefix = "The previous wild Pokémon fled!\n\n" if previous_spawn else ""
    plain_text = (
        f"{prefix}A wild Pokémon has appeared!\n"
        "Guess the Pokémon and type !c <pokemon> to catch it!\n"
        "Use !h for a hint."
    )

    html_prefix = (
        "<strong>The previous wild Pokémon fled!</strong><br><br>"
        if previous_spawn
        else ""
    )
    formatted_body = (
        f"{html_prefix}<strong>A wild Pokémon has appeared!</strong><br>"
        "Guess the Pokémon and type !c &lt;pokemon&gt; to catch it!<br>"
        "Use !h for a hint."
    )
    return plain_text, formatted_body
