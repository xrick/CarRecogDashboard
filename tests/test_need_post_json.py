import requests
from requests.auth import HTTPDigestAuth

DEVICE_IP = "192.168.1.108"
USERNAME = "admin"
PASSWORD = "your_password"

url = f"http://{DEVICE_IP}/cgi-bin/configManager.cgi?action=setConfig"

payload = {
    "name": "Network",
    "Enable": True
}

try:
    response = requests.post(
        url,
        json=payload,
        auth=HTTPDigestAuth(USERNAME, PASSWORD),
        timeout=10
    )

    print("Status:", response.status_code)
    print(response.text)

except Exception as e:
    print(e)