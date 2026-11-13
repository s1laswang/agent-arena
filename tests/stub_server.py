from mcp.server.mcpserver import MCPServer as FastMCP

m = FastMCP("stub")


@m.tool()
def my_tickets() -> str:
    return "[]"


@m.tool()
def end_turn() -> str:
    return "ok"


m.run()
