"""Dropdown Agent 1 (`agent_1_without_kc`): Smart Gemini 4 Argon WITHOUT Knowledge Studio."""

from __future__ import annotations

from google.adk.apps import App

from app.builders import build_without_kc_agent

root_agent = build_without_kc_agent("agent_1_without_kc")
app = App(root_agent=root_agent, name="agent_1_without_kc")
