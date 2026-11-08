# One container: API + trained RL + judge page + 3D room + kitchen.   docker build -t gpu-lens . && docker run -p 8000:8000 gpu-lens
# Needs the git-LFS files (data parquet, model, GLB) to be present in the build context: run `git lfs pull` first.
FROM node:20-slim AS web
WORKDIR /src
COPY server-room ./server-room
COPY restaurant ./restaurant
RUN cd server-room && npm install --no-audit --no-fund && npm run build \
 && cd ../restaurant && npm install --no-audit --no-fund && npm run build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 NUMBA_CACHE_DIR=/tmp/numba OMP_NUM_THREADS=2
WORKDIR /app
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY scheduler ./scheduler
COPY harmonized/alibaba ./harmonized/alibaba
COPY harmonized/pricing ./harmonized/pricing
COPY integrated ./integrated
COPY models ./models
COPY analysis/rl ./analysis/rl
COPY analysis/graphs ./analysis/graphs
COPY --from=web /src/server-room/dist ./server-room/dist
COPY --from=web /src/restaurant/dist ./restaurant/dist
RUN rm -f restaurant/dist/pitch.html          # internal presentation page: not for visitors
# fail early with a clear message if the LFS files are still pointer stubs
RUN python - <<'PY'
import os, sys
for f in ("harmonized/alibaba/jobs.parquet", "harmonized/alibaba/nodes.parquet", "models/ppo_u6_shuf_s12/best.zip", "integrated/hardware/thermal_load_profiles.parquet"):
    if os.path.getsize(f) < 2000:
        sys.exit(f"{f} is a git-LFS pointer, not the real file: run 'git lfs pull' before building")
PY
# warm caches at build time (duration-hint model, demand forecaster, numba) so the first request is fast
RUN python - <<'PY'
from scheduler.run_baselines import setup
from scheduler.duration_model import load_or_fit
from scheduler import demand_forecast as d
pools, jobs, base, cl = setup(0.85); load_or_fit(jobs, 40); d.load_or_fit(jobs, len(pools))
PY
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn scheduler.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
