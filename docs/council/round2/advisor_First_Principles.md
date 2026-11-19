**First Principles Thinker, round 2**

Round 1 is mostly addressed. The BRD now rests on the right question: will a seller trust and pay for a reconciled return? The weak point is that the gates record that work was done, not whether it passed.

**Blocker**
1. **L-0 has no pass threshold (s10, 10a).** "15 interviews, one concierge filing, teardown completed" is an activity count. Nothing says what result stops the project. The kill rules (second period, WTP, accuracy over 3 periods) need pilot data. Yet 10a row 4 makes the "pilot decision against the kill rules" in week 4, before any pilot seller exists. Two decisions are merged. Fix: split into Gate A (week 4, pre-pilot) and Gate B (end of pilot, about month 3). Gate A needs numbers, for example: at least X of 15 name return prep as a top pain and would pay; at least 8 interviewees come from outside Pankaj's circle across 2+ marketplaces; the concierge diff has zero unexplained differences. Also fill in "Pankaj's spend or time cap", which is currently blank, and record it in DECISIONS in week 0. Weight real payment over stated intent: at least 3 sellers actually pay (UPI) before Gate B.

**Major**
2. **Week 1 concierge conflicts with NF-14 and s2.** Vaashi's real filed period cannot go through the app while "real data only after approval" and "no real data in AI sessions" stand. Add an explicit approval record, with consent and an India-only environment, or run it masked.
3. **Hand-collected payment (10a) contradicts L-5.** Taking money before our own GST registration (D6) and lawyer review (L-3) is charging. Also, s1 says all gates must hold, but L-5 is "only when charging starts". Fix: pilot is free until L-5 passes, or L-5 applies to hand collection.
4. **Pilot returns are unreviewed.** The banner (GC-W1) is the only protection once real sellers use the JSON. Fix: add a pilot rule that no seller uploads a Kartaa figure until the named CA has reviewed it, or that the seller files by their normal method and Kartaa is the parallel run. The accuracy metric implies this but never states it.
5. **No remaining-build list, so the week 0 to 4 dates are unsupported.** Table 13 (#353), GF-31, CA-1 home, how-to screens, ON-10, LG-3, SP-1 and the banner are all new or unbuilt, and s3 is not updated. L-2, the portal upload in week 2, cannot pass without Table 13. D-099 is still "proposed" and is missing from the s13 Pankaj list. Fix: add a "R1 pilot build list" in dependency order with owners, and add D-099 to s13.

**Minor**
- ID collision: the new CA-1 "CA home" (7.7) clashes with open question CA-1 (PG-4, s13, L-1). Rename it to CAH-1.
- The wedge text in s2 states "₹149 to ₹250" as fact, while the table marks GST Tool's ₹149 as unverified. The s5 claim "no affordable tool found" and Zoho "high plan" sit beside "not verified" rows.
- ON-1 adds TOTP for owners and CAs "in R1". It is not marked as new scope or as built or unbuilt.

No silent overrides of D-094, numbering OFF, web-only or pricing were found.

Remaining material objections: 5 (L-0 thresholds and Gate A/B split with cap; real-data conflict; payment vs L-5; unreviewed pilot returns; no launch build list and D-099 approval).
Would I back this as the final baseline: no. It is one revision away: the five fixes are text-only.