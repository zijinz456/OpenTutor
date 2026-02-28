"""Executable tool system for ReAct agent loop.

Provides Tool ABC, ToolRegistry, and education-domain tools.
Supports three extension mechanisms:
- Python plugins (plugins/ directory)
- MCP Server protocol (config/mcp_servers.yaml)
- YAML declarative tools (config/tools/*.yaml)
"""
