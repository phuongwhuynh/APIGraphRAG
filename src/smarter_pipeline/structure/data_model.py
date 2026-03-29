from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Trace:
    file: str
    line: int
    code: str


@dataclass
class Parameter:
    name: str
    location: str = "query"  # query, path, header, cookie
    type: str = "unknown"


@dataclass
class Condition:
    expr: str
    trace: Trace


@dataclass
class Response:
    status: Optional[int]
    trigger: str
    trace: Trace


@dataclass
class LinkedCondition:
    expr: str
    uses_params: List[str]
    trace: Trace


@dataclass
class LinkedResponse:
    status: Optional[int]
    trigger: str
    conditions: List[LinkedCondition]
    trace: Trace


@dataclass
class FunctionNode:
    name: str
    file: str
    params: List[str]
    calls: List[str] = field(default_factory=list)
    conditions: List[Condition] = field(default_factory=list)
    responses: List[Response] = field(default_factory=list)
