# Demo Folder Guide

This README describes only the `demo/` folder and how to run its document-generation pipeline.

## What `demo/` does

The `demo/` pipeline analyzes a FastAPI codebase, builds a dependency graph between code components, then generates documentation artifacts with three agent roles:

- **Reader**: identifies which dependencies are important for each target component.
- **Searcher**: retrieves source/docstring context for those dependencies.
- **Writer**: generates final structured documentation output.

The workflow is implemented in `demo/main.py` and processes components by topological groups to respect dependency order.

## Folder layout (demo only)

```text
demo/
├── main.py
├── output/
│   ├── dispatch.json
│   └── dispatch_map.json
└── src/
    ├── agent/
    │   ├── base.py
    │   ├── evaluator.py
    │   ├── reader.py
    │   ├── searcher.py
    │   └── writer.py
    ├── dependency_analyzer/
    │   ├── ast_parser.py
    │   └── topo_sort.py
    └── tools/
        ├── evaluate/
        └── get_spec/
```

## File responsibilities (what each file supports)

- `demo/main.py`: Orchestrates the full demo pipeline (parse repository, sort components, run Reader/Searcher/Writer, and save outputs).
- `demo/src/dependency_analyzer/ast_parser.py`: Supports static AST parsing of Python code, component extraction (function/class/method), import collection, dependency detection, and dependency-graph serialization.
- `demo/src/dependency_analyzer/topo_sort.py`: Supports dependency ordering by resolving cycles and producing topological groups so independent components can be processed in parallel batches.
- `demo/src/agent/base.py`: Supports shared LLM utilities (model initialization, token counting, context-window fitting, and per-agent logging).
- `demo/src/agent/reader.py`: Supports context-priority analysis for each component and doc type (docstring/openapi/schema), returning structured retrieval requirements.
- `demo/src/agent/searcher.py`: Supports local context retrieval by mapping Reader requests to component source/docstrings from the parsed repository graph.
- `demo/src/agent/writer.py`: Supports final generation of structured documentation artifacts (docstrings, endpoint/path data, and schema-oriented outputs).
- `demo/src/agent/evaluator.py`: Supports evaluation utilities for generated results (quality/consistency checks).
- `demo/src/tools/get_spec/get_spec.py`: Supports OpenAPI/spec extraction helpers used by the dependency parser workflow.

## Execution flow

1. `DependencyParser` scans the target repository and extracts components/dependencies.
2. The dependency graph is saved to `demo/output/dependency_graph.json`.
3. Components are grouped by topological order.
4. For each batch:
   - Reader produces context requirements.
   - Searcher fetches relevant local context.
   - Writer generates documentation output.
5. Intermediate agent outputs are persisted as JSON in `demo/output/`.

## Prerequisites

- Python environment with dependencies installed from `requirements.txt`.
- A running LLM provider matching the config in `demo/main.py`.
  - Current defaults: model `llama3.2:3b`, provider `ollama`.
- Access to the target project being analyzed (configured through `REPO_DIR` in `demo/main.py`).

## Configure before running

Open `demo/main.py` and verify these values for your machine/project:

- `REPO_DIR`: target repository root to analyze.
- `python_exec`: Python executable used by spec extraction.
- `compose_file` and `service_name`: Docker service configuration if needed.
- `app_instance_path`: FastAPI app import path.
- `excluded_dirs`: folders to skip during analysis.
- `reader_model` / `writer_model` and provider values.

## Run

From the workspace root:

```bash
python demo/main.py
```

## Output files generated

- `demo/output/dependency_graph.json`: graph extracted by static analysis.
- `demo/output/reader_output.json`: Reader context-priority decisions.
- `demo/output/searcher_output.json`: retrieved context payloads.
- `demo/output/writer_output.json`: final generated documentation content.
- `output/log/*.log`: per-agent message/token logs.

Note: `demo/main.py` removes `demo/output/` at startup if it already exists, then recreates outputs for a fresh run.

## Quick troubleshooting

- If model calls fail, verify your configured provider is available (for example, Ollama running locally and model pulled).
- If no components are found, re-check `REPO_DIR` and `app_instance_path`.
- If dependency parsing fails on environment-specific paths, update `python_exec` and Docker-related settings in `demo/main.py`.