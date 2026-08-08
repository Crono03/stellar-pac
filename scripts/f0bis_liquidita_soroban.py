"""F0-bis — la liquidita' che il CONTRATTO puo' davvero raggiungere.

    python scripts/f0bis_liquidita_soroban.py

PERCHE' ESISTE QUESTO SCRIPT.
`f0_liquidita.py` misura la SDEX classica e da' numeri ottimi (0,001% a 2 EUR).
Ma un contratto Soroban **non puo' toccare la SDEX**: quel mercato non e'
raggiungibile da `execute()`. La misura che conta e' questa, sui protocolli
Soroban, ed e' l'unica su cui si puo' basare il disegno.

Metodo: simulazione di una chiamata al SoroswapRouter via Soroban RPC. E'
gratuita, in sola lettura, non richiede un conto finanziato e non tocca la rete.
"""
from __future__ import annotations

from stellar_sdk import (Address, Asset, Keypair, Network, SorobanServer,
                         TransactionBuilder, scval)

RPC = "https://mainnet.sorobanrpc.com"
RETE = Network.PUBLIC_NETWORK_PASSPHRASE

ROUTER = "CAG5LRYQ5JVEUI5TEID72EYOVX44TTUJT5BQR2J6J77FH65PCCFAJDDH"
FACTORY = "CA4HEQTL2WPEUYKYKCDOHCDNIV4QHNJ7EL4J4NQ6VADP7SYHVRYZ7AW2"

EMITTENTE_EURC = "GDHU6WRG4IEQXM5NZ4BMPKOXHW76MZM4Y2IEMFDVXBSDP6SJY4ITNPP2"
EMITTENTE_USDC = "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN"

STROOP = 10 ** 7          # tutti gli importi Stellar hanno 7 decimali
TAGLIE = (1, 2, 5, 10, 25, 50, 100, 250, 1000)


def sac(asset: Asset) -> str:
    return asset.contract_id(RETE)


def simula(srv: SorobanServer, contratto: str, funzione: str, args: list):
    """Chiama una funzione in simulazione. Nessuna firma, nessun costo.

    Il conto sorgente e' una chiave a caso mai finanziata: la simulazione non
    verifica saldo ne' sequence, serve solo a costruire una transazione valida.
    """
    kp = Keypair.random()
    conto = srv.load_account(kp.public_key) if False else None
    from stellar_sdk import Account
    conto = Account(kp.public_key, 0)
    tx = (TransactionBuilder(conto, RETE, base_fee=100)
          .append_invoke_contract_function_op(contratto, funzione, args)
          .set_timeout(60).build())
    return srv.simulate_transaction(tx)


def quota(srv: SorobanServer, da: str, a: str, importo_umano: float):
    """Quanto rende uno swap di `importo_umano` unita' di `da` verso `a`."""
    amount = int(importo_umano * STROOP)
    args = [scval.to_int128(amount),
            scval.to_vec([Address(da).to_xdr_sc_val(), Address(a).to_xdr_sc_val()])]
    for nome in ("router_get_amounts_out", "get_amounts_out"):
        r = simula(srv, ROUTER, nome, args)
        if getattr(r, "error", None):
            continue
        if r.results:
            v = scval.to_native(r.results[0].xdr)
            return (v[-1] / STROOP) if isinstance(v, list) else None, nome
    return None, None


def main() -> None:
    srv = SorobanServer(RPC)
    xlm, eurc = sac(Asset.native()), sac(Asset("EURC", EMITTENTE_EURC))
    usdc = sac(Asset("USDC", EMITTENTE_USDC))

    print("=" * 76)
    print("F0-bis — LIQUIDITA' RAGGIUNGIBILE DA UN CONTRATTO SOROBAN")
    print("=" * 76)
    print(f"\n  router  {ROUTER}")
    print(f"  XLM     {xlm}")
    print(f"  EURC    {eurc}")
    print(f"  USDC    {usdc}\n")

    for eti, sorgente in (("EURC -> XLM", eurc), ("USDC -> XLM", usdc)):
        print("-" * 76)
        print(f"  {eti}")
        print("-" * 76)
        print(f"  {'invii':>10} {'ricevi XLM':>15} {'prezzo':>12} {'slippage':>11}")
        rif = None
        vuoto = True
        for a in TAGLIE:
            out, _ = quota(srv, sorgente, xlm, a)
            if out is None or out <= 0:
                print(f"  {a:>10,} {'nessuna rotta':>15}")
                continue
            vuoto = False
            p = a / out
            if rif is None:
                rif = p
            print(f"  {a:>10,} {out:>15,.4f} {p:>12.6f} {p / rif - 1:>10.3%}")
        if vuoto:
            print("\n  NESSUNA LIQUIDITA' SOROBAN su questa coppia.")
        print()


if __name__ == "__main__":
    main()
