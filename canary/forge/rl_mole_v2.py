"""Catchability-guaranteed RL mole policy v2 (pure NumPy 2-head MLP)."""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_cur_pp = os.environ.get("PYTHONPATH", "")
if _REPO_ROOT not in _cur_pp.split(os.pathsep):
    os.environ["PYTHONPATH"] = f"{_REPO_ROOT}{os.pathsep}{_cur_pp}" if _cur_pp else _REPO_ROOT

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

from canary import rules
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleView,
    _select_frame,
    _select_leak,
)

FEATURE_NAMES = (
    "day",
    "days_since_last_leak",
    "i_am_restricted",
    "n_restricted_colleagues",
    "recent_low_recipient_docs",
    "n_leakable",
    "min_recipient_count",
    "max_recipient_count",
    "newest_doc_age_days",
    "can_leak",
    "wide_doc_share",
    "spread_recipients",
    "has_decoy",
    "has_restricted_peer",
)
SCALE = np.array(
    [21.0, 21.0, 1.0, 10.0, 6.0, 12.0, 20.0, 40.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    dtype=np.float64,
)
N_FEAT = len(FEATURE_NAMES) + 1
N_LEAK = len(LEAK_SELECTORS)
N_FRAME = len(FRAME_SELECTORS)
NONE_LEAK_IDX = LEAK_SELECTORS.index("none")
ACTIVE_LEAK_IDXS = tuple(i for i in range(N_LEAK) if i != NONE_LEAK_IDX)

IDX_RESTRICTED = FEATURE_NAMES.index("i_am_restricted")
IDX_MAX_REC = FEATURE_NAMES.index("max_recipient_count")

INVESTIGATORS = ("grok_tactics", "heuristic", "hinted_heuristic")
ALL_AGENTS = ("solver",) + INVESTIGATORS

MIN_SOLVER_ACC = 0.85
TARGET_SOLVER_ACC = 0.90
VAL_MIN_SOLVER_ACC = 0.88

DEFAULT_NONE_PENALTY = 2.5
DEFAULT_NONE_CAP_GAP = 2.8
EPS = 1e-12

TRAIN_SEEDS = range(160_000, 190_000)
VAL_SEEDS = range(190_000, 190_050)
WS3_HELDOUT_SEEDS = range(200_000, 200_100)
RULES_HELDOUT_SEEDS = range(800_000, 800_100)


def features(view: MoleView) -> np.ndarray:
    n_docs = len(view.docs)
    min_rec = float(view.feature("min_recipient_count"))
    max_rec = float(view.feature("max_recipient_count"))
    wide_doc_share = (
        sum(1 for d in view.docs if d.recipient_count >= 10) / float(n_docs)
        if n_docs > 0
        else 0.0
    )
    spread_recipients = (max_rec - min_rec) / 20.0
    has_decoy = float(view.decoy is not None)
    has_restricted_peer = float(len(view.restricted_peers) > 0)
    raw = [
        float(view.day),
        float(view.days_since_last_leak),
        float(view.i_am_restricted),
        float(view.n_restricted_colleagues),
        float(view.recent_low_recipient_docs),
        float(n_docs),
        min_rec,
        max_rec,
        float(min(view.feature("newest_doc_age_days"), 3)),
        float(view.can_leak),
        wide_doc_share,
        spread_recipients,
        has_decoy,
        has_restricted_peer,
    ]
    normed = np.clip(np.asarray(raw, dtype=np.float64) / SCALE, 0.0, 2.0)
    return np.concatenate([normed, [1.0]])


def is_wide_unrestricted(x: np.ndarray) -> bool:
    max_rec = float(x[IDX_MAX_REC]) * float(SCALE[IDX_MAX_REC])
    restricted = float(x[IDX_RESTRICTED]) >= 0.5
    return (max_rec > 8.0 + 1e-6) and (not restricted)


def _softmax(z: np.ndarray) -> np.ndarray:
    z_shift = z - np.max(z)
    e = np.exp(z_shift)
    return e / np.sum(e)


def _softplus(u: float) -> float:
    if u > 0.0:
        return u + math.log1p(math.exp(-u))
    return math.log1p(math.exp(u))


def _sigmoid(u: float) -> float:
    if u >= 0.0:
        return 1.0 / (1.0 + math.exp(-u))
    eu = math.exp(u)
    return eu / (1.0 + eu)


def init_params(hidden: int = 20, seed: int = 0) -> dict[str, np.ndarray]:
    r = np.random.default_rng(seed)
    return {
        "W1": r.normal(0.0, 0.35, (N_FEAT, hidden)),
        "b1": np.zeros(hidden, dtype=np.float64),
        "Wl": r.normal(0.0, 0.2, (hidden, N_LEAK)),
        "bl": np.zeros(N_LEAK, dtype=np.float64),
        "Wf": r.normal(0.0, 0.2, (hidden, N_FRAME)),
        "bf": np.zeros(N_FRAME, dtype=np.float64),
    }


def warm_start_params(hidden: int = 20, seed: int = 0) -> dict[str, np.ndarray]:
    p = init_params(hidden=hidden, seed=seed)
    i_new = LEAK_SELECTORS.index("newest")
    i_old = LEAK_SELECTORS.index("oldest")
    i_most = LEAK_SELECTORS.index("most_recipients")
    i_few = LEAK_SELECTORS.index("fewest_recipients")
    i_rnd = LEAK_SELECTORS.index("random_seeded")

    f_dec = FRAME_SELECTORS.index("decoy")
    f_mrp = FRAME_SELECTORS.index("most_restricted_peer")
    f_rpr = FRAME_SELECTORS.index("random_peer")
    f_non = FRAME_SELECTORS.index("none")

    p["bl"][i_rnd] = 0.45
    p["bl"][i_most] = 0.45
    p["bl"][i_few] = 0.35
    p["bl"][i_new] = 0.50
    p["bl"][i_old] = 0.05
    p["bl"][NONE_LEAK_IDX] = -2.2

    p["bf"][f_dec] = 0.20
    p["bf"][f_mrp] = 0.25
    p["bf"][f_rpr] = 0.45
    p["bf"][f_non] = -0.20

    if hidden >= 3:
        idx_day = FEATURE_NAMES.index("day")
        idx_low = FEATURE_NAMES.index("recent_low_recipient_docs")
        idx_spread = FEATURE_NAMES.index("spread_recipients")
        idx_rpeer = FEATURE_NAMES.index("has_restricted_peer")

        p["W1"][idx_low, 0] += 2.0
        p["W1"][idx_spread, 0] += 1.2
        p["b1"][0] = -0.25
        p["Wl"][0, i_most] += 1.3
        p["Wl"][0, i_few] -= 1.0

        p["W1"][idx_day, 1] += 2.2
        p["b1"][1] = -0.75
        p["Wl"][1, i_few] -= 0.8
        p["Wl"][1, i_new] += 1.0
        p["Wl"][1, i_rnd] += 0.7

        p["W1"][idx_rpeer, 2] += 1.4
        p["b1"][2] = -0.3
        p["Wf"][2, f_mrp] += 0.8
        p["Wf"][2, f_rpr] += 0.3
    return p


def forward_details(
    p: dict[str, np.ndarray],
    x: np.ndarray,
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
):
    h = np.tanh(x @ p["W1"] + p["b1"])
    zl_raw = h @ p["Wl"] + p["bl"]
    zf = h @ p["Wf"] + p["bf"]
    if is_wide_unrestricted(x):
        active_idx = np.asarray(ACTIVE_LEAK_IDXS, dtype=np.int64)
        za = zl_raw[active_idx]
        m_max = float(np.max(za))
        exp_a = np.exp(za - m_max)
        sum_exp_a = float(np.sum(exp_a))
        lse_active = m_max + math.log(sum_exp_a)
        q_active = exp_a / sum_exp_a
        ceil_logit = lse_active - float(none_cap_gap)
        shifted_none = float(zl_raw[NONE_LEAK_IDX]) - float(none_penalty)
        u = ceil_logit - shifted_none
        zl_eff = zl_raw.copy()
        zl_eff[NONE_LEAK_IDX] = ceil_logit - _softplus(u)
        cap_info = (True, _sigmoid(u), q_active)
    else:
        zl_eff = zl_raw
        cap_info = (False, 1.0, None)
    return h, _softmax(zl_eff), _softmax(zf), cap_info


def forward(
    p: dict[str, np.ndarray],
    x: np.ndarray,
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
):
    h, pl, pf, _ = forward_details(p, x, none_penalty=none_penalty, none_cap_gap=none_cap_gap)
    return h, pl, pf


def _backprop_heads(
    p: dict[str, np.ndarray],
    x: np.ndarray,
    h: np.ndarray,
    dz_l_eff: np.ndarray,
    dz_f: np.ndarray,
    cap_info: tuple,
) -> dict[str, np.ndarray]:
    if cap_info[0]:
        _, sig_u, q_active = cap_info
        active_idx = np.asarray(ACTIVE_LEAK_IDXS, dtype=np.int64)
        g_none = float(dz_l_eff[NONE_LEAK_IDX])
        dz_l = dz_l_eff.copy()
        dz_l[active_idx] = dz_l_eff[active_idx] + g_none * (1.0 - sig_u) * q_active
        dz_l[NONE_LEAK_IDX] = g_none * sig_u
    else:
        dz_l = dz_l_eff
    dh = (p["Wl"] @ dz_l + p["Wf"] @ dz_f) * (1.0 - h * h)
    return {
        "W1": np.outer(x, dh),
        "b1": dh,
        "Wl": np.outer(h, dz_l),
        "bl": dz_l,
        "Wf": np.outer(h, dz_f),
        "bf": dz_f,
    }


def _entropy_eps(pr: np.ndarray) -> float:
    return float(-np.sum(pr * np.log(pr + EPS)))


def _grad_logp(
    p: dict[str, np.ndarray],
    x: np.ndarray,
    li: int,
    fi: int,
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
):
    h, pl, pf, cap_info = forward_details(p, x, none_penalty=none_penalty, none_cap_gap=none_cap_gap)
    dz_l = -pl.copy()
    dz_l[li] += 1.0
    dz_f = -pf.copy()
    dz_f[fi] += 1.0
    grad = _backprop_heads(p, x, h, dz_l, dz_f, cap_info)
    ent = _entropy_eps(pl) + _entropy_eps(pf)
    return grad, ent


def _grad_entropy(
    p: dict[str, np.ndarray],
    x: np.ndarray,
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
) -> dict[str, np.ndarray]:
    h, pl, pf, cap_info = forward_details(p, x, none_penalty=none_penalty, none_cap_gap=none_cap_gap)
    dz = {}
    for key, pr in (("l", pl), ("f", pf)):
        du = -(np.log(pr + EPS) + pr / (pr + EPS))
        dz[key] = pr * (du - float(np.dot(pr, du)))
    return _backprop_heads(p, x, h, dz["l"], dz["f"], cap_info)


def mi_bonus_and_grad(
    p: dict[str, np.ndarray],
    xs: list[np.ndarray],
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
) -> tuple[float, dict[str, np.ndarray]]:
    grad = {k: np.zeros_like(v) for k, v in p.items()}
    m = len(xs)
    if m == 0:
        return 0.0, grad
    cache = [forward_details(p, x, none_penalty=none_penalty, none_cap_gap=none_cap_gap) for x in xs]
    pls = np.stack([c[1] for c in cache], axis=0)
    pfs = np.stack([c[2] for c in cache], axis=0)
    pbar_l = np.mean(pls, axis=0)
    pbar_f = np.mean(pfs, axis=0)

    mi_l = _entropy_eps(pbar_l) - float(np.mean([-np.sum(pls * np.log(pls + EPS), axis=1)]))
    mi_f = _entropy_eps(pbar_f) - float(np.mean([-np.sum(pfs * np.log(pfs + EPS), axis=1)]))

    base_l = np.log(pbar_l + EPS) + pbar_l / (pbar_l + EPS)
    base_f = np.log(pbar_f + EPS) + pbar_f / (pbar_f + EPS)
    inv_m = 1.0 / float(m)

    for x, (h, pl, pf, cap_info) in zip(xs, cache):
        du_l = inv_m * ((np.log(pl + EPS) + pl / (pl + EPS)) - base_l)
        du_f = inv_m * ((np.log(pf + EPS) + pf / (pf + EPS)) - base_f)
        dz_l = pl * (du_l - float(np.dot(pl, du_l)))
        dz_f = pf * (du_f - float(np.dot(pf, du_f)))
        g_step = _backprop_heads(p, x, h, dz_l, dz_f, cap_info)
        for k in grad:
            grad[k] += g_step[k]

    return float(mi_l + mi_f), grad


class RLMoleV2:
    def __init__(
        self,
        params: dict,
        greedy: bool = False,
        trace: list | None = None,
        name: str = "rl_mole_v2",
        none_penalty: float = DEFAULT_NONE_PENALTY,
        none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
    ):
        req = {"W1", "b1", "Wl", "bl", "Wf", "bf"}
        if not isinstance(params, dict) or not req.issubset(params.keys()):
            raise ValueError("missing MLP parameter keys")
        self.p = {k: np.asarray(params[k], dtype=np.float64) for k in ("W1", "b1", "Wl", "bl", "Wf", "bf")}
        hidden = int(self.p["b1"].shape[0])
        if (
            self.p["W1"].shape != (N_FEAT, hidden)
            or self.p["Wl"].shape != (hidden, N_LEAK)
            or self.p["bl"].shape != (N_LEAK,)
            or self.p["Wf"].shape != (hidden, N_FRAME)
            or self.p["bf"].shape != (N_FRAME,)
        ):
            raise ValueError("invalid MLP parameter shapes for RLMoleV2")
        self.greedy = bool(greedy)
        self.trace = trace
        self.name = str(name)
        self.none_penalty = float(none_penalty)
        self.none_cap_gap = float(none_cap_gap)

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        x = features(view)
        _, pl, pf = forward(
            self.p,
            x,
            none_penalty=self.none_penalty,
            none_cap_gap=self.none_cap_gap,
        )
        if self.greedy:
            li = int(np.argmax(pl))
            fi = int(np.argmax(pf))
        else:
            li = int(np.searchsorted(np.cumsum(pl), rng.random() * float(pl.sum())))
            fi = int(np.searchsorted(np.cumsum(pf), rng.random() * float(pf.sum())))
            li = min(li, N_LEAK - 1)
            fi = min(fi, N_FRAME - 1)
        if self.trace is not None:
            self.trace.append((x, li, fi))
        return {
            "leak": _select_leak(LEAK_SELECTORS[li], view, rng),
            "frame": _select_frame(FRAME_SELECTORS[fi], view, rng),
        }

    def to_json(self) -> dict:
        return {
            "kind": "rl_mole_v2",
            "name": self.name,
            "greedy": self.greedy,
            "none_penalty": self.none_penalty,
            "none_cap_gap": self.none_cap_gap,
            "features": list(FEATURE_NAMES),
            "leak_selectors": list(LEAK_SELECTORS),
            "frame_selectors": list(FRAME_SELECTORS),
            "params": {k: v.tolist() for k, v in self.p.items()},
        }

    @classmethod
    def from_json(cls, obj: dict) -> "RLMoleV2":
        if (
            not isinstance(obj, dict)
            or obj.get("kind") != "rl_mole_v2"
            or list(obj.get("features", [])) != list(FEATURE_NAMES)
            or list(obj.get("leak_selectors", [])) != list(LEAK_SELECTORS)
            or list(obj.get("frame_selectors", [])) != list(FRAME_SELECTORS)
        ):
            raise ValueError("not an rl_mole_v2 policy for this vocabulary")
        return cls(
            obj["params"],
            greedy=bool(obj.get("greedy", False)),
            name=str(obj.get("name", "rl_mole_v2")),
            none_penalty=float(obj.get("none_penalty", DEFAULT_NONE_PENALTY)),
            none_cap_gap=float(obj.get("none_cap_gap", DEFAULT_NONE_CAP_GAP)),
        )


def _check_not_judge_seeds(seeds) -> None:
    judge = set(rules.JUDGE_SEEDS)
    if any(int(s) in judge for s in seeds):
        raise ValueError("refusing to run on JUDGE_SEEDS")


def _agent(name: str, tier: str, seed: int):
    from canary.baselines import GrokTactics, Heuristic
    from canary.forge.investigators import HintedHeuristic
    from canary.solver.policy import SolverPolicy

    if name == "solver":
        return SolverPolicy(tier)
    if name == "grok_tactics":
        try:
            return GrokTactics(seed=seed)
        except TypeError:
            return GrokTactics()
    if name == "heuristic":
        return Heuristic(seed=seed)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    raise ValueError(f"unknown investigator: {name}")


def rollout_v2(task) -> dict:
    from canary.env import Env
    from canary.eval import run_episode

    params, tier, seed, agents, greedy, none_penalty, none_cap_gap = task
    out = {}
    for name in agents:
        tr: list = []
        mole = RLMoleV2(
            params,
            greedy=greedy,
            trace=tr,
            none_penalty=none_penalty,
            none_cap_gap=none_cap_gap,
        )
        res = run_episode(Env(tier, seed, mole_strategy=mole), _agent(name, tier, seed))
        out[name] = (float(res.score), bool(res.correct), tr)
    return out


def _default_rollout(task) -> dict:
    from canary.env import Env
    from canary.eval import run_episode

    tier, seed, agents = task
    out = {}
    for name in agents:
        res = run_episode(Env(tier, seed, mole_strategy=DEFAULT_STRATEGY), _agent(name, tier, seed))
        out[name] = (float(res.score), bool(res.correct), [])
    return out


def _v1_rollout(task) -> dict:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.forge.rl_mole import RLMole

    params, tier, seed, agents, greedy = task
    out = {}
    for name in agents:
        tr: list = []
        res = run_episode(
            Env(tier, seed, mole_strategy=RLMole(params, greedy=greedy, trace=tr)),
            _agent(name, tier, seed),
        )
        out[name] = (float(res.score), bool(res.correct), tr)
    return out


def run_batch(
    params: dict[str, np.ndarray],
    tier: str,
    seeds: list[int],
    workers: int = 1,
    agents: tuple[str, ...] = ALL_AGENTS,
    greedy: bool = False,
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
    ex: ProcessPoolExecutor | None = None,
) -> list[dict]:
    _check_not_judge_seeds(seeds)
    p_copy = {k: v.copy() for k, v in params.items()}
    tasks = [(p_copy, tier, int(s), agents, greedy, none_penalty, none_cap_gap) for s in seeds]
    if ex is not None and workers > 1:
        chunk = max(1, len(tasks) // max(1, 2 * workers))
        return list(ex.map(rollout_v2, tasks, chunksize=chunk))
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            chunk = max(1, len(tasks) // max(1, 2 * workers))
            return list(pool.map(rollout_v2, tasks, chunksize=chunk))
    return [rollout_v2(t) for t in tasks]


def summarize(
    rows: list[dict],
    agents: tuple[str, ...] = ALL_AGENTS,
    min_solver_acc: float = MIN_SOLVER_ACC,
) -> dict:
    n = max(1, len(rows))
    s: dict = {
        a: {
            "score": sum(r[a][0] for r in rows) / n,
            "acc": sum(float(r[a][1]) for r in rows) / n,
        }
        for a in agents
    }
    inv = [a for a in agents if a != "solver"]
    if "solver" in s and inv:
        s["min_regret"] = s["solver"]["score"] - max(s[a]["score"] for a in inv)
        s["strongest"] = max(inv, key=lambda a: s[a]["score"])
        s["feasible"] = s["solver"]["acc"] >= min_solver_acc
    return s


class Adam:
    def __init__(
        self,
        params: dict[str, np.ndarray],
        lr: float = 0.025,
        b1: float = 0.9,
        b2: float = 0.999,
        max_grad_norm: float = 5.0,
    ):
        self.lr = lr
        self.b1 = b1
        self.b2 = b2
        self.max_grad_norm = max_grad_norm
        self.t = 0
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}

    def step(self, params: dict[str, np.ndarray], grad: dict[str, np.ndarray]) -> None:
        total_sq = sum(float(np.sum(g * g)) for g in grad.values())
        norm = math.sqrt(total_sq)
        scale = min(1.0, self.max_grad_norm / (norm + 1e-12)) if self.max_grad_norm > 0 else 1.0
        self.t += 1
        for k in params:
            g = grad[k] * scale
            self.m[k] = self.b1 * self.m[k] + (1.0 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1.0 - self.b2) * (g * g)
            mh = self.m[k] / (1.0 - self.b1 ** self.t)
            vh = self.v[k] / (1.0 - self.b2 ** self.t)
            params[k] = params[k] + self.lr * mh / (np.sqrt(vh) + 1e-8)


def train(
    iters: int = 50,
    batch: int = 16,
    workers: int = 1,
    tier: str = "hard",
    lr: float = 0.025,
    hidden: int = 20,
    seed: int = 0,
    ent: float = 0.02,
    beta_mi: float = 0.15,
    lam0: float = 1.5,
    lam_lr: float = 3.0,
    lam_max: float = 12.0,
    target_acc: float = TARGET_SOLVER_ACC,
    val_min_acc: float = VAL_MIN_SOLVER_ACC,
    val_every: int = 10,
    temp: float = 0.08,
    none_penalty: float = DEFAULT_NONE_PENALTY,
    none_cap_gap: float = DEFAULT_NONE_CAP_GAP,
    train_seeds: range | list[int] = TRAIN_SEEDS,
    val_seeds: range | list[int] = VAL_SEEDS,
    out: str | Path = "/tmp/opencode/rl_mole_v2_work",
    best_policy_out: str | Path | None = None,
    log=print,
) -> dict:
    train_pool = list(train_seeds)
    val_list = list(val_seeds)
    _check_not_judge_seeds(train_pool)
    _check_not_judge_seeds(val_list)

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = warm_start_params(hidden=hidden, seed=seed)
    opt = Adam(params, lr=lr)
    lam_catch = float(lam0)
    base: dict[str, float | None] = {a: None for a in ALL_AGENTS}
    curve: list[dict] = []
    val_curve: list[dict] = []
    best_feasible: dict | None = None
    best_fallback: dict | None = None
    best_params: dict[str, np.ndarray] = {k: v.copy() for k, v in params.items()}

    rng = random.Random(seed)
    ex = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None

    def maybe_validate(step_idx: int) -> dict:
        nonlocal best_feasible, best_fallback, best_params
        val_t0 = time.time()
        val_rows = run_batch(
            params,
            tier,
            val_list,
            workers=workers,
            agents=ALL_AGENTS,
            greedy=False,
            none_penalty=none_penalty,
            none_cap_gap=none_cap_gap,
            ex=ex,
        )
        vst = summarize(val_rows, min_solver_acc=MIN_SOLVER_ACC)
        vrow = {
            "iter": step_idx,
            "val_n": len(val_list),
            "val_solver_acc": vst["solver"]["acc"],
            "val_solver_score": vst["solver"]["score"],
            "val_min_regret": vst["min_regret"],
            "val_strongest": vst["strongest"],
            **{f"val_{a}_score": vst[a]["score"] for a in INVESTIGATORS},
            "sec": round(time.time() - val_t0, 2),
        }
        val_curve.append(vrow)
        (out_dir / "val_curve.jsonl").write_text("".join(json.dumps(c) + "\n" for c in val_curve))
        log(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in vrow.items()}))

        cand_key = (vst["min_regret"], vst["solver"]["acc"])
        if vst["solver"]["acc"] >= val_min_acc:
            if best_feasible is None or cand_key > (
                best_feasible["val_min_regret"],
                best_feasible["val_solver_acc"],
            ):
                best_feasible = dict(vrow)
                best_params = {k: v.copy() for k, v in params.items()}
                best_pol = RLMoleV2(
                    best_params,
                    greedy=False,
                    name="rl_mole_v2_best",
                    none_penalty=none_penalty,
                    none_cap_gap=none_cap_gap,
                )
                (out_dir / "policy_best.json").write_text(json.dumps(best_pol.to_json()))

        fb_key = (
            vst["solver"]["acc"] >= MIN_SOLVER_ACC,
            vst["solver"]["acc"],
            vst["min_regret"],
        )
        if best_fallback is None or fb_key > (
            best_fallback["val_solver_acc"] >= MIN_SOLVER_ACC,
            best_fallback["val_solver_acc"],
            best_fallback["val_min_regret"],
        ):
            best_fallback = dict(vrow)
            if best_feasible is None:
                best_params = {k: v.copy() for k, v in params.items()}
                fb_pol = RLMoleV2(
                    best_params,
                    greedy=False,
                    name="rl_mole_v2_best",
                    none_penalty=none_penalty,
                    none_cap_gap=none_cap_gap,
                )
                (out_dir / "policy_best.json").write_text(json.dumps(fb_pol.to_json()))
        return vrow

    try:
        if val_list and iters > 1:
            maybe_validate(-1)

        for it in range(iters):
            t0 = time.time()
            seeds = [train_pool[rng.randrange(len(train_pool))] for _ in range(batch)]
            rows = run_batch(
                params,
                tier,
                seeds,
                workers=workers,
                agents=ALL_AGENTS,
                greedy=False,
                none_penalty=none_penalty,
                none_cap_gap=none_cap_gap,
                ex=ex,
            )
            st = summarize(rows, min_solver_acc=MIN_SOLVER_ACC)
            inv_scores = np.array([st[a]["score"] for a in INVESTIGATORS], dtype=np.float64)
            w = _softmax(inv_scores / temp)

            rets_by_agent: dict[str, list[float]] = {
                a: (
                    [r[a][0] + lam_catch * float(r[a][1]) for r in rows]
                    if a == "solver"
                    else [-r[a][0] for r in rows]
                )
                for a in ALL_AGENTS
            }
            sums_by_agent = {a: float(sum(vals)) for a, vals in rets_by_agent.items()}

            pg_grad = {k: np.zeros_like(v) for k, v in params.items()}
            ent_grad = {k: np.zeros_like(v) for k, v in params.items()}
            batch_xs: list[np.ndarray] = []
            wide_none_count = 0
            wide_total_count = 0

            for ri, r in enumerate(rows):
                for ai, a in enumerate(ALL_AGENTS):
                    _, _, tr = r[a]
                    ret = rets_by_agent[a][ri]
                    coef = 1.0 if a == "solver" else float(w[ai - 1])
                    if len(rows) > 1:
                        b = (sums_by_agent[a] - ret) / float(len(rows) - 1)
                    else:
                        b = base[a] if base[a] is not None else ret
                    adv = coef * (ret - b)
                    for x, li, fi in tr:
                        g_lp, _ = _grad_logp(
                            params,
                            x,
                            li,
                            fi,
                            none_penalty=none_penalty,
                            none_cap_gap=none_cap_gap,
                        )
                        g_e = _grad_entropy(
                            params,
                            x,
                            none_penalty=none_penalty,
                            none_cap_gap=none_cap_gap,
                        )
                        for k in pg_grad:
                            pg_grad[k] += adv * g_lp[k]
                            ent_grad[k] += g_e[k]
                        batch_xs.append(x)
                        if is_wide_unrestricted(x):
                            wide_total_count += 1
                            if li == NONE_LEAK_IDX:
                                wide_none_count += 1

            for a in base:
                rm = float(np.mean(rets_by_agent[a]))
                base[a] = rm if base[a] is None else (0.8 * base[a] + 0.2 * rm)

            mi_val, mi_grad = mi_bonus_and_grad(
                params,
                batch_xs,
                none_penalty=none_penalty,
                none_cap_gap=none_cap_gap,
            )
            n_eps = max(1, len(rows))
            n_steps = max(1, len(batch_xs))
            total_grad = {
                k: (pg_grad[k] / n_eps) + ent * (ent_grad[k] / n_steps) + beta_mi * mi_grad[k]
                for k in params
            }
            opt.step(params, total_grad)

            lam_catch = float(
                np.clip(lam_catch + lam_lr * (target_acc - st["solver"]["acc"]), 0.0, lam_max)
            )
            wide_none_rate = wide_none_count / float(max(1, wide_total_count))
            row = {
                "iter": it,
                "min_regret": st["min_regret"],
                "strongest": st["strongest"],
                "solver_score": st["solver"]["score"],
                "solver_acc": st["solver"]["acc"],
                **{f"{a}_score": st[a]["score"] for a in INVESTIGATORS},
                "lam_catch": lam_catch,
                "mi_nats": mi_val,
                "wide_none_rate": wide_none_rate,
                "steps": len(batch_xs),
                "sec": round(time.time() - t0, 2),
            }
            curve.append(row)
            log(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}))
            (out_dir / "curve.jsonl").write_text("".join(json.dumps(c) + "\n" for c in curve))

            if val_list and ((it + 1) % max(1, val_every) == 0 or it == iters - 1):
                maybe_validate(it)

        final_pol = RLMoleV2(
            params,
            greedy=False,
            name="rl_mole_v2_final",
            none_penalty=none_penalty,
            none_cap_gap=none_cap_gap,
        )
        (out_dir / "policy_final.json").write_text(json.dumps(final_pol.to_json()))

        chosen_pol = RLMoleV2(
            best_params,
            greedy=False,
            name="rl_mole_v2",
            none_penalty=none_penalty,
            none_cap_gap=none_cap_gap,
        )
        (out_dir / "policy_best.json").write_text(json.dumps(chosen_pol.to_json()))
        if best_policy_out is not None:
            bp = Path(best_policy_out)
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text(json.dumps(chosen_pol.to_json()) + "\n")
    finally:
        if ex is not None:
            ex.shutdown()

    return {
        "curve": curve,
        "val_curve": val_curve,
        "params": params,
        "best_params": best_params,
        "best_val": best_feasible if best_feasible is not None else best_fallback,
    }


def boot_ci(xs: list[float], B: int = 2000, seed: int = 0) -> list[float]:
    n = len(xs)
    if n == 0:
        return [0.0, 0.0, 0.0]
    r = random.Random(seed)
    means = sorted(sum(xs[r.randrange(n)] for _ in range(n)) / float(n) for _ in range(B))
    return [
        round(sum(xs) / float(n), 4),
        round(means[int(0.025 * B)], 4),
        round(means[int(0.975 * B)], 4),
    ]


def _empirical_selector_stats(rows: list[dict]) -> dict:
    cl: Counter = Counter()
    cf: Counter = Counter()
    for r in rows:
        for _, li, fi in r["solver"][2]:
            cl[LEAK_SELECTORS[li]] += 1
            cf[FRAME_SELECTORS[fi]] += 1
    tot = sum(cl.values())
    if tot == 0:
        return {
            "total_solver_decisions": 0,
            "H_leak": 0.0,
            "H_frame": 0.0,
            "leak": {},
            "frame": {},
        }
    pl_emp = [v / float(tot) for v in cl.values() if v > 0]
    pf_emp = [v / float(tot) for v in cf.values() if v > 0]
    h_leak = -sum(p * math.log(p) for p in pl_emp)
    h_frame = -sum(p * math.log(p) for p in pf_emp)
    return {
        "total_solver_decisions": tot,
        "H_leak": round(h_leak, 4),
        "H_frame": round(h_frame, 4),
        "leak": {k: round(v / float(tot), 4) for k, v in cl.most_common()},
        "frame": {k: round(v / float(tot), 4) for k, v in cf.most_common()},
    }


def action_diagnostics(
    rows: list[dict],
    policy: RLMoleV2,
) -> dict:
    base_stats = _empirical_selector_stats(rows)
    xs: list[np.ndarray] = []
    cond_hl: list[float] = []
    cond_hf: list[float] = []
    wide_total = 0
    wide_none = 0
    for r in rows:
        for x, li, _ in r["solver"][2]:
            xs.append(x)
            _, pl, pf = forward(
                policy.p,
                x,
                none_penalty=policy.none_penalty,
                none_cap_gap=policy.none_cap_gap,
            )
            cond_hl.append(_entropy_eps(pl))
            cond_hf.append(_entropy_eps(pf))
            if is_wide_unrestricted(x):
                wide_total += 1
                if li == NONE_LEAK_IDX:
                    wide_none += 1
    mi_val, _ = mi_bonus_and_grad(
        policy.p,
        xs,
        none_penalty=policy.none_penalty,
        none_cap_gap=policy.none_cap_gap,
    )
    return {
        **base_stats,
        "policy_H_leak_cond": round(float(np.mean(cond_hl)) if cond_hl else 0.0, 4),
        "policy_H_frame_cond": round(float(np.mean(cond_hf)) if cond_hf else 0.0, 4),
        "wide_unrestricted_none_rate": round(wide_none / float(max(1, wide_total)), 4),
        "mutual_info_nats": round(mi_val, 4),
    }


def _summarize_policy_rows(
    rows: list[dict],
    default_solver_score: float | None = None,
    min_solver_acc: float = MIN_SOLVER_ACC,
    B: int = 2000,
) -> dict:
    n = max(1, len(rows))
    raw_solver_score = sum(r["solver"][0] for r in rows) / float(n)
    raw_solver_acc = sum(float(r["solver"][1]) for r in rows) / float(n)
    ref_solver_score = raw_solver_score if default_solver_score is None else float(default_solver_score)
    out: dict = {}
    for ag in ALL_AGENTS:
        out[ag] = {
            "score": boot_ci([r[ag][0] for r in rows], B=B, seed=0),
            "acc": boot_ci([float(r[ag][1]) for r in rows], B=B, seed=0),
        }
    out["regret"] = {
        k: boot_ci([r["solver"][0] - r[k][0] for r in rows], B=B, seed=0)
        for k in INVESTIGATORS
    }
    sol_mean = out["solver"]["score"][0]
    inv_max = max(out[k]["score"][0] for k in INVESTIGATORS)
    out["min_regret"] = round(sol_mean - inv_max, 4)
    out["strongest_investigator"] = max(INVESTIGATORS, key=lambda k: out[k]["score"][0])
    out["solver_acc_point"] = out["solver"]["acc"][0]
    out["solver_score_point"] = sol_mean
    out["default_solver_score_half"] = round(0.5 * ref_solver_score, 4)
    out["catchable"] = bool(raw_solver_acc >= min_solver_acc - 1e-12)
    out["catchable_85"] = bool(
        (raw_solver_acc >= 0.85 - 1e-12)
        and (raw_solver_score >= 0.5 * ref_solver_score - 1e-12)
    )
    return out


def _paired_diff_summary(cand_rows: list[dict], ref_rows: list[dict], B: int = 2000) -> dict:
    diff = {
        **{
            f"{ag}_score": boot_ci(
                [y[ag][0] - x[ag][0] for x, y in zip(ref_rows, cand_rows)],
                B=B,
                seed=0,
            )
            for ag in ALL_AGENTS
        },
        "solver_acc": boot_ci(
            [float(y["solver"][1]) - float(x["solver"][1]) for x, y in zip(ref_rows, cand_rows)],
            B=B,
            seed=0,
        ),
        **{
            f"regret_{k}": boot_ci(
                [(y["solver"][0] - y[k][0]) - (x["solver"][0] - x[k][0]) for x, y in zip(ref_rows, cand_rows)],
                B=B,
                seed=0,
            )
            for k in INVESTIGATORS
        },
    }
    cand_min_reg = (
        sum(y["solver"][0] for y in cand_rows) / max(1, len(cand_rows))
        - max(sum(y[k][0] for y in cand_rows) / max(1, len(cand_rows)) for k in INVESTIGATORS)
    )
    ref_min_reg = (
        sum(x["solver"][0] for x in ref_rows) / max(1, len(ref_rows))
        - max(sum(x[k][0] for x in ref_rows) / max(1, len(ref_rows)) for k in INVESTIGATORS)
    )
    diff["min_regret_diff"] = round(cand_min_reg - ref_min_reg, 4)
    return diff


def evaluate_paired_set(
    policy: RLMoleV2,
    seeds: list[int],
    tier: str = "hard",
    workers: int = 1,
    v1_policy_path: str | Path | None = "data/rl_mole/policy_final.json",
    min_solver_acc: float = MIN_SOLVER_ACC,
    B: int = 2000,
    ex: ProcessPoolExecutor | None = None,
) -> dict:
    from canary.forge.rl_mole import RLMole

    _check_not_judge_seeds(seeds)
    t0 = time.time()
    own_ex = False
    if ex is None and workers > 1:
        ex = ProcessPoolExecutor(max_workers=workers)
        own_ex = True

    try:
        v2_rows = run_batch(
            policy.p,
            tier,
            seeds,
            workers=workers,
            agents=ALL_AGENTS,
            greedy=policy.greedy,
            none_penalty=policy.none_penalty,
            none_cap_gap=policy.none_cap_gap,
            ex=ex,
        )
        def_tasks = [(tier, int(s), ALL_AGENTS) for s in seeds]
        if ex is not None and workers > 1:
            chunk = max(1, len(def_tasks) // max(1, 2 * workers))
            def_rows = list(ex.map(_default_rollout, def_tasks, chunksize=chunk))
        else:
            def_rows = [_default_rollout(t) for t in def_tasks]

        v1_rows = None
        if v1_policy_path is not None and Path(v1_policy_path).is_file():
            v1_pol = RLMole.from_json(json.loads(Path(v1_policy_path).read_text()))
            v1_tasks = [(v1_pol.p, tier, int(s), ALL_AGENTS, v1_pol.greedy) for s in seeds]
            if ex is not None and workers > 1:
                chunk = max(1, len(v1_tasks) // max(1, 2 * workers))
                v1_rows = list(ex.map(_v1_rollout, v1_tasks, chunksize=chunk))
            else:
                v1_rows = [_v1_rollout(t) for t in v1_tasks]
    finally:
        if own_ex and ex is not None:
            ex.shutdown()

    def_solver_score = sum(r["solver"][0] for r in def_rows) / float(max(1, len(def_rows)))
    out = {
        "seeds": f"{seeds[0]}-{seeds[-1]}" if seeds else "",
        "seed_range": [int(seeds[0]), int(seeds[-1])] if seeds else [],
        "n": len(seeds),
        "seconds": round(time.time() - t0, 2),
        "rl_mole_v2": {
            **_summarize_policy_rows(
                v2_rows,
                default_solver_score=def_solver_score,
                min_solver_acc=min_solver_acc,
                B=B,
            ),
            "action_profile": action_diagnostics(v2_rows, policy),
        },
        "default_mole": {
            **_summarize_policy_rows(
                def_rows,
                default_solver_score=def_solver_score,
                min_solver_acc=min_solver_acc,
                B=B,
            ),
            "action_profile": {
                "H_leak": 0.0,
                "H_frame": 0.0,
                "leak": {"random_seeded": 1.0},
                "frame": {"none": 1.0},
            },
        },
        "diff_v2_minus_default": _paired_diff_summary(v2_rows, def_rows, B=B),
    }
    if v1_rows is not None:
        out["rl_mole_v1"] = {
            **_summarize_policy_rows(
                v1_rows,
                default_solver_score=def_solver_score,
                min_solver_acc=min_solver_acc,
                B=B,
            ),
            "action_profile": _empirical_selector_stats(v1_rows),
        }
        out["diff_v2_minus_v1"] = _paired_diff_summary(v2_rows, v1_rows, B=B)
    return out


def run_dual_heldout_eval(
    policy_path: str | Path,
    v1_policy_path: str | Path | None = "data/rl_mole/policy_final.json",
    n: int = 60,
    tier: str = "hard",
    workers: int = 1,
    min_solver_acc: float = MIN_SOLVER_ACC,
    B: int = 2000,
    out_path: str | Path | None = None,
) -> dict:
    pol = RLMoleV2.from_json(json.loads(Path(policy_path).read_text()))
    ws3_seeds = list(range(WS3_HELDOUT_SEEDS.start, WS3_HELDOUT_SEEDS.start + n))
    rules_seeds = list(rules.HELDOUT_SEEDS)[:n]
    _check_not_judge_seeds(ws3_seeds)
    _check_not_judge_seeds(rules_seeds)

    ex = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        ws3_res = evaluate_paired_set(
            pol,
            ws3_seeds,
            tier=tier,
            workers=workers,
            v1_policy_path=v1_policy_path,
            min_solver_acc=min_solver_acc,
            B=B,
            ex=ex,
        )
        rules_res = evaluate_paired_set(
            pol,
            rules_seeds,
            tier=tier,
            workers=workers,
            v1_policy_path=v1_policy_path,
            min_solver_acc=min_solver_acc,
            B=B,
            ex=ex,
        )
    finally:
        if ex is not None:
            ex.shutdown()

    both_catch85 = bool(
        ws3_res["rl_mole_v2"]["catchable_85"] and rules_res["rl_mole_v2"]["catchable_85"]
    )
    report = {
        "policy": str(policy_path),
        "v1_policy": str(v1_policy_path) if v1_policy_path else None,
        "tier": tier,
        "workers": workers,
        "agents": list(ALL_AGENTS),
        "n_per_set": n,
        "bootstrap_resamples": B,
        "ci_format": "[mean, lo95, hi95]",
        "min_solver_acc_threshold": min_solver_acc,
        "catchable_85_definition": "solver_acc >= 0.85 and solver_score >= 0.5 * default_solver_score",
        "seed_ranges": {
            "train": [TRAIN_SEEDS.start, TRAIN_SEEDS.stop - 1],
            "val": [VAL_SEEDS.start, VAL_SEEDS.stop - 1],
            "ws3_heldout": [ws3_seeds[0], ws3_seeds[-1]],
            "rules_heldout": [rules_seeds[0], rules_seeds[-1]],
            "judge": [rules.JUDGE_SEEDS.start, rules.JUDGE_SEEDS.stop - 1],
        },
        "catchable_85_both_sets": both_catch85,
        "all_heldout_catchable": both_catch85,
        "ws3_heldout": ws3_res,
        "rules_heldout": rules_res,
    }
    if out_path is not None:
        op = Path(out_path)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="canary.forge.rl_mole_v2")
    sub = ap.add_subparsers(dest="cmd", required=True)

    tr = sub.add_parser("train")
    tr.add_argument("--iters", type=int, default=50)
    tr.add_argument("--batch", type=int, default=16)
    tr.add_argument("--workers", type=int, default=1)
    tr.add_argument("--tier", default="hard")
    tr.add_argument("--lr", type=float, default=0.025)
    tr.add_argument("--hidden", type=int, default=20)
    tr.add_argument("--seed", type=int, default=0)
    tr.add_argument("--ent", type=float, default=0.02)
    tr.add_argument("--beta-mi", type=float, default=0.15)
    tr.add_argument("--lam0", type=float, default=1.5)
    tr.add_argument("--lam-lr", type=float, default=3.0)
    tr.add_argument("--target-acc", type=float, default=TARGET_SOLVER_ACC)
    tr.add_argument("--val-min-acc", type=float, default=VAL_MIN_SOLVER_ACC)
    tr.add_argument("--val-every", type=int, default=10)
    tr.add_argument("--out", default="/tmp/opencode/rl_mole_v2_work")
    tr.add_argument("--best-out", default=None)

    ho = sub.add_parser("heldout")
    ho.add_argument("--policy", required=True)
    ho.add_argument("--v1-policy", default="data/rl_mole/policy_final.json")
    ho.add_argument("--n", type=int, default=60)
    ho.add_argument("--tier", default="hard")
    ho.add_argument("--workers", type=int, default=1)
    ho.add_argument("--resamples", type=int, default=2000)
    ho.add_argument("--out", default=None)

    a = ap.parse_args(argv)
    if a.cmd == "train":
        train(
            iters=a.iters,
            batch=a.batch,
            workers=a.workers,
            tier=a.tier,
            lr=a.lr,
            hidden=a.hidden,
            seed=a.seed,
            ent=a.ent,
            beta_mi=a.beta_mi,
            lam0=a.lam0,
            lam_lr=a.lam_lr,
            target_acc=a.target_acc,
            val_min_acc=a.val_min_acc,
            val_every=a.val_every,
            out=a.out,
            best_policy_out=a.best_out,
        )
        return 0

    rep = run_dual_heldout_eval(
        policy_path=a.policy,
        v1_policy_path=a.v1_policy,
        n=a.n,
        tier=a.tier,
        workers=a.workers,
        B=a.resamples,
        out_path=a.out,
    )
    print(json.dumps(rep, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
