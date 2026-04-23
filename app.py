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
# Ensure your MongoDB IP Access is set to 0.0.0.0/0 in Atlas!
client = pymongo.MongoClient("mongodb+srv://admin:1234@cluster0.vbcsfq7.mongodb.net/?appName=Cluster0")
db = client["GlobalCurb"]
spots_col = db["world_spots"]
users_col = db["users"]
logs_col = db["live_training_logs"]

MODEL_PATH = 'adaptive_brain.pkl'

# --- AI PRICING BRAIN ---
def get_dynamic_price(lat, lon, hr, q):
    """Calculates price using AI or fallback logic with a realistic bracket."""
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            pred = model.predict([[lat, lon, hr, q]])[0]
            # Safety rails: Minimum 30, Maximum 250
            return round(max(30.0, min(pred, 250.0)), 2)
        except:
            pass 
    
    # NEW LOW-COST FALLBACK (Market Entry Pricing)
    base = 40.0  
    is_peak = (8 <= hr <= 11) or (17 <= hr <= 21)
    multiplier = 1.3 if is_peak else 1.0
    quality_bonus = 20.0 if q == 1 else 0.0
    return (base * multiplier) + quality_bonus

def retrain_model():
    """Trains the AI only on SUCCESSFUL (Accepted) bookings."""
    # We filter for 'Accepted' so the brain doesn't learn from rejected high prices
    logs = list(logs_col.find({"outcome": "Accepted"}))
    if len(logs) > 2:
        df = pd.DataFrame(logs)
        X = df[['lat', 'lon', 'hour', 'quality']]
        y = df['price']
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
        width: 100%; border: none; padding: 14px; font-weight: bold;
        margin-top: 15px; transition: 0.3s;
    }
    div.stButton > button:hover { background-color: #333; }
    </style>
""", unsafe_allow_html=True)

# --- PAN-INDIA GEO-ENGINE ---
def get_pan_india_address(lat, lon):
    try:
        geolocator = Nominatim(user_agent="curbit_v2_pune")
        location = geolocator.reverse(f"{lat}, {lon}", timeout=5)
        if location and 'address' in location.raw:
            a = location.raw['address']
            area = a.get('suburb', a.get('neighbourhood', a.get('residential', '')))
            city = a.get('city', a.get('town', a.get('village', 'Unknown City')))
            return f"{area}, {city}" if area else city
        return f"Node {lat:.2f}"
    except:
        return "Network Node"

# --- AUTH LOGIC ---
if 'user' not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<h1 style='text-align:center; font-size:65px; letter-spacing:-4px;'>CURBIT.</h1>", unsafe_allow_html=True)
        t_l, t_r = st.tabs(["Login", "Register"])
        with t_l:
            u_in = st.text_input("Username", key="login_u")
            p_in = st.text_input("Password", type="password", key="login_p")
            if st.button("SIGN IN"):
                res = users_col.find_one({"user": u_in, "pass": p_in})
                if res: st.session_state.user = res; st.rerun()
                else: st.error("Access Denied")
        with t_r:
            u_reg = st.text_input("Set Username")
            p_reg = st.text_input("Set Password", type="password")
            role = st.selectbox("I am a", ["Host (Owner)", "Driver (User)"])
            if st.button("CREATE ACCOUNT"):
                users_col.insert_one({"user": u_reg, "pass": p_reg, "role": role})
                st.success("Registered! Go to Login.")
else:
    user = st.session_state.user
    st.sidebar.markdown(f"## CURBIT.")
    st.sidebar.write(f"Verified: **{user['user']}**")
    
    # Live GPS Tracking with safety check
    loc = get_geolocation()
    if loc and 'coords' in loc:
        lat, lon = (loc['coords']['latitude'], loc['coords']['longitude'])
    else:
        lat, lon = (18.62, 73.79) # Default to Pune/Chinchwad

    if st.sidebar.button("SIGN OUT"):
        st.session_state.user = None
        st.rerun()

    # --- HOST PORTAL ---
    if "Host" in user['role']:
        st.title("Host Dashboard")
        
        @st.fragment(run_every="5s") # Auto-refresh to see new bookings
        def host_ui():
            my_assets = list(spots_col.find({"host": user['user']}))
            
            # Show Metrics
            rev = sum([s['price'] for s in my_assets if s['status'] == "Occupied"])
            active = len([s for s in my_assets if s['status'] == "Available"])
            c1, c2 = st.columns(2)
            c1.metric("LIVE EARNINGS", f"₹{rev}")
            c2.metric("ACTIVE NODES", active)
            
            st.divider()
            
            for s in my_assets:
                with st.container(border=True):
                    ca, cb, cc = st.columns([1, 2, 1])
                    if "image_data" in s: ca.image(s['image_data'], width=100)
                    
                    # Manage Booking Requests
                    if s['status'] == "Booked":
                        cb.warning(f"Request from: {s.get('booked_by')}")
                        btn_col1, btn_col2 = cb.columns(2)
                        if btn_col1.button("Accept", key=f"acc_{s['_id']}"):
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Occupied"}})
                            logs_col.insert_one({
                                "lat": s['lat'], "lon": s['lon'], "hour": s['hour'], 
                                "quality": s['quality'], "price": s['price'], "outcome": "Accepted"
                            })
                            retrain_model()
                            st.rerun()
                        if btn_col2.button("Decline", key=f"dec_{s['_id']}"):
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Available", "booked_by": None}})
                            logs_col.insert_one({
                                "lat": s['lat'], "lon": s['lon'], "hour": s['hour'], 
                                "quality": s['quality'], "price": s['price'], "outcome": "Declined"
                            })
                            # Retrain even on decline so AI understands the rejection boundary
                            retrain_model() 
                            st.rerun()
                    else:
                        cb.write(f"**{s['address']}**")
                    
                    cc.write(f"₹{s['price']}/hr")
                    status_emoji = "🟢" if s['status']=="Available" else "🟡" if s['status']=="Booked" else "🔴"
                    cc.caption(f"{status_emoji} {s['status']}")

        host_ui()

        with st.expander("➕ PUBLISH NEW PARKING SPOT"):
            f = st.file_uploader("Upload Image", type=['jpg', 'png'])
            if f:
                st.image(f, width=300)
                q = random.choice([0, 1]) 
                hr = datetime.now().hour
                with st.spinner("Analyzing Location & Demand..."):
                    addr = get_pan_india_address(lat, lon)
                    d_price = get_dynamic_price(lat, lon, hr, q)
                
                st.write(f"📍 **{addr}**")
                st.write(f"### Suggested Price : ₹{d_price}/hr")
                
                if st.button("CONFIRM & PUBLISH"):
                    spots_col.insert_one({
                        "host": user['user'], "price": d_price, "lat": lat, "lon": lon,
                        "address": addr, "status": "Available", "image_data": f.getvalue(),
                        "hour": hr, "quality": q
                    })
                    st.toast("Published Successfully!")
                    time.sleep(1); st.rerun()

    # --- DRIVER PORTAL ---
    else:
        st.title("Nearby Infrastructure")
        t_find, t_mine = st.tabs(["🔍 Browse Spots", "My Bookings"])
        
        with t_find:
            available = list(spots_col.find({"status": "Available"}))
            if not available: st.info("Scanning for parking spots..")
            for s in available:
                with st.container(border=True):
                    ca, cb = st.columns([1, 2])
                    with ca: st.image(s['image_data'], use_container_width=True)
                    with cb:
                        st.subheader(s['address'])
                        st.write(f"**Rate:** ₹{s['price']}/hr")
                        if st.button("REQUEST BOOKING", key=str(s['_id'])):
                            spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Booked", "booked_by": user['user']}})
                            st.success("Request Sent to Host!")
                            time.sleep(1); st.rerun()

        with t_mine:
            mine = list(spots_col.find({"booked_by": user['user']}))
            if not mine: st.caption("No active bookings.")
            for t in mine:
                with st.container(border=True):
                    c1, c2 = st.columns([1, 2])
                    c1.image(t['image_data'], use_container_width=True)
                    c2.write(f"### {t['address']}")
                    status_color = "Green" if t['status'] == "Occupied" else "Orange"
                    c2.markdown(f"Status: **:{status_color}[{t['status']}]**")
                    if t['status'] == "Occupied":
                        maps_url = f"https://www.google.com/maps?q={t['lat']},{t['lon']}"
                        c2.link_button("Start Navigation", maps_url)
                    else:
                        c2.info("Waiting for Host to Accept...")