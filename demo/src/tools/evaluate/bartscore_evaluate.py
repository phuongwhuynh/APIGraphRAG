from src.tools.evaluate.BARTScore.bart_score import BARTScorer
from pathlib import Path
from typing import List, Dict
from src.tools.json.json import save_as_json, load_json
from statistics import mean
from src.dependency_analyzer.ast_parser import DocType


# 'Salesforce/codet5-base-multi-sum'
# 'facebook/bart-large-cnn'
class TraditionalEvaluator:
    def __init__(self, output_dir: str, device: str = "cpu", checkpoint: str = 'facebook/bart-large-cnn', docstring_evaluate: bool = False):
        self.evaluator = BARTScorer(device=device, checkpoint=checkpoint) 
        self.docstring_evaluate = docstring_evaluate
        self.api_result = {}
        self.docstring_result = {}
        self.api_result_file = Path(output_dir) / "evaluate" / "openapi_bartscore_result.json"
        self.docstring_result_file = Path(output_dir) / "evaluate" / "docstring_bartscore_result.json"

    def evaluate(self, batch_code:  Dict[str, Dict[str, str]]):
        for code_id, docs in batch_code.items():
            source_code = docs["source_code"]
            for doc_type, doc_content in docs.items():
                if doc_type == "source_code" or (not doc_content):
                    continue
                if self.docstring_evaluate and doc_type == DocType.DOCSTRING.value:
                    self.docstring_result[code_id] = self._evaluate(source_code=source_code, generated_doc=doc_content)
                if doc_type == DocType.ENDPOINT.value :
                    for path, doc in doc_content.items():
                        self.api_result[path] = self._evaluate(source_code=source_code, generated_doc=doc)
                if doc_type == DocType.SCHEMA.value or doc_type == DocType.PARAMETER.value:
                    self.api_result[code_id] = self._evaluate(source_code=source_code, generated_doc=doc_content)

        self._save_results()

        return {
            "api_evaluation": self.api_result,
            "docstring_evaluation": self.docstring_result
        }


    def _evaluate(self, source_code: str, generated_doc: str):
        # how likely it is that the document could be generated based on the source code
        faithfulness = self.evaluator.score([source_code], [generated_doc])
        return faithfulness[0]
        

    def _save_results(self):
        if self.api_result:
            save_as_json(file_path=self.api_result_file, data=self.api_result)
        if self.docstring_result:
            save_as_json(file_path=self.docstring_result_file, data=self.docstring_result)

    
    def show_statistic(self):

        return {
            "docstring": self._show_statistic(self.docstring_result_file),
            "openapi": self._show_statistic(self.api_result_file),
        }
    
    def _show_statistic(self, file_path: str):
        data = load_json(file_path=file_path)

        if not isinstance(data, dict) or not data:
            return {}
        
        scores = data.values()

        return {
            "evaluated_items": len(scores),
            "min": min(scores),
            "max": max(scores),
            "avg": mean(scores),
        }

# hallucinate
# tools to run
# after generate save into db