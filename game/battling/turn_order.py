from data.constants import STAT_STAGE_MULTIPLIERS


def get_priority(action, selected) -> tuple[float, float]:
    """Calculate action ordering using move priority and effective speed.

    Non-move actions take precedence over moves.
    Moves are ordered by their priority, then by effective speed.
    Paralysis reduces effective speed by half.
    """
    if action["type"] != "move":
        return (float("inf"), 0.0)

    speed = selected.spd

    if "Paralysis" in selected.ailments:
        speed *= 0.5

    effective_speed = speed * STAT_STAGE_MULTIPLIERS[selected.stages.spd]

    return (action["value"].priority, effective_speed)
