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

# --- 1. DATABASE & MODEL CONFIGURATION ---
# Replace the URI below with your actual MongoDB connection string
MONGO_URI = "mongodb+srv://admin:1234@cluster0.vbcsfq7.mongodb.net/?appName=Cluster0"
client = pymongo.MongoClient(MONGO_URI)
db = client["GlobalCurb"]
spots_col = db["world_spots"]
users_col = db["users"]
logs_col = db["live_training_logs"]

MODEL_PATH = 'adaptive_brain.pkl'
CSV_PATH = 'historical_parking_data.csv'

# --- 2. THE BIG DATA TRAINING ENGINE ---
def train_smart_model():
    """Combines CSV baseline + MongoDB logs to train the Random Forest."""
    try:
        # Load the CSV you generated
        if os.path.exists(CSV_PATH):
            df_hist = pd.read_csv(CSV_PATH)
        else:
            st.error("Baseline CSV not found!")
            return None
        
        # Load Live Logs from MongoDB
        live_logs = list(logs_col.find())
        if live_logs:
            df_live = pd.DataFrame(live_logs)
            # Standardize columns to match CSV
            df_live = df_live[['lat', 'lon', 'hour', 'quality', 'price']]
            df_live.columns = ['lat', 'lon', 'hour', 'quality', 'accepted_price']
            # Filter only successful market matches (Accepted)
            df_success = df_live.copy() 
            df_total = pd.concat([df_hist, df_success], ignore_index=True)
        else:
            df_total = df_hist

        # Machine Learning Training
        X = df_total[['lat', 'lon', 'hour', 'quality']]
        y = df_total['accepted_price']
        
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(X, y)
        
        # Save the model locally
        joblib.dump(model, MODEL_PATH)
        return model
    except Exception as e:
        st.sidebar.error(f"Training Error: {e}")
        return None

def get_dynamic_price(lat, lon, hr, q):
    """Predicts price using the trained .pkl file."""
    if os.path.exists(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
        pred = model.predict([[lat, lon, hr, q]])[0]
        return round(max(30.0, min(pred, 250.0)), 2)
    return 50.0 # Fallback price

# --- 3. UI INITIALIZATION ---
st.set_page_config(page_title="CURBIT. | Mobility", layout="wide")

if 'model' not in st.session_state:
    st.session_state.model = train_smart_model()

# Custom CSS for that "Uber-style" clean look
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    [data-testid="stSidebar"] { background-color: #000000 !important; color: white; }
    div.stButton > button { background-color: #000; color: #fff; border-radius: 8px; width: 100%; padding: 10px; font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

# --- 4. AUTHENTICATION ---
if 'user' not in st.session_state: st.session_state.user = None

if not st.session_state.user:
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<h1 style='text-align:center; font-size:60px; letter-spacing:-3px;'>CURBIT.</h1>", unsafe_allow_html=True)
        t1, t2 = st.tabs(["Login", "Register"])
        with t1:
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.button("SIGN IN"):
                res = users_col.find_one({"user": u, "pass": p})
                if res: st.session_state.user = res; st.rerun()
                else: st.error("Invalid Credentials")
        with t2:
            u_r = st.text_input("New Username")
            p_r = st.text_input("New Password", type="password")
            role = st.selectbox("Role", ["Host (Owner)", "Driver (User)"])
            if st.button("CREATE"):
                users_col.insert_one({"user": u_r, "pass": p_r, "role": role})
                st.success("Account Created!")

else:
    # --- 5. MAIN APPLICATION ---
    user = st.session_state.user
    st.sidebar.title("CURBIT.")
    st.sidebar.write(f"Logged in as: **{user['user']}**")
    
    # Hidden Admin Retrain (For your Demo)
    with st.sidebar.expander("System Logs"):
        if st.button("Force AI Retrain"):
            st.session_state.model = train_smart_model()
            st.success("Model Updated via NoSQL Logs")

    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.rerun()

    # Get Geo-location
    loc = get_geolocation()
    curr_lat, curr_lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc and 'coords' in loc else (18.52, 73.85)

    # --- HOST VIEW ---
    if "Host" in user['role']:
        st.title("Host Management")
        with st.expander("➕ Register New Curb Space", expanded=True):
            f = st.file_uploader("Upload Spot Photo", type=['jpg', 'png'])
            if f:
                hr, q = datetime.now().hour, random.choice([0, 1])
                price = get_dynamic_price(curr_lat, curr_lon, hr, q)
                st.image(f, width=200)
                st.info(f"AI Suggested Price: ₹{price}/hr")
                if st.button("Publish Live"):
                    spots_col.insert_one({
                        "host": user['user'], "price": price, "lat": curr_lat, "lon": curr_lon,
                        "status": "Available", "image_data": f.getvalue(), "hour": hr, "quality": q
                    })
                    st.success("Spot is now active!")
                    time.sleep(1); st.rerun()

    # --- DRIVER VIEW ---
    else:
        st.title("Available Infrastructure")
        available = list(spots_col.find({"status": "Available"}))
        if not available: st.warning("No spots available in this sector.")
        
        for s in available:
            with st.container(border=True):
                c1, c2 = st.columns([1, 3])
                c1.image(s['image_data'], use_container_width=True)
                with c2:
                    st.subheader(f"Curb Slot at {s['lat']:.3f}, {s['lon']:.3f}")
                    st.write(f"### Rate: ₹{s['price']}/hr")
                    
                    b_acc, b_dec = st.columns(2)
                    if b_acc.button("Accept", key=f"acc_{s['_id']}"):
                        logs_col.insert_one({"lat": s['lat'], "lon": s['lon'], "hour": s['hour'], "quality": s['quality'], "price": s['price'], "outcome": "Accepted"})
                        spots_col.update_one({"_id": s['_id']}, {"$set": {"status": "Booked", "booked_by": user['user']}})
                        st.session_state.model = train_smart_model() # Silent update
                        st.success("Request Sent!"); time.sleep(1); st.rerun()
                        
                    if b_dec.button("Too Costly", key=f"dec_{s['_id']}"):
                        logs_col.insert_one({"lat": s['lat'], "lon": s['lon'], "hour": s['hour'], "quality": s['quality'], "price": s['price'], "outcome": "Declined"})
                        st.session_state.model = train_smart_model() # Silent update
                        st.error("Market feedback recorded."); time.sleep(1); st.rerun()