import os
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import sqlalchemy
from sqlalchemy.engine import URL

st.set_page_config(page_title="Air Tracker", page_icon="✈️", layout="wide")


# ---------------------------------------------------------------- database
@st.cache_resource
def get_engine():
    """One pooled connection engine shared across reruns.
    Credentials come from environment variables, never from the code."""
    url = URL.create(
        "mysql+mysqlconnector",
        username=os.getenv("DB_USER", "root"),
        password=os.getenv("7860"),
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "air_tracker"),
    )
    return sqlalchemy.create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=300)
def run_query(sql, params=None):
    with get_engine().connect() as conn:
        return pd.read_sql(sqlalchemy.text(sql), conn, params=params or {})


def safe_query(sql, params=None):
    """Run a query; show a friendly error instead of crashing the app."""
    try:
        return run_query(sql, params)
    except Exception as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------- navigation
st.sidebar.title("✈️ Air Tracker")
page = st.sidebar.radio(
    "Go to",
    ["Home", "Flight Explorer", "Airport Analytics", "SQL Insights", "About"],
)

# ---------------------------------------------------------------- HOME
if page == "Home":
    st.title("✈️ Air Tracker: Flight Analytics")
    st.write(
        "Explore flights, airports and delays collected from the AeroDataBox API "
        "and stored in a MySQL database."
    )
    counts = safe_query(
        """
        SELECT 'Airports' AS tbl, COUNT(*) AS n FROM airport
        UNION ALL SELECT 'Aircraft', COUNT(*) FROM aircraft
        UNION ALL SELECT 'Flights', COUNT(*) FROM flights
        UNION ALL SELECT 'Airport-day delay rows', COUNT(*) FROM airport_delays
        """
    )
    if not counts.empty:
        cols = st.columns(len(counts))
        for col, (_, row) in zip(cols, counts.iterrows()):
            col.metric(row["tbl"], f"{int(row['n']):,}")

    st.subheader("Airports in the database")
    airports = safe_query(
        "SELECT name, city, country, latitude, longitude FROM airport "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    )
    if airports.empty:
        st.info("No airport data yet. Run the data loader first.")
    else:
        st.map(airports, latitude="latitude", longitude="longitude")

# ---------------------------------------------------------------- FLIGHT EXPLORER
elif page == "Flight Explorer":
    st.title("🔎 Flight Explorer")

    ap = safe_query(
        "SELECT iata_code, name FROM airport WHERE iata_code IS NOT NULL ORDER BY name"
    )
    labels = dict(zip(ap["iata_code"], ap["name"])) if not ap.empty else {}
    codes = ["All"] + list(labels.keys())
    fmt = lambda c: "All" if c == "All" else f"{c} - {labels[c]}"

    c1, c2, c3 = st.columns(3)
    origin = c1.selectbox("Origin", codes, format_func=fmt)
    dest = c2.selectbox("Destination", codes, format_func=fmt)
    statuses = safe_query("SELECT DISTINCT status FROM flights WHERE status IS NOT NULL")
    status = c3.selectbox("Status", ["All"] + sorted(statuses["status"].tolist()) if not statuses.empty else ["All"])

    today = date.today()
    picked = st.date_input("Scheduled departure between", (today - timedelta(days=7), today))

    where, params = ["1=1"], {}
    if origin != "All":
        where.append("f.origin_iata = :origin")
        params["origin"] = origin
    if dest != "All":
        where.append("f.destination_iata = :dest")
        params["dest"] = dest
    if status != "All":
        where.append("f.status = :status")
        params["status"] = status
    if isinstance(picked, tuple) and len(picked) == 2:
        where.append("f.scheduled_departure >= :d1 AND f.scheduled_departure < :d2")
        params["d1"] = picked[0]
        params["d2"] = picked[1] + timedelta(days=1)

    df = safe_query(
        f"""
        SELECT f.flight_number, f.airline_code, f.origin_iata, f.destination_iata,
               f.scheduled_departure, f.actual_departure,
               f.scheduled_arrival, f.actual_arrival, f.status,
               TIMESTAMPDIFF(MINUTE, f.scheduled_departure, f.actual_departure)
                   AS departure_delay_min
        FROM flights f
        WHERE {' AND '.join(where)}
        ORDER BY f.scheduled_departure DESC
        LIMIT 500
        """,
        params,
    )
    if df.empty:
        st.warning("No flights match the selected filters.")
    else:
        st.caption(f"Showing {len(df)} flights (max 500)")
        st.dataframe(df, use_container_width=True)
        st.download_button("Download CSV", df.to_csv(index=False), "flights.csv", "text/csv")

# ---------------------------------------------------------------- AIRPORT ANALYTICS
elif page == "Airport Analytics":
    st.title("📍 Airport Analytics")

    ap = safe_query(
        "SELECT iata_code, name FROM airport WHERE iata_code IS NOT NULL ORDER BY name"
    )
    if ap.empty:
        st.info("No airport data yet. Run the data loader first.")
        st.stop()
    labels = dict(zip(ap["iata_code"], ap["name"]))
    iata = st.selectbox("Airport", list(labels), format_func=lambda c: f"{c} - {labels[c]}")

    stats = safe_query(
        """
        SELECT SUM(origin_iata = :i)          AS departures,
               SUM(destination_iata = :i)     AS arrivals,
               ROUND(AVG(CASE WHEN origin_iata = :i
                    THEN TIMESTAMPDIFF(MINUTE, scheduled_departure, actual_departure) END), 1)
                    AS avg_departure_delay_min,
               SUM(origin_iata = :i AND LOWER(status) LIKE '%cancel%') AS cancelled
        FROM flights
        WHERE origin_iata = :i OR destination_iata = :i
        """,
        {"i": iata},
    )
    if not stats.empty:
        r = stats.iloc[0].fillna(0)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Departures", int(r["departures"]))
        m2.metric("Arrivals", int(r["arrivals"]))
        m3.metric("Avg departure delay (min)", r["avg_departure_delay_min"])
        m4.metric("Cancelled departures", int(r["cancelled"]))

    st.subheader("Top destinations from this airport")
    top = safe_query(
        """
        SELECT destination_iata, COUNT(*) AS flights
        FROM flights WHERE origin_iata = :i
        GROUP BY destination_iata ORDER BY flights DESC LIMIT 10
        """,
        {"i": iata},
    )
    if top.empty:
        st.warning("No departures recorded for this airport.")
    else:
        st.bar_chart(top.set_index("destination_iata"))

    st.subheader("Daily delay index")
    daily = safe_query(
        """
        SELECT delay_date, delay_index FROM airport_delays
        WHERE airport_iata = :i ORDER BY delay_date
        """,
        {"i": iata},
    )
    if daily.empty:
        st.info("No delay history yet for this airport.")
    else:
        st.line_chart(daily.set_index("delay_date"))

# ---------------------------------------------------------------- SQL INSIGHTS
elif page == "SQL Insights":
    st.title("📋 SQL Insights")

    queries = {
        "Flights per aircraft model": """
            SELECT a.model, COUNT(f.flight_id) AS total_flights
            FROM aircraft a
            LEFT JOIN flights f ON f.aircraft_registration = a.registration
            GROUP BY a.model ORDER BY total_flights DESC""",
        "Aircraft with more than 5 flights": """
            SELECT a.registration, a.model, COUNT(f.flight_id) AS flight_count
            FROM aircraft a JOIN flights f ON f.aircraft_registration = a.registration
            GROUP BY a.registration, a.model
            HAVING COUNT(f.flight_id) > 5 ORDER BY flight_count DESC""",
        "Airports with more than 5 outbound flights": """
            SELECT ap.name, COUNT(f.flight_id) AS outbound_flights
            FROM airport ap JOIN flights f ON f.origin_iata = ap.iata_code
            GROUP BY ap.airport_id, ap.name
            HAVING COUNT(f.flight_id) > 5 ORDER BY outbound_flights DESC""",
        "Top 3 destination airports": """
            SELECT ap.name, ap.city, COUNT(f.flight_id) AS arriving_flights
            FROM airport ap JOIN flights f ON f.destination_iata = ap.iata_code
            GROUP BY ap.airport_id, ap.name, ap.city
            ORDER BY arriving_flights DESC, ap.name LIMIT 3""",
        "Domestic vs international flights": """
            SELECT f.flight_number, f.origin_iata AS origin, f.destination_iata AS destination,
                   CASE WHEN o.country IS NULL OR d.country IS NULL THEN 'Unknown'
                        WHEN o.country = d.country THEN 'Domestic'
                        ELSE 'International' END AS flight_type
            FROM flights f
            LEFT JOIN airport o ON o.iata_code = f.origin_iata
            LEFT JOIN airport d ON d.iata_code = f.destination_iata
            LIMIT 500""",
        "5 most recent arrivals at DEL": """
            SELECT f.flight_number, f.aircraft_registration AS aircraft,
                   o.name AS departure_airport, f.actual_arrival AS arrival_time
            FROM flights f JOIN airport o ON o.iata_code = f.origin_iata
            WHERE f.destination_iata = 'DEL' AND f.actual_arrival IS NOT NULL
            ORDER BY f.actual_arrival DESC LIMIT 5""",
        "Airports with no arriving flights": """
            SELECT ap.icao_code, ap.iata_code, ap.name, ap.city
            FROM airport ap
            WHERE NOT EXISTS (SELECT 1 FROM flights f WHERE f.destination_iata = ap.iata_code)""",
        "Flights per airline by status": """
            SELECT airline_code, airline_name, COUNT(*) AS total_flights,
                   SUM(category = 'On Time') AS on_time,
                   SUM(category = 'Delayed') AS delayed,
                   SUM(category = 'Cancelled') AS cancelled,
                   SUM(category = 'Other') AS other
            FROM (
                SELECT airline_code, airline_name,
                       CASE WHEN LOWER(status) LIKE '%cancel%' THEN 'Cancelled'
                            WHEN LOWER(status) = 'delayed'
                                 OR TIMESTAMPDIFF(MINUTE, scheduled_departure, actual_departure) > 15
                                 THEN 'Delayed'
                            WHEN actual_departure IS NOT NULL
                                 AND TIMESTAMPDIFF(MINUTE, scheduled_departure, actual_departure) <= 15
                                 THEN 'On Time'
                            ELSE 'Other' END AS category
                FROM flights) t
            GROUP BY airline_code, airline_name ORDER BY total_flights DESC""",
        "Cancelled flights": """
            SELECT f.flight_number, f.scheduled_departure, f.aircraft_registration AS aircraft,
                   o.name AS origin_airport, d.name AS destination_airport, f.status
            FROM flights f
            LEFT JOIN airport o ON o.iata_code = f.origin_iata
            LEFT JOIN airport d ON d.iata_code = f.destination_iata
            WHERE LOWER(f.status) LIKE '%cancel%'
            ORDER BY f.scheduled_departure DESC""",
        "City pairs with more than 2 aircraft models": """
            SELECT o.city AS origin_city, d.city AS destination_city,
                   COUNT(DISTINCT ac.model) AS aircraft_models, COUNT(*) AS flights
            FROM flights f
            JOIN airport o ON o.iata_code = f.origin_iata
            JOIN airport d ON d.iata_code = f.destination_iata
            JOIN aircraft ac ON ac.registration = f.aircraft_registration
            GROUP BY o.city, d.city
            HAVING COUNT(DISTINCT ac.model) > 2
            ORDER BY aircraft_models DESC, flights DESC""",
        "Delayed arrivals % by destination": """
            SELECT ap.name, ap.iata_code, COUNT(*) AS arrivals_with_times,
                   ROUND(100 * SUM(TIMESTAMPDIFF(MINUTE, f.scheduled_arrival, f.actual_arrival) > 15)
                         / COUNT(*), 2) AS delayed_pct
            FROM flights f JOIN airport ap ON ap.iata_code = f.destination_iata
            WHERE f.actual_arrival IS NOT NULL AND f.scheduled_arrival IS NOT NULL
            GROUP BY ap.airport_id, ap.name, ap.iata_code
            ORDER BY delayed_pct DESC""",
    }

    choice = st.selectbox("Choose a query", list(queries))
    sql = queries[choice]
    with st.expander("Show SQL"):
        st.code(" ".join(sql.split()), language="sql")

    result = safe_query(sql)
    if result.empty:
        st.info("This query returned no rows (the tables may not be loaded yet).")
    else:
        st.dataframe(result, use_container_width=True)

# ---------------------------------------------------------------- ABOUT
elif page == "About":
    st.title("About this project")
    st.write(
        """
        **Air Tracker** collects flight data from the AeroDataBox API (via RapidAPI),
        stores it in MySQL (airport, aircraft, flights, airport_delays), and presents
        analysis in this Streamlit app.

        **Stack:** Python, MySQL, SQLAlchemy, Pandas, Streamlit

        **Developed by:** *DEEPAK SHAH*
        """
    )