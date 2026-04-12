import os
from flask import Flask, jsonify, render_template
import requests
import threading
import websocket
import json
import time
import random
from skyfield.api import Loader, wgs84

app = Flask(__name__)

# Bypasses Hugging Face write-permission errors
load = Loader('/tmp')

live_ships = {}
live_planes = {"states": []} 
live_satellites = {"sats": []}

def generate_ghost_fleet():
    ghosts = []
    for i in range(400): 
        lat = random.uniform(-60.0, 70.0) 
        lon = random.uniform(-180.0, 180.0) 
        ghosts.append([f"GHOST{i}", f"SIM-{i}", "GLOBAL", None, None, lon, lat, 10000, False, 250, 90])
    return ghosts

def run_plane_fetcher():
    url = 'https://opensky-network.org/api/states/all'
    my_opensky_auth = (os.environ.get("OPENSKY_USERNAME", "wallma"), os.environ.get("OPENSKY_PASSWORD", "")) 

    live_planes["states"] = generate_ghost_fleet()

    while True:
        try:
            headers = {'User-Agent': 'Python/GlobalRadarProject'}
            response = requests.get(url, auth=my_opensky_auth, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data and data.get('states'):
                    valid_planes = [p for p in data["states"] if p[5] is not None and p[6] is not None]
                    live_planes["states"] = random.sample(valid_planes, min(200, len(valid_planes)))
            else:
                live_planes["states"] = generate_ghost_fleet()
        except Exception:
            live_planes["states"] = generate_ghost_fleet()
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
                "lon": msg["Longitude"]
            }
            if len(live_ships) > 200:
                live_ships.pop(next(iter(live_ships)))
    except Exception:
        pass 

def run_websocket():
    while True:
        try:
            ws = websocket.WebSocketApp("wss://stream.aisstream.io/v0/stream", 
                on_message=on_message,
                on_open=lambda ws: ws.send(json.dumps({
                    "APIKey": os.environ.get("AISSTREAM_API_KEY", ""), 
                    "BoundingBoxes": [[[24.0, -125.0], [50.0, -66.0]]] 
                })))
            ws.run_forever()
        except Exception:
            pass
        time.sleep(5) 

def run_satellite_tracker():
    stations_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'
    ts = load.timescale()
    try:
        satellites = load.tle_file(stations_url)
        swarm = [sat for sat in satellites if 'STARLINK' in sat.name or 'ISS' in sat.name]
        tracked_sats = random.sample(swarm, min(100, len(swarm)))
    except Exception:
        tracked_sats = []

    while True:
        try:
            t0 = ts.now()
            sat_data = []
            for sat in tracked_sats:
                p0 = wgs84.subpoint(sat.at(t0))
                sat_data.append({"id": sat.name, "lat": p0.latitude.degrees, "lon": p0.longitude.degrees})
            live_satellites["sats"] = sat_data
        except Exception:
            pass
        time.sleep(15) 

threading.Thread(target=run_websocket, daemon=True).start()
threading.Thread(target=run_plane_fetcher, daemon=True).start()
threading.Thread(target=run_satellite_tracker, daemon=True).start()

@app.route('/')
def home(): return render_template('index.html')
@app.route('/api/planes')
def get_planes(): return jsonify(live_planes)
@app.route('/api/ships')
def get_ships(): return jsonify({"ships": list(live_ships.values())})
@app.route('/api/satellites')
def get_satellites(): return jsonify(live_satellites)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
