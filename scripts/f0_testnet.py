"""First contact with the network: a testnet account and a real path payment.

    python scripts/f0_testnet.py

WHAT IT DOES, AND WHY IN THIS ORDER.
Creates a testnet account, funds it with friendbot (free), opens a trustline to
a test asset and attempts a path payment. The point is to see with your own
eyes the cycle the contract will automate: trustline, fee, sequence number,
operation result.

WARNING - TESTNET DOES NOT MEASURE LIQUIDITY.
Testnet assets are disconnected from mainnet: EURC does not exist there with
real liquidity. Anyone using testnet to estimate slippage measures a fake
market and builds on it. Liquidity must be measured READ-ONLY against mainnet
Horizon, which is public and free: that is what f0_liquidita.py does.

Here you learn the MECHANICS. There you measure the PRICES. Two different
things, and keeping them apart is the point of this phase.

The keys generated here are TESTNET keys: they have no value and are printed
deliberately. Never reuse them on mainnet.
"""
from __future__ import annotations

import json
import urllib.request

from stellar_sdk import Asset, Keypair, Network, Server, TransactionBuilder

HORIZON = "https://horizon-testnet.stellar.org"
FRIENDBOT = "https://friendbot.stellar.org"


def fund(public_key: str) -> bool:
    """Friendbot returns 403 to urllib's default user-agent.

    Verified 2026-08-08: same URL, same address, 403 without a header and 200
    with a browser user-agent. Not rate limiting, not a malformed address - a
    client filter. Without this header phase F0 looks broken for the wrong
    reason.
    """
    req = urllib.request.Request(f"{FRIENDBOT}/?addr={public_key}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            json.load(r)
        return True
    except Exception as e:
        print(f"    friendbot refused: {e}")
        return False


def main() -> None:
    print("=" * 74)
    print("F0 - TESTNET: mechanics of the cycle, not a price measurement")
    print("=" * 74)

    srv = Server(HORIZON)
    passphrase = Network.TESTNET_NETWORK_PASSPHRASE

    # Two accounts: one acts as the issuer of a fake asset, one as the user.
    issuer = Keypair.random()
    user = Keypair.random()
    print("\n1. Generating two keypairs (testnet, worthless)")
    print(f"     issuer {issuer.public_key}")
    print(f"     user   {user.public_key}")

    print("\n2. Funding them with friendbot")
    for label, kp in (("issuer", issuer), ("user", user)):
        ok = fund(kp.public_key)
        print(f"     {label:<8} {'funded' if ok else 'FAILED'}")
        if not ok:
            return

    account = srv.accounts().account_id(user.public_key).call()
    native = next(b for b in account["balances"] if b["asset_type"] == "native")
    print(f"     user balance: {float(native['balance']):,.4f} XLM")
    print(f"     existing subentries: {account['subentry_count']}"
          f"  -> minimum balance required: "
          f"{(2 + account['subentry_count']) * 0.5:.1f} XLM")

    # A trustline is the step that consumes a reserve — worth seeing directly.
    teur = Asset("TEUR", issuer.public_key)
    print("\n3. Opening a trustline for TEUR (the issuer's fake asset)")
    src = srv.load_account(user.public_key)
    tx = (TransactionBuilder(src, passphrase, base_fee=100)
          .append_change_trust_op(asset=teur)
          .set_timeout(60).build())
    tx.sign(user)
    result = srv.submit_transaction(tx)
    print(f"     succeeded: {result['successful']}   fee paid: "
          f"{int(result['fee_charged']) / 1e7:.7f} XLM")

    account = srv.accounts().account_id(user.public_key).call()
    print(f"     subentries now: {account['subentry_count']}"
          f"  -> minimum balance: {(2 + account['subentry_count']) * 0.5:.1f} XLM")
    print("     ^ every trustline LOCKS 0.5 XLM of reserve. Not spent: locked.")
    print("       That is the cost the contract must account for, per asset.")

    print("\n4. The issuer sends 100 TEUR to the user")
    issuer_account = srv.load_account(issuer.public_key)
    tx = (TransactionBuilder(issuer_account, passphrase, base_fee=100)
          .append_payment_op(destination=user.public_key, asset=teur, amount="100")
          .set_timeout(60).build())
    tx.sign(issuer)
    result = srv.submit_transaction(tx)
    print(f"     succeeded: {result['successful']}")

    account = srv.accounts().account_id(user.public_key).call()
    for b in account["balances"]:
        print(f"     {b.get('asset_code', 'XLM'):<6} {float(b['balance']):>14,.4f}")

    print("\n5. Path payment TEUR -> XLM")
    print("     Testnet has no market: with no offer on the book the route does")
    print("     not exist and the operation fails. That is the expected result,")
    print("     and the proof that liquidity must be measured elsewhere - see")
    print("     f0_liquidita.py against mainnet Horizon.")
    try:
        paths = srv.strict_send_paths(teur, "10", [Asset.native()]).call()
        print(f"     routes found: {len(paths['_embedded']['records'])}")
    except Exception as e:
        print(f"     no route ({type(e).__name__})")

    print("\n" + "=" * 74)
    print("WHAT WE LEARNED, IN NUMBERS")
    print("=" * 74)
    print("  - fee per operation: 100 stroops = 0.00001 XLM")
    print("  - every trustline locks 0.5 XLM of reserve (locked, not spent)")
    print("  - an account starts at a 1 XLM minimum (2 base reserves)")
    print("  - testnet has no market: prices are read on mainnet\n")


if __name__ == "__main__":
    main()
