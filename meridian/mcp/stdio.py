"""`python -m meridian.mcp.stdio <market|analytics|portfolio>` - run one MCP server over stdio."""
import sys

from .servers import build_server

if __name__ == "__main__":
    build_server(sys.argv[1]).serve_stdio()
