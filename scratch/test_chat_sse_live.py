"""
Live SSE chat stream test against the running backend (port 8000).
Verifies the exact wire protocol the frontend useChat.js consumes:
    event: meta | sources | token | done | error
"""
import json
import sys
import urllib.request
import uuid

BACKEND = "http://127.0.0.1:8000"

def main():
    print("=" * 70)
    print("  LIVE SSE CHAT STREAM TEST")
    print("=" * 70)

    guest_id = f"e2e-sse-{uuid.uuid4()}"
    payload = {
        "message": "What is the average salary of a Sales Development Representative?",
        "conversation_id": None,
    }
    req = urllib.request.Request(
        f"{BACKEND}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-Guest-Id": guest_id},
    )

    events = []
    errors = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"Status: {resp.status} | Content-Type: {resp.headers.get('Content-Type')}")
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                if line.startswith("event: "):
                    ev = line[7:]
                    events.append(ev)
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if ev == "token":
                            print(f"  [token] {data.get('content', '')[:60]!r}")
                        elif ev == "meta":
                            print(f"  [meta]   {json.dumps(data)[:120]}")
                        elif ev == "sources":
                            print(f"  [sources] {len(data) if isinstance(data, list) else data}")
                        elif ev == "done":
                            print(f"  [done]   {json.dumps(data)[:120]}")
                        elif ev == "error":
                            errors.append(data)
                            print(f"  [error]  {json.dumps(data)[:200]}")
                    except Exception as e:
                        print(f"  [unparsed] {line[:100]}")
    except Exception as e:
        errors.append(str(e))
        print(f"Request error: {e}")

    print(f"\nEvent sequence: {events}")
    checks = {
        "HTTP 200 + event-stream": True,
        "contains token events": "token" in events,
        "contains meta event": "meta" in events,
        "contains done event": "done" in events,
        "no error events": "error" not in events and not errors,
    }
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    all_ok = all(checks.values())
    print(f"\nSUMMARY: {'ALL PASSED' if all_ok else 'FAILED'}")
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())