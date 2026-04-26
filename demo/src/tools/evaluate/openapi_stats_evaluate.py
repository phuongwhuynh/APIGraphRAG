import json 
from src.tools.json.json import save_as_json, load_json
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
        self.results = {
            "endpoint_statistics": endpoint_stats, 
            "schema_statistics": schema_stats,
        }
        self._save_results()
        return self.results
    
    def _save_results(self):
        save_as_json(file_path=self.output_file, data= self.results)
    
    def _evaluate_endpoint(self):
        num_endpoints = len(self.data["paths"])
        num_endpoint_methods = sum(len(methods) for methods in self.data["paths"].values())

        num_endpoint_method_description = 0

        for endpoint_field in self.data["paths"].values():
            for method_fields in endpoint_field.values():
                if not method_fields.get("description", None):
                    continue
                num_endpoint_method_description += 1

        return {
            "Number of endpoints": num_endpoints, 
            "Number of methods over endpoints": num_endpoint_methods, 
            "Ratio of method with description": num_endpoint_method_description / num_endpoint_methods,
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
            "Ratio of schema with description": num_schema_description / num_schemas,
        }






# Explain why we have to use LLM to generate documents: 

# The challenges of applying LLM to generate documents:

# To tacle the context window challenges we propose:


# Explain why we break the repo into small code components: 
## The problem of context window: too small to deal with the repo size; even if big enough suffer the forget at the middle of the context -> Low quality
###### mimic the process of chain-of-thought [REF]
###### break the complex repo into single, isolated component which is easy to comprehend [REF]
###### Topological order process: we build the context incrementally so that high abstract code components can inherit the resulted work from the prior components that they depend on -> big reduce on the size of related component information to support the understand --> each component only needs to access and analyze the information from its direct neighbours
###### To further mitigate the problem of context window overflow, we introduce the mechanism of ranking to rank the importance of related component so that important pieces of information are prioritized to be included when it comes to the situation that context window is reached. METHODS FOR RANKING:
###### 1. Using LLM -> query generation, likelihood generation, list permutation, distilled models [REF]
###### 2. Using method such as encoding-decoding -> not high quality [REF]
## Evaluate method: reference-based, reference-free, LLM -> weak and strength [REF]


# Special points:
## Topo order: allow level concurrent process [REF]
## Prompting strategies: COT, Talec notes -> a prelimianry assessment about the code is made before further analyzation such as ranking and document generation [REF]
## Ranking: list permutation, expected scores from logprob of the last token -> mitigate the problem of unstable, unformatted result from LLM [REF]
## Evaluate method: details of the criteria used for LLM prompt

# Result:
## Empirical result: how how
##
##






