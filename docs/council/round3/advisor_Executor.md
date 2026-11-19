**Executor review of v2.2: gates, the section 3a build list and the 10a plan**

Rounds 1 and 2 are addressed in substance. Gate A and B thresholds are numeric, L-0a exists, the build list exists, the CA-channel items have IDs, and approved decisions are untouched. Two ordering and consistency defects remain that would stall or mislead execution. Both are fixable in text.

**1. Major: the launch gates contradict the pilot sequence (section 10, 10a, L-5, L-6, NF-17).**
- The header says all of L-0a to L-6 "must hold before any external user".
- The same section says that until L-5 holds the pilot is free, so external pilot sellers exist before L-5.
- The 10a row for week 4 admits sellers on "L-1 to L-4" only.
- L-5 and L-6 have no week, owner or backup in 10a.
- GF-18 and GF-19 are written "after payment", with no stated pilot behaviour.

Change:
- Split the gates into tiers. Pilot entry is L-0a to L-4. L-5 is required before any money is taken. L-6 is required before public launch.
- Add 10a rows for L-5 and L-6. The L-5 row should say it runs in parallel and must close before any real payment test after Gate B.
- Add one line to BL-2 saying that in the pilot GF-18 and GF-19 are open (the gate is off), consistent with GF-29.

**2. Major: the 10a schedule does not cover the work the gates and metrics depend on (3a, 10a, Gate A, Gate B).**
- 10a builds only 3a items 1 to 4 and 7 in weeks 0 to 3.
- Item 8 (NF-13 events) is the data source for "first return completed" and "time to first value", and it is unscheduled.
- Item 6 (CAH-1, CAH-2) is needed because the mix includes up to 5 clients of CAs and a CA reviews every return. It is also unscheduled.
- Items 5 and 10 (#369 for SI-8) are unscheduled.
- L-4 requires real staging, UAT, SES production access, a restore test and isolation tests. No 10a row schedules that work, only the week-1 approval.
- Gate A at week 4 requires L-4 to hold.
- The week-3 portal upload (L-2) has no failure path or slack.

Change:
- Schedule every 3a item by week.
- Add a "pilot-ready checklist" row at week 3 to 4 that names which of items 1 to 8 and 10 must be done.
- Add an L-4 work row with an owner.
- State what happens if the L-2 upload is rejected. For example, Gate A slips by a fixed number of weeks with a cap, or the stop rule applies.

**Minor:** the "CA channel" metric reads "3 named CAs each bring clients (3 each target)". This is ambiguous against the mix (up to 5 CA clients) and Gate B ("no CA has brought a client"). State a total count.

Remaining material objections: 2 (gate tiering contradiction with L-5 and L-6 unscheduled; 10a omits 3a items 5, 6, 8, 10 and the L-4 work)
Would I back this as the final baseline: no