import json
import os
from typing import List, Literal
from tqdm.auto import tqdm
from pathlib import Path
# import psutil
import shutil
from src.dependency_analyzer.ast_parser import DependencyParser
from src.dependency_analyzer.topo_sort import topo_sort, graph_from_components
from src.agent.reader import Reader, CodeComponent
from src.agent.searcher import Searcher
from src.agent.writer import Writer
from langchain_core.runnables import RunnableConfig


CURRENT_PATH = Path(__file__)
REPO_DIR = CURRENT_PATH.parent.parent / "data" / "dispatch"
OUTPUT_DIR = CURRENT_PATH.parent / "output"
READER_OUTPUT_FILEPATH = OUTPUT_DIR / "reader_output.json"
SEARCHER_OUTPUT_FILEPATH = OUTPUT_DIR / "searcher_output.json"
WRITER_OUTPUT_FILEPATH = OUTPUT_DIR / "writer_output.json"

# def calculate_dynamic_concurrency(ram_per_worker: float) -> int:
#     """Calculates safe parallel workers based on system hardware."""
    
#     # Check available CPU Cores
#     total_cores = os.cpu_count() or 1
    
#     # Check available RAM (in Gigabytes)
#     free_ram_gb = psutil.virtual_memory().available / (1024 ** 3)
    
#     # to handle the context window during parallel generation.
#     ram_based_workers = int(free_ram_gb // ram_per_worker)
    
#     # 4. Pick the safest number: At least 1, but don't exceed your CPU cores or RAM limits.
#     safe_concurrency = max(1, min(ram_based_workers, total_cores - 1))
    
#     print(f"Hardware Check: {free_ram_gb:.1f}GB free RAM, {total_cores} cores.")
#     print(f"Dynamically setting max_concurrency to: {safe_concurrency}")
    
#     return safe_concurrency

# # Apply it to your LangGraph config dynamically
# config: RunnableConfig = {
#     "max_concurrency": calculate_dynamic_concurrency(2.0)
# }

def print_dict(d):
    """A function to print nested dictionary"""
    if isinstance(d, dict):
        for key, value in d.items():
            print(key)
            print_dict(value)
    else:
        print(d)

def save_as_json(file_path: str, data: dict) -> None:
    """Save or merge dictionary data to a json file"""
    # 1. Handle Path objects natively
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Merge with existing data if it exists
    if file_path.exists():
        existing_data = load_json(file_path) or {}
        # Merge dictionaries. In Python 3.9+, you can use the | operator. 
        # It creates a new dict with updated values.
        merged_data = existing_data | data
    else:
        merged_data = data

    # 3. Write securely
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=2)

def load_json(file_path: str) -> dict:
    """Load data from a json file securely"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {} # Return empty dict if file doesn't exist yet
    except json.JSONDecodeError:
        print(f"File {file_path} is corrupted or empty. Returning empty dict.")
        return {}
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return {}

def generate_docs(components: List[CodeComponent], reader: Reader, searcher: Searcher, writer: Writer):
    """ Simutaneously generate docs for components through simple straight pipeline: Context Analysis (Reader) -> Context Retrieval (Searcher) -> Document Generation (Writer)
        Args:
            components: target components to be documneted"""

    # Return the dictionary context analysis, the analysis is returned as dict with hierarchy: component.id -> "docstring"/"endpoint"/"schema" -> ComponentContext(reasoning, context, suggested_misisng_info)
    context_analysis = reader.invoke(components)

    save_as_json(file_path= READER_OUTPUT_FILEPATH, data = context_analysis)
    # context_analysis = load_json(file_path=READER_OUTPUT_FILEPATH)

    # Retrieve the context data as a dict with hierarchy: component.id -> "docstring"/"openapi" -> "high_importance"/ "medium_importance"/ "low_importance"/ "suggested_missing_info" -> List[str]
    context_retrieval = searcher.invoke(context_analysis)
    save_as_json(file_path= SEARCHER_OUTPUT_FILEPATH, data = context_retrieval)


    # generated_docs, schemas = writer.invoke(components, context_retrieval, type_doc)
    docs = writer.invoke(components=components, contexts= context_retrieval)
    save_as_json(file_path= WRITER_OUTPUT_FILEPATH, data= docs)

    return

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)

reader_model = "llama3.2:3b"
reader_model_provider = "ollama"
writer_model = "llama3.2:3b"
writer_model_provider = "ollama"
config: RunnableConfig = {
    "max_concurrency": 1
}


# Build dependency graph
dependencyParser = DependencyParser(framework="fastapi",
                                    project_dir=REPO_DIR,
                                    output_dir=OUTPUT_DIR,
                                    app_instance_path="src.dispatch.main:api",
                                    python_exec="/Users/phuocpham/Desktop/BachPhuoc/Year4/DoAn/SelfDocAgent/data/dispatch/venv/bin/python",
                                    compose_file= REPO_DIR / ".devcontainer" / "docker-compose.yml",
                                    service_name="app",
                                    excluded_dirs=["tests", "src/dispatch/database/revisions"]
                                    )
dependencyParser.parse_repository()

print(f"\n\nAPI endpoints: {len(dependencyParser.endpoints.endpoints)}")#,dependencyParser.endpoints.endpoints)
print(f"\n\nAPI schemas: {len(dependencyParser.endpoints.schemas)}")#,dependencyParser.endpoints.schemas)

dependencyParser.save_dependency_graph("output/dependency_graph.json")

# Determine the traversal order on the graph
repo_graph = graph_from_components(dependencyParser.components)
topo_order = topo_sort(repo_graph)
#print("Topological order of components:" , topo_order)


# Initialize specialized models
reader = Reader(model= reader_model, 
                model_provider= reader_model_provider, 
                input_context_window= 4096,
                output_context_window= 1024,
                config= config)

searcher = Searcher(dependencyParser.components)

writer = Writer(model= writer_model, 
                model_provider= writer_model_provider, 
                input_context_window= 4096,
                output_context_window= 1024,
                config= config)



# Traverse according to the order and generate the docs
total_files = sum(len(group) for group in topo_order)

with tqdm(total=total_files, desc="Generating document") as pbar:
    for group in topo_order:
        components = [dependencyParser.components[component] for component in group]
        
        # Process components in batches of max 5
        for i in range(0, len(components), 5):
            batch = components[i:i + 5]
            print("The components number in batch: ", len(batch))

            generate_docs(components=batch,
                          reader=reader,
                          searcher=searcher,
                          writer=writer)
            
            pbar.update(len(batch))


