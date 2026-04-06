"""Programs page — generate and manage dynamic FastAPI programs via Qwen."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import streamlit as st
from helpers.chat_ui import render_page_nav

MANAGER_URL = os.environ.get("MANAGER_API_URL", "http://localhost:8500")

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


# ── Generate form ─────────────────────────────────────────────────────────────

# ── Generate / Modify form ───────────────────────────────────────────────────

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
            st.rerun()

    with st.form("generate_form"):
        col1, col2 = st.columns(2)
        with col1:
            prog_name = st.text_input(
                "Program name",
                value=modify_orig.get("name", ""),
                placeholder="e.g. currency-converter",
            )
            mode = st.selectbox(
                "Execution mode",
                ["service", "on_demand"],
                index=["service", "on_demand"].index(modify_orig.get("mode", "service")),
            )
        with col2:
            description = st.text_area(
                "Description",
                value=modify_orig.get("description", ""),
                placeholder="What should this API do?",
                height=200,
            )
        requirements = st.text_area(
            "Requirements / endpoints",
            value=modify_orig.get("requirements", ""),
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
            # Check what changed vs original
            desc_changed = description != modify_orig.get("description", "")
            other_changed = (
                prog_name != modify_orig.get("name", "")
                or requirements != modify_orig.get("requirements", "")
                or mode != modify_orig.get("mode", "service")
            )

            if other_changed:
                # Name / requirements / mode changed → create new program
                with st.spinner("Generating new program with Qwen…"):
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
                    st.success(
                        f"Program **{result['name']}** created — ID `{result['id']}`, "
                        f"port **{result['port']}**"
                    )
                    del st.session_state["modify_id"]
                    del st.session_state["modify_orig"]
                    st.rerun()
            elif desc_changed:
                # Only description changed → regenerate in-place
                with st.spinner("Regenerating program with Qwen…"):
                    result = _api(
                        "POST",
                        f"/programs/{modify_id}/regenerate",
                        json={"description": description},
                    )
                if result:
                    st.success(
                        f"Program **{result['name']}** regenerated in-place — "
                        f"ID `{result['id']}`, port **{result['port']}**"
                    )
                    del st.session_state["modify_id"]
                    del st.session_state["modify_orig"]
                    st.rerun()
            else:
                st.info("No changes detected.")
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
                        f"[Open API docs →](http://localhost:{port}/docs)"
                        f" &nbsp; [Health check](http://localhost:{port}/health)"
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

            # Logs viewer
            logs_key = f"show_logs_{prog_id}"
            if st.button("Logs", key=f"logs_btn_{prog_id}"):
                st.session_state[logs_key] = not st.session_state.get(logs_key, False)

            if st.session_state.get(logs_key):
                logs_data = _api("GET", f"/programs/{prog_id}/logs", params={"lines": 200})
                if logs_data:
                    log_text = logs_data.get("logs", "(no output yet)")
                    st.code(log_text or "(no output yet)", language="text")
