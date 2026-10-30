# Semantic OpenAPI Documentation with AST Parsing + GraphRAG

Research project on automatically enriching OpenAPI specifications with **semantic documentation** — human-readable `description` text for endpoints, schemas and path/query parameters — that frameworks such as FastAPI cannot produce from type hints alone.

The approach combines:

- **Static analysis (Python `ast`)** to turn a web-API codebase into a dependency graph of code components (classes, functions, methods, global variables, endpoint parameters).
- **Graph-based retrieval-augmented generation (GraphRAG)**: components are documented in dependency order, and the context for each component is retrieved from its neighbours in the graph — preferring documentation already generated for those neighbours over raw source code.
- **Merging** the generated text back into the framework's own OpenAPI spec, with an `x-trace` pointer to the source lines each description came from.

The current experiments target [Netflix Dispatch](https://github.com/Netflix/dispatch) (a FastAPI application, vendored in `data/dispatch/`) and use local models served by Ollama.

## Pipeline

```text
                ┌────────────────────────┐
 target repo ──▶│ 1. OpenAPI extraction  │──▶ <repo>.json (baseline spec)
                │   (docker or local)    │──▶ <repo>_map.json (endpoint → function)
                └───────────┬────────────┘
                            ▼
                ┌────────────────────────┐
                │ 2. AST dependency graph│──▶ SQLite (src/database/dependency_graph.db)
                └───────────┬────────────┘
                            ▼
                ┌────────────────────────┐
                │ 3. Cycle removal +     │──▶ groups of components, dependencies first
                │    topological groups  │
                └───────────┬────────────┘
                            ▼   for each batch
     ┌──────────────────────┼───────────────────────┐
     ▼                      ▼                       ▼
 4a. CoT analysis     4b. Context ranking     4c. Generation
 (knowledge gaps)     (sliding-window LLM     (docstring / endpoint /
                      reranking of graph      schema / parameter text;
                      neighbours)             written back to the graph)
                            │
                            ▼
                ┌────────────────────────┐
                │ 5. Merge into OpenAPI  │──▶ resulted_<repo>.json, merge_stats.json
                └───────────┬────────────┘
                            ▼
                ┌────────────────────────┐
                │ 6. Evaluation          │──▶ output/evaluate/*.json
                └────────────────────────┘
```

1. **OpenAPI extraction** — `SpecGetterFactory` runs the target app (inside its docker-compose service, falling back to a local virtualenv) to dump the framework-generated OpenAPI spec and a map from each `METHOD:/path` to the Python function that handles it. FastAPI, Flask and Django are supported.
2. **AST dependency graph** — `DependencyParser` walks every Python file, collects components and their imports, and resolves which repo components each one references (calls, attribute access, type annotations, base classes, `Depends(...)` injections). Each component is tagged with the document types it needs:
   - `docstring` — every component;
   - `endpoint` — functions mapped to a route in step 1;
   - `schema` — classes that appear in `components.schemas`;
   - `parameter` — path/query parameters of an endpoint (including those injected via `Depends`).

   The graph is stored in SQLite so the heavy source code stays on disk while the LLMs run.
3. **Ordering** — back edges are removed by DFS, and Kahn's algorithm produces groups of components whose dependencies have all been processed. Components in a group are independent and are processed in parallel batches.
4. **Generation** (LangGraph map-reduce workflows, one worker per component):
   - **CoT** (`src/llm/cot.py`) — asks the model which custom types, undefined calls and logic blocks in the component need outside context.
   - **Ranker** (`src/llm/rank.py`) — reorders the component's graph neighbours by usefulness. Each sliding window of candidates is scored by the log-probabilities the model assigns to each candidate's index as the "single most helpful" snippet; windows slide back-to-front until the top-k is stable.
   - **Generator** (`src/llm/generate.py`) — builds the prompt from the ranked neighbours (their generated docstring if one exists, otherwise their source), fits it into the context window with a tokenizer, and writes a description for each required doc type. The result is saved back into the graph, so components further up the order receive the documentation of their dependencies as context — this is the GraphRAG loop.
5. **Merge** (`src/openapi/merge_spec.py`) — writes endpoint, schema and parameter descriptions into the baseline spec, adds `x-trace` (`file`, `start_line`, `end_line`), and records what could not be matched in `merge_stats.json`.
6. **Evaluation** — coverage statistics over the enriched spec, an LLM-as-judge score (1–5 for motivation, functionality and parameter/attribute description, computed from the judge's token log-probabilities), and optionally BARTScore.

## Repository layout

```text
.
├── README.md
├── requirements.txt
├── data/
│   └── dispatch/                 # target codebase used in the experiments
└── api_graphrag/                 # the pipeline
    ├── main.py                   # end-to-end generation pipeline (steps 1–5)
    ├── evaluate_result.py        # evaluation of the generated output (step 6)
    ├── count_tokens.py           # total LLM token usage from the run logs
    ├── output/                   # generated at run time (git-ignored)
    └── src/
        ├── dependency_analyzer/
        │   ├── ast_parser.py     # CodeComponent, DocType, DependencyParser, OpenAPICollector
        │   └── topo_sort.py      # cycle removal + grouped topological sort
        ├── database/
        │   └── storage.py        # SQLite store for the component graph
        ├── llm/
        │   ├── base.py           # BasicModel: model init, tokenizer, context-window fitting, logging
        │   ├── prompt.py         # all prompts (CoT, ranking, generation, evaluation)
        │   ├── cot.py            # knowledge-gap analysis
        │   ├── rank.py           # log-prob sliding-window context reranker
        │   └── generate.py       # description generation per doc type
        ├── openapi/
        │   ├── spec_extractor.py # dump OpenAPI spec + endpoint→function map (FastAPI/Flask/Django, docker/local)
        │   └── merge_spec.py     # merge generated text into the spec
        ├── evaluation/
        │   ├── openapi_stats_evaluate.py  # description coverage statistics
        │   ├── llm_evaluate.py            # LLM-as-judge scoring
        │   ├── bartscore_evaluate.py      # BARTScore wrapper
        │   ├── hallucination_evaluate.py  # (work in progress, currently disabled)
        │   └── BARTScore/                 # vendored BARTScore source
        └── utils/
            ├── json_io.py        # save_as_json (merging) / load_json
            ├── match.py          # code ↔ OpenAPI parameter-name matching
            └── sliding_window.py # standalone version of the reranking window
```

## Setup

1. Python environment:

   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

   BARTScore evaluation additionally needs `torch`.

2. Models — the defaults in `api_graphrag/main.py` use `qwen2.5-coder:7b` through Ollama:

   ```bash
   ollama pull qwen2.5-coder:7b
   ollama serve
   ```

   The Ranker and the LLM judge use Ollama's OpenAI-compatible endpoint (`http://localhost:11434/v1`), because they need `logprobs`.

3. Target project — the spec extractor needs to be able to import the target app, either through its docker-compose service (`data/dispatch/.devcontainer/docker-compose.yml`, service `app`) or through a local virtualenv at `data/dispatch/venv`.

## Configuration

Set these in `api_graphrag/main.py`:

| Setting | Meaning |
| --- | --- |
| `REPO_DIR` | root of the codebase to document (default `data/dispatch`) |
| `framework` | `fastapi`, `flask` or `django` |
| `app_instance_path` | import path of the app object, e.g. `src.dispatch.main:api` |
| `python_exec` | interpreter for local-mode spec extraction |
| `compose_file`, `service_name` | docker-mode spec extraction |
| `excluded_dirs` | directories (relative to `REPO_DIR`) to skip |
| `*_model`, `*_model_provider` | models used by CoT, Ranker and Generator |
| `input_context_window`, `output_context_window` | token budgets used when fitting context |
| `window_size`, `step`, `top_k` | Ranker sliding-window parameters |

## Running

```bash
cd api_graphrag
python main.py             # generate documentation and the enriched spec
python evaluate_result.py  # evaluate it
python count_tokens.py     # total tokens spent
```

`main.py` deletes `api_graphrag/output/` at start-up. A previously extracted spec is reused only if it is still present, so the extraction step re-runs on every fresh run.

## Outputs (`api_graphrag/output/`)

| File | Content |
| --- | --- |
| `<repo>.json` | baseline OpenAPI spec produced by the framework |
| `<repo>_map.json` | `METHOD:/path` → handler component ids |
| `cot_output.json` | CoT prompt and analysis per component |
| `rank_output.json` | ranked neighbour ids per component |
| `generate_output.json` | generated `docstring`, `endpoint`, `schema`, `path_parameter`, `query_parameter` per component |
| `traces_output.json` | source file and line range per component |
| `resulted_<repo>.json` | **enriched OpenAPI spec** with descriptions and `x-trace` |
| `merge_stats.json` | merged / unmatched endpoints, schemas and parameters |
| `evaluate/*.json` | coverage statistics, LLM-judge and BARTScore results |
| `log/*_messages.log`, `log/*_tokens.log` | full prompts/responses and token usage per stage |

## Troubleshooting

- **Model calls fail** — check that Ollama is running and the model has been pulled.
- **Ranker warns "No logprobs returned"** — the Ranker must use `model_provider="openai"` with the Ollama `/v1` base URL; the native Ollama provider does not return log-probabilities, and the ranking is not meaningful without them.
- **No endpoints or schemas detected** — spec extraction failed (check the docker service or `python_exec`) or `app_instance_path` is wrong; every component then gets a docstring only.
