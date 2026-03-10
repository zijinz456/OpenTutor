"""Quiz endpoints: aggregate sub-routers for generation and submission."""

from fastapi import APIRouter

from routers.quiz_generation import router as generation_router
from routers.quiz_submission import router as submission_router

router = APIRouter()
router.include_router(generation_router)
router.include_router(submission_router)
