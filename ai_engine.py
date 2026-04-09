import pandas as pd
from openai import OpenAI
import config
from datetime import date

# =============================================================================
# OpenAI Client Setup
# =============================================================================
_client = OpenAI(api_key=config.OPENAI_API_KEY)

# Lean system prompt — instructs tone and structure without wasting tokens
_SYSTEM_PROMPT = (
    "You are an energetic, straight-talking performance coach briefing a Head of Department. "
    "Be sharp, specific, and motivating — never vague. Use 🟢🟡🔴 to signal KPI health inline. "
    "Write exactly three labelled paragraphs (2-3 sentences each):\n"
    "SITUATION: What the numbers actually show — no fluff.\n"
    "SCRUTINY: Do the comments explain the gaps? Call out weak excuses.\n"
    "ACTION: Concrete improvement steps with clear ownership and urgency.\n"
    "End with one punchy motivational line. Max 180 words total."
)


# =============================================================================
# Prompt builder — abbreviated field names to minimise input tokens
# =============================================================================

def _build_kpi_block(df: pd.DataFrame) -> str:
    """Compact KPI summary — short field labels to reduce token count."""
    lines = []
    for _, row in df.iterrows():
        name    = row.get(config.KPI_COL_NAME, "?")
        target  = row.get(config.KPI_COL_TARGET)
        actual  = row.get("Latest Actual")
        mtd     = row.get("MTD Progress")
        gap     = row.get("Gap to Target")
        comment = str(row.get("Latest Comment", "") or "").strip()
        rag     = row.get("RAG Status", "?")
        weekly  = str(row.get(config.KPI_COL_WEEKLY_TRACKED, "")).strip().upper()

        t_str = f"{target:.2f}" if pd.notna(target) else "—"
        rag_icon = {"Green": "🟢", "Amber": "🟡", "Red": "🔴"}.get(rag, "⚪")

        if weekly == "YES" and pd.notna(mtd):
            g_str = f"{gap:+.2f}" if pd.notna(gap) else "—"
            line = f"{rag_icon} {name} | T:{t_str} MTD:{mtd:.2f} GAP:{g_str}"
        else:
            a_str = f"{actual:.2f}" if pd.notna(actual) else "no data"
            line = f"{rag_icon} {name} | T:{t_str} A:{a_str}"

        if comment:
            line += f' | "{comment}"'
        lines.append(line)

    return "\n".join(lines)


def generate_insights(department: str, enriched_df: pd.DataFrame) -> str:
    """
    Generate a concise, engaging executive narrative for a department's KPIs.
    Never raises — returns a safe error string on failure.
    """
    if enriched_df.empty:
        return "No KPI data available for this department."

    kpi_block = _build_kpi_block(enriched_df)
    user_msg  = (
        f"Dept: {department} | {date.today().strftime('%d %b %Y')}\n"
        f"{kpi_block}"
    )

    try:
        response = _client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.6,
            max_tokens=350,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_str = str(e)

        if "429" in error_str or "rate_limit" in error_str.lower():
            return (
                "📊 **Insights paused** — rate limit hit. Wait a moment and try again."
            )
        if "401" in error_str or "invalid_api_key" in error_str.lower():
            return (
                "❌ **Auth error** — check your OPENAI_API_KEY in Streamlit secrets."
            )
        return f"⚠️ Could not generate insights: {e}"
