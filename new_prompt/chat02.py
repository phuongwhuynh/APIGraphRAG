import os
import json
import sys
import argparse
from prompt_template import SYSTEM_PROMPT_COMPONENT, SYSTEM_PROMPT_PATH
from graph_rag import CodeGraph
from parser import parse_directory
from llm import query_ollama, get_model_context_limit, ensure_model_downloaded

# --- CLI ARGUMENT SETUP ---
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Auto-generate OpenAPI Documentation using Local LLMs."
    )
    parser.add_argument(
        "input_dir", 
        type=str, 
        help="Path to the root directory of your Python repository."
    )
    parser.add_argument(
        "--model", 
        type=str, 
        default="llama3", 
        help="Name of the Ollama model to use (default: llama3)."
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="generated_docs", 
        help="Directory to save the generated JSON files (default: generated_docs)."
    )
    return parser.parse_args()

# --- MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
    args = parse_arguments()

    # --- CONFIGURATION ---
    INPUT_DIR = args.input_dir
    OUTPUT_DIR = args.output
    MODEL_NAME = args.model
    
    SCHEMAS_DIR = os.path.join(OUTPUT_DIR, "components", "schemas")
    PATHS_DIR = os.path.join(OUTPUT_DIR, "paths")

    # Validate Input
    if not os.path.exists(INPUT_DIR):
        print(f" Error: Input directory '{INPUT_DIR}' does not exist.")
        sys.exit(1)

    # Ensure Output Directories
    os.makedirs(SCHEMAS_DIR, exist_ok=True)
    os.makedirs(PATHS_DIR, exist_ok=True)

    print(f" Starting OpenAPI Generator")
    print(f"   Input: {INPUT_DIR}")
    print(f"   Model: {MODEL_NAME}")
    print(f"   Output: {OUTPUT_DIR}\n")

    # --- 1. MODEL PREPARATION ---
    # This step is critical: It will attempt to pull the model if it's missing.
    # The updated logic in llm.py handles the list parsing more safely now.
    if not ensure_model_downloaded(MODEL_NAME):
        print(" Critical Error: Model could not be loaded.")
        print("   Please check if 'ollama serve' is running and you have internet access.")
        sys.exit(1)

    print(f"  Detecting Context Window for {MODEL_NAME}...")
    CTX_LIMIT = get_model_context_limit(MODEL_NAME)
    print(f"   Detected Window: {CTX_LIMIT} tokens")

    # --- 2. PARSE REPOSITORY ---
    graph = CodeGraph()
    parse_directory(INPUT_DIR, graph)

    # --- 3. EXECUTION PLAN ---
    execution_order = graph.get_execution_order()
    print(f" Execution Plan: {len(execution_order)} nodes identified.")

    # --- 4. GENERATION LOOP ---
    def generate_component(class_name, node_data, ctx_limit):
        source_code = graph.fetch_source_code(class_name)
        print(f"[{class_name}] Building Schema...")
        
        context_data = graph.get_related_context_content(class_name)
        
        inheritance_context = ""
        # Access 'inherits' safely using the defaultdict logic from graph_rag
        if context_data.get("inherits"):
            inheritance_context = "INHERITANCE CONTEXT:\n"
            for item in context_data["inherits"]:
                if item['doc']:
                    inheritance_context += f"- Parent {item['name']} Schema:\n{json.dumps(item['doc'])}\n"
                else:
                    inheritance_context += f"- Parent {item['name']} Code:\n{item['code']}\n"

        user_prompt = f"Generate OpenAPI Schema for class '{class_name}'.\nSOURCE CODE:\n{source_code}\n{inheritance_context}"
        
        return query_ollama(MODEL_NAME, SYSTEM_PROMPT_COMPONENT, user_prompt, context_data="", max_ctx=ctx_limit)

    def generate_path(route_name, node_data, ctx_limit):
        source_code = graph.fetch_source_code(route_name)
        path_str = node_data.get('http_method', '').upper() + " " + (node_data.get('path') or "")
        print(f"  [{path_str}] Building Path...")
        
        context_data = graph.get_related_context_content(route_name)
        
        returns_context = ""
        known_components = []
        
        if context_data.get("returns"):
            returns_context = "RETURN MODELS:\n"
            for item in context_data["returns"]:
                known_components.append(item['name'])
                if item['doc']:
                    returns_context += f"- Model {item['name']} (Generated):\n{json.dumps(item['doc'])}\n"
                else:
                    returns_context += f"- Model {item['name']} (Raw Code):\n{item['code']}\n"

        user_prompt = (
            f"Generate OpenAPI Path Item for route '{route_name}'.\n"
            f"SOURCE CODE:\n{source_code}\n"
            f"--- CONTEXT ---\n{returns_context}\n"
            f"Available Components for $ref: {known_components}"
        )
        
        return query_ollama(MODEL_NAME, SYSTEM_PROMPT_PATH, user_prompt, context_data="", max_ctx=ctx_limit)

    # Iterate Graph
    for node_name in execution_order:
        node = graph.nodes[node_name]
        result = None
        file_path = None
        
        if node["type"] == "class":
            result = generate_component(node_name, node, CTX_LIMIT)
            if result:
                file_path = os.path.join(SCHEMAS_DIR, f"{node_name}.json")
                
        elif node["type"] == "route":
            result = generate_path(node_name, node, CTX_LIMIT)
            if result:
                safe_name = f"{node_name}.json"
                file_path = os.path.join(PATHS_DIR, safe_name)

        if result and file_path:
            with open(file_path, "w") as f:
                json.dump(result, f, indent=2)
            graph.set_doc_path(node_name, file_path)

    # --- 5. FINAL ASSEMBLY ---
    print("\n Assembling Root Document...")

    all_schemas = {}
    all_paths = {}

    for name, data in graph.nodes.items():
        if data.get("generated_doc"):
            if data["type"] == "class":
                all_schemas[name] = { "$ref": f"./components/schemas/{name}.json" }
            elif data["type"] == "route" and data.get("path"):
                all_paths[data["path"]] = { "$ref": f"./paths/{name}.json" }

    root_doc = {
        "openapi": "3.1.0",
        "info": {"title": "GraphRAG Generated API", "version": "2.0"},
        "paths": all_paths,
        "components": {
            "schemas": all_schemas
        }
    }

    with open(os.path.join(OUTPUT_DIR, "openapi.json"), "w") as f:
        json.dump(root_doc, f, indent=2)

    print(f" Done. Open {os.path.join(OUTPUT_DIR, 'openapi.json')} in Swagger UI.")