# Business Requirements Document v1.3: Small Business GST Invoicing & Filing Portal

Oct 24, 2026 · @Pankaj Kumar (Product Owner)

This BRD defines what we build first: a web portal where any small GST-registered business signs up by itself, then uses **GST Filing** (GSTR-1 and the GSTR-3B worksheet ready every month or quarter from its own invoices and, for online sellers, its marketplace reports, so the CA only checks and files) and **Business Hub** (company, products, GST invoices to business customers, and AI insights). Mobile apps follow the web. It is for every small business for which GST invoices and returns are a monthly pain and a CA bill. Businesses that also sell on Amazon, Flipkart or Meesho get the most from it.

## Status and how to read this

- **Status:** v1.3 (12 Nov 2026, adds the GSTR-3B worksheet to Release 1; see the Release 1 GSTR-3B section), built on v1.2 (12 Nov, Release 1 re-scoped) and v1.1 (24 Oct): v1.0 was approved by the CEO on 24 Oct 2026 under Pankaj's delegation; v1.1 is a minor fix setting GF-6 to 10,000 line items per file (CEO). Pankaj reviews it later. All 83 review comments are closed (team/reviews/rm-1a-brd/review-log.md) and the open decisions are decided below. Reframed on 16 Oct for every small business, not only distributors and marketplace sellers (Pankaj). Next: the Staff Engineer's tech plan, then HLD and LLD; coding waits for their approval.
- **Owner:** Product Owner. **Approver:** CEO, with final say delegated by Pankaj (24 Oct); Pankaj reviews later. **Reviewers:** Research, Engineering Manager and Staff Engineer (Pankaj's rule, 16 Oct). The first round also had QA, Lead, Designer and the GST expert.
- **After approval:** Staff owns the project-level tech plan, Lead owns the HLD, a Senior engineer owns each LLD. Each document gets its own review meeting before the next starts.
- **IDs:** requirement IDs (ON-, GF-, BH-, AI-, NF-) are stable. After approval the PO rewrites the stories in `team/backlog.md` to match them, because the current backlog predates this BRD. Acceptance criteria are written to be testable by QA as stated.
- **Tax caution:** nothing here is tax advice. Every GST rule, rate, form layout and due date cited by the GST expert or research needs sign-off from a qualified CA before live use. The product never claims a return is compliant or filed.

**v1.2 in one line:** Release 1 is now onboarding and GST filing for online sellers (Pankaj, release plan v2, approved 12 Nov 2026). It replaces the R1a and R1b split in v1.1. Invoicing and Business Hub move to Release 2; Releases 2 to 4 appear here as a roadmap only and get their own BRD versions (v1.4 to v1.6). Where an older section below conflicts with the Release 1 section, the Release 1 section wins.

**v1.3 in one line:** Release 1 now also includes a GSTR-3B worksheet (Pankaj, 12 Nov 2026), built right after the GSTR-1 JSON: outward supplies are computed from the same uploads, and the seller enters input tax credit (ITC) by hand. It is a worksheet to check and key into the GST portal, never a filing. Requirements are GF-21 to GF-29 in the new Release 1 GSTR-3B section. Anything not yet confirmed from an official source is marked "to be confirmed". Because v1.3 is used here, the Release 2 to 4 BRDs become v1.4 to v1.6.

## Release 1 (v1.2): onboarding and GST filing for online sellers

Release 1 is a web-only portal where a GST-registered seller who sells on Amazon, Flipkart or Meesho, or who has own sales invoices as PDF or Excel, signs up, says which platforms and filing frequency applies, uploads what they have (every section optional), sees a brief business summary, pays, and gets a step-by-step guide plus a ready-to-upload GSTR-1 JSON. We do not file for them; the seller or their CA uploads the JSON on the GST portal.

### What changed from v1.1

| Topic | v1.1 | v1.2 (Release 1) |
| --- | --- | --- |
| Release 1 content | R1a: invoicing, Business Hub and GST from own invoices; R1b: marketplace uploads | Onboarding, uploads (marketplaces and own invoices), GSTR-1 JSON, guide, payment gate |
| Own sales invoices | Created in Business Hub | Uploaded as PDF, Excel or both; cross-checked when both are given |
| Business type | None at sign-up | Distributor/retail field shown greyed out with an "Upcoming" tag; switched on in Release 2 |
| Export | Offline-tool Excel first, JSON later | GSTR-1 JSON in the official GSTN format; no offline-tool Excel in Release 1 |
| Deadlines | Dated table, source link | Same, and the dates must be confirmed from the GST portal before they are shown (GF-12) |
| Pricing | Price ladder, four periods, three plans | Two periods and one plan for Release 1 (BL-1); the old ladder is superseded |
| Staff and CA invites | In Release 1 (ON-5) | Release 4, by invitation link; Release 1 is the owner only |
| Invoicing, credit notes, products, customers, insights, period lock, CA pack | In Release 1 | Not in Release 1. Invoicing and Business Hub: Release 2. The rest is dropped for now (release plan v2, section 8) |
| GSTR-3B worksheet | Output tax from GSTR-1, ITC typed in (GF-7) | v1.3: back in Release 1 as GF-21 to GF-29 (outward supplies from the same uploads, ITC entered by the seller, worksheet not a filing) |

### Release 1 journey (replaces J1 to J3 for Release 1)

1. Sign up with email and verify a one-time code (ON-1, unchanged).
2. Onboarding, as separate steps: business name, GSTIN, address; which platforms the business sells on (Amazon, Flipkart, Meesho, own invoices); GST filing frequency, monthly or quarterly. The business-type field is visible but greyed out with an "Upcoming" tag.
3. Filing home: the business's filing periods with their GSTR-1 and GSTR-3B deadlines, and an option to file for each period according to the chosen frequency.
4. Uploads: one section per chosen platform plus one for own sales invoices. Every section is optional. The seller sees parsed rows, held rows and, for own invoices given as both PDF and Excel, the differences to fix.
5. GSTR-3B worksheet (v1.3): for each period, outward supplies computed from the same uploaded rows, and ITC entered by the seller, shown after the GSTR-1 build (GF-21 to GF-28).
6. Summary page: a brief business summary (periods, sources uploaded, sales and tax totals, open flags). The seller pays here.
7. After payment: the step-by-step guide to upload on the GST portal, the GSTR-1 JSON and the GSTR-3B worksheet (GF-29).

### Release 1 requirements and acceptance criteria

New IDs continue the stable numbering. Requirements not listed here and not marked as moved (ON-1, ON-3, GF-2 upload safety, GF-4, GF-5, NF-1 to NF-13, GC-P1 to GC-P6) still apply as written in v1.1. QA tests the criteria as stated.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| ON-2 (revised) | Platforms the business sells on | Onboarding asks which of Amazon, Flipkart, Meesho and "own sales invoices" apply; one or more can be chosen. It is a separate onboarding step, not part of the profile form. Only chosen platforms get upload sections (GF-13). There is no "salon" or other business wording anywhere. |
| ON-4 (revised) | GST filing frequency | Monthly or quarterly, asked in onboarding as its own step, stored with an effective-from period and history as built. The switching-window warnings of v1.1 still show; the app never blocks the choice. |
| ON-7 | Business type field (Upcoming) | Sign-up/onboarding and the business-update section show a distributor/retail business-type field that is greyed out and cannot be selected, with an "Upcoming" tag. It stores nothing in Release 1. Release 2 switches it on. |
| ON-8 | Change anytime | The owner can change filing frequency and platforms at any time in Business Setup. A change applies to periods not yet started or not yet paid; it never edits uploaded data or an already generated JSON, and it is audited. Admin changes for another business are by support access only (existing rule). |
| GF-12 | Deadlines confirmed from the GST portal | The filing home shows the GSTR-1 and GSTR-3B deadline for each period for the business's frequency and state group. Every date comes from dated reference data with an official GST-portal source link and a last-checked date, sourced in R1-M0. A date that is not confirmed shows "check on the GST portal" and is never guessed or computed from memory. |
| GF-13 | Per-section optional uploads | Each chosen platform and "own sales invoices" is its own section. Every section is optional: the seller can skip any and still reach the summary. Each section shows its status (not uploaded, processing, ready, rows held). Large files process in the background; the seller can leave and return. The identical file or an overlapping report never counts twice (GF-2 rules apply). Held rows must be resolved or explicitly accepted, and each is traceable to its file and row. |
| GF-14 | Own sales invoices: PDF and/or Excel | The own-invoices section accepts PDF, Excel or both; at least one is required for that section to count as uploaded. A provided Excel template is offered. A file the app cannot read is rejected with a plain reason. Invoice photos and PDF reading depend on decision D2; until it is made, Excel is the supported path. |
| GF-15 | Cross-verify PDF and Excel | When both are uploaded for the same period, invoices are matched by invoice number. The app highlights every difference: an invoice in one file only, or a mismatch in date, customer GSTIN, taxable value, tax or total. Each difference shows both values and lets the seller fix the data or accept one value; nothing is chosen silently, and the choice is audited. The JSON cannot be generated while a difference is unresolved. |
| GF-16 | Excel-only note | If the seller has uploaded Excel invoices but no PDF invoices for the period, the section shows the note "Upload invoices and we can validate." Once any invoices are uploaded, the note is not shown. |
| GF-17 | GSTR-1 from uploaded rows | The return is built from the rows of every uploaded section with the v1.1 sections and checks (GF-4, GF-5), through the existing section builder. Any case that depends on an open CA answer (CA-2, CA-3, Table 12 netting, b2cs Type E, Flipkart cash-back) is flagged "needs CA check" on screen and in the summary. |
| GF-18 | GSTR-1 JSON export | After payment and when the period has no unresolved blocks, the seller downloads a GSTR-1 JSON in the official GSTN format, which R1-M0 identifies and cites. It is checked against that format, and against the seller's own filed return in the pilot. Our wording is "ready to upload", never "filed" or "accepted by the portal" until a seller confirms it uploaded cleanly. Each JSON records the source files and the build it came from. |
| GF-19 | Step-by-step portal guide | After payment, a guide shows how to upload the JSON on the GST portal, one step at a time with screenshots or exact menu names, checked against the current portal before launch and re-checked on a schedule. The guide is behind the payment gate. |
| GF-20 | Summary page | Before payment, the last page shows a brief business summary: business name and GSTIN, filing frequency, period, platforms and files uploaded, counts of invoices and held rows, sales and tax totals by head, and "needs CA check" items. It does not reveal the JSON or the guide. |
| BL-1 | Release 1 plan and price | One plan, GST filing only: ₹499 per month or ₹1,499 per quarter, plus 18% GST on our fee. The seller sees the plan matching their filing frequency and can choose the other period. |
| BL-2 | Payment gate | No trial and no upfront charge. The seller uploads, sees the summary, and pays on the final page; payment unlocks the guide and JSON. Payment status is checked on the server for every download. A failed or abandoned payment leaves the uploads intact. The payment provider is decision D3. |
| BL-3 | Cancellation and plan change | No refunds on cancel; the service runs to the end of the paid period. A plan change shows prorated rates before the seller confirms. Our own GST registration and tax invoices for these fees are decision D6; the app does not claim to issue GST invoices for its fee until D6 is settled. |

### Release 1: GSTR-3B worksheet (v1.3)

Pankaj added this on 12 Nov 2026. For each filing period the seller gets a GSTR-3B worksheet: outward supplies computed from the same uploaded rows as the GSTR-1, and input tax credit (ITC) typed in by the seller. It is a worksheet, not a filing; Release 1 never files. Because the GST portal fills GSTR-3B Table 3 from the filed GSTR-1 (reported as locked from about July 2025, to be confirmed), the worksheet is mainly a check: "these are the numbers the portal should show; compare before you file".

Sources: the GST researcher's notes (team/research/gstr-3b-worksheet-requirements.md, 12 Nov 2026) were updated the same day after reading the official GSTR-3B Excel utility V5.8 (saved in team/gst/offline-tools/; files read only, no macro or program run). The table layout and the JSON section names are confirmed from that file. Still not confirmed: how a quarterly filer's period is entered (the utility takes months only), the exact JSON period string, the date and scope of the portal's lock on Table 3, and the CA items on credit-note netting and marketplace sales. A real exported GSTR-3B JSON is still needed as a fixture. "To be confirmed" means a GST rule or form layout still waiting for an official source or the CA.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| GF-21 | Worksheet per period | One worksheet per filing period, monthly or quarterly as chosen, opened from the filing home beside GSTR-1. It can be built only when that period's GSTR-1 build (GF-17) has no unresolved blocks. Every screen and download says "Worksheet, not a filing". Wording is "numbers to check and enter on the GST portal", never "ready to file", "filed" or "accepted". AC: a UI-string test finds no "filed" or "ready to file" wording for GSTR-3B; the label appears on screen and on every download. |
| GF-22 | Outward supplies from the same uploads | Table 3.1 and Table 3.2 figures come from exactly the rows and totals of the period's GSTR-1: 3.1(a) taxable outward supplies (B2B, B2C large and B2C summary, net of credit and debit notes), 3.1(c) nil-rated and exempt, 3.1(e) non-GST, and 3.2 inter-state supplies by place of supply, state by state, for unregistered persons, composition dealers and UIN holders, as in the official utility V5.8. 3.1(b) zero-rated shows zero because exports and SEZ are outside Release 1. Which GSTR-1 buckets feed which line, and the netting of notes, is to be confirmed (CA). Every figure drills down to its file and row. AC: on the Jul to Sep pilot sample and every golden case in team/gst/gstr1-examples.md, taxable value and tax by head (IGST, CGST, SGST or UTGST, cess) equal the GSTR-1 totals to the paisa in decimal arithmetic; each figure drills to its source rows. |
| GF-23 | Follows GSTR-1, outward values not editable | Outward figures cannot be typed over in the worksheet. If an upload, a held-row decision or a GSTR-1 figure changes after the worksheet was built, the worksheet shows "out of date" until rebuilt, and the seller's own entries are kept. A note says the portal fills Table 3 from the filed GSTR-1 and that corrections go through GSTR-1 or GSTR-1A (lock scope and start period to be confirmed from the official GSTN advisory). Table 3.1.1 (supplies on which the platform pays tax) shows "check on the GST portal" until the GST expert and CA confirm how goods sold on marketplaces are reported. AC: change a source row and the worksheet is marked out of date; the audit log records the rebuild. |
| GF-24 | Seller-entered figures | The seller can type: ITC by head for Table 4 (available rows 1 to 5, reversed rows 1 and 2, other and ineligible rows 1 and 2, as in utility V5.8; net ITC is shown as available minus reversed), copied from GSTR-2B on the portal; reverse-charge inward supplies (3.1(d)); exempt, nil and non-GST inward supplies (Table 5); and interest (Table 5.1). As in the utility, CGST is typed once and SGST copies it, and unequal input is refused. Every field is optional, in rupees with two decimals, not negative, labelled "entered by you", with a hint to copy it from the portal. Each change is audited (who, when, old and new value). The app never computes or checks ITC, reverse charge, interest or late fee in Release 1. A late-fee note, if shown, is information only, after official check. Row labels follow utility V5.8 and are re-checked against the portal form before launch. AC: values round-trip exactly; negative input is refused with a reason; audit entries exist for each edit; no field in this table is pre-filled by the app. |
| GF-25 | Totals and no offset | The worksheet shows output tax by head and the ITC the seller entered, side by side, and the line "Offset and payment are done on the GST portal". It shows no net-payable figure in Release 1, because the order of using ITC across heads has not been confirmed (a later release can add it after the CA confirms). AC: no net cash payable value appears anywhere in the worksheet or its downloads. |
| GF-26 | Frequency and quarters | A monthly filer gets a worksheet per month. A quarterly filer gets one worksheet per quarter showing quarter totals, with invoices already reported in IFF counted once and never twice. Whether the portal fills the quarter's Table 3 from GSTR-1 plus IFF is to be confirmed, and so is how a quarter is entered, because the official utility takes months only. The GSTR-3B due date comes from the same confirmed reference data as GF-12 and shows "check on the GST portal" when not confirmed. PMT-06 amounts for months 1 and 2 are not calculated in Release 1. AC: a quarter with an IFF invoice gives the same quarter total as the GSTR-1 build; a change of filing frequency never rewrites an existing worksheet (ON-8). |
| GF-27 | View and download | The worksheet is shown on screen and downloads as Excel and PDF, laid out in the order of the portal form so the seller can compare it section by section. Each download carries the source-file list, the build version, the time generated and the "worksheet, not a filing" label. A GSTR-3B JSON for the offline utility is not part of Release 1 (it can follow once a real exported file exists as a fixture; see the open items). AC: downloaded values equal the screen; amounts show two decimals; tenant scoping and authorization are tested as for the GSTR-1 JSON. |
| GF-28 | Flags and checks | The "needs CA check" flags of GF-17 carry over wherever they affect a worksheet figure, and anything resting on a "to be confirmed" rule above carries the same flag. The worksheet checks that Table 3.2 does not exceed Table 3.1(a), as the offline utility does (to be confirmed), and shows a warning, not a block. The flag count appears on the summary page (GF-20). AC: each open CA item that touches a figure is flagged on that figure and counted in the summary. |
| GF-29 | Plan and payment gate | The worksheet is part of the Release 1 plan (BL-1) at no extra price and sits behind the same payment gate as the GSTR-1 JSON (BL-2): before payment the summary says the worksheet exists but shows no figures; after payment it is viewable and downloadable. Payment status is checked on the server for every view and download. This is the Product Owner's reading; Pankaj can change it. AC: an unpaid tenant gets no worksheet figures from the screen or the API. |

Not in this version: a GSTR-3B JSON, filing, ITC checked against GSTR-2B or purchases, tax offset and net payable, interest and late-fee calculation, PMT-06 calculation, the TCS credit line, exports and SEZ, and Release 2 purchase data (which can later feed ITC).

**Proposed milestones** (the Engineering Manager confirms sizes and order): R1-M8a, GSTR-3B scope: the GST expert settles quarterly period handling and the lock behaviour (the form rows are already read from the official utility V5.8) and lists what is still to be confirmed, and the designer adds the worksheet mock for Pankaj's approval (size S). R1-M8b, worksheet build for GF-21 to GF-29 (size M). Both come after R1-M8 and before R1-M9, and each stops for Pankaj's go.

### Roadmap: Releases 2 to 4 (not in Release 1)

These come from Pankaj's notes of 10 Nov 2026 and release plan v2. Each gets its own BRD version, mocks and approval before building starts.

| Release | Scope | BRD |
| --- | --- | --- |
| R2: distributor and retail invoicing | Business type switched on. Purchase invoices as PDF or photo with a review screen, catalog and inventory built from confirmed lines, selling price per 1 qty, sales invoices with GST recalculation, stock reduced per invoice (a "no stock" message that never blocks). Monthly and quarterly GST-ready Excel and JSON for sales and purchases. Invoicing plan: ₹999 per month or ₹2,499 per quarter, first 10 invoices free. | v1.4 |
| R3: GST filing from our own invoices | Filing opens after all purchase invoices are uploaded and every invoice is confirmed in the portal; a one-click button enabled only once the period has ended and the filing period has started; asks for platform files when the business also sells on platforms. | v1.5 |
| R4: team members by invitation | Admin sends an invitation link; the invitee gets only the permissions the admin chose (starting with four fixed roles). | v1.6 |

Mobile apps come after all four releases are live on web. Existing v1.1 requirements for invoicing (BH-1 to BH-12, J4, J5, AI-1 to AI-4 from own invoices) are kept as reference for Release 2 and are rewritten in v1.3.

### Open items for Release 1

| Item | Owner | Needed by | Effect if open |
| --- | --- | --- | --- |
| Deadline dates confirmed from the GST portal (GF-12) | GST expert, R1-M0 | R1-M2 | Dates show "check on the GST portal" |
| Official GSTR-1 JSON format identified (GF-18) | GST expert, R1-M0 | R1-M8 | JSON cannot be built |
| D2: how PDFs and photos are read (paid or extra tools) | Pankaj | R1-M6 | GF-14 PDF path and GF-15 wait; Excel path works |
| D3: payment provider | Pankaj | R1-M9 | No payment gate |
| D6: our own GST registration and invoices for our fees | Pankaj and CA | R1-M9 | BL-3 wording stays cautious |
| CA-1 to CA-5, b2cs Type E, Flipkart cash-back, Table 12 netting | Pankaj's CA | Go-live | Cases shown as "needs CA check" |
| Live-numbering scope for invoices | Pankaj's CA | Release 2 | Invoices stay in practice mode |
| Product name, domain, SES production access, support contact | Pankaj | R1-M11 | Go-live blocked |
| GSTR-3B quarterly period entry, exact JSON period string, itc\_rev and itc\_inelg codes, and a real exported JSON as fixture (GF-26, GF-27) | GST expert | R1-M8a | No GSTR-3B JSON; quarterly period shows "check on the GST portal" |
| GSTR-3B Table 3 lock: scope, start period, GSTR-1A corrections, and quarterly with IFF (GF-23, GF-26) | GST expert | R1-M8a | Wording stays "check against the portal" |
| GSTR-3B netting of credit and debit notes in 3.1(a); marketplace sales in 3.1(a) and 3.1.1; late fee and interest handling (GF-22, GF-23, GF-24) | Pankaj's CA | Go-live | Figures shown as "needs CA check" |
| Should Release 1 also give a GSTR-3B JSON for the offline utility? (PO reading: not now; add after a real exported file exists) | Pankaj | R1-M8a | Worksheet only, on screen and as Excel or PDF |

### Mocks for Release 1 (v12)

Setup (platforms, frequency, greyed "Upcoming" business type), filing home with deadlines, upload sections with the Excel-only note, review of held rows and PDF/Excel differences, summary and pay, the step-by-step guide, and the GSTR-3B worksheet screen (v1.3: outward supplies, ITC entry, totals; a new mock to add to the v12 set). Each at desktop and 360 px phone width, with empty, error and unpaid states. Pankaj approves them before the screens are built.

## Problem and opportunity

Small Indian sellers lose hours every month turning scattered reports and paper bills into GST returns, and many pay a CA mainly to do that data entry.

- **Marketplace sellers** download different GST and tax reports from Amazon, Flipkart and Meesho, each in its own layout. They must merge these into GSTR-1, including the separate table for sales made through each marketplace (Table 14), then work out GSTR-3B. Mistakes cost late fees and lost input tax credit.
- **Small businesses (traders, wholesalers, distributors, retail shops)** who sell to other businesses or consumers often bill in Excel, Word, a basic billing app or by hand, then pay a CA to rebuild the return from those bills. Invoices miss mandatory fields, numbering breaks, and their GST-registered customers lose input tax credit when invoices are not reported on time, for example through the optional monthly IFF for quarterly filers.
- **Both** use the same few facts every period: what they sold, to whom, at what tax rate, and in which state. No affordable tool combines a seller's own invoices and their marketplace reports into one ready return. Repotic, eVanik and BUSY Recom handle the marketplace reports alone.

**Opportunity:** one portal that takes the reports and invoices a seller already has and gives back a return ready to upload, for any small business: invoices made here flow straight into the return, and marketplace reports join them. Filing stays on the GST portal: the seller or their CA files it themselves. This avoids the cost and approval needed for a GST Suvidha Provider (GSP) integration, which stays a later option.

Market research (15 Oct 2026, report in the project files) says to lead with GST return prep, not billing:

- India has 1.67 crore active GSTINs (GSTN report, June 2026, via a secondary copy). Meesho has about 20 lakh sellers, Amazon 16 lakh+ and Flipkart 14 lakh+ (company-reported, festive 2024), with overlap. Our estimate is 8 to 15 lakh unique GST-registered marketplace sellers.
- Marketplace sellers already pay about ₹15,000 a year to a CA, or ₹20,000 to ₹36,000+ a year to reconciliation tools, for GSTR-1 and TCS matching.
- Billing apps are crowded at ₹3,500 to ₹10,000 a year and loss-making: Vyapar lost ₹63 crore on ₹69 crore revenue in FY25.
- No affordable tool combines wholesale invoicing with marketplace GST prep. Zoho Books covers marketplaces only on its ₹4,999 a month Elite plan.

These are desk-research figures. Seller and CA interviews must confirm them before the build starts. The research sized marketplace sellers; the wider small-business segment needs its own sizing and competitor check by the Market Research Lead before pricing is fixed.

## Users

Release 1 serves any small GST-registered business that sells goods. Selling on marketplaces is an add-on any business can switch on; there is no business type to choose.

| Persona | Example | Main job in the product | Uses |
| --- | --- | --- | --- |
| Marketplace seller | One-person brand selling hair care on Amazon, Flipkart, Meesho | Upload monthly marketplace reports, get GSTR-1 / IFF data and a GSTR-3B worksheet, see deadlines | GST Filing |
| Small business that invoices | A trader, wholesaler, distributor or retail shop, such as Pankaj's distribution business in Maharashtra | Bill customers quickly from saved products, issue credit notes for returns, see who buys what | Business Hub, then GST Filing from the same invoices |
| Both | Seller with a marketplace store and a wholesale side business | One combined return per GSTIN from both sources | Both sections |
| Staff member | Billing clerk at the business | Create invoices only; no settings, no cost data | Business Hub (limited role) |
| CA or accountant | The seller's CA | Review the prepared return, download the hand-off pack, file on the portal | GST Filing: upload, prepare, export and lock periods; view only in Business Hub (invited by owner; role table under ON-5) |

Priority: we sell to every small business that invoices and files GST, and we market first to **hybrid sellers**, who invoice customers and also sell on marketplaces, because no affordable tool serves both. Billing alone is a crowded market (Vyapar, myBillBook), so the reason to buy is the ready return that cuts the CA's data-entry fee; invoicing is how the data gets in.

CAs are a sales channel as well as users. One CA prepares returns for many small sellers, so a CA login can belong to many businesses from R1, and R2 adds a free multi-client CA workspace.

**First test customers:** Vashi Essentials (marketplace) and Pankaj's distribution business (invoicing business), using synthetic data until real data use is approved.

**Assumed profile (to confirm with research):** 1 to 20 users per business, selling goods (service and composition businesses come in R2), turnover under ₹5 crore so quarterly filing is possible, comfortable on a phone browser, not on accounting software.

Planning scale (PO assumption for the cost estimate and load tests): 10 pilot sellers in the first 3 months and 100 by month 6, each with up to 500 invoices and 20,000 marketplace report rows a month.

## Product structure

After onboarding, every seller lands on Home and works in two sections: **GST Filing** and **Business Hub**.

&#91;embedded content: product structure · onboarding, Home, two sections\]

Every business sees Home, Business Hub and GST Filing, and invoices flow into GST Filing without re-entry. Marketplace uploads appear in GST Filing once the owner ticks a marketplace, at sign-up or later in Settings. A seller who only sells on marketplaces can simply not use invoicing; nothing is hidden by a business type.

**Name for "Manage Business":** Decided by the CEO: **Business Hub**. It's short, works in Hindi-English UI copy, and fits invoices, products and insights.

## Scope by release

**Superseded in v1.2:** the R1a and R1b split below is replaced by the Release 1 section near the top. What this section calls R1a (invoicing and Business Hub) is now Release 2; the marketplace parts of R1b are in Release 1. Kept for reference until v1.3.

Release 1 ships the web portal with onboarding, both sections and basic insights; anything that needs a paid provider, a government API or a mobile app comes later.

Release 1 ships in two gates, each piloted and CA-checked on its own (**order decided by the CEO, 24 Oct**). **R1a** gives every small business sign-up, invoices and credit notes, and GST Filing from its own invoices (GSTR-1/IFF, the GSTR-3B worksheet, export, period lock and the CA pack). It has no outside blocker. **R1b** adds marketplace report uploads for Amazon, Flipkart and Meesho, Table 14 and the TCS check. It starts the day Vashi's redacted sample reports arrive, because report readers must not be guessed. Ready-to-file returns are the headline we sell from R1a.

Requirements by gate. During R1a, a seller who sells only on marketplaces can sign up and file from own invoices, but the pilot invites businesses that invoice; Vashi joins in R1b.

| Gate | Requirements | Mocks |
| --- | --- | --- |
| R1a | ON-1 to ON-6 and the role table; BH-1 to BH-9, BH-11, BH-12; GF-1, GF-3 to GF-10 from own invoices, with the checks table; AI-1, AI-2 and AI-4 from own invoices; NF-1 to NF-13 | M1 to M4, M6 to M16 (without marketplace parts) |
| R1b | GF-2 marketplace uploads; GF-4 Table 14 and operator GSTIN; GF-11 TCS check and its warning; marketplace rows in GF-3, GF-5 and GF-7; AI-1 adds marketplace sources | M5, marketplace parts of M3, M6 and M7 |

| Area | Release 1 (web MVP) | Release 2 | Later (needs approval) |
| --- | --- | --- | --- |
| Onboarding | Self sign-up, marketplace channels, business profile, filing frequency, invite staff and CA | GSTIN lookup to prefill details; mobile number sign-up (needs an SMS provider); CA workspace across many client businesses, free for CAs |  |
| GST Filing | Filing profile and calendar; upload Amazon, Flipkart, Meesho GST/tax reports; GSTR-1 and IFF preparation; validation; offline-tool Excel export; GSTR-3B worksheet (sales side); period lock; CA hand-off pack | GSTR-2B upload for input tax credit; direct portal-ready JSON export; amendments | Filing directly through a GSP; e-invoice (IRN) and e-way bill via API; a free public "marketplace report to GSTR-1 summary" tool to attract sellers |
| Business Hub: company and products | Company profile, invoice branding, products with HSN and effective-dated GST rate, CSV import | Price lists per customer | Multiple GSTINs or locations |
| Business Hub: invoices | Business customers (retailers, shops, other businesses), create, finalize, PDF, share link, credit notes, view and search, paid/unpaid mark, e-way bill details | Part payments, advances, receivables ageing, reminders | WhatsApp/SMS sending (paid provider) |
| Business Hub: stock | None (moves to R2) | Stock on/off, opening stock, on-hand and low-stock alerts; purchases and stock-in | Batch/expiry, warehouses |
| Insights (AI) | Dashboard: sales trend, top-selling products from own invoices, filing reminders | Marketplace SKU mapping, reorder suggestions, slow movers, customer buying patterns, return/RTO rate per SKU per marketplace, overdue customer payments by age | Natural-language questions ("which customers stopped ordering?") |
| Platforms | Responsive web (desktop and phone browser) | Android app | iOS app |

### Out of scope for Release 1

- Filing returns on the GST portal from the app, and any GSP integration.
- Generating invoices for marketplace orders (the marketplace issues them).
- Exports, SEZ, reverse charge, compensation cess, composition-scheme businesses, and exempt-only bills of supply. Services invoices (SAC codes, place of supply for services) come in R2 (CEO, 24 Oct).
- Full accounting (ledger, balance sheet), payroll and bank reconciliation.
- Marketplace settlement and payout reconciliation, and per-channel profitability.
- Subscription billing and plans.
- Release 1 GSTR-3B: a JSON for the GSTR-3B Offline Utility, filing, ITC checked against GSTR-2B, tax-payment offset, interest and late-fee calculation, and PMT-06 (v1.3).

## User journeys

**v1.2 note:** for Release 1 use the Release 1 journey near the top. J1 to J3 are partly reused (sign-up, frequency, quarterly months); J4 and J5 (billing and credit notes) belong to Release 2.

Five journeys cover Release 1; each one becomes a mock flow and a UAT script.

**J1. Sign up and onboard (any business, target under 10 minutes, timed from the first sign-up screen to Home for a first-time user with the code email at hand)**

1. Sign up with email and verify a one-time code sent by email.
2. Answer one skippable question: do you also sell on Amazon, Flipkart or Meesho? Ticking one turns on marketplace uploads; it can be switched on later in Settings.
3. Enter the business name, GSTIN (state auto-filled from it), address and legal name.
4. Choose the GSTR-1 frequency: monthly or quarterly (QRMP), with the switching window shown.
5. Adding the first product and first customer is on the Home setup checklist, not in onboarding.
6. Land on Home with a setup checklist and the next filing deadline.

**J2. Prepare a monthly GSTR-1 (marketplace seller)**

1. Home shows "GSTR-1 for October is due 11 Nov. Upload your marketplace reports."
2. In GST Filing, open October and upload the Amazon, Flipkart and Meesho reports named on screen.
3. The app previews rows per marketplace, flags errors (missing HSN, unknown state, duplicates), and shows totals by state and rate.
4. The seller fixes or accepts the flags, then sees the return by section (B2C by state and rate, sales through each marketplace, HSN summary, documents issued).
5. They download the offline-tool Excel, or the hand-off pack for their CA, and file on the GST portal.
6. They enter the filing date and acknowledgement number (ARN), and the month locks.

**J3. Quarterly filer (QRMP) months**

1. Months 1 and 2: if there are B2B invoices, Home prompts "Upload IFF by the 13th so your business customers get their credit", and the PMT-06 payment reminder shows for the 25th.
2. Month 3: the app prepares the quarterly GSTR-1, excluding invoices already sent in IFF, plus the GSTR-3B worksheet due on the 22nd or 24th depending on the state.

**J4. Bill a customer (any business, repeat invoice under 60 seconds)**

1. Business Hub → New invoice → pick the customer (or "cash sale").
2. Search saved products by name, code or barcode; quantity and last-used rate fill in.
3. Tax splits automatically into CGST+SGST or IGST from the place of supply, which the screen shows (for example "Place of supply: Maharashtra, intra-state"); total in figures and words.
4. Finalize: next number allocated, PDF ready, share link copied. The invoice also appears in that month's GST Filing.

Until Pankaj's CA approves the numbering format, invoices run in **practice mode**: a "Practice mode, don't send to customers" banner shows and finalize gives practice numbers that don't use up the real series.

**J5. Return from a customer (credit note)**

1. Open the invoice → Create credit note → pick lines and a reason.
2. The credit note gets its own number series and reduces the customer's balance and the month's tax.
3. If the invoice's month is already filed, the note falls in the current open month.

## Functional requirements and acceptance criteria

Each requirement below is in Release 1 unless marked R2; QA tests the acceptance criteria exactly as written.

### Onboarding (ON)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| ON-1 | Self sign-up with email | A new user signs up with email and a password and verifies a 6-digit code sent by email; mobile sign-up waits for R2. One email opens only one account. A code is valid for 10 minutes, 5 wrong tries void it, and at most 5 code requests per email and 20 per IP address are allowed per hour. Sign-in is email and password; owners and CAs can turn on an authenticator-app code (optional, off by default, in R1 because a CA login reaches many businesses). A session ends after 24 hours idle or 30 days, and at once on a password change. Signing up with an existing email gets the same message as a new sign-up. The error for an existing account doesn't reveal that it exists. |
| ON-2 | Marketplace channels | There is no business type: every business gets Business Hub and GST Filing. The owner ticks the marketplaces they sell on (Amazon, Flipkart, Meesho) at sign-up or later in Settings, and only ticked marketplaces show upload screens. The server refuses every action a user's role can't do with "not found" (role table below). Ticking or unticking a marketplace later never changes existing data. |
| ON-3 | Business profile | GSTIN format and check digit are checked, and its first two digits set the state. A state mismatch shows a warning (wording in mock M2). Legal name and address are required before the first invoice PDF or GSTR export. A marketplace-only seller without a GSTIN can enter a PAN-based enrolment number instead (Notification 34/2023). The turnover band is captured per FY; it decides 4- or 6-digit HSN on invoices, whether e-invoicing applies (over ₹5 crore in any FY since 2017-18) and the 30-day IRN limit. |
| ON-4 | Filing frequency for the business's GSTIN | Monthly or quarterly, stored with an effective-from quarter and its history. The rule 61A switching window is shown (for Q4: 1 Nov to 31 Jan), with warnings when today is outside it, when the last due return is unfiled, or when last FY's turnover was over ₹5 crore (monthly then applies from the next quarter). The app never blocks the choice. The portal manual reads stricter than rule 61A (a change only if no return is filed yet in the FY); CA to confirm which applies. |
| ON-5 | Invite staff and CA | The owner invites by email with a role: admin, billing or CA, with permissions as in the role table below. One CA login can belong to many businesses and switch between them; each owner grants and removes that access, and removal never deletes the CA's own login. Owner or admin can deactivate and reactivate a member with a reason (a blank reason is refused). It is audited, takes effect on the member's next request, and the last owner can't be removed. |
| ON-6 | Setup checklist on Home | Shows each incomplete step with a link, and disappears when all are done. |

Roles in R1 are owner, admin, billing and CA. They replace the six stock-era roles in `team/product/roles-matrix.md`. The server enforces every cell, and QA tests each one through the UI and the API.

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

### GST Filing (GF)

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| GF-1 | Return calendar | Shows the next due date per return for the seller's frequency and state group (GSTR-1 11th or 13th, IFF 13th, PMT-06 25th, GSTR-3B 20th or 22nd/24th). Dates come from a dated table with a source link and a last-checked date. A return still unfiled near 3 years after its due date gets a warning that it will soon become unfileable (GC-24). |
| GF-2 | Upload marketplace reports | For each marketplace, the screen names the exact report to download and how. Accepts CSV/XLSX up to 20 MB per file (to confirm against Vashi's largest report). Large files are processed in the background: the screen shows progress, the seller can leave and come back, and the preview appears when ready. Several files can be dropped at once; the app detects the marketplace from the columns and the seller confirms it. Preview shows rows, errors and totals before anything is saved. Nothing is ever counted twice. The identical file, or the same report downloaded again under a new name, shows "already imported" and adds nothing. A file whose dates overlap an earlier one is matched line by line on order and invoice ID: identical lines are skipped, and changed lines are shown for the seller to accept (audited) or skip. |
| GF-3 | Combine sources per period | A period's return includes uploaded marketplace sales plus invoices and credit notes created in Business Hub. Each figure links back to its source file and row, or to its invoice. |
| GF-4 | GSTR-1 / IFF preparation | Builds the sections a small seller needs: B2B, B2C large, B2C summary by state and rate, credit/debit notes, HSN summary (B2B and B2C split), documents issued, and supplies through each marketplace (with the operator's GSTIN). Quarterly filers get IFF for months 1 and 2 (B2B only), and the quarterly return excludes invoices already in IFF. Section totals match the worked examples in \`team/gst/gstr1-examples.md\`, which the GST expert writes before the HLD and the CA reviews, including a quarter with an IFF invoice left out. Table 14 only discloses supplies already in other tables, so liability totals are identical with and without it. The operator's GSTIN is a seller setting per marketplace and state, because the reports don't carry it. The B2C large threshold is dated config: default ₹1 lakh per Notification 12/2024, though the portal manual still says ₹2.5 lakh (CA to confirm). IFF warns when a month's B2B value passes ₹50 lakh, and after the 13th says those invoices go into the quarterly GSTR-1 (CA to confirm). Table 13 lists our series and the marketplace invoice series issued in the seller's name (CA to confirm). |
| GF-5 | Validation before export | Blocks export on: missing HSN, invalid customer GSTIN, invoice number over 16 characters or with invalid characters, duplicate invoice number in the financial year (ignoring letter case, across our invoices and imported marketplace invoices for the same GSTIN), period already locked. The full list of checks, and which block or only warn, is in the table below. Each error names the row and how to fix it. A marketplace row with a blank HSN is held until the seller enters the HSN once for that SKU; the entry is audited and shown as "entered by you", and a different HSN in a later report wins, with the conflict shown. |
| GF-6 | Export | Downloads the GST offline-tool Excel in the official template layout (template version recorded), plus a readable PDF/Excel summary per section. A golden test proves the official offline tool accepts our file: QA imports it into the named tool version with zero errors, records the tool and template versions, and repeats this whenever GSTN publishes a new template. This is a manual release gate owned by QA, because the tool is a Windows desktop app and can't run in CI. CI checks our file's structure against the official template file, which the GST expert attaches with its version. Each export file holds at most 10,000 line items, the most one JSON upload can carry (offline tool FAQ 16), and the app warns that the JSON must stay under 5 MB (FAQ 43). Larger returns split only on invoice boundaries, with the summary sections (B2CS, HSN, Table 13, Table 14) once, in the last file (team/gst/gstr1-examples.md, Part D). |
| GF-7 | GSTR-3B worksheet | Shows output tax by head (IGST, CGST, SGST) from the prepared GSTR-1, and marketplace TCS as a credit. Labelled "worksheet, not a filing". TCS is shown as a cash-ledger credit the seller can use after accepting it on the portal, never deducted from output tax. Output tax uses exactly the GSTR-1 figures, since GSTR-3B Table 3.1 is locked to them from the July 2025 period; fixes go through GSTR-1A. For QRMP months 1 and 2 it shows the PMT-06 amount both ways, fixed sum (35% of last quarter's cash tax, or 100% of last month's cash tax for a seller who filed monthly last quarter; CA to confirm) and self-assessed, citing the rules once RS-2 confirms them. Input tax credit entry is manual in R1; GSTR-2B upload comes in R2. v1.3: for Release 1 this row is superseded by GF-21 to GF-29 (no TCS credit line and no PMT-06 in Release 1). |
| GF-8 | Mark as filed and lock | Owner or CA enters the filing date and ARN, and the period locks. The ARN format is checked. Only the owner can unlock, with a reason, for example to fix a wrong ARN. A credit note for a locked period goes into the current open period, and a new upload for a locked period is refused with that explanation. Invoices dated in a locked period can't be cancelled; corrections go to an open period. Every action is in the audit log. |
| GF-9 | CA hand-off pack | One download per period: the export, the summary, a list of uploaded source files, validation results and the invoice list. |
| GF-10 | Nil month | When a period has no sales (no invoices, and uploaded marketplace reports that show zero), the app says so and shows the SMS option for nil filing (source cited). A seller who hasn't uploaded reports is never told to file nil. |
| GF-11 | TCS check per marketplace | The seller enters the TCS the GST portal shows for each marketplace and month. The app compares it with the TCS worked out from that marketplace's reports and shows the difference with the rows behind it. Labelled a check, not a reconciliation. TDS under section 194-O (0.1%, an income-tax deduction) is shown separately as a credit once settlement reports are imported after R1, and is never treated as a marketplace fee. |

Checks before export (GF-5). A block must be fixed; a warning can be accepted by the seller, and the acceptance is audited.

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
| TCS entered differs from the TCS worked out (GF-11) | Warn |

### Business Hub (BH)

**Moved to Release 2 in v1.2.** BH-1 to BH-12 are not in Release 1. They stay as reference and are rewritten in BRD v1.3 around purchase upload, catalog, stock and sales invoices from the catalog.

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| BH-1 | Company profile and invoice branding | Logo, bank/UPI details, terms and invoice prefix. A prefix preview shows the next number, at most 16 characters (e.g. `SBD/2627/00001`). |
| BH-2 | Products | Name, code (unique, case-insensitive), HSN, unit, sale rate, GST rate with a valid-from date (history kept). The app never suggests a GST rate. The owner or admin can tick "Confirmed with CA" on a product's rate; an unticked rate shows a warning on the product and invoice screens but never blocks. A product marked exempt or nil-rated, or carrying compensation cess, can't be put on an R1 invoice, and nor can a reverse-charge or export sale: invoice creation blocks it with a clear message (GC-11; CA to confirm Vashi needs none). Archive instead of delete once used. CSV import with preview. |
| BH-3 | Customers | Business name, optional GSTIN (format checked), state required, addresses, credit days. |
| BH-4 | Create invoice | Per the J4 journey. A repeat invoice for a saved customer with 3 saved products is finalized in 60 seconds or less: median of 5 timed runs on a mid-range Android phone on 4G, starting from Home. The worked examples also cover freight or packing charged on the invoice (added to taxable value) and an invoice-level discount, both spread across lines with different rates; the method needs CA sign-off. Tax split and totals match the worked examples in `team/product/r3-invoice-examples.md`. B2C cash sale is supported. When the business has ticked a marketplace, the new-invoice screen notes "Marketplace orders are invoiced by the marketplace; don't bill them again here" (GC-P5). |
| BH-5 | Finalize | One atomic step: number allocated with no gaps and no duplicates, values snapshotted, no stock effect in R1 (stock moves to R2). A retry or double-click within 24 hours, or two browser tabs finalizing the same draft, gives one invoice. R1 has no invoice cancellation: corrections are credit notes, and every number stays used. The GST expert's alternative, cancelling only on the invoice date with the number kept as Cancelled in Table 13, is the CA's call. Finalize needs a connection; drafts are saved on the server, and there is no offline mode in R1. Finalized invoices cannot be edited or deleted. In practice mode (J4), invoices take their own PR- numbers, never enter GST Filing, Insights or stock, and are kept and marked void when real numbering goes live. |
| BH-6 | Invoice PDF and share | The PDF carries every field the GST expert lists in `team/gst/document-fields.md`. The share link uses our own random token and opens only that invoice without login, never other invoices or the account. It expires after 30 days by default, the owner can revoke it, and every open is logged. |
| BH-7 | View invoices | Search and filter by date, customer, status and number. Shows paid/unpaid. CSV export with formula-injection protection. Duplicate an invoice into a new draft. |
| BH-8 | Credit notes | Per J5. Cannot exceed the remaining invoiced quantity or value. Has its own series. Appears in the GSTR-1 notes section. Keeps the original invoice's rate and place of supply. After the s.34(2) deadline (30 November after the FY ends, or the annual return date if earlier) it is blocked unless the owner overrides with a reason, which is audited (CA to confirm). |
| BH-9 | Payments received | R1: mark an invoice paid or unpaid, with date and mode (cash, UPI, bank, cheque). Part payments, advances and customer statements move to R2, with worked examples and the GST expert's view on advances. |
| BH-10 | Stock (optional, R2) | Moves to R2. The R2 update settles warn versus block, its default and who changes it, and what happens to on-hand when tracking is switched off and on again. |
| BH-11 | Cash sale (B2C) details | The buyer's state is always recorded, because it sets the place of supply (IGST s.10(1)(ca), Circular 209/2024). Name, delivery address and state are mandatory at ₹50,000 and above (Rule 46(e)). |
| BH-12 | E-way bill details (manual) | An invoice above the configured consignment value (default ₹50,000; state limits differ, CA to confirm) shows "e-way bill needed". The user records transporter, vehicle number and the e-way bill number they generated on the portal, and the PDF prints it. API generation comes later. |

## Insights and AI features

**v1.2 note:** insights (AI-1 to AI-10) are not in Release 1; the filing deadlines on the filing home (GF-12) replace the nudges. AI use planned for Release 1 is reading invoices (decision D2); other AI ideas wait for Pankaj's approval.

Release 1 insights are rule-based calculations that explain themselves. Generative AI (questions in plain language, summaries) waits until the data is trustworthy and its cost and privacy are reviewed.

Market research shows insights keep sellers coming back but are not why they sign up; saving time and fees on GST returns is. So R1 insights stay few and simple.

| ID | Insight | Release | Acceptance criteria |
| --- | --- | --- | --- |
| AI-1 | Sales trend | R1 | Home shows the last 30 days and the last 6 months of sales (excluding GST), by source: each marketplace and own invoices. Totals equal the sum of the underlying invoices and report rows for the same dates. |
| AI-2 | Top-selling SKUs | R1 | Top 10 products by quantity and by value for a chosen period. In R1 it counts own invoices only; marketplace SKUs join when SKU mapping ships in R2. |
| AI-3 | Low-stock alert | R2 (stock on) | A product appears when on-hand is at or below its reorder level. It shows on-hand, reorder level and units sold in the last 30 days. No alert when stock tracking is off. |
| AI-4 | Filing and compliance nudges | R1 | Upcoming due dates, the IFF prompt when B2B invoices exist in months 1 and 2, validation errors pending, the nil-month note (GF-10), and a warning when this FY's sales near ₹5 crore, based on sales in this app plus the turnover the seller declares in the profile. Each nudge links to the screen that fixes it. |
| AI-5 | Days of stock left and reorder suggestion | R2 | Days left = on-hand ÷ average daily units over the last 28 days, shown with that formula. The suggested quantity covers a chosen number of days. Labelled a suggestion. |
| AI-6 | Slow movers | R2 | Products with no sales in 60 days and stock on hand, with their value at cost. |
| AI-7 | Customer buying patterns | R2 | Customers whose order gap is more than twice their usual gap are flagged "may have stopped ordering". |
| AI-8 | Ask a question (generative) | Later | Needs approval of the model provider, cost and data handling. Answers must cite the numbers they used. |
| AI-9 | Return/RTO rate per SKU | R2 | Returned units ÷ sold units per mapped SKU and marketplace for a chosen period, from the uploaded reports, with the formula shown. |
| AI-10 | Overdue customer payments by age | R2 | Unpaid invoices past their credit days, grouped 0–30, 31–60, 61–90 and 90+ days, with totals per customer. |

Further insight ideas from research (team/research/AI-insights.md) are AI-9 and AI-10. The competitor walk-throughs (team/research/competitor-flows.md) added none for R1.

## GST and compliance requirements

The GST expert's 28 requirements (GC-1 to GC-28) are part of this BRD, each with its legal source and a flag where Pankaj's CA must sign off. The full list is in `team/gst/brd-section-gst-compliance.md`. Six principles apply to every feature:

| ID | Principle |
| --- | --- |
| GC-P1 | The app prepares returns; the seller or CA files on the GST portal. The app never says a return is "filed" or "compliant", only "ready to file" or "for CA review". |
| GC-P2 | No tax rate, threshold, due date or format is hard-coded. Each is dated reference data with its source and a last-checked date. |
| GC-P3 | The app never guesses a GST rate or HSN from a product name. A person enters and verifies each rate, with a rate history. |
| GC-P4 | Finalized invoices, credit notes and filed periods are never edited or deleted. Corrections are credit notes, cancellations or amendments, each audited. |
| GC-P5 | Marketplace invoices are the seller's own supplies. The app imports them as external invoices, never re-issues them, and includes them in returns and numbering checks. |
| GC-P6 | GSTINs are checked for format and checksum only. The app never calls a GSTIN "verified" or "active" without a portal lookup. |

## Non-functional requirements

These apply to every feature; the tech plan, HLD and LLD must show how each is met and tested.

| ID | Area | Requirement |
| --- | --- | --- |
| NF-1 | Data isolation | A business never sees another's data. Every request is checked on the server. Guessing another business's invoice or file ID returns "not found", and a test proves it for every screen and export. Our own support staff can't see a business's data unless the owner grants time-limited access (24 hours by default), and every view shows in that business's audit log. |
| NF-2 | Money accuracy | All amounts use decimal arithmetic, rounded to paise as specified. Totals are reproducible from source rows and invoices. |
| NF-3 | Audit and immutability | Finalized invoices, credit notes and locked periods are never edited or deleted. Who did what and when is logged for sign-up, finalize, credit notes, lock and unlock, settings, member invite, deactivate and reactivate, share-link creation, and exports or downloads of GST files. Owner and admin can read the log. Overrides, unlocks and deactivations need a reason, and a blank reason is refused. |
| NF-4 | Safe uploads | Size and type limits. Spreadsheet formulas are neutralised. Retries and re-uploads never double count. Raw files are stored encrypted and private and deleted 90 days after upload. Parsed rows (personal columns removed), file name and checksum are kept with the GST records, so every figure still traces to its file and row. Decided by the CEO, 24 Oct; CA to confirm against the 72-month rule (GC-27). |
| NF-5 | Privacy | Marketplace buyer names, phones and addresses are not stored beyond what the return needs: state and PIN for B2C rows, plus buyer GSTIN and legal name for B2B rows only (GSTR-1 Table 4). The raw file holding them is deleted after 90 days (NF-4). No real customer data in development or tests. |
| NF-6 | Performance | Warm pages load within 2 seconds at p95 on a 4G phone; the first request after idle may take up to 3 seconds. A 10,000-row report previews within 30 seconds of upload finishing, processed in the background with a progress state (GF-2). Finalizing an invoice takes under 2 seconds. |
| NF-7 | Responsive and accessible web | Every screen works at 360 px width: the page never scrolls sideways, invoice lines become stacked cards, and wide return tables scroll inside their own box with the first column fixed. WCAG 2.1 AA contrast and keyboard use. Indian number format (₹1,23,456.00) and DD-MMM-YYYY dates. |
| NF-8 | Reliability | At most 24 hours of data lost and service back within 8 hours after a failure. Backups are encrypted and kept 35 days, and a restore is tested before launch and every quarter. A failed upload or finalize leaves nothing half-saved. |
| NF-9 | Tax-content governance | Rates, thresholds, due dates and form layouts live in dated, cited data, not code. A change needs GST expert review. The UI never claims compliance. |
| NF-10 | Platforms | Web first (current Chrome, Safari, Edge; Android Chrome). The design and APIs must allow Android and iOS apps later without rework. |
| NF-11 | Cost | Fits the approved AWS budget for a small user base. No paid third-party service without approval. |
| NF-12 | Account closure | The owner gets a full export first and login is disabled at once. GST records are archived for the 72-month period (GC-27) and then deleted; other personal data is deleted within 30 days, including from backups as they expire. |

NF-13 Usage events: the product records the events the success metrics need (sign-up steps, first invoice, first upload, export, period locked) with a timestamp and business ID, and no personal data or amounts. The tech plan picks where they are stored.

Security-critical requirements, where QA's merge block applies: ON-1, ON-5 and the role table, NF-1, NF-3, NF-4, NF-5, NF-12 and BH-6.

## Success metrics and launch criteria

Release 1 launches to a closed group of about 10 sellers once the launch criteria pass. Targets are first guesses for Pankaj to adjust.

| Metric | Target in first 3 months | How measured |
| --- | --- | --- |
| Onboarding completion | 70% of sign-ups finish J1 | Event funnel |
| Time to first value | Median under 10 minutes to the first invoice or first uploaded report | Event timestamps |
| Return accuracy | 0 differences between our GSTR-1 and what the CA filed, for 3 pilot periods, matched to the paisa per GSTR-1 table, rate and state, with every difference explained in writing | CA comparison on pilot sellers |
| Prep time saved | Seller reports at least 50% less time per return | Pilot interviews |
| Repeat invoice speed | Median under 60 seconds | Event timestamps |
| Retention | 60% of active sellers prepare their next period's return in the app | Monthly cohort |
| Trust | No data-isolation incident; no duplicate invoice numbers | Monitoring, audit log |
| Willingness to pay | At least 5 of about 10 pilot sellers say they would pay the adopted price for their plan; the pilot interviews test the price ladder under Decisions | Pilot interviews |
| CA channel | At least 2 pilot CAs add a second client business | Account data |

**Launch criteria for the closed pilot**

- [ ] Pankaj's CA approves a sample invoice, credit note, and one GSTR-1 export prepared from real (redacted) Vashi reports. The CA also approves the numbering format, rounding, the B2C large threshold, the cancel versus credit-note policy, the HSN and GST rate of every pilot product (rates changed 22 Sep 2025), and the GST expert's 22-scenario checklist. Pankaj names the CA and their turnaround time; QA owns the offline-tool release gate. QA builds the sample pack: an intra-state B2B invoice, an inter-state B2B invoice, a B2C cash sale, and a credit note against one of them. Each CA sign-off is recorded in docs/DECISIONS.md.
- [ ] UAT scripts for J1 to J5 pass on staging. QA writes them as Given/When/Then lists with the unhappy paths, and the PO signs off each one.
- [ ] Tenant isolation and security tests pass, and a backup restore has been tested.
- [ ] Every screen carries the "prepared for filing, check before you file" wording where relevant.
- [ ] Pankaj approves going public (needed for any public deployment).

## Decisions, assumptions, risks and open questions

**Decisions already taken**

| Decision | Taken by | Date |
| --- | --- | --- |
| Built for every small GST-registered business: invoicing plus ready-to-file returns, with marketplace uploads as an add-on (Pankaj, 16 Oct; replaces the two business types of 14 Oct) | Pankaj | 14 Oct 2026 |
| The app prepares returns; the seller or CA files on the GST portal. GSP filing is a later option, priced by research | CEO (on Pankaj's delegation) | 15 Oct 2026 |
| Web first, then Android, then iOS | Pankaj | 14 Oct 2026 |
| Coding paused until BRD and mocks are approved; then tech plan (Staff), HLD (Lead), LLD (Senior), each reviewed | Pankaj | 14 Oct 2026 |
| AWS Mumbai, Python services, Terraform (existing stack; the Staff tech plan may revisit it, including the five-service split, with Pankaj's approval. Existing code and the frozen PRs are reference only, not a constraint) | Pankaj | 12 Oct 2026 |
| Invoice numbers: one series per GSTIN, document type and financial year, max 16 characters, no gaps | PO default, CA to confirm | 14 Oct 2026 |
| Stock tracking optional per business, from R2 | PO | 14 Oct 2026 |
| Lead with ready-to-file GST returns for every small business; invoicing is how the data gets in. Release 1 ships in two gates: R1a invoicing plus GST returns from own invoices, R1b marketplace uploads | PO, from market research and EM review; order decided by the CEO, 24 Oct | 15 Oct 2026 |
| Export in the government offline-tool template first; direct JSON later, only after golden files made by that tool (GC-22) | PO and GST expert | 15 Oct 2026 |
| Keep GST records for 72 months after the annual-return due date, even if a business closes its account; export and archive instead of deleting (GC-27, CGST s.36) | PO default, CA to confirm | 15 Oct 2026 |
| Sign-up is email-only in R1; mobile sign-up waits for an approved SMS provider and DLT registration | PO, from EM review | 15 Oct 2026 |

**Assumptions**

- Sellers can download their GST/tax reports from each marketplace's seller panel each month.
- Most target sellers have never had aggregate turnover above ₹5 crore across their PAN in any FY since 2017-18. Once that happens, e-invoicing (IRN) applies to their B2B invoices from then on, with a manual IRN step until an API integration is approved. Vashi's and the distribution's turnover history is asked for below.
- Sellers have one GSTIN. Multiple GSTINs, for example from Amazon FBA warehouses in other states, come later.

**Risks**

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Marketplace report layouts change without notice | Uploads fail or misread | Versioned adapters, a preview before saving, alerts on unknown columns |
| Wrong tax treatment in a prepared return | Seller penalties; loss of trust | CA review gate, cited rules, "check before you file" wording, golden tests against the official offline tool |
| Portal rules differ from the law text (B2CL ₹1 lakh vs ₹2.5 lakh) | Export rejected | Thresholds as dated config; re-check against the offline tool before each release |
| Sellers expect one-click filing | Lower adoption | Clear positioning; GSP option researched and priced |
| Data breach of financial data | Severe | Isolation tests, encryption, least privilege, no real data in tests |

**Decided by the CEO, 24 Oct 2026 (final under Pankaj's delegation; Pankaj reviews later)**

- [x] Release gates: R1a is Business Hub invoicing plus GST returns from the business's own invoices; R1b adds marketplace uploads (Amazon, Flipkart, Meesho), Table 14 and the TCS check.
- [x] Pricing: the price ladder below from the pricing research (team/research/pricing/pricing-research.md), validated in the pilot interviews.
- [x] Raw uploads are deleted after 90 days and GST records are kept 72 months (NF-4, GC-27), pending CA confirmation.
- [x] Approve comments from the shared GitHub account are accepted until real users arrive.
- [x] Section name: Business Hub.
- [x] Service (SAC) and composition-scheme businesses go to R2.
- [ ] Still open, data only Pankaj can supply: Vashi's redacted reports and largest file size, turnover history since 2017-18, the CA's name and turnaround, and interview introductions.

| Plan (₹ per period) | Monthly | Quarterly | Half-yearly | Yearly |
| --- | --- | --- | --- | --- |
| GST Filing | 499 | 1,399 | 2,599 | 4,799 |
| Business Hub | 399 | 1,099 | 2,099 | 3,799 |
| Both | 749 | 2,049 | 3,899 | 6,999 |

**Superseded in v1.2:** this price ladder is replaced by BL-1 (₹499 per month or ₹1,499 per quarter for Release 1, plus 18% GST) and the Release 2 plan in the roadmap.

"Confirmed with CA" is a tick the owner or admin sets on a product's GST rate (BH-2); an unticked rate warns but never blocks. Items marked "CA to confirm" elsewhere stay open notes.

**Open questions (owner)**

- [ ] Which exact report from each marketplace is the source of truth for GSTR-1? (Research RS-4, GST expert; blocks the GST Filing HLD, not BRD approval)
- [ ] Answered by the GST expert: marketplace B2C sales go in Table 7 and are also disclosed in Table 14(a); B2B marketplace orders go in Table 4 and Table 14 (GSTN advisory, Jan 2024 period on). CA to confirm only; doesn't block.
- [x] Pricing decided by the CEO, 24 Oct: the price ladder above, validated in the pilot interviews.
- [x] Section name: "Business Hub" (decided by the CEO, 24 Oct).
- [ ] From Pankaj: redacted real reports and one real invoice per marketplace from Vashi, plus the largest monthly report's size (blocks the GST Filing HLD); the turnover history since 2017-18 for Vashi and the distribution (blocks R1a go-live, for e-invoicing); the CA's name and turnaround (blocks the pilot); and introductions for validation interviews with 10 marketplace sellers, 5 invoicing small businesses of different kinds and 3 CAs (before the build starts).

**Questions for Pankaj's CA** (from team/gst/gstr1-examples.md; the GST expert sends them)

- [ ] Review every figure and every \[CA\]-tagged row in the GSTR-1 worked examples.
- [ ] Quarterly GSTR-1: do Table 12 (HSN) and Table 13 (documents) cover the whole quarter, including invoices already sent in IFF?
- [ ] If the offline tool rejects a negative B2C summary row (returns larger than sales for a state and rate), how should it be reported?
- [ ] Table 13: which invoice series to list for marketplace invoices issued in the seller's name?

## Mocks needed and approval checklist

**v1.2 note:** the Release 1 mocks (v12) are listed in the Release 1 section. M8 to M13 (products, customers, invoices, credit notes) move to Release 2; M14 and M16 (team and CA access) move to Release 4.

The Designer produces web mocks for these screens, at desktop and 360 px phone width, before Pankaj's approval. Every mock shows its empty, error, locked-period and practice-mode states where they apply, and M3 comes in two variants: without marketplaces, and with marketplaces ticked.

| Mock | Covers | Journey |
| --- | --- | --- |
| M1 Sign-up, verify, marketplace channels | ON-1, ON-2 | J1 |
| M2 Business profile and filing frequency | ON-3, ON-4 | J1 |
| M3 Home dashboard (both types) | ON-6, AI-1 to AI-4, GF-1 | J1, J2, J3 |
| M4 GST Filing: period list and calendar | GF-1, GF-8 | J2, J3 |
| M5 Upload marketplace report and preview with errors | GF-2, GF-5 | J2 |
| M6 Prepared return by section, export, CA pack | GF-3, GF-4, GF-6, GF-9 | J2, J3 |
| M7 GSTR-3B worksheet | GF-7 | J3 |
| M8 Products list and product form | BH-2 | J4 |
| M9 Customers list and form | BH-3 | J4 |
| M10 New invoice (desktop and phone) and finalize | BH-4, BH-5 | J4 |
| M11 Invoice PDF layout | BH-6 | J4 |
| M12 Invoices list and invoice detail | BH-7, BH-9 | J4 |
| M13 Credit note | BH-8 | J5 |
| M14 Settings: company, team and roles | BH-1, ON-5 | J1 |
| M15 Insights page | AI-1, AI-2, AI-4 | J2, J4 |
| M16 CA access and business switcher | ON-5, role table | J2, J3 |
| M17 SKU link (R2) | AI-2, AI-9 (marketplace SKU mapping) | R2 |

**Review and approval**

- [x] BRD review meeting RM-1a: 83 comments logged, all closed by 16 Oct; their decisions were made by the CEO on 24 Oct. Re-review by Research, Engineering Manager and Staff Engineer.
- [ ] Market research folded into Problem, Users, Scope and Insights (done 15 Oct). Competitor flows (SUP-5) folded in on 16 Oct: place of supply shown on the invoice screen.
- [ ] Mocks M1 to M16 reviewed in a design review meeting.
- [x] CEO approved BRD v1.0 on 24 Oct 2026 (final under Pankaj's delegation; Pankaj reviews later). Mocks approval follows the design review.
- [ ] Then: the project-level tech plan (Staff), HLD (Lead) and LLDs (Senior), each with its own review meeting.

## Invoice flow review (2026-11-19, proposed, owner approval pending)

From the owner's test of the invoice screen and a comparison with Tally and Zoho Invoice. Full write-up: `docs/INVOICE_FLOW.md`. Mocks: v14 (Home, New invoice, Invoice created). Tally facts come from web summaries only; low or unverified items are marked in that file. Numbering stays off until the CA confirms, so every invoice is a practice invoice.

**What Tally does that we should match:** one accept key posts the voucher, there is no half-way draft step, a missing HSN is flagged where you are and fixed in place, new parties and items are created without leaving the voucher, and negative stock only warns.

**New and changed requirements, with acceptance criteria:**

- **BH-4a Create is the primary action.** The invoice screen's main button is Create invoice (Create practice invoice while numbering is off), next to the totals, sticky on phone. It saves and finalizes in one retry-safe request. Save draft is secondary. A double press creates one invoice.
- **BH-4b Missing HSN is fixed on the line.** A product with no HSN can be added to an invoice. Its line shows an HSN box; saving a valid HSN updates the product and enables Create. The server still refuses a finalize with a blank HSN, and we never suggest a code.
- **BH-4c Inline new customer and new product** stay on the invoice screen; the product mini-form allows a blank HSN.
- **BH-4d Preview PDF has five states:** idle, preparing, ready, slow (over 30 seconds, offers retry), session ended (keeps the draft, Sign in again returns to the same invoice and restarts the preview). Preview never blocks Create.
- **BH-4e Home links:** New invoice (primary), Products, Customers and Invoices are one click from Home and in the top bar.
- **BH-2 wording:** the product form says HSN is optional while adding products but needed before the product can go on a tax invoice.

**Open for the CA:** is an HSN mandatory on every sales invoice for this business, and with how many digits (OQ-INV-1).
