from types import SimpleNamespace

from game.battling.turn_order import get_priority


def make_pokemon(speed=100, ailments=None, speed_stage=0):
    return SimpleNamespace(
        spd=speed,
        ailments=set(ailments or []),
        stages=SimpleNamespace(spd=speed_stage),
    )


def make_move_action(priority=0):
    return {
        "type": "move",
        "value": SimpleNamespace(priority=priority),
    }


def test_higher_move_priority_acts_first():
    pokemon = make_pokemon()

    normal = get_priority(make_move_action(0), pokemon)
    priority_move = get_priority(make_move_action(1), pokemon)

    assert priority_move > normal


def test_speed_breaks_ties_for_same_move_priority():
    fast = make_pokemon(speed=120)
    slow = make_pokemon(speed=100)

    assert get_priority(make_move_action(1), fast) > get_priority(
        make_move_action(1), slow
    )


def test_paralysis_halves_effective_speed():
    healthy = make_pokemon(speed=100)
    paralyzed = make_pokemon(speed=100, ailments=["Paralysis"])

    assert get_priority(make_move_action(), healthy) == (0, 100)
    assert get_priority(make_move_action(), paralyzed) == (0, 50)


def test_speed_stages_affect_turn_order():
    normal = make_pokemon(speed=100)
    boosted = make_pokemon(speed=100, speed_stage=1)

    assert get_priority(make_move_action(), boosted) > get_priority(
        make_move_action(), normal
    )


def test_non_move_actions_precede_moves():
    pokemon = make_pokemon()

    assert get_priority({"type": "switch"}, pokemon) > get_priority(
        make_move_action(), pokemon
    )


def test_move_priority_takes_precedence_over_speed():
    slow_priority_move = get_priority(
        make_move_action(priority=1),
        make_pokemon(speed=50),
    )

    fast_normal_move = get_priority(
        make_move_action(priority=0),
        make_pokemon(speed=200),
    )

    assert slow_priority_move > fast_normal_move
