import pytest

from gridiron.data.sample import generate_sample_league
from gridiron.engine.adapter import build_team
from gridiron.engine.skeleton.game import GameSim


@pytest.fixture(scope="session")
def sample_league():
    return generate_sample_league(seed=7)


@pytest.fixture
def init_game_sim(sample_league):
    """원본 테스트의 initGameSim: 두 팀으로 새 GameSim."""

    def make(seed: int = 0) -> GameSim:
        abbrs = sorted(sample_league.teams)[:2]
        day = sample_league.season_start()
        teams = [build_team(sample_league, abbrs[0], 0, day), build_team(sample_league, abbrs[1], 1, day)]
        return GameSim(teams, seed=seed)

    return make
