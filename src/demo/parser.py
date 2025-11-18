import libcst as cst
from libcst.metadata import PositionProvider
from pathlib import Path

code_file = Path("src/demo/code_file.py").read_text()


class Analyzer(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str = "", results: dict = None):
        self.file_path = file_path
        self.results = results
        self.results.setdefault("imports", {}).setdefault(
            self.file_path, {}
        ).setdefault(
            "*", []
        )  # list of wildcard imports
        self.current_function = None

    def visit_ImportFrom(self, node: cst.ImportFrom):
        if node.module:
            module = (
                "." * len(node.relative) if node.relative else ""
            ) + node.module.value
        else:
            module = "." * len(node.relative)

        if isinstance(node.names, cst.ImportStar):
            self.results["imports"][self.file_path]["*"].append(f"{module}.*")
        else:
            for alias in node.names:
                local = alias.asname.name.value if alias.asname else alias.name.value
                self.results["imports"][self.file_path][
                    local
                ] = f"{module}.{alias.name.value}"

    def visit_FunctionDef(self, node: cst.FunctionDef):
        print("Function:", node.name.value)
        pos = self.get_metadata(PositionProvider, node)
        print("Start line:", pos.start.line)
        print("End line:", pos.end.line)


def analyze_folder(folder_path: str):
    results = {"functions": [], "imports": {}, "calls": []}

    for path in Path(folder_path).rglob("*.py"):
        results["imports"][str(path)] = {}
        code = path.read_text()
        wrapper = cst.MetadataWrapper(cst.parse_module(code))
        wrapper.visit(Analyzer(str(path), results))

    return results


module = cst.parse_module(code_file)
wrapper = cst.MetadataWrapper(module)
wrapper.visit(Analyzer())
