### Peer review (Contrarian-lens)
**1. Strongest: C.** It names the core contradiction: the "ready return" promise versus practice-only invoicing (D-010/SI-6), where no invoice ever enters a return. Its fix is a concrete scope cut: the launch wedge is R1 marketplace GSTR-1/3B only, with R2-R4 behind flags. It makes the 0-diff CA check a hard release gate, adds a first-return-free proposal, and finds that the buyer is often the CA. D is the runner-up for its owners, dates, testable ACs and kill rule. B has the most detailed findings, including the GF-18 versus GF-21 wording conflict and the GSTR-3B gap, but it is less decisive on scope.

**2. Biggest blind spot: A.** It is an expansionist reading that treats the BRD as a business to grow. It never confronts that invoicing is unusable while numbering is off, and it adds scope (tiers, referral footer, certificate, Tally export) to an unvalidated product. It also underweights the paywall-after-value trust problem and never mentions support.

**3. Missed by all five:**
- **Competitive positioning:** no one asks why a seller would switch when Vyapar and ClearTax already export GSTR-1 JSON (E noted this but proposed no answer). Nobody proposes a one-sentence wedge, e.g. "marketplace TCS/settlement-to-return in one upload," or tests it.
- **Marketplace dependency risk:** no one asks about report-format drift or platform data-access terms. B flagged drift only as a residual objection.
- **Liability and legal:** nobody asks for terms, a disclaimer or professional-indemnity cover if a figure is wrong. D flagged only refund terms.
- **Privacy and consent:** no one raises DPDP Act (India's data-protection law) consent, grievance contact or breach process. D-094 covers where data lives, not consent. This is unverified and should be checked.
- **Pricing model:** no one proposes per-return pricing, annual plans or UPI/Razorpay mandates. Nobody tests the seasonal churn that follows monthly filing deadlines.
- **Retention and reminders:** no one proposes deadline reminders by SMS or WhatsApp, or a mobile OTP login. Only E raised OTP login, as a minor point.
- **Cheaper CA-channel proof:** nobody suggests a CA-led pilot where CAs bring their own client files.

### Peer review (FirstPrinciples-lens)
**1. Strongest: C.** It names the real problem: the customer buys avoided CA data-entry and penalty fear, not "invoicing + GST". It spots the contradiction that practice-only invoicing (D-010/SI-6) means R2-R4 cannot produce a single real return, so only the marketplace GSTR-1/3B path (R1) delivers value. It proposes a concrete cut (R1 as the wedge, R2-R4 behind flags). It also makes CA sign-off a hard release gate and calls "final" premature. D is a close second on executability. B and E share C's diagnosis but lean less on cutting scope.

**2. Biggest blind spot: A.** It is the only response that treats the product as a business to expand: an upsell ladder, a "Prepared with Kartaa" footer, a Tally/Busy export, a data-graph roadmap. It never questions whether the core promise is true. It treats the missing human CA as a "remaining objection" rather than a blocker, and it ignores the practice-invoice contradiction that makes R2/R3 unsellable. Its referral footer is also moot while invoices are "not for your customer". It adds scope to an unvalidated product.

**3. What all five missed:**
- **Competitive reality is never checked.** E says Vyapar, ClearTax and Busy "already export GSTR-1 JSON" and B says they "may already cover" this, both flagged unverified. Nobody used WebSearch, even though the rules allowed it. The "do we win" question rests on an unchecked premise.
- **Portal-format drift.** None asks who owns the JSON schema and the marketplace report formats as they change (B touches it only as a remaining objection). A single schema change breaks every user's output.
- **Liability.** Nobody addresses who bears the loss when a wrong figure leads to a penalty. The terms and disclaimers are missing, and "no refunds" compounds it. D only notes the legal check on refunds.
- **Data protection.** Sellers' GSTINs and sales data are stored, and D-094 covers residency only. Nobody mentions consent or breach duties.
- **Cheapest validation.** A concierge test, where Pankaj hand-prepares one real filing before any more building, would answer the demand question.

### Peer review (Expansionist-lens)
**Expansionist review**

**1. Strongest: A.** It is the only response that sees a business beyond the BRD's utility. It turns the CA from a login into a distribution engine (CA workspace plus a partner plan). It also adds a referral loop through the invoice footer, a trust asset (a reconciliation certificate), and flags the marketplace settlement data as the long-term asset. It still labels its pricing and PWA ideas as PROPOSALs, as the rules require. D is the best runner-up on execution, and B/C/E are better on gating but are defensive.

**2. Biggest blind spot: C.** It argues for cutting scope to a marketplace GSTR-1 wedge and hiding R2-R4 behind flags. It shrinks the ambition and never asks what the wedge could grow into. It treats the CA as a buyer-decision point but gives no growth model. Its proposals to defer offline and to cut Insights discard upside. B is a close second: it is mostly a list of gates and hygiene fixes, with no growth thesis.

**3. What all five missed:**
- **Unit economics.** Nobody checks ₹499/month against the cost of Bedrock, SES, Lambda and support, or against CAC. Nobody says what happens to the margin if the CA pays for 50 clients.
- **Data moat and network effects.** Nobody mentions anonymised benchmarks, or the fact that CA-validated rules and parser fixes for Amazon/Flipkart/Meesho report drift could be sold as a rules/parser API to other tools.
- **Regulatory timing as a wedge.** Notice and reconciliation workflows (GSTR-2B vs books, mismatch notices) are natural adjacent paid products. These should be checked against current official sources.
- **Partnerships.** Nobody suggests marketplace seller-support or seller-community partnerships, or accountant associations.
- **Trust as a brand.** A named, registered CA's "Reviewed by" credential is a trust asset that competitors will find hard to copy, not just a launch gate.
- **Mobile OTP login** (E mentioned it only as minor) is also a conversion lever.

### Peer review (Outsider-lens)
**1. Strongest: B (with C close).** B is the only one that questions whether the product should be sold yet. It ties the unsupported "gap" claim, the missing human CA, the paywall placement, and the dead-on-arrival invoicing (numbering OFF but BL-4 sells a ₹999 invoicing plan) into one verdict and concrete gates (L-0 interviews, no paid plan before CA sign-off). It also flags the GF-18 "ready to upload" vs GF-21 contradiction and the GSTR-3B thinness. C's "launch the marketplace GSTR-1 wedge only, hide R2-R4" is the sharpest scope cut. As a shop owner, I'd want that cut.

**2. Biggest blind spot: A.** It is an expansionist wish list (data graph, working-capital signals, referral footer, Tally export) for a product with no customer, no CA and no price proof. It calls the practice-invoice problem nothing, never mentions that invoicing cannot be sold with numbering OFF, and proposes adding tiers and features rather than cutting. It also treats "Prepared with Kartaa" footers as growth when no live invoice can exist yet.

**3. What ALL five missed:**
- **Liability and trust if a figure is wrong.** None asks for terms, indemnity, or what happens when a seller pays a penalty or interest because of Kartaa's JSON. A CA will ask this first. E touches on it only through a refund promise.
- **Data protection and CA confidentiality.** Sellers upload sales data and customer GSTINs. Nobody mentions a DPDP-style privacy notice and consent (unverified applicability), CA-client data separation, or breach handling.
- **Portal and format drift.** B mentions marketplace report drift. Nobody covers GST portal JSON schema changes or an update-and-notify process, which breaks silently each time the portal changes.
- **Who pays the CA for review.** A named CA is demanded by everyone, but nobody budgets that cost or says how that CA is paid.
- **Willingness to pay for "prepare only"** versus free export in existing apps (E partly).
- **Ongoing mistakes by the seller.** Nobody covers wrong period or wrong GSTIN selection.

### Peer review (Executor-lens)
EXECUTOR REVIEW (Monday-morning lens)

1. Strongest: D. It is the only response that turns findings into a sequence with owners and dates (Week 0-4: engage a paid CA, pay for AWS staging, Pankaj does a test portal upload, diff Vaashi's real filed period against the CA's return). It also flags acceptance criteria that cannot be tested (GF-18 format unnamed, NF-6 no measurement method) and gives a pilot cut list (AK-1..4, ON-9). It adds a kill rule, counts instead of percentages, and manual UPI/Razorpay-link charging for the first 3 sellers. C is the best strategist (cut to the R1 marketplace wedge) but gives little on execution.

2. Biggest blind spot: A. It is an expansionist wish list: a CA partner plan, a higher tier, a referral loop, a settlement/working-capital roadmap, a "reconciliation certificate", PWA and Tally export. It adds scope to a product that is unlaunched, has no CA, and no pilot. It never questions that invoice numbering is OFF, which leaves R2/R3 unusable (B, C, D and E all flag this). It also never challenges the paywall-after-value structure. A's remaining-objections count of 3 understates the problem.

3. Missed by ALL five:
- Pankaj as a single point of failure for sequencing. D comes closest but still treats him as the only owner.
- Legal and regulatory exposure of the CA-adjacent claims. Marketing "ready to upload" returns, the "no refunds" policy, DPDP/consent for GSTIN and sales data, and the lack of any ToS or privacy policy. D only mentions a legal check on refunds.
- A concrete kill criterion tied to cost: how many months or how much spend before stopping.
- Cost and unit economics: AWS, Bedrock reader and SES cost per tenant against ₹499.
- Marketplace report format drift. Only B mentions it.
- A build-vs-buy check against existing GSP/ASP APIs. This is a legitimate question even though "we never file" is the position.
- Whether any of this is worth doing before 3 pilot CAs commit. A's gate is the only one close.