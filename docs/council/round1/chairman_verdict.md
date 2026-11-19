# Chairman's Verdict: Kartaa BRD v2.0

Verdict: as specified, Kartaa does not yet win, and it should not be called "final". It is a sound build baseline for one narrow product, marketplace-seller GSTR-1/3B preparation (R1). The BRD currently presents a much larger product (R1-R4, invoicing plan, help bot, team roles) whose value claim is unproven, whose numbers no human CA has checked, and whose invoicing half cannot issue a legal invoice while numbering is OFF (D-010, SI-6). Market-fit claims against Vyapar, Zoho, ClearTax, Tally, MyBillBook and Busy are all unverified in the BRD and by this Council; no advisor checked competitors, so every competitor statement below stays marked unverified.

## Where the Council Agrees

1. **No human CA, no trust.** All five say the golden GSTR-1/3B cases and Table 13 are "AI reader, not human-signed" (s8), yet GF-18 ships "ready to upload" JSON. A named, engaged CA signing the cases is a hard gate before any external user.
2. **Demand is unvalidated.** s5 admits the "hybrid seller" wedge and the market numbers are desk research. No interviews, no pilot customer, no real CA. "Final baseline" is the wrong label.
3. **Invoicing is not sellable while numbering is OFF.** Every invoice is a PR- practice invoice that never enters a return, yet BL-4 prices a Rs 999 "invoicing plan". Four of five advisors (not the Expansionist) and all five peer reviews flagged this.
4. **The CA is a login, not a channel.** s5 calls CAs a channel, s7.1/TM-1 gives them nothing, and the metric "2 pilot CAs add a second client" has no feature behind it.
5. **No go-to-market, no support model.** No named source for the 10 pilot sellers, no onboarding, no support contact or response time (s13 leaves it open and go-live is blocked).
6. **Payment-after-value plus "no refunds" works against trust** for an unknown brand selling an unverified tax output (BL-2, BL-3).
7. **WhatsApp, Hindi/regional language and offline are absent.** Four of five rank this Major; the Council differs on timing (see Clashes).

## Where the Council Clashes

1. **Cut scope or grow it.** First Principles, Outsider, Contrarian and Executor want R1 alone as the wedge. The Expansionist wants more: CA partner plan, higher tier, footer referral loop, reconciliation certificate, Tally export, settlement roadmap. **Chairman: the cutters are right.** The product is unlaunched with no customer. Growth scope is rejected or deferred (row 28), except the CA home, which is the cheapest distribution lever and which four advisors independently asked for (row 8).
2. **WhatsApp and Hindi: now or after the pilot.** Four advisors want WhatsApp share and Hindi in R1/R2 acceptance. **Chairman: defer WhatsApp**, because the product sold at launch is the filing flow, which produces no customer-facing invoice, so WhatsApp share has little to attach to. Do cheap groundwork now (externalise strings, row 22) and let pilot interviews decide Hindi guide copy. Cost of deferring: a pilot seller may compare against billing apps; that risk is small while invoicing is not sold. This is a recommendation, not a certainty. Competitor feature lists are unverified.
3. **Pricing.** Contrarian suggests Rs 299 or per-return, Expansionist suggests tiers, Outsider and First Principles want a free first return. **Chairman: keep Rs 499/999 as the stated hypothesis**, label it "to validate", test alternatives in the interviews, and change the payment terms (first-period guarantee), not the price. The price points themselves are the Council's weakest evidence (no WTP data).
4. **Severity of the missing CA.** The Expansionist treats it as a residual objection; the other four treat it as a Blocker. **Chairman: Blocker.** Wrong figures in a tax product lose the customer permanently, and no CA will endorse it unsigned.
5. **Scope of CA work.** The Expansionist wants a CA partner plan and bulk tools; the Executor wants a CA home before the help bot. **Chairman: minimal CA home (list, status, needs-check counts) now; partner pricing and bulk download only after 3 pilot CAs ask for them.**
6. **Build vs buy GSP APIs** (raised by one peer review). Rejected: it contradicts the approved "we never file / no GSP" position and would need approval gates under the project rules. Not worth a council row.
7. **Percentage metrics vs counts.** Executor's counts ("7 of 10 reach a JSON") are better for n=10. Adopted.

## Blind Spots the Council Caught

Peer reviews found gaps that all five advisors missed. Each is now a row.

- **Why would a seller switch?** Vyapar, ClearTax, Busy and Tally are said (unverified) to export GSTR-1 JSON already. The BRD has no one-sentence wedge. Candidate to test: marketplace report plus own invoices to a reconciled GSTR-1/3B in one upload, with held rows explained. Unproven (rows 4, 7).
- **Liability and terms.** Nobody asked what happens when a wrong figure causes a penalty. No ToS, privacy notice, disclaimer, or professional-indemnity position exists, and "no refunds" compounds it (rows 5, 15, 16).
- **Data protection.** D-094 covers residency, not consent, grievance contact or breach handling. Applicability of India's DPDP Act to Kartaa is unverified and needs a lawyer (rows 15, 16).
- **Format drift.** Marketplace report formats and the portal JSON schema change; one change silently breaks every user. The BRD names no owner (row 17).
- **Pankaj as single point of failure** for every launch step (row 10).
- **Who pays the CA reviewer**, and how (row 3).
- **Unit economics**: Bedrock, SES, Lambda and support cost per tenant against Rs 499 (row 26).
- **Cheapest validation**: a concierge test where Pankaj hand-prepares one real filing before more building, and a CA-led pilot where CAs bring their own client files (row 4).
- **Seller errors**: wrong period or wrong GSTIN selected (row 29).
- **Kill rule tied to cost or time**, not only to seller counts (row 4).
- Mobile OTP login and deadline reminders came up only once each; deferred (row 23).

## The Recommendation

1. **Call v2.0 the "working baseline", not final**, and re-baseline to a single launch product: **R1, marketplace-seller GSTR-1 JSON and GSTR-3B worksheet preparation** (row 2). R2-R4 stay in the codebase, unsold and out of launch criteria, until a CA settles numbering scope and the R1 loop is proven.
2. **No external user and no money until a named, engaged CA has signed the golden cases and Table 13** (row 3). Until then everything is "pilot, unverified" and the UI says so.
3. **Validate before building more**: 15 recorded interviews, a verified-or-unverified competitor teardown, one concierge filing, and a written kill rule (row 4).
4. **Fix trust mechanics, not price**: first-period guarantee for CA-confirmed errors, a "report a wrong figure" path, terms and privacy notice, support contact with a response time (rows 5, 14, 15).
5. **Make the CA useful** with a minimal multi-client home, and test CA-pays vs seller-pays in the pilot (rows 8, 9).
6. **Reject for now** (not for the product forever): WhatsApp, PWA/offline, tiers, referral footer, certificate page, Tally export, settlement roadmap, Ask Kartaa and GSTIN lookup in launch criteria.

I disagree with the Expansionist's framing that this is "a utility missing a business". It is a utility missing a customer. The business thesis can wait for evidence.

## The One Thing to Do First

**Pankaj engages a named, paid CA under a written scope this week**, and in the same week runs one real filed period (Vaashi's) through the app and diffs it against that CA's return. It unblocks the largest trust objection, tests the only real value claim, and every other gate depends on it. Interview scheduling can run in parallel.

## Consolidated change list for the BRD

| # | Finding | Severity | Concrete BRD change (new/changed requirement ID or section) | Type |
|---|---|---|---|---|
| 1 | "Final baseline" label is unearned; most facts are desk research (s1, title, s5) | Major | Retitle "v2.0 working baseline"; s1 states "final" follows pilot evidence and CA sign-off; every market and competitor fact in s5 gets a verified/unverified tag | EDIT |
| 2 | "Ready return" promise contradicts practice-only invoicing; R2-R4 cannot produce a real return or be legally sold (D-010, SI-6, BL-4, s3). Only marketplace R1 delivers value | Blocker | Add to s2: "Launch product = R1 marketplace GSTR-1/3B preparation." s3: R2-R4 flagged "built, not sold, not in launch criteria". BL-4 marked inactive. Code stays. **Recommendation:** adopt. **Cost of leaving it:** months of polish and a Rs 999 plan that sells practice invoices | PROPOSAL |
| 3 | No human CA; golden cases are AI-written (s8, CA-1..5, Table 13, GF-18) | Blocker | New launch gate L-1 and NF-17: no external user until a named registered CA signs GSTR-1/3B golden cases and Table 13 in writing; no paid plan until recorded. Until then GF-18/19 show a "pilot, unverified" banner. Record the CA's name; show "Reviewed by" only with written consent. Budget the CA's fee (see s13) | PANKAJ |
| 4 | Demand and wedge unvalidated; no kill rule (s5, s10) | Blocker | New gate L-0: at least 15 recorded interviews plus one concierge filing (Pankaj hand-prepares a real return) and a competitor teardown (each competitor verified/unverified, including whether they already export GSTR-1 JSON). Add kill/pivot rule, e.g. fewer than 3 of 10 file a second period, or fewer than 5 of 10 would pay, or a spend/time cap Pankaj sets | PANKAJ |
| 5 | Payment after value plus "no refunds" at an unproven price (BL-2, BL-3, GF-19/20, s4) | Major | Pilot stays free with no gate. When charging starts: first paid period refundable if a figure is CA-confirmed wrong; BL-3 "no refunds" limited to change of mind after the first period. Add "report a wrong figure" action. Gate placement stays at JSON download (approved) but the summary must say so before upload. **Recommendation:** adopt. **Cost of leaving it:** conversion loss and liability exposure. Needs legal review of the terms (row 16) | PROPOSAL |
| 6 | Rs 499/month filing price is an untested hypothesis against billing-app prices (s4, s5, BL-1) | Minor | Keep price. Mark "to validate (unverified WTP)". Interview script tests Rs 299, per-return and annual. Reject tiers and per-GSTIN add-ons until proven. **Cost of leaving it:** none now; a wrong price is discovered at the 5-of-10 willingness-to-pay check | PROPOSAL |
| 7 | "We don't file" is not obvious; sellers expect filing (s2, GC-P1, GF-18/19) | Major | New ON-AC: landing, sign-up and summary carry "what you still do yourself" (download, upload to portal). Acceptance: 8 of 10 first-time interviewees correctly state what Kartaa does and does not do. Add one-sentence wedge, to be tested in row 4 | EDIT |
| 8 | CA is a login, not a channel (s5, s7.1, TM-1, s10 metric) | Major | New CA-1 "CA home": one screen listing the CA's client businesses, each period status, and "needs CA check" counts. AC: a CA with 5 clients sees all 5 on one screen. Tenant isolation test per NF-1. Excluded until demand shown: bulk download, partner billing | EDIT |
| 9 | Who pays (seller or CA) and CA economics undefined (s4, BL) | Major | Pankaj decides after 3 CA conversations; record in s13 and DECISIONS. Replace metric with "3 named CAs each bring clients" | PANKAJ |
| 10 | No go-to-market; launch chain runs through one person (s3, s10, s13) | Blocker | New s10a "First 10 and Weeks 0-4": every launch checkbox and s13 row gets an owner and date; named sources (Vaashi, Pankaj's contacts, 3 CAs each bringing 3 clients, seller communities); founder-led onboarding call; backup owner named for each step. Pankaj assigns the dates | PANKAJ |
| 11 | Acceptance criteria not testable: GF-18 format not named, GF-2 20 MB "to confirm", accuracy "0 differences" has no sample or procedure, NF-6 has no tool | Major | Per item add fixture, pass/fail check, owner. GF-18 names schema version after R1-M0. NF-6 names measurement method and environment. Accuracy: define periods, who diffs, and what counts as a difference | EDIT |
| 12 | GF-18 "ready to upload" conflicts with GF-21 "never ready to file" | Major | One approved wording set in s8: "prepared for your CA or you to check and upload". Apply to GF-18, GF-19, GF-21 and UI copy | EDIT |
| 13 | GSTR-3B has no ITC or net payable; thin product (GF-24, GF-25) | Major | State in GF-21 and marketing: worksheet from your sales only, no ITC, no net payable. Defer GSTR-2B ingestion; revisit after interviews. **Reason for deferral:** scope on an unlaunched product | EDIT |
| 14 | No support requirement or SLA (s13) | Major | New requirement SP-1: published support address, stated response time, named weekly owner; static FAQ page. Pankaj supplies the contact (go-live blocker already in s13) | EDIT |
| 15 | No terms, privacy notice or disclaimer; consent and breach handling absent (D-094 covers residency only) | Major | New requirements: ToS with liability limits and "prepared, not filed" disclaimer; privacy notice with consent, grievance contact, breach process; per-business confirmation of period and GSTIN | EDIT |
| 16 | Legal review of terms, refund policy, DPDP applicability (unverified) and professional indemnity | Major | Add to s13 as launch gate with owner. Do not state any statutory requirement in the BRD until a lawyer confirms | PANKAJ |
| 17 | Marketplace report and portal JSON schema drift has no owner | Major | New GF-AC: parser versioned per platform; fixture per platform and format version; unknown column set blocks with a clear message rather than guessing; named owner; process to re-check portal schema before each filing deadline | EDIT |
| 18 | Onboarding assumes the seller can already fetch the right report (J1, J2, GF-2) | Major | GF-2 AC: per-platform "how to get this file" screens; measure "first return completed", not sign-up | EDIT |
| 19 | Pilot carries unneeded scope (AK-1..4, ON-9, 4-role route tests) | Minor | Remove AK and ON-9 from launch criteria; static FAQ replaces help bot at launch; keep code. Role tests stay on regression, not on the launch path | EDIT |
| 20 | Percentage metrics meaningless at n=10; test tenants are the founder's own circle (s2, s10, s11) | Minor | Replace with counts ("7 of 10 reach a GSTR-1 JSON"); pilot must include at least 5 external sellers on 2 or more marketplaces | EDIT |
| 21 | WhatsApp share deferred (SI-11); competitor feature parity unverified | Minor | **Recommendation:** keep deferred; revisit when invoicing is sold. If the pilot asks, add wa.me link share of an issued invoice page (no Business API). **Cost of leaving it:** gap versus billing apps if invoicing launches | PROPOSAL |
| 22 | No Hindi or regional language (s2, s6) | Minor | New NF: all UI strings externalised from now; Hindi for the filing guide decided from interview results, not committed | EDIT |
| 23 | Offline, PWA, mobile OTP login, deadline reminders (NF-10, NF-15, ON-1) | Minor | **Recommendation:** reject PWA and offline for now; NF-10 states "no offline support". OTP and reminders go to s12 as ideas for post-pilot. **Cost of leaving it:** shop owners without email may not sign up; test in interviews | PROPOSAL |
| 24 | Housekeeping: duplicate ON-1 sentences, dangling "decision D2" in GF-14, undefined "BH-6" and "ON-5" IDs, R1 "Built" next to "payment placeholder", NF-16 demo has no PDF renderer | Minor | Fix each or delete it; confirm mocks link is shared (s14) | EDIT |
| 25 | Ops: Lambda cold start vs 2 s target (NF-6), one session per user hurts shared CA logins (NF-15), 90-day raw-file deletion vs disputes | Minor | Write cold-start mitigation or relax NF-6; NF-15 allows concurrent CA sessions or documents the limit; state dispute-handling retention | EDIT |
| 26 | Unit economics untested (NF-11) | Minor | Add per-tenant cost measure (Bedrock, SES, Lambda, support time) against Rs 499 to s10; stop rule if it exceeds an agreed share | EDIT |
| 27 | Numbering decision open with no date; R2/R3 unsellable until it closes (D-010, s13) | Major | Keep OFF. Add owner and date to the CA question; R2 claims in any copy gated on the CA answer. No change to the approved decision | PANKAJ |
| 28 | Expansion ideas for an unlaunched product: partner plan billing, upsell tiers, "Prepared with Kartaa" footer, reconciliation certificate, Tally/Busy export, settlement and working-capital roadmap | Minor | **Rejected for now.** Record in s12 as unapproved ideas with trigger: revisit after the R1 loop works and 3 CAs commit. One cheap design rule to keep: stable SKU key on imported rows. **Cost of leaving it:** none before launch | EDIT |
| 29 | Seller errors: wrong period or GSTIN picked | Minor | Confirm step before build: period, GSTIN and platform shown for confirmation; recoverable without data loss (extends ON-8) | EDIT |

Counts: 29 rows. EDIT 18, PROPOSAL 5, PANKAJ 6. Blockers 4 (rows 2, 3, 4, 10).

## Material objections that would remain after this list is applied

1. **CA sign-off still has to be obtained.** The list makes it a gate, but until a named CA signs, the compliance accuracy objection stands. Only Pankaj can close it.
2. **Demand and willingness to pay are unproven.** Gates L-0 and the kill rule make it testable, not true. The Rs 499 price and the hybrid-seller wedge stay hypotheses until interviews and pilot payments.
3. **Competitive position is unverified.** No one checked Vyapar, Zoho, ClearTax, Tally, MyBillBook or Busy. The teardown in row 4 must be done before the market-fit claim can stand.
4. **Invoicing remains practice-only** until the CA answers numbering scope (row 27), so the "invoicing plus GST" story cannot be sold even after this list.
5. **Legal posture is unverified** (terms, liability, DPDP applicability) until Pankaj obtains legal review (row 16).
