import operator
import re
from src.llm.base import BasicModel
from typing import List, Dict, TypedDict, Annotated, Tuple, Literal
from pydantic import BaseModel, Field
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from src.dependency_analyzer.ast_parser import CodeComponent, DocType
from src.llm.prompt import COT_SYSTEM_PROMPT, RANK_INSTRUCT
from math import ceil


class Context(BaseModel):
    """Context information categorization"""

    reasoning: str = Field(
        description="Briefly summarize the Directives defined in your system prompt. Also write again the original list of provided Information snippets."
    )
    ranked_indices: List[int] = Field(
        description="A list of the snippet index numbers, ordered from most helpful to least helpful. Example: [1, 0, 2]"
    )


# Workflow states
class State(TypedDict):
    """State of the workflow"""

    code_components: List[CodeComponent]
    cots: Dict[str, List[str]]
    worker_rank: Annotated[List[Tuple[str, List[str]]], operator.add]
    # docstring_context: Annotated[List[Tuple[str, List[int]]], operator.add]
    # endpoint_context: Annotated[List[Tuple[str, List[int]]], operator.add]
    # schema_context: Annotated[List[Tuple[str, List[int]]], operator.add]
    workflow_rank: Dict[str, List[str]]


class WorkerState(TypedDict):
    """State of each reading worker"""

    code_component: CodeComponent
    cot: List[str]
    worker_rank: Annotated[List[Tuple[str, List[str]]], operator.add]
    # doc_type: Literal["docstring", "endpoint", "schema"]
    # docstring_context: Annotated[List[Tuple[str, List[int]]], operator.add]
    # endpoint_context: Annotated[List[Tuple[str, List[int]]], operator.add]
    # schema_context: Annotated[List[Tuple[str, List[int]]], operator.add]


# Workflow
class Ranker(BasicModel):
    def __init__(
        self,
        model: str,
        model_provider: str,
        input_context_window: int,
        output_context_window: int,
        output_dir: str,
        window_size: int,
        step: int,
        top_k: int,
        **kwarg,
    ):
        """Initiate a reading workflow"""

        super().__init__(
            agent_name="rank",
            model=model,
            model_provider=model_provider,
            input_context_window=input_context_window,
            output_context_window=output_context_window,
            output_dir=output_dir,
            **kwarg,
        )

        self.window_size = window_size
        self.step = step
        self.top_k = top_k

        # Workflow compile
        builder = StateGraph(State)

        builder.add_node("rank", self._rank)
        builder.add_node("synthesizer", self._synthesizer)

        builder.add_conditional_edges(START, self._assign_worker, ["rank"])
        builder.add_edge("rank", "synthesizer")
        builder.add_edge("synthesizer", END)

        self.rank = builder.compile()

        # Workflow invoke

    def invoke(
        self, components: List[CodeComponent], cots: Dict[str, List[str]]
    ) -> Dict[str, Dict[str, Context]]:
        """Send formatted request to reader llm"""
        result = self.rank.invoke(
            {
                "code_components": components,
                "cots": cots,
            }
        )
        return result["workflow_rank"]

    # Workflow nodes
    def _assign_worker(self, state: State):
        """Assign a reader to each code comoponent in the list"""

        sends = []

        for code_component in state["code_components"]:
            sends.append(
                Send(
                    "rank",
                    {
                        "code_component": code_component,
                        "cot": state["cots"][code_component.id],
                    },
                )
            )

        return sends

        # Workflow nodes

    def _synthesizer(self, state: State):
        """Synthesize the returned result from parralel work"""

        workflow_rank = {}

        for id, context in state["worker_rank"]:
            workflow_rank[id] = context

        return {"workflow_rank": workflow_rank}

    def _extract_code_component(self, instruct: str) -> str:
        match = re.search(
            r"<Code Component>\s*(.*?)\s*</Code Component>", instruct, re.DOTALL
        )
        if match:
            return match.group(1).strip()
        return instruct

    # Workflow nodes
    def _llm_call(
        self, instruct: str, chain_of_thought: str, information_list: List[str]
    ):
        """rank retrieved information"""

        system_prompt = SystemMessage(COT_SYSTEM_PROMPT)
        instruction = HumanMessage(
            RANK_INSTRUCT.format(instruct_1="", chain_of_thought="", information="")
        )
        contexts = [information_list, [instruct], [chain_of_thought]]
        fit_contexts = self.context_window_fit(
            contexts=contexts,
            messages=[system_prompt, instruction],
            structured_output=None,
        )
        information_list = fit_contexts[0]
        instruct = (
            fit_contexts[1][0]
            if fit_contexts[1]
            else self._extract_code_component(instruct)
        )
        chain_of_thought = fit_contexts[2][0]

        # Build the formatted statement list
        indices = [str(i + 1) for i in range(len(information_list))]
        information = ""
        for idx, info in zip(indices, information_list):
            information += f"{idx}. {info}\n"

        system_prompt = SystemMessage(COT_SYSTEM_PROMPT)
        instruction = HumanMessage(
            RANK_INSTRUCT.format(
                instruct_1=instruct,
                chain_of_thought=chain_of_thought,
                information=information,
            )
        )

        result = self.base_llm.invoke([system_prompt, instruction])

        # Prompt 2 Information
        self.messages_logger.info(
            f"System message: {system_prompt.content}\n\n Instruction 2: {instruction.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}"
        )
        self.tokens_logger.info(f"Token usage: {result.usage_metadata}")

        logprobs_content = result.response_metadata.get("logprobs", {}).get(
            "content", []
        )
        if not logprobs_content:
            print("Warning: No logprobs returned from the model.")
            return [(0.0, info) for info in information]

        # Only care about the very first token
        first_token_info = logprobs_content[0]
        top_logprobs = first_token_info.get("top_logprobs", [])

        # Build a dictionary mapping token -> logprob probability
        logprob_map = {}
        for top in top_logprobs:
            token_str = top["token"].strip()
            if token_str not in logprob_map or top["logprob"] > logprob_map[token_str]:
                logprob_map[token_str] = top["logprob"]

        # Assign probabilities back to our information array
        ranked_items = []
        for idx, info in zip(indices, information_list):
            # If the model didn't rank it in the top N tokens, give it a heavily penalized logprob
            lp = logprob_map.get(idx, -999.0)
            ranked_items.append((lp, info))

        # Sort by logprobability (Descending: highest logprob first)
        ranked_items.sort(key=lambda x: x[0], reverse=True)

        return [item[1] for item in ranked_items]

    def _rank(self, state: WorkerState):
        # Set up input parameter
        id = state["code_component"].id
        context = list(state["code_component"].depends_on)
        instruct, chain_of_thought = state["cot"]

        if len(state["code_component"].doc_type) <= 1:
            return {"worker_rank": [(state["code_component"].id, context)]}

        if len(context) <= 1:
            return {"worker_rank": [(state["code_component"].id, context)]}

        ranked_context = self._sliding_window(
            instruct=instruct,
            chain_of_thought=chain_of_thought,
            array=context,
            window_size=self.window_size,
            step=self.step,
            k_element=self.top_k,
        )

        return {"worker_rank": [(id, ranked_context)]}

    def _array_eq(self, array_1: List[str], array_2: List[str]):
        l1 = len(array_1)
        l2 = len(array_2)

        if l1 != l2:
            return False

        for i in range(l1):
            if array_1[i] != array_2[i]:
                return False

        return True

    def _sliding_window(
        self,
        instruct: str,
        chain_of_thought: str,
        array: List[str],
        window_size: int = 5,
        step: int = 4,
        k_element: int = 5,
    ):

        # Base condition for recursion to stop
        if not array or len(array) <= 1:
            return array

        array_copy = array.copy()

        window_size = min(window_size, len(array))
        # Loop 1 time through the array with window_size and step
        windows = [_ for _ in range(len(array))][-1::-step]
        iterations = ceil((len(array) - window_size) / step) + 1

        # A flag to know if that is a list or item returned by the sorting algorithm
        list_flag = True

        for i in range(iterations):
            end = windows[i]
            start = max(0, end - window_size + 1)
            window = array[start : end + 1]
            sorted_window = self._llm_call(
                instruct=instruct,
                chain_of_thought=chain_of_thought,
                information_list=window,
            )

            # Handling different returned result from the sorting algorithm
            if isinstance(sorted_window, list):
                # The returned result is an sorted list
                for j in range(start, end + 1):
                    array[j] = sorted_window[j - start]
            elif isinstance(sorted_window, tuple):
                # The returned result is the min/max item of the list
                list_flag = False
                value, pos = sorted_window
                array[start + pos] = array[start]
                array[start] = value

        # The number of element in the correct place
        if list_flag:
            cut = window_size - step
        else:
            cut = 1

        # Check for k_elment in the correct order
        k_element -= cut
        if iterations == 1 or k_element <= 0 or self._array_eq(array_copy, array):
            return array

        # Recurse to sort the remaining elements
        left_array = self._sliding_window(
            instruct, chain_of_thought, array[cut:], window_size, step, k_element
        )

        # Apply the sorted order of remaining elements to the current array
        array = array[0:cut] + left_array

        return array
