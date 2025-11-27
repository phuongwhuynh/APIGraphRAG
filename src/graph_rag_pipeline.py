import libcst as cst
from libcst.metadata import PositionProvider, MetadataWrapper
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any
import re
import json
import os
from dotenv import load_dotenv
from google.genai import client as genai_client, types

load_dotenv()
client = genai_client.Client()


# -----------------------------
# 1. Project Scanner
# -----------------------------
class ProjectScanner:
    def __init__(self, project_root: str):
        self.root = Path(project_root)

    def scan_files(self) -> List[Path]:
        return list(self.root.rglob("*.py"))


# -----------------------------
# 2. CST Parser
# -----------------------------
class CSTParser:
    def parse(self, files: List[Path]) -> Dict[Path, MetadataWrapper]:
        parsed = {}
        for path in files:
            code = path.read_text()
            wrapper = MetadataWrapper(cst.parse_module(code))
            parsed[path] = wrapper
        return parsed


# -----------------------------
# 3. Import Visitor
# -----------------------------
class ImportVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: Path, edges: List[Dict[str, Any]]):
        self.file_path = file_path
        self.edges = edges

    @staticmethod
    def get_full_name(node):
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Attribute):
            left = ImportVisitor.get_full_name(node.value)
            return f"{left}.{node.attr.value}" if left else node.attr.value
        return ""

    def visit_Import(self, node: cst.Import):
        for alias in node.names:
            full_name = ImportVisitor.get_full_name(alias.name)
            self.edges.append(
                {
                    "source": f"module:{self.file_path}",
                    "target": f"module:{full_name}",
                    "type": "import",
                }
            )

    def visit_ImportFrom(self, node: cst.ImportFrom):
        module_name = self.get_full_name(node.module) if node.module else ""
        for alias in node.names:
            alias_name = alias.asname.name.value if alias.asname else alias.name.value
            full_name = f"{module_name}.{alias_name}" if module_name else alias_name
            self.edges.append(
                {
                    "source": f"module:{self.file_path}",
                    "target": f"module:{full_name}",
                    "type": "import",
                }
            )


# -----------------------------
# 4. Semantic Visitor
# -----------------------------
class SemanticVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self, file_path: Path, nodes: List[Dict], edges: List[Dict], module: cst.Module
    ):
        self.file_path = file_path
        self.nodes = nodes
        self.edges = edges
        self.current_class = None
        self.current_function = None
        self.module = module

    @staticmethod
    def get_full_name(node):
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Attribute):
            left = SemanticVisitor.get_full_name(node.value)
            return f"{left}.{node.attr.value}" if left else node.attr.value
        return None

    def visit_ClassDef(self, node: cst.ClassDef):
        pos = self.get_metadata(PositionProvider, node)
        node_id = f"class:{self.file_path}:{node.name.value}"
        # generate code for each base properly
        bases_code = [self.module.code_for_node(b.value) for b in node.bases]

        self.nodes.append(
            {
                "id": node_id,
                "type": "class",
                "name": node.name.value,
                "file": str(self.file_path),
                "start": pos.start.line,
                "end": pos.end.line,
                "bases": bases_code,
            }
        )

        # contain edge: module -> class
        self.edges.append(
            {"source": f"module:{self.file_path}", "target": node_id, "type": "contain"}
        )

        # inherit edges
        for b_code in bases_code:
            self.edges.append(
                {
                    "source": node_id,
                    "target": f"class:{b_code}",
                    "type": "inherit",
                }
            )

        self.current_class = node.name.value

    def visit_FunctionDef(self, node: cst.FunctionDef):
        pos = self.get_metadata(PositionProvider, node)
        node_id = f"function:{self.file_path}:{node.name.value}"
        params = [p.name.value for p in node.params.params]

        # Capture decorators as strings
        decorators = [self.module.code_for_node(d.decorator) for d in node.decorators]

        self.nodes.append(
            {
                "id": node_id,
                "type": "function",
                "name": node.name.value,
                "file": str(self.file_path),
                "class": self.current_class,
                "start": pos.start.line,
                "end": pos.end.line,
                "params": params,
                "decorators": decorators,  # ✅ add this
            }
        )

        if self.current_class:
            self.edges.append(
                {
                    "source": f"class:{self.file_path}:{self.current_class}",
                    "target": node_id,
                    "type": "contain",
                }
            )
        else:
            self.edges.append(
                {
                    "source": f"module:{self.file_path}",
                    "target": node_id,
                    "type": "contain",
                }
            )
        self.current_function = node.name.value


# -----------------------------
# 5. Route Finder for REST APIs
# -----------------------------
class OASRouteFinder:
    FLASK_DECORATOR = re.compile(r".*\.route\(")
    FASTAPI_DECORATOR = re.compile(r".*\.(get|post|put|patch|delete)\(")

    def __init__(self, nodes: List[Dict]):
        self.functions = [f for f in nodes if f["type"] == "function"]

    def find_routes(self) -> List[Dict[str, Any]]:
        routes = []
        for func in self.functions:
            for deco in func.get("decorators", []):
                # Flask
                if self.FLASK_DECORATOR.match(deco):
                    methods = self.extract_methods(deco)
                    routes.append(
                        {
                            "framework": "flask",
                            "path": self.extract_path(deco),
                            "methods": methods,
                            "handler": func,
                        }
                    )
                # FastAPI
                elif self.FASTAPI_DECORATOR.match(deco):
                    method = deco.split(".")[-1].split("(")[0].upper()
                    routes.append(
                        {
                            "framework": "fastapi",
                            "path": self.extract_path(deco),
                            "methods": [method],
                            "handler": func,
                        }
                    )
        return routes

    @staticmethod
    def extract_path(deco: str) -> str:
        m = re.search(r'["\'](.+?)["\']', deco)
        return m.group(1) if m else "/"

    @staticmethod
    def extract_methods(deco: str) -> List[str]:
        m = re.search(r"methods\s*=\s*\[([^\]]+)\]", deco)
        if m:
            return [x.strip().strip("'\"") for x in m.group(1).split(",")]
        return ["GET"]


# -----------------------------
# 6. OpenAPI Generator
# -----------------------------
class OASGenerator:
    def __init__(self, nodes: List[Dict], edges: List[Dict], llm_client=None):
        self.nodes = nodes
        self.edges = edges
        self.llm = llm_client

    # flexible, replace with local LLM or other service
    def summarize_route(self, route: Dict) -> str:
        print("Summarizing route:", route["path"])

        try:
            handler_file = route["handler"]["file"]
            start_line = route["handler"]["start"]
            end_line = route["handler"]["end"]

            with open(handler_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            code_snippet = "".join(lines[start_line - 1 : end_line])
        except Exception as e:
            code_snippet = f"# Could not read code: {e}"

        prompt = (
            f"Explain what this REST API handler does in simple terms:\n\n"
            f"Path: {route.get('path')}\n"
            f"Method: {', '.join(route.get('method', []))}\n"
            f"Handler name: {route['handler']['name']}\n"
            f"Code:\n{code_snippet}"
        )

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                ),
            )
            return response.text.strip()
        except Exception as e:
            return f"Could not summarize route: {e}"

    def generate_oas(self, routes: List[Dict]) -> Dict:
        oas = {
            "openapi": "3.0.0",
            "info": {"title": "Project API", "version": "1.0.0"},
            "paths": {},
        }
        for r in routes:
            path = r["path"]
            if path not in oas["paths"]:
                oas["paths"][path] = {}
            summary = self.summarize_route(r)
            for method in r["methods"]:
                oas["paths"][path][method.lower()] = {
                    "summary": summary,
                    "operationId": r["handler"]["name"],
                    "responses": {"200": {"description": "Successful Response"}},
                    "x-code-trace": {
                        "file": r["handler"]["file"],
                        "start_line": r["handler"].get("start"),
                        "end_line": r["handler"].get("end"),
                    },
                }
        return oas


# -----------------------------
# 7. Graph + OAS Builder
# -----------------------------
class GraphRAGBuilder:
    def __init__(self, project_root: str):
        self.root = Path(project_root)

    def build_graph(self) -> Dict[str, Any]:
        nodes = []
        edges = []

        # directories
        for d in self.root.rglob("*"):
            if d.is_dir():
                nodes.append({"id": f"dir:{d}", "type": "directory", "name": d.name})

        # files
        files = list(self.root.rglob("*.py"))
        for f in files:
            nodes.append({"id": f"module:{f}", "type": "module", "name": f.name})
            edges.append(
                {
                    "source": f"dir:{f.parent}",
                    "target": f"module:{f}",
                    "type": "contain",
                }
            )

        parser = CSTParser()
        parsed = parser.parse(files)

        for path, wrapper in parsed.items():
            wrapper.visit(ImportVisitor(path, edges))
            wrapper.visit(SemanticVisitor(path, nodes, edges, wrapper.module))

        return {"nodes": nodes, "edges": edges}

    def build_oas(self) -> Dict[str, Any]:
        graph = self.build_graph()
        route_finder = OASRouteFinder(graph["nodes"])
        routes = route_finder.find_routes()
        oas_gen = OASGenerator(graph["nodes"], graph["edges"])
        return oas_gen.generate_oas(routes)


# -----------------------------
# 8. Example usage
# -----------------------------
if __name__ == "__main__":
    project_root = "src/fastapi"
    builder = GraphRAGBuilder(project_root)

    print("=== Building Graph ===")
    graph = builder.build_graph()
    for n in graph["nodes"]:
        print(f"[{n['type']}] {n['name']}")
    for e in graph["edges"]:
        print(f"[{e['type']}] {e['source']} -> {e['target']}")

    print("\n=== Generating OpenAPI Document ===")
    oas = builder.build_oas()
    print(json.dumps(oas, indent=2))
