"""
Autonomous Incident Agent - Core orchestration logic.

This module contains the main agent class that orchestrates incident analysis
by delegating investigation tasks to Claude using available MCP tools.
Claude has full autonomy to decide which tools to use and how to investigate.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

from anthropic import Anthropic
from mcp_client import MCPClient

logger = logging.getLogger(__name__)

class AutonomousIncidentAgent:
    """
    Autonomous agent that analyzes infrastructure incidents using Claude and MCP servers.
    
    The agent provides Claude with access to Grafana and OpsGenie tools, allowing
    Claude to autonomously decide how to investigate incidents and what data to collect.
    """
    
    def __init__(self):
        """
        Initialize the agent with MCP client and Anthropic API.
        
        Environment variables required:
        - ANTHROPIC_API_KEY: API key for Claude
        - GRAFANA_MCP_URL: URL for Grafana MCP server 
        - OPSGENIE_API_KEY: API key for OpsGenie
        """
        self.anthropic = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
        self.mcp_client = MCPClient()
        
        # MCP server configurations
        self.mcp_servers = {
            "grafana": {
                "url": os.environ.get('GRAFANA_MCP_URL', 'http://grafana-mcp-server:8080'),
                "name": "Grafana MCP Server",
                "description": "Provides access to Grafana metrics, logs, and dashboards"
            },
            "opsgenie": {
                "url": os.environ.get('OPSGENIE_MCP_URL', 'http://opsgenie-mcp-server:8080'),
                "name": "OpsGenie MCP Server", 
                "description": "Provides access to OpsGenie alerts and ticket management"
            }
        }
        
        self.initialized = False
        self.available_tools = []

    async def initialize(self):
        """
        Initialize connections to all MCP servers and discover available tools.
        This should be called once during application startup.
        """
        logger.info("Initializing Autonomous Incident Agent...")
        
        try:
            # Connect to all MCP servers
            for server_name, config in self.mcp_servers.items():
                logger.info(f"Connecting to {config['name']} at {config['url']}")
                await self.mcp_client.connect_server(server_name, config['url'])
            
            # Discover all available tools from connected servers
            await self._discover_tools()
            
            self.initialized = True
            logger.info(f"Agent initialized successfully with {len(self.available_tools)} tools available")
            
        except Exception as e:
            logger.error(f"Failed to initialize agent: {str(e)}")
            raise e

    async def _discover_tools(self):
        """
        Discover and catalog all available tools from connected MCP servers.
        This creates the tool definitions that will be provided to Claude.
        """
        self.available_tools = []
        
        for server_name in self.mcp_servers.keys():
            try:
                # Get tools from each server
                server_tools = await self.mcp_client.list_tools(server_name)
                
                # Add server context to each tool
                for tool in server_tools:
                    tool['server'] = server_name
                    tool['server_name'] = self.mcp_servers[server_name]['name']
                    self.available_tools.append(tool)
                
                logger.info(f"Discovered {len(server_tools)} tools from {server_name}")
                
            except Exception as e:
                logger.error(f"Failed to discover tools from {server_name}: {str(e)}")
                # Continue with other servers even if one fails
                continue

    async def analyze_incident(self, alert_data: Dict[str, Any]) -> str:
        """
        Analyze an incident by providing Claude with full autonomy to investigate.
        
        Claude receives the alert information and access to all available tools,
        then decides independently how to investigate and analyze the incident.
        
        Args:
            alert_data: Alert information from OpsGenie webhook
            
        Returns:
            str: Comprehensive analysis result from Claude
        """
        if not self.initialized:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        
        alert_id = alert_data.get('alertId', 'unknown')
        logger.info(f"Starting autonomous analysis for alert: {alert_id}")
        
        try:
            # Create the investigation prompt for Claude
            investigation_prompt = self._create_investigation_prompt(alert_data)
            
            # Start conversation with Claude, providing all available tools
            messages = [
                {
                    "role": "user",
                    "content": investigation_prompt
                }
            ]
            
            # Let Claude investigate autonomously using available tools
            analysis_result = await self._conduct_autonomous_investigation(messages)
            
            # Update OpsGenie ticket with the analysis
            await self.update_opsgenie_ticket(alert_id, analysis_result)
            
            logger.info(f"Analysis completed for alert: {alert_id}")
            return analysis_result
            
        except Exception as e:
            logger.error(f"Error analyzing incident {alert_id}: {str(e)}")
            raise e

    def _create_investigation_prompt(self, alert_data: Dict[str, Any]) -> str:
        """
        Create the initial investigation prompt that gives Claude full context
        and autonomy to investigate the incident.
        
        Args:
            alert_data: Alert information from OpsGenie
            
        Returns:
            str: Formatted prompt for Claude
        """
        prompt = f"""
You are an expert DevOps engineer analyzing a critical infrastructure incident. You have been given full access to monitoring tools and must conduct a thorough investigation.

**INCIDENT DETAILS:**
- Alert ID: {alert_data.get('alertId', 'N/A')}
- Affected Entity: {alert_data.get('entity', 'N/A')}
- Alert Message: {alert_data.get('message', 'N/A')}
- Description: {alert_data.get('description', 'N/A')}
- Priority: {alert_data.get('priority', 'N/A')}
- Source: {alert_data.get('source', 'N/A')}
- Tags: {', '.join(alert_data.get('tags', []))}
- Created At: {alert_data.get('createdAt', 'N/A')}

**YOUR MISSION:**
Conduct a comprehensive investigation to determine the root cause and provide actionable recommendations. You have complete autonomy to:

1. **Explore Grafana** - Search dashboards, query metrics, analyze logs, investigate datasources
2. **Examine patterns** - Look for correlations, anomalies, and trends
3. **Cross-reference data** - Combine multiple data sources for deeper insights
4. **Research context** - Understand the infrastructure setup and dependencies

**INVESTIGATION STRATEGY:**
- Start by exploring relevant dashboards and datasources
- Query specific metrics related to the alert (CPU, memory, network, disk, etc.)
- Examine logs for error patterns and anomalies
- Look for correlations with other systems or recent changes
- Consider both immediate and underlying causes

**EXPECTED DELIVERABLE:**
Provide a comprehensive analysis report with:

## 🔍 **ROOT CAUSE ANALYSIS**
- Primary cause of the incident
- Contributing factors
- Timeline of events

## 📊 **IMPACT ASSESSMENT**
- Affected systems and services
- Severity and scope of impact
- Business impact estimation

## 🛠️ **IMMEDIATE ACTIONS**
- Step-by-step resolution procedures
- Priority order of actions
- Required resources or permissions

## 📋 **RECOMMENDATIONS**
- Long-term prevention measures
- Monitoring improvements
- Infrastructure optimizations

## 🚨 **ESCALATION CRITERIA**
- When to escalate
- Who to involve
- Additional resources needed

Begin your investigation now. Use all available tools as needed and be thorough in your analysis.
"""
        return prompt

    async def _conduct_autonomous_investigation(self, messages: List[Dict]) -> str:
        """
        Conduct the investigation by allowing Claude to use tools autonomously.
        This handles the conversation loop where Claude can call multiple tools
        and continue investigating based on what it discovers.
        
        Args:
            messages: Conversation history with Claude
            
        Returns:
            str: Final analysis result
        """
        max_iterations = 20  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Investigation iteration {iteration}")
            
            try:
                # Send message to Claude with available tools
                response = await self.anthropic.messages.create(
                    model="claude-3-sonnet-20240229",
                    max_tokens=4000,
                    messages=messages,
                    tools=self._format_tools_for_claude(),
                    tool_choice="auto"
                )
                
                # Add Claude's response to conversation
                messages.append({
                    "role": "assistant", 
                    "content": response.content
                })
                
                # Check if Claude wants to use tools
                if response.stop_reason == "tool_use":
                    # Execute the tool calls Claude requested
                    tool_results = await self._execute_tool_calls(response.content)
                    
                    # Add tool results to conversation
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
                    
                    # Continue the conversation loop
                    continue
                else:
                    # Claude provided final analysis without using more tools
                    final_response = response.content[0].text if response.content else "Analysis completed"
                    logger.info(f"Investigation completed in {iteration} iterations")
                    return final_response
                    
            except Exception as e:
                logger.error(f"Error in investigation iteration {iteration}: {str(e)}")
                # Try to continue with next iteration unless it's a critical error
                if iteration >= 3:  # Fail after a few retries
                    raise e
                continue
        
        logger.warning(f"Investigation reached maximum iterations ({max_iterations})")
        return "Analysis completed (reached iteration limit)"

    def _format_tools_for_claude(self) -> List[Dict]:
        """
        Format the available MCP tools for Claude's tool calling interface.
        
        Returns:
            List[Dict]: Tool definitions in Claude's expected format
        """
        claude_tools = []
        
        for tool in self.available_tools:
            claude_tool = {
                "name": f"{tool['server']}_{tool['name']}",  # Prefix with server name
                "description": f"[{tool['server_name']}] {tool['description']}",
                "input_schema": tool.get('inputSchema', {})
            }
            claude_tools.append(claude_tool)
        
        return claude_tools

    async def _execute_tool_calls(self, content: List[Any]) -> str:
        """
        Execute the tool calls requested by Claude and format the results.
        
        Args:
            content: Claude's response content containing tool use blocks
            
        Returns:
            str: Formatted tool results to send back to Claude
        """
        results = []
        
        for content_block in content:
            if content_block.type == "tool_use":
                tool_name = content_block.name
                tool_input = content_block.input
                tool_use_id = content_block.id
                
                try:
                    # Parse server and tool name
                    server_name, actual_tool_name = tool_name.split('_', 1)
                    
                    # Execute the tool via MCP client
                    result = await self.mcp_client.call_tool(
                        server_name, 
                        actual_tool_name, 
                        tool_input
                    )
                    
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(result, indent=2)
                    })
                    
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    results.append({
                        "type": "tool_result", 
                        "tool_use_id": tool_use_id,
                        "content": f"Error executing tool: {str(e)}"
                    })
        
        return json.dumps(results, indent=2)

    async def update_opsgenie_ticket(self, alert_id: str, analysis: str):
        """
        Update the OpsGenie ticket with the analysis results.
        
        Args:
            alert_id: OpsGenie alert ID
            analysis: Analysis results from Claude
        """
        try:
            # Format the analysis note for OpsGenie
            formatted_note = f"""
🤖 **AUTONOMOUS AI ANALYSIS**

{analysis}

---
*Analysis generated automatically at {datetime.now().isoformat()}*
*Powered by Claude AI + Grafana Integration*
"""
            
            # Use OpsGenie MCP server to add the note
            await self.mcp_client.call_tool(
                "opsgenie",
                "add_note",
                {
                    "alert_id": alert_id,
                    "note": formatted_note
                }
            )
            
            logger.info(f"Successfully updated OpsGenie ticket: {alert_id}")
            
        except Exception as e:
            logger.error(f"Failed to update OpsGenie ticket {alert_id}: {str(e)}")
            raise e

    async def check_health(self) -> Dict[str, Any]:
        """
        Check health status of the agent and all MCP server connections.
        
        Returns:
            Dict: Health status information
        """
        health_status = {
            "healthy": True,
            "servers": {}
        }
        
        for server_name, config in self.mcp_servers.items():
            try:
                # Try to ping the MCP server
                tools = await self.mcp_client.list_tools(server_name)
                health_status["servers"][server_name] = {
                    "status": "healthy",
                    "url": config["url"],
                    "tools_count": len(tools)
                }
            except Exception as e:
                health_status["healthy"] = False
                health_status["servers"][server_name] = {
                    "status": "unhealthy",
                    "url": config["url"],
                    "error": str(e)
                }
        
        return health_status

    async def shutdown(self):
        """
        Clean shutdown of all MCP connections and resources.
        """
        logger.info("Shutting down Autonomous Incident Agent...")
        
        try:
            await self.mcp_client.disconnect_all()
            logger.info("All MCP connections closed")
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
        
        self.initialized = False