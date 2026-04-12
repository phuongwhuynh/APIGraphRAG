import operator
from src.agent.base import BasicModel
from typing import List, Dict, TypedDict, Annotated, Tuple, Literal
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from src.dependency_analyzer.ast_parser import CodeComponent



READER_SYSTEM_PROMPT = """
<role>
Your mission is to evaluate the importance of provided context dependencies for generating a {doc_type}. 
You are an expert technical writer. You need to decide which external components are most important to understand in order to document this code properly.
</role>

<background>
- <context>: A list of external dependencies extracted by static analysis. Assume all items here are genuinely related to the code.
- <imports>: A mapping of modules and components available to the file.
- <source_code>: The source code of the target component.
</background>

<instruction>
{instruction_steps}
</instruction>

<execution_rule>
You MUST use the `reasoning` field in your output to write down your thought process BEFORE categorizing. 
- If the <context> tag is empty, your reasoning MUST start with: "Context is empty, importance arrays will be empty."
- You must explicitly cross-check any missing info against the <imports> map.
</execution_rule>

<constraints>
1. EMPTY CONTEXT RULE: If the <context> tag is empty, your `high_importance`, `medium_importance`, and `low_importance` arrays MUST be 100% empty. NEVER move items from <imports> into these lists to fill space.
2. RANK THE CONTEXT: If <context> is NOT empty, you must place EVERY item from the <context> tag into the high, medium, or low arrays based on how critical it is for writing the {doc_type}. 
3. RESTRICTED MISSING INFO: If the code uses a complex class, decorator, or function that is NOT in the <context>, you may suggest it. HOWEVER, you may ONLY suggest items that are explicitly listed in the <imports> block. 
4. NO HALLUCINATIONS: Do not guess underlying types (e.g., if you see `.to_dict()`, do not hallucinate `datetime` or `sqlalchemy` unless they are explicitly in the <imports> map).
5. FQN FORMATTING: Format missing suggestions as Fully Qualified Names using a dot (e.g., `app.models.TodoDB`) based on the <imports> map.
</constraints>
"""

DOCSTRING_INSTRUCTION_STEPS = """
Evaluate importance based on Docstring needs:
- high_importance: Direct inputs/outputs, Data models (Pydantic/ORM), Enums. You absolutely need to see these to explain parameters and return types.
- medium_importance: External services, Database sessions, Custom Exceptions. You need to see these to explain side-effects and state changes.
- low_importance: Internal implementation details, standard utilities (logging, math). You do not need to see their source code to explain what the function does.
"""

ENDPOINT_INSTRUCTION_STEPS = """
Evaluate importance based on OpenAPI needs:
- high_importance: Pydantic schemas, Request/Response typing, Routing decorators. You absolutely need their source code to define the API HTTP contract.
- medium_importance: Auth/Authorization middleware (Depends), HTTP Exceptions. You need these to define security and error responses.
- low_importance: Database ORM models, internal business services. These do not affect the public OpenAPI HTTP contract.
"""

SCHEMA_INSTRUCTION_STEPS = """
Evaluate importance based on Schema/Data Model needs:
- high_importance: Parent base classes, nested schema objects (other Pydantic models/Serializers), and Enums used as field types. You absolutely need their source code to define the complete JSON structure, inherited fields, and allowed choice values.
- medium_importance: Custom field validators, default value factories, and complex type aliases. You need these to accurately document property constraints (e.g., regex, min/max boundaries) and default behaviors.
- low_importance: Database ORM models, repository layers, and business logic services. The underlying database implementation or business use-case does not alter the exact JSON shape of this specific schema.
"""

READER_USER_PROMPT = """
<context>
{context}
</context>

<imports>
{imports}
</imports>

<source_code>
{source_code}
</source_code>

Evaluate the importance of the <context> items and identify any critical missing dependencies needed to generate the {doc_type}.
"""


class Context(BaseModel):
    """Context information categorization"""
    high_importance: List[str] = Field(default_factory=list, description="Dependencies classified as HIGH importance based on the provided instruction steps. DO NOT include internal variables or standard built-in types.")
    medium_importance: List[str] = Field(default_factory=list, description="Dependencies classified as MEDIUM importance based on the provided instruction steps. DO NOT include internal database columns.")
    low_importance: List[str] = Field(default_factory=list, description="Dependencies classified as LOW importance based on the provided instruction steps, or items not actively used.")

class ComponentContext(BaseModel):
    """Context information accessed by reader"""
    reasoning: str = Field(
        description=(
            """You MUST structure your reasoning exactly like this:\n
            1. Context Ranking: [Go through every item in the <context> tag. Explain WHY it is High, Medium, or Low importance based on its semantic role.]\n
            2. Missing Info Check: [If you need to see the source code of a component used in the code, identify its local name. THEN, explicitly verify it exists in the <imports> block. If it is NOT in <imports>, you MUST write 'Not in imports, ignoring'. If it is, map it to its FQN.]"""
        )
    )
    context: Context = Field(description="The categorization of available context information")
    suggested_missing_information: List[str] = Field(description="A flat list of critical schemas, decorators, or external functions visible in the source code but NOT in the provided context.")

# Workflow states
class State(TypedDict):
    """State of the workflow"""
    code_components: List[CodeComponent]
    docstring_context: Annotated[List[Tuple[str, ComponentContext]], operator.add]
    endpoint_context: Annotated[List[Tuple[str, ComponentContext]], operator.add]
    schema_context: Annotated[List[Tuple[str, ComponentContext]], operator.add]
    context_dict: Dict[str, Dict[str, ComponentContext]]

class WorkerState(TypedDict):
    """State of each reading worker"""
    code_component: CodeComponent
    doc_type: Literal["docstring", "endpoint", "schema"]
    docstring_context: Annotated[List[Tuple[str, ComponentContext]], operator.add]
    endpoint_context: Annotated[List[Tuple[str, ComponentContext]], operator.add]
    schema_context: Annotated[List[Tuple[str, ComponentContext]], operator.add]

# Workflow
class Reader(BasicModel):
    def __init__(self, model: str, model_provider: str, input_context_window: int, output_context_window: int, **kwarg):
        """Initiate a reading workflow"""

        super().__init__(
            agent_name= "reader",
            model= model,
            model_provider= model_provider,
            input_context_window= input_context_window,
            output_context_window= output_context_window,
            **kwarg
        )

        self.llm_structured_output = self.base_llm.with_structured_output(ComponentContext, include_raw= True)


        # Workflow compile
        builder = StateGraph(State)

        builder.add_node("llm_call", self._llm_call)
        builder.add_node("synthesizer", self._synthesizer)

        builder.add_conditional_edges(START, self._assign_worker, ["llm_call"])
        builder.add_edge("llm_call", "synthesizer")
        builder.add_edge("synthesizer", END)

        self.reader = builder.compile()
        

    # Workflow nodes
    def _llm_call(self, state: WorkerState):
        """Reader generate requirements for code context"""
        imports = list(state["code_component"].imports)
        if imports:
            imports[0] = "import:\n" + imports[0]
        from_imports = state["code_component"].from_imports
        if from_imports:
            from_imports = [f"from {key} imports : {values}" for key, values in from_imports.items()]
        context= state["code_component"].depends_on
        source_code = state["code_component"].source_code

        doc_type = state["doc_type"]
        if doc_type == "docstring":
            return_type = "docstring_context"
            instruction_steps = DOCSTRING_INSTRUCTION_STEPS

        elif doc_type == "endpoint":
            doc_type = "openAPI spec for an" + doc_type 
            return_type = "endpoint_context"
            instruction_steps = ENDPOINT_INSTRUCTION_STEPS

        elif doc_type == "schema":
            doc_type = "openAPI spec for a" + doc_type
            return_type = "schema_context"
            instruction_steps = SCHEMA_INSTRUCTION_STEPS
        
        # Construct prompt fit with context window
        # Prompt template
        system_prompt = SystemMessage(READER_SYSTEM_PROMPT.format(doc_type=doc_type, instruction_steps=instruction_steps))
        user_prompt = HumanMessage(READER_USER_PROMPT.format(context= "", imports= "", source_code=source_code, doc_type=doc_type))
        # Importance order: context > from_imports > imports
        contexts = [context, from_imports, imports] 
        contexts = self._context_window_fit(contexts= contexts, messages=[system_prompt, user_prompt], structured_output=ComponentContext)

        # Create the prompt
        context = "\n".join(contexts[0])
        from_imports = "\n".join(contexts[1]) if contexts[1] else ""
        imports = ", ".join(contexts[2]) if contexts[2] else ""

        user_prompt = HumanMessage(READER_USER_PROMPT.format(context= context, imports= imports + '\n' + from_imports, source_code=source_code, doc_type=doc_type))

        result = self.llm_structured_output.invoke([system_prompt, user_prompt])
        raw_result = result['raw']
        result = result['parsed']

        self.messages_logger.info(f"System message: {system_prompt.content}\n Human message: {user_prompt.content}\n result: {result}\n Token usage: {raw_result.usage_metadata}")

        return {return_type: [( state["code_component"].id, result )]}

    # Workflow nodes
    def _assign_worker(self, state: State):
        """Assign a reader to each code comoponent in the list"""

        sends = []

        for code_component in state["code_components"]:
            for doc_type in code_component.doc_type:
                sends.append(Send('llm_call', {"code_component": code_component,
                                               "doc_type": doc_type,}))

        return sends

    # Workflow nodes
    def _synthesizer(self, state: State):
        """Synthesize the returned result from parralel work"""

        context_dict = {}

        for component_id, context in state.get("docstring_context", []):
            context_dict[component_id] = {"docstring": context.model_dump(), "endpoint": None, "schema": None}
        for component_id, context in state.get("endpoint_context", []):
            context_dict[component_id]["openapi"] = context.model_dump()
        for component_id, context in state.get("schema_context", []):
            context_dict[component_id]["schema"] = context.model_dump()



        return {"context_dict": context_dict}

    # Workflow invoke
    def invoke(self, components: List[CodeComponent]) -> Dict[str,  Dict[str, ComponentContext]]:
        """Send formatted request to reader llm"""
        result = self.reader.invoke({"code_components": components})
        return result["context_dict"]


