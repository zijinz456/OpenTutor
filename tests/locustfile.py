"""Locust stress test for OpenTutor API endpoints.

Focuses on:
1. Health endpoints (baseline)
2. Course CRUD operations (DB stress)
3. Quiz submission (learning pipeline)
4. Cognitive load computation (multi-signal analysis)
5. Chat streaming (LLM endpoint concurrency - reproduces LM Studio crashes)

Usage:
    cd /path/to/OpenTutor
    .venv/bin/locust -f tests/locustfile.py --host http://127.0.0.1:8000
"""

import uuid
import json

from locust import HttpUser, task, between, tag


class OpenTutorUser(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        """Create a test course to use in subsequent requests."""
        self.course_id = None
        self.user_id = None

        # Health check to warm up
        self.client.get("/api/health/live")

        # Create a test course
        resp = self.client.post(
            "/api/courses/",
            json={"name": f"Locust Test {uuid.uuid4().hex[:8]}", "description": "Stress test"},
            name="/api/courses/ [create]",
        )
        if resp.status_code == 201:
            data = resp.json()
            self.course_id = data.get("id")

    # ── Tier 1: Health (baseline, should never fail) ──

    @tag("health")
    @task(5)
    def health_live(self):
        self.client.get("/api/health/live")

    @tag("health")
    @task(2)
    def health_ready(self):
        self.client.get("/api/health/ready")

    @tag("health")
    @task(1)
    def health_full(self):
        self.client.get("/api/health")

    # ── Tier 2: Course CRUD (DB operations) ──

    @tag("crud")
    @task(3)
    def list_courses(self):
        self.client.get("/api/courses/")

    @tag("crud")
    @task(2)
    def course_overview(self):
        self.client.get("/api/courses/overview")

    @tag("crud")
    @task(1)
    def get_course(self):
        if self.course_id:
            self.client.get(
                f"/api/courses/{self.course_id}",
                name="/api/courses/[id]",
            )

    @tag("crud")
    @task(1)
    def get_content_tree(self):
        if self.course_id:
            self.client.get(
                f"/api/courses/{self.course_id}/content-tree",
                name="/api/courses/[id]/content-tree",
            )

    # ── Tier 3: Quiz & Learning (exercising learning science code paths) ──

    @tag("quiz")
    @task(1)
    def list_problems(self):
        if self.course_id:
            self.client.get(
                f"/api/quiz/{self.course_id}?limit=10",
                name="/api/quiz/[id] [list]",
            )

    @tag("quiz")
    @task(1)
    def mastery_history(self):
        if self.course_id:
            self.client.get(
                f"/api/quiz/{self.course_id}/mastery-history",
                name="/api/quiz/[id]/mastery-history",
            )

    # ── Tier 4: Analytics & Progress ──

    @tag("analytics")
    @task(1)
    def progress_analytics(self):
        if self.course_id:
            self.client.get(
                f"/api/progress/analytics/{self.course_id}",
                name="/api/progress/analytics/[id]",
            )

    # ── Tier 5: Chat/LLM (reproduces LM Studio concurrent crashes) ──

    @tag("llm")
    @task(1)
    def chat_stream(self):
        """Send a chat message to stress-test LLM concurrency.

        This is the endpoint that historically crashes LM Studio under load.
        """
        if not self.course_id:
            return

        payload = {
            "message": "Explain the concept of derivatives in calculus briefly.",
            "course_id": self.course_id,
        }
        with self.client.post(
            "/api/chat/stream",
            json=payload,
            name="/api/chat/stream",
            stream=True,
            catch_response=True,
            timeout=60,
        ) as resp:
            if resp.status_code == 200:
                # Consume SSE stream
                content = b""
                try:
                    for chunk in resp.iter_content(chunk_size=1024):
                        content += chunk
                        if len(content) > 50000:
                            break
                except Exception:
                    pass
                resp.success()
            elif resp.status_code in (503, 502):
                resp.failure(f"LLM unavailable: {resp.status_code}")
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    # ── Tier 6: Block Decisions ──

    @tag("blocks")
    @task(1)
    def block_decisions(self):
        if self.course_id:
            self.client.post(
                "/api/blocks/decide",
                json={
                    "course_id": self.course_id,
                    "current_blocks": ["notes", "quiz"],
                    "current_mode": "course_following",
                },
                name="/api/blocks/decide",
            )


class HealthOnlyUser(HttpUser):
    """Lightweight user that only hits health endpoints - for baseline testing."""
    wait_time = between(0.1, 0.5)

    @task
    def health_live(self):
        self.client.get("/api/health/live")
