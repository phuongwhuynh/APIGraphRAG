import networkx as nx
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client()

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


def graph_retrieve(content: str, graph: nx.Graph, max_depth: int = 2) -> set:
    relevant_nodes = [node for node in graph.nodes if content.lower() in node.lower()]
    visited = set(relevant_nodes)

    for node in relevant_nodes:
        for neighbor in nx.single_source_shortest_path_length(
            graph, node, cutoff=max_depth
        ):
            visited.add(neighbor)
    return visited


def answer_query(content: str, query: str, graph: nx.Graph) -> str:
    relevant_nodes = graph_retrieve(content, graph)
    context = "\n".join(
        f"{node}: {graph.nodes[node]['info']}" for node in relevant_nodes
    )

    prompt = f"Using the following context, answer the question:\n\nContext:\n{context}\n\nQuestion: {query}\nAnswer:"
    print("Prompt:", prompt)

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        ),
    )
    return response.text


print(answer_query("python", "How is Python related to machine learning?", G))
