"""주간 훈련 (PRD F11-1·F11-2, ENGINE_DESIGN §7).

주 초점 1개 + 보조 초점 1개(효과 절반) + 강도. 효과는 그 주 경기 준비값(`prep`)과 숙련도로 나타난다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .familiarity import DOMAINS

FOCUSES = ("familiarity", "opponent", "redzone", "third_down", "two_minute", "special", "recovery")
FOCUS_LABELS = {"familiarity": "전술 숙련", "opponent": "상대 분석", "redzone": "레드존", "third_down": "3rd down",
                "two_minute": "2분 드릴", "special": "특수팀", "recovery": "회복"}
INTENSITY = {"light": (0.4, 10.0), "normal": (1.0, 0.0), "hard": (1.6, -10.0)}   # (효과 배율, 컨디션 변화)
DRILL = 0.06            # 상황 훈련 보너스 (분위수·로짓 이동 단위)


@dataclass
class TrainingPlan:
    main: str = "familiarity:auto"      # "familiarity:<영역>" | "opponent" | ...
    sub: str | None = "opponent"
    intensity: str = "normal"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "TrainingPlan":
        return cls(**d) if d else cls()

    def validate(self) -> list[str]:
        errs = []
        for f in (self.main, self.sub):
            if f is None:
                continue
            kind, _, dom = f.partition(":")
            if kind not in FOCUSES:
                errs.append(f"초점 {f}: {FOCUSES}")
            if kind == "familiarity" and dom not in DOMAINS + ("auto",):
                errs.append(f"숙련 영역 {dom}: {DOMAINS}")
        if self.intensity not in INTENSITY:
            errs.append(f"강도: {tuple(INTENSITY)}")
        return errs


def resolve_auto(domain: str, fam: dict[str, float], used: list[str]) -> str:
    """'auto' 영역 = 지금 전술이 쓰는 영역 중 숙련도가 가장 낮은 곳 (코칭 스태프 권고, F11-1e)."""
    if domain != "auto":
        return domain
    cands = [d for d in used if d in fam] or list(fam)
    return min(cands, key=lambda d: fam[d])


def apply_week(plan: TrainingPlan, fam: dict[str, float], used_domains: list[str]) -> tuple[dict, dict, float]:
    """한 주 훈련 → (새 숙련도, 이번 주 경기 준비값, 컨디션 변화)."""
    mult, cond = INTENSITY[plan.intensity]
    out = dict(fam)
    prep = {"kappa_mult": 1.0, "scout_add": 0.0, "drill": {}}
    for focus, w in ((plan.main, 1.0), (plan.sub, 0.5)):
        if not focus:
            continue
        kind, _, dom = focus.partition(":")
        eff = w * mult
        if kind == "familiarity":
            target = resolve_auto(dom or "auto", out, used_domains)
            for d in out:
                out[d] = min(100.0, out[d] + (5.0 if d == target else 1.5) * eff)
        elif kind == "opponent":
            prep["kappa_mult"] *= 1 + 0.5 * eff
            prep["scout_add"] += 0.1 * eff
        elif kind == "special":
            out["special"] = min(100.0, out["special"] + 5.0 * eff)
            prep["drill"]["special"] = prep["drill"].get("special", 0.0) + DRILL * eff
        elif kind in ("redzone", "third_down", "two_minute"):
            prep["drill"][kind] = prep["drill"].get(kind, 0.0) + DRILL * eff
        elif kind == "recovery":
            cond += 10.0 * w
    return out, prep, cond
