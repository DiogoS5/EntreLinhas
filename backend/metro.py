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

def load_from_firebase():
    """Load existing hourly averages from Firebase"""
    try:
        import firebase_admin
        from firebase_admin import credentials, db
        
        # Initialize Firebase if not already initialized
        if not firebase_admin._apps:
            cred = credentials.Certificate("firebase-credentials.json")
            firebase_admin.initialize_app(cred, {
                'databaseURL': secret.FIREBASE_URL
            })
        
        ref = db.reference('/hourly_averages')
        existing_data = ref.get()
        
        if existing_data:
            # Convert loaded averages into hourly_data structure
            for station_name, destinations in existing_data.items():
                for destination_name, hours in destinations.items():
                    for hour, avg in hours.items():
                        # Start with loaded average and count=0 (will be updated with new data)
                        hourly_data[station_name][destination_name][int(hour)] = {"avg": avg, "count": 0}
            print("Loaded existing averages from Firebase")
    except Exception as e:
        print(f"Could not load from Firebase: {e}")

def get_waiting_time_data(station_id):
    try:
        url = f"https://api.metrolisboa.pt:8243/estadoServicoML/1.0.1/tempoEspera/Estacao/{station_id}"
        headers = {
            "accept": "application/json", 
            "Authorization": f"Bearer {secret.METRO_API_KEY}"
        }
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        return response.json()
    except requests.exceptions.Timeout:
        print(f"Timeout getting data for station {station_id}")
        return None
    except Exception as e:
        print(f"Error getting waiting time data for station {station_id}: {e}")
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

# Gets lines for a station/destination (parses string format "[Line1, Line2]")
def get_lines(station_name):
    with open("infoEstacao.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        for item in data["resposta"]:
            if item["stop_name"] == station_name:
                linha_str = item["linha"]
                # Parse string like "[Azul]" or "[Verde, Vermelha]"
                if linha_str.startswith("[") and linha_str.endswith("]"):
                    linha_str = linha_str[1:-1]  # Remove brackets
                    lines = [line.strip() for line in linha_str.split(",")]
                    return lines
                return [linha_str]  # Return as list if not in bracket format
    return []

def collect_wait_times():
    """Collect current wait times and update hourly averages"""
    current_hour = datetime.now().hour
    current_data = {}
    
    with open("infoEstacao.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        # Loop through stations
        for station in data["resposta"]:
            station_id = station["stop_id"]
            station_name = get_station_name(station_id)
            if station_name not in current_data:
                current_data[station_name] = {}
            
            station_lines = get_lines(station_name)
            if not station_lines or len(station_lines) == 0:
                print(f"Warning: No lines found for station {station_name}")
            else:     
                for line in station_lines:
                    if line not in current_data[station_name]:
                        current_data[station_name][line] = {}
                    
            destinations = get_waiting_time_data(station_id)
            if not destinations or destinations.get("codigo") == "404":
                current_data[station_name] = {"NA": "NA"}
                continue

            # Loop through destinations
            for destination in destinations["resposta"]:
                destination_id = destination["destino"]
                destination_name = get_destination_name(destination_id)
                
                if not destination_name:
                    continue
                
                destination_lines = get_lines(destination_name)
                
                if not destination_lines or len(destination_lines) == 0:
                    print(f"Warning: No lines found for destination {destination_name}")
                    continue
                
                # Get all available wait times (include "--" as string, convert numbers to int)
                wait_times = []
                for i in range(3):
                    time_value = destination[f"tempoChegada{i+1}"]
                    if time_value == "--":
                        wait_times.append("--")
                    else:
                        wait_times.append(int(time_value))
                
                if wait_times:
                    for destination_line in destination_lines:
                        if destination_line in current_data[station_name]: #finds which line to put the destination in
                            # Store all current wait times with the correct line
                            current_data[station_name][destination_line][destination_name] = wait_times
                    
                    # Update hourly average incrementally using first valid wait time
                    first_valid_time = next((t for t in wait_times if isinstance(t, int) and t > 0), None)
                    if first_valid_time:
                        update_hourly_average(station_name, destination_name, current_hour, first_valid_time)
    
    return current_data

def update_hourly_average(station_name, destination_name, hour, wait_time):
    """Update hourly average incrementally for a station-destination-hour combination"""
    hour_data = hourly_data[station_name][destination_name][hour]
    
    # If count is 0, this means we loaded it from Firebase or it's new
    # Start fresh calculation for this session
    if hour_data["count"] == 0 and hour_data["avg"] > 0:
        # Has loaded data, replace with new calculation
        hourly_data[station_name][destination_name][hour] = {"avg": float(wait_time), "count": 1}
    else:
        # Continue incremental averaging
        old_avg = hour_data["avg"]
        old_count = hour_data["count"]
        new_count = old_count + 1
        new_avg = (old_avg * old_count + wait_time) / new_count
        hourly_data[station_name][destination_name][hour] = {"avg": new_avg, "count": new_count}

def get_hourly_averages():
    """Retrieve formatted hourly average wait times"""
    averages = {}
    for station_name, destinations in hourly_data.items():
        averages[station_name] = {}
        for destination_name, hours in destinations.items():
            averages[station_name][destination_name] = {}
            for hour, data in hours.items():
                if data["count"] > 0:
                    # Convert hour to string for Firebase compatibility
                    averages[station_name][destination_name][str(hour)] = data["avg"]
    return averages

def sanitize_key(key):
    """Sanitize key for Firebase (remove spaces and special chars)"""
    if not key:
        return "unknown"
    key = str(key)
    sanitized = key.replace(" ", "_").replace(".", "").replace("$", "").replace("#", "").replace("[", "").replace("]", "").replace("/", "")
    return sanitized if sanitized else "unknown"

def sanitize_data_for_firebase(data):
    """Recursively sanitize all keys in nested dict for Firebase"""
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            sanitized_key = sanitize_key(str(key))
            sanitized[sanitized_key] = sanitize_data_for_firebase(value)
        return sanitized
    elif isinstance(data, list):
        # Sanitize list items (but keep lists as lists)
        return [sanitize_data_for_firebase(item) for item in data]
    else:
        # For primitive values, return as-is (but ensure no None values that could cause issues)
        return data if data is not None else ""

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
        
        # Sanitize data for Firebase
        sanitized_current = sanitize_data_for_firebase(current_data)
        sanitized_averages = sanitize_data_for_firebase(averages)
        
        # Update Firebase
        ref = db.reference('/')
        ref.child('timestamp').set(datetime.now().isoformat())
        ref.child('current_wait_times').set(sanitized_current)
        ref.child('hourly_averages').set(sanitized_averages)
        
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
    
    # Load existing data from Firebase if enabled
    if args.firebase:
        load_from_firebase()
    
    print(f"Starting Metro Monitor (update every {args.period}s)")
    print(f"Firebase: {'Enabled' if args.firebase else 'Disabled'}")
    print(f"Local storage: {'Enabled' if args.local else 'Disabled'}")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            start_time = time.time()
            
            print(f"Collecting data at {datetime.now().strftime('%H:%M:%S')}...")
            current_data = collect_wait_times()
            averages = get_hourly_averages()
            
            if args.local:
                save_local(current_data, averages)
            
            if args.firebase:
                send_to_firebase(current_data, averages)
            
            # Sleep for remaining time to maintain consistent period
            elapsed = time.time() - start_time
            sleep_time = max(0, args.period - elapsed)
            print(f"Collection took {elapsed:.1f}s, sleeping {sleep_time:.1f}s")
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif elapsed > args.period:
                print(f"Warning: Data collection took {elapsed:.1f}s, longer than period {args.period}s")
    except KeyboardInterrupt:
        print("\nStopped by user")

if __name__ == "__main__":
    main()
