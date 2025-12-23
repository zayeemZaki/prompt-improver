import difflib
import time
from typing import Any, Dict, List, Optional, Tuple
import os
import pandas as pd
import requests
import streamlit as st

API_URL = "http://127.0.0.1:8000"

def init_state() -> None:
    defaults = {
        "project_slug": None,
        "creation_error": None,
        "data_generated": False,
        "current_step": "1. Define Task",
        "initial_prompt_input": "Summarize this article: {{article}}",
        "scroll_to_results": False,
        "test_cases": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[str]]:
    try:
        response = requests.get(f"{API_URL}{path}", params=params, timeout=20)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as exc:
        return None, f"API request failed: {exc}"
    except ValueError:
        return None, "Invalid response from server."


def api_post(path: str, payload: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    try:
        response = requests.post(f"{API_URL}{path}", json=payload)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as exc:
        return None, f"API request failed: {exc}"
    except ValueError:
        return None, "Invalid response from server."


def handle_create_project() -> None:
    prompt_text = st.session_state.initial_prompt_input.strip()
    if not prompt_text:
        st.session_state.creation_error = "Initial prompt is required."
        return

    data, error = api_post("/create_project", {"initial_prompt": prompt_text})
    if error:
        st.session_state.creation_error = error
        return

    st.session_state.project_slug = data.get("slug")
    st.session_state.creation_error = None
    st.session_state.data_generated = False
    st.session_state.current_step = "2. Generate Data"


def go_to_step(step: str) -> None:
    st.session_state.current_step = step


def reset_project() -> None:
    st.session_state.project_slug = None
    st.session_state.creation_error = None
    st.session_state.data_generated = False
    st.session_state.current_step = "1. Define Task"


def show_diff(previous: str, current: str) -> None:
    diff = difflib.ndiff(previous.splitlines(), current.splitlines())
    changes_found = False
    for line in diff:
        if line.startswith("+ "):
            st.markdown(f"<span style='color: green;'>+ {line[2:]}</span>", unsafe_allow_html=True)
            changes_found = True
        elif line.startswith("- "):
            st.markdown(f"<span style='color: red;'>- {line[2:]}</span>", unsafe_allow_html=True)
            changes_found = True
        elif line.startswith("  "):
            st.markdown(line[2:])
    if not changes_found:
        st.info("No text changes detected in this version.")


def fetch_history(slug: str) -> List[Dict[str, Any]]:
    data, error = api_get("/get_history", params={"slug": slug})
    if error:
        st.error(error)
        return []
    return data or []


st.set_page_config(page_title="Prompt Improver", layout="wide")
init_state()

steps = ["1. Define Task", "2. Generate Data", "3. Optimize & Analyze"]

st.title("Prompt Improver")
st.radio("Workflow", steps, horizontal=True, key="current_step", label_visibility="collapsed")
st.divider()

# === STEP 1: DEFINE ===
if st.session_state.current_step == "1. Define Task":
    st.header("Define Your Task")
    if st.session_state.creation_error:
        st.error(st.session_state.creation_error)

    st.text_area(
        "Initial Prompt",
        height=150,
        key="initial_prompt_input",
    )
    actions = st.columns([1, 1])
    actions[0].button("Create Project", type="primary", on_click=handle_create_project)
    actions[1].button("Reset", on_click=reset_project)

# === STEP 2: GENERATE DATA ===
elif st.session_state.current_step == "2. Generate Data":
    if not st.session_state.project_slug:
        st.warning("Create a project first.")
    else:
        st.header("Synthetic Test Data")
        st.write("Generate test cases to unlock the optimizer.")
        num_cases = st.slider("Number of test cases", 1, 20, 5)

        if st.button("Generate Test Cases", type="primary"):
            with st.spinner("Generating test data..."):
                data, error = api_post(
                    "/generate_tests",
                    {"slug": st.session_state.project_slug, "num_cases": num_cases},
                )
            if error:
                st.error(error)
            else:
                st.session_state.data_generated = True
                st.session_state.test_cases = data.get("data", [])
                st.success("Test data generated.")
                time.sleep(0.3)

        if st.session_state.test_cases:
            with st.expander("🔎 View Generated Test Cases", expanded=True):
                st.json(st.session_state.test_cases)

        st.button("Proceed to Optimization", on_click=lambda: go_to_step("3. Optimize & Analyze"))

# === STEP 3: OPTIMIZE & ANALYZE ===
elif st.session_state.current_step == "3. Optimize & Analyze":
    if not st.session_state.project_slug:
        st.warning("Create a project first.")
    else:
        st.header("Optimization Studio")

        results_anchor = st.empty()
        results_anchor.markdown("<div id='results-anchor'></div>", unsafe_allow_html=True)

        col_controls, col_results = st.columns([1, 3])

        history = fetch_history(st.session_state.project_slug)

        with col_results:
            metrics_container = st.container()
            chart_placeholder = st.empty()
            tabs_placeholder = st.empty()

        def render_dashboard(history_data: List[Dict[str, Any]]) -> None:
            if not history_data:
                with chart_placeholder:
                    st.info("No history yet. Generate data and run the optimizer.")
                return

            latest = history_data[-1]
            best = max(history_data, key=lambda item: item.get("score", 0))

            with metrics_container:
                metrics_container.empty()
                m1, m2, m3 = metrics_container.columns(3)
                m1.metric("Current Score", f"{latest.get('score', 0):.1f}%", f"v{latest.get('version', 1)}")
                m2.metric("Best Score", f"{best.get('score', 0):.1f}%", f"v{best.get('version', 1)}")
                trend = "Improving" if latest.get("score", 0) >= best.get("score", 0) else "Regression"
                m3.metric("Trend", trend)

            df = pd.DataFrame(history_data)
            chart_placeholder.line_chart(df, x="version", y="score")

            with tabs_placeholder.container():
                tab_diff, tab_raw = st.tabs(["Prompt Diff", "Raw Data"])

                with tab_diff:
                    if len(history_data) > 1:
                        previous = history_data[-2]
                        st.markdown(
                            f"Latest change: v{previous.get('version')} to v{latest.get('version')}"
                        )
                        rationale = latest.get("rationale")
                        if rationale:
                            st.info(rationale)
                        show_diff(previous.get("template_text", ""), latest.get("template_text", ""))
                    else:
                        st.info("Run additional iterations to see diffs.")
                        if latest.get("template_text"):
                            st.code(latest["template_text"])

                with tab_raw:
                    st.json(latest)

        if history:
            render_dashboard(history)
        else:
            with col_results:
                st.info("No evaluation history available yet.")

        with col_controls:
            st.subheader("Run Optimizer")
            loops = st.slider("Iterations", 1, 10, 3)
            run_disabled = not st.session_state.data_generated
            if run_disabled:
                st.caption("Generate test data to enable optimization.")

            if st.button("Run Optimizer", type="primary", disabled=run_disabled):
                st.session_state.scroll_to_results = True
                progress = st.progress(0)
                status = st.empty()

                for iteration in range(loops):
                    status.write(f"Iteration {iteration + 1} of {loops}...")
                    _, error = api_post("/optimize", {"slug": st.session_state.project_slug})
                    if error:
                        st.error(error)
                        break

                    history = fetch_history(st.session_state.project_slug)
                    render_dashboard(history)
                    progress.progress((iteration + 1) / loops)
                    time.sleep(0.2)
                else:
                    status.success("Optimization complete.")

        if st.session_state.scroll_to_results:
            st.markdown(
                """
                <script>
                    const el = document.getElementById('results-anchor');
                    if (el) { el.scrollIntoView({behavior: 'smooth'}); }
                </script>
                """,
                unsafe_allow_html=True,
            )
            st.session_state.scroll_to_results = False
