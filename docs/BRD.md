# Kartaa BRD v2.5 (council-reviewed baseline): GST invoicing and filing for small Indian businesses

19 Nov 2026 · Pankaj Kumar (owner) · Product Owner, reviewed by a five-advisor council (rounds 1 to 5 applied)

Kartaa is a web portal where a small GST-registered business signs up by itself and gets a **GSTR-1 JSON** prepared for them to check and upload, plus a **GSTR-3B sales worksheet**, from its own invoices and marketplace reports. ITC and payment are entered or done on the GST portal. The owner or CA checks and uploads instead of retyping. We prepare, you file.

## Changes made after each council review

| Round | Council finding | Change made | Section |
| --- | --- | --- | --- |
| 0 | Baseline: consolidated v1.0 to v1.3 and everything decided or built to 19 Nov 2026 | New BRD v2.0 | All |
| 1 | The BRD is titled "final" while demand, compliance accuracy and competitors are all unverified (all 5 advisors) | Retitled "council-reviewed baseline"; status says final for build, not validated; launch gates added | 1, 10 |
| 1 | The "ready return" promise cannot be delivered by invoicing while numbering is OFF; only marketplace R1 produces a real return (4 of 5) | Added a launch-product statement and "built, not sold" flags for R2 to R4 and BL-4 as **PROPOSAL P-1** (approved scope untouched) | 2, 3, 7.8, 12 |
| 1 | No human CA has signed any golden case or Table 13 yet; trust is the product (5 of 5) | Hard gates L-1 and NF-17: no external user before a named CA signs; "pilot, unverified" banner on the JSON until then | 10, 9 |
| 1 | Demand and wedge unvalidated; no kill rule (5 of 5) | Gate L-0 (15 interviews, one concierge filing, competitor teardown) and kill rules; verified competitor table added | 5, 10 |
| 1 | Payment after value plus "no refunds" at an unproven price works against trust (4 of 5) | **PROPOSAL P-2** first-period guarantee; price kept but marked "to validate"; summary states the paywall before upload | 7.8, 12 |
| 1 | "We prepare, you file" is not obvious; competitors already export GSTR-1 JSON (verified for four vendors) | New ON-10 "what you still do yourself" and acceptance test; wedge rewritten around marketplace plus own invoices in one reconciled return with held rows | 2, 7.1 |
| 1 | The CA is a login, not a channel (4 of 5) | New CAH-1 CA home (client list, period status, needs-check counts); partner pricing and bulk tools deferred until 3 pilot CAs ask | 7.7 |
| 1 | No go-to-market, no owners or dates, one person on every launch step (3 of 5) | New section 10a "First 10 and weeks 0 to 4" with owner per gate; backup owner rule | 10 |
| 1 | No support, terms, privacy notice or liability position (4 of 5) | New SP-1 support, LG-1 terms and disclaimer, LG-2 privacy and consent, LG-3 wrong-figure report; lawyer review is a Pankaj item | 7.11, 13 |
| 1 | Acceptance criteria not testable (GF-18 format, GF-2 limit, accuracy method, NF-6 tool) | Fixture, check and owner added to each; accuracy procedure defined | 7.2, 9, 10 |
| 1 | "Ready to upload" (GF-18) contradicts "never ready to file" (GF-21) | One wording set GC-W1 used everywhere | 8, 7.2 |
| 1 | Marketplace report and portal JSON drift has no owner | New GF-31 versioned readers, unknown-layout block, pre-deadline schema check | 7.2 |
| 1 | Seller cannot find the right report; no reminder of period or GSTIN mistakes | GF-2 "how to get this file" screens; ON-8 confirm period, GSTIN and platform before build | 7.1, 7.2 |
| 1 | WhatsApp, Hindi, offline, mobile OTP absent | Strings externalised now (NF-18); WhatsApp share, PWA and OTP recorded as **PROPOSALS P-4 and P-5**, recommended deferral | 9, 12 |
| 1 | Pilot carries scope it does not need (help bot, GSTIN lookup) | Removed from launch criteria; static FAQ at launch; code kept | 7.9, 10 |
| 1 | Percent metrics meaningless at n=10; pilot is the founder's own circle | Count targets; at least 5 external sellers on 2+ marketplaces | 10 |
| 1 | Unit economics, cold start, shared CA sessions, dispute retention untested | Cost per tenant metric, NF-6 method, limits documented, open questions | 9, 10 |
| 1 | Expansion ideas (tiers, referral footer, certificate, Tally export, settlement roadmap) | Rejected for now, recorded with a revisit trigger | 12 |
| 1 | Housekeeping: duplicate ON-1 text, dangling D2, undefined IDs | Fixed | 7.1, 7.2, 9 |
| 2 | Hand-collected payment in the first-10 plan contradicts "pilot is free", D6 and the L-5 gate (5 of 5) | Pilot free for every seller until L-5, by any method; hand collection removed; willingness measured by stated intent | 10, 10a |
| 2 | Concierge filing on real Vaashi data conflicts with the synthetic-or-masked rule (5 of 5) | New gate L-0a real-data approval protocol (where, who, consent, deletion); "external user" defined | 1, 10 |
| 2 | Kill rules cannot be tested at week 4; L-0 had no pass thresholds (5 of 5) | Gate A (week 4, numeric thresholds) and Gate B (week 16, three filing periods); spend cap recorded in week 0; pilot safety rule that a CA reviews before a seller relies on a figure | 10, 10a |
| 2 | No list of the build still needed; Table 13 and D-099 approval missing from the plan (4 of 5) | New section 3a build list in dependency order; D-099 approval in week 0 and before L-2; Pankaj item added | 3a, 10, 13 |
| 2 | Headline oversells GSTR-3B (4 of 5) | Promise reworded: GSTR-1 JSON plus a 3B outward-supply worksheet, no ITC; interview question on 3B value in Gate A; GSTR-2B revisit trigger | Top, 2, 10 |
| 2 | CA channel gated but unbuildable; ID clash with CA-1 question; no CA-initiated invite (3 of 5) | Renamed CAH-1; added CAH-2; TM-1 to TM-3 and CA parts kept in launch criteria; 5 CA conversations in L-0; no-CA-client kill rule | 7.7, 10 |
| 2 | First-10 mix overbooked; accuracy needs three filing cycles (2 of 5) | Mix set (1 Vaashi, up to 4 contacts, up to 5 CA clients); pilot runs three periods to week 16 | 10a |
| 2 | Contradictions and gaps: P-1 status, mobile sign-up line, Zoho and BUSY Recom claims, "Vashi", undefined GF-11, P-2 adjudicator and refund scope, 90-day deletion vs LG-3, jargon, interview consent, EM and PO undefined | Fixed or defined; SP-2 plain-words requirement; marginal vs fully loaded cost | 1, 5, 7, 10 |
| 2+ | Coordinator update (not a council finding): #365, #366, #367 (D-101), #363, #364 merged; #368 (D-102) and #369 in review | Build state and SI-2, SI-8, ON-9 updated | 3, 7 |
| 3 | Launch gates contradict the free pilot (L-5 and L-6 listed before any external user) and L-5, L-6 had no schedule (all 4 raising it) | Gates split into pilot-entry (L-0a, L-0, L-1 to L-4), L-5 before money, L-6 and Gate B before public launch; L-5 and L-6 rows in 10a; BL-2 says the gate is off in the pilot | 1, 10, 10a, 7.8 |
| 3 | Gate A tested price, not whether sellers would switch from Vyapar, Zoho, Tally or their CA (1 of 5) | Gate A records each seller's current method and cost; at least 6 of 15 must say they would switch after a masked concierge output | 10 |
| 3 | Pilot banner condition was dead (shown only until L-1, which precedes any pilot) (1 of 5) | Banner shown until the named CA reviews that return or Gate B accuracy passes | 8, 3a |
| 3 | 10a omitted build items 5, 6, 8, 10, the L-4 work, and a failure path for the portal upload (3 of 5) | All pilot-entry items scheduled in weeks 0 to 3; L-4 row; written pilot-entry checklist at week 3 to 4; capped slip rule for L-2 | 3a, 10a |
| 3 | Minor consistency and safety items: "ready" wording, IRN claim without CA tag, backup window, QRMP in the accuracy metric, CA channel count, channel for sellers 11 to 100, mandatory TOTP for CAs | Fixed; mandatory TOTP recorded as proposal P-7 | 2, 7.1, 9, 10, 12 |
| 4 | Gate B could not be evaluated at week 16 (three filed periods end after it) and a slip had no testable consequence (3 of 5) | Gate B runs when the third period's CA diff is done, not before week 18 and no later than week 22; periods filed before the pilot can be back-tested; a Gate A slip beyond 4 weeks stops the plan until Pankaj decides | 10, 10a |
| 4 | Gate A had two untestable criteria (1 of 5) | 3B worksheet: at least 8 of 15 would use it; if L-0a is not approved the concierge diff is against the CA's independent preparation of the masked case and the golden cases | 10 |
| 4 | Money and build were committed before the demand gate (1 of 5) | Pilot-entry split: L-0a, L-0, L-1, L-2 before Gate A; L-3, L-4 and build items 6 to 8 after Gate A and before the first seller; pilot starts week 6 | 3a, 10, 10a |
| 4 | No gate observed real payment (1 of 5) | Gate B: once L-5 holds, at least 3 of 10 pilot sellers make a real first payment; otherwise "payment unproven" and public launch is a paid soft launch capped at 20 sellers | 10 |
| 4 | Retention rule measured forgetfulness: no reminder existed (1 of 5) | New GF-32 email period reminders (pilot-entry); second-period rate reported with and without a reminder | 7.2, 3a, 10 |
| 4 | Portal test upload on a live GSTIN had no safeguards (1 of 5) | L-2 rules: no Generate Summary, Submit or File; test period already filed or not open; draft reset and recorded; CA confirms procedure | 10, 10a |
| 4 | "The named CA" was singular and P-7 was unscheduled (1 of 5) | Reviewing CA defined; CA review capacity and fee in L-1; P-7 decided in week 0 or CAH-1 ships only with it; banner tied to the accuracy metric | 1, 8, 10, 10a |
| 5 | Accuracy test not independent: the CA saw Kartaa's figures before filing (1 of 5) | Accuracy sample is prepared blind: the reviewing CA prepares and files from source documents before seeing Kartaa output; reliance review applies only to non-sample returns; "named CA" replaced by "reviewing CA" in the metric, Gate B and GC-W1 | 10, 8 |
| 5 | Gate B real-payment test had no consequence when L-5 holds and fewer than 3 pay (1 of 5) | Fewer than 3 of 10 paying at the tested price is a Gate B stop-or-reposition item | 10 |
| 5 | Own-invoice intake undefined: sellers hold sales data in Vyapar, myBillBook, Tally or Busy (1 of 5) | New GF-14a column-mapping intake (any Excel or CSV, saved mapping, unmappable rows held); interview question on invoice source; Gate A line (more than 5 of 15 not covered means revisit); 3a item 12 after Gate A | 7.2, 3a, 10 |
| 5 | Pilot CA diff used real seller figures with no handling rule, and named AI roles as owners (2 of 5) | Diff runs only in the India-region environment or on a named human's device in India, never in an AI session or shared project file; only anonymised difference descriptions leave it; consent names the CA comparison; interviews use an interim written consent; 10a week 1 owner is Pankaj and a named human | 10, 10a, L-0a |
| 5 | Minor: stale planning scale, GC-W1 wording, week 6 and L-5 targets | Planning scale reworded; "reviewing CA" in GC-W1; week 6 is a target and the pilot starts when the written checklist is complete; L-5 target week 14 | 5, 8, 10a |

## 1. Status and how to read this

- **Status:** v2.5, 19 Nov 2026. Council rounds ended at the five-round cap; the round 5 fixes in v2.5 were applied by the product owner and were not given a sixth review (see the change log). This is the **final baseline for scope and build**: it replaces the layered v1.0 to v1.3 text (kept unchanged as `brd-v1.3-archive.md` in the project files and in this document's history). It is **not yet validated in the market**: the council's unanimous finding is that demand, compliance accuracy and competitive position are unproven, so a pilot seller is admitted only through the **pilot-entry gates** (L-0a, L-0, L-1, L-2 before Gate A; L-3, L-4 after Gate A and before the first seller) and the public launch through the **public-launch gates** (L-5, L-6, Gate B), both in section 10. **External user** means anyone other than Pankaj, Vaashi's principals and the named CA working under the written scope. **Reviewing CA** means the named CA or, for a seller who already has one, that seller's own registered CA. **EM** is the Engineering Manager role, **PO** the Product Owner role (the simulated team in `team/`). Provisional status of P-1: sections 2, 3 and 7.8 carry it as a note and Pankaj can reverse it in one edit. The word "final" for the product itself follows pilot evidence and a CA sign-off.
- **Owner:** Product Owner. **Approver:** Pankaj, with day-to-day decisions delegated to the CEO since 24 Oct 2026. Items only Pankaj can decide are listed once, in section 13.
- **What "built" means in this document:** merged to `main` with tests passing in CI, per `docs/DECISIONS.md`. Nothing is deployed to real AWS, no real customer has used it, and no payment is taken. No CA has signed off any tax treatment. Every GST rule below is either cited from an official source or marked "to be confirmed".
- **Tax caution:** nothing here is tax advice. The product prepares numbers and files for the seller or their CA to check and upload on the GST portal; it never files and never says a return is compliant, filed or accepted.
- **Requirement IDs** (ON-, GF-, BL-, PU-, CS-, SI-, PG-, TM-, AK-, GL-, NF-, GC-) are stable. Where this baseline and the archive differ, this baseline wins.
- **Product name:** Kartaa. Domain and support contact are open (section 13).
- **Council review:** this baseline was reviewed by a five-advisor council (round-by-round log at the top). Council-driven changes to approved decisions appear only as marked **proposals** in section 12, never as silent edits.

## 2. The product in one page

**Promise.** A small GST-registered business signs up by itself and gets a GSTR-1 JSON prepared from its own invoices and marketplace reports, plus a GSTR-3B outward-supply worksheet (no ITC, no net payable), so its CA or the owner checks and uploads instead of retyping. Whether a 3B worksheet without ITC has value is a question in L-0; GSTR-2B ingestion is revisited only if the answer is no. Invoicing is how the data gets in; the ready return is why they pay.

**For whom.** Any small GST-registered business that sells goods: traders, wholesalers, distributors, retailers, and online sellers on Amazon, Flipkart and Meesho. Business type is an optional multi-select that never blocks anything (D-095). First test tenant: Vaashi Essentials (West Bengal, state 19, monthly filer), plus Pankaj's distribution business, on synthetic or masked data until real-data use is approved.

**What the product does.**

| Area | What the user gets |
| --- | --- |
| Onboarding | Self sign-up with email and one-time code, business profile, optional GSTIN lookup, filing frequency (monthly or quarterly), platforms sold on |
| GST Filing | Upload marketplace reports and own invoices, see held rows, get a GSTR-1 JSON in the official tool format, a GSTR-3B worksheet, deadlines, a step-by-step portal guide, mark filed and lock |
| Business Hub | Upload purchase invoices, build the catalog and stock, create sales invoices (practice invoices until the CA confirms numbering), credit notes, monthly sales-and-purchases files |
| Filing from own invoices | A per-period gate and one button that opens once the period has ended and the user has confirmed purchases and invoices |
| Team | Invite by link; four fixed roles: owner, admin, billing, CA |
| Ask Kartaa | In-app help for the GST portal and for the product (proposed, not built) |

**Launch product (PROPOSAL P-1, section 12; scope of R1 to R4 itself is unchanged).** Council recommendation: the first thing sold is **R1, marketplace-seller and own-invoice GSTR-1 JSON and GSTR-3B worksheet preparation**. R2 to R4 stay built but unsold and outside the launch criteria until a CA settles invoice numbering scope and the R1 loop is proven. While live numbering is off, every invoice is a practice invoice that never enters a return (D-010, SI-6).

**What you still do yourself.** We prepare and you (or your CA) check and upload on the GST portal; we do not file. This sentence appears on the landing page, sign-up and summary page (ON-10).

**What we do not do.** We do not file returns, do not integrate with GSPs or e-invoice (IRN) or e-way bill APIs, do not run accounting ledgers, payroll or bank reconciliation, do not issue invoices on a marketplace's behalf, and do not hold tenant data outside India (D-094). Mobile apps come after all four web releases.

**How we win (hypothesis to test in gate L-0).** Verified from vendor help pages on 19 Nov 2026: Vyapar, myBillBook, Zoho Books and TallyPrime all export a GSTR-1 JSON for upload to the GST portal, so a JSON file is table stakes, not our difference. What is not verified for any of them is a single reconciled return from a seller's own invoices **plus** Amazon, Flipkart and Meesho reports, with every figure traced to its file and row and every doubtful row held and explained. Our test wedge: "your own bills and your marketplace reports in one upload, every number traceable, so your CA only checks". If interviews show sellers do not value that over a low-priced tool (reported, unverified, at about ₹149 to ₹250 a month), we stop or reposition (kill rules, section 10).

| Competitor | Verified from its own page | Not verified |
| --- | --- | --- |
| [Vyapar](https://vyaparapp.in/videos/how-to-download-json-file) | Reports, GST reports, GSTR-1, export JSON, upload on portal | Plan that includes it; marketplace coverage |
| [myBillBook](https://mybillbook.in/s/gst-goods-and-services-tax/downloading-gstr1-json-file/) | GSTR-1 JSON from Reports in the app | Plan prices differ across its pages (about ₹250 a month billed yearly on one page, ₹399 a year Android plan on another); marketplace coverage |
| [Zoho Books](https://www.zoho.com/in/books/kb/gst/export-gstr1-details.html) | GSTR-1 export as JSON from GST filing; a competitor says marketplace coverage is Amazon and Shopify only | Current INR plans; Flipkart and Meesho |
| [TallyPrime](https://help.tallysolutions.com/tally-prime/gstr-1/export-gstr-1-in-json-format-update-rate-wise-hsn-sac-summary/) | GSTR-1 export in JSON | Marketplace reports; price |
| [Repotic](https://www.repotic.in/products/e-commerce-gst) | Marketplace GSTR-1 for Amazon, Flipkart, Meesho and others | No public price found |
| GST Tool, eVanik | Marketplace data to GSTR-1 JSON (vendor and third-party pages) | GST Tool about ₹149 a month is third-party and unverified |

## 3. Releases and build state

Four web releases, then mobile. Build state is from the decision register; "built" never means deployed or piloted.

| Release | Scope | Build state (19 Nov 2026) |
| --- | --- | --- |
| R1: onboarding and GST filing | Sign-up, setup, filing home with deadlines, per-section uploads, Amazon, Flipkart and Meesho readers, own invoices by Excel and PDF with cross-check, GSTR-1 build and checks, GSTR-1 JSON, GSTR-3B worksheet, plan display ("free for now"), step-by-step guide | Built through the worksheet. GSTIN lookup at sign-up is merged behind an adapter with a fake provider in the demo (#366); the real vendor is pending a sandbox from Masters India. B2C-large limit chosen by return period (#363) and provisional refdata labels cleared (#364) are merged. Payment gate is a placeholder (D-074). Table 13 in the JSON is specified (D-099, proposed); build pending (#353). Go-live prep (R1-M11) waits on real AWS |
| R2: invoicing (built, not sold: P-1; hybrid sellers are served by R1, which accepts own invoices as Excel or PDF plus marketplace reports) | Purchase upload and review, catalog and stock ledger, sales invoices with GST recalculated, practice PDFs, monthly and quarterly files, invoicing plan | Built. Live numbering is off until the CA confirms scope (D-010). Invoice-flow changes (D-097, approved by Pankaj) merged; blank-HSN relief for small sellers merged (#367, D-101); marketplace place of supply in review (#368, D-102, then the held-row screen #369); issued invoice page merged (#365) |
| R3: filing from own invoices (built, not sold: P-1) | Per-period gate, one-click file button, GSTR-1 from finalized invoices, platform files for hybrid sellers, return assignment | Built, live finalize shipped off behind a switch (D-091) |
| R4: team by invitation (built, not in launch criteria: P-1) | Invitation links, four fixed roles, permission tests on every route | Built (D-089) |
| After R4 | Android and iOS apps | Not started; needs approval |

### 3a. Build before the pilot (EM assigns owners and weeks; order is dependency order; items 1 to 5, 10 and 11 are needed before Gate A or the first seller as marked; items 6 to 8 and 12 are built after Gate A and before the first seller; item 9 may follow)

| # | Item | Needed for | Status |
| --- | --- | --- | --- |
| 1 | Approve D-099, then build Table 13 in the GSTR-1 JSON (#353, GF-30, C-08) | L-2 (portal upload fails without it), GF-18 | Not built; D-099 proposed |
| 2 | GC-W1 wording and the pilot banner (shown until the reviewing CA has reviewed that return, or the section 10 accuracy metric has passed) | Pilot entry | Not built |
| 3 | ON-8 confirm step (period, GSTIN, platforms) and ON-10 sentence | Pilot | Not built |
| 4 | GF-2 "how to get this file" screens and the 20 MB check against the largest real report | Pilot | Not built |
| 5 | GF-31 versioned readers and schema watch on the release checklist | Pilot | Partly (readers versioned; process not) |
| 6 | CAH-1 CA home and CAH-2 CA-initiated invite | CA channel | Not built |
| 7 | LG-3 wrong-figure report, SP-1 support footer and FAQ page | L-3 | Not built |
| 8 | NF-13 usage events for the pilot metrics | Gate B metrics | Not built |
| 9 | NF-18 string externalisation | Later languages | Not built |
| 10 | Held-row screen for marketplace place of supply (#369) after #368 | SI-8 | In review pipeline |
| 11 | GF-32 email period reminders | Pilot (second-period metric) | Not built |
| 12 | GF-14a column-mapping intake (after Gate A, before the first seller) | Wedge (own bills plus marketplace) | Not built |

Not yet done and outside the build: staging and production on real AWS, payment provider and our own GST registration, CA sign-offs, the test GSTR-1 upload to the GST portal, domain and email setup, pilot with real sellers.

## 4. Decisions in force

Approved decisions are listed with their source. A change to any row needs a recorded decision; council suggestions are in section 12 as proposals.

| Topic | Decision | Source |
| --- | --- | --- |
| Product | Self-onboarding GST invoicing and filing for any small GST-registered goods seller; marketplace uploads are an add-on; no business-type gating | D-001, D-095 |
| We prepare, you file | The app prepares returns; the seller or CA uploads on the GST portal. No GSP filing now | GC-P1, CEO 15 Oct |
| Platform | Web only for R1 to R4; mobile after | Pankaj 14 Oct, release plan v2 |
| Architecture | One modular-monolith app on AWS Lambda, RDS PostgreSQL, Terraform, Mumbai; React SPA | D-007, D-027 |
| Data location | Tenant data, files, backups and logs holding them stay in AWS Mumbai or Hyderabad only; no third-party service gets tenant data unless it processes in India; API not behind CloudFront | D-094, D-096 |
| Sessions | Access token 5 minutes, session 30 days, 24 hours idle; one active session per user; password policy 10+ characters with upper, lower, digit and special | D-028, D-060, D-061, D-092, D-093 |
| Roles | Owner, admin, billing, CA; every business route declares one permission, enforced by test | D-033, D-089 |
| Invoice numbering | One series per GSTIN, document type and FY, max 16 characters, no gaps; **live numbering OFF until the CA confirms scope**, so every invoice is a practice invoice (PR- number) | D-010, D-030, D-044, D-091 |
| PDF reading | Free text-layer reader in the app; paid Bedrock reader built but off; local OCR built, not used in production | D-054, D-077, D-078 |
| Payments | Placeholder: plans show prices and "free for now". Payment provider and our own GST registration are release blockers for Pankaj | D-074 |
| Pricing | GST filing only ₹499 per month or ₹1,499 per quarter; invoicing plus GST ₹999 per month or ₹2,499 per quarter, first 10 invoices free; all plus 18% GST; no refunds | Release plan v2 section 6, D-086 |
| Stock | Insert-only ledger; stock never blocks a sale | D-081, D-082 |
| Retention | Raw uploads deleted after 90 days; GST records 72 months (CA to confirm) | D-036, D-048, NF-4 |
| Calendar | GST due-date calendar is national; unconfirmed dates show "Check on the GST portal" | Pankaj, D-045 |
| Testing AWS | Emulator first; no real AWS or staging spend without approval | D-075 |
| Approved | Invoice flow: Create invoice primary, inline HSN, Home links | D-097 |
| Proposed, not yet approved | Table 13 in the GSTR-1 JSON (D-099); Ask Kartaa help bot (D-098) | Sections 7.3 and 7.9 |
| Built, off until a vendor exists | GSTIN lookup at sign-up (adapter and fake provider; real vendor pending) | D-100 (GSTIN), #249 |

## 5. Problem, market and users

Small Indian sellers lose hours every period turning scattered bills and marketplace reports into GST returns, and many pay a CA mainly for that data entry. Marketplace sellers download different reports from Amazon, Flipkart and Meesho and must merge them into GSTR-1, including the separate marketplace table (Table 14), then work out GSTR-3B. Traders, wholesalers and shops bill in Excel, Word, basic apps or by hand and pay a CA to rebuild the return.

**Desk-research figures (15 Oct 2026; secondary sources; interviews have not yet been done, so treat as hypotheses).** India has about 1.67 crore active GSTINs. Meesho, Amazon and Flipkart each report lakhs of sellers, with overlap; our estimate is 8 to 15 lakh unique GST-registered marketplace sellers. Marketplace sellers pay a CA about ₹15,000 a year or ₹20,000 to ₹36,000+ a year to reconciliation tools. Billing apps are crowded at roughly ₹3,500 to ₹10,000 a year; one listed player reported a large loss in FY25. We found no tool with a public price that combines own invoicing with marketplace GST preparation, but this is unverified (see the table in section 2). Repotic and eVanik handle marketplace reports; BUSY Recom was named in the October desk research and is not verified here; Zoho Books marketplace coverage is disputed by a competitor and unverified.

| Persona | Example | Main job |
| --- | --- | --- |
| Marketplace seller | One-person brand on Amazon, Flipkart, Meesho | Upload monthly reports, get GSTR-1, GSTR-3B worksheet and deadlines |
| Small business that invoices | Trader, wholesaler, distributor, retail shop | Upload purchases, bill customers, issue credit notes, file from the same data |
| Hybrid seller | Marketplace store plus wholesale side | One combined return per GSTIN from both sources |
| Staff | Billing clerk | Create invoices only |
| CA or accountant | The seller's CA | Review prepared numbers, file on the portal; one CA login can belong to many businesses |

Priority: hybrid sellers first, because no affordable tool serves both; CAs are a channel as well as users. Assumed profile: 1 to 20 users, goods only (services and composition come later), turnover under ₹5 crore so quarterly filing is possible, comfortable on a phone browser, not on accounting software. Planning scale: 10 pilot sellers to Gate B, and 100 only if Gate B passes, each up to 500 invoices and 20,000 marketplace rows a month.

## 6. User journeys

**J1. Sign up and set up (target under 10 minutes to Home).** Email and password, verify a 6-digit code; business name, GSTIN (optional lookup fills name and address; state from GSTIN), address; optional business types (multi-select); platforms sold on (Amazon, Flipkart, Meesho, own invoices); frequency, monthly or quarterly, with the switching window shown; land on Home with a checklist and the next deadline.

**J2. Prepare a return from uploads.** Filing home shows the period and deadlines; open the period; upload each section (every section optional): marketplace reports (zips of reports are sorted by content before staging) and own invoices as Excel, PDF or both; see parsed rows, held rows and PDF versus Excel differences; fix or accept each; build GSTR-1 on screen with checks; enter or confirm Table 13 series; download the GSTR-1 JSON; view the GSTR-3B worksheet; follow the portal guide; mark filed with the ARN and lock the period.

**J3. Quarterly filer (QRMP).** Months 1 and 2: optional IFF for B2B invoices by the 13th; month 3: quarterly GSTR-1 excluding invoices already in IFF, and a GSTR-3B worksheet. PMT-06 is not calculated.

**J4. Bill a customer (target: repeat invoice under 60 seconds).** Home, New invoice; pick or create the customer inline; add products by search, creating a product inline if needed; a missing HSN is fixed on the line; totals come from the server; tap **Create invoice** (shown as **Create practice invoice** while numbering is off); download the PDF or copy the link. Practice invoices never enter the GST return and carry a "not for your customer" label.

**J5. Return from a customer (credit note).** Credit note against an invoice; cannot exceed what was invoiced; own series; falls in the current open period if the original's period is filed. Credit-note finalize is not yet built (D-091).

**J6. Buy stock.** Upload a purchase invoice (PDF, or a photo typed in); review the read lines; confirm; the catalog and stock are built from confirmed lines; set the selling price per 1 unit.

**J7. File from own invoices.** At period end, confirm "all purchase invoices uploaded" and "every invoice is in the portal"; the button opens only after the period has ended and the filing period has started; platform files are asked for if the business also sells on platforms.

**J8. Invite a team member.** The owner or admin sends an invitation link by email (single use, 7 days); the invitee gets one of the four roles.

## 7. Requirements and acceptance criteria

QA tests every acceptance criterion as written. Rows marked **(proposed)** await approval. Rows marked **(carried)** are unchanged from v1.1 to v1.3 apart from clean-up.

### 7.1 Onboarding and account (ON)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| ON-1 | Self sign-up with email | A new user signs up with email and a password and verifies a 6-digit code sent by email; mobile sign-up is not in R1 to R4 (P-5). One email opens only one account. A code is valid for 10 minutes, 5 wrong tries void it, and at most 5 code requests per email and 20 per IP address are allowed per hour. Sign-in is email and password; owners and CAs can turn on an authenticator-app code (built, optional, off by default, because a CA login reaches many businesses). A session ends after 24 hours idle or 30 days, and at once on a password change. Signing up with an existing email gets the same message as a new sign-up, so the response never reveals whether an account exists. |
| ON-2 (revised) | Platforms the business sells on | Onboarding asks which of Amazon, Flipkart, Meesho and "own sales invoices" apply; one or more can be chosen. It is a separate onboarding step, not part of the profile form. Only chosen platforms get upload sections (GF-13). There is no "salon" or other business wording anywhere. |
| ON-3 | Business profile | GSTIN format and check digit are checked, and its first two digits set the state. A state mismatch shows a warning (wording in mock M2). Legal name and address are required before the first invoice PDF or GSTR export. A marketplace-only seller without a GSTIN can enter a PAN-based enrolment number instead (Notification 34/2023). The turnover band is captured per FY; it decides 4- or 6-digit HSN on invoices, whether e-invoicing applies (the ₹5 crore figure and any IRN time limit are statutory claims to be confirmed by the CA; Kartaa does no e-invoicing). |
| ON-4 (revised) | GST filing frequency | Monthly or quarterly, asked in onboarding as its own step, stored with an effective-from period and history as built. The switching-window warnings of v1.1 still show; the app never blocks the choice. |
| ON-6 | Setup checklist on Home | Shows each incomplete step with a link, and disappears when all are done. |
| ON-7 (replaces the greyed field) | Business types | Sign-up and Business setup offer an optional multi-select of Retailer, Wholesaler, Distributor, Manufacturer, Online seller, Service provider, Other. It never blocks any screen, invoice, purchase or filing step (D-095). AC: with no type chosen every feature is reachable; the profile change is audited. |
| ON-8 | Change anytime | The owner can change filing frequency and platforms at any time in Business Setup. A change applies to periods not yet started or not yet paid; it never edits uploaded data or an already generated JSON, and it is audited. Admin changes for another business are by support access only (existing rule). Before any build the screen shows period, GSTIN and platforms for confirmation; a wrong choice is recoverable without data loss (rebuild, never edit uploaded data). |
| ON-9 | GSTIN lookup (built, off) | After a well-formed GSTIN (format and check digit) the sign-up form may fill empty legal name, trade name and address from a lookup; the person can type over or ignore them; nothing from the lookup is stored; no screen says "verified" or "active". Only the 15-character GSTIN is sent, from the server, to a provider that has stated in writing it processes in India (D-094, D-100). Off by default until Pankaj approves a vendor and price. AC: lookup off says nothing; a failure or rate limit shows one plain line and never blocks sign-up; the endpoint is rate-limited per user. |
| ON-10 | What you still do yourself | Landing page, sign-up and the summary page say in one plain sentence that Kartaa prepares and the user or their CA checks and uploads on the GST portal. QA test: the sentence is present on those three screens (UI string test). Pilot measure (not a QA test): at least 8 of 10 interviewees correctly say what Kartaa does and does not do. |

**Roles.** Owner, admin, billing and CA. The server enforces every cell and a test calls every business route as every role (D-089); a role without the permission gets the same "not found" as a non-member.

| Action | Owner | Admin | Billing | CA |
| --- | --- | --- | --- | --- |
| Business settings and invoice prefix | Yes | Yes | No | No |
| Invite, deactivate and reactivate members | Yes | Yes, except owners | No | No |
| Products and customers | Yes | Yes | Yes | View only |
| Create and finalize invoices and credit notes | Yes | Yes | Yes | No |
| Mark an invoice paid | Yes | Yes | Yes | No |
| Upload marketplace reports | Yes | Yes | No | Yes |
| Prepare and export returns, TCS check | Yes | Yes | No | Yes |
| Mark a period filed and lock it | Yes | Yes | No | Yes |
| Unlock a period (reason required) | Yes | No | No | No |
| View the audit log | Yes | Yes | No | No |
| Grant time-limited support access | Yes | No | No | No |

### 7.2 GST Filing (GF), Release 1

Marketplace and own-invoice uploads, the GSTR-1 build and its JSON, and the GSTR-3B worksheet.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| GF-2 | Upload marketplace reports | For each marketplace, the screen names the exact report to download and how. Accepts CSV/XLSX up to 20 MB per file (to confirm against Vaashi's largest report). Large files are processed in the background: the screen shows progress, the seller can leave and come back, and the preview appears when ready. Several files can be dropped at once; the app detects the marketplace from the columns and the seller confirms it. Preview shows rows, errors and totals before anything is saved. Nothing is ever counted twice. The identical file, or the same report downloaded again under a new name, shows "already imported" and adds nothing. A file whose dates overlap an earlier one is matched line by line on order and invoice ID: identical lines are skipped, and changed lines are shown for the seller to accept (audited) or skip. For each marketplace the screen shows a short "how to get this file" guide (menu path, report name, date range) with a picture, reviewed against the seller panel before launch. Measured outcome is "first return completed", not sign-up. The 20 MB limit is checked against the largest real report in the pilot; a larger file is rejected with a plain reason, never truncated. |
| GF-12 | Deadlines confirmed from the GST portal | The filing home shows the GSTR-1 and GSTR-3B deadline for each period for the business's frequency and state group. Every date comes from dated reference data with an official GST-portal source link and a last-checked date, sourced in R1-M0. A date that is not confirmed shows "check on the GST portal" and is never guessed or computed from memory. |
| GF-13 | Per-section optional uploads | Each chosen platform and "own sales invoices" is its own section. Every section is optional: the seller can skip any and still reach the summary. Each section shows its status (not uploaded, processing, ready, rows held). Large files process in the background; the seller can leave and return. The identical file or an overlapping report never counts twice (GF-2 rules apply). Held rows must be resolved or explicitly accepted, and each is traceable to its file and row. |
| GF-14 | Own sales invoices: PDF and/or Excel | The own-invoices section accepts PDF, Excel or both; at least one is required for that section to count as uploaded. A provided Excel template is offered. A file the app cannot read is rejected with a plain reason. PDF reading uses the free text-layer reader (D-054); photos and scans are typed in against the stored file until a picture reader is approved (D-077, D-078). |
| GF-14a | Own-invoice file intake | Besides the Kartaa template, the seller can upload any Excel or CSV sales register (for example an export from Vyapar, myBillBook, Tally or Busy) and map its columns once on a screen; the mapping is saved per business and audited. Rows that cannot be mapped are held with a reason, never guessed (rule 10). Specific app-export readers are built only for sources named by 3 or more interviewees. AC: Vaashi's invoice file (masked if L-0a is not approved) completes mapping in under 10 minutes; a file with a missing required column is rejected with the column named. |
| GF-15 | Cross-verify PDF and Excel | When both are uploaded for the same period, invoices are matched by invoice number. The app highlights every difference: an invoice in one file only, or a mismatch in date, customer GSTIN, taxable value, tax or total. Each difference shows both values and lets the seller fix the data or accept one value; nothing is chosen silently, and the choice is audited. The JSON cannot be generated while a difference is unresolved. |
| GF-16 | Excel-only note | If the seller has uploaded Excel invoices but no PDF invoices for the period, the section shows the note "Upload invoices and we can validate." Once any invoices are uploaded, the note is not shown. |
| GF-17 | GSTR-1 from uploaded rows | The return is built from the rows of every uploaded section with the v1.1 sections and checks (GF-4, GF-5), through the existing section builder. Any case that depends on an open CA answer (CA-2, CA-3, Table 12 netting, b2cs Type E, Flipkart cash-back) is flagged "needs CA check" on screen and in the summary. |
| GF-18 | GSTR-1 JSON export | After payment and when the period has no unresolved blocks, the seller downloads a GSTR-1 JSON in the official GSTN format, which R1-M0 identifies and cites. It is checked against that format, and against the seller's own filed return in the pilot. Wording follows GC-W1; never "filed" or "accepted by the portal" until a seller confirms it uploaded cleanly. Named fixtures: the real tool-exported file structure (`team/research/gstr1-offline-json-structure.md`) and the golden cases in `team/gst/gstr1-examples.md`; the check is `make test` filing golden tests plus the manual portal upload (owner: Pankaj, gate L-2). Each JSON records the source files and the build it came from. |
| GF-19 | Step-by-step portal guide | After payment, a guide shows how to upload the JSON on the GST portal, one step at a time with screenshots or exact menu names, checked against the current portal before launch and re-checked on a schedule. The guide is behind the payment gate. |
| GF-20 | Summary page | Before payment, the last page shows a brief business summary: business name and GSTIN, filing frequency, period, platforms and files uploaded, counts of invoices and held rows, sales and tax totals by head, and "needs CA check" items. It does not reveal the JSON or the guide. |
| GF-8 | Mark as filed and lock | Owner or CA enters the filing date and ARN, and the period locks. The ARN format is checked. Only the owner can unlock, with a reason, for example to fix a wrong ARN. A credit note for a locked period goes into the current open period, and a new upload for a locked period is refused with that explanation. Invoices dated in a locked period can't be cancelled; corrections go to an open period. Every action is in the audit log. |
| GF-4 | GSTR-1 / IFF preparation | Builds the sections a small seller needs: B2B, B2C large, B2C summary by state and rate, credit/debit notes, HSN summary (B2B and B2C split), documents issued, and supplies through each marketplace (with the operator's GSTIN). Quarterly filers get IFF for months 1 and 2 (B2B only), and the quarterly return excludes invoices already in IFF. Section totals match the worked examples in \`team/gst/gstr1-examples.md\`, which the GST expert writes before the HLD and the CA reviews, including a quarter with an IFF invoice left out. Table 14 only discloses supplies already in other tables, so liability totals are identical with and without it. The operator's GSTIN is a seller setting per marketplace and state, because the reports don't carry it. The B2C large threshold is dated config: default ₹1 lakh per Notification 12/2024, though the portal manual still says ₹2.5 lakh (CA to confirm). IFF warns when a month's B2B value passes ₹50 lakh, and after the 13th says those invoices go into the quarterly GSTR-1 (CA to confirm). Table 13 lists our series and the marketplace invoice series issued in the seller's name (CA to confirm). |
| GF-5 | Validation before export | Blocks export on: missing HSN, invalid customer GSTIN, invoice number over 16 characters or with invalid characters, duplicate invoice number in the financial year (ignoring letter case, across our invoices and imported marketplace invoices for the same GSTIN), period already locked. The full list of checks, and which block or only warn, is in the table below. Each error names the row and how to fix it. A marketplace row with a blank HSN is held until the seller enters the HSN once for that SKU; the entry is audited and shown as "entered by you", and a different HSN in a later report wins, with the conflict shown. |

**Checks before export (GF-5).** A block must be fixed; a warning can be accepted by the seller and the acceptance is audited. Check C-08 (Table 13: the portal blocks Generate Summary when Table 13 is empty) is specified under GF-30 and blocks export once built.

| Check | Type |
| --- | --- |
| Missing HSN on a line | Block |
| Customer GSTIN fails format or check digit | Block |
| Invoice number over 16 characters or with characters other than A-Z, 0-9, - and / | Block |
| Duplicate invoice number in the FY, ignoring case, across own and marketplace invoices | Block |
| Missing or unknown state | Block |
| Period already locked | Block |
| B2B rows but no HSN B2B summary | Block |
| Data in any table while Table 13 (documents issued) is empty | Block |
| Uploaded report has columns the app can't read | Block for that file |
| HSN totals differ from the other tables by more than 10% | Warn |
| B2B value in an IFF month over ₹50 lakh | Warn |
| A marketplace ticked in the profile has no report for the period | Warn |
| TCS entered differs from the TCS worked out (GF-11: **deferred, not built in R1 to R4**; row kept for later) | Warn when built |

### 7.3 Table 13, documents issued (GF-30, proposed)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| GF-30 | Table 13 in the GSTR-1 JSON (D-099, proposed) | The portal blocks Generate Summary when Tables 4 to 10, 14 or 15 hold data and Table 13 is empty (portal FAQ and manual). Table 13 is written to the JSON from user-confirmed rows: own series by default; marketplace-issued series opt-in per series and labelled "needs CA check"; practice documents never counted; cancelled counts typed for uploaded series; all 12 slots written, `chksum` omitted until the test upload. A marketplace-only seller must tick a series or enter their own, because the app never guesses. Check C-08 blocks export until rows exist. AC: a return with B2B or B2C data and no Table 13 rows cannot be exported; a practice invoice never appears in any row; JSON keys equal the structure of the real tool-exported file; marketplace series are excluded unless ticked. Full spec: `docs/TABLE13_SPEC.md`. |

### 7.3a Layout drift and platform changes (GF-31)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| GF-31 | Versioned readers and schema watch | Each marketplace reader is versioned and has a fixture per layout version; a file whose columns do not match a known version is held with a plain message, never guessed (rule 10). Before each filing deadline an owner re-checks the portal's offline-tool and JSON schema version and records it. AC: a file with a renamed column is held, not mis-read; the schema check is on the release checklist with a named owner (EM). |
| GF-32 | Period reminders | An email goes to the business owner when a filing period opens and 3 days before the confirmed GSTR-1 due date; where the date is not confirmed it says "check the GST portal". It has an unsubscribe link and an audit entry, and is sent through SES in India (D-094). AC: a test tenant receives both emails once per period and none after unsubscribing. SMS and WhatsApp reminders stay under P-5. |

### 7.4 GSTR-3B worksheet (GF-21 to GF-29)

Built (D-076). While payments are a placeholder (D-074) the gate in GF-29 is open. Rows are otherwise unchanged from v1.3.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| GF-21 | Worksheet per period | One worksheet per filing period, monthly or quarterly as chosen, opened from the filing home beside GSTR-1. It can be built only when that period's GSTR-1 build (GF-17) has no unresolved blocks. Every screen and download says "Worksheet, not a filing". Wording is "numbers to check and enter on the GST portal", never "ready to file", "filed" or "accepted". AC: a UI-string test finds no "filed" or "ready to file" wording for GSTR-3B; the label appears on screen and on every download. What the worksheet is not: it is built from the seller's sales only, with no ITC computation, no net payable and no GSTR-2B ingestion; this is stated in the screen and in any marketing (GSTR-2B ingestion is deferred until interviews justify it). |
| GF-22 | Outward supplies from the same uploads | Table 3.1 and Table 3.2 figures come from exactly the rows and totals of the period's GSTR-1: 3.1(a) taxable outward supplies (B2B, B2C large and B2C summary, net of credit and debit notes), 3.1(c) nil-rated and exempt, 3.1(e) non-GST, and 3.2 inter-state supplies by place of supply, state by state, for unregistered persons, composition dealers and UIN holders, as in the official utility V5.8. 3.1(b) zero-rated shows zero because exports and SEZ are outside Release 1. Which GSTR-1 buckets feed which line, and the netting of notes, is to be confirmed (CA). Every figure drills down to its file and row. AC: on the Jul to Sep pilot sample and every golden case in team/gst/gstr1-examples.md, taxable value and tax by head (IGST, CGST, SGST or UTGST, cess) equal the GSTR-1 totals to the paisa in decimal arithmetic; each figure drills to its source rows. |
| GF-23 | Follows GSTR-1, outward values not editable | Outward figures cannot be typed over in the worksheet. If an upload, a held-row decision or a GSTR-1 figure changes after the worksheet was built, the worksheet shows "out of date" until rebuilt, and the seller's own entries are kept. A note says the portal fills Table 3 from the filed GSTR-1 and that corrections go through GSTR-1 or GSTR-1A (lock scope and start period to be confirmed from the official GSTN advisory). Table 3.1.1 (supplies on which the platform pays tax) shows "check on the GST portal" until the GST expert and CA confirm how goods sold on marketplaces are reported. AC: change a source row and the worksheet is marked out of date; the audit log records the rebuild. |
| GF-24 | Seller-entered figures | The seller can type: ITC by head for Table 4 (available rows 1 to 5, reversed rows 1 and 2, other and ineligible rows 1 and 2, as in utility V5.8; net ITC is shown as available minus reversed), copied from GSTR-2B on the portal; reverse-charge inward supplies (3.1(d)); exempt, nil and non-GST inward supplies (Table 5); and interest (Table 5.1). As in the utility, CGST is typed once and SGST copies it, and unequal input is refused. Every field is optional, in rupees with two decimals, not negative, labelled "entered by you", with a hint to copy it from the portal. Each change is audited (who, when, old and new value). The app never computes or checks ITC, reverse charge, interest or late fee in Release 1. A late-fee note, if shown, is information only, after official check. Row labels follow utility V5.8 and are re-checked against the portal form before launch. AC: values round-trip exactly; negative input is refused with a reason; audit entries exist for each edit; no field in this table is pre-filled by the app. |
| GF-25 | Totals and no offset | The worksheet shows output tax by head and the ITC the seller entered, side by side, and the line "Offset and payment are done on the GST portal". It shows no net-payable figure in Release 1, because the order of using ITC across heads has not been confirmed (a later release can add it after the CA confirms). AC: no net cash payable value appears anywhere in the worksheet or its downloads. |
| GF-26 | Frequency and quarters | A monthly filer gets a worksheet per month. A quarterly filer gets one worksheet per quarter showing quarter totals, with invoices already reported in IFF counted once and never twice. Whether the portal fills the quarter's Table 3 from GSTR-1 plus IFF is to be confirmed, and so is how a quarter is entered, because the official utility takes months only. The GSTR-3B due date comes from the same confirmed reference data as GF-12 and shows "check on the GST portal" when not confirmed. PMT-06 amounts for months 1 and 2 are not calculated in Release 1. AC: a quarter with an IFF invoice gives the same quarter total as the GSTR-1 build; a change of filing frequency never rewrites an existing worksheet (ON-8). |
| GF-27 | View and download | The worksheet is shown on screen and downloads as Excel and PDF, laid out in the order of the portal form so the seller can compare it section by section. Each download carries the source-file list, the build version, the time generated and the "worksheet, not a filing" label. A GSTR-3B JSON for the offline utility is not part of Release 1 (it can follow once a real exported file exists as a fixture; see the open items). AC: downloaded values equal the screen; amounts show two decimals; tenant scoping and authorization are tested as for the GSTR-1 JSON. |
| GF-28 | Flags and checks | The "needs CA check" flags of GF-17 carry over wherever they affect a worksheet figure, and anything resting on a "to be confirmed" rule above carries the same flag. The worksheet checks that Table 3.2 does not exceed Table 3.1(a), as the offline utility does (to be confirmed), and shows a warning, not a block. The flag count appears on the summary page (GF-20). AC: each open CA item that touches a figure is flagged on that figure and counted in the summary. |
| GF-29 | Plan and payment gate | The worksheet is part of the Release 1 plan (BL-1) at no extra price and sits behind the same payment gate as the GSTR-1 JSON (BL-2): before payment the summary says the worksheet exists but shows no figures; after payment it is viewable and downloadable. Payment status is checked on the server for every view and download. This is the Product Owner's reading; Pankaj can change it. AC: an unpaid tenant gets no worksheet figures from the screen or the API. |
### 7.5 Business Hub: purchases, catalog, stock and sales invoices (Release 2, built)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| PU-1 | Purchase invoice upload and review | A PDF purchase invoice is read by the free text-layer reader; a photo or scan gets a blank draft the user types against the stored file (no picture reader is on). Nothing is confirmed until the user reviews it; a draft is decided once; an invoice is unique per supplier GSTIN, FY and number. Product name is typed on review. AC: no write to catalog or stock before confirm; duplicate supplier invoice refused; fields the reader cannot read are blank and named, never guessed (D-084, D-054). |
| CS-1 | Catalog from confirmed purchases | Confirmed lines create products; a product with no selling price is marked "price needed" until the business sets a price per 1 unit. HSN may be blank when adding a product but is needed before the product can go on a tax invoice. The app never suggests an HSN or GST rate. A rate carries a valid-from date and history; the owner or admin can tick "Confirmed with CA", an unticked rate warns and never blocks. |
| CS-2 | Stock ledger | Stock is an insert-only ledger of signed movements (purchase in, sale out, adjustment with a reason, reversal); the balance is the sum; no stored balance; update and delete are refused by the database. Stock never blocks a sale; "no stock" and "low stock" are warnings. Unit cost is stored but no costing or profit figure is shown (costing policy needs approval). AC: balance equals the sum of movements; a failed finalize leaves no movement (D-081, D-082). |
| SI-1 | Create invoice is the primary action (D-097, approved) | The invoice screen's main button is Create invoice (Create practice invoice while numbering is off), beside the totals and sticky on phone. It saves and finalizes in one request with one idempotency key; Save draft is secondary. AC: a double press creates one invoice; works from an unsaved form; stock never blocks it. |
| SI-2 | Missing HSN fixed on the line (D-097) | A product with no HSN can be added to an invoice. The line shows an HSN box; saving a valid HSN updates the product and enables Create; the server still refuses a finalize with a blank HSN where the rule requires it, and we never choose a code. **Relief (#344, merged as #367, D-101, `docs/HSN_B2C_RELIEF.md`):** a blank or short HSN is a warning, not a block, when the buyer has no GSTIN and last FY's turnover band says the seller is up to ₹5 crore (Notification 78/2020-CT, per the CA expert reading; CA to confirm); it still blocks for a buyer with a GSTIN, a seller above the limit, or an unset band. Finalize stores an empty HSN as it was; the GSTR-1 build keeps check C-01. |
| SI-3 | Inline customer and product | A new customer or product is created on the invoice screen without leaving it. |
| SI-4 | Preview PDF | Five states: idle, preparing, ready, slow (over 30 seconds, offers retry), session ended (keeps the draft; Sign in again returns to the same invoice and restarts the preview). Preview never blocks Create. |
| SI-5 | Home links | New invoice (primary), Products, Customers and Invoices are one click from Home and in the top bar, visible without scrolling at 1366x768 and at 360 px. |
| SI-6 | Finalize, practice mode and PDF | Finalize is one atomic, retry-safe step: number allocated with no gaps or duplicates, values snapshotted, stock out written in the same transaction. While live numbering is off every invoice takes a PR- number, never enters GST Filing, and its PDF is marked as a practice document, built only from stored finalize data (D-083, D-044). Finalized invoices are never edited or deleted. A live-numbered invoice is assigned to its return at finalize (D-091, shipped off). |
| SI-7 | Issued invoice page (#328) | The page shows buyer and ship-to as snapshotted, place of supply, every line with its stored tax split, discount, charge, cess, round-off and amount in words; the page computes nothing. |
| SI-8 | Marketplace place of supply (#345; D-102, `docs/MARKETPLACE_POS.md`; #368 in review for the Amazon B2B reader, #369 for the held-row web screen) | For marketplace rows take the place of supply from Ship To only when Bill To and Ship To are in the same state; otherwise hold the row for review rather than guess (first built for Amazon B2B rows). The CA default before this change was Ship To (CA-4). AC: a differing-state row is held, shown in the upload summary and the worksheet, released only by an audited user decision. |
| SI-9 | Credit notes | Credit note against an invoice, own series, cannot exceed the remaining invoiced quantity or value, keeps the original rate and place of supply; after the section 34(2) deadline it is blocked unless the owner overrides with a reason (CA to confirm). Finalize of credit notes is not yet built (D-091). |
| SI-10 | Monthly and quarterly files (D-085) | For a finished month, or a finished quarter of a quarterly filer, an Excel workbook (Summary, Sales, Purchases, and a Practice sheet kept apart and in no total) and a purchase-register JSON in our own plain format, not a portal file. Same data asked twice returns the same export; changed data makes a new one and keeps the old. No GSTR-3B JSON. |
| SI-11 | Deferred | Invoice sharing by link, WhatsApp and email sending, e-way bill details, part payments, receivables ageing, reminders, batch and expiry, multiple warehouses, services (SAC) and composition scheme, exports and SEZ, reverse charge, and tax-inclusive (MRP) pricing (CA-5) are not in R1 to R4. |

### 7.6 Filing from our own invoices (Release 3, built)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| PG-1 | Per-period gate | For a month, or a quarter for a quarterly filer, the business confirms "all purchase invoices uploaded" and "every invoice is in the portal". Each confirmation is stored against a fingerprint of the period's rows and goes stale when they change. The gate applies once the business has an own invoice, finalized or practice (D-095). |
| PG-2 | File button | Opens only when the period has ended and the filing period has started, and both confirmations stand; the server refuses otherwise (`period_gate_closed`). A due date shows only when its refdata row is confirmed. |
| PG-3 | Platform files | A business that also sells on a marketplace must provide each platform's files for the period, or a no-sales note, before filing (D-088). |
| PG-4 | Return assignment and lock | A live invoice is assigned once to the return covering its date; a filed return refuses a new document with `period_locked` (D-091, D-034 interim, CA-1 open). |

### 7.7 Team by invitation and the CA (Release 4 built; CAH-1 and CAH-2 to build)

Per P-1, TM-1, TM-2, TM-3, CAH-1 and CAH-2 stay **in the launch criteria** because the CA channel is part of the wedge; the rest of R2 to R4 does not.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| TM-1 | Invitation links | The owner or admin sends an invitation link by email; the token is hashed, single use, expires in 7 days and must match the invitee's email; it reaches no log, audit row or stored column (tested). One CA login can belong to many businesses; removal never deletes the CA's own login. Deactivation and reactivation need a reason and are audited; the last owner cannot be removed. |
| TM-2 | Four fixed roles | Owner, admin, billing, CA per the role table; the admin picks one (D4 option (a)). Per-person custom permissions are not built. |
| CAH-1 | CA home (not built) | A signed-in CA belonging to several businesses has one screen listing each client business with its current period status (not started, uploaded, held rows, built, exported, filed) and the count of "needs CA check" items. AC: a CA with 5 clients sees all 5 and their statuses on one screen; tenant isolation is tested so a CA sees only businesses that granted access (NF-1). Not included until three pilot CAs ask: bulk download, partner pricing, CA-pays billing. |
| CAH-2 | CA-initiated client invite (not built) | A CA can send a prospective client a link that asks the client to add the CA; the client's owner accepts and chooses the role (CA). The CA gains no access until the owner accepts. AC: an unaccepted request exposes nothing; acceptance is audited; the link is single use and expires in 7 days (same rules as TM-1). |
| TM-3 | Permission tests | Every business route declares one permission; a test fails if one does not (D-089). |

### 7.8 Plans and payment (BL)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| BL-1 | Release 1 plan and price | One plan, GST filing only: ₹499 per month or ₹1,499 per quarter, plus 18% GST on our fee. The seller sees the plan matching their filing frequency and can choose the other period. The price is a hypothesis to validate in the pilot interviews (no willingness-to-pay data yet); alternatives tested there: ₹299 a month, per return, annual. |
| BL-2 | Payment gate | No trial and no upfront charge. The seller uploads, sees the summary, and pays on the final page; payment unlocks the guide and JSON. The sign-up page and the summary state this order before the seller uploads anything. The pilot is free with no gate. Payment status is checked on the server for every download. A failed or abandoned payment leaves the uploads intact. The payment provider is decision D3. In the pilot the gate is off: GF-18, GF-19 and GF-29 are open to every pilot seller (D-074 free for now). |
| BL-3 | Cancellation and plan change | No refunds on cancel; the service runs to the end of the paid period (approved). See proposal P-2 for a first-period guarantee when a figure is confirmed wrong. A plan change shows prorated rates before the seller confirms. Our own GST registration and tax invoices for these fees are decision D6; the app does not claim to issue GST invoices for its fee until D6 is settled. |
| BL-4 | Invoicing plan (built, free for now) | ₹999 per month or ₹2,499 per quarter plus 18% GST on our fee, GST filing support included. The first 10 finalized invoices (practice ones counted, because every invoice is practice while numbering is off) are free; the server refuses the 11th with `invoice_plan_required` and takes no number. While `FREE_FOR_NOW` is true nothing is refused (D-086, D-074). Per P-1 this plan is not sold or shown to new customers while live numbering is off; the code and counter stay. (P-1 is a proposal; this is provisionally in force until Pankaj decides.) |

### 7.9 Ask Kartaa help bot (AK, proposed, no code yet; not in launch criteria)

At launch a static FAQ page replaces the bot (SP-1). The bot is built only after the pilot shows what users ask.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| AK-1 | Floating help button | A button on every signed-in screen opens a box; the answer is at most about 3 sentences (60 words) about how the GST portal works (from the GST Portal Tutorial pack) or how to use Kartaa (our own help text), with a link to the portal's own page when the answer is long. |
| AK-2 | Safe by design | No tenant data goes into or out of the bot; it does not know the user's GSTIN, invoices or plan; no tax or legal advice; says plainly when it does not know; any figure or date appears only with its retrieved source and a "check the portal" note, because the pack contains stale lines (for example the B2C-large threshold). Route is business-scoped, server-checked, rate-limited, flag-controlled. |
| AK-3 | India only, no new service | Search runs in the app with an in-memory index; any model call goes only to an in-region Bedrock model in Mumbai or Hyderabad through the pinned client. Extractive answers first; generative only after a paid-service approval (recommended cap about USD 10 a month) and a console check. |
| AK-4 | Content terms | The bot stays off for customers until Pankaj confirms we may reuse GST portal tutorial text. The tutorial corpus is never committed to the repository. See `docs/ASK_BOT.md` (D-098, proposed). |

### 7.10 Insights

Not in Release 1 to 4 except what the filing home and Home show: deadlines, checklist and held rows. Sales trend, top products, low-stock and customer insights (AI-1 to AI-10 in the archive) are deferred; generative questions about a business's data need a model, cost and privacy decision first.

### 7.11 Support, terms and privacy (SP, LG)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| SP-1 | Support | A published support address and WhatsApp or phone number, a stated response time, a named weekly owner, and a static FAQ page at launch. Pankaj supplies the contact. AC: every screen footer shows it; a test message gets a reply inside the stated time during the pilot. |
| LG-1 | Terms and disclaimer | Terms of service with a liability limit and the line "prepared for you or your CA to check and upload; not filed, not tax advice", reviewed by a lawyer before launch. The BRD states no statutory requirement until the lawyer confirms. |
| LG-2 | Privacy and consent (includes interview recordings) | A privacy notice, consent at sign-up for the data used, a grievance contact and a breach process. Whether and how India's data protection law applies to Kartaa is **unverified**; lawyer to confirm. D-094 covers where data lives, not consent. Interview recordings need written consent and are stored only in India (D-094). |
| LG-3 | Wrong-figure report | Any figure has a "report a wrong figure" action that records the figure, period and rows, and reaches support. A confirmed error caused by Kartaa is handled under the policy in P-2. The record keeps figure, period and parsed row identifiers, not raw files, so it works after the 90-day raw-file deletion (NF-4). |
| SP-2 | Plain words | Screens and help use plain words: "held row" is shown as "a row we could not read safely, set aside for you to fix"; "needs CA check" as "ask your CA about this". A glossary page lists each term. AC: no user-facing screen shows an unexplained internal term (review by the PO before launch). |

## 8. GST and compliance principles

The GST expert's requirements (GC-1 to GC-28, `team/gst/brd-section-gst-compliance.md`) stay part of this BRD. Six principles apply to every feature. The answers from the GST CA expert (v1 to v4) and the GST portal expert come from AI readers of government documents, not a registered CA: every item they settled is "documented, not human-signed" until Pankaj's CA confirms it.

| ID | Principle |
| --- | --- |
| GC-P1 | The app prepares returns; the seller or CA files on the GST portal. The app never says a return is "filed", "compliant", "accepted" or "ready to file". |
| GC-W1 | One wording set everywhere (screens, downloads, emails, help): "prepared for you or your CA to check and upload on the GST portal". Never "filed", "compliant", "accepted by the portal" or "ready to file". A UI-string test enforces the banned words for GSTR-1, GSTR-3B and Table 13 screens. The JSON and worksheet carry the banner "Pilot: figures not yet checked by a registered CA" until the reviewing CA has reviewed that return, or until the section 10 accuracy metric has passed (0 differences for 3 periods of at least 3 sellers; not merely until L-1, which covers the golden cases only). |
| GC-P2 | No tax rate, threshold, due date or format is hard-coded. Each is dated reference data with its source and a last-checked date. |
| GC-P3 | The app never guesses a GST rate or HSN from a product name. A person enters and verifies each rate, with a rate history. |
| GC-P4 | Finalized invoices, credit notes and filed periods are never edited or deleted. Corrections are credit notes, cancellations or amendments, each audited. |
| GC-P5 | Marketplace invoices are the seller's own supplies. The app imports them as external invoices, never re-issues them, and includes them in returns and numbering checks. |
| GC-P6 | GSTINs are checked for format and checksum only. The app never calls a GSTIN "verified" or "active" without a portal lookup. |

**Settled from official documents (human CA still to confirm).** B2C-large limit is ₹2.5 lakh up to the July 2024 return period and ₹1 lakh from August 2024, chosen by the **return period being built** (merged, #363); marketplace B2C small sales go in b2cs with Type E and the operator GSTIN, own non-marketplace B2C uses OE (template reading, medium confidence); Table 12 has B2B and B2C tabs from May 2025, B2B tab needed if other B2B data exists, 10% tolerance warning; Table 13 is compulsory when Tables 4 to 10, 14 or 15 have data; HSN digits are at least 4 up to ₹5 crore turnover, 6 above; invoice number max 16 characters of letters, digits, hyphen and slash.

## 9. Non-functional requirements

| ID | Area | Requirement |
| --- | --- | --- |
| NF-1 | Data isolation | A business never sees another's data. Every request is checked on the server. Guessing another business's invoice or file ID returns "not found", and a test proves it for every screen and export. Our own support staff can't see a business's data unless the owner grants time-limited access (24 hours by default), and every view shows in that business's audit log. |
| NF-2 | Money accuracy | All amounts use decimal arithmetic, rounded to paise as specified. Totals are reproducible from source rows and invoices. |
| NF-3 | Audit and immutability | Finalized invoices, credit notes and locked periods are never edited or deleted. Who did what and when is logged for sign-up, finalize, credit notes, lock and unlock, settings, member invite, deactivate and reactivate, share-link creation, and exports or downloads of GST files. Owner and admin can read the log. Overrides, unlocks and deactivations need a reason, and a blank reason is refused. |
| NF-4 | Safe uploads | Size and type limits. Spreadsheet formulas are neutralised. Retries and re-uploads never double count. Raw files are stored encrypted and private and deleted 90 days after upload. Parsed rows (personal columns removed), file name and checksum are kept with the GST records, so every figure still traces to its file and row. Decided by the CEO, 24 Oct; CA to confirm against the 72-month rule (GC-27). Raw files deleted at 90 days: disputes are handled from the kept parsed rows and checksums; a seller who needs a file longer re-uploads. |
| NF-5 | Privacy | Marketplace buyer names, phones and addresses are not stored beyond what the return needs: state and PIN for B2C rows, plus buyer GSTIN and legal name for B2B rows only (GSTR-1 Table 4). The raw file holding them is deleted after 90 days (NF-4). No real customer data in development or tests. |
| NF-6 | Performance | Warm pages load within 2 seconds at p95 on a 4G phone; the first request after idle may take up to 3 seconds. A 10,000-row report previews within 30 seconds of upload finishing, processed in the background with a progress state (GF-2). Finalizing an invoice takes under 2 seconds. Measured with a synthetic 4G-throttled browser test against staging (Playwright, owner QA), 20 runs, p95 reported; cold-start mitigation (provisioned concurrency or a warm ping) is written down in the tech plan, or the 3-second first-request allowance is accepted. |
| NF-7 | Responsive and accessible web | Every screen works at 360 px width: the page never scrolls sideways, invoice lines become stacked cards, and wide return tables scroll inside their own box with the first column fixed. WCAG 2.1 AA contrast and keyboard use. Indian number format (₹1,23,456.00) and DD-MMM-YYYY dates. |
| NF-8 | Reliability | At most 24 hours of data lost and service back within 8 hours after a failure. Backups are encrypted and kept 35 days, and a restore is tested before launch and every quarter. A failed upload or finalize leaves nothing half-saved. |
| NF-9 | Tax-content governance | Rates, thresholds, due dates and form layouts live in dated, cited data, not code. A change needs GST expert review. The UI never claims compliance. |
| NF-10 | Platforms | Web first (current Chrome, Safari, Edge; Android Chrome). The design and APIs must allow Android and iOS apps later without rework. There is no offline mode and no installable app in R1 to R4 (P-5 records the option). |
| NF-11 | Cost | Fits the approved AWS budget for a small user base. No paid third-party service without approval. Cost per tenant per month (Lambda, RDS, SES, storage, support time) is measured in the pilot and compared with the ₹499 price; stop rule in section 10. |
| NF-12 | Account closure | The owner gets a full export first and login is disabled at once. GST records are archived for the 72-month period (GC-27) and then deleted; other personal data is deleted within 30 days, and from backups as they expire (up to the 35-day backup window of NF-8). |
| NF-14 | India-only data | Tenant data, invoices, GST data, uploaded files, backups and logs holding them are stored and processed only in AWS Mumbai or Hyderabad; no cross-region copy, global inference profile or third-party service receiving tenant data unless it processes in India (D-094, D-096). Real tenant data never goes to GitHub, CI, AI sessions or shared project files; only masked synthetic fixtures. |
| NF-15 | Sessions and passwords | Access token 5 minutes, session 30 days, ended after 24 hours idle and at once on a password change; one active session per user (a second sign-in asks to replace the live one; live means used in the last 30 minutes); password at least 10 characters with upper, lower, digit and special (D-028, D-061, D-092, D-093). Shared logins are not supported: each CA and member has their own sign-in; whether concurrent CA sessions are needed is an open question (OQ-CA-1). |
| NF-17 | CA sign-off gate | No pilot seller (an external user) and no paid plan until a named, registered CA has signed the golden GSTR-1, GSTR-3B and Table 13 cases in writing, recorded in `docs/DECISIONS.md` (gate L-1). "Reviewed by" appears in the product only with that CA's written consent. |
| NF-18 | Language readiness | All user-facing strings are externalised from now so Hindi and a regional language can be added without code change. The Hindi scope (filing guide first) is decided from pilot interviews, not committed. |
| NF-16 | Local demo | The product runs end to end locally with `./demo.sh`, with no real AWS and no payment (D-075). The demo has no PDF renderer. |

NF-13 Usage events: the product records the events the success metrics need (sign-up steps, first invoice, first upload, export, period locked) with a timestamp and business ID, and no personal data or amounts. The tech plan picks where they are stored.

Security-critical requirements, where QA's merge block applies: ON-1, TM-1 and the role table, NF-1, NF-3, NF-4, NF-5, NF-12 and NF-14.

## 10. Success metrics, launch gates and kill rules

Targets are counts, because the pilot has about 10 sellers and percentages would mean nothing.

| Metric | Target in the pilot | How measured |
| --- | --- | --- |
| First return completed | 7 of 10 pilot sellers reach a GSTR-1 JSON | Event log |
| Time to first value | Median under 10 minutes from sign-up to Home; first upload parsed in the same session | Event timestamps |
| Return accuracy | 0 differences between our GSTR-1 and what the reviewing CA files, for 3 periods of at least 3 sellers (at least 2 marketplaces among them); every difference explained in writing. Procedure: the sample is prepared blind: the reviewing CA (or the seller's own CA by their normal method, with Kartaa run in parallel) prepares and files from the source documents before seeing Kartaa's output; the diff is done afterwards by a named human, table by table, rate by rate and state by state to the paisa. The CA comparison uses real seller figures, so it runs only in the India-region tenant environment or on a named person's device in India, is never committed or pasted into an AI session or shared project file, only anonymised difference descriptions leave it, the sheet is deleted on the raw-file schedule (NF-4), and seller consent (LG-2) names the CA comparison; before L-4 it runs on masked data only. Reviewing a Kartaa return for reliance applies only to returns outside the sample | CA comparison sheet (India-only storage) |
| Prep time saved | At least 5 of 10 sellers report 50% less time per return | Interviews |
| Second period | 5 of 10 file a second period in the app, reported with and without a reminder email (GF-32) | Account data |
| Willingness to pay | At least 5 of 10 say they would pay the tested price; alternatives ₹299, per return and annual are also tested | Interviews |
| Explained correctly | At least 8 of 10 interviewees say what Kartaa does and does not do (ON-10) | Interviews |
| CA channel | At least 3 named CAs bring at least 5 client businesses in total | Account data |
| Trust | No data-isolation incident; no wrong-figure report left unanswered beyond the support time | Monitoring, support log |
| Cost per tenant | Measured monthly against the ₹499 price (NF-11) | AWS bills, support time |

**Two decision points (Pankaj sets the values; these are recommended).**

- **Gate A, week 4, before any pilot seller, interview and concierge based.** Proceed only if all hold: at least 8 of the 15 interviewees would pay at a tested price; at least 8 of the 15 are outside Pankaj's circle and at least 4 sell on two or more marketplaces; at least 5 CA conversations held and at least 3 CAs willing to try it; the concierge diff has zero unexplained differences (if L-0a is not approved the baseline is the CA's independent preparation of the masked case and the golden cases); every interview records the seller's current method, what they pay for it, and which tool or file their sales bills come from and whether it exports (more than 5 of 15 whose source is covered by neither the template nor column mapping, GF-14a, means revisit before the pilot; app-specific readers only for sources named by 3 or more interviewees), and at least 6 of the 15 say they would use Kartaa instead of that method after seeing a masked concierge output (this tests the wedge, not only price); and at least 8 of the 15 say they would use a GSTR-3B sales worksheet without ITC (if fewer, revisit GSTR-2B ingestion before going on). Otherwise stop or reposition.
- **Gate B, run when the third monthly period's CA diff is complete: not before week 18 and no later than week 22 (the pilot starts in week 6; returns for periods a pilot seller already filed before joining may be back-tested and count toward the three).** Stop or reposition if: fewer than 3 of 10 file a second period; or fewer than 5 of 10 would pay at any tested price; or marginal cost per tenant exceeds one third of the price; or the reviewing CA finds systematic errors we cannot fix in two cycles; or no CA has brought a client; or Pankaj's recorded spend or time cap is reached. **Real payment:** once L-5 holds, pilot sellers are asked to pay for their next period, and at least 3 of 10 must make a real first payment (fewer than 3 paying at the tested price while L-5 holds is a stop-or-reposition item); if L-5 does not hold by Gate B, Gate B records "payment unproven" and L-6 allows only a paid soft launch capped at 20 sellers. Quarterly (QRMP) filers are counted in the second-period and willingness metrics but not in the three-period accuracy test, which uses monthly filers only. Gate B also records the intended channel for sellers 11 to 100 (CA referrals first; other channels only if Gate B passes). Cost per tenant is reported two ways: marginal (AWS and SES) and fully loaded (including support time).
- **Pilot safety rule.** During the pilot no seller relies on a Kartaa figure until the reviewing CA has reviewed it, or the seller files by their normal method and Kartaa runs in parallel.

**Gates.** Before Gate A: L-0a, L-0, L-1, L-2 and 3a items 1 to 5, 10 and 11 (no paid infrastructure or legal spend yet beyond the CA fee and the spend cap). After Gate A and before the first seller: L-3, L-4 and 3a items 6 to 8 and 12; those costs are therefore not spent if Gate A fails. L-5 (payments) must hold before any money is taken. L-6 (go public) and Gate B must hold before public launch. Owners are in 10a.

- [ ] **L-0a Real-data approval:** before any real tenant data (such as Vaashi's filed period) enters the product, Pankaj records approval stating where it runs (his own machine or the local demo, in India, no AWS and no AI session), who may see it (never an AI session or AI role; named humans only),  consent from the data owner (interviews use a simple written consent form with India-only storage, pending the lawyer-reviewed text in L-3), and when it is deleted. If not approved, the concierge runs on masked data only.
- [ ] **L-0 Validation (Gate A):** 15 recorded seller interviews (each recording the seller's current method and cost, and a switching question after a masked concierge output; consent and India-only storage per LG-2), 5 CA conversations on who pays and what they need, one concierge filing, and the competitor teardown of section 2 with every row verified or marked unverified. Pass thresholds are in Gate A.
- [ ] **L-1 CA sign-off:** a named, registered CA signs the golden GSTR-1, GSTR-3B and Table 13 cases and answers CA-1 to CA-5 in writing; recorded in `docs/DECISIONS.md` (NF-17). The CA's fee and review capacity are budgeted: scope states how many pilot returns (about 30) the reviewing CAs will review and at what fee.
- [ ] **L-2 Portal test:** D-099 approved and #353 merged (Table 13 is in the JSON), then one test GSTR-1 upload on the GST portal succeeds (sets `gstr1.portal_file.verified` only if accepted). Safeguards: use a period already filed or not yet open for the test GSTIN (or a dedicated test GSTIN if lawfully available); never press Generate Summary, Submit or File; delete or reset the draft afterwards and record it in DECISIONS; the CA confirms the procedure first (CA to confirm whether portal drafts can be safely reset). The uploaded file contains only masked or synthetic data (NF-14) unless L-0a covers it.
- [ ] **L-3 Legal and support:** lawyer-reviewed terms and privacy notice (LG-1, LG-2); support contact and response time live (SP-1).
- [ ] **L-4 Infrastructure:** real AWS staging approved by Pankaj (Lambda limit, paid plan before 2027-01-25), domain, SES production access; UAT scripts for the launch journeys pass on staging; tenant isolation tests pass; a backup restore is tested.
- [ ] **L-5 Payments:** payment provider and our own GST registration and invoicing arrangement (D3, D6), plus the lawyer's review of the refund policy (P-2). Until L-5 holds **the pilot is free for every seller and no money is collected, by any method.** This also applies to the first three sellers.
- [ ] **L-6 Approval:** Pankaj approves going public.

## 10a. First 10 sellers and weeks 0 to 22

Pankaj is on every gate, so each step also names a backup. Dates are set by Pankaj; the order is the recommendation. EM assigns the 3a build items in parallel from week 0.

| Week | Step | Owner | Backup |
| --- | --- | --- | --- |
| 0 | Engage a named CA under a written scope and fee (L-1); approve D-099 (Table 13); decide P-7 (or CAH-1 ships only with it); record the spend or time cap and the L-0a approval in DECISIONS | Pankaj | EM drafts the scope |
| 0 to 3 | Build 3a items 1 to 5, 10 and 11; EM assigns owners and weeks at week 0 | EM and engineers | Lead |
| 1 | Concierge filing on Vaashi's period under L-0a (masked if not approved); real figures handled only by Pankaj and a named human, never in an AI session | Pankaj, named human | Pankaj |
| 1 to 4 | 15 seller interviews and 5 CA conversations; the CA signs or answers the golden cases (L-1) | Pankaj, PO | PO |
| 3 | After #353 merges: test portal upload with Pankaj's own GSTIN (L-2). If the portal rejects it, fix and retry; Gate A slips one week at a time, at most 4 weeks; beyond that the plan stops and Pankaj decides whether to continue or stop | Pankaj | none (only he can) |
| 3 to 4 | Pre-Gate-A checklist: L-0a, L-0, L-1, L-2 and build items 1 to 5, 10, 11 confirmed done, in writing | EM | PO |
| 4 | **Gate A.** If it fails, stop or reposition and spend nothing further | Pankaj | CEO role |
| 4 to 6 | After Gate A: lawyer review of terms, privacy and refund policy (L-3); support contact and FAQ live; L-4 work (approve real AWS staging, SES production access, UAT scripts, isolation tests, restore test); build items 6 to 8; pilot-entry checklist for L-3, L-4 and these items confirmed in writing | Pankaj approves; EM runs; PO | Staff engineer, PO |
| 6 (target; the pilot starts when the written checklist is complete) | Invite the first sellers (free) | Pankaj | CEO role |
| 6 to 22 | Pilot: three monthly filing periods, the reviewing CA reviews each return before a seller relies on it | Pankaj, CA, EM | EM |
| in parallel, target week 14, before any payment test | L-5: payment provider, our own GST registration, lawyer review of the refund policy | Pankaj, CA, lawyer | none |
| 18 to 22 | **Gate B** (when the third period's CA diff is complete) against the metrics and kill rules; L-6 (go public) approved only after Gate B and L-5 | Pankaj | CEO role |

**First 10 mix:** Vaashi (1); up to 4 from Pankaj's contacts; up to 5 who are clients of 3 pilot CAs. At least 5 are outside Pankaj's circle and at least 2 sell on two or more marketplaces (hybrid sellers; own invoices come in R1 and marketplace files in R1, so the hybrid return is an R1 feature). Founder-led onboarding: a screen-share call where the founder helps upload the first report. Free for everyone until L-5; willingness to pay is measured by stated intent at a tested price plus a written non-binding "I would subscribe at ₹X" note, and real payment is tested only after L-5.

## 11. Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Marketplace report layouts or the portal JSON schema change | Uploads fail or misread; every user breaks at once | Versioned readers, unknown-layout holds, pre-deadline schema check (GF-31) |
| Wrong tax treatment in a prepared return | Penalties, loss of trust, liability | CA review gate (L-1), GC-W1 wording, golden tests, test portal upload, terms with a liability limit (LG-1), wrong-figure report (LG-3) |
| Rules differ between law text and portal | Export rejected | Dated refdata chosen by return period; re-check before each release |
| Competitors already export GSTR-1 JSON (verified for four vendors) | No reason to switch | Test the reconciled-return wedge in L-0; kill rule |
| AI readers of government documents mistaken for a CA | Wrong defaults shipped as settled | Labelled "not human-signed" until L-1 |
| Practice-only invoicing cannot support the invoicing plan | Selling something unusable | P-1: do not sell R2 to R4 until the CA settles numbering |
| One founder on every launch step | Slow or stalled launch | 10a owners and backups |
| Data protection and liability exposure | Legal claims | LG-1, LG-2 lawyer review; D-094 India-only data |
| Unit economics unproven | Losses at ₹499 | Cost per tenant metric and stop rule |
| Sellers expect one-click filing | Lower adoption | ON-10 plain statement; GSP filing remains a later option |
| Data breach | Severe | Server-side tenant scoping, role tests, encryption, no real data in tests |

## 12. Council-driven proposals (recommendations; not approved)

Council advice that would change an approved decision is listed here with a recommendation and the cost of leaving it. Nothing in this section is applied to the requirements above except where marked "applied as a note".

| ID | Proposal | Decision it touches | Recommendation | Cost of leaving it | Needs Pankaj |
| --- | --- | --- | --- | --- | --- |
| P-1 | Launch only R1 (marketplace and own-invoice GSTR-1 and 3B preparation); R2 to R4 built but unsold and out of launch criteria; do not sell the invoicing plan while numbering is off | Release plan v2 order (R1 to R4), BL-4 | Adopt | Months of polish and a ₹999 plan that sells practice invoices (applied as a note in sections 2, 3, 7.8) | Yes |
| P-2 | First paid period refundable if a figure is confirmed wrong, meaning the named CA (or the support owner with the CA's written view) confirms the error was Kartaa's; refund is that period's fee only; Kartaa does not indemnify penalties or interest, and the liability cap is set in LG-1 after lawyer review; "no refunds" limited to change of mind after the first period | BL-3 "no refunds" | Adopt, after a lawyer reviews the terms | Conversion loss; liability exposure | Yes |
| P-3 | Test ₹299, per-return and annual prices in interviews; keep ₹499 and ₹999 until evidence | Pricing | Keep price, test alternatives | A wrong price is found only at the pilot check | No, unless a price changes |
| P-4 | WhatsApp click-to-share link for an issued invoice page (wa.me link, no WhatsApp Business API) | SI-11 deferral | Defer until invoicing is sold | Gap against billing apps if invoicing launches | If pilot asks |
| P-5 | PWA and offline, mobile OTP sign-in, deadline reminders by SMS or WhatsApp | Web only for R1 to R4, email sign-up | Defer; test OTP demand in interviews | Shop owners without email may not sign up | If interviews show demand |
| P-6 | Allow concurrent sessions for CA logins | One active session per user (D-092) | Keep; revisit if CAs object | CA friction | If CAs object |
| P-7 | Make the authenticator app mandatory for the CA role, because one CA login reaches many businesses | ON-1 (optional, off by default) | Adopt before CAH-1 ships | A single CA-account breach exposes many clients | Yes |

**Rejected for now (revisit when the R1 loop works and 3 CAs commit):** upsell tiers and per-GSTIN add-ons, "Prepared with Kartaa" invoice footer and referral credits, reconciliation certificate page, Tally or Busy export, settlement and working-capital roadmap, GSTR-2B ingestion, build-versus-buy of a GSP filing API (conflicts with "we never file"). One design rule is kept now: every imported row keeps a stable seller SKU key so these can be built later without re-import.

## 13. Open items

**Only Pankaj can decide or do**

| Item | Why it needs Pankaj | Effect if open |
| --- | --- | --- |
| Engage a named, paid CA under a written scope (L-1); decide whether the seller or the CA pays | He owns the relationship; no real CA is engaged | No external user |
| Run the concierge filing, 15 interviews and set kill-rule values and spend cap (L-0) | Needs his contacts and time | No validation |
| Test GSTR-1 upload to the portal (L-2) | Needs his login | JSON stays "not verified on the portal" |
| Lawyer review of terms, privacy, refund policy and data protection applicability (L-3) | Legal spend | No launch |
| Support contact and response time; domain; landing placeholders | Brand and contact details | Go-live blocked |
| Real AWS staging, Lambda limit, paid plan before 2027-01-25 (L-4) | Paid infrastructure | No staging |
| Payment provider and our own GST registration (D3, D6) (L-5) | Money and legal identity | Stays "free for now" |
| Date for the CA to settle invoice numbering scope (D-010) | Only he can set it | R2 to R4 stay practice-only and unsold |
| Approve D-099 (Table 13 in the JSON) and D-098 (Ask Kartaa, only if wanted); approve L-0a real-data use | They touch approved decisions | Recommendations stay unapplied |
| Accept or reject proposals P-1 to P-7 | They touch approved decisions | Recommendations stay unapplied |
| GSTIN lookup vendor and price (#249); Ask Kartaa spend and content terms; old branches | Paid services and rights | Both stay off |

**For the CA (human)** CA-1 (document dated in a filed return), CA-2 (paisa rounding), CA-3 (HSN quantity rounding), CA-4 (marketplace place of supply, partly overtaken by #345), CA-5 (tax-inclusive prices), T13-1, T13-4, T13-5 (Table 13), OQ-INV-1, OQ-HSN-1, OQ-HSN-2, OQ-B2CL-1, GSTR-3B netting and marketplace sales, invoice numbering scope and cancellation policy, 72-month retention.

**For the portal test upload** whether `chksum`, system flags and empty `doc_issue` slots are required (T13-2, T13-3), the GSTR-3B JSON period string, quantity decimals in Table 12.

**Open questions** OQ-CA-1: do CAs need concurrent sessions across devices (NF-15, D-092)?

## 14. Mocks

Mocks v15 are the contract: the mocks artifact in the project, v15 (sources `docs/mocks/`). They cover setup, filing home, uploads, held rows, summary and plan, guide, GSTR-3B worksheet, invoice create and created (v14), Home links and the Ask Kartaa control row (v15). Each at desktop and 360 px, with empty, error and unpaid states.

## 15. Source documents

BRD archive (v1.0 to v1.3), release plan v2, `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`, `docs/INVOICE_FLOW.md`, `docs/TABLE13_SPEC.md`, `docs/ASK_BOT.md`, `docs/GSTIN_LOOKUP.md`, `docs/IMPORTS.md`, CA expert answers v1 to v4 and the GST portal expert files in the project folder, and the market research and pricing research under `team/research/`.
