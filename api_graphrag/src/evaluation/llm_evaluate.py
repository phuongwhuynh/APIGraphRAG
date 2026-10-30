from dataclasses import dataclass
from enum import Enum
from typing import List, Literal, Dict, Optional, Any, TypedDict, Annotated, Tuple
from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
import ast
import math
from statistics import mean, pstdev
from pathlib import Path
import json
import operator

from src.llm.base import BasicModel
from src.llm.prompt import EVALUATE_PROMPT, EVALUATE_SYSTEM_PROMPT
from src.utils.json_io import save_as_json, load_json
from src.dependency_analyzer.ast_parser import DocType


class ScoreLevel(Enum):
    POOR = 1
    FAIR = 2
    GOOD = 3
    VERY_GOOD = 4
    EXCELLENT = 5


class EvaluationAspect(Enum):
    MOTIVATION = "motivation"
    FUNCTIONALITY = "functionality"
    PARAMETER_ATTRIBUTE_DESCRIPTION = "parameter_attribute_description"


@dataclass
class AspectCriteria:
    description: str
    score_criteria: Dict[ScoreLevel, str]


class State(TypedDict):
    code_components: Dict[str, Dict[str, str]]
    docstring_results: Dict[str, Dict[str, float]]
    api_results: Dict[str, Dict[str, float]]
    results: Annotated[List[Tuple[str, float]], operator.add]


class WorkerState(TypedDict):
    component_id: str
    source_code: str
    component_type: str
    document: str | Dict[str, str]
    criteria: str
    results: Annotated[List[Tuple[str, float]], operator.add]


class LLMEvaluator(BasicModel):
    def __init__(
        self,
        model: str,
        model_provider: str,
        input_context_window: int,
        output_context_window: int,
        output_dir: str,
        tokenizer: Optional[str] = None,
        docstring_evaluate: bool = False,
        **kwarg,
    ):
        super().__init__(
            agent_name="evaluate",
            model=model,
            model_provider=model_provider,
            input_context_window=input_context_window,
            output_context_window=output_context_window,
            max_tokens=1,
            logprobs=True,
            top_logprobs=10,
            output_dir=output_dir,
            tokenizer=tokenizer,
            **kwarg,
        )
        self.docstring_evaluate = docstring_evaluate
        self.api_result = {}
        self.docstring_result = {}
        self.openapi_result_file = (
            Path(output_dir) / "evaluate" / "openapi_llm_evaluation.json"
        )
        self.docstring_result_file = (
            Path(output_dir) / "evaluate" / "docstring_llm_evaluation.json"
        )
        self.total_object = 0

        # Workflow compile
        builder = StateGraph(State)

        builder.add_node("evaluate", self._evaluate_criteria)
        builder.add_node("synthesizer", self._synthesize)

        builder.add_conditional_edges(START, self._assign_worker, ["evaluate"])
        builder.add_edge("evaluate", "synthesizer")
        builder.add_edge("synthesizer", END)

        self.evaluator = builder.compile()

    def invoke(self, code_components: Dict[str, Dict[str, str]]):
        """Evaluate a batch and keep all raw scores for later analysis.

        Returns a nested mapping:
        component_id -> doc_type -> aspect -> score
        """

        self.total_object = len(code_components)

        result = self.evaluator.invoke({"code_components": code_components})

        # print(f"Result: {result.keys()}\n{result}")
        self.docstring_result = result.get("docstring_results", {})
        self.api_result = result.get("api_results", {})
        self._save_results()

        return {
            "api_evaluation": self.docstring_result,
            "docstring_evaluation": self.api_result,
        }

    def _save_results(self):
        if self.api_result:
            save_as_json(file_path=self.openapi_result_file, data=self.api_result)
        if self.docstring_result:
            save_as_json(
                file_path=self.docstring_result_file, data=self.docstring_result
            )

    def show_statistic(self, file_path: str):
        data = load_json(file_path=file_path)

        if not isinstance(data, dict) or not data:
            return {}

        stats = {
            EvaluationAspect.MOTIVATION.title(): [0],
            EvaluationAspect.FUNCTIONALITY.title(): [0],
            EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION.title(): [0],
        }

        for _, aspect_scores in data.items():
            for key, score in aspect_scores.items():
                stats[key].append(score)

        return {
            "evaluated_items": self.total_object,
            "MOTIVATION": {
                "evaluated_items": len(stats[EvaluationAspect.MOTIVATION.title()]),
                "min": min(stats[EvaluationAspect.MOTIVATION.title()]),
                "max": max(stats[EvaluationAspect.MOTIVATION.title()]),
                "avg": mean(stats[EvaluationAspect.MOTIVATION.title()]),
            },
            "FUNCTIONALITY": {
                "evaluated_items": len(stats[EvaluationAspect.FUNCTIONALITY.title()]),
                "min": min(stats[EvaluationAspect.FUNCTIONALITY.title()]),
                "max": max(stats[EvaluationAspect.FUNCTIONALITY.title()]),
                "avg": mean(stats[EvaluationAspect.FUNCTIONALITY.title()]),
            },
            "PARAMETER_ATTRIBUTE_DESCRIPTION": {
                "evaluated_items": len(
                    stats[EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION.title()]
                ),
                "min": min(
                    stats[EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION.title()]
                ),
                "max": max(
                    stats[EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION.title()]
                ),
                "avg": mean(
                    stats[EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION.title()]
                ),
            },
        }

    def _assign_worker(self, state: State) -> Dict[str, float]:
        sends = []
        for component_id, code_component in state["code_components"].items():
            source_code = code_component["source_code"]
            for doc_type, doc_content in code_component.items():
                if doc_type == "source_code" or (not doc_content):
                    continue
                if self.docstring_evaluate and doc_type == DocType.DOCSTRING.value:
                    continue
                criteria = self._get_criteria(doc_type)
                has_parameter_attribute = self._has_parameter_attribute(source_code)

                if not has_parameter_attribute:
                    criteria.pop(EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION, None)

                for c in criteria.keys():
                    criteria_str = self._format_criteria({c: criteria[c]})
                    if doc_type == DocType.ENDPOINT.value:
                        for path, doc in doc_content.items():
                            combined_component_id = "+".join(
                                [doc_type, path, c.value.title()]
                            )
                            sends.append(
                                Send(
                                    "evaluate",
                                    {
                                        "component_id": combined_component_id,
                                        "source_code": source_code,
                                        "criteria": criteria_str,
                                        "component_type": doc_type,
                                        "document": doc,
                                    },
                                )
                            )
                    else:
                        combined_component_id = "+".join(
                            [doc_type, component_id, c.value.title()]
                        )
                        sends.append(
                            Send(
                                "evaluate",
                                {
                                    "component_id": combined_component_id,
                                    "source_code": source_code,
                                    "criteria": criteria_str,
                                    "component_type": doc_type,
                                    "document": doc_content,
                                },
                            )
                        )

        return sends

    def _evaluate_criteria(self, state: WorkerState) -> float:
        system_prompt = SystemMessage(
            EVALUATE_SYSTEM_PROMPT.format(criteria=state["criteria"])
        )
        human_prompt = HumanMessage(
            EVALUATE_PROMPT.format(
                source_code=state["source_code"],
                document=state["document"],
                component_type=state["component_type"],
            )
        )

        result = self.base_llm.invoke([system_prompt, human_prompt])

        self.messages_logger.info(
            f"System message: {system_prompt.content}\n\n Instruction: {human_prompt.content}\n\n result: {result.content}\n\n Token usage: {result.usage_metadata}"
        )
        self.tokens_logger.info(f"Token usage: {result.usage_metadata}")

        logprobs_content = result.response_metadata.get("logprobs", {}).get(
            "content", []
        )
        if not logprobs_content:
            print("Warning: No logprobs returned from the model.")
            return 0

        score = self._expected_score_from_first_token(logprobs_content[0])

        return {"results": [(state["component_id"], score)]}

    def _synthesize(self, state: State):
        docstring_results = {}
        api_results = {}
        for id, score in state["results"]:
            doc_type, component_id, criteria = id.split("+")
            if doc_type == DocType.DOCSTRING.value:
                if component_id not in docstring_results:
                    docstring_results[component_id] = {}
                docstring_results[component_id][criteria] = score
            else:
                if component_id not in api_results:
                    api_results[component_id] = {}
                api_results[component_id][criteria] = score

        return {"docstring_results": docstring_results, "api_results": api_results}

    def _format_criteria(self, criteria: Dict[EvaluationAspect, AspectCriteria]) -> str:
        formatted_criteria = []
        for aspect, aspect_criteria in criteria.items():
            score_lines = []
            for level, score_text in aspect_criteria.score_criteria.items():
                score_lines.append(f"- {level.value}: {score_text}")

            formatted_criteria.append(
                f"{aspect.value.title()}\n"
                f"Description: {aspect_criteria.description}\n"
                f"Score Criteria:\n" + "\n".join(score_lines)
            )

        return "\n\n".join(formatted_criteria)

    def _expected_score_from_first_token(self, first_token_info: Dict) -> float:
        score_probabilities = {score.value: 0.0 for score in ScoreLevel}
        top_logprobs = first_token_info.get("top_logprobs", [])

        for token_info in top_logprobs:
            token = token_info.get("token", "").strip()
            if token in {"1", "2", "3", "4", "5"}:
                score_probabilities[int(token)] = math.exp(
                    token_info.get("logprob", float("-inf"))
                )

        total_probability = sum(score_probabilities.values())
        if total_probability <= 0:
            return 1.0

        expected_score = sum(
            score * (probability / total_probability)
            for score, probability in score_probabilities.items()
        )
        return expected_score

    def _get_criteria(self, doc_type: Literal["docstring", "endpoint", "schema"]):
        if doc_type == DocType.DOCSTRING:
            return {
                EvaluationAspect.MOTIVATION: AspectCriteria(
                    description=(
                        "Evaluate how well the docstring explains the 'why'. "
                        "It should strictly communicate the architectural or business problem solved, "
                        "the underlying purpose, and the strategic value of the code."
                    ),
                    score_criteria={
                        ScoreLevel.POOR: "No explanation of the purpose or reason the code exists.",
                        ScoreLevel.FAIR: "States a vague purpose, but lacks clear business or architectural value.",
                        ScoreLevel.GOOD: "Explains the basic purpose and the problem it attempts to solve.",
                        ScoreLevel.VERY_GOOD: "Clearly connects the code to its broader architectural or business value.",
                        ScoreLevel.EXCELLENT: "Provides a compelling 'why' that establishes strategic value and perfectly frames the exact architectural bottleneck or business requirement addressed",
                    },
                ),
                EvaluationAspect.FUNCTIONALITY: AspectCriteria(
                    description=(
                        "Evaluate how clearly the docstring explains the 'what'. "
                        "It should detail the core logic, algorithms, and transformations "
                        "performed by the code, balancing clarity with technical detail."
                    ),
                    score_criteria={
                        ScoreLevel.POOR: "No explanation of the internal functionality or logic.",
                        ScoreLevel.FAIR: "Overly vague explanation, or conversely, an overly dense literal line-by-line translation of the code to text.",
                        ScoreLevel.GOOD: "Basic, clear explanation of the main logic and data transformations.",
                        ScoreLevel.VERY_GOOD: "Clear, balanced explanation of the core algorithms, data handling, and expected return states.",
                        ScoreLevel.EXCELLENT: "Perfect balance of clarity and technical detail; explains complex logic elegantly without forcing the reader to read the underlying source code.",
                    },
                ),
                EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION: AspectCriteria(
                    description=(
                        "Evaluate how effectively parameter or attribute descriptions convey purpose, "
                        "constraints, and usage context. They must go beyond basic type hints to explain "
                        "lifecycle, default behaviors, and execution impacts."
                    ),
                    score_criteria={
                        ScoreLevel.POOR: "Merely restates the type hint or signature into natural language (e.g., 'user_id is an int') without adding context.",
                        ScoreLevel.FAIR: "Provides basic information about purpose but lacks details about constraints, valid values, or initialization context.",
                        ScoreLevel.GOOD: "Explains purpose and includes key constraints or valid value ranges, but might miss edge cases or complex state behaviors.",
                        ScoreLevel.VERY_GOOD: "Clearly explains purpose, constraints, default behaviors, and (for classes) modification patterns.",
                        ScoreLevel.EXCELLENT: "Comprehensive guidance including edge cases, default behaviors, and impact on execution flow. For classes, thoroughly explains the attribute's lifecycle and immutability.",
                    },
                ),
            }
        return {
            EvaluationAspect.MOTIVATION: AspectCriteria(
                description=(
                    "Evaluate how well the description explains the business value ('why') "
                    "It should focus purely on the overarching goal and the strategic reason an API consumer would need this endpoint."
                ),
                score_criteria={
                    ScoreLevel.POOR: "Treats the endpoint purely as a database operation with no business context or workflow guidance.",
                    ScoreLevel.FAIR: "Vaguely hints at a use case, but lacks clear business value or integration workflow details.",
                    ScoreLevel.GOOD: "Provides a clear, standard business use case",
                    ScoreLevel.VERY_GOOD: "Explains specific business scenarios where this endpoint provides crucial value to the client.",
                    ScoreLevel.EXCELLENT: "Connects the endpoint directly to overarching business goals, providing a compelling 'why' that helps consumers understand its strategic value.",
                },
            ),
            EvaluationAspect.FUNCTIONALITY: AspectCriteria(
                description=(
                    "Evaluate how clearly the description explains what the endpoint accomplishes, "
                    "including BOTH the primary intended action and any secondary system state changes "
                    "or side effects (e.g., async jobs, cascading deletes, webhooks)."
                ),
                score_criteria={
                    ScoreLevel.POOR: "Merely restates the HTTP method and path (e.g., 'Posts a user') with no explanation of the actual outcome.",
                    ScoreLevel.FAIR: "Mentions the primary action vaguely, but provides no details on exactly what data is modified or if side effects occur.",
                    ScoreLevel.GOOD: "Clearly explains the main action and immediate data returned/modified, but ignores secondary system impacts.",
                    ScoreLevel.VERY_GOOD: "Explains the main action clearly and mentions key side effects or asynchronous behaviors triggered by the request.",
                    ScoreLevel.EXCELLENT: "Comprehensively explains the primary action AND maps out all hidden state changes, asynchronous jobs, or downstream notifications.",
                },
            ),
            EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION: AspectCriteria(
                description=(
                    "Evaluate parameter and schema property descriptions for human-readable business context, "
                    "cross-parameter dependencies, and property lifecycle. It MUST penalize descriptions that "
                    "merely repeat strict JSON schema validation rules."
                ),
                score_criteria={
                    ScoreLevel.POOR: "Solely repeats JSON schema validation rules (e.g., 'Must be a string of max length 10').",
                    ScoreLevel.FAIR: "Adds slight business context but relies heavily on repeating technical limits already enforced by the schema.",
                    ScoreLevel.GOOD: "Explains the domain meaning/business purpose of the property, but misses complex dependencies.",
                    ScoreLevel.VERY_GOOD: "Explains the 'why' behind constraints, mentions read-only/immutability rules, and gives examples of valid states.",
                    ScoreLevel.EXCELLENT: "Clearly defines business reasoning, documents complex cross-parameter dependencies (e.g., 'Required only if X is true'), and explains exact state transitions without redundant schema restatements.",
                },
            ),
        }

    def _has_parameter_attribute(self, source_code: str):
        try:
            node = ast.parse(source_code)
        except SyntaxError:
            return False

        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [
                    arg.arg for arg in child.args.args if arg.arg not in {"self", "cls"}
                ]
                if (
                    args
                    or child.args.vararg
                    or child.args.kwarg
                    or child.args.kwonlyargs
                ):
                    return True

            if isinstance(child, ast.ClassDef):
                for class_body_item in child.body:
                    if isinstance(class_body_item, (ast.Assign, ast.AnnAssign)):
                        return True

        return False
