"""
backend/api/profile.py  —  candidate profile endpoints
"""
from fastapi import APIRouter
from backend.schemas.profile_schemas import ProfileIn, ProfileOut
from backend.services.profile.profile_service import save_profile, load_profile

router = APIRouter()


@router.get("", response_model=ProfileOut)
def get_profile():
    return load_profile()


@router.post("", response_model=ProfileOut)
def upsert_profile(data: ProfileIn):
    return save_profile(data.model_dump())
