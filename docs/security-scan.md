# Self-service security scan

Required by the Soroban Audit Bank pre-audit preparation phase.

Target: `contracts/pac/src/lib.rs` · Rust stable 1.97.0 · soroban-sdk 27.0.5
Date: 2026-08-08

---

## Tools run

| Tool | Scope | Result |
|---|---|---|
| `cargo clippy` (default) | general correctness | 10 warnings, all stylistic |
| `cargo clippy` (financial lint set) | arithmetic, panics, unwraps, indexing | **7 findings, all fixed** |
| `cargo clippy` (pedantic) | style and documentation | cosmetic only, see *Not fixed* |
| `cargo-scout-audit` 0.3.16 | Soroban-specific detectors | **could not run — see F-03** |

Financial lint set:

```
-D clippy::arithmetic_side_effects
-D clippy::unwrap_used
-D clippy::expect_used
-D clippy::panic
-D clippy::indexing_slicing
```

---

## Findings and remediation

### F-01 — Unchecked arithmetic in 7 locations · severity: low · **fixed**

`clippy::arithmetic_side_effects` flagged seven operations:

| Location | Operation | Real risk |
|---|---|---|
| `create_plan` | `id + 1` | plan counter, u32 — would need 4·10⁹ plans |
| `deposit` | `plan.budget += amount` | i128 — bounded by tokens actually transferred |
| `execute` | `plan.amount - plan.keeper_fee` | guarded by `keeper_fee < amount` at creation |
| `execute` | `plan.budget -= plan.amount` | guarded by the budget check above it |
| `execute` | `plan.next_exec + plan.interval` | u64 timestamps — ~584 billion years of headroom |
| `withdraw` | `plan.budget -= amount` | guarded by `amount > plan.budget` |
| `swap` | `timestamp() + 300` | u64, same headroom |

**None were exploitable**, and `overflow-checks = true` in the release profile means each would have panicked rather than wrapped — a safe failure mode.

Fixed anyway, replacing all seven with `checked_*` returning a new typed `Error::Overflow`. Two reasons, neither cosmetic:

1. A **panic is an opaque failure**. A typed error tells a caller — including the keeper, which simulates before submitting — *why* an execution cannot proceed.
2. Three of the seven were safe only because of a guard **elsewhere in the code**. Relying on a distant invariant is how a later refactor introduces a bug silently. The check now sits next to the operation.

Verification: the full lint set passes with `-D` (deny), and all 12 tests still pass.

### F-02 — Documentation and style · severity: none · **not fixed**

`clippy::pedantic` reports missing backticks in doc comments, absent `# Errors` sections, and `create_plan` having 10 arguments against a threshold of 7.

Not fixed: the argument count is deliberate — every plan parameter is explicit precisely because the contract is immutable and has no configuration surface. `needless_pass_by_value` on `env: Env` is a false positive; Soroban requires that signature.

### F-03 — Scout cannot analyse a soroban-sdk 27 contract, and reports a false clean result · **unresolved, reported here**

Scout is the tool named by the Audit Bank's pre-audit phase. It **could not analyse this contract**, and — more importantly — **it did not say so**.

**What happens.** Scout 0.3.16 (latest; crates.io 2026-02-13, Docker `coinfabrik/scout:0.3.16`) runs dylint on a pinned `nightly-2025-08-07` toolchain targeting `wasm32-unknown-unknown`. The `soroban-sdk` 27.0.5 build script rejects that target outright:

> Rust compiler 1.82+ with target `wasm32-unknown-unknown` is unsupported by the Soroban Environment, use `wasm32v1-none` available with Rust 1.84+.

The build fails. Scout then prints its summary anyway:

```
| Crate | Status   | Critical | Medium | Minor | Enhancement |
| pac   | Analyzed | 0        | 0      | 0     | 0           |
```

**Status `Analyzed`, zero findings — on a build that never compiled.**

**How this was established, rather than assumed.** A `0/0/0/0` result on first run is indistinguishable from a genuinely clean contract, so it was tested with a canary: a `.unwrap()` was planted in `Pac::leggi`, matching Scout's own documented `unsafe-unwrap` detector. Scout reported `Analyzed` with **0 findings** again. The canary was then removed and the test suite re-verified.

A tool that reports a clean result on code containing a defect it is specifically built to detect is not producing a scan — it is producing a false assurance, which is worse than no scan at all.

**Attempted workarounds**: native `cargo install` fails earlier and for an unrelated reason (`curl-sys` and `libgit2-sys` need a C toolchain not configured on this Windows host). The Docker image gets further but hits the target incompatibility. No newer Scout release exists.

**Consequence for this project**: Soroban-specific detector coverage is currently **missing**, and that gap is stated rather than papered over. Downgrading `soroban-sdk` purely to satisfy the scanner was rejected: it would analyse a different contract from the one that is deployed and would be audited.

**Worth reporting upstream** to CoinFabrik as two separate issues — the SDK 27 incompatibility, and the summary reporting `Analyzed` after a failed build.

---

## Threat model

A STRIDE analysis is maintained separately in [`threat-model.md`](threat-model.md). It identified **no exploitable vulnerability**, and two gaps scheduled before mainnet:

1. No contract-level events for create/execute/cancel.
2. Destination trustline not verified at plan creation.

It also records a **retracted finding**: reentrancy was initially classified as the most serious issue, then withdrawn — Soroban forbids reentrancy at the host level. The entry was kept rather than deleted, because a reviewer will ask the same question.

---

## What this scan does not cover

Static analysis checks the contract in isolation. It does not cover:

- the behaviour of the **external router** the contract calls;
- **keeper competition** under concurrency;
- **economic** attacks — MEV is analysed separately, and the defence is trade size rather than code;
- assets with `auth_required` or clawback enabled.

Those need an external audit, which is what the Audit Bank exists for.
