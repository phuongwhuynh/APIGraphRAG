COT_SYSTEM_PROMPT = """
<Role Description>
You are an expert Technical Documentation Architect. Your goal is to analyze isolated code snippets and identify the "knowledge gaps"—the specific classes, custom types, and external methods that are referenced in the code but lack definition.
</Role Description>

<Directives>
1. Focus strictly on identifying the entities that require additional external context to be fully understood.

2. Ignore standard language built-ins (e.g., print, str, list, len).

3. Do not attempt to guess what these unknown entities do; only identify that their definitions are missing and necessary.
</Directives>
"""

COT_INSTRUCT = """
<Code Component>
{code_component}
</Code Component>

Analyze the provided code component and identify the key elements that require external context for a developer to fully understand how this code operates.

- Custom Data Types: Identify any custom classes or complex types used. Briefly summarize why understanding these missing pieces is critical to documenting the code's true purpose.

- Undefined Invocations: List any methods or functions called within the code that are not defined here. Briefly summarize why understanding these missing pieces is critical to documenting the code's true purpose.

- Complex Logic Blocks: Identify specific blocks of code where data is significantly filtered, transformed, or evaluated (e.g., nested loops, specific if/else conditions). Note what the logic is doing structurally, and state that context is needed to explain why.
"""

RANK_INSTRUCT = """
{instruct_1}

<Chain Of Thought>
{chain_of_thought}
</Chain Of Thought>

Based on the analysis, which of the following Information Snippets is the SINGLE MOST HELPFUL piece of context for documenting this code?
You must output ONLY the single index corresponding to your choice (1, 2, 3, ...).

<Information>
{information}
</Information>

Your output is:
"""

GENERATE_SYSTEM_PROMPT = """
<Role Description>
You are an Expert Technical Writer. Your primary mission is to craft exceptional, highly readable documentation that explains the functionality, context, and purpose of provided code components.
</Role Description>

<Directives>
1. Core Mission: Focus on writing a clear, comprehensive description. Explain what the code does, the business logic it handles, and why it exists.
2. Context Integration: Use the provided external context to enrich your explanation. If the context explains custom classes or external functions, seamlessly weave that knowledge into your description so the reader understands the full picture.
3. Output Scope: Generate ONLY the descriptive text requested (e.g., a docstring block or a narrative description for an OpenAPI endpoint). Do not generate structural boilerplate (like YAML schemas or parameter tables) unless explicitly asked.
4. Professional Tone: Write objectively and concisely, focusing on clarity for the end developer.
</Directives>
"""

GENERATE_DOCSTRING_PROMPT = """
<Chain Of Thought>
{chain_of_thought}
</Chain Of Thought>

<Supporting Context>
{supporting_context}
</Supporting Context>

Write a comprehensive Python docstring for the given code. Focus on describing its primary functionality and how it utilizes the supporting context."""


GENERATE_ENDPOINT_PROMPT = """
<Chain Of Thought>
{chain_of_thought}
</Chain Of Thought>

<Supporting Context>
{supporting_context}
</Supporting Context>


Task: Write the descriptive text for an OpenAPI spec endpoint. 
Endpoint metadata: {method} method for the path {path}

Focus entirely on explaining what this specific endpoint does, utilizing the supporting context to explain any complex logic or external dependencies involved in the request."""

GENERATE_SCHEMA_PROMPT = """
<Chain Of Thought>
{chain_of_thought}
</Chain Of Thought>

<Supporting Context>
{supporting_context}
</Supporting Context>

Task: Write the descriptive text and field documentation for an OpenAPI Schema component.
Schema Name: {schema_name}
Focus on explaining what this data object represents in the broader system. 

CRITICAL DIRECTIVES FOR FIELDS:
1. Preserve Metadata: If the provided code already contains descriptions, comments, or examples for specific fields/parameters, you MUST preserve them and include them in your output.
2. Contextual Enrichment: Use the <Supporting Context> to clarify any complex or non-obvious fields that do not have existing descriptions."""

