"""전술 3계층 모델 (PRD F4): 팀 철학 → 상황별 성향 → 주간 게임플랜.

값은 모두 "리그 평균 대비 배율·이동"으로 저장한다. 기본값(모두 1.0·0)은 nflverse 실측 리그 평균 콜 분포와 같다.
엔진은 이 값으로 실측 분포를 기울여 팀의 **정체성 분포**를 만든다 (`tactics.apply`).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace

LEAGUE_PASS_RATE = 0.57          # 일반 상황(승률 10–90%) 리그 패스 비율 — 런 비율 슬라이더 기준점
RUN_STYLES = ("mixed", "inside_zone", "outside_zone", "gap")
PRESS = ("low", "normal", "high")
TENDENCY_BREAK = ("off", "normal", "aggressive")
FOURTH_DOWN = ("conservative", "standard", "aggressive")
TWO_POINT = ("never", "chart", "aggressive")
COVERS = ("C0", "C1", "2M", "C2", "C3", "QTR")
MAN_COVERS = ("C0", "C1", "2M")
PERSONNEL = ("11", "12", "21", "13", "22", "10")
DOWN_DIST = ("1", "2s", "2m", "2l", "3s", "3m", "3l", "4")   # F4-3 버킷 (1st는 거리 구분 없음)
FIELD = ("backed", "own", "opp", "red", "goal")


@dataclass
class OffenseTactics:
    run_share: float | None = None        # 런 비율 목표 (0.3–0.7). None이면 리그 평균
    short: float = 1.0                    # 패스 깊이 배율
    mid: float = 1.0
    deep: float = 1.0
    run_style: str = "mixed"
    play_action: float = 1.0              # 낮음 0.5 / 보통 1.0 / 높음 1.6
    screen: float = 1.0
    tempo: str = "normal"                 # slow | normal | no_huddle
    personnel: dict = field(default_factory=dict)   # 퍼스넬별 배율
    qb_style: float = 0.0                 # −1 안전 우선 ↔ +1 공격적

    def pass_shift(self) -> float:
        """런 비율 목표 → 패스 확률 로짓 이동."""
        if self.run_share is None:
            return 0.0
        p = min(max(1 - self.run_share, 0.05), 0.95)
        return math.log(p / (1 - p)) - math.log(LEAGUE_PASS_RATE / (1 - LEAGUE_PASS_RATE))


@dataclass
class DefenseTactics:
    coverage: dict = field(default_factory=dict)    # 쉘별 배율 (C0 … QTR)
    man_zone: float = 0.0                 # −1 존 위주 ↔ +1 맨 위주
    blitz: float = 1.0                    # 블리츠 오즈 배율
    box: float = 0.0                      # −1 가벼운 박스 ↔ +1 무거운 박스
    press: str = "normal"


@dataclass
class Predictability:
    lam: float = 0.35                     # 상대 대응 강도 (0–0.7)
    tendency_break: str = "normal"
    personnel_mix: bool = False           # 퍼스넬 섞기


@dataclass
class GameManagement:
    fourth_down: str = "standard"
    two_point: str = "chart"


@dataclass
class Tactics:
    offense: OffenseTactics = field(default_factory=OffenseTactics)
    defense: DefenseTactics = field(default_factory=DefenseTactics)
    # 상황별 성향 (F4-3): "3s|opp" 같은 키 → {"pass": 패스 비율 가감(−0.5–0.5), "blitz": 블리츠 배율}
    situational: dict = field(default_factory=dict)
    predictability: Predictability = field(default_factory=Predictability)
    management: GameManagement = field(default_factory=GameManagement)
    name: str = "custom"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Tactics":
        if not d:
            return cls()
        def build(klass, data):
            names = {f.name for f in fields(klass)}
            return klass(**{k: v for k, v in (data or {}).items() if k in names})
        return cls(offense=build(OffenseTactics, d.get("offense")), defense=build(DefenseTactics, d.get("defense")),
                   situational=dict(d.get("situational") or {}),
                   predictability=build(Predictability, d.get("predictability")),
                   management=build(GameManagement, d.get("management")), name=d.get("name", "custom"))

    def merged(self, gameplan: dict | None) -> "Tactics":
        """주간 게임플랜(부분 덮어쓰기)을 합친 이번 경기 전술 (F4-7b)."""
        if not gameplan:
            return self
        out = Tactics.from_dict(self.to_dict())
        for section in ("offense", "defense", "predictability", "management"):
            for k, v in (gameplan.get(section) or {}).items():
                setattr(getattr(out, section), k, v)
        out.situational = {**out.situational, **(gameplan.get("situational") or {})}
        return out

    def validate(self) -> list[str]:
        errs = []
        o, d = self.offense, self.defense
        if o.run_share is not None and not 0.2 <= o.run_share <= 0.8:
            errs.append("런 비율은 0.2–0.8")
        if o.run_style not in RUN_STYLES:
            errs.append(f"러닝 스타일은 {RUN_STYLES}")
        if not 0 <= self.predictability.lam <= 0.7:
            errs.append("상대 대응 강도는 0–0.7")
        if self.predictability.tendency_break not in TENDENCY_BREAK:
            errs.append(f"성향 깨기는 {TENDENCY_BREAK}")
        if not -1 <= d.man_zone <= 1 or not -1 <= d.box <= 1 or not -1 <= o.qb_style <= 1:
            errs.append("맨/존·박스·QB 성향은 −1–1")
        for key in self.situational:
            dd, _, fz = key.partition("|")
            if dd not in DOWN_DIST or (fz and fz not in FIELD):
                errs.append(f"상황 키 {key}: 다운·거리 {DOWN_DIST}, 필드 {FIELD}")
        return errs


# ── 프리셋 (F4-7c) ──────────────────────────────────────────────
def _off(**kw) -> OffenseTactics:
    return OffenseTactics(**kw)


def _def(**kw) -> DefenseTactics:
    return DefenseTactics(**kw)


OFFENSE_PRESETS: dict[str, tuple[str, OffenseTactics]] = {
    "balanced": ("리그 평균", _off()),
    "west_coast": ("웨스트 코스트: 짧은 패스·스크린으로 패스를 런처럼",
                   _off(run_share=0.42, short=1.35, mid=1.0, deep=0.7, screen=1.3)),
    "air_raid": ("에어 레이드: 4–5 리시버, 패스 위주",
                 _off(run_share=0.32, short=1.2, mid=1.15, deep=1.15, play_action=0.6,
                      personnel={"10": 3.0, "11": 1.3, "12": 0.4, "21": 0.3, "13": 0.2, "22": 0.2})),
    "ground_pound": ("그라운드 앤 파운드: 갭 런·헤비 퍼스넬·플레이액션",
                     _off(run_share=0.58, run_style="gap", play_action=1.4, deep=0.9,
                          personnel={"12": 1.6, "21": 1.8, "22": 2.5, "13": 1.5, "11": 0.75, "10": 0.3})),
    "wide_zone": ("샌너핸 와이드 존: 아웃사이드 존 + 부트레그 플레이액션",
                  _off(run_share=0.5, run_style="outside_zone", play_action=1.6, deep=1.1, short=0.9,
                       personnel={"21": 2.0, "12": 1.3, "11": 0.9})),
    "vertical": ("버티컬: 딥 패스로 수비를 늘린다",
                 _off(run_share=0.42, deep=1.7, mid=1.1, short=0.8, play_action=1.2, qb_style=0.5)),
}
DEFENSE_PRESETS: dict[str, tuple[str, DefenseTactics]] = {
    "balanced": ("리그 평균", _def()),
    "tampa2": ("탬파 2: 존 2-하이, 블리츠 적게", _def(coverage={"C2": 2.2, "QTR": 1.2, "C1": 0.6, "C0": 0.4},
                                                  man_zone=-0.5, blitz=0.65, box=-0.3)),
    "seattle_c3": ("시애틀 Cover 3: 싱글하이 존, 8인 박스", _def(coverage={"C3": 2.2, "C1": 1.1, "C2": 0.6},
                                                             man_zone=-0.2, blitz=0.9, box=0.5)),
    "man_blitz": ("맨 블리츠: Cover 1·0 + 압박", _def(coverage={"C1": 2.0, "C0": 2.5, "2M": 1.3, "C2": 0.6},
                                                 man_zone=0.7, blitz=2.0, box=0.2, press="high")),
    "quarters": ("쿼터스: 2-하이 매치 존, 빅 플레이 억제", _def(coverage={"QTR": 2.4, "C2": 1.2, "C1": 0.6, "C0": 0.4},
                                                          man_zone=-0.3, blitz=0.8, box=-0.4)),
}


def preset(offense: str = "balanced", defense: str = "balanced") -> Tactics:
    return Tactics(offense=replace(OFFENSE_PRESETS[offense][1]), defense=replace(DEFENSE_PRESETS[defense][1]),
                   name=f"{offense}+{defense}")


# ── 실측 성향 → 전술 (AI 팀 기본값, 사용자 팀 시작값) ─────────────
def from_tendencies(team: dict, league: dict) -> Tactics:
    """2025 실측 성향(team_tendencies.json의 한 팀)을 리그 평균 대비 배율로 바꾼다."""
    to, lo = team["offense"], league["offense"]
    td, ld = team["defense"], league["defense"]

    def ratio(a, b, lo_=0.4, hi=2.5):
        return round(min(max(a / b, lo_), hi), 3) if b else 1.0

    outside = to["outside_run"] - lo["outside_run"]
    style = "outside_zone" if outside > 0.08 else ("gap" if outside < -0.08 else "mixed")
    pers = {k: ratio(to["personnel"].get(k, 0.0) + 1e-3, v + 1e-3, 0.2, 4.0) for k, v in lo["personnel"].items()}
    off = OffenseTactics(run_share=round(1 - (LEAGUE_PASS_RATE + to["proe"] - lo["proe"]), 3),
                         deep=ratio(to["deep_rate"], lo["deep_rate"]), screen=ratio(to["screen_rate"], lo["screen_rate"]),
                         play_action=ratio(to["pa_rate"], lo["pa_rate"]), run_style=style, personnel=pers)
    cov = {k: ratio(td["coverage"].get(k, 0.0) + 1e-3, v + 1e-3, 0.2, 4.0) for k, v in ld["coverage"].items()}
    odds = lambda p: p / (1 - p)  # noqa: E731
    box = ((td["heavy_box"] - td["light_box"]) - (ld["heavy_box"] - ld["light_box"])) * 3
    dfn = DefenseTactics(coverage=cov, blitz=round(odds(td["blitz_rate"]) / odds(ld["blitz_rate"]), 3),
                         box=round(min(max(box, -1.0), 1.0), 3))
    return Tactics(offense=off, defense=dfn, name="2025 실측 성향")
