# UNESCO Educational policy — scoped integration candidate

Repository: `Konstellation-Publisher`  
Windows path: `C:\mycode\Konstellation\Konstellation-Publisher`  
Role: `optional_delivery_adapter`

This file is a **non-normative pilot integration record**, not a claim of interoperability or a public release. The 41 UNESCO concepts are **seed membership**, not 41 canonical KQ or 41 published articles. The 36 Wikidata P3916 candidates remain unreviewed. The Wikipedia EN SQL index and compressed XML remain local on D:; this repo must not redistribute them.

**Consumes:** `externally_approved_immutable_publication`.  
**Produces:** `controlled_deployment_result`.

**Next correction:** Optional routing only; never treat local build success as public release authorization.

## Mandatory invariants

- **One branch Kristal** `unesco-mt1-10`; 41 starting concepts; individual multilingual encyclopedia articles are **projections**, not distinct Kristals or copies/translations of Wikipedia.
- KQ/KP/KA/KS require their own native provenance and appropriate canonical review. QID and UNESCO identifiers remain external. An AI suggestion or Wikipedia reference does not create canonical KA or KS.
- The 14 requested locales are an **objective**, not proof of GF/SemantiK/Spek qualification or 574 completed articles.
- Never enable GitHub synchronization, Pages, wiki upload or public mode based solely on this pilot manifest. C1/C2/C3/C4 authorizations remain external and blocked.
- All source readings and candidate handoffs are local or explicitly chosen; never rewrite D: source dumps, framework pins, existing Kristal commitments, or private databases.

An additive contract smoke test is at `tests/test_unesco_mt1_10_handoff.py`; run it without touching existing repository semantics.
