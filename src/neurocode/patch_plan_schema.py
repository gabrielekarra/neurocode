from __future__ import annotations

"""JSON schema for PatchPlanBundle used in LLM roundtrips."""

# Draft-07 style schema kept as a Python dict to avoid runtime jsonschema dependency.
PATCH_PLAN_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "NeuroCode PatchPlanBundle",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version",
        "engine_version",
        "repo_root",
        "file",
        "module",
        "fix",
        "target",
        "operations",
    ],
    "properties": {
        "version": {"type": "integer"},
        "engine_version": {"type": "string"},
        "repo_root": {"type": "string"},
        "file": {"type": "string"},
        "module": {"type": "string"},
        "fix": {"type": "string"},
        "related_files": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
        },
        "call_graph_neighbors": {
            "type": "object",
            "additionalProperties": False,
            "required": ["callers", "callees"],
            "properties": {
                "target": {"type": ["string", "null"]},
                "callers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["symbol", "module", "file", "lineno"],
                        "properties": {
                            "symbol": {"type": "string"},
                            "module": {"type": "string"},
                            "file": {"type": "string"},
                            "lineno": {"type": "integer", "minimum": 1},
                        },
                    },
                },
                "callees": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["symbol", "module", "file", "lineno"],
                        "properties": {
                            "symbol": {"type": "string"},
                            "module": {"type": "string"},
                            "file": {"type": "string"},
                            "lineno": {"type": "integer", "minimum": 1},
                        },
                    },
                },
            },
        },
        "source_slices": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["file", "text"],
                "properties": {
                    "file": {"type": "string"},
                    "text": {"type": "string"},
                    "truncated": {"type": "boolean"},
                },
            },
        },
        "truncation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "applied": {"type": "boolean"},
                "reason": {"type": "string"},
                "functions_included": {"type": "integer", "minimum": 0},
            },
        },
        "target": {
            "type": "object",
            "additionalProperties": False,
            "required": ["symbol", "kind", "lineno"],
            "properties": {
                "symbol": {"type": "string"},
                "kind": {"type": "string"},
                "lineno": {"type": "integer", "minimum": 1},
            },
        },
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "op",
                    "enabled",
                    "file",
                    "symbol",
                    "lineno",
                    "end_lineno",
                    "description",
                    "code",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": [
                            "insert_before",
                            "insert_after",
                            "replace_range",
                            "append_to_function",
                        ],
                    },
                    "enabled": {"type": "boolean"},
                    "file": {"type": "string"},
                    "symbol": {"type": "string"},
                    "lineno": {"type": "integer", "minimum": 1},
                    "end_lineno": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                    },
                    "description": {"type": "string"},
                    "code": {"type": "string"},
                },
            },
        },
    },
}

__all__ = ["PATCH_PLAN_SCHEMA"]
