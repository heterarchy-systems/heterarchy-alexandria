---
title: Workflow Approval UI
status: implemented
created: 2026-05-26
updated: 2026-05-26
owner: heterarchy-alexandria
scope: langgraph-ui
---

# Workflow Approval UI

LangGraph workflow state now renders with explicit status badges and approval
cards. Each pending backend action gets a checkbox, type badge, and safety
summary before `resume` is called.

GPT OAuth librarian output is rendered separately from the local answer by
splitting the backend `## GPT OAuth Librarian` section into a dedicated panel.
