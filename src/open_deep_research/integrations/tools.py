"""Assemble repository, history, web and MCP tools for the researcher."""
import asyncio
import logging
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from open_deep_research.configuration import Configuration, SearchAPI
from open_deep_research.workflow.state import ResearchComplete
from open_deep_research.integrations.mcp import load_mcp_tools
from open_deep_research.integrations.models import get_config_value
from open_deep_research.integrations.web_search import tavily_search

@tool(description="Strategic reflection tool for research planning")
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"

async def get_search_tool(search_api: SearchAPI):
    """Configure and return search tools based on the specified API provider.
    
    Args:
        search_api: The search API provider to use (Anthropic, OpenAI, Tavily, or None)
        
    Returns:
        List of configured search tool objects for the specified provider
    """
    if search_api == SearchAPI.ANTHROPIC:
        # Anthropic's native web search with usage limits
        return [{
            "type": "web_search_20250305", 
            "name": "web_search", 
            "max_uses": 5
        }]
        
    elif search_api == SearchAPI.OPENAI:
        # OpenAI's web search preview functionality
        return [{"type": "web_search_preview"}]
        
    elif search_api == SearchAPI.TAVILY:
        # Configure Tavily search tool with metadata
        search_tool = tavily_search
        search_tool.metadata = {
            **(search_tool.metadata or {}), 
            "type": "search", 
            "name": "web_search"
        }
        return [search_tool]
        
    elif search_api == SearchAPI.NONE:
        # No search functionality configured
        return []
        
    # Default fallback for unknown search API types
    return []
    
async def get_all_tools(config: RunnableConfig, context=None, history_matches=None):
    """Assemble complete toolkit including research, search, and MCP tools.
    
    Args:
        config: Runtime configuration specifying search API and MCP settings
        
    Returns:
        List of all configured and available tools for research operations
    """
    # Start with core research tools
    tools = [tool(ResearchComplete), think_tool]
    
    # Add configured search tools
    configurable = Configuration.from_runnable_config(config)
    if configurable.repository_path:
        from open_deep_research.repository.tools import code_tools
        tools.extend(await asyncio.to_thread(code_tools, configurable, context))
        from open_deep_research.wiki.tools import wiki_tools
        tools.extend(await asyncio.to_thread(wiki_tools, configurable))
    from open_deep_research.history.service import history_tools
    tools.extend(history_tools(config, history_matches or []))
    if configurable.repository_allow_web:
        search_api = SearchAPI(get_config_value(configurable.search_api))
        tools.extend(await get_search_tool(search_api))
    
    # Track existing tool names to prevent conflicts
    existing_tool_names = {
        tool.name if hasattr(tool, "name") else tool.get("name", "web_search") 
        for tool in tools
    }
    
    # Add MCP tools if configured
    if configurable.mcp_config:
        try:
            tools.extend(await load_mcp_tools(config, existing_tool_names))
        except Exception as error:
            logging.warning("Optional MCP tools unavailable (%s)", type(error).__name__)
    
    return tools
