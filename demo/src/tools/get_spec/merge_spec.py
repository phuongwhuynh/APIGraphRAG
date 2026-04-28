import json
from typing import Dict, Any, Optional


def merge_docs_into_openapi(
    generated_docs_path: str,
    openapi_spec_path: str,
    output_path: str = None,
    module_path_separator: Optional[str] = "__",
    variant_separator: Optional[str] = "-",
) -> Dict[str, Any]:
    with open(generated_docs_path, "r") as f:
        generated_docs = json.load(f)

    with open(openapi_spec_path, "r") as f:
        openapi_spec = json.load(f)

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

    print("schema dictionary", len(schema_dict))

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
    }

    for component_id, doc_data in generated_docs.items():
        endpoints = doc_data.get("endpoint", {})
        schema = doc_data.get("schema", "")

        if endpoints:
            stats["endpoint_methods_processed"] += len(endpoints)

            for endpoint_key, doc_text in endpoints.items():
                method, path = endpoint_key.split(":")

                openapi_path = openapi_spec["paths"].get(path, None).get(method, None)

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
                stats["schemas_added"] += 1

    

    with open(output_path, "w") as f:
        json.dump(openapi_spec, f, indent=2)

    return stats
