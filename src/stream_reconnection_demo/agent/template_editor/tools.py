"""Shared tools for the template editor agents.

All tools use ToolRuntime + Command to atomically read and update
the graph state. Both FE-tool and BE-only agents share these tools.

ToolRuntime provides both state access and tool_call_id, which is
required for building the ToolMessage that Command.update must include.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from stream_reconnection_demo.agent.template.analysis_graph import build_analysis_graph
from stream_reconnection_demo.agent.template.quality_graph import build_quality_graph
from stream_reconnection_demo.core.llm import DEFAULT_MODEL

logger = logging.getLogger(__name__)

# ── Component defaults ───────────────────────────────────────────────

COMPONENT_DEFAULTS: dict[str, dict] = {
    "header": {
        "content": "Your Header Title",
        "styles": {
            "background-color": "#333",
            "color": "#fff",
            "padding": "20px",
            "text-align": "center",
            "font-size": "24px",
        },
    },
    "body": {
        "content": "Your body text goes here. Write something compelling.",
        "styles": {
            "padding": "20px",
            "font-size": "14px",
            "line-height": "1.6",
            "color": "#333",
        },
    },
    "footer": {
        "content": "\u00a9 2026 Your Company. All rights reserved.",
        "styles": {
            "background-color": "#f5f5f5",
            "color": "#999",
            "padding": "20px",
            "text-align": "center",
            "font-size": "12px",
        },
    },
    "cta": {
        "content": "Click Here",
        "styles": {
            "background-color": "#007bff",
            "color": "#fff",
            "padding": "14px 28px",
            "text-align": "center",
            "border-radius": "4px",
        },
    },
    "image": {
        "content": "https://via.placeholder.com/600x200",
        "styles": {"text-align": "center", "padding": "0"},
    },
    "divider": {
        "content": "",
        "styles": {"padding": "10px 20px"},
    },
    "spacer": {
        "content": "",
        "styles": {"height": "20px"},
    },
    "social_links": {
        "content": "Follow us: Twitter | LinkedIn | GitHub",
        "styles": {
            "text-align": "center",
            "padding": "20px",
            "font-size": "14px",
        },
    },
    "text_block": {
        "content": "A rich text content block for detailed information.",
        "styles": {
            "padding": "20px",
            "font-size": "14px",
            "line-height": "1.6",
            "color": "#333",
        },
    },
    "columns": {
        "content": "Column 1 content | Column 2 content",
        "styles": {"padding": "20px"},
    },
}

VALID_SECTION_TYPES = set(COMPONENT_DEFAULTS.keys())


def _default_template() -> dict:
    return {
        "sections": [],
        "html": "",
        "css": "",
        "subject": "",
        "preview_text": "",
        "version": 0,
    }


# ── HTML assembly ────────────────────────────────────────────────────


def assemble_html(template_dict: dict) -> dict:
    """Build a full HTML email document from the sections array."""
    sections = template_dict.get("sections", [])
    if not sections:
        template_dict["html"] = ""
        return template_dict

    parts: list[str] = []
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
        elif s_type == "divider":
            parts.append(
                f'<tr><td id="{s_id}" style="padding:10px 20px;">'
                f'<hr style="border:none;border-top:1px solid #e0e0e0;margin:0;" />'
                f"</td></tr>"
            )
        elif s_type == "spacer":
            height = s.get("styles", {}).get("height", "20px")
            parts.append(
                f'<tr><td id="{s_id}" style="padding:0;height:{height};'
                f'line-height:{height};font-size:1px;">&nbsp;</td></tr>'
            )
        elif s_type == "social_links":
            parts.append(
                f'<tr><td id="{s_id}" style="text-align:center;padding:20px;'
                f'font-family:Arial,sans-serif;font-size:14px;">{content}</td></tr>'
            )
        elif s_type == "text_block":
            parts.append(
                f'<tr><td id="{s_id}" style="padding:20px;font-family:Arial,sans-serif;'
                f'font-size:14px;line-height:1.6;color:#333;">{content}</td></tr>'
            )
        elif s_type == "columns":
            cols = content.split("|") if "|" in content else [content, content]
            left = cols[0].strip()
            right = cols[1].strip() if len(cols) > 1 else ""
            parts.append(
                f'<tr><td id="{s_id}" style="padding:20px;">'
                f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
                f'<td width="50%" style="padding-right:10px;font-family:Arial,sans-serif;'
                f'font-size:14px;vertical-align:top;">{left}</td>'
                f'<td width="50%" style="padding-left:10px;font-family:Arial,sans-serif;'
                f'font-size:14px;vertical-align:top;">{right}</td>'
                f"</tr></table></td></tr>"
            )
        else:  # body or unknown
            parts.append(
                f'<tr><td id="{s_id}" style="padding:20px;font-family:Arial,sans-serif;'
                f'font-size:14px;line-height:1.6;color:#333;">{content}</td></tr>'
            )

    body = "\n".join(parts)
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#f5f5f5;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;max-width:600px;width:100%;">'
        f"{body}"
        "</table></td></tr></table></body></html>"
    )
    template_dict["html"] = html
    return template_dict


# ── Section manipulation tools ───────────────────────────────────────


@tool
def add_section(
    section_type: str,
    content: str,
    runtime: ToolRuntime,
    position: int = -1,
) -> Command:
    """Add a section to the email template.

    Args:
        section_type: One of header, body, footer, cta, image, divider,
                      spacer, social_links, text_block, columns.
        content: HTML content for the section.
        position: Index to insert at. -1 appends to end.
    """
    state = runtime.state
    template = dict(state.get("template") or _default_template())
    sections = list(template.get("sections", []))
    new_id = f"s{len(sections) + 1}"
    defaults = COMPONENT_DEFAULTS.get(section_type, COMPONENT_DEFAULTS["body"])
    new_section = {
        "id": new_id,
        "type": section_type,
        "content": content or defaults["content"],
        "styles": dict(defaults.get("styles", {})),
    }
    if 0 <= position < len(sections):
        sections.insert(position, new_section)
    else:
        sections.append(new_section)
    template["sections"] = sections
    template = assemble_html(template)
    msg = ToolMessage(content=f"Added {section_type} section '{new_id}'", tool_call_id=runtime.tool_call_id)
    return Command(update={"template": template, "version": state.get("version", 0) + 1, "messages": [msg]})


@tool
def update_section(
    section_id: str,
    runtime: ToolRuntime,
    content: str | None = None,
    styles: str | None = None,
) -> Command:
    """Update an existing section's content or styles.

    Args:
        section_id: The id of the section to update (e.g. "s1").
        content: New HTML content (optional).
        styles: JSON string of style overrides (optional).
    """
    state = runtime.state
    template = dict(state.get("template") or _default_template())
    sections = list(template.get("sections", []))
    found = False
    for i, s in enumerate(sections):
        if s.get("id") == section_id:
            s = dict(s)
            if content is not None:
                s["content"] = content
            if styles is not None:
                try:
                    s["styles"] = {**s.get("styles", {}), **json.loads(styles)}
                except json.JSONDecodeError:
                    pass
            sections[i] = s
            found = True
            break
    msg = ToolMessage(
        content=f"Updated section '{section_id}'" if found else f"Section '{section_id}' not found",
        tool_call_id=runtime.tool_call_id,
    )
    if not found:
        return Command(update={"messages": [msg]})
    template["sections"] = sections
    template = assemble_html(template)
    return Command(update={"template": template, "version": state.get("version", 0) + 1, "messages": [msg]})


@tool
def remove_section(
    section_id: str,
    runtime: ToolRuntime,
) -> Command:
    """Remove a section from the template.

    Args:
        section_id: The id of the section to remove.
    """
    state = runtime.state
    template = dict(state.get("template") or _default_template())
    sections = [s for s in template.get("sections", []) if s.get("id") != section_id]
    template["sections"] = sections
    template = assemble_html(template)
    msg = ToolMessage(content=f"Removed section '{section_id}'", tool_call_id=runtime.tool_call_id)
    return Command(update={"template": template, "version": state.get("version", 0) + 1, "messages": [msg]})


@tool
def reorder_sections(
    section_ids: list[str],
    runtime: ToolRuntime,
) -> Command:
    """Reorder template sections.

    Args:
        section_ids: Ordered list of section ids defining the new order.
    """
    state = runtime.state
    template = dict(state.get("template") or _default_template())
    by_id = {s["id"]: s for s in template.get("sections", [])}
    reordered = [by_id[sid] for sid in section_ids if sid in by_id]
    remaining = [s for s in template.get("sections", []) if s["id"] not in set(section_ids)]
    template["sections"] = reordered + remaining
    template = assemble_html(template)
    msg = ToolMessage(content="Sections reordered", tool_call_id=runtime.tool_call_id)
    return Command(update={"template": template, "version": state.get("version", 0) + 1, "messages": [msg]})


@tool
def update_metadata(
    runtime: ToolRuntime,
    subject: str | None = None,
    preview_text: str | None = None,
) -> Command:
    """Update the email template metadata (subject line and preview text).

    Args:
        subject: New subject line (optional).
        preview_text: New preview text snippet (optional).
    """
    state = runtime.state
    template = dict(state.get("template") or _default_template())
    if subject is not None:
        template["subject"] = subject
    if preview_text is not None:
        template["preview_text"] = preview_text
    msg = ToolMessage(content="Metadata updated", tool_call_id=runtime.tool_call_id)
    return Command(update={"template": template, "version": state.get("version", 0) + 1, "messages": [msg]})


@tool
def finalize_html(
    runtime: ToolRuntime,
) -> Command:
    """Rebuild the full HTML from sections. Call this after making section changes."""
    state = runtime.state
    template = dict(state.get("template") or _default_template())
    template = assemble_html(template)
    msg = ToolMessage(content="HTML finalized", tool_call_id=runtime.tool_call_id)
    return Command(update={"template": template, "messages": [msg]})


# ── Sub-graph wrapper tools ──────────────────────────────────────────


@tool
async def analyze_template(
    runtime: ToolRuntime,
) -> Command:
    """Run a design analysis on the email template.

    Checks subject line, color scheme, typography, and HTML structure.
    Agent decides when to invoke this based on user request.
    """
    state = runtime.state
    template = state.get("template")
    if not template:
        msg = ToolMessage(content="No template to analyze", tool_call_id=runtime.tool_call_id)
        return Command(update={"messages": [msg]})

    analysis_graph = build_analysis_graph(model=DEFAULT_MODEL).compile()
    result = await analysis_graph.ainvoke({"template": template}, config=runtime.config)

    msg = ToolMessage(content="Analysis complete", tool_call_id=runtime.tool_call_id)
    return Command(
        update={
            "analyses": result.get("analyses", []),
            "overall_assessment": result.get("overall_assessment"),
            "needs_improvement": result.get("needs_improvement", False),
            "messages": [msg],
        }
    )


@tool
async def quality_check(
    runtime: ToolRuntime,
) -> Command:
    """Run a content quality check on the email template.

    Checks spelling, tone consistency, and CTA effectiveness.
    Agent decides when to invoke this based on user request.
    """
    state = runtime.state
    template = state.get("template")
    if not template:
        msg = ToolMessage(content="No template to check", tool_call_id=runtime.tool_call_id)
        return Command(update={"messages": [msg]})

    quality_graph = build_quality_graph(model=DEFAULT_MODEL).compile()
    result = await quality_graph.ainvoke({"template": template}, config=runtime.config)

    msg = ToolMessage(content="Quality check complete", tool_call_id=runtime.tool_call_id)
    return Command(
        update={
            "spelling_report": result.get("spelling_report"),
            "tone_report": result.get("tone_report"),
            "cta_report": result.get("cta_report"),
            "quality_summary": result.get("quality_summary", ""),
            "messages": [msg],
        }
    )


# ── Tool registry ───────────────────────────────────────────────────

ALL_TOOLS = [
    add_section,
    update_section,
    remove_section,
    reorder_sections,
    update_metadata,
    finalize_html,
    analyze_template,
    quality_check,
]
