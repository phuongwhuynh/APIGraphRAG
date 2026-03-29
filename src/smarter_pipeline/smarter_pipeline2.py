# =========================
# GRAPH-RAG API DOC GENERATOR (FULL VERSION)
# =========================

import libcst as cst
from libcst.metadata import PositionProvider, MetadataWrapper
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import heapq
import json
import re
from dotenv import load_dotenv
from google.genai import client as genai_client, types
import requests

load_dotenv()
client = genai_client.Client()
total_prompts = 0
# =========================
# 1. DATA MODELS
# =========================


@dataclass
class Trace:
    file: str
    line: int
    code: str


@dataclass
class Parameter:
    name: str
    location: str = "query"
    type: str = "unknown"


@dataclass
class Condition:
    expr: str
    trace: Trace


@dataclass
class Response:
    status: Optional[int]
    trigger: str
    trace: Trace


@dataclass
class LinkedCondition:
    expr: str
    uses_params: List[str]
    trace: Trace


@dataclass
class LinkedResponse:
    status: Optional[int]
    trigger: str
    conditions: List[LinkedCondition]
    trace: Trace


@dataclass
class FunctionNode:
    name: str
    file: str
    params: List[str]
    calls: List[str] = field(default_factory=list)
    conditions: List[Condition] = field(default_factory=list)
    responses: List[Response] = field(default_factory=list)


# =========================
# 2. SCANNER + PARSER
# =========================


class Scanner:
    def __init__(self, root):
        self.root = Path(root)

    def files(self):
        return list(self.root.rglob("*.py"))


class Parser:
    def parse(self, files):
        parsed = {}
        for f in files:
            code = f.read_text(encoding="utf-8")
            parsed[f] = MetadataWrapper(cst.parse_module(code))
        return parsed


# =========================
# 3. FUNCTION ANALYZER
# =========================


class FunctionVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path, module):
        self.file = str(file_path)
        self.module = module
        self.functions: Dict[str, FunctionNode] = {}
        self.current = None

    def visit_FunctionDef(self, node):
        name = node.name.value
        params = [p.name.value for p in node.params.params]
        self.current = FunctionNode(name, self.file, params)
        self.functions[name] = self.current

    def leave_FunctionDef(self, node):
        self.current = None

    def visit_Call(self, node):
        if not self.current:
            return
        fn = self._get_name(node.func)
        if fn:
            self.current.calls.append(fn)

    def visit_If(self, node):
        if not self.current:
            return
        pos = self.get_metadata(PositionProvider, node)
        expr = self.module.code_for_node(node.test)

        self.current.conditions.append(
            Condition(expr, Trace(self.file, pos.start.line, expr))
        )

    def visit_Raise(self, node):
        if not self.current:
            return
        pos = self.get_metadata(PositionProvider, node)
        code = self.module.code_for_node(node)
        status = self._extract_status(code)

        self.current.responses.append(
            Response(status, code, Trace(self.file, pos.start.line, code))
        )

    def visit_Return(self, node):
        if not self.current:
            return
        pos = self.get_metadata(PositionProvider, node)
        code = self.module.code_for_node(node)

        self.current.responses.append(
            Response(200, code, Trace(self.file, pos.start.line, code))
        )

    def _extract_status(self, code):
        m = re.search(r"\b(4\d{2}|5\d{2})\b", code)
        return int(m.group(1)) if m else None

    def _get_name(self, node):
        if isinstance(node, cst.Name):
            return node.value
        if isinstance(node, cst.Attribute):
            return node.attr.value
        return None


# =========================
# 4. ROUTE DETECTOR (BASIC)
# =========================


class FastAPIAdapter:
    def extract(self, functions):
        routes = []
        for fn in functions.values():
            if fn.name.startswith(("get_", "create_", "update_", "delete_")):
                routes.append(
                    {"path": f"/{fn.name}", "method": "GET", "handler": fn.name}
                )
        return routes


# =========================
# 5. SCORING + ADAPTIVE EXPANSION
# =========================


def score_node(fn: FunctionNode, root_params, distance):
    score = 0

    if fn.responses:
        score += 10

    score += len(fn.conditions) * 4

    for cond in fn.conditions:
        if any(p in cond.expr for p in root_params):
            score += 6

    return score / (distance + 1)


def expand_adaptive(functions, root, root_params, token_budget=800):
    visited = set()
    heap = []

    def cost(fn):
        return len(fn.params) * 10 + len(fn.conditions) * 30 + len(fn.responses) * 30

    heapq.heappush(heap, (-100, 0, root))

    selected = []
    used = 0

    while heap and used < token_budget:
        _, dist, fn_name = heapq.heappop(heap)

        if fn_name in visited or fn_name not in functions:
            continue

        fn = functions[fn_name]
        c = cost(fn)

        if used + c > token_budget:
            continue

        visited.add(fn_name)
        selected.append(fn_name)
        used += c

        for callee in fn.calls:
            if callee in functions:
                s = score_node(functions[callee], root_params, dist + 1)
                heapq.heappush(heap, (-s, dist + 1, callee))

    return selected


# =========================
# 6. LINKING LOGIC
# =========================


def extract_param_usage(expr, params):
    return [p for p in params if re.search(rf"\b{p}\b", expr)]


def link_conditions(functions, func_names, root_params):
    linked = []

    for f in func_names:
        if f not in functions:
            continue

        for cond in functions[f].conditions:
            linked.append(
                LinkedCondition(
                    expr=cond.expr,
                    uses_params=extract_param_usage(cond.expr, root_params),
                    trace=cond.trace,
                )
            )

    return linked


def link_responses(functions, func_names, linked_conditions):
    linked_responses = []

    for f in func_names:
        if f not in functions:
            continue

        fn = functions[f]

        for r in fn.responses:
            conds = [
                c
                for c in linked_conditions
                if c.trace.file == r.trace.file and c.trace.line <= r.trace.line
            ]

            linked_responses.append(
                LinkedResponse(
                    status=r.status, trigger=r.trigger, conditions=conds, trace=r.trace
                )
            )

    return linked_responses


# =========================
# 7. FACT BUILDER
# =========================


class FactBuilder:
    def __init__(self, functions):
        self.functions = functions

    def build(self, route):
        root = route["handler"]
        root_params = self.functions[root].params

        selected = expand_adaptive(self.functions, root, root_params)

        linked_conditions = link_conditions(self.functions, selected, root_params)

        linked_responses = link_responses(self.functions, selected, linked_conditions)

        params = [Parameter(name=p) for p in root_params]

        return {
            "path": route["path"],
            "method": route["method"],
            "params": params,
            "conditions": linked_conditions,
            "responses": linked_responses,
        }


# =========================
# 8. LLM GENERATOR
# =========================


class OASGenerator:
    def __init__(self, llm=None):
        self.llm = llm

    def generate(self, fact):
        p_desc = self._describe_params(fact)
        r_desc = self._describe_responses(fact)
        return self._assemble(fact, p_desc, r_desc)

    def _describe_params(self, fact):
        prompt = f"""
Parameters:
{[p.__dict__ for p in fact["params"]]}

Conditions:
{[c.expr for c in fact["conditions"] if c.uses_params]}

Return JSON mapping param -> description.
"""
        return self._safe_llm(prompt)

    def _describe_responses(self, fact):
        prompt = f"""
Responses:
{[{
    "status": r.status,
    "conditions": [c.expr for c in r.conditions]
} for r in fact["responses"]]}

Explain when and why each response occurs.
Return ONLY valid JSON.
No explanation.
No markdown.
"""
        return self._safe_llm(prompt)

    def _assemble(self, fact, p_desc, r_desc):
        return {
            "summary": fact["path"],
            "parameters": [
                {
                    "name": p.name,
                    "in": p.location,
                    "description": p_desc.get(p.name, ""),
                }
                for p in fact["params"]
            ],
            "responses": {
                str(r.status or 200): {
                    "description": r_desc.get(str(r.status), ""),
                    "x-trace": r.trace.__dict__,
                }
                for r in fact["responses"]
            },
        }

    def _safe_llm(self, prompt):
        global total_prompts
        total_prompts += 1
        if not self.llm:
            return {}

        raw = self.llm(prompt)

        start = raw.find("{")
        end = raw.rfind("}")

        if start == -1 or end == -1:
            return {}

        try:
            return json.loads(raw[start : end + 1])
        except:
            return {}


# =========================
# 9. PIPELINE
# =========================


class Pipeline:
    def __init__(self, root, llm=None):
        self.root = root
        self.llm = llm

    def run(self):
        files = Scanner(self.root).files()
        parsed = Parser().parse(files)

        functions = {}

        for path, wrapper in parsed.items():
            visitor = FunctionVisitor(path, wrapper.module)
            wrapper.visit(visitor)
            functions.update(visitor.functions)

        routes = FastAPIAdapter().extract(functions)

        builder = FactBuilder(functions)
        generator = OASGenerator(self.llm)

        oas = {"openapi": "3.0.0", "paths": {}}

        for r in routes:
            fact = builder.build(r)
            op = generator.generate(fact)

            oas["paths"].setdefault(r["path"], {})
            oas["paths"][r["path"]][r["method"].lower()] = op

        return oas


# =========================
# 10. LLM
# =========================


def gemini_llm(prompt: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        ),
    )
    return response.text


def ollama_llm(prompt: str) -> str:
    with open(
        "src/smarter_pipeline/ollama_prompt_log.txt", "a", encoding="utf-8"
    ) as log_file:
        log_file.write(prompt + "\n" + "=" * 40 + "\n")
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen3:4b",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
        },
        timeout=120,
    )
    return response.json().get("text", "")


# =========================
# 11. RUN
# =========================

if __name__ == "__main__":
    pipeline = Pipeline("src", llm=ollama_llm)
    result = pipeline.run()
    with open("src/smarter_pipeline/openapi_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Total prompts sent: {total_prompts}")
