# main.py
import os
from graph import CodeGraph
from extractor import extract
from generator import generate
from assembler import assemble_openapi

INPUT_DIR = "/project_dir/"
OUTPUT_DIR = "generated"
MODEL = "llama3"

os.makedirs(f"{OUTPUT_DIR}/schemas", exist_ok=True)
os.makedirs(f"{OUTPUT_DIR}/paths", exist_ok=True)
os.makedirs(f"{OUTPUT_DIR}/functions", exist_ok=True)

graph = CodeGraph()


extract(INPUT_DIR, graph)
# for node in graph.nodes.values():
#     print(f"Node: {node.name}, Kind: {node.kind}")
generate(graph, MODEL, OUTPUT_DIR)

assemble_openapi(
    title="Auto Generated API",
    version="1.0.0",
    schema_dir=f"{OUTPUT_DIR}/schemas",
    path_dir=f"{OUTPUT_DIR}/paths",
    output_file=f"{OUTPUT_DIR}/openapi.json"
)

print("OpenAPI generation complete.")
