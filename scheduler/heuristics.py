"""Hand-coded rules over the RL observation (used for behaviour-cloning warm start and as an in-env baseline)."""
import numpy as np


def hp_then_min_hint(obs: np.ndarray, mask: np.ndarray, K: int = 8, P: int = 6) -> int:
    """Among startable candidates: HP before spot, then smallest runtime hint. Falls back to 'advance' (K)."""
    base = P + 6
    best, bk = None, (9, 9e9)
    for k in range(K):
        if not mask[k]:
            continue
        o = base + 8 * k
        key = (0 if obs[o + 2] > 0.5 else 1, float(obs[o + 5]))
        if key < bk:
            bk, best = key, k
    return best if best is not None else K


def hint_rule_with_offload(obs: np.ndarray, mask: np.ndarray, K: int = 8, P: int = 6, min_wait_h: float = 2.0) -> int:
    """The shortest-predicted-job rule plus the baseline cloud rule: send the queue head to the simulated cloud once it has waited >= min_wait_h
    (the environment's mask already enforces the predicted-cost budget). Used only to initialise the cost-aware policy by cloning."""
    base = P + 6
    if len(mask) == K + 2 and mask[K + 1] and obs[base + 4] >= np.log1p(min_wait_h) / 4.0:
        return K + 1
    return hp_then_min_hint(obs, mask[: K + 1], K, P)
