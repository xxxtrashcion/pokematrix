import pytest

from bot import format_matrix_pokemon_info, format_matrix_pokedex, matrix_pokedex_page, normalize_command


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("!p", "!pokemon"),
        ("!P", "!pokemon"),
        ("!pokemon", "!pokemon"),
        ("!c", "!catch"),
        ("!C", "!catch"),
        ("!h", "!hint"),
        ("!s", "!select"),
        ("!S", "!select"),
        ("!select", "!select"),
        ("!i", "!info"),
        ("!INFO", "!info"),
        ("!d", "!dex"),
        ("!DEX", "!dex"),
        ("!start", "!start"),
        ("!UNKNOWN", "!unknown"),
    ],
)
def test_normalize_command_resolves_aliases_case_insensitively(command, expected):
    assert normalize_command(command) == expected


def test_format_matrix_pokemon_info_includes_stats_ivs_and_shiny_marker():
    class Pokemon:
        idx = 3
        level = 12
        nature = "Brave"
        gender = "Male"
        shiny = True
        iv_hp = 31
        iv_atk = 30
        iv_defn = 29
        iv_satk = 28
        iv_sdef = 27
        iv_spd = 26
        hp = 40
        atk = 35
        defn = 30
        satk = 25
        sdef = 26
        spd = 20

        def __format__(self, spec):
            return "Greavard No. 3"

    rendered = format_matrix_pokemon_info(Pokemon())

    assert "Greavard ♂ No. 3" in rendered
    assert "Level 12 · Brave · Male" in rendered
    assert "HP: 40 (IV 31/31)" in rendered
    assert "Total IV: 171/186" in rendered
    assert "Shiny ✨" in rendered


def test_format_matrix_pokedex_summarizes_unique_species_and_total_catches():
    class Species:
        def __init__(self, name):
            self.name = name

    class GameData:
        total_pokedex_count = 100

        @staticmethod
        def species_by_number(number):
            return {25: Species("Pikachu"), 133: Species("Eevee")}.get(number)

    rendered = format_matrix_pokedex({"pokedex": {"25": 3, "133": 1, "999": 4}}, GameData())

    assert "Your Pokédex · 2/100 species · 2.0%" in rendered
    assert "█░░░░░░░░░" in rendered
    assert "Total Pokémon caught: 4" in rendered
    assert "#025 Pikachu · 3 caught" in rendered
    assert "#133 Eevee · 1 caught" in rendered
    assert "999" not in rendered


def test_matrix_pokedex_page_includes_species_status_and_inline_sprite():
    class Species:
        id = 25
        dex_number = 25
        name = "Pikachu"
        catchable = True

    class GameData:
        total_pokedex_count = 1

        @staticmethod
        def all_pokemon():
            return [Species()]

    body, formatted_body, page, page_count = matrix_pokedex_page(
        {"pokedex": {"25": 2}},
        GameData(),
        1,
        {25: "mxc://example.org/sprite"},
    )

    assert "Pikachu #25 · ✅ 2 caught!" in body
    assert '<img src="mxc://example.org/sprite" width="20" height="20"' in formatted_body
    assert "<table>" not in formatted_body
    assert "<img src=\"mxc://example.org/sprite\"" in formatted_body
    assert page == page_count == 1
