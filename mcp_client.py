"""
MCP Client implementation for communicating with MCP servers.

This module provides a client for connecting to and communicating with
Model Context Protocol (MCP) servers over HTTP/WebSocket connections.
"""

import asyncio
import json
import logging
import aiohttp
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class MCPClient:
    """
    Client for communicating with MCP (Model Context Protocol) servers.
    
    Supports HTTP-based communication with MCP servers, handling connection
    management, tool discovery, and tool execution.
    """
    
    def __init__(self):
        """Initialize the MCP client with empty server connections."""
        self.connected_servers: Dict[str, Dict] = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self._request_id_counter = 0

    async def _ensure_session(self):
        """Ensure aiohttp session is created and available."""
        if self.session is None or self.session.closed:
            # Configure session with reasonable timeouts
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
            
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "AutonomousIncidentAgent/1.0.0"
                }
            )

    def _get_next_request_id(self) -> int:
        """Generate unique request ID for MCP protocol messages."""
        self._request_id_counter += 1
        return self._request_id_counter

    async def connect_server(self, server_name: str, server_url: str):
        """
        Connect to an MCP server and perform initialization handshake.
        
        Args:
            server_name: Identifier for this server connection
            server_url: Base URL of the MCP server
            
        Raises:
            Exception: If connection or initialization fails
        """
        await self._ensure_session()
        
        logger.info(f"Connecting to MCP server '{server_name}' at {server_url}")
        
        try:
            # Perform MCP initialization handshake
            init_request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "clientInfo": {
                        "name": "autonomous-incident-agent",
                        "version": "1.0.0"
                    }
                }
            }
            
            # Send initialization request
            init_url = urljoin(server_url.rstrip('/') + '/', 'mcp')
            async with self.session.post(init_url, json=init_request) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {await response.text()}")
                
                init_response = await response.json()
                
                if "error" in init_response:
                    raise Exception(f"MCP Error: {init_response['error']}")
                
                # Store server connection info
                self.connected_servers[server_name] = {
                    "url": server_url,
                    "base_mcp_url": init_url,
                    "capabilities": init_response.get("result", {}).get("capabilities", {}),
                    "server_info": init_response.get("result", {}).get("serverInfo", {})
                }
                
                logger.info(f"Successfully connected to MCP server '{server_name}'")
                logger.debug(f"Server capabilities: {self.connected_servers[server_name]['capabilities']}")
                
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{server_name}': {str(e)}")
            raise e

    async def list_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """
        Get list of available tools from a specific MCP server.
        
        Args:
            server_name: Name of the connected server
            
        Returns:
            List[Dict]: List of tool definitions
            
        Raises:
            ValueError: If server is not connected
            Exception: If request fails
        """
        if server_name not in self.connected_servers:
            raise ValueError(f"Server '{server_name}' is not connected")
        
        await self._ensure_session()
        server_info = self.connected_servers[server_name]
        
        try:
            # Create tools/list request
            list_request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "tools/list",
                "params": {}
            }
            
            # Send request to server
            async with self.session.post(server_info["base_mcp_url"], json=list_request) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {await response.text()}")
                
                list_response = await response.json()
                
                if "error" in list_response:
                    raise Exception(f"MCP Error: {list_response['error']}")
                
                tools = list_response.get("result", {}).get("tools", [])
                logger.debug(f"Retrieved {len(tools)} tools from server '{server_name}'")
                
                return tools
                
        except Exception as e:
            logger.error(f"Failed to list tools from server '{server_name}': {str(e)}")
            raise e

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute a tool on a specific MCP server.
        
        Args:
            server_name: Name of the connected server
            tool_name: Name of the tool to execute
            arguments: Tool arguments/parameters
            
        Returns:
            Any: Tool execution result
            
        Raises:
            ValueError: If server is not connected
            Exception: If tool execution fails
        """
        if server_name not in self.connected_servers:
            raise ValueError(f"Server '{server_name}' is not connected")
        
        await self._ensure_session()
        server_info = self.connected_servers[server_name]
        
        logger.debug(f"Calling tool '{tool_name}' on server '{server_name}' with args: {arguments}")
        
        try:
            # Create tools/call request
            call_request = {
                "jsonrpc": "2.0",
                "id": self._get_next_request_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            # Send request to server
            async with self.session.post(server_info["base_mcp_url"], json=call_request) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {await response.text()}")
                
                call_response = await response.json()
                
                if "error" in call_response:
                    raise Exception(f"MCP Tool Error: {call_response['error']}")
                
                result = call_response.get("result", {})
                logger.debug(f"Tool '{tool_name}' executed successfully")
                
                return result
                
        except Exception as e:
            logger.error(f"Failed to call tool '{tool_name}' on server '{server_name}': {str(e)}")
            raise e

    async def ping_server(self, server_name: str) -> bool:
        """
        Check if a server is responding to requests.
        
        Args:
            server_name: Name of the server to ping
            
        Returns:
            bool: True if server is responding, False otherwise
        """
        if server_name not in self.connected_servers:
            return False
        
        try:
            # Try to list tools as a health check
            await self.list_tools(server_name)
            return True
        except Exception as e:
            logger.warning(f"Server '{server_name}' health check failed: {str(e)}")
            return False

    async def get_server_info(self, server_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a connected server.
        
        Args:
            server_name: Name of the connected server
            
        Returns:
            Dict: Server information including capabilities and metadata
            
        Raises:
            ValueError: If server is not connected
        """
        if server_name not in self.connected_servers:
            raise ValueError(f"Server '{server_name}' is not connected")
        
        return self.connected_servers[server_name].copy()

    async def disconnect_server(self, server_name: str):
        """
        Disconnect from a specific MCP server.
        
        Args:
            server_name: Name of the server to disconnect
        """
        if server_name in self.connected_servers:
            logger.info(f"Disconnecting from MCP server '{server_name}'")
            del self.connected_servers[server_name]

    async def disconnect_all(self):
        """
        Disconnect from all MCP servers and close the HTTP session.
        """
        logger.info("Disconnecting from all MCP servers...")
        
        # Clear all server connections
        self.connected_servers.clear()
        
        # Close HTTP session
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("HTTP session closed")

    def list_connected_servers(self) -> List[str]:
        """
        Get list of currently connected server names.
        
        Returns:
            List[str]: Names of connected servers
        """
        return list(self.connected_servers.keys())

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect_all()