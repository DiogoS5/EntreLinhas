import requests
import urllib3
import json
import argparse
import time
from datetime import datetime
from collections import defaultdict

import secret

# Suppress SSL warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Storage for hourly averages: {station_name: {destination_name: {hour: {"avg": float, "count": int}}}}
hourly_data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"avg": 0.0, "count": 0})))

def get_waiting_time_data(station_id):
    try:
        url = f"https://api.metrolisboa.pt:8243/estadoServicoML/1.0.1/tempoEspera/Estacao/{station_id}"
        headers = {
            "accept": "application/json", 
            "Authorization": f"Bearer {secret.METRO_API_KEY}"
        }
        response = requests.get(url, headers=headers, verify=False)
        return response.json()
    except Exception as e:
        print(f"Error getting waiting time data: {e}")
        return None

def get_station_name(station_id):
    with open("infoEstacao.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        for item in data["resposta"]:
            if item["stop_id"] == station_id:
                return item["stop_name"]
    return None

def get_destination_name(destination_id):
    with open("infoDestinos.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        for item in data["resposta"]:
            if item["id_destino"] == destination_id:
                return item["nome_destino"]
    return None

def collect_wait_times():
    """Collect current wait times and update hourly averages"""
    current_hour = datetime.now().hour
    current_data = {}
    
    with open("infoEstacao.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        for item in data["resposta"]:
            station_id = item["stop_id"]
            station_name = get_station_name(station_id)
            
            times = get_waiting_time_data(station_id)
            if not times or "resposta" not in times:
                continue
            
            if station_name not in current_data:
                current_data[station_name] = {}
            
            for time in times["resposta"]:
                destination_id = time["destino"]
                destination_name = get_destination_name(destination_id)
                
                # Get all available wait times
                wait_times = []
                for i in range(3):
                    if time[f"tempoChegada{i+1}"] != "--":
                        wait_times.append(int(time[f"tempoChegada{i+1}"]))
                
                if wait_times:
                    # Store all current wait times
                    current_data[station_name][destination_name] = wait_times
                    
                    # Update hourly average incrementally using first wait time
                    first_wait_time = wait_times[0]
                    hour_data = hourly_data[station_name][destination_name][current_hour]
                    old_avg = hour_data["avg"]
                    old_count = hour_data["count"]
                    new_count = old_count + 1
                    new_avg = (old_avg * old_count + first_wait_time) / new_count
                    hourly_data[station_name][destination_name][current_hour] = {"avg": new_avg, "count": new_count}
    
    return current_data

def calculate_averages():
    """Get current average wait times per hour"""
    averages = {}
    for station_name, destinations in hourly_data.items():
        averages[station_name] = {}
        for destination_name, hours in destinations.items():
            averages[station_name][destination_name] = {}
            for hour, data in hours.items():
                if data["count"] > 0:
                    averages[station_name][destination_name][hour] = data["avg"]
    return averages

def sanitize_key(key):
    """Sanitize key for Firebase (remove spaces and special chars)"""
    # Replace spaces with underscores and remove problematic characters
    return key.replace(" ", "_").replace(".", "").replace("$", "").replace("#", "").replace("[", "").replace("]", "").replace("/", "")

def sanitize_data_for_firebase(data):
    """Recursively sanitize all keys in nested dict for Firebase"""
    if not isinstance(data, dict):
        return data
    
    sanitized = {}
    for key, value in data.items():
        sanitized_key = sanitize_key(str(key))
        if isinstance(value, dict):
            sanitized[sanitized_key] = sanitize_data_for_firebase(value)
        else:
            sanitized[sanitized_key] = value
    return sanitized

def save_local(current_data, averages):
    """Save data to local JSON file"""
    # Sanitize data for consistency with Firebase
    sanitized_current = sanitize_data_for_firebase(current_data)
    sanitized_averages = sanitize_data_for_firebase(averages)
    
    data = {
        "timestamp": datetime.now().isoformat(),
        "current_wait_times": sanitized_current,
        "hourly_averages": sanitized_averages
    }
    with open("metro_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Data saved locally at {datetime.now().strftime('%H:%M:%S')}")

def send_to_firebase(current_data, averages):
    """Send data to Firebase Realtime Database"""
    try:
        import firebase_admin
        from firebase_admin import credentials, db
        
        # Initialize Firebase if not already initialized
        if not firebase_admin._apps:
            cred = credentials.Certificate("firebase-credentials.json")
            firebase_admin.initialize_app(cred, {
                'databaseURL': secret.FIREBASE_URL
            })
        
        # Sanitize data for Firebase (keys can't have spaces or special chars)
        sanitized_current = sanitize_data_for_firebase(current_data)
        sanitized_averages = sanitize_data_for_firebase(averages)
        
        # Update Firebase
        ref = db.reference('/')
        ref.update({
            "timestamp": datetime.now().isoformat(),
            "current_wait_times": sanitized_current,
            "hourly_averages": sanitized_averages
        })
        print(f"Data sent to Firebase at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"Error sending to Firebase: {e}")

def main():
    parser = argparse.ArgumentParser(description='Metro Lisbon Wait Times Monitor')
    parser.add_argument('--firebase', action='store_true', help='Send data to Firebase')
    parser.add_argument('--local', action='store_true', help='Save data locally')
    parser.add_argument('--period', type=int, default=60, help='Update period in seconds (default: 60)')
    
    args = parser.parse_args()
    
    if not args.firebase and not args.local:
        print("Please specify --firebase and/or --local flag")
        return
    
    print(f"Starting Metro Monitor (update every {args.period}s)")
    print(f"Firebase: {'Enabled' if args.firebase else 'Disabled'}")
    print(f"Local storage: {'Enabled' if args.local else 'Disabled'}")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            start_time = time.time()
            
            current_data = collect_wait_times()
            averages = calculate_averages()
            
            if args.local:
                save_local(current_data, averages)
            
            if args.firebase:
                send_to_firebase(current_data, averages)
            
            # Sleep for remaining time to maintain consistent period
            elapsed = time.time() - start_time
            sleep_time = max(0, args.period - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif elapsed > args.period:
                print(f"Warning: Data collection took {elapsed:.1f}s, longer than period {args.period}s")
    except KeyboardInterrupt:
        print("\nStopped by user")

if __name__ == "__main__":
    main()
