import os
from typing import Optional
from pydantic import ValidationError
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from schemas import PlanOut

# Streamlit exposes secrets via st.secrets, but we also fall back to env
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model=GROQ_MODEL,
    temperature=0.2,   # stable outputs
)

structured_llm = llm.with_structured_output(PlanOut)

prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a meticulous project planner. "
     "Return a feasible, time-bound plan as VALID JSON matching the schema."),
    ("user",
     "Goal: {goal}\nAudience: {audience}\nConstraints: {constraints}\n\n"
     "Rules:\n"
     "- 2–5 milestones with due dates (YYYY-MM-DD)\n"
     "- 2–5 tasks per milestone; effort_hrs between 1 and 12\n"
     "- Include success_metrics and risks with mitigations\n"
     "- Be concise and realistic\n"
     "Return JSON only."
    )
])

planner_chain = prompt | structured_llm

def make_plan(goal: str,
              audience: Optional[str] = None,
              constraints: Optional[str] = None) -> PlanOut:
    """Generate a validated plan. Retries once if JSON fails."""
    payload = {
        "goal": goal,
        "audience": audience or "general",
        "constraints": constraints or "keep budget low"
    }
    try:
        return planner_chain.invoke(payload)
    except ValidationError:
        payload["constraints"] += " STRICT JSON ONLY."
        return planner_chain.invoke(payload)
