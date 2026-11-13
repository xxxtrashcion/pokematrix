def test_loads_all_datasets(game_data):
    assert len(game_data.pokemon) == 1472
    assert len(game_data.moves) == 826
    assert len(game_data.items) == 108
    assert len(game_data.effects) == 430


def test_pikachu_lookup(game_data):
    pikachu = game_data.species_by_number(25)

    assert pikachu is not None
    assert pikachu.name == "Pikachu"
    assert pikachu.dex_number == 25


def test_species_have_valid_stats(game_data):
    pikachu = game_data.species_by_number(25)

    assert pikachu.base_stats.total > 0
    assert pikachu.base_stats.hp > 0
    assert pikachu.base_stats.atk > 0


def test_species_have_moves(game_data):
    pikachu = game_data.species_by_number(25)

    assert len(pikachu.moves) > 0


def test_random_spawn_returns_catchable_species(game_data):
    for _ in range(100):
        species = game_data.random_spawn()

        assert species is not None
        assert species.catchable
        assert species.id in game_data.pokemon


def test_random_legendary_spawn(game_data):
    species = game_data.random_spawn(rarity="legendary")

    assert species.catchable
    assert species.legendary


def test_random_mythical_spawn(game_data):
    species = game_data.random_spawn(rarity="mythical")

    assert species.catchable
    assert species.mythical
