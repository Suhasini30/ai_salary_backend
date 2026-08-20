"""
Authenticated end-to-end test (live server on port 8000).

Phase 1 (async, single loop): create two distinct users + one banned user in
Mongo exactly as the Clerk handshake would, insert messages, mint real access
tokens using the SAME JWT secret the running server uses (.env).

Phase 2 (sync urllib): verify over live HTTP —
  1. Each user only lists their own conversations.
  2. A user cannot read/delete another user's conversation (404).
  3. Messages are scoped to the conversation owner.
  4. Refresh endpoint rotates cookie -> new access token.
  5. Banned user -> 403.
  6. Invalid/garbage token -> 401 (no silent guest downgrade).
"""
import asyncio
import http.cookiejar
import json
import sys
import urllib.request
import urllib.error
import uuid

sys.path.insert(0, r"C:\Users\acer\Documents\sales_market_full_implementation\ai_salary_backend")

BACKEND = "http://127.0.0.1:8000"
RESULTS = []


def record(name, passed, detail=""):
    RESULTS.append((name, bool(passed)))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class HttpClient:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.headers = {}

    def request(self, method, url, data=None, timeout=20):
        body = None
        headers = dict(self.headers)
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            resp = self.opener.open(req, timeout=timeout)
            raw = resp.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = raw.decode("utf-8", errors="replace")
            return resp.status, payload
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = raw.decode("utf-8", errors="replace")
            return e.code, payload


def seed(settings, users_repo, messages_repo):
    """Phase 1 — must run inside a single asyncio event loop."""
    from app.core.security import create_access_token

    async def _seed():
        email_a = f"a_{uuid.uuid4().hex[:6]}@test.local"
        email_b = f"b_{uuid.uuid4().hex[:6]}@test.local"
        email_c = f"banned_{uuid.uuid4().hex[:6]}@test.local"

        user_a = await users_repo.upsert_from_clerk({"sub": f"clerk_e2e_a_{uuid.uuid4()}"}, email=email_a)
        user_b = await users_repo.upsert_from_clerk({"sub": f"clerk_e2e_b_{uuid.uuid4()}"}, email=email_b)
        user_c = await users_repo.upsert_from_clerk({"sub": f"clerk_e2e_c_{uuid.uuid4()}"}, email=email_c)

        from app.core.database import users_collection
        from bson import ObjectId
        await users_collection().update_one({"_id": ObjectId(user_c.id)}, {"$set": {"is_banned": True}})

        # Seed two messages directly for the conversation-isolation read check.
        # Create conversation for A via repo so we have its id.
        from app.repos import chats_repo
        conv_a = await chats_repo.create(user_a.id, "User A private chat", "hello from A")
        await messages_repo.insert(user_a.id, conv_a.id, "user", "What is the avg salary in tech?")
        await messages_repo.insert(user_a.id, conv_a.id, "assistant", "Approx $95k per year.")

        token_a = create_access_token(user_a.id)
        token_b = create_access_token(user_b.id)
        token_c = create_access_token(user_c.id)

        return {
            "user_a": user_a, "user_b": user_b, "user_c": user_c,
            "conv_a_id": conv_a.id,
            "token_a": token_a, "token_b": token_b, "token_c": token_c,
            "conversations_repo": chats_repo,
        }

    return asyncio.run(_seed())


def main():
    print("=" * 70)
    print("  AUTHENTICATED PER-USER ISOLATION E2E (live server)")
    print("=" * 70)

    from app.core.config import settings
    from app.repos import users_repo, messages_repo

    # Read the REAL secret the running server uses (do NOT override).
    ctx = seed(settings, users_repo, messages_repo)

    c_a = HttpClient(); c_a.headers["Authorization"] = f"Bearer {ctx['token_a']}"
    c_b = HttpClient(); c_b.headers["Authorization"] = f"Bearer {ctx['token_b']}"
    c_c = HttpClient(); c_c.headers["Authorization"] = f"Bearer {ctx['token_c']}"
    conv_a = ctx["conv_a_id"]

    # 1. Fresh users list only their own conversations.
    s, body = c_a.request("GET", f"{BACKEND}/api/conversations")
    ids_a = [x["id"] for x in body]
    record("1. User A lists own conversation", s == 200 and conv_a in ids_a, f"status={s}")

    s, body = c_b.request("GET", f"{BACKEND}/api/conversations")
    ids_b = [x["id"] for x in body]
    record("2. User B lists 0 conversations", s == 200 and len(ids_b) == 0, f"count={len(ids_b)}")

    # 2. Cross-user isolation.
    record("3. User B cannot see A's conversation", conv_a not in ids_b)

    s, _ = c_b.request("GET", f"{BACKEND}/api/conversations/{conv_a}")
    record("4. Cross-user read blocked (404)", s == 404, f"status={s}")

    s, _ = c_b.request("DELETE", f"{BACKEND}/api/conversations/{conv_a}")
    record("5. Cross-user delete blocked (404)", s == 404, f"status={s}")

    # 3. Owner reads messages (seeded 2).
    s, body = c_a.request("GET", f"{BACKEND}/api/conversations/{conv_a}")
    msgs = body.get("messages", []) if isinstance(body, dict) else []
    record("6. Owner sees 2 messages", s == 200 and len(msgs) == 2, f"count={len(msgs)}")

    # 4. Refresh rotation (cookie).
    from app.core.security import create_refresh_token
    c_r = HttpClient()
    c_r.jar.set_cookie(http.cookiejar.Cookie(
        0, settings.COOKIE_NAME, create_refresh_token(ctx["user_a"].id), None, False,
        "127.0.0.1", False, False, "/", False, False, None, False, None, None, {})
    )
    s, body = c_r.request("POST", f"{BACKEND}/api/auth/refresh")
    record("7. Refresh rotates cookie -> new access token",
           s == 200 and bool(body.get("access_token")) and body.get("access_token") != ctx["token_a"],
           f"status={s}, rotated={'access_token' in body}")

    # 5. Banned user -> 403.
    s, _ = c_c.request("GET", f"{BACKEND}/api/conversations")
    record("8. Banned user blocked (403)", s == 403, f"status={s}")

    # 6. Garbage token -> 401 (no silent guest downgrade).
    c_g = HttpClient(); c_g.headers["Authorization"] = "Bearer garbage.token.here"
    s, _ = c_g.request("GET", f"{BACKEND}/api/conversations")
    record("9. Invalid token -> 401", s == 401, f"status={s}")

    # Cleanup.
    c_a.request("DELETE", f"{BACKEND}/api/conversations/{conv_a}")

    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print(f"\nSUMMARY: {passed}/{total} passed")
    for n, ok in RESULTS:
        if not ok:
            print(f"  FAILED: {n}")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())