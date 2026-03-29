import libcst as cst
from libcst.metadata import PositionProvider, MetadataWrapper
import re
from typing import Dict
from data_model import FunctionNode, Condition, Response, Trace


class Parser:
    """Parse the source code into an abstract syntax tree (AST) using libcst."""

    def parse(self, files):
        parsed = {}
        for f in files:
            code = f.read_text(encoding="utf-8")
            parsed[f] = MetadataWrapper(cst.parse_module(code))
        return parsed


class FunctionVisitor(cst.CSTVisitor):
    """Visit function definitions to extract conditions and responses."""

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
