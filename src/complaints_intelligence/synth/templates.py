"""Text templates for synthetic complaints and resolution notes.

Complaint text is composed rather than sampled from a corpus, for two reasons.
It keeps the fixtures readable — a reviewer can open the Parquet and follow
what the pipeline is doing — and it makes the semantic content controllable,
so a planted theme is genuinely coherent in embedding space rather than
coherent only by label.

Each channel has a distinct register, because the register differences are
real and they drive design decisions downstream: sentiment is compared within
channel, never pooled across it, precisely because a branch note and a call
transcript do not sound alike.
"""

from __future__ import annotations

from dataclasses import dataclass

from complaints_intelligence.domain.complaint import Channel, Outcome

# --------------------------------------------------------------------------
# Per-category subject matter. The first clause is the grievance, the second
# the concrete detail, the third the impact.
# --------------------------------------------------------------------------
CATEGORY_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "payments_failed": {
        "grievance": (
            "a payment I set up did not leave my account",
            "my transfer failed without any explanation",
            "a standing order was not paid on the due date",
            "the same payment was taken from my account twice",
        ),
        "detail": (
            "the money showed as sent but never arrived with the payee",
            "I received an error code and no further information",
            "the payment sat as pending for four days before failing",
            "I tried three times and each attempt was rejected",
        ),
        "impact": (
            "my rent was late and the landlord has charged me",
            "I was left unable to pay a supplier on time",
            "I incurred a late fee that I should not have to pay",
            "I had to borrow money to cover the shortfall",
        ),
    },
    "card_fraud_handling": {
        "grievance": (
            "I reported fraudulent transactions and nothing has been done",
            "my fraud claim was rejected without investigation",
            "I have had no update on my disputed transactions",
        ),
        "detail": (
            "there were six transactions I did not authorise",
            "I was told the case was closed but never informed of the outcome",
            "the refund was reversed weeks after it was credited",
        ),
        "impact": (
            "I am still out of pocket for money I never spent",
            "I have lost confidence that my account is secure",
            "I have spent hours chasing this with no progress",
        ),
    },
    "card_declines": {
        "grievance": (
            "my card was declined despite having funds available",
            "my card stopped working with no warning",
        ),
        "detail": (
            "there was no block showing and no message was sent to me",
            "it worked at one shop and failed at the next",
        ),
        "impact": (
            "I was embarrassed at the till and had to leave the shopping",
            "I could not pay for fuel and was stranded",
        ),
    },
    "mortgage_arrears_support": {
        "grievance": (
            "I asked for help with my mortgage arrears and was refused",
            "no one has discussed forbearance options with me",
            "I explained my circumstances and was offered nothing",
        ),
        "detail": (
            "I told the adviser I had lost my job and was told to pay in full",
            "I asked about a payment holiday and the request was never logged",
            "I was passed between four different departments",
        ),
        "impact": (
            "I am now facing possession proceedings that could have been avoided",
            "the stress of this has affected my health",
            "the arrears have grown while I waited for a response",
        ),
    },
    "overdraft_fees": {
        "grievance": (
            "I was charged overdraft fees I was never told about",
            "the charges applied are far more than I expected",
            "fees were applied while my account was in credit",
        ),
        "detail": (
            "no notification was sent before the account went overdrawn",
            "the charge appeared three days after the transaction",
            "I was quoted one rate and charged another",
        ),
        "impact": (
            "the charges pushed me further overdrawn and compounded",
            "I could not afford food that week because of the fees",
        ),
    },
    "app_login": {
        "grievance": (
            "I cannot log into the app at all",
            "the app will not accept my passcode",
            "I have been locked out since updating the app",
        ),
        "detail": (
            "it says my device is not recognised every single time",
            "the verification code never arrives",
            "it crashes on the login screen and closes itself",
        ),
        "impact": (
            "I have no way to check my balance or make payments",
            "I had to visit a branch because I could not use the app",
        ),
    },
    "branch_closure": {
        "grievance": (
            "my local branch has closed with very little notice",
            "the branch hours have been cut and I cannot get there",
        ),
        "detail": (
            "the nearest alternative is an hour away by bus",
            "the notice was posted in the window and nowhere else",
        ),
        "impact": (
            "I do not use the internet and now have no way to bank",
            "I care for my husband and cannot travel that far",
        ),
    },
    "complaint_handling_delay": {
        "grievance": (
            "I complained months ago and have heard nothing since",
            "my complaint was acknowledged and then ignored",
        ),
        "detail": (
            "I was promised a response within eight weeks and it is now sixteen",
            "each time I call I am told it has been escalated",
        ),
        "impact": (
            "I have had to go to the ombudsman to get any response",
            "the original problem is still unresolved",
        ),
    },
    "savings_rate_change": {
        "grievance": (
            "my savings rate was cut without proper notice",
            "the rate change was not communicated to me at all",
        ),
        "detail": (
            "I found out only when I checked my statement",
            "the letter arrived after the change had already taken effect",
        ),
        "impact": (
            "I would have moved my money had I been told in time",
            "I have lost interest I was relying on",
        ),
    },
    "direct_debit_errors": {
        "grievance": (
            "a direct debit was cancelled without my instruction",
            "a direct debit I cancelled was taken anyway",
        ),
        "detail": (
            "I have the cancellation confirmation and it was still collected",
            "the mandate was set up against the wrong account",
        ),
        "impact": (
            "my insurance lapsed because the payment did not go out",
            "the account went overdrawn as a result",
        ),
    },
    "vulnerable_customer_support": {
        "grievance": (
            "I told you about my circumstances and nothing was adjusted",
            "the support I was promised was never put in place",
            "I asked for large print communications and still receive standard letters",
        ),
        "detail": (
            "I disclosed my diagnosis and was asked to repeat it four times",
            "the note about my hearing loss was clearly never read",
            "I was told a vulnerability marker was added but nothing changed",
        ),
        "impact": (
            "I felt dismissed and have avoided contacting you since",
            "I could not follow what was being asked of me",
            "this has made a very difficult period considerably worse",
        ),
    },
    "statement_errors": {
        "grievance": (
            "my statement shows a balance that is not correct",
            "I have not received statements for several months",
        ),
        "detail": (
            "two transactions appear that I do not recognise as mine",
            "the closing balance does not match the transactions listed",
        ),
        "impact": (
            "I cannot reconcile my accounts for my tax return",
            "I have no record to give my accountant",
        ),
    },
}

# --------------------------------------------------------------------------
# Candidate-theme text. These sit in the residual pool and match no category.
# --------------------------------------------------------------------------
THEME_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "CT-007": {
        "grievance": (
            "the round-up feature has taken the same transfer twice",
            "my round-ups are being double counted into the savings pot",
            "round up savings has moved more money than my purchases justify",
        ),
        "detail": (
            "I spent £3.40 and it rounded up twice, taking £1.20 not 60p",
            "the savings pot shows two identical round-up entries for one purchase",
            "it has done this on every contactless payment since the update",
        ),
        "impact": (
            "my current account is being drained faster than I budgeted for",
            "I had to turn the feature off entirely to stop it",
            "I went overdrawn because more was swept than I expected",
        ),
    },
    # CT-012 is the ingest artefact: one CRM template, duplicated. Its text is
    # deliberately near-identical across members, which is exactly the signal
    # that should give it away.
    "CT-012": {
        "grievance": ("customer unable to book branch appointment via system",),
        "detail": ("appointment booking system returned no availability",),
        "impact": ("customer advised to call back; no further action taken",),
    },
    "CT-019": {
        "grievance": (
            "I am generally unhappy with the service I have received",
            "the whole experience has been poor from start to finish",
            "nobody seems to take any responsibility",
        ),
        "detail": (
            "it is one thing after another with this bank",
            "I have been a customer for thirty years and it has got worse",
            "every interaction takes far longer than it should",
        ),
        "impact": (
            "I am considering moving my accounts elsewhere",
            "I would not recommend you to anyone",
            "it has all been extremely frustrating",
        ),
    },
}

# --------------------------------------------------------------------------
# Channel register. Each channel wraps the same three clauses differently.
# --------------------------------------------------------------------------
CHANNEL_OPENERS: dict[Channel, tuple[str, ...]] = {
    Channel.FOS_REFERRAL: (
        "The complainant submits that",
        "This referral concerns a complaint that",
        "The customer's position is that",
    ),
    Channel.MOBILE_APP: (
        "Hi,",
        "hello",
        "",
    ),
    Channel.BRANCH: (
        "Customer attended branch to report that",
        "Note taken in branch:",
        "Customer raised at counter that",
    ),
    Channel.CALL_CENTRE: (
        "[Agent] Thanks for holding. [Customer] Yeah so,",
        "[Customer] Right, um,",
        "[Agent] How can I help today? [Customer] Well,",
    ),
}

CHANNEL_CLOSERS: dict[Channel, tuple[str, ...]] = {
    Channel.FOS_REFERRAL: (
        "The complainant seeks redress and a written explanation.",
        "The firm's final response is disputed in full.",
        "The complainant requests that the matter be reviewed independently.",
    ),
    Channel.MOBILE_APP: (
        "Please sort this out.",
        "Can someone actually help pls",
        "I want this fixed and compensation.",
        "",
    ),
    Channel.BRANCH: (
        "Customer requests callback. Advised complaint logged.",
        "Escalated to complaints team. Customer given reference.",
        "Customer left dissatisfied.",
    ),
    Channel.CALL_CENTRE: (
        "[Customer] So what are you going to do about it? [inaudible]",
        "[Customer] I just want it sorted, honestly. [Agent] Understood.",
        "[Customer] ...and that's, that's the whole thing really. [inaudible]",
    ),
}


def channel_register(channel: Channel, text: str) -> str:
    """Apply channel-specific surface characteristics to composed text.

    The app channel is terse and typo-prone; call centre text carries
    disfluencies. Applied deterministically from the text itself rather than
    at random, so the same input always yields the same output.
    """
    match channel:
        case Channel.MOBILE_APP:
            # Lowercase and lightly degraded, as short-form input tends to be.
            return text.replace(" and ", " n ").replace("cannot", "cant")
        case Channel.CALL_CENTRE:
            return text.replace(", ", ", um, ", 1)
        case _:
            return text


# --------------------------------------------------------------------------
# Resolution notes. The sole knowledge source for remediation, so the action
# vocabulary is per-category and concrete.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolutionAction:
    """One recorded action, tagged with the outcome its prose describes.

    The tag exists because the prose is not neutral: it already says whether
    the complaint was upheld and whether money changed hands. Drawing an
    outcome beside it rather than reading it off produces notes that
    contradict their own structured fields — a note stamped ``not_upheld``
    with ``redress_gbp=0`` whose text describes refunding the customer. The
    remediation prompt asks the model to weigh exactly that, so the fixture
    has to be coherent for the judgement to mean anything.
    """

    outcome: Outcome
    #: Whether the prose describes money changing hands. Carried separately
    #: from ``outcome`` because it does not follow from it: a complaint can be
    #: upheld and remedied without redress, and several of these are.
    pays_redress: bool
    text: str


#: One action per (category, outcome), so the outcome can be sampled at its
#: intended rate and the prose chosen to match. Every category therefore has a
#: rejected precedent available, which is what makes "we looked and it did not
#: transfer" a reportable outcome rather than a gap.
RESOLUTION_ACTIONS: dict[str, tuple[ResolutionAction, ...]] = {
    "payments_failed": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Payment traced and re-presented manually. Failure attributed to a "
            "timeout in the payments gateway during the release window. Customer "
            "refunded the late fee on production of evidence and a goodwill "
            "payment made. Gateway timeout raised with the payments engineering "
            "team.",
        ),
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Confirmed the duplicate debit and reversed the second collection same "
            "day. Root cause was a retry that did not check for an existing "
            "reference. Fix deployed; affected customers identified by query and "
            "proactively refunded.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "The payment itself was correctly rejected, but the customer was not "
            "told for two working days and the failure notice went to a dormant "
            "inbox. Notification routing corrected and the charge arising from "
            "the delay refunded. The underlying rejection stands.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Investigation found the payment was correctly rejected because the "
            "payee details did not match the beneficiary record. The error "
            "message was unclear and has been rewritten; the customer was given "
            "a written explanation and shown how to verify payee details before "
            "submitting.",
        ),
    ),
    "card_fraud_handling": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Provisional credit reinstated within 24 hours of review. The original "
            "decision had been taken without reviewing the device evidence. Case "
            "handler retrained and the review checklist updated to require device "
            "data before rejection.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "Disputed transactions refunded in full and card reissued. Delay was "
            "caused by the case sitting unallocated in a queue; queue monitoring "
            "alert added at the five-day mark. The initial decision to investigate "
            "rather than refund immediately was correct on the evidence held.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Device and location evidence placed the disputed transactions with "
            "the registered handset, and the card was not reported lost. The "
            "dispute decision stands. Customer given the evidence relied on and "
            "referred to the ombudsman route.",
        ),
    ),
    "card_declines": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Block was applied by fraud rules and no notification was sent due to "
            "an out-of-date mobile number. Number updated and customer advised how "
            "to maintain contact details. Goodwill payment made for the "
            "inconvenience.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            False,
            "The block itself was correctly applied under the travel rules, but "
            "the customer had notified us of the trip and the note was not "
            "attached to the card record. Note-linking corrected and the block "
            "lifted on the call. No charge arose.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Declines were caused by insufficient available balance on the dates "
            "in question, not by any block applied by the firm. Statement extract "
            "provided and the available-balance display explained.",
        ),
    ),
    "mortgage_arrears_support": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Arrangement to pay agreed over 24 months and arrears fees refunded "
            "from the date support was first requested. The initial request had "
            "not been logged as a forbearance enquiry; call handling guidance "
            "updated and the file marked for vulnerability support.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "Referred to the specialist support team who agreed a payment "
            "concession. Possession action suspended. Compensation paid for "
            "distress caused by the delay in assessing affordability, though the "
            "affordability assessment itself was carried out correctly.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Forbearance was offered at each contact and declined; the arrears "
            "position and the fees applied were both correct under the mortgage "
            "conditions. Support options set out again in writing and the file "
            "left open for the customer to take them up.",
        ),
    ),
    "overdraft_fees": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Charges refunded in full for the period where no pre-notification was "
            "sent. Notification failure traced to a suppressed alerting flag on the "
            "account. Flag cleared and a query run to identify other affected "
            "accounts.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "Pre-notification was sent for two of the four charges. The two "
            "unnotified charges were refunded; the remainder stand. Alerting "
            "coverage gap raised with the servicing team.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Fees were correctly applied and clearly disclosed, and each was "
            "pre-notified to the registered contact details. Customer offered a "
            "review of account options better suited to their usage.",
        ),
    ),
    "app_login": (
        ResolutionAction(
            Outcome.UPHELD,
            False,
            "Device registration record was corrupted and was cleared, restoring "
            "access. Underlying defect fixed in the following release. Customer "
            "given a direct contact while the issue persisted.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "Verification messages were failing to a ported number. Routed via an "
            "alternative provider and delivery confirmed. Goodwill payment made "
            "for the period without access; the security step that caused it was "
            "operating as designed.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Access was blocked by repeated incorrect passcode entry, which is the "
            "documented behaviour. Identity re-verified in branch and access "
            "restored the same day. Passcode reset guidance sent.",
        ),
    ),
    "branch_closure": (
        ResolutionAction(
            Outcome.UPHELD,
            False,
            "Closure notice was not issued to this customer at all owing to a gap "
            "in the mailing extract. Personal apology issued, a home visit "
            "arranged to set up telephone banking, and the extract logic corrected "
            "before the next closure programme.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            False,
            "Closure confirmed as proceeding; decision not reversed. Customer "
            "referred to the local Post Office banking service and a home visit "
            "arranged to set up telephone banking. Communication of the closure "
            "found to be inadequate and the notice process revised.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "Closure decision follows a documented review of branch usage and is "
            "not reversible on individual request. Statutory notice was given in "
            "branch and by post within the required period. Alternative access "
            "arrangements set out in writing.",
        ),
    ),
    "complaint_handling_delay": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Original complaint reopened and concluded within ten days. Delay "
            "caused by the case being closed in error at first assessment. "
            "Compensation paid for the delay and for the distress caused. "
            "Case-closure controls tightened to require a recorded outcome.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "The case did exceed the eight-week deadline, but the substantive "
            "decision was correct and is unchanged. Payment made for the delay "
            "alone. Holding-letter automation extended to cover cases awaiting "
            "third-party evidence.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "The complaint was acknowledged and concluded within the required "
            "period, with two updates issued in between. Correspondence log "
            "provided to the customer along with the ombudsman referral rights.",
        ),
    ),
    "savings_rate_change": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Notice was issued but to a superseded address. Interest difference "
            "refunded for the notice period and address records corrected. Address "
            "propagation defect raised with the servicing team.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "Notice was given within the required period but the wording did not "
            "make the size of the reduction clear. Interest difference paid for "
            "one month as a gesture and the notice template rewritten; the rate "
            "change itself stands.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "The rate change was made under the variation terms and notice was "
            "given in writing 60 days beforehand to the address held. Copy of the "
            "notice supplied and the alternative products explained.",
        ),
    ),
    "direct_debit_errors": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Mandate reinstated and the lapsed policy restored with the insurer at "
            "the firm's cost. Cancellation was actioned against the wrong mandate "
            "reference. Confirmation step added before any cancellation is applied.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            False,
            "The mandate was cancelled on the customer's own instruction, but the "
            "instruction was ambiguous and should have been queried before it was "
            "actioned. Mandate reinstated at no cost and the call-handling script "
            "amended to require read-back. No loss arose.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "The collection was presented by the originator on the date agreed in "
            "the mandate, and the firm applied it correctly. Customer referred to "
            "the originator to vary the schedule, and the indemnity route "
            "explained.",
        ),
    ),
    "vulnerable_customer_support": (
        ResolutionAction(
            Outcome.UPHELD,
            True,
            "Vulnerability marker was recorded but not surfaced to the servicing "
            "screens, so disclosed needs were repeatedly missed. Marker visibility "
            "corrected across all channels. Communications switched to large print "
            "and a named contact assigned. Compensation paid for distress.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            False,
            "Reasonable adjustment request had been recorded in free text rather "
            "than as a structured flag and was therefore never applied. Request "
            "re-recorded correctly and applied retrospectively. Free-text capture "
            "replaced with a structured field in the servicing journey.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "The adjustments the customer asked for were in place on the account "
            "throughout and were applied at each contact on the call recordings "
            "reviewed. Adjustments restated in writing and a named contact "
            "assigned so the customer need not explain again.",
        ),
    ),
    "statement_errors": (
        ResolutionAction(
            Outcome.UPHELD,
            False,
            "Statement suppression had been left in place after a duplicate "
            "address merge. Suppression removed, missing statements reissued and "
            "the balance discrepancy traced to a pending transaction display "
            "defect, now corrected.",
        ),
        ResolutionAction(
            Outcome.PARTIALLY_UPHELD,
            True,
            "Statements were issued on time, but a merchant name displayed against "
            "the wrong reference for three entries and the customer reasonably "
            "read them as unrecognised. Descriptions corrected at source and a "
            "payment made for the trouble of reconciling them.",
        ),
        ResolutionAction(
            Outcome.NOT_UPHELD,
            False,
            "The entries queried are pending authorisations that had not yet "
            "settled, and the closing balance is correct once they clear. Worked "
            "example provided and the pending-transaction display explained.",
        ),
    ),
}
