from lib.probability import (
    num_compositions,
    random_iv_composition,
    random_iv_sum,
)


def test_num_compositions():
    assert num_compositions(3, 2) == 4
    assert num_compositions(120, 6, upper_bound=31) == 9565682


def test_random_iv_composition():
    for _ in range(100):
        ivs = random_iv_composition()

        assert len(ivs) == 6
        assert all(0 <= iv <= 31 for iv in ivs)
        assert 0 <= sum(ivs) <= 186


def test_random_iv_composition_with_exact_total():
    for _ in range(25):
        ivs = random_iv_composition(
            sum_lower_bound=93,
            sum_upper_bound=93,
        )

        assert len(ivs) == 6
        assert all(0 <= iv <= 31 for iv in ivs)
        assert sum(ivs) == 93


def test_random_iv_sum_respects_bounds():
    for _ in range(100):
        total = random_iv_sum(lower_bound=20, upper_bound=40)

        assert 20 <= total <= 40
