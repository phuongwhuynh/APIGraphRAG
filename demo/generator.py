# generator.py
import json
import ollama
from graph import CodeGraph
from prompts import SCHEMA_PROMPT, PATH_PROMPT, FUNCTION_PROMPT
from resolver import detect_dynamic_usage


def read_source(node):
    with open(node.file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[node.start - 1: node.end])


def generate(graph: CodeGraph, model: str, out_dir: str):
    order = graph.execution_plan()

    for name in order:
        node = graph.nodes[name]
        source = read_source(node)

        dependency_docs = []
        for dep in graph.edges.get(name, []):
            dep_node = graph.nodes.get(dep)
            if dep_node and dep_node.artifact_path:
                with open(dep_node.artifact_path) as f:
                    dependency_docs.append(json.load(f))

        payload = {
            "source": source,
            "dependencies": dependency_docs,
            "meta": node.meta,
            "dynamic_lines": detect_dynamic_usage(source)
        }

        system_prompt = (
            SCHEMA_PROMPT if node.kind == "schema"
            else PATH_PROMPT if node.kind == "route"
            else FUNCTION_PROMPT
        )
        
        print(f"  [{node.kind.upper()}] Generating artifact for '{name}'...")

        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)}
            ],
            format="json",
            options={"temperature": 0}
        )

        artifact = json.loads(response["message"]["content"])
        subdir = "schemas" if node.kind == "schema" else "paths" if node.kind == "route" else "functions"
        out_path = f"{out_dir}/{subdir}/{name}.json"

        if node.kind == "route":
            artifact["_PATH_"] = node.meta["path"]

        
        with open(out_path, "w") as f:
            json.dump(artifact, f, indent=2)

        node.artifact_path = out_path
