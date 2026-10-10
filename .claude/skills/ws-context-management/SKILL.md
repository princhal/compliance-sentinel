---
name: ws-context-management
description: Context management: state, memory, RAG context windows, agent context budgets.
source: wshobson-agents/plugins/context-management
imported: 2026-05-08
---

# ws-context-management

Context management: state, memory, RAG context windows, agent context budgets.

This plugin was imported without a structured `skills/` directory. The reference content lives in:

- `./agents/` &mdash; per-agent system prompts that describe how to act in this domain.
- `./commands/` &mdash; slash commands defined for the plugin.

When this skill is triggered, read the relevant `agents/*.md` file matching the task and follow its instructions. `agents/` files are the source of truth.
