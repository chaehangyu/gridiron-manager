"""한 플레이의 이벤트 누적과 상태 전이, 페널티 판정 (원본 Play.ts, getBestPenaltyResult.ts).

이벤트는 원본과 같은 이름의 `type` 키를 가진 dict다.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .game import GameSim

SCRIMMAGE_KICKOFF = 35
SCRIMMAGE_KICKOFF_SAFETY = 20
SCRIMMAGE_EXTRA_POINT = 85
SCRIMMAGE_TWO_POINT_CONVERSION = 98
SCRIMMAGE_TOUCHBACK = 20

UPDATE_SPOT_OF_ENFORCEMENT = {
    "possessionChange", "k", "onsideKick", "touchbackKick", "kr", "onsideKickRecovery", "p", "touchbackPunt",
    "touchbackInt", "pr", "rus", "kneel", "sk", "pssCmp", "int", "fg", "xp", "fmb", "fmbRec",
}
TOUCHDOWN_IS_POSSIBLE = {"kr", "onsideKickRecovery", "pr", "rus", "pssCmp", "int", "fmbRec"}
SAFETY_IS_POSSIBLE = {"rus", "pssCmp", "sk"}

STATE_KEYS = [
    "down", "toGo", "scrimmage", "o", "d", "isClockRunning", "awaitingKickoff", "awaitingAfterSafety",
    "awaitingAfterTouchdown", "currentDrive", "overtimeState", "playUntimedPossession",
]


class State:
    def __init__(self, src: Any, *, downIncremented: bool, firstDownLine: int | None, madeLateFG: int | None,
                 missedXP: int | None, numPossessionChanges: int, pts: list[int],
                 twoPointConversionTeam: int | None, turnoverOnDowns: bool) -> None:
        self.down = src.down
        self.toGo = src.toGo
        self.scrimmage = src.scrimmage
        self.o = src.o
        self.d = src.d
        self.isClockRunning = src.isClockRunning
        self.awaitingKickoff = src.awaitingKickoff
        self.awaitingAfterSafety = src.awaitingAfterSafety
        self.awaitingAfterTouchdown = src.awaitingAfterTouchdown
        self.currentDrive = src.currentDrive
        self.overtimeState = src.overtimeState
        self.overtimeType = src.overtimeType
        self.playUntimedPossession = src.playUntimedPossession

        self.downIncremented = downIncremented
        self.firstDownLine = firstDownLine if firstDownLine is not None else self.scrimmage + self.toGo
        self.madeLateFG = madeLateFG
        self.missedXP = missedXP
        self.numPossessionChanges = numPossessionChanges
        self.pts = pts
        self.twoPointConversionTeam = twoPointConversionTeam
        self.turnoverOnDowns = turnoverOnDowns

    def clone(self) -> "State":
        return State(self, downIncremented=self.downIncremented, firstDownLine=self.firstDownLine,
                     madeLateFG=self.madeLateFG, missedXP=self.missedXP,
                     numPossessionChanges=self.numPossessionChanges, pts=list(self.pts),
                     twoPointConversionTeam=self.twoPointConversionTeam, turnoverOnDowns=self.turnoverOnDowns)

    def incrementDown(self) -> None:
        if not self.downIncremented:
            self.down += 1
            self.downIncremented = True

    def newFirstDown(self) -> None:
        self.down = 1
        self.toGo = min(10, 100 - self.scrimmage)
        self.firstDownLine = self.scrimmage + self.toGo

    def possessionChange(self) -> None:
        if self.overtimeState == "firstPossession":
            self.overtimeState = "secondPossession"
        elif self.overtimeState == "secondPossession":
            self.overtimeState = "bothTeamsPossessed"
        self.scrimmage = 100 - self.scrimmage
        self.o = 0 if self.o == 1 else 1
        self.d = 0 if self.o == 1 else 1
        self.newFirstDown()
        self.isClockRunning = False
        self.numPossessionChanges += 1


def get_pts(event: dict, two_point_conversion: bool) -> int | None:
    t = event["type"]
    if t.endswith("TD"):
        return 2 if two_point_conversion else 6
    if t == "xp" and event["made"]:
        return 1
    if t == "fg" and event["made"]:
        return 3
    if t == "defSft":
        return 2
    return None


class Play:
    def __init__(self, game: "GameSim") -> None:
        self.g = game
        self.events: list[dict] = []
        initial = State(game, downIncremented=False, firstDownLine=None, numPossessionChanges=0, madeLateFG=None,
                        missedXP=None, pts=[game.team[0].stat["pts"], game.team[1].stat["pts"]],
                        twoPointConversionTeam=None, turnoverOnDowns=False)
        self.state = {"initial": initial, "current": initial.clone()}
        self.penaltyRollbacks: list[dict] = []
        self.spotOfEnforcementIndexes: list[int] = []
        self.cleanHandsChangeOfPossessionIndexes: list[int] = []

    # ── 유틸 ──────────────────────────────────────────────
    def boundedYds(self, yds: int) -> int:
        scrimmage = self.state["current"].scrimmage
        yds_td = 100 - scrimmage
        yds_safety = -scrimmage
        if yds > yds_td:
            return yds_td
        if yds < yds_safety:
            return yds_safety
        return yds

    @property
    def numPenalties(self) -> int:
        return len(self.penaltyRollbacks)

    # ── 통계 변화 ─────────────────────────────────────────
    def getStatChanges(self, event: dict, state: State) -> list[tuple]:
        sc: list[tuple] = []
        et = event["type"]
        if et == "twoPointConversionDone":
            sc.append((event["t"], None, "tpa"))
            if event["made"]:
                sc.append((event["t"], None, "tp"))
        elif not state.awaitingAfterTouchdown or et == "xp":
            if et == "penalty":
                actual = event["spotYds"] if (event["name"] == "Pass interference" and event["penYds"] == 0) else event["penYds"]
                sc += [(event["t"], event["p"], "pen"), (event["t"], event["p"], "penYds", actual)]
            if et == "k":
                sc += [(state.o, event["p"], "ko"), (state.o, event["p"], "koYds", 65 - event["kickTo"])]
            elif et == "kr":
                sc += [(state.o, event["p"], "kr"), (state.o, event["p"], "krYds", event["yds"]),
                       (state.o, event["p"], "krLng", event["yds"])]
            elif et == "onsideKick":
                sc.append((state.o, event["p"], "ok"))
            elif et == "onsideKickRecovery":
                if event["success"]:
                    sc.append((state.o, event["kicker"], "okRec"))
                else:
                    sc += [(state.o, event["p"], "kr"), (state.o, event["p"], "krYds", event["yds"]),
                           (state.o, event["p"], "krLng", event["yds"])]
            elif et == "krTD":
                sc.append((state.o, event["p"], "krTD"))
            elif et == "p":
                sc += [(state.o, event["p"], "pnt"), (state.o, event["p"], "pntYds", event["yds"]),
                       (state.o, event["p"], "pntLng", event["yds"])]
                kick_to = state.scrimmage + event["yds"]
                if 80 < kick_to < 100:
                    sc.append((state.o, event["p"], "pntIn20"))
            elif et == "touchbackPunt":
                sc.append((state.d, event["p"], "pntTB"))
            elif et == "touchbackKick":
                sc.append((state.d, event["p"], "koTB"))
            elif et == "pr":
                sc += [(state.o, event["p"], "pr"), (state.o, event["p"], "prYds", event["yds"]),
                       (state.o, event["p"], "prLng", event["yds"])]
            elif et == "prTD":
                sc.append((state.o, event["p"], "prTD"))
            elif et == "rus":
                sc += [(state.o, event["p"], "rus"), (state.o, event["p"], "rusYds", event["yds"]),
                       (state.o, event["p"], "rusLng", event["yds"])]
                if event.get("rbw"):
                    for p, info in event["rbw"].items():
                        sc.append((state.o, p, "rba"))
                        if info["won"]:
                            sc.append((state.o, p, "rbw"))
            elif et == "rusTD":
                sc.append((state.o, event["p"], "rusTD"))
            elif et == "kneel":
                sc += [(state.o, event["p"], "rus"), (state.o, event["p"], "rusYds", event["yds"]),
                       (state.o, event["p"], "rusLng", event["yds"])]
            elif et == "sk":
                sc += [(state.o, event["qb"], "pssSk"), (state.o, event["qb"], "pssSkYds", abs(event["yds"])),
                       (state.d, event["p"], "defSk"), (state.d, event["p"], "defTckSolo"),
                       (state.d, event["p"], "defTckLoss")]
                if event.get("ol") is not None:
                    sc.append((state.o, event["ol"], "skAlw"))
            elif et == "pss":
                sc += [(state.o, event["qb"], "pss"), (state.o, event["target"], "tgt")]
            elif et == "pssCmp":
                sc += [(state.o, event["qb"], "pssCmp"), (state.o, event["qb"], "pssYds", event["yds"]),
                       (state.o, event["qb"], "pssLng", event["yds"]), (state.o, event["target"], "rec"),
                       (state.o, event["target"], "recYds", event["yds"]),
                       (state.o, event["target"], "recLng", event["yds"])]
            elif et == "pssInc":
                if event.get("defender") is not None:
                    sc.append((state.d, event["defender"], "defPssDef"))
            elif et == "pssTD":
                sc += [(state.o, event["qb"], "pssTD"), (state.o, event["target"], "recTD")]
            elif et == "int":
                sc += [(state.d, event["qb"], "pssInt"), (state.o, event["defender"], "defPssDef"),
                       (state.o, event["defender"], "defInt")]
                if not state.scrimmage + event["ydsReturn"] <= 0:
                    sc += [(state.o, event["defender"], "defIntYds", event["ydsReturn"]),
                           (state.o, event["defender"], "defIntLng", event["ydsReturn"])]
            elif et == "intTD":
                sc.append((state.o, event["p"], "defIntTD"))
            elif et in ("fg", "xp"):
                if et == "xp":
                    att, made = "xpa", "xp"
                elif event["distance"] < 20:
                    att, made = "fga0", "fg0"
                elif event["distance"] < 30:
                    att, made = "fga20", "fg20"
                elif event["distance"] < 40:
                    att, made = "fga30", "fg30"
                elif event["distance"] < 50:
                    att, made = "fga40", "fg40"
                else:
                    att, made = "fga50", "fg50"
                sc.append((state.o, event["p"], att))
                if event["made"]:
                    sc.append((state.o, event["p"], made))
                    if et != "xp":
                        sc.append((state.o, event["p"], "fgLng", event["distance"]))
            elif et == "fmb":
                sc += [(state.o, event["pFumbled"], "fmb"), (state.d, event["pForced"], "defFmbFrc")]
            elif et == "fmbRec":
                sc.append((state.o, event["pRecovered"], "defFmbRec"))
                if event["lost"]:
                    sc.append((state.d, event["pFumbled"], "fmbLost"))
                sc += [(state.o, event["pRecovered"], "defFmbYds", event["yds"]),
                       (state.o, event["pRecovered"], "defFmbLng", event["yds"])]
            elif et == "fmbTD":
                sc.append((state.o, event["p"], "defFmbTD"))
            elif et == "defSft":
                sc.append((state.d, event["p"], "defSft"))
            elif et == "tck":
                for tackler in event["tacklers"]:
                    sc.append((state.d, tackler, "defTckSolo" if len(event["tacklers"]) == 1 else "defTckAst"))
                    if event["loss"]:
                        sc.append((state.d, tackler, "defTckLoss"))
            elif et == "dropback":
                for p, info in event["pbw"].items():
                    sc.append((state.o, p, "pba"))
                    if info["won"]:
                        sc.append((state.o, p, "pbw"))
            elif et == "newDrive":
                sc += [(state.o, None, "drives"), (state.o, None, "totStartYds", state.scrimmage)]

        pts = get_pts(event, state.twoPointConversionTeam is not None)
        if pts is not None:
            scoring_team = state.d if et == "defSft" else state.o
            sc.append((scoring_team, None, "pts", pts))
        return sc

    def getPenaltyInfo(self, state: State, event: dict) -> dict:
        side = "off" if state.o == event["t"] else "def"
        pen_yds_signed = -event["penYds"] if side == "off" else event["penYds"]
        return {
            "halfDistanceToGoal": side == "off" and state.scrimmage / 2 < event["penYds"],
            "onDefense": event["t"] == state.d,
            "penYdsSigned": pen_yds_signed,
            "placeOnOne": side == "def" and state.scrimmage + pen_yds_signed > 99,
        }

    # ── 상태 전이 ─────────────────────────────────────────
    def updateState(self, state: State, event: dict) -> dict:
        rng = self.g.rng
        et = event["type"]

        def after_kickoff() -> None:
            if state.overtimeState == "initialKickoff":
                state.overtimeState = "firstPossession"

        if et == "penalty":
            if event["spotYds"] is not None and not event["tackOn"]:
                state.scrimmage += event["spotYds"]
            info = self.getPenaltyInfo(state, event)
            if info["placeOnOne"]:
                state.scrimmage = 99
            elif info["halfDistanceToGoal"]:
                state.scrimmage = js_round(state.scrimmage / 2)
            else:
                state.scrimmage += info["penYdsSigned"]
            if event["automaticFirstDown"] or state.numPossessionChanges > 0:
                state.newFirstDown()
            state.isClockRunning = False
        elif et == "possessionChange":
            state.scrimmage += event["yds"]
            state.possessionChange()
            if event["subtype"] == "missedFg" and state.scrimmage < SCRIMMAGE_TOUCHBACK:
                state.scrimmage = SCRIMMAGE_TOUCHBACK
            if event["subtype"] == "kickoff":
                state.awaitingKickoff = None
                state.awaitingAfterSafety = False
                after_kickoff()
            if event["subtype"] != "turnover":
                state.currentDrive = None
        elif et in ("k", "onsideKick"):
            state.scrimmage = 100 - event["kickTo"]
        elif et == "touchbackKick":
            state.scrimmage = self.g.settings.scrimmage_touchback_kickoff
        elif et == "kr":
            state.scrimmage += event["yds"]
        elif et == "onsideKickRecovery":
            state.scrimmage += event["yds"]
            state.awaitingKickoff = None
            state.awaitingAfterSafety = False
            state.newFirstDown()
        elif et == "p":
            state.scrimmage += event["yds"]
        elif et in ("touchbackPunt", "touchbackInt"):
            state.scrimmage = SCRIMMAGE_TOUCHBACK
        elif et == "pr":
            state.scrimmage += event["yds"]
        elif et == "rus":
            state.incrementDown()
            state.scrimmage += event["yds"]
            state.isClockRunning = rng.random() < 0.85
        elif et == "kneel":
            state.incrementDown()
            state.scrimmage += event["yds"]
            state.isClockRunning = False
        elif et == "sk":
            state.scrimmage += event["yds"]
            state.isClockRunning = rng.random() < 0.98
        elif et == "dropback":
            state.incrementDown()
        elif et == "pssCmp":
            state.scrimmage += event["yds"]
            state.isClockRunning = rng.random() < 0.75
        elif et == "pssInc":
            state.isClockRunning = False
        elif et == "int":
            state.scrimmage += event["ydsReturn"]
        elif et in ("fg", "xp"):
            if et == "xp" or event["made"]:
                state.awaitingKickoff = self.state["initial"].o
                state.scrimmage = SCRIMMAGE_KICKOFF
            if et == "xp" and not event["made"]:
                state.missedXP = state.o
            if et == "fg" and event["made"] and event["late"]:
                state.madeLateFG = state.o
            state.awaitingAfterTouchdown = False
            state.isClockRunning = False
        elif et == "twoPointConversion":
            state.twoPointConversionTeam = event["t"]
        elif et == "twoPointConversionDone":
            state.o = event["t"]
            state.d = 1 if state.o == 0 else 0
            state.twoPointConversionTeam = None
            state.awaitingKickoff = event["t"]
            state.scrimmage = SCRIMMAGE_KICKOFF
            state.awaitingAfterTouchdown = False
            state.isClockRunning = False
        elif et == "defSft":
            state.awaitingKickoff = state.o
            state.scrimmage = SCRIMMAGE_KICKOFF_SAFETY
            state.awaitingAfterSafety = True
            state.isClockRunning = False
        elif et == "fmb":
            state.scrimmage += event["yds"]
        elif et == "fmbRec":
            state.scrimmage += event["yds"]
            state.isClockRunning = False if event["lost"] else rng.random() > 0.05
        elif et == "newDrive":
            state.currentDrive = state.o

        if et.endswith("TD"):
            state.awaitingAfterTouchdown = True
            state.isClockRunning = False
            state.down = 1

        td = state.scrimmage >= 100 and et in TOUCHDOWN_IS_POSSIBLE
        touchback = False
        if state.scrimmage <= 0:
            if et == "int" or (et == "fmbRec" and event["lost"]):
                touchback = True
        elif state.scrimmage >= 100 and et == "p":
            touchback = True

        safety = False
        if state.scrimmage <= 0:
            safety = et in SAFETY_IS_POSSIBLE or (et == "fmbRec" and not event["lost"])

        if et == "fmbRec" and state.scrimmage <= 0:
            if event["lost"]:
                state.scrimmage = SCRIMMAGE_TOUCHBACK
                touchback = True
            else:
                safety = True
            state.isClockRunning = False

        if state.overtimeState is not None:
            if et.endswith("TD"):
                if state.overtimeState in ("initialKickoff", "firstPossession") and state.overtimeType != "bothPossess":
                    state.overtimeState = "over"
            elif et == "defSft":
                if state.overtimeState in ("initialKickoff", "firstPossession"):
                    state.overtimeState = "over"
            elif et in ("fg", "xp") and not event["made"]:
                if state.pts[state.o] < state.pts[state.d]:
                    state.overtimeState = "over"

        pts = get_pts(event, state.twoPointConversionTeam is not None)
        if pts is not None:
            t = state.d if et == "defSft" else state.o
            state.pts[t] += pts
            if state.overtimeState == "secondPossession" or (
                state.overtimeState is not None and state.overtimeType == "suddenDeath"
            ):
                t2 = 1 if t == 0 else 0
                if state.pts[t] > state.pts[t2]:
                    state.overtimeState = "over"

        return {"safety": safety, "td": td, "touchback": touchback}

    def checkDownAtEndOfPlay(self, state: State) -> None:
        if state.scrimmage >= 100 or state.scrimmage <= 0:
            return
        if state.awaitingAfterTouchdown or state.awaitingAfterSafety:
            return
        if state.numPossessionChanges > 0:
            state.newFirstDown()
            return
        state.toGo = state.firstDownLine - state.scrimmage
        if state.toGo <= 0:
            state.newFirstDown()
        state.turnoverOnDowns = state.down > 4
        if state.turnoverOnDowns:
            state.possessionChange()

    def addEvent(self, event: dict) -> dict:
        stat_changes = self.getStatChanges(event, self.state["current"])
        if event["type"] == "penalty":
            if event["tackOn"]:
                rtype = "tackOn"
            elif event["spotYds"] is not None:
                rtype = "spotOfEnforcement"
            else:
                rtype = "cleanHandsChangeOfPossession"
            self.penaltyRollbacks.append({"type": rtype, "indexEvent": len(self.events)})
            self.events.append({"event": event, "statChanges": stat_changes,
                                "penaltyInfo": self.getPenaltyInfo(self.state["current"], event)})
            return {"safety": False, "td": False, "touchback": False}

        for change in stat_changes:
            self.g.recordStat(*change)
        self.events.append({"event": event, "statChanges": stat_changes})

        offense_before = self.state["current"].o
        info = self.updateState(self.state["current"], event)
        offense_after = self.state["current"].o
        if offense_after != offense_before:
            clean = all(e["event"]["type"] != "penalty" or e["event"]["t"] != offense_after for e in self.events)
            if clean:
                self.cleanHandsChangeOfPossessionIndexes.append(len(self.events) - 1)
        if event["type"] in UPDATE_SPOT_OF_ENFORCEMENT:
            self.spotOfEnforcementIndexes.append(len(self.events) - 1)
        return info

    # ── 페널티 판정 ───────────────────────────────────────
    def adjudicatePenalties(self, time_expired_at_end_of_half: bool) -> None:
        penalties = [e for e in self.events if e["event"]["type"] == "penalty"]
        if not penalties:
            return
        possession_change_indexes = [i for i, e in enumerate(self.events) if e["event"]["type"] == "possessionChange"]

        options = None
        choosing_team = None
        offset_status = None
        if len(penalties) == 1:
            options = [["decline"], ["accept"]]
            choosing_team = 1 if penalties[0]["event"]["t"] == 0 else 0
        elif len(penalties) == 2:
            if penalties[0]["event"]["t"] == penalties[1]["event"]["t"]:
                options = [["decline", "decline"], ["decline", "accept"], ["accept", "decline"]]
                choosing_team = 1 if penalties[0]["event"]["t"] == 0 else 0
            else:
                p5 = [p for p in penalties if p["event"]["penYds"] == 5]
                p15 = [p for p in penalties if p["event"]["penYds"] == 15 or p["event"]["name"] == "Pass interference"]
                if len(p5) == 1 and len(p15) == 1:
                    choosing_team = 1 if p15[0]["event"]["t"] == 0 else 0
                    options = [["accept", "decline"]] if p15[0] is penalties[0] else [["decline", "accept"]]
                    offset_status = "overrule"
                else:
                    choosing_team = 0
                    npc = [len([idx for idx in possession_change_indexes if idx <= self.penaltyRollbacks[i]["indexEvent"]])
                           for i in range(2)]
                    if npc[0] == npc[1] and npc[0] > 0:
                        options = [["offset", "offset"]]
                        offset_status = "offset"
                    elif npc[0] > 0 or npc[1] > 0:
                        options = [["accept", "decline"]] if npc[0] > npc[1] else [["decline", "accept"]]
                        offset_status = "overrule"
                    else:
                        options = [["offset", "offset"]]
                        offset_status = "offset"
        else:
            raise RuntimeError("Not supported")

        results = []
        for decisions in options:
            index_accept = decisions.index("accept") if "accept" in decisions else -1
            index_offset = decisions.index("offset") if "offset" in decisions else -1
            penalty = penalties[index_accept] if index_accept >= 0 else None
            offsetting = decisions[0] == "offset"
            sub_results = []
            if index_accept < 0 and index_offset < 0:
                sub_results.append({"indexEvent": None, "state": self.state["current"], "tackOn": False})
            else:
                rollback = self.penaltyRollbacks[index_accept] if index_accept >= 0 else self.penaltyRollbacks[index_offset]
                if rollback["type"] in ("cleanHandsChangeOfPossession", "spotOfEnforcement") or offsetting:
                    valid = [i for i in self.spotOfEnforcementIndexes if i < rollback["indexEvent"]]
                    sub_results.append({"indexEvent": max(valid) if valid else -1,
                                        "state": self.state["initial"].clone(), "tackOn": False})
                elif rollback["type"] == "tackOn":
                    sub_results.append({"indexEvent": -1, "state": self.state["initial"].clone(), "tackOn": False})
                    idx = self.spotOfEnforcementIndexes[-1] if self.spotOfEnforcementIndexes else -1
                    if idx > 0:
                        sub_results.append({"indexEvent": idx, "state": self.state["initial"].clone(), "tackOn": True})

                for sr in sub_results:
                    st = sr["state"]
                    if sr["indexEvent"] is not None and sr["indexEvent"] >= 0:
                        for i in range(sr["indexEvent"] + 1):
                            ev = self.events[i]["event"]
                            if ev["type"] != "penalty":
                                self.updateState(st, ev)
                    if offset_status == "offset":
                        st.isClockRunning = False
                    else:
                        self.updateState(st, penalty["event"])
                        if penalty["penaltyInfo"]["onDefense"] and time_expired_at_end_of_half:
                            st.playUntimedPossession = True
                    self.checkDownAtEndOfPlay(st)

            stat_changes = penalty["statChanges"] if (penalty is not None and offset_status != "offset") else []
            for sr in sub_results:
                results.append({"indexAccept": index_accept, "decisions": decisions, "statChanges": stat_changes, **sr})

        game_can_end = len(self.g.team[0].stat["ptsQtrs"]) >= self.g.num_periods
        result = get_best_penalty_result(results, self.state["initial"], choosing_team,
                                         time_expired_at_end_of_half, game_can_end, self.g.rng)

        if len(result["decisions"]) > 1:
            self.g.playByPlay.logEvent({"type": "penaltyCount", "count": len(result["decisions"]),
                                        "offsetStatus": offset_status})
        for kind in ("decline", "accept"):
            for i, pen in enumerate(penalties):
                if result["decisions"][i] != kind:
                    continue
                yds = pen["event"]["penYds"]
                spot_foul = False
                if pen["event"]["spotYds"] is not None:
                    if yds == 0:
                        yds = pen["event"]["spotYds"]
                    else:
                        spot_foul = True
                self.g.playByPlay.logEvent({
                    "type": "penalty", "automaticFirstDown": pen["event"]["automaticFirstDown"],
                    "decision": kind, "halfDistanceToGoal": pen["penaltyInfo"]["halfDistanceToGoal"],
                    "names": [pen["event"]["p"].name] if pen["event"]["p"] is not None else [],
                    "offsetStatus": offset_status, "penaltyName": pen["event"]["name"],
                    "penaltyNameKo": pen["event"].get("nameKo", pen["event"]["name"]),
                    "possessionAfter": result["state"].o, "placeOnOne": pen["penaltyInfo"]["placeOnOne"],
                    "scrimmageAfter": result["state"].scrimmage, "spotFoul": spot_foul, "t": pen["event"]["t"],
                    "tackOn": result["tackOn"], "yds": yds,
                })

        self.state["current"] = result["state"]

        if result["indexAccept"] >= 0 or offset_status == "offset":
            changes = list(result["statChanges"])
            for i, e in enumerate(self.events):
                if e["event"]["type"] == "penalty":
                    continue
                if result["indexEvent"] is None or i > result["indexEvent"]:
                    for c in e["statChanges"]:
                        c = list(c)
                        if len(c) < 4:
                            c.append(1)
                        if len(c) < 5:
                            c.append(True)
                        else:
                            c[4] = True
                        changes.append(tuple(c))
            for c in changes:
                self.g.recordStat(*c)
            if any((c[2] == "pts" and c[1] is None) or c[2].startswith("fga") for c in changes):
                self.g.playByPlay.removeLastScore()

    def commit(self, time_expired_at_end_of_half: bool) -> None:
        self.checkDownAtEndOfPlay(self.state["current"])
        self.adjudicatePenalties(time_expired_at_end_of_half)
        if self.state["current"].turnoverOnDowns:
            self.g.playByPlay.logEvent({"type": "turnoverOnDowns", "t": self.state["current"].d})
        for key in STATE_KEYS:
            setattr(self.g, key, getattr(self.state["current"], key))


def js_round(x: float) -> int:
    """JavaScript Math.round (0.5는 올림)."""
    import math
    return math.floor(x + 0.5)


def get_best_penalty_result(results: list[dict], initial: State, t: int, time_expired_at_end_of_half: bool,
                            game_can_end_at_end_of_period: bool, rng) -> dict:
    """선택하는 팀 관점에서 가장 유리한 결과를 여러 기준 순서로 고른다."""
    if len(results) == 1:
        return results[0]
    t2 = 1 if t == 0 else 0
    scores = []
    for r in results:
        st: State = r["state"]
        scored = [st.pts[i] - initial.pts[i] for i in (0, 1)]
        overtime_score = 0
        if st.overtimeState == "over":
            if st.pts[t] > st.pts[t2]:
                overtime_score = 1
            elif st.pts[t2] < st.pts[t]:  # 원본 그대로 (사실상 도달하지 않음)
                overtime_score = -1
        td_score = 0
        if scored[t] in (6, 2):
            td_score = scored[t]
        elif scored[t2] in (-6, -2):
            td_score = -scored[t2]
        missed_xp = -1 if st.missedXP == t else (1 if st.missedXP == t2 else 0)
        made_late_fg = 1 if st.madeLateFG == t else (-1 if st.madeLateFG == t2 else 0)
        untimed = 0
        if time_expired_at_end_of_half:
            points_down = st.pts[t2] - st.pts[t]
            if (st.o == t and game_can_end_at_end_of_period and 0 <= points_down <= 8) or (
                not game_can_end_at_end_of_period and scored[t] == 0
            ):
                untimed = 1
        cop = 1 if (st.o == t and initial.o != t) else (-1 if (st.o == t2 and initial.o != t2) else 0)
        first_down = 0
        if st.o == t and initial.o == t and st.down == 1 and initial.down > 1 and st.scrimmage >= initial.scrimmage:
            first_down = 1
        elif st.o == t2 and initial.o == t2 and st.down == 1 and initial.down > 1 and st.scrimmage >= initial.scrimmage:
            first_down = -1
        any_score = scored[t] if scored[t] > 0 else (-scored[t2] if scored[t2] > 0 else 0)
        fourth_long = 0
        if st.down == 4 and (st.scrimmage <= 35 or st.toGo > 2):
            fourth_long = -1 if st.o == t else 1
        field_pos = st.scrimmage if st.o == t else (-st.scrimmage if st.o == t2 else 0)
        down = -st.down if st.o == t else (st.down if st.o == t2 else 0)
        to_go = -st.toGo if st.o == t else (st.toGo if st.o == t2 else 0)
        scores.append([overtime_score, td_score, missed_xp, made_late_fg, untimed, cop, first_down, any_score,
                       fourth_long, field_pos, down, to_go])
    best = max(scores)
    best_key = json.dumps(best)
    candidates = [i for i, s in enumerate(scores) if json.dumps(s) == best_key]
    return results[rng.choice(candidates)]
