# Ask Kartaa: in-app help bot (feature spec, v1)

Status: **proposed, no code yet.** Written by the Product Owner, Researcher and Designer roles for the owner's approval. Mocks: `docs/mocks/seller-portal-mocks-v15.html` (the "Ask Kartaa" control row). Decision entry: D-098 in `docs/DECISIONS.md`. Open items: "Ask bot" in `docs/OPEN_QUESTIONS.md`.

## 1. What it is

A floating **Ask Kartaa** button at the bottom right of every signed-in screen. A user clicks it, types a question, and gets a **short** answer (about 3 sentences, 60 words at most) about either:

1. **How the GST portal works** (returns, GSTR-1, GSTR-3B, QRMP, IFF, IMS, 2A/2B and similar), answered from the GST Portal Tutorial pack, or
2. **How to use Kartaa** (our own help text).

When the answer would be long, the bot gives one or two lines and a **"Read more on GST portal"** link instead of a long reply. It never gives tax or legal advice, never reads the user's business data, and says plainly when it does not know.

### Non-goals (v1)
- No tenant data in or out: the bot does not know the user's GSTIN, invoices, periods, frequency or plan.
- No actions (it cannot create invoices, change settings or file anything).
- No live portal status, no live due dates, no law/section/rate answers (those go to "ask your CA").
- Web only. No landing-page bot (needs anonymous abuse limits; later). English answers (Hinglish questions are accepted; Hindi answers later).
- No chat history stored for the user to revisit (the conversation lives in the page and is cleared on sign-out).

## 2. Hard constraints this design obeys

| Rule | How |
|---|---|
| D-094 India only | Search runs inside our own Mumbai app. Any model call goes only to a Bedrock model **in ap-south-1/ap-south-2**, through the existing pinned client (`platform_common.aws.bedrock_client`) and model-id guard (`bedrock_model_in_india`). No cross-region or global inference profile. No third-party chat/AI SaaS. A typed question can contain tenant data by accident, so it is treated as tenant data: stored and processed in India only. |
| Rule 8 server-side scoping | Route is business-scoped (`POST /api/v1/b/{id}/ask`), needs a signed-in active member, rate-limited per user and per business. The flag is also checked on the server (off means 404). |
| Rule 12 no invented facts | The bot may state a figure or date only if it comes from a retrieved passage, and then shows that passage's source. The pack contains conflicts (e.g. B2C-large threshold, see QUICKFACTS), so on figure questions the answer carries "per the GST portal guide, check the portal for your period" and the link. Kartaa's own deadlines come from refdata on Home, not from the bot. |
| Rule 13 no new ops complexity | No new service and no vector database. One module inside the existing app; the search index is a file loaded in memory. |
| Rule 5 no false claims | The bot never says it checked the live portal. Footer states answers are from guides as of the pack date. |

## 3. Knowledge base

### 3.1 Sources
- **GST portal pack**: 83 PDFs from `GST Portal Tutorial.zip` (44 FAQ, 38 Manual, 1 GSTR-9C offline-utility doc by our own count; the expert thread counts 41/41/1, reconcile in the build step), about 216k words, 2,346 PDF pages. Text is extracted already (`team/gst-portal-expert/corpus/`, index in `INDEX.md`).
- **Kartaa help**: 40 to 60 short entries written by the Product Owner from the BRD and the mocks (what each screen does, what we do and do not do, plans, "we do not file for you"). Lives in the repo (`app/.../ask/help/*.md`), reviewed like docs. This is our own text and safe to commit.

### 3.2 What the pack does not cover (the bot must say "not in the guides")
Per the expert thread's gap list: the Returns Offline Tool guide and GSTR-1 JSON schema/error file, registration, payments and ledgers (PMT-06, refunds), e-invoice/IRP and e-way bill system manuals, notifications and due-date extensions, newest GSTR-1 JSON field changes. These are the questions our users are most likely to ask next, so adding them (Pankaj downloads them from the portal) is a v1.1 content item, not a blocker.

### 3.3 Chunking and citations
- One chunk per **FAQ question** (with its number) or per **manual step heading** (with its section letter). Target 150 to 350 words, never split a numbered step list. Estimate 1,000 to 1,500 chunks.
- Metadata per chunk: `source_title` (breadcrumb such as "FAQs > Form GSTR-3B"), `kind`, `question_or_section` (e.g. "Q5", "Section B"), `file_sha256`, `pack_date`, `url`.
- **URLs: per-topic deep links, verified, never invented.** The PDFs carry no per-page URL (printed from a browser; only 12 URL strings in the whole pack), so the links come from the live tutorial table of contents. The GST portal expert thread read it on 2026-11-19 and verified a link for each of 42 tutorial topics (Manual and FAQ pages), in `team/gst-portal-expert/URLS.md`. The pattern is `https://tutorial.gst.gov.in/userguide/returns/index.htm#t=<page>.htm`, and each page also loads directly at `https://tutorial.gst.gov.in/userguide/returns/<page>.htm`. `refdata/ask_bot/sources.yaml` maps each pack document (by its breadcrumb title and sha256) to that topic's URL, seeded from `URLS.md`. **Three entries have no page yet** (the GSTR-3B FAQs, GSTR-9 FAQs and GSTR-9A FAQs rows are empty in `URLS.md`); until a person fills them, those documents use the index URL `https://tutorial.gst.gov.in/userguide/returns/index.htm` and the answer still shows the document title and question/section number. Where a topic has several pack files (for example the two Nil GSTR-1 SMS FAQ parts), the mapping names the exact page, and a document with no verified row falls back to the index URL, never a guess. The build fails if a mapped page does not load (link check against `tutorial.gst.gov.in`; it sends no tenant data), and the check is re-run at every pack refresh because the portal can rename pages. The answer links to the topic page, not to a question inside it, so the question number stays in the source chip. The link a user sees comes from this metadata, never from model text.
- The user-visible link text is "Read more on GST portal". It opens in a new tab with `rel="noopener noreferrer"`.

### 3.4 Where the corpus lives (not in the repo)
The extracted text is government content whose reuse terms are unconfirmed (section 9, decision P3) and is 1.5 MB of text we do not need to review in PRs. So:
1. **Repo holds** only the builder script, the chunking rules, `sources.yaml` (title, expected sha256, verified URL) and the golden question set. No PDFs, no pack text.
2. **Private S3 bucket in ap-south-1** holds the pack text (uploaded by Pankaj or EM from the project folder). Not public, not replicated.
3. **Build step** (`make ask-index`, run by EM on a machine with the bucket, and by the deploy job): reads the bucket, chunks, writes `ask_index.bin` (chunks + search index, about 3 to 10 MB), checks every `sha256` against `sources.yaml`, and fails if a file is missing or changed. The index is a build artifact in the Mumbai deploy bucket, loaded by the app at cold start. A refresh is a new build, so the pack date shown to users is always the build's pack date.

## 4. Retrieval and answer options (Researcher)

The bot's question and the retrieved passages are the only inputs. Four options:

| # | Option | Quality | India-only | Cost | Ops |
|---|---|---|---|---|---|
| A | **Extractive only**: keyword search (BM25 plus a synonym list) returns the best passage's first 2 sentences and the link. No model. | Fair. Good on exact terms ("GSTR-3B nil"), weak on paraphrase and Hinglish. | Trivially yes | Zero | Lowest |
| B | **A, then a Bedrock model in Mumbai writes the short answer** from the top 4 passages. | Good. Handles paraphrase, trims to 3 sentences. | Yes if an in-region model exists (**unverified**, see below) | About 0.2 rupee a question (section 8) | Low |
| C | **B plus embeddings** (hybrid BM25 and vectors). | Best recall. | Needs an in-region embedding model or a self-hosted one | Small | Medium: embedding model to host or call; query embedding must also stay in India |
| D | Fine-tune or train | Not justified for 216k words. | n/a | High | High |

**Recommendation: ship A first, B behind a second flag, C only if measured need.**
- The mode is a refdata value `ask_bot.mode` = `off | extractive | generative`. Extractive mode costs nothing and cannot hallucinate, so it can go live first and is also the **fallback** when the model is down, throttled or not approved.
- Move to C only if the golden set (below) shows the correct source in the top 4 less than 85% of the time with BM25.
- **Bedrock availability in Mumbai is UNVERIFIED.** I could not reach the AWS documentation from this session. Before B is built, EM reads the AWS console in ap-south-1 (and ap-south-2) for: which Anthropic or other text models are on-demand **in-region** (not only via a cross-region inference profile, which D-094 forbids), their price per million tokens, and model access approval. Same practice as D-077: no model id or price is stored in code until read from the console. If no suitable in-region model exists, we stay on A (or choose self-hosting, a new decision).
- Owner decision D2 earlier chose free OCR over paid Bedrock for the invoice reader. B is a **separate paid-service decision** (P2 below).

### 4.1 Answer rules (system prompt and server checks)
1. Answer only from the supplied passages. If they do not contain the answer, say so (the "not covered" state). Never fill from memory.
2. At most 3 sentences and 60 words. If the passage answer is longer (a procedure with more than about 4 steps), give a one-sentence summary and set `long=true`, which makes "Read the full steps on GST portal" the primary button.
3. Always show the source chip: document title and question/section number. Product answers show "Kartaa help" and an in-app link from a fixed route allowlist.
4. No law, section number, rate, threshold or due date unless it is in the cited passage. For a figure, add "check the GST portal for your period".
5. Law or advice questions ("should I", "can I claim", "which rate applies to my goods", income tax): decline and say "ask your CA". No tax or legal advice.
6. Never say the portal's live state or that a return was filed.
7. Output is **plain text**: no markdown links, no HTML, no URLs from the model. The server removes any URL the model wrote, and attaches links from chunk metadata only.
8. **Blocked passages.** The bot cites only passages that are not on the CA expert's stale or conflicting list. That list lives in `refdata/ask_bot/blocked_passages.yaml` (source title, question or section, reason, who checked, date); the index build drops these chunks (they are never retrieved or quoted), and a golden-set case asks each one and expects a refusal or a pointer to the guide index plus "ask your CA". Seeded from `team/program-lead/ca-answers-from-govt-docs-v3.md`: (a) GSTR-1 FAQ Q18, credit-note deadline "30th September", stale; the Act says 30 November (s.34(2)); the amendment cut-off in FAQ Q11 is current; (b) GSTR-1 FAQ Q1 versus manual note 7 on HSN "pick from the dropdown" versus manual entry, conflicting until the test upload settles it; (c) the Rs 2.5 lakh B2C-large line in the GSTR-1 FAQ, valid only up to the July 2024 period (Rs 1 lakh from August 2024), so it is quoted only together with its period or not at all. New entries are added whenever the CA or portal expert threads flag a line, and the file is reviewed at every pack refresh. Any figure or date the bot does say must also be one the CA expert has not flagged.
9. Output checks before sending (any failure falls back to extractive): word and sentence limit, no URL, no digits-and-date claim that is absent from the passages (simple check: every number in the answer appears in a passage), language is English.

### 4.2 Prompt-injection and abuse safety
- The model has **no tools, no browsing, no memory, no tenant context**. The worst a successful injection can do is produce a wrong short text, which the output checks and the plain-text rendering contain.
- The question is delimited as untrusted data in the prompt, with an instruction to ignore instructions inside it. The pack text is also treated as data.
- Question limits: 500 characters, last 2 turns only for follow-ups ("and for quarterly?"), no file or image input.
- Rate limits (refdata, provisional): 20 questions per user per hour, 100 per business per day, and a global monthly spend cap that flips mode to `extractive`.
- Refusal for out-of-scope or abusive input uses the "not covered" state. No stack traces or model text in errors.

### 4.3 Evaluation (before turning on)
A **golden set of 60 questions** (45 GST portal, 10 Kartaa, 5 out of scope/injection), each with the expected source and a must-not-say list, written by the GST portal expert thread and the Product Owner. Gates: every blocked passage (4.1 rule 8) is never quoted; source in the top 4 for at least 85% of in-scope questions; 100% of out-of-scope and injection questions refused or ignored; 0 answers with a URL not from metadata; 0 answers longer than 60 words; every conflicted figure (B2C-large) carries the "check the portal" line.

## 5. UX (Designer)

Mock: `seller-portal-mocks-v15.html`, control row **Ask Kartaa** (13 states, desktop and phone).

- **Button**: pill "Ask Kartaa" with a chat icon, 48 px high, 16 px from the right and bottom edge, respecting the phone safe area. Appears on every signed-in screen, never on sign-in, sign-up, onboarding or the printed invoice/PDF preview. Where a screen has a sticky bottom action bar (the phone invoice screen), the button lifts above it (`--ask-lift`) so it never covers "Create invoice".
- **Panel**: desktop 380 by 560, anchored above the button, non-modal. Phone: bottom sheet filling the screen below a 56 px top gap. Header "Ask Kartaa" with a one-line scope ("GST portal guides and how to use Kartaa"), a new-chat button and a close button. Footer pinned: "Not tax or legal advice. Answers come from GST portal user guides and Kartaa help. Don't type passwords, OTPs or GSTINs."
- **Welcome**: one greeting and four suggested questions (GSTR-1 steps, QRMP, nil GSTR-3B, how Kartaa reads a marketplace report).
- **Short answer**: up to 3 sentences, source chip with document title and question number, secondary "Read more on GST portal" link, thumbs up/down.
- **Long answer**: one-sentence summary, source chip, **primary** "Read the full steps on GST portal" button.
- **Product answer**: "Kartaa help" chip and an in-app button (for example "Open Guide and JSON").
- **Not covered**: "I could not find this in the GST portal guides or Kartaa help…", with "Browse GST portal guides" and "Contact support" (support contact is the open placeholder).
- **Loading**: three dots with `role=status`. After 8 seconds, "Still looking" and a Cancel button. A 20 second server timeout becomes the error state.
- **Error**: "Something went wrong on our side. Your question is saved in the box below." with Try again. Question text is kept.
- **Offline**: input disabled, "You are offline", draft kept, re-enabled on reconnect.
- **Rate limit**: says when to try again and offers the guide index.
- **Session ended**: same pattern as the invoice preview: "Sign in again", draft kept, returns to the same screen.
- **Flag off**: the button is not rendered at all.
- **Accessibility**: button is a real `<button>` with `aria-expanded` and `aria-controls`; panel `role=dialog` named by its title; focus moves to the input on open and back to the button on close; Esc closes; new answers arrive in an `aria-live="polite"` region; all targets at least 40 px (44 px for input and Ask); contrast uses the existing tokens in light and dark; animation off under `prefers-reduced-motion`; text wraps at 200% zoom; works at 320 px width.
- **Conversation**: in memory only, cleared on sign-out or New chat. Nothing is put in `localStorage`.

## 6. Product requirements (Product Owner)

### 6.1 User stories and acceptance criteria
| ID | Story | Acceptance criteria |
|---|---|---|
| AB-1 | As a seller I can open the bot from any screen. | Button visible bottom right on all signed-in screens when the flag is on; opens the panel; Esc and close return focus to the button; hidden on auth, onboarding and invoice print. |
| AB-2 | I get a short GST portal answer. | Answer at most 3 sentences and 60 words; shows document title and question/section number; shows "Read more on GST portal"; link host is `tutorial.gst.gov.in`. |
| AB-3 | For a long procedure I am sent to the guide. | If the best passage is a procedure of more than about 4 steps the reply is one sentence plus a primary link; no step list is typed out. |
| AB-4 | I can ask how Kartaa works. | Product questions answered from Kartaa help only; shows "Kartaa help"; in-app links limited to an allowlist of routes. |
| AB-5 | It tells me when it does not know. | Below the retrieval threshold, or out of scope, shows the not-covered reply with the index link and support contact; never guesses. |
| AB-6 | It does not give tax or legal advice. | Law, rate, eligibility and "should I" questions get the "ask your CA" reply; the golden set has at least 10 such cases that must pass. |
| AB-7 | My business data is not used or leaked. | Request to the model contains only the question, last 2 turns and passages; a test fails the build if any tenant field, GSTIN pattern or business id reaches the prompt; GSTIN/PAN/email/phone patterns in the question are masked before storage. |
| AB-8 | It works when things go wrong. | Offline, error, slow, rate-limit and session-ended states behave as in the mock; question kept; a model failure falls back to extractive, not an error. |
| AB-9 | I can say if an answer helped. | Thumbs up/down stored with the question id; no free text in v1. |
| AB-10 | The owner can switch it off or control cost. | Flag `ask_bot.enabled` and `ask_bot.mode` in refdata; off means no button and the API returns 404; spend cap forces extractive. |
| AB-11 | Staff can see how it is doing. | Per-day counts of questions, not-covered rate, thumbs-down rate, fallback rate, average latency, and cost; no per-user question browsing UI in v1. |

### 6.2 Logging and privacy
- Table `support.ask_log` (tenant-scoped like the other business tables, in Mumbai): id, business id, user id, time, mode, masked question, source ids shown, answer length, latency, thumbs, outcome (answered, not_covered, refused, error, fallback). The model's answer text is **not** stored (it can be rebuilt from source ids). Retention 90 days (provisional), then deleted by a job.
- Masking before write: 15-character GSTIN, PAN, email, phone and any run of 9 or more digits become `[masked]`.
- Bedrock model-invocation logging stays off or goes only to a Mumbai bucket; nothing is sent to analytics or error-tracking tools with the question text.
- The question is never part of an audit-log entry (this is not a financial or stock record).

### 6.3 Feature flag and scope limits
- Build-time `FEATURES.askBot` (web) plus server refdata `ask_bot.enabled` and `ask_bot.mode`. A hidden route is not needed (it is a widget); the API route returns 404 when off.
- Default at ship: `enabled=false`. First turn-on: `mode=extractive`.

### 6.4 Release placement (web only)
**Recommendation: its own track, shipped with R2 (alongside invoicing), not a blocker for R1 or any other release.** Reasons: R1 scope and tests are settled and the bot is not needed to file; the bot's best value is when users have invoices and GST questions together; the build needs a tenant-safe route and a new module, which is one team's work in parallel with the invoice flow. Slices:
1. **S1 (extractive, no cost)**: index builder, `ask` module and route, rate limits, logging, flag, web widget, Kartaa help entries, golden set, tests. Turn on for Pankaj's tenant first.
2. **S2 (generative)**: after P2 is approved and the console check passes: Bedrock call behind `ask_bot.mode=generative`, output checks, spend cap.
3. **S3 (content and later)**: add the missing pack documents (3.2), fill the three empty deep links, optional embeddings (C), landing-page bot.

## 7. Technical shape for the EM (non-binding, decided at build)
- Module `app/src/app/modules/ask/` (or `support`), no new service. Route `POST /api/v1/b/{id}/ask`, body `{question, history?: [{q,a_id}], screen?: enum}`, response `{answer, long, sources: [{kind, title, ref, url|route}], id}`. The `screen` hint is a fixed enum (for example `filing.uploads`) used only to bias retrieval; it is not tenant data. `POST /api/v1/b/{id}/ask/{id}/feedback`.
- Idempotency: a question is a read; no `Idempotency-Key` needed, but a retry must not double-count against the rate limit (use the client request id).
- Route changes need `make openapi` and committed `app/openapi.json` and `web/src/api/schema.d.ts` (CI runs Python 3.12).
- Tests needed (definition of done): tenant isolation (a user of business A cannot post to business B's route), flag off returns 404, rate limits, no-tenant-data-in-prompt test, region guard test (model id and ARN), URL allowlist, output checks, golden-set run (retrieval only; generative runs are manual and recorded), web states from the mock, accessibility checks (axe) on the panel, phone layout with the sticky bar.
- CI scan `india_only.py` already blocks non-India hosts; add the Bedrock call site to its allowlist review.

## 8. Cost per question (illustrative, not a quote)
Mode A costs nothing beyond the app. For mode B, per question about 1,500 input tokens (instructions, 4 passages, question) and 120 output tokens. Cost = 1,500 × input price + 120 × output price. **Placeholder prices** of USD 1 and USD 5 per million tokens give about USD 0.002, roughly 0.2 rupee per question; 1,000 questions a month is about USD 2. Real prices come from the AWS console (decision P2). Even at 10 times this, cost is small next to the 999-rupee plans; the per-business daily cap and monthly spend cap bound the worst case.

## 9. Decisions only Pankaj can make (recommended defaults)

| # | Decision | Recommendation |
|---|---|---|
| P1 | Name and label of the button. | "Ask Kartaa" (product name per CEO decision; one-line change in `brand.ts`). |
| P2 | Allow a **paid** Bedrock model in Mumbai for generative answers (S2), with a monthly cap? | Yes, cap USD 10 a month to start, only after EM confirms an in-region model and price in the console. Until then run extractive. |
| P3 | **GSTN/GST portal content reuse terms.** May we store derived chunks of the tutorial text and show short quoted or paraphrased passages with attribution? I could not read the portal's terms from this session. | Treat as **not confirmed**. Until confirmed: keep text out of the repo, store it only in the private Mumbai bucket, show at most 3 sentences per answer, always attribute and link to the source, and do not publish the corpus. Pankaj (or the GST CA expert thread, from the govt documents) checks the portal's copyright/terms page and records the answer. This blocks turning the bot on for customers, not the build. |
| P4 | Provide the missing pack documents (3.2): the offline tool guide and JSON schema, registration, payments, e-invoice and e-way bill. (Deep links no longer need the owner; see 3.3.) | Yes, before S3. Not needed for S1. |
| P5 | Release placement. | Own track, ships with R2, non-blocking. |
| P6 | Support contact shown in the "not covered" state. | Reuse the open support-contact placeholder; the bot hides the button until one exists. |
| P7 | Log retention for questions. | 90 days. |
| P8 | Who sees the bot: all signed-in members, or owners only? | All members. |

## 10. Risks
- **Stale or conflicting guidance.** The pack is a snapshot (about late 2025 by its own text) and conflicts with itself on some figures. Mitigation: pack date shown, figure rule 4, refresh by rebuild, golden set re-run.
- **A wrong answer read as advice.** Mitigation: not-advice footer, "ask your CA" rule, link to the source, thumbs feedback, and extractive fallback.
- **Typed tenant data.** Mitigation: warning text, masking, India-only processing, short retention.
- **Model not available in India.** Mitigation: mode A stands on its own.
- **Corpus reuse terms.** Mitigation: P3.
