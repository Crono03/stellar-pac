#![no_std]
//! Recurring investment plans (DCA), triggered by a permissionless keeper.
//!
//! Status 2026-08-08: complete, deployed and verified on testnet against the
//! real Soroswap router. Never on mainnet, never audited.
//!
//! Cost note, so it is not a surprise: this contract can only reach Soroban
//! venues, not the classic Stellar DEX, and there is a **structural 0.49%
//! spread** between the two, measured. With the keeper fee, cost per execution
//! is ~0.71%. **This does not compete on price** with a free broker savings
//! plan — it competes on access and non-custody. See `docs/security-scan.md`
//! and the README for the full accounting.
//!
//! # The three constraints that determined this shape
//!
//! 1. **Soroban has no scheduler.** No contract wakes itself up. Hence
//!    `execute` is public and whoever calls it is paid: no privileged
//!    operator, no server to keep alive, no off switch.
//!
//! 2. **Immutable, to stay outside the MiCA CASP perimeter.** No admin, no
//!    upgrade, **no developer fee**. Direct consequence on the code: there are
//!    no constants that would ever need changing. Assets, router and pair are
//!    **per-plan**, chosen by the owner. If an asset issuer rotated, the
//!    contract needs no upgrade — the owner cancels and recreates the plan.
//!
//! 3. **MEV defence is trade size, not code.** Below ~EUR 200 per execution a
//!    sandwich costs the attacker more than it extracts. `min_out` is NOT MEV
//!    protection: it is the guardrail that stops an execution at an absurd
//!    price, whatever the size.
//!
//! # The invariant that never bends
//!
//! **Only `owner` can move value out of a plan to an address of their own.**
//! A keeper can trigger an execution and collect `keeper_fee`, which the owner
//! set at creation. This is the first thing an audit should verify, and the
//! reason `withdraw` and `cancel` call `require_auth` while `execute` does not.

use soroban_sdk::{
    auth::{ContractContext, InvokerContractAuthEntry, SubContractInvocation},
    contract, contractclient, contracterror, contractimpl, contracttype, token, vec,
    Address, Env, IntoVal, Symbol, Vec,
};

/// The SoroswapRouter interface — only the part used here.
///
/// The exported name has no `router_` prefix, unlike `router_get_amounts_out`.
/// That is not a style choice: Soroban symbols are capped at **32 characters**
/// and `router_swap_exact_tokens_for_tokens` is 35, so that name cannot exist.
/// Verified by simulation on 2026-08-08.
#[contractclient(name = "RouterClient")]
pub trait RouterInterface {
    fn swap_exact_tokens_for_tokens(
        env: Env,
        amount_in: i128,
        amount_out_min: i128,
        path: Vec<Address>,
        to: Address,
        deadline: u64,
    ) -> Vec<i128>;
}

/// Storage keys. `Plan(u32)` is persistent: it must survive between executions,
/// and it is the entry whose TTL `execute` renews.
#[contracttype]
#[derive(Clone)]
pub enum DataKey {
    /// Incrementing counter of created plans.
    NextId,
    /// The plan itself.
    Plan(u32),
}

#[contracttype]
#[derive(Clone)]
pub struct Plan {
    /// The only address that can withdraw or cancel.
    pub owner: Address,
    /// Asset spent on each execution (e.g. EURC). SAC address.
    pub from: Address,
    /// Asset bought (e.g. XLM). SAC address.
    pub to: Address,
    /// Swap venue. A parameter and not a constant: see constraint 2.
    pub router: Address,
    /// The router's pair for (from, to). Supplied by the owner rather than
    /// looked up on the factory at every execution: saves a cross-contract
    /// call per run. If it is wrong, the authorisation does not match the
    /// transfer the router actually attempts and execution **fails**: a wrong
    /// value cannot divert funds, only block them.
    pub pair: Address,
    /// Amount to spend per execution, in units of `from`.
    pub amount: i128,
    /// Seconds between executions.
    pub interval: u64,
    /// Timestamp of the next permitted execution.
    pub next_exec: u64,
    /// Remaining deposited funds, in units of `from`. Decremented each run.
    pub budget: i128,
    /// Minimum acceptable `to` per execution. Guardrail, not anti-MEV.
    pub min_out: i128,
    /// Paid to whoever calls `execute`. Taken from `budget`.
    pub keeper_fee: i128,
}

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    PlanNotFound = 1,
    NotOwner = 2,
    NotDueYet = 3,
    InsufficientBudget = 4,
    InvalidParameters = 5,
    /// The swap returned less than `min_out`: the guardrail stopped execution.
    PriceOutOfBounds = 6,
    /// Arithmetic out of range. With `overflow-checks = true` these cases would
    /// panic anyway, so the failure would already be safe: using `checked_*`
    /// returns a **typed** error instead of an opaque panic, and makes the
    /// intent legible to a reviewer.
    Overflow = 7,
}

/// TTL renewal. Values read from mainnet on 2026-08-08, not estimated.
///
/// | network parameter | ledgers | days (at 5.59 s) |
/// |---|---|---|
/// | `max_entry_ttl` | 3,110,400 | 201.2 |
/// | `min_persistent_ttl` | 2,073,600 | 134.2 |
///
/// **Two earlier versions of these constants were wrong.**
///
/// The first used threshold 100,000 and extension 500,000, written believing
/// the minimum persistent TTL was 4,096 ledgers — a number taken from a
/// documentation example that actually concerned *restored* entries. Since
/// every write brings an entry to at least `min_persistent_ttl`, that threshold
/// was never reached, and had it fired it would have *lowered* the TTL. Code
/// that did nothing and looked prudent.
///
/// The second extended to the network maximum. That works, but rent is charged
/// in proportion to the TTL requested — measured at 5.55 XLM per million
/// ledgers — and `create_plan` cost **17.264 XLM**. Since `min_persistent_ttl`
/// is a floor any write reaches anyway, extending beyond it is pure expense.
/// Renewing to the floor instead of the ceiling: **11.281 XLM, -35%**, and the
/// entry still lives 134 days, well beyond the maximum interval allowed.
const TTL_THRESHOLD: u32 = 1_500_000;
const TTL_EXTEND_TO: u32 = 2_073_600;

/// Maximum interval allowed for a plan: **beyond this the entry would archive
/// between executions** and recovering the remainder costs a paid restore.
/// Kept under `min_persistent_ttl` with margin: 2,000,000 ledgers ≈ 129 days.
const MAX_INTERVAL: u64 = 2_000_000 * 5;

#[contract]
pub struct Pac;

#[contractimpl]
impl Pac {
    /// Registers a plan. The caller becomes `owner`.
    ///
    /// No validation of `from`, `to`, `router` or `pair`: the owner pins the
    /// addresses and carries the risk. The contract does not know asset names
    /// and must not — 66 issuers use the code "EURC", with active
    /// typosquatting, so resolving by code would be a security hole.
    ///
    /// # Errors
    /// `InvalidParameters` if any value is non-positive, if `interval` is zero
    /// or above `MAX_INTERVAL`, or if `keeper_fee >= amount`.
    /// `Overflow` if the plan counter would wrap.
    pub fn create_plan(
        env: Env,
        owner: Address,
        from: Address,
        to: Address,
        router: Address,
        pair: Address,
        amount: i128,
        interval: u64,
        min_out: i128,
        keeper_fee: i128,
    ) -> Result<u32, Error> {
        owner.require_auth();

        if amount <= 0 || interval == 0 || keeper_fee < 0 || min_out < 0 {
            return Err(Error::InvalidParameters);
        }
        // The fee cannot swallow the contribution: without this, a plan of 1
        // with a fee of 1 would be accepted and would buy nothing.
        if keeper_fee >= amount {
            return Err(Error::InvalidParameters);
        }
        // An interval longer than the entry's life would archive the plan
        // between executions. Better rejected at creation than discovered
        // months later with the remainder stuck.
        if interval > MAX_INTERVAL {
            return Err(Error::InvalidParameters);
        }

        let id: u32 = env.storage().instance().get(&DataKey::NextId).unwrap_or(0);

        let plan = Plan {
            owner,
            from,
            to,
            router,
            pair,
            amount,
            interval,
            next_exec: env.ledger().timestamp(),
            budget: 0,
            min_out,
            keeper_fee,
        };

        let next = id.checked_add(1).ok_or(Error::Overflow)?;
        env.storage().persistent().set(&DataKey::Plan(id), &plan);
        env.storage().instance().set(&DataKey::NextId, &next);
        Self::renew_ttl(&env, id);
        Ok(id)
    }

    /// Adds budget. Anyone may fund someone else's plan: this is harmless,
    /// because only the owner can take funds out.
    ///
    /// # Errors
    /// `InvalidParameters` if `amount <= 0`; `PlanNotFound`; `Overflow`.
    pub fn deposit(env: Env, from: Address, id: u32, amount: i128) -> Result<(), Error> {
        from.require_auth();
        if amount <= 0 {
            return Err(Error::InvalidParameters);
        }
        let mut plan = Self::read(&env, id)?;

        token::Client::new(&env, &plan.from).transfer(
            &from,
            &env.current_contract_address(),
            &amount,
        );

        plan.budget = plan.budget.checked_add(amount).ok_or(Error::Overflow)?;
        Self::write(&env, id, &plan);
        Ok(())
    }

    /// **Public by design.** Anyone may call it; whoever does collects
    /// `keeper_fee`. No `require_auth`: that is the heart of the design.
    ///
    /// The caller cannot divert funds. The swap output goes to this contract
    /// and is then forwarded to `plan.owner`, read from storage and never from
    /// an argument; the caller only supplies the address that receives the fee.
    ///
    /// # Errors
    /// `NotDueYet`, `InsufficientBudget`, `PriceOutOfBounds`, `Overflow`.
    pub fn execute(env: Env, keeper: Address, id: u32) -> Result<i128, Error> {
        let mut plan = Self::read(&env, id)?;

        if env.ledger().timestamp() < plan.next_exec {
            return Err(Error::NotDueYet);
        }
        if plan.budget < plan.amount {
            return Err(Error::InsufficientBudget);
        }

        // `keeper_fee < amount` is guaranteed by create_plan, but a distant
        // invariant is not relied upon: the check sits next to the operation.
        let to_swap = plan
            .amount
            .checked_sub(plan.keeper_fee)
            .ok_or(Error::Overflow)?;

        let received = Self::swap(&env, &plan, to_swap)?;

        if received < plan.min_out {
            return Err(Error::PriceOutOfBounds);
        }

        // The keeper is paid AFTER a successful swap: if the swap fails the
        // whole transaction reverts and nobody collects anything.
        if plan.keeper_fee > 0 {
            token::Client::new(&env, &plan.from).transfer(
                &env.current_contract_address(),
                &keeper,
                &plan.keeper_fee,
            );
        }

        plan.budget = plan
            .budget
            .checked_sub(plan.amount)
            .ok_or(Error::Overflow)?;
        // Addition, not "now + interval": a late execution must not push the
        // whole subsequent schedule forward.
        plan.next_exec = plan
            .next_exec
            .checked_add(plan.interval)
            .ok_or(Error::Overflow)?;
        Self::write(&env, id, &plan);
        Ok(received)
    }

    /// Withdraws part of the unspent budget. Owner only.
    ///
    /// # Errors
    /// `InsufficientBudget` if `amount` is non-positive or exceeds the budget.
    pub fn withdraw(env: Env, id: u32, amount: i128) -> Result<(), Error> {
        let mut plan = Self::read(&env, id)?;
        plan.owner.require_auth();

        if amount <= 0 || amount > plan.budget {
            return Err(Error::InsufficientBudget);
        }
        token::Client::new(&env, &plan.from).transfer(
            &env.current_contract_address(),
            &plan.owner,
            &amount,
        );
        plan.budget = plan.budget.checked_sub(amount).ok_or(Error::Overflow)?;
        Self::write(&env, id, &plan);
        Ok(())
    }

    /// Stops the plan and returns the whole remainder. Owner only.
    ///
    /// Should be used before the budget falls below a usable threshold: once
    /// nobody can call `execute`, the entry stops being renewed and archives,
    /// and recovering the remainder then costs a paid restore.
    ///
    /// # Errors
    /// `PlanNotFound`.
    pub fn cancel(env: Env, id: u32) -> Result<(), Error> {
        let plan = Self::read(&env, id)?;
        plan.owner.require_auth();

        if plan.budget > 0 {
            token::Client::new(&env, &plan.from).transfer(
                &env.current_contract_address(),
                &plan.owner,
                &plan.budget,
            );
        }
        env.storage().persistent().remove(&DataKey::Plan(id));
        Ok(())
    }

    /// Read-only plan state.
    ///
    /// # Errors
    /// `PlanNotFound`.
    pub fn get_plan(env: Env, id: u32) -> Result<Plan, Error> {
        Self::read(&env, id)
    }

    /// Ids of plans executable right now. A convenience for keepers.
    pub fn due_plans(env: Env) -> Vec<u32> {
        let mut out = Vec::new(&env);
        let n: u32 = env.storage().instance().get(&DataKey::NextId).unwrap_or(0);
        let now = env.ledger().timestamp();
        for id in 0..n {
            if let Some(p) = env
                .storage()
                .persistent()
                .get::<DataKey, Plan>(&DataKey::Plan(id))
            {
                if now >= p.next_exec && p.budget >= p.amount {
                    out.push_back(id);
                }
            }
        }
        out
    }

    // ---- internal ----

    fn read(env: &Env, id: u32) -> Result<Plan, Error> {
        env.storage()
            .persistent()
            .get(&DataKey::Plan(id))
            .ok_or(Error::PlanNotFound)
    }

    /// Every write renews the TTL: the plan keeps itself alive precisely
    /// because it is recurring. That is the answer to state rent, and it needs
    /// no additional component.
    fn write(env: &Env, id: u32, plan: &Plan) {
        env.storage().persistent().set(&DataKey::Plan(id), plan);
        Self::renew_ttl(env, id);
    }

    fn renew_ttl(env: &Env, id: u32) {
        env.storage()
            .persistent()
            .extend_ttl(&DataKey::Plan(id), TTL_THRESHOLD, TTL_EXTEND_TO);
        env.storage()
            .instance()
            .extend_ttl(TTL_THRESHOLD, TTL_EXTEND_TO);
    }

    /// Performs the swap on the router and forwards the proceeds to the owner.
    ///
    /// # Why `to` is THIS contract and not the owner
    ///
    /// Soroban has no `msg.sender` and the router signature has no `from`
    /// parameter: the pair pulls the input **from `to`**, which is therefore
    /// both payer and recipient (Soroswap source: the pair runs
    /// `sell_token.transfer(&to, &pair, &amount_in)`).
    ///
    /// Consequence not to get wrong: passing `plan.owner` as `to` would make
    /// the router pull from the **owner's wallet** instead of the budget
    /// deposited here. The contract would do something other than what it
    /// claims. So `to` is this contract, and the output is forwarded to the
    /// owner with a second transfer: the bought asset passes through for a
    /// single transaction, never at rest.
    ///
    /// # The authorisation, which is the non-obvious part
    ///
    /// The router does not receive the tokens: it **pulls** them, calling
    /// `transfer(from = this contract, to = pair, amount)`. That transfer needs
    /// this contract's authorisation, and in Soroban a sub-invocation must be
    /// authorised explicitly with `authorize_as_current_contract`, declaring in
    /// advance EXACTLY which call is being permitted.
    ///
    /// That is also a defence: the authorisation covers one transfer, of this
    /// amount, to this pair. A malicious router cannot use it to drain the rest
    /// of the budget.
    fn swap(env: &Env, plan: &Plan, amount: i128) -> Result<i128, Error> {
        let me = env.current_contract_address();

        env.authorize_as_current_contract(vec![
            env,
            InvokerContractAuthEntry::Contract(SubContractInvocation {
                context: ContractContext {
                    contract: plan.from.clone(),
                    fn_name: Symbol::new(env, "transfer"),
                    args: (me.clone(), plan.pair.clone(), amount).into_val(env),
                },
                sub_invocations: vec![env],
            }),
        ]);

        let path = vec![env, plan.from.clone(), plan.to.clone()];
        // Generous deadline: the transaction already has its own time bound,
        // and a tight one here would only add a way to fail.
        let deadline = env
            .ledger()
            .timestamp()
            .checked_add(300)
            .ok_or(Error::Overflow)?;

        let out = RouterClient::new(env, &plan.router).swap_exact_tokens_for_tokens(
            &amount,
            &plan.min_out,
            &path,
            &me,
            &deadline,
        );

        let received = out.last().ok_or(Error::PriceOutOfBounds)?;
        token::Client::new(env, &plan.to).transfer(&me, &plan.owner, &received);
        Ok(received)
    }
}

mod test;
