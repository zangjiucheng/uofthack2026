### Plan outputted by the LLM from MCP from /plan
```json
{
    "ok": true,
    "plan": {
        "version": "mcp.plan.v1",
        "goal_type": "FIND_OBJECT",
        "steps": [
            {
                "type": "tool",
                "name": "kb_query",
                "args": {
                    "kind": "object",
                    "q": "bottle",
                    "top_k": 3
                },
                "save_as": "bottle_query"
            },
            {
                "type": "if",
                "cond": {
                    "op": "exists",
                    "value": "$bottle_query"
                },
                "then": [
                    {
                        "type": "tool",
                        "name": "kb_last_seen",
                        "args": {
                            "kind": "object",
                            "label": "bottle"
                        },
                        "save_as": "bottle_last_seen"
                    },
                    {
                        "type": "if",
                        "cond": {
                            "op": "exists",
                            "value": "$bottle_last_seen"
                        },
                        "then": [
                            {
                                "type": "tool",
                                "name": "approach_object",
                                "args": {
                                    "object": "bottle"
                                }
                            }
                        ],
                        "else": [
                            {
                                "type": "tool",
                                "name": "update_detic_objects",
                                "args": {
                                    "object_list": "bottle"
                                }
                            },
                            {
                                "type": "tool",
                                "name": "trigger_detic",
                                "args": {}
                            },
                            {
                                "type": "wait",
                                "timeout_s": 10,
                                "refresh": [
                                    {
                                        "type": "tool",
                                        "name": "kb_last_seen",
                                        "args": {
                                            "kind": "object",
                                            "label": "bottle"
                                        },
                                        "save_as": "bottle_last_seen"
                                    }
                                ],
                                "cond": {
                                    "op": "exists",
                                    "value": "$bottle_last_seen"
                                }
                            },
                            {
                                "type": "tool",
                                "name": "approach_object",
                                "args": {
                                    "object": "bottle"
                                }
                            }
                        ]
                    }
                ],
                "else": [
                    {
                        "type": "tool",
                        "name": "notify",
                        "args": {
                            "text": "No bottle found."
                        }
                    }
                ]
            }
        ]
    }
}
```
### Example from mcp_run
```json
{
    "ok": true,
    "run_id": "9a98f5be2abc40bca7b2f532922619f0",
    "plan": {
        "version": "mcp.plan.v1",
        "goal_type": "FIND_OBJECT",
        "steps": [
            {
                "type": "tool",
                "name": "kb_query",
                "args": {
                    "kind": "object",
                    "q": "bottle",
                    "top_k": 3
                },
                "save_as": "bq"
            },
            {
                "type": "if",
                "cond": {
                    "op": "==",
                    "left": "$bq.found",
                    "right": true
                },
                "then": [
                    {
                        "type": "tool",
                        "name": "kb_last_seen",
                        "args": {
                            "kind": "object",
                            "label": "$bq.label"
                        },
                        "save_as": "bls"
                    },
                    {
                        "type": "tool",
                        "name": "approach_object",
                        "args": {
                            "object": "$bq.label"
                        }
                    }
                ],
                "else": [
                    {
                        "type": "tool",
                        "name": "update_detic_objects",
                        "args": {
                            "object_list": "bottle"
                        }
                    },
                    {
                        "type": "tool",
                        "name": "trigger_detic",
                        "args": {}
                    },
                    {
                        "type": "wait",
                        "timeout_s": 10,
                        "cond": {
                            "op": "exists",
                            "value": "$bls.label"
                        },
                        "refresh": [
                            {
                                "type": "tool",
                                "name": "kb_last_seen",
                                "args": {
                                    "kind": "object",
                                    "label": "bottle",
                                    "save_as": "bls"
                                }
                            }
                        ]
                    },
                    {
                        "type": "tool",
                        "name": "approach_object",
                        "args": {
                            "object": "bottle"
                        }
                    }
                ]
            }
        ]
    }
}
```

### From plan
```json
{
    "ok": true,
    "plan": {
        "version": "mcp.plan.v1",
        "goal_type": "ENROLL_PERSON",
        "vars": {
            "person_name": "Bob"
        },
        "steps": [
            {
                "type": "tool",
                "name": "notify",
                "args": {
                    "text": "Starting face enrollment for Bob."
                },
                "on_fail": "continue"
            },
            {
                "type": "tool",
                "name": "set_face_only",
                "args": {
                    "enabled": true
                },
                "on_fail": "continue"
            },
            {
                "type": "tool",
                "name": "start_face_record",
                "args": {
                    "name": "Bob"
                }
            },
            {
                "type": "tool",
                "name": "notify",
                "args": {
                    "text": "Face enrollment for Bob is in progress."
                },
                "on_fail": "continue"
            }
        ]
    }
}
```
### From mcp_run
```json
{
    "ok": true,
    "run_id": "9909214991f04d71876b279da5ec8459",
    "plan": {
        "version": "mcp.plan.v1",
        "goal_type": "ENROLL_PERSON",
        "steps": [
            {
                "type": "tool",
                "name": "notify",
                "args": {
                    "text": "Starting face enrollment for Bob."
                },
                "on_fail": "continue"
            },
            {
                "type": "tool",
                "name": "set_face_only",
                "args": {
                    "enabled": true
                },
                "on_fail": "continue"
            },
            {
                "type": "tool",
                "name": "start_face_record",
                "args": {
                    "name": "Bob"
                }
            },
            {
                "type": "tool",
                "name": "notify",
                "args": {
                    "text": "Face enrollment for Bob has started."
                },
                "on_fail": "continue"
            }
        ]
    }
}
```