import json 
from typing import Dict, Any 


def merge_docs_into_openapi(generated_docs_path: str, openapi_spec_path: str, output_path: str = None) -> Dict[str, Any]:
    with open(generated_docs_path, 'r') as f:
        generated_docs = json.load(f)

    with open(openapi_spec_path, 'r') as f:
        openapi_spec = json.load(f)

    # Track statistics
    stats = {
        "total_components": len(generated_docs),
        "endpoints_processed": 0,
        "endpoints_added": 0,
        "endpoints_not_found": [],
        "schemas_processed": 0,
        "schemas_added": 0,
        "schemas_not_found": [],
    }

    for component_id, doc_data in generated_docs.items():
        endpoints = doc_data.get("endpoint", {})
        schema = doc_data.get("schema", "")

        if endpoints:
            stats["endpoints_processed"] += len(endpoints)

            for endpoint_key, doc_text in endpoints.items():
                method, path = endpoint_key.split(":")

                openapi_path = openapi_spec["paths"].get(path, None).get(method, None)

                if openapi_path:
                    stats["endpoints_not_found"].append({
                    "component": component_id,
                    "endpoint": endpoint_key,
                    "reason": f"Method '{method.upper()}' not found for path '{path}'"
                })
                    continue
                    
                openapi_path["description"] = doc_text
                
                stats["endpoints_added"] += 1

        if schema:
            schema_name = (component_id.split('.'))[-1]
            stats["schemas_processed"] += 1

            openapi_path = openapi_spec["components"]["schema"].get(schema_name, None)

            if not openapi_path:
                stats["schemas_not_found"].append({
                    "component": component_id,
                    "reason": f"Component schema {schema_name} not found in OpenAPI"
                })
                continue

            openapi_path["description"] = schema

            stats["schemas_added"] += 1



    with open(output_path, 'w') as f:
        json.dump(openapi_spec, f, indent=2)
