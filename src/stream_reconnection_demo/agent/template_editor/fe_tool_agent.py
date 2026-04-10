"""FE-tool agent -- create_react_agent for FE-tools mode.

Same tools as BE-only agent. The difference is in EventAdapter config:
FE-tools mode streams TOOL_CALL events to the frontend, where
useCopilotAction handlers execute them for live canvas updates.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from stream_reconnection_demo.agent.template_editor.state import TemplateEditorState
from stream_reconnection_demo.agent.template_editor.tools import ALL_TOOLS
from stream_reconnection_demo.core.llm import DEFAULT_MODEL, get_llm

SYSTEM_PROMPT = """\
You are an expert email template editor. Help users create and modify \
professional HTML email templates by calling tools.

## CRITICAL RULE
You MUST call exactly ONE tool at a time. NEVER call multiple tools \
in the same response. Wait for each tool result before calling the next. \
This is required because each tool updates shared state.

## Available section types
header, body, footer, cta, image, divider, spacer, social_links, \
text_block, columns.

## Workflow
1. Use add_section to build the template piece by piece — ONE call per response.
2. Use update_section to modify existing sections.
3. Use update_metadata to set subject and preview_text.
4. Use finalize_html to rebuild the full HTML after changes.
5. Optionally use analyze_template or quality_check for reviews.

Each tool call updates the template in real-time on the user's screen. \
Be methodical — add sections one at a time so the user sees progress.

If the user already has sections (from drag-and-drop), work with what \
exists. Use update_section to improve existing content rather than \
removing and re-adding.
"""


def build_fe_tool_agent(checkpointer=None, model: str = DEFAULT_MODEL):
    llm = get_llm(model)
    return create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
        state_schema=TemplateEditorState,
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer or MemorySaver(),
    )
