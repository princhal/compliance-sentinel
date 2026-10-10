---
name: ws-code-documentation
description: Code-level documentation: docstrings, inline comments, API docs generation, code-comment quality.
source: wshobson-agents/plugins/code-documentation
imported: 2026-05-08
---

# ws-code-documentation

Code-level documentation: docstrings, inline comments, API docs generation, code-comment quality.

This plugin was imported without a structured `skills/` directory. The reference content lives in:

- `./agents/` &mdash; per-agent system prompts that describe how to act in this domain.
- `./commands/` &mdash; slash commands defined for the plugin.

When this skill is triggered, read the relevant `agents/*.md` file matching the task and follow its instructions. `agents/` files are the source of truth.
