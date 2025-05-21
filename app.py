import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import math
from PIL import Image
import base64

# === BACKGROUND ===
def add_bg_from_local(image_file):
    with open(image_file, "rb") as file:
        encoded = base64.b64encode(file.read()).decode()
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: url("data:image/png;base64,{encoded}");
            background-size: cover;
            background-position: top left;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

# === PAGE CONFIG ===
st.set_page_config(page_title="EV Charger Feasibility", layout="wide")
add_bg_from_local("background.png")

# === LOGO ===
logo = Image.open("logo.png")
st.image(logo, width=200)

st.title("EV Charger Feasibility Dashboard")

# === TABS ===
tab1, tab2, tab3 = st.tabs(["📊 Analyzer", "📁 How to Use", "ℹ️ About Fleet Zero"])

# === PROCESSING FUNCTIONS ===
def process_tall_format(df):
    try:
        if 'Unnamed: 1' in df.columns and df.iloc[0].astype(str).str.contains("DATE", case=False, na=False).any():
            df.columns = df.iloc[0]
            df = df[1:]
        df.columns = [col.lower().strip() if isinstance(col, str) else col for col in df.columns]

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        elif 'date' in df.columns and 'time' in df.columns:
            df['timestamp'] = pd.to_datetime(df['date'] + ' ' + df['time'], errors='coerce')
        else:
            return None, "Missing 'timestamp' or 'date' + 'time' columns."

        power_col = next((col for col in df.columns if isinstance(col, str) and 'kw' in col.lower()), None)
        if power_col is None:
            return None, "No 'kW' column found."

        df["kW"] = pd.to_numeric(df[power_col], errors="coerce")
        df = df.dropna(subset=["timestamp", "kW"])
        df["hour"] = df["timestamp"].dt.hour
        hourly = df.groupby("hour")["kW"].max().reset_index()
        hourly.columns = ["Hour", "Max_Power_kW"]
        return hourly, None
    except Exception as e:
        return None, f"Error in tall format: {e}"

def process_wide_format(df):
    try:
        if df.iloc[0].astype(str).str.contains("Date", case=False, na=False).any():
            df.columns = df.iloc[0]
            df = df[1:].copy()

        df = df.rename(columns={df.columns[0]: "date"})
        
        time_cols = [col for col in df.columns if isinstance(col, str) and ":" in col]
        daily_total_col = next((col for col in df.columns if 'total' in str(col).lower() or 'kwh' in str(col).lower()), None)

        if len(time_cols) > 0:
            df_melted = df.melt(id_vars=["date"], value_vars=time_cols, var_name="time", value_name="kWh")
            df_melted["timestamp"] = pd.to_datetime(df_melted["date"] + " " + df_melted["time"], errors='coerce')
            df_melted = df_melted[df_melted['timestamp'].notna()]
            df_melted["kWh"] = pd.to_numeric(df_melted["kWh"], errors="coerce")
            df_melted = df_melted.dropna(subset=["kWh"])
            interval_guess = 0.25 if len(time_cols) >= 96 else 1.0
            df_melted["kW"] = df_melted["kWh"] / interval_guess
            df_melted["hour"] = df_melted["timestamp"].dt.hour
            hourly = df_melted.groupby("hour")["kW"].max().reset_index()
            hourly.columns = ["Hour", "Max_Power_kW"]
            return hourly, None

        elif daily_total_col:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["kWh"] = pd.to_numeric(df[daily_total_col], errors="coerce")
            df = df.dropna(subset=["date", "kWh"])
            st.warning("⚠️ Daily kWh file detected — assuming uniform 24-hour usage.")
            df["kW_avg"] = df["kWh"] / 24
            hourly = pd.DataFrame({
                "Hour": list(range(24)),
                "Max_Power_kW": [df["kW_avg"].max()] * 24
            })
            return hourly, None

        else:
            return None, "Unsupported format: no valid time columns or total kWh column found."

    except Exception as e:
        return None, f"Error in wide format: {e}"

# === TAB 1: ANALYZER ===
# === TAB 1: ANALYZER ===
with tab1:
    uploaded_files = st.file_uploader("📁 Upload load profile files", type=["csv", "xlsx"], accept_multiple_files=True)

    level2_kw = st.number_input("🔋 Global Level 2 Charger Size (kW)", min_value=1.0, value=7.2)
    level3_kw = st.number_input("⚡ Global Level 3 Charger Size (kW)", min_value=10.0, value=50.0)

    if uploaded_files:
        for uploaded_file in uploaded_files:
            st.markdown("---")
            st.subheader(f"📄 {uploaded_file.name}")

            capacity_kw = st.number_input(
                f"🏢 Utility capacity for {uploaded_file.name} (kW)",
                min_value=0.0, value=100.0, step=1.0,
                key=f"capacity_{uploaded_file.name}"
            )

            tick_spacing = st.number_input("📏 X-axis Tick Interval (hours)", min_value=1, max_value=24, value=3, step=1, key=f"tick_{uploaded_file.name}")

            st.markdown("### 📐 Y-axis Range (optional)")
            y_min = st.number_input("Minimum Y-axis (kW)", min_value=0.0, value=0.0, step=1.0, key=f"ymin_{uploaded_file.name}")
            y_max = st.number_input("Maximum Y-axis (kW)", min_value=0.0, value=0.0, step=1.0, key=f"ymax_{uploaded_file.name}")
            use_y_limits = st.checkbox("Use custom Y-axis limits", key=f"useylim_{uploaded_file.name}")

            try:
                if uploaded_file.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_file)
                else:
                    raw = pd.read_excel(uploaded_file, header=None)
                    header_row_index = None
                    for i in range(min(5, len(raw))):
                        row = raw.iloc[i].astype(str).str.lower()
                        if any('date' in cell for cell in row) and any(':' in cell for cell in row):
                            header_row_index = i
                            break
                    if header_row_index is not None:
                        df = pd.read_excel(uploaded_file, header=header_row_index)
                    else:
                        df = raw.copy()

                raw_cols = df.columns.tolist()
                time_like_cols = [col for col in raw_cols if isinstance(col, str) and ":" in col]
                has_date = any("date" in str(col).lower() for col in raw_cols)
                is_wide = has_date and len(time_like_cols) >= 20

                result, error = process_wide_format(df) if is_wide else process_tall_format(df)

                if error:
                    st.error(f"❌ {error}")
                    continue

                result["Capacity_kW"] = capacity_kw
                result["Excess_Power_kW"] = result["Capacity_kW"] - result["Max_Power_kW"]

                custom_test = st.checkbox(f"🔧 Enable Custom Charger Test for {uploaded_file.name}", key=f"custom_{uploaded_file.name}")

                if custom_test:
                    st.markdown("### ⚙️ Define Up to 5 Custom Charger Types")
                    custom_chargers = []
                    for i in range(1, 6):
                        col1, col2, col3 = st.columns([3, 3, 2])
                        with col1:
                            label = st.text_input(f"Charger {i} Name", value=f"Type-{i}", key=f"label_{uploaded_file.name}_{i}")
                        with col2:
                            kw = st.number_input(f"{label} Power (kW)", min_value=1.0, step=1.0, key=f"kw_{uploaded_file.name}_{i}")
                        with col3:
                            count = st.number_input(f"{label} Qty", min_value=0, step=1, key=f"qty_{uploaded_file.name}_{i}")
                        if count > 0:
                            custom_chargers.append({
                                "Name": label,
                                "Power_kW": kw,
                                "Quantity": count,
                                "Total_kW": kw * count
                            })

                    if custom_chargers:
                        summary_df = pd.DataFrame(custom_chargers)
                        st.markdown("### 📋 Charger Input Summary")
                        st.dataframe(summary_df)

                    total_custom_kw = sum(c["Total_kW"] for c in custom_chargers)
                    result["Custom_Load_kW"] = total_custom_kw
                    result["Total_Load_kW"] = result["Max_Power_kW"] + result["Custom_Load_kW"]

                    if (result["Total_Load_kW"] > result["Capacity_kW"]).any():
                        st.error("❌ Custom charger combination exceeds capacity at one or more hours.")
                    else:
                        st.success("✅ Custom charger combination fits within available capacity.")

                    st.markdown("### 📊 Load Analysis with Custom Chargers")
                    st.dataframe(result)

                    fig2, ax2 = plt.subplots()
                    ax2.plot(result["Hour"], result["Total_Load_kW"], label="Total Load (Usage + Custom Chargers)", color="red")
                    ax2.plot(result["Hour"], result["Capacity_kW"], label="Capacity", color="green", linestyle="--")
                    ax2.set_xlabel("Hour")
                    ax2.set_ylabel("Power (kW)")
                    ax2.set_xticks(range(0, 24, tick_spacing))
                    if use_y_limits and y_max > y_min:
                        ax2.set_ylim(y_min, y_max)
                    ax2.set_title(f"{uploaded_file.name} – Custom Load vs Capacity")
                    ax2.legend()
                    st.pyplot(fig2)

                    csv = result.to_csv(index=False).encode("utf-8")
                    st.download_button("📥 Download CSV", data=csv, file_name=f"{uploaded_file.name}_custom_analysis.csv")

            except Exception as e:
                st.error(f"❌ Failed to process {uploaded_file.name}: {str(e)}")





# === TAB 2: HOW TO USE ===
with tab2:
    st.header("📁 How to Use This Tool")
    st.markdown("""
    This tool helps you calculate **available power** at EV charging sites using load profile files and utility power input.

    ---
    ### 🛠 Step-by-Step Instructions

    **1. Prepare your data**
    - Use 15-minute or 1-hour interval load profile files (CSV or Excel)
    - Ensure the first column is the **Date** and the rest are time intervals (e.g., `0:15`, `1:00`, ...)

    **2. Upload files**
    - Upload one or more usage files using the uploader under the **"📊 Analyzer" tab**

    **3. Enter site details**
    - For each site, enter the **utility power capacity (in kW)**
    - Set your Level 2 and Level 3 charger sizes (these apply to all files)

    **4. Review output**
    - The tool will calculate:
        - Hourly maximum demand
        - Excess available power
        - Number of Level 2 / Level 3 chargers that can be supported
    - View line charts and download analysis CSVs

    ---
    ### 🧮 Calculation Rules

    - 15-min kWh data → `Power = Energy / 0.25`
    - 1-hour kWh data → `Power = Energy / 1.0`
    - Chargers = `Excess Power / Charger kW`

    ---
    ### 📎 Need Help?

    Contact **Fleet Zero** at: [info@fleetzero.ai](mailto:info@fleetzero.ai)
    """)

# === TAB 3: ABOUT ===
with tab3:
    st.header("🌱 About Fleet Zero")
    st.markdown("""
Fleet Zero is your trusted advisor and solution provider for your fleet transition journey.

We help **light to heavy duty fleets** navigate their route to **zero emissions** by offering:
- 🎯 Strategic fleet electrification planning
- 🔌 Charging infrastructure design and analysis
- 🧠 Data-driven operational insights
- 🛠 Turnkey transition support

Our **sustainable and experienced team** removes the complexity so you can focus on staying on the road.

---

📍 **Website**: [fleetzero.ai](https://fleetzero.ai)  
📧 **Email**: [info@fleetzero.ai](mailto:info@fleetzero.ai)
""")
