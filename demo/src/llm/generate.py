import json
import operator
import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, List, TypedDict, Annotated, Literal, Tuple, Optional, Any, Type
import yaml
from src.llm.base import BasicModel
from src.dependency_analyzer.ast_parser import CodeComponent, DocType
from src.llm.prompt import (
    GENERATE_DOCSTRING_PROMPT,
    GENERATE_ENDPOINT_PROMPT,
    GENERATE_SYSTEM_PROMPT,
    GENERATE_SCHEMA_PROMPT,
    GENERATE_PARAMETER_PROMPT,
)
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langchain.messages import HumanMessage, SystemMessage, AnyMessage


class State(TypedDict):
    """State of the Writer workflow"""

    components: List[CodeComponent]
    # cots: Dict[str, List[str]]
    ranks: Dict[str, List[str]]
    workflow_docs: Dict[str, Dict[str, str]]
    workflow_traces: Dict[str, Dict[str, Any]]
    worker_docs: Annotated[
        List[Tuple[str, Dict[str, Any], Dict[str, Any]]], operator.add
    ]
    # contexts: Dict[str, Dict[str, Dict[str, List[str]]]]
    # type_doc: Literal["non_schema", "schema"]
    # generated_endpoint_documents: Annotated[List[Tuple[str, OpenAPIPathItem]], operator.add]
    # generated_docstring_documents: Annotated[List[Tuple[str, DocstringOutput]], operator.add]
    # generated_documents: Dict[str, Dict[str, str]]


class WorkerState(TypedDict):
    """Worker state of workers in Writer workflow"""

    component: CodeComponent
    # cot: List[str]
    rank: List[str]
    worker_docs: Annotated[
        List[Tuple[str, Dict[str, Any], Dict[str, Any]]], operator.add
    ]
    # doc_type: Literal["docstring", "endpoint", "schema"]
    # context: Dict[str, List[str]]
    # generated_endpoint_documents: Annotated[List[Tuple[str, OpenAPIPathItem]], operator.add]
    # generated_docstring_documents: Annotated[List[Tuple[str, DocstringOutput]], operator.add]


class Generator(BasicModel):
    def __init__(
        self,
        model: str,
        model_provider: str,
        input_context_window: int,
        output_context_window: int,
        output_dir: str,
        db_conn,
        **kwarg,
    ):
        """Initialize a writer object

        Args:
            model: the model name
            model_provider: the provider of the model
            input_context_window: the size of input context window
            output_context_window: the size of the output context window

        Returns:
            a writer object"""

        super().__init__(
            agent_name="generate",
            model=model,
            model_provider=model_provider,
            input_context_window=input_context_window,
            output_context_window=output_context_window,
            output_dir=output_dir,
            **kwarg,
        )
        # self.docstring = self.base_llm.with_structured_output(DocstringOutput, include_raw=True)
        # self.endpoint = self.base_llm.with_structured_output(OpenAPIPathItem, include_raw=True)
        # self.schema = self.base_llm.with_structured_output(OpenAPISchema, include_raw= True)
        self.input_context_window = input_context_window
        self.output_context_window = output_context_window
        self.db_conn = db_conn

        # self.base_path = Path(base_path).resolve()

        # Workflow compilation
        builder = StateGraph(State)

        # Workflow nodes
        builder.add_node("llm_call", self._llm_call)
        builder.add_node("synthesize", self._synthesize)

        # Workflow edges
        builder.add_conditional_edges(START, self._assign_workers, ["llm_call"])
        builder.add_edge("llm_call", "synthesize")
        builder.add_edge("synthesize", END)

        self.writer = builder.compile()

    def invoke(
        self,
        components: CodeComponent,
        # cots: Dict[str, List[str]],
        ranks: Dict[str, List[str]],
    ) -> Dict[str, Dict[str, str]]:
        """Send data for writer workflow to generate documents

        Args:
            components: List of components that is about to be documented
            contexts: List of context information provided for each component

        Returns:
            A dictionary that contains docstring and openapi (optional) to corresponding component
        """

        result = self.writer.invoke(
            {
                "components": components,
                # "cots": cots,
                "ranks": ranks,
            }
        )

        return {
            "workflow_docs": result["workflow_docs"],
            "workflow_traces": result["workflow_traces"],
        }

    # Workflow node
    def _assign_workers(self, state: State):
        """Distribute dynamically tasks over workers"""
        sends = []
        for component in state["components"]:
            sends.append(
                Send(
                    "llm_call",
                    {
                        "component": component,
                        # "cot": state["cots"][component.id],
                        "rank": state["ranks"][component.id],
                    },
                )
            )

        return sends

    # Workflow node
    def _llm_call(self, state: WorkerState):
        """Worker using llm core for document generation"""
        trace = {
            "start_line": state["component"].start_line,
            "end_line": state["component"].end_line,
        }
        if len(state["component"].doc_type) <= 1:
            return {
                "worker_docs": [
                    (
                        state["component"].id,
                        {"docstring": "", "endpoint": {}, "schema": ""},
                        trace,
                    )
                ]
            }

        source_code = state["component"].source_code
        doc_type = state["component"].doc_type
        api_methods = state["component"].api_methods

        # cot = state["cot"]
        rank = state["rank"]
        context = self.db_conn.get_batch(rank)
        supporting_context = []
        for i in range(len(rank)):
            for j in range(len(context)):
                if rank[i] == context[j].id:
                    if context[j].has_docstring:
                        supporting_context.append(
                            f"\n{context[j].id}:\n{context[j].docstring}\n"
                        )
                    else:
                        supporting_context.append(
                            f"\n{context[j].id}:\n{context[j].source_code}\n"
                        )

        docs = {
            "docstring": "",
            "endpoint": {},
            "schema": "",
            "path_parameter": {},
            "query_parameter": {},
        }

        system_prompt = SystemMessage(GENERATE_SYSTEM_PROMPT)

        if DocType.DOCSTRING.value in doc_type:
            user_prompt = HumanMessage(
                GENERATE_DOCSTRING_PROMPT.format(
                    # chain_of_thought="",
                    supporting_context=""
                )
            )
            contexts = [[source_code], supporting_context]
            fit_contexts = self.context_window_fit(
                contexts=contexts, messages=[system_prompt, user_prompt]
            )

            fit_supporting_context = "\n".join(fit_contexts[0] + fit_contexts[1])

            chain_of_thought = fit_contexts[0][0] + (
                fit_contexts[1][0] if fit_contexts[1] else ""
            )
            # print(
            #     "The supporting context used for docstring generation: ",
            #     fit_supporting_context,
            # )
            user_prompt = HumanMessage(
                GENERATE_DOCSTRING_PROMPT.format(
                    # chain_of_thought=chain_of_thought,
                    supporting_context=fit_supporting_context,
                )
            )
            result = self.base_llm.invoke([system_prompt, user_prompt])
            docs["docstring"] = result.content
            state["component"].has_docstring = True
            state["component"].docstring = result.content

            self.messages_logger.info(
                f"System message: {system_prompt.content}\n\n Instruction: {user_prompt.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}"
            )
            self.tokens_logger.info(f"Token usage: {result.usage_metadata}")

        if DocType.ENDPOINT.value in doc_type:
            for endpoint in api_methods:
                method, path = endpoint.split(":")
                user_prompt = HumanMessage(
                    GENERATE_ENDPOINT_PROMPT.format(
                        # chain_of_thought="",
                        supporting_context="",
                        method=method,
                        path=path,
                    )
                )
                contexts = [[source_code], supporting_context]
                fit_contexts = self.context_window_fit(
                    contexts=contexts, messages=[system_prompt, user_prompt]
                )
                fit_supporting_context = "\n".join(fit_contexts[0] + fit_contexts[1])
                # chain_of_thought = fit_contexts[0][0] + (
                #     fit_contexts[1][0] if fit_contexts[1] else ""
                # )
                user_prompt = HumanMessage(
                    GENERATE_ENDPOINT_PROMPT.format(
                        # chain_of_thought=chain_of_thought,
                        supporting_context=fit_supporting_context,
                        method=method,
                        path=path,
                    )
                )
                result = self.base_llm.invoke([system_prompt, user_prompt])
                docs["endpoint"][endpoint] = result.content
                state["component"].endpoint[endpoint] = result.content

                self.messages_logger.info(
                    f"System message: {system_prompt.content}\n\n Instruction: {user_prompt.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}"
                )
                self.tokens_logger.info(f"Token usage: {result.usage_metadata}")

        if DocType.SCHEMA.value in doc_type:
            schema_name = (state["component"].id.split("."))[-1]
            user_prompt = HumanMessage(
                GENERATE_SCHEMA_PROMPT.format(
                    # chain_of_thought="",
                    schema_name=schema_name,
                    supporting_context="",
                )
            )
            contexts = [[source_code], supporting_context]
            fit_contexts = self.context_window_fit(
                contexts=contexts, messages=[system_prompt, user_prompt]
            )
            fit_supporting_context = "\n".join(fit_contexts[0] + fit_contexts[1])
            # chain_of_thought = fit_contexts[0][0] + (
            #     fit_contexts[1][0] if fit_contexts[1] else ""
            # )
            user_prompt = HumanMessage(
                GENERATE_SCHEMA_PROMPT.format(
                    # chain_of_thought=chain_of_thought,
                    supporting_context=fit_supporting_context,
                    schema_name=schema_name,
                )
            )
            result = self.base_llm.invoke([system_prompt, user_prompt])
            docs["schema"] = result.content
            state["component"].schema = result.content

            self.messages_logger.info(
                f"System message: {system_prompt.content}\n\n Instruction: {user_prompt.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}"
            )
            self.tokens_logger.info(f"Token usage: {result.usage_metadata}")

        if DocType.PARAMETER.value in doc_type:
            parameter_name = (state["component"].id.split("."))[-1]
            user_prompt = HumanMessage(
                GENERATE_PARAMETER_PROMPT.format(
                    # chain_of_thought="",
                    supporting_context="",
                    parameter_name=parameter_name,
                    parameter_type=state["component"].parameter_type,
                )
            )
            contexts = [[source_code], supporting_context]
            fit_contexts = self.context_window_fit(
                contexts=contexts, messages=[system_prompt, user_prompt]
            )
            fit_supporting_context = "\n".join(fit_contexts[0] + fit_contexts[1])
            # chain_of_thought = fit_contexts[0][0] + (
            #     fit_contexts[1][0] if fit_contexts[1] else ""
            # )
            user_prompt = HumanMessage(
                GENERATE_PARAMETER_PROMPT.format(
                    # chain_of_thought=chain_of_thought,
                    supporting_context=fit_supporting_context,
                    parameter_name=parameter_name,
                    parameter_type=state["component"].parameter_type,
                )
            )
            result = self.base_llm.invoke([system_prompt, user_prompt])
            if state["component"].parameter_type == "path":
                docs["path_parameter"] = result.content
            elif state["component"].parameter_type == "query":
                docs["query_parameter"] = result.content
            state["component"].parameter_description = result.content

            self.messages_logger.info(
                f"System message: {system_prompt.content}\n\n Instruction: {user_prompt.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}"
            )
            self.tokens_logger.info(f"Token usage: {result.usage_metadata}")

        return {"worker_docs": [(state["component"].id, docs, trace)]}

    # Workflow node
    def _synthesize(self, state: State):
        """Compose and reformat the distributed work from workers

        Args:
            state: the state of the workflow
        """
        update_components = {c.id: c.to_dict() for c in state["components"]}
        self.db_conn.save(update_components)

        document = {}
        traces = {}
        for id, docs, trace in state["worker_docs"]:
            document[id] = docs
            traces[id] = trace

        return {"workflow_docs": document, "workflow_traces": traces}