import ast
import os
import glob

class ProjectVisitor(ast.NodeVisitor):
    def __init__(self, filepath, graph):
        self.filepath = filepath
        self.graph = graph
        self.current_scope = None

    def visit_ClassDef(self, node):
        # Store Metadata Only
        self.graph.add_node(
            name=node.name, 
            node_type="class", 
            filepath=self.filepath, 
            start_line=node.lineno,
            end_line=node.end_lineno
        )
        
        for base in node.bases:
            if isinstance(base, ast.Name):
                self.graph.add_relation(node.name, base.id, "inherits")
        
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.current_scope = node.name
        is_route = False
        http_method = None
        route_path = None
        
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and hasattr(decorator.func, "attr"):
                if decorator.func.attr in ["get", "post", "put", "delete", "patch"]:
                    is_route = True
                    http_method = decorator.func.attr
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        route_path = decorator.args[0].value

        if is_route:
            self.graph.add_node(
                name=node.name, 
                node_type="route", 
                filepath=self.filepath, 
                start_line=node.lineno,
                end_line=node.end_lineno,
                http_method=http_method, 
                path=route_path
            )
            
            if node.returns:
                self._extract_dependency(node.name, node.returns, "returns")
                
            for arg in node.args.args:
                if arg.annotation:
                    self._extract_dependency(node.name, arg.annotation, "uses_input")

        self.generic_visit(node)
        self.current_scope = None

    def _extract_dependency(self, source, annotation_node, relation):
        if isinstance(annotation_node, ast.Name):
            self.graph.add_relation(source, annotation_node.id, relation)
        elif isinstance(annotation_node, ast.Subscript):
            if isinstance(annotation_node.slice, ast.Name):
                 self.graph.add_relation(source, annotation_node.slice.id, relation)

    def visit_Call(self, node):
        if self.current_scope:
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr 
            
            if callee_name:
                self.graph.add_relation(self.current_scope, callee_name, "calls")
        
        self.generic_visit(node)

def parse_directory(directory, graph):
    print(f"Scanning directory: {directory}...")
    for filepath in glob.glob(os.path.join(directory, "**/*.py"), recursive=True):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                source = f.read()
                tree = ast.parse(source)
                # Pass only filepath and graph, source code reading is deferred
                visitor = ProjectVisitor(filepath, graph)
                visitor.visit(tree)
            except Exception as e:
                print(f"Error parsing {filepath}: {e}")