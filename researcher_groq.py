import os
from typing import Optional
from pydantic import ValidationError
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from schemas import ResearchOut
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from schemas import ResearchOut


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

llm = ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.2)
structured_llm = llm.with_structured_output(ResearchOut)

prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a focused research analyst. Return VALID JSON for the schema."),
    ("user",
     "Goal: {goal}\nAudience: {audience}\nConstraints: {constraints}\n\n"
     "Return JSON with:\n"
     "- targets: [{name, why}] (2–4)\n"
     "- insights: [string] (5–8 concise points)\n"
     "- risks: array of objects with keys 'risk' and 'mitigation' (2–4)\n"
     "- references: [{title, url}] (3–5; trustworthy sources)\n"
     "Return JSON only."
    )
])

research_chain = prompt | structured_llm


def make_research(goal: str, audience: str, constraints: str) -> ResearchOut:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful research assistant. "
                   "Analyze the project idea and provide targets, insights, risks, and references."),
        ("human", "Goal: {goal}\nAudience: {audience}\nConstraints: {constraints}")
    ])

    llm = ChatGroq(model=os.getenv("GROQ_MODEL"), temperature=0)
    chain = prompt | llm.with_structured_output(ResearchOut)
    return chain.invoke({"goal": goal, "audience": audience, "constraints": constraints})