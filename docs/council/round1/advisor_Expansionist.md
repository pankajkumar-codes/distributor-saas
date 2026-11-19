EXPANSIONIST VIEW: the BRD specifies a good filing utility and misses the bigger company hiding inside it. If this works better than expected, Kartaa becomes the system of record for the small-seller GST data graph, with the CA as the distribution engine. The BRD cites the CA channel (sec 5, sec 10 "CA channel" metric) but builds nothing for it.

1. BLOCKER (positioning/distribution): the CA is a user, not a channel. Sec 5 says "CAs are a channel", yet sec 7.1 gives the CA a login and nothing else. One CA typically serves 30 to 200 small clients (unverified). The BRD prices per seller (BL-1, BL-4), which pits Kartaa against the CA's own data-entry fee.
 - Change: add CA-1 "CA workspace". It needs a multi-client dashboard (periods ready, held rows, "needs CA check" counts per client), bulk JSON download, and a client-invite flow where the CA sends the seller a link.
 - Add BL-5 "CA partner plan": CA pays for N clients at a volume rate, or the seller pays and the CA is free.
 - Acceptance criterion: a CA with 20 clients clears all of them from one screen.
 - Drop the "2 pilot CAs add a second client" metric (sec 10) for "5 CAs onboard 10+ clients each". Without this, distribution is paid acquisition against Vyapar and ClearTax budgets.

2. BLOCKER (pricing power): sec 4 prices the output (₹499 per month) but not the moat. Per BL-2 the only thing behind the gate is the JSON. Once a seller has one JSON, the price is anchored against the ₹15,000-a-year CA fee in sec 5 (unverified). This is a PROPOSAL, not a change to the approved pricing.
 - Keep the ₹499/₹999 pricing as it is.
 - Add a higher tier and a per-GSTIN add-on for multi-GSTIN and multi-state sellers, which sec 5 itself implies.
 - Cost of leaving it: an undifferentiated ₹499 ceiling and no upsell path.

3. MAJOR (WhatsApp and regional language): sec 7.5 SI-11 defers WhatsApp invoice sharing, and sec 7.9 plans an English help bot. In Indian SMB, WhatsApp is the interface and Hindi, Bengali and Tamil are the trust signal, so this deferral is wrong. It does not touch the approved web-only rule.
 - Change: move "share invoice link via WhatsApp (wa.me click-to-share, not the Business API)" into R2. It needs no vendor, no data egress and no approval gate.
 - Add NF-17: UI strings externalised from day one, with Hindi and one regional language as the R2 target, starting with West Bengal for Vaashi.
 - The "Ask Kartaa" bot (AK-1) should answer in Hindi and Hinglish.
 - Cost of leaving it: retrofitting i18n later is far more expensive than externalising strings now.

4. MAJOR (the real wedge: marketplace data): the "hybrid seller" in sec 5 is a segment, but the underlying asset is the cleaned, de-duplicated marketplace settlement data that the BRD already parses. Add a stated roadmap item, outside R1 to R4: settlement and TCS reconciliation (sec 7.2 GF-11 is already referenced for TCS) and, later, receivables and working-capital signals. Add an AC that every imported row keeps a stable seller SKU key so these can be built without a re-import. The BRD should also say that seller-data portability and consent are designed in now (NF-12 already covers export).

5. MAJOR (referral loop): every invoice PDF is a free billboard. Add to SI-6 an optional footer "Prepared with Kartaa" on live invoices, plus a referral credit (one free month) for seller-to-seller and CA-to-seller invites. This is a growth requirement the BRD does not mention at all.

6. MAJOR (trust as the product): GF-18 and sec 10 treat the "0 differences vs CA-filed" metric as pilot QA. Turn it into marketing. Add a "reconciliation certificate" page that shows the seller and the CA how every figure ties to its source row. No competitor can copy it quickly if the golden-test corpus is kept. Also publish an accuracy changelog. The AI-reader caveat in sec 8 needs a human CA before any public claim.

7. MINOR (offline): sec 7.5 does not mention offline. Cheaper than a native app is an installable PWA with a cached invoice draft queue, which would fit NF-10. This is a PROPOSAL, because "web only" is approved and a PWA is still web.

8. MINOR (adjacency): the Excel templates (GF-14) and the monthly files (SI-10) are the first step into the CA's own tools. A Tally or Busy import export is a high-value follow-on that costs only a file format and calls no API. Mark it "unverified demand" and ask in the pilot interviews.

9. MAJOR (go-to-market sequencing): sec 3 lists "pilot with real sellers" last and no CA is engaged. Add a launch criterion: 3 named CAs signed to the partner plan before public launch. Hybrid-first positioning is good, but unvalidated.

Remaining material objections if all my changes are made: 3 (no human CA yet; hybrid-seller demand unproven with no interviews; payments and our own GST registration not in place, so willingness to pay is untested).
Would I back this as final: no. The BRD is a strong spec for a utility. It becomes a baseline for a business only once the CA channel, WhatsApp and regional language, and an upsell ladder are in it.