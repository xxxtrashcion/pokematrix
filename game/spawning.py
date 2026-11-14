"""Shared wild-spawn helpers used by the platform adapters."""

import random

from data import models


SPAWN_MESSAGE_THRESHOLD = 24
GMAX_CHANCE = 1 / 100
POKEDEX_MILESTONE_REWARDS = {
    10: 350,
    100: 3_500,
    1_000: 35_000,
    10_000: 350_000,
    100_000: 3_500_000,
}


def normalize_guess(guess: str) -> str:
    """Normalize a catch guess the same way the original Pokétwo command does."""
    return models.deaccent(guess.lower().replace("′", "'"))


def is_correct_guess(guess: str, species) -> bool:
    return normalize_guess(guess) in species.correct_guesses


def make_hint(species, *, rng=random) -> str:
    """Reveal roughly half of the alphabetic characters in a species name."""
    name = species.name
    eligible = [index for index, character in enumerate(name) if character.isalpha()]
    blanks = set(rng.sample(eligible, len(eligible) // 2))
    return "".join("＿" if index in blanks else character for index, character in enumerate(name))


def rolls_gigantamax(species, *, rng=random) -> bool:
    """Apply the original 1% Gigantamax-factor chance for eligible species."""
    return bool(species.gmax and rng.random() < GMAX_CHANCE)


def pokedex_reward(current_count: int) -> int:
    """Return the original game's Pokécoin reward for the next species catch."""
    if current_count == 0:
        return 35
    return POKEDEX_MILESTONE_REWARDS.get(current_count + 1, 0)
