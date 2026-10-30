from pathlib import Path
from src.openapi.merge_spec import merge_docs_into_openapi
from src.utils.json_io import save_as_json, load_json
from src.evaluation.bartscore_evaluate import TraditionalEvaluator
from src.evaluation.llm_evaluate import LLMEvaluator
from src.evaluation.openapi_stats_evaluate import OpenAPIStatsEvaluator
from src.database.storage import Storage
from tqdm.auto import tqdm

CURRENT_PATH = Path(__file__)
REPO_DIR = CURRENT_PATH.parent.parent / "data" / "dispatch"
OUTPUT_DIR = CURRENT_PATH.parent / "output"
OPENAPI_SPEC_PATH = OUTPUT_DIR / REPO_DIR.name
RESULTED_OPENAPI_SPEC_PATH = OUTPUT_DIR / ("resulted_" + REPO_DIR.name)
RANK_OUTPUT_FILEPATH = OUTPUT_DIR / "rank_output.json"
COT_OUTPUT_FILEPATH = OUTPUT_DIR / "cot_output.json"
GENERATE_OUTPUT_FILEPATH = OUTPUT_DIR / "generate_output.json"
TRACES_OUTPUT_FILEPATH = OUTPUT_DIR / "traces_output.json"
FUNCTION_MAPPING_PATH = OUTPUT_DIR / (REPO_DIR.name + "_map.json")

# merge_docs_into_openapi(
#     generated_docs_path=GENERATE_OUTPUT_FILEPATH,
#     openapi_spec_path=OPENAPI_SPEC_PATH.with_suffix(".json"),
#     output_path=RESULTED_OPENAPI_SPEC_PATH.with_suffix(".json"),
#     traces_path=TRACES_OUTPUT_FILEPATH,
#     function_mapping_path=FUNCTION_MAPPING_PATH,
# )

stats_evaluator = OpenAPIStatsEvaluator(
    file_path=RESULTED_OPENAPI_SPEC_PATH.with_suffix(".json"), output_dir=OUTPUT_DIR
)
print(stats_evaluator.evaluate())

docstring_evaluate = False
evaluator_model = "qwen2.5-coder:7b"
evaluator_model_provider = "openai"

llm_evaluator = LLMEvaluator(
    model=evaluator_model,
    model_provider=evaluator_model_provider,
    api_key="ollama",
    base_url="http://localhost:11434/v1",
    input_context_window=4096,
    output_context_window=1024,
    output_dir=OUTPUT_DIR,
    docstring_evaluate=docstring_evaluate,
)


# bartscore_evaluator = TraditionalEvaluator(
#     OUTPUT_DIR, docstring_evaluate=docstring_evaluate
# )


db_storage = Storage("dependency_graph.db")


generated_docs = load_json(GENERATE_OUTPUT_FILEPATH)


for component_id, component_docs in generated_docs.items():
    component_docs["source_code"] = (db_storage.get(component_id)).source_code

total_components = len(generated_docs)

with tqdm(total=total_components, desc="Evaluating document") as pbar:
    batch = {}
    for compoent_id, component_doc in generated_docs.items():
        batch[compoent_id] = component_doc
        if len(batch) < 2:
            continue
        elif len(batch) == 2:
            # result = bartscore_evaluator.evaluate(batch)
            result = llm_evaluator.invoke(batch)
            pbar.update(len(batch))
            batch = {}

    if batch:
        # result = bartscore_evaluator.evaluate(batch)
        result = llm_evaluator.invoke(batch)
        print(result)
        pbar.update(len(batch))

# print(bartscore_evaluator.show_statistic())
