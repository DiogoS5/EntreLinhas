import requests
import secret
import urllib3
import json

# Suppress SSL warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://api.metrolisboa.pt:8243/estadoServicoML/1.0.1/infoDestinos/todos"    
NAME = "infoDestinos.json"

headers = {
    "accept": "application/json", 
    "Authorization": f"Bearer {secret.METRO_API_KEY}"
}
response = requests.get(URL, headers=headers, verify=False)

with open(NAME, "w") as f:
    json.dump(response.json(), f)