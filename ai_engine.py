import pandas as pd
from openai import OpenAI
import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_kpi_block(df: pd.DataFrame) -> str:
    """Render the KPI data as a compact text table for the prompt."""
    lines = []
    for _, row in df.iterrows():
        actual  = row.get("Latest Actual")
        target  = row.get(config.KPI_COL_TARGET)
        comment = str(row.get(config.ACTUAL_COL_COMMENT, "") or "").strip()

        if pd.notna(actual) and pd.notna(target) and target != 0:
            variance_pct = ((actual - target) / target) * 100
            variance_str = f"{variance_pct:+.1f}%"
            status = row.get("RAG Status", "Unknown")
        else:
            variance_str = "N/A"
            status = "No Data"

        actual_str = f"{actual:.2f}" if pd.notna(actual) else "—"
        target_str = f"{target:.2f}" if pd.notna(target) else "—"

        line = (
            f"- {row[config.KPI_COL_NAME]}: "
            f"Actual={actual_str}, Target={target_str}, "
            f"Variance={variance_str}, Status={status}"
        )
        if comment:
            line += f'\n  HoD comment: "{comment}"'
        lines.append(line)

    return "\n".join(lines)


_SYSTEM_PROMPT = """\
You are a chief of staff briefing a CEO. You write in tight, direct prose — \
no filler, no hedging, no bullet-point padding. Every sentence must carry information.

Your job when analysing KPI data:
1. Identify what is actually going wrong (not just what is red).
2. Use the HoD comments as evidence — but interrogate them. \
   If a comment does not credibly explain the miss, say so explicitly.
3. Flag inconsistencies: a green KPI with a worrying comment, \
   a red KPI with a dismissive comment, or a pattern across multiple KPIs \
   that the HoD has not acknowledged.
4. Recommend specific actions — who should do what, not generic advice.
5. If the data is genuinely healthy, say so in one sentence and stop.

Output format — three sections, each a short paragraph, no headers or bullets:
  SITUATION: What the numbers actually show.
  SCRUTINY: Whether the explanations hold up.
  ACTION: What needs to happen next and who owns it.
"""


def _build_user_prompt(department: str, kpi_block: str) -> str:
    return (
        f"Department: {department}\n\n"
        f"KPI Performance this week:\n{kpi_block}\n\n"
        "Provide your executive assessment."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_insights(department: str, enriched_df: pd.DataFrame) -> str:
    """
    Generate an executive AI insight narrative for a department's KPI data.

    Parameters
    ----------
    department   : Department name (used for context in the prompt).
    enriched_df  : DataFrame from enrich_with_rag(), must contain columns:
                   KPI Name, Target, Latest Actual, RAG Status,
                   and optionally ACTUAL_COL_COMMENT.

    Returns
    -------
    str  Plain-text insight with three sections: SITUATION, SCRUTINY, ACTION.
         Returns an error string (never raises) so the UI can display it safely.
    """
    if enriched_df.empty:
        return "No KPI data available for this department."

    kpi_block = _build_kpi_block(enriched_df)

    try:
        response = _client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system",  "content": _SYSTEM_PROMPT},
                {"role": "user",    "content": _build_user_prompt(department, kpi_block)},
            ],
            temperature=0.4,
            max_tokens=600,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"Could not generate insights: {e}"
