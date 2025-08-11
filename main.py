"""
Main application entry point for the autonomous incident analysis agent.
This FastAPI application receives webhooks from OpsGenie and orchestrates
the incident analysis using Claude and MCP servers.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from autonomous_incident_agent import AutonomousIncidentAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Autonomous Incident Analysis Agent",
    description="AI-powered incident analysis system integrating OpsGenie and Grafana",
    version="1.0.0"
)

# Global agent instance (initialized on startup)
agent: AutonomousIncidentAgent = None

@app.on_event("startup")
async def startup_event():
    """
    Initialize the agent and MCP connections on application startup.
    This ensures all MCP servers are ready before processing webhooks.
    """
    global agent
    logger.info("Initializing Autonomous Incident Agent...")
    
    try:
        agent = AutonomousIncidentAgent()
        await agent.initialize()
        logger.info("Agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize agent: {str(e)}")
        raise e

@app.on_event("shutdown")
async def shutdown_event():
    """
    Clean shutdown of MCP connections and resources.
    """
    global agent
    if agent:
        logger.info("Shutting down agent...")
        await agent.shutdown()
        logger.info("Agent shutdown complete")

@app.post("/webhook/opsgenie")
async def handle_opsgenie_webhook(request: Request):
    """
    Main webhook endpoint for OpsGenie alerts.
    
    Expected payload structure from OpsGenie:
    {
        "alert": {
            "alertId": "string",
            "message": "string", 
            "description": "string",
            "entity": "string",
            "source": "string",
            "tags": ["string"],
            "priority": "string",
            "createdAt": "timestamp"
        }
    }
    
    Returns:
        JSONResponse: Processing status and basic info
    """
    try:
        # Parse webhook payload
        body = await request.body()
        webhook_data = json.loads(body.decode('utf-8'))
        
        # Validate webhook structure
        if 'alert' not in webhook_data:
            logger.warning("Received webhook without alert data")
            raise HTTPException(
                status_code=400, 
                detail="Invalid webhook: missing alert data"
            )
        
        alert_data = webhook_data['alert']
        alert_id = alert_data.get('alertId', 'unknown')
        
        logger.info(f"Processing OpsGenie alert: {alert_id}")
        
        # Validate required alert fields
        required_fields = ['alertId', 'message', 'entity']
        missing_fields = [field for field in required_fields if field not in alert_data]
        
        if missing_fields:
            logger.warning(f"Alert {alert_id} missing required fields: {missing_fields}")
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields: {missing_fields}"
            )
        
        # Process the incident asynchronously
        # We return immediately to acknowledge the webhook
        asyncio.create_task(process_incident_async(alert_data))
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "alert_id": alert_id,
                "message": "Incident analysis started",
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except json.JSONDecodeError:
        logger.error("Failed to parse webhook JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def process_incident_async(alert_data: Dict[str, Any]):
    """
    Asynchronously process the incident using the autonomous agent.
    This function runs in the background to avoid blocking the webhook response.
    
    Args:
        alert_data: Alert information from OpsGenie webhook
    """
    alert_id = alert_data.get('alertId', 'unknown')
    
    try:
        logger.info(f"Starting async analysis for alert: {alert_id}")
        
        # Use the global agent instance to analyze the incident
        analysis_result = await agent.analyze_incident(alert_data)
        
        logger.info(f"Analysis completed for alert: {alert_id}")
        logger.debug(f"Analysis result preview: {analysis_result[:200]}...")
        
    except Exception as e:
        logger.error(f"Error in async incident processing for alert {alert_id}: {str(e)}")
        
        # Try to notify OpsGenie about the analysis failure
        try:
            await agent.update_opsgenie_ticket(
                alert_id,
                f"❌ **Automatic Analysis Failed**\n\nError: {str(e)}\n\nTimestamp: {datetime.now().isoformat()}"
            )
        except Exception as notify_error:
            logger.error(f"Failed to notify OpsGenie about analysis error: {str(notify_error)}")

@app.get("/health")
async def health_check():
    """
    Health check endpoint for Kubernetes liveness/readiness probes.
    
    Returns:
        JSONResponse: Health status of the application and MCP connections
    """
    try:
        # Check if agent is initialized and healthy
        if agent is None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "reason": "Agent not initialized"
                }
            )
        
        # Check MCP server connections
        health_status = await agent.check_health()
        
        if health_status["healthy"]:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "mcp_servers": health_status["servers"]
                }
            )
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "reason": "MCP server connection issues",
                    "details": health_status["servers"]
                }
            )
            
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "reason": str(e)
            }
        )

@app.get("/")
async def root():
    """
    Root endpoint providing basic API information.
    """
    return {
        "service": "Autonomous Incident Analysis Agent",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "webhook": "/webhook/opsgenie",
            "health": "/health"
        }
    }

if __name__ == "__main__":
    # Run the application with uvicorn
    # In production, this should be handled by the container orchestration
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="info"
    )