# """
# Merge generated documentation into OpenAPI spec (dispatch.json)

# The generated docs have this structure:
# {
#   "component_id": {
#     "docstring": "...",
#     "endpoint": {
#       "GET:/{organization}/auth/me": "Generated documentation text",
#       "POST:/users": "..."
#     },
#     "schema": "..."
#   }
# }

# We merge these into dispatch.json by:
# 1. Parsing endpoint key format: "METHOD:/path"
# 2. Finding matching path and method in OpenAPI spec
# 3. Adding description field to the endpoint operation
# """

# import json
# from pathlib import Path
# from typing import Dict, Tuple, Any


# def parse_endpoint_key(endpoint_key: str) -> Tuple[str, str]:
#     """
#     Parse endpoint key format "METHOD:/path" into (method, path).
    
#     Example:
#         "GET:/{organization}/auth/me" -> ("get", "/{organization}/auth/me")
#     """
#     method, path = endpoint_key.split(":", 1)
#     return method.lower(), path


# def find_path_in_openapi(paths: Dict, target_path: str) -> Tuple[str, bool]:
#     """
#     Find exact or similar path in OpenAPI spec.
    
#     Returns:
#         (matched_path, is_exact_match)
#     """
#     # Try exact match first
#     if target_path in paths:
#         return target_path, True
    
#     # Try case-insensitive or partial match
#     for path_key in paths.keys():
#         if path_key.lower() == target_path.lower():
#             return path_key, True
    
#     return None, False


# def merge_docs_into_openapi(
#     generated_docs_path: str,
#     openapi_spec_path: str,
#     output_path: str = None
# ) -> Dict[str, Any]:
#     """
#     Merge generated documentation into OpenAPI spec.
    
#     Args:
#         generated_docs_path: Path to generate_output.json
#         openapi_spec_path: Path to dispatch.json
#         output_path: Path to save merged spec (default: dispatch_with_docs.json)
    
#     Returns:
#         The merged OpenAPI spec dictionary
#     """
    
#     # Load files
#     with open(generated_docs_path, 'r') as f:
#         generated = json.load(f)
    
#     with open(openapi_spec_path, 'r') as f:
#         openapi_spec = json.load(f)
    
#     # Track statistics
#     stats = {
#         "total_components": len(generated),
#         "endpoints_processed": 0,
#         "endpoints_added": 0,
#         "endpoints_not_found": [],
#     }
    
#     # Iterate through generated docs
#     for component_id, doc_data in generated.items():
#         endpoints = doc_data.get("endpoint", {})
        
#         if not endpoints:
#             continue
        
#         stats["endpoints_processed"] += len(endpoints)
        
#         # For each endpoint in this component
#         for endpoint_key, doc_text in endpoints.items():
#             method, path = parse_endpoint_key(endpoint_key)
            
#             # Find the path in OpenAPI spec
#             matched_path, found = find_path_in_openapi(openapi_spec["paths"], path)
            
#             if not found or not matched_path:
#                 stats["endpoints_not_found"].append({
#                     "component": component_id,
#                     "endpoint": endpoint_key,
#                     "reason": f"Path '{path}' not found in OpenAPI"
#                 })
#                 continue
            
#             # Check if method exists
#             if method not in openapi_spec["paths"][matched_path]:
#                 stats["endpoints_not_found"].append({
#                     "component": component_id,
#                     "endpoint": endpoint_key,
#                     "reason": f"Method '{method.upper()}' not found for path '{matched_path}'"
#                 })
#                 continue
            
#             # Add description to the endpoint operation
#             endpoint_op = openapi_spec["paths"][matched_path][method]
            
#             # Preserve existing summary if present, add description from generated docs
#             if "summary" not in endpoint_op:
#                 # If no summary, extract first line from doc as summary
#                 first_line = doc_text.split('\n')[0][:120]
#                 endpoint_op["summary"] = first_line
            
#             # Always add/update description
#             endpoint_op["description"] = doc_text
            
#             stats["endpoints_added"] += 1
#             print(f"✓ {method.upper()} {matched_path} - documented")
    
#     # Save merged spec
#     if output_path is None:
#         output_path = Path(openapi_spec_path).parent / "dispatch_with_docs.json"
    
#     with open(output_path, 'w') as f:
#         json.dump(openapi_spec, f, indent=2)
    
#     print("\n" + "="*60)
#     print("MERGE SUMMARY")
#     print("="*60)
#     print(f"Processed endpoints: {stats['endpoints_processed']}")
#     print(f"Successfully added: {stats['endpoints_added']}")
#     print(f"Not found: {len(stats['endpoints_not_found'])}")
    
#     if stats["endpoints_not_found"]:
#         print("\nEndpoints not found:")
#         for missed in stats["endpoints_not_found"][:5]:  # Show first 5
#             print(f"  - {missed['component']}: {missed['reason']}")
    
#     print(f"\nOutput saved to: {output_path}")
#     return openapi_spec


# if __name__ == "__main__":
#     # Example usage
#     generated_file = "output/generate_output.json"
#     dispatch_file = "output/dispatch.json"
#     output_file = "output/dispatch_with_docs.json"
    
#     merged_spec = merge_docs_into_openapi(
#         generated_docs_path=generated_file,
#         openapi_spec_path=dispatch_file,
#         output_path=output_file
#     )

from pathlib import Path
from src.tools.get_spec.merge_spec import merge_docs_into_openapi
from src.tools.json.json import save_as_json, load_json
from src.tools.evaluate.bartscore_evaluate import TraditionalEvaluator
from src.tools.evaluate.llm_evaluate import LLMEvaluator
from src.tools.evaluate.openapi_stats_evaluate import OpenAPIStatsEvaluator
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

merge_docs_into_openapi(GENERATE_OUTPUT_FILEPATH, OPENAPI_SPEC_PATH.with_suffix(".json"), RESULTED_OPENAPI_SPEC_PATH.with_suffix(".json"))

# stats_evaluator = OpenAPIStatsEvaluator(file_path=RESULTED_OPENAPI_SPEC_PATH, output_dir=OUTPUT_DIR)
# print(stats_evaluator.evaluate())


# evaluator_model = "llama3.2:3b"
# evaluator_model_provider = "openai"

# llm_evaluator = LLMEvaluator(model= evaluator_model, 
#                 model_provider= evaluator_model_provider, 
#                 api_key="ollama",
#                 base_url="http://localhost:11434/v1",
#                 input_context_window= 4096,
#                 output_context_window= 1024,
#                 output_dir= OUTPUT_DIR,)


# bartscore_evaluator = TraditionalEvaluator(OUTPUT_DIR)


# db_storage = Storage("dependency_graph.db")


# generated_docs = load_json(GENERATE_OUTPUT_FILEPATH)


# for component_id, component_docs in generated_docs.items():
#     component_docs["source_code"] = (db_storage.get(component_id)).source_code

# total_components = len(generated_docs)

# with tqdm(total=total_components, desc="Evaluating document") as pbar:
#     batch = {}
#     for compoent_id, component_doc in generated_docs.items():
#         batch[compoent_id] = component_doc
#         if len(batch) < 5:
#             continue
#         elif len(batch) == 5:     
#             result = bartscore_evaluator.evaluate(batch)
#             result = llm_evaluator.invoke(batch)
#             pbar.update(len(batch))
#             batch = {}
        
#     if batch:
#         result = bartscore_evaluator.evaluate(batch)
#         print(result)
#         pbar.update(len(batch))

# print(bartscore_evaluator.show_statistic())



    

