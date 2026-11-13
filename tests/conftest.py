import pytest

from data import DataManager


@pytest.fixture(scope="session")
def game_data():
    return DataManager()
