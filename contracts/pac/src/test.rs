//! Test della macchina a stati. Lo swap e' sostituito da un router finto.
//!
//! Il router finto **fa un trasferimento vero** dal contratto alla pair e poi
//! accredita l'output all'owner: se l'autorizzazione costruita in `swap()`
//! fosse sbagliata, questi test fallirebbero. E' il motivo per cui non ritorna
//! semplicemente un numero.

#![cfg(test)]

use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger},
    token::{StellarAssetClient, TokenClient},
    Address, Env,
};

// ---- router finto ----

#[contract]
pub struct RouterFinto;

#[contractimpl]
impl RouterFinto {
    /// Prezzo fisso 1:2 — un'unita' in, due unita' out. Basta a verificare
    /// contabilita', autorizzazioni e parapetto `min_out`.
    pub fn swap_exact_tokens_for_tokens(
        env: Env,
        amount_in: i128,
        amount_out_min: i128,
        path: Vec<Address>,
        to: Address,
        _deadline: u64,
    ) -> Vec<i128> {
        let da = path.get(0).unwrap();
        let a = path.get(1).unwrap();
        let pair: Address = env
            .storage()
            .instance()
            .get(&Symbol::new(&env, "pair"))
            .unwrap();

        // Semantica del router VERO: la pair preleva da `to`, che e' insieme
        // pagatore e destinatario. Se l'auth costruita in swap() non coprisse
        // esattamente questo trasferimento, il test fallirebbe.
        token::Client::new(&env, &da).transfer(&to, &pair, &amount_in);

        let out = amount_in * 2;
        assert!(out >= amount_out_min, "sotto min_out");
        // Paga dalle proprie riserve, come una pair vera. La prima versione
        // faceva `mint`, che richiede l'auth dell'admin dell'asset: una
        // autorizzazione non legata all'invocazione radice, che
        // `mock_all_auths` non sa registrare. Pre-finanziare e' anche piu'
        // fedele: una pool paga da cio' che ha.
        token::Client::new(&env, &a).transfer(&env.current_contract_address(), &to, &out);
        vec![&env, amount_in, out]
    }

    pub fn set_pair(env: Env, pair: Address) {
        env.storage().instance().set(&Symbol::new(&env, "pair"), &pair);
    }
}

// ---- impalcatura ----

struct Banco {
    env: Env,
    pac: PacClient<'static>,
    owner: Address,
    keeper: Address,
    da: Address,
    a: Address,
    router: Address,
    pair: Address,
}

fn banco() -> Banco {
    let env = Env::default();
    env.mock_all_auths();

    let owner = Address::generate(&env);
    let keeper = Address::generate(&env);
    let emittente = Address::generate(&env);

    let da = env.register_stellar_asset_contract_v2(emittente.clone()).address();
    let a = env.register_stellar_asset_contract_v2(emittente.clone()).address();

    let router = env.register(RouterFinto, ());
    let pair = Address::generate(&env);
    RouterFintoClient::new(&env, &router).set_pair(&pair);

    let pac = PacClient::new(&env, &env.register(Pac, ()));

    // l'owner parte con 1.000 unita' dell'asset di partenza
    StellarAssetClient::new(&env, &da).mint(&owner, &1_000);
    // il router finto ha riserve dell'asset di arrivo, come una pool vera
    StellarAssetClient::new(&env, &a).mint(&router, &1_000_000);

    Banco { env, pac, owner, keeper, da, a, router, pair }
}

fn crea(b: &Banco, amount: i128, interval: u64, min_out: i128, fee: i128) -> u32 {
    b.pac.create_plan(
        &b.owner, &b.da, &b.a, &b.router, &b.pair, &amount, &interval, &min_out, &fee,
    )
}

// ---- test ----

#[test]
fn crea_e_deposita() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &500);

    let p = b.pac.get_plan(&id);
    assert_eq!(p.budget, 500);
    assert_eq!(p.owner, b.owner);
    assert_eq!(TokenClient::new(&b.env, &b.da).balance(&b.owner), 500);
}

#[test]
fn la_fee_non_puo_divorare_il_versamento() {
    let b = banco();
    // fee >= amount deve essere rifiutata: un piano che non compra nulla
    assert!(b
        .pac
        .try_create_plan(&b.owner, &b.da, &b.a, &b.router, &b.pair, &10, &3600, &0, &10)
        .is_err());
}

#[test]
fn parametri_assurdi_rifiutati() {
    let b = banco();
    for (amount, interval) in [(0i128, 3600u64), (-5, 3600), (100, 0)] {
        assert!(b
            .pac
            .try_create_plan(
                &b.owner, &b.da, &b.a, &b.router, &b.pair, &amount, &interval, &0, &1
            )
            .is_err());
    }
}

#[test]
fn esecuzione_paga_keeper_e_accredita_owner() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &300);

    let ricevuto = b.pac.execute(&b.keeper, &id);

    // scambiati 95 (100 - 5 di fee), al cambio finto 1:2
    assert_eq!(ricevuto, 190);
    assert_eq!(TokenClient::new(&b.env, &b.a).balance(&b.owner), 190);
    assert_eq!(TokenClient::new(&b.env, &b.da).balance(&b.keeper), 5);
    assert_eq!(b.pac.get_plan(&id).budget, 200);
}

#[test]
fn non_si_puo_eseguire_due_volte_subito() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &300);

    b.pac.execute(&b.keeper, &id);
    assert!(b.pac.try_execute(&b.keeper, &id).is_err());

    // passato l'intervallo, riparte
    b.env.ledger().with_mut(|l| l.timestamp += 3600);
    b.pac.execute(&b.keeper, &id);
    assert_eq!(b.pac.get_plan(&id).budget, 100);
}

#[test]
fn il_ritardo_non_sposta_la_cadenza() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &300);
    b.pac.execute(&b.keeper, &id);

    // un keeper chiama con 10 ore di ritardo
    b.env.ledger().with_mut(|l| l.timestamp += 36_000);
    b.pac.execute(&b.keeper, &id);

    // la prossima resta ancorata alla griglia originale, non a "ora + intervallo"
    let p = b.pac.get_plan(&id);
    assert_eq!(p.next_exec, 3600 * 2);
}

#[test]
fn budget_insufficiente_ferma_tutto() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &50);
    assert!(b.pac.try_execute(&b.keeper, &id).is_err());
}

#[test]
fn min_out_e_un_parapetto_vero() {
    let b = banco();
    // il router finto rende 2x: chiedere 500 su 95 scambiati deve fermare
    let id = crea(&b, 100, 3600, 500, 5);
    b.pac.deposit(&b.owner, &id, &300);
    assert!(b.pac.try_execute(&b.keeper, &id).is_err());

    // e il budget non deve essere stato toccato
    assert_eq!(b.pac.get_plan(&id).budget, 300);
}

#[test]
fn cancel_restituisce_tutto_e_cancella() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &400);

    b.pac.cancel(&id);
    assert_eq!(TokenClient::new(&b.env, &b.da).balance(&b.owner), 1_000);
    assert!(b.pac.try_get_plan(&id).is_err());
}

#[test]
fn withdraw_non_puo_superare_il_budget() {
    let b = banco();
    let id = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &id, &200);
    assert!(b.pac.try_withdraw(&id, &500).is_err());
    b.pac.withdraw(&id, &150);
    assert_eq!(b.pac.get_plan(&id).budget, 50);
}

#[test]
fn intervallo_troppo_lungo_rifiutato() {
    let b = banco();
    // oltre ~129 giorni la entry si archivierebbe fra un'esecuzione e l'altra
    let troppo = 2_000_000u64 * 5 + 1;
    assert!(b
        .pac
        .try_create_plan(
            &b.owner, &b.da, &b.a, &b.router, &b.pair, &100, &troppo, &0, &5
        )
        .is_err());
    // un trimestrale (90 giorni) invece deve passare
    let trimestrale = 90 * 24 * 3600;
    assert!(b
        .pac
        .try_create_plan(
            &b.owner, &b.da, &b.a, &b.router, &b.pair, &100, &trimestrale, &0, &5
        )
        .is_ok());
}

#[test]
fn eseguibili_elenca_solo_i_pronti() {
    let b = banco();
    let pieno = crea(&b, 100, 3600, 0, 5);
    let vuoto = crea(&b, 100, 3600, 0, 5);
    b.pac.deposit(&b.owner, &pieno, &300);

    let pronti = b.pac.eseguibili();
    assert!(pronti.contains(&pieno));
    assert!(!pronti.contains(&vuoto)); // senza budget non e' pronto
}
