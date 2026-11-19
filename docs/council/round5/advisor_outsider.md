**Round 5 review of BRD v2.4 (Outsider: skeptical seller plus practising CA)**

**Rounds 1 to 3 and the round-4 outsider finding.** I found no contradiction, invented statutory fact or silent change to approved decisions. D-094, numbering OFF, web only and pricing are intact, and P-1 to P-7 are still labelled proposals. The L-2 portal-upload safeguards I raised in round 4 are now in L-2, 10a week 3 and the change log. Gate A and Gate B are numeric, ordered, owned and have kill rules. The pilot is consistently free until L-5. 3B is honestly a worksheet with no ITC.

**Material objection**

**M-1 (Major): the pilot CA-diff data has no handling rule (section 10 Return accuracy, "CA comparison sheet"; 10a weeks 6 to 22; NF-14; L-0a).**
- L-0a covers only the concierge filing on Vaashi's data. The accuracy metric requires "an engineer diffs table by table, rate by rate and state by state to the paisa" between our GSTR-1 and the CA's filed GSTR-1 for real external sellers.
- The BRD does not say where that diff runs or where the comparison sheet lives.
- Section 1 describes the engineers as a simulated team in `team/`, and NF-14 bars real tenant data from "GitHub, CI, AI sessions or shared project files".
- The sheet is real sellers' tax figures. Done in the obvious way, the gate that proves accuracy would breach D-094 and NF-14 and the sellers' consent under LG-2. A CA would ask about this first.
- **Fix (about three lines):**
  - Add to section 10 and L-3: "The CA comparison uses real seller figures. It runs only inside the India-region tenant environment or on a named person's machine in India. The sheet is kept in India-only storage, is never committed or pasted into an AI session or shared project file, and is deleted on the same schedule as the raw files (NF-4). Seller consent in LG-2 names the CA comparison. Pre-L-4, diffs run only on masked data."
  - Add "AI sessions" to the "who may see it" line in L-0a.
  - Add a sentence: "the diff tool is an in-product CA-review view, or an exported sheet handled as above."

**Minor, not counted (each is a one-line text fix)**
1. Section 5 planning scale says "10 pilot sellers in 3 months, 100 by month 6". This is stale. The pilot runs weeks 6 to 22, and an unproven payment caps the soft launch at 20 sellers. Reword it to "10 pilot sellers to Gate B; 100 only if Gate B passes".
2. The metric and banner (GC-W1) say "the named CA files/reviewed". Section 1 now defines "reviewing CA", which can be the seller's own CA. Replace "named CA" with "reviewing CA" in the Return accuracy row and GC-W1.
3. ON-3 lets a seller with no GSTIN use a PAN-based enrolment number (Notification 34/2023). That sits oddly with "GST-registered" everywhere else. The notification is also not marked "CA to confirm", unlike the ₹5 crore and IRN items beside it. Add the flag and a note that no GSTR-1 is produced for such a seller until confirmed.
4. "One-click file button" (section 2 table, J7, PG-2, R3) conflicts in spirit with GC-P1, "we never file", and with the ON-10 risk of sellers expecting one-click filing. R3 is unsold, so relabel it "Prepare return" before R3 is ever sold.
5. GF-2 and 3a item 4 check the 20 MB limit "against the largest real report in the pilot", but item 4 is required before Gate A. Say "Vaashi's largest report, re-checked in the pilot".
6. L-4's "paid plan before 2027-01-25" is an unsourced date. A Gate A slip of up to 4 weeks consumes much of that slack. Add "source: AWS account notice; verify".
7. The interview recording consent (LG-2) is needed in weeks 1 to 4, but the lawyer-reviewed privacy text (L-3) comes after Gate A. State that a simple written consent form, India-only storage, covers interviews until L-3.

Remaining material objections: 1 (M-1, data handling for the pilot CA comparison against real seller figures)
Would I back this as the final baseline: yes, once the M-1 text is added. It is a text-only fix with no new gate.