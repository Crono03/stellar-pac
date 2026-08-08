#![no_std]
//! PAC on-chain: versamenti ricorrenti innescati da un keeper permissionless.
//!
//! Stato all'8/8/2026: logica completa, swap attuato sul SoroswapRouter.
//! Mai deployato, mai auditato.
//!
//! Nota di costo, perche' non sia una sorpresa: il contratto puo' raggiungere
//! solo le venue Soroban, non la SDEX classica, e fra le due c'e' uno scarto
//! **strutturale dello 0,49%** misurato. Con la fee del keeper il costo per
//! esecuzione e' ~0,71%. Questo prodotto **non compete sul prezzo** con un piano
//! di accumulo gratuito di broker: compete sull'accesso e sulla non-custodia.
//! Vedi `brain/concetti/costo-vero-esecuzione`.
//!
//! # I tre vincoli che hanno determinato questa forma
//!
//! 1. **Soroban non ha scheduler.** Nessun contratto si sveglia da solo. Quindi
//!    `execute` e' pubblica e chi la chiama viene pagato: nessun operatore
//!    privilegiato, nessun server da tenere vivo, nessun interruttore.
//!
//! 2. **Immutabile per restare fuori dal perimetro MiCA.** Niente admin, niente
//!    upgrade, **nessuna fee allo sviluppatore**. Conseguenza diretta sul
//!    codice: non esistono costanti che un domani andrebbero cambiate. Asset,
//!    router e parametri sono **per-piano**, scelti dall'owner. Se l'emittente
//!    di un asset ruotasse, il contratto non va aggiornato: e' l'owner a
//!    cancellare e ricreare il piano.
//!
//! 3. **La difesa dal MEV e' la taglia, non il codice.** Sotto ~200 EUR per
//!    esecuzione il sandwich costa all'attaccante piu' di quanto estrae.
//!    `min_out` NON e' una difesa dal MEV: e' il parapetto che ferma
//!    un'esecuzione a un prezzo assurdo, qualunque sia la taglia.
//!
//! # L'invariante da non rompere mai
//!
//! **Solo `owner` puo' far uscire valore dal piano verso un indirizzo suo.**
//! Il keeper puo' soltanto innescare l'esecuzione e incassare `keeper_fee`, che
//! e' fissata dall'owner alla creazione. E' la prima cosa che un audit deve
//! verificare, ed e' il motivo per cui `withdraw` e `cancel` chiamano
//! `require_auth` sull'owner e `execute` no.

use soroban_sdk::{
    auth::{ContractContext, InvokerContractAuthEntry, SubContractInvocation},
    contract, contractclient, contracterror, contractimpl, contracttype, token, vec,
    Address, Env, IntoVal, Symbol, Vec,
};

/// Interfaccia del SoroswapRouter, la sola parte che ci serve.
///
/// Il nome esportato e' senza prefisso `router_`, a differenza di
/// `router_get_amounts_out`. Non e' una scelta di stile: i simboli Soroban sono
/// limitati a **32 caratteri** e `router_swap_exact_tokens_for_tokens` ne conta
/// 35, quindi quel nome non puo' esistere. Verificato in simulazione l'8/8/2026.
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

/// Chiavi dello storage. `Plan(u32)` e' persistent: deve sopravvivere fra
/// un'esecuzione e l'altra, ed e' la entry di cui `execute` rinnova la TTL.
#[contracttype]
#[derive(Clone)]
pub enum DataKey {
    /// Contatore incrementale dei piani creati.
    NextId,
    /// Il piano vero e proprio.
    Plan(u32),
}

#[contracttype]
#[derive(Clone)]
pub struct Plan {
    /// L'unico che puo' prelevare o cancellare.
    pub owner: Address,
    /// Asset speso a ogni esecuzione (es. EURC). Indirizzo del SAC.
    pub from: Address,
    /// Asset acquistato (es. XLM). Indirizzo del SAC.
    pub to: Address,
    /// Venue dello swap. Parametro e non costante: vedi vincolo 2.
    pub router: Address,
    /// La pair del router per (from, to). Passata dall'owner invece di essere
    /// cercata sulla factory a ogni esecuzione: risparmia una chiamata
    /// cross-contract per giro. Se e' sbagliata l'autorizzazione non combacia
    /// con il trasferimento che il router tenta davvero e l'esecuzione
    /// FALLISCE: un valore errato non puo' dirottare fondi, puo' solo bloccare.
    pub pair: Address,
    /// Quanto spendere a ogni esecuzione, in unita' di `from`.
    pub amount: i128,
    /// Secondi fra un'esecuzione e la successiva.
    pub interval: u64,
    /// Timestamp della prossima esecuzione ammessa.
    pub next_exec: u64,
    /// Residuo depositato, in unita' di `from`. Decrementato a ogni giro.
    pub budget: i128,
    /// Minimo accettabile di `to` per esecuzione. Parapetto, non anti-MEV.
    pub min_out: i128,
    /// Quanto incassa chi chiama `execute`. Prelevata da `budget`.
    pub keeper_fee: i128,
}

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    PianoInesistente = 1,
    NonSeiOwner = 2,
    NonEAncoraOra = 3,
    BudgetInsufficiente = 4,
    ParametriNonValidi = 5,
    /// Lo swap ha reso meno di `min_out`: il parapetto ha fermato l'esecuzione.
    PrezzoFuoriSoglia = 6,
    /// Aritmetica fuori intervallo. Con `overflow-checks = true` questi casi
    /// andrebbero comunque in panic, quindi il fallimento sarebbe gia' sicuro:
    /// usare `checked_*` serve a restituire un errore TIPIZZATO invece di un
    /// panic opaco, e a rendere l'intenzione leggibile a chi revisiona.
    Overflow = 7,
}

/// Rinnovo della TTL. Valori letti dalla mainnet l'8/8/2026, non stimati.
///
/// | parametro di rete | ledger | giorni (a 5,59 s) |
/// |---|---|---|
/// | `max_entry_ttl` | 3.110.400 | 201,2 |
/// | `min_persistent_ttl` | 2.073.600 | 134,2 |
///
/// **La prima stesura era inutile.** Aveva soglia 100.000 ed estensione
/// 500.000, scritte credendo che la TTL minima fosse 4.096 ledger — numero
/// preso da un esempio della documentazione che riguardava invece le entry
/// *ripristinate*. Poiche' ogni scrittura porta la entry ad almeno
/// `min_persistent_ttl` = 2.073.600, quella soglia non veniva mai raggiunta e
/// l'estensione, se pure fosse scattata, avrebbe abbassato la TTL invece di
/// alzarla. Codice che non faceva nulla e sembrava prudente.
///
/// **Seconda correzione, dopo il deploy in testnet dell'8/8/2026.** Estendere
/// sempre al massimo costa caro: `create_plan` con estensione a 3.110.000 ha
/// pagato **17,264 XLM = 2,45 EUR** di rent, misurati. Il rent e' proporzionale
/// alla TTL richiesta: 5,55 XLM per milione di ledger.
///
/// Su mainnet `min_persistent_ttl` = 2.073.600 e' un pavimento -- qualunque
/// scrittura ci arriva comunque -- quindi estendere OLTRE quel valore e' spesa
/// pura. Si rinnova percio' al pavimento e non al tetto: **1,63 EUR invece di
/// 2,45 per piano**, e la entry vive comunque 134 giorni, ben oltre
/// l'intervallo massimo ammesso.
const TTL_SOGLIA: u32 = 1_500_000;
const TTL_ESTENSIONE: u32 = 2_073_600;

/// Intervallo massimo ammesso per un piano: **oltre questo la entry si archivia
/// fra un'esecuzione e l'altra** e recuperare il residuo costa un ripristino.
/// Tenuto sotto `min_persistent_ttl` con margine: 2.000.000 ledger ~ 129 giorni.
const INTERVALLO_MAX: u64 = 2_000_000 * 5;

#[contract]
pub struct Pac;

#[contractimpl]
impl Pac {
    /// Registra un piano. Chi chiama diventa `owner`.
    ///
    /// Nessun controllo su `from`, `to` e `router`: e' l'owner a pinnare gli
    /// indirizzi e a portarne il rischio. Il contratto non conosce nomi di
    /// asset e non deve conoscerli — 66 emittenti usano il codice "EURC" e
    /// risolvere per codice sarebbe un buco di sicurezza.
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
            return Err(Error::ParametriNonValidi);
        }
        // Un intervallo piu' lungo della vita della entry farebbe archiviare il
        // piano fra un'esecuzione e l'altra. Meglio rifiutarlo alla creazione
        // che scoprirlo mesi dopo con il residuo bloccato.
        if interval > INTERVALLO_MAX {
            return Err(Error::ParametriNonValidi);
        }
        // La fee non puo' divorare il versamento: senza questo vincolo un piano
        // da 1 EUR con fee da 1 EUR sarebbe accettato e non comprerebbe nulla.
        if keeper_fee >= amount {
            return Err(Error::ParametriNonValidi);
        }

        let id: u32 = env
            .storage()
            .instance()
            .get(&DataKey::NextId)
            .unwrap_or(0);

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

        env.storage().persistent().set(&DataKey::Plan(id), &plan);
        let prossimo = id.checked_add(1).ok_or(Error::Overflow)?;
        env.storage().instance().set(&DataKey::NextId, &prossimo);
        Self::rinnova_ttl(&env, id);
        Ok(id)
    }

    /// Aggiunge budget. Chiunque puo' finanziare un piano altrui: e' innocuo,
    /// perche' solo l'owner puo' far uscire i fondi.
    pub fn deposit(env: Env, da: Address, id: u32, amount: i128) -> Result<(), Error> {
        da.require_auth();
        if amount <= 0 {
            return Err(Error::ParametriNonValidi);
        }
        let mut plan = Self::leggi(&env, id)?;

        token::Client::new(&env, &plan.from).transfer(
            &da,
            &env.current_contract_address(),
            &amount,
        );

        plan.budget = plan.budget.checked_add(amount).ok_or(Error::Overflow)?;
        Self::scrivi(&env, id, &plan);
        Ok(())
    }

    /// **Pubblica di proposito.** Chiunque puo' chiamarla; chi lo fa incassa
    /// `keeper_fee`. Nessun `require_auth`: e' il cuore del disegno.
    ///
    /// Non c'e' modo per il chiamante di deviare fondi: la destinazione dello
    /// swap e' `plan.owner`, letta dallo storage e non da un argomento.
    pub fn execute(env: Env, keeper: Address, id: u32) -> Result<i128, Error> {
        let mut plan = Self::leggi(&env, id)?;

        let ora = env.ledger().timestamp();
        if ora < plan.next_exec {
            return Err(Error::NonEAncoraOra);
        }
        if plan.budget < plan.amount {
            return Err(Error::BudgetInsufficiente);
        }

        // `keeper_fee < amount` e' garantito da create_plan, ma non ci si affida
        // a un invariante lontano: il controllo sta accanto all'operazione.
        let da_scambiare = plan
            .amount
            .checked_sub(plan.keeper_fee)
            .ok_or(Error::Overflow)?;

        // APERTO — vedi brain/concetti/soroban-non-vede-la-sdex.
        // Il path payment classico NON e' invocabile da un contratto Soroban.
        // Lo swap deve passare per una DEX Soroban, e quale non e' ancora
        // deciso perche' la liquidita' EURC sul lato Soroban non e' misurata.
        // Finche' resta aperto, `Router` e' un'interfaccia e non un'attuazione.
        let ricevuto = Self::swap(&env, &plan, da_scambiare)?;

        if ricevuto < plan.min_out {
            return Err(Error::PrezzoFuoriSoglia);
        }

        // Il keeper viene pagato DOPO uno swap riuscito: se lo swap fallisce
        // l'intera transazione torna indietro e nessuno incassa nulla.
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
        // Somma, non "ora + interval": cosi' un'esecuzione in ritardo non
        // sposta in avanti tutta la cadenza successiva.
        plan.next_exec = plan
            .next_exec
            .checked_add(plan.interval)
            .ok_or(Error::Overflow)?;
        Self::scrivi(&env, id, &plan);
        Ok(ricevuto)
    }

    /// Preleva parte del budget non ancora speso. Solo owner.
    pub fn withdraw(env: Env, id: u32, amount: i128) -> Result<(), Error> {
        let mut plan = Self::leggi(&env, id)?;
        plan.owner.require_auth();

        if amount <= 0 || amount > plan.budget {
            return Err(Error::BudgetInsufficiente);
        }
        token::Client::new(&env, &plan.from).transfer(
            &env.current_contract_address(),
            &plan.owner,
            &amount,
        );
        plan.budget = plan.budget.checked_sub(amount).ok_or(Error::Overflow)?;
        Self::scrivi(&env, id, &plan);
        Ok(())
    }

    /// Ferma il piano e restituisce tutto il residuo. Solo owner.
    ///
    /// Va usato prima che il budget scenda sotto una soglia utile: se nessuno
    /// puo' piu' chiamare `execute` la entry smette di essere rinnovata e si
    /// archivia, e recuperare il residuo costa un ripristino a pagamento.
    pub fn cancel(env: Env, id: u32) -> Result<(), Error> {
        let plan = Self::leggi(&env, id)?;
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

    /// Sola lettura, per il keeper che cerca piani scaduti.
    pub fn get_plan(env: Env, id: u32) -> Result<Plan, Error> {
        Self::leggi(&env, id)
    }

    /// Id dei piani eseguibili adesso. Comodita' per il keeper.
    pub fn eseguibili(env: Env) -> Vec<u32> {
        let mut out = Vec::new(&env);
        let n: u32 = env.storage().instance().get(&DataKey::NextId).unwrap_or(0);
        let ora = env.ledger().timestamp();
        for id in 0..n {
            if let Some(p) = env
                .storage()
                .persistent()
                .get::<DataKey, Plan>(&DataKey::Plan(id))
            {
                if ora >= p.next_exec && p.budget >= p.amount {
                    out.push_back(id);
                }
            }
        }
        out
    }

    // ---- interni ----

    fn leggi(env: &Env, id: u32) -> Result<Plan, Error> {
        env.storage()
            .persistent()
            .get(&DataKey::Plan(id))
            .ok_or(Error::PianoInesistente)
    }

    /// Ogni scrittura rinnova la TTL: il piano si mantiene vivo da solo proprio
    /// perche' e' ricorrente. E' la soluzione al problema del rent, e non
    /// richiede componenti aggiuntive.
    fn scrivi(env: &Env, id: u32, plan: &Plan) {
        env.storage().persistent().set(&DataKey::Plan(id), plan);
        Self::rinnova_ttl(env, id);
    }

    fn rinnova_ttl(env: &Env, id: u32) {
        env.storage()
            .persistent()
            .extend_ttl(&DataKey::Plan(id), TTL_SOGLIA, TTL_ESTENSIONE);
        env.storage()
            .instance()
            .extend_ttl(TTL_SOGLIA, TTL_ESTENSIONE);
    }

    /// Esegue lo swap sul router e manda il ricevuto direttamente all'owner.
    ///
    /// # Perche' `to` e' QUESTO contratto e non l'owner
    ///
    /// In Soroban non esiste `msg.sender` e la firma del router non ha un
    /// parametro `from`: la pair preleva l'importo **da `to`**, che e' quindi
    /// insieme pagatore e destinatario (sorgente Soroswap: la pair esegue
    /// `sell_token.transfer(&to, &pair, &amount_in)`).
    ///
    /// Conseguenza da non sbagliare: passando `plan.owner` come `to`, il router
    /// preleverebbe dal **portafoglio dell'owner** invece che dal budget
    /// depositato qui. Il contratto farebbe una cosa diversa da quella
    /// dichiarata. Quindi `to` e' questo contratto, e l'output viene inoltrato
    /// all'owner con un secondo trasferimento: l'asset comprato transita da qui
    /// per una sola transazione, mai a riposo.
    ///
    /// # L'autorizzazione, che e' la parte non ovvia
    ///
    /// Il router non riceve i token: li **preleva**, chiamando
    /// `transfer(from = questo contratto, to = pair, amount)`. Quel trasferimento
    /// richiede l'autorizzazione di questo contratto, e in Soroban una
    /// sotto-invocazione va autorizzata esplicitamente con
    /// `authorize_as_current_contract`, dichiarando in anticipo ESATTAMENTE
    /// quale chiamata si sta permettendo.
    ///
    /// E' anche una difesa: l'autorizzazione e' limitata a un solo trasferimento,
    /// di questo importo, verso questa pair. Un router malevolo non puo' usarla
    /// per prelevare il resto del budget.
    fn swap(env: &Env, plan: &Plan, amount: i128) -> Result<i128, Error> {
        let io = env.current_contract_address();

        env.authorize_as_current_contract(vec![
            env,
            InvokerContractAuthEntry::Contract(SubContractInvocation {
                context: ContractContext {
                    contract: plan.from.clone(),
                    fn_name: Symbol::new(env, "transfer"),
                    args: (io.clone(), plan.pair.clone(), amount).into_val(env),
                },
                sub_invocations: vec![env],
            }),
        ]);

        let path = vec![env, plan.from.clone(), plan.to.clone()];
        // Scadenza generosa: la transazione ha gia' il proprio limite temporale,
        // e una deadline stretta qui aggiungerebbe solo un modo di fallire.
        let scadenza = env
            .ledger()
            .timestamp()
            .checked_add(300)
            .ok_or(Error::Overflow)?;

        let out = RouterClient::new(env, &plan.router).swap_exact_tokens_for_tokens(
            &amount,
            &plan.min_out,
            &path,
            &io,
            &scadenza,
        );

        let ricevuto = out.last().ok_or(Error::PrezzoFuoriSoglia)?;
        token::Client::new(env, &plan.to).transfer(&io, &plan.owner, &ricevuto);
        Ok(ricevuto)
    }
}

mod test;
