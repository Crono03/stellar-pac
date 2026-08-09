# stellar-pac — project brief

**Recurring investment plans (DCA) as an immutable Soroban contract, executed by a permissionless keeper.**

Repository: [github.com/Crono03/stellar-pac](https://github.com/Crono03/stellar-pac) · Apache-2.0
Status: deployed and verified on testnet · not audited · not on mainnet

---

## The problem, from a measurement rather than an intuition

Buying **€5** of an ETF through a retail broker cost **€1 in commission** — 20% of the capital. The order cost is not a parameter to optimise, it is a **binary filter**: either it is zero, or you do not contribute at all. At €1 per order, a contribution only makes sense above **€200**.

That threshold excludes exactly the people for whom small, regular accumulation matters most.

## What this does

A user creates a plan — *every month, convert 10 EURC into XLM* — funds it, and it runs. No account to open, no counterparty holding the funds, nobody who can close it.

| | Cost per execution | Minimum sensible size |
|---|---|---|
| Retail broker, manual order | €1.00 | €200 |
| **This contract** | **€0.011** | **€2.22** |

## The constraint that defines the design

**Soroban has no scheduler.** No contract can wake itself: something outside must call it.

That constraint *is* the product. If Soroban had cron, a DCA contract would be trivial and would already exist several times over. Solving the trigger problem well is the whole value.

The answer is a **permissionless keeper**: `execute()` is public, anyone may call it, and whoever does collects a fee taken from the plan. No privileged operator, no server that must stay alive, no off switch.

**The invariant: only the owner can move value out of a plan to an address of their own.** A keeper can trigger an execution and collect the pre-set fee — nothing else.

## What already exists

Not a proposal. A working system, verified on a live network.

| | |
|---|---|
| Contract | complete, 14 tests, financial lint set clean under `-D deny` |
| Keeper | working; simulates before submitting so it never pays for a failing transaction |
| Testnet | full cycle executed through the **real Soroswap router** |
| Events | all five lifecycle events, plan id as a topic |
| Threat model | STRIDE, **no open items**, no exploitable vulnerability identified |

A real execution: 5 XLM taken from budget, 0.1 to the keeper, **4.9 swapped**. At the pool's reserve ratio the expected output was 0.5006 USDC; **0.4994 arrived**. The difference is the pool's own 0.3% fee. The accounting closes to the cent.

## What it does not claim

**It is not cheaper than a free broker savings plan.** If your broker offers a zero-fee recurring plan on an asset you want, use it.

A Soroban contract **cannot reach the classic Stellar DEX** — no path payments, no order books. It must trade on a Soroban venue, and those price about **0.49% worse**, measured on both venues simultaneously. With the keeper fee, cost per execution is ~0.71%.

What it offers instead: assets a broker will not list, **non-custodial** holding, **permissionless** access with no onboarding, and no counterparty who can close the plan or offboard the user.

## Why it is built the way it is

**Immutable — no admin key, no upgrade path, no developer fee.** MiCA Recital 22 excludes services provided "in a fully decentralised manner without any intermediary"; admin keys, upgrade keys and fee extraction all put a protocol back in scope.

The consequence is deliberate and worth stating plainly: **this contract can never generate protocol-fee revenue.** It is infrastructure, not a business, and its sustainability has to come from somewhere other than rent-seeking on its users.

## What funding would build

The contract is finished. Funding would not pay for it — it would pay for the three things that turn a working contract into ecosystem infrastructure:

1. **Multi-venue routing.** Today a plan is pinned to one venue. Quoting across Soroswap, Phoenix and Aqua at execution time would attack the product's single largest cost, the 0.49% venue spread.
2. **An integration library.** So any Stellar wallet can offer recurring plans without reimplementing this. The contract is a primitive; today nothing makes it easy to consume.
3. **Public keeper infrastructure.** Below roughly 6,755 executions per month no third party has an economic reason to run a keeper, so today the owner runs their own. Shared, observable keeper infrastructure is what makes the "nobody needs to be online" claim true in practice rather than only in principle.

## Honest gaps

- **No audit.** The Stellar Audit Bank requires SCF funding first.
- **No Soroban-specific static analysis.** Scout does not support soroban-sdk 27; worse, on a build-script panic it reports `Analyzed / 0` — a false clean, established by planting a defect it is built to detect. Five workarounds are documented in the repository, and the issue is worth reporting upstream.
- **No users.** The contract works; nobody uses it yet.
- **Plans are public.** Anyone can read amounts, cadence and remaining budget: a recurring plan is a readable behavioural profile.

## About the author

Solo builder. First Soroban project. Every design decision in this repository has a measured number behind it rather than an intuition — TTL constants read from the network, the MEV threshold computed against real liquidity, the venue spread measured on both venues at the same instant. Several of those measurements **overturned an earlier assumption**, and the repository documents the corrections rather than the conclusions alone.

That is the strongest claim available here, and it is deliberately not a claim about track record: there isn't one yet.
