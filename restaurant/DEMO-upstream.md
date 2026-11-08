# 3-minute demo script

Setup once (see README.md for details), three terminals:
```
cd backend && uvicorn app.main:app --port 8000                       # must log no "RL CHECKPOINT NOT LOADED"
cd frontend-restaurant && npm ci && npm run build && npx vite preview --port 5174 --host localhost
cd frontend-rack       && npm ci && npm run build && npx vite preview --port 5173 --host localhost
```
Use `localhost`, not `127.0.0.1` (CORS/WebSocket origin allow-list). Keep injected jobs inside the default sizes (do not hand-craft jobs longer than 24 s: the policy never starts them, see RESULTS.md).

| time | do this | say / show |
|---|---|---|
| 0:00 | Open **http://localhost:5174/?source=live**. Point at the badges: `SOURCE: LIVE`, `SCHEDULER: RL policy`, `SIMULATED DATA`. | "Customers are computing jobs, chefs are GPUs, the manager is a reinforcement-learning policy. Everything is simulated." If it says `FALLBACK, NOT RL` stop and fix the checkpoint. |
| 0:20 | Click **Start**, click speed **4x**. Watch customers walk to Zone A (premium), Zone B (standard), the Waiting area. | Shirt colour = priority, group size = GPU memory. |
| 0:45 | Click **VIP** (crown customer). | Scenario 2: VIP jumps the queue; show it in the decision panel and the completed counter. |
| 1:05 | Click **Spike** twice. | Scenario 3: crowd at the entrance, some customers go to **C Cloud Takeaway**; side panel waiting count rises. |
| 1:30 | Pick GPU **premium-0** in "PICK A GPU", click **Heat +20** four to six times. | Scenario 4: chef steams, `TOO HOT` sign, new customers go to other chefs; premium-0 gets nothing until it cools. |
| 1:55 | Pick **standard-1**, click **Disable**, then **Restore**. | Scenario 5: chef greyed `CLOSED`, its jobs return to the queue and are re-assigned. |
| 2:10 | Open **http://localhost:5173/?source=rest** (rack view). Click **Start**, **Spike (12 jobs)**, choose `premium-0` in Target GPU, **Force heat**. | Same engine, technical view: tank fill = VRAM, side column = temperature, Last Decisions with `valid x/6`, `predT`, `cost`. |
| 2:30 | Back in the restaurant UI click scheduler **fifo**, then **rl** (same traffic) - or show the table in `RESULTS.md`. In a terminal: `/tmp/venv-rest/bin/python scripts/run_scenarios.py --only 6`. | Scenario 6: same seed, three schedulers. Say the honest result: RL spends ~65 % less time in critical temperature and is cheaper at high load, but waits longer and starves 1-2 jobs per run. |
| 2:50 | Show `RESULTS.md` headline + limitations. | "We report the result even though RL loses on latency." |

Fallback if the backend dies: both UIs show `REPLAY` / `MOCK` banners (never `LIVE`); say so, restart uvicorn.
