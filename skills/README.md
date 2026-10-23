# skills/ — Jarvis-learned skills (self-learning loop)

Each file is one skill the agent proposed and sir approved:

```python
"""One-line description shown to the model."""
SPEC = {
    "name": "skill_name",          # ^[a-z][a-z0-9_]{2,40}$
    "description": "What it does.",
    "parameters": {                # JSON schema, all args arrive as strings
        "type": "object",
        "properties": {"arg": {"type": "string"}},
        "required": ["arg"],
    },
}
def run(**kwargs) -> str:
    return "..."                   # returned text goes back to the model
```

Skills load fresh on every chat turn (the MCP server restarts per turn),
so a newly approved skill is usable immediately in the next message.
