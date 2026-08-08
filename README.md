# stellar-pac

Recurring investment plans (DCA) as an immutable Soroban contract, executed by a permissionless keeper.

You create a plan — *every month, convert 10 EURC into XLM* — fund it, and it runs. No account to open, no counterparty holding your money, nobody who can close it.

**Status: deployed and verified on testnet. Not audited. Not on mainnet.**

---

## The constraint this is built around

**Soroban has no scheduler.** A contract cannot wake itself up: something outside must call it.

That constraint *is* the product. If Soroban had cron, a DCA contract would be trivial and would already exist ten times over. Solving the trigger problem well is the whole value.

The answer here is a **permissionless keeper**: `execute(plan_id)` is public, anyone can call it, and whoever does collects a fee taken from the plan. No privileged operator, no server that must stay alive, no single point of failure.

**The invariant that never bends: only `owner` can move value out of a plan to an address of their own.** A keeper can trigger an execution and collect the pre-set fee — nothing else.

---

## Honest cost accounting

Every number below was measured, not estimated. Reproduce them with the scripts in `scripts/`.

### One-off, per plan

| | XLM | EUR |
|---|---|---|
| Upload contract WASM (10,183 bytes) | 0.698 | 0.099 |
| Deploy contract instance | 0.002 | 0.000 |
| **`create_plan`** | **11.281** | **1.600** |

Creating a persistent entry costs about a thousand times more than writing to one: you prepay rent for its whole lifetime. This one-off cost dominates the economics, and it means a plan makes sense from roughly **€150–300 of total lifetime contributions**, not from a single small payment.

### Per execution

| | Cost |
|---|---|
| Venue spread (Soroban DEX vs classic SDEX) | **0.49%** — structural, unavoidable |
| Keeper fee (3× network cost) | 0.22% on a €5 payment — **zero if you run your own keeper** |
| Slippage at €2–50 | 0.001%–0.054% |
| Ledger write | €0.002 |

### What this means

A Soroban contract **cannot reach the classic Stellar DEX** — no path payments, no order books. It must trade on a Soroban DEX, and those price about **0.49% worse** than the classic order books. Measured simultaneously on both venues to isolate the spread from price drift.

**So this does not compete on price with a free broker savings plan.** If your broker offers a zero-fee recurring plan on an asset you want, use it — it is cheaper.

What this offers instead: assets a broker will not list, **non-custodial** holding, **permissionless** access with no account and no onboarding, and no counterparty who can close your plan or offboard you.

---

## Interface

| Function | Who | What |
|---|---|---|
| `create_plan(...)` | anyone | registers a plan, caller becomes owner |
| `deposit(from, id, amount)` | anyone | adds budget |
| `execute(keeper, id)` | **anyone** | if due and funded: swaps, pays the keeper, advances the schedule |
| `withdraw(id, amount)` | owner only | takes back unspent budget |
| `cancel(id)` | owner only | stops the plan, returns everything |
| `get_plan(id)` / `due_plans()` | read-only | state, and which plans are ready |

Assets, router and pair are **per-plan parameters**, never contract constants — see *Immutability* below.

---

## Design decisions worth knowing

**Immutable, no admin key, no developer fee.** MiCA Recital 22 excludes services provided "in a fully decentralised manner without any intermediary". Admin keys, upgrade keys, fee extraction or an operated front-end all put a protocol back in scope. This contract has none. *This is not legal advice.*

Consequence: **this contract can never generate protocol-fee revenue**, and the asset cannot be a constant — if an issuer rotated, an immutable contract would be stuck. The owner pins their own asset when creating a plan.

**Asset identity is the owner's responsibility, deliberately.** On Stellar an asset is the pair *(code, issuer)*. As of 2026-08-08 there are **66 distinct issuers using the code `EURC`**, including active typosquatting (`circle-assets.com`, 8 billion fake supply, 154 holders). The contract never resolves an asset by code. Use `scripts/f0_liquidita.py` to identify a real issuer — the reliable signal is the **number of liquidity pools**, which impersonators cannot cheaply fake.

**MEV defence is size, not code.** A keeper chooses *when* to call and could sandwich the trade. Measured against real liquidity: below roughly **€200 per execution the attack costs the attacker more than it extracts** (at €5 the attacker loses €0.10). So: no oracle, no decaying fee, no added complexity. `min_out` stays as a guardrail against gross failure — illiquidity, a depeg — **not** as MEV protection. Above ~€200 per execution this defence stops holding, and that threshold belongs in user-facing documentation.

**The plan renews its own storage.** Soroban ledger entries expire. Because the product is recurring, every write extends the TTL — no separate keeper for renewals. `create_plan` therefore rejects intervals longer than ~129 days, staying under `min_persistent_ttl` (2,073,600 ledgers ≈ 134 days on mainnet) with margin, so a plan cannot archive itself between executions.

---

## Keeper economics, stated plainly

Per execution a keeper earns about **€0.0074** net. For an independent operator to bother, you would need roughly **6,755 executions per month**. With five monthly plans, keeper revenue is **four cents a month**.

**So at the start you run the keeper for your own plans** — and there the fee is not a cost, since you pay it to yourself.

The fee is not how the system runs. **It is what makes it survive your absence**: machine off, travelling, forgot — the plan does not skip, someone else executes it and is paid for the trouble.

---

## Build, test, deploy

```bash
cd contracts && cargo test              # 12 tests
stellar contract build                  # -> target/wasm32v1-none/release/pac.wasm
stellar contract deploy --wasm target/wasm32v1-none/release/pac.wasm \
  --source <identity> --network testnet

python keeper/keeper.py <CONTRACT_ID> <SECRET> --network testnet
```

Requires Rust **stable** (pinned in `contracts/rust-toolchain.toml`) and `stellar-cli` 27.x. The toolchain is pinned because a nightly build fails on a transitive dependency, in a way that looks like a bug in this code and is not.

### Measurement scripts

| Script | What it answers |
|---|---|
| `scripts/f0_liquidita.py` | who really issues an asset, and slippage on the classic SDEX |
| `scripts/f0bis_liquidita_soroban.py` | slippage on the venue a contract can actually reach |
| `scripts/f0_testnet.py` | account mechanics: trustlines, reserves, fees |

All read-only against public endpoints. No account, no cost.

---

## Verified on testnet

Contract `CBAIBHJIN5TALZM7KAUFETJFMHLVFKEJ6KPHUOSLF6LYOS544JE75FNV`, executing through the **real Soroswap testnet router**:

| | before | after |
|---|---|---|
| plan budget | 15 XLM | 10 XLM |
| next execution | now | **+30 days exactly** |
| owner's USDC | 0.4993884 | **0.9987756** |

5 XLM taken from budget, 0.1 to the keeper, **4.9 swapped**. At the pool's reserve ratio the expected output was 0.5006; 0.4994 arrived. The difference is the pool's own 0.3% fee.

This run was repeated after the source was translated to English and `eseguibili` was renamed to `due_plans`, to verify the rename had not broken the contract/keeper interface. It had not.

---

## Known gaps

- **No audit.** The Stellar Audit Bank requires SCF funding first.
- **No events of its own** for create/execute/cancel — a plan's history must be reconstructed from invocations.
- **Destination trustline is not checked at creation**, so a missing one surfaces at first execution instead.
- **Plans are public.** Anyone can read amounts, cadence and remaining budget. That is chain transparency, not a contract defect, but a recurring plan is a readable behavioural profile.

Threat model: [`docs/threat-model.md`](docs/threat-model.md) · Security scan: [`docs/security-scan.md`](docs/security-scan.md).

## License

Apache-2.0.
