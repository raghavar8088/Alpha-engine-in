"""Index Option Buying > NIFTY BANK: the paper desk running the ten strategies the 2026-10
BANKNIFTY research chose, and that research itself (app.services.banknifty_desk)."""

from fastapi import APIRouter

from app.services import banknifty_desk

router = APIRouter(prefix="/api/banknifty-desk", tags=["banknifty-desk"])


@router.get("/summary")
async def get_summary() -> dict:
    """The ten strategies (research record + forward paper record), open positions with live
    marks, recent trades, the engine's state and the research summary."""
    return await banknifty_desk.summary()


@router.get("/research")
async def get_research() -> dict:
    """Every strategy the research tested, chosen or not, with its tier and both periods."""
    return banknifty_desk.research_table()
