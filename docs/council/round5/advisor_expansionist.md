**Expansionist, round 5, on BRD v2.4**

Rounds 1 to 4 are addressed. I read the change log, sections 1 to 4, 7.1, 7.2, 7.7 to 7.11, 10, 10a, 12 and 13. I found no new contradictions, invented facts or silent changes to approved decisions. D-094, numbering OFF, web-only R1 to R4 and the pricing rows are intact. P-1, P-2 and P-7 are labelled proposals.

Checked and sound:
- GF-32 exists in 7.2, is listed as 3a item 11, is scheduled in weeks 0 to 3, and feeds the second-period metric in section 10.
- The Gate A to Gate B ordering, the payment evidence rule and the spend cap are consistent across sections 10 and 10a.
- The gates that depend on outside facts (CA signature, interviews, lawyer, Pankaj's money) each have an owner, an order and a kill or pivot rule.

**Material 1 (Major): the own-invoice input path is undefined, so the stated wedge may not work for the sellers it targets.**
- The wedge in section 2 is "your own bills and your marketplace reports in one upload".
- GF-14 only says "a provided Excel template is offered" plus a text-layer PDF reader.
- Nothing says how an Excel file in a seller's own layout, or a sales-register export from Vyapar, myBillBook, Tally or Busy, gets in.
- The hybrid persona is the stated priority in section 5. Those sellers already hold their sales data in some tool. If they must re-key it into our template, "time to first value under 10 minutes" and "prep time saved 50%" will fail.
- Gate A records each seller's current method, but no requirement says what we accept or what a failure looks like. That wastes build effort and could kill the wedge for a fixable reason.
- Section 12 rejects Tally or Busy **export**. That is output and does not cover this input question.

**Concrete BRD change (text only, no stack choice):**
- Add a new requirement, for example GF-14a "Own-invoice file intake". Accepted at launch: the Kartaa template, plus any Excel or CSV through a one-time column-mapping screen. The mapping is saved per business and is audited. Rows that cannot be mapped are held, never guessed.
- Add one L-0 question per interview: "which tool or file do your sales bills come from, and can you export it?" Record the top sources.
- Add a Gate A line: if more than 5 of 15 sellers' own-invoice source is not covered by template or mapping, revisit before the pilot. Specific app-export readers are added only for sources named by 3 or more interviewees.
- Add a 3a item for the mapping screen, scheduled after Gate A and before the first seller. This keeps spend behind the demand gate.
- Acceptance test: Vaashi's real invoice file, or a masked version, completes mapping in under 10 minutes.

**Minor (not counted as material):**
- GF-32 goes only to the owner (section 7.2). For CA-managed clients, the CA is the real filer and should also be able to receive the reminder. Add "owner and, if opted in, the CA" to GF-32.
- Section 10a puts the interviews in weeks 1 to 4. Their wording should include the Material 1 question.

**Upside I am deliberately not raising:** GSTR-2B, Tally export, tiers, referral and WhatsApp are correctly deferred in section 12 with revisit triggers.

Remaining material objections: 1 (GF-14 has no defined intake path for sellers' own invoice files beyond a template and text PDFs, so the "own bills plus marketplace in one upload" wedge is untested and unbuilt for the target hybrid persona)

Would I back this as the final baseline: yes, conditional on that one text addition. The change is small and does not alter any approved decision.