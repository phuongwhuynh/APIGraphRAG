from src.dependency_analyzer.ast_parser import DependencyParser
from src.llm.rank import ComponentContext, CodeComponent
from typing import Any, Dict, List


class Searcher():
    def __init__(self, storage_conn: Any, none_local_search: bool = False):
        self.storage_conn = storage_conn
        self.none_local_search = none_local_search


    def _none_local_search(self, component: str):
        if not self.none_local_search:
            return None


    def _retrieve(self, component_context: Dict[str, Any]) -> List[str]:
        if not component_context:
            return None
        
        context = {}
        # Get the main context information
        for level, requests in component_context['context'].items():
            result = []
            for request in requests:
                target = self.repo_components.get(request, None)
                if target:
                    # the target is in local repository
                    data = target.docstring if target.has_docstring else target.source_code
                    data = request + ":\n" + data + "\n\n"
                else:
                    # the target is not in local repository
                    data = self._none_local_search(request)

                if data:
                    result.append(data)
            context[level] = result

        # Get the suggested missing information
        result = []
        requests = component_context["suggested_missing_information"]
        for request in requests:
            target = self.repo_components.get(request, None)
            if target:
                # the target is in local repository
                data = target.docstring if target.has_docstring else target.source_code
            else:
                # the target is not in local repository
                data = self._none_local_search(target)
            result.append(data)
        context["suggested_missing_information"] = result

        return context

    def invoke(self, required_context: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
        retrieved_context = {}

        for component, doc_types in required_context.items():
            component_contexts = {}

            for doc_type, context_object in doc_types.items():
               component_contexts[doc_type] = self._retrieve(context_object)

            retrieved_context[component] = component_contexts

        return retrieved_context
                

                

            
            
                
        return retrieved_context
            




 


    