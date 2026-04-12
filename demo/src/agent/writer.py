import json
import operator
import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, List, TypedDict, Annotated, Literal, Tuple, Optional, Any, Type
import yaml
from src.agent.base import BasicModel
from src.dependency_analyzer.ast_parser import CodeComponent
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename



OPENAPI_ENDPOINT_SYSTEM_PROMPT = """
<role>
You are an API Architect generating official OpenAPI 3.0 Specifications. Your job is to generate a standalone Path Item Object that will be saved as an individual file in a multi-file OpenAPI architecture.
</role>

<background>
- <source_code>: The endpoint routing function or class view.
- <resolved_context>: The source code of the schemas and dependencies used.
</background>

<instruction>
Focus strictly on the HTTP contract:
1. Route & Method Extraction: Identify the exact path. Then, scan the code to identify ALL HTTP methods it handles (e.g., checking `@route(methods=['GET', 'POST'])` or `if request.method == 'POST':`).
2. Split Operations: For EACH HTTP method you find, you must generate a distinct Operation object in the `operations` dictionary.
3. Parameters: Map path variables to `in: path` and query variables to `in: query` for the specific method they apply to.
4. Request Body: If a specific method (like POST) accepts a payload, put its FQN in `requestBody_fqn`.
5. Responses: Map the success and error returns for EACH method. 
6. External Referencing: Whenever you reference a schema, use its Fully Qualified Name (e.g., `app.schemas.TodoResponse`).
</instruction>

<execution_rule>
You MUST use the `reasoning` field to explicitly state the path and list every HTTP method you found in the code BEFORE filling out the `operations` dictionary.
</execution_rule>

<constraints>
1. NO HALLUCINATIONS: Do not document arguments, exceptions, or response codes that do not explicitly exist.
2. STANDALONE FOCUS: Remember this is a standalone Path Item file. Output ONLY the raw path item object.
</constraints>
"""

OPENAPI_ENDPOINT_USER_PROMPT = """
<resolved_context>
{context_text}
</resolved_context>

<source_code>
{source_code}
</source_code>

Generate the structured OpenAPI Endpoint object for the provided <source_code>.
"""

OPENAPI_SCHEMA_SYSTEM_PROMPT = """
<role>
You are an API Architect generating OpenAPI 3.0 Schema Objects. Your job is to convert a Python class into a standalone Schema Object file that will be referenced by other parts of the OpenAPI spec.
</role>

<background>
- <source_code>: The class definition you must parse.
- <resolved_context>: The source code of the schemas and dependencies used.
</background>

<instruction>
1. Map Python types to OpenAPI standard types.
2. Detect Required Fields: Any field lacking a default value and not wrapped in `Optional[]` goes into the `required` list.
3. Nested Schemas: If a field references another custom class, capture its FQN in `ref_fqn`. Our build system will convert this into a relative file reference (e.g., `$ref: './NestedSchema.json'`).
</instruction>

<execution_rule>
You MUST use the `reasoning` field to explicitly list the class name, all attributes, and their raw Python types before generating the final JSON structure.
</execution_rule>

<constraints>
1. STANDALONE FOCUS: Do not wrap your output in a `components: schemas:` block. Output ONLY the raw schema object for this specific class.
</constraints>
"""

OPENAPI_SCHEMA_USER_PROMPT = """
<resolved_context>
{context_text}
</resolved_context>

<source_code>
{source_code}
</source_code>

Parse this class into a structured OpenAPI Schema Object.
"""

DOCSTRING_SYSTEM_PROMPT = """
<role>
You are an Expert Technical Writer. Your job is to write highly accurate, developer-friendly documentation for the provided code component.
</role>

<background>
- <source_code>: The target function or class you must document.
- <resolved_context>: The actual source code of the external dependencies (schemas, services) this component relies on. Use this to understand underlying types.
</background>

<instruction>
Focus on execution logic, arguments, and return types. Follow these steps:
1. Analyze the signature: List every argument and its exact type.
2. Analyze the body: Identify what the function actually does and any side-effects (e.g., database writes).
3. Analyze exceptions: Look for `raise` statements to populate the exceptions list.
4. Consult context: If an argument is a custom class (e.g., `TodoService`), look at the <resolved_context> to briefly explain what it is expected to do.
</instruction>

<execution_rule>
You MUST use the `reasoning` field to plan your documentation BEFORE generating the final fields. Identify the core action, arguments, returns, and exceptions visible in the code.
</execution_rule>

<constraints>
1. NO HALLUCINATIONS: Do not document arguments or exceptions that do not explicitly exist in the <source_code>.
2. ACCURATE TYPING: Use the <resolved_context> to provide exact type hints. 
3. CONCISE CLARITY: Keep summaries to a single imperative sentence (e.g., "Fetches a user by ID."). Do not use filler phrases like "This function is responsible for...".
</constraints>
"""

DOCSTRING_USER_PROMPT = """
<resolved_context>
{context_text}
</resolved_context>

<source_code>
{source_code}
</source_code>

Generate the structured Docstring for the provided <source_code>.
"""

class ParameterDoc(BaseModel):
    """Parameter documentation of a function/method"""
    name: str = Field(description="The exact name of the argument in the code.")
    type_hint: str = Field(description="The data type (e.g., int, str, app.schemas.Todo).")
    description: str = Field(description="A brief explanation of what this parameter does.")

class ReturnDoc(BaseModel):
    """Return documentation of a function/method"""
    type_hint: str = Field(description="The return type.")
    description: str = Field(description="What the function outputs.")

class ExceptionDoc(BaseModel):
    """Exception Document of a function/method"""
    exception_type: str = Field(description="The type of error raised (e.g., ValueError, HTTPException).")
    condition: str = Field(description="Under what circumstances this error is raised.")

class DocstringOutput(BaseModel):
    """Structured output for code docstrings."""
    reasoning: str = Field(
        description="Plan the docstring. Identify the core action, list the arguments, and note any returns or exceptions visible in the source code."
    )
    summary: str = Field(description="A single-line, imperative sentence summarizing what the component does (e.g., 'Fetches a user by ID.').")
    extended_description: Optional[str] = Field(description="1-2 paragraphs detailing the execution logic or side effects. Leave null if the summary is enough.")
    arguments: List[ParameterDoc] = Field(description="List of parameters. Must match the source code signature exactly.")
    returns: Optional[ReturnDoc] = Field(description="Return documentation. Leave null if the function returns None.")
    raises: List[ExceptionDoc] = Field(description="List of exceptions explicitly raised in the source code.")

    def to_string(self) -> str:
        """Generate docstring fom DocStringOutput object"""
        doc = f'"""\n{self.summary}\n\n'
        if self.extended_description:
            doc += f"{self.extended_description}\n\n"

        if self.arguments:
            doc += "Args:\n"
            for arg in self.arguments:
                doc += f"    {arg.name} ({arg.type_hint}): {arg.description}\n"

        # ... handle returns and raises ...
        doc += '"""'
        return doc

class OpenAPIParameter(BaseModel):
    name: str = Field(description="The exact name of the parameter.")
    in_: str = Field(alias="in", description="Location: MUST be 'query', 'header', 'path', or 'cookie'.")
    description: str = Field(description="Description of the parameter.")
    required: bool = Field(description="True if the parameter is required.")
    type: str = Field(description="The OpenAPI data type (e.g., 'integer', 'string', 'boolean').")

class OpenAPIResponse(BaseModel):
    description: str = Field(description="What this response means (e.g., 'Successful retrieval').")
    schema_fqn: Optional[str] = Field(description="The Fully Qualified Name of the schema returned here. Leave null if no body is returned.")

    def to_dict(self) -> Dict[str, Any]:
        """Convert response object into dict"""

class OpenAPIOperation(BaseModel):
    """The OpenAPI 3.0 Operation Object."""
    summary: str = Field(description="Short summary of the endpoint.")
    description: str = Field(description="Detailed explanation of the endpoint behavior.")
    operationId: str = Field(description="Unique string to identify the operation (usually the function name).")
    tags: List[str] = Field(default_factory=list, description="Tags for logical grouping in the spec.")
    
    parameters: List[OpenAPIParameter] = Field(default_factory=list, description="Path, query, and header parameters.")
    requestBody_fqn: Optional[str] = Field(description="The FQN of the Pydantic schema used for the request body. Null if no body is expected.")
    
    responses: Dict[str, OpenAPIResponse] = Field(
        description="A map of HTTP status codes (as strings, e.g., '200', '404') to their response objects."
    )

class OpenAPIPathItem(BaseModel):
    """Top-level structured output mapping to an OpenAPI Path Item, supporting multiple methods."""
    
    reasoning: str = Field(
        description="1. Identify the path. 2. Identify ALL HTTP methods handled by this code (e.g., GET, POST). 3. Plan the parameters and responses for EACH method distinctly."
    )
    
    path: str = Field(description="The exact routing path (e.g., '/todos/').")
    
    operations: Dict[str, OpenAPIOperation] = Field(
        description="A dictionary where the key is the strictly lowercase HTTP method (e.g., 'get', 'post', 'put') and the value is the operation details. Create a key for EVERY method handled by the code."
    )

class OpenAPISchema(BaseModel):
    """
    A streamlined representation of an OpenAPI Schema Object.
    Contains only the most heavily used fields.
    """
    
    # --- IDENTITY & REUSABILITY ---
    
    type: Optional[str] = Field(
        default=None, 
        description="The base data type (e.g., 'string', 'integer', 'object', 'array', 'boolean')."
    )
    
    ref: Optional[str] = Field(
        default=None, 
        # alias="$ref", # OpenAPI requires "$ref", but Python doesn't allow $ in variable names
        description="Path to a reusable schema (e.g., '#/components/schemas/User'). If this is used, other fields are typically ignored."
    )

    # --- DOCUMENTATION ---

    description: Optional[str] = Field(
        default=None, 
        description="A human-readable explanation of what this specific data field represents."
    )
    
    examples: Optional[List[Any]] = Field(
        default=None, 
        description="A list of real-world sample values to show developers what the data looks like."
    )
    
    format: Optional[str] = Field(
        default=None, 
        description="A hint for the exact data format (e.g., 'date-time', 'email', 'uuid', 'password')."
    )

    # --- STRUCTURE (Recursive) ---

    properties: Optional[Dict[str, "OpenAPISchema"]] = Field(
        default=None, 
        description="For 'object' types only: A dictionary mapping property names to their child schemas."
    )
    
    required: Optional[List[str]] = Field(
        default=None, 
        description="For 'object' types only: A list of property keys that must be present in the payload."
    )
    
    items: Optional["OpenAPISchema"] = Field(
        default=None, 
        description="For 'array' types only: The schema defining what each item inside the list looks like."
    )


class State(TypedDict):
    """State of the Writer workflow"""
    components: List[CodeComponent]
    contexts: Dict[str, Dict[str, Dict[str, List[str]]]]
    type_doc: Literal["non_schema", "schema"]
    generated_endpoint_documents: Annotated[List[Tuple[str, OpenAPIPathItem]], operator.add]
    generated_docstring_documents: Annotated[List[Tuple[str, DocstringOutput]], operator.add]
    generated_documents: Dict[str, Dict[str, str]]

class WorkerState(TypedDict):
    """Worker state of workers in Writer workflow"""
    component: CodeComponent
    doc_type: Literal["docstring", "endpoint", "schema"]
    context: Dict[str, List[str]]
    generated_endpoint_documents: Annotated[List[Tuple[str, OpenAPIPathItem]], operator.add]
    generated_docstring_documents: Annotated[List[Tuple[str, DocstringOutput]], operator.add]

class Writer(BasicModel):
    def __init__(self, model: str, model_provider: str, input_context_window: int, output_context_window: int, **kwarg):
        """ Initialize a writer object

            Args:
                model: the model name
                model_provider: the provider of the model
                input_context_window: the size of input context window
                output_context_window: the size of the output context window
                
            Returns:
                a writer object"""
        
        super().__init__(agent_name="Writer",
                         model=model,
                         model_provider=model_provider,
                         input_context_window=input_context_window,
                         output_context_window=output_context_window,
                         **kwarg)
        self.docstring = self.base_llm.with_structured_output(DocstringOutput)
        self.endpoint = self.base_llm.with_structured_output(OpenAPIPathItem)
        self.schema = self.base_llm.with_structured_output(OpenAPISchema)
        self.input_context_window = input_context_window
        self.output_context_window = output_context_window

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

    def _write_openapi_spec(self, path: str, content: Dict[str, Any]) -> None:
        """Write the content into an component file in openAPI spec"""
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w") as f:
            yaml.safe_dump(content, f, sort_keys=False)

    # Workflow node
    def _llm_call(self, state: WorkerState):
        """Worker using llm core for document generation"""
        source_code = state["component"].source_code
        context = state["context"]
        doc_type = state["doc_type"]

        if doc_type == "docstring":
            schemas = DocstringOutput
            system_prompt = DOCSTRING_SYSTEM_PROMPT
            user_prompt = DOCSTRING_USER_PROMPT
            return_type = "generated_docstring_documents"
            llm = self.docstring
        elif doc_type == "endpoint":
            schemas  = OpenAPIPathItem
            system_prompt = OPENAPI_ENDPOINT_SYSTEM_PROMPT
            user_prompt = OPENAPI_ENDPOINT_USER_PROMPT
            return_type = "generated_endpoint_documents"
            llm = self.endpoint
        elif doc_type == "schema":
            schemas = OpenAPISchema
            system_prompt = OPENAPI_SCHEMA_SYSTEM_PROMPT
            user_prompt = OPENAPI_SCHEMA_USER_PROMPT
            return_type = "generated_endpoint_documents"
            llm = self.schema

        user_prompt_temp = DOCSTRING_USER_PROMPT.format(context_text = "", source_code = source_code)

        if context:
            contexts = self._context_window_fit(contexts=context, messages= [SystemMessage(system_prompt), HumanMessage(user_prompt_temp)], structured_output= schemas)
            contexts = ["\n\n".join(c) for c in contexts]
            contexts = "\n\n".join(contexts)
        else: 
            contexts = ""

        user_prompt = user_prompt.format(context_text = contexts, source_code = source_code)

        result = llm.invoke([SystemMessage(system_prompt), HumanMessage(user_prompt)])

        return {return_type: [(state["component"].id ,result)]}

    # Workflow node
    def _assign_workers(self, state: State):
        """Distribute dynamically tasks over workers"""
        sends = []
        for component in state['components']:

            context = state["contexts"][component.id]

            for doc_type in component.doc_type:
                sends.append(Send("llm_call", {"component": component,
                                               "doc_type": doc_type,
                                               "context": context[doc_type]}))

        return sends

    # Workflow node
    def _synthesize(self, state: State):
        """ Compose and reformat the distributed work from workers
            
            Args:
                state: the state of the workflow
                """
        docs = {}
        for component, docstring in state['generated_docstring_documents']:
            docs[component] = {"docstring": docstring.to_string(), "openapi": ""}

        for component, openapi in state["generated_endpoint_documents"]:
            docs[component]["openapi"] = openapi.model_dump()

        return {"generated_documents": docs}

    def invoke(self, components: CodeComponent, contexts: Dict[str, Dict[str, Dict[str, List[str]]]]) -> Dict[str, Dict[str, str]]:
        """ Send data for writer workflow to generate documents
            
            Args:
                components: List of components that is about to be documented
                contexts: List of context information provided for each component
                
            Returns:
                A dictionary that contains docstring and openapi (optional) to corresponding component"""
        
        result = self.writer.invoke({
            "components": components,
            "contexts": contexts,
        })

        return result["generated_documents"]


    def validate(self, file_path):
        file_path = Path(file_path).resolve()
        spec_dict, base_uri = read_from_filename(file_path)
        base_uri = file_path.as_uri()
        validate(spec_dict, base_uri = base_uri)
