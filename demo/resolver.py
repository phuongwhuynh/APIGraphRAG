# resolver.py
import ast


DYNAMIC_MARKERS = {
    "getattr",
    "setattr",
    "globals",
    "locals",
    "eval",
    "exec",
    "importlib"
}


class DynamicUsageDetector(ast.NodeVisitor):
    def __init__(self):
        self.lines = []

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in DYNAMIC_MARKERS:
                self.lines.append(node.lineno)
        self.generic_visit(node)


def detect_dynamic_usage(source: str):
    tree = ast.parse(source)
    detector = DynamicUsageDetector()
    detector.visit(tree)
    return detector.lines
