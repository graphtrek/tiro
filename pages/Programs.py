"""Programs page — generate and manage dynamic FastAPI programs via Qwen."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import requests
import streamlit as st
from helpers.chat_ui import render_page_nav
from helpers.program_generator import plan_program_iteration

_GENERATED_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "generated_programs"


def _save_plan_for_program(program_id: str, plan_text: str) -> None:
    matches = list(_GENERATED_DIR.glob(f"*-{program_id}"))
    if matches:
        (matches[0] / "plan.md").write_text(plan_text, encoding="utf-8")


def _load_plan_for_program(program_id: str) -> str | None:
    matches = list(_GENERATED_DIR.glob(f"*-{program_id}"))
    if matches:
        plan_path = matches[0] / "plan.md"
        if plan_path.exists():
            return plan_path.read_text(encoding="utf-8")
    return None

MANAGER_URL = os.environ.get("MANAGER_API_URL", "http://localhost:8500")
PROGRAMS_HOST = os.environ.get("PROGRAMS_HOST", "localhost")

st.set_page_config(page_title="Programs", page_icon="⚙️", layout="wide")

render_page_nav("⚙️ Programs")

st.markdown(
    """
    <style>
    div[data-testid="stButton"] > button {
        font-size: 0.75rem;
        padding: 0.25rem 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("⚙️ Dynamic Program Generator")
st.caption(f"Manager API: `{MANAGER_URL}`")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _api(method: str, path: str, **kwargs):
    """Make a request to the manager API and surface errors cleanly."""
    try:
        resp = requests.request(method, f"{MANAGER_URL}{path}", timeout=120, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot reach Manager API at `{MANAGER_URL}`. "
            "Make sure `graphtrek-ai-manager` is running."
        )
        return None
    except requests.exceptions.HTTPError as exc:
        st.error(f"API error {exc.response.status_code}: {exc.response.text}")
        return None


def _status_badge(status: str) -> str:
    return "🟢" if status == "running" else "🔴"


def _parse_plan(plan_text: str) -> dict:
    """Extract fields from a structured plan produced by the LLM.

    Returns a dict with keys: name, description, requirements, mode.
    Any section that is missing falls back to an empty string.
    """
    heading_re = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    headings = list(heading_re.finditer(plan_text))
    sections: dict[str, str] = {}
    for i, match in enumerate(headings):
        title = match.group(1).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(plan_text)
        sections[title.lower()] = plan_text[start:end].strip()

    def _get(*keys: str) -> str:
        for k in keys:
            for sec_key, val in sections.items():
                if k in sec_key:
                    return val
        return ""

    raw_name = _get("program name", "name")
    # Normalise to kebab-case slug (keep only alphanumeric + hyphen)
    slug = re.sub(r"[^a-z0-9]+", "-", raw_name.lower()).strip("-") if raw_name else ""

    mode_raw = _get("execution mode", "mode").lower()
    mode = "on_demand" if "on_demand" in mode_raw or "on demand" in mode_raw else "service"

    return {
        "name": slug,
        "description": _get("description"),
        "requirements": _get("requirements", "endpoints"),
        "mode": mode,
    }


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_plan, tab_generate = st.tabs(["📋 Plan", "➕ Generate"])

# ── Plan tab ──────────────────────────────────────────────────────────────────

with tab_plan:
    st.markdown("### 📋 Plan your program iteratively")
    st.caption(
        "Describe what you want to build. "
        "Every iteration: searches the web (DuckDuckGo), fetches any URLs you paste in, "
        "and takes your already-generated programs into account — so the new plan stays "
        "consistent with what you've built. "
        "When happy, click **Accept & Implement** to pre-fill the Generate form."
    )

    # Init session state
    if "plan_conversation" not in st.session_state:
        st.session_state["plan_conversation"] = []  # list[dict] role/content
    if "plan_latest" not in st.session_state:
        st.session_state["plan_latest"] = ""

    plan_conv: list[dict] = st.session_state["plan_conversation"]

    if st.session_state.pop("plan_restored", False):
        st.success("♻️ Plan visszatöltve a mentett fájlból.")

    if st.session_state.pop("plan_accepted", False):
        modify_pending = st.session_state.get("modify_id")
        if modify_pending:
            st.success("✅ Plan elfogadva! Váltson a **➕ Generate** tabra és kattintson a **Regenerate / Generate** gombra.")
        else:
            st.success("✅ Plan elfogadva! Váltson a **➕ Generate** tabra és kattintson a **Generate** gombra.")

    # Show conversation history
    if plan_conv:
        for msg in plan_conv:
            if msg["role"] == "user":
                # Strip the appended web-search block before displaying
                display_text = msg["content"].split("\n\n=== Referenced URL Content")[0]
                display_text = display_text.split("\n\n=== Web Search Results")[0]
                with st.chat_message("user"):
                    st.markdown(display_text)
            else:
                with st.chat_message("assistant"):
                    st.markdown(msg["content"])

    # Input row
    is_first = len(plan_conv) == 0
    placeholder_text = (
        "Describe what you want to build…"
        if is_first
        else "Refine the plan (e.g. add an endpoint, change the mode, ask a question)…"
    )
    plan_input = st.text_area(
        "Your message",
        placeholder=placeholder_text,
        height=120,
        key="plan_input_area",
        label_visibility="collapsed",
    )

    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 6])
    search_clicked = btn_col1.button("🔍 Search & Plan", type="primary", key="plan_search_btn")
    reset_clicked = btn_col2.button("🗑️ Reset", key="plan_reset_btn")
    accept_clicked = btn_col3.button(
        "✅ Accept & Implement",
        key="plan_accept_btn",
        disabled=not st.session_state.get("plan_latest", ""),
    )

    if reset_clicked:
        st.session_state["plan_conversation"] = []
        st.session_state["plan_latest"] = ""
        st.rerun()

    if search_clicked:
        if not plan_input.strip():
            st.warning("Please enter a description or refinement before searching.")
        else:
            with st.spinner("Searching the web and planning with Qwen… this may take a moment."):
                try:
                    # Build history without the raw augmented messages (clean roles only)
                    clean_history = plan_conv  # already role/content dicts
                    plan_text = plan_program_iteration(plan_input.strip(), clean_history)
                    # Store in conversation
                    st.session_state["plan_conversation"].append(
                        {"role": "user", "content": plan_input.strip()}
                    )
                    st.session_state["plan_conversation"].append(
                        {"role": "assistant", "content": plan_text}
                    )
                    st.session_state["plan_latest"] = plan_text
                except Exception as exc:
                    st.error(f"Planning failed: {exc}")
            st.rerun()

    if accept_clicked and st.session_state.get("plan_latest"):
        parsed = _parse_plan(st.session_state["plan_latest"])
        # Write directly into the form widget keys so the values survive reruns
        st.session_state["gen_name"] = parsed["name"]
        st.session_state["gen_description"] = parsed["description"]
        st.session_state["gen_requirements"] = parsed["requirements"]
        st.session_state["gen_mode"] = parsed["mode"]
        st.session_state["plan_prefilled"] = True
        st.session_state["pending_plan_save"] = st.session_state["plan_latest"]
        st.session_state["plan_accepted"] = True
        st.rerun()

# ── Generate / Modify tab ─────────────────────────────────────────────────────

with tab_generate:
    # Apply any pending prefill values BEFORE widgets are instantiated
    for _k in ["gen_name", "gen_description", "gen_requirements", "gen_mode"]:
        _pk = f"_prefill_{_k}"
        if _pk in st.session_state:
            st.session_state[_k] = st.session_state.pop(_pk)
    # Initialize form widget keys with empty defaults if not already set
    for _k, _v in [("gen_name", ""), ("gen_description", ""),
                   ("gen_requirements", ""), ("gen_mode", "service")]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    if st.session_state.pop("plan_prefilled", False):
        st.info("Fields pre-filled from the accepted plan. Review and click **Generate**.")

    modify_id = st.session_state.get("modify_id")
    modify_orig = st.session_state.get("modify_orig", {})

    if modify_id:
        expander_label = f"✏️ Modify: {modify_orig.get('name', modify_id)}"
    else:
        expander_label = "➕ Generate a new program"

    with st.expander(expander_label, expanded=True):
        if modify_id:
            if st.button("Cancel", key="cancel_modify"):
                del st.session_state["modify_id"]
                del st.session_state["modify_orig"]
                st.session_state["gen_name"] = ""
                st.session_state["gen_description"] = ""
                st.session_state["gen_requirements"] = ""
                st.session_state["gen_mode"] = "service"
                st.rerun()

        with st.form("generate_form"):
            col1, col2 = st.columns(2)
            with col1:
                prog_name = st.text_input(
                    "Program name",
                    key="gen_name",
                    placeholder="e.g. currency-converter",
                )
                mode = st.selectbox(
                    "Execution mode",
                    ["service", "on_demand"],
                    key="gen_mode",
                )
            with col2:
                description = st.text_area(
                    "Description",
                    key="gen_description",
                    placeholder="What should this API do?",
                    height=200,
                )
            requirements = st.text_area(
                "Requirements / endpoints",
                key="gen_requirements",
                placeholder=(
                    "e.g.\n"
                    "- GET /convert?from=USD&to=EUR&amount=100 → returns converted amount\n"
                    "- Use an in-memory exchange rate table"
                ),
                height=120,
            )
            btn_label = "Regenerate / Generate" if modify_id else "Generate"
            submitted = st.form_submit_button(btn_label, type="primary")

        if submitted:
            if not prog_name or not description or not requirements:
                st.warning("Please fill in all fields.")
            elif modify_id:
                # Always regenerate in-place (same ID/port), update all fields
                with st.spinner("Regenerating program with Qwen…"):
                    result = _api(
                        "POST",
                        f"/programs/{modify_id}/regenerate",
                        json={
                            "description": description,
                            "name": prog_name,
                            "requirements": requirements,
                            "mode": mode,
                        },
                    )
                if result:
                    pending_plan = st.session_state.pop("pending_plan_save", None)
                    if pending_plan:
                        _save_plan_for_program(result["id"], pending_plan)
                    st.success(
                        f"Program **{result['name']}** regenerated in-place — "
                        f"ID `{result['id']}`, port **{result['port']}**"
                    )
                    del st.session_state["modify_id"]
                    del st.session_state["modify_orig"]
                    st.rerun()
                else:
                    # Regenerate failed (e.g. program was deleted) — fall back to new program
                    st.warning(
                        "A program nem található (lehet, hogy törölve lett). "
                        "Kattintson mégegyszer a gombra új programként való létrehozáshoz."
                    )
                    del st.session_state["modify_id"]
                    if "modify_orig" in st.session_state:
                        del st.session_state["modify_orig"]
            else:
                with st.spinner("Generating program with Qwen…"):
                    result = _api(
                        "POST",
                        "/programs/generate",
                        json={
                            "name": prog_name,
                            "description": description,
                            "requirements": requirements,
                            "mode": mode,
                        },
                    )
                if result:
                    pending_plan = st.session_state.pop("pending_plan_save", None)
                    if pending_plan:
                        _save_plan_for_program(result["id"], pending_plan)
                    st.success(
                        f"Program **{result['name']}** created — ID `{result['id']}`, "
                        f"port **{result['port']}**"
                    )
                    st.rerun()

# ── Program list ──────────────────────────────────────────────────────────────

st.subheader("Programs")

programs = _api("GET", "/programs") or []

if not programs:
    st.info("No programs yet. Generate one above.")
else:
    for prog in programs:
        prog_id = prog["id"]
        status = prog.get("status", "stopped")
        port = prog["port"]

        with st.container(border=True):
            header_col, action_col = st.columns([3, 2])
            with header_col:
                st.markdown(
                    f"{_status_badge(status)} **{prog['name']}** "
                    f"&nbsp; `{prog_id}` &nbsp; port **{port}**"
                )
                st.caption(prog.get("description", ""))
                if status == "running":
                    st.markdown(
                        f"[Open API docs →](http://{PROGRAMS_HOST}:{port}/docs)"
                        f" &nbsp; [Health check](http://{PROGRAMS_HOST}:{port}/health)"
                    )
            with action_col:
                btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
                if status == "stopped":
                    if btn_col1.button("Start", key=f"start_{prog_id}"):
                        res = _api("POST", f"/programs/{prog_id}/start")
                        if res:
                            st.rerun()
                else:
                    if btn_col1.button("Stop", key=f"stop_{prog_id}"):
                        res = _api("POST", f"/programs/{prog_id}/stop")
                        if res:
                            st.rerun()

                if btn_col2.button("Delete", key=f"del_{prog_id}"):
                    _api("DELETE", f"/programs/{prog_id}")
                    st.rerun()

                if btn_col3.button("Code", key=f"code_{prog_id}"):
                    st.session_state[f"show_code_{prog_id}"] = not st.session_state.get(
                        f"show_code_{prog_id}", False
                    )

                if btn_col4.button("Modify", key=f"modify_{prog_id}"):
                    st.session_state["modify_id"] = prog_id
                    st.session_state["modify_orig"] = {
                        "name": prog.get("name", ""),
                        "description": prog.get("description", ""),
                        "requirements": prog.get("requirements", ""),
                        "mode": prog.get("mode", "service"),
                    }
                    # Stage prefill values; applied before widgets render on next run
                    st.session_state["_prefill_gen_name"] = prog.get("name", "")
                    st.session_state["_prefill_gen_description"] = prog.get("description", "")
                    st.session_state["_prefill_gen_requirements"] = prog.get("requirements", "")
                    st.session_state["_prefill_gen_mode"] = prog.get("mode", "service")
                    # Restore saved plan if available
                    saved_plan = _load_plan_for_program(prog_id)
                    if saved_plan:
                        st.session_state["plan_conversation"] = [
                            {"role": "assistant", "content": saved_plan}
                        ]
                        st.session_state["plan_latest"] = saved_plan
                        st.session_state["plan_restored"] = True
                    st.rerun()

            # Code viewer / editor
            if st.session_state.get(f"show_code_{prog_id}"):
                code_data = _api("GET", f"/programs/{prog_id}/code")
                if code_data:
                    new_code = st.text_area(
                        "Source code (edit and save to update)",
                        value=code_data["code"],
                        height=350,
                        key=f"editor_{prog_id}",
                    )
                    if st.button("Save changes", key=f"save_{prog_id}"):
                        res = _api(
                            "PUT",
                            f"/programs/{prog_id}/code",
                            json={"code": new_code},
                        )
                        if res:
                            st.success("Code updated. Restart the program to apply changes.")

            # Logs + Download row
            logs_key = f"show_logs_{prog_id}"
            bottom_col1, bottom_col2, bottom_col3, bottom_col4 = st.columns([1, 1, 1, 5])
            if bottom_col1.button("Logs", key=f"logs_btn_{prog_id}"):
                st.session_state[logs_key] = not st.session_state.get(logs_key, False)

            if bottom_col2.button("Download", key=f"download_btn_{prog_id}"):
                zip_resp = requests.get(
                    f"{MANAGER_URL}/programs/{prog_id}/download", timeout=30
                )
                if zip_resp.ok:
                    st.session_state[f"zip_data_{prog_id}"] = zip_resp.content
                else:
                    st.error(f"Download failed: {zip_resp.status_code}")

            if st.session_state.get(f"zip_data_{prog_id}"):
                bottom_col3.download_button(
                    label="Save ZIP",
                    data=st.session_state[f"zip_data_{prog_id}"],
                    file_name=f"{prog['name']}.zip",
                    mime="application/zip",
                    key=f"save_zip_{prog_id}",
                )

            if st.session_state.get(logs_key):
                logs_data = _api("GET", f"/programs/{prog_id}/logs", params={"lines": 200})
                if logs_data:
                    log_text = logs_data.get("logs", "(no output yet)")
                    st.code(log_text or "(no output yet)", language="text")
