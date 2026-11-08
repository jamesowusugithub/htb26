// Pure functions that turn a what-if control into a backend scenario patch. They only edit scenario PARAMETERS
// (the backend then simulates); nothing here predicts or decides scheduling outcomes.
// All times are hours since window start. `nowH` is the playhead; changes start just after it so history is unchanged.

const EPS_H = 0.005; // 18 s of trace time: keeps the change strictly in the future of the playhead
const r4 = x => Math.round(x * 1e4) / 1e4;
const clone = sc => JSON.parse(JSON.stringify(sc));

export function addInjectedJob(sc, nowH, { pool, gpus = 1, priority = 'hp', duration_s = 900 }) {
  const s = clone(sc);
  s.injected_jobs = [...(s.injected_jobs || []), { at_h: r4(nowH + EPS_H), pool, gpus, priority, duration_s }];
  return s;
}
export function addBurst(sc, nowH, { duration_h = 0.5, mult = 4 } = {}) {
  const s = clone(sc);
  s.burst = { start_h: r4(nowH + EPS_H), duration_h, mult };
  return s;
}
export function failBoard(sc, nowH, board) {
  const s = clone(sc);
  const open = f => f.repair_after_h == null || f.at_h + f.repair_after_h > nowH;
  if ((s.failures || []).some(f => f.board === board && f.at_h <= nowH && open(f))) return s; // already failed
  s.failures = [...(s.failures || []), { board, at_h: r4(nowH + EPS_H), repair_after_h: null }];
  return s;
}
export function repairBoard(sc, nowH, board) {
  const s = clone(sc);
  s.failures = (s.failures || []).map(f => {
    const down = f.board === board && f.at_h <= nowH && (f.repair_after_h == null || f.at_h + f.repair_after_h > nowH);
    return down ? { ...f, repair_after_h: r4(Math.max(nowH + EPS_H - f.at_h, EPS_H)) } : f;
  });
  return s;
}
export const boardIsFailed = (sc, nowH, board) =>
  (sc.failures || []).some(f => f.board === board && f.at_h <= nowH && (f.repair_after_h == null || f.at_h + f.repair_after_h > nowH));
export function startCoolingFault(sc, nowH, delta_c = 35) {
  const s = clone(sc);
  s.cooling_fault = { at_h: r4(nowH + EPS_H), delta_c, duration_h: null };
  return s;
}
export function stopCoolingFault(sc, nowH) {
  const s = clone(sc);
  if (s.cooling_fault) s.cooling_fault = { ...s.cooling_fault, duration_h: r4(Math.max(nowH + EPS_H - s.cooling_fault.at_h, EPS_H)) };
  return s;
}
export const coolingFaultActive = (sc, nowH) => !!sc.cooling_fault && sc.cooling_fault.at_h <= nowH &&
  (sc.cooling_fault.duration_h == null || sc.cooling_fault.at_h + sc.cooling_fault.duration_h > nowH);
export const burstActive = (sc, nowH) => !!sc.burst && sc.burst.start_h <= nowH && nowH < sc.burst.start_h + sc.burst.duration_h;
