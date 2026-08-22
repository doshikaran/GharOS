# Household Council protocol

Source: `GharOS_Build_Spec_v2.md` §12.3, `PHASES.md` §5.4.

```mermaid
flowchart TB
    T[Major decision trigger] --> CV[A41 Convener]
    CV --> P1
    subgraph P1[Phase 1 — ISOLATED independent reporting]
        direction LR
        F[A42 Finance<br/>ledger subgraph ONLY]
        C[A43 Care<br/>constraint subgraph ONLY]
        E[A44 Education]
        L[A45 Logistics]
    end
    P1 --> HC[Publish hard constraints<br/>ELIMINATE options, do not score]
    HC --> OG[Generate grounded options]
    OG --> D[A47 Delegates score from<br/>REAL valuation profiles]
    D --> ADV[A48 Adversary attacks leader<br/>using household history]
    ADV --> ARB[DETERMINISTIC mechanism arbiter<br/>NOT an LLM]
    ARB --> BR[Decision brief + explicit trade-off]
    BR --> H[Humans decide — R4 never auto-resolves]
    BR --> G[(DECISION + COUNCIL_POSITIONs<br/>permanent record)]
```

**Reading this diagram — read `GharOS_Build_Spec_v2.md` §12.2 before implementing anything here.** This is not multi-agent debate. Every agent in Phase 1 queries a *different subgraph* and reports *before seeing any other agent's output* — that isolation is what prevents conformity bias, and it is a structural design constraint, not a convention. The mechanism arbiter that resolves Phase 6 is deterministic code, never an LLM synthesizing a consensus. The word "debate" must not appear anywhere this diagram's design is discussed, in code, comments, or UI.
