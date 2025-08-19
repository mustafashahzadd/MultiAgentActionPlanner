from pydantic import BaseModel, Field
from typing import List, Dict, Union

# ---------- Planner ----------
class TaskItem(BaseModel):
    desc: str = Field(..., description="Short actionable task")
    owner: str = Field("You")
    effort_hrs: int = Field(..., ge=1, le=12)

class Milestone(BaseModel):
    title: str
    due: str = Field(..., description="YYYY-MM-DD")
    tasks: List[TaskItem]

class PlanOut(BaseModel):
    milestones: List[Milestone]
    success_metrics: List[str]
    # accept list OR dict then normalize in UI
    risks: Union[List[Dict[str, str]], Dict[str, str]]

# ---------- Researcher ----------
class Target(BaseModel):
    name: str
    why: str

class Reference(BaseModel):
    title: str
    url: str

class ResearchOut(BaseModel):
    targets: List[Target]
    insights: List[str]
    # accept list OR dict; normalize in UI
    risks: Union[List[Dict[str, str]], Dict[str, str]]
    references: List[Reference]

# ---------- Producer ----------
class AssetsOut(BaseModel):
    launch_email: str
    social_posts: List[str]  # 3–5 posts
    script_outline: str      # markdown
    weekly_checklist: str    # markdown
