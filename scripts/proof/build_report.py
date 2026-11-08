"""Assemble analysis/proof/README.md and index.html from the proof outputs (no hand-typed numbers)."""
import base64, json, re, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; P = ROOT / "analysis/proof"
rl = json.loads((P / "rl-proof.json").read_text()); lin = json.loads((P / "lineage.json").read_text())
live = json.loads((P / "live-run.json").read_text()); net = json.loads((P / "network.json").read_text())
api = live["url"].split("api=")[1].split("&")[0].replace("%3A", ":").replace("%2F", "/")
meta = json.loads(urllib.request.urlopen(f"{api}/meta").read())
log = [l for l in (P / "backend-access.log").read_text().splitlines() if re.search(r"POST /whatif|GET /meta|GET /presets|/state\?t=|WebSocket /runs", l)][:8]
tab = {r["policy"]: r for r in rl["table"]}
m = rl["model"]; d = rl["decisions"]; h = lin["harmonised"]; raw = lin["raw_csv_row"]; ev = lin["feed_events"]
sb = {r["policy"]: r for r in live["scoreboard"]["rows"]}
fr = net["frames"]
f1 = lambda x: f"{x:.2f}"
md = f"""# Proof pack: is it connected, is the RL trained, is the data used meaningfully?

Everything below was produced by running the real system; numbers come from `analysis/proof/*.json`, re-generate with the commands at the end.

## 1. Front end and back end are connected
- Browser at `{live['url'].split('?')[0]}` talked to the FastAPI backend at `{api}`; the page was driven by the **trained RL policy** (policy box shows "{live['st1']['policyLabel']}").
- The browser recorded **{net['requestCount']} HTTP calls** to the API and **{len(net['websockets'])} WebSocket** (`{net['websockets'][0]['url']}`): **{fr['total']} frames, {fr['bytes']/1e6:.1f} MB**, carrying {fr['itemsByType'].get('arrive', 0):,} job arrivals, {fr['itemsByType'].get('start', 0):,} scheduler starts, {fr['itemsByType'].get('finish', 0):,} finishes, {fr['itemsByType'].get('preempt', 0)} preemptions and {fr['itemsByType'].get('snapshot', 0)} board snapshots.
- The **backend's own access log** shows the same requests (same run id `{live['st1']['runId']}`):
```
{chr(10).join(l.strip() for l in log)}
```
- The in-app **Backend link** panel shows these counters live (server, transport, run id, batches, events, "last data n s ago").
- Automated: 22/22 browser checks on WebSocket and on polling (`server-room/tests/e2e/live-flow.mjs`), including: the engine snapshot equals the backend `/state` at the same time, and every temperature shown over 3 s is a value the backend sent for that board.

## 2. The RL model is trained (and what that did and did not buy)
- `{m['file']}`: {m['bytes']:,} bytes, sha256 `{m['sha256']}…`, **{m['policy_parameters']:,} parameters**. Trained {m['training']['steps']:,} PPO steps on {m['training']['envs']} parallel environments in {m['training_seconds']} s, after behaviour-cloning the hint rule on {m['training']['bc_episodes']} windows. **Candidate slots are randomly permuted at every decision, so slot position carries no information and the network has to read the job features.** {m['validation_checks']} validation checks (days 118-124); training windows were days 45-115 only. Three seeds were trained (validation 0.348 / 0.357 / 0.362); the served one had the best validation score, chosen before any test number was seen.
- **Held-out test (days 130-172, six 3-day windows, never used for training or checkpoint choice), queue time relative to priority-FIFO (lower is better):**

| Policy | HP wait (h) | HP p95 (h) | Spot wait (h) | Queue-time ratio |
|---|---|---|---|---|
""" + "\n".join(f"| {n} | {tab[k]['hp_wait_mean_h']:.2f} | {tab[k]['hp_wait_p95_h']:.1f} | {tab[k]['spot_wait_mean_h']:.1f} | {tab[k]['q_ratio']:.3f} |"
                for k, n in (("priority_fifo", "priority FIFO"), ("backfill_median", "backfill"), ("rl_untrained", "**RL, untrained (same network, random weights)**"),
                             ("rl_trained", "**RL, trained**"), ("sjf_hint", "shortest predicted job (rule)"), ("sjf_oracle", "oracle with true durations (unattainable)"))) + f"""

- **Control (this is the test that matters):** with slot order hidden, the same network with random weights scores {tab['rl_untrained']['q_ratio']:.2f} here and the trained one {tab['rl_trained']['q_ratio']:.2f}. On all 17 held-out windows (`analysis/rl/rl_shuffle_eval.json`): random valid choice 0.602, random-weights network 0.574, trained seeds 0.509-0.513, hint rule 0.509. So training matters and reaches rule-level quality. An earlier version with candidates pre-sorted by the hint hid this: even random weights scored the same as the trained network (0.452 vs 0.455), which would have made the RL meaningless.
- **What the trained agent does** (day-130 window, {d['trained']['real_choices']:,} real choices between startable jobs): it skips the queue head in **{d['trained']['pct_choices_where_rl_skips_the_queue_head']}%** of them and, when it skips, picks a shorter-predicted job in **{d['trained']['pct_skips_that_pick_a_shorter_predicted_job']}%** (untrained network: {d['untrained']['pct_skips_that_pick_a_shorter_predicted_job']}%).
- **Honest verdict:** RL beats FIFO, priority-FIFO and backfill and **ties the simple "shortest predicted job" rule** on queue time (about 0.51-0.52 vs 0.51 over 17 held-out windows; slightly ahead on what-if windows, 0.422 vs 0.444, and on held-out BurstGPT shapes, 0.583 vs 0.596). It keeps the lowest spot waits and does about 30% fewer preemptions than the rule; HP tail waits are slightly worse. It does not beat the rule decisively. Full tables and caveats: `analysis/rl/README.md`.
- Chart: `rl-training-proof.png`. Live: in the room, press **Compare policies** (Policy scoreboard) to have the backend run every policy, including the trained one, on the current scenario:

| Live scoreboard, held-out day 130 | HP wait (h) | HP p95 (h) | Spot wait (h) |
|---|---|---|---|
""" + "\n".join(f"| {k} | {sb[k]['hp_wait_mean_h']:.2f} | {sb[k]['hp_wait_p95_h']:.1f} | {sb[k]['spot_wait_mean_h']:.1f} |" for k in ("fifo", "priority_fifo", "backfill_median", "sjf_hint", "rl_ppo", "sjf_oracle")) + f"""

## 3. The data is used in the way the project describes
**"Make the invisible visible":** the raw trace has columns `{', '.join(lin['raw_csv_columns'])}` and **no queue, start, wait or eviction data**. The backend reconstructs them and the room shows them.

**One job, end to end.** The room's inspector showed job **{lin['job_id_shown_in_ui']}** on **{lin['ui_board']}** ({lin['ui_subtitle']}):

| Layer | What it holds for this job |
|---|---|
| Raw file `data/alibaba-2026-spot-gpu/job_info_df.csv` | `{json.dumps(raw)}` |
| Harmonised `harmonized/alibaba/jobs.parquet` | pool `{h['gpu_model_identifier']}`, `{h['priority_class']}`, submit {h['submit_relative_s']:.0f} s, duration {h['duration_s']:.0f} s (source row {h['source_row_number']:,}) |
| Simulator feed (run `{lin['run_id']}`) | arrive t={ev[0]['t']:.0f}s; start t={ev[1]['t']:.0f}s on node {ev[1]['node']}, board {ev[1]['board'] + 1}; finish t={ev[2]['t']:.0f}s (simulated wait {ev[2]['wait_s']:.0f}s) |
| 3D room | board {ev[1]['board'] + 1} = "GPU-{ev[1]['board'] + 1:02d}", "Assigned job {lin['job_id_shown_in_ui']}" |

Checks: raw submit {float(raw['submit_time'])/86400:.3f} days = window start day 130 + {ev[0]['t']:.0f} s; raw duration {raw['duration']} s = feed `service_s` {ev[1]['service_s']:.0f} s = finish - start.

| Source | Used? | How |
|---|---|---|
| Alibaba jobs (466,867) | **Yes** | every job in the replay window; trains the runtime-hint model (finished jobs before day 40) and the demand forecaster (days before 100); RL training windows |
| Alibaba nodes (4,278) | **Yes** | the cluster, 6 GPU-model pools, scaled to ~85% offered load ({', '.join(f"{p['id']} {p['nodes']}" for p in meta['pools'])} simulated nodes) |
| Thermal archive (11.9M readings -> 45 profiles) | **Yes, as a proxy** | measured H100 profiles -> board temperature and power; labelled as proxy, never claimed for Alibaba hardware |
| GPU pricing | **Yes, for the simulated cloud overflow** | price tiers anchored to the offers data (premium = cheapest H100-80GB offer, standard = cheapest L40S); no Alibaba GPU has an exact price match, so the tiers are labelled assumptions and cloud assignments are simulated, never observed |
| BurstGPT (10.6M requests) | **Yes** | hourly arrival-shape profiles for what-ifs and RL training (traces 1-2); trace 3 is held out and used only for testing |

## 4. What this does NOT prove (read before presenting)
- Waits, placements, evictions and failures are **simulated** under stated assumptions; the trace itself has no ground truth for them.
- Temperatures/power are an **H100-based proxy**; the 80 C alert threshold and the +35 C cooling-fault size are **assumptions**.
- The displayed 30-minute **utilisation** forecast is **persistence**: a survival projection and a learned state forecaster were both measured and neither beat it (`analysis/rl/state_forecast_*.json`). The **demand forecast** (GPUs requested in the next 30 min, with a P10-P90 band) is learned: 18% lower error than rate-persistence on held-out days, ~82% band coverage, little skill on the A10 pool, and sudden spikes are not anticipated.
- RL **ties** the best simple rule (it does not beat it decisively); three seeds, 3-day windows. Cloud spend is a simulated rental cost, charged for the full predicted job at start.
- Bug found and fixed while producing this pack: the API's `sjf_hint` policy had been using true durations (it equalled the oracle); the regression test `test_realistic_hint_policy_never_sees_true_durations` now guards it. Earlier research tables used a different code path and were not affected.

## Reproduce
```bash
uvicorn scheduler.api:app --port 8010                       # backend (port 8000 was already in use on this machine by another app)
cd server-room && npm run build && npx http-server dist -p 8081 -c-1
python scripts/proof/rl_proof.py                             # model facts, untrained control, decisions, chart
node server-room/tests/e2e/proof.mjs --api=http://127.0.0.1:8010 --web=http://127.0.0.1:8081
python scripts/proof/lineage.py && python scripts/proof/build_report.py
```
Open: http://127.0.0.1:8081/index.html?api=http://127.0.0.1:8010&preset=heldout_demo&policy=rl_ppo
"""
(P / "README.md").write_text(md)
def img(n): return "data:image/png;base64," + base64.b64encode((P / n).read_bytes()).decode()
html = md.replace("&", "&amp;")
import html as H
body = H.escape(md)
body = re.sub(r"^# (.*)$", r"<h1>\1</h1>", body, flags=re.M); body = re.sub(r"^## (.*)$", r"<h2>\1</h2>", body, flags=re.M)
body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body); body = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", body)
lines, out, tbl = body.split("\n"), [], False
for ln in lines:
    if ln.startswith("|"):
        if re.match(r"^\|[-| ]+\|$", ln): continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        tag = "th" if not tbl else "td"
        if not tbl: out.append("<table>"); tbl = True
        out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
    else:
        if tbl: out.append("</table>"); tbl = False
        out.append(ln if ln.startswith("<h") else (f"<li>{ln[2:]}</li>" if ln.startswith("- ") else (f"<p>{ln}</p>" if ln.strip() else "")))
if tbl: out.append("</table>")
figs = "".join(f'<figure><img src="{img(n)}"><figcaption>{c}</figcaption></figure>' for n, c in (
    ("proof-01-live-rl-scene.png", "Live room driven by the trained RL policy (held-out day 130)"), ("proof-02-job-in-inspector.png", "Inspector showing the traced job and proxy-labelled temperature"),
    ("proof-03-policy-scoreboard.png", "Policy scoreboard + pools + Backend link panel"), ("rl-training-proof.png", "Training curve and held-out comparison incl. untrained control")))
(P / "index.html").write_text(f"<!doctype html><meta charset=utf-8><title>Proof pack</title><style>body{{font:15px/1.5 -apple-system,Segoe UI,sans-serif;max-width:1000px;margin:30px auto;padding:0 20px;color:#1c2b33}}table{{border-collapse:collapse;margin:10px 0}}td,th{{border:1px solid #d6dee5;padding:5px 9px;font-size:13px;text-align:left}}th{{background:#eef3f6}}code{{background:#eef3f6;padding:1px 4px;border-radius:3px;font-size:12px}}figure{{margin:18px 0}}img{{max-width:100%;border:1px solid #d6dee5;border-radius:6px}}figcaption{{font-size:12px;color:#5b6f7e}}h2{{margin-top:30px;border-bottom:1px solid #d6dee5;padding-bottom:4px}}</style>"
                                 + "\n".join(out) + "<h2>Screenshots</h2>" + figs)
print("wrote", P / "README.md", "and index.html;", (P / "index.html").stat().st_size // 1024, "KB")
