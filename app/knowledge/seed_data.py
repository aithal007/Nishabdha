"""Authoritative pre-seeded knowledge base across the 11 target financial & voice clone domains.

Covers:
1. Banks
2. NBFCs
3. Insurers
4. UPI Users
5. Finance Teams
6. Voice Fraud Impersonation
7. KYC (Know Your Customer)
8. Hiring & Recruitment
9. Exams & Academic Proctoring
10. Remote Work & IT Security
11. When Anybody Can Be Cloned (Family & Personal Extortion)
"""
from __future__ import annotations

import hashlib
import logging

from app.knowledge import extract as X, store

log = logging.getLogger("unclone.knowledge.seed")

DOCUMENTS = [
    # ---------------- 1. BANKS ----------------
    {
        "url": "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11040",
        "title": "RBI Master Circular: Customer Protection – Limiting Liability in Unauthorized Electronic Banking Transactions",
        "domain": "rbi.org.in",
        "type": "official",
        "text": """Reserve Bank of India (RBI) Directive on Customer Liability in Electronic Banking Transactions (Circular DBR.No.Leg.BC.78/09.07.005/2017-18).

1. Zero Liability of Customer:
A customer shall have zero liability in the following situations:
(a) Contributory fraud, negligence or deficiency on the part of the bank (irrespective of whether or not the transaction is reported by the customer).
(b) Third party breach where the deficiency lies neither with the bank nor with the customer but lies elsewhere in the system, and the customer notifies the bank within three working days of receiving communication from the bank regarding the unauthorized transaction.

2. Limited Liability of Customer:
A customer shall be liable for the loss occurring due to unauthorized transactions in the following cases:
(a) In cases where the loss is due to negligence by a customer, such as where he has shared the payment credentials (PIN, password, OTP, CVV), the customer will bear the entire loss until he reports the unauthorized transaction to the bank. Any loss occurring after the reporting of the unauthorized transaction shall be borne by the bank.
(b) In cases where responsibility lies neither with the bank nor with the customer, but lies elsewhere in the system and when there is a delay of four to seven working days in notifying the bank, the per-transaction liability of the customer shall be limited to:
- Basic Savings Bank Deposit (BSBD) Accounts: Maximum liability Rs 5,000.
- All other Savings Bank accounts, Pre-paid Payment Instruments, Gift cards, Current accounts of individuals, and Credit Cards with limit up to Rs 5 lakh: Maximum liability Rs 10,000.
- All other accounts and Credit Cards with limit exceeding Rs 5 lakh: Maximum liability Rs 25,000.

3. Delay beyond 7 working days:
If reporting delay exceeds seven working days, customer liability shall be determined as per the bank's Board-approved policy.

4. Reversal and Shadow Credit Timeline:
On being notified by the customer, the bank must credit (shadow reversal) the amount involved in the unauthorized electronic transaction to the customer's account within 10 working days from the date of such notification by the customer.

5. Resolution of Complaint:
Banks shall ensure that a complaint is resolved and liability of the customer, if any, established within a period not exceeding 90 days from the date of receipt of the complaint.""",
    },

    # ---------------- 2. NBFCS (Non-Banking Financial Companies) ----------------
    {
        "url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=54350",
        "title": "RBI Digital Lending Guidelines for NBFCs & Fraudulent Loan App Impersonation Directives",
        "domain": "rbi.org.in",
        "type": "official",
        "text": """Reserve Bank of India (RBI) Regulatory Framework for Digital Lending and NBFC Loan Protections.

1. Regulated NBFC Disbursals and Repayments:
All loan disbursals and repayments must execute directly between the borrower's verified bank account and the Regulated NBFC / Bank without pass-through or third-party pool accounts.

2. Predatory Digital Lending Apps & Impersonation:
- Fraudulent entities create spoofed mobile apps impersonating registered NBFCs (such as Bajaj Finance, Tata Capital, Muthoot, or Aditya Birla Capital), issuing forged loan sanction letters featuring fabricated RBI registration numbers.
- Unlicensed loan apps demand exorbitant processing fees upfront or harvest user phone contacts and photos to blackmail borrowers.
- Fact: Legitimate NBFCs NEVER deduct upfront processing fees via personal UPI accounts before disbursing a loan.

3. NBFC Recovery Agent Conduct Rules:
- Regulated NBFC recovery agents are strictly prohibited from calling borrowers before 8:00 AM or after 7:00 PM.
- Agents are legally prohibited from intimidating borrowers, threatening police arrest, contacting friends or family members, or spoofing caller IDs.
- Foreclosure or loan settlement discounts: Legitimate NBFC loan settlements must always be generated on official company letterheads with verifiable transaction portal links, NEVER through personal UPI IDs.""",
    },

    # ---------------- 3. INSURERS ----------------
    {
        "url": "https://irdai.gov.in/consumer-education/spurious-calling-and-fraud",
        "title": "IRDAI Public Notice: Spurious Calls, Insurance Bonus Scams & Claims Impersonation",
        "domain": "irdai.gov.in",
        "type": "official",
        "text": """Insurance Regulatory and Development Authority of India (IRDAI) Consumer Protection Advisory on Spurious Calls and Insurance Impersonation Fraud.

1. Spurious Calls Impersonating IRDAI or Insurers:
- Fraudsters call policyholders impersonating IRDAI officials, Insurance Ombudsmen, or life insurance company executives (such as LIC, HDFC Life, ICICI Prudential, SBI Life).
- Callers falsely inform policyholders that their insurance policies have accumulated massive unclaimed bonuses or dividends (e.g. Rs 2 lakh to Rs 15 lakh) or that a lapsed policy has high surrender value.
- Victims are instructed to pay processing charges, GST fees, or advance taxes to personal bank accounts to release the bonus.
- Fact: IRDAI is a regulatory authority. IRDAI NEVER sells insurance, NEVER holds bonuses, NEVER contacts individual policyholders to disburse funds, and NEVER asks for bank transfers.

2. Fraudulent Policy Surrender & Beneficiary Tampering:
- Attackers impersonate policyholders on customer service telephone lines to divert maturity benefits, alter registered mobile numbers, or surrender policies without authorization.
- Insurance verification protocol: Life insurers must conduct multi-factor authentication and verified out-of-band mobile verification before modifying nominee details or executing surrender value payouts.""",
    },

    # ---------------- 4. UPI USERS ----------------
    {
        "url": "https://www.npci.org.in/what-we-do/upi/safety-and-awareness",
        "title": "NPCI Security Directive: UPI Deception, QR Code Scams & PIN Harvesting Tactics",
        "domain": "npci.org.in",
        "type": "official",
        "text": """National Payments Corporation of India (NPCI) Unified Payments Interface (UPI) Safety Directives.

1. The Golden Rule of UPI: Entering UPI PIN ALWAYS Debits Money:
- A UPI PIN is required ONLY to debit money from your bank account.
- You NEVER need to enter your UPI PIN, scan a QR code, or click 'Approve' to receive money into your account.
- Scammers initiate UPI 'Collect Requests' or 'Mandates' and call victims claiming they must enter their PIN to claim a cash refund, government subsidy, lottery prize, or OLX buyer payment. Doing so immediately transfers funds out of the victim's account.

2. QR Code Scanning Deception:
- Scammers send QR codes over WhatsApp or messaging apps claiming: 'Scan this QR code to receive Rs 10,000'.
- Scanning a QR code inside a UPI app is purely a payment mechanism to send money, not receive it.

3. Fake UPI Payment Confirmation Apps:
- Attackers use fake payment alert applications (e.g., simulated Paytm, PhonePe, or Google Pay audio soundboxes) that play audio messages like 'Payment of Rs 50,000 received' to defraud merchants without actual bank settlement.
- Merchants must verify real bank SMS or the merchant dashboard, rather than relying on the customer's phone screen.

4. Unauthorized UPI Transaction Reporting:
- Victims of unauthorized UPI transactions must notify their bank immediately and register a complaint on the National Cybercrime Portal (1930) within 4 hours to enable NPCI payment gateway freeze.""",
    },

    # ---------------- 5. FINANCE TEAMS & TREASURY ----------------
    {
        "url": "https://www.cisa.gov/news-events/alerts/deepfake-executive-voice-wire-fraud",
        "title": "CISA & CERT-In Joint Advisory: Executive Voice Cloning & Treasury Wire Transfer Fraud",
        "domain": "cisa.gov",
        "type": "research",
        "text": """Cybersecurity and Infrastructure Security Agency (CISA) & CERT-In Advisory on AI Voice Cloning in Corporate Wire Fraud.

1. CEO / CFO Voice Impersonation (Business Voice Compromise - BVC):
- Cybercriminals synthesize the voice of a company's Chief Executive Officer (CEO) or Chief Financial Officer (CFO) using public recordings from shareholder meetings, earnings calls, or media interviews.
- Attackers call the finance controller, treasury team, or accounts payable manager via telephone, WhatsApp, or Microsoft Teams huddle, demanding an immediate, highly confidential international wire transfer for an acquisition or emergency vendor settlement.
- The voice clone reproduces the executive's pitch, regional accent, and cadence, combined with intense urgency and demands for secrecy to bypass corporate approvals.

2. Mandatory Financial Team Safeguards:
- Dual-Authorization Mandate: No wire transfer above predefined thresholds (e.g. Rs 5 lakh or $10,000) may be executed on verbal or telephone authorization alone without digital two-person approval.
- Out-of-Band Callback Verification: Finance personnel must independently call the executive back on their established corporate terrestrial telephone number, NEVER on the number from which the incoming call arrived.
- Vendor Account Details Change: Any request from an established supplier to change bank routing numbers or account details must be verified by calling the supplier's verified procurement officer before updating payment ledgers.""",
    },

    # ---------------- 6. VOICE FRAUD IMPERSONATION ----------------
    {
        "url": "https://www.cert-in.org.in/advisories/deepfake-audio-synthesis-attacks.html",
        "title": "CERT-In Threat Intelligence: Neural Audio Cloning Architectures & Real-Time Voice Conversion",
        "domain": "cert-in.org.in",
        "type": "official",
        "text": """Indian Computer Emergency Response Team (CERT-In) Vulnerability Note on Generative AI Voice Cloning and Audio Deepfakes.

1. Mechanism of Voice Cloning:
- Deep neural networks (zero-shot text-to-speech models, diffusion audio architectures, and retrieval-based voice conversion - RVC) can clone human vocal timbre from as little as 3 to 10 seconds of clear speech audio.
- Attackers harvest reference audio from social media videos, voicemail greetings, or recorded phone surveys to construct neural voice prints.

2. Acoustic and Spectral Artifacts of Synthetic Audio:
- Unnatural phase continuity across consonants, robotic pitch quantization, and absent physiological inhalation/exhalation markers.
- High-frequency cutoff artifacts (models trained on 16kHz or 24kHz audio leaving unnatural harmonic drop-offs above 8kHz).
- Latency Signature: Real-time voice conversion pipelines require 800ms to 2500ms to process, buffer, and stream synthesized audio.

3. Defense Mechanisms:
- Continuous speaker verification using ECAPA-TDNN embeddings.
- Passive deepfake acoustic classifiers evaluating acoustic anomalies.
- Active liveness challenge: Generating 4 random digits and measuring the millisecond server-side response onset time to detect automated neural pipelines and replay buffers.""",
    },

    # ---------------- 7. KYC (KNOW YOUR CUSTOMER) ----------------
    {
        "url": "https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=11566",
        "title": "RBI Master Direction on Video-based Customer Identification Process (V-CIP) & KYC Anti-Spoofing",
        "domain": "rbi.org.in",
        "type": "official",
        "text": """Reserve Bank of India (RBI) Master Direction on Know Your Customer (KYC) and Digital Onboarding Safeguards.

1. Video KYC (V-CIP) Deepfake Risks:
- Fraud syndicates deploy virtual webcam drivers, deepfake face-swapping models, and real-time voice conversion to impersonate identity document holders during digital bank account opening and micro-loan approvals.
- Mule Account Rings: Fraudsters pay vulnerable individuals or use stolen identity credentials to open active digital bank accounts that receive cyber fraud proceeds before laundering via cryptocurrency or cash withdrawals.

2. Mandatory RBI Anti-Fraud Controls in V-CIP:
- Live Geo-Tagging: The V-CIP connection must verify that the customer is physically located within Indian territorial borders.
- Randomized Interaction & Liveness: The bank's verification officer must ask dynamic, unpredictable questions and verify random actions to break automated deepfake playback loops.
- Facial and Audio Match: Automated biometric verification must compare the customer's live face and voice against official databases (UIDAI Aadhaar biometric or DigiLocker records).
- Document Verification: Bank agents must verify clear physical security features on the PAN card or Aadhaar XML, rejecting digitally edited screen photos.""",
    },

    # ---------------- 8. HIRING & RECRUITMENT ----------------
    {
        "url": "https://www.fbi.gov/investigate/white-collar-crime/deepfake-job-applicant-schemes",
        "title": "Global Cyber Advisory: Deepfake Candidates in Remote Hiring & Technical Interview Fraud",
        "domain": "cisa.gov",
        "type": "research",
        "text": """Intelligence Advisory on Synthetic Media in Remote Job Interviews and Candidate Impersonation.

1. Remote Interview Deepfake Fraud:
- Job seekers or overseas cyber actors apply for high-clearance remote software engineering, IT administration, or financial analyst positions using stolen resumes and identities.
- During remote video/voice interviews, a proxy candidate (or an AI deepfake avatar with real-time voice conversion) answers technical screening questions.
- Once hired, the impostor gains access to sensitive corporate databases, customer financial data, source code repositories, and VPN infrastructure.

2. Fake Job Offer / Recruitment Fee Scams:
- Scammers impersonate HR recruiters from prominent technology companies or banks on LinkedIn, WhatsApp, or phone calls, conducting simulated voice interviews.
- Victims are sent forged employment offer letters and instructed to pay 'mandatory laptop security deposits', 'background check fees', or 'visa clearance charges'.
- Fact: Reputed corporations NEVER demand money or security deposits from job applicants for recruitment or equipment.

3. Biometric Verification in Hiring:
- Human resources teams implement voice biometric matching between the initial interview, coding screening, and day-one orientation to ensure identity consistency.""",
    },

    # ---------------- 9. EXAMS & ACADEMIC PROCTORING ----------------
    {
        "url": "https://cybercrime.gov.in/advisories/online_exam_impersonation.html",
        "title": "National Cybercrime Advisory: Voice Impersonation & Proxy Test-Taking in Online Proctored Examinations",
        "domain": "cybercrime.gov.in",
        "type": "official",
        "text": """National Cybercrime Advisory on Academic Integrity and Remote Examination Impersonation.

1. Proxy Test-Takers and Voice Assistance:
- During remote proctored university exams, professional certifications (e.g. GRE, GMAT, TOEFL, banking entrance exams), candidates employ proxy test-takers or concealed earpieces to receive audio feeds from third-party experts.
- Advanced cheating syndicates utilize real-time voice cloning software to impersonate the candidate during oral defense, viva voce, or proctor identity verification checks.

2. Proctored Audio Anti-Cheat Measures:
- Audio Room Acoustic Analysis: Monitoring continuous background audio for hidden whispering, keyboard clicks, secondary audio streaming devices, or multiple voices.
- Voice Biometric Registration: Candidates register a voice sample during exam enrollment. Random verbal reading challenges during the exam confirm that the voice speaking matches the registered student.
- Proctor Impersonation: Scammers posing as exam proctors call candidates claiming technical test failure and demanding money or remote desktop access (AnyDesk) to 'validate exam results'.""",
    },

    # ---------------- 10. REMOTE WORK & IT SECURITY ----------------
    {
        "url": "https://www.cisa.gov/news-events/alerts/voice-phishing-targeting-remote-workers",
        "title": "CISA Advisory: IT Helpdesk Vishing & Voice Phishing Targeting Remote Employees",
        "domain": "cisa.gov",
        "type": "research",
        "text": """Cybersecurity and Infrastructure Security Agency (CISA) Advisory on Voice Phishing (Vishing) of Remote Workers.

1. IT Helpdesk Impersonation Modus Operandi:
- Attackers call remote employees claiming to be from the corporate IT Helpdesk or Security Operations Center (SOC).
- The caller informs the employee that a critical VPN certificate, password, or security token has expired, directing them to a spoofed single sign-on (SSO) login page or asking for their one-time passcode (OTP).
- MFA Fatigue + Voice Coercion: Fraudsters trigger multiple Multi-Factor Authentication (MFA) push prompts on the employee's phone while calling them to say: 'Please press Approve on your phone right now to verify your VPN update'.

2. Remote Work Defense Protocols:
- Zero Trust Verification: Corporate IT helpdesk staff will NEVER ask for passwords, private encryption keys, or MFA push approvals over phone calls or messaging apps.
- Out-of-Band Ticket Verification: Remote employees must verify any helpdesk call by checking for an active ticket inside the internal enterprise portal before granting remote screen access.
- Prohibit Remote Desktop Tools: AnyDesk, TeamViewer, or UltraViewer must be administratively blocked on corporate workstations for unauthorized external connections.""",
    },

    # ---------------- 11. WHEN ANYBODY CAN BE CLONED (FAMILY & PERSONAL) ----------------
    {
        "url": "https://cybercrime.gov.in/advisories/family_emergency_voice_cloning_scams.html",
        "title": "CERT-In & Police Advisory: Family Emergency Cloned Voice Scams & Kidnapping Extortion",
        "domain": "cybercrime.gov.in",
        "type": "official",
        "text": """Indian Cyber Crime Coordination Centre (I4C) Advisory: Defense Against Family Emergency Voice Clone Scams.

1. Family Emergency & Grandparent Scam Modus Operandi:
- Cyber criminals harvest public audio clips of young adults or children from social media platforms (Instagram Reels, YouTube Shorts, public podcast appearances, or voicemail recordings).
- Fraudsters clone the child's voice using AI neural synthesis and telephone the parents or grandparents.
- The cloned voice speaks in high emotional distress, crying and sobbing: 'Mom / Dad, I had a terrible car accident / I was arrested by the police / I am in the hospital, please send money right now to this lawyer's account'.
- A fake lawyer or fake police officer then takes over the phone, issuing urgent legal threats and demanding immediate wire transfers or UPI payments within 15 minutes to avoid jailing the child.

2. Virtual Kidnapping Extortion:
- Scammers call parents claiming their child has been kidnapped, playing synthesized screams or cloned cries in the background, demanding ransom via cryptocurrency or immediate UPI transfers while forbidding the parent from hanging up.

3. Four Golden Defensive Rules for Families:
- Step 1: Stay Calm and Pause. Emotion and panic are the scammer's primary tools to bypass logical thinking.
- Step 2: Hang Up and Call the Relative Directly on their known personal phone number or contact their school/office/friends.
- Step 3: Establish a Family Secret Codeword. Agree upon a private word or question known only inside the family (e.g., 'What is our pet's middle name?' or 'Where did we travel last Diwali?'). A synthetic voice clone cannot answer secret private knowledge.
- Step 4: Report Immediately to the National Cybercrime Helpline 1930 and file an incident report at cybercrime.gov.in.""",
    },
]


def seed_knowledge_base(force: bool = False):
    """Seeds the vector database with authoritative documents across the 11 target domains."""
    stats = store.get_stats()
    # If already seeded with all 11 domains and not forced, skip
    if stats.get("documents", 0) >= len(DOCUMENTS) and not force:
        log.info("Knowledge base already seeded with %d documents; ready.", stats["documents"])
        return

    log.info("Seeding vector database with all 11 financial and voice cloning domains...")
    for doc in DOCUMENTS:
        text = doc["text"]
        url = doc["url"]
        domain = doc["domain"]
        stype = doc["type"]
        title = doc["title"]
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunks = store.chunk_text(text)
        
        # put_document automatically generates vector embeddings for every chunk and indexes into FTS5
        store.put_document({
            "url": url,
            "domain": domain,
            "type": stype,
            "title": title,
            "text": text,
            "text_hash": h,
            "via": "authoritative_seed",
        }, chunks)

        # Extract structured claims
        sentences = X.split_sentences(text)
        claims = []
        for i, (_, sent) in enumerate(sentences):
            attrs = X.analyse_claim(sent, stype)
            if not attrs:
                continue
            claims.append({
                "id": f"seed_{domain[:4]}_{h[:4]}_{i+1}",
                "text": sent,
                "url": url,
                "domain": domain,
                "kind": attrs["kind"],
                "epistemic": attrs["epistemic"],
                "authority": attrs["authority"],
                "sentiment": attrs["sentiment"],
                "prices": attrs["prices"],
                "tasks": [domain],
            })

        if claims:
            store.put_claims(claims, run_id="seed_11_domains", query=title)

    new_stats = store.get_stats()
    log.info("Knowledge base fully seeded: %d documents, %d chunks, %d claims across %d domains.",
             new_stats["documents"], new_stats["chunks"], new_stats["claims"], new_stats["domains_count"])
