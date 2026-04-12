import logging
from typing import Dict, List, Tuple
from collections import deque
from .ast_parser import CodeComponent

logger = logging.getLogger(__name__)

def resolve_cycles(graph: Dict[str, List[str]]) -> Tuple[Dict[str, List[str]], List[Tuple[str, str]]]:
    """
    Removes back-edges to break cycles in a directed graph.

    Args:
        graph: the dependency graph
    
    Returns:
        acyclic_graph: The resolved graph with cycles broken.
        removed_edges: A list of the (source, target) edges that were deleted.
    """
    visited = set()
    recursion_stack = set()
    removed_edges = []
    
    # Initialize the new graph safely (ensuring all nodes are keys)
    acyclic_graph = {node: [] for node in graph}
    for edges in graph.values():
        for target in edges:
            if target not in acyclic_graph:
                acyclic_graph[target] = []

    def dfs(node: str):
        visited.add(node)
        recursion_stack.add(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                # Unvisited node: safe to traverse
                acyclic_graph[node].append(neighbor)
                dfs(neighbor)
            elif neighbor in recursion_stack:
                # Node is in our current path: this is a back-edge (cycle!)
                removed_edges.append((node, neighbor))
            else:
                # Visited node, but not in current path: forward or cross edge (safe)
                acyclic_graph[node].append(neighbor)

        # Remove the node from the current path as we backtrack
        recursion_stack.remove(node)

    # Run DFS over all nodes to handle disconnected subgraphs
    for node in list(acyclic_graph.keys()):
        if node not in visited:
            dfs(node)

    return acyclic_graph, removed_edges

def topo_sort(graph: Dict[str, List[str]]) -> List[str]:
    """ Define a topological order over the acyclic graph

        Args:
            graph: an acyclic dependency graph

        Return:
            an topologically ordered list of node. This toppological order allows for parrallel processing of nodes in the same group
    """

    acyclic_graph, removed_edges = resolve_cycles(graph)

    out_degrees = {node: len(acyclic_graph[node]) for node in acyclic_graph}
    
    queue = deque([node for node in out_degrees if out_degrees[node] == 0])
    next_queue = deque([])

    result = [list(queue)]

    counter = 1

    while queue:
        node = queue.popleft()
        

        for dependent, deps in acyclic_graph.items():
            if node in deps:
                out_degrees[dependent] -= 1
                if out_degrees[dependent] == 0:
                    next_queue.append(dependent)
        
        if not queue:
            # If the current parrallel group is finished processing, move to the next group
            queue = next_queue
            if queue:
                result.append(list(queue))
                next_queue = deque([])
                counter += 1

    if sum(len(group) for group in result) != len(acyclic_graph):
        logger.warning("Topological sort failed: graph has cycles that weren't resolved")
        # Return all nodes in some order to avoid breaking the process
        print(result)
        print(sum(len(group) for group in result), len(acyclic_graph))
        return list(acyclic_graph.keys())
    
    # Reverse the result to get dependencies first
    return result

def graph_from_components(components: List[CodeComponent]) -> Dict[str, List[str]]:
    graph = {}
    for id, component in components.items():
        graph[id] = component.depends_on
    return graph



# # Graph with cycles: A->B->C->A and C->D->C
# original_graph = {
#     "A": ["B"],
#     "B": ["C"],
#     "C": ["A", "D"],
#     "D": ["C", "E"],
#     "E": []
# }
# # acyclic_graph, removed_edges = resolve_cycles(original_graph)
# topo_list = topo_sort(original_graph)
# # print(acyclic_graph, removed_edges)
# print(topo_list)
