"""Catch missing API dependencies before producing a native installer."""
import unittest
import secrets
from unittest.mock import patch
from fastapi import FastAPI

class NativeApiDependencyTests(unittest.TestCase):
 def test_core_api_imports_without_starting_services(self):
  from main import app
  self.assertIsInstance(app,FastAPI)
  self.assertTrue(any(route.path=="/api/health/live" for route in app.routes))
 def test_upstream_jwt_dependency_round_trips_a_synthetic_subject(self):
  from services.auth.jwt import create_access_token,decode_token
  from config import settings
  with patch.object(settings,"jwt_secret_key",secrets.token_hex(32)),patch.object(settings,"jwt_algorithm","HS256"):
   self.assertEqual(decode_token(create_access_token("synthetic-install-check"))["sub"],"synthetic-install-check")
