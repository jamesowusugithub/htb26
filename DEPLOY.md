# Deploy (Render, Docker) and the judge QR code

One container serves everything: `/` home + QR, `/judge` (judges submit a workload), `/kitchen/` (chef animation), `/room/` (3D room), `/graphs/`, and the API.

## Try it locally first
```bash
git lfs pull                      # the data, model and GLB are git-LFS files; the build refuses to continue if they are still stubs
docker build -t gpu-lens .
docker run -p 8000:8000 gpu-lens  # then open http://localhost:8000
```

## Render
1. Push this repo to GitHub (done: `main`). In Render: **New > Blueprint** > pick the repo (uses `render.yaml`), or **New > Web Service > Docker**.
2. **Plan: Standard (2 GB RAM) or larger.** The backend loads 467k jobs plus torch; the free/starter 512 MB tier will be killed. Health check path: `/health`.
3. **Git LFS:** Render's Docker build must have the LFS files. If the build stops with "git-LFS pointer", either enable LFS for the repo in Render, or build the image yourself and deploy it instead:
   `docker build -t <registry>/gpu-lens . && docker push <registry>/gpu-lens`, then **New > Web Service > Existing image**.
4. First deploy takes several minutes (torch + two frontend builds). The image warms the model caches at build time, so the first request is fast.

## The QR code
- Open `https://<your-app>.onrender.com/` : the home page shows a QR code that points at `/judge` on the same host.
- Or fetch the image directly: `https://<your-app>.onrender.com/qr.svg` (add `?url=<any address>` to encode a different link). Print or project it.
- Judges scan it, pick a workload (GPU type, GPUs, priority, run time) and see how fast it would complete under four schedulers.

## What the judge sees (and does not)
Simulated minutes on a small mixed kitchen replaying real Alibaba jobs; the visitor's job arrives at minute 45 when the queue is building. FIFO often never starts it within the 9 simulated hours; priority starts it late; the shortest-predicted-job rule and the trained RL start it early. A800 is a quiet pool (no waiting): the page says so. `GET /judge/board` returns the running totals of submissions.
Limits: submissions are kept in memory (lost on restart); there is no rate limit or authentication, so don't expose it beyond the event.
