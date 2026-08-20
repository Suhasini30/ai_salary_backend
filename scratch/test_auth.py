import sys
import os
import unittest
import time
import base64
from unittest.mock import patch, MagicMock, AsyncMock
from bson import ObjectId

# Ensure backend directory is in path
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import Response

# Import FastAPI app and settings
from app.main import app
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    clear_refresh_cookie,
    set_refresh_cookie
)

# Mock cryptography keys for testing Clerk handshake
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Generate RSA key pair for testing
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()

class MockMongoCollection:
    def __init__(self, data=None):
        self.data = data if data is not None else []

    async def find_one(self, filter, projection=None):
        for doc in self.data:
            match = True
            for k, v in filter.items():
                # Convert ObjectId to string for comparison if needed
                doc_val = doc.get(k)
                if k == "_id":
                    if isinstance(v, ObjectId):
                        if ObjectId(doc.get("_id")) != v:
                            match = False
                            break
                    else:
                        if str(doc.get("_id")) != str(v):
                            match = False
                            break
                elif k == "user_id":
                    if isinstance(v, ObjectId):
                        if ObjectId(doc.get("user_id")) != v:
                            match = False
                            break
                    else:
                        if str(doc.get("user_id")) != str(v):
                            match = False
                            break
                else:
                    if doc_val != v:
                        match = False
                        break
            if match:
                if projection:
                    # Projection is dict e.g. {"email": 1}
                    return {k: v for k, v in doc.items() if k in projection or k == "_id"}
                return doc
        return None

    async def insert_one(self, document):
        if "_id" not in document:
            document["_id"] = ObjectId()
        self.data.append(document)
        class InsertResult:
            inserted_id = document["_id"]
        return InsertResult()

    async def update_one(self, filter, update, upsert=False):
        doc = await self.find_one(filter)
        if doc:
            if "$set" in update:
                doc.update(update["$set"])
        class UpdateResult:
            modified_count = 1
        return UpdateResult()


class TestAuthFlow(unittest.TestCase):
    def setUp(self):
        # Setup clean in-memory mock collections
        self.users_data = []
        self.profiles_data = []
        self.mock_users_col = MockMongoCollection(self.users_data)
        self.mock_profiles_col = MockMongoCollection(self.profiles_data)

        # Patch the collection names as they are bound INSIDE the repos
        # (`from app.core.database import users_collection`), not the source
        # module attribute, otherwise the patch never takes effect.
        self.users_patcher = patch(
            "app.repos.users_repo.users_collection", return_value=self.mock_users_col
        )
        self.profiles_patcher = patch(
            "app.repos.profiles_repo._p", return_value=self.mock_profiles_col
        )
        self.profiles_users_patcher = patch(
            "app.repos.profiles_repo.users_collection", return_value=self.mock_users_col
        )

        self.users_patcher.start()
        self.profiles_patcher.start()
        self.profiles_users_patcher.start()

        # Patch Jwks loading to return our public key
        self.jwks_patcher = patch("app.core.security._load_jwks", return_value={"mock-kid": PUBLIC_KEY})
        self.jwks_patcher.start()

        # Update settings for tests
        settings.CLERK_ISSUER = "mock-clerk-issuer"
        settings.JWT_SECRET_KEY = "test-secret-key-test-secret-key-test-secret-key-test-secret"
        settings.JWT_ALGORITHM = "HS256"

        self.client = TestClient(app)

    def tearDown(self):
        self.users_patcher.stop()
        self.profiles_patcher.stop()
        self.profiles_users_patcher.stop()
        self.jwks_patcher.stop()

    def generate_clerk_token(self, sub="user_clerk_123", email="test@example.com", username="testuser"):
        import jwt
        payload = {
            "sub": sub,
            "email": email,
            "username": username,
            "email_verified": True,
            "iss": "mock-clerk-issuer",
            "exp": int(time.time()) + 300,
        }
        return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": "mock-kid"})

    def test_token_creation_and_decoding(self):
        """Test creating and decoding our own JWT tokens."""
        access_token = create_access_token("user_123")
        claims = decode_token(access_token, expected_type="access")
        self.assertEqual(claims["sub"], "user_123")
        self.assertEqual(claims["type"], "access")

        refresh_token = create_refresh_token("user_123")
        claims_refresh = decode_token(refresh_token, expected_type="refresh")
        self.assertEqual(claims_refresh["sub"], "user_123")
        self.assertEqual(claims_refresh["type"], "refresh")

    def test_delete_cookie_not_raising_type_error(self):
        """Test that clear_refresh_cookie does not raise a TypeError."""
        res = Response()
        try:
            clear_refresh_cookie(res)
            cookies = res.headers.getlist("set-cookie")
            self.assertTrue(any("Max-Age=0" in c for c in cookies))
        except TypeError as e:
            self.fail(f"clear_refresh_cookie raised TypeError: {e}")

    def test_api_verify_handshake(self):
        """Test POST /api/auth/verify creates user, profile, and returns tokens."""
        clerk_token = self.generate_clerk_token()

        response = self.client.post("/api/auth/verify", json={"clerk_token": clerk_token})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify access token exists in response
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["clerk_id"], "user_clerk_123")

        # Verify refresh token cookie is set
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("rag_refresh_token=" in c for c in cookies))

        # Verify user and profile records are upserted in mock collections
        self.assertEqual(len(self.users_data), 1)
        self.assertEqual(len(self.profiles_data), 1)
        self.assertEqual(self.users_data[0]["clerk_id"], "user_clerk_123")
        self.assertEqual(str(self.profiles_data[0]["user_id"]), str(self.users_data[0]["_id"]))

    def test_api_login_endpoint(self):
        """Test POST /api/auth/login (canonical path) creates user, profile, and returns tokens."""
        clerk_token = self.generate_clerk_token()

        response = self.client.post("/api/auth/login", json={"clerk_token": clerk_token})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["clerk_id"], "user_clerk_123")

        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("rag_refresh_token=" in c for c in cookies))
        self.assertEqual(len(self.users_data), 1)
        self.assertEqual(len(self.profiles_data), 1)

    def test_api_me_endpoint(self):
        """Test GET /api/auth/me returns current user and profile details."""
        # Pre-seed user and profile
        user_id = ObjectId()
        user_doc = {
            "_id": user_id,
            "clerk_id": "user_clerk_123",
            "email": "test@example.com",
            "username": "testuser",
            "is_verified": True,
            "is_banned": False,
        }
        profile_doc = {
            "user_id": user_id,
            "username": "testuser",
            "full_name": "Test User",
            "skills": ["Python", "FastAPI"],
        }
        self.users_data.append(user_doc)
        self.profiles_data.append(profile_doc)

        # Generate access token
        access_token = create_access_token(str(user_id))

        # Call /me endpoint with authorization header
        response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["user"]["clerk_id"], "user_clerk_123")
        self.assertEqual(data["profile"]["full_name"], "Test User")
        self.assertEqual(data["profile"]["skills"], ["Python", "FastAPI"])

    def test_api_refresh_endpoint(self):
        """Test POST /api/auth/refresh rotates the refresh token and returns a new access token."""
        user_id = ObjectId()
        user_doc = {
            "_id": user_id,
            "clerk_id": "user_clerk_123",
            "email": "test@example.com",
            "username": "testuser",
            "is_verified": True,
            "is_banned": False,
        }
        self.users_data.append(user_doc)

        # Generate refresh token
        refresh_token = create_refresh_token(str(user_id))

        # Call /refresh with the cookie
        # set cookie manually on client
        self.client.cookies.set("rag_refresh_token", refresh_token)
        response = self.client.post("/api/auth/refresh")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)

        # Verify a new refresh token cookie was set
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("rag_refresh_token=" in c for c in cookies))

    def test_api_logout_endpoint(self):
        """Test POST /api/auth/logout clears the refresh cookie."""
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "logged_out"})

        # Check cookie deletion header exists
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("Max-Age=0" in c or "expires=Thu, 01 Jan 1970 00:00:00 GMT" in c for c in cookies))

if __name__ == "__main__":
    unittest.main()