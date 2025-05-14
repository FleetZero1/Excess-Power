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
def compute_optimal_mix(result, charger_sizes, label_prefix):
    charger_sizes = sorted([int(s) for s in charger_sizes], reverse=True)
    for size in charger_sizes:
        result[f"Opt_{label_prefix}_{size}kW"] = 0
    result[f"Opt_{label_prefix}_Used_kW"] = 0
    result[f"Opt_{label_prefix}_Remaining_kW"] = result["Excess_Power_kW"]

    for i, row in result.iterrows():
        remaining = row["Excess_Power_kW"]
        used = 0
        combo = {}
        for size in charger_sizes:
            count = math.floor(remaining / size)
            used += count * size
            remaining -= count * size
            combo[size] = count
        for size in charger_sizes:
            result.at[i, f"Opt_{label_prefix}_{size}kW"] = combo[size]
        result.at[i, f"Opt_{label_prefix}_Used_kW"] = used
        result.at[i, f"Opt_{label_prefix}_Remaining_kW"] = remaining
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

                result, error = process_wide_format(df) if df.shape[1] > 10 else process_tall_format(df)
                if error:
                    st.error(f"❌ {error}")
                    continue

                result["Capacity_kW"] = capacity_kw
                result["Excess_Power_kW"] = result["Capacity_kW"] - result["Max_Power_kW"]
                result["L2_Global_Count"] = result["Excess_Power_kW"].apply(lambda x: math.floor(x / level2_kw))
                result["L3_Global_Count"] = result["Excess_Power_kW"].apply(lambda x: math.floor(x / level3_kw))

                if st.checkbox(f"🔍 Check custom charger feasibility for {uploaded_file.name}", key=f"custom_{uploaded_file.name}"):
                    st.markdown("**Enter custom charger sizes and desired counts**")

                    custom_l2 = st.text_input("🔌 Level 2 chargers (size,count) e.g., 7.2:4, 11:2", key=f"l2_input_{uploaded_file.name}")
                    custom_l3 = st.text_input("⚡ Level 3 chargers (size,count) e.g., 50:1, 150:2", key=f"l3_input_{uploaded_file.name}")

                    def validate_chargers(input_str, label):
                        try:
                            chargers = [s.strip() for s in input_str.split(",") if ":" in s]
                            for c in chargers:
                                size, count = map(float, c.split(":"))
                                total_kw = size * count
                                result[f"{label}_{int(size)}kW_Count"] = int(count)
                                result[f"{label}_{int(size)}kW_Used_kW"] = total_kw
                                result[f"{label}_{int(size)}kW_Valid"] = result["Excess_Power_kW"] >= total_kw
                                if not result[f"{label}_{int(size)}kW_Valid"].all():
                                    st.error(f"❌ {label} {int(size)}kW charger x{int(count)} exceeds available power at some hours.")
                        except Exception:
                            st.warning(f"⚠️ Invalid format in {label} input. Use format like '50:2, 150:1'")

                    if custom_l2:
                        validate_chargers(custom_l2, "L2_Custom")
                    if custom_l3:
                        validate_chargers(custom_l3, "L3_Custom")

                st.markdown("#### 🚀 Optimal Level 3 Charger Mix")
opt_sizes_input = st.text_input("Suggest optimal mix from these Level 3 sizes (kW)", value="150, 250", key=f"opt_l3_{uploaded_file.name}")
try:
    opt_sizes = [int(s.strip()) for s in opt_sizes_input.split(",") if s.strip().isdigit()]
    if opt_sizes:
        compute_optimal_mix(result, opt_sizes, "L3")
except Exception:
    st.warning("⚠️ Could not process optimal mix sizes. Use numbers like 150,250")

st.dataframe(result)

                fig, ax = plt.subplots()
                ax.plot(result["Hour"], result["Max_Power_kW"], label="Usage", color="black", linewidth=2)
                ax.plot(result["Hour"], result["Capacity_kW"], label="Capacity", color="green", linestyle="--", linewidth=2)
                ax.set_xlabel("Hour of Day")
                ax.set_ylabel("Power (kW")
                ax.set_title(f"{uploaded_file.name} - Usage vs Capacity")
                ax.legend()
                st.pyplot(fig)

                csv = result.to_csv(index=False).encode("utf-8")
                st.download_button("📥 Download CSV", data=csv, file_name=f"{uploaded_file.name}_analysis.csv")

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
    - You can use default charger sizes or enter your own custom ones

    **4. Review output**
    - The tool will calculate:
        - Hourly max demand
        - Excess available power
        - Max chargers that can be supported
    - Optionally test your own charger setup

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

📍 **Website**: [fleetzero.ai](https://fleetzero.ai)  
📧 **Email**: [info@fleetzero.ai](mailto:info@fleetzero.ai)
""")
