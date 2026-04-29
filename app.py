import streamlit as st
import pymongo
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import joblib
import os
from datetime import datetime, time
import random
import time as sleep_time
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import pytesseract
import re

# If Windows Tesseract path needed, uncomment this:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------------- DATABASE ----------------
client = pymongo.MongoClient("mongodb+srv://admin:1234@cluster0.vbcsfq7.mongodb.net/?appName=Cluster0")
db = client["GlobalCurb"]
spots_col = db["world_spots"]
users_col = db["users"]
logs_col = db["live_training_logs"]

MODEL_PATH = "adaptive_brain.pkl"


# ---------------- AI PRICE ----------------
def get_dynamic_price(lat, lon, hr, q):
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            features = pd.DataFrame(
                [[lat, lon, hr, q]],
                columns=["lat", "lon", "hour", "quality"]
            )
            pred = model.predict(features)[0]
            return round(max(30.0, min(pred, 250.0)), 2)
        except Exception:
            pass

    base = 40.0
    is_peak = (8 <= hr <= 11) or (17 <= hr <= 21)
    multiplier = 1.3 if is_peak else 1.0
    quality_bonus = 20.0 if q == 1 else 0.0
    return float((base * multiplier) + quality_bonus)


def retrain_model():
    logs = list(logs_col.find())
    if len(logs) > 5:
        df = pd.DataFrame(logs)
        success_df = df[df["outcome"] == "Accepted"]

        if len(success_df) >= 3:
            X = success_df[["lat", "lon", "hour", "quality"]]
            y = success_df["price"]

            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model.fit(X, y)
            joblib.dump(model, MODEL_PATH)


# ---------------- EXIF GPS EXTRACTION ----------------
def get_gps_from_image(uploaded_file):
    try:
        uploaded_file.seek(0)
        image = Image.open(uploaded_file)
        exif_data = image._getexif()

        if not exif_data:
            uploaded_file.seek(0)
            return None, None

        gps_info = {}

        for tag, value in exif_data.items():
            tag_name = TAGS.get(tag, tag)

            if tag_name == "GPSInfo":
                for gps_tag in value:
                    gps_name = GPSTAGS.get(gps_tag, gps_tag)
                    gps_info[gps_name] = value[gps_tag]

        if not gps_info:
            uploaded_file.seek(0)
            return None, None

        def convert_to_degrees(value):
            d = float(value[0])
            m = float(value[1])
            s = float(value[2])
            return d + (m / 60.0) + (s / 3600.0)

        lat = convert_to_degrees(gps_info["GPSLatitude"])
        lon = convert_to_degrees(gps_info["GPSLongitude"])

        if gps_info.get("GPSLatitudeRef") == "S":
            lat = -lat

        if gps_info.get("GPSLongitudeRef") == "W":
            lon = -lon

        uploaded_file.seek(0)
        return lat, lon

    except Exception:
        uploaded_file.seek(0)
        return None, None


# ---------------- OCR GPS EXTRACTION ----------------
def extract_gps_from_text(uploaded_file):
    try:
        uploaded_file.seek(0)
        image = Image.open(uploaded_file)

        text = pytesseract.image_to_string(image)

        pattern1 = r"Lat\s*[:\-]?\s*([+-]?\d+\.\d+).*?Long\s*[:\-]?\s*([+-]?\d+\.\d+)"
        match = re.search(pattern1, text, re.IGNORECASE | re.DOTALL)

        if match:
            uploaded_file.seek(0)
            return float(match.group(1)), float(match.group(2))

        pattern2 = r"([+-]?\d{1,2}\.\d+)\s*[, ]+\s*([+-]?\d{2,3}\.\d+)"
        match = re.search(pattern2, text)

        if match:
            uploaded_file.seek(0)
            return float(match.group(1)), float(match.group(2))

        uploaded_file.seek(0)
        return None, None

    except Exception:
        uploaded_file.seek(0)
        return None, None


# ---------------- ADDRESS FROM LAT/LON ----------------
def get_pan_india_address(lat, lon):
    try:
        geolocator = Nominatim(user_agent="curbit_v2")
        location = geolocator.reverse(f"{lat}, {lon}", timeout=5)

        if location and "address" in location.raw:
            a = location.raw["address"]
            area = a.get("suburb", a.get("neighbourhood", "Residential Area"))
            city = a.get("city", a.get("town", a.get("village", "Unknown City")))
            return f"{area}, {city}"

        return f"Node {lat:.2f}"

    except Exception:
        return "Network Node"


# ---------------- PAGE CONFIG ----------------
st.set_page_config(page_title="CURBIT | Smart Parking", layout="wide")


# ---------------- IMPROVED CSS ----------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    color: #0f172a !important;
}

/* MAIN BACKGROUND */
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #eaf8ff 0%, #dff3ff 45%, #f5fbff 100%);
}

/* MAIN CONTENT WIDTH */
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}

/* SIDEBAR */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a, #1e293b) !important;
}

[data-testid="stSidebar"] * {
    color: #ffffff !important;
}

/* LOGIN CARD */
.auth-box {
    background: #ffffff;
    padding: 35px;
    border-radius: 28px;
    box-shadow: 0 18px 50px rgba(14, 165, 233, 0.22);
    border: 1px solid #bae6fd;
    margin-top: 45px;
}

.auth-logo {
    text-align: center;
    font-size: 58px;
    font-weight: 900;
    letter-spacing: -4px;
    color: #075985;
}

.auth-caption {
    text-align: center;
    color: #475569;
    font-size: 15px;
    margin-bottom: 18px;
}

/* HEADINGS */
h1, h2, h3 {
    color: #0f172a !important;
    font-weight: 800 !important;
}

/* INPUT BOXES */
input, textarea, select {
    background-color: #ffffff !important;
    color: #0f172a !important;
    border: 1px solid #94a3b8 !important;
    border-radius: 12px !important;
}

/* INPUT LABELS */
label, .stTextInput label, .stPassword label, .stSelectbox label {
    color: #0f172a !important;
    font-weight: 700 !important;
}

/* TABS */
.stTabs [data-baseweb="tab-list"] {
    gap: 10px;
}

.stTabs [data-baseweb="tab"] {
    background: #ffffff;
    color: #0f172a;
    border-radius: 999px;
    padding: 10px 22px;
    border: 1px solid #bae6fd;
    font-weight: 800;
}

.stTabs [aria-selected="true"] {
    background: #0284c7 !important;
    color: #ffffff !important;
}

/* CARDS */
.glass-card, .parking-card {
    background: #ffffff;
    border: 1px solid #bae6fd;
    border-radius: 24px;
    padding: 22px;
    box-shadow: 0 12px 32px rgba(15, 23, 42, 0.10);
    margin-bottom: 20px;
}

/* HERO CARD */
.hero-card {
    background: linear-gradient(135deg, #0369a1, #0284c7);
    color: white;
    padding: 30px;
    border-radius: 28px;
    box-shadow: 0 18px 45px rgba(2, 132, 199, 0.35);
    margin-bottom: 24px;
}

.hero-card h1 {
    color: white !important;
    font-size: 46px;
    font-weight: 900;
}

.hero-card p {
    color: #e0f2fe;
    font-size: 16px;
}

/* TEXT */
.location-title {
    font-size: 22px;
    font-weight: 800;
    color: #0f172a;
    margin-bottom: 8px;
}

.price-text {
    font-size: 28px;
    font-weight: 900;
    color: #075985;
    margin-top: 8px;
}

/* BADGES */
.badge {
    display: inline-block;
    padding: 6px 13px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
    margin: 5px 5px 5px 0;
}

.badge-green {
    background: #dcfce7;
    color: #166534;
}

.badge-orange {
    background: #ffedd5;
    color: #9a3412;
}

.badge-red {
    background: #fee2e2;
    color: #991b1b;
}

.badge-blue {
    background: #dbeafe;
    color: #1d4ed8;
}

.badge-dark {
    background: #e2e8f0;
    color: #0f172a;
}

/* BUTTONS */
div.stButton > button {
    background: linear-gradient(135deg, #0284c7, #075985);
    color: #ffffff !important;
    border-radius: 14px;
    border: none;
    padding: 13px 18px;
    font-weight: 800;
    width: 100%;
    box-shadow: 0 8px 20px rgba(2, 132, 199, 0.28);
}

div.stButton > button:hover {
    background: linear-gradient(135deg, #0369a1, #0c4a6e);
    color: #ffffff !important;
}

/* FILE UPLOADER */
[data-testid="stFileUploader"] {
    background: #ffffff;
    border: 2px dashed #38bdf8;
    border-radius: 20px;
    padding: 16px;
}

/* METRIC CARDS */
[data-testid="stMetric"] {
    background: #ffffff;
    padding: 18px;
    border-radius: 20px;
    border: 1px solid #bae6fd;
    box-shadow: 0 10px 25px rgba(15, 23, 42, 0.08);
}

[data-testid="stMetric"] * {
    color: #0f172a !important;
}

/* LINKS */
a {
    color: #0369a1 !important;
    font-weight: 800;
    text-decoration: none;
}

/* ALERT BOX */
[data-testid="stAlert"] {
    border-radius: 14px;
    font-weight: 600;
}

/* IMAGES */
img {
    border-radius: 18px;
}

/* CAPTIONS */
small, .caption, [data-testid="stCaptionContainer"] {
    color: #475569 !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------- SESSION ----------------
if "user" not in st.session_state:
    st.session_state.user = None


# ---------------- AUTH PAGE ----------------
if not st.session_state.user:
    _, col, _ = st.columns([1, 1.15, 1])

    with col:
        st.markdown("""
        <div class="auth-box">
            <div class="auth-logo">CURBIT.</div>
            <div class="auth-caption">
                Smart parking discovery with GPS, AI pricing and live availability
            </div>
        </div>
        """, unsafe_allow_html=True)

        t_l, t_r = st.tabs(["Login", "Register"])

        with t_l:
            st.markdown("### Welcome Back")
            u_in = st.text_input("Username", placeholder="Enter username")
            p_in = st.text_input("Password", type="password", placeholder="Enter password")

            if st.button("SIGN IN"):
                res = users_col.find_one({"user": u_in, "pass": p_in})

                if res:
                    st.session_state.user = res
                    st.rerun()
                else:
                    st.error("Access Denied")

        with t_r:
            st.markdown("### Create Account")
            u_reg = st.text_input("New Username", placeholder="Choose username")
            p_reg = st.text_input("New Password", type="password", placeholder="Choose password")
            role = st.selectbox("I am a", ["Host (Owner)", "Driver (User)"])

            if st.button("CREATE ACCOUNT"):
                if not u_reg or not p_reg:
                    st.error("Please enter username and password")
                else:
                    users_col.insert_one({
                        "user": u_reg,
                        "pass": p_reg,
                        "role": role
                    })
                    st.success("Registered successfully! Now login.")


# ---------------- MAIN APP ----------------
else:
    user = st.session_state.user

    st.sidebar.markdown("##  CURBIT.")
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 **{user['user']}**")
    st.sidebar.write(f" **{user['role']}**")
    st.sidebar.markdown("---")

    loc = get_geolocation()

    if loc and "coords" in loc:
        browser_lat = loc["coords"]["latitude"]
        browser_lon = loc["coords"]["longitude"]
    else:
        browser_lat, browser_lon = 18.62, 73.79

    st.sidebar.caption(f"Browser GPS: {round(browser_lat, 5)}, {round(browser_lon, 5)}")

    if st.sidebar.button("SIGN OUT"):
        st.session_state.user = None
        st.rerun()


    # ---------------- HOST PORTAL ----------------
    if "Host" in user["role"]:
        my_assets = list(spots_col.find({"host": user["user"]}))
        now = datetime.now()

        total_spots = len(my_assets)
        live_spots = sum(
            1 for s in my_assets
            if s.get("status") == "Available"
            and "start_time" in s
            and "end_time" in s
            and s["start_time"] <= now <= s["end_time"]
        )
        booked_spots = sum(1 for s in my_assets if s.get("status") == "Booked")
        occupied_spots = sum(1 for s in my_assets if s.get("status") == "Occupied")
        rev = sum([s.get("price", 0) for s in my_assets if s.get("status") == "Occupied"])

        st.markdown("""
        <div class="hero-card">
            <h1>Host Dashboard</h1>
            <p>Upload parking spots, detect GPS automatically, set visibility time and manage driver requests.</p>
        </div>
        """, unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Spots", total_spots)
        m2.metric("Live Now", live_spots)
        m3.metric("Booked", booked_spots)
        m4.metric("Earnings", f"₹{rev}")

        st.markdown("## ➕ Publish New Parking Spot")
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)

        f = st.file_uploader(
            "Upload parking photo",
            type=["jpg", "jpeg", "png"],
            help="Supports GPS camera photos and photos with Lat/Long text."
        )

        if f:
            left, right = st.columns([1, 1.4])

            with left:
                image_bytes = f.getvalue()
                st.image(image_bytes, use_container_width=True)

            with right:
                q = random.choice([0, 1])
                hr = datetime.now().hour

                image_lat, image_lon = get_gps_from_image(f)
                location_source = "EXIF Metadata"

                if image_lat is None or image_lon is None:
                    image_lat, image_lon = extract_gps_from_text(f)
                    location_source = "OCR Text from Image"

                if image_lat is None or image_lon is None:
                    final_lat = browser_lat
                    final_lon = browser_lon
                    location_source = "Host Browser GPS"
                    st.warning("No GPS found in EXIF or image text. Using Host current location.")
                else:
                    final_lat = image_lat
                    final_lon = image_lon
                    st.success(f"GPS detected using {location_source}")

                addr = get_pan_india_address(final_lat, final_lon)
                d_price = get_dynamic_price(final_lat, final_lon, hr, q)
                maps_link = f"https://www.google.com/maps?q={final_lat},{final_lon}"

                st.markdown(f"""
                <div class="location-title">📍 {addr}</div>
                <span class="badge badge-blue">{location_source}</span>
                <span class="badge badge-dark">GPS: {round(final_lat, 6)}, {round(final_lon, 6)}</span>
                <div class="price-text">₹{d_price}/hr</div>
                """, unsafe_allow_html=True)

                st.markdown(f"[Open in Google Maps]({maps_link})")

                st.markdown("### ⏰ Post Visibility Time")

                c1, c2 = st.columns(2)

                with c1:
                    start_date = st.date_input("Start Date")
                    start_clock = st.time_input(
                        "Start Time",
                        value=datetime.now().time().replace(second=0, microsecond=0)
                    )

                with c2:
                    end_date = st.date_input("End Date")
                    end_clock = st.time_input("End Time", value=time(23, 59))

                start_datetime = datetime.combine(start_date, start_clock)
                end_datetime = datetime.combine(end_date, end_clock)

                if end_datetime <= start_datetime:
                    st.error("End Time must be greater than Start Time")

                if st.button("CONFIRM & PUBLISH LIVE"):
                    if end_datetime <= start_datetime:
                        st.error("Please select valid Start Time and End Time")
                    else:
                        spots_col.insert_one({
                            "host": user["user"],
                            "price": d_price,
                            "lat": final_lat,
                            "lon": final_lon,
                            "maps_link": maps_link,
                            "location_source": location_source,
                            "address": addr,
                            "status": "Available",
                            "image_data": image_bytes,
                            "hour": hr,
                            "quality": q,
                            "start_time": start_datetime,
                            "end_time": end_datetime,
                            "created_at": datetime.now()
                        })

                        st.success("Spot published successfully!")
                        sleep_time.sleep(1)
                        st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("## 🅿️ Your Parking Spots")

        my_assets = list(spots_col.find({"host": user["user"]}))

        if not my_assets:
            st.info("You have not uploaded any parking spots yet.")

        for s in my_assets:
            st.markdown('<div class="parking-card">', unsafe_allow_html=True)

            ca, cb, cc = st.columns([1.1, 2.2, 1])

            with ca:
                if "image_data" in s:
                    st.image(s["image_data"], use_container_width=True)

            with cb:
                st.markdown(
                    f'<div class="location-title">{s.get("address", "No Address")}</div>',
                    unsafe_allow_html=True
                )

                if "lat" in s and "lon" in s:
                    st.markdown(
                        f'<span class="badge badge-dark">GPS: {round(s["lat"], 6)}, {round(s["lon"], 6)}</span>',
                        unsafe_allow_html=True
                    )

                st.markdown(
                    f'<span class="badge badge-blue">{s.get("location_source", "Unknown Source")}</span>',
                    unsafe_allow_html=True
                )

                if "maps_link" in s:
                    st.markdown(f"[Open in Google Maps]({s['maps_link']})")

                if s.get("status") == "Booked":
                    st.warning(f"Driver request from: {s.get('booked_by')}")

                    b1, b2 = st.columns(2)

                    if b1.button("Allow Parking", key=f"h_acc_{s['_id']}"):
                        spots_col.update_one(
                            {"_id": s["_id"]},
                            {"$set": {"status": "Occupied"}}
                        )
                        st.rerun()

                    if b2.button("Deny Request", key=f"h_rej_{s['_id']}"):
                        spots_col.update_one(
                            {"_id": s["_id"]},
                            {"$set": {"status": "Available", "booked_by": None}}
                        )
                        st.rerun()

                if "start_time" in s and "end_time" in s:
                    st.caption(
                        f"Visible: {s['start_time'].strftime('%d-%m-%Y %I:%M %p')} "
                        f"to {s['end_time'].strftime('%d-%m-%Y %I:%M %p')}"
                    )

                    if now < s["start_time"]:
                        st.markdown('<span class="badge badge-orange">Scheduled</span>', unsafe_allow_html=True)
                    elif now > s["end_time"]:
                        st.markdown('<span class="badge badge-red">Expired - Hidden from Drivers</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="badge badge-green">Live - Visible to Drivers</span>', unsafe_allow_html=True)
                else:
                    st.warning("Old post - No visibility time added")

            with cc:
                st.markdown(
                    f'<div class="price-text">₹{s.get("price", 0)}/hr</div>',
                    unsafe_allow_html=True
                )

                status = s.get("status", "Unknown")

                if status == "Available":
                    st.markdown('<span class="badge badge-green">Available</span>', unsafe_allow_html=True)
                elif status == "Booked":
                    st.markdown('<span class="badge badge-orange">Booked</span>', unsafe_allow_html=True)
                elif status == "Occupied":
                    st.markdown('<span class="badge badge-blue">Occupied</span>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<span class="badge badge-dark">{status}</span>', unsafe_allow_html=True)

                if st.button("🗑️ Remove Post", key=f"remove_{s['_id']}"):
                    spots_col.delete_one({
                        "_id": s["_id"],
                        "host": user["user"]
                    })
                    st.success("Post removed successfully!")
                    sleep_time.sleep(1)
                    st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)


    # ---------------- DRIVER PORTAL ----------------
    else:
        st.markdown("""
        <div class="hero-card">
            <h1>Find Parking Nearby</h1>
            <p>View live parking spots, check GPS location, open Google Maps and request parking instantly.</p>
        </div>
        """, unsafe_allow_html=True)

        t_find, t_mine = st.tabs([" Find Parking", " My Bookings"])

        with t_find:
            now = datetime.now()

            available = list(spots_col.find({
                "status": "Available",
                "start_time": {"$lte": now},
                "end_time": {"$gte": now}
            }))

            st.markdown(f"### Available Now: {len(available)}")

            if not available:
                st.info("No spots available right now.")

            for s in available:
                st.markdown('<div class="parking-card">', unsafe_allow_html=True)

                ca, cb, cc = st.columns([1.2, 2.2, 1])

                with ca:
                    if "image_data" in s:
                        st.image(s["image_data"], use_container_width=True)

                with cb:
                    st.markdown(
                        f'<div class="location-title">{s.get("address", "No Address")}</div>',
                        unsafe_allow_html=True
                    )

                    if "lat" in s and "lon" in s:
                        st.markdown(
                            f'<span class="badge badge-dark">GPS: {round(s["lat"], 6)}, {round(s["lon"], 6)}</span>',
                            unsafe_allow_html=True
                        )

                    st.markdown(
                        f'<span class="badge badge-blue">{s.get("location_source", "Unknown Source")}</span>',
                        unsafe_allow_html=True
                    )

                    if "maps_link" in s:
                        st.markdown(f"[Open Location in Google Maps]({s['maps_link']})")

                    if "start_time" in s and "end_time" in s:
                        st.caption(
                            f"Available from {s['start_time'].strftime('%d-%m-%Y %I:%M %p')} "
                            f"to {s['end_time'].strftime('%d-%m-%Y %I:%M %p')}"
                        )

                with cc:
                    st.markdown(
                        f'<div class="price-text">₹{s.get("price", 0)}/hr</div>',
                        unsafe_allow_html=True
                    )

                    st.markdown('<span class="badge badge-green">Available Now</span>', unsafe_allow_html=True)

                    if st.button("Accept Price", key=f"d_acc_{s['_id']}"):
                        logs_col.insert_one({
                            "lat": s["lat"],
                            "lon": s["lon"],
                            "hour": s["hour"],
                            "quality": s["quality"],
                            "price": s["price"],
                            "outcome": "Accepted",
                            "timestamp": datetime.now()
                        })

                        spots_col.update_one(
                            {"_id": s["_id"]},
                            {"$set": {"status": "Booked", "booked_by": user["user"]}}
                        )

                        retrain_model()
                        st.success("Request sent to Host!")
                        sleep_time.sleep(1)
                        st.rerun()

                    if st.button("💸 Too Costly", key=f"d_dec_{s['_id']}"):
                        logs_col.insert_one({
                            "lat": s["lat"],
                            "lon": s["lon"],
                            "hour": s["hour"],
                            "quality": s["quality"],
                            "price": s["price"],
                            "outcome": "Declined",
                            "timestamp": datetime.now()
                        })

                        retrain_model()
                        st.error("Reported: Price too high.")
                        sleep_time.sleep(1)
                        st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)

        with t_mine:
            mine = list(spots_col.find({"booked_by": user["user"]}))

            if not mine:
                st.info("No bookings yet.")

            for t in mine:
                st.markdown('<div class="parking-card">', unsafe_allow_html=True)

                c1, c2, c3 = st.columns([1.2, 2.2, 1])

                with c1:
                    if "image_data" in t:
                        st.image(t["image_data"], use_container_width=True)

                with c2:
                    st.markdown(
                        f'<div class="location-title">{t.get("address", "No Address")}</div>',
                        unsafe_allow_html=True
                    )

                    if "lat" in t and "lon" in t:
                        st.markdown(
                            f'<span class="badge badge-dark">GPS: {round(t["lat"], 6)}, {round(t["lon"], 6)}</span>',
                            unsafe_allow_html=True
                        )

                    if "maps_link" in t:
                        st.markdown(f"[Open Location in Google Maps]({t['maps_link']})")

                    if "start_time" in t and "end_time" in t:
                        st.caption(
                            f"Booking window: {t['start_time'].strftime('%d-%m-%Y %I:%M %p')} "
                            f"to {t['end_time'].strftime('%d-%m-%Y %I:%M %p')}"
                        )

                with c3:
                    st.markdown(
                        f'<div class="price-text">₹{t.get("price", 0)}/hr</div>',
                        unsafe_allow_html=True
                    )

                    status = t.get("status", "Unknown")

                    if status == "Occupied":
                        st.markdown('<span class="badge badge-green">Approved</span>', unsafe_allow_html=True)
                    elif status == "Booked":
                        st.markdown('<span class="badge badge-orange">Pending</span>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<span class="badge badge-dark">{status}</span>', unsafe_allow_html=True)

                st.markdown('</div>', unsafe_allow_html=True)