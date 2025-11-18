import networkx as nx

G = nx.Graph()

G.add_node(
    "Python", info="A high-level programming language for general-purpose programming."
)
G.add_node("NumPy", info="A library for numerical computing in Python.")
G.add_node("Pandas", info="A library for data analysis in Python.")
G.add_node("Machine Learning", info="A field of AI focused on learning from data.")
G.add_node("TensorFlow", info="An ML library developed by Google.")

G.add_edges_from(
    [
        ("Python", "NumPy"),
        ("Python", "Pandas"),
        ("Python", "TensorFlow"),
        ("TensorFlow", "Machine Learning"),
    ]
)


def graph_retrieve(query: str, graph: nx.Graph, max_depth: int = 2) -> set:
    relevant_nodes = [node for node in graph.nodes if query.lower() in node.lower()]
    visited = set(relevant_nodes)

    for node in relevant_nodes:
        for neighbor in nx.single_source_shortest_path_length(
            graph, node, cutoff=max_depth
        ):
            visited.add(neighbor)
    return visited


print(graph_retrieve("what is Python", G))
