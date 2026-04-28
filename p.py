import streamlit as st
import pymongo
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import joblib
import os
from datetime import datetime
import random
import time
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim

# --- DATABASE CONFIGURATION ---
client = pymongo.MongoClient("mongodb+srv://admin:1234@cluster0.vbcsfq7.mongodb.net/?appName=Cluster0")
db = client["GlobalCurb"]
spots_col = db["world_spots"]
users_col = db["users"]
logs_col = db["live_training_logs"]

MODEL_PATH = 'adaptive_brain.pkl'

# --- HELPER: STATUS BADGE (TRAFFIC LIGHTS) ---
def get_status_badge(status):
    color_map = {
        "Available": "#2ecc71", # Green
        "Booked": "#f39c12",    # Orange/Amber
        "Occupied": "#e74c3c"   # Red
    }
    bg_color = color_map.get(status, "#7f8c8d")
    return f"""
        <div style="background-color: {bg_color}; color: white; padding: 5px 15px; 
        border-radius: 20px; display: inline-block; font-size: 12px; font-weight: bold; 
        text-transform: uppercase; letter-spacing: 1px;">
            {status}
        </div>
    """

# --- AI PRICING BRAIN ---
def get_dynamic_price(lat, lon, hr, q):
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            features = pd.DataFrame([[lat, lon, hr, q]], columns=['lat', 'lon', 'hour', 'quality'])
            pred = model.predict(features)[0]
            return round(max(30.0, min(pred, 250.0)), 2)
        except:
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
        success_df = df[df['outcome'] == 'Accepted']
        if len(success_df) >= 3:
            X = success_df[['lat', 'lon', 'hour', 'quality']]
            y = success_df['price']
            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model.fit(X, y)
            joblib.dump(model, MODEL_PATH)

# --- MODERN UI STYLING ---
st.set_page_config(page_title="CURBIT. | Mobility", layout="wide")
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; background-color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #000000 !important; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    div.stButton > button { 
        background-color: #000; color: #fff; border-radius: 8px; 
        width: 100%; border: none; padding: 12px; font-weight: bold;
        transition: 0.3s;
    }
    div.stButton > button:hover { background-color: #333; transform: translateY(-2px); }
    a { text-decoration: none; color: #007bff; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- GEO-ENGINE ---
def get_pan_india_address(lat, lon):
    try:
        geolocator = Nominatim(user_agent="curbit_v3")
        location = geolocator.reverse(f"{lat}, {lon}", timeout=5)
        if location and 'address' in location.raw:
            a = location.raw['address']
            area = a.get('suburb', a.get('neighbourhood', a.get('road', 'Residential Area')))
            city = a.get('city', a.get('town', 'Unknown City'))
            return f"{area}, {city}"
        return f"Node {lat:.2f}, {lon:.2f}"
    except:
        return "Network Node"

# --- AUTH LOGIC ---
if 'user' not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<h1 style='text-align:center; font-size:65px; letter-spacing:-4px;'>CURBIT.</h1>", unsafe_allow_html=True)
        t_l, t_r = st.tabs(["Login", "Register"])
        with t_l:
            u_in = st.text_input("Username")
            p_in = st.text_input("Password", type="password")
            if st.button("SIGN IN"):
                res = users_col.find_one({"user": u_in, "pass": p_in})
                if res: st.session_state.user = res; st.rerun()
                else: st.error("Access Denied")
        with t_r:
            u_reg = st.text_input("New Username")
            p_reg = st.text_input("New Password", type="password")
            role = st.selectbox("I am a", ["Host (Owner)", "Driver (User)"])
            if st.button("CREATE ACCOUNT"):
                users_col.insert_one({"user": u_reg, "pass": p_reg, "role": role})
                st.success("Registered!")
else:
    user = st.session_state.user
    st.sidebar.markdown(f"## CURBIT.")
    st.sidebar.write(f"User: **{user['user']}**")
    st.sidebar.write(f"Role: **{user['role']}**")
    
    loc = get_geolocation()
    lat, lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc and 'coords' in loc else (18.62, 73.79)

    if st.sidebar.button("SIGN OUT"):
        st.session_state.user = None
        st.rerun()

    # --- HOST PORTAL ---
    if "Host" in user['role']:
        st.title("Host Management Console")
        my_assets = list(spots_col.find({"host": user['user']}))
        
        # Calculate earnings
        rev = sum([s['price'] for s in my_assets if s['status'] == "Occupied"])
        st.metric("TOTAL LIVE REVENUE", f"₹{rev}")
        
        st.divider()
        with st.expander("➕ REGISTER NEW ASSET", expanded=False):
            f = st.file_uploader("Spot Image", type=['jpg', 'png'])
            if f:
                st.image(f, width=300)
                q, hr = random.choice([0, 1]), datetime.now().hour
                addr = get_pan_india_address(lat, lon)
                d_price = get_dynamic_price(lat, lon, hr, q)
                
                st.info(f"📍 Node: {addr}")
                st.markdown(f"### AI Suggested Price: **₹{d_price}/hr**")
                
                if st.button("PUBLISH TO MARKET"):
                    spots_col.insert_one({
                        "host": user['user'], "price": d_price, 
                        "lat": lat, "lon": lon, "address": addr, 
                        "status": "Available", "image_data": f.getvalue(),
                        "hour": hr, "quality": q
                    })
                    st.success("Market Listing Active!")
                    time.sleep(1); st.rerun()

        st.divider()
        st.subheader("Asset Inventory")
        for s in my_assets:
            with st.container(border=True):
                ca, cb, cc = st.columns([1, 2, 1.2])
                if "image_data" in s: ca.image(s['image_data'], width=120)
                
                with cb:
                    st.write(f"**{s['address']}**")
                    st.markdown(f"[View Location on Maps](https://www.google.com/maps?q={s['lat']},{s['lon']})")
                    if s['status'] == "Booked":
                        st.warning(f"Booking Request: {s.get('booked_by')}")
                        b1, b2 = st.columns(2)
                        if b1.button("APPROVE", key=f"h_acc_{s['_id']}"):
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Occupied"}})
                            st.rerun()
                        if b2.button("DECLINE", key=f"h_rej_{s['_id']}"):
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Available", "booked_by": None}})
                            st.rerun()
                
                with cc:
                    st.write(f"**₹{s['price']}/hr**")
                    st.markdown(get_status_badge(s['status']), unsafe_allow_html=True)

    # --- DRIVER PORTAL ---
    else:
        st.title("Urban Navigation")
        t_find, t_mine = st.tabs(["Find Infrastructure", " My Bookings"])
        
        with t_find:
            available = list(spots_col.find({"status": "Available"}))
            if not available: st.info("Scanning for nodes... No vacant spots found.")
            for s in available:
                with st.container(border=True):
                    ca, cb = st.columns([1.5, 3])
                    with ca: st.image(s['image_data'], use_container_width=True)
                    with cb:
                        st.subheader(s['address'])
                        st.markdown(f"[📍 Get Directions](https://www.google.com/maps?q={s['lat']},{s['lon']})")
                        st.write(f"### Rate: ₹{s['price']}/hr")
                        
                        c_acc, c_dec = st.columns(2)
                        if c_acc.button("BOOK SESSION", key=f"d_acc_{s['_id']}"):
                            logs_col.insert_one({
                                "lat": s['lat'], "lon": s['lon'], "hour": s['hour'], 
                                "quality": s['quality'], "price": s['price'], "outcome": "Accepted",
                                "timestamp": datetime.now()
                            })
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Booked", "booked_by": user['user']}})
                            retrain_model()
                            st.success("Handshake initiated with Host!")
                            time.sleep(1); st.rerun()
                            
                        if c_dec.button("PRICE TOO HIGH", key=f"d_dec_{s['_id']}"):
                            logs_col.insert_one({
                                "lat": s['lat'], "lon": s['lon'], "hour": s['hour'], 
                                "quality": s['quality'], "price": s['price'], "outcome": "Declined",
                                "timestamp": datetime.now()
                            })
                            retrain_model()
                            st.error("Log updated. Calibrating AI...")
                            time.sleep(1); st.rerun()

        with t_mine:
            mine = list(spots_col.find({"booked_by": user['user']}))
            if not mine: st.caption("No active bookings.")
            for t in mine:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 2, 1])
                    if "image_data" in t: c1.image(t['image_data'], width=150)
                    with c2:
                        st.write(f"### {t['address']}")
                        st.markdown(f"[📍 Open Location Route](https://www.google.com/maps?q={t['lat']},{t['lon']})")
                        st.markdown(get_status_badge(t['status']), unsafe_allow_html=True)
                    with c3:
                        st.write(f"**₹{t['price']}/hr**")
                        if st.button("RELEASE SLOT", key=f"rel_{t['_id']}"):
                            spots_col.update_one({"_id": t['_id']}, {"$set": {"status": "Available", "booked_by": None}})
                            st.success("Slot Released!")
                            time.sleep(1); st.rerun()