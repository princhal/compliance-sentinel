---
name: ws-agent-orchestration
description: Multi-agent orchestration patterns for AI agents and subagents working in concert.
source: wshobson-agents/plugins/agent-orchestration
imported: 2026-05-08
---

# ws-agent-orchestration

Multi-agent orchestration patterns for AI agents and subagents working in concert.

This plugin was imported without a structured `skills/` directory. The reference content lives in:

- `./agents/` &mdash; per-agent system prompts that describe how to act in this domain.
- `./commands/` &mdash; slash commands defined for the plugin.

When this skill is triggered, read the relevant `agents/*.md` file matching the task and follow its instructions. `agents/` files are the source of truth.
