# assembler.py (FIXED)

import json
import os


def assemble_openapi(
    title: str,
    version: str,
    schema_dir: str,
    path_dir: str,
    output_file: str
):
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "paths": {},
        "components": {"schemas": {}}
    }

    # Load schemas
    for f in os.listdir(schema_dir):
        if f.endswith(".json"):
            with open(os.path.join(schema_dir, f)) as sf:
                openapi["components"]["schemas"][f[:-5]] = json.load(sf)

    # Load paths
    for f in os.listdir(path_dir):
        if not f.endswith(".json"):
            continue

        with open(os.path.join(path_dir, f)) as pf:
            operations = json.load(pf)

        # Filename convention: <function_name>.json
        # We must embed path elsewhere (see NOTE below)
        if "_PATH_" not in operations:
            raise ValueError(
                f"Path file {f} missing '_PATH_' key (path must be explicit)"
            )

        path = operations.pop("_PATH_")
        openapi["paths"].setdefault(path, {}).update(operations)

    with open(output_file, "w") as out:
        json.dump(openapi, out, indent=2)
