#!/bin/bash

# 1. Run the Backend INTERNALLY on port 8000
uvicorn api:app --host 0.0.0.0 --port 8000 &

# 2. Run the Frontend PUBLICLY on port 7860 (The "Main Stage")
streamlit run app.py --server.port 7860 --server.address 0.0.0.0