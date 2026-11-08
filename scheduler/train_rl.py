"""Train masked PPO on randomised training windows.

    python -m scheduler.train_rl --steps 3000000 --envs 8 --device cpu --out models/ppo_a
Training windows: days 45-115 (random start, 3 days, arrival x0.8-1.4, capacity x0.9-1.1).
Validation windows (checkpoint selection): days 118-127. Test windows (days >= 130) are never used here.
The runtime-hint model is trained only on jobs finished before day 40.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np
import torch
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.utils import get_action_masks
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecNormalize

from .run_baselines import setup
from .duration_model import load_or_fit
from .env import SchedulingEnv
from .whatif import Scenario
from .heuristics import hp_then_min_hint

VAL = [Scenario(name="val", start_day=d, days=3.0, seed=0) for d in (118.0, 121.0, 124.0)]


WIDE = dict(arrival_mult=(0.7, 1.5), capacity_jitter=(0.85, 1.15))


def make_env(rank, seed, K, days, wide=False, burst_prob=0.0):
    def _f():
        pools, jobs, base, cl = setup(0.85)
        hint = load_or_fit(jobs, 40)
        kw = WIDE if wide else {}
        return SchedulingEnv(jobs, cl, hint, train_days=(45.0, 115.0), days=days, seed=seed + rank, K=K, burst_prob=burst_prob, **kw)
    return _f


def behaviour_clone(model, K, episodes, seed, wide, epochs=12, lr=1e-3, burst_prob=0.0):
    """Imitate hp_then_min_hint on random training windows, then train the policy net on (obs, mask) -> action."""
    env = make_env(999, seed, K, 3.0, wide, burst_prob)()
    X, M, A = [], [], []
    for _ in range(episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            mask = env.action_masks()
            act = hp_then_min_hint(obs, mask, K, env.base_cluster.n_pools)
            X.append(obs); M.append(mask); A.append(act)
            obs, r, te, tr, info = env.step(act)
            done = te or tr
    X, M, A = (torch.as_tensor(np.array(v)) for v in (X, M, A))
    print(f"[bc] {len(A):,} samples from {episodes} windows", flush=True)
    opt = torch.optim.Adam(model.policy.parameters(), lr=lr)
    dev = model.device
    for ep in range(epochs):
        perm = torch.randperm(len(A))
        tot, acc = 0.0, 0.0
        for i in range(0, len(A), 4096):
            idx = perm[i:i + 4096]
            _, logp, _ = model.policy.evaluate_actions(X[idx].to(dev), A[idx].to(dev), action_masks=M[idx].numpy())
            loss = -logp.mean()
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss) * len(idx)
        print(f"[bc] epoch {ep + 1}/{epochs} nll={tot / len(A):.4f}", flush=True)


class ValCallback(BaseCallback):
    def __init__(self, every, out, K):
        super().__init__()
        self.every, self.out, self.K = every, out, K
        self.best = np.inf
        self.last = 0
        pools, jobs, base, cl = setup(0.85)
        self.env = SchedulingEnv(jobs, cl, load_or_fit(jobs, 40), K=K)
        self.hist = []

    def _val(self):
        ratios, hp = [], []
        for sc in VAL:
            obs, _ = self.env.reset(options={"scenario": sc})
            done = False
            while not done:
                a, _ = self.model.predict(obs, action_masks=self.env.action_masks(), deterministic=True)
                obs, r, te, tr, info = self.env.step(int(a))
                done = te or tr
            ratios.append(info["qint_ratio_vs_priority_fifo"])
            hp.append(info["metrics"]["hp"]["wait_mean_s"] / 3600)
        return float(np.mean(ratios)), float(np.mean(hp))

    def _on_step(self):
        if self.num_timesteps - self.last >= self.every:
            self.last = self.num_timesteps
            ratio, hp = self._val()
            self.hist.append({"steps": self.num_timesteps, "val_q_ratio": ratio, "val_hp_wait_h": hp})
            print(f"[val] steps={self.num_timesteps:,} queue-time ratio vs priority_fifo={ratio:.3f} HP wait={hp:.2f}h", flush=True)
            self.logger.record("val/q_ratio", ratio)
            if ratio < self.best:
                self.best = ratio
                self.model.save(self.out / "best")
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3_000_000)
    ap.add_argument("--envs", type=int, default=8)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default="models/ppo_a")
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--days", type=float, default=3.0)
    ap.add_argument("--val-every", type=int, default=300_000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--verbose", type=int, default=0)
    ap.add_argument("--bc-episodes", type=int, default=0, help="behaviour-clone hp_then_min_hint on this many windows first")
    ap.add_argument("--wide", action="store_true", help="wider load/capacity randomisation")
    ap.add_argument("--ent", type=float, default=0.003)
    ap.add_argument("--burst-prob", type=float, default=0.0, help="share of training episodes using a BurstGPT arrival shape (combined layer)")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--net", type=int, nargs="+", default=[128, 128])
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(a.seed)
    fns = [make_env(i, a.seed * 1000, a.K, a.days, a.wide, a.burst_prob) for i in range(a.envs)]
    venv = SubprocVecEnv(fns) if a.envs > 1 else DummyVecEnv(fns)
    venv = VecNormalize(venv, norm_obs=False, norm_reward=True, gamma=0.999)
    model = MaskablePPO("MlpPolicy", venv, device=a.device, learning_rate=a.lr, n_steps=2048, batch_size=4096,
                        n_epochs=4, gamma=0.999, gae_lambda=0.95, ent_coef=a.ent, clip_range=0.2,
                        policy_kwargs=dict(net_arch=dict(pi=a.net, vf=a.net)), seed=a.seed, verbose=a.verbose,
                        tensorboard_log=str(out / "tb"))
    if a.bc_episodes:
        behaviour_clone(model, a.K, a.bc_episodes, a.seed, a.wide, burst_prob=a.burst_prob)
    cb = ValCallback(a.val_every, out, a.K)
    t = time.time()
    model.learn(a.steps, callback=cb, progress_bar=False)
    model.save(out / "final")
    venv.save(str(out / "vecnormalize.pkl"))
    (out / "history.json").write_text(json.dumps({"args": vars(a), "seconds": time.time() - t, "val": cb.hist}, indent=1))
    print(f"done in {time.time() - t:.0f}s; best val ratio {cb.best:.3f}")


if __name__ == "__main__":
    main()
