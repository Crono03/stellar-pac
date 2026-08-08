# Threat model — STRIDE

Scope: `contracts/pac/src/lib.rs`.
Actors: **owner** (creates and funds a plan), **keeper** (anyone, calls `execute`), **external router**, **token contract** (SAC).

Last reviewed: 2026-08-08. **This document must be updated whenever the contract changes**, otherwise it describes a program that no longer exists.

---

## S — Spoofing

| Threat | Status | Defence |
|---|---|---|
| Impersonating the owner to withdraw | **covered** | `withdraw` and `cancel` call `plan.owner.require_auth()`; the owner is read from storage, never from an argument |
| Impersonating another keeper to steal its fee | **not applicable** | the fee goes to the caller; there is no keeper registry to impersonate |
| An asset impersonating a legitimate one | **transferred to the owner** | the contract never resolves an asset by code. As of 2026-08-08, 66 distinct issuers use the code `EURC`, with active typosquatting. The issuer address is a per-plan parameter: the owner pins it and carries the risk |

## T — Tampering

| Threat | Status | Defence |
|---|---|---|
| Altering amount, interval or destination of someone else's plan | **covered** | no mutation function exists; parameters are fixed at creation |
| Keeper redirecting the output to itself | **covered** | destination is read from storage; the keeper supplies only its own address, and only for the fee |
| An admin changing the rules | **impossible by construction** | no admin, no upgrade path |
| A malicious router draining the whole budget | **covered** | authorisation is built for a **single** transfer, of an exact amount, to the declared pair — not an open-ended approval |

## R — Repudiation

Not materially relevant: everything is on-chain and verifiable, and token transfer events are emitted.

**Known gap**: the contract emits no events of its own for `create_plan` / `execute` / `cancel`, so a plan's history must be reconstructed from invocations. Cheap to add; planned before mainnet.

## I — Information disclosure

| Threat | Status |
|---|---|
| Plans and budgets are **public** | **accepted, not mitigable** |

Anyone can call `get_plan` and see how much an address accumulates, how often, and what remains. This is chain transparency rather than a contract defect — but it must be stated to users: **a recurring plan is a behavioural profile readable by anyone.**

## D — Denial of service

| Threat | Status | Notes |
|---|---|---|
| **Nobody executes the plans** | **real, unsolved** | below ~6,755 executions/month no third party has an incentive. Initially the owner runs their own keeper |
| A wrong `pair` blocks every execution | **fails safe** | the authorisation does not match the transfer the router attempts, so the transaction reverts and no funds move. The owner can always `cancel` and recover everything |
| Budget exhausted → entry archived → remainder stuck | **real, partly mitigated** | mitigated by the interval cap (~129 days, under `min_persistent_ttl` of ~134 days) and by TTL renewal on every write. The residual case is a plan neither executed nor cancelled for over 134 days |
| External router deprecated or drained | **real** | `execute` fails; the owner can `cancel` and recreate the plan on another router. No loss, only interruption |
| Missing trustline on the destination asset | **real** | the final forward fails and the whole execution reverts. Should be checked at plan creation rather than discovered at first execution |

## E — Elevation of privilege

| Threat | Status |
|---|---|
| Keeper acquiring owner privileges | **covered** — `execute` touches neither `owner` nor destinations |
| Reentrancy from the router back into the contract | **not applicable: the platform forbids it** |

> **A correction worth keeping.** An earlier revision of this document classified reentrancy as *"the most serious vulnerability identified"*: `execute` writes state **after** the external swap, so a malicious router re-entering `execute` would find `budget` and `next_exec` stale.
>
> That reasoning is correct on EVM and **does not apply here**. Soroban does not permit reentrancy at the host level, an explicit architectural choice made precisely because reentrancy caused some of the largest thefts on other chains.
>
> No change was made as a result. Applying checks-effects-interactions anyway would be cargo cult — a defence against a threat the environment has already removed, imported out of habit from another platform. The entry is kept rather than deleted because an auditor will ask the same question and will find the answer here.

---

## Summary

**Covered**: owner spoofing, plan tampering, fund redirection by a keeper, open-ended router approvals.

**Accepted and disclosed**: plan visibility, asset choice resting with the owner, absence of keepers at low volume.

**To fix before mainnet** — both observability and UX gaps, not exploitable flaws:

1. **Emit contract events** for creation, execution and cancellation.
2. **Check the destination trustline** at plan creation.

**No exploitable vulnerability identified by this analysis.** That is a statement about this analysis, not a guarantee: it is exactly what an external audit exists to test.
