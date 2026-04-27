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
from src.utils.match import match_param

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
    PARAMETER = "parameter"


@dataclass
class CodeComponent:
    """Represent a single code component (function, parameter, class or method) in a Python codebase.
    Stores the component's identifier, AST node, dependencies, and other metadata."""

    # Unique identifier for the component, format: module_path.ClassName.method_name
    id: str

    # AST node representing this component
    node: ast.AST

    # Type of component: 'class', 'function', 'method', 'parameter' (for path and query parameter), 'global' (for global variables/constants)
    component_type: Literal["class", "function", "method", "parameter", "global"]

    # Full path to the file containing this component
    file_path: str

    # Relative path within the repo
    relative_path: str

    # Import modules
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
    docstring: str = ""
    endpoint: Dict[str, str] = field(default_factory=lambda: {})
    schema: str = ""
    parameter_description: str = ""
    doc_type: List[str] = field(default_factory=lambda: [DocType.DOCSTRING.value])
    api_methods: List[str] = field(default_factory=lambda: [])

    # For parameter components, indicate whether it's a path or query parameter
    parameter_type: Optional[Literal["path", "query"]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert this component to a dictionary representation for JSON serialization."""
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
            "parameter_type": self.parameter_type,
            "parameter_description": self.parameter_description,
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
            parameter_type=data.get("parameter_type", None),
            parameter_description=data.get("parameter_description", ""),
        )


class ImportCollector(ast.NodeVisitor):
    """Collect import statements from Python code."""

    def __init__(self, current_module: str):
        self.imports: Set[str] = set()
        self.from_imports: Dict[str, List[str]] = {}
        self.current_module = current_module

    def visit_Import(self, node: ast.Import):
        for name in node.names:
            self.imports.add(name.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module_name = node.module or ""

        if node.level > 0:
            # Relative import
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
            # Absolute import
            final_module = module_name

        if final_module not in self.from_imports:
            self.from_imports[final_module] = []
        for name in node.names:
            self.from_imports[final_module].append(name.name)

        self.generic_visit(node)


class DependencyCollector(ast.NodeVisitor):
    """Collect dependencies between code components by analyzing
    attribute access, function calls, and class references."""

    def __init__(self, imports, from_imports, current_module, repo_modules):
        self.imports = imports
        self.from_imports = from_imports
        self.current_module = current_module
        self.repo_modules = repo_modules
        self.dependencies: Set[str] = set()
        self._current_class = None
        self.local_variable: Set[str] = set()

    def _add_dependency(self, name: str) -> None:
        if (
            name in BUILTIN_TYPES
            or name in EXCLUDED_NAMES
            or name in self.local_variable
        ):
            return

        for module, imported_names in self.from_imports.items():
            if module in self.repo_modules and name in imported_names:
                self.dependencies.add(f"{module}.{name}")
                return

        self.dependencies.add(f"{self.current_module}.{name}")

    def _process_attribute(self, node: ast.AST) -> None:
        parts = []
        current = node

        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.insert(0, current.id)

            if parts[0] in self.local_variable or parts[0] in EXCLUDED_NAMES:
                return

            if (
                parts[0] in self.imports
                and parts[0] in self.repo_modules
                and len(parts) > 1
            ):
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
        old_class = self._current_class
        self._current_class = node.name

        for base in node.bases:
            if isinstance(base, ast.Name):
                self._add_dependency(base.id)
            elif isinstance(base, ast.Attribute):
                self._process_attribute(base)

        self._current_class = old_class
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            self._add_dependency(node.func.id)
        if isinstance(node.func, ast.Attribute):
            self._process_attribute(node.func)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self._add_dependency(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        self._process_attribute(node)
        self.generic_visit(node)

    def _process_annotation(self, node: Optional[ast.AST]) -> None:
        if node is None:
            return
        if isinstance(node, ast.Name):
            self._add_dependency(node.id)
        elif isinstance(node, ast.Attribute):
            self._process_attribute(node)
        elif isinstance(node, ast.Subscript):
            self._process_annotation(node.value)
            self._process_annotation(node.slice)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                self._process_annotation(elt)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            self._process_annotation(node.left)
            self._process_annotation(node.right)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for arg in node.args.args:
            self._process_annotation(arg.annotation)
        for arg in node.args.kwonlyargs:
            self._process_annotation(arg.annotation)
        if node.args.vararg:
            self._process_annotation(node.args.vararg.annotation)
        if node.args.kwarg:
            self._process_annotation(node.args.kwarg.annotation)
        if node.returns:
            self._process_annotation(node.returns)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)


def add_parent_to_nodes(tree: ast.AST) -> None:
    """Add a parent attribute to each node in the AST."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node


class OpenAPICollector:
    """Determine OpenAPI components (endpoints and schemas) for a project."""

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
        """Initialize OpenAPI component collector.

        Args:
            framework: the web framework used (e.g., "django", "fastapi", "flask")
            project_dir: the root directory of the Python project
            output_dir: the directory to save parsing results and generated documentation
            app_instance_path: module path to the web app instance, e.g. "myapp.main:app"
            python_exec: path to the Python environment for running the project
            compose_file: path to the docker-compose file
            service_name: name of the service running in docker
        """
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
            logger.error(f"Cannot get specification via docker: {e}")
            logger.info("Falling back to local environment")
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
                logger.error(f"Cannot get specification via local env: {e}")

        self.schemas: Set[str] = set()

    def is_schema(self, component: "CodeComponent") -> bool:
        """Determine if a component represents an API schema/model."""
        node = component.node
        if not isinstance(node, ast.ClassDef):
            return False
        if component.id in self.schemas:
            return True

        schema_identifiers = {
            "BaseModel",  # Pydantic (FastAPI)
            "Serializer",  # DRF (Django)
            "ModelSerializer",  # DRF (Django)
            "Schema",  # Marshmallow (Flask)
        }

        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in schema_identifiers:
                self.schemas.add(component.id)
                return True
            elif isinstance(base, ast.Attribute) and base.attr in schema_identifiers:
                self.schemas.add(component.id)
                return True

        return False

    def get_endpoint(self, component: "CodeComponent") -> Optional[Dict[str, str]]:
        """Return endpoint metadata if the component is an API endpoint, else None."""
        return self.endpoints.get(component.id)


class DependencyParser:
    """Parse Python code to build a dependency graph between code components."""

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
        """Initialize a dependency parser for a Python repository.

        Args:
            project_dir: the root directory of the Python project to parse
            framework: the web framework used (e.g., "django", "fastapi", "flask")
            output_dir: the directory to save parsing results and generated documentation
            app_instance_path: module path to the web app instance, e.g. "myapp.main:app"
            python_exec: path to the Python environment for running the project
            compose_file: path to the docker-compose file
            service_name: name of the service running in docker
            excluded_dirs: directory paths (relative to project_dir) to exclude from parsing
            excluded_files: file paths to exclude from parsing
        """
        self.project_dir = Path(os.path.abspath(project_dir))
        self.framework: Literal["django", "fastapi", "flask"] = framework
        self.output_dir = output_dir
        self.app_instance_path = app_instance_path
        self.python_exec = python_exec
        self.compose_file = compose_file
        self.service_name = service_name

        self.excluded_dirs = set(
            self.project_dir / Path(d) for d in (excluded_dirs or [])
        )
        self.excluded_files = set(
            self.project_dir / Path(f) for f in (excluded_files or [])
        )

        self.components: Dict[str, CodeComponent] = {}
        self.modules: Set[str] = set()
        self._source_cache: Dict[str, str] = {}

        self.endpoints = OpenAPICollector(
            framework=framework,
            project_dir=project_dir,
            output_dir=output_dir,
            app_instance_path=app_instance_path,
            python_exec=python_exec,
            compose_file=compose_file,
            service_name=service_name,
        )

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    def parse_repository(self) -> Dict[str, CodeComponent]:
        """Parse all Python files in the repository to build the dependency graph."""
        logger.info(f"Parsing repository at {self.project_dir}")
        logger.info(f"Excluded directories: {self.excluded_dirs}")

        instance_file = self.app_instance_path.split(":")[0]
        main_dir = self.project_dir
        for part in instance_file.split(".")[:-2]:
            main_dir = main_dir / part

        python_files = self._collect_python_files(main_dir)

        # Pass 1: collect all modules and components
        for file_path in tqdm(python_files, desc="Parsing Python files", unit="file"):
            relative_path = os.path.relpath(file_path, main_dir)
            module_path = self._file_to_module_path(relative_path)
            self.modules.add(module_path)
            self._parse_file(file_path, relative_path, module_path)

        # Pass 2: resolve cross-component dependencies
        logger.info("Resolving dependencies...")
        self._resolve_dependencies()

        # Pass 3: wire methods to their parent class
        logger.info("Adding class/method dependencies...")
        self._add_class_method_dependencies()

        # Pass 4: resolve Depends()-injected parameters (requires all components to exist)
        logger.info("Resolving Depends-injected parameters...")
        self._resolve_depends_params()

        for component in self.components.values():
            component.node = None
        gc.collect()

        logger.info(f"Found {len(self.components)} code components")
        return self.components

    # -------------------------------------------------------------------------
    # File helpers
    # -------------------------------------------------------------------------

    def _collect_python_files(self, main_dir: Path) -> List[str]:
        """Walk main_dir and return all parseable Python file paths."""
        python_files = []
        for root, dirs, files in os.walk(main_dir):
            root_path = Path(root)
            dirs[:] = [
                d
                for d in dirs
                if d not in EXCLUDE_DIRS and (root_path / d) not in self.excluded_dirs
            ]
            for file in files:
                if not file.endswith(".py") or file == "__init__.py":
                    continue
                file_path = root_path / file
                if file_path not in self.excluded_files:
                    python_files.append(str(file_path))
        return python_files

    def _file_to_module_path(self, file_path: str) -> str:
        """Convert a relative file path to a dotted Python module path."""
        path = file_path[:-3] if file_path.endswith(".py") else file_path
        return path.replace(os.path.sep, ".")

    def _module_to_file(self, module_path: str) -> Optional[str]:
        """Convert a dotted module path back to an absolute file path, or None if not found."""
        relative = module_path.replace(".", os.path.sep) + ".py"
        candidate = self.project_dir / relative
        if candidate.exists():
            return str(candidate)
        # Fallback: walk the project to find a file whose path ends with the module
        for root, _, files in os.walk(self.project_dir):
            for f in files:
                if not f.endswith(".py"):
                    continue
                full = Path(root) / f
                if str(full).replace(os.path.sep, ".").endswith(module_path + ".py"):
                    return str(full)
        return None

    def _read_source(self, file_path: str) -> str:
        """Read source from a file with simple caching."""
        if file_path not in self._source_cache:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self._source_cache[file_path] = f.read()
            except Exception:
                self._source_cache[file_path] = ""
        return self._source_cache[file_path]

    def _parse_file(self, file_path: str, relative_path: str, module_path: str):
        """Parse a single Python file and collect its components."""
        try:
            source = self._read_source(file_path)
            tree = ast.parse(source)
            add_parent_to_nodes(tree)
            self._collect_components(
                tree, file_path, relative_path, module_path, source
            )
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.warning(f"Error parsing {file_path}: {e}")

    # -------------------------------------------------------------------------
    # Pass 1: component collection
    # -------------------------------------------------------------------------

    def _collect_components(
        self,
        tree: ast.AST,
        file_path: str,
        relative_path: str,
        module_path: str,
        source: str,
    ):
        """Collect all code components (functions, classes, methods, globals) from an AST."""
        import_collector = ImportCollector(module_path)
        import_collector.visit(tree)

        self._collect_global_assignments(
            tree, file_path, relative_path, module_path, source, import_collector
        )

        for node in ast.walk(tree):
            # --- CLASS ---
            if isinstance(node, ast.ClassDef):
                class_id = f"{module_path}.{node.name}"
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

                endpoint_metadata = self.endpoints.get_endpoint(component)
                if endpoint_metadata:
                    component.doc_type.append(DocType.ENDPOINT.value)
                    component.api_methods = endpoint_metadata.get("endpoints", [])

                if self.endpoints.is_schema(component):
                    component.doc_type.append(DocType.SCHEMA.value)

                self.components[class_id] = component

                # --- METHODS ---
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

                        endpoint_metadata = self.endpoints.get_endpoint(
                            method_component
                        )
                        if endpoint_metadata:
                            method_component.doc_type.append(DocType.ENDPOINT.value)
                            method_component.api_methods = endpoint_metadata.get(
                                "endpoints", []
                            )
                            param_ids = self._collect_direct_params(
                                node=item,
                                component_id=method_id,
                                endpoint_metadata=endpoint_metadata,
                                file_path=file_path,
                                relative_path=relative_path,
                                import_collector=import_collector,
                                source=source,
                            )
                            method_component.depends_on.update(param_ids)

                        self.components[method_id] = method_component

            # --- TOP-LEVEL FUNCTIONS ---
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and hasattr(node, "parent")
                and isinstance(node.parent, ast.Module)
            ):
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

                endpoint_metadata = self.endpoints.get_endpoint(func_component)
                if endpoint_metadata:
                    func_component.doc_type.append(DocType.ENDPOINT.value)
                    func_component.api_methods = endpoint_metadata.get("endpoints", [])
                    param_ids = self._collect_direct_params(
                        node=node,
                        component_id=func_id,
                        endpoint_metadata=endpoint_metadata,
                        file_path=file_path,
                        relative_path=relative_path,
                        import_collector=import_collector,
                        source=source,
                    )
                    func_component.depends_on.update(param_ids)

                self.components[func_id] = func_component

    def _collect_global_assignments(
        self,
        tree: ast.AST,
        file_path: str,
        relative_path: str,
        module_path: str,
        source: str,
        import_collector: ImportCollector,
    ) -> None:
        """Collect module-level variable assignments as 'global' components."""
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(getattr(node, "parent", None), ast.Module)
            ):
                var_name = node.targets[0].id
                var_id = f"{module_path}.{var_name}"
                self.components[var_id] = CodeComponent(
                    id=var_id,
                    node=node,
                    component_type="global",
                    file_path=file_path,
                    relative_path=relative_path,
                    imports=import_collector.imports,
                    from_imports=import_collector.from_imports,
                    depends_on=set(),
                    source_code=self._get_source_segment(source, node),
                    start_line=getattr(node, "lineno", 0),
                    end_line=getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                    has_docstring=False,
                    docstring="",
                    endpoint={},
                    schema="",
                    doc_type=[DocType.DOCSTRING.value],
                )

    def _collect_direct_params(
        self,
        node: ast.FunctionDef,
        component_id: str,
        endpoint_metadata: Dict,
        file_path: str,
        relative_path: str,
        import_collector: ImportCollector,
        source: str,
    ) -> List[str]:
        """Collect parameter components for args that are directly path/query params.

        Depends()-injected params are handled later in _resolve_depends_params (pass 4),
        once all components are guaranteed to exist.
        """
        param_ids = []
        path_params = endpoint_metadata.get("path_params", [])
        query_params = endpoint_metadata.get("query_params", [])

        for arg in node.args.args:
            if arg.arg in EXCLUDED_NAMES:
                continue
            if arg.arg not in path_params and arg.arg not in query_params:
                continue

            param_id = f"{component_id}.{arg.arg}"
            start_line = getattr(arg, "lineno", node.lineno)
            end_line = getattr(arg, "end_lineno", start_line)

            self.components[param_id] = CodeComponent(
                id=param_id,
                node=arg,
                component_type="parameter",
                parameter_type="path" if arg.arg in path_params else "query",
                file_path=file_path,
                relative_path=relative_path,
                imports=import_collector.imports,
                from_imports=import_collector.from_imports,
                depends_on=set(),
                source_code=self._get_source_segment(source, arg),
                start_line=start_line,
                end_line=end_line,
                has_docstring=False,
                docstring="",
                endpoint={},
                schema="",
                doc_type=[DocType.PARAMETER.value, DocType.DOCSTRING.value],
            )
            param_ids.append(param_id)

        return param_ids

    # -------------------------------------------------------------------------
    # Pass 2: dependency resolution
    # -------------------------------------------------------------------------

    def _resolve_dependencies(self):
        """Resolve cross-component dependencies by re-visiting each component's AST node."""
        for component_id, component in tqdm(
            self.components.items(), desc="Resolving dependencies", unit="component"
        ):
            file_path = component.file_path
            module_path = self._file_to_module_path(component.relative_path)

            try:
                source = self._read_source(file_path)
                tree = ast.parse(source)
                add_parent_to_nodes(tree)

                import_collector = ImportCollector(module_path)
                import_collector.visit(tree)

                component_node = component.node
                dep_collector = DependencyCollector(
                    import_collector.imports,
                    import_collector.from_imports,
                    module_path,
                    self.modules,
                )

                if isinstance(component_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in component_node.args.args:
                        dep_collector.local_variable.add(arg.arg)

                if component.component_type == "parameter" and hasattr(
                    component_node, "annotation"
                ):
                    dep_collector._process_annotation(component_node.annotation)
                else:
                    dep_collector.visit(component_node)

                component.depends_on.update(dep_collector.dependencies)
                # Filter out dependencies that don't map to a known component
                component.depends_on = {
                    dep for dep in component.depends_on if dep in self.components
                }

            except (SyntaxError, UnicodeDecodeError) as e:
                logger.warning(f"Error resolving dependencies in {file_path}: {e}")

    # -------------------------------------------------------------------------
    # Pass 3: class/method wiring
    # -------------------------------------------------------------------------

    def _add_class_method_dependencies(self):
        """Make each method depend on its parent class."""
        for component_id, component in tqdm(
            self.components.items(), desc="Wiring class/method deps", unit="component"
        ):
            if component.component_type != "method":
                continue
            parts = component_id.split(".")
            class_id = ".".join(parts[:-1])
            if (
                class_id in self.components
                and self.components[class_id].component_type == "class"
            ):
                component.depends_on.add(class_id)

    # -------------------------------------------------------------------------
    # Pass 4: Depends()-injected parameter resolution
    # -------------------------------------------------------------------------

    def _resolve_depends_params(self):
        """Resolve parameters injected via Annotated[..., Depends(func)] for all endpoints.

        Runs after all components are collected (pass 1) so the target depends
        function is guaranteed to exist in self.components.
        """
        # Group endpoint functions/methods by file to minimise re-parsing
        file_to_endpoints: Dict[str, List[CodeComponent]] = {}
        for component in self.components.values():
            if DocType.ENDPOINT.value not in component.doc_type:
                continue
            if component.component_type not in ("function", "method"):
                continue
            file_to_endpoints.setdefault(component.file_path, []).append(component)

        for file_path, endpoint_components in tqdm(
            file_to_endpoints.items(), desc="Resolving Depends params", unit="file"
        ):
            try:
                source = self._read_source(file_path)
                tree = ast.parse(source)
                add_parent_to_nodes(tree)
            except Exception as e:
                logger.warning(f"Could not re-parse {file_path}: {e}")
                continue

            module_path = self._file_to_module_path(
                os.path.relpath(file_path, self.project_dir)
            )
            import_collector = ImportCollector(module_path)
            import_collector.visit(tree)

            # Map function name -> AST node for quick lookup within this file
            func_node_map: Dict[str, ast.AST] = {
                node.name: node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

            for component in endpoint_components:
                endpoint_metadata = self.endpoints.get_endpoint(component)
                if not endpoint_metadata:
                    continue

                path_params = endpoint_metadata.get("path_params", [])
                query_params = endpoint_metadata.get("query_params", [])

                func_name = component.id.split(".")[-1]
                func_node = func_node_map.get(func_name)
                if func_node is None:
                    continue

                for arg in func_node.args.args:
                    if arg.arg in EXCLUDED_NAMES:
                        continue

                    # Skip args already collected as direct params in pass 1
                    if f"{component.id}.{arg.arg}" in self.components:
                        continue

                    depends_func_id = self._resolve_depends_func(
                        arg, tree, module_path, import_collector
                    )
                    if not depends_func_id or depends_func_id not in self.components:
                        continue
                    depends_func_component = self.components[depends_func_id]
                    depends_source = self._read_source(depends_func_component.file_path)

                    try:
                        depends_tree = ast.parse(depends_source)
                    except Exception as e:
                        logger.warning(f"Could not parse depends file: {e}")
                        continue

                    depends_func_name = depends_func_id.split(".")[-1]
                    depends_func_node = next(
                        (
                            n
                            for n in ast.walk(depends_tree)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and n.name == depends_func_name
                        ),
                        None,
                    )
                    if depends_func_node is None:
                        continue

                    for inner_arg in depends_func_node.args.args:
                        if inner_arg.arg in EXCLUDED_NAMES:
                            continue
                        if not match_param(
                            inner_arg.arg, path_params
                        ) and not match_param(inner_arg.arg, query_params):
                            continue

                        inner_param_id = f"{component.id}.{inner_arg.arg}"
                        if inner_param_id in self.components:
                            continue

                        start_line = getattr(
                            inner_arg, "lineno", depends_func_node.lineno
                        )
                        end_line = getattr(inner_arg, "end_lineno", start_line)

                        self.components[inner_param_id] = CodeComponent(
                            id=inner_param_id,
                            node=inner_arg,
                            component_type="parameter",
                            parameter_type=(
                                "path" if inner_arg.arg in path_params else "query"
                            ),
                            # file_path/relative_path point to the depends function's file
                            # so line-number tracing resolves to where the arg is written
                            file_path=depends_func_component.file_path,
                            relative_path=depends_func_component.relative_path,
                            imports=depends_func_component.imports,
                            from_imports=depends_func_component.from_imports,
                            depends_on=set(),
                            source_code=self._get_source_segment(
                                depends_source, inner_arg
                            ),
                            start_line=start_line,
                            end_line=end_line,
                            has_docstring=False,
                            docstring="",
                            endpoint={},
                            schema="",
                            doc_type=[DocType.PARAMETER.value, DocType.DOCSTRING.value],
                        )
                        component.depends_on.add(inner_param_id)

    # -------------------------------------------------------------------------
    # Depends() resolution helpers
    # -------------------------------------------------------------------------

    def _resolve_depends_func(
        self,
        arg: ast.arg,
        tree: ast.AST,
        module_path: str,
        import_collector: ImportCollector,
    ) -> Optional[str]:
        """Return the component ID of the function inside Depends() for this arg, or None.

        Handles both direct annotations and type-alias indirection:
          - Direct:  param: Annotated[..., Depends(common_parameters)]
          - Aliased: CommonParameters = Annotated[..., Depends(common_parameters)]
                     param: CommonParameters
        """
        annotation = arg.annotation
        if annotation is None:
            return None

        # Unwrap a Name alias, e.g. CommonParameters — pass import_collector so
        # _resolve_alias can follow imports into other files if the alias is defined there
        if isinstance(annotation, ast.Name):
            annotation, mod = self._resolve_alias(annotation.id, tree, import_collector)
            if annotation is None:
                return None
            if mod is not None:
                module_path = mod
        return self._extract_depends_from_annotated(
            annotation, module_path, import_collector
        )

    def _resolve_alias(
        self,
        name: str,
        tree: ast.AST,
        import_collector: ImportCollector,
    ) -> Tuple[Optional[ast.AST], Optional[str]]:
        """Return the RHS of `name = <expr>`, searching the current file first,
        then any imported file that exports `name`.

        The parent check from earlier versions is intentionally omitted: nodes in
        trees not processed by add_parent_to_nodes have no parent attribute, and
        matching by exact variable name is already precise enough.
        """
        # Search current file first
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name
            ):
                return node.value, None

        # Not found locally — follow imports into other files
        for mod, names in import_collector.from_imports.items():
            if name not in names:
                continue
            mod_file = self._module_to_file(mod)
            if mod_file is None:
                continue
            try:
                source = self._read_source(mod_file)
                imported_tree = ast.parse(source)
                for node in ast.walk(imported_tree):
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == name
                    ):
                        return node.value, mod
            except Exception as e:
                logger.warning(f"Could not search alias '{name}' in {mod_file}: {e}")

        return None, None

    def _extract_depends_from_annotated(
        self,
        node: ast.AST,
        module_path: str,
        import_collector: ImportCollector,
    ) -> Optional[str]:
        """Extract the component ID of the function inside Depends() from an Annotated[...] node."""
        if not isinstance(node, ast.Subscript):
            return None

        outer = node.value
        is_annotated = (isinstance(outer, ast.Name) and outer.id == "Annotated") or (
            isinstance(outer, ast.Attribute) and outer.attr == "Annotated"
        )
        if not is_annotated:
            return None

        slice_node = node.slice
        if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) < 2:
            return None

        for meta in slice_node.elts[1:]:
            if not isinstance(meta, ast.Call):
                continue
            func = meta.func
            is_depends = (isinstance(func, ast.Name) and func.id == "Depends") or (
                isinstance(func, ast.Attribute) and func.attr == "Depends"
            )
            if not is_depends or not meta.args:
                continue

            dep_func_node = meta.args[0]

            if isinstance(dep_func_node, ast.Name):
                func_name = dep_func_node.id
                # Check if imported from another module in the repo
                for mod, names in import_collector.from_imports.items():
                    if func_name in names and mod in self.modules:
                        return f"{mod}.{func_name}"
                # Otherwise treat as local to current module
                return f"{module_path}.{func_name}"

            elif isinstance(dep_func_node, ast.Attribute):
                parts = []
                curr = dep_func_node
                while isinstance(curr, ast.Attribute):
                    parts.insert(0, curr.attr)
                    curr = curr.value
                if isinstance(curr, ast.Name):
                    parts.insert(0, curr.id)
                    return ".".join(parts)

        return None

    # -------------------------------------------------------------------------
    # AST / source helpers
    # -------------------------------------------------------------------------

    def _get_docstring(self, source: str, node: ast.AST) -> Tuple[bool, str]:
        """Extract the docstring from a class or function node, if present."""
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
        """Return the source code segment corresponding to an AST node."""
        try:
            if hasattr(ast, "get_source_segment"):
                segment = ast.get_source_segment(source=source, node=node)
            else:
                lines = source.split("\n")
                start = node.lineno - 1
                end = getattr(node, "end_lineno", node.lineno) - 1
                segment = "\n".join(lines[start : end + 1])

            # Prepend decorators if present
            if hasattr(node, "decorator_list") and node.decorator_list:
                dec_start = min(d.lineno - 1 for d in node.decorator_list)
                lines = source.split("\n")
                segment = "\n".join(lines[dec_start : node.lineno - 1]) + "\n" + segment

            # For classes: strip out method bodies (they are separate components)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name != "__init__"
                    ):
                        segment = segment.replace(
                            self._get_source_segment(source, child), ""
                        )

            return segment.strip() if segment is not None else ""
        except Exception as e:
            logger.warning(f"Error getting source segment: {e}")
            return ""

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def save_dependency_graph(self, storage_conn: Any) -> None:
        """Save the dependency graph via storage_conn and as a JSON file."""
        serializable = {
            comp_id: component.to_dict()
            for comp_id, component in self.components.items()
        }

        storage_conn.save(serializable)

        try:
            out_path = Path(self.output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            with open(out_path / "dependency_graph.json", "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error saving dependency graph to JSON: {e}")

        logger.info(f"Saved dependency graph to {storage_conn.db_path}")

    def load_dependency_graph(self, input_path: str) -> Dict[str, CodeComponent]:
        """Load the dependency graph from a JSON file."""
        with open(input_path, "r", encoding="utf-8") as f:
            serialized = json.load(f)

        self.components = {
            comp_id: CodeComponent.from_dict(comp_data)
            for comp_id, comp_data in serialized.items()
        }

        logger.info(f"Loaded {len(self.components)} components from {input_path}")
        return self.components