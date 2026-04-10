import json

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from stream_reconnection_demo.agent.template.state import (
    TemplateAgentState,
    TemplateOutput,
)
from stream_reconnection_demo.schemas.template import EmailTemplate
from stream_reconnection_demo.agent.template.analysis_graph import build_analysis_graph
from stream_reconnection_demo.agent.template.quality_graph import build_quality_graph

def _assemble_html(template_dict: dict) -> dict:
    """Build a full HTML document from sections when html is empty."""
    if template_dict.get("html"):
        return template_dict
    sections = template_dict.get("sections", [])
    if not sections:
        return template_dict

    parts = []
    for s in sections:
        content = s.get("content", "")
        s_type = s.get("type", "body")
        s_id = s.get("id", "")

        if s_type == "header":
            parts.append(
                f'<tr><td id="{s_id}" style="background-color:#333;color:#fff;'
                f'padding:20px;text-align:center;font-size:24px;font-family:Arial,sans-serif;">'
                f"{content}</td></tr>"
            )
        elif s_type == "image":
            parts.append(
                f'<tr><td id="{s_id}" style="text-align:center;padding:0;">'
                f'<img src="{content}" alt="" style="width:100%;max-width:600px;display:block;" />'
                f"</td></tr>"
            )
        elif s_type in ("cta", "button"):
            parts.append(
                f'<tr><td id="{s_id}" style="text-align:center;padding:30px;">'
                f'<a href="#" style="background-color:#007bff;color:#fff;'
                f'padding:14px 28px;text-decoration:none;border-radius:4px;'
                f'font-family:Arial,sans-serif;font-size:16px;">{content}</a>'
                f"</td></tr>"
            )
        elif s_type == "footer":
            parts.append(
                f'<tr><td id="{s_id}" style="background-color:#f5f5f5;color:#999;'
                f'padding:20px;text-align:center;font-size:12px;font-family:Arial,sans-serif;">'
                f"{content}</td></tr>"
            )
        else:
            parts.append(
                f'<tr><td id="{s_id}" style="padding:20px;font-family:Arial,sans-serif;'
                f'font-size:14px;line-height:1.6;color:#333;">{content}</td></tr>'
            )

    body = "\n".join(parts)
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#f5f5f5;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;max-width:600px;width:100%;">'
        f"{body}"
        "</table></td></tr></table></body></html>"
    )
    template_dict["html"] = html
    return template_dict


GENERATE_SYSTEM_PROMPT = """\
You are an expert email template designer. Given a user's description, \
generate a professional HTML email template.

## Output Requirements

- A clear, descriptive subject line.
- A short preview text (the snippet shown in email clients).
- Fully self-contained HTML with **inline CSS** (email clients strip \
<style> blocks).
- Use a 600px centered container for maximum compatibility.
- Include sections such as header, body, CTA (call-to-action), and footer.
- Each section must have a unique ``id`` (e.g. "s1", "s2"), a ``type`` \
(header | body | cta | footer | image), and its HTML ``content``.
- Keep the design responsive using percentage-based widths inside the \
600px container.
- Use web-safe fonts (Arial, Helvetica, Georgia, etc.).
"""

MODIFY_SYSTEM_PROMPT = """\
You are an expert email template designer. The user has an existing \
template and wants to modify it.

## Current Template

Subject: {subject}
Sections: {sections}

Full HTML:
{html}

## Instructions

Apply the user's requested changes to the template. Preserve any \
sections not mentioned. Return the complete updated template with all \
sections.
"""


def _build_generate_node(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(EmailTemplate)

    async def generate_template(
        state: TemplateAgentState, config: RunnableConfig
    ) -> dict:
        try:
            query = ""
            for msg in reversed(state["messages"]):
                if hasattr(msg, "content"):
                    query = msg.content
                    break
                elif isinstance(msg, dict) and msg.get("role") == "user":
                    query = msg.get("content", "")
                    break

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Generating template",
                    "progress": 0.1,
                    "details": "Starting LLM generation...",
                },
                config=config,
            )

            messages = [
                SystemMessage(content=GENERATE_SYSTEM_PROMPT),
                HumanMessage(content=query),
            ]
            result = await structured_llm.ainvoke(messages, config=config)

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Template generated",
                    "progress": 1.0,
                    "details": f"Created: {result.subject}",
                },
                config=config,
            )

            template_data = _assemble_html(result.model_dump())
            return {
                "template": template_data,
                "error": None,
                "version": 1,
            }
        except Exception as e:
            return {"template": None, "error": str(e)}

    return generate_template


def _build_modify_node(llm: ChatAnthropic):
    structured_llm = llm.with_structured_output(EmailTemplate)

    async def modify_template(
        state: TemplateAgentState, config: RunnableConfig
    ) -> dict:
        try:
            query = ""
            for msg in reversed(state["messages"]):
                if hasattr(msg, "content"):
                    query = msg.content
                    break
                elif isinstance(msg, dict) and msg.get("role") == "user":
                    query = msg.get("content", "")
                    break

            existing = state.get("template") or {}
            sections_summary = json.dumps(
                [
                    {"id": s.get("id"), "type": s.get("type")}
                    for s in existing.get("sections", [])
                ]
            )

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Modifying template",
                    "progress": 0.1,
                    "details": "Applying changes...",
                },
                config=config,
            )

            system_content = MODIFY_SYSTEM_PROMPT.format(
                subject=existing.get("subject", ""),
                sections=sections_summary,
                html=existing.get("html", ""),
            )

            messages = [
                SystemMessage(content=system_content),
                HumanMessage(content=query),
            ]
            result = await structured_llm.ainvoke(messages, config=config)
            current_version = state.get("version", 0)

            await adispatch_custom_event(
                "activity_snapshot",
                {
                    "title": "Template updated",
                    "progress": 1.0,
                    "details": f"Updated: {result.subject}",
                },
                config=config,
            )

            template_data = _assemble_html(result.model_dump())
            return {
                "template": template_data,
                "error": None,
                "version": current_version + 1,
            }
        except Exception as e:
            return {"template": state.get("template"), "error": str(e)}

    return modify_template


def _build_quality_check_node(model: str):
    """Wrapper node that invokes the quality check subgraph via ainvoke().

    This is Approach B — the subgraph is NOT a native LangGraph subgraph.
    Its internal events are hidden from the parent's astream_events().
    """
    quality_graph = build_quality_graph(model=model).compile()

    async def quality_check_node(
        state: TemplateAgentState, config: RunnableConfig
    ) -> dict:
        template = state.get("template")
        if template is None:
            return {"quality_summary": "No template to check."}

        result = await quality_graph.ainvoke(
            {"template": template},
            config=config,
        )
        return {
            "spelling_report": result.get("spelling_report"),
            "tone_report": result.get("tone_report"),
            "cta_report": result.get("cta_report"),
            "quality_summary": result.get("quality_summary", ""),
        }

    return quality_check_node


def _route_by_state(state: TemplateAgentState) -> str:
    """Route to generate or modify based on whether a template exists."""
    if state.get("template") is None:
        return "generate_template"
    return "modify_template"


def build_template_graph(checkpointer=None, model="claude-sonnet-4-20250514"):
    """Build and compile the template generation/modification graph.

    Includes two subgraphs:
    - analyze_template: HTML analysis via native LangGraph composition (Approach A)
    - quality_check: Content quality via manual ainvoke wrapper (Approach B)
    """
    llm = ChatAnthropic(model=model)

    graph = StateGraph(TemplateAgentState, output=TemplateOutput)

    # Original nodes
    graph.add_node("generate_template", _build_generate_node(llm))
    graph.add_node("modify_template", _build_modify_node(llm))

    # Subgraph A: native composition — compiled graph as a node
    analysis_subgraph = build_analysis_graph(model=model).compile()
    graph.add_node("analyze_template", analysis_subgraph)

    # Subgraph B: wrapper node using ainvoke internally
    graph.add_node("quality_check", _build_quality_check_node(model=model))

    # Routing from START
    graph.add_conditional_edges(START, _route_by_state)

    # generate/modify → analyze → quality_check → END
    graph.add_edge("generate_template", "analyze_template")
    graph.add_edge("modify_template", "analyze_template")
    graph.add_edge("analyze_template", "quality_check")
    graph.add_edge("quality_check", END)

    return graph.compile(checkpointer=checkpointer)
