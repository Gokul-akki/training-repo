from mcp.server.fastmcp import FastMCP, Context
import json
import time
import signal
import sys
import threading
 
from app.logger import (
    get_logger,
    log_server_startup,
    log_server_ready,
    log_server_shutdown,
    log_request_metrics,
    log_server_health,
    setup_mcp_logging,
    create_server_stats
)
from app.middleware import setup_uvicorn_logging
from app.util import extract_links, extract_allowed_links

def on_request(ctx: Context, tool_input: dict):
    logger.info(f"📥 Request received for tool: {tool_input.get('tool')} | Session: {ctx.session_id}")
 
# Server configuration
HOST = "0.0.0.0"
PORT = 5000
mcp = FastMCP("ScraperTool MCP Server", host=HOST, port=PORT, on_request=on_request)
 
# Logger configs
logger = get_logger(__name__)
 
# Test log to ensure logging is working
print("DEBUG: Logger created, testing...", file=sys.stderr)
logger.info("🔥 LOGGER TEST - If you see this, logging is working!")
 
# Track server metrics
server_stats = create_server_stats()
def setup_signal_handlers():
    """Setup graceful shutdown handlers"""
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        log_server_shutdown(logger)
        sys.exit(0)
   
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
 
 
# --- Scraper MCP Tool ---
@mcp.tool()
def scrape_links(start_url: str) -> str:
    """
    Scrape internal links from a website starting at start_url.
    Returns the path to the JSON file and the list of links.
    """
    start_time = time.time()
    tool_name = "scrape_links"
    try:
        logger.info(f"=== TOOL SCRAP LINKS : {tool_name} ===")
        logger.info(f"🔧 TOOL_START | {tool_name} | Input: {start_url} ")
        links = extract_links(start_url, logger)
        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, True, duration)
        if len(links) == 0:
            return "NULL"
        else: 
            return json.dumps({
                "links": links,
                "count": len(links)
            })
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"error": str(e)})
 

# --- ROBOT SCRAPER ---
@mcp.tool()
def scrape_allowed_links(start_url: str) -> str:
    """
    Scrape links from a website starting at start_url, respecting robots.txt rules.
    Returns only the links that are allowed by the site's robots.txt.
    """
    start_time = time.time()
    tool_name = "scrape_allowed_links"
    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | Input: {start_url}")
        
        # Extract the allowed links from the website
        links = extract_allowed_links(start_url, logger)
        
        # Log performance metrics
        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, True, duration)
        
        # Return the list of allowed links as JSON
        return json.dumps({
            "links": links,
            "count": len(links)
        })
    except Exception as e:
        # Log error metrics
        duration = time.time() - start_time
        logger.error(f"TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        
        # Return the error message as JSON
        return json.dumps({"error": str(e)})

# Add health check endpoint for Kubernetes
@mcp.tool()
def health_check() -> str:
    """
    Health check endpoint for monitoring systems
    """
    try:
        logger.info("=== HEALTH CHECK TOOL INVOKED ===")
        uptime = time.time() - server_stats["start_time"]
        health_data = {
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "total_requests": server_stats["total_requests"],
            "success_rate": round(
            (server_stats["successful_requests"] / max(server_stats["total_requests"], 1)) * 100,
            2
            ),
            "timestamp": time.time()
        }
       
        logger.debug(f"Health check requested - {health_data}")
        return json.dumps(health_data)
       
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return json.dumps({"status": "unhealthy", "error": str(e)})

if __name__ == "__main__":
    try:
        # Setup MCP protocol logging
        setup_mcp_logging(logger=logger)
       
        # Setup uvicorn logging filters first
        setup_uvicorn_logging()
       
        # Setup signal handlers
        setup_signal_handlers()
       
        # Log startup information
        log_server_startup(logger, HOST, PORT)
       
        # Start periodic health logging in background
        print("=== RAW STDERR TEST ===", file=sys.__stderr__, flush=True)
        logger.info("Log before the server started running")
        def periodic_health_log():
            time.sleep(60)  # Wait 1 minute before first health log
            while True:
                log_server_health(logger, server_stats)
                time.sleep(300)  # Log health every 5 minutes
       
        health_thread = threading.Thread(target=periodic_health_log, daemon=True)
        health_thread.start()
       
        # Log when server is ready
        log_server_ready(logger)
       
        logger.info("🌐 Starting MCP server with stdio transport")
        logger.info("💡 TIP: Use the health_check tool to monitor server status")
       
        mcp.run(transport="streamable-http")
       
    except Exception as e:
        logger.error(f"FATAL ERROR - Server failed to start: {e}")
        sys.exit(1)
    finally:
        log_server_shutdown(logger)