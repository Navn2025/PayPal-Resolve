# Suggested README and status-doc updates (for Navneet)

The work on `feat/ai-part` (CHG-035 to CHG-060 in `docs/ENGINEERING_LOG.md`) changed
what is implemented. These files are yours, so they were not edited. The suggested
wording is below; keep, change or drop it as you see fit.

## README.md

1. **Development roadmap, "Add AI commitment extraction":** change the line to
   `- [x] Add AI commitment proposals (review-only; merchant accept step and live evaluation pending)`.
   - **Already built:**
     - **Extraction:** Groq extraction from the stored conversation, with
       masking and injection flags (CHG-035, CHG-044).
     - **Evaluation:** a labelled synthetic evaluation (CHG-036).
     - **Review:** a review panel that pre-fills the promise form.
   - **Why the wording matters:** proposals are never saved as promises
     automatically, so "extraction" alone would overstate it.
2. **Development roadmap, new items you may want to add:**
   - `- [x] Add broken-promise detection, missing-information checks and code-built remedy suggestions` (CHG-047, CHG-048, CHG-058)
   - `- [ ] Add a merchant accept step that turns a reviewed AI proposal into a promise in one action`
   - `- [ ] Run the live (account-backed) AI evaluation and finish the CHG-038 injection runs`
3. **"Evaluate complete resolution workflows":** a synthetic end-to-end harness
   now covers every metric in the README evaluation plan
   (`backend/evals/run_e2e_eval.py`; results in
   `backend/evals/results/e2e_2026-11-11.md`, 103/103 checks; CHG-061).
   Suggested line:
   `- [x] Evaluate complete resolution workflows (synthetic; Sandbox-backed run pending)`.
   You may prefer to keep it unticked until a Sandbox-backed run exists.
4. **Evaluation plan:** you could link `backend/evals/README.md`, which maps
   each metric to its synthetic check and states the limits.

## docs/BUILD_STATUS.md

- **"Not built: AI extraction or recommendations":** this no longer holds.
  Suggested wording: "AI extraction is review-only (proposals, not promises);
  remedy suggestions are code-built with an optional fact-guarded AI ranking.
  Not built: a merchant accept step for proposals, or a live AI evaluation."

## docs/PROJECT_STATUS.md

- **"AI extraction/evaluation … remain future work":** suggested wording: "AI
  proposals and a synthetic evaluation exist; a live evaluation and the
  merchant accept step remain future work."

## Already updated by us (no action needed)

- **`docs/ENGINEERING_LOG.md`:** open-work items 4 and 5 are corrected (CHG-060).
- **`backend/README.md`:** has a "Suggested remedies" section (CHG-058), because
  it documents new endpoints.
