**Round 2 coverage.** The nine round-2 issues are addressed in text. The pilot-free rule (L-5, §10a), real-data approval (L-0a), numeric Gates A and B, the build list (§3a), the 3B wording and CAH-1/CAH-2 all hold up. P-1 to P-6 are labelled as proposals and approved decisions are untouched. I found no invented GST rules. The statutory citations (Notifications 78/2020, 12/2024, 34/2023) are all flagged "CA to confirm". That leaves two internal contradictions introduced by the round-2 gate rewrite.

**1. Major: the launch gates contradict the pilot sequence (§1, §10, §10a, NF-17).**
- §1 and §10 say "all must hold before any external user", and that list includes L-5 (payments) and L-6 (go public).
- §10a invites the first sellers at Gate A when only "L-1 to L-4 hold".
- L-5 itself says the pilot runs free "until L-5 holds", so L-5 cannot come before the pilot.
- The checklist as written cannot be satisfied, and QA cannot test it.
- Fix: split the list into "Pilot-entry gates" (L-0a, L-0, L-1 to L-4 plus the §3a build items marked "Pilot") and "Public-launch gates" (L-5, L-6, Gate B pass). Make §1, §10 and NF-17 say which set applies to which kind of user.

**2. Major: the pilot banner never ships, and the build list is not tied to any gate (GC-W1, §3a, L-1).**
- GC-W1 shows "figures not yet checked by a registered CA" only "until L-1 is met".
- L-1 must be met before any external user, so no external user ever sees the banner. The L-1 sign-off covers golden cases, not each seller's return.
- The §10a safety rule (the CA reviews each return) shows the banner's real condition is per-return review. Left as written, build item 2 is wasted effort and the pilot has no wording that warns sellers.
- Fix: keep the banner until Gate B accuracy passes, or until the named CA has reviewed that return.
- Also, §10a schedules only build items 1 to 4 and 7 in weeks 0 to 3. Items 5 (GF-31), 6 (CAH-1/CAH-2) and 8 (NF-13, which Gate B's metrics need) have no week.
- Fix: add "§3a items marked Pilot, plus 8, complete" to the pilot-entry gate.

I have no other material objections. Everything else depends on outside facts (CA, interviews, lawyer, Pankaj's time) and is already gated with an owner, an order and a kill rule.

Remaining material objections: 2 (L-0 to L-6 scope contradicts the free pilot; banner condition is dead and the §3a build items are not gated or scheduled)
Would I back this as the final baseline: no. It becomes yes once those two text fixes are made.