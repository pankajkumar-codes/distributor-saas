Round 5, First Principles. I read the full BRD v2.4 and the round-4 first-principles report.

**Do rounds 1 to 4 hold?** Yes. The question the product turns on is whether a seller will pay and switch for one reconciled return (own invoices plus marketplace reports, traced to row level) instead of Vyapar, Zoho, Tally or their own CA. The BRD now tests that question in the right order.
- Gate A tests switching and the 3B worksheet.
- Pre-Gate-A and post-Gate-A spend is split (section 10 "Gates", 10a, section 3a).
- Gate B observes a real first payment, with a "payment unproven" fallback to a soft launch capped at 20 sellers.
- GF-32 reminders are in.
- L-2 has portal-test safeguards.
- The banner is tied to the accuracy metric.

I found no silent change to D-094, numbering OFF, web only, or pricing. P-1, P-2 and P-7 are correctly labelled as proposals, and BL-4 says it is provisional. Unverified claims (₹149, Zoho marketplace coverage, Notifications 78/2020 and 34/2023) are flagged "to confirm" or "unverified". I found no invented facts.

**Material objection (1)**

**Major: real seller data meets AI roles in the pilot, against NF-14 and NF-1.**
- Section 1 defines EM and PO as the simulated team in `team/`, which are AI roles.
- L-0a says real data runs with "no AI session".
- Yet 10a week 1 gives the concierge filing on Vaashi data to "Pankaj, EM" with the staff engineer as backup.
- Section 10 says "an engineer diffs table by table" against the CA's filed return for pilot sellers. That is real seller data.
- NF-14 says real tenant data never goes to AI sessions, and NF-1 bars staff viewing except under a time-limited grant.
- L-0a covers only the concierge, not the pilot accuracy diff. As written, the BRD's own measurement procedure breaks its own data rules, which is a trust and compliance failure on the metric that decides Gate B.

Concrete change:
- In section 10 (Return accuracy), name a human diff operator. The diff runs on a Pankaj-approved India-hosted device or under an NF-1 support grant. No raw seller data goes into an AI session. Only anonymised difference descriptions leave that environment.
- Replace "EM" in the 10a week 1 row with Pankaj and a named human.
- Extend L-0a, or add a short L-3 item, so pilot-seller consent covers the CA seeing the data and the diff being done.

**Minor (not blocking)**
- GC-W1 says "named CA". Section 3a item 2 and section 10 say "reviewing CA". Use "reviewing CA" everywhere.
- Weeks 4 to 6 pack L-3, L-4 (SES production access, restore test), build items 6 to 8 and P-7. Add one line: "week 6 is a target; the pilot starts when the written checklist is complete".
- L-5 has no date, so real payment evidence will probably default to "payment unproven". Add "target L-5 by week 14". This is acceptable if left, because the fallback is a capped soft launch.
- LG-2 interview consent is needed in weeks 1 to 4, but the lawyer review (L-3) comes after Gate A. Use a minimal consent line for interviews now, marked "pending lawyer review".
- A strict reading would also flag the Gate A switching test, since it shows a masked Vaashi output rather than each interviewee's own report. That is not material, because the pilot's second-period metric tests it with real data.

Interviews, the CA's signature, the lawyer's opinion, the portal test and Pankaj's spend cap all have an owner, an order and a kill or pivot rule, so I did not count them as objections.

Remaining material objections: 1 (real seller data in pilot diff and concierge vs NF-14, NF-1, L-0a; AI-role EM named as owner)

Would I back this as the final baseline: yes, conditional on that single text edit.