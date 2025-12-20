# graph.py
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Node:
    name: str
    kind: str           # "schema" | "route"
    file: str
    start: int
    end: int
    meta: dict
    artifact_path: Optional[str] = None


class CodeGraph:
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, List[str]] = defaultdict(list)

    def add_node(self, node: Node):
        if node.name not in self.nodes:
            self.nodes[node.name] = node

    def add_edge(self, src: str, dst: str):
        if dst not in self.edges[src]:
            self.edges[src].append(dst)

    def execution_plan(self) -> List[str]:
        indegree = defaultdict(int)

        for src, targets in self.edges.items():
            for t in targets:
                indegree[t] += 1

        queue = deque(n for n in self.nodes if indegree[n] == 0)
        order = []

        while queue:
            n = queue.popleft()
            order.append(n)
            for dep in self.edges.get(n, []):
                indegree[dep] -= 1
                if indegree[dep] == 0:
                    queue.append(dep)

        return [n for n in order if n in self.nodes]
