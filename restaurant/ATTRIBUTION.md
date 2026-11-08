# Attribution

The 2D restaurant animation in this folder is the `frontend-restaurant` of "The Restaurant" project
(https://github.com/carlkaziboni/HTB26, branch `claude/charming-hypatia-kj4ziu`, `projects/the-restaurant/`, commit d2c1b7a),
copied 2026-11-08 under the MIT licence of that repository (`LICENSE-upstream-MIT`). `CONTRACT-upstream.md` and `DEMO-upstream.md` are the
upstream event contract and 3-minute demo script, kept for reference.

Changes made here (see `git log -- restaurant/`): it can play recordings generated from OUR real-trace simulator
(`scheduler/restaurant_export.py`) and labels were changed so nothing implies data the trace does not contain
(no VRAM, deadlines, SLO or cost). The upstream synthetic sample (`public/sample-events.json`) is kept unchanged as a fallback.
