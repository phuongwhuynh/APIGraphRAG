from dataclasses import dataclass
from enum import Enum
from typing import List, Literal, Dict, Optional, Any, TypedDict, Annotated, Tuple
from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
import ast
import math
from statistics import mean, pstdev, median, quantiles
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

        self.total_object += len(code_components)

        result = self.evaluator.invoke({"code_components": code_components})

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

    def _calculate_statistics(self, scores: List[float]) -> Dict[str, float]:
        """
        Calculate comprehensive statistics for a list of scores.

        Returns a dictionary with: count, min, max, avg, median, std_dev,
        coefficient_of_variation, Q1, Q2, Q3.
        """
        if not scores:
            return {}

        count = len(scores)
        avg = mean(scores)
        std_dev = pstdev(scores) if count > 1 else 0.0

        # Calculate coefficient of variation (CV = std_dev / mean * 100)
        cv = (std_dev / avg * 100) if avg != 0 else 0.0

        # Calculate quartiles using quantiles
        if count >= 3:
            quarts = quantiles(scores, n=4)  # Returns Q1, Q2 (median), Q3
            q1, q2, q3 = quarts[0], quarts[1], quarts[2]
        else:
            q1 = q2 = q3 = median(scores) if count > 0 else 0.0

        return {
            "count": count,
            "min": min(scores),
            "max": max(scores),
            "avg": round(avg, 4),
            "median": round(q2, 4),
            "std_dev": round(std_dev, 4),
            "cv_percent": round(cv, 2),  # Coefficient of variation as percentage
            "Q1": round(q1, 4),
            "Q2": round(q2, 4),
            "Q3": round(q3, 4),
        }

    def show_statistic(self, file_path: str):
        data = load_json(file_path=file_path)

        if not isinstance(data, dict) or not data:
            return {}

        stats = {
            EvaluationAspect.MOTIVATION.value.title(): [],
            EvaluationAspect.FUNCTIONALITY.value.title(): [],
            EvaluationAspect.PARAMETER_ATTRIBUTE_DESCRIPTION.value.title(): [],
        }

        for _, aspect_scores in data.items():
            for key, score in aspect_scores.items():
                stats[key].append(score)

        return {
            "evaluated_items": self.total_object,
            EvaluationAspect.MOTIVATION.value.title(): self._calculate_statistics(
                stats[EvaluationAspect.MOTIVATION.value.title()]
            ),
            EvaluationAspect.FUNCTIONALITY.value.title(): self._calculate_statistics(
                stats[EvaluationAspect.FUNCTIONALITY.value.title()]
            ),
        }

    def _assign_worker(self, state: State) -> Dict[str, float]:
        sends = []
        for component_id, code_component in state["code_components"].items():
            source_code = code_component["source_code"]
            for doc_type, doc_content in code_component.items():
                if doc_type == "source_code" or (not doc_content):
                    continue
                if not self.docstring_evaluate and doc_type == DocType.DOCSTRING.value:
                    continue
                criteria = self._get_criteria(doc_type)

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

    def _get_criteria(self, doc_type: Literal["docstring", "endpoint", "schema", "parameter"]):
        if doc_type == DocType.DOCSTRING.value:
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
            }
        elif doc_type == DocType.ENDPOINT.value:
            return {
            EvaluationAspect.MOTIVATION: AspectCriteria(
                description=(
                    "Assesses how effectively the description communicates the purpose of the endpoint from the perspective of an API consumer — the why that justifies calling this endpoint."
                ),
                score_criteria={
                    ScoreLevel.POOR: "No indication of purpose or use case. The description merely restates the HTTP method and path or the function name.",
                    ScoreLevel.FAIR: "Vaguely hints at a use case but provides no concrete workflow context or consumer-facing value.",
                    ScoreLevel.GOOD: "Clearly states the business goal or user scenario the endpoint addresses.",
                    ScoreLevel.VERY_GOOD: "Explains specific scenarios or workflows in which the endpoint provides value to the API consumer.",
                    ScoreLevel.EXCELLENT: "Provides a precise and concrete articulation of the endpoint's consumer-facing purpose, situating it within a meaningful workflow context that guides a developer on when and why to use it.",
                },
            ),
            EvaluationAspect.FUNCTIONALITY: AspectCriteria(
                description=(
                    "Assesses how clearly and completely the description explains what the endpoint does when invoked — the what of its operational behavior"
                ),
                score_criteria={
                    ScoreLevel.POOR: "Merely restates the HTTP method and path with no explanation of actual behavior or outcome.",
                    ScoreLevel.FAIR: "Mentions the primary action vaguely without specifying what data is modified, returned, or affected.",
                    ScoreLevel.GOOD: "Clearly explains the primary action and its immediate outcome, but omits secondary system effects.",
                    ScoreLevel.VERY_GOOD: "Explains the primary action and mentions key secondary effects or asynchronous behaviors triggered by the request.",
                    ScoreLevel.EXCELLENT: "Comprehensively describes the primary action and all material secondary effects, giving the consumer a complete picture of the endpoint's behavioral contract.",
                },
            ),
        }
        elif doc_type == DocType.SCHEMA.value:
            
            return {
            EvaluationAspect.MOTIVATION: AspectCriteria(
                description=(
                    "Assesses how effectively the description communicates the domain purpose of the data object — what real-world concept or system entity it represents and why it exists as a distinct model."
                ),
                score_criteria={
                    ScoreLevel.POOR: "No indication of what the object represents or why it exists. The description merely restates the class name.",
                    ScoreLevel.FAIR: "Identifies the object type in generic terms but provides no domain context or system role.",
                    ScoreLevel.GOOD: "Clearly states what domain concept the object represents and its general role within the system.",
                    ScoreLevel.VERY_GOOD: "Explains the object's domain purpose and provides context about when or how it is used within the system, as inferable from the source code.",
                    ScoreLevel.EXCELLENT: "Provides a precise characterization of the domain concept modeled, its system role, and any notable constraints or behavioral properties — such as validation rules or state restrictions — that are directly evident from the source code.",
                },
            ),
            EvaluationAspect.FUNCTIONALITY: AspectCriteria(
                description=(
                    "Assesses how clearly the description explains the structural and behavioral characteristics of the data object — what its fields represent, what constraints govern them, and any validation or transformation logic applied at the schema level"
                ),
                score_criteria={
                    ScoreLevel.POOR: "No description of fields, constraints, or schema behavior.",
                    ScoreLevel.FAIR: "Mentions fields superficially by restating their names or types without adding semantic meaning.",
                    ScoreLevel.GOOD: "Explains the semantic meaning of the primary fields in human-readable terms beyond their type declarations.",
                    ScoreLevel.VERY_GOOD: "Explains field semantics and captures key constraints or validation rules directly present in the source code.",
                    ScoreLevel.EXCELLENT: "Accurately describes all significant fields, their semantic meaning, any validation constraints, cross-field dependencies, or state restrictions directly evident from the source code, giving the consumer a complete understanding of the data contract.",
                },
            ),
        }
        else:
            return {
            EvaluationAspect.MOTIVATION: AspectCriteria(
                description=(
                    "Assesses how effectively the description communicates the purpose of the parameter from the perspective of an API consumer — what the parameter controls or enables, and why a caller would need to provide it."
                ),
                score_criteria={
                    ScoreLevel.POOR: "No indication of purpose. The description merely restates the parameter name or type.",
                    ScoreLevel.FAIR: "Vaguely states that the parameter is used by the endpoint without explaining what it controls or enables.",
                    ScoreLevel.GOOD: "Clearly states what the parameter controls or enables in the context of the endpoint's behavior.",
                    ScoreLevel.VERY_GOOD: "Explains the parameter's role and provides context about its effect on the endpoint's behavior or output.",
                    ScoreLevel.EXCELLENT: "Precisely articulates the parameter's role, its effect on endpoint behavior, and any notable constraints or conditional behavior directly inferable from the source code.",
                },
            ),
            EvaluationAspect.FUNCTIONALITY: AspectCriteria(
                description=(
                    "Assesses how accurately and completely the description characterizes the parameter's constraints, valid values, and behavioral implications — the what of how the parameter behaves within the endpoint."
                ),
                score_criteria={
                    ScoreLevel.POOR: "Solely restates the parameter type or copies the validation rule verbatim with no semantic explanation.",
                    ScoreLevel.FAIR: "Adds slight context beyond the type but relies heavily on restating technical constraints already visible in the schema.",
                    ScoreLevel.GOOD: "Explains the semantic meaning of the parameter's constraints or valid values in human-readable terms.",
                    ScoreLevel.VERY_GOOD: "Explains constraint semantics and captures any default behavior, optional versus required distinction, or conditional usage directly inferable from the source code.",
                    ScoreLevel.EXCELLENT: "Comprehensively describes the parameter's constraints, their semantic meaning, any cross-parameter dependencies, and the behavioral implications of different values, as directly inferable from the source code.",
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
