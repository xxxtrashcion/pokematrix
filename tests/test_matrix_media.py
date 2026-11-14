from game.matrix_media import pokemon_image_path, spawn_announcement


def test_female_species_uses_gender_specific_artwork(tmp_path):
    female_image = tmp_path / "592F.png"
    female_image.touch()
    (tmp_path / "592.png").touch()

    path = pokemon_image_path(
        592,
        gender="Female",
        has_gender_differences=True,
        image_directory=tmp_path,
    )

    assert path == female_image


def test_male_species_uses_base_artwork(tmp_path):
    base_image = tmp_path / "592.png"
    base_image.touch()
    (tmp_path / "592F.png").touch()

    path = pokemon_image_path(
        592,
        gender="Male",
        has_gender_differences=True,
        image_directory=tmp_path,
    )

    assert path == base_image


def test_missing_female_variant_falls_back_to_base_artwork(tmp_path):
    base_image = tmp_path / "592.png"
    base_image.touch()

    path = pokemon_image_path(
        592,
        gender="Female",
        has_gender_differences=True,
        image_directory=tmp_path,
    )

    assert path == base_image


def test_species_without_gender_differences_always_uses_base_artwork(tmp_path):
    base_image = tmp_path / "25.png"
    base_image.touch()

    path = pokemon_image_path(
        25,
        gender="Female",
        has_gender_differences=False,
        image_directory=tmp_path,
    )

    assert path == base_image



def test_spawn_announcement_hides_species_and_keeps_catch_and_hint_commands():
    plain_text, formatted_body = spawn_announcement(False)

    assert plain_text == (
        "A wild Pokémon has appeared!\n"
        "Guess the Pokémon and type !c <pokemon> to catch it!\n"
        "Use !h for a hint."
    )
    assert "<strong>A wild Pokémon has appeared!</strong>" in formatted_body
    assert "!c &lt;pokemon&gt;" in formatted_body
    assert "!h" in formatted_body
    assert "<code>" not in formatted_body


def test_spawn_announcement_mentions_previous_spawn_fleeing_without_revealing_name():
    plain_text, formatted_body = spawn_announcement(True)

    assert plain_text.startswith("The previous wild Pokémon fled!\n\n")
    assert "A wild Pokémon has appeared!" in plain_text
    assert "<strong>The previous wild Pokémon fled!</strong>" in formatted_body
