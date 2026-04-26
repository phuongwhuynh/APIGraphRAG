from src.llm.base import BasicModel
from src.llm.prompt import COT_SYSTEM_PROMPT, COT_INSTRUCT
from src.dependency_analyzer.ast_parser import CodeComponent, DocType
from langgraph.types import Send
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, List, Dict, Annotated, Tuple
import operator


class State(TypedDict):
    code_components: List[CodeComponent]
    workflow_thoughts: Dict[str, List[str]]
    worker_thoughts: Annotated[List[Tuple[str, List[str]]], operator.add]

class WorkerState(TypedDict):
    code_component: CodeComponent
    worker_thoughts: Annotated[List[Tuple[str, List[str]]], operator.add]

class CoT(BasicModel):
    def __init__(self, model: str, model_provider: str, input_context_window: int, output_context_window: int, output_dir: str, **kwarg):
        """Initiate a reading workflow"""

        super().__init__(
            agent_name= "cot",
            model= model,
            model_provider= model_provider,
            input_context_window= input_context_window,
            output_context_window= output_context_window,
            output_dir = output_dir,
            **kwarg
        )

        # Workflow compile
        builder = StateGraph(State)

        builder.add_node("llm_call", self._llm_call)
        builder.add_node("synthesizer", self._synthesizer)

        builder.add_conditional_edges(START, self._assign_worker, ["llm_call"])
        builder.add_edge("llm_call", "synthesizer")
        builder.add_edge("synthesizer", END)

        self.cot = builder.compile()

    def invoke(self, components: CodeComponent):
        result = self.cot.invoke({"code_components": components})
        return result["workflow_thoughts"]
    
    # Workflow nodes
    def _llm_call(self, state: WorkerState):
        """cot generate analysis about a code"""
        # Set up input parameter
        ###############################################
        # if len(state["code_component"].depends_on) <= 1:
        #     return {"worker_thoughts": [(state["code_component"].id, ["", ""])]}
        if len(state["code_component"].doc_type) <= 1:
            return {"worker_thoughts": [(state["code_component"].id, ["", ""])]}


        source_code = state["code_component"].source_code
        
        system_prompt = SystemMessage(COT_SYSTEM_PROMPT)
        instruct = HumanMessage(COT_INSTRUCT.format(code_component=""))

        # Truncate the source code to fit with the context window
        truncated_source_code = self.context_window_fit(contexts= source_code, messages=[system_prompt, instruct], structured_output=None)

        instruct = HumanMessage(COT_INSTRUCT.format(code_component=truncated_source_code))
        result = self.base_llm.invoke([system_prompt, instruct])

        # Log prompting information
        self.messages_logger.info(f"System message: {system_prompt.content}\n\n Instruction: {instruct.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}")
        self.tokens_logger.info(f"Token usage: {result.usage_metadata}")
        

        return {"worker_thoughts": [(state["code_component"].id, [instruct.content, result.content])]}

    # Workflow nodes
    def _assign_worker(self, state: State):
        """Assign a reader to each code comoponent in the list"""

        sends = []

        for code_component in state["code_components"]:
            sends.append(Send('llm_call', {"code_component": code_component}))

        return sends

    # Workflow nodes
    def _synthesizer(self, state: State):
        """Synthesize the returned result from parralel work"""

        workflow_thoughts = {}

        for id, thought in state["worker_thoughts"]:
            workflow_thoughts[id] = thought

        return {"workflow_thoughts": workflow_thoughts}