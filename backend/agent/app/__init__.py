"""ADK agent package.

`adk web` / `adk api_server` load an agent directory by importing the package
and reading `<package>.agent.root_agent`, so the submodule is imported here.
"""

from . import agent

__all__ = ["agent"]
