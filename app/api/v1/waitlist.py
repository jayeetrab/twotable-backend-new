from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app.db.session import get_db
from app.models.waitlist import WaitlistSubscriber
from app.schemas.waitlist import WaitlistCreate, WaitlistRead

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post("", response_model=WaitlistRead, status_code=status.HTTP_201_CREATED)
async def join_waitlist(payload: WaitlistCreate, db: AsyncSession = Depends(get_db)):
    subscriber = WaitlistSubscriber(email=payload.email, source=payload.source)
    db.add(subscriber)
    try:
        await db.commit()
        await db.refresh(subscriber)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already on the waitlist.",
        )
    return subscriber
