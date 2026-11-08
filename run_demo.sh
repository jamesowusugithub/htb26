#!/usr/bin/env bash
# One command to run the whole demo and open it in your browser.   ./run_demo.sh [--no-open]
#   backend (scheduler + trained RL)  http://127.0.0.1:8020
#   3D server room (Blender/Three.js) http://127.0.0.1:8082
#   chef / restaurant animation       http://127.0.0.1:5174
# Safe to run twice: anything already listening is left alone. Stop everything: ./run_demo.sh --stop
set -u
cd "$(dirname "$0")"
PY="${PYTHON:-$HOME/anaconda3/envs/htb/bin/python}"; [ -x "$PY" ] || PY="$(command -v python3)"
API=http://127.0.0.1:8020; ROOM=http://127.0.0.1:8082; KITCHEN=http://127.0.0.1:5174
LOG="${TMPDIR:-/tmp}/htb-demo"; mkdir -p "$LOG"
if [ "${1:-}" = "--stop" ]; then
  pkill -f "uvicorn scheduler.api:app --port 8020"; pkill -f "http-server dist -a 127.0.0.1 -p 8082"; pkill -f "http.server 5174"; echo stopped; exit 0
fi
up() { curl -s -o /dev/null -m 2 "$1"; }
if ! up "$API/health"; then
  echo "starting backend (first start loads the models, about a minute)..."
  OMP_NUM_THREADS=4 nohup "$PY" -m uvicorn scheduler.api:app --port 8020 --log-level warning > "$LOG/backend.log" 2>&1 &
fi
if ! up "$ROOM/index.html"; then
  [ -d server-room/dist ] || (cd server-room && npm run build >/dev/null 2>&1)
  (cd server-room && nohup npx --no-install http-server dist -a 127.0.0.1 -p 8082 -c-1 > "$LOG/room.log" 2>&1 &)
fi
if ! up "$KITCHEN/"; then
  [ -d restaurant/dist ] || (cd restaurant && npm run build >/dev/null 2>&1)
  nohup "$PY" -m http.server 5174 --bind 127.0.0.1 --directory restaurant/dist > "$LOG/kitchen.log" 2>&1 &
fi
for i in $(seq 1 90); do up "$API/health" && break; sleep 2; done
up "$API/health" || { echo "backend did not start: see $LOG/backend.log"; exit 1; }
echo "warming the scenario cache..."
curl -s -m 280 -X POST "$API/whatif" -H 'content-type: application/json' -d '{"preset":"heldout_demo","policies":["rl_ppo"],"snapshot_s":600}' >/dev/null
curl -s -m 280 "$API/restaurant/trace?policy=rl_ppo" >/dev/null
ROOM_URL="$ROOM/index.html?api=$API&preset=heldout_demo&policy=rl_ppo"
KITCHEN_URL="$KITCHEN/?trace=rl_ppo&api=$API"
GRAPHS="file://$PWD/analysis/graphs/index.html"
echo; echo "3D room : $ROOM_URL"; echo "kitchen : $KITCHEN_URL"; echo "graphs  : $GRAPHS"
[ "${1:-}" = "--no-open" ] || { command -v open >/dev/null && { open "$ROOM_URL"; sleep 1; open "$KITCHEN_URL"; sleep 1; open "$GRAPHS"; }; }
