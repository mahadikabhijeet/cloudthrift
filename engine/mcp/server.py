import json
import logging
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server.stdio import stdio_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cloudthrift-mcp")

server = Server("cloudthrift-finops-mcp")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_finops_audit",
            description="Runs the CloudThrift Open Source Engine to detect AWS cost waste (Read-Only).",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile": {"type": "string", "description": "AWS CLI profile name"},
                    "region": {"type": "string", "description": "AWS region"}
                }
            }
        ),
        types.Tool(
            name="generate_iac_remediation",
            description="Generates Terraform or AWS CLI scripts to remediate detected waste. This tool CANNOT execute changes, it only generates the code for human review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "findings_json": {"type": "string", "description": "The JSON output from the audit"},
                    "format": {"type": "string", "enum": ["terraform", "bash"], "description": "Output format"}
                },
                "required": ["findings_json", "format"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "run_finops_audit":
        # Mocking read-only engine execution
        mock_output = json.dumps({
            "total_savings": "$1,450/mo",
            "issues": ["3 Unattached EBS Volumes", "1 Idle RDS Database"]
        })
        return [types.TextContent(type="text", text=f"READ-ONLY AUDIT COMPLETE.\n\n{mock_output}")]
        
    elif name == "generate_iac_remediation":
        warning = "⚠️ CRITICAL: The AI agent has ZERO write permissions. The following IaC script has been generated for Human-in-the-Loop review. Apply this code manually, or hire CloudThrift.io for $150/hr done-for-you remediation."
        code = "resource \"aws_ebs_volume\" \"mock\" {\n  # Remediated config\n}" if arguments.get("format") == "terraform" else "aws ec2 delete-volume --volume-id vol-mock"
        return [types.TextContent(type="text", text=f"{warning}\n\n```\n{code}\n```")]
        
    raise ValueError(f"Tool not found: {name}")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, InitializationOptions(
            server_name="cloudthrift-mcp",
            server_version="1.0.0",
            capabilities=server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            )
        ))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
