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

# --- AI PRICING BRAIN ---
def get_dynamic_price(lat, lon, hr, q):
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            pred = model.predict([[lat, lon, hr, q]])[0]
            return round(max(30.0, min(pred, 250.0)), 2)
        except:
            pass 
    
    base = 40.0  
    is_peak = (8 <= hr <= 11) or (17 <= hr <= 21)
    multiplier = 1.3 if is_peak else 1.0
    quality_bonus = 20.0 if q == 1 else 0.0
    return (base * multiplier) + quality_bonus

def retrain_model():
    """Retrains the model using both Accepted and Declined logs."""
    logs = list(logs_col.find())
    if len(logs) > 5:
        df = pd.DataFrame(logs)
        # Brain learns from Successful (Accepted) transactions to predict future 'Good' prices
        success_df = df[df['outcome'] == 'Accepted']
        if len(success_df) > 2:
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
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    [data-testid="stSidebar"] { background-color: #000000 !important; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    div.stButton > button { 
        background-color: #000; color: #fff; border-radius: 8px; 
        width: 100%; border: none; padding: 12px; font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# --- GEO-ENGINE ---
def get_pan_india_address(lat, lon):
    try:
        geolocator = Nominatim(user_agent="curbit_v2")
        location = geolocator.reverse(f"{lat}, {lon}", timeout=5)
        if location and 'address' in location.raw:
            a = location.raw['address']
            area = a.get('suburb', a.get('neighbourhood', 'Residential Area'))
            city = a.get('city', a.get('town', 'Unknown City'))
            return f"{area}, {city}"
        return f"Node {lat:.2f}"
    except:
        return "Network Node"

# --- AUTH LOGIC ---
if 'user' not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<h1 style='text-align:center; font-size:60px;'>CURBIT.</h1>", unsafe_allow_html=True)
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
    
    loc = get_geolocation()
    lat, lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc and 'coords' in loc else (18.62, 73.79)

    if st.sidebar.button("SIGN OUT"):
        st.session_state.user = None
        st.rerun()

    # --- HOST PORTAL ---
    if "Host" in user['role']:
        st.title("Host Dashboard")
        
        my_assets = list(spots_col.find({"host": user['user']}))
        rev = sum([s['price'] for s in my_assets if s['status'] == "Occupied"])
        st.metric("LIVE EARNINGS", f"₹{rev}")
        
        st.divider()
        
        for s in my_assets:
            with st.container(border=True):
                ca, cb, cc = st.columns([1, 2, 1])
                if "image_data" in s: ca.image(s['image_data'], width=100)
                
                if s['status'] == "Booked":
                    cb.warning(f"Request from: {s.get('booked_by')}")
                    b1, b2 = cb.columns(2)
                    if b1.button("Allow Parking", key=f"h_acc_{s['_id']}"):
                        spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Occupied"}})
                        st.rerun()
                    if b2.button("Deny Request", key=f"h_rej_{s['_id']}"):
                        spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Available", "booked_by": None}})
                        st.rerun()
                else:
                    cb.write(f"**{s['address']}**")
                
                cc.write(f"₹{s['price']}/hr")
                cc.caption(f"Status: {s['status']}")

        with st.expander("➕ PUBLISH NEW SPOT"):
            f = st.file_uploader("Upload Image", type=['jpg', 'png'])
            if f:
                q, hr = random.choice([0, 1]), datetime.now().hour
                addr = get_pan_india_address(lat, lon)
                d_price = get_dynamic_price(lat, lon, hr, q)
                st.write(f"📍 {addr} | Suggested Price: **₹{d_price}/hr**")
                if st.button("CONFIRM & PUBLISH"):
                    spots_col.insert_one({
                        "host": user['user'], "price": d_price, "lat": lat, "lon": lon,
                        "address": addr, "status": "Available", "image_data": f.getvalue(),
                        "hour": hr, "quality": q
                    })
                    st.rerun()

    # --- DRIVER PORTAL (THE FEEDBACK LOOP) ---
    else:
        st.title("Nearby Infrastructure")
        t_find, t_mine = st.tabs(["🔍 Find Parking", "My Bookings"])
        
        with t_find:
            available = list(spots_col.find({"status": "Available"}))
            if not available: st.info("No spots found nearby.")
            for s in available:
                with st.container(border=True):
                    ca, cb = st.columns([1, 2])
                    with ca: st.image(s['image_data'], use_container_width=True)
                    with cb:
                        st.subheader(s['address'])
                        st.write(f"### AI Rate: ₹{s['price']}/hr")
                        
                        # DRIVER BUTTONS
                        c_acc, c_dec = st.columns(2)
                        
                        if c_acc.button("✅ ACCEPT PRICE", key=f"d_acc_{s['_id']}"):
                            # Log success to AI
                            logs_col.insert_one({
                                "lat": s['lat'], "lon": s['lon'], "hour": s['hour'], 
                                "quality": s['quality'], "price": s['price'], "outcome": "Accepted"
                            })
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Booked", "booked_by": user['user']}})
                            retrain_model()
                            st.success("Request Sent!")
                            time.sleep(1); st.rerun()
                            
                        if c_dec.button("❌ TOO COSTLY", key=f"d_dec_{s['_id']}"):
                            # Log rejection to AI
                            logs_col.insert_one({
                                "lat": s['lat'], "lon": s['lon'], "hour": s['hour'], 
                                "quality": s['quality'], "price": s['price'], "outcome": "Declined"
                            })
                            retrain_model() # Learns this was too expensive
                            st.error("Reported: Price is too high.")
                            time.sleep(1); st.rerun()

        with t_mine:
            mine = list(spots_col.find({"booked_by": user['user']}))
            for t in mine:
                with st.container(border=True):
                    st.write(f"### {t['address']} - ₹{t['price']}/hr")
                    st.write(f"Current Status: **{t['status']}**")