"""예측 가능성 장치의 단순 모형 (엔진 설계서 §6.7).

공격은 런/패스 두 종류, 수비는 콜 4개(기본, 런 스톱, 블리츠, 라이트 박스)만 있는 모형이다.
수비는 공격의 런/패스 성향을 디리클레 방식으로 학습하고, 기대 EPA가 낮은 콜을 소프트맥스로 고른다.
공격 효율표는 measure_effects.py의 실측값(E1, E3, E11)을 반올림해 썼다.

확인하려는 것:
1. 읽힘 효과(g_pass)가 없으면 "항상 패스"가 최선이 된다 → 읽힘 효과가 필요하다.
2. 읽힘 효과를 실측 크기로 넣으면 최적 런 비율이 현실 범위(약 30%)로 들어온다.
3. 극단 성향 팀은 경기 후반에 효율이 떨어진다 (상대가 학습했기 때문).

사용법: python tools/research/predictability_toy.py
"""
import numpy as np

CALLS = ["base", "run_stop", "blitz", "light"]
EPA = {"run": np.array([-0.08, -0.14, -0.06, -0.05]), "pass": np.array([0.09, 0.10, 0.04, 0.06])}
DEF_IDENTITY = np.array([0.55, 0.15, 0.20, 0.10])  # 수비 전술 슬라이더가 정한 기본 콜 비율
NEUTRAL_PASS = 0.55


def game(rng, run_rate, lam, g_pass, g_run=0.03, tau=0.02, kappa=20, plays=60):
    alpha = np.array([kappa * (1 - NEUTRAL_PASS), kappa * NEUTRAL_PASS])  # 사전 믿음 [런, 패스]
    total, halves = 0.0, [0.0, 0.0]
    for i in range(plays):
        b_run = alpha[0] / alpha.sum()
        b_pass = 1 - b_run
        adj_pass = -g_pass * max(0.0, b_pass - NEUTRAL_PASS)
        adj_run = -g_run * max(0.0, b_run - (1 - NEUTRAL_PASS))
        ev = b_run * (EPA["run"] + adj_run) + b_pass * (EPA["pass"] + adj_pass)
        best = np.exp(-(ev - ev.min()) / tau)
        best /= best.sum()
        call = rng.choice(len(CALLS), p=(1 - lam) * DEF_IDENTITY + lam * best)
        kind = "run" if rng.random() < run_rate else "pass"
        r = EPA[kind][call] + (adj_run if kind == "run" else adj_pass)
        total += r
        halves[i >= plays // 2] += r
        alpha[0 if kind == "run" else 1] += 1
    return total / plays, halves[0] / (plays / 2), halves[1] / (plays / 2)


def main():
    rng = np.random.default_rng(11)
    rates = (0.0, 0.15, 0.30, 0.40, 0.50, 0.65, 0.80)
    print("런 비율별 공격 EPA/플레이 (각 1,500경기)")
    for g in (0.0, 0.23, 0.35):
        for lam in (0.0, 0.35):
            cells = [f"{rr:.2f}:{np.mean([game(rng, rr, lam, g)[0] for _ in range(1500)]):+.3f}" for rr in rates]
            print(f"g_pass={g:.2f} λ={lam:.2f} | " + "  ".join(cells))
    print("\n전반 vs 후반 (g_pass=0.23, λ=0.35, 각 3,000경기)")
    for rr in (0.0, 0.40, 0.80):
        res = np.array([game(rng, rr, 0.35, 0.23) for _ in range(3000)])
        print(f"런 {rr:.2f}: 전반 {res[:, 1].mean():+.3f}  후반 {res[:, 2].mean():+.3f}")


if __name__ == "__main__":
    main()
