import streamlit as st
from supabase import create_client
import datetime
from groq import Groq
import json
import io
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CLC Team Meetings", page_icon="👥", layout="wide")

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "CLC2026admin")
GROQ_KEY = st.secrets.get("GROQ_API_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────
PROGRAMS = {
    "JP":    {"label": "Junior Primary",  "color": "#2d7d4f", "light": "#d1fae5", "emoji": "🟢"},
    "PY":    {"label": "Primary Years",   "color": "#1a4d8c", "light": "#dbeafe", "emoji": "🔵"},
    "SY":    {"label": "Senior Years",    "color": "#7c3aed", "light": "#ede9fe", "emoji": "🟣"},
    "STAFF": {"label": "Staff Meetings",  "color": "#1e6f75", "light": "#ccfbf1", "emoji": "👥"},
    "ADMIN": {"label": "Admin Meetings",  "color": "#92400e", "light": "#fef3c7", "emoji": "🏢"},
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
RECURRENCE_TYPES = ["Weekly", "Fortnightly", "Monthly"]

def get_program_from_params():
    params = st.query_params
    prog = params.get("program", "JP")
    return prog if prog in PROGRAMS else "JP"

def get_week_from_params():
    """Return (monday, sunday) date tuple if ?week= param present, else None."""
    week_str = st.query_params.get("week", None)
    if not week_str:
        return None
    try:
        monday = datetime.date.fromisoformat(week_str)
        monday = monday - datetime.timedelta(days=monday.weekday())
        return monday, monday + datetime.timedelta(days=6)
    except ValueError:
        return None

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
    """Use Groq to improve meeting minutes from raw transcript."""
    if not GROQ_KEY:
        return raw_text
    client = Groq(api_key=GROQ_KEY)
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

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000
    )
    return response.choices[0].message.content

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
# WORD DOCUMENT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def _set_cell_bg(cell, hex_colour):
    """Set background colour of a table cell."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_colour)
    tcPr.append(shd)

def _set_col_width(table, col_idx, width_cm):
    for row in table.rows:
        row.cells[col_idx].width = Cm(width_cm)

def _heading_para(doc, text, level=1, colour="1e293b"):
    p   = doc.add_paragraph()
    run = p.add_run(text)
    run.bold      = True
    run.font.size = Pt(14 if level == 1 else 12 if level == 2 else 11)
    run.font.color.rgb = RGBColor.from_string(colour)
    p.paragraph_format.space_before = Pt(10 if level == 1 else 6)
    p.paragraph_format.space_after  = Pt(4)
    return p

def _section_divider(doc, title, bg_hex="1e293b", text_hex="FFFFFF"):
    """Full-width dark banner acting as a section separator."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    _set_cell_bg(cell, bg_hex)
    p   = cell.paragraphs[0]
    run = p.add_run(f"  {title}  ")
    run.bold           = True
    run.font.size      = Pt(12)
    run.font.color.rgb = RGBColor.from_string(text_hex)
    p.alignment        = WD_ALIGN_PARAGRAPH.LEFT
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after  = Pt(4)
    doc.add_paragraph()  # spacer

def _info_table(doc, rows_data, header_bg="334155", header_text="FFFFFF"):
    """Two-column key/value info table."""
    table = doc.add_table(rows=len(rows_data), cols=2)
    table.style = "Table Grid"
    for i, (key, val) in enumerate(rows_data):
        lc = table.cell(i, 0)
        rc = table.cell(i, 1)
        _set_cell_bg(lc, header_bg if i == 0 else "f1f5f9")
        _set_cell_bg(rc, header_bg if i == 0 else "FFFFFF")
        lr = lc.paragraphs[0].add_run(key)
        lr.bold           = True
        lr.font.size      = Pt(10)
        lr.font.color.rgb = RGBColor.from_string(header_text if i == 0 else "0f172a")
        rr = rc.paragraphs[0].add_run(val)
        rr.font.size      = Pt(10)
        rr.font.color.rgb = RGBColor.from_string(header_text if i == 0 else "0f172a")
    _set_col_width(table, 0, 5)
    _set_col_width(table, 1, 11)
    doc.add_paragraph()

def _attendees_table(doc, present_list, apology_list):
    """Side-by-side attendees / apologies table."""
    table = doc.add_table(rows=1 + max(len(present_list), len(apology_list), 1), cols=2)
    table.style = "Table Grid"
    # Headers
    for ci, (txt, bg) in enumerate([("✅  Present", "2d7d4f"), ("⚠️  Apologies", "92400e")]):
        cell = table.cell(0, ci)
        _set_cell_bg(cell, bg)
        run = cell.paragraphs[0].add_run(txt)
        run.bold           = True
        run.font.size      = Pt(10)
        run.font.color.rgb = RGBColor.from_string("FFFFFF")
    # Data rows
    max_rows = max(len(present_list), len(apology_list), 1)
    for ri in range(max_rows):
        p_name = present_list[ri]  if ri < len(present_list)  else ""
        a_name = apology_list[ri] if ri < len(apology_list) else ""
        for ci, name in enumerate([p_name, a_name]):
            cell = table.cell(ri + 1, ci)
            _set_cell_bg(cell, "f8fafc")
            run = cell.paragraphs[0].add_run(name)
            run.font.size = Pt(10)
    _set_col_width(table, 0, 8)
    _set_col_width(table, 1, 8)
    doc.add_paragraph()

def _digital_actions_table(doc, items):
    """Table of digital meeting items with viewed/actioned status."""
    if not items:
        doc.add_paragraph("No items recorded from digital staff meeting.", style="Normal")
        doc.add_paragraph()
        return
    cols = ["Item / Notice", "Raised By", "Actioned By", "Status"]
    table = doc.add_table(rows=1 + len(items), cols=len(cols))
    table.style = "Table Grid"
    # Header row
    for ci, col_name in enumerate(cols):
        cell = table.cell(0, ci)
        _set_cell_bg(cell, "1e3a5f")
        run = cell.paragraphs[0].add_run(col_name)
        run.bold           = True
        run.font.size      = Pt(9)
        run.font.color.rgb = RGBColor.from_string("FFFFFF")
    # Data rows
    for ri, item in enumerate(items):
        row_bg = "f8fafc" if ri % 2 == 0 else "FFFFFF"
        status = item.get("status", "Noted")
        status_bg = "d1fae5" if "action" in status.lower() else "fef3c7" if "noted" in status.lower() else "f8fafc"
        for ci, val in enumerate([
            item.get("item", ""),
            item.get("raised_by", ""),
            item.get("actioned_by", ""),
            status
        ]):
            cell = table.cell(ri + 1, ci)
            _set_cell_bg(cell, status_bg if ci == 3 else row_bg)
            run = cell.paragraphs[0].add_run(str(val))
            run.font.size = Pt(9)
    widths = [8.5, 3.5, 3.5, 2.5]
    for ci, w in enumerate(widths):
        _set_col_width(table, ci, w)
    doc.add_paragraph()

def _actions_summary_table(doc, action_text):
    """Render action items summary as a formatted table."""
    if not action_text.strip():
        return
    _heading_para(doc, "Action Items Summary", level=2, colour="7c3aed")
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for ci, hdr in enumerate(["Action", "Assigned To", "Due"]):
        cell = table.cell(0, ci)
        _set_cell_bg(cell, "5b21b6")
        run = cell.paragraphs[0].add_run(hdr)
        run.bold           = True
        run.font.size      = Pt(10)
        run.font.color.rgb = RGBColor.from_string("FFFFFF")
    lines = [l.strip() for l in action_text.splitlines() if l.strip()]
    for li, line in enumerate(lines):
        parts = [p.strip() for p in line.split("|")]
        row = table.add_row()
        bg  = "f5f3ff" if li % 2 == 0 else "FFFFFF"
        for ci in range(3):
            val  = parts[ci] if ci < len(parts) else ""
            cell = row.cells[ci]
            _set_cell_bg(cell, bg)
            run = cell.paragraphs[0].add_run(val)
            run.font.size = Pt(9)
    _set_col_width(table, 0, 9)
    _set_col_width(table, 1, 4)
    _set_col_width(table, 2, 3)
    doc.add_paragraph()

def generate_meeting_docx(
    program: str,
    meeting_date: str,
    chair: str,
    location: str,
    present: list,
    apologies: list,
    digital_summary: str,
    digital_items: list,
    face_to_face_content: str,
    action_summary: str,
    title: str = ""
) -> bytes:
    """Generate a fully formatted Word document for a combined staff meeting."""
    doc  = Document()
    prog = PROGRAMS[program]

    # ── Page margins ──────────────────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin    = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # ── Cover header ──────────────────────────────────────────────────────────
    header_table = doc.add_table(rows=1, cols=1)
    header_cell  = header_table.cell(0, 0)
    _set_cell_bg(header_cell, "0f172a")
    hp = header_cell.paragraphs[0]
    run = hp.add_run(f"  Cowandilla Learning Centre — Learning & Behaviour Unit")
    run.bold           = True
    run.font.size      = Pt(11)
    run.font.color.rgb = RGBColor.from_string("94a3b8")
    hp.paragraph_format.space_before = Pt(6)
    hp.paragraph_format.space_after  = Pt(2)
    hp2 = header_cell.add_paragraph()
    r2  = hp2.add_run(f"  {title or prog['label'] + ' Meeting Minutes'}")
    r2.bold           = True
    r2.font.size      = Pt(16)
    r2.font.color.rgb = RGBColor.from_string("FFFFFF")
    hp2.paragraph_format.space_before = Pt(2)
    hp2.paragraph_format.space_after  = Pt(8)
    doc.add_paragraph()

    # ── Meeting details table ─────────────────────────────────────────────────
    _section_divider(doc, "📋  MEETING DETAILS", bg_hex="1e3a5f")
    _info_table(doc, [
        ("Field", "Details"),
        ("Program", prog["label"]),
        ("Date", meeting_date),
        ("Chair", chair or "—"),
        ("Location", location or "—"),
    ])

    # ── Attendees ─────────────────────────────────────────────────────────────
    _section_divider(doc, "🙋  ATTENDANCE", bg_hex="1e3a5f")
    _attendees_table(doc, present, apologies)

    # ── Digital Staff Meeting section ─────────────────────────────────────────
    _section_divider(doc, "💻  PART 1 — DIGITAL STAFF MEETING", bg_hex="1a4d8c")
    if digital_summary.strip():
        _heading_para(doc, "Digital Meeting Summary", level=2, colour="1a4d8c")
        for line in digital_summary.strip().splitlines():
            if line.strip():
                p = doc.add_paragraph(line.strip(), style="Normal")
                p.paragraph_format.space_after = Pt(2)
        doc.add_paragraph()

    _heading_para(doc, "Items Raised — Viewed & Actioned", level=2, colour="1a4d8c")
    _digital_actions_table(doc, digital_items)

    # ── Face-to-Face section ──────────────────────────────────────────────────
    _section_divider(doc, "👥  PART 2 — FACE-TO-FACE MEETING", bg_hex="2d7d4f")
    if face_to_face_content.strip():
        for line in face_to_face_content.strip().splitlines():
            if line.strip():
                p = doc.add_paragraph(line.strip(), style="Normal")
                p.paragraph_format.space_after = Pt(2)
        doc.add_paragraph()
    else:
        doc.add_paragraph("No face-to-face minutes recorded.", style="Normal")
        doc.add_paragraph()

    # ── Action items ──────────────────────────────────────────────────────────
    if action_summary.strip():
        _section_divider(doc, "✅  ACTION ITEMS", bg_hex="5b21b6")
        _actions_summary_table(doc, action_summary)

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_table = doc.add_table(rows=1, cols=1)
    fc = footer_table.cell(0, 0)
    _set_cell_bg(fc, "f1f5f9")
    fp = fc.paragraphs[0]
    fr = fp.add_run(f"  Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}  |  CLC Learning & Behaviour Unit  |  CONFIDENTIAL")
    fr.font.size      = Pt(8)
    fr.font.color.rgb = RGBColor.from_string("64748b")
    fr.italic         = True

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def generate_simple_minutes_docx(
    program: str,
    meeting_date: str,
    chair: str,
    location: str,
    present: list,
    apologies: list,
    content: str,
    action_summary: str,
    title: str = ""
) -> bytes:
    """Generate a Word doc for JP/PY/SY team meeting minutes (no digital section)."""
    doc  = Document()
    prog = PROGRAMS[program]

    for section in doc.sections:
        section.top_margin    = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # Header
    header_table = doc.add_table(rows=1, cols=1)
    header_cell  = header_table.cell(0, 0)
    _set_cell_bg(header_cell, "0f172a")
    hp = header_cell.paragraphs[0]
    run = hp.add_run("  Cowandilla Learning Centre — Learning & Behaviour Unit")
    run.bold = True; run.font.size = Pt(11)
    run.font.color.rgb = RGBColor.from_string("94a3b8")
    hp.paragraph_format.space_before = Pt(6)
    hp.paragraph_format.space_after  = Pt(2)
    hp2 = header_cell.add_paragraph()
    r2  = hp2.add_run(f"  {title or prog['label'] + ' Team Meeting'}")
    r2.bold = True; r2.font.size = Pt(16)
    r2.font.color.rgb = RGBColor.from_string("FFFFFF")
    hp2.paragraph_format.space_before = Pt(2)
    hp2.paragraph_format.space_after  = Pt(8)
    doc.add_paragraph()

    prog_colours = {"JP": "2d7d4f", "PY": "1a4d8c", "SY": "7c3aed", "STAFF": "1e6f75", "ADMIN": "92400e"}
    col = prog_colours.get(program, "1e293b")

    _section_divider(doc, "📋  MEETING DETAILS", bg_hex=col)
    _info_table(doc, [
        ("Field", "Details"),
        ("Program", prog["label"]),
        ("Date", meeting_date),
        ("Chair", chair or "—"),
        ("Location", location or "—"),
    ])

    _section_divider(doc, "🙋  ATTENDANCE", bg_hex=col)
    _attendees_table(doc, present, apologies)

    _section_divider(doc, "📝  MEETING MINUTES", bg_hex=col)
    if content.strip():
        for line in content.strip().splitlines():
            if line.strip():
                p = doc.add_paragraph(line.strip(), style="Normal")
                p.paragraph_format.space_after = Pt(2)
        doc.add_paragraph()
    else:
        doc.add_paragraph("No minutes recorded.", style="Normal")

    if action_summary.strip():
        _section_divider(doc, "✅  ACTION ITEMS", bg_hex="5b21b6")
        _actions_summary_table(doc, action_summary)

    footer_table = doc.add_table(rows=1, cols=1)
    fc = footer_table.cell(0, 0)
    _set_cell_bg(fc, "f1f5f9")
    fp = fc.paragraphs[0]
    fr = fp.add_run(f"  Generated: {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}  |  CLC Learning & Behaviour Unit  |  CONFIDENTIAL")
    fr.font.size = Pt(8); fr.font.color.rgb = RGBColor.from_string("64748b"); fr.italic = True

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()

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


def render_minutes(program, week_range=None):
    """Minutes — rich combined view for STAFF, clean team minutes for JP/PY/SY."""
    st.subheader("📝 Meeting Minutes")

    minutes_list = fetch("tm_minutes", {"program": program}, "meeting_date")

    # Linked-week notice
    if week_range:
        monday, sunday = week_range
        week_str = f"{monday.strftime('%-d %b')} – {sunday.strftime('%-d %b %Y')}"
        st.markdown(f"""
        <div style="background:#e8edf3;border:1px solid #b8cfe8;border-radius:8px;
                    padding:10px 16px;margin-bottom:14px;font-size:13px;color:#1a2e44;">
          🔗 <strong>Linked from Digital Staff Meeting</strong> — showing minutes for week of {week_str}
        </div>""", unsafe_allow_html=True)

    # ── View existing minutes ─────────────────────────────────────────────────
    if minutes_list:
        for m in minutes_list:
            auto_expand = False
            if week_range:
                try:
                    m_date = datetime.date.fromisoformat(m["meeting_date"])
                    auto_expand = week_range[0] <= m_date <= week_range[1]
                except (ValueError, KeyError):
                    pass

            is_staff = program == "STAFF"

            with st.expander(
                f"📄 {m.get('meeting_date','')} — {m.get('title','Untitled')}",
                expanded=auto_expand
            ):
                # Meeting meta
                meta_cols = st.columns(3)
                with meta_cols[0]: st.caption(f"**Chair:** {m.get('chair','—')}")
                with meta_cols[1]: st.caption(f"**Location:** {m.get('location','—')}")
                with meta_cols[2]: st.caption(f"**Date:** {m.get('meeting_date','—')}")

                # Attendees
                if m.get("attendees") or m.get("apologies"):
                    att_cols = st.columns(2)
                    with att_cols[0]:
                        st.markdown("**✅ Present**")
                        for name in (m.get("attendees") or "").split(","):
                            if name.strip(): st.markdown(f"- {name.strip()}")
                    with att_cols[1]:
                        st.markdown("**⚠️ Apologies**")
                        for name in (m.get("apologies") or "").split(","):
                            if name.strip(): st.markdown(f"- {name.strip()}")
                    st.divider()

                # Digital section (STAFF only)
                if is_staff and m.get("digital_summary"):
                    st.markdown("""
                    <div style="background:#dbeafe;border-left:4px solid #1a4d8c;
                                border-radius:6px;padding:10px 14px;margin-bottom:10px;">
                      <strong style="color:#1a4d8c;">💻 Part 1 — Digital Staff Meeting</strong>
                    </div>""", unsafe_allow_html=True)
                    st.markdown(m["digital_summary"])

                    if m.get("digital_items"):
                        st.markdown("**Items — Viewed & Actioned**")
                        try:
                            items = json.loads(m["digital_items"])
                            if items:
                                cols = st.columns([4, 2, 2, 1.5])
                                headers = ["Item / Notice", "Raised By", "Actioned By", "Status"]
                                for col, hdr in zip(cols, headers):
                                    col.markdown(f"**{hdr}**")
                                st.divider()
                                for item in items:
                                    ic = st.columns([4, 2, 2, 1.5])
                                    ic[0].write(item.get("item", ""))
                                    ic[1].write(item.get("raised_by", ""))
                                    ic[2].write(item.get("actioned_by", ""))
                                    status = item.get("status", "Noted")
                                    color  = "🟢" if "action" in status.lower() else "🟡"
                                    ic[3].write(f"{color} {status}")
                        except Exception:
                            st.markdown(m["digital_items"])
                    st.divider()

                # Main content
                if is_staff and m.get("face_to_face_content"):
                    st.markdown("""
                    <div style="background:#d1fae5;border-left:4px solid #2d7d4f;
                                border-radius:6px;padding:10px 14px;margin-bottom:10px;">
                      <strong style="color:#2d7d4f;">👥 Part 2 — Face-to-Face Meeting</strong>
                    </div>""", unsafe_allow_html=True)
                    st.markdown(m.get("face_to_face_content", ""))
                elif m.get("content"):
                    st.markdown(m["content"])

                if m.get("action_summary"):
                    st.info(f"**Actions:** {m['action_summary']}")

                # Download button
                st.markdown("")
                if is_staff:
                    try:
                        digital_items = json.loads(m.get("digital_items") or "[]")
                    except Exception:
                        digital_items = []
                    docx_bytes = generate_meeting_docx(
                        program       = program,
                        meeting_date  = m.get("meeting_date", ""),
                        chair         = m.get("chair", ""),
                        location      = m.get("location", ""),
                        present       = [n.strip() for n in (m.get("attendees") or "").split(",") if n.strip()],
                        apologies     = [n.strip() for n in (m.get("apologies") or "").split(",") if n.strip()],
                        digital_summary     = m.get("digital_summary", ""),
                        digital_items       = digital_items,
                        face_to_face_content= m.get("face_to_face_content", ""),
                        action_summary      = m.get("action_summary", ""),
                        title               = m.get("title", ""),
                    )
                else:
                    docx_bytes = generate_simple_minutes_docx(
                        program      = program,
                        meeting_date = m.get("meeting_date", ""),
                        chair        = m.get("chair", ""),
                        location     = m.get("location", ""),
                        present      = [n.strip() for n in (m.get("attendees") or "").split(",") if n.strip()],
                        apologies    = [n.strip() for n in (m.get("apologies") or "").split(",") if n.strip()],
                        content      = m.get("content", ""),
                        action_summary = m.get("action_summary", ""),
                        title        = m.get("title", ""),
                    )
                safe_title = (m.get("title") or "minutes").replace(" ", "_")
                st.download_button(
                    label    = "📥 Download Word Document",
                    data     = docx_bytes,
                    file_name= f"{safe_title}_{m.get('meeting_date','')}.docx",
                    mime     = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key      = f"dl_{m['id']}"
                )

                # Admin edit / delete
                if st.session_state.get("admin"):
                    st.divider()
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✏️ Edit", key=f"edit_min_{m['id']}"):
                            st.session_state[f"editing_min_{m['id']}"] = True
                    with col2:
                        if st.button("🗑️ Delete", key=f"del_min_{m['id']}"):
                            delete_row("tm_minutes", m["id"])
                            st.rerun()
                    if st.session_state.get(f"editing_min_{m['id']}"):
                        with st.form(f"edit_min_form_{m['id']}"):
                            etitle   = st.text_input("Title", value=m.get("title",""))
                            edate    = st.date_input("Date", value=datetime.date.fromisoformat(m["meeting_date"]) if m.get("meeting_date") else datetime.date.today())
                            echair   = st.text_input("Chair", value=m.get("chair",""))
                            eloc     = st.text_input("Location", value=m.get("location",""))
                            eatt     = st.text_input("Attendees (comma-separated)", value=m.get("attendees",""))
                            eapol    = st.text_input("Apologies (comma-separated)", value=m.get("apologies",""))
                            if program == "STAFF":
                                edigital = st.text_area("Digital meeting summary", value=m.get("digital_summary",""), height=150)
                                eff      = st.text_area("Face-to-face minutes", value=m.get("face_to_face_content",""), height=200)
                                econtent = ""
                            else:
                                edigital = ""; eff = ""
                                econtent = st.text_area("Minutes", value=m.get("content",""), height=300)
                            eactions = st.text_area("Action summary", value=m.get("action_summary",""))
                            if st.form_submit_button("Save"):
                                update_row("tm_minutes", m["id"], {
                                    "title": etitle, "meeting_date": str(edate),
                                    "chair": echair, "location": eloc,
                                    "attendees": eatt, "apologies": eapol,
                                    "digital_summary": edigital,
                                    "face_to_face_content": eff,
                                    "content": econtent,
                                    "action_summary": eactions
                                })
                                del st.session_state[f"editing_min_{m['id']}"]
                                st.rerun()
    else:
        st.info("No minutes recorded yet.")

    # ── Record new minutes (admin only) ──────────────────────────────────────
    if not st.session_state.get("admin"):
        return

    st.divider()

    if program == "STAFF":
        _render_new_staff_minutes()
    else:
        _render_new_team_minutes(program)


def _render_new_staff_minutes():
    """New combined staff meeting minutes form (digital + face-to-face)."""
    st.subheader("✍️ Record Combined Staff Meeting Minutes")

    st.markdown("""
    <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;
                padding:12px 16px;margin-bottom:16px;font-size:13px;color:#0c4a6e;">
      📋 This form combines the <strong>Digital Staff Meeting</strong> section
      (items raised online + who actioned them) with the <strong>Face-to-Face</strong>
      section into one unified, downloadable document.
    </div>""", unsafe_allow_html=True)

    with st.form("new_staff_minutes_form"):
        st.markdown("#### 📋 Meeting Details")
        c1, c2, c3 = st.columns(3)
        with c1: m_title = st.text_input("Meeting title *", placeholder="e.g. Staff Meeting — T1 W4")
        with c2: m_date  = st.date_input("Date *", value=datetime.date.today())
        with c3: m_chair = st.text_input("Chair", placeholder="e.g. Candice Cooper")
        m_location = st.text_input("Location", placeholder="e.g. Staff Room / Teams")

        st.markdown("#### 🙋 Attendance")
        att_c1, att_c2 = st.columns(2)
        with att_c1:
            m_attendees = st.text_area("Present (one per line or comma-separated)",
                                       placeholder="e.g.\nCandice Cooper\nJane Smith", height=100)
        with att_c2:
            m_apologies = st.text_area("Apologies (one per line or comma-separated)",
                                       placeholder="e.g.\nBob Jones", height=100)

        st.markdown("#### 💻 Part 1 — Digital Staff Meeting")
        m_digital_summary = st.text_area(
            "Digital meeting summary (paste or type overview of online notices/discussion)",
            placeholder="e.g. Staff reviewed 4 notices this week: timetable update, PD day reminder, student transport change, and health & safety reminder.",
            height=100
        )

        st.markdown("**Items raised — add each row below (Item | Raised By | Actioned By | Status)**")
        st.caption("Enter one item per line in format: Item description | Raised By | Actioned By | Status (e.g. Actioned / Noted / Pending)")
        m_digital_items_raw = st.text_area(
            "Digital items table",
            placeholder="Timetable update for Week 5 | Candice Cooper | All staff | Noted\nStudent transport change — JP | Admin | JP team | Actioned\nPD Day reminder 14 March | Candice Cooper | All staff | Actioned",
            height=120
        )

        st.markdown("#### 👥 Part 2 — Face-to-Face Meeting")
        ff_method = st.radio(
            "Input method",
            ["📄 Type / paste minutes directly", "🎙️ Drop transcript — AI will improve it"],
            horizontal=True
        )
        m_ff_content = st.text_area(
            "Face-to-face minutes" if "📄" in ff_method else "Paste transcript or rough notes",
            height=300,
            placeholder="Type your face-to-face meeting minutes here..." if "📄" in ff_method
            else "Paste the recorded transcript or rough notes here. AI will structure and polish them."
        )
        do_ai = "🎙️" in ff_method

        st.markdown("#### ✅ Action Items")
        m_actions = st.text_area(
            "Action items (one per line: Action | Assigned To | Due date)",
            placeholder="Update student profiles | Candice Cooper | Week 5\nBook PD venue | Admin | 14 March",
            height=80
        )

        submitted = st.form_submit_button(
            "✨ Improve with AI & Save" if do_ai else "💾 Save Combined Minutes",
            type="primary"
        )

        if submitted:
            if not m_title.strip():
                st.warning("Please enter a meeting title.")
            else:
                # Parse attendees
                attendees_str = ", ".join([
                    n.strip() for n in
                    (m_attendees.replace("\n", ",").split(","))
                    if n.strip()
                ])
                apologies_str = ", ".join([
                    n.strip() for n in
                    (m_apologies.replace("\n", ",").split(","))
                    if n.strip()
                ])

                # Parse digital items
                digital_items = []
                for line in m_digital_items_raw.splitlines():
                    parts = [p.strip() for p in line.split("|")]
                    if parts and parts[0]:
                        digital_items.append({
                            "item":        parts[0] if len(parts) > 0 else "",
                            "raised_by":   parts[1] if len(parts) > 1 else "",
                            "actioned_by": parts[2] if len(parts) > 2 else "",
                            "status":      parts[3] if len(parts) > 3 else "Noted",
                        })

                # AI improvement
                final_ff = m_ff_content.strip()
                if do_ai and final_ff:
                    with st.spinner("AI is improving your minutes…"):
                        final_ff = improve_with_ai(final_ff, "STAFF", str(m_date))

                insert("tm_minutes", {
                    "program":             "STAFF",
                    "title":               m_title.strip(),
                    "meeting_date":        str(m_date),
                    "chair":               m_chair.strip(),
                    "location":            m_location.strip(),
                    "attendees":           attendees_str,
                    "apologies":           apologies_str,
                    "digital_summary":     m_digital_summary.strip(),
                    "digital_items":       json.dumps(digital_items),
                    "face_to_face_content": final_ff,
                    "content":             "",
                    "action_summary":      m_actions.strip(),
                })
                st.success("✅ Combined meeting minutes saved!")
                st.rerun()


def _render_new_team_minutes(program):
    """New minutes form for JP/PY/SY team meetings."""
    st.subheader("✍️ Record New Minutes")

    input_method = st.radio(
        "Input method",
        ["📄 Type / paste minutes directly", "🎙️ Drop transcript — AI will improve it"],
        horizontal=True
    )

    with st.form("new_minutes_form"):
        st.markdown("#### 📋 Meeting Details")
        c1, c2, c3 = st.columns(3)
        with c1: m_title = st.text_input("Meeting title *", placeholder=f"e.g. {PROGRAMS[program]['label']} Meeting — T1 W4")
        with c2: m_date  = st.date_input("Date *", value=datetime.date.today())
        with c3: m_chair = st.text_input("Chair", placeholder="e.g. Jane Smith")
        m_location = st.text_input("Location", placeholder="e.g. Room 3 / Teams")

        st.markdown("#### 🙋 Attendance")
        att_c1, att_c2 = st.columns(2)
        with att_c1:
            m_attendees = st.text_area("Present (one per line or comma-separated)", height=90)
        with att_c2:
            m_apologies = st.text_area("Apologies (one per line or comma-separated)", height=90)

        schedules  = fetch("tm_schedules", {"program": program})
        sched_opts = {s["schedule_name"]: s["id"] for s in schedules}
        sched_opts["General / Unassigned"] = None
        m_sched = st.selectbox("Associated schedule", list(sched_opts.keys()))

        st.markdown("#### 📝 Minutes")
        if "📄" in input_method:
            m_content = st.text_area("Minutes", height=300, placeholder="Type or paste your meeting minutes here...")
            do_ai = False
        else:
            m_content = st.text_area("Paste transcript or rough notes", height=300,
                                     placeholder="AI will structure and polish these into professional minutes.")
            do_ai = True

        m_actions = st.text_area(
            "Action items (one per line: Action | Assigned To | Due date)",
            placeholder="Update student profiles | Jane Smith | Week 5",
            height=80
        )

        submitted = st.form_submit_button(
            "✨ Improve with AI & Save" if do_ai else "💾 Save Minutes",
            type="primary"
        )

        if submitted:
            if not m_title.strip():
                st.warning("Please enter a meeting title.")
            else:
                attendees_str = ", ".join([n.strip() for n in (m_attendees.replace("\n",",").split(",")) if n.strip()])
                apologies_str = ", ".join([n.strip() for n in (m_apologies.replace("\n",",").split(",")) if n.strip()])
                final_content = m_content.strip()
                if do_ai and final_content:
                    with st.spinner("AI is improving your minutes…"):
                        final_content = improve_with_ai(final_content, program, str(m_date))
                insert("tm_minutes", {
                    "program":       program,
                    "schedule_id":   sched_opts.get(m_sched),
                    "title":         m_title.strip(),
                    "meeting_date":  str(m_date),
                    "chair":         m_chair.strip(),
                    "location":      m_location.strip(),
                    "attendees":     attendees_str,
                    "apologies":     apologies_str,
                    "content":       final_content,
                    "action_summary": m_actions.strip(),
                    "digital_summary": "",
                    "digital_items":   "[]",
                    "face_to_face_content": "",
                })
                st.success("✅ Minutes saved!")
                st.rerun()


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
    week_range = get_week_from_params()

    admin_login()

    # ── Header ──
    grad_end = {
        "JP": "#3fa86a", "PY": "#2a6fd4", "SY": "#9b59b6",
        "STAFF": "#2a9fa8", "ADMIN": "#c97b1a"
    }.get(program, "#2a6fd4")

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{prog_info['color']},{grad_end});
                padding:1.5rem 2rem;border-radius:16px;margin-bottom:1.5rem;">
      <div style="font-size:2.5rem;margin-bottom:0.25rem;">{prog_info['emoji']}</div>
      <h1 style="color:white;margin:0;font-size:1.8rem;">{prog_info['label']}</h1>
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
        render_minutes(program, week_range=week_range if program == "STAFF" else None)
    with tab_actions:
        render_actions(program)
    with tab_attend:
        render_attendance(program)
    with tab_docs:
        render_documents(program)


if __name__ == "__main__":
    main()
