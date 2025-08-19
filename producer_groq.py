import os
from typing import Optional
from pydantic import ValidationError
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from schemas import AssetsOut, PlanOut, ResearchOut

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

llm = ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.3)
structured_llm = llm.with_structured_output(AssetsOut)

prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You create concise, ready-to-use assets. Return VALID JSON for AssetsOut."),
    ("user",
     "Goal: {goal}\nAudience: {audience}\nConstraints: {constraints}\n\n"
     "Plan JSON:\n{plan_json}\n\n"
     "Optional research highlights:\n{research_summary}\n\n"
     "Produce:\n"
     "- launch_email: brief subject + body, friendly & clear CTA\n"
     "- social_posts: 3–5 short posts (platform-agnostic, with hooks/CTAs)\n"
     "- script_outline: markdown outline (H2 sections, bullets)\n"
     "- weekly_checklist: markdown checklist for the next 2 weeks\n"
     "Return JSON only."
    )
])

def make_assets(goal: str,
                audience: Optional[str],
                constraints: Optional[str],
                plan: PlanOut,
                research: Optional[ResearchOut] = None) -> AssetsOut:
    # small summary string to help Producer ground content
    research_summary = ""
    if research:
        # normalize research risks (they may be dict)
        rrisks = research.risks
        if isinstance(rrisks, dict):
            rrisks = [{"risk": k, "mitigation": v} for k, v in rrisks.items()]
        research_summary = (
            f"targets={ [t.name for t in research.targets] }\n"
            f"insights_top3={ research.insights[:3] }\n"
            f"risks_top2={ [r['risk'] for r in rrisks[:2]] }"
        )

    payload = dict(
        goal=goal,
        audience=audience or "general",
        constraints=constraints or "concise, friendly",
        plan_json=plan.model_dump_json(),
        research_summary=research_summary
    )
    try:
        return (prompt | structured_llm).invoke(payload)
    except ValidationError:
        payload["constraints"] += " STRICT JSON ONLY."
        return (prompt | structured_llm).invoke(payload)
