import json
import os
import gc
from typing import List, Literal
from tqdm.auto import tqdm
from pathlib import Path

# import psutil
import shutil
from src.dependency_analyzer.ast_parser import DependencyParser
from src.dependency_analyzer.topo_sort import topo_sort, graph_from_components
from src.llm.rank import Ranker, CodeComponent
from src.llm.cot import CoT

# from src.llm.searcher import Searcher
from src.llm.generate import Generator
from src.database.storage import Storage
from langchain_core.runnables import RunnableConfig
from src.tools.get_spec.merge_spec import merge_docs_into_openapi
from src.tools.json.json import save_as_json, load_json


CURRENT_PATH = Path(__file__)
REPO_DIR = CURRENT_PATH.parent.parent / "data" / "dispatch"
OUTPUT_DIR = CURRENT_PATH.parent / "output"
OPENAPI_SPEC_PATH = OUTPUT_DIR / REPO_DIR.name
RESULTED_OPENAPI_SPEC_PATH = OUTPUT_DIR / ("resulted_" + REPO_DIR.name)
RANK_OUTPUT_FILEPATH = OUTPUT_DIR / "rank_output.json"
COT_OUTPUT_FILEPATH = OUTPUT_DIR / "cot_output.json"
GENERATE_OUTPUT_FILEPATH = OUTPUT_DIR / "generate_output.json"
TRACES_OUTPUT_FILEPATH = OUTPUT_DIR / "traces_output.json"


def generate_docs(
    components: List[CodeComponent], cot: CoT, rank: Ranker, generate: Generator
):
    """Simutaneously generate docs for components through simple straight pipeline: Context Analysis (rank) -> Context Retrieval (Searcher) -> Document Generation (generate)
    Args:
        components: target components to be documneted"""

    # Return the dictionary context analysis, the analysis is returned as dict with hierarchy: component.id -> "docstring"/"endpoint"/"schema" -> ComponentContext(reasoning, context, suggested_misisng_info)
    chain_of_thoughts = cot.invoke(components)
    save_as_json(file_path=COT_OUTPUT_FILEPATH, data=chain_of_thoughts)
    ranks = rank.invoke(components, chain_of_thoughts)
    save_as_json(file_path=RANK_OUTPUT_FILEPATH, data=ranks)

    # chain_of_thoughts = load_json(COT_OUTPUT_FILEPATH)
    # ranks = load_json(RANK_OUTPUT_FILEPATH)

    result = generate.invoke(
        components=components,
        #  cots=chain_of_thoughts,
        ranks=ranks,
    )
    docs = result["workflow_docs"]
    traces = result["workflow_traces"]
    save_as_json(file_path=GENERATE_OUTPUT_FILEPATH, data=docs)
    save_as_json(file_path=TRACES_OUTPUT_FILEPATH, data=traces)
    return


if __name__ == "__main__":
    # if OUTPUT_DIR.exists():
    #     shutil.rmtree(OUTPUT_DIR)

    db_storage = Storage("dependency_graph.db")
    db_storage._init_db()

    rank_model = "llama3.2:3b"
    rank_model_provider = "openai"
    cot_model = "llama3.2:3b"
    cot_model_provider = "ollama"
    generate_model = "llama3.2:3b"
    generate_model_provider = "ollama"

    # Build dependency graph
    dependencyParser = DependencyParser(
        framework="fastapi",
        project_dir=REPO_DIR,
        output_dir=OUTPUT_DIR,
        app_instance_path="src.dispatch.main:api",
        python_exec=REPO_DIR / "venv" / "bin" / "python",
        compose_file=REPO_DIR / ".devcontainer" / "docker-compose.yml",
        service_name="app",
        excluded_dirs=["tests", "src/dispatch/database/revisions"],
    )
    dependencyParser.parse_repository()

    dependencyParser.save_dependency_graph(db_storage)
    del dependencyParser
    gc.collect()

    # Determine the traversal order on the graph
    repo_graph = graph_from_components(db_storage.get_all_topologies())
    topo_order = topo_sort(repo_graph)

    del repo_graph
    gc.collect()

    # Initialize specialized models
    cot = CoT(
        model=cot_model,
        model_provider=cot_model_provider,
        input_context_window=4096,
        output_context_window=1024,
        output_dir=OUTPUT_DIR,
    )

    rank = Ranker(
        model=rank_model,
        model_provider=rank_model_provider,
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        max_tokens=1,
        logprobs=True,
        top_logprobs=10,
        input_context_window=4096,
        output_context_window=1024,
        output_dir=OUTPUT_DIR,
        window_size=10,
        step=5,
        top_k=10,
    )

    # searcher = Searcher(db_storage)

    generate = Generator(
        model=generate_model,
        model_provider=generate_model_provider,
        input_context_window=4096,
        output_context_window=1024,
        db_conn=db_storage,
        output_dir=OUTPUT_DIR,
    )

    # Traverse according to the order and generate the docs
    total_files = sum(len(group) for group in topo_order)

    with tqdm(total=total_files, desc="Generating document") as pbar:
        for group in topo_order:

            # Process components in batches of max 5
            for i in range(0, len(group), 5):
                batch = group[i : i + 5]
                batch = db_storage.get_batch(batch)
                # print("The components number in batch: ", len(batch), type(batch[0]))

                generate_docs(components=batch, cot=cot, rank=rank, generate=generate)

                pbar.update(len(batch))

    # merge_docs_into_openapi(
    #     GENERATE_OUTPUT_FILEPATH,
    #     OPENAPI_SPEC_PATH.with_suffix(".json"),
    #     RESULTED_OPENAPI_SPEC_PATH.with_suffix(".json"),
    # )