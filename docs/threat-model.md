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

**Covered as of 2026-08-08.** The contract emits its own events for all five state-changing operations: `created`, `deposited`, `executed`, `withdrawn`, `cancelled`.

The **plan id is a topic**, not payload, so a single plan's history can be filtered without scanning everything the contract ever emitted — which was the entire point of the gap this closes. Topic shape `(action, plan_id)`; payload carries the rest. `executed` also carries `next_exec`, so an observer can distinguish a caught-up plan from a late one without a second query.

Verified on-chain, not only in tests: `create_plan` on testnet emitted `[{"symbol":"created"},{"u32":0}] = [owner, 50000000, 2592000]`.

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
| Missing trustline on the destination asset | **covered 2026-08-09** | `create_plan` probes `balance(owner)` on the destination token. Without a trustline the call traps and plan creation fails immediately, instead of the problem surfacing at first execution |

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

**Fixed since the first revision**:

1. ~~Emit contract events~~ — **done 2026-08-08**, see *Repudiation*.
2. ~~Check the destination trustline at plan creation~~ — **done 2026-08-09**, see *Denial of service*.

**No open items remain from this analysis, and no exploitable vulnerability was identified.** That is a statement about this analysis, not a guarantee: it is exactly what an external audit exists to test.

### On the trustline check, because the obvious choice was wrong

The intuitive probe is `authorized(owner)`. It is the wrong one: `authorized` belongs to the **Stellar Asset** interface, so requiring it would break any plan whose destination is a native Soroban token, which has no such function. `balance` is in the **standard token** interface, exists everywhere, and on a Stellar Asset Contract happens to trap precisely when the trustline is missing.

Measured on testnet rather than assumed. Without a trustline, `balance` and `authorized` both fail with `Error(Contract, #13)`, *"trustline entry is missing for account"* — they do **not** return zero, which is what made a balance probe usable as a check at all.

Verified three ways on testnet: destination with a trustline succeeds; destination without one fails immediately at creation; **destination in native XLM still succeeds**, so the check does not reject valid plans.
