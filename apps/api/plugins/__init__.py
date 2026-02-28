"""User-extensible plugin directory.

Drop any Python file here that defines a Tool subclass.
On startup, the loader scans this directory and registers every Tool
it finds into the global ToolRegistry.

Example:
    # plugins/my_tool.py
    from services.agent.tools.base import Tool, ToolParameter, ToolResult

    class MyTool(Tool):
        name = "my_tool"
        description = "Does something useful"
        def get_parameters(self):
            return [ToolParameter(name="query", type="string", description="...")]
        async def run(self, parameters, ctx, db):
            return ToolResult(success=True, output="result")
"""
