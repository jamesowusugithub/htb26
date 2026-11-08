# Demo guide (5 minutes)

**Run:** `./run_demo.sh` (starts the backend, the 3D room and the kitchen, then opens them). Stop with `./run_demo.sh --stop`.
First start takes about a minute (models load). Needs the conda env `htb` and `git lfs pull` for the model files.

| Tab | URL |
|---|---|
| 3D server room | http://127.0.0.1:8082/index.html?api=http://127.0.0.1:8020&preset=heldout_demo&policy=rl_ppo |
| Kitchen (chef animation) | http://127.0.0.1:5174/?trace=rl_ppo&api=http://127.0.0.1:8020 |
| 30-second pitch with animation | http://127.0.0.1:5174/pitch.html?api=http://127.0.0.1:8020 |
| Charts | `analysis/graphs/index.html` |

## Running order
1. **Pitch (30 s)** - `pitch.html`, press *Play pitch*.
2. **3D room (90 s)** - jobs stream in from the real Alibaba trace; each streak is a scheduler decision. Point at **How jobs are placed** (side panel): job, size, priority, board, wait, deciding policy. Click **Compare policies** to run all six managers on this scenario. Press **Fail GPU** to show eviction and re-placement; **Job burst** for a spike. Open **Demand forecast**: forecast vs what arrived, including the misses.
3. **Kitchen (90 s)** - click **Apply kitchen** after choosing different GPU types and counts for the chefs (mix A10 / A100 / H800 / series 1...). Place an order for a chosen type, or **Rush: 6 big orders** to see the simulated cloud takeaway. Click **Compare all managers on this kitchen**: four charts plus predicted-vs-actual runtime.
4. **Charts (60 s)** - `analysis/graphs/index.html`: data used, policies on held-out days, the random-weights control, forecast.

## What to say about the numbers (all held-out data, all simulated waits)
- Learned scheduler: queue time about **half** of priority FIFO (0.52 vs 1.00) and clearly better than backfill (0.81) on days it never saw.
- It **ties** the best simple rule (shortest predicted job, 0.51) on queue time. Its edge: about 20% lower spot waits and about a third fewer preemptions; HP tail waits are slightly higher.
- It is a real learner: a network with random weights scores 0.57, training brings it to rule level (`analysis/rl/README.md`).
- Forecast: 11% / 18% / 27% lower error than "same as just now" at 10 / 30 / 60 min; no skill on the A10 pool; sudden spikes are not anticipated.
- Cloud costs are **simulated** rentals with assumed price tiers; temperatures are an H100-based **proxy**.

## Limits to state honestly
- The chef scene shows at most 5 chefs (40 GPUs); the RL policy supports the six real GPU types, any mix.
- The kitchen is a small demo cluster; the 3D room shows the full-scale simulated cluster. Kitchen times are simulated minutes, the room's are hours.
- A "board" in the 3D room is a slice of a pool's nodes, not one physical GPU.
- The 3D hall is graphically heavy: if it stutters, use a machine with a real GPU.

## If something is off
- Blank room / no data: the backend is still loading; check `$TMPDIR/htb-demo/backend.log`.
- First scenario is slow once (caches); `run_demo.sh` warms it.
- Port in use: `./run_demo.sh --stop`, then run again.
