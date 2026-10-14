"""Intents and the risk-tier policy table.

The LLM only *classifies* what the caller wants. The tier comes from this fixed table in code, so a
prompt-injected or confused LLM can never lower the security level of an action.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntentSpec:
    name: str
    tier: int  # 0 = no check, 1 = passive voice check, 2 = hard gate (liveness + fusion + maybe OTP)
    description: str
    required: tuple[str, ...] = ()
    money_moving: bool = False
    account_data: bool = False


INTENTS: dict[str, IntentSpec] = {
    # ---- Tier 0: no customer data
    "greeting": IntentSpec("greeting", 0, "hello / small talk"),
    "faq": IntentSpec("faq", 0, "general bank info: hours, IFSC, rates, how-to, fraud advice"),
    "verify_bank": IntentSpec("verify_bank", 0, "caller asks to verify this is really the bank"),
    "goodbye": IntentSpec("goodbye", 0, "end the call"),
    "confirm_yes": IntentSpec("confirm_yes", 0, "caller says yes / confirms"),
    "confirm_no": IntentSpec("confirm_no", 0, "caller says no / cancels"),
    "provide_info": IntentSpec("provide_info", 0, "caller provides a requested detail (number, amount, code)"),
    "unknown": IntentSpec("unknown", 0, "anything else"),
    # ---- Tier 1: passive voice check (account data or protective, reversible actions)
    "balance": IntentSpec("balance", 1, "account balance", account_data=True),
    "recent_transactions": IntentSpec("recent_transactions", 1, "last few transactions", account_data=True),
    "card_status": IntentSpec("card_status", 1, "status of cards", account_data=True),
    "card_freeze": IntentSpec("card_freeze", 1, "temporarily freeze a card (protective, reversible)"),
    # ---- Tier 2: hard gate
    "card_unfreeze": IntentSpec("card_unfreeze", 2, "unfreeze a frozen card"),
    "card_block": IntentSpec("card_block", 2, "permanently block a card and reissue"),
    "card_limit_change": IntentSpec("card_limit_change", 2, "change daily card limit", required=("new_limit_rupees",)),
    "card_international": IntentSpec("card_international", 2, "enable/disable international usage", required=("international",)),
    "update_mobile": IntentSpec("update_mobile", 2, "change registered mobile number", required=("new_mobile",)),
    "add_payee": IntentSpec("add_payee", 2, "add a beneficiary", required=("payee_name", "payee_account"), money_moving=True),
    "transfer_funds": IntentSpec("transfer_funds", 2, "send money to an existing payee", required=("payee_name", "amount_rupees"), money_moving=True),
}

ACTION_INTENTS = {k for k, v in INTENTS.items() if v.tier >= 1}
PARAM_PROMPTS = {
    "new_limit_rupees": {"en": "the new daily limit in rupees", "hi": "नई दैनिक लिमिट (रुपये में)", "kn": "ಹೊಸ ದೈನಂದಿನ ಮಿತಿ (ರೂಪಾಯಿಯಲ್ಲಿ)"},
    "international": {"en": "whether to turn international use on or off", "hi": "अंतरराष्ट्रीय उपयोग चालू करना है या बंद", "kn": "ಅಂತರರಾಷ್ಟ್ರೀಯ ಬಳಕೆ ಆನ್ ಅಥವಾ ಆಫ್"},
    "new_mobile": {"en": "the new 10-digit mobile number", "hi": "नया 10 अंकों का मोबाइल नंबर", "kn": "ಹೊಸ 10 ಅಂಕಿಯ ಮೊಬೈಲ್ ಸಂಖ್ಯೆ"},
    "payee_name": {"en": "the payee's name", "hi": "पेयी का नाम", "kn": "ಪೇಯಿಯ ಹೆಸರು"},
    "payee_account": {"en": "the payee's account number", "hi": "पेयी का खाता नंबर", "kn": "ಪೇಯಿಯ ಖಾತೆ ಸಂಖ್ಯೆ"},
    "amount_rupees": {"en": "the amount in rupees", "hi": "राशि (रुपये में)", "kn": "ಮೊತ್ತ (ರೂಪಾಯಿಯಲ್ಲಿ)"},
}


def tier_of(intent: str) -> int:
    spec = INTENTS.get(intent)
    return spec.tier if spec else 0


def missing_params(intent: str, params: dict) -> list[str]:
    spec = INTENTS.get(intent)
    if not spec:
        return []
    return [p for p in spec.required if params.get(p) in (None, "", [])]


@dataclass
class Decision:
    outcome: str  # allow | challenge | stepup | refuse
    trust: float
    reasons: list[str] = field(default_factory=list)
    factors: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "trust": round(self.trust, 3), "reasons": self.reasons, "factors": self.factors}
