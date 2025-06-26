
import streamlit as st
import pandas as pd
import numpy as np
import openai, os
import matplotlib.pyplot as plt
from datetime import date

st.set_page_config(page_title="Resin Purchase & Production Advisor", layout="wide")
st.title("📈 Resin Purchase & Production Advisor")

st.markdown(
"""* Corporate **Resin Games Plan**  
* FG capacity 500 t  
* Historical price chart (USD/t) + dotted 3‑month forecast  
* **AI Outlook** – ใช้เพียง `OPENAI_API_KEY` เท่านั้น (ไม่มี NewsAPI)"""
)

# Sidebar parameters (unchanged) ...
