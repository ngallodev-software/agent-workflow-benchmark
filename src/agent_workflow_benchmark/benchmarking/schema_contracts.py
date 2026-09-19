from __future__ import annotations
import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from agent_workflow.errors import WorkflowError

def _schemas() -> dict[str, dict[str, Any]]:
    result={}
    root=files("agent_workflow_benchmark").joinpath("schemas")
    for item in root.iterdir():
        if item.name.endswith(".json"):
            value=json.loads(item.read_text(encoding="utf-8")); sid=value.get("$id")
            if isinstance(sid,str): result[sid]=value
    return result

def validate_instance(value: Any, schema: str, *, artifact: str="value") -> None:
    spec=_schemas().get(schema)
    if spec is None: raise WorkflowError(f"unknown benchmark schema: {schema}")
    errors=sorted(Draft202012Validator(spec).iter_errors(value), key=lambda e:list(e.path))
    if errors:
        first=errors[0]; where=".".join(str(x) for x in first.path) or "<root>"
        raise WorkflowError(f"{artifact} does not satisfy {schema} at {where}: {first.message}")

def read_contract(path: Path, schema: str|None=None) -> dict[str, Any]:
    try: value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise WorkflowError(f"invalid benchmark contract {path}: {exc}") from exc
    if not isinstance(value,dict): raise WorkflowError(f"benchmark contract must be an object: {path}")
    expected=schema or value.get("schema")
    if not isinstance(expected,str): raise WorkflowError(f"benchmark contract has no schema: {path}")
    validate_instance(value,expected,artifact=str(path)); return value
