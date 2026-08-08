//! State-machine tests. The swap is replaced by a mock router.
//!
//! The mock performs a **real transfer** with the same semantics as the actual
//! router: it pulls from `to`. If the authorisation built in `swap()` did not
//! match, these tests would fail. That is why it does not simply return a
//! number. A mock that does not imitate real behaviour is not a test, it is a
//! confirmation of what you already believe.

#![cfg(test)]

use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger},
    token::{StellarAssetClient, TokenClient},
    Address, Env,
};

// ---- mock router ----

#[contract]
pub struct MockRouter;

#[contractimpl]
impl MockRouter {
    /// Fixed 1:2 rate: one unit in, two out. Enough to verify accounting,
    /// authorisation and the `min_out` guardrail.
    pub fn swap_exact_tokens_for_tokens(
        env: Env,
        amount_in: i128,
        amount_out_min: i128,
        path: Vec<Address>,
        to: Address,
        _deadline: u64,
    ) -> Vec<i128> {
        let from = path.get(0).unwrap();
        let to_asset = path.get(1).unwrap();
        let pair: Address = env
            .storage()
            .instance()
            .get(&Symbol::new(&env, "pair"))
            .unwrap();

        // REAL router semantics: the pair pulls from `to`, which is both payer
        // and recipient. If the auth built in swap() did not cover exactly this
        // transfer, the test would fail.
        token::Client::new(&env, &from).transfer(&to, &pair, &amount_in);

        let out = amount_in * 2;
        assert!(out >= amount_out_min, "below min_out");
        // Pays from its own reserves, like a real pair. The first version used
        // `mint`, which needs the asset admin's auth: an authorisation not tied
        // to the root invocation, which `mock_all_auths` cannot record.
        // Pre-funding is also more faithful: a pool pays from what it holds.
        token::Client::new(&env, &to_asset)
            .transfer(&env.current_contract_address(), &to, &out);
        vec![&env, amount_in, out]
    }

    pub fn set_pair(env: Env, pair: Address) {
        env.storage().instance().set(&Symbol::new(&env, "pair"), &pair);
    }
}

// ---- harness ----

struct Rig {
    env: Env,
    pac: PacClient<'static>,
    owner: Address,
    keeper: Address,
    from: Address,
    to: Address,
    router: Address,
    pair: Address,
}

fn rig() -> Rig {
    let env = Env::default();
    env.mock_all_auths();

    let owner = Address::generate(&env);
    let keeper = Address::generate(&env);
    let issuer = Address::generate(&env);

    let from = env.register_stellar_asset_contract_v2(issuer.clone()).address();
    let to = env.register_stellar_asset_contract_v2(issuer.clone()).address();

    let router = env.register(MockRouter, ());
    let pair = Address::generate(&env);
    MockRouterClient::new(&env, &router).set_pair(&pair);

    let pac = PacClient::new(&env, &env.register(Pac, ()));

    // the owner starts with 1,000 units of the source asset
    StellarAssetClient::new(&env, &from).mint(&owner, &1_000);
    // the mock router holds reserves of the destination asset, like a real pool
    StellarAssetClient::new(&env, &to).mint(&router, &1_000_000);

    Rig { env, pac, owner, keeper, from, to, router, pair }
}

fn create(b: &Rig, amount: i128, interval: u64, min_out: i128, fee: i128) -> u32 {
    b.pac.create_plan(
        &b.owner, &b.from, &b.to, &b.router, &b.pair, &amount, &interval, &min_out, &fee,
    )
}

// ---- tests ----

#[test]
fn create_and_deposit() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &500);

    let p = b.pac.get_plan(&id);
    assert_eq!(p.budget, 500);
    assert_eq!(p.owner, b.owner);
    assert_eq!(TokenClient::new(&b.env, &b.from).balance(&b.owner), 500);
}

#[test]
fn fee_cannot_swallow_the_contribution() {
    let b = rig();
    // fee >= amount must be rejected: a plan that would buy nothing
    assert!(b
        .pac
        .try_create_plan(&b.owner, &b.from, &b.to, &b.router, &b.pair, &10, &3600, &0, &10)
        .is_err());
}

#[test]
fn absurd_parameters_rejected() {
    let b = rig();
    for (amount, interval) in [(0i128, 3600u64), (-5, 3600), (100, 0)] {
        assert!(b
            .pac
            .try_create_plan(
                &b.owner, &b.from, &b.to, &b.router, &b.pair, &amount, &interval, &0, &1
            )
            .is_err());
    }
}

#[test]
fn execution_pays_keeper_and_credits_owner() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &300);

    let received = b.pac.execute(&b.keeper, &id);

    // 95 swapped (100 minus the 5 fee), at the mock 1:2 rate
    assert_eq!(received, 190);
    assert_eq!(TokenClient::new(&b.env, &b.to).balance(&b.owner), 190);
    assert_eq!(TokenClient::new(&b.env, &b.from).balance(&b.keeper), 5);
    assert_eq!(b.pac.get_plan(&id).budget, 200);
}

#[test]
fn cannot_execute_twice_immediately() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &300);

    b.pac.execute(&b.keeper, &id);
    assert!(b.pac.try_execute(&b.keeper, &id).is_err());

    // once the interval has passed, it runs again
    b.env.ledger().with_mut(|l| l.timestamp += 3600);
    b.pac.execute(&b.keeper, &id);
    assert_eq!(b.pac.get_plan(&id).budget, 100);
}

#[test]
fn lateness_does_not_shift_the_schedule() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &300);
    b.pac.execute(&b.keeper, &id);

    // a keeper calls ten hours late
    b.env.ledger().with_mut(|l| l.timestamp += 36_000);
    b.pac.execute(&b.keeper, &id);

    // the next stays anchored to the original grid, not to "now + interval"
    let p = b.pac.get_plan(&id);
    assert_eq!(p.next_exec, 3600 * 2);
}

#[test]
fn insufficient_budget_stops_everything() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &50);
    assert!(b.pac.try_execute(&b.keeper, &id).is_err());
}

#[test]
fn min_out_is_a_real_guardrail() {
    let b = rig();
    // the mock returns 2x: asking for 500 on 95 swapped must stop it
    let id = create(&b, 100, 3600, 500, 5);
    b.pac.deposit(&b.owner, &id, &300);
    assert!(b.pac.try_execute(&b.keeper, &id).is_err());

    // and the budget must be untouched
    assert_eq!(b.pac.get_plan(&id).budget, 300);
}

#[test]
fn cancel_returns_everything_and_deletes() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &400);

    b.pac.cancel(&id);
    assert_eq!(TokenClient::new(&b.env, &b.from).balance(&b.owner), 1_000);
    assert!(b.pac.try_get_plan(&id).is_err());
}

#[test]
fn withdraw_cannot_exceed_budget() {
    let b = rig();
    let id = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &200);
    assert!(b.pac.try_withdraw(&id, &500).is_err());
    b.pac.withdraw(&id, &150);
    assert_eq!(b.pac.get_plan(&id).budget, 50);
}

#[test]
fn interval_too_long_rejected() {
    let b = rig();
    // beyond ~129 days the entry would archive between executions
    let too_long = 2_000_000u64 * 5 + 1;
    assert!(b
        .pac
        .try_create_plan(
            &b.owner, &b.from, &b.to, &b.router, &b.pair, &100, &too_long, &0, &5
        )
        .is_err());
    // a quarterly plan (90 days) must be accepted
    let quarterly = 90 * 24 * 3600;
    assert!(b
        .pac
        .try_create_plan(
            &b.owner, &b.from, &b.to, &b.router, &b.pair, &100, &quarterly, &0, &5
        )
        .is_ok());
}

#[test]
fn due_plans_lists_only_the_ready() {
    let b = rig();
    let funded = create(&b, 100, 3600, 0, 5);
    let empty = create(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &funded, &300);

    let ready = b.pac.due_plans();
    assert!(ready.contains(&funded));
    assert!(!ready.contains(&empty)); // no budget means not ready
}
