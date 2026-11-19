EXECUTOR, round 2. Read the full BRD v2.1 and the chairman verdict. Round 1 is mostly closed. The weeks 0-4 plan and the gates are not yet testable, ordered or consistent with the build state.

**Blocker**
1. **Plan does not reach the gates it names (10a vs 10, L-1, L-2, L-0).**
 - No step has the CA signing the goldens, so L-1 is never met before "invite first 10" in week 4. Week 2 only sends the question sheet.
 - L-2 (week 2) needs a Table 13 JSON. GF-30 says the portal blocks an empty Table 13, but D-099 is unapproved and the build (#353) is pending. Neither is scheduled.
 - L-0 has no pass/fail threshold, only "completed". Week 4 "decision against the kill rules" is impossible, because those rules (second period, cost per tenant, CA diffs over 3 periods) need months of pilot data.
 - Change: add pre-pilot kill thresholds (e.g. WTP count from the 15 interviews, concierge diff result). Add a week 3 "CA signs / answers" step with a fallback owner. Add D-099 approval to week 0. Add a dated pilot review (about week 16) for the post-pilot kill rules.

**Major**
2. **Build state is silent on new scope (3, 7, 9).** Section 3 lists none of these as unbuilt, with no owner or week:
 - #353 Table 13 build
 - GF-31
 - the pilot banner (GC-W1)
 - CA-1 home
 - the ON-8 confirm screen
 - GF-2 how-to screens
 - LG-3
 - NF-13 events (every metric depends on it)
 - NF-18
 
 Add a "Build before gates" table with owner and week.
3. **ID collision.** CA-1 means the CA home in 7.7, but also the "document in filed return" CA question in PG-4, L-1 ("CA-1 to CA-5") and section 13. L-1 is ambiguous. Rename the home to CH-1.
4. **Real data vs NF-14 and section 2.** Week 1 runs Vaashi's real filed period "on synthetic or masked data until real-data use is approved". There is no approval step, and it is unclear whether Vaashi counts as an "external user" under NF-17. Add a Pankaj approval step and a definition.
5. **Payment contradictions.**
 - 10a collects payment by hand from the first three sellers.
 - BL-2 says "pilot is free, no gate".
 - NF-17 says no paid plan before CA sign-off.
 - BL-3/D6 says we have no GST registration.
 - P-2 refund terms are unreviewed.
 
 Change: pilot stays free until L-5, or say explicitly that hand-collection waits for D6 and the lawyer.
6. **First-10 mix is overbooked and conflicts with itself (10, 10a).**
 - Vaashi + Pankaj's contacts + 3 CAs × 3 clients exceeds 10.
 - "At least 5 external sellers on 2+ marketplaces" is unlikely to hold when CA clients are mostly traders.
 - Return accuracy needs 3 filing cycles, which the plan never schedules.

**Minor**
- ON-1 "mobile sign-up waits for R2" contradicts P-5 and the web-only rule.
- "Vashi" typo in GF-2.
- GF-5 check C-08 is unlabelled in the table.
- "EM" and "PO" are undefined in the BRD.
- The pilot spend cap is "set by Pankaj" with no week.
- Cost-per-tenant at n=10 needs a marginal vs fully-loaded definition.
- Interview recordings need a consent and storage line (LG-2, D-094).
- ON-10's 10-interview AC is a pilot metric, not a QA test.

No approved decision was silently overridden. P-1 to P-6 are properly labelled.

Remaining material objections: 6 (1 plan vs gates and kill rules, 2 build backlog, 3 CA-1 ID collision, 4 real-data approval, 5 payment contradictions, 6 first-10 mix and accuracy timeline)
Would I back this as the final baseline: no (every fix is a BRD text change, about one more pass)