# extractor.py
import ast
import os
from graph import CodeGraph, Node


# ---------- PASS 1: INDEX SYMBOLS ----------

class IndexVisitor(ast.NodeVisitor):
    def __init__(self, file: str, graph: CodeGraph):
        self.file = file
        self.graph = graph

    def visit_ClassDef(self, node):
        self.graph.add_node(Node(
            name=node.name,
            kind="schema",
            file=self.file,
            start=node.lineno,
            end=node.end_lineno,
            meta={}
        ))

    def visit_FunctionDef(self, node):
        is_route = False
        method = None
        path = None

        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and hasattr(deco.func, "attr"):
                if deco.func.attr in {"get", "post", "put", "delete", "patch"}:
                    is_route = True
                    method = deco.func.attr
                    path = deco.args[0].value if deco.args else None

        if is_route:
            self.graph.add_node(Node(
                name=node.name,
                kind="route",
                file=self.file,
                start=node.lineno,
                end=node.end_lineno,
                meta={"method": method, "path": path}
            ))
            
        else:
            self.graph.add_node(Node(
                name=node.name,
                kind="function",
                file=self.file,
                start=node.lineno,
                end=node.end_lineno,
                meta={"method": method, "path": path}
            ))


# ---------- PASS 2: RESOLVE EDGES ----------

class EdgeVisitor(ast.NodeVisitor):
    def __init__(self, graph):
        self.graph = graph
        self.scope = None

    def visit_ClassDef(self, node):
        self.scope = node.name
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in self.graph.nodes:
                # base must be generated BEFORE class
                self.graph.add_edge(base.id, node.name)
        self.generic_visit(node)
        self.scope = None

    def visit_FunctionDef(self, node):
        self.scope = node.name

        if node.returns and isinstance(node.returns, ast.Name):
            if node.returns.id in self.graph.nodes:
                # return type must be generated BEFORE route
                self.graph.add_edge(node.returns.id, node.name)

        self.generic_visit(node)
        self.scope = None

    def visit_Call(self, node):
        if self.scope and isinstance(node.func, ast.Name):
            target = node.func.id
            if target in self.graph.nodes:
                # callee must exist before caller
                self.graph.add_edge(target, self.scope)
        self.generic_visit(node)



# ---------- ORCHESTRATION ----------

def extract(directory: str, graph: CodeGraph):
    files = []

    for root, _, fs in os.walk(directory):
        for f in fs:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))

    # PASS 1
    for file in files:
        with open(file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            IndexVisitor(file, graph).visit(tree)

    # PASS 2
    for file in files:
        with open(file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            EdgeVisitor(graph).visit(tree)
