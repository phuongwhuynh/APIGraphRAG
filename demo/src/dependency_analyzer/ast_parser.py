"""
AST-based Python code parser that extracts dependency information between code components (functions, classes, methods) --> Result: a dependency graph
"""

import json
import os
import ast
import builtins
import logging
import gc
from tqdm.auto import tqdm
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Optional, Literal, Dict, Any, Tuple
from src.tools.get_spec.get_spec import SpecGetterFactory
from enum import Enum


logger = logging.getLogger(__name__)

BUILTIN_TYPES = {name for name in dir(builtins)}
EXCLUDED_NAMES = {"self", "cls"}
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "build",
    "dist",
}


class DocType(Enum):
    DOCSTRING = "docstring"
    ENDPOINT = "endpoint"
    SCHEMA = "schema"


@dataclass
class CodeComponent:
    """Represent a single code component (function, parameter, class or method) in a Python codebase
    Store the component's identifier, AST node, dependencies, and other metadata"""

    # Unique identifier for the component, format: module_path.ClassName.method_name
    id: str

    # AST node representing this component
    node: ast.AST

    # Type of component: 'class', 'function', 'method', 'parameter' (for path and query parameter)
    component_type: Literal["class", "function", "method", "parameter"]

    # Full path to the file containing this component
    file_path: str
    # Relative path within the repo
    relative_path: str

    # import modules
    imports: Set[str]
    from_imports: Dict[str, List[str]]

    # Set of component IDs this component depends on
    depends_on: Set[str]

    # Original source code of the component
    source_code: Optional[str] = None

    # Line numbers in the file (1-indexed)
    start_line: int = 0
    end_line: int = 0

    # Whether the component already has a docstring
    has_docstring: bool = False
    # Content of the docstring if it exists
    docstring: str = ""
    endpoint: Dict[str, str] = field(default_factory=lambda: {})
    schema: str = ""

    # Is this an endpoint
    doc_type: List[str] = field(default_factory=lambda: [DocType.DOCSTRING.value])
    api_methods: List[str] = field(default_factory=lambda: [])

    def to_dict(self) -> Dict[str, Any]:
        """Convert this component to a dictionary representation for JSON serialization"""
        return {
            "id": self.id,
            "component_type": self.component_type,
            "file_path": self.file_path,
            "relative_path": self.relative_path,
            "imports": list(self.imports),
            "from_imports": self.from_imports,
            "depends_on": list(self.depends_on),
            "source_code": self.source_code,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "has_docstring": self.has_docstring,
            "docstring": self.docstring,
            "endpoint": self.endpoint,
            "schema": self.schema,
            "doc_type": self.doc_type,
            "api_methods": self.api_methods,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CodeComponent":
        return CodeComponent(
            id=data.get("id", ""),
            node=data.get("node", None),
            component_type=data.get("component_type", None),
            file_path=data.get("file_path", None),
            relative_path=data.get("relative_path", None),
            imports=set(data.get("imports", [])),
            from_imports=data.get("from_imports", {}),
            depends_on=set(data.get("depends_on", [])),
            source_code=data.get("source_code", None),
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
            has_docstring=data.get("has_docstring", False),
            docstring=data.get("docstring", ""),
            endpoint=data.get("endpoint", {}),
            schema=data.get("schema", ""),
            doc_type=data.get("doc_type", [DocType.DOCSTRING.value]),
            api_methods=data.get("api_methods", []),
        )


import ast


class ImportCollector(ast.NodeVisitor):
    """Collect import statements from Python code."""

    def __init__(self, current_module: str):
        self.imports = set()
        self.from_imports = {}
        self.current_module = current_module

    def visit_Import(self, node: ast.Import):
        """Process 'import x' statements."""
        for name in node.names:
            self.imports.add(name.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Process 'from x import y' statements."""
        # Handle the module name (it is None for syntax like 'from . import foo')
        module_name = node.module or ""

        # Handle Absolute vs Relative imports
        if node.level > 0:
            # It's a RELATIVE import
            module_parts = self.current_module.split(".")

            if len(module_parts) >= node.level:
                base_module = ".".join(module_parts[: -node.level])

                if base_module and module_name:
                    final_module = f"{base_module}.{module_name}"
                elif base_module:
                    final_module = base_module
                else:
                    final_module = module_name
            else:
                final_module = module_name
        else:
            # It's an ABSOLUTE import
            final_module = module_name

        # Store the results
        if final_module not in self.from_imports:
            self.from_imports[final_module] = []

        for name in node.names:
            self.from_imports[final_module].append(name.name)

        self.generic_visit(node)


class DependencyCollector(ast.NodeVisitor):
    """Collect dependencies between code components by analyzing
    attribute access, function calls and class references"""

    def __init__(self, imports, from_imports, current_module, repo_modules):
        self.imports = imports
        self.from_imports = from_imports
        self.current_module = current_module
        self.repo_modules = repo_modules
        self.dependencies = set()
        self._current_class = None
        self.local_variable = set()

    def _add_dependency(self, name: str) -> None:
        """Add dependency based on name references"""
        # Skip bultin, self reference and local variables
        if (
            name in BUILTIN_TYPES
            or name in EXCLUDED_NAMES
            or name in self.local_variable
        ):
            return

        # Name imported from a module
        for module, imported_names in self.from_imports.items():
            if module in self.repo_modules and name in imported_names:
                self.dependencies.add(f"{module}.{name}")
                return

        # Name from the current module
        local_component_id = f"{self.current_module}.{name}"
        self.dependencies.add(local_component_id)

    def _process_attribute(self, node: ast.AST) -> None:
        """Add dependency based on attribute access"""
        parts = []
        current = node

        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.insert(0, current.id)

            if parts[0] in self.local_variable or parts[0] in EXCLUDED_NAMES:
                return

            if parts[0] in self.imports and parts[0] in self.repo_modules:
                if len(parts) > 1:
                    self.dependencies.add(f"{parts[0]}.{parts[1]}")
                    return

            for module, imported_names in self.from_imports.items():
                if (
                    parts[0] in imported_names
                    and parts[0] in self.repo_modules
                    and len(parts) > 1
                ):
                    self.dependencies.add(f"{module}.{parts[0]}")
                    return

    def visit_ClassDef(self, node: ast.ClassDef):
        """Process class definition"""
        old_class = self._current_class
        self._current_class = node.name

        for base in node.bases:
            if isinstance(base, ast.Name):
                # Simple name references, ex: imported class
                self._add_dependency(base.id)
            elif isinstance(base, ast.Attribute):
                # Module.Class references
                self._process_attribute(base)

        self._current_class = old_class
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Process function call"""

        if isinstance(node.func, ast.Name):
            # Function call
            self._add_dependency(node.func.id)
        if isinstance(node.func, ast.Attribute):
            # Method call
            self._process_attribute(node.func)

        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Process name references"""
        if isinstance(node.ctx, ast.Load):
            self._add_dependency(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Process attribute access"""
        self._process_attribute(node)
        self.generic_visit(node)

    def _process_annotation(self, node: Optional[ast.AST]) -> None:
        """Process type hints/annotations for dependencies."""
        if node is None:
            return

        if isinstance(node, ast.Name):
            self._add_dependency(node.id)
        elif isinstance(node, ast.Attribute):
            self._process_attribute(node)
        elif isinstance(node, ast.Subscript):
            # For types like List[MyClass], Dict[str, OtherClass]
            self._process_annotation(node.value)
            self._process_annotation(node.slice)
        elif isinstance(node, ast.Tuple):
            # For Tuple[A, B] inside subscripts
            for elt in node.elts:
                self._process_annotation(elt)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # For Union types like A | B in Python 3.10+
            self._process_annotation(node.left)
            self._process_annotation(node.right)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Process function definition annotations."""

        # Process argument type annotations
        for arg in node.args.args:
            self._process_annotation(arg.annotation)

        for arg in node.args.kwonlyargs:
            self._process_annotation(arg.annotation)

        if node.args.vararg:
            self._process_annotation(node.args.vararg.annotation)

        if node.args.kwarg:
            self._process_annotation(node.args.kwarg.annotation)

        # Process return type annotation
        if node.returns:
            self._process_annotation(node.returns)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Process async function definition annotations exactly like standard functions."""
        self.visit_FunctionDef(node)


def add_parent_to_nodes(tree: ast.AST) -> None:
    """Add a parent attribute to each node in the AST

    Args:
        tree: the AST to process"""

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node


class OpenAPICollector:
    """A class for OpenAPI componenents determination"""

    def __init__(
        self,
        framework: str,
        project_dir: str,
        output_dir: str,
        app_instance_path: str,
        python_exec: Optional[str] = None,
        compose_file: Optional[str] = None,
        service_name: Optional[str] = None,
    ):
        """Initialize a class for openAPI components determinination

        Args:
            project_dir: the root directory of the Python project to parse
            framework: the web framework used in the project (e.g., "django", "fastapi", "flask")
            output_dir: the directory to save the parsing results and generated documentation
            app_instance_path: the module path to the web application instance for endpoint extraction. Ex:"myapp.main:app" -> myapp.main is the module; app is the instance
            python_exec: the path to the Python environment to use for running the project (if needed for endpoint extraction)
            compose_file: the path to the docker-compose file to use for running the project (if needed for endpoint extraction)
            service_name: the name of the service running in docker"""
        try:
            spec_getter = SpecGetterFactory.create(
                framework=framework,
                mode="docker",
                project_dir=project_dir,
                output_dir=output_dir,
                app_instance_path=app_instance_path,
                python_exec=python_exec,
                compose_file=compose_file,
                service_name=service_name,
            )
            if not Path(spec_getter.output_file).exists():
                spec_getter.get_spec()

            self.endpoints = spec_getter.endpoint_func_map()
        except Exception as e:
            logger.error(f"Cannot get specification skeleton by running on docker: {e}")
            logger.info(
                f"Try to get specification skeleton by running on local environment"
            )
            try:
                spec_getter = SpecGetterFactory.create(
                    framework=framework,
                    mode="local",
                    project_dir=project_dir,
                    output_dir=output_dir,
                    app_instance_path=app_instance_path,
                    python_exec=python_exec,
                    compose_file=compose_file,
                    service_name=service_name,
                )
                if not Path(spec_getter.output_file).exists():
                    spec_getter.get_spec()
                self.endpoints = spec_getter.endpoint_func_map()
            except Exception as e:
                logger.error(
                    f"Cannot get specification skeleton by running on local env: {e}"
                )

        # self.endpoints = spec_getter.endpoint_func_map()
        self.schemas = set()

    # deprecated
    def urls_endpoints(self, tree: ast.AST, module_path: str) -> None:
        """Parse urls.py to collect endpoints in django"""
        pass
        # endpoints = set()

        # # 1. BUILD THE IMPORT MAP
        # # Example output: {'views': 'myapp.views', 'UserView': 'myapp.users.views.UserView'}
        # import_map = {}

        # # Determine base package for resolving relative imports (e.g., 'myapp' from 'myapp.urls')
        # parts = module_path.split(".")
        # base_package_parts = parts[:-1] if len(parts) > 1 else parts

        # for node in ast.walk(tree):
        #     if isinstance(node, ast.Import):
        #         for alias in node.names:
        #             local_name = alias.asname or alias.name
        #             import_map[local_name] = alias.name

        #     elif isinstance(node, ast.ImportFrom):
        #         level = node.level
        #         module = node.module or ""

        #         # Handle relative imports (e.g., `from . import views` -> level 1)
        #         if level > 0:
        #             base = ".".join(base_package_parts[:len(base_package_parts) - level + 1])
        #             full_module = f"{base}.{module}" if module else base
        #         else:
        #             full_module = module

        #         for alias in node.names:
        #             local_name = alias.asname or alias.name
        #             import_map[local_name] = f"{full_module}.{alias.name}" if full_module else alias.name

        # # 2. EXTRACT ENDPOINTS USING THE IMPORT MAP
        # for node in ast.walk(tree):
        #     if isinstance(node, (ast.Assign, ast.AugAssign)):
        #         is_urlpatterns = False

        #         if isinstance(node, ast.Assign):
        #             for target in node.targets:
        #                 if isinstance(target, ast.Name) and target.id == 'urlpatterns':
        #                     is_urlpatterns = True
        #         elif isinstance(node, ast.AugAssign):
        #             if isinstance(node.target, ast.Name) and node.target.id == 'urlpatterns':
        #                 is_urlpatterns = True

        #         if is_urlpatterns and isinstance(node.value, (ast.List, ast.Tuple)):
        #             for element in node.value.elts:
        #                 if isinstance(element, ast.Call) and isinstance(element.func, ast.Name):
        #                     if element.func.id in ['path', 're_path', 'url']:
        #                         if len(element.args) >= 2:
        #                             view_arg = element.args[1]

        #                             # Target nodes to resolve
        #                             target_node = None
        #                             if isinstance(view_arg, (ast.Attribute, ast.Name)):
        #                                 target_node = view_arg
        #                             elif isinstance(view_arg, ast.Call) and isinstance(view_arg.func, ast.Attribute) and view_arg.func.attr == 'as_view':
        #                                 if isinstance(view_arg.func.value, (ast.Attribute, ast.Name)):
        #                                     target_node = view_arg.func.value

        #                             if target_node:
        #                                 full_path = self._resolve_view_path(target_node, import_map, ".".join(base_package_parts))
        #                                 if full_path:
        #                                     endpoints.add(full_path)

        # if not hasattr(self, 'endpoints') or self.endpoints is None:
        #     self.endpoints = set()
        # self.endpoints.update(endpoints)

    # deprecated
    def _resolve_view_path(
        self, node: ast.AST, import_map: dict, fallback_package: str
    ) -> str:
        """
        Takes an AST Name or Attribute node and looks it up in the import map
        to return the fully qualified module path.
        """
        pass
        # parts = []
        # curr = node

        # # Unroll the AST Attribute tree (e.g., some_app.views.MyView -> ['some_app', 'views', 'MyView'])
        # while isinstance(curr, ast.Attribute):
        #     parts.insert(0, curr.attr)
        #     curr = curr.value
        # if isinstance(curr, ast.Name):
        #     parts.insert(0, curr.id)

        # if not parts:
        #     return None

        # root = parts[0]

        # # If the root of the call (e.g., 'views' in 'views.my_view') is imported, map it.
        # if root in import_map:
        #     resolved_root = import_map[root]
        #     return ".".join([resolved_root] + parts[1:])
        # else:
        #     # If it's not in the imports, it might be in the exact same file/package natively
        #     return ".".join([fallback_package] + parts) if fallback_package else ".".join(parts)

    def is_schema(self, component: CodeComponent) -> bool:
        """
        Determines if an AST node represents an API Schema / Model.
        """
        # Schemas are almost exclusively defined as classes
        node = component.node

        if not isinstance(node, ast.ClassDef):
            return False

        if component.id in self.schemas:
            print("schemaschema")
            return True

        # The known base classes that indicate a schema
        schema_identifiers = {
            "BaseModel",  # Pydantic (FastAPI)
            "Serializer",  # DRF (Django)
            "ModelSerializer",  # DRF (Django)
            "Schema",  # Marshmallow (Flask)
        }

        # Examine what this class inherits from
        for base in node.bases:

            # 1. Catch direct inheritance: class User(BaseModel):
            if isinstance(base, ast.Name):
                if base.id in schema_identifiers:
                    self.schemas.add(component.id)
                    print("schemaschema")
                    return True

            # 2. Catch attributed inheritance: class User(pydantic.BaseModel):
            elif isinstance(base, ast.Attribute):
                if base.attr in schema_identifiers:
                    self.schemas.add(component.id)
                    print("schemaschema")
                    return True

        return False

    def is_endpoint(self, component: CodeComponent) -> bool:
        """Decide if a code component is a openAPI endpoint"""
        # for endpoint in self.endpoints:
        #     if endpoint in component.id:
        #         return self.endpoints[endpoint]
        if component.id in self.endpoints:
            return self.endpoints[component.id]

        return None
        # if framework == "django":
        #     # Assumes urls.py was parsed perfectly elsewhere
        #     return component.id in self.endpoints

        # elif framework in ["fastapi", "flask"]:

        #     # 1. Handle Function-Based Views (FBVs)
        #     if component.component_type == "function":
        #         for decorator in component.node.decorator_list:
        #             # Ensure the decorator is called as a function: e.g., @app.get("/")
        #             if isinstance(decorator, ast.Call):
        #                 method_name = None

        #                 # Catch @app.get(...) or @router.post(...)
        #                 if isinstance(decorator.func, ast.Attribute):
        #                     method_name = decorator.func.attr.lower()
        #                 # Catch @get(...) or @route(...)
        #                 elif isinstance(decorator.func, ast.Name):
        #                     method_name = decorator.func.id.lower()

        #                 # Expanded list of valid routing identifiers
        #                 valid_routers = {
        #                     'get', 'post', 'put', 'delete', 'patch',
        #                     'options', 'head', 'trace', 'route',
        #                     'api_route', 'websocket'
        #                 }

        #                 if method_name in valid_routers:
        #                     self.endpoints.add(component.id)
        #                     return True

        #     # 2. Handle Class-Based Views (CBVs) for Flask/FastAPI
        #     elif component.component_type == "class":
        #         # If your CodeComponent has access to base classes via AST
        #         for base in component.node.bases:
        #             if isinstance(base, ast.Name):
        #                 # Check for common Flask CBV base classes
        #                 if base.id in ['MethodView', 'View', 'Resource']:
        #                     self.endpoints.add(component.id)
        #                     return True
        #             elif isinstance(base, ast.Attribute):
        #                 # Catch cases like flask.views.MethodView
        #                 if base.attr in ['MethodView', 'View', 'Resource']:
        #                     self.endpoints.add(component.id)
        #                     return True

        #     return False

    # def collect_endpoints(self, tree: ast.AST, framework="django"):
    #     if framework == "django":


class DependencyParser:
    """Parse Python code to build a dependency graph between code components"""

    def __init__(
        self,
        project_dir: str,
        framework: str,
        output_dir: str,
        app_instance_path: str,
        python_exec: Optional[str] = None,
        compose_file: Optional[str] = "docker-compose.yml",
        service_name: Optional[str] = "app",
        excluded_dirs: Optional[List] = [],
        excluded_files: Optional[List] = [],
    ):
        """Initialize a dependency parser for a Python repository

        Args:
            project_dir: the root directory of the Python project to parse
            framework: the web framework used in the project (e.g., "django", "fastapi", "flask")
            output_dir: the directory to save the parsing results and generated documentation
            app_instance_path: the module path to the web application instance for endpoint extraction. Ex:"myapp.main:app" -> myapp.main is the module; app is the instance
            python_exec: the path to the Python environment to use for running the project (if needed for endpoint extraction)
            compose_file: the path to the docker-compose file to use for running the project (if needed for endpoint extraction)
            service_name: the name of the service running in docker
            excluded_dirs: a list of directory paths (relative to project_dir) to exclude from parsing
            excluded_files: a list of file paths to exclude from parsing

        Returns:
            A DependencyParser object"""
        self.project_dir = Path(os.path.abspath(project_dir))
        self.framework = framework
        self.output_dir = output_dir
        self.app_instance_path = app_instance_path
        self.python_exec = python_exec
        self.compose_file = compose_file
        self.service_name = service_name

        # Store specific full paths for the user-provided excluded directories
        self.excluded_dirs = set(
            self.project_dir / Path(d) for d in (excluded_dirs or [])
        )
        self.excluded_files = set(
            self.project_dir / Path(f) for f in (excluded_files or [])
        )

        self.components: Dict[str, CodeComponent] = {}
        # self.dependency_graph: Dict[str, List[str]] = {}
        self.modules: Set[str] = set()
        self.endpoints: OpenAPICollector = OpenAPICollector(
            framework=framework,
            project_dir=project_dir,
            output_dir=output_dir,
            app_instance_path=app_instance_path,
            python_exec=python_exec,
            compose_file=compose_file,
            service_name=service_name,
        )

        self.framework: Literal["django", "fastapi", "flask"] = framework

    def parse_repository(self) -> Dict[str, CodeComponent]:
        """Parse each Python files in the repository to build the dependency graph"""
        logger.info(f"Parsing repository at {self.project_dir}")
        print("Excluded directories: ", self.excluded_dirs)
        # First pass: collect all modules and code components
        python_files = []

        instance_file = (self.app_instance_path.split(":"))[0]
        instance_file = (instance_file.split("."))[:-2]
        main_dir = self.project_dir
        for part in instance_file:
            main_dir = main_dir / part

        for root, dirs, files in os.walk(main_dir):
            root_path = Path(root)

            # Prune traversal tree in-place using OS-agnostic Path comparison
            # Exclude global basenames (e.g., node_modules) and specific absolute paths
            dirs[:] = [
                d
                for d in dirs
                if d not in EXCLUDE_DIRS and (root_path / d) not in self.excluded_dirs
            ]

            for file in files:
                if not file.endswith(".py") or file == "__init__.py":
                    continue

                file_path = root_path / file
                if file_path in self.excluded_files:
                    continue

                python_files.append(str(file_path))

        for file_path in tqdm(python_files, desc="Parsing Python files", unit="file"):
            relative_path = os.path.relpath(file_path, main_dir)
            # COnvert file path to module path
            module_path = self._file_to_module_path(relative_path)
            self.modules.add(module_path)
            # Parse the file to collect code components
            self._parse_file(file_path, relative_path, module_path)

        logger.info("Creating dependency graph from the parsing result...")
        self._resolve_dependencies()

        logger.info("Adding class and method dependencies...")
        self._add_class_method_dependencies()

        for component in self.components.values():
            component.node = None
        gc.collect()

        logger.info(f"Found {len(self.components)} code components")
        return self.components

    def _file_to_module_path(self, file_path: str) -> str:
        """Convert a file path to a Python module path"""

        path = file_path[:-3] if file_path.endswith(".py") else file_path
        return path.replace(os.path.sep, ".")

    def _parse_file(self, file_path: str, relative_path: str, module_path: str):
        """Parse a single Python file to collect code components."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()

            tree = ast.parse(source)

            # Add parent field to AST nodes for easier traversal
            add_parent_to_nodes(tree)

            # if self.framework == "django" and file_path.endswith("urls.py"):
            #     self.endpoints.urls_endpoints(tree, module_path)

            self._collect_components(
                tree, file_path, relative_path, module_path, source
            )

        except (SyntaxError, UnicodeDecodeError) as e:
            logger.warning(f"Error parsing {file_path}: {e}")

    def _collect_components(
        self,
        tree: ast.AST,
        file_path: str,
        relative_path: str,
        module_path: str,
        source: str,
    ):
        """Collect all node components (functions, classes, methods) from an AST"""

        import_collector = ImportCollector(module_path)
        import_collector.visit(tree)
        for node in ast.walk(tree):
            # Collect class definition
            if isinstance(node, ast.ClassDef):
                # Class definition
                class_id = f"{module_path}.{node.name}"

                # Extract docstring if exist
                has_docstring, docstring = self._get_docstring(source, node)

                component = CodeComponent(
                    id=class_id,
                    node=node,
                    component_type="class",
                    file_path=file_path,
                    relative_path=relative_path,
                    imports=import_collector.imports,
                    from_imports=import_collector.from_imports,
                    depends_on=set(),
                    source_code=self._get_source_segment(source, node),
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    has_docstring=has_docstring,
                    docstring=docstring,
                    endpoint={},
                    schema="",
                    doc_type=[DocType.DOCSTRING.value],
                )

                endpoint = self.endpoints.is_endpoint(component)
                if endpoint:
                    component.doc_type.append(DocType.ENDPOINT.value)
                    component.api_methods = endpoint

                schema = self.endpoints.is_schema(component)
                if schema:
                    component.doc_type.append(DocType.SCHEMA.value)

                self.components[class_id] = component

                # Collect method definition
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name != "__init__"
                    ):
                        method_id = f"{class_id}.{item.name}"

                        has_docstring, docstring = self._get_docstring(source, item)

                        method_component = CodeComponent(
                            id=method_id,
                            node=item,
                            component_type="method",
                            file_path=file_path,
                            relative_path=relative_path,
                            imports=import_collector.imports,
                            from_imports=import_collector.from_imports,
                            depends_on=set(),
                            source_code=self._get_source_segment(source, item),
                            start_line=item.lineno,
                            end_line=getattr(item, "end_lineno", item.lineno),
                            has_docstring=has_docstring,
                            docstring=docstring,
                            endpoint={},
                            schema="",
                            doc_type=[DocType.DOCSTRING.value],
                        )
                        endpoint = self.endpoints.is_endpoint(method_component)
                        if endpoint:
                            method_component.doc_type.append(DocType.ENDPOINT.value)
                            method_component.api_methods = endpoint

                        self.components[method_id] = method_component

            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and not isinstance(node.parent, ast.ClassDef):
                # Collect top-level functions only
                if hasattr(node, "parent") and isinstance(node.parent, ast.Module):
                    func_id = f"{module_path}.{node.name}"

                    has_docstring, docstring = self._get_docstring(source, node)

                    func_component = CodeComponent(
                        id=func_id,
                        node=node,
                        component_type="function",
                        file_path=file_path,
                        relative_path=relative_path,
                        imports=import_collector.imports,
                        from_imports=import_collector.from_imports,
                        depends_on=set(),
                        source_code=self._get_source_segment(source, node),
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        has_docstring=has_docstring,
                        docstring=docstring,
                        endpoint={},
                        schema="",
                        doc_type=[DocType.DOCSTRING.value],
                    )
                    endpoint = self.endpoints.is_endpoint(func_component)
                    if endpoint:
                        func_component.doc_type.append(DocType.ENDPOINT.value)
                        func_component.api_methods = endpoint

                    self.components[func_id] = func_component

    def _get_docstring(self, source: str, node: ast.AST) -> Tuple[bool, str]:
        """Get docstring of a class, function or method"""
        try:
            has_docstring = (
                len(node.body) > 0
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )

            docstring = node.body[0].value.value if has_docstring else ""

            return has_docstring, docstring
        except Exception as e:
            logger.warning(f"Error getting docstring: {e}")
            return False, ""

    def _get_source_segment(self, source: str, node: ast.AST) -> str:
        """Get source segment for an AST node"""
        try:
            if hasattr(ast, "get_source_segment"):
                segment = ast.get_source_segment(source=source, node=node)

            else:
                lines = source.split("\n")
                startline = node.lineno - 1
                endline = getattr(node, "end_lineno", node.lineno) - 1
                segment = "\n".join(lines[startline : endline + 1])
            if hasattr(node, "decorator_list") and node.decorator_list:
                decorator_start_line = min(
                    decorator.lineno - 1 for decorator in node.decorator_list
                )
                lines = source.split("\n")
                decoratorblock = "\n".join(
                    lines[decorator_start_line : node.lineno - 1]
                )
                segment = decoratorblock + "\n" + segment

            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name != "__init__"
                    ):
                        method_str = self._get_source_segment(source, child)
                        segment = segment.replace(method_str, "")

            if segment is not None:
                return segment.strip()
            return ""
        except Exception as e:
            logger.warning(f"Error getting source segment: {e}")
            return ""

    def _resolve_dependencies(self):
        """Second pass to resolve dependencies between components"""

        for component_id, component in tqdm(
            self.components.items(), desc="Resolving Dependency", unit="code component"
        ):
            file_path = component.file_path
            module_path = self._file_to_module_path(component.relative_path)

            try:
                with open(file_path, "r") as f:
                    source = f.read()

                tree = ast.parse(source)

                add_parent_to_nodes(tree)

                import_collector = ImportCollector(module_path)
                import_collector.visit(tree)

                component_node = component.node

                dependency_collector = DependencyCollector(
                    import_collector.imports,
                    import_collector.from_imports,
                    module_path,
                    self.modules,
                )

                if isinstance(component_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in component_node.args.args:
                        dependency_collector.local_variable.add(arg.arg)

                dependency_collector.visit(component_node)

                # Add dependencies to the component:
                component.depends_on.update(dependency_collector.dependencies)

                # Filter out non-existent dependencies
                component.depends_on = {
                    dep for dep in component.depends_on if dep in self.components
                }

            except (SyntaxError, UnicodeDecodeError) as e:
                logger.warning(f"Error analyzing dependencies in {file_path}: {e}")

    def _add_class_method_dependencies(self):
        """Third pass to make methods dependent on their class (except __init__)"""
        for component_id, component in tqdm(
            self.components.items(),
            desc="Method & Class dependencies",
            unit="method&class",
        ):
            if component.component_type == "method":
                parts = component_id.split(".")
                method_name = parts[-1]
                class_id = ".".join(parts[:-1])
                if method_name == "__init__":
                    continue
                if (
                    class_id in self.components
                    and self.components[class_id].component_type == "class"
                ):
                    component.depends_on.add(class_id)

    def save_dependency_graph(self, storage_conn: Any) -> None:
        """Save the dependency graph to a JSON file"""
        # Convert to serializable format
        serializable_components = {
            comp_id: component.to_dict()
            for comp_id, component in self.components.items()
        }

        storage_conn.save(serializable_components)

        logger.info(f"Save dependency graph to {storage_conn.db_path}")

    def load_dependency_graph(self, input_path: str) -> None:
        """Load the dependency graph from a JSON file"""
        with open(input_path, "r", encoding="utf-8") as f:
            serialized_components = json.load(f)

        self.components = {
            comp_id: CodeComponent.from_dict(comp_data)
            for comp_id, comp_data in serialized_components.items()
        }

        logger.info(f"Loaded {len(self.components)} components from {input_path}")
        return self.components
