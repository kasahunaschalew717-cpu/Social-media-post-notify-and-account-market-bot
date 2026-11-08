from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel
from typing import Optional
from core.config import settings
from core.logger import logger
from core.database import async_session_factory
from models.escrow import EscrowTransaction, EscrowStatus
from marketplace.escrow import escrow_state_machine
from telegram import Bot
from sqlalchemy import select

router = APIRouter(prefix="/webhooks/escrow", tags=["Escrow Payment Gateway"])


class PaymentCallbackPayload(BaseModel):
    escrow_reference: str
    tx_hash: str
    amount_usd: float
    currency: str = "USDT"
    status: str  # "CONFIRMED", "PENDING", "FAILED"
    gateway_secret: Optional[str] = None


@router.post("/payment", status_code=status.HTTP_200_OK)
async def process_payment_callback(payload: PaymentCallbackPayload):
    """
    Webhook endpoint invoked by crypto processor or payment gateway
    when buyer's deposit is confirmed on-chain.
    """
    # Authenticate gateway call
    if payload.gateway_secret != settings.SECRET_KEY:
        logger.warning(f"Unauthorized payment callback attempt for {payload.escrow_reference}")
        raise HTTPException(status_code=403, detail="Invalid gateway authorization token.")

    if payload.status != "CONFIRMED":
        logger.info(f"Payment callback for {payload.escrow_reference} with non-confirmed status: {payload.status}")
        return {"status": "ignored", "reason": f"Payment status is {payload.status}"}

    success, message = await escrow_state_machine.confirm_payment(
        escrow_ref=payload.escrow_reference,
        tx_hash=payload.tx_hash,
    )

    if not success:
        logger.error(f"Failed to confirm escrow payment for {payload.escrow_reference}: {message}")
        raise HTTPException(status_code=400, detail=message)

    # Notify buyer and seller via Telegram
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    async with async_session_factory() as session:
        stmt = (
            select(EscrowTransaction)
            .where(EscrowTransaction.escrow_reference == payload.escrow_reference)
        )
        res = await session.execute(stmt)
        escrow = res.scalar_one_or_none()

        if escrow:
            try:
                # Notify Buyer
                await bot.send_message(
                    chat_id=escrow.buyer.telegram_id,
                    text=(
                        f"✅ <b>Payment Confirmed for Deal <code>{escrow.escrow_reference}</code>!</b>\n\n"
                        f"Amount: <b>${payload.amount_usd:.2f} {payload.currency}</b>\n"
                        f"Funds are now locked in platform escrow. The seller has been notified to hand over credentials."
                    ),
                    parse_mode="HTML",
                )
                # Notify Seller
                await bot.send_message(
                    chat_id=escrow.seller.telegram_id,
                    text=(
                        f"💰 <b>Buyer Payment Received for Deal <code>{escrow.escrow_reference}</code>!</b>\n\n"
                        f"Funds (${escrow.seller_receives_usd:.2f}) are held in escrow.\n"
                        f"Please tap <b>/escrow</b> to provide account login credentials via the encrypted vault."
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Error notifying escrow parties via Telegram: {e}")

    return {"status": "success", "message": message}

