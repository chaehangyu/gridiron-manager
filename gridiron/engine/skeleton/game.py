"""경기 진행 (원본 GameSim.football/index.ts).

메서드 이름은 원본 테스트를 그대로 옮길 수 있도록 원본(camelCase)을 유지한다.
시계 단위는 원본처럼 "분"이다 (clock=15.0 → 15:00).
"""
from __future__ import annotations

from typing import Iterable

from ..outcome.base import OutcomeModel
from ..outcome.fbgm import FbgmOutcome
from . import formations
from .composite import FACTOR_OPTIONS, POSITIONS, blocking_factors, composite_factor, get_players
from .lng_tracker import LngTracker
from .pbp import PlayByPlayLogger
from .penalties import PENALTIES_BY_PLAY_TYPE
from .play import SCRIMMAGE_EXTRA_POINT, SCRIMMAGE_KICKOFF, SCRIMMAGE_TWO_POINT_CONVERSION, Play, js_round
from .rng import Rng, bound
from .settings import GameSettings
from .types import PlayerGameSim, TeamGameSim

TEAM_NUMS = (0, 1)
FIELD_GOAL_DISTANCE_YARDS_ADDED_FROM_SCRIMMAGE = 17
ESTIMATED_SECONDS_PER_KNEEL = 42
ESTIMATED_SECONDS_PER_KNEEL_TIMEOUT = 2
YARDS_NEEDED_TO_KNEEL = 3
NUM_DOWNS = 4
TWO_MINUTE_WARNING_TIME = 2
FEWER_INJURIES_POS = {"QB", "P", "K"}
FATIGUE_POS = {"RB", "WR", "TE", "DL", "LB", "CB", "S"}


def fatigue(energy: float, injured: bool) -> float:
    """에너지(0=지침, 1=생생) → 피로 계수 (원본 fatigue)."""
    if injured:
        return 0.0
    energy += 0.05
    return 1.0 if energy > 1 else energy


def get_injury_rate(base_rate: float, age: float, playing_through: bool) -> float:
    rate = base_rate * 1.03 ** (min(50, age) - 26)
    if playing_through:
        rate *= 1.5
    return rate


class GameSim:
    def __init__(self, teams: list[TeamGameSim], *, settings: GameSettings | None = None,
                 outcome: OutcomeModel | None = None, seed: int | None = None, do_play_by_play: bool = False,
                 playoffs: bool = False, neutral_site: bool = False, home_court_factor: float = 1.0,
                 gid: str = "") -> None:
        self.id = gid
        self.settings = settings or GameSettings()
        self.outcome: OutcomeModel = outcome or FbgmOutcome()
        self.rng = Rng(seed)
        self.playoffs = playoffs
        self.neutral_site = neutral_site
        self.team = teams
        self.playByPlay = PlayByPlayLogger(do_play_by_play)
        self.playByPlay.game = self
        s = self.settings
        self.overtimeType = s.overtime_type_playoffs if playoffs else s.overtime_type
        self.maxOvertimes = s.max_overtimes_playoffs if playoffs else s.max_overtimes
        self.overtime = False
        self.overtimes = 0

        self.overtimeState: str | None = None
        self.isClockRunning = False
        self.awaitingAfterTouchdown = False
        self.awaitingAfterSafety = False
        self.currentDrive: int | None = None
        self.scrimmage = SCRIMMAGE_KICKOFF
        self.down = 1
        self.toGo = 10
        self.timeouts = [s.timeouts_per_half, s.timeouts_per_half]
        self.twoMinuteWarningHappened = False
        self.playUntimedPossession = False
        self.twoPointConversionTeam: int | None = None
        self.num_periods = s.num_periods
        self.clock = s.quarter_length

        for t in self.team:
            for p in t.players:
                p.stat["energy"] = 1.0
                p.stat.setdefault("min", 0.0)

        self.playersOnField: list[dict[str, list[PlayerGameSim]]] = [{}, {}]
        self.o, self.d = 0, 1
        self.updatePlayersOnField("starters")
        self.o, self.d = 1, 0
        self.updatePlayersOnField("starters")

        self.awaitingKickoff: int | None = 0 if self.rng.random() < 0.5 else 1
        self.d = self.awaitingKickoff
        self.o = 1 if self.awaitingKickoff == 0 else 0
        self.lastHalfAwaitingKickoff = self.awaitingKickoff
        self.currentPlay = Play(self)
        self.lngTracker = LngTracker()

        if not neutral_site:
            self.homeCourtAdvantage(home_court_factor)

    # ── 경기 전체 ─────────────────────────────────────────
    def homeCourtAdvantage(self, home_court_factor: float) -> None:
        modifier = home_court_factor * bound(1 + self.settings.home_advantage_pct / 100, 0.01, float("inf"))
        for t in TEAM_NUMS:
            factor = modifier if t == 0 else 1.0 / modifier
            for p in self.team[t].players:
                for r in list(p.composite):
                    if r != "endurance":
                        p.composite[r] *= factor

    def run(self) -> dict:
        self.simRegulation()
        num_ot = 0
        while self.team[0].stat["pts"] == self.team[1].stat["pts"] and num_ot < self.maxOvertimes:
            self.simOvertime()
            num_ot += 1
        self.playByPlay.logEvent({"type": "gameOver"})
        return {
            "gid": self.id,
            "overtimes": self.overtimes,
            "team": self.team,
            "playByPlay": self.playByPlay.events,
            "scoringSummary": self.playByPlay.final_scoring_summary(),
        }

    def isFirstPeriodAfterHalftime(self, quarter: int) -> bool:
        return self.num_periods % 2 == 0 and quarter == self.num_periods // 2 + 1

    def kickoffAfterEndOfPeriod(self, quarter: int) -> bool:
        return self.isFirstPeriodAfterHalftime(quarter + 1) or quarter >= self.num_periods

    def logTimeouts(self) -> None:
        self.playByPlay.logEvent({"type": "timeouts", "timeouts": list(self.timeouts)})

    def simRegulation(self) -> None:
        quarter = 1
        while True:
            while self.clock > 0 or self.awaitingAfterTouchdown or self.playUntimedPossession:
                self.simPlay()
            if self.isFirstPeriodAfterHalftime(quarter + 1):
                self.timeouts = [self.settings.timeouts_per_half] * 2
                self.logTimeouts()
                self.twoMinuteWarningHappened = False
                self.d = 1 if self.lastHalfAwaitingKickoff == 0 else 0
                self.o = self.lastHalfAwaitingKickoff
                self.awaitingKickoff = self.d
                self.lastHalfAwaitingKickoff = self.d
                self.scrimmage = SCRIMMAGE_KICKOFF
            elif quarter == self.num_periods:
                break
            quarter += 1
            self.team[0].stat["ptsQtrs"].append(0)
            self.team[1].stat["ptsQtrs"].append(0)
            self.clock = self.settings.quarter_length
            self.playByPlay.logEvent({"type": "quarter", "quarter": quarter,
                                      "startsWithKickoff": self.kickoffAfterEndOfPeriod(quarter - 1)})

    def simOvertime(self) -> None:
        self.clock = self.settings.overtime_length_playoffs if self.playoffs else self.settings.overtime_length
        self.overtime = True
        self.overtimes += 1
        if self.overtimeState is None:
            self.overtimeState = "initialKickoff"
            self.awaitingKickoff = 0 if self.rng.random() < 0.5 else 1
            self.lastHalfAwaitingKickoff = self.awaitingKickoff
            self.scrimmage = SCRIMMAGE_KICKOFF
        self.team[0].stat["ptsQtrs"].append(0)
        self.team[1].stat["ptsQtrs"].append(0)
        self.timeouts = [self.settings.timeouts_overtime] * 2
        self.logTimeouts()
        self.twoMinuteWarningHappened = False
        self.playByPlay.logEvent({"type": "overtime", "overtimes": self.overtimes,
                                  "startsWithKickoff": self.kickoffAfterEndOfPeriod(self.num_periods + self.overtimes - 1)})
        self.d = 1 if self.lastHalfAwaitingKickoff == 0 else 0
        self.o = self.lastHalfAwaitingKickoff
        self.awaitingKickoff = self.d
        self.lastHalfAwaitingKickoff = self.d
        self.scrimmage = SCRIMMAGE_KICKOFF
        while (self.clock > 0 or self.playUntimedPossession) and self.overtimeState != "over":
            self.simPlay()

    def getTopPlayerOnField(self, t: int, pos: str) -> PlayerGameSim:
        players = self.playersOnField[t].get(pos)
        if not players:
            raise RuntimeError(f"No player found at position {pos}")
        return players[0]

    # ── 플레이 선택 ───────────────────────────────────────
    def probPass(self) -> float:
        return self.outcome.prob_pass(self)

    def probOnside(self) -> float:
        if self.awaitingAfterSafety:
            return 0.0
        n_qtrs = len(self.team[0].stat["ptsQtrs"])
        if n_qtrs < self.num_periods:
            return 0.001 * self.settings.onside_factor
        if n_qtrs != self.num_periods:
            return 0.0
        import math
        scores_down = math.ceil((self.team[self.d].stat["pts"] - self.team[self.o].stat["pts"]) / 8)
        if scores_down <= 0 or scores_down >= 4:
            return 0.0
        if self.clock < 2:
            return 1.0
        if scores_down >= 2 and self.clock < 2.5:
            return 0.9
        if scores_down >= 3 and self.clock < 3.5:
            return 0.8
        if scores_down >= 2 and self.clock < 5:
            return scores_down / 20
        return 0.0

    def hurryUp(self) -> bool:
        pts_down = self.team[self.d].stat["pts"] - self.team[self.o].stat["pts"]
        quarter = len(self.team[0].stat["ptsQtrs"])
        return ((self.kickoffAfterEndOfPeriod(quarter) and self.scrimmage >= 50)
                or (quarter == self.num_periods and pts_down >= 0)) and self.clock <= 2

    def probMadeFieldGoal(self, kicker: PlayerGameSim | None = None) -> float:
        if kicker is None:
            kicker = next((p for p in self.team[self.o].depth.get("K", []) if not p.injured), None)
        if kicker is None:
            return 0.0
        return self.outcome.prob_made_field_goal(self, kicker)

    def getPlayType(self) -> str:
        rng = self.rng
        if self.awaitingKickoff is not None:
            return "onsideKick" if rng.random() < self.probOnside() else "kickoff"

        pts_down = self.team[self.d].stat["pts"] - self.team[self.o].stat["pts"]
        quarter = len(self.team[0].stat["ptsQtrs"])

        if self.awaitingAfterTouchdown:
            if not self.settings.two_point_conversions:
                return "extraPoint"
            if pts_down == 2 and rng.random() < 0.7:
                return "twoPointConversion"
            if quarter >= self.num_periods - 1:
                chart = {0: "extraPoint", 1: "extraPoint", 2: "twoPointConversion", 4: "extraPoint",
                         5: "twoPointConversion", 7: "extraPoint", 8: "extraPoint", 10: "twoPointConversion",
                         11: "extraPoint", 13: "twoPointConversion", 14: "extraPoint", 15: "extraPoint",
                         18: "twoPointConversion", -1: "twoPointConversion", -2: "extraPoint", -3: "extraPoint",
                         -5: "twoPointConversion", -6: "extraPoint", -7: "extraPoint", -8: "extraPoint",
                         -9: "extraPoint", -10: "extraPoint", -12: "twoPointConversion", -13: "extraPoint",
                         -14: "extraPoint"}
                if pts_down in chart:
                    return chart[pts_down]
            return "extraPoint" if rng.random() < 0.95 else "twoPointConversion"

        if quarter >= self.num_periods and pts_down < 0:
            num_timeouts = self.timeouts[self.d] + (1 if self.clock > TWO_MINUTE_WARNING_TIME else 0)
            downs_remaining = NUM_DOWNS - self.down
            timeout_downs = min(num_timeouts, downs_remaining)
            clock_running_downs = downs_remaining - timeout_downs
            time_after = self.clock - (ESTIMATED_SECONDS_PER_KNEEL_TIMEOUT * timeout_downs
                                       + ESTIMATED_SECONDS_PER_KNEEL * clock_running_downs) / 60
            if time_after < 0:
                if self.scrimmage > YARDS_NEEDED_TO_KNEEL * downs_remaining:
                    return "kneel"
                if rng.random() < 0.9:
                    return "run"

        need_touchdown = quarter >= self.num_periods and pts_down > 3 and (
            self.clock <= 2 or self.overtimeState == "secondPossession")

        never_punt = False
        if quarter == self.num_periods and pts_down > 0:
            num_timeouts = self.timeouts[self.o] + (1 if self.clock > TWO_MINUTE_WARNING_TIME else 0)
            downs_remaining = NUM_DOWNS - 1
            timeout_downs = min(num_timeouts, downs_remaining)
            clock_running_downs = downs_remaining - timeout_downs
            time_after = self.clock - (ESTIMATED_SECONDS_PER_KNEEL_TIMEOUT * timeout_downs
                                       + ESTIMATED_SECONDS_PER_KNEEL * clock_running_downs) / 60
            if time_after < 0.5:
                never_punt = True
        elif quarter > self.num_periods and pts_down > 0:
            never_punt = True

        if (self.clock <= 10 / 60 and self.kickoffAfterEndOfPeriod(quarter) and not need_touchdown
                and self.probMadeFieldGoal() >= 0.02):
            return "fieldGoalLate"

        if (quarter > self.num_periods
                and (self.overtimeType == "suddenDeath" or self.overtimeState in ("secondPossession", "bothTeamsPossessed"))
                and pts_down < 3 and self.probMadeFieldGoal() >= 0.9):
            return "fieldGoal"

        if self.down == 4 and not need_touchdown:
            prob_fg = self.probMadeFieldGoal()
            if (prob_fg >= 0.5 and quarter == self.num_periods and self.clock <= 6
                    and ((0 <= pts_down <= 2) or (-8 <= pts_down <= -4))):
                return "fieldGoal"

            def go_for_it() -> float:
                if (((quarter > self.num_periods and self.overtimeType == "suddenDeath")
                     or self.overtimeState != "firstPossession") and pts_down == 0 and prob_fg >= 0.7):
                    return 0.0
                if self.scrimmage < 40:
                    return 0.0
                for limit, prob in ((1, 0.75), (2, 0.5), (3, 0.35), (4, 0.2), (5, 0.05), (7, 0.01), (10, 0.001)):
                    if self.toGo <= limit:
                        return prob
                return 0.0

            prob_go = min(0.99, go_for_it() * self.settings.fourth_down_factor)
            if rng.random() > prob_go:
                if prob_fg >= 0.7:
                    return "fieldGoal"
                if rng.random() < bound((prob_fg - 0.3) / 0.5, 0, 1):
                    return "fieldGoal"
                if not never_punt:
                    return "punt"

        return "pass" if rng.random() < self.probPass() else "run"

    # ── 한 플레이 ─────────────────────────────────────────
    def simPlay(self) -> None:
        self.playUntimedPossession = False
        play_type = self.getPlayType()
        if play_type == "extraPoint":
            self.scrimmage = SCRIMMAGE_EXTRA_POINT
            self.down = 1
            self.toGo = 100 - self.scrimmage
        elif play_type == "twoPointConversion":
            self.scrimmage = SCRIMMAGE_TWO_POINT_CONVERSION
            self.down = 1
            self.toGo = 100 - self.scrimmage

        self.currentPlay = Play(self)
        self.playByPlay.logClock(awaitingKickoff=self.awaitingKickoff, awaitingAfterTouchdown=self.awaitingAfterTouchdown,
                                 clock=self.clock, down=self.down, scrimmage=self.scrimmage, t=self.o, toGo=self.toGo)

        if self.o != self.currentDrive and self.down == 1 and play_type not in (
                "kickoff", "onsideKick", "extraPoint", "twoPointConversion"):
            self.currentPlay.addEvent({"type": "newDrive"})

        if play_type == "kickoff":
            dt = self.doKickoff()
        elif play_type == "onsideKick":
            dt = self.doKickoff(True)
        elif play_type in ("extraPoint", "fieldGoal", "fieldGoalLate"):
            dt = self.doFieldGoal(play_type)
        elif play_type == "twoPointConversion":
            dt = self.doTwoPointConversion()
        elif play_type == "punt":
            dt = self.doPunt()
        elif play_type in ("pass", "run"):
            if self.down == 4:
                self.playByPlay.logEvent({"type": "goingForItOn4th", "t": self.o})
            dt = self.doPass() if play_type == "pass" else self.doRun()
        elif play_type == "kneel":
            dt = self.doKneel()
        else:
            raise RuntimeError(f'Unknown playType "{play_type}"')

        dt /= 60
        quarter = len(self.team[0].stat["ptsQtrs"])
        clock_at_end = self.clock - dt
        time_expired = clock_at_end <= 0 and self.kickoffAfterEndOfPeriod(quarter)
        self.currentPlay.commit(time_expired)

        two_min_now = False
        if self.kickoffAfterEndOfPeriod(quarter) and clock_at_end <= 2 and not self.twoMinuteWarningHappened:
            self.twoMinuteWarningHappened = True
            self.isClockRunning = False
            self.playByPlay.logEvent({"type": "twoMinuteWarning", "clock": clock_at_end})
            two_min_now = True

        if clock_at_end > 0 and not two_min_now:
            if self.rng.random() < 0.01:
                self.doTimeout(self.o, False)
            elif self.rng.random() < 0.003:
                self.doTimeout(self.d, False)
            if self.kickoffAfterEndOfPeriod(quarter) and self.isClockRunning:
                diff = self.team[self.o].stat["pts"] - self.team[self.d].stat["pts"]
                if quarter >= self.num_periods:
                    if diff < 24:
                        if diff > 0:
                            if self.clock < 2.5:
                                self.doTimeout(self.d, True)
                        elif self.clock < 1.5:
                            self.doTimeout(self.o, True)
                elif self.clock < 1.5:
                    self.doTimeout(self.o, True)

        dt_running = 0.0
        if self.isClockRunning:
            if self.hurryUp():
                dt_running = self.rng.rand_int(5, 13) / 60
                if self.clock - dt - dt_running < 0:
                    dt_running = self.rng.rand_int(0, 4) / 60
            else:
                dt_running = self.rng.rand_int(37, 62) / 60
            dt_running /= self.settings.pace

        if (self.kickoffAfterEndOfPeriod(quarter) and clock_at_end - dt_running <= 2
                and not self.twoMinuteWarningHappened):
            self.twoMinuteWarningHappened = True
            self.isClockRunning = False
            self.playByPlay.logEvent({"type": "twoMinuteWarning", "clock": 2})
            dt_running = bound(clock_at_end - 2, 0, float("inf"))

        dt += dt_running
        self.clock -= dt
        if self.clock < 0:
            dt += self.clock
            self.clock = 0

        self.updatePlayingTime(dt)
        if play_type != "kneel":
            self.injuries()

        if self.team[0].stat["pts"] != self.team[1].stat["pts"] and (
            (self.overtimeState is not None and self.overtimeType == "suddenDeath")
            or (self.overtimeState == "bothTeamsPossessed"
                and (not self.awaitingAfterTouchdown or abs(self.team[0].stat["pts"] - self.team[1].stat["pts"]) > 2))
        ):
            self.overtimeState = "over"

    # ── 세부 동작 ─────────────────────────────────────────
    def doTackle(self, yds_from_scrimmage: int | None) -> None:
        d = self.currentPlay.state["current"].d
        rng = self.rng
        if rng.random() < 0.9:
            positions = None
            if yds_from_scrimmage is not None:
                r = rng.random()
                if yds_from_scrimmage < 2:
                    if r < 0.4:
                        positions = ["DL", "LB"]
                elif yds_from_scrimmage < 7:
                    if r < 0.2:
                        positions = ["LB"]
                    elif r < 0.4:
                        positions = ["LB", "S"]
                elif yds_from_scrimmage < 15:
                    if r < 0.3:
                        positions = ["LB", "S"]
                    elif r < 0.95:
                        positions = ["LB", "S", "CB"]
                else:
                    positions = ["S"] if r < 0.3 else (["S", "CB"] if r < 0.9 else ["S", "CB", "LB"])
            if rng.random() < 0.25:
                tacklers = {self.pickPlayer(d, "tackling", positions, 1.5), self.pickPlayer(d, "tackling", positions, 1.5)}
            else:
                tacklers = {self.pickPlayer(d, "tackling", positions, 1.5)}
            self.currentPlay.addEvent({"type": "tck", "tacklers": tacklers,
                                       "loss": yds_from_scrimmage is not None and yds_from_scrimmage < 0})

    def updateTeamCompositeRatings(self) -> None:
        o, d = self.o, self.d
        tc_o, tc_d = self.team[o].composite, self.team[d].composite
        tc_o["receiving"] = composite_factor(self.playersOnField[o], FACTOR_OPTIONS["receiving"])
        tc_o["rushing"] = composite_factor(self.playersOnField[o], FACTOR_OPTIONS["rushing"])
        tc_d["passRushing"] = composite_factor(self.playersOnField[d], FACTOR_OPTIONS["passRushing"])
        tc_d["runStopping"] = composite_factor(self.playersOnField[d], FACTOR_OPTIONS["runStopping"])
        tc_d["passCoverage"] = composite_factor(self.playersOnField[d], FACTOR_OPTIONS["passCoverage"])
        tc_d["tackling"] = composite_factor(self.playersOnField[d], FACTOR_OPTIONS["tackling"])
        tc_o["passBlocking"], tc_o["runBlocking"] = blocking_factors(self.playersOnField[o])

    def updatePlayersOnField(self, play_type: str) -> None:
        if play_type in ("starters", "startersFake"):
            formation = formations.NORMAL[0]
        elif play_type in ("run", "pass"):
            formation = self.rng.choice(formations.NORMAL)
        elif play_type in ("extraPoint", "fieldGoal"):
            formation = self.rng.choice(formations.FIELD_GOAL)
        elif play_type == "punt":
            formation = self.rng.choice(formations.PUNT)
        elif play_type == "kickoff":
            formation = self.rng.choice(formations.KICKOFF)
        else:
            raise RuntimeError(f'Unknown playType "{play_type}"')

        for i, side in enumerate(("off", "def")):
            t = self.o if i == 0 else self.d
            used: set[str] = set()
            self.playersOnField[t] = {}
            for pos, num in formation[side].items():
                fatigue_mod = 0.75 if pos == "WR" else 1.0
                depth = self.team[t].depth.get(pos, [])
                players: list[PlayerGameSim] = []
                if pos in FATIGUE_POS:
                    for p in depth:
                        if len(players) >= num:
                            break
                        if p.injured or p.id in used:
                            continue
                        if self.rng.random() < fatigue_mod * fatigue(p.stat["energy"], p.injured):
                            players.append(p)
                            used.add(p.id)
                else:
                    for p in depth:
                        if len(players) >= num:
                            break
                        if not p.injured and p.id not in used:
                            players.append(p)
                            used.add(p.id)
                if len(players) < num:
                    for p in depth:
                        if len(players) >= num:
                            break
                        if not p.injured and p.id not in used:
                            players.append(p)
                            used.add(p.id)
                    if len(players) < num:
                        for p in depth:
                            if len(players) >= num:
                                break
                            if p.id not in used:
                                players.append(p)
                                used.add(p.id)
                self.playersOnField[t][pos] = players
                for p in players:
                    if play_type == "starters":
                        self.recordStat(t, p, "gs")
                    self.recordStat(t, p, "gp")
        self.updateTeamCompositeRatings()

    def doTimeout(self, t: int, to_stop_clock: bool) -> None:
        if self.timeouts[t] <= 0:
            return
        self.timeouts[t] -= 1
        self.logTimeouts()
        self.isClockRunning = False
        self.playByPlay.logEvent({"type": "timeout", "offense": t == self.o, "numLeft": self.timeouts[t], "t": t,
                                  "toStopClock": to_stop_clock})

    def doKickoff(self, onside: bool = False) -> float:
        rng = self.rng
        self.updatePlayersOnField("kickoff")
        kicker = self.getTopPlayerOnField(self.o, "K")
        dt = 0.0
        if onside:
            dt = rng.rand_int(2, 5)
            kick_to = rng.rand_int(40, 55)
            self.currentPlay.addEvent({"type": "onsideKick", "p": kicker, "kickTo": kick_to})
            self.playByPlay.logEvent({"type": "onsideKick", "names": [kicker.name], "t": self.o})
            success = rng.random() < 0.1 * self.settings.onside_recovery_factor
            p = self.pickPlayer(self.o) if success else self.pickPlayer(self.d)
            yds = 0
            if not success:
                self.currentPlay.addEvent({"type": "possessionChange", "subtype": "kickoff", "yds": 0})
                raw = 100 if rng.random() < 0.003 else rng.rand_int(0, 5)
                yds = self.currentPlay.boundedYds(raw)
                dt += abs(yds) / 8
            info = self.currentPlay.addEvent({"type": "onsideKickRecovery", "success": success, "kicker": kicker,
                                              "p": p, "yds": yds})
            if info["td"]:
                self.currentPlay.addEvent({"type": "krTD", "p": p})
            else:
                self.doTackle(None)
            self.playByPlay.logEvent({"type": "onsideKickRecovery", "names": [p.name], "success": success,
                                      "t": self.currentPlay.state["current"].o, "td": info["td"]})
        else:
            adjust = js_round(30 * (0.7 - kicker.composite["kickingPower"])) if kicker.composite["kickingPower"] < 0.7 else 0
            if self.awaitingAfterSafety:
                rng_lo, rng_hi = 15 + adjust, 35 + adjust
            else:
                rng_lo, rng_hi = -15 + adjust, 5 + adjust
                tb = self.settings.scrimmage_touchback_kickoff
                if tb > 25:
                    max_min = -15 + (tb - 25) if tb < 35 else -5 + ((tb - 35) * 2) / 5
                    max_min = min(10, js_round(max_min))
                    if max_min > rng_lo:
                        diff = max_min - rng_lo
                        rng_lo += diff
                        rng_hi += diff
            returner = self.getTopPlayerOnField(self.d, "KR")
            kick_to = rng.rand_int(rng_lo, rng_hi)
            touchback = kick_to <= -10 or (kick_to < 0 and rng.random() < 0.8)
            self.currentPlay.addEvent({"type": "k", "p": kicker, "kickTo": kick_to})
            self.playByPlay.logEvent({"type": "kickoff", "names": [kicker.name], "t": self.o, "touchback": touchback,
                                      "yds": kick_to})
            self.currentPlay.addEvent({"type": "possessionChange", "subtype": "kickoff", "yds": 0})
            if touchback:
                self.currentPlay.addEvent({"type": "touchbackKick", "p": kicker})
            else:
                raw = self.outcome.kickoff_return_yds(self, returner)
                length = self.currentPlay.boundedYds(raw)
                dt = abs(length) / 8
                self.checkPenalties("kickoffReturn", ball_carrier=returner, play_yds=length)
                info = self.currentPlay.addEvent({"type": "kr", "p": returner, "yds": length})
                if info["td"]:
                    self.currentPlay.addEvent({"type": "krTD", "p": returner})
                else:
                    self.doTackle(None)
                self.playByPlay.logEvent({"type": "kickoffReturn", "names": [returner.name],
                                          "t": self.currentPlay.state["current"].o, "td": info["td"], "yds": length})
        return dt

    def doPunt(self) -> float:
        rng = self.rng
        self.playByPlay.logEvent({"type": "puntTeam", "t": self.o})
        self.updatePlayersOnField("punt")
        if self.checkPenalties("beforeSnap"):
            return 0.0
        punter = self.getTopPlayerOnField(self.o, "P")
        returner = self.getTopPlayerOnField(self.d, "PR")
        max_distance = 109 - self.scrimmage
        distance = self.outcome.punt_distance(self, punter)
        distance_bounded = min(distance, max_distance)
        dt = float(rng.rand_int(5, 9))
        self.checkPenalties("punt")
        info = self.currentPlay.addEvent({"type": "p", "p": punter, "yds": distance_bounded})
        self.playByPlay.logEvent({"type": "punt", "names": [punter.name], "t": self.o, "touchback": info["touchback"],
                                  "yds": distance})
        self.currentPlay.addEvent({"type": "possessionChange", "subtype": "punt", "yds": 0})
        if info["touchback"]:
            self.currentPlay.addEvent({"type": "touchbackPunt", "p": punter})
        else:
            max_return = 100 - self.currentPlay.state["current"].scrimmage
            raw = self.outcome.punt_return_yds(self, returner)
            length = int(bound(raw, 0, max_return))
            dt += abs(length) / 8
            self.checkPenalties("puntReturn", ball_carrier=returner, play_yds=length)
            r = self.currentPlay.addEvent({"type": "pr", "p": returner, "yds": length})
            if r["td"]:
                self.currentPlay.addEvent({"type": "prTD", "p": returner})
            else:
                self.doTackle(None)
            self.playByPlay.logEvent({"type": "puntReturn", "names": [returner.name],
                                      "t": self.currentPlay.state["current"].o, "td": r["td"], "yds": length})
        return dt

    def doFieldGoal(self, play_type: str) -> float:
        self.updatePlayersOnField("fieldGoal")
        extra_point = play_type == "extraPoint"
        distance = 100 - self.scrimmage + FIELD_GOAL_DISTANCE_YARDS_ADDED_FROM_SCRIMMAGE
        kicker = self.getTopPlayerOnField(self.o, "K")
        self.playByPlay.logEvent({"type": "extraPointAttempt" if extra_point else "fieldGoalAttempt",
                                  "names": [kicker.name], "t": self.o, "yds": distance})
        if not extra_point and self.checkPenalties("beforeSnap"):
            return 0.0
        made = self.rng.random() < self.probMadeFieldGoal(kicker)
        dt = 0 if extra_point else self.rng.rand_int(4, 6)
        if not extra_point:
            self.checkPenalties("fieldGoal")
        if extra_point:
            self.currentPlay.addEvent({"type": "xp", "p": kicker, "made": made, "distance": distance})
        else:
            self.currentPlay.addEvent({"type": "fg", "p": kicker, "made": made, "distance": distance,
                                       "late": play_type == "fieldGoalLate"})
            if not made:
                self.currentPlay.addEvent({"type": "possessionChange", "subtype": "missedFg", "yds": -7})
        self.playByPlay.logEvent({"type": "extraPoint" if extra_point else "fieldGoal", "made": made,
                                  "names": [kicker.name], "t": self.o, "yds": distance})
        return float(dt)

    def doTwoPointConversion(self) -> float:
        def pts() -> int:
            cur = self.currentPlay.state["current"]
            return cur.pts[0] + cur.pts[1]

        team = self.o
        self.currentPlay.addEvent({"type": "twoPointConversion", "t": team})
        self.twoPointConversionTeam = team
        self.playByPlay.logEvent({"type": "twoPointConversion", "t": team})
        before = pts()
        if self.rng.random() < 0.5 * self.settings.pass_factor:
            self.doPass()
        else:
            self.doRun()
        made = pts() > before
        self.currentPlay.addEvent({"type": "twoPointConversionDone", "t": team, "made": made})
        if not made:
            self.playByPlay.logEvent({"type": "twoPointConversionFailed", "t": team})
        self.twoPointConversionTeam = None
        return 0.0

    def probFumble(self, p: PlayerGameSim) -> float:
        return self.outcome.prob_fumble(self, p)

    def doFumble(self, p_fumbled: PlayerGameSim, spot_yds: int) -> float:
        rng = self.rng
        cur = self.currentPlay.state["current"]
        o, d = cur.o, cur.d
        p_forced = self.pickPlayer(d, "tackling")
        self.currentPlay.addEvent({"type": "fmb", "pFumbled": p_fumbled, "pForced": p_forced, "yds": spot_yds})
        self.playByPlay.logEvent({"type": "fumble", "names": [p_fumbled.name, p_forced.name], "t": o})
        lost = rng.random() > 0.5
        t_rec = d if lost else o
        p_rec = self.pickPlayer(t_rec)
        raw = js_round(rng.trunc_gauss(2, 6, -5, 15))
        if rng.random() < (0.01 if lost else 0.0001):
            raw += rng.rand_int(0, 109)
        if lost:
            self.currentPlay.addEvent({"type": "possessionChange", "subtype": "turnover", "yds": 0})
        yds = self.currentPlay.boundedYds(raw)
        info = self.currentPlay.addEvent({"type": "fmbRec", "pFumbled": p_fumbled, "pRecovered": p_rec, "yds": yds,
                                          "lost": lost})
        dt = abs(yds) / 6
        fumble_again = False
        if not info["touchback"]:
            if info["td"]:
                self.currentPlay.addEvent({"type": "fmbTD", "p": p_rec})
            elif info["safety"]:
                self.doSafety()
            elif rng.random() < self.probFumble(p_rec):
                fumble_again = True
            else:
                self.doTackle(None)
        self.playByPlay.logEvent({"type": "fumbleRecovery", "lost": lost, "names": [p_rec.name],
                                  "safety": info["safety"], "t": t_rec, "td": info["td"],
                                  "touchback": info["touchback"], "twoPointConversionTeam": self.twoPointConversionTeam,
                                  "yds": yds, "ydsBefore": spot_yds})
        if fumble_again:
            dt += self.doFumble(p_rec, 0)
        return dt

    def doInterception(self, qb: PlayerGameSim, yds_pass: int, p: PlayerGameSim) -> float:
        rng = self.rng
        self.playByPlay.logEvent({"type": "interception", "names": [p.name], "t": self.currentPlay.state["current"].d,
                                  "twoPointConversionTeam": self.twoPointConversionTeam, "yds": yds_pass})
        self.currentPlay.addEvent({"type": "possessionChange", "subtype": "turnover", "yds": yds_pass})
        raw = js_round(rng.trunc_gauss(4, 6, -5, 15))
        if rng.random() < 0.075:
            raw += rng.rand_int(0, 109)
        yds = self.currentPlay.boundedYds(raw)
        dt = abs(yds) / 8
        info = self.currentPlay.addEvent({"type": "int", "qb": qb, "defender": p, "ydsReturn": yds})
        fumble = False
        if info["touchback"]:
            self.currentPlay.addEvent({"type": "touchbackInt"})
        elif info["td"]:
            self.currentPlay.addEvent({"type": "intTD", "p": p})
        elif rng.random() < self.probFumble(p):
            fumble = True
        else:
            self.doTackle(None)
        self.playByPlay.logEvent({"type": "interceptionReturn", "names": [p.name],
                                  "t": self.currentPlay.state["current"].o, "td": info["td"],
                                  "touchback": info["touchback"], "twoPointConversionTeam": self.twoPointConversionTeam,
                                  "yds": yds})
        if fumble:
            dt += self.doFumble(p, 0)
        return dt

    def doSafety(self, p: PlayerGameSim | None = None) -> None:
        if p is None:
            p = self.pickPlayer(self.d, "passRushing" if self.rng.random() < 0.5 else "runStopping")
        self.currentPlay.addEvent({"type": "defSft", "p": p})

    def doSack(self, qb: PlayerGameSim, pbw: dict) -> float:
        d = self.currentPlay.state["initial"].d
        p = self.pickPlayer(d, "passRushing", None, 5)
        yds = self.currentPlay.boundedYds(self.rng.rand_int(-1, -12))
        ol = None
        if p in (self.playersOnField[d].get("DL") or []) or p in (self.playersOnField[d].get("LB") or []):
            losers = [bp for bp, info in pbw.items() if not info["won"] and info["type"] == "OL"]
            if losers:
                ol = self.rng.choice(losers)
        info = self.currentPlay.addEvent({"type": "sk", "qb": qb, "p": p, "ol": ol, "yds": yds})
        if info["safety"]:
            self.doSafety(p)
        self.playByPlay.logEvent({"type": "sack", "names": [qb.name, p.name], "safety": info["safety"],
                                  "t": self.currentPlay.state["initial"].o, "yds": yds})
        return float(self.rng.rand_int(3, 8))

    def doPass(self) -> float:
        o = self.o
        self.updatePlayersOnField("pass")
        if self.checkPenalties("beforeSnap"):
            return 0.0
        plan = self.outcome.pass_play(self)
        qb = self.getTopPlayerOnField(o, "QB")
        self.currentPlay.addEvent({"type": "dropback", "pbw": plan.pbw})
        self.playByPlay.logEvent({"type": "dropback", "names": [qb.name], "t": o})
        dt = float(self.rng.rand_int(2, 6))

        if plan.qb_fumble:
            return dt + self.doFumble(qb, self.currentPlay.boundedYds(plan.qb_fumble_yds))
        if plan.sack:
            return self.doSack(qb, plan.pbw)
        if plan.scramble:
            return self.doRun(True)

        target, defender = plan.target, plan.defender
        yds = self.currentPlay.boundedYds(plan.yds)
        self.checkPenalties("pass", ball_carrier=target, play_yds=yds,
                            incomplete_pass=not plan.complete and not plan.interception)
        self.currentPlay.addEvent({"type": "pss", "qb": qb, "target": target})

        if plan.interception:
            dt += self.doInterception(qb, yds, defender)
        else:
            dt += abs(yds) / 20
            if plan.complete:
                info = self.currentPlay.addEvent({"type": "pssCmp", "qb": qb, "target": target, "yds": yds})
                complete_event = {"type": "passComplete", "names": [qb.name, target.name], "safety": info["safety"],
                                  "t": o, "td": info["td"], "twoPointConversionTeam": self.twoPointConversionTeam,
                                  "yds": yds, **{f"x_{k}": v for k, v in plan.extra.items()}}
                if not info["td"] and not info["safety"] and self.rng.random() < self.probFumble(target):
                    self.playByPlay.logEvent(complete_event)
                    return dt + self.doFumble(target, 0)
                if info["td"]:
                    self.currentPlay.addEvent({"type": "pssTD", "qb": qb, "target": target})
                if info["safety"]:
                    self.doSafety()
                self.playByPlay.logEvent(complete_event)
                if not info["td"] and not info["safety"]:
                    self.doTackle(yds)
            else:
                self.currentPlay.addEvent({"type": "pssInc", "defender": defender if self.rng.random() < 0.28 else None})
                self.playByPlay.logEvent({"type": "passIncomplete", "names": [qb.name, target.name], "t": o, "yds": yds,
                                          **{f"x_{k}": v for k, v in plan.extra.items()}})
        return dt

    def doRun(self, qb_scramble: bool = False) -> float:
        o = self.o
        if qb_scramble:
            positions = ["QB"]
        else:
            positions = ["RB"]
            r = self.rng.random()
            rbs = self.playersOnField[o].get("RB") or []
            if r < 0.5 or not rbs:
                positions.append("QB")
            elif r < 0.57:
                positions.append("WR")
            self.updatePlayersOnField("run")
            if self.checkPenalties("beforeSnap"):
                return 0.0

        plan = self.outcome.run_play(self, positions, qb_scramble)
        p = plan.carrier
        qb = self.getTopPlayerOnField(o, "QB")
        self.playByPlay.logEvent({"type": "handoff", "t": o, "names": [qb.name] if p is qb else [qb.name, p.name],
                                  "scramble": qb_scramble})
        yds = self.currentPlay.boundedYds(plan.yds)
        dt = self.rng.rand_int(2, 4) + abs(yds) / 10
        self.checkPenalties("run", ball_carrier=p, play_yds=yds)
        info = self.currentPlay.addEvent({"type": "rus", "p": p, "yds": yds, "rbw": plan.rbw})
        if info["td"]:
            self.currentPlay.addEvent({"type": "rusTD", "p": p})
        elif info["safety"]:
            self.doSafety()
        else:
            self.doTackle(yds)
        self.playByPlay.logEvent({"type": "run", "names": [p.name], "safety": info["safety"], "t": o, "td": info["td"],
                                  "twoPointConversionTeam": self.twoPointConversionTeam, "yds": yds,
                                  "scramble": qb_scramble, **{f"x_{k}": v for k, v in plan.extra.items()}})
        if not info["td"] and not info["safety"] and self.rng.random() < self.probFumble(p):
            self.awaitingAfterTouchdown = False
            return dt + self.doFumble(p, 0)
        return dt

    def doKneel(self) -> float:
        o = self.o
        self.updatePlayersOnField("run")
        qb = self.getTopPlayerOnField(o, "QB")
        yds = self.rng.rand_int(0, -YARDS_NEEDED_TO_KNEEL)
        self.currentPlay.addEvent({"type": "kneel", "p": qb, "yds": yds})
        self.playByPlay.logEvent({"type": "kneel", "names": [qb.name], "t": o, "yds": yds})
        return float(self.rng.rand_int(ESTIMATED_SECONDS_PER_KNEEL - 1, ESTIMATED_SECONDS_PER_KNEEL))

    def checkPenalties(self, play_type: str, ball_carrier: PlayerGameSim | None = None,
                       incomplete_pass: bool = False, play_yds: int = 0) -> bool:
        rng = self.rng
        cur = self.currentPlay.state["current"]
        if cur.twoPointConversionTeam is not None:
            return False
        max_allowed = 2 - self.currentPlay.numPenalties
        if max_allowed <= 0:
            return False
        rate = self.settings.foul_rate_factor
        called = [pen for pen in PENALTIES_BY_PLAY_TYPE[play_type] if rng.random() < pen.prob_per_play * rate]
        if not called:
            return False
        if len(called) > max_allowed:
            rng.shuffle(called)
            called = called[:max_allowed]
        scrimmage = cur.scrimmage
        infos = []
        for pen in called:
            spot = None
            t = cur.o if pen.side == "offense" else cur.d
            is_return = play_type in ("kickoffReturn", "puntReturn")
            tack_on = (pen.tack_on and play_yds > 0 and not incomplete_pass) or (is_return and pen.side == "defense")
            if (pen.spot_foul or (is_return and pen.side == "offense")) and not tack_on:
                if pen.side == "offense" and play_yds > 0:
                    spot = rng.rand_int(1, play_yds)
                    if spot + scrimmage < 1:
                        spot = 1 - scrimmage
                elif pen.side == "defense" and not is_return:
                    spot = rng.rand_int(0, play_yds)
                if spot is not None and play_type == "kickoffReturn" and spot + scrimmage <= 10:
                    spot += rng.rand_int(10, play_yds)
            elif tack_on:
                spot = play_yds
            if spot is not None and spot + scrimmage > 99:
                spot = 99 - scrimmage
            infos.append((pen, spot, t, tack_on))

        for pen, spot, t, tack_on in infos:
            p = None
            if pen.pos_odds is not None:
                on_field = list(self.playersOnField[t].keys())
                positions = [pos for pos in on_field if pos in pen.pos_odds]
                if positions:
                    pos = rng.choice(positions, lambda x: pen.pos_odds[x])
                    players = self.playersOnField[t].get(pos)
                    if players:
                        p = rng.choice(players)
                if p is None:
                    p = self.pickPlayer(t)
            self.currentPlay.addEvent({"type": "penalty", "p": p, "automaticFirstDown": pen.automatic_first_down,
                                       "name": pen.name, "nameKo": pen.name_ko, "penYds": pen.yds, "spotYds": spot,
                                       "t": t, "tackOn": tack_on})
            self.playByPlay.logEvent({"type": "flag"})
        return True

    def updatePlayingTime(self, possession_time: float) -> None:
        self.recordStat(self.o, None, "timePos", possession_time)
        for t in TEAM_NUMS:
            on_field = set()
            for players in self.playersOnField[t].values():
                for p in players:
                    on_field.add(p.id)
                    p.stat["min"] += possession_time
                    self.team[t].stat["min"] += possession_time
                    p.stat["courtTime"] += possession_time
                    p.stat["energy"] = max(0.0, p.stat["energy"] - 0.08 * (1 - p.composite["endurance"]))
                    p.stat["snaps"] += 1
            for p in self.team[t].players:
                if p.id not in on_field:
                    p.stat["benchTime"] += possession_time
                    p.stat["energy"] = min(1.0, p.stat["energy"] + 0.5)

    def injuries(self) -> None:
        base = self.settings.base_injury_rate
        if base == 0:
            return
        for t in TEAM_NUMS:
            on_field = {p for players in self.playersOnField[t].values() for p in players}
            for p in sorted(on_field, key=lambda x: x.id):
                rate = get_injury_rate(base, p.age, p.playing_through_injury)
                if self.rng.random() < rate:
                    if p.pos in FEWER_INJURIES_POS and self.rng.random() < 0.5:
                        continue
                    p.injured = True
                    p.new_injury = True
                    self.playByPlay.logEvent({"type": "injury", "injuredPID": p.id, "names": [f"{p.pos} {p.name}"],
                                              "t": t})

    def pickPlayer(self, t: int, rating: str | None = None, positions: Iterable[str] | None = None,
                   power: float = 1.0) -> PlayerGameSim:
        players = get_players(self.playersOnField[t], list(positions) if positions is not None else POSITIONS)
        if rating is None:
            return self.rng.choice(players)
        return self.rng.choice(players, lambda p: (p.composite[rating] * fatigue(p.stat["energy"], p.injured)) ** power)

    def recordStat(self, t: int, p: PlayerGameSim | None, s: str, amt: float = 1, remove: bool = False) -> None:
        signed = -amt if remove else amt
        is_lng = s.endswith("Lng")
        if p is not None:
            if s in ("gs", "gp"):
                p.stat[s] = 1
            elif is_lng:
                p.stat[s] = self.lngTracker.log("player", p.id, s, amt, remove)
            else:
                p.stat[s] += signed
        if s not in ("gs", "gp"):
            ts = self.team[t].stat
            if is_lng:
                ts[s] = self.lngTracker.log("team", t, s, amt, remove)
            else:
                ts[s] += signed
            if p is None and s == "pts":
                ts["ptsQtrs"][-1] += signed
