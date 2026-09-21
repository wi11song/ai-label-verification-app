# Software Requirements Document
# AI-Powered Alcohol Label Verification App (Prototype)

**Source:** Take-home discovery notes (Compliance Division)  
**Scope:** Standalone proof-of-concept. No COLA integration.  
**Priority:** Working core + clean code over incomplete extra features.

---

## 1. Problem

TTB agents review ~150,000 label applications/year. Much of the work is matching label artwork to application data (brand, ABV, warning, etc.). A prior scanning pilot failed because it was slower than visual review.

---

## 2. Users

| Persona | Need |
|---|---|
| Compliance agents (mixed tech skill; ~half over 50) | Fast, obvious UI; no hunting for buttons |
| Peak-season reviewers | Batch process 200–300 applications |
| IT (Azure, restricted outbound network) | Local/self-contained processing where possible; no sensitive storage |

UX bar: **a 73-year-old who recently learned video calling should be able to use it.**

---

## 3. In Scope / Out of Scope

**In scope**
- Upload label image(s) and corresponding application field values
- Extract label text/fields with AI/OCR
- Compare extracted fields to application data
- Report match / mismatch / needs-review per field
- Single-label and batch verification
- Deployed prototype + source repo

**Out of scope**
- COLA / .NET system integration
- FedRAMP, PII, document retention, production security
- Replacing agent judgment for nuanced compliance decisions
- Full TTB rule engine by beverage type (beer vs wine vs spirits exceptions)

---

## 4. Functional Requirements

### 4.1 Upload & Input
- FR-1: User can upload a label image (photo or scan).
- FR-2: User can enter (or upload) application data to compare against: brand name, class/type, alcohol content, net contents, government warning (and optionally bottler name/address, country of origin).
- FR-3: User can run verification on a **single** label.
- FR-4: User can **batch-upload** many labels + application records (target: 200–300 items).
- FR-5: System accepts imperfect images as a stretch goal (angle, glare, poor lighting); if unreadable, fail clearly and ask for a better image.

### 4.2 Extraction
- FR-6: System extracts these fields from the label when present:
  - Brand name
  - Class/type designation
  - Alcohol content (e.g. `45% Alc./Vol. (90 Proof)`)
  - Net contents (e.g. `750 mL`)
  - Government Health Warning Statement
  - Name/address of bottler/producer (if present)
  - Country of origin (if present / imports)
- FR-7: Distilled-spirits sample like “OLD TOM DISTILLERY / Kentucky Straight Bourbon Whiskey / 45% Alc./Vol. (90 Proof) / 750 mL / standard warning” must be supported.
- FR-8: If a field cannot be read, mark it **unreadable** (do not silently treat as a match).

### 4.3 Comparison Rules
- FR-9: **Brand name** — treat case/styling differences as the same (e.g. `STONE'S THROW` vs `Stone's Throw`). Flag only genuine wording differences.
- FR-10: **Alcohol content** — application value must match the number/unit on the label.
- FR-11: **Class/type, net contents, bottler, origin** — report match vs mismatch; exactness may be normalized (whitespace, punctuation) but wording changes are mismatches.
- FR-12: **Government warning** — **word-for-word exact**:
  - Must include `GOVERNMENT WARNING:` in **ALL CAPS**
  - That prefix must be **bold** when the image allows detecting emphasis; the remaining statutory text must **not** be bold
  - Remaining statutory text must match exactly (no rewording, title case, smaller/buried text workarounds)
- FR-13: Overall result per label: **Pass** | **Fail** | **Needs review** (unreadable or ambiguous).
- FR-14: Per-field results shown: application value, extracted value, status, short reason.

### 4.4 Results & Workflow
- FR-15: Results appear without extra navigation (single obvious primary action: upload → verify).
- FR-16: Batch run shows a progress list and a summary (counts of pass / fail / needs review).
- FR-17: User can inspect any batch item’s field-level diffs.
- FR-18: Errors (bad file, timeout, unreadable image, missing application data) are plain-language and recoverable.

---

## 5. Non-Functional Requirements

- NFR-1 **Latency:** Single-label result in **~5 seconds**. Slower than this is a failed UX (prior vendor at 30–40s was abandoned).
- NFR-2 **Usability:** Large, labeled controls; one primary path; no hidden menus; readable status colors + text (not color-only).
- NFR-3 **Network:** This applies to any future integration into TTB's own network, not to the publicly deployed prototype itself. If TTB later hosts this behind its restricted outbound firewall, prefer processing that works within it (avoid hard dependency on cloud ML endpoints that may be blocked); document any external API dependency and a degraded/offline path.
- NFR-4 **Data:** Prototype stores **no PII / no sensitive application data** long-term. Transient processing only.
- NFR-5 **Standalone:** No auth against COLA; no write-back to government systems.
- NFR-6 **Reliability:** Batch of hundreds should not hang the UI; failed items must not abort the whole batch.
- NFR-7 **Stack:** Any language/framework; choices should match prototype scope (simple, deployable).

---

## 6. Government Warning (Exact Text)

Use the statutory TTB health warning (verified against 27 CFR 16.21):

> **GOVERNMENT WARNING:** (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.

Fail if the prefix is not all-caps, not bold (when detectable), if the remaining text is bold, or if the body text is not exact.

---

## 7. Deliverables

- Source repository: all code, setup/run README, short write-up of approach, tools, assumptions, trade-offs.
- Public URL of a working prototype.

---

## 8. Implementation Priority

1. **P0 — Must have:** Single upload, extract core fields, compare, show pass/fail in ≤5s, dead-simple UI, error handling, deployed demo, repo docs.
2. **P1 — Should have:** Batch upload + per-item drill-down; fuzzy brand matching; unreadable-image handling.
3. **P2 — Nice to have:** Bold/caps detection on warning; skewed/glare images; class/type-specific TTB rules.

---

## 9. Assumptions (fill independently unless blocked)

- Application data is provided by the user (form or CSV/JSON) because COLA is not connected.
- “Match” for non-warning fields is semantic/normalized, not pixel-identical typography—except the warning, which is exact.
- Beverage-type exceptions (some wine/beer ABV rules) are not fully implemented; document the limitation.
- Prototype may use synthetic/generated test labels in addition to the bourbon example.
- If OCR cannot meet the 5s target, favor a faster local/hosted model over a more accurate but slower pipeline.
