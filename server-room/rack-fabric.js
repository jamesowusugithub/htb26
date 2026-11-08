export const RACKS_PER_POOL = 20;
export const POOL_RACK_STARTS = [0, 40, 80, 120, 160, 240];

export function rackIndicesForPool(poolIndex) {
  const start = POOL_RACK_STARTS[poolIndex];
  return start == null ? [] : Array.from({ length: RACKS_PER_POOL }, (_, i) => start + i);
}

export function buildRackPools(metaPools = [], poolSnapshots = {}, boards = [], display = null) {
  return metaPools.slice(0, POOL_RACK_STARTS.length).map((meta, poolIndex) => {
    const live = poolSnapshots[meta.id] || {};
    const related = (display?.boards || []).map((board, i) => ({ ...board, live: boards[i] })).filter(board => board.pool === meta.id);
    const capacity = Number(live.capacity_gpus ?? meta.capacity_gpus ?? 0);
    const busy = Number(live.busy_gpus ?? 0);
    const queueHp = Number(live.queue_hp ?? 0);
    const queueSpot = Number(live.queue_spot ?? 0);
    const queue = queueHp + queueSpot;
    const utilPct = capacity > 0 ? 100 * busy / capacity : 0;
    const nodesDown = related.reduce((sum, board) => sum + Number(board.live?.nodes_down || 0), 0);
    const nodes = related.reduce((sum, board) => sum + Number(board.live?.nodes ?? board.nodes ?? 0), 0);
    const alerts = related.filter(board => board.live?.alert).length;
    const temperatures = related.map(board => board.live?.temp_c).filter(Number.isFinite);
    const unavailable = capacity <= 0 || (nodes > 0 && nodesDown >= nodes);
    const overloaded = !unavailable && queue > 0 && (utilPct >= 90 || Number(live.max_free_gpus_on_one_node || 0) === 0);
    const status = unavailable ? 'failed' : overloaded ? 'overloaded' : busy > 0 ? 'busy' : 'idle';
    return {
      id: meta.id, label: meta.label, poolIndex, rackIndices: rackIndicesForPool(poolIndex),
      representation: `${RACKS_PER_POOL} visual racks mirror one aggregate backend pool`,
      nodeCount: Number(meta.node_count ?? meta.nodes ?? 0), capacityGpus: capacity, busyGpus: busy,
      utilisation: utilPct, queueHp, queueSpot, queue, runningJobs: Number(live.running_jobs || 0),
      maxFreeGpusOnOneNode: Number(live.max_free_gpus_on_one_node || 0), nodesDown, nodesMapped: nodes,
      thermalAvailable: temperatures.length > 0, maxTemperature: temperatures.length ? Math.max(...temperatures) : null,
      thermalAlerts: alerts, status,
    };
  });
}
