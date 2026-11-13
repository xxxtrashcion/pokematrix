import random
from collections.abc import Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def select_rewards(
    rewards: Sequence[T],
    *,
    k: int = 1,
    rng: Any = random,
) -> list[T]:
    """Select rewards using their configured probability weights."""

    weights = [reward.chance for reward in rewards]

    if sum(weights) not in (1, 100):
        raise ValueError("Chances of rewards must add up to a total of 1 or 100 (100%)")

    return rng.choices(rewards, weights=weights, k=k)


def select_amount(
    amounts: Sequence[int],
    *,
    rng: Any = random,
) -> int:
    """Choose a random quantity from a reward's configured amounts."""

    return rng.choice(amounts)
