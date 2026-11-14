import pytest

from bot import format_matrix_pokemon


class FakePokemon:
    def __init__(self, gender):
        self.gender = gender
        self.idx = 12
        self.format_spec = None

    def __format__(self, format_spec):
        self.format_spec = format_spec
        return "Level 5 92.00% Eevee No. 12"


@pytest.mark.parametrize(
    ("gender", "symbol"),
    [
        ("male", "♂"),
        ("female", "♀"),
        ("unknown", "⚪"),
    ],
)
def test_matrix_pokemon_uses_unicode_gender_symbols(gender, symbol):
    pokemon = FakePokemon(gender)

    rendered = format_matrix_pokemon(pokemon)

    assert rendered == f"Level 5 92.00% Eevee {symbol} No. 12"
    assert pokemon.format_spec == "lnpfx!G"


def test_matrix_pokemon_does_not_add_symbol_for_unrecognized_gender():
    pokemon = FakePokemon("not-set")

    rendered = format_matrix_pokemon(pokemon)

    assert rendered == "Level 5 92.00% Eevee No. 12"
    assert pokemon.format_spec == "lnpfx!G"
