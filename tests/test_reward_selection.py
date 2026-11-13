from random import Random
from types import SimpleNamespace

import pytest

from game.rewards.selection import select_amount, select_rewards


def make_reward(chance, amounts):
    return SimpleNamespace(chance=chance, amounts=amounts)


def test_select_rewards_returns_requested_count():
    rewards = [
        make_reward(100, [1]),
        make_reward(0, [2]),
    ]

    selected = select_rewards(rewards, k=5, rng=Random(0))

    assert len(selected) == 5
    assert all(reward is rewards[0] for reward in selected)


def test_select_rewards_accepts_fractional_weights():
    rewards = [
        make_reward(0.25, [1]),
        make_reward(0.75, [2]),
    ]

    selected = select_rewards(rewards, k=20, rng=Random(0))

    assert len(selected) == 20
    assert all(reward in rewards for reward in selected)


def test_select_rewards_rejects_invalid_probability_total():
    rewards = [
        make_reward(40, [1]),
        make_reward(40, [2]),
    ]

    with pytest.raises(ValueError, match="Chances of rewards must add up"):
        select_rewards(rewards)


def test_select_amount_returns_configured_amount():
    assert select_amount(range(10, 11), rng=Random(0)) == 10


def test_select_amount_only_returns_allowed_values():
    allowed = [5, 10, 15, 20]

    for _ in range(100):
        assert select_amount(allowed) in allowed
