import json
from typing import Dict, Any, Optional
from ...utils.match import match_param
import os


def merge_docs_into_openapi(
    generated_docs_path: str,
    openapi_spec_path: str,
    traces_path: str,
    function_mapping_path: str = None,
    output_path: str = None,
    module_path_separator: Optional[str] = "__",
    variant_separator: Optional[str] = "-",
) -> Dict[str, Any]:
    with open(generated_docs_path, "r") as f:
        generated_docs = json.load(f)

    with open(openapi_spec_path, "r") as f:
        openapi_spec = json.load(f)

    with open(traces_path, "r") as f:
        traces = json.load(f)

    with open(function_mapping_path, "r") as f:
        function_mapping = json.load(f)

    schemas = openapi_spec["components"]["schemas"]
    schema_dict = {}
    for schema_name in schemas:
        schema = schema_name
        schema = schema.split(variant_separator)[0]
        schema = schema.split(module_path_separator)
        schema = ".".join(schema)
        if schema not in schema_dict:
            schema_dict[schema] = [schema_name]
        else:
            schema_dict[schema].append(schema_name)

    # Track statistics
    stats = {
        "number of endpoints in static docs:": len(openapi_spec["paths"]),
        "number of endpoint methods in static docs:": sum(len(methods) for methods in openapi_spec["paths"].values()),
        "total_components": len(generated_docs),
        "endpoint_methods_processed": 0,
        "endpoint_methods_added": 0,
        "endpoint_methods_not_found": [],
        "number of schemas in static docs:": len(openapi_spec["components"]["schemas"]),
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
        file_path = traces.get(component_id, {}).get("file", None)

        if endpoints:
            stats["endpoint_methods_processed"] += len(endpoints)

            for endpoint_key, doc_text in endpoints.items():
                method, path = endpoint_key.split(":")

                openapi_path_dict = openapi_spec["paths"].get(path, None)
                openapi_path = (
                    openapi_path_dict.get(method, None) if openapi_path_dict else None
                )

                if not openapi_path:
                    stats["endpoint_methods_not_found"].append(
                        {
                            "component": component_id,
                            "endpoint": endpoint_key,
                            "reason": f"Method '{method.upper()}' not found for path '{path}'",
                        }
                    )
                    continue

                openapi_path["description"] = doc_text

                if "x-trace" not in openapi_path:
                    openapi_path["x-trace"] = {}
                openapi_path["x-trace"]["start_line"] = start_line
                openapi_path["x-trace"]["end_line"] = end_line
                openapi_path["x-trace"]["file"] = file_path
                stats["endpoints_added"] += 1

                stats["endpoint_methods_added"] += 1

                

        if schema:
            schema_object = schema_dict.get(component_id, None)
            
            if schema_object is None:
                name = component_id.split(".")[-1]
                schema_object = schema_dict.get(name, None)

            if not schema_object:
                stats["schemas_not_found"].append(
                    {
                        "component": component_id,
                        "reason": f"Component schema {component_id} not found in OpenAPI",
                    }
                )
                continue

            for schema_path in schema_object:
                openapi_path = openapi_spec["components"]["schemas"].get(schema_path, None)

                openapi_path["description"] = schema
                if "x-trace" not in openapi_path:
                    openapi_path["x-trace"] = {}
                openapi_path["x-trace"]["start_line"] = start_line
                openapi_path["x-trace"]["end_line"] = end_line
                openapi_path["x-trace"]["file"] = file_path
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
                            if "x-trace" not in param:
                                param["x-trace"] = {}
                            param["x-trace"] = {
                                "start_line": start_line,
                                "end_line": end_line,
                                "file": file_path,
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
                            if "x-trace" not in param:
                                param["x-trace"] = {}
                            param["x-trace"] = {
                                "start_line": start_line,
                                "end_line": end_line,
                                "file": file_path,
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
