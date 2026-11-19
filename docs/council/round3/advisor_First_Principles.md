The BRD is now built on the right question. v2.2 treats demand, CA sign-off and the reconciled-return wedge as things to test before building more, and Gates A and B, L-0 to L-6 and the 10a owners are numeric, ordered and have kill rules. I found no invented facts and no silent changes to approved decisions. I read the whole file. Two text-level defects remain, both fixable in a line or two.

**1. Major: Gate A does not test the wedge it is supposed to test (sections 2, 10).**
- Section 2 says that if sellers do not value the reconciled return over a ₹149-250 tool, "we stop or reposition". Gate A passes on "8 of 15 would pay at a tested price", which does not test that.
- Stated willingness to pay says nothing about whether Kartaa beats Vyapar, myBillBook, Zoho, Tally or the seller's current CA process. All four export a GSTR-1 JSON (verified in section 2).
- Gate A could pass while the wedge fails, and the build effort would be wasted.
- Change: add to Gate A that at least 8 of the 15 interviews record each seller's current method and what they pay for it. At least 6 of the 15 must also say they would use Kartaa instead of that method after seeing a masked concierge output, or the gate fails. Mirror the same line in the L-0 text.

**2. Major: the gate wording contradicts itself (sections 10, 10a, NF-17).**
- The launch-gate list says "all must hold before any external user", which includes L-5 (payments) and L-6 (go public).
- The same section, L-5 and 10a say the pilot is free until L-5. 10a also invites the first sellers at week 4 once "L-1 to L-4 hold".
- NF-17 says "no external user and no paid plan" until L-1.
- Read literally, nobody can pilot until payments exist, which also makes "free pilot" meaningless.
- Change: "L-0a to L-4 before any pilot seller; L-5 before taking money; L-6 before public launch."

**Minor, not counted:** Gate B tests retention, price and cost but not how sellers 11 to 100 will be found. The 100-by-month-6 planning scale has no channel hypothesis, only the CA-brings-a-client rule. One sentence in Gate B recording the intended channel would close it.

Remaining material objections: 2 (Gate A has no switching or wedge test; the "all gates before any external user" wording contradicts the free pilot, L-5 and NF-17)
Would I back this as the final baseline: no. After the two one-line edits above, yes.