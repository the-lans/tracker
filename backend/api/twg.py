"""Личное подключение TWG: пользователь работает только со своими доступами."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import TwgConnectionRequest, TwgConnectionResponse
from db.models.users import User
from db.session import get_session
from services import twg

router = APIRouter(prefix="/profile/twg", tags=["profile"])
Db = Annotated[AsyncSession, Depends(get_session)]
Actor = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=TwgConnectionResponse)
async def get_connection(db: Db, user: Actor) -> twg.TwgConnectionStatus:
    return await twg.connection_status(db, user.id)


@router.put("", response_model=TwgConnectionResponse)
async def put_connection(
    body: TwgConnectionRequest, db: Db, user: Actor
) -> twg.TwgConnectionStatus:
    return await twg.save_connection(
        db,
        user_id=user.id,
        site=body.site,
        email=body.email,
        token=body.token.get_secret_value() if body.token is not None else None,
    )


@router.delete("", response_model=TwgConnectionResponse)
async def remove_connection(db: Db, user: Actor) -> twg.TwgConnectionStatus:
    return await twg.delete_connection(db, user.id)
