import pandas as pd
import google.generativeai as genai
import config

# Initialise Gemini client
genai.configure(api_key=config.GEMINI_API_KEY)
_model = genai.GenerativeModel(
    model_name=config.GEMINI_MODEL,
    generation_config=genai.GenerationConfig(
        temperature=0.4,
        max_output_tokens=800,
    ),
)


# =============================================================================
# Prompt builder
# =============================================================================

def _build_kpi_block(df: pd.DataFrame) -> str:
    """Build a structured KPI context block for the prompt."""
    lines = []
    for _, row in df.iterrows():
        name        = row.get(config.KPI_COL_NAME, "Unknown")
        target      = row.get(config.KPI_COL_TARGET)
        target_desc = str(row.get(config.KPI_COL_TARGET_DESC, "") or "").strip()
        mtd         = row.get("MTD Progress")
        gap         = row.get("Gap to Target")
        actual      = row.get("Latest Actual")
        comment     = str(row.get("Latest Comment", "") or "").strip()
        rag         = row.get("RAG Status", "Unknown")
        weekly      = str(row.get(config.KPI_COL_WEEKLY_TRACKED, "")).strip().upper()

        target_str = f"{target:.2f}" if pd.notna(target) else "—"
        actual_str = f"{actual:.2f}" if pd.notna(actual) else "No data"

        line = f"- {name} | Target: {target_str}"
        if target_desc:
            line += f" ({target_desc})"
        line += f" | Status: {rag}"

        if weekly == "YES" and pd.notna(mtd):
            gap_str = f"{gap:+.2f}" if pd.notna(gap) else "—"
            line += f" | MTD Progress: {mtd:.2f} | Gap to Target: {gap_str}"
        else:
            line += f" | Latest Actual: {actual_str}"

        if comment:
            line += f'\n  Comment: "{comment}"'

        lines.append(line)

    return "\n".join(lines)


_SYSTEM_PROMPT = """\
You are a business performance reviewer briefing a senior executive.
Write in tight, direct prose — no filler, no bullet-point padding.
Every sentence must carry information.

For each KPI assess:
1. Is it on track to meet its target? State clearly.
2. Is the gap (if any) recoverable this month? Be specific.
3. Does the HoD comment credibly explain the result? If not, say so.
4. What specific action should be taken and who owns it?

If all KPIs are on track, say so in one sentence and stop.

Output three sections — each a short paragraph, no headers needed:
  SITUATION: What the numbers actually show.
  SCRUTINY: Whether the explanations hold up.
  ACTION: Specific next steps with clear ownership.
"""


def _build_prompt(department: str, kpi_block: str) -> str:
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Department: {department}\n\n"
        f"KPI Performance:\n{kpi_block}\n\n"
        "Provide your assessment."
    )


# =============================================================================
# Public API
# =============================================================================

def generate_insights(department: str, enriched_df: pd.DataFrame) -> str:
    """
    Generate an executive AI narrative for a department's KPI data.
    Never raises — returns an error string on failure so the UI stays safe.
    """
    if enriched_df.empty:
        return "No KPI data available for this department."

    kpi_block = _build_kpi_block(enriched_df)
    prompt    = _build_prompt(department, kpi_block)

    try:
        response = _model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not generate insights: {e}"
