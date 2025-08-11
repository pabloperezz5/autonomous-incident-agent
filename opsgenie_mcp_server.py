"""
OpsGenie MCP Server implementation.

This module implements an MCP server that provides tools for interacting
with OpsGenie API, including adding notes to alerts, updating alert status,
and retrieving alert information.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OpsGenieMCPServer:
    """
    MCP Server implementation for OpsGenie integration.
    
    Provides tools for interacting with OpsGenie alerts and incidents,
    following the Model Context Protocol specification.
    """
    
    def __init__(self, api_key: str):
        """
        Initialize OpsGenie MCP server.
        
        Args:
            api_key: OpsGenie API key for authentication
        """
        self.api_key = api_key
        self.base_url = "https://api.opsgenie.com/v2"
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Server metadata
        self.server_info = {
            "name": "opsgenie-mcp-server",
            "version": "1.0.0",
            "description": "MCP server for OpsGenie integration"
        }
        
        # Define available tools
        self.tools = [
            {
                "name": "add_note",
                "description": "Add a note to an OpsGenie alert",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "alert_id": {
                            "type": "string",
                            "description": "The ID of the alert to add note to"
                        },
                        "note": {
                            "type": "string", 
                            "description": "The note content to add to the alert"
                        }
                    },
                    "required": ["alert_id", "note"]
                }
            },
            {
                "name": "get_alert",
                "description": "Get details of a specific OpsGenie alert",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "alert_id": {
                            "type": "string",
                            "description": "The ID of the alert to retrieve"
                        }
                    },
                    "required": ["alert_id"]
                }
            },
            {
                "name": "update_alert_priority",
                "description": "Update the priority of an OpsGenie alert",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "alert_id": {
                            "type": "string",
                            "description": "The ID of the alert to update"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["P1", "P2", "P3", "P4", "P5"],
                            "description": "New priority level for the alert"
                        }
                    },
                    "required": ["alert_id", "priority"]
                }
            },
            {
                "name": "add_tags",
                "description": "Add tags to an OpsGenie alert",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "alert_id": {
                            "type": "string",
                            "description": "The ID of the alert to add tags to"
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of tags to add to the alert"
                        }
                    },
                    "required": ["alert_id", "tags"]
                }
            }
        ]

    async def _ensure_session(self):
        """Ensure aiohttp session is created with proper configuration."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            headers = {
                "Authorization": f"GenieKey {self.api_key}",
                "Content-Type": "application/json"
            }
            
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers=headers
            )

    async def handle_mcp_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming MCP protocol requests.
        
        Args:
            request: MCP request following JSON-RPC 2.0 format
            
        Returns:
            Dict: MCP response in JSON-RPC 2.0 format
        """
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {})
        
        try:
            if method == "initialize":
                return await self._handle_initialize(request_id, params)
            elif method == "tools/list":
                return await self._handle_tools_list(request_id)
            elif method == "tools/call":
                return await self._handle_tools_call(request_id, params)
            else:
                return self._create_error_response(
                    request_id, 
                    -32601, 
                    f"Method not found: {method}"
                )
                
        except Exception as e:
            logger.error(f"Error handling MCP request: {str(e)}")
            return self._create_error_response(
                request_id,
                -32603,
                f"Internal error: {str(e)}"
            )

    async def _handle_initialize(self, request_id: int, params: Dict) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": self.server_info
            }
        }

    async def _handle_tools_list(self, request_id: int) -> Dict[str, Any]:
        """Handle tools/list request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": self.tools
            }
        }

    async def _handle_tools_call(self, request_id: int, params: Dict) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        # Route to appropriate tool handler
        if tool_name == "add_note":
            result = await self._add_note(arguments)
        elif tool_name == "get_alert":
            result = await self._get_alert(arguments)
        elif tool_name == "update_alert_priority":
            result = await self._update_alert_priority(arguments)
        elif tool_name == "add_tags":
            result = await self._add_tags(arguments)
        else:
            raise Exception(f"Unknown tool: {tool_name}")
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }
        }

    async def _add_note(self, arguments: Dict) -> Dict[str, Any]:
        """
        Add a note to an OpsGenie alert.
        
        Args:
            arguments: Tool arguments containing alert_id and note
            
        Returns:
            Dict: API response from OpsGenie
        """
        await self._ensure_session()
        
        alert_id = arguments["alert_id"]
        note = arguments["note"]
        
        url = f"{self.base_url}/alerts/{alert_id}/notes"
        payload = {
            "note": note,
            "user": "AI Analysis Agent"
        }
        
        logger.info(f"Adding note to alert {alert_id}")
        
        async with self.session.post(url, json=payload) as response:
            if response.status not in [200, 201, 202]:
                error_text = await response.text()
                raise Exception(f"OpsGenie API error: {response.status} - {error_text}")
            
            result = await response.json()
            logger.info(f"Successfully added note to alert {alert_id}")
            return result

    async def _get_alert(self, arguments: Dict) -> Dict[str, Any]:
        """
        Get details of a specific OpsGenie alert.
        
        Args:
            arguments: Tool arguments containing alert_id
            
        Returns:
            Dict: Alert details from OpsGenie
        """
        await self._ensure_session()
        
        alert_id = arguments["alert_id"]
        url = f"{self.base_url}/alerts/{alert_id}"
        
        logger.info(f"Retrieving alert details for {alert_id}")
        
        async with self.session.get(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"OpsGenie API error: {response.status} - {error_text}")
            
            result = await response.json()
            logger.info(f"Successfully retrieved alert {alert_id}")
            return result

    async def _update_alert_priority(self, arguments: Dict) -> Dict[str, Any]:
        """
        Update the priority of an OpsGenie alert.
        
        Args:
            arguments: Tool arguments containing alert_id and priority
            
        Returns:
            Dict: API response from OpsGenie
        """
        await self._ensure_session()
        
        alert_id = arguments["alert_id"]
        priority = arguments["priority"]
        
        url = f"{self.base_url}/alerts/{alert_id}/priority"
        payload = {"priority": priority}
        
        logger.info(f"Updating priority of alert {alert_id} to {priority}")
        
        async with self.session.put(url, json=payload) as response:
            if response.status not in [200, 202]:
                error_text = await response.text()
                raise Exception(f"OpsGenie API error: {response.status} - {error_text}")
            
            result = await response.json()
            logger.info(f"Successfully updated priority of alert {alert_id}")
            return result

    async def _add_tags(self, arguments: Dict) -> Dict[str, Any]:
        """
        Add tags to an OpsGenie alert.
        
        Args:
            arguments: Tool arguments containing alert_id and tags
            
        Returns:
            Dict: API response from OpsGenie
        """
        await self._ensure_session()
        
        alert_id = arguments["alert_id"]
        tags = arguments["tags"]
        
        url = f"{self.base_url}/alerts/{alert_id}/tags"
        payload = {"tags": tags}
        
        logger.info(f"Adding tags {tags} to alert {alert_id}")
        
        async with self.session.post(url, json=payload) as response:
            if response.status not in [200, 202]:
                error_text = await response.text()
                raise Exception(f"OpsGenie API error: {response.status} - {error_text}")
            
            result = await response.json()
            logger.info(f"Successfully added tags to alert {alert_id}")
            return result

    def _create_error_response(self, request_id: int, code: int, message: str) -> Dict[str, Any]:
        """Create a JSON-RPC 2.0 error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }

    async def cleanup(self):
        """Clean up resources."""
        if self.session and not self.session.closed:
            await self.session.close()

# FastAPI application for serving the MCP server
app = FastAPI(
    title="OpsGenie MCP Server",
    description="Model Context Protocol server for OpsGenie integration",
    version="1.0.0"
)

# Global server instance
mcp_server: Optional[OpsGenieMCPServer] = None

@app.on_event("startup")
async def startup_event():
    """Initialize the MCP server on startup."""
    global mcp_server
    
    api_key = os.environ.get('OPSGENIE_API_KEY')
    if not api_key:
        raise RuntimeError("OPSGENIE_API_KEY environment variable is required")
    
    mcp_server = OpsGenieMCPServer(api_key)
    logger.info("OpsGenie MCP Server initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown."""
    global mcp_server
    if mcp_server:
        await mcp_server.cleanup()

@app.post("/mcp")
async def handle_mcp_request(request: Dict[str, Any]):
    """Handle MCP protocol requests."""
    global mcp_server
    
    if not mcp_server:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    
    try:
        response = await mcp_server.handle_mcp_request(request)
        return JSONResponse(content=response)
    except Exception as e:
        logger.error(f"Error handling MCP request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "OpsGenie MCP Server",
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        "opsgenie_mcp_server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        log_level="info"
    )