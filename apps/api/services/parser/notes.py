"""AI Notes restructuring service.

Takes content tree nodes and restructures them based on user preferences.
Supports formats: bullet_point, table, mind_map, step_by_step, summary.

Phase 0-B: LLM-based restructuring with Mermaid/KaTeX output.
Reference: textbook_quality project for content generation pipeline.
"""

from services.llm.router import get_llm_client

# Format-specific system prompts for note restructuring
FORMAT_PROMPTS = {
    "bullet_point": """Restructure the following content into clear, hierarchical bullet points.
Use markdown formatting:
- Main points as top-level bullets
- Sub-points indented with proper hierarchy
- Bold key terms
- Keep it concise but comprehensive""",

    "table": """Restructure the following content into markdown tables where appropriate.
- Use tables for comparisons, definitions, properties, or any structured data
- Include a brief intro paragraph before each table
- Bold headers and key terms""",

    "mind_map": """Restructure the following content as a Mermaid.js mind map diagram.
Output valid Mermaid mindmap syntax that can be rendered.
Example format:
```mermaid
mindmap
  root((Topic))
    Branch 1
      Sub-point
      Sub-point
    Branch 2
      Sub-point
```
Also include a brief text summary after the diagram.""",

    "step_by_step": """Restructure the following content as numbered steps or a process flow.
- Number each step clearly
- Include prerequisites if any
- Use arrows (→) to show flow/dependencies
- For complex processes, include a Mermaid flowchart:
```mermaid
graph TD
    A[Step 1] --> B[Step 2]
```""",

    "summary": """Create a concise summary of the following content.
- Start with a one-sentence overview
- List 3-5 key takeaways
- Include any important formulas using KaTeX: $formula$
- End with connections to other concepts if applicable""",
}

VISUAL_PROMPT = """You are an expert at choosing the best visual representation for educational content.
When the content includes:
- Processes/workflows → use Mermaid flowchart (graph TD)
- Comparisons → use markdown tables
- Hierarchies/taxonomies → use Mermaid mindmap
- Mathematical formulas → use KaTeX ($...$) or ($$...$$)
- Timelines → use Mermaid timeline
- Relationships → use Mermaid class diagram

Always output valid Mermaid syntax wrapped in ```mermaid blocks.
Always output valid KaTeX wrapped in $ or $$ delimiters."""


async def restructure_notes(
    content: str,
    title: str,
    note_format: str = "bullet_point",
    visual_preference: str = "auto",
) -> str:
    """Restructure content based on user preference format.

    Args:
        content: Raw content text from content tree node
        title: Section title for context
        note_format: One of bullet_point, table, mind_map, step_by_step, summary
        visual_preference: "auto" lets AI decide, or specify mermaid/katex/table/none

    Returns:
        Restructured content as markdown string (may include Mermaid/KaTeX)
    """
    format_prompt = FORMAT_PROMPTS.get(note_format, FORMAT_PROMPTS["bullet_point"])

    system_prompt = f"""You are OpenTutor, an AI study assistant that restructures learning materials.

{format_prompt}

{VISUAL_PROMPT if visual_preference == "auto" else ""}

Important:
- Preserve all important information from the original
- Use proper markdown formatting
- Include Mermaid diagrams and KaTeX formulas where they add value
- Do NOT add information not present in the original content"""

    user_message = f"## {title}\n\n{content}"

    client = get_llm_client()
    result, _ = await client.chat(system_prompt, user_message)
    return result


async def restructure_content_tree(
    nodes: list[dict],
    note_format: str = "bullet_point",
    visual_preference: str = "auto",
) -> list[dict]:
    """Restructure all content tree nodes.

    Args:
        nodes: List of content tree node dicts with 'title' and 'content'
        note_format: User's preferred format
        visual_preference: Visual rendering preference

    Returns:
        Same nodes with 'ai_content' field added
    """
    results = []
    for node in nodes:
        if node.get("content"):
            ai_content = await restructure_notes(
                node["content"],
                node["title"],
                note_format,
                visual_preference,
            )
            results.append({**node, "ai_content": ai_content})
        else:
            results.append(node)
    return results
