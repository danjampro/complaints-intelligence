# Weekly Complaints Report — 2026-W31

**Status:** draft · **Run:** `2026-W31` ·
**Generated:** 2026-08-05 09:10 UTC ·
**Compared against:** 2026-W30

> This report is a **draft**. It is not a published record until a named
> reviewer signs it off. All figures are precomputed and referenced by fact ID;
> no figure in this document was produced by a language model.

---

## 1 · Complaint drivers

### 1. Failed or delayed payments

**Outbound payments faced rejections and duplicate deductions alongside delivery delays.**

Customers report that outbound payments failed repeatedly or were rejected without explanation, reaching 131.

> “outbound payment was rejected repeatedly without explanation and”
> — `CMP-2026W31-0006` (fos referral, chars 32–96)
> “my transfer failed with no explanation at all. I tried t”
> — `CMP-2026W31-0002` (mobile app, chars 0–56)

Transfers experienced delays or duplicated withdrawals, accompanied by late fees.

> “order was not paid on the due date. It sat as pending for four days and then just failed, and I incurred a late fee”
> — `CMP-2026W31-0004` (call centre, chars 62–178)
> “same payment was taken from my account twice. I have been charged doub”
> — `CMP-2026W31-0003` (mobile app, chars 4–74)

**Hypotheses requiring confirmation.** These are not established findings. Each
needs a named owner to confirm or reject it before it may be relied on.

- Technical glitches in the mobile application may have triggered duplicate transfers. *(unconfirmed)*

### 2. Direct debit set-up and cancellation errors

**Customers report unauthorised collections and unexpected cancellations of direct debits alongside misdirected mandates.**

Cancelled direct debits continue to be collected from accounts, reaching 45 complaints.

> “direct debit I cancelled was taken anyway. I h”
> — `CMP-2026W31-0012` (call centre, chars 50–96)
> “a direct debit I cancelled was taken anyway.”
> — `CMP-2026W31-0015` (mobile app, chars 0–44)

Direct debits are reported as cancelled without customer instruction, leading to lapsed insurance policies.

> “ter that a direct debit was cancelled without instru”
> — `CMP-2026W31-0016` (branch, chars 23–75)
> “, um, a direct debit was cancelled without my in”
> — `CMP-2026W31-0013` (call centre, chars 16–64)

**Hypotheses requiring confirmation.** These are not established findings. Each
needs a named owner to confirm or reject it before it may be relied on.

- System processing errors during automated mandate updates may explain the concurrent rise in unexpected collections and unrequested cancellations. *(unconfirmed)*

### 3. Overdraft fees and charges

**Customers report unexpected overdraft fees applied without prior notification.**

Customers report that overdraft fees were applied without any prior notification 58.

> “ld about. No notification was s”
> — `CMP-2026W31-0010` (mobile app, chars 43–74)
> “charges were applied without any”
> — `CMP-2026W31-0007` (fos referral, chars 50–83)

Complainants note that charges occurred alongside delays in transaction processing 31.

> “charge appeared three days after the transa”
> — `CMP-2026W31-0009` (fos referral, chars 32–76)
> “rged for going overdrawn and nobody w”
> — `CMP-2026W31-0011` (call centre, chars 37–74)

**Hypotheses requiring confirmation.** These are not established findings. Each
needs a named owner to confirm or reject it before it may be relied on.

- Increased fee volumes may be driven by recent changes in automated notification timings. *(unconfirmed)*

### 4. Support for customers in vulnerable circumstances

**Vulnerable customer support complaints rose this week following repeated failures to apply reasonable adjustments.**

The category reached 37 complaints, representing 68.2%.

> “The complainant submits that disclosed needs were recorded and then ignored at every subsequent”
> — `CMP-2026W31-0020` (fos referral, chars 0–96)
> “Customer] Yeah so, I told you about my circumstances and no”
> — `CMP-2026W31-0017` (call centre, chars 29–88)

Customers report that previously disclosed needs and promised adjustments were ignored during subsequent contacts.

> “at disclosed needs were recorded and then ignored at every subsequent contact,”
> — `CMP-2026W31-0020` (fos referral, chars 26–105)
> “support promised was never put in place. Customer states a vuln”
> — `CMP-2026W31-0019` (branch, chars 44–107)

Individuals state that requested format changes, such as large print communications, were not implemented.

> “ight, um, I asked for large print communications and”
> — `CMP-2026W31-0018` (call centre, chars 12–64)
> “d branch to report that the support promised was ne”
> — `CMP-2026W31-0019` (branch, chars 16–67)

**Hypotheses requiring confirmation.** These are not established findings. Each
needs a named owner to confirm or reject it before it may be relied on.

- The rise in complaints was driven by systemic failures in updating customer records across branch and telephone channels. *(unconfirmed)*

### 5. Branch closure and reduced hours

**Customers report difficulty accessing banking services following branch closures and reduced operating hours.**

Customers report that reduced branch operating hours conflict with standard working hours, reaching 29.

> “the branch hours have been cut and I cannot get there before it shuts. I work until”
> — `CMP-2026W31-0024` (mobile app, chars 0–83)
> “ght, um, my branch has gone and I do not use the internet at all. I care for my husband and”
> — `CMP-2026W31-0022` (call centre, chars 13–105)

Customers report that branch closures were announced with inadequate notice and lacked alternative access arrangements.

> “The complainant's position is that the closure notice given was inadequate and that no alternati”
> — `CMP-2026W31-0023` (fos referral, chars 0–96)
> “Customer attended branch to report that their local branch has closed with very little not”
> — `CMP-2026W31-0021` (branch, chars 0–90)

**Hypotheses requiring confirmation.** These are not established findings. Each
needs a named owner to confirm or reject it before it may be relied on.

- The increase in complaints is driven by recent unannounced branch closures and abrupt timetable changes. *(unconfirmed)*


---

## 2 · Sentiment trends vs 2026-W30

| Category | Channel | 2026-W30 | 2026-W31 | Shift |
|---|---|---|---|---|
| Failed or delayed payments | mobile app | -0.54 | -0.76 | -0.22 |
| Direct debit set-up and cancellation errors | call centre | -0.46 | -0.70 | -0.24 |

Sentiment runs from `-1` to `+1` and is compared **within channel**, never
pooled across channels: a category whose complaints shift from the app to the
call centre would otherwise appear to change tone when only its channel mix
moved. A row appears only where the shift cleared both a significance test and
a minimum size.

No model was involved in producing this section at all. A sentiment trend is
entirely figures, and figures are the one thing the model may never author.

---

## 3 · Emerging risk themes

Themes below are clusters of complaints that matched no existing category. They
are reported as narrative with evidence and **are not counted in the trend
tables** — they have no comparable history. Adopting one as a category is a
separate, human-approved decision.

### CT-007 — Savings round up feature duplicates transfers on purchases

Customers report that the automatic savings round up feature transfers money twice for a single purchase, coinciding with an application update. This pattern appears across multiple channel streams among 34 complaints. The text shows distinct phrasing across records.

> “, um, every time I tap my card the savings pot takes the round-up twice”
> — `CMP-2026W31-0031` (call centre, chars 16–88)
> “he automatic round-up savings feature is collecting each transfer twic”
> — `CMP-2026W31-0032` (branch, chars 41–111)


### Candidate themes considered

| Theme | Verdict | Reasoning |
|---|---|---|
| `CT-007` | **real signal** | Customers report that the automatic savings round up feature transfers money twice for a single purchase, coinciding with an application update. This pattern appears across multiple channel streams among 34 complaints. The text shows distinct phrasing across records. |
| `CT-012` | **ingest artefact** | The cluster exhibits near-identical phrasing across 28 complaints arriving through a single intake channel on its initial appearance. Customers describe system unavailability when booking branch appointments. Additional independent sources or varied wording would change this assessment. |

Every candidate the metrics layer carried appears above, including those
rejected. A theme dismissed silently is indistinguishable from one never
examined.

---

## 4 · Remediation recommendations

Recommendations are grounded in how comparable complaints were **actually
resolved**, retrieved from resolution notes on closed cases. They are not
general good practice.

### F-01

The payments engineering team must investigate gateway timeouts and payment retries following 131 complaints, while customer support manually traces affected transactions and refunds any associated fees.

**Suggested owner:** Payments Engineering Team *(advisory — a named owner is
assigned at sign-off)*

**Precedents relied on**

- `CMP-2026W30-0001` — This precedent transfers because it addresses payment failures caused by gateway timeouts that required manual tracing and fee refunds.
- `CMP-2026W30-0002` — This precedent transfers because it involves duplicate debits and retries that required reversing collections and deploying a technical fix.

**Precedents considered and ruled out**

- `CMP-2026W30-0003` — This precedent does not transfer because it concerns a correctly rejected standing order rather than systemic outbound payment failures and duplicate deductions.

> “transfer failed and the m”
> — `CMP-2026W30-0001` (mobile app)
> “me payment was taken from my account tw”
> — `CMP-2026W30-0002` (call centre)

### F-02

The operations team must reinstate the affected mandates and restore lapsed policies at the firm expense, following the precedent set in CMP-2026W30-0006 where a cancelled direct debit was collected in error. Additionally, staff must add a confirmation step before applying any cancellation, addressing 45 complaints.

**Suggested owner:** Operations Team *(advisory — a named owner is
assigned at sign-off)*

**Precedents relied on**

- `CMP-2026W30-0006` — This precedent directly addresses unauthorised collections following a direct debit cancellation error, making the resolution actions fully applicable.

**Precedents considered and ruled out**

- `CMP-2026W30-0007` — This precedent involves a mandate set up against the wrong account rather than unexpected collections of cancelled direct debits.

> “, um, a direct debit I cancelled was collected anyway. I have the cancellation c”
> — `CMP-2026W30-0006` (call centre)

### F-03

Customer operations and servicing teams should refund unnotified overdraft charges affecting 58 complaints and clear any suppressed alerting flags, following the resolution of similar cases.

**Suggested owner:** Customer Operations *(advisory — a named owner is
assigned at sign-off)*

**Precedents relied on**

- `CMP-2026W30-0004` — This precedent applies because the complaint involved unnotified overdraft charges and was successfully resolved by refunding charges and clearing a suppressed alerting flag.
- `CMP-2026W30-0005` — This precedent transfers as it similarly addresses overdraft fees applied without warning by refunding unnotified charges.


> “that overdraft charges were applied wi”
> — `CMP-2026W30-0004` (fos referral)
> “overdraft fees with no warning”
> — `CMP-2026W30-0005` (mobile app)

### F-04

Customer service operations must ensure that reasonable adjustments are applied consistently across all channels following 37 complaints, representing 68.2%. The servicing team should replace free-text capture with structured fields and correct vulnerability marker visibility.

**Suggested owner:** Customer Operations Team *(advisory — a named owner is
assigned at sign-off)*

**Precedents relied on**

- `CMP-2026W30-0009` — This precedent directly addresses failure to provide requested large print communications due to free-text capture limitations.
- `CMP-2026W30-0008` — This precedent involves repeated failures to apply disclosed needs and adjust communications across multiple contacts.


> “t that requested large print communicatio”
> — `CMP-2026W30-0009` (branch)
> “u about my hearing loss and nothing”
> — `CMP-2026W30-0008` (call centre)

### F-05

The customer relations team should issue a personal apology, arrange a home visit to set up telephone banking, and correct mailing extract logic, following the precedent set in CMP-2026W30-0010 to address 29.

**Suggested owner:** Customer Relations *(advisory — a named owner is
assigned at sign-off)*

**Precedents relied on**

- `CMP-2026W30-0010` — This precedent transfers because it directly addresses unannounced branch closures and successfully resolves access issues through home visits and mailing corrections.

**Precedents considered and ruled out**

- `CMP-2026W30-0011` — This precedent does not transfer because the closure decision followed a documented statutory notice period and was not upheld.

> “rt that closure notice was not r”
> — `CMP-2026W30-0010` (branch)

### E-01

The servicing team should investigate the application update to identify the root cause of the duplicate transfers reported across 34 complaints, following the approach used in previous technical investigations.

**Suggested owner:** Servicing Team *(advisory — a named owner is
assigned at sign-off)*


**Precedents considered and ruled out**

- `CMP-2026W30-0003` — This precedent addresses a standing order failure notification issue rather than a duplicate transfer feature defect.
- `CMP-2026W30-0007` — This precedent involves an ambiguous mandate instruction rather than a software-driven duplicate transaction.
- `CMP-2026W30-0005` — This precedent concerns missing overdraft pre-notification alerts rather than duplicate feature transfers.
- `CMP-2026W30-0004` — This precedent relates to suppressed alerting flags for overdraft charges rather than savings feature duplication.
- `CMP-2026W30-0009` — This precedent deals with reasonable adjustment communication preferences rather than a savings feature issue.
- `CMP-2026W30-0010` — This precedent addresses missing account closure notices rather than a duplicate transfer application defect.



---

## 5 · Verification

Every check below is programmatic. No model was involved in verifying this
report.

| Check | Result | Detail |
|---|---|---|
| `facts_resolve` | pass | every referenced fact ID resolves in the fact store |
| `no_literal_numbers` | pass | no published sentence states a figure directly |
| `citations_present` | pass | every qualitative claim carries at least 2 citations |
| `citations_resolve` | pass | every citation resolves to source text |
| `no_pii` | pass | no personal data detected in output |


Revisions used: 0

### Run notes

The following degradations were recorded. They are part of the record.

- statement_errors was flagged but fell outside the investigation budget of 5
- remediation for E-01: only 0 of 6 precedents transferred; widening retrieval beyond the category

---

## 6 · Provenance

This report is reconstructable from the pinned versions below plus the fact
store for run `2026-W31`.

| | |
|---|---|
| Taxonomy version | `v4.2` |
| Prompt version | `v1` |
| Model | `gemini-3.5-flash-lite` |
| Model mode | `replay` |

**Run cost.** 14 model call(s),
14 tool call(s).

**Node sequence.** `investigate → adjudicate → remediate → critic`

---

*All data in this report is synthetic. Nothing here relates to any real
customer, complaint, or firm.*
