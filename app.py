from flask import Flask, jsonify, render_template
import requests
import threading
import websocket
import json
import time
import random
from skyfield.api import load, wgs84
import os  # <--- Replaced 'import config' with the built-in 'os' library

app = Flask(__name__)

live_ships = {}
live_planes = {"states": []} 
live_satellites = {"sats": []}

# --- GLOBAL GHOST FLEET SIMULATOR ---
def generate_ghost_fleet():
    ghosts = []
    for i in range(400): 
        lat = random.uniform(-60.0, 70.0) 
        lon = random.uniform(-180.0, 180.0) 
        heading = random.uniform(0, 360)
        speed = random.uniform(200, 260) 
        
        ghosts.append([
            f"GHOST{i}", f"SIM-{i}", "GLOBAL", None, None,
            lon, lat, 10000, False, speed, heading,       
        ])
    return ghosts

def run_plane_fetcher():
    url = 'https://opensky-network.org/api/states/all'
    
    my_opensky_auth = (
        os.environ.get("OPENSKY_USERNAME", "wallma"), 
        os.environ.get("OPENSKY_PASSWORD", "")
    ) 

    while True:
        try:
            headers = {'User-Agent': 'Python/GlobalRadarProject'}
            response = requests.get(url, auth=my_opensky_auth, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data and data.get('states'):
                    valid_planes = [p for p in data["states"] if p[5] is not None and p[6] is not None]
                    live_planes["states"] = random.sample(valid_planes, min(200, len(valid_planes)))
                    print(f"Planes updated: {len(live_planes['states'])} real aircraft tracked.")
            else:
                # TRIGGERS ON ANY ERROR (429 Ban, 403 Datacenter Block, etc.)
                print(f"OpenSky API Error {response.status_code}. Deploying GLOBAL Ghost Fleet...")
                live_planes["states"] = generate_ghost_fleet()
        except Exception as e:
            pass
        
        time.sleep(60) 





def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("MessageType") == "PositionReport":
            msg = data["Message"]["PositionReport"]
            meta = data["MetaData"]
            mmsi = meta["MMSI"]
            live_ships[mmsi] = {
                "id": meta["ShipName"].strip() or str(mmsi),
                "lat": msg["Latitude"],
                "lon": msg["Longitude"],
                "heading": msg["TrueHeading"],
                "speed": msg["Sog"] 
            }
            if len(live_ships) > 200:
                live_ships.pop(next(iter(live_ships)))
    except Exception as e:
        pass 

def on_error(ws, error): pass

def on_open(ws):
    print("Connected to AISStream!")
    subscription = {
        # READS DIRECTLY FROM THE CLOUD VAULT!
        "APIKey": os.environ.get("AISSTREAM_API_KEY", ""), 
        "BoundingBoxes": [
            [[24.0, 54.0], [27.0, 57.0]],    
            [[24.0, -125.0], [50.0, -66.0]]  
        ]
    }
    ws.send(json.dumps(subscription))

def run_websocket():
    while True:
        ws = websocket.WebSocketApp("wss://stream.aisstream.io/v0/stream", on_message=on_message, on_error=on_error, on_open=on_open)
        ws.run_forever()
        time.sleep(5) 

def run_satellite_tracker():
    print("Downloading Orbital Data from Celestrak...")
    stations_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'
    ts = load.timescale()
    satellites = load.tle_file(stations_url)
    
    swarm = [sat for sat in satellites if 'STARLINK' in sat.name or 'ISS' in sat.name]
    tracked_sats = random.sample(swarm, min(100, len(swarm)))

    while True:
        try:
            t0 = ts.now()
            t1 = ts.tt_jd(t0.tt + (1.0 / 86400.0)) 
            sat_data = []
            
            for sat in tracked_sats:
                p0 = wgs84.subpoint(sat.at(t0))
                p1 = wgs84.subpoint(sat.at(t1))
                
                dlon = p1.longitude.degrees - p0.longitude.degrees
                if dlon > 180: dlon -= 360
                elif dlon < -180: dlon += 360
                
                sat_data.append({
                    "id": sat.name,
                    "lat": p0.latitude.degrees,
                    "lon": p0.longitude.degrees,
                    "alt": p0.elevation.km,
                    "dlat": p1.latitude.degrees - p0.latitude.degrees,
                    "dlon": dlon 
                })
            live_satellites["sats"] = sat_data
        except Exception as e:
            pass
        time.sleep(15) 

# --- START WORKERS ---
threading.Thread(target=run_websocket, daemon=True).start()
threading.Thread(target=run_plane_fetcher, daemon=True).start()
threading.Thread(target=run_satellite_tracker, daemon=True).start()

# --- ENDPOINTS ---
@app.route('/')
def home(): return render_template('index.html')
@app.route('/api/planes')
def get_planes(): return jsonify(live_planes)
@app.route('/api/ships')
def get_ships(): 
    ships = list(live_ships.values())
    return jsonify({"ships": ships})
@app.route('/api/satellites')
def get_satellites(): return jsonify(live_satellites)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
