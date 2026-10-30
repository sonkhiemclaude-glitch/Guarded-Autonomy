"""Action grammar for grammar-constrained decoding (Sec. 3.1, Sec. 7.1).

Two equivalent descriptions of the action schema are provided:
* ``ACTION_JSON_SCHEMA``: a JSON Schema using only ``oneOf``, ``const``, ``type``, ``required``,
  ``properties`` and ``additionalProperties`` (intended to stay inside the subset that llama.cpp
  converts to a grammar and that vLLM's ``json`` structured output accepts);
* ``ACTION_GBNF``: a hand-written GBNF grammar for llama.cpp's ``--grammar`` / ``grammar`` field.

Both must be validated against the *pinned* llama.cpp commit / vLLM version before the system-level
runs (TODO_IMPLEMENTATION.md, item AG-2). Tests here check only that every string accepted by the
schema parses with ``parse_action`` and that the grammar text is well-formed at the rule level.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List

_INT = {"type": "integer"}
_REASON = {"type": "string", "maxLength": 200}


def _obj(kind: str, props: Dict[str, Any]) -> Dict[str, Any]:
    properties = {"type": {"const": kind}, **props, "reason": _REASON}
    return {"type": "object", "properties": properties, "required": ["type", *props.keys()],
            "additionalProperties": False}


ACTION_JSON_SCHEMA: Dict[str, Any] = {
    "title": "GuardedAutonomyAction",
    "oneOf": [
        _obj("route_change", {"dest": _INT, "next_hop": _INT}),
        _obj("isolate", {"node": _INT}),
        _obj("reinstate", {"node": _INT}),
        _obj("set_power", {"power_dbm": {"type": "number"}}),
        _obj("defer", {}),
    ],
}

ACTION_GBNF = r'''
root         ::= route-change | isolate | reinstate | set-power | defer
route-change ::= "{" ws "\"type\"" ws ":" ws "\"route_change\"" ws "," ws "\"dest\"" ws ":" ws int ws "," ws "\"next_hop\"" ws ":" ws int reason? ws "}"
isolate      ::= "{" ws "\"type\"" ws ":" ws "\"isolate\"" ws "," ws "\"node\"" ws ":" ws int reason? ws "}"
reinstate    ::= "{" ws "\"type\"" ws ":" ws "\"reinstate\"" ws "," ws "\"node\"" ws ":" ws int reason? ws "}"
set-power    ::= "{" ws "\"type\"" ws ":" ws "\"set_power\"" ws "," ws "\"power_dbm\"" ws ":" ws number reason? ws "}"
defer        ::= "{" ws "\"type\"" ws ":" ws "\"defer\"" reason? ws "}"
reason       ::= ws "," ws "\"reason\"" ws ":" ws string
string       ::= "\"" ( [^"\\] | "\\" ["\\/bfnrt] )* "\""
int          ::= "-"? [0-9]+
number       ::= "-"? [0-9]+ ("." [0-9]+)?
ws           ::= [ \t\n]*
'''.strip()


def gbnf_rule_names(grammar: str = ACTION_GBNF) -> List[str]:
    return re.findall(r"^([a-z][a-z0-9-]*)\s*::=", grammar, flags=re.M)


def gbnf_undefined_references(grammar: str = ACTION_GBNF) -> List[str]:
    """Rule names referenced but not defined (should be empty)."""
    defined = set(gbnf_rule_names(grammar))
    body = re.sub(r'"(?:[^"\\]|\\.)*"', "", grammar)        # drop string literals
    body = re.sub(r"\[(?:[^\]\\]|\\.)*\]", "", body)          # drop character classes
    refs = set(re.findall(r"(?<![a-z0-9-])([a-z][a-z0-9-]*)(?![a-z0-9-]*\s*::=)", body))
    return sorted(r for r in refs if r not in defined)


def validate_against_schema(obj: Any) -> bool:
    """Minimal validator for ACTION_JSON_SCHEMA (the keywords it uses), for tests and for
    rejecting malformed agent output early in logs. The shield's I0 remains authoritative."""
    if not isinstance(obj, dict):
        return False
    for alt in ACTION_JSON_SCHEMA["oneOf"]:
        props = alt["properties"]
        if obj.get("type") != props["type"]["const"]:
            continue
        if set(obj) - set(props):
            return False
        if any(k not in obj for k in alt["required"]):
            return False
        for k, spec in props.items():
            if k == "type" or k not in obj:
                continue
            val = obj[k]
            t = spec.get("type")
            if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
                return False
            if t == "number":
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    return False
                try:
                    if not math.isfinite(val):
                        return False
                except OverflowError:
                    return False
            if t == "string" and (not isinstance(val, str) or len(val) > spec.get("maxLength", 10**9)):
                return False
        return True
    return False
