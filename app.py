# app.py — Action Planner (text-friendly UI + Run All + Deliver)

import os, json, io, zipfile, datetime as dt
import streamlit as st
from schemas import PlanOut, ResearchOut, AssetsOut, Milestone
from planner_groq import make_plan
from researcher_groq import make_research
from producer_groq import make_assets

# ---- Optional email/calendar helpers ----
import ssl, smtplib
from email.message import EmailMessage
from urllib.parse import quote

# Calendar export is optional; if 'ics' isn't installed, button will be hidden
try:
    from ics import Calendar, Event
    ICS_AVAILABLE = True
except Exception:
    Calendar = Event = None
    ICS_AVAILABLE = False

# ---------- Secrets -> env (Groq) ----------
if "GROQ_API_KEY" in st.secrets:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
if "GROQ_MODEL" in st.secrets:
    os.environ["GROQ_MODEL"] = st.secrets["GROQ_MODEL"]

# ---------- Page chrome ----------
st.set_page_config(page_title="Action Planner", page_icon="🧭", layout="wide")
st.markdown("""
<h1 style="margin-bottom:0">🧭 Action Planner</h1>
<p style="color:#64748B; margin-top:4px">From goal → research → plan → assets — in minutes.</p>
<hr style="margin:8px 0 16px 0; opacity:.2">
""", unsafe_allow_html=True)

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Model")
    current = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
    chosen = st.text_input(
        "Groq model",
        current,
        help="Examples: llama-3.1-70b-versatile, llama-3.1-8b-instant, deepseek-r1-distill-llama-70b",
    )
    if chosen:
        os.environ["GROQ_MODEL"] = chosen

    st.divider()
    st.caption("Presets")
    if st.button("🎙️ Podcast"):
        st.session_state.goal = "Launch a podcast in 2 weeks"
        st.session_state.audience = "aspiring CS students"
        st.session_state.constraints = "low budget; weekly episodes; concise; 3 milestones max"
    if st.button("🧪 1-day AI Workshop"):
        st.session_state.goal = "Plan a 1-day AI workshop in 10 days"
        st.session_state.audience = "high-school students"
        st.session_state.constraints = "budget < $200; 25 attendees; include consent forms"
    if st.button("🚀 Landing Page"):
        st.session_state.goal = "Ship a product landing page in 5 days"
        st.session_state.audience = "early adopters of a task manager app"
        st.session_state.constraints = "no-code tools; mobile-first; 5 sections max"

# ---------- Inputs ----------
c1, c2 = st.columns(2)
goal = c1.text_input("Goal", st.session_state.get("goal", "Launch a podcast in 2 weeks"))
audience = c1.text_input("Audience", st.session_state.get("audience", "aspiring CS students"))
constraints = c2.text_area(
    "Constraints (budget/time/tone)",
    st.session_state.get("constraints", "low budget; weekly episodes; concise"),
)

# ---------- Session buckets ----------
st.session_state.setdefault("research", None)
st.session_state.setdefault("plan", None)
st.session_state.setdefault("assets", None)
st.session_state.setdefault("edit_mode", False)

# ---------- Render helpers (text-friendly) ----------
def render_targets(targets):
    if not targets:
        st.write("No targets found."); return
    st.markdown("**🎯 Targets**")
    for t in targets:
        name = getattr(t, "name", t)
        st.markdown(f"- {name}")

def render_insights(insights):
    if not insights:
        st.write("No insights yet."); return
    st.markdown("**💡 Insights**")
    for i in insights:
        st.markdown(f"- {i}")

def render_risks(risks):
    if not risks:
        st.write("No major risks identified."); return
    st.markdown("**⚠️ Risks & Mitigations**")
    for r in risks:
        risk = r.get("risk") if isinstance(r, dict) else str(r)
        mit  = r.get("mitigation") if isinstance(r, dict) else ""
        st.markdown(f"- **Risk:** {risk} — *Mitigation:* {mit}")

def render_references(refs):
    if not refs:
        st.write("No references."); return
    st.markdown("**🔗 References**")
    for ref in refs:
        if hasattr(ref, "title"):                  # Pydantic Reference
            title = ref.title; url = getattr(ref, "url", "")
        elif isinstance(ref, dict):                # dict fallback
            title = ref.get("title", "Reference"); url = ref.get("url", "")
        else:
            title, url = str(ref), ""
        st.markdown(f"- [{title}]({url})" if url else f"- {title}")



def render_tasks_table(tasks):
    rows = []
    for t in tasks:
        d = t.model_dump() if hasattr(t, "model_dump") else t
        rows.append({"Task": d.get("desc",""), "Owner": d.get("owner","You"), "Effort (hrs)": d.get("effort_hrs","")})
    st.table(rows)

def timeline():
    def badge(ok, label): return f"{'✅' if ok else '⏳'} {label}"
    r_ok = st.session_state.research is not None
    p_ok = st.session_state.plan is not None
    a_ok = st.session_state.assets is not None
    st.markdown(f"**Workflow:** {badge(r_ok,'Research')} → {badge(p_ok,'Plan')} → {badge(a_ok,'Produce')}")

# ---- Deliver helpers ----
def build_mailto_link(to_email: str, subject: str, body: str) -> str:
    return f"mailto:{quote(to_email)}?subject={quote(subject)}&body={quote(body)}"

def build_eml_bytes(subject: str, body: str, sender: str, recipient: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender or "me@example.com"
    msg["To"] = recipient or "you@example.com"
    msg.set_content(body)
    return msg.as_bytes()

def smtp_send(subject: str, body: str, sender: str, recipient: str) -> tuple[bool, str]:
    host = os.getenv("SMTP_HOST", st.secrets.get("SMTP_HOST", ""))
    port = int(os.getenv("SMTP_PORT", st.secrets.get("SMTP_PORT", "0") or "0"))
    user = os.getenv("SMTP_USER", st.secrets.get("SMTP_USER", ""))
    pw   = os.getenv("SMTP_PASS", st.secrets.get("SMTP_PASS", ""))
    if not all([host, port, user, pw]):
        return False, "SMTP not configured"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender or user
    msg["To"] = recipient
    msg.set_content(body)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(user, pw)
            server.send_message(msg)
        return True, "Sent"
    except Exception as e:
        return False, str(e)

def build_ics_from_plan(plan: PlanOut, title_prefix="Milestone"):
    if not ICS_AVAILABLE:
        return None
    cal = Calendar()
    for i, m in enumerate(plan.milestones, 1):
        e = Event()
        e.name = f"{title_prefix} {i}: {m.title}"
        e.begin = f"{m.due} 09:00"   # naive time; editable after import
        e.make_all_day()
        cal.events.add(e)
    return str(cal).encode("utf-8")

# ---------- Top timeline ----------
timeline()

# ---------- Controls ----------
b1, b2, b3, b4, b5 = st.columns([1,1,1,1,1])
run_research = b1.button("1) Research")
run_plan     = b2.button("2) Plan")
run_assets   = b3.button("3) Produce assets")
clear_all    = b4.button("🧹 Reset")
run_all      = b5.button("✨ Run all")

if clear_all:
    st.session_state.research = None
    st.session_state.plan = None
    st.session_state.assets = None
    st.session_state.edit_mode = False
    st.experimental_rerun()

# ---------- Run All ----------
if run_all:
    try:
        with st.spinner("Researching…"):
            r = make_research(goal, audience, constraints)
        if isinstance(r.risks, dict):
            r.risks = [{"risk": k, "mitigation": v} for k, v in r.risks.items()]
        st.session_state.research = r
        st.success("Research ready ✅")
    except Exception as e:
        st.error("Research failed."); st.caption(str(e))

    if st.session_state.research:
        try:
            with st.spinner("Planning…"):
                p = make_plan(goal, audience, constraints)
            if isinstance(p.risks, dict):
                p.risks = [{"risk": k, "mitigation": v} for k, v in p.risks.items()]
            st.session_state.plan = p
            st.success("Plan ready ✅")
        except Exception as e:
            st.error("Plan failed."); st.caption(str(e))

    if st.session_state.plan:
        try:
            with st.spinner("Producing assets…"):
                a = make_assets(
                    goal, audience, constraints,
                    plan=st.session_state.plan,
                    research=st.session_state.research
                )
            st.session_state.assets = a
            st.success("Assets ready ✅")
        except Exception as e:
            st.error("Assets failed."); st.caption(str(e))

# ---------- Step 1: Research ----------
if run_research:
    try:
        with st.spinner("Researching…"):
            r: ResearchOut = make_research(goal, audience, constraints)
        if isinstance(r.risks, dict):
            r.risks = [{"risk": k, "mitigation": v} for k, v in r.risks.items()]
        st.session_state.research = r
        st.success("Research ready ✅")
    except Exception as e:
        st.error("Research failed. Please try again."); st.caption(str(e))

if st.session_state.research:
    st.markdown("### 🔎 Research")
    r = st.session_state.research
    render_targets(r.targets)
    with st.expander("Insights", expanded=True):
        render_insights(r.insights)
    with st.expander("Risks & mitigations", expanded=False):
        render_risks(r.risks)
    with st.expander("References", expanded=False):
        render_references(r.references)

# ---------- Step 2: Plan ----------
if run_plan:
    try:
        with st.spinner("Planning…"):
            p: PlanOut = make_plan(goal, audience, constraints)
        if isinstance(p.risks, dict):
            p.risks = [{"risk": k, "mitigation": v} for k, v in p.risks.items()]
        st.session_state.plan = p
        st.session_state.edit_mode = True
        st.success("Plan ready ✅ — you can edit it below before producing assets.")
    except Exception as e:
        st.error("Plan failed. Please try again."); st.caption(str(e))

if st.session_state.plan:
    st.markdown("### 📅 Plan")
    p: PlanOut = st.session_state.plan
    with st.form("edit_plan"):
        st.caption("Edit milestone titles/dates if needed, then Save changes.")
        new_milestones = []
        for i, m in enumerate(p.milestones):
            with st.expander(f"Milestone {i+1}: {m.title} — due {m.due}", expanded=(i==0)):
                t = st.text_input("Title", m.title, key=f"title_{i}")
                due = st.text_input("Due (YYYY-MM-DD)", m.due, key=f"due_{i}")
                st.markdown("**Tasks**"); render_tasks_table(m.tasks)
                new_milestones.append(Milestone(title=t, due=due, tasks=m.tasks))
        save = st.form_submit_button("💾 Save changes")
        if save:
            p.milestones = new_milestones
            st.session_state.plan = p
            st.success("Saved.")

    st.markdown("**✅ Success metrics**")
    for mtr in p.success_metrics: st.markdown(f"- {mtr}")
    with st.expander("⚠️ Risks & mitigations", expanded=False):
        render_risks(p.risks)

# ---------- Step 3: Produce assets ----------
if run_assets:
    try:
        if not st.session_state.plan:
            st.warning("Run planning first.")
        else:
            with st.spinner("Producing assets…"):
                a: AssetsOut = make_assets(
                    goal, audience, constraints,
                    plan=st.session_state.plan,
                    research=st.session_state.research
                )
            st.session_state.assets = a
            st.success("Assets ready ✅")
    except Exception as e:
        st.error("Asset generation failed. Please try again."); st.caption(str(e))

if st.session_state.assets:
    st.markdown("### ✉️ Assets")
    a: AssetsOut = st.session_state.assets
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Launch email");    st.code(a.launch_email, language="markdown")
    with c2:
        st.subheader("Script outline");  st.code(a.script_outline, language="markdown")
    st.subheader("Social posts")
    for i, post in enumerate(a.social_posts, 1): st.code(f"{i}. {post}", language="markdown")
    st.subheader("Weekly checklist");    st.code(a.weekly_checklist, language="markdown")

    # ---- ZIP + individual downloads ----
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("plan.json", st.session_state.plan.model_dump_json(indent=2))
        if st.session_state.research:
            z.writestr("research.json", st.session_state.research.model_dump_json(indent=2))
        z.writestr("launch_email.md", a.launch_email)
        z.writestr("social_posts.md", "\n\n".join(a.social_posts))
        z.writestr("script_outline.md", a.script_outline)
        z.writestr("weekly_checklist.md", a.weekly_checklist)
        z.writestr("meta.txt", f"generated_at={dt.datetime.utcnow().isoformat()}Z")

    st.download_button("⬇️ Download launch pack (.zip)", data=buf.getvalue(), file_name="action-planner-pack.zip")
    st.download_button("Download plan.json", data=st.session_state.plan.model_dump_json(indent=2), file_name="plan.json")

# ---------- 📤 Deliver ----------
if st.session_state.assets and st.session_state.plan:
    st.markdown("### 📤 Deliver")

    a = st.session_state.assets

    # Prefill subject from first line if present
    default_subject = "Launch: Podcast"
    if a.launch_email:
        first = a.launch_email.splitlines()[0]
        if first.lower().startswith("subject:"):
            default_subject = first.split(":", 1)[1].strip()

    # --- inputs
    with st.form("deliver_form", clear_on_submit=False):
        email_subject = st.text_input("Email subject", value=default_subject)
        email_body    = st.text_area("Email body", value=a.launch_email, height=220)

        colA, colB = st.columns(2)
        with colA:
            recipient_name  = st.text_input("Recipient name", value="")
            recipient_email = st.text_input("Recipient email", value="", placeholder="person@example.com")
        with colB:
            sender_name  = st.text_input("Your name (signature)", value="Action Planner")
            sender_email = st.text_input("Sender email (for .eml/SMTP)", value=st.secrets.get("SMTP_USER", ""))

        confirm = st.checkbox("I confirm the recipient and content are correct.")
        submit  = st.form_submit_button("✉️ Send via SMTP (one click)")

    # --- utilities
    import re, ssl, smtplib
    from email.message import EmailMessage
    from urllib.parse import quote

    def valid_email(x: str) -> bool:
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", x or ""))

    def smtp_send(subject: str, body: str, sender: str, recipient: str) -> tuple[bool, str]:
        host = os.getenv("SMTP_HOST", st.secrets.get("SMTP_HOST", ""))
        port = int(os.getenv("SMTP_PORT", st.secrets.get("SMTP_PORT", "0") or "0"))
        user = os.getenv("SMTP_USER", st.secrets.get("SMTP_USER", ""))
        pw   = os.getenv("SMTP_PASS", st.secrets.get("SMTP_PASS", ""))
        if not all([host, port, user, pw]):
            return False, "SMTP not configured in secrets."
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender or user
        msg["To"] = recipient
        msg.set_content(body)
        try:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as server:
                server.login(user, pw)
                server.send_message(msg)
            return True, "Email sent ✅"
        except Exception as e:
            return False, f"Send failed: {e}"

    # --- actions
    if submit:
        # guardrails
        if not confirm:
            st.warning("Please confirm the recipient and content.")
        elif not valid_email(recipient_email):
            st.error("Recipient email looks invalid.")
        elif not valid_email(sender_email):
            st.error("Sender email looks invalid.")
        else:
            ok, msg = smtp_send(email_subject, email_body, sender_email, recipient_email)
            (st.success if ok else st.error)(msg)

    # Always show mailto + .eml fallback
    from urllib.parse import quote
    mailto = f"mailto:{quote(recipient_email or '')}?subject={quote(email_subject)}&body={quote(email_body)}"
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"[📧 Open in Mail app (mailto)]({mailto})")
    with c2:
        # Build .eml bytes
        m = EmailMessage(); m["Subject"]=email_subject; m["From"]=sender_email or "me@example.com"; m["To"]=recipient_email or "you@example.com"; m.set_content(email_body)
        st.download_button("⬇️ Download .eml", data=m.as_bytes(), file_name="launch-email.eml")

    # Optional calendar export (requires 'ics' in requirements)
    try:
        from ics import Calendar, Event
        cal = Calendar()
        for i, m in enumerate(st.session_state.plan.milestones, 1):
            ev = Event()
            ev.name = f"Milestone {i}: {m.title}"
            ev.begin = f"{m.due} 09:00"; ev.make_all_day()
            cal.events.add(ev)
        st.download_button("📆 Download milestones.ics", data=str(cal).encode("utf-8"), file_name="milestones.ics")
    except Exception:
        st.caption("Install `ics` in requirements.txt to enable calendar export.")
