import streamlit as st
import os
import time as time_tool
from datetime import datetime, time
from src.database import run_query
from src.components import maps, tab1, tab2, tab3
from src import pipeline, queries

# SETUP
st.set_page_config(page_title="Air Tracker: Flight Analysis", layout="wide")

# 1. Initialize Session State 
if 'etl_success' not in st.session_state:
    st.session_state.etl_success = False
if 'last_synced_airport' not in st.session_state:
    st.session_state.last_synced_airport = ""
if 'view_dashboard' not in st.session_state:
    st.session_state.view_dashboard = False

# ETL Controls (Sidebar)
st.sidebar.title("ETL Controls")
api_key_input = st.sidebar.text_input("AeroDataBox API Key", type="password")
sync_date_input = st.sidebar.date_input("Select Date to Sync")

# Time Range Inputs
t_col1, t_col2 = st.sidebar.columns(2)
with t_col1:
    start_time_input = st.time_input("From", time(8, 0))
with t_col2:
    end_time_input = st.time_input("To", time(20, 0))

sync_location_input = st.sidebar.text_input("Airport IATA Code (e.g., LHR)")

if st.sidebar.button("Sync Data"):
    # Calculate time difference in hours
    duration = datetime.combine(sync_date_input, end_time_input) - datetime.combine(sync_date_input, start_time_input)
    duration_hours = duration.total_seconds() / 3600

    if not api_key_input or not sync_location_input:
        st.sidebar.error("API Key and Airport IATA are required.")
    elif len(sync_location_input) != 3:
        st.sidebar.error("Invalid IATA code.")
    elif start_time_input >= end_time_input:
        st.sidebar.error("End time must be after start time.")
    elif duration_hours > 12:
        st.sidebar.error("Maximum sync window is 12 hours.")
    else:
        from_time = datetime.combine(sync_date_input, start_time_input).strftime("%Y-%m-%dT%H:%M")
        to_time = datetime.combine(sync_date_input, end_time_input).strftime("%Y-%m-%dT%H:%M")

        with st.spinner(f"Syncing {sync_location_input.upper()}..."):
            try:
                pipeline.run_pipeline(api_key_input, sync_location_input.upper(), from_time, to_time)
                st.session_state.etl_success = True
                st.session_state.last_synced_airport = sync_location_input.upper()
                st.cache_data.clear() 
            except Exception as e:
                st.sidebar.error(f"Error: {e}")
        if st.session_state.etl_success:
            st.rerun()

if st.session_state.etl_success:
    st.sidebar.success(f"Sync Complete: {st.session_state.last_synced_airport}")
    st.session_state.etl_success = False

# 2. Intro Page vs Dashboard Logic

# Check if DB has data
db_has_data = False
try:
    check_db = run_query("SELECT 1 FROM airport LIMIT 1")
    if not check_db.empty:
        db_has_data = True
except Exception:
    db_has_data = False

# Logic to display Intro or Dashboard
if not st.session_state.view_dashboard:
    # INTRO PAGE
    st.title("✈️ Welcome to Air Tracker: Flight Analytics")
    
    st.markdown("""
    ### About this App
    This tool allows you to track and analyse flight operations, airline performance, and aircraft types for specific airports globally.
    
    * **What it does:** Fetches specific flight schedules based on your time inputs, calculates delay statistics, and visualises flight paths.
    * **What it cannot do:** Access restricted military flights or provide historical data outside the API's lookback window.
    * **Data Source:** AeroDataBox API. Each sync consumes API units based on the volume of data retrieved.
    ---
    """)

    if db_has_data:
        st.success("✅ Database Connection Established. Data is available.")
        if st.button("Enter Dashboard"):
            st.session_state.view_dashboard = True
            st.rerun()
    else:
        st.warning("⚠️ No data found in the database. Please use the **ETL Controls** in the sidebar to sync an airport and begin.")
        st.info("Tip: Try entering 'LHR' (London) or 'JFK' (New York) and a 12-hour window.")
    
    st.markdown("---")
    st.caption("**Disclaimer:** This dashboard is for educational and informational purposes only and is a part of GUVI DS project.")

else:
    # MAIN DASHBOARD PAGE
    top_col1, top_col2 = st.columns([1, 4])
    with top_col1:
        if st.button("← Back to Intro"):
            st.session_state.view_dashboard = False
            st.rerun()
    with top_col2:
        st.caption(f"Session Active | Dashboard Refreshed: {datetime.now().strftime('%H:%M:%S')}")

    # --- Map Display ---
    try:
        st.subheader("🗺️ Global Flight Map")
        sql = queries.get_airport_list()
        all_airports_df = run_query(sql)
        
        airport_options = {"All Airports (Global View)": "ALL"}
        if not all_airports_df.empty:
            airport_options.update({
                f"{row['name']} ({row['iata_code']})": row['iata_code'] 
                for _, row in all_airports_df.iterrows()
            })

        selected_airport_label = st.selectbox(
            "Choose an airport to focus the map:", 
            options=list(airport_options.keys()),
            key='main_map_airport_select'
        )
        selected_iata = airport_options[selected_airport_label]

        maps.render_map(selected_iata)

    except Exception as e:
        st.error(f"An error occurred while loading the map: {e}")

    st.divider()

    # --- Main Dashboard Tabs ---
    try:
        ops_tab, airline_tab, aircraft_tab = st.tabs(["Operations", "Airlines", "Aircraft"])
        
        with ops_tab: 
            tab1.render_tab1()
        with airline_tab: 
            tab2.render_tab2()
        with aircraft_tab: 
            tab3.render_tab3()

    except Exception as e:
        st.error(f"An error occurred while loading the dashboard tabs: {e}")
        st.warning("Try clearing the cache and refreshing the page.")
        if st.button("Reset View"):
            st.session_state.view_dashboard = False
            st.rerun()
