#!/usr/bin/env python3

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_endpoints():
    print("Testing API endpoints...")

    try:
        # Test stats endpoint
        print("\n1. Testing /api/stats:")
        response = requests.get(f"{BASE_URL}/api/stats", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Data: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"   Error: {response.text}")

        # Test jobs endpoint
        print("\n2. Testing /api/jobs:")
        response = requests.get(f"{BASE_URL}/api/jobs", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Data: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"   Error: {response.text}")

        # Test history endpoint
        print("\n3. Testing /api/history:")
        response = requests.get(f"{BASE_URL}/api/history", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Data: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"   Error: {response.text}")

    except requests.exceptions.ConnectionError as e:
        print(f"Connection error: {e}")
        print("Make sure the Flask app is running on localhost:8000")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    test_endpoints()