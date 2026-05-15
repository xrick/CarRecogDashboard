import requests
from requests.auth import HTTPDigestAuth

# =========================
# Device Information
# =========================
DEVICE_IP = "192.168.0.80"
# DEVICE_IP = "192.168.0.108"
USERNAME = "admin"
PASSWORD = "ai123456"

# =========================
# API URL
# =========================
url = f"http://{DEVICE_IP}/cgi-bin/magicBox.cgi?action=getSystemInfo"

try:
    # 發送 GET Request
    response = requests.get(
        url,
        auth=HTTPDigestAuth(USERNAME, PASSWORD),
        timeout=10
    )

    # 檢查 HTTP 狀態碼
    response.raise_for_status()

    print("=== Response Status ===")
    print(response.status_code)

    print("\n=== Response Body ===")
    print(response.text)

except requests.exceptions.RequestException as e:
    print("Request Failed:")
    print(e)