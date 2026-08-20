import urllib.request
import urllib.parse
import json
import time

BASE_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://localhost:3000"

def test_endpoint(name, url, method="GET", data=None, headers=None):
    print(f"\n--- [Test Case] {name} ---")
    print(f"Request: {method} {url}")
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data:
        json_bytes = json.dumps(data).encode('utf-8')
        req.add_header("Content-Type", "application/json")
        req.data = json_bytes
    
    try:
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = (time.time() - start_time) * 1000
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            print(f"Response Status: {status} ({elapsed:.1f} ms)")
            print(f"Content-Type: {content_type}")
            
            if "text/event-stream" in content_type:
                print("SSE Stream chunks received:")
                for i in range(10):
                    line = resp.readline().decode('utf-8')
                    if not line:
                        break
                    print(f"  {line.strip()}")
            else:
                body = resp.read().decode('utf-8', errors='replace')
                print(f"Response Body Snippet: {body[:300]}")
            print(f"RESULT: PASSED")
            return True
    except Exception as e:
        print(f"RESULT: FAILED - Error: {e}")
        return False

def main():
    print("==================================================")
    print("     PREVIEW & INTEGRATION TEST SUITE RUNNER      ")
    print("==================================================")

    # 1. Test Frontend Server
    test_endpoint("1. Frontend Server (Next.js)", FRONTEND_URL)

    # 2. Test Backend Root & Health
    test_endpoint("2. Backend Root Endpoint", f"{BASE_URL}/")
    test_endpoint("3. Backend Health Check", f"{BASE_URL}/health")

    # 3. Test Conversations API (Guest user fallback)
    test_endpoint("4. Conversations List API", f"{BASE_URL}/api/conversations")

    # 4. Test Chat Stream SSE
    chat_payload = {
        "message": "What is the average salary of a Sales Development Representative in Tech?",
        "conversation_id": None
    }
    test_endpoint("5. Chat Stream SSE API", f"{BASE_URL}/api/chat", method="POST", data=chat_payload)

if __name__ == "__main__":
    main()
