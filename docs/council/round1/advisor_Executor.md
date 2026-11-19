EXECUTOR REVIEW: Kartaa BRD v2.0

Verdict: it is buildable and mostly built, but it is not launchable. Every launch step has no owner or sits behind Pankaj, and the BRD has no go-to-market.

1. BLOCKER, sequencing (s3, s10, s13). Launch depends on a chain that runs in series through one person. The chain is: real AWS, domain and SES, a CA who doesn't exist yet, a test portal upload, then the pilot. s13 says "Take the CA question sheet to his CA", but no CA is engaged. Change: add an owner and a date to every s10 launch checkbox and every s13 row. Add a "Week 0 to 4 launch plan" section. Week 1: engage a paid CA with a signed scope. Week 1: pay for AWS staging. Week 2: Pankaj does the test portal upload using his own GSTIN. Weeks 2 to 4: run Vaashi's real filed period through the app and diff it against the CA's return. Cut anything not on this path.

2. BLOCKER, no go-to-market (s5, s10). The only plan is "10 pilot sellers in 3 months". There is no named source for those 10 sellers and no channel, no onboarding call and no support. Change: add s10a "First 10". Seed it with Vaashi, Pankaj's distribution contacts, 3 CAs who each bring 3 clients, and the Meesho, Amazon and Flipkart seller communities. Add a CA-channel offer, for example free for CAs plus one client's first quarter free. Add a founder-led white-glove onboarding step for the first 10: a screen-share, and the founder uploads their first report. Add a support requirement: a WhatsApp or email address, a stated response time, and a weekly named person on rota. The BRD has no support requirement at all.

3. BLOCKER, acceptance criteria that can't be tested. Items that can't be tested as written:
- GF-18 says "checked against that format". The format is not named.
- GF-2's 20 MB limit is "to confirm".
- Return accuracy ("0 differences, 3 pilot periods") has no sample size or comparison procedure, and the CA to do it doesn't exist.
- NF-6 says p95 under 2 seconds but gives no measurement tool or environment.
Change: for each, add a fixture file, a pass/fail command and an owner. The GSTR-1 golden examples ("team/gst/gstr1-examples.md") are written by an AI reader and are not human-signed (s8), yet the launch gate rests on them. Make a human CA's sign-off a hard gate on the first real export, and say that explicitly.

4. MAJOR, payment model contradicts the first-10 plan (BL-2, BL-4, s7.8). Payment sits on the last page, after the seller has uploaded everything. D3 and D6 are open, so no money can be taken. The pilot is "free for now", yet willingness to pay is a launch metric. Change: for the pilot, record intent to pay with a Razorpay payment link or manual UPI invoice. Charge the first 3 sellers by hand before building any payment integration. Move D3 and D6 from s13 into the launch path with an owner and a date. Also note that "no refunds" plus "no trial" needs a legal check on the terms and refund policy, and none is listed.

5. MAJOR, scope that isn't shippable. Ask Kartaa (s7.9), the GSTIN lookup (ON-9), 4 roles with route-by-route permission tests (s7.7) and the Bedrock reader are all built or specified, and none is needed to run 10 sellers. Cut for the pilot: AK-1 to AK-4 and ON-9. Keep the code but remove them from the launch criteria. Replace the Ask Kartaa help bot with a static FAQ page.

6. MAJOR, onboarding has no CA story (s6 J8, TM-1). CA onboarding is only "one CA login can belong to many businesses". There is no CA-first flow: no multi-client dashboard, no bulk or quick client add, no CA-facing pricing, and no re-filing ease. Change: add CA-1 "CA home". It shows a list of client businesses, each client's period status, and "needs CA check" counts across clients. Acceptance criterion: a CA with 5 clients sees all 5 and their statuses on one screen. This is the cheapest channel, so build it before the Ask Kartaa help bot.

7. MAJOR, success metrics (s10). 70% onboarding completion and 60% retention are guesses taken from only 10 sellers. Change: for the pilot, replace the percentages with counts, for example "7 of 10 reach a GSTR-1 JSON". Also add one interview script, one weekly founder review, and a kill or pivot rule such as "if fewer than 3 of 10 file a second period, stop and reposition".

8. MAJOR, WhatsApp and regional language are absent (SI-11 defers WhatsApp). Indian small traders live in WhatsApp and Hindi. I would not ship without a WhatsApp link share (invoice link plus support). PROPOSAL to change an approved decision: allow a share-by-link and WhatsApp deep-link on the issued invoice page (SI-7). It is a link, not an API. Cost of leaving it as is: invoicing users will compare against Vyapar and myBillBook, which have this, and feel the gap straight away. I have not verified competitor feature lists.

9. MINOR. NF-16: ./demo.sh has no PDF renderer, so it can't demo the main invoice outcome. s14 mocks: confirm the mocks artifact link is shared with the team.

Remaining material objections if all my changes are made: 3. (a) Market fit is unproven without interviews, so the BRD should say "pilot, not final". (b) Compliance accuracy still rests on AI-read rules until a human CA signs. (c) Invoice numbering stays off, so invoicing is a practice-only product until a CA decides. That makes the 999 plan hard to sell before that decision.

Would I back this as final: no. I would back it as the pilot baseline once items 1 to 4 are in.