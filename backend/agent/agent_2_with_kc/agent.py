"""Dropdown Agent 2 (`agent_2_with_kc`): Exact same Gemini 4 Argon POWERED BY Knowledge Studio."""

from __future__ import annotations

from google.adk.apps import App

from app.builders import build_with_kc_agent

root_agent = build_with_kc_agent("agent_2_with_kc")
app = App(root_agent=root_agent, name="agent_2_with_kc")
