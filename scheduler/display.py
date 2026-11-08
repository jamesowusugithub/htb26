"""How scheduler pools map onto the room's 24 GPU boards (4 pods x 6 boards).

A board is a *slice of nodes* of one pool: node local index % boards_per_pod. Failing a board fails all nodes in
its slice. Pools not shown as pods still run in the simulation; their totals are in every snapshot.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

DEFAULT_PODS = ["a100", "a10", "h800", "series1"]   # pod 1..4 in the room
BOARDS_PER_POD = 6


@dataclass(frozen=True)
class Display:
    pods: tuple = tuple(DEFAULT_PODS)
    boards_per_pod: int = BOARDS_PER_POD

    @property
    def n_boards(self) -> int:
        return len(self.pods) * self.boards_per_pod

    def pool_of_board(self, b: int) -> str:
        return self.pods[b // self.boards_per_pod]

    def board_of_nodes(self, cluster) -> np.ndarray:
        """Board index per global node (-1 when the node's pool is not displayed)."""
        ids = [p["id"] for p in cluster.pools]
        out = np.full(len(cluster.node_pool), -1, dtype=np.int64)
        starts = np.concatenate([[0], np.cumsum(np.bincount(cluster.node_pool, minlength=cluster.n_pools))])
        for pod, pid in enumerate(self.pods):
            p = ids.index(pid)
            local = np.arange(starts[p + 1] - starts[p])
            out[starts[p]:starts[p + 1]] = pod * self.boards_per_pod + local % self.boards_per_pod
        return out

    def nodes_of_board(self, cluster, board: int) -> np.ndarray:
        return np.flatnonzero(self.board_of_nodes(cluster) == board)

    def describe(self, cluster) -> dict:
        bon = self.board_of_nodes(cluster)
        ids = [p["id"] for p in cluster.pools]
        labels = {p["id"]: p["label"] for p in cluster.pools}
        boards = []
        for b in range(self.n_boards):
            m = bon == b
            boards.append({"index": b, "pod": b // self.boards_per_pod, "slice": b % self.boards_per_pod,
                           "pool": self.pool_of_board(b), "nodes": int(m.sum()),
                           "capacity_gpus": float(cluster.node_ngpu[m].sum())})
        return {"boards_per_pod": self.boards_per_pod, "slice_rule": "node local index % boards_per_pod",
                "pods": [{"pod": i, "pool": pid, "label": labels[pid], "boards": list(range(i * self.boards_per_pod, (i + 1) * self.boards_per_pod))}
                         for i, pid in enumerate(self.pods)],
                "boards": boards, "note": "Each board is a slice of its pool's nodes, not a single physical GPU."}
