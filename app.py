import streamlit as st
import requests
import pandas as pd
import json
import time

API_URL = "http://127.0.0.1:8000"
st.set_page_config(page_title="Prompt Improver", layout="wide")

st.title("Prompt Improver Agent")

st.sidebar.header("Project Config")
project_slug = st.sidebar.text_input("Project Slug", value="news-summarizer")

tab1, tab2, tab3 = st.tabs(["1. Define & Create", "2. Data & Testing", "3. Optimization & Results"])

with tab1:
    st.header("Create New Prompt Project")
    initial_prompt = st.text_area("Initial Prompt", height=150, value="Summarize this article: {{article}}")
    if st.button("Create Project"):
        try:
            resp = requests.post(f"{API_URL}/create_project", json={"slug": project_slug, "initial_prompt": initial_prompt})
            if resp.status_code == 200:
                st.success(f"Project '{project_slug}' created!")
            else:
                st.error(resp.json().get("detail", "Error"))
        except Exception as e:
            st.error(f"Connection Error: {e}")

with tab2:
    st.header("Synthetic Test Data")
    num_cases = st.slider("Number of Test Cases", 1, 5, 3)
    if st.button("Generate Test Cases"):
        with st.spinner("Teacher AI is inventing test cases..."):
            resp = requests.post(f"{API_URL}/generate_tests", json={"slug": project_slug, "num_cases": num_cases})
            if resp.status_code == 200:
                st.success("Data Generated!")
                st.json(resp.json().get("data", []))
            else:
                st.error("Failed to generate data")

with tab3:
    st.header("Optimization Dashboard")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown("### Auto-Optimize")
        target_loops = st.slider("Target Iterations", min_value=1, max_value=10, value=3)
        
        if st.button("Run Auto-Loop", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i in range(target_loops):
                status_text.text(f"Running Iteration {i+1}/{target_loops}...")
                
                try:
                    resp = requests.post(f"{API_URL}/optimize", json={"slug": project_slug})
                    if resp.status_code != 200:
                        st.error(f"Error on loop {i+1}: {resp.text}")
                        break
                except Exception as e:
                    st.error(f"Connection failed: {e}")
                    break
                
                progress_bar.progress((i + 1) / target_loops)
                time.sleep(1)
                
            status_text.text("Optimization Sequence Complete!")
            st.rerun()

    with col2:
        st.markdown("### Performance History")
        
        try:
            hist_resp = requests.get(f"{API_URL}/get_history", params={"slug": project_slug})
            if hist_resp.status_code == 200:
                history = hist_resp.json()
                
                if history:
                    df = pd.DataFrame(history)
                    
                    st.line_chart(df, x="version", y="score")
                    
                    latest = history[-1]
                    st.metric(
                        label=f"Latest Score (v{latest['version']})", 
                        value=f"{latest['score']:.1f}%",
                        delta=f"{latest['pass_count']} passing / {latest['fail_count']} failing"
                    )
                else:
                    st.info("No evaluation history yet. Run the optimizer to see data.")
        except Exception:
            st.warning("Could not connect to history endpoint.")

    st.divider()

    st.subheader("Prompt Evolution")
    
    prompt_resp = requests.get(f"{API_URL}/get_prompt", params={"slug": project_slug})
    if prompt_resp.status_code == 200:
        p_data = prompt_resp.json()
        
        st.markdown(f"**Current Version: v{p_data['version']}**")
        
        with st.expander("See Prompt Template", expanded=True):
            st.code(p_data['template_text'], language="jinja2")
            
        if p_data.get('rationale'):
            st.info(f"**AI Rationale:** {p_data['rationale']}")