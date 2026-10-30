import json
from src.utils.json_io import save_as_json, load_json
from pathlib import Path


class OpenAPIStatsEvaluator:

    def __init__(self, file_path: str, output_dir: str):
        self.output_file = Path(output_dir) / "evaluate" / "openapi_stats_result.json"
        self.data = self._load_data(Path(file_path))
        self.results = {}

    def _load_data(self, file_path: str):
        data = load_json(file_path)
        return data

    def evaluate(self):
        endpoint_stats = self._evaluate_endpoint()
        schema_stats = self._evaluate_schema()
        parameter_stats = self._evaluate_parameter()
        self.results = {
            "endpoint_statistics": endpoint_stats,
            "schema_statistics": schema_stats,
            "parameter_statistics": parameter_stats,
        }
        self._save_results()
        return self.results

    def _save_results(self):
        save_as_json(file_path=self.output_file, data=self.results)

    def _evaluate_endpoint(self):
        number_of_endpoint = len(self.data["paths"])
        number_of_endpoint_methods = sum(
            len(methods) for methods in self.data["paths"].values()
        )

        number_of_endpoint_method_description = 0

        for endpoint_field in self.data["paths"].values():
            for method_fields in endpoint_field.values():
                if not method_fields.get("description", None):
                    continue
                number_of_endpoint_method_description += 1

        return {
            "Number of endpoint": number_of_endpoint,
            "Number of endpoint method": number_of_endpoint_methods,
            "Number of methods with description": number_of_endpoint_method_description,
            "Ratio of method with description": (
                number_of_endpoint_method_description / number_of_endpoint_methods
                if number_of_endpoint_methods > 0
                else "No endpoint exists"
            ),
        }

    def _evaluate_schema(self):
        num_schemas = len(self.data["components"]["schemas"])

        num_schema_description = 0

        for schema in self.data["components"]["schemas"].values():
            if not schema.get("description", None):
                continue
            num_schema_description += 1

        return {
            "Number of schema": num_schemas,
            "Number of schema with description": num_schema_description,
            "Ratio of schema with description": (
                num_schema_description / num_schemas
                if num_schemas > 0
                else "No schema exists"
            ),
        }

    def _evaluate_parameter(self):
        number_of_parameter = 0
        number_parameter_description = 0

        for _, endpoint in self.data["paths"].items():
            for method in endpoint.values():
                if method.get("parameters", None):
                    for parameter in method["parameters"]:
                        number_of_parameter += 1
                        if parameter.get("description", None):
                            number_parameter_description += 1

        return {
            "Number of parameter": number_of_parameter,
            "Number of parameter with description": number_parameter_description,
            "Ratio of parameter with description": (
                number_parameter_description / number_of_parameter
                if number_of_parameter > 0
                else "No endpoint parameter exists"
            ),
        }
