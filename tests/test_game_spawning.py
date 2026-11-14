from game.spawning import is_correct_guess, make_hint, normalize_guess, pokedex_reward, rolls_gigantamax


def test_normalize_guess_uses_original_deaccenting_rules():
    assert normalize_guess("PIKACHU") == "pikachu"


def test_is_correct_guess_uses_species_correct_guesses(game_data):
    pikachu = game_data.species_by_number(25)

    assert is_correct_guess("Pikachu", pikachu)
    assert not is_correct_guess("Raichu", pikachu)


def test_make_hint_masks_half_of_alphabetic_characters(game_data):
    bulbasaur = game_data.species_by_name("Bulbasaur")

    class FirstHalfRandom:
        @staticmethod
        def sample(population, count):
            return population[:count]

    hint = make_hint(bulbasaur, rng=FirstHalfRandom)

    assert hint.count("＿") == len(bulbasaur.name) // 2
    assert len(hint) == len(bulbasaur.name)


def test_pokedex_reward_matches_original_first_catch_and_milestones():
    assert pokedex_reward(0) == 35
    assert pokedex_reward(8) == 0
    assert pokedex_reward(9) == 350
    assert pokedex_reward(99) == 3_500
    assert pokedex_reward(999) == 35_000



def test_gigantamax_roll_uses_one_percent_for_eligible_species(game_data):
    species = game_data.species_by_number(1)

    class AlwaysRollLow:
        @staticmethod
        def random():
            return 0.0

    class AlwaysRollHigh:
        @staticmethod
        def random():
            return 1.0

    assert rolls_gigantamax(species, rng=AlwaysRollLow) is bool(species.gmax)
    assert rolls_gigantamax(species, rng=AlwaysRollHigh) is False
