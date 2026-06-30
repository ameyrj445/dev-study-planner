# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import logging
import os
import re
import sys
from typing import Any, AsyncGenerator
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.genai import types

from app.config import config

# Logging setup
logger = logging.getLogger(__name__)

# Initialize MCP Toolset (stdio communication with our local database server)
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
        )
    )
)

# Define Specialist Agents
dsa_agent = LlmAgent(
    name="dsa_agent",
    model=config.model,
    instruction="""You are a Data Structures & Algorithms (DSA) Specialist Agent.
Your domain is specifically the Striver A-Z DSA sheet (Arrays, Strings, Linked Lists, Recursion, Binary Search, Trees, Graphs, DP, etc.).
Analyze the user's DSA study request, partition it into study topics/problems, and estimate the number of 25-minute Pomodoro sessions needed for each topic.
Respond in a clean list format with details on topics and difficulty levels.""",
    tools=[mcp_toolset],
)

tech_agent = LlmAgent(
    name="tech_agent",
    model=config.model,
    instruction="""You are a Tech Developer Specialist Agent.
Your domain covers Java, Python, React, Express, Node, FastAPI, Django, Docker, Kubernetes, AWS, GCP, Gen AI, etc.
Analyze the user's technical skills learning request, partition it into structured modules, and estimate the number of 25-minute Pomodoro sessions needed for each topic.
Respond in a clean list format with details on topics and practical exercises.""",
    tools=[mcp_toolset],
)

# Output schemas for Orchestrator
class TopicItem(BaseModel):
    title: str = Field(description="Title of the topic/problem to study (e.g. 'Binary Search - Lower Bound' or 'Docker Compose tutorial')")
    category: str = Field(description="Category of the study topic: 'DSA' or 'Tech'")
    estimated_pomodoros: int = Field(description="Estimated number of 25-minute Pomodoros needed for this topic (must be >= 1).")

class PlannerOutput(BaseModel):
    plan_name: str = Field(description="Descriptive title of the study plan")
    topics: list[TopicItem] = Field(description="List of study topics/problems to register")
    summary: str = Field(description="A friendly summary explaining the logic and goals of the study session")

# Define Orchestrator
orchestrator = LlmAgent(
    name="orchestrator",
    model=config.model,
    instruction="""You are the Study Planner Orchestrator. 
Your goal is to parse user study requests and generate a structured study plan (PlannerOutput).
You MUST delegate specific tasks to the specialized agents:
- Use dsa_agent (via the dsa_agent tool) to get details for any Data Structures & Algorithms request (e.g. Striver DSA sheet).
- Use tech_agent (via the tech_agent tool) to get details for developer skill requests (Java, Python, React, Cloud, DevOps, Gen AI).
Synthesize the recommendations from the specialists into a single, cohesive PlannerOutput.
If the request is simple (e.g., 'start a Pomodoro session' or 'show my tasks'), you can handle it directly or output details, but for study planning, always leverage the specialist sub-agents.
You also have access to the mcp_toolset tools directly to query or modify the task database.""",
    tools=[AgentTool(dsa_agent), AgentTool(tech_agent), mcp_toolset],
    output_schema=PlannerOutput,
    output_key="planner_output",
)

# ── Node 1: Security Checkpoint ──
def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    """Filters PII, prevents prompt injections, and records audit logs."""
    query = ""
    if isinstance(node_input, types.Content):
        parts = node_input.parts
        if parts:
            query = "".join([p.text for p in parts if p.text])
    elif isinstance(node_input, str):
        query = node_input
    elif isinstance(node_input, dict):
        query = str(node_input)

    # 1. PII Redaction
    email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    phone_pattern = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
    
    scrubbed_query = query
    if config.pii_redaction_enabled:
        scrubbed_query = email_pattern.sub("[EMAIL_REDACTED]", scrubbed_query)
        scrubbed_query = phone_pattern.sub("[PHONE_REDACTED]", scrubbed_query)

    # 2. Prompt Injection Detection
    has_injection = False
    if config.injection_detection_enabled:
        injection_keywords = ["ignore previous instructions", "system prompt", "override rules", "bypass security"]
        has_injection = any(kw in query.lower() for kw in injection_keywords)

    # 3. Domain Specific Rules (e.g., prevent malicious software keywords)
    restricted_keywords = ["exploit", "hack", "bypass", "crack", "torrent"]
    has_restricted = any(kw in query.lower() for kw in restricted_keywords)

    # Audit Logging
    audit_log = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": ctx.session.id,
        "has_pii": scrubbed_query != query,
        "has_injection": has_injection,
        "has_restricted": has_restricted,
        "severity": "INFO"
    }

    if has_injection or has_restricted:
        audit_log["severity"] = "CRITICAL"
        logger.error(f"[SECURITY AUDIT] {audit_log}")
        return Event(output="Request blocked by security policy.", route="SECURITY_EVENT")

    if scrubbed_query != query:
        audit_log["severity"] = "WARNING"
        logger.warning(f"[SECURITY AUDIT] {audit_log}")
        return Event(output=scrubbed_query, route="CLEAN")

    logger.info(f"[SECURITY AUDIT] {audit_log}")
    return Event(output=query, route="CLEAN")

# ── Node 2: Security Failure Node ──
def security_failure(node_input: str) -> Event:
    msg = "🚫 Access Denied: The request violated security policies (contains PII, prompt injection, or restricted topics)."
    content = types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    return Event(output=msg, content=content)

# ── Node 3: Study Scheduler Node (HITL) ──
async def schedule_study(ctx: Context, node_input: dict) -> AsyncGenerator[Any, Any]:
    """Presents the study plan and asks the user for confirmation (HITL)."""
    plan_name = node_input.get("plan_name", "Study Plan")
    summary = node_input.get("summary", "")
    topics = node_input.get("topics", [])

    if not ctx.resume_inputs or "approved" not in ctx.resume_inputs:
        msg = f"### 📅 Proposed Study Plan: {plan_name}\n*{summary}*\n\n**Topics Scheduled:**\n"
        for t in topics:
            msg += f"- **[{t.get('category')}]** {t.get('title')} (~{t.get('estimated_pomodoros')} Pomodoros)\n"
        msg += "\nWould you like to approve and save this plan? (Yes / No)"

        yield Event(
            content=types.Content(role="model", parts=[types.Part.from_text(text=msg)]),
            state={"proposed_plan": node_input}
        )
        yield RequestInput(interrupt_id="approved", message="Approve study plan? (yes/no)")
        return

    approval = ctx.resume_inputs.get("approved", "").lower().strip()
    if approval == "yes":
        yield Event(output=node_input, route="approved")
    else:
        yield Event(output="Study plan rejected.", route="rejected")

# ── Node 4: Save Plan Node ──
async def save_plan(ctx: Context, node_input: dict) -> Event:
    """Saves the study plan details using the MCP database helper functions."""
    from app.mcp_server import add_study_todo
    topics = node_input.get("topics", [])
    for t in topics:
        add_study_todo(
            task=t.get("title"),
            category=t.get("category"),
            estimation_pomodoros=t.get("estimated_pomodoros")
        )
    msg = f"✅ Study plan successfully approved and scheduled with {len(topics)} tasks added to your Todo list!"
    content = types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    return Event(output=msg, content=content)

# ── Node 5: Reject Plan Node ──
def reject_plan(node_input: str) -> Event:
    msg = "❌ Study plan rejected. Tell me how you'd like to adjust it!"
    content = types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    return Event(output=msg, content=content)

# Define the workflow graph
# ADK 2.x conditional routing uses 2-tuple format:
#   (source, {route_key: target_node}) for routed edges
#   (source, target) for unconditional edges
workflow_agent = Workflow(
    name="dev_study_planner_workflow",
    edges=[
        ("START", security_checkpoint),
        (security_checkpoint, {"SECURITY_EVENT": security_failure, "CLEAN": orchestrator}),
        (orchestrator, schedule_study),
        (schedule_study, {"approved": save_plan, "rejected": reject_plan}),
    ]
)

# Resumable Application Container
app = App(
    root_agent=workflow_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
