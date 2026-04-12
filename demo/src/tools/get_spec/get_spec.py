import logging
import subprocess
import time
import json
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

class SpecGetterException(Exception):
    pass

class SpecGetterFactory:
    """
    Unified Factory to instantiate the correct framework spec getter based on mode (local vs docker).
    """
    @staticmethod
    def create(
        framework: Literal["django", "fastapi", "flask"], 
        mode: Literal["local", "docker"],
        project_dir: str, 
        output_dir: str, 
        app_instance_path: str,
        # Local specific
        python_exec: Optional[str] = None,
        # Docker specific
        compose_file: Optional[str] = "docker-compose.yml", 
        service_name: str = "app"
    ):

        if mode == "local":
            if not python_exec:
                raise ValueError("python_exec path must be provided for 'local' mode.")
            getters = {
                "django": DjangoLocalGetter,
                "fastapi": FastAPILocalGetter,
                "flask": FlaskLocalGetter,
            }
            getter_class = getters.get(framework)
            if not getter_class:
                raise ValueError(f"Unsupported framework: {framework} for local mode.")
            return getter_class(project_dir, output_dir, app_instance_path, python_exec)

        elif mode == "docker":
            getters = {
                "django": DjangoDockerGetter,
                "fastapi": FastAPIDockerGetter,
                "flask": FlaskDockerGetter,
            }
            getter_class = getters.get(framework)
            if not getter_class:
                raise ValueError(f"Unsupported framework: {framework} for docker mode.")
            return getter_class(project_dir, output_dir, app_instance_path, compose_file, service_name)
        
        else:
            raise ValueError(f"Unsupported mode: {mode}. Use 'local' or 'docker'.")


# =========================================================================================
# BASE SHARED LOGIC
# =========================================================================================

class BaseSpecGetter:
    file_extension = ".json"

    def __init__(self, project_dir: str, output_dir: str, app_instance_path: Optional[str]):
        self.project_dir = Path(project_dir).resolve()
        self.app_instance_path = app_instance_path
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        self.output_file = (output_path / self.project_dir.name).with_suffix(self.file_extension)

    def load(self):
        """
        Memory efficient line-by-line reading of the generated JSON or YAML file.
        Detects endpoints progressively to prevent Out-Of-Memory errors on massive spec dumps.
        """
        with open(self.output_file, 'r', encoding='utf-8') as f:
            in_paths = False
            current_path = None
            valid_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
            
            for line in f:
                if self.file_extension == ".json":
                    # JSON Logic
                    if not in_paths:
                        if line.startswith('  "paths":'):
                            in_paths = True
                        continue
                    if line.startswith('  }'):
                        break  
                    if line.startswith('    "/') and '": {' in line:
                        current_path = line.strip().split('":')[0].strip('"')
                    elif current_path and line.startswith('      "') and '": {' in line:
                        method = line.strip().split('":')[0].strip('"').lower()
                        if method in valid_methods:
                            yield f"{method}:{current_path}"
                            
                elif self.file_extension == ".yaml":
                    # YAML Logic (drf-spectacular default)
                    if not in_paths:
                        if line.startswith('paths:'):
                            in_paths = True
                        continue
                    if in_paths:
                        if line and not line.startswith(' ') and not line.startswith('\n') and not line.startswith('#'):
                            break
                        if line.startswith('  /') and not line.startswith('   '):
                            current_path = line.strip().rstrip(':').strip("'\"")
                        elif current_path and line.startswith('    ') and not line.startswith('      ') and line.endswith(':\n'):
                            method = line.strip().rstrip(':').strip("'\"").lower()
                            if method in valid_methods:
                                yield f"{method}:{current_path}"

    def endpoints(self) -> list:
        """Returns a list of all API endpoints."""
        return list(self.load())

    def _process_map(self, raw_map: dict) -> dict:
        """
        Filters out internal routes by comparing against API endpoints, 
        and inverts the dictionary mapping format.
        Returns: { "module.function": ["/api/v1/endpoint", ...] }
        """
        import re
        api_endpoints = self.endpoints()
        
        def normalize(p: str) -> str:
            # Strip out different route parameter definitions across formats to match them
            p = re.sub(r'\{[^}]+\}', '{}', p)
            p = re.sub(r'<[^>]+>', '{}', p)
            p = re.sub(r'\(\?P<[^>]+>[^\)]+\)', '{}', p)
            # Remove regex formatting from django
            p = p.replace('^', '').replace('$', '')
            
            # Extract method if it exists
            parts = p.split(':', 1)
            if len(parts) == 2 and parts[0] in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                return f"{parts[0]}:{parts[1].strip('/')}"
            else:
                return p.strip('/')

        # Precompute normalized OpenAPI endpoints
        normalized_apis = {normalize(ep): ep for ep in api_endpoints}
        
        processed = {}
        for raw_url, func_list in raw_map.items():
            # If the intermediate map wasn't returning a list (like from an older run or unsupported change), wrap it to avoid breaking
            if not isinstance(func_list, list):
                func_list = [func_list]

            norm_raw = normalize(raw_url)
            has_method = ":" in norm_raw
            
            matched_eps = []
            if has_method:
                if norm_raw in normalized_apis:
                    matched_eps.append(normalized_apis[norm_raw])
                else:
                    # Fuzzy fallback matching
                    for api_n, original_ep in normalized_apis.items():
                        if norm_raw == api_n or (api_n and norm_raw and norm_raw.endswith(api_n.split(':', 1)[-1])):
                            # Enforce method matching if fuzzy matching path
                            if api_n.startswith(norm_raw.split(':', 1)[0] + ':'):
                                matched_eps.append(original_ep)
            else:
                # No method specified - Map to ALL generated methods for this exact path
                for api_n, original_ep in normalized_apis.items():
                    api_n_path = api_n.split(':', 1)[-1]
                    if norm_raw == api_n_path or (api_n_path and norm_raw and norm_raw.endswith(api_n_path)):
                        matched_eps.append(original_ep)

            # Add uniquely
            for matched_ep in set(matched_eps):
                for func in func_list:
                    if func not in processed:
                        processed[func] = []
                    if matched_ep not in processed[func]:
                        processed[func].append(matched_ep)
                    
        return processed

    def get_spec(self) -> bool:
        raise NotImplementedError

    # ---------------------------------------------------------
    # Shared Extraction Scripts (Injected into Target context)
    # ---------------------------------------------------------
    def _build_fastapi_script(self, target_output_path: str) -> str:
        if not self.app_instance_path:
            self.app_instance_path = "main:app"
        module_name, object_name = self.app_instance_path.split(":")
        
        return f"""
import sys, json, traceback
sys.path.insert(0, r'{self.project_dir}')
try:
    from {module_name} import {object_name} as target_api
    with open(r'{target_output_path}', 'w') as f:
        json.dump(target_api.openapi(), f, indent=2)
except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)
"""

    def _build_flask_script(self, target_output_path: str) -> str:
        module_name, object_name = self.app_instance_path.split(":")
        base_module_name = module_name.split('.')[0]
        
        return f"""
import sys, json, traceback, importlib
sys.path.insert(0, r'{self.project_dir}')
try:
    app = None
    try:
        base_module = importlib.import_module('{base_module_name}')
        if hasattr(base_module, 'create_app'):
            app = base_module.create_app()
        elif hasattr(base_module, 'app'):
            app = base_module.app
    except Exception:
        pass
        
    def extract():
        from {module_name} import {object_name} as target_api
        if hasattr(target_api, '__schema__'):
            try:
                from flask_restx.swagger import Swagger
                schema = Swagger(target_api).as_dict()
            except Exception:
                sys.stderr.write("SWAGGER GENERATION ERROR:\\n" + traceback.format_exc())
                sys.exit(1)
        elif hasattr(target_api, '_schema'):
            schema = target_api._schema.to_dict() if hasattr(target_api._schema, 'to_dict') else target_api._schema
        elif hasattr(target_api, 'spec'):
            try:
                schema = target_api.spec.to_dict()
            except AttributeError:
                schema = target_api.spec
        else:
            raise AttributeError(f"Could not find schema attributes on {object_name}. Available: {{dir(target_api)}}")
            
        with open(r'{target_output_path}', 'w') as f:
            json.dump(schema, f, indent=2)

    if app is not None:
        app.config['SERVER_NAME'] = 'localhost'
        with app.app_context():
            with app.test_request_context():
                extract()
    else:
        extract()

except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)
"""

    def _build_django_map_script(self, target_output_path: str) -> str:
        manage_py_dir = Path(self.app_instance_path).parent if self.app_instance_path else self.project_dir
        
        return f"""
import sys, json, traceback, os
import django
from django.urls import get_resolver, URLPattern, URLResolver

sys.path.insert(0, r'{manage_py_dir}')
# Best effort guess based on typical structures. User might need to adapt DJANGO_SETTINGS_MODULE
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "netbox.settings")

try:
    django.setup()
    
    def extract_views(urlpatterns, prefix=''):
        views = {{}}
        for pattern in urlpatterns:
            if hasattr(pattern, 'pattern'):
                pattern_str = str(pattern.pattern)
            else:
                pattern_str = str(pattern.regex.pattern)

            if isinstance(pattern, URLPattern):
                path = prefix + pattern_str
                path = path.replace('^', '/').replace('$', '').replace('//', '/')
                
                func = pattern.callback
                module = func.__module__ if hasattr(func, '__module__') else ''
                name = func.__name__ if hasattr(func, '__name__') else str(func)
                func_name = f"{{module}}.{{name}}"
                
                if path not in views:
                    views[path] = []
                if func_name not in views[path]:
                    views[path].append(func_name)
                    
            elif isinstance(pattern, URLResolver):
                new_prefix = prefix + pattern_str
                sub_views = extract_views(pattern.url_patterns, new_prefix)
                for k, v in sub_views.items():
                    if k not in views:
                        views[k] = []
                    for f_name in v:
                        if f_name not in views[k]:
                            views[k].append(f_name)
        return views

    resolver = get_resolver()
    url_map = extract_views(resolver.url_patterns)

    with open(r'{target_output_path}', 'w') as f:
        json.dump(url_map, f, indent=2)

except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)
"""

    def _build_fastapi_map_script(self, target_output_path: str) -> str:
        if not self.app_instance_path:
            self.app_instance_path = "main:app"
        module_name, object_name = self.app_instance_path.split(":")
        
        return f"""
import sys, json, traceback
sys.path.insert(0, r'{self.project_dir}')

try:
    from {module_name} import {object_name} as app
    
    url_map = {{}}
    for route in app.routes:
        if hasattr(route, "endpoint"):
            module = route.endpoint.__module__
            name = route.endpoint.__name__
            func_name = f"{{module}}.{{name}}"
            
            methods = getattr(route, "methods", {{"GET"}})
            for method in methods:
                path_key = f"{{method.lower()}}:{{route.path}}"
                if path_key not in url_map:
                    url_map[path_key] = []
                if func_name not in url_map[path_key]:
                    url_map[path_key].append(func_name)
        
    with open(r'{target_output_path}', 'w') as f:
        json.dump(url_map, f, indent=2)

except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)
"""

    def _build_flask_map_script(self, target_output_path: str) -> str:
        module_name, object_name = self.app_instance_path.split(":")
        base_module_name = module_name.split('.')[0]
        
        return f"""
import sys, json, traceback, importlib
sys.path.insert(0, r'{self.project_dir}')

try:
    app = None
    try:
        base_module = importlib.import_module('{base_module_name}')
        if hasattr(base_module, 'create_app'):
            app = base_module.create_app()
        elif hasattr(base_module, 'app'):
            app = base_module.app
    except Exception:
        pass
        
    if app is None:
        sys.stderr.write("Could not load Flask app to extract url_map")
        sys.exit(1)
        
    url_map = {{}}
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            func = app.view_functions[rule.endpoint]
            module = func.__module__
            name = func.__name__
            func_name = f"{{module}}.{{name}}"
            rule_str = str(rule)
            
            for method in rule.methods:
                if method not in ('HEAD', 'OPTIONS'):
                    path_key = f"{{method.lower()}}:{{rule_str}}"
                    if path_key not in url_map:
                        url_map[path_key] = []
                    if func_name not in url_map[path_key]:
                        url_map[path_key].append(func_name)

    with open(r'{target_output_path}', 'w') as f:
        json.dump(url_map, f, indent=2)

except Exception:
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)
"""


# =========================================================================================
# LOCAL EXECUTION MODE
# =========================================================================================

class LocalBaseGetter(BaseSpecGetter):
    def __init__(self, project_dir: str, output_dir: str, app_instance_path: Optional[str], python_exec: str):
        super().__init__(project_dir, output_dir, app_instance_path)
        self.python_exec = str(Path(python_exec))

    def run_local_extractor(self, extractor_code: str) -> bool:
        try:
            subprocess.run(
                [self.python_exec],
                input=extractor_code,
                text=True,
                capture_output=True,
                check=True,
                cwd=str(self.project_dir),
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Local Spec extraction failed: {e.stderr}")
            return False

    def endpoint_func_map(self) -> dict:
        raise NotImplementedError

class DjangoLocalGetter(LocalBaseGetter):
    file_extension = ".yaml"
    def get_spec(self) -> bool:
        if not self.output_file.exists():
            self.output_file.touch()
        # Find manage.py (might be at root or one level deep like netbox/netbox)
        manage_py_path = self.app_instance_path

        command = [self.python_exec, str(manage_py_path), 'spectacular', '--file', str(self.output_file)]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Django local spec generation failed: {e.stderr}")
            return False

    def endpoint_func_map(self) -> dict:
        map_file = self.output_file.with_name(f"{self.output_file.stem}_map.json")
        script = self._build_django_map_script(str(map_file))
        if self.run_local_extractor(script) and map_file.exists():
            with open(map_file, 'r', encoding='utf-8') as f:
                return self._process_map(json.load(f))
        return {}

class FastAPILocalGetter(LocalBaseGetter):
    def get_spec(self) -> bool:
        return self.run_local_extractor(self._build_fastapi_script(str(self.output_file)))

    def endpoint_func_map(self) -> dict:
        map_file = self.output_file.with_name(f"{self.output_file.stem}_map.json")
        script = self._build_fastapi_map_script(str(map_file))
        if self.run_local_extractor(script) and map_file.exists():
            with open(map_file, 'r', encoding='utf-8') as f:
                return self._process_map(json.load(f))
        return {}

class FlaskLocalGetter(LocalBaseGetter):
    def get_spec(self) -> bool:
        return self.run_local_extractor(self._build_flask_script(str(self.output_file)))

    def endpoint_func_map(self) -> dict:
        map_file = self.output_file.with_name(f"{self.output_file.stem}_map.json")
        script = self._build_flask_map_script(str(map_file))
        if self.run_local_extractor(script) and map_file.exists():
            with open(map_file, 'r', encoding='utf-8') as f:
                return self._process_map(json.load(f))
        return {}



# =========================================================================================
# DOCKER EXECUTION MODE
# =========================================================================================

class DockerBaseGetter(BaseSpecGetter):
    def __init__(self, project_dir: str, output_dir: str, app_instance_path: Optional[str], compose_file: str, service_name: str):
        super().__init__(project_dir, output_dir, app_instance_path)
        self.service_name = service_name
        
        compose_path = Path(compose_file)
        self.compose_file = compose_path if compose_path.is_absolute() else (self.project_dir / compose_file).resolve()

    def get_spec(self) -> bool:
        if not self.compose_file.exists():
            logger.error(f"Compose file missing at: {self.compose_file}")
            return False

        try:
            logger.info("Spinning up Docker environment...")
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "up", "-d"], cwd=self.project_dir, check=True)
            time.sleep(5) # Allow container initialization
            
            return self._extract_spec_with_retry()
        finally:
            logger.info("Tearing down Docker environment...")
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "down", "-v"], cwd=self.project_dir)

    def _extract_spec_with_retry(self, max_retries=10, delay_seconds=5) -> bool:
        logger.info(f"Waiting for '{self.service_name}' to be ready...")
        for attempt in range(1, max_retries + 1):
            if self._run_extraction_command():
                logger.info(f"Docker Extraction successful on attempt {attempt}!")
                return self._copy_file_from_container()
            if attempt == max_retries:
                logger.error("Docker Extraction failed after all attempts.")
                return False
            time.sleep(delay_seconds)

    def _run_extraction_command(self) -> bool:
        raise NotImplementedError

    def _copy_file_from_container(self) -> bool:
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "cp", f"{self.service_name}:/tmp/schema_dump.json", str(self.output_file)],
                cwd=self.project_dir, check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def endpoint_func_map(self) -> dict:
        raise NotImplementedError

    def _copy_map_from_container(self, map_file: Path) -> dict:
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "cp", f"{self.service_name}:/tmp/map_dump.json", str(map_file)],
                cwd=self.project_dir, check=True
            )
            if map_file.exists():
                with open(map_file, 'r', encoding='utf-8') as f:
                    return self._process_map(json.load(f))
        except subprocess.CalledProcessError:
            pass
        return {}

class DjangoDockerGetter(DockerBaseGetter):
    def _run_extraction_command(self) -> bool:
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "exec", "-T", self.service_name, 
                 "python", "manage.py", "spectacular", "--format", "openapi-json", "--file", "/tmp/schema_dump.json"],
                cwd=self.project_dir, check=True, capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def endpoint_func_map(self) -> dict:
        if not self.compose_file.exists():
            return {}

        map_file = self.output_file.with_name(f"{self.output_file.stem}_map.json")
        extractor_code = self._build_django_map_script("/tmp/map_dump.json")
        try:
            logger.info("Spinning up Docker environment for mapping...")
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "up", "-d"], cwd=self.project_dir, check=True)
            time.sleep(5)
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "exec", "-T", self.service_name, "python"],
                input=extractor_code, text=True, cwd=self.project_dir, check=True, capture_output=True
            )
            return self._copy_map_from_container(map_file)
        except subprocess.CalledProcessError:
            return {}
        finally:
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "down", "-v"], cwd=self.project_dir)

class FastAPIDockerGetter(DockerBaseGetter):
    def _run_extraction_command(self) -> bool:
        extractor_code = self._build_fastapi_script("/tmp/schema_dump.json")
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "exec", "-T", self.service_name, "python"],
                input=extractor_code, text=True, cwd=self.project_dir, check=True, capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def endpoint_func_map(self) -> dict:
        if not self.compose_file.exists():
            return {}
            
        map_file = self.output_file.with_name(f"{self.output_file.stem}_map.json")
        extractor_code = self._build_fastapi_map_script("/tmp/map_dump.json")
        try:
            logger.info("Spinning up Docker environment for mapping...")
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "up", "-d"], cwd=self.project_dir, check=True)
            time.sleep(5)
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "exec", "-T", self.service_name, "python"],
                input=extractor_code, text=True, cwd=self.project_dir, check=True, capture_output=True
            )
            return self._copy_map_from_container(map_file)
        except subprocess.CalledProcessError:
            return {}
        finally:
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "down", "-v"], cwd=self.project_dir)

class FlaskDockerGetter(DockerBaseGetter):
    def _run_extraction_command(self) -> bool:
        if not self.app_instance_path:
            logger.error("app_instance_path is minimally required for Flask Docker execution.")
            return False
            
        extractor_code = self._build_flask_script("/tmp/schema_dump.json")
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "exec", "-T", self.service_name, "python"],
                input=extractor_code, text=True, cwd=self.project_dir, check=True, capture_output=True
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Flask Docker extraction threw internal error: {e.stderr}")
            return False

    def endpoint_func_map(self) -> dict:
        if not self.compose_file.exists():
            return {}
            
        map_file = self.output_file.with_name(f"{self.output_file.stem}_map.json")
        extractor_code = self._build_flask_map_script("/tmp/map_dump.json")
        try:
            logger.info("Spinning up Docker environment for mapping...")
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "up", "-d"], cwd=self.project_dir, check=True)
            time.sleep(5)
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "exec", "-T", self.service_name, "python"],
                input=extractor_code, text=True, cwd=self.project_dir, check=True, capture_output=True
            )
            return self._copy_map_from_container(map_file)
        except subprocess.CalledProcessError:
            return {}
        finally:
            subprocess.run(["docker", "compose", "-f", str(self.compose_file), "down", "-v"], cwd=self.project_dir)
