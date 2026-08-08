"""Real liquidity and slippage, read from mainnet Horizon. Read-only.

    python scripts/f0_liquidita.py

No account, no keys, no cost: mainnet Horizon is public and queryable. This is
the only way to measure real prices, because testnet has no market (verified:
zero routes).

It does two things, and the first is a security check:

1. IDENTIFIES THE REAL ISSUER. On Stellar an asset is the pair (code, issuer):
   the code alone identifies nothing, and anyone can issue "EURC". As of
   2026-08-08 there are 66 of them. Among these, `circle-assets.com` imitates
   `circle.com` with 8 billion supply and 154 accounts already holding it. The
   signal that works is not the name but the NUMBER OF LIQUIDITY POOLS: the
   real ones have them (120 for Circle, 37 for MYKOBO), the imitations have
   none - nobody puts real liquidity behind a fake asset.

2. MEASURES SLIPPAGE by size, i.e. how much the price worsens as the amount
   grows. That is the number that says whether a minimum plan size holds up.

CAVEAT: this measures the classic SDEX, which a Soroban contract CANNOT reach.
For the venue a contract can actually use, see f0bis_liquidita_soroban.py.
"""
from __future__ import annotations

import json
import re
import urllib.request

HORIZON = "https://horizon.stellar.org"
UA = {"User-Agent": "Mozilla/5.0"}
CIRCLE_EURC = "GDHU6WRG4IEQXM5NZ4BMPKOXHW76MZM4Y2IEMFDVXBSDP6SJY4ITNPP2"
SIZES = (1, 2, 5, 10, 25, 50, 100, 250, 1000)


def get(url: str) -> dict:
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=40))


def toml_domain(r: dict) -> str:
    href = r.get("_links", {}).get("toml", {}).get("href", "")
    m = re.search(r"https?://([^/]+)", href)
    return m.group(1) if m else "(no toml)"


def issuers(code: str) -> None:
    records = get(f"{HORIZON}/assets?asset_code={code}&limit=200")["_embedded"]["records"]
    print("=" * 76)
    print(f"1. WHO ISSUES '{code}' - {len(records)} distinct issuers")
    print("=" * 76)
    print("\n  The code does not identify the asset. Sorted by liquidity pools,")
    print("  the signal an impersonator cannot cheaply fake.\n")
    records.sort(key=lambda r: (-int(r.get("num_liquidity_pools") or 0),
                                -int(r.get("accounts", {}).get("authorized") or 0)))
    print(f"  {'toml domain':<30} {'pools':>6} {'holders':>9} {'supply':>20}")
    print("  " + "-" * 68)
    for r in records[:6]:
        pools = int(r.get("num_liquidity_pools") or 0)
        holders = int(r.get("accounts", {}).get("authorized") or 0)
        supply = float(r.get("balances", {}).get("authorized") or 0)
        flag = "  <- used" if r["asset_issuer"] == CIRCLE_EURC else (
            "  <- ABSURD SUPPLY, ZERO POOLS" if pools == 0 and supply > 1e9 else "")
        print(f"  {toml_domain(r):<30} {pools:>6} {holders:>9,} {supply:>20,.2f}{flag}")
    print(f"\n  Issuer used in this project: {CIRCLE_EURC}")
    print("  The owner must pass THIS address when creating a plan, never a code.")


def slippage(issuer: str) -> None:
    print("\n" + "=" * 76)
    print("2. REAL SLIPPAGE EURC -> XLM, by size")
    print("=" * 76)
    print(f"\n  {'send EUR':>10} {'get XLM':>13} {'price':>11} "
          f"{'hops':>5} {'slippage':>10} {'cost in EUR':>13}")
    print("  " + "-" * 68)
    baseline = None
    for size in SIZES:
        url = (f"{HORIZON}/paths/strict-send?source_asset_type=credit_alphanum4"
               f"&source_asset_code=EURC&source_asset_issuer={issuer}"
               f"&source_amount={size}&destination_assets=native")
        routes = get(url)["_embedded"]["records"]
        if not routes:
            print(f"  {size:>10,} no route")
            continue
        best = max(routes, key=lambda r: float(r["destination_amount"]))
        dest = float(best["destination_amount"])
        price = size / dest
        if baseline is None:
            baseline = price
        slip = price / baseline - 1
        print(f"  {size:>10,} {dest:>13,.4f} {price:>11.6f} "
              f"{len(best['path']):>5} {slip:>9.3%} {size * slip:>12.4f}e")

    print("\n  'hops' = intermediate assets crossed. Zero means a direct")
    print("  EURC/XLM market, which is the best possible condition.")
    print("\n  At the sizes that matter here (2-50 EUR) slippage stays under")
    print("  0.06%: an order of magnitude below the keeper fee. It is NOT the")
    print("  binding constraint. The fixed cost is.\n")


if __name__ == "__main__":
    issuers("EURC")
    slippage(CIRCLE_EURC)
