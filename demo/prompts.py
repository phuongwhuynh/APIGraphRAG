# prompts.py

SCHEMA_PROMPT = SCHEMA_PROMPT = """
You are a senior backend engineer specializing in API schema design.

Your task is to generate a SINGLE OpenAPI-compatible JSON Schema
for the provided Python data model.

IMPORTANT RULES:
- Do NOT invent fields or types.
- Use ONLY information visible in the source code and provided dependencies.
- Respect inheritance using OpenAPI `allOf`.
- If a type cannot be statically resolved, mark it as `"type": "object"` and explain why.
- Reason internally, but DO NOT reveal chain-of-thought.
- Output must be VALID JSON and match the required structure exactly.

========================
OUTPUT FORMAT (STRICT)
========================

{
  "name": "<SchemaName>",
  "type": "object | string | integer | number | boolean",
  "description": "<High-level description of the schema>",
  "properties": {
    "<field_name>": {
      "type": "<OpenAPI type>",
      "format": "<optional>",
      "description": "<field description>",
      "nullable": true | false
    }
  },
  "required": [
    "<field_name>"
  ],
  "enum": [
    "<enum_value>"
  ],
  "allOf": [
    { "$ref": "<parent_schema_ref>" }
  ],
  "dynamic_behavior": {
    "detected": true | false,
    "notes": "<limitations of static analysis>"
  },
  "confidence": "high | medium | low"
}

Omit keys that do NOT apply (e.g., enum, allOf).

========================
FEW-SHOT EXAMPLES
========================

--- Example 1 (Pydantic Model) ---

SOURCE:
class User(BaseModel):
    id: int
    name: str
    email: Optional[str]

OUTPUT:
{
  "name": "User",
  "type": "object",
  "description": "Represents a user entity.",
  "properties": {
    "id": {
      "type": "integer",
      "description": "Unique identifier.",
      "nullable": false
    },
    "name": {
      "type": "string",
      "description": "User's name.",
      "nullable": false
    },
    "email": {
      "type": "string",
      "description": "User email address.",
      "nullable": true
    }
  },
  "required": ["id", "name"],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "high"
}

--- Example 2 (Enum) ---

SOURCE:
class Status(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

OUTPUT:
{
  "name": "Status",
  "type": "string",
  "description": "Allowed status values.",
  "enum": ["active", "inactive"],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "high"
}

--- Example 3 (Inheritance) ---

SOURCE:
class BaseResponse(BaseModel):
    success: bool

class UserResponse(BaseResponse):
    user: User

OUTPUT:
{
  "name": "UserResponse",
  "type": "object",
  "description": "Response wrapper containing a user.",
  "allOf": [
    { "$ref": "./BaseResponse.json" }
  ],
  "properties": {
    "user": {
      "$ref": "./User.json"
    }
  },
  "required": ["user"],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "high"
}

========================
NOW DOCUMENT THIS SCHEMA
========================

SCHEMA NAME:
{schema_name}

SOURCE CODE:
{source_code}

PARENT SCHEMAS:
{parents}

DEPENDENCIES:
{dependencies}

DYNAMIC FLAGS:
{dynamic_flags}
"""



PATH_PROMPT = """
You are a senior API architect.

Your task is to generate an OpenAPI Path Item Object
for a SINGLE API endpoint based on the provided Python route function.

IMPORTANT RULES:
- Do NOT invent routes, parameters, or responses.
- Use ONLY decorators, function signature, and type hints.
- If response or request schemas are unknown, reference provided dependencies.
- Reason internally, but DO NOT reveal chain-of-thought.
- Output must be VALID OpenAPI JSON.

========================
OUTPUT FORMAT (STRICT)
========================

{
  "path": "<URL path>",
  "method": "<get | post | put | delete | patch>",
  "summary": "<1-line description>",
  "description": "<Detailed behavior description>",
  "parameters": [
    {
      "name": "<param_name>",
      "in": "path | query",
      "required": true | false,
      "schema": {
        "type": "<OpenAPI type>"
      },
      "description": "<parameter meaning>"
    }
  ],
  "requestBody": {
    "required": true | false,
    "content": {
      "application/json": {
        "schema": {
          "$ref": "<schema_ref>"
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "<success description>",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "<schema_ref>"
          }
        }
      }
    }
  },
  "dependencies": [
    "<schema or function names>"
  ],
  "dynamic_behavior": {
    "detected": true | false,
    "notes": "<limitations>"
  },
  "confidence": "high | medium | low"
}

Omit parameters or requestBody if not applicable.

========================
FEW-SHOT EXAMPLES
========================

--- Example 1 (GET with path param) ---

SOURCE:
@app.get("/users/{user_id}")
def get_user(user_id: int) -> UserResponse:
    ...

OUTPUT:
{
  "path": "/users/{user_id}",
  "method": "get",
  "summary": "Retrieve a user by ID.",
  "description": "Returns user details for the specified identifier.",
  "parameters": [
    {
      "name": "user_id",
      "in": "path",
      "required": true,
      "schema": { "type": "integer" },
      "description": "User identifier."
    }
  ],
  "responses": {
    "200": {
      "description": "User retrieved successfully.",
      "content": {
        "application/json": {
          "schema": { "$ref": "./UserResponse.json" }
        }
      }
    }
  },
  "dependencies": ["UserResponse"],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "high"
}

--- Example 2 (POST with request body) ---

SOURCE:
@app.post("/todos")
def create(todo: TodoCreate) -> TodoResponse:
    ...

OUTPUT:
{
  "path": "/todos",
  "method": "post",
  "summary": "Create a new todo item.",
  "description": "Creates and returns a new todo resource.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": { "$ref": "./TodoCreate.json" }
      }
    }
  },
  "responses": {
    "200": {
      "description": "Todo created successfully.",
      "content": {
        "application/json": {
          "schema": { "$ref": "./TodoResponse.json" }
        }
      }
    }
  },
  "dependencies": ["TodoCreate", "TodoResponse"],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "high"
}

========================
NOW DOCUMENT THIS API ROUTE
========================

ROUTE NAME:
{route_name}

SOURCE CODE:
{source_code}

DEPENDENCIES (SCHEMAS & FUNCTIONS):
{dependencies}

DYNAMIC FLAGS:
{dynamic_flags}
"""



FUNCTION_PROMPT = """
You are a senior software engineer and technical writer.

Your task is to generate accurate, concise documentation for an INTERNAL Python FUNCTION
based strictly on the provided source code and dependency context.

IMPORTANT RULES:
- Do NOT guess behavior that is not visible in the code.
- Do NOT invent parameters, return values, or side effects.
- If information is unclear, explicitly state "Not statically determinable".
- Reason internally, but DO NOT reveal chain-of-thought or internal reasoning.
- Output must follow the specified structure exactly.

The function is NOT an API endpoint.
It is NOT exposed in OpenAPI.
It is an internal program unit.

You will be given:
1. Function source code
2. Known dependencies (functions, schemas)
3. Dynamic analysis flags (if any)

========================
OUTPUT FORMAT (STRICT)
========================

{
  "name": "<function_name>",
  "summary": "<1–2 sentence high-level description>",
  "parameters": [
    {
      "name": "<param_name>",
      "type": "<type or 'Unknown'>",
      "description": "<what this parameter represents>",
      "required": true | false
    }
  ],
  "returns": {
    "type": "<type or 'Unknown'>",
    "description": "<what is returned or 'No return value'>"
  },
  "raises": [
    {
      "exception": "<exception name>",
      "condition": "<when it may occur>"
    }
  ],
  "side_effects": [
    "<file I/O | database mutation | state change | None detected>"
  ],
  "dependencies": [
    "<function or schema names used>"
  ],
  "dynamic_behavior": {
    "detected": true | false,
    "notes": "<why static analysis is limited, if applicable>"
  },
  "confidence": "high | medium | low"
}

========================
FEW-SHOT EXAMPLES
========================

--- Example 1 (Pure function) ---

SOURCE:
def add(a: int, b: int) -> int:
    return a + b

OUTPUT:
{
  "name": "add",
  "summary": "Computes the sum of two integers.",
  "parameters": [
    {
      "name": "a",
      "type": "int",
      "description": "First operand.",
      "required": true
    },
    {
      "name": "b",
      "type": "int",
      "description": "Second operand.",
      "required": true
    }
  ],
  "returns": {
    "type": "int",
    "description": "The sum of a and b."
  },
  "raises": [],
  "side_effects": [
    "None detected"
  ],
  "dependencies": [],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "high"
}

--- Example 2 (Calls another function, unclear types) ---

SOURCE:
def create_todo(data):
    validated = validate_input(data)
    return save_todo(validated)

OUTPUT:
{
  "name": "create_todo",
  "summary": "Validates input data and persists a new todo item.",
  "parameters": [
    {
      "name": "data",
      "type": "Unknown",
      "description": "Raw input used to create a todo item.",
      "required": true
    }
  ],
  "returns": {
    "type": "Unknown",
    "description": "The persisted todo object."
  },
  "raises": [],
  "side_effects": [
    "Database mutation"
  ],
  "dependencies": [
    "validate_input",
    "save_todo"
  ],
  "dynamic_behavior": {
    "detected": false,
    "notes": ""
  },
  "confidence": "medium"
}

--- Example 3 (Dynamic behavior present) ---

SOURCE:
def load_plugin(name):
    module = __import__(name)
    return module.run()

OUTPUT:
{
  "name": "load_plugin",
  "summary": "Dynamically loads a plugin module and executes its entry point.",
  "parameters": [
    {
      "name": "name",
      "type": "str",
      "description": "Module name to import at runtime.",
      "required": true
    }
  ],
  "returns": {
    "type": "Unknown",
    "description": "Result of the plugin execution."
  },
  "raises": [],
  "side_effects": [
    "Dynamic module loading"
  ],
  "dependencies": [],
  "dynamic_behavior": {
    "detected": true,
    "notes": "Dynamic import prevents full static resolution."
  },
  "confidence": "low"
}

========================
NOW DOCUMENT THIS FUNCTION
========================

FUNCTION NAME:
{function_name}

SOURCE CODE:
{source_code}

DEPENDENCIES:
{dependencies}

DYNAMIC FLAGS:
{dynamic_flags}
"""
