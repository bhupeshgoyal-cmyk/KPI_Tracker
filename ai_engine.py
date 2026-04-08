import pandas as pd
import google.generativeai as genai
import config
from datetime import datetime, date
import requests

# =============================================================================
# Gemini API Client Setup
# =============================================================================
# Note: Free tier has quota limits (5 requests/minute, 1500 requests/day)
# For production use, upgrade to a paid plan at https://ai.google.dev
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
# Context helpers
# =============================================================================

def _get_greeting_context() -> str:
    """Generate contextual greeting based on day of week and time."""
    now = datetime.now()
    day_name = now.strftime("%A")
    hour = now.hour
    
    greeting = f"Good {('morning' if hour < 12 else 'afternoon' if hour < 17 else 'evening')}."
    
    # Add day-specific context
    if day_name == "Monday":
        greeting += " Hope you had a restful weekend."
    elif day_name == "Friday":
        greeting += " Great work this week — let's finish strong."
    
    return greeting


def _get_weather_context() -> str:
    """Try to get weather context for Delhi (optional/non-critical)."""
    try:
        # Using Open-Meteo API (free, no key required)
        # Delhi coordinates
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 28.7041,
                "longitude": 77.1025,
                "current": "temperature_2m,weather_code,relative_humidity_2m",
                "timezone": "Asia/Kolkata"
            },
            timeout=3
        )
        if response.status_code == 200:
            data = response.json()
            current = data.get("current", {})
            temp = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            
            if temp is not None:
                # Interpret weather code
                weather_code = current.get("weather_code", 0)
                conditions = {
                    0: "Clear",
                    1: "Partly cloudy",
                    2: "Overcast",
                    3: "Overcast",
                    45: "Foggy",
                    48: "Foggy",
                    51: "Light drizzle",
                    61: "Light rain",
                    80: "Showers",
                    95: "Thunderstorm"
                }
                condition = conditions.get(weather_code, "Variable conditions")
                return f"In Delhi, it's {temp}°C and {condition}."
    except Exception:
        pass
    
    return ""


def _build_context_header() -> str:
    """Build a brief context header for the briefing."""
    greeting = _get_greeting_context()
    weather = _get_weather_context()
    
    header = greeting
    if weather:
        header += f" {weather}"
    
    header += " Here's your KPI briefing."
    return header


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
    context_header = _build_context_header()
    return (
        f"{context_header}\n\n"
        f"{_SYSTEM_PROMPT}\n\n"
        f"Department: {department}\n"
        f"Date: {date.today().strftime('%d %B %Y')}\n\n"
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
        error_str = str(e)
        
        # Handle quota exceeded error
        if "429" in error_str or "quota" in error_str.lower():
            return (
                "📊 **Insights Generation Paused** — API quota exceeded.\n\n"
                "The free tier allows 5 requests per minute. To continue using AI insights:\n"
                "• **Upgrade Plan**: Visit [Google AI Studio](https://ai.google.dev) to upgrade to a paid plan\n"
                "• **Wait & Retry**: Wait 1 minute before generating insights again\n\n"
                "Meanwhile, you can still view your KPI data and manual comments below."
            )
        
        # Handle other API errors
        if "401" in error_str or "unauthorized" in error_str.lower():
            return (
                "❌ **Authentication Error** — Invalid or missing API key.\n\n"
                "Please check your GEMINI_API_KEY configuration."
            )
        
        # Generic error
        return f"⚠️ Could not generate insights: {e}"
