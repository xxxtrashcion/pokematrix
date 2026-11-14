"""Shared Pokémon-generation rules used by the platform adapters."""

import math
import random
from typing import Any, Optional

from data import models
from helpers import constants
from helpers.genders import generate_gender
from lib.probability import random_iv_composition


random_iv = lambda: random.randint(0, 31)
random_nature = lambda: random.choice(constants.NATURES)


def iv_percent_to_total(percent: float) -> int:
    return math.ceil(percent / 100 * 186)


def make_pokemon_data(
    member,
    species: models.Species,
    *,
    owner_id: str,
    idx: int,
    shiny_boost: Optional[int] = 1,
    min_iv_percent: Optional[float] = 0,
    max_iv_percent: Optional[float] = 100,
    fixed_level: Optional[int] = None,
    **kwargs,
) -> dict[str, Any]:
    """Build a Pokémon document using the original game's generation rules.

    The caller supplies the member model, owner ID, and reserved collection
    index. Discord and Matrix adapters can therefore share all generation
    behavior without sharing their transport or persistence layers.

    ``fixed_level`` is used for the Matrix starter flow. Normal game catches
    retain the original level distribution when it is omitted.
    """
    ivs = [random_iv() for _ in range(6)]
    if min_iv_percent > 0 or max_iv_percent < 100:
        min_iv = iv_percent_to_total(min_iv_percent)
        max_iv = iv_percent_to_total(max_iv_percent)
        ivs = random_iv_composition(sum_lower_bound=min_iv, sum_upper_bound=max_iv)

    level = fixed_level if fixed_level is not None else min(max(int(random.normalvariate(20, 10)), 1), 50)
    shiny = member.determine_shiny(species, boost=shiny_boost)
    gender = generate_gender(species)

    possible_moves = [x.move.id for x in species.moves if level >= x.method.level]
    moves = random.sample(possible_moves, k=min(len(possible_moves), 4))

    return {
        "owner_id": owner_id,
        "owned_by": "user",
        "species_id": species.id,
        "level": level,
        "xp": 0,
        "nature": random_nature(),
        "iv_hp": ivs[0],
        "iv_atk": ivs[1],
        "iv_defn": ivs[2],
        "iv_satk": ivs[3],
        "iv_sdef": ivs[4],
        "iv_spd": ivs[5],
        "iv_total": sum(ivs),
        "shiny": shiny,
        "gender": gender,
        "moves": moves,
        "idx": idx,
        **kwargs,
    }
