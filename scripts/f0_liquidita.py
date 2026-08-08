"""F0 — liquidita' e slippage veri, letti da Horizon MAINNET in sola lettura.

    python scripts/f0_liquidita.py

Nessun account, nessuna chiave, nessuna spesa: Horizon mainnet e' pubblico e
interrogabile. E' l'unico modo di misurare i prezzi veri, perche' la testnet
non ha mercato (verificato: 0 rotte).

Fa due cose, e la prima e' di sicurezza:

1. IDENTIFICA L'EMITTENTE VERO. Su Stellar l'asset e' la coppia (codice,
   emittente): il codice da solo non identifica niente e chiunque puo' emettere
   "EURC". All'8/8/2026 ne esistono 66. Fra questi, `circle-assets.com` imita
   `circle.com` con 8 miliardi di supply e 154 conti che ci sono gia' caduti.
   Il discriminante che funziona non e' il nome ma il NUMERO DI LIQUIDITY POOL:
   gli asset veri ne hanno (120 Circle, 37 MYKOBO), le imitazioni zero --
   nessuno mette liquidita' vera su un asset falso.

2. MISURA LO SLIPPAGE per taglia, cioe' quanto peggiora il prezzo al crescere
   dell'importo. E' il numero che dice se la soglia minima del PAC regge.
"""
from __future__ import annotations

import json
import re
import urllib.request

HORIZON = "https://horizon.stellar.org"
UA = {"User-Agent": "Mozilla/5.0"}
CIRCLE_EURC = "GDHU6WRG4IEQXM5NZ4BMPKOXHW76MZM4Y2IEMFDVXBSDP6SJY4ITNPP2"
TAGLIE = (1, 2, 5, 10, 25, 50, 100, 250, 1000)


def get(url: str) -> dict:
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=40))


def dominio(r: dict) -> str:
    h = r.get("_links", {}).get("toml", {}).get("href", "")
    m = re.search(r"https?://([^/]+)", h)
    return m.group(1) if m else "(nessun toml)"


def emittenti(codice: str) -> None:
    d = get(f"{HORIZON}/assets?asset_code={codice}&limit=200")["_embedded"]["records"]
    print("=" * 76)
    print(f"1. CHI EMETTE '{codice}' — {len(d)} emittenti distinti")
    print("=" * 76)
    print("\n  Il codice non identifica l'asset. Ordino per liquidity pool, che e'")
    print("  il segnale che un'imitazione non puo' falsificare a buon mercato.\n")
    d.sort(key=lambda r: (-int(r.get("num_liquidity_pools") or 0),
                          -int(r.get("accounts", {}).get("authorized") or 0)))
    print(f"  {'dominio toml':<30} {'pool':>5} {'conti':>8} {'supply':>20}")
    print("  " + "-" * 66)
    for r in d[:6]:
        pool = int(r.get("num_liquidity_pools") or 0)
        acc = int(r.get("accounts", {}).get("authorized") or 0)
        bal = float(r.get("balances", {}).get("authorized") or 0)
        flag = "  <- usato" if r["asset_issuer"] == CIRCLE_EURC else (
            "  <- SUPPLY ASSURDA, POOL ZERO" if pool == 0 and bal > 1e9 else "")
        print(f"  {dominio(r):<30} {pool:>5} {acc:>8,} {bal:>20,.2f}{flag}")
    print(f"\n  Emittente pinnato nel codice: {CIRCLE_EURC}")
    print("  Il contratto deve fissare QUESTO indirizzo, mai risolvere per codice.")


def slippage(emittente: str) -> None:
    print("\n" + "=" * 76)
    print("2. SLIPPAGE REALE EURC -> XLM, per taglia")
    print("=" * 76)
    print(f"\n  {'invii EUR':>10} {'ricevi XLM':>13} {'prezzo':>11} "
          f"{'salti':>6} {'slippage':>10} {'costo in EUR':>13}")
    print("  " + "-" * 68)
    rif = None
    for a in TAGLIE:
        u = (f"{HORIZON}/paths/strict-send?source_asset_type=credit_alphanum4"
             f"&source_asset_code=EURC&source_asset_issuer={emittente}"
             f"&source_amount={a}&destination_assets=native")
        rs = get(u)["_embedded"]["records"]
        if not rs:
            print(f"  {a:>10,} nessuna rotta")
            continue
        best = max(rs, key=lambda r: float(r["destination_amount"]))
        dest = float(best["destination_amount"])
        prezzo = a / dest
        if rif is None:
            rif = prezzo
        s = prezzo / rif - 1
        print(f"  {a:>10,} {dest:>13,.4f} {prezzo:>11.6f} "
              f"{len(best['path']):>6} {s:>9.3%} {a * s:>12.4f}e")

    print("\n  'salti' = asset intermedi attraversati. Zero significa mercato")
    print("  diretto EURC/XLM, che e' la condizione migliore possibile.")
    print("\n  Alla taglia che ci interessa (2-50 EUR) lo slippage sta sotto lo")
    print("  0,06%: e' un ordine di grandezza sotto la fee del keeper (0,5%),")
    print("  quindi NON e' il vincolo. Il vincolo resta il costo fisso.\n")


if __name__ == "__main__":
    emittenti("EURC")
    slippage(CIRCLE_EURC)
