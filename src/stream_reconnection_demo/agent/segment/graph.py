import asyncio
import re

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from stream_reconnection_demo.agent.segment.state import SegmentAgentState
from stream_reconnection_demo.schemas.segment import Segment

SYSTEM_PROMPT = """\
You are a user segmentation expert. Given a natural language description, \
generate a structured segment definition.

## Available Field Types

- **User properties**: age, gender, country, city, language, signup_date, \
plan_type, account_status
- **Behavioral events**: purchase_count, last_purchase_date, total_spent, \
login_count, last_login_date, page_views, session_duration
- **Engagement**: email_opened, email_clicked, push_notification_opened, \
app_opens, feature_used
- **Custom attributes**: any user-defined property (use descriptive snake_case names)

## Available Operators

- **Comparison**: equals, not_equals, greater_than, less_than, \
greater_than_or_equal, less_than_or_equal
- **String**: contains, not_contains, starts_with, ends_with
- **Temporal**: within_last, before, after, between
- **Existence**: is_set, is_not_set
- **List**: in, not_in

## Rules

1. Generate a concise, descriptive segment name.
2. Write a clear human-readable description of who this segment targets.
3. Group conditions logically using AND/OR groups.
4. Use the most specific field and operator that matches the user's intent.
5. For temporal values, use clear formats like "30 days", "2024-01-01", etc.
6. If the query implies multiple independent criteria, use separate condition \
groups joined appropriately.
7. Set estimated_scope to a brief description of the expected audience size \
or reach (e.g., "Users matching all activity and location criteria").
"""

# Catalog of available fields for validation
AVAILABLE_FIELDS = {
    "age", "gender", "country", "city", "language", "signup_date",
    "plan_type", "account_status",
    "purchase_count", "last_purchase_date", "total_spent",
    "login_count", "last_login_date", "page_views", "session_duration",
    "email_opened", "email_clicked", "push_notification_opened",
    "app_opens", "feature_used",
}

# Common keyword-to-field mappings
KEYWORD_FIELD_MAP = {
    "us": "country", "usa": "country", "united states": "country",
    "uk": "country", "canada": "country", "india": "country",
    "purchase": "purchase_count", "bought": "purchase_count",
    "spent": "total_spent", "spend": "total_spent",
    "signup": "signup_date", "signed up": "signup_date", "registered": "signup_date",
    "login": "login_count", "logged in": "last_login_date",
    "active": "last_login_date", "inactive": "last_login_date",
    "email": "email_opened", "clicked": "email_clicked",
    "age": "age", "old": "age", "young": "age",
    "plan": "plan_type", "premium": "plan_type", "free": "plan_type",
    "views": "page_views", "session": "session_duration",
    "app": "app_opens", "feature": "feature_used",
    "gender": "gender", "male": "gender", "female": "gender",
    "city": "city", "language": "language",
}


async def analyze_requirements(state: SegmentAgentState) -> dict:
    """Node 1: Analyze the user's query and extract key requirements."""
    await asyncio.sleep(8)

    query = ""
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content"):
            query = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            query = msg.get("content", "")
            break

    # Extract keywords and build a requirements summary
    words = re.findall(r'\b\w+\b', query.lower())
    detected_intents = []
    for word in words:
        if word in KEYWORD_FIELD_MAP:
            field = KEYWORD_FIELD_MAP[word]
            detected_intents.append(f"{word} -> {field}")

    requirements = (
        f"Query: {query}\n"
        f"Detected intents: {', '.join(detected_intents) or 'general segmentation'}\n"
        f"Keywords: {', '.join(words[:10])}"
    )

    return {
        "current_node": "analyze_requirements",
        "requirements": requirements,
    }


async def extract_entities(state: SegmentAgentState) -> dict:
    """Node 2: Identify entity types from the requirements."""
    await asyncio.sleep(8)

    requirements = state.get("requirements", "")
    entities = []

    entity_categories = {
        "location": ["country", "city"],
        "temporal": ["signup_date", "last_purchase_date", "last_login_date"],
        "behavioral": ["purchase_count", "total_spent", "login_count", "page_views"],
        "demographic": ["age", "gender", "language"],
        "engagement": ["email_opened", "email_clicked", "app_opens", "feature_used"],
        "account": ["plan_type", "account_status"],
    }

    for category, fields in entity_categories.items():
        for field in fields:
            if field in requirements.lower():
                entities.append({"category": category, "field": field})

    if not entities:
        entities = [
            {"category": "location", "field": "country"},
            {"category": "behavioral", "field": "purchase_count"},
        ]

    return {
        "current_node": "extract_entities",
        "entities": entities,
    }


async def validate_fields(state: SegmentAgentState) -> dict:
    """Node 3: Validate detected fields against the available catalog."""
    await asyncio.sleep(8)

    requirements = state.get("requirements", "")
    # Extract field names from the requirements
    validated = []
    for keyword, field in KEYWORD_FIELD_MAP.items():
        if keyword in requirements.lower():
            if field not in validated:
                validated.append(field)

    # If no fields detected, use a default set
    if not validated:
        validated = ["country", "signup_date", "purchase_count"]

    return {
        "current_node": "validate_fields",
        "validated_fields": validated,
    }


async def map_operators(state: SegmentAgentState) -> dict:
    """Node 4: Select appropriate operators for each validated field."""
    await asyncio.sleep(8)

    validated_fields = state.get("validated_fields", [])
    operator_mappings = []

    for field in validated_fields:
        if field in ("country", "city", "language", "gender", "plan_type", "account_status"):
            operator_mappings.append({
                "field": field, "operator": "equals", "type": "categorical",
            })
        elif field in ("signup_date", "last_purchase_date", "last_login_date"):
            operator_mappings.append({
                "field": field, "operator": "within_last", "type": "temporal",
            })
        elif field in ("purchase_count", "total_spent", "login_count",
                        "page_views", "session_duration", "age"):
            operator_mappings.append({
                "field": field, "operator": "greater_than", "type": "numeric",
            })
        else:
            operator_mappings.append({
                "field": field, "operator": "is_set", "type": "existence",
            })

    return {
        "current_node": "map_operators",
        "operator_mappings": operator_mappings,
    }


async def generate_conditions(state: SegmentAgentState) -> dict:
    """Node 5: Generate draft condition structures from validated fields."""
    await asyncio.sleep(10)

    operator_mappings = state.get("operator_mappings", [])
    validated_fields = state.get("validated_fields", [])
    conditions_draft = []

    if operator_mappings:
        for mapping in operator_mappings:
            conditions_draft.append({
                "field": mapping["field"],
                "operator": mapping["operator"],
                "value_hint": f"{mapping['type']} match",
            })
    else:
        for field in validated_fields:
            if field in ("country", "city", "language", "gender", "plan_type", "account_status"):
                conditions_draft.append({"field": field, "operator": "equals", "value_hint": "exact match"})
            elif field in ("signup_date", "last_purchase_date", "last_login_date"):
                conditions_draft.append({"field": field, "operator": "within_last", "value_hint": "temporal range"})
            elif field in ("purchase_count", "total_spent", "login_count", "page_views", "session_duration", "age"):
                conditions_draft.append({"field": field, "operator": "greater_than", "value_hint": "numeric threshold"})
            else:
                conditions_draft.append({"field": field, "operator": "is_set", "value_hint": "existence check"})

    return {
        "current_node": "generate_conditions",
        "conditions_draft": conditions_draft,
    }


async def optimize_conditions(state: SegmentAgentState) -> dict:
    """Node 6: Simplify and deduplicate conditions."""
    await asyncio.sleep(10)

    conditions_draft = state.get("conditions_draft", [])
    seen_fields = set()
    optimized = []

    for cond in conditions_draft:
        field = cond.get("field", "")
        if field not in seen_fields:
            seen_fields.add(field)
            optimized.append({**cond, "optimized": True})

    return {
        "current_node": "optimize_conditions",
        "optimized_conditions": optimized,
    }


async def estimate_scope(state: SegmentAgentState) -> dict:
    """Node 7: Estimate audience size and reach."""
    await asyncio.sleep(8)

    optimized_conditions = state.get("optimized_conditions", [])
    num_conditions = len(optimized_conditions)

    if num_conditions <= 1:
        estimate = "Broad audience — minimal filtering applied"
    elif num_conditions <= 3:
        estimate = "Moderate audience — balanced between reach and specificity"
    else:
        estimate = "Narrow audience — highly targeted with multiple filters"

    return {
        "current_node": "estimate_scope",
        "scope_estimate": f"{estimate} ({num_conditions} conditions active)",
    }


def _build_segment_node(llm: ChatAnthropic):
    """Node 4: Use LLM to generate the final structured segment."""
    structured_llm = llm.with_structured_output(Segment)

    async def build_segment(state: SegmentAgentState) -> dict:
        query = ""
        for msg in reversed(state["messages"]):
            if hasattr(msg, "content"):
                query = msg.content
                break
            elif isinstance(msg, dict) and msg.get("role") == "user":
                query = msg.get("content", "")
                break

        requirements = state.get("requirements", "")
        entities = state.get("entities", [])
        validated_fields = state.get("validated_fields", [])
        operator_mappings = state.get("operator_mappings", [])
        conditions_draft = state.get("conditions_draft", [])
        optimized_conditions = state.get("optimized_conditions", [])
        scope_estimate = state.get("scope_estimate", "")

        enriched_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"## Pre-analyzed Context\n"
            f"Requirements: {requirements}\n"
            f"Entities: {entities}\n"
            f"Validated fields: {', '.join(validated_fields)}\n"
            f"Operator mappings: {operator_mappings}\n"
            f"Draft conditions: {conditions_draft}\n"
            f"Optimized conditions: {optimized_conditions}\n"
            f"Scope estimate: {scope_estimate}\n\n"
            f"Use these pre-analyzed results to generate the final segment."
        )

        try:
            messages = [
                SystemMessage(content=enriched_prompt),
                HumanMessage(content=query),
            ]
            result = await structured_llm.ainvoke(messages)
            return {
                "current_node": "build_segment",
                "segment": result,
                "error": None,
            }
        except Exception as e:
            return {
                "current_node": "build_segment",
                "segment": None,
                "error": str(e),
            }

    return build_segment


def build_segment_graph(model: str = "claude-sonnet-4-20250514"):
    """Build and compile the 8-node segment generation graph."""
    llm = ChatAnthropic(model=model)

    graph = StateGraph(SegmentAgentState)
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("validate_fields", validate_fields)
    graph.add_node("map_operators", map_operators)
    graph.add_node("generate_conditions", generate_conditions)
    graph.add_node("optimize_conditions", optimize_conditions)
    graph.add_node("estimate_scope", estimate_scope)
    graph.add_node("build_segment", _build_segment_node(llm))

    graph.add_edge(START, "analyze_requirements")
    graph.add_edge("analyze_requirements", "extract_entities")
    graph.add_edge("extract_entities", "validate_fields")
    graph.add_edge("validate_fields", "map_operators")
    graph.add_edge("map_operators", "generate_conditions")
    graph.add_edge("generate_conditions", "optimize_conditions")
    graph.add_edge("optimize_conditions", "estimate_scope")
    graph.add_edge("estimate_scope", "build_segment")
    graph.add_edge("build_segment", END)

    return graph.compile()
