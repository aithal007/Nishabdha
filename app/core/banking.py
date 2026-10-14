"""Simulated core-banking actions. Only ever called by the agent AFTER the policy gate returned 'allow'
(or after an approved step-up). Every function validates its own inputs - never trust the LLM's params."""
from __future__ import annotations

import re
from datetime import timedelta

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.i18n import format_inr
from app.models import Account, Card, Customer, Payee, Transaction, utcnow


class ActionError(Exception):
    """User-facing problem (wrong card, insufficient funds...). `need` names a missing/ambiguous param."""

    def __init__(self, message: str, need: str | None = None):
        super().__init__(message)
        self.need = need


MAX_CARD_LIMIT_RUPEES = 5_00_000


async def _cards(db: AsyncSession, customer_id: str) -> list[Card]:
    return list((await db.execute(select(Card).where(Card.customer_id == customer_id))).scalars())


async def pick_card(db: AsyncSession, customer_id: str, params: dict, statuses: tuple[str, ...] | None = None) -> Card:
    cards = await _cards(db, customer_id)
    if statuses:
        cards = [c for c in cards if c.status in statuses] or cards
    if params.get("card_last4"):
        cards = [c for c in cards if c.last4 == params["card_last4"]]
        if not cards:
            raise ActionError(f"No card ending {params['card_last4']} on your profile.", need="card_last4")
    if params.get("card_kind"):
        cards = [c for c in cards if c.kind == params["card_kind"]] or cards
    if not cards:
        raise ActionError("You don't have a card that fits that request.")
    if len(cards) > 1:
        endings = " and ".join(f"{c.kind} card ending {c.last4}" for c in cards)
        raise ActionError(f"You have {endings}. Which one?", need="card_last4")
    return cards[0]


async def _primary_account(db: AsyncSession, customer_id: str) -> Account:
    acc = (await db.execute(select(Account).where(Account.customer_id == customer_id).order_by(Account.id).limit(1))).scalar_one_or_none()
    if acc is None:
        raise ActionError("No account found.")
    return acc


async def execute(db: AsyncSession, customer: Customer, intent: str, params: dict, call_transferred_paise: int = 0) -> dict:
    """Returns {"summary": english text, "data": {...}}. Raises ActionError for user-fixable problems."""
    s = get_settings()
    cid = customer.id

    if intent == "balance":
        accs = list((await db.execute(select(Account).where(Account.customer_id == cid))).scalars())
        parts = [f"your {a.kind} account ending {a.number[-4:]} has {format_inr(a.balance_paise)}" for a in accs]
        return {"summary": "; ".join(parts).capitalize() + ".", "data": {"accounts": [{"number_last4": a.number[-4:], "balance_paise": a.balance_paise} for a in accs]}}

    if intent == "recent_transactions":
        acc = await _primary_account(db, cid)
        txns = list((await db.execute(select(Transaction).where(Transaction.account_id == acc.id).order_by(Transaction.created_at.desc()).limit(5))).scalars())
        if not txns:
            return {"summary": "There are no recent transactions.", "data": {"transactions": []}}
        spoken = "; ".join(f"{'debit' if t.amount_paise < 0 else 'credit'} of {format_inr(abs(t.amount_paise))} for {t.description}" for t in txns[:3])
        return {"summary": f"Your last transactions: {spoken}.", "data": {"transactions": [{"amount_paise": t.amount_paise, "description": t.description, "at": t.created_at.isoformat()} for t in txns]}}

    if intent == "card_status":
        cards = await _cards(db, cid)
        return {"summary": " ".join(f"Your {c.kind} card ending {c.last4} is {c.status}." for c in cards), "data": {"cards": [{"last4": c.last4, "kind": c.kind, "status": c.status} for c in cards]}}

    if intent == "card_freeze":
        card = await pick_card(db, cid, params, statuses=("active",))
        if card.status == "blocked":
            raise ActionError(f"Your card ending {card.last4} is already permanently blocked.")
        if card.status == "frozen":
            return {"summary": f"Your card ending {card.last4} is already frozen.", "data": {"card": card.last4, "status": card.status}}
        card.status = "frozen"
        return {"summary": f"Your {card.kind} card ending {card.last4} is now frozen. No one can use it.", "data": {"card": card.last4, "status": "frozen"}}

    if intent == "card_unfreeze":
        card = await pick_card(db, cid, params, statuses=("frozen",))
        if card.status == "blocked":
            raise ActionError(f"Your card ending {card.last4} is permanently blocked and cannot be unfrozen. A replacement is on its way.")
        if card.status == "active":
            return {"summary": f"Your card ending {card.last4} is already active.", "data": {"card": card.last4, "status": "active"}}
        card.status = "active"
        return {"summary": f"Your card ending {card.last4} is active again.", "data": {"card": card.last4, "status": "active"}}

    if intent == "card_block":
        card = await pick_card(db, cid, params, statuses=("active", "frozen"))
        if card.status == "blocked":
            return {"summary": f"Your card ending {card.last4} is already blocked.", "data": {"card": card.last4, "status": "blocked"}}
        card.status = "blocked"
        return {"summary": f"Your card ending {card.last4} is permanently blocked and a replacement will reach your registered address in 5 to 7 days.", "data": {"card": card.last4, "status": "blocked", "reissue": True}}

    if intent == "card_limit_change":
        try:
            new = int(params.get("new_limit_rupees"))
        except (TypeError, ValueError):
            raise ActionError("What should the new daily limit be?", need="new_limit_rupees")
        if not 0 < new <= MAX_CARD_LIMIT_RUPEES:
            raise ActionError(f"The limit must be between Rs 1 and {format_inr(MAX_CARD_LIMIT_RUPEES * 100)}.", need="new_limit_rupees")
        card = await pick_card(db, cid, params, statuses=("active", "frozen"))
        old = card.daily_limit_paise
        card.daily_limit_paise = new * 100
        return {"summary": f"Daily limit on card ending {card.last4} changed from {format_inr(old)} to {format_inr(new * 100)}.", "data": {"card": card.last4, "old_paise": old, "new_paise": new * 100}}

    if intent == "card_international":
        val = params.get("international")
        if not isinstance(val, bool):
            raise ActionError("Should international use be turned on or off?", need="international")
        card = await pick_card(db, cid, params, statuses=("active", "frozen"))
        card.international_enabled = val
        return {"summary": f"International use is now {'enabled' if val else 'disabled'} on card ending {card.last4}.", "data": {"card": card.last4, "international": val}}

    if intent == "update_mobile":
        new = re.sub(r"\D", "", str(params.get("new_mobile") or ""))[-10:]
        if not re.fullmatch(r"[6-9]\d{9}", new):
            raise ActionError("Please say a valid 10-digit mobile number.", need="new_mobile")
        if new == customer.phone[-10:]:
            raise ActionError("That is already your registered number.")
        clash = (await db.execute(select(Customer).where(Customer.phone == new, Customer.id != cid))).scalar_one_or_none()
        if clash:
            raise ActionError("That number cannot be used. Please visit a branch.")
        old = customer.phone
        customer.phone = new
        return {"summary": f"Your registered mobile number is updated to one ending {new[-4:]}. A confirmation was sent to your old number ending {old[-4:]}.", "data": {"old_last4": old[-4:], "new_last4": new[-4:]}}

    if intent == "add_payee":
        name = str(params.get("payee_name") or "").strip()
        acct = re.sub(r"\D", "", str(params.get("payee_account") or ""))
        if not name:
            raise ActionError("What is the payee's name?", need="payee_name")
        if not 9 <= len(acct) <= 18:
            raise ActionError("Please say the payee's account number.", need="payee_account")
        active_from = utcnow() + timedelta(hours=s.payee_cooling_hours)
        p = Payee(customer_id=cid, name=name[:120], account_number=acct, ifsc=str(params.get("payee_ifsc") or "")[:11], active_from=active_from)
        db.add(p)
        return {"summary": f"{name} is added as a payee. For your safety, transfers to a new payee are allowed after {s.payee_cooling_hours} hours.", "data": {"payee": name, "account_last4": acct[-4:], "active_from": active_from.isoformat()}}

    if intent == "transfer_funds":
        name = str(params.get("payee_name") or "").strip()
        try:
            amount = int(params.get("amount_rupees"))
        except (TypeError, ValueError):
            raise ActionError("How much would you like to send?", need="amount_rupees")
        if amount <= 0:
            raise ActionError("The amount must be more than zero.", need="amount_rupees")
        payees = list((await db.execute(select(Payee).where(Payee.customer_id == cid))).scalars())
        if not payees:
            raise ActionError("You have no saved payees. Please add one first.")
        if not name:
            raise ActionError("Who should I send it to?", need="payee_name")
        match = process.extractOne(name, {p.id: p.name for p in payees}, scorer=fuzz.WRatio)
        if not match or match[1] < 80:
            raise ActionError(f"I couldn't find a payee called {name}.", need="payee_name")
        payee = next(p for p in payees if p.id == match[2])
        if payee.active_from > utcnow():
            mins = int((payee.active_from - utcnow()).total_seconds() // 60)
            raise ActionError(f"{payee.name} was added recently. Transfers open in about {mins // 60} hours {mins % 60} minutes - this cooling period protects you from scams.")
        if call_transferred_paise + amount * 100 > s.max_transfer_paise:
            left = max(0, s.max_transfer_paise - call_transferred_paise)
            raise ActionError(f"Phone banking transfers are limited to {format_inr(s.max_transfer_paise)} per call; {format_inr(left)} remains. Please use net banking for larger amounts.")
        acc = await _primary_account(db, cid)
        if acc.balance_paise < amount * 100:
            raise ActionError("There isn't enough balance for that transfer.")
        acc.balance_paise -= amount * 100
        db.add(Transaction(account_id=acc.id, amount_paise=-amount * 100, description=f"Transfer to {payee.name}"))
        return {"summary": f"Sent {format_inr(amount * 100)} to {payee.name}. Your new balance is {format_inr(acc.balance_paise)}.", "data": {"payee": payee.name, "amount_paise": amount * 100, "balance_paise": acc.balance_paise}}

    raise ActionError("I can't do that over the phone.")
