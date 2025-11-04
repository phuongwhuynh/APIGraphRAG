import libcst as cst
from libcst.metadata import PositionProvider
from pathlib import Path

code_file = Path("src/code_file.py").read_text()


class Analyzer(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def visit_FunctionDef(self, node: cst.FunctionDef):
        print("Function:", node.name.value)
        pos = self.get_metadata(PositionProvider, node)
        print("Start line:", pos.start.line)
        print("End line:", pos.end.line)

        # print("Decorators:", [d.decorator.code for d in node.decorators])
        # for subnode in node.body.body:
        #     if isinstance(subnode, cst.SimpleStatementLine):
        #         for expr in subnode.body:
        #             if isinstance(expr, cst.Raise):
        #                 print("Raise code:", cst.Module([subnode]).code.strip())


module = cst.parse_module(code_file)
wrapper = cst.MetadataWrapper(module)
wrapper.visit(Analyzer())
