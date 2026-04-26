# from src.llm.base import BasicModel
# from src.llm.prompt import ENTITY_EXTRACTION_PROMPT
# from typing import Optional, TypedDict, List, Dict, Annotated, Tuple
# from pathlib import Path
# import operator 
# from langchain.messages import HumanMessage, SystemMessage
# from langgraph.graph import StateGraph, START, END
# from langgraph.types import Send



# class State(TypedDict):
#     documents: Dict[str, str]
#     results: Annotated[List[Tuple[str, Dict[str, float]]], operator.add]

# class WrokerState(TypedDict):
#     document_id: str
#     document: str
#     results: Annotated[List[Tuple[str, Dict[str, float]]], operator.add]


# class HallucinationEvaluator(BasicModel):
#     def __init__(self, model: str, model_provider: str, input_context_window: int, output_context_window: int, output_dir: str, db_conn, tokenizer: Optional[str] = None, **kwarg):
#         super().__init__(agent_name="evaluate",
#                          model=model,
#                          model_provider=model_provider,
#                          input_context_window=input_context_window,
#                          output_context_window=output_context_window,
#                          output_dir=output_dir,
#                          tokenizer=tokenizer,
#                          **kwarg) 
#         self.api_result = {}
#         self.docstring_result = {}
#         self.openapi_result_file = Path(output_dir) / "evaluate" / "openapi_llm_evaluation.json"
#         self.docstring_result_file = Path(output_dir) / "evaluate" / "docstring_llm_evaluation.json"
#         self.total_object = 0
#         self.db_conn = db_conn

#     def invoke(self, documents: Dict[str, str]):

#         result = self.evalutor.invoke({"documents": documents})
    
#     def _assign_worker(self, state: State):

#         sends = []

#         for document_id, document in state["documents"].items():
#             sends.append(Send("evaluate", {"document_id": document_id,
#                                                  "document": document}))
#         return sends 
    
#     def _entities_from_llm_result(self, reponse: str):
#         pass
    
#     def _evaluate(self, state: WrokerState):

#         prompt = ENTITY_EXTRACTION_PROMPT.format(document=state["document"])

#         result = self.base_llm.invoke(prompt)

#         entities = self._entities_from_llm_result(result.content)

#         target_entity = self.db_conn.get(state["document_id"])

#         result = {"total_mentioned": len(entities),
#                   "existing_mentions": 0}

#         for e in entities:
#             exist = True

#             dependencies = target_entity.depends_on

#             for d in dependencies:


            





    