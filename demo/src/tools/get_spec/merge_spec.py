import json
from typing import Dict, Any
from ...utils.match import match_param
import os


def merge_docs_into_openapi(
    generated_docs_path: str,
    traces_path: str,
    openapi_spec_path: str,
    function_mapping_path: str = None,
    output_path: str = None,
) -> Dict[str, Any]:
    with open(generated_docs_path, "r") as f:
        generated_docs = json.load(f)

    with open(traces_path, "r") as f:
        traces = json.load(f)

    with open(openapi_spec_path, "r") as f:
        openapi_spec = json.load(f)

    with open(function_mapping_path, "r") as f:
        function_mapping = json.load(f)

    # Track statistics
    stats = {
        "total_components": len(generated_docs),
        "endpoints_processed": 0,
        "endpoints_added": 0,
        "endpoints_not_found": [],
        "schemas_processed": 0,
        "schemas_added": 0,
        "schemas_not_found": [],
        "parameters_processed": 0,
        "parameters_added": 0,
        "parameters_not_found": [],
    }

    for component_id, doc_data in generated_docs.items():
        endpoints = doc_data.get("endpoint", {})
        schema = doc_data.get("schema", "")
        path_param = doc_data.get("path_parameter", "")
        query_param = doc_data.get("query_parameter", "")
        start_line = traces.get(component_id, {}).get("start_line", None)
        end_line = traces.get(component_id, {}).get("end_line", None)

        if endpoints:
            stats["endpoints_processed"] += len(endpoints)

            for endpoint_key, doc_text in endpoints.items():
                method, path = endpoint_key.split(":")

                openapi_path_dict = openapi_spec["paths"].get(path, None)
                openapi_path = (
                    openapi_path_dict.get(method, None) if openapi_path_dict else None
                )

                if not openapi_path:
                    stats["endpoints_not_found"].append(
                        {
                            "component": component_id,
                            "endpoint": endpoint_key,
                            "reason": f"Method '{method.upper()}' not found for path '{path}'",
                        }
                    )
                    continue

                openapi_path["description"] = doc_text
                if "x-traces" not in openapi_path:
                    openapi_path["x-traces"] = {}
                openapi_path["x-traces"]["start_line"] = start_line
                openapi_path["x-traces"]["end_line"] = end_line
                stats["endpoints_added"] += 1

        if schema:
            schema_name = (component_id.split("."))[-1]
            stats["schemas_processed"] += 1

            openapi_path = openapi_spec["components"]["schemas"].get(schema_name, None)

            if not openapi_path:
                stats["schemas_not_found"].append(
                    {
                        "component": component_id,
                        "reason": f"Component schema {schema_name} not found in OpenAPI",
                    }
                )
                continue

            openapi_path["description"] = schema
            if "x-traces" not in openapi_path:
                openapi_path["x-traces"] = {}
            openapi_path["x-traces"]["start_line"] = start_line
            openapi_path["x-traces"]["end_line"] = end_line
            stats["schemas_added"] += 1

        if path_param or query_param:
            stats["parameters_processed"] += 1
            endpoint_id, param_name = component_id.rsplit(".", 1)
            endpoints = []
            for endpoint_key, id_list in function_mapping.items():
                if endpoint_id in id_list:
                    endpoints.append(endpoint_key)

            if len(endpoints) == 0:
                stats["parameters_not_found"].append(
                    {
                        "component": component_id,
                        "reason": f"Parent endpoint for parameter not found in function mapping",
                    }
                )
                continue
            for endpoint_key in endpoints:
                method, path = endpoint_key.split(":")
                openapi_path_dict = openapi_spec["paths"].get(path, None)
                openapi_path = (
                    openapi_path_dict.get(method, None) if openapi_path_dict else None
                )
                if not openapi_path:
                    continue

                added = False
                if path_param:
                    for param in openapi_path.get("parameters", []):
                        if param["in"] == "path" and match_param(
                            param_name, [param["name"]]
                        ):
                            param["description"] = path_param
                            if "x-traces" not in param:
                                param["x-traces"] = {}
                            param["x-traces"] = {
                                "start_line": start_line,
                                "end_line": end_line,
                            }
                            stats["parameters_added"] += 1
                            added = True
                            break
                else:
                    for param in openapi_path.get("parameters", []):
                        if param["in"] == "query" and match_param(
                            param_name, [param["name"]]
                        ):
                            param["description"] = query_param
                            if "x-traces" not in param:
                                param["x-traces"] = {}
                            param["x-traces"] = {
                                "start_line": start_line,
                                "end_line": end_line,
                            }
                            stats["parameters_added"] += 1
                            added = True
                            break
                if not added:
                    stats["parameters_not_found"].append(
                        {
                            "component": component_id,
                            "reason": f"Parameter '{param_name}' not found in OpenAPI for endpoint '{endpoint_key}'",
                        }
                    )

    with open(output_path, "w") as f:
        json.dump(openapi_spec, f, indent=2)
    print(f"Merged OpenAPI spec saved to {output_path}")
    stats_path = os.path.join(os.path.dirname(output_path), "merge_stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
