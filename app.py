import streamlit as st
from supabase import create_client
import datetime
import anthropic
import json

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CLC Team Meetings", page_icon="👥", layout="wide")

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "CLC2026admin")
ANTHROPIC_KEY  = st.secrets.get("ANTHROPIC_API_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────
PROGRAMS = {
    "JP": {"label": "Junior Primary",  "color": "#2d7d4f", "light": "#d1fae5", "emoji": "🟢"},
    "PY": {"label": "Primary Years",   "color": "#1a4d8c", "light": "#dbeafe", "emoji": "🔵"},
    "SY": {"label": "Senior Years",    "color": "#7c3aed", "light": "#ede9fe", "emoji": "🟣"},
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
RECURRENCE_TYPES = ["Weekly", "Fortnightly", "Monthly"]

def get_program_from_params():
    params = st.query_params
    prog = params.get("program", "JP")
    return prog if prog in PROGRAMS else "JP"

def admin_login():
    if "admin" not in st.session_state:
        st.session_state.admin = False
    with st.sidebar:
        if not st.session_state.admin:
            with st.expander("🔐 Admin Login"):
                pw = st.text_input("Password", type="password", key="pw_input")
                if st.button("Login"):
                    if pw == ADMIN_PASSWORD:
                        st.session_state.admin = True
                        st.rerun()
                    else:
                        st.error("Incorrect password")
        else:
            st.success("✅ Admin logged in")
            if st.button("Logout"):
                st.session_state.admin = False
                st.rerun()

def improve_with_ai(raw_text: str, program: str, meeting_date: str) -> str:
    """Use Claude to improve meeting minutes from raw transcript."""
    if not ANTHROPIC_KEY:
        return raw_text
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = f"""You are a professional minute-taker for an alternative education school (Cowandilla Learning Centre, Learning & Behaviour Unit).

Program team: {PROGRAMS[program]['label']} ({program})
Meeting date: {meeting_date}

Transform the following raw transcript or rough notes into polished, professional meeting minutes.

Format requirements:
- Clear heading with meeting details
- Numbered agenda items with concise summaries
- Action items clearly identified with: Action | Assigned to | Timeline
- Professional but accessible language
- Trauma-informed, strengths-based framing where relevant
- Preserve all factual content — do not add or fabricate information
- End with a summary table of all action items

Raw input:
{raw_text}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

# ── DB helpers ────────────────────────────────────────────────────────────────
def fetch(table, filters=None, order=None):
    q = supabase.table(table).select("*")
    if filters:
        for k, v in filters.items():
            q = q.eq(k, v)
    if order:
        q = q.order(order, desc=True)
    return q.execute().data or []

def insert(table, data):
    supabase.table(table).insert(data).execute()

def update_row(table, row_id, data):
    supabase.table(table).update(data).eq("id", row_id).execute()

def delete_row(table, row_id):
    supabase.table(table).delete().eq("id", row_id).execute()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION RENDERERS
# ─────────────────────────────────────────────────────────────────────────────

def render_schedules(program):
    """Meeting schedule management — recurring + additional."""
    st.subheader("📅 Meeting Schedules")

    schedules = fetch("tm_schedules", {"program": program}, "created_at")

    # ── Display existing schedules ──
    if schedules:
        for s in schedules:
            col1, col2, col3 = st.columns([4, 1, 1])
            with col1:
                rec_label = f"{s['recurrence_type']} · {s['day_of_week']} · {s['meeting_time']}"
                if s.get("schedule_type") == "additional":
                    date_str = s.get("specific_date", "")
                    rec_label = f"Additional · {date_str} · {s['meeting_time']}"
                badges = []
                if s.get("show_calendar"):
                    badges.append("📅 Calendar")
                if s.get("show_bulletin"):
                    badges.append("📋 Bulletin")
                badge_str = "  ".join(badges) if badges else "No display"
                st.markdown(f"**{s['schedule_name']}** — {rec_label}  \n{badge_str}")
            if st.session_state.get("admin"):
                with col2:
                    if st.button("✏️", key=f"edit_sched_{s['id']}"):
                        st.session_state[f"editing_sched_{s['id']}"] = True
                with col3:
                    if st.button("🗑️", key=f"del_sched_{s['id']}"):
                        delete_row("tm_schedules", s["id"])
                        st.rerun()

            # Inline edit
            if st.session_state.get("admin") and st.session_state.get(f"editing_sched_{s['id']}"):
                with st.form(key=f"form_edit_sched_{s['id']}"):
                    en = st.text_input("Schedule name", value=s["schedule_name"])
                    et = s.get("schedule_type", "recurring")
                    etype = st.selectbox("Type", ["recurring", "additional"], index=0 if et=="recurring" else 1)
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        if etype == "recurring":
                            eday = st.selectbox("Day", DAYS_OF_WEEK, index=DAYS_OF_WEEK.index(s.get("day_of_week", "Monday")))
                            erecur = st.selectbox("Recurrence", RECURRENCE_TYPES, index=RECURRENCE_TYPES.index(s.get("recurrence_type", "Weekly")))
                            espec = None
                        else:
                            eday = None
                            erecur = None
                            espec = st.date_input("Date", value=datetime.date.today())
                    with ec2:
                        etime = st.time_input("Time", value=datetime.time(14, 0))
                        ecal = st.checkbox("Show in Calendar", value=s.get("show_calendar", False))
                        ebul = st.checkbox("Show in Bulletin", value=s.get("show_bulletin", False))
                    enotes = st.text_area("Notes", value=s.get("notes", ""))
                    if st.form_submit_button("Save Changes"):
                        update_row("tm_schedules", s["id"], {
                            "schedule_name": en, "schedule_type": etype,
                            "day_of_week": eday, "recurrence_type": erecur,
                            "specific_date": str(espec) if espec else None,
                            "meeting_time": etime.strftime("%H:%M"),
                            "show_calendar": ecal, "show_bulletin": ebul, "notes": enotes
                        })
                        del st.session_state[f"editing_sched_{s['id']}"]
                        st.rerun()
            st.divider()
    else:
        st.info("No meeting schedules set up yet.")

    # ── Add new schedule (admin only) ──
    if st.session_state.get("admin"):
        with st.expander("➕ Add Meeting Schedule"):
            with st.form("new_schedule_form"):
                sname = st.text_input("Schedule name", placeholder="e.g. Weekly Team Meeting")
                stype = st.selectbox("Schedule type", ["recurring", "additional"],
                                     help="Recurring = ongoing pattern · Additional = one-off or extra meeting")
                c1, c2 = st.columns(2)
                with c1:
                    if stype == "recurring":
                        sday = st.selectbox("Day of week", DAYS_OF_WEEK)
                        srecur = st.selectbox("Recurrence", RECURRENCE_TYPES)
                        sspec = None
                    else:
                        sday = None
                        srecur = None
                        sspec = st.date_input("Specific date")
                with c2:
                    stime = st.time_input("Meeting time", value=datetime.time(14, 0))
                    scal = st.checkbox("Show in Calendar 📅")
                    sbul = st.checkbox("Show in Bulletin 📋")
                snotes = st.text_area("Notes / location", placeholder="e.g. Meeting Room 1, via Teams")
                if st.form_submit_button("Add Schedule"):
                    if sname.strip():
                        insert("tm_schedules", {
                            "program": program, "schedule_name": sname.strip(),
                            "schedule_type": stype, "day_of_week": sday,
                            "recurrence_type": srecur,
                            "specific_date": str(sspec) if sspec else None,
                            "meeting_time": stime.strftime("%H:%M"),
                            "show_calendar": scal, "show_bulletin": sbul,
                            "notes": snotes.strip()
                        })
                        st.success("Schedule added!")
                        st.rerun()
                    else:
                        st.warning("Please enter a schedule name.")


def render_agenda(program):
    """Agenda management — any staff can add, admin can finalise."""
    st.subheader("📋 Agenda")

    # Pick meeting to associate agenda items with
    schedules = fetch("tm_schedules", {"program": program})
    schedule_options = {s["schedule_name"]: s["id"] for s in schedules} if schedules else {}
    schedule_options["General / Unassigned"] = None

    selected_sched = st.selectbox("Filter by meeting", list(schedule_options.keys()), key="agenda_sched_filter")
    sched_id = schedule_options[selected_sched]

    agenda_items = fetch("tm_agenda_items", {"program": program})
    if sched_id:
        agenda_items = [a for a in agenda_items if a.get("schedule_id") == sched_id]
    elif selected_sched == "General / Unassigned":
        agenda_items = [a for a in agenda_items if not a.get("schedule_id")]

    if agenda_items:
        for item in sorted(agenda_items, key=lambda x: x.get("created_at", "")):
            c1, c2 = st.columns([5, 1])
            with c1:
                status_icon = "✅" if item.get("status") == "completed" else ("⏳" if item.get("status") == "in_progress" else "🔲")
                st.markdown(f"{status_icon} **{item['title']}**")
                if item.get("description"):
                    st.caption(item["description"])
                st.caption(f"Submitted by: {item.get('submitted_by', 'Unknown')} · {item.get('created_at','')[:10]}")
            if st.session_state.get("admin"):
                with c2:
                    new_status = st.selectbox("Status", ["pending", "in_progress", "completed"],
                                               index=["pending","in_progress","completed"].index(item.get("status","pending")),
                                               key=f"status_{item['id']}", label_visibility="collapsed")
                    if new_status != item.get("status", "pending"):
                        update_row("tm_agenda_items", item["id"], {"status": new_status})
                        st.rerun()
            st.divider()
    else:
        st.info("No agenda items yet for this meeting.")

    # Submit agenda item — any staff
    with st.expander("➕ Submit an Agenda Item"):
        with st.form("agenda_form"):
            submitter = st.text_input("Your name")
            title = st.text_input("Agenda item title")
            description = st.text_area("Details / context (optional)")
            assoc_sched = st.selectbox("Associate with meeting", list(schedule_options.keys()), key="agenda_assoc")
            if st.form_submit_button("Submit"):
                if submitter.strip() and title.strip():
                    insert("tm_agenda_items", {
                        "program": program,
                        "schedule_id": schedule_options.get(assoc_sched),
                        "submitted_by": submitter.strip(),
                        "title": title.strip(),
                        "description": description.strip(),
                        "status": "pending"
                    })
                    st.success("Agenda item submitted!")
                    st.rerun()
                else:
                    st.warning("Please enter your name and a title.")


def render_minutes(program):
    """Minutes — admin only to create/edit, all can view."""
    st.subheader("📝 Meeting Minutes")

    minutes_list = fetch("tm_minutes", {"program": program}, "meeting_date")

    # ── View existing minutes ──
    if minutes_list:
        for m in minutes_list:
            with st.expander(f"📄 {m.get('meeting_date','')} — {m.get('title','Untitled')}"):
                st.markdown(m.get("content", "No content recorded."))
                if m.get("action_summary"):
                    st.info(f"**Actions:** {m['action_summary']}")
                if st.session_state.get("admin"):
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✏️ Edit Minutes", key=f"edit_min_{m['id']}"):
                            st.session_state[f"editing_min_{m['id']}"] = True
                    with col2:
                        if st.button("🗑️ Delete", key=f"del_min_{m['id']}"):
                            delete_row("tm_minutes", m["id"])
                            st.rerun()
                    if st.session_state.get(f"editing_min_{m['id']}"):
                        with st.form(f"edit_min_form_{m['id']}"):
                            etitle = st.text_input("Title", value=m.get("title",""))
                            edate  = st.date_input("Date", value=datetime.date.fromisoformat(m["meeting_date"]) if m.get("meeting_date") else datetime.date.today())
                            econtent = st.text_area("Minutes content", value=m.get("content",""), height=300)
                            eactions = st.text_area("Action summary", value=m.get("action_summary",""))
                            if st.form_submit_button("Save"):
                                update_row("tm_minutes", m["id"], {
                                    "title": etitle, "meeting_date": str(edate),
                                    "content": econtent, "action_summary": eactions
                                })
                                del st.session_state[f"editing_min_{m['id']}"]
                                st.rerun()
    else:
        st.info("No minutes recorded yet.")

    # ── Record new minutes (admin only) ──
    if st.session_state.get("admin"):
        st.divider()
        st.subheader("✍️ Record New Minutes")

        input_method = st.radio("Input method", ["📄 Type / paste minutes directly", "🎙️ Drop transcript — AI will improve it"], horizontal=True)

        with st.form("new_minutes_form"):
            m_title = st.text_input("Meeting title", placeholder="e.g. JP Team Meeting — Term 1 Week 4")
            m_date  = st.date_input("Meeting date", value=datetime.date.today())

            schedules = fetch("tm_schedules", {"program": program})
            sched_opts = {s["schedule_name"]: s["id"] for s in schedules}
            sched_opts["General / Unassigned"] = None
            m_sched = st.selectbox("Associated schedule", list(sched_opts.keys()))

            if "📄" in input_method:
                m_content = st.text_area("Minutes", height=350, placeholder="Type or paste your meeting minutes here...")
                do_ai = False
            else:
                m_content = st.text_area("Paste transcript or rough notes", height=350,
                                          placeholder="Paste the transcript or your rough notes here. AI will structure and improve them into polished minutes.")
                do_ai = True

            m_actions = st.text_area("Action items summary (optional — leave blank to auto-extract from minutes)",
                                      placeholder="e.g. Update student profiles – Candice – Week 3")

            submitted = st.form_submit_button("💾 Save Minutes" if not do_ai else "✨ Improve with AI & Save")

            if submitted:
                if m_title.strip() and m_content.strip():
                    final_content = m_content.strip()
                    if do_ai:
                        with st.spinner("Claude is improving your minutes…"):
                            final_content = improve_with_ai(final_content, program, str(m_date))
                    insert("tm_minutes", {
                        "program": program,
                        "schedule_id": sched_opts.get(m_sched),
                        "title": m_title.strip(),
                        "meeting_date": str(m_date),
                        "content": final_content,
                        "action_summary": m_actions.strip()
                    })
                    st.success("Minutes saved!")
                    st.rerun()
                else:
                    st.warning("Please enter a title and content.")


def render_actions(program):
    """Action items tracker."""
    st.subheader("✅ Action Items")

    actions = fetch("tm_actions", {"program": program}, "due_date")

    open_actions = [a for a in actions if a.get("status") != "completed"]
    completed    = [a for a in actions if a.get("status") == "completed"]

    if open_actions:
        st.markdown("**Open Actions**")
        for a in open_actions:
            c1, c2, c3 = st.columns([4, 2, 1])
            with c1:
                st.markdown(f"🔲 **{a['action']}**")
                st.caption(f"Assigned to: {a.get('assigned_to','—')} · Due: {a.get('due_date','—')}")
            with c2:
                if st.session_state.get("admin"):
                    if st.button("✅ Mark complete", key=f"complete_{a['id']}"):
                        update_row("tm_actions", a["id"], {"status": "completed"})
                        st.rerun()
            with c3:
                if st.session_state.get("admin"):
                    if st.button("🗑️", key=f"del_action_{a['id']}"):
                        delete_row("tm_actions", a["id"])
                        st.rerun()
            st.divider()
    else:
        st.info("No open action items.")

    if completed:
        with st.expander(f"✅ Completed ({len(completed)})"):
            for a in completed:
                st.markdown(f"~~{a['action']}~~ — {a.get('assigned_to','—')}")

    if st.session_state.get("admin"):
        with st.expander("➕ Add Action Item"):
            with st.form("action_form"):
                a_text = st.text_input("Action")
                a_col1, a_col2 = st.columns(2)
                with a_col1:
                    a_assigned = st.text_input("Assigned to")
                with a_col2:
                    a_due = st.date_input("Due date", value=datetime.date.today() + datetime.timedelta(weeks=2))
                a_notes = st.text_input("Notes (optional)")
                if st.form_submit_button("Add"):
                    if a_text.strip():
                        insert("tm_actions", {
                            "program": program,
                            "action": a_text.strip(),
                            "assigned_to": a_assigned.strip(),
                            "due_date": str(a_due),
                            "notes": a_notes.strip(),
                            "status": "open"
                        })
                        st.success("Action added!")
                        st.rerun()


def render_attendance(program):
    """Attendance register."""
    st.subheader("🙋 Attendance")

    schedules = fetch("tm_schedules", {"program": program})
    if not schedules:
        st.info("Add a meeting schedule first.")
        return

    sched_opts = {s["schedule_name"]: s["id"] for s in schedules}
    sel_sched = st.selectbox("Meeting", list(sched_opts.keys()), key="att_sched")
    sel_date  = st.date_input("Meeting date", value=datetime.date.today(), key="att_date")

    existing = supabase.table("tm_attendance").select("*").eq("program", program)\
        .eq("schedule_id", sched_opts[sel_sched]).eq("meeting_date", str(sel_date)).execute().data or []

    if existing:
        st.markdown("**Attendance record:**")
        for att in existing:
            status_icon = "✅" if att["status"] == "present" else "❌"
            st.markdown(f"{status_icon} {att['staff_name']} — {att['status'].title()}")
    else:
        st.info("No attendance recorded for this meeting date yet.")

    if st.session_state.get("admin"):
        with st.expander("📝 Record Attendance"):
            with st.form("attendance_form"):
                names_raw = st.text_area("Staff names (one per line)")
                status_val = st.selectbox("Status for all entered", ["present", "absent", "apology"])
                if st.form_submit_button("Save"):
                    names = [n.strip() for n in names_raw.splitlines() if n.strip()]
                    for name in names:
                        # Upsert by checking if already exists
                        check = supabase.table("tm_attendance").select("id")\
                            .eq("program", program).eq("schedule_id", sched_opts[sel_sched])\
                            .eq("meeting_date", str(sel_date)).eq("staff_name", name).execute().data
                        if check:
                            update_row("tm_attendance", check[0]["id"], {"status": status_val})
                        else:
                            insert("tm_attendance", {
                                "program": program,
                                "schedule_id": sched_opts[sel_sched],
                                "meeting_date": str(sel_date),
                                "staff_name": name,
                                "status": status_val
                            })
                    st.success(f"Attendance saved for {len(names)} staff member(s).")
                    st.rerun()


def render_documents(program):
    """Supporting documents — links/notes."""
    st.subheader("📎 Supporting Documents")

    docs = fetch("tm_documents", {"program": program}, "created_at")

    if docs:
        for d in docs:
            c1, c2 = st.columns([5, 1])
            with c1:
                if d.get("url"):
                    st.markdown(f"📄 [{d['title']}]({d['url']})")
                else:
                    st.markdown(f"📄 **{d['title']}**")
                if d.get("description"):
                    st.caption(d["description"])
                st.caption(f"Added: {d.get('created_at','')[:10]}")
            if st.session_state.get("admin"):
                with c2:
                    if st.button("🗑️", key=f"del_doc_{d['id']}"):
                        delete_row("tm_documents", d["id"])
                        st.rerun()
            st.divider()
    else:
        st.info("No documents added yet.")

    if st.session_state.get("admin"):
        with st.expander("➕ Add Document Link"):
            with st.form("doc_form"):
                d_title = st.text_input("Title")
                d_url   = st.text_input("URL (optional)")
                d_desc  = st.text_area("Description (optional)")
                if st.form_submit_button("Add"):
                    if d_title.strip():
                        insert("tm_documents", {
                            "program": program, "title": d_title.strip(),
                            "url": d_url.strip(), "description": d_desc.strip()
                        })
                        st.success("Document added!")
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    program = get_program_from_params()
    prog_info = PROGRAMS[program]

    admin_login()

    # ── Header ──
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{prog_info['color']},{'#3fa86a' if program=='JP' else '#2a6fd4' if program=='PY' else '#9b59b6'});
                padding:1.5rem 2rem;border-radius:16px;margin-bottom:1.5rem;">
      <div style="font-size:2.5rem;margin-bottom:0.25rem;">{prog_info['emoji']}</div>
      <h1 style="color:white;margin:0;font-size:1.8rem;">{prog_info['label']} Team Meetings</h1>
      <p style="color:rgba(255,255,255,0.85);margin:0.25rem 0 0;">Cowandilla Learning Centre · LBU</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Program switcher ──
    with st.sidebar:
        st.markdown("### 🔀 Switch Program")
        for p, info in PROGRAMS.items():
            if p != program:
                st.markdown(f"[{info['emoji']} {info['label']}](?program={p})")
        st.divider()
        if st.session_state.get("admin"):
            st.markdown("### ⚙️ Admin Mode Active")
            st.caption("You can add, edit and delete all content.")

    # ── Tabs ──
    tab_sched, tab_agenda, tab_minutes, tab_actions, tab_attend, tab_docs = st.tabs([
        "📅 Schedules", "📋 Agenda", "📝 Minutes", "✅ Actions", "🙋 Attendance", "📎 Documents"
    ])

    with tab_sched:
        render_schedules(program)
    with tab_agenda:
        render_agenda(program)
    with tab_minutes:
        render_minutes(program)
    with tab_actions:
        render_actions(program)
    with tab_attend:
        render_attendance(program)
    with tab_docs:
        render_documents(program)


if __name__ == "__main__":
    main()
