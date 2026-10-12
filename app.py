import re
import math
import random
import datetime

import requests
import pandas as pd
import streamlit as st
import pydeck as pdk

try:  # optional: only needed for real browser GPS
    from streamlit_js_eval import get_geolocation
except ImportError:
    get_geolocation = None

# ---------------------------------------------------------
# Page configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="Smart Traffic & Live Parking System - India",
    page_icon="🚦",
    layout="wide",
)

st.title("🚦 Smart Parking, Traffic Enforcement & Citizen Reporting Portal")
st.caption("Pan-India Smart City Initiative")
st.markdown("---")

# ---------------------------------------------------------
# Data: states -> cities (lat, lon)
# ---------------------------------------------------------
CITIES = {
    "Puducherry": {"Puducherry": (11.9416, 79.8083)},
    "Tamil Nadu": {
        "Chennai": (13.0827, 80.2707),
        "Coimbatore": (11.0168, 76.9558),
        "Madurai": (9.9252, 78.1198),
        "Hosur": (12.7409, 77.8253),
        "Tiruchirappalli": (10.7905, 78.7047),
    },
    "Karnataka": {
        "Bengaluru": (12.9716, 77.5946),
        "Mysuru": (12.2958, 76.6394),
        "Mangaluru": (12.9141, 74.8560),
    },
    "Kerala": {
        "Kochi": (9.9312, 76.2673),
        "Thiruvananthapuram": (8.5241, 76.9366),
        "Kozhikode": (11.2588, 75.7804),
    },
    "Andhra Pradesh": {
        "Visakhapatnam": (17.6868, 83.2185),
        "Vijayawada": (16.5062, 80.6480),
        "Tirupati": (13.6288, 79.4192),
    },
    "Telangana": {"Hyderabad": (17.3850, 78.4867), "Warangal": (17.9689, 79.5941)},
    "Maharashtra": {
        "Mumbai": (19.0760, 72.8777),
        "Pune": (18.5204, 73.8567),
        "Nagpur": (21.1458, 79.0882),
    },
    "Delhi": {"New Delhi": (28.6139, 77.2090)},
    "Gujarat": {
        "Ahmedabad": (23.0225, 72.5714),
        "Surat": (21.1702, 72.8311),
        "Vadodara": (22.3072, 73.1812),
    },
    "Rajasthan": {"Jaipur": (26.9124, 75.7873), "Udaipur": (24.5854, 73.7125)},
    "Uttar Pradesh": {
        "Lucknow": (26.8467, 80.9462),
        "Varanasi": (25.3176, 82.9739),
        "Noida": (28.5355, 77.3910),
    },
    "West Bengal": {"Kolkata": (22.5726, 88.3639)},
    "Madhya Pradesh": {"Bhopal": (23.2599, 77.4126), "Indore": (22.7196, 75.8577)},
    "Punjab": {"Ludhiana": (30.9010, 75.8573), "Amritsar": (31.6340, 74.8723)},
    "Chandigarh": {"Chandigarh": (30.7333, 76.7794)},
    "Bihar": {"Patna": (25.5941, 85.1376)},
    "Odisha": {"Bhubaneswar": (20.2961, 85.8245)},
    "Assam": {"Guwahati": (26.1445, 91.7362)},
    "Goa": {"Panaji": (15.4909, 73.8278)},
}

FINES = {
    "Illegal Parking Fine (₹500)": 500,
    "No Helmet Fine (₹1000)": 1000,
    "Signal Jump Fine (₹1000)": 1000,
    "Triple Riding Fine (₹1000)": 1000,
    "Traffic Obstruction Fine (₹500)": 500,
}


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _overpass_query(lat, lon, radius_m, limit):
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="parking"](around:{radius_m},{lat},{lon});
      way["amenity"="parking"](around:{radius_m},{lat},{lon});
    );
    out center {limit};
    """
    last_error = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(
                url,
                data={"data": query},
                timeout=40,
                headers={"User-Agent": "smart-parking-streamlit-app"},
            )
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except Exception as e:
            last_error = e
    raise last_error


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_parking_cached(lat, lon, radius_m, limit=30):
    elements = _overpass_query(lat, lon, radius_m, limit)
    rows = []
    for el in elements:
        plat = el.get("lat") or el.get("center", {}).get("lat")
        plon = el.get("lon") or el.get("center", {}).get("lon")
        if plat is None or plon is None:
            continue
        tags = el.get("tags", {})
        name = tags.get("name") or f"Parking #{str(el['id'])[-4:]}"
        cap = tags.get("capacity", "")
        rows.append(
            {
                "id": el["id"],
                "Location": name,
                "lat": plat,
                "lon": plon,
                "capacity_tag": int(cap) if str(cap).isdigit() else None,
                "fee": tags.get("fee", "unknown"),
            }
        )
    return pd.DataFrame(rows)


def fetch_parking(lat, lon, radius_m=2500, limit=30):
    try:
        return _fetch_parking_cached(lat, lon, radius_m, limit), True
    except Exception:
        return pd.DataFrame(), False


def add_availability(df):
    """DEMO availability. Replace with real sensor / IoT / booking data."""
    hour_seed = datetime.datetime.now().strftime("%Y%m%d%H")
    caps, frees = [], []
    for _, row in df.iterrows():
        rnd = random.Random(f"{row['id']}-{hour_seed}")
        cap_tag = row["capacity_tag"]
        if pd.notna(cap_tag) and int(cap_tag) > 0:
            cap = int(cap_tag)
        else:
            cap = rnd.choice([20, 30, 50, 80, 100])
        free = rnd.randint(0, cap)
        caps.append(cap)
        frees.append(free)
    df = df.copy()
    df["Capacity"] = caps
    df["Free"] = frees
    return df


def status_color(free, cap):
    ratio = free / cap if cap else 0
    if free == 0:
        return "red"
    if ratio < 0.25:
        return "orange"
    return "green"


# ---------------------------------------------------------
# Session state
# ---------------------------------------------------------
st.session_state.setdefault("reservations", [])
st.session_state.setdefault("reports", [])
st.session_state.setdefault("challans", [])

# ---------------------------------------------------------
# Sidebar: location selection (GPS or State/City)
# ---------------------------------------------------------
with st.sidebar:
    st.header("📍 Location")
    mode = st.radio("Choose location mode", ["📡 My GPS location", "🏙️ Select State / City"])

    user_lat = user_lon = None
    if mode.startswith("📡"):
        if get_geolocation is None:
            st.warning(
                "Real GPS needs an extra package. Run: python -m pip install streamlit-js-eval "
                "(or use the State / City mode instead)."
            )
            geo = None
        else:
            st.caption("Click 'Allow' when your browser asks for location access.")
            geo = get_geolocation()
        if geo and "coords" in geo:
            user_lat = geo["coords"]["latitude"]
            user_lon = geo["coords"]["longitude"]
            acc = geo["coords"].get("accuracy")
            st.success(f"GPS locked: {user_lat:.5f}, {user_lon:.5f}")
            if acc:
                st.caption(f"Accuracy: ±{int(acc)} m")
        elif get_geolocation is not None:
            st.warning("Waiting for GPS... please allow location access (works on https or localhost).")

    if user_lat is None:
        state = st.selectbox("State / UT", sorted(CITIES.keys()), index=sorted(CITIES.keys()).index("Puducherry"))
        city = st.selectbox("City", list(CITIES[state].keys()))
        center_lat, center_lon = CITIES[state][city]
        place_label = f"{city}, {state}"
    else:
        center_lat, center_lon = user_lat, user_lon
        place_label = "Your current location"

    radius_km = st.slider("Search radius (km)", 1, 10, 3)

# ---------------------------------------------------------
# Tabs
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs(
    ["🅿️ Live Parking Management", "📸 Citizen Reporting System", "👮 Police Enforcement Area"]
)

# =========================================================
# TAB 1: PARKING
# =========================================================
with tab1:
    st.header(f"🅿️ Smart Parking Map - {place_label}")

    with st.spinner("Loading real parking locations..."):
        parking_df, ok = fetch_parking(
            round(center_lat, 4), round(center_lon, 4), radius_km * 1000
        )

    if not ok:
        st.error("Could not fetch parking data. Please check your internet connection or try again in a minute.")
    elif parking_df.empty:
        st.warning("No parking data found in this area. Try increasing the search radius.")
    else:
        parking_df = add_availability(parking_df)
        parking_df["Distance (km)"] = parking_df.apply(
            lambda r: round(haversine_km(center_lat, center_lon, r["lat"], r["lon"]), 2), axis=1
        )
        parking_df = parking_df.sort_values("Distance (km)").reset_index(drop=True)

        st.caption(
            "ℹ️ Parking locations are real (OpenStreetMap). Free-slot counts are currently DEMO data "
            "and will become live once real sensors or a booking system are connected."
        )

        # Summary metrics (nearest 4)
        top = parking_df.head(4)
        cols = st.columns(len(top))
        for col, (_, r) in zip(cols, top.iterrows()):
            col.metric(
                label=f"{r['Location'][:22]} ({r['Distance (km)']} km)",
                value=f"{r['Free']} / {r['Capacity']} Free",
                delta="FULL" if r["Free"] == 0 else None,
                delta_color="inverse",
            )

        st.markdown("---")
        st.subheader("📍 Interactive Parking Map")

        colors = {"green": [0, 170, 80, 210], "orange": [255, 150, 0, 230], "red": [220, 30, 30, 240]}
        parking_df["color"] = parking_df.apply(
            lambda r: colors[status_color(r["Free"], r["Capacity"])], axis=1
        )
        parking_df["info"] = parking_df.apply(lambda r: f"{r['Free']}/{r['Capacity']} free", axis=1)
        parking_df["dist"] = parking_df["Distance (km)"]

        layers = [
            pdk.Layer(
                "ScatterplotLayer",
                data=parking_df,
                get_position="[lon, lat]",
                get_fill_color="color",
                get_radius=60,
                radius_min_pixels=8,
                pickable=True,
            )
        ]
        if user_lat is not None:
            user_df = pd.DataFrame({"lat": [user_lat], "lon": [user_lon]})
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=user_df,
                    get_position="[lon, lat]",
                    get_fill_color=[0, 90, 255, 255],
                    get_radius=80,
                    radius_min_pixels=10,
                )
            )

        st.pydeck_chart(
            pdk.Deck(
                map_style="light",
                initial_view_state=pdk.ViewState(
                    latitude=center_lat, longitude=center_lon, zoom=13
                ),
                layers=layers,
                tooltip={"text": "{Location}\n{info}\n{dist} km away"},
            )
        )
        st.caption("🟢 Available  🟠 Filling fast  🔴 Full")

        st.markdown("---")
        st.subheader("🎟️ Reserve / Check Parking Availability")
        c1, c2 = st.columns(2)
        with c1:
            vehicle_type = st.radio(
                "Vehicle Type", ["Two Wheeler (Bike)", "Four Wheeler (Car)"], horizontal=True
            )
            selected_spot = st.selectbox("Choose Parking Location", parking_df["Location"] + " (" + parking_df["Distance (km)"].astype(str) + " km)")
            duration = st.slider("Select Duration (Hours)", 1, 6, 2)
        with c2:
            st.write(" ")
            st.write(" ")
            if st.button("⚡ Reserve Live Slot Now", type="primary"):
                idx = list(parking_df["Location"] + " (" + parking_df["Distance (km)"].astype(str) + " km)").index(selected_spot)
                row = parking_df.iloc[idx]
                if row["Free"] == 0:
                    st.error("❌ This parking lot is FULL. Please choose another location.")
                else:
                    code = f"IN-SLOT-{random.randint(10000, 99999)}"
                    st.session_state.reservations.append(
                        {"Pass ID": code, "Location": row["Location"], "Hours": duration,
                         "Vehicle": vehicle_type, "Time": str(datetime.datetime.now())}
                    )
                    st.success(f"✅ Slot reserved at **{row['Location']}** for {duration} hours!")
                    st.info(f"🎫 Parking Pass ID: **{code}** (show this at the entry gate)")

        if st.session_state.reservations:
            with st.expander("My reservations"):
                st.dataframe(pd.DataFrame(st.session_state.reservations))

# =========================================================
# TAB 2: CITIZEN REPORTING
# =========================================================
with tab2:
    st.header("📸 Report Traffic Violations (Public Portal)")
    st.info("Citizens can report illegal parking, helmetless riding, or traffic obstruction.")

    default_loc = (
        f"{center_lat:.5f}, {center_lon:.5f}" if user_lat is not None else ""
    )

    with st.form("citizen_report_form"):
        reporter_name = st.text_input("Your Name (Optional)")
        violation_type = st.selectbox(
            "Violation Type",
            ["No Parking Zone", "Helmetless Riding", "Triple Riding", "Signal Jump", "Traffic Obstruction"],
        )
        location_input = st.text_input(
            "Location / Street Name (auto-filled in GPS mode)", value=default_loc
        )
        uploaded_image = st.file_uploader("Upload Proof Photo...", type=["jpg", "png", "jpeg"])
        description = st.text_area("Additional Details")
        submit_citizen = st.form_submit_button("🚨 Submit Incident Report")

    if submit_citizen:
        if not location_input.strip():
            st.error("Please enter a location.")
        else:
            report_id = f"RPT-{random.randint(100000, 999999)}"
            st.session_state.reports.append(
                {
                    "Report ID": report_id,
                    "Reporter": reporter_name or "Anonymous",
                    "Violation": violation_type,
                    "Location": location_input,
                    "Has Photo": uploaded_image is not None,
                    "Details": description,
                    "Time": str(datetime.datetime.now()),
                }
            )
            st.success(f"✅ Thank you! Report **{report_id}** submitted to the Traffic Control Room.")
            st.balloons()

# =========================================================
# TAB 3: POLICE ENFORCEMENT
# =========================================================
with tab3:
    st.header("👮 Police Enforcement & Challan Dashboard")
    st.caption("Restricted Access — Traffic Police Officials")

    password = st.text_input("Officer Password", type="password")
    # Change this: set POLICE_PASSWORD in .streamlit/secrets.toml
    try:
        expected = st.secrets["POLICE_PASSWORD"]
    except Exception:
        expected = "admin123"

    if password != expected:
        st.warning("Enter the officer password to access this area.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            vehicle_no = st.text_input("Vehicle Registration Number", placeholder="TN01AB1234")
            offense = st.selectbox("Offense Category", list(FINES.keys()))
        with col_b:
            officer_id = st.text_input("Officer ID", placeholder="TP-XXX-000")
            st.write(" ")
            st.write(" ")
            issue = st.button("⚡ Issue Digital E-Challan", type="primary")

        if issue:
            cleaned = re.sub(r"[\s-]", "", vehicle_no.upper())
            # Indian format: 2 letters (state) + 2 digits + 1-3 letters + 4 digits
            if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}", cleaned):
                st.error("Invalid vehicle number format (example: TN01AB1234, PY01AB1234, KA05MN4321).")
            elif not officer_id.strip():
                st.error("Please enter the Officer ID.")
            else:
                challan_id = f"CH-{random.randint(100000, 999999)}"
                record = {
                    "Challan ID": challan_id,
                    "Vehicle Number": cleaned,
                    "State Code": cleaned[:2],
                    "Offense": offense,
                    "Fine (₹)": FINES[offense],
                    "Issued By Officer": officer_id,
                    "Location": place_label,
                    "Timestamp": str(datetime.datetime.now()),
                }
                st.session_state.challans.append(record)
                st.error(f"⚠️ E-Challan Generated: **{challan_id}** for **{cleaned}**")
                st.json(record)

        if st.session_state.challans:
            st.subheader("Issued Challans (this session)")
            st.dataframe(pd.DataFrame(st.session_state.challans))

        if st.session_state.reports:
            st.subheader("Citizen Reports Received")
            st.dataframe(pd.DataFrame(st.session_state.reports))