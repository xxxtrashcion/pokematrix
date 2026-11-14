"""Shared Pokédex milestone definitions and progression rules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PokedexMilestone:
    key: str
    title: str
    first_entry: int
    last_entry: int
    reward_species_id: int = 10147  # Original Magearna
    reward_count: int = 1

    @property
    def total_entries(self) -> int:
        return self.last_entry - self.first_entry + 1


@dataclass(frozen=True)
class PokedexMilestoneProgress:
    milestone: PokedexMilestone
    entries_caught: int
    unlocked: bool
    complete: bool
    claimed: bool

    @property
    def unclaimed(self) -> bool:
        return self.complete and not self.claimed


POKEDEX_MILESTONES = (
    PokedexMilestone("GEN_1_TO_7", "Gen I-VII", 1, 809),
    PokedexMilestone("GEN_8", "Gen VIII Expansion", 810, 898),
    PokedexMilestone("HISUI", "Hisui Expansion", 899, 905),
    PokedexMilestone("GEN_9", "Gen IX Expansion", 906, 1010),
    PokedexMilestone("DLC_1", "Teal Mask Expansion", 1011, 1017),
    PokedexMilestone("DLC_2", "Indigo Disk Expansion", 1018, 1025),
)


def get_pokedex_milestones(pokedex: dict, claimed_rewards: dict) -> list[PokedexMilestoneProgress]:
    """Return progress with later milestones locked until the prior one is complete."""
    progress = []
    unlocked = True
    for milestone in POKEDEX_MILESTONES:
        entries_caught = sum(
            bool(pokedex.get(str(entry), 0))
            for entry in range(milestone.first_entry, milestone.last_entry + 1)
        )
        complete = unlocked and entries_caught == milestone.total_entries
        claimed = complete and bool(claimed_rewards.get(milestone.key))
        progress.append(
            PokedexMilestoneProgress(
                milestone=milestone,
                entries_caught=entries_caught,
                unlocked=unlocked,
                complete=complete,
                claimed=claimed,
            )
        )
        unlocked = complete
    return progress
