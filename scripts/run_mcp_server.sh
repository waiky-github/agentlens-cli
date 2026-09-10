#!/bin/bash
# Wrapper for hermes mcp add: avoids hermes CLI eating the "-m" flag.
exec /home/agentuser/agentlens-venv/bin/python -m agentlens_cli.mcp_server "$@"
