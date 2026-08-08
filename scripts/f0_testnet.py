"""F0 — primo contatto con la rete: conto testnet e un path payment vero.

    python scripts/f0_testnet.py

COSA FA E PERCHE' IN QUEST'ORDINE.
Crea un conto su testnet, lo finanzia con friendbot (gratis), apre una
trustline verso un asset di test e prova un path payment. Serve a vedere con
gli occhi il ciclo che il contratto dovra' automatizzare: trustline, fee,
sequence number, risultato dell'operazione.

ATTENZIONE — LA TESTNET NON MISURA LA LIQUIDITA'.
Gli asset di testnet sono scollegati dalla mainnet: EURC li' non esiste con
liquidita' vera. Chi usa la testnet per stimare slippage misura un mercato
finto e ci costruisce sopra. La misura di liquidita' va fatta in SOLA LETTURA
su Horizon mainnet, che e' pubblico e gratuito: lo fa `f0_liquidita.py`.

Qui si impara la MECCANICA. Li' si misurano i PREZZI. Sono due cose diverse e
tenerle separate e' il punto di questa fase.

Le chiavi generate sono di TESTNET: non hanno valore e vengono stampate
apposta. Non riusarle mai in mainnet.
"""
from __future__ import annotations

import json
import urllib.request

from stellar_sdk import Asset, Keypair, Network, Server, TransactionBuilder

HORIZON = "https://horizon-testnet.stellar.org"
FRIENDBOT = "https://friendbot.stellar.org"


def finanzia(pub: str) -> bool:
    """Friendbot rifiuta con 403 lo user-agent predefinito di urllib.

    Verificato l'8/8/2026: stessa URL, stesso indirizzo, 403 senza header e 200
    con uno user-agent da browser. Non e' un limite di frequenza ne' un
    indirizzo malformato -- e' un filtro sul client, e senza questo header la
    fase F0 sembra rotta per il motivo sbagliato.
    """
    req = urllib.request.Request(f"{FRIENDBOT}/?addr={pub}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            json.load(r)
        return True
    except Exception as e:
        print(f"    friendbot ha rifiutato: {e}")
        return False


def main() -> None:
    print("=" * 74)
    print("F0 — TESTNET: meccanica del ciclo, non misura dei prezzi")
    print("=" * 74)

    srv = Server(HORIZON)
    rete = Network.TESTNET_NETWORK_PASSPHRASE

    # 1. due conti: uno fa da emittente dell'asset finto, uno da utente
    emittente = Keypair.random()
    utente = Keypair.random()
    print(f"\n1. Genero due coppie di chiavi (testnet, senza valore)")
    print(f"     emittente {emittente.public_key}")
    print(f"     utente    {utente.public_key}")

    print("\n2. Li finanzio con friendbot")
    for nome, kp in (("emittente", emittente), ("utente", utente)):
        ok = finanzia(kp.public_key)
        print(f"     {nome:<10} {'finanziato' if ok else 'FALLITO'}")
        if not ok:
            return

    c = srv.accounts().account_id(utente.public_key).call()
    saldo = next(b for b in c["balances"] if b["asset_type"] == "native")
    print(f"     saldo utente: {float(saldo['balance']):,.4f} XLM")
    print(f"     subentry gia' presenti: {c['subentry_count']}"
          f"  -> saldo minimo richiesto: {(2 + c['subentry_count']) * 0.5:.1f} XLM")

    # 2. trustline: e' il passaggio che consuma una reserve, va visto
    TEUR = Asset("TEUR", emittente.public_key)
    print(f"\n3. Apro una trustline su TEUR (asset finto dell'emittente)")
    conto = srv.load_account(utente.public_key)
    tx = (TransactionBuilder(conto, rete, base_fee=100)
          .append_change_trust_op(asset=TEUR)
          .set_timeout(60).build())
    tx.sign(utente)
    r = srv.submit_transaction(tx)
    print(f"     riuscita: {r['successful']}   fee pagata: "
          f"{int(r['fee_charged']) / 1e7:.7f} XLM")

    c = srv.accounts().account_id(utente.public_key).call()
    print(f"     subentry ora: {c['subentry_count']}"
          f"  -> saldo minimo: {(2 + c['subentry_count']) * 0.5:.1f} XLM")
    print("     ^ ogni trustline costa 0,5 XLM di riserva BLOCCATA, non spesa.")
    print("       E' il costo che il contratto dovra' considerare per ogni asset.")

    # 3. l'emittente manda TEUR all'utente
    print(f"\n4. L'emittente emette 100 TEUR verso l'utente")
    ce = srv.load_account(emittente.public_key)
    tx = (TransactionBuilder(ce, rete, base_fee=100)
          .append_payment_op(destination=utente.public_key, asset=TEUR, amount="100")
          .set_timeout(60).build())
    tx.sign(emittente)
    r = srv.submit_transaction(tx)
    print(f"     riuscita: {r['successful']}")

    c = srv.accounts().account_id(utente.public_key).call()
    for b in c["balances"]:
        eti = b.get("asset_code", "XLM")
        print(f"     {eti:<6} {float(b['balance']):>14,.4f}")

    print("\n5. Path payment TEUR -> XLM")
    print("     Su testnet non esiste un mercato: senza un'offerta sul libro")
    print("     la rotta non esiste e l'operazione fallisce. E' il risultato")
    print("     atteso, ed e' la dimostrazione che la liquidita' va misurata")
    print("     altrove -- vedi f0_liquidita.py su Horizon mainnet.")
    try:
        p = srv.strict_send_paths(TEUR, "10", [Asset.native()]).call()
        n = len(p["_embedded"]["records"])
        print(f"     rotte trovate: {n}")
    except Exception as e:
        print(f"     nessuna rotta ({type(e).__name__})")

    print("\n" + "=" * 74)
    print("COSA ABBIAMO IMPARATO, IN NUMERI")
    print("=" * 74)
    print("  - fee per operazione: 100 stroops = 0,00001 XLM")
    print("  - ogni trustline blocca 0,5 XLM di riserva (non spesa: bloccata)")
    print("  - un conto parte da 1 XLM minimo (2 base reserve)")
    print("  - la testnet non ha mercato: i prezzi si guardano in mainnet\n")


if __name__ == "__main__":
    main()
