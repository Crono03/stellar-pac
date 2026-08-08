"""Keeper: finds due plans and executes them, collecting the fee.

    python keeper/keeper.py <CONTRACT_ID> <SECRET_KEY> [--network testnet|mainnet]
    python keeper/keeper.py <CONTRACT_ID> <SECRET_KEY> --once
    python keeper/keeper.py <CONTRACT_ID> --read-only

WHAT THIS KEEPER IS NOT.
It is not a privileged component. The contract does not know it exists and does
not depend on it: `execute` is public and anyone may call it. If this process
stops, plans remain valid and the next passer-by executes them.

THE ECONOMICS, STATED BEFORE THE CODE BECAUSE THEY CHANGE WHO THIS IS FOR.
Per execution: collects 0.0783 XLM (fee at a 3x margin over network cost), pays
~0.0261 XLM of network cost, nets **EUR 0.0074**. For an independent third
party to keep a process running you would need ~6,755 executions per month.
With five monthly plans, revenue is **four cents a month**.

Honest conclusion: **at the start the owner runs this for their own plans.**
There the fee is not a cost, because they pay it to themselves: their real
outlay is the network cost alone, EUR 0.0037. The fee exists for another
reason -- **it is not how the system runs, it is what makes it survive your
absence.** Machine off, travelling, forgot: the plan does not skip, someone
else executes it and is paid for the trouble.

TWO FRICTIONS WORTH KNOWING
1. The fee is paid in the source asset (e.g. EURC), but transactions are paid
   in XLM: a third-party keeper collects one and consumes the other, so it must
   periodically convert.
2. Receiving a non-native asset needs a trustline, which locks 0.5 XLM.
   Recovered in ~10 executions, but it is a barrier to entry.
"""
from __future__ import annotations

import sys
import time

from stellar_sdk import (Account, Keypair, Network, SorobanServer,
                         TransactionBuilder, scval)

NETWORKS = {
    "mainnet": ("https://mainnet.sorobanrpc.com", Network.PUBLIC_NETWORK_PASSPHRASE),
    "testnet": ("https://soroban-testnet.stellar.org", Network.TESTNET_NETWORK_PASSPHRASE),
}
POLL_SECONDS = 60


def due_plans(srv: SorobanServer, passphrase: str, contract: str) -> list[int]:
    """Asks the contract which plans are ready. Simulated, so it costs nothing.

    Distinguishes "no plans due" from "contract unreachable" by **raising** in
    the second case. The first version returned an empty list for both: a wrong
    contract id printed "no plans due" and the keeper spun forever, looking
    healthy. A configuration fault disguised as normal operation is worse than
    a noisy error.
    """
    tx = (TransactionBuilder(Account(Keypair.random().public_key, 0), passphrase,
                             base_fee=100)
          .append_invoke_contract_function_op(contract, "due_plans", [])
          .set_timeout(60).build())
    r = srv.simulate_transaction(tx)
    if getattr(r, "error", None):
        raise RuntimeError(f"contract did not answer: {str(r.error)[:120]}")
    if not r.results:
        raise RuntimeError("simulation returned no result - is the contract id right?")
    v = scval.to_native(r.results[0].xdr)
    return list(v) if v else []


def try_execute(srv: SorobanServer, passphrase: str, contract: str, kp: Keypair,
                account: Account, plan_id: int):
    """Simulates `execute` BEFORE submitting it.

    This is the difference between a keeper that earns and one that loses. If
    another keeper got there first, or `min_out` is not met, the transaction
    would fail **and the network fee would still be paid**. Simulating costs
    nothing and allows walking away in time.
    """
    tx = (TransactionBuilder(account, passphrase, base_fee=1_000_000)
          .append_invoke_contract_function_op(
              contract, "execute",
              [scval.to_address(kp.public_key), scval.to_uint32(plan_id)])
          .set_timeout(120).build())
    # Broad catch on purpose: any simulation failure has the same consequence
    # for a keeper -- skip this plan and move on. Distinguishing the causes
    # would not change the action.
    try:
        return srv.prepare_transaction(tx), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:130]}"


def loop(contract: str, secret: str | None, network: str, once: bool) -> None:
    url, passphrase = NETWORKS[network]
    srv = SorobanServer(url)
    kp = Keypair.from_secret(secret) if secret else None

    print(f"  network   {network}")
    print(f"  contract  {contract}")
    print(f"  keeper    {kp.public_key if kp else '(read-only)'}\n")

    while True:
        try:
            ready = due_plans(srv, passphrase, contract)
        except Exception as e:
            print(f"  [{time.strftime('%H:%M:%S')}] ERROR: {e}")
            if once:
                return
            time.sleep(POLL_SECONDS)
            continue

        now = time.strftime("%H:%M:%S")
        if not ready:
            print(f"  [{now}] no plans due")
        else:
            print(f"  [{now}] {len(ready)} due: {ready}")
            if kp is None:
                print("         read-only, not executing")
            else:
                account = srv.load_account(kp.public_key)
                for plan_id in ready:
                    prepared, error = try_execute(srv, passphrase, contract, kp,
                                                  account, plan_id)
                    if error:
                        # The normal case, not a fault: someone got there
                        # first, or the min_out guardrail stopped the run.
                        print(f"         plan {plan_id}: skipping - {error}")
                        continue
                    prepared.sign(kp)
                    result = srv.send_transaction(prepared)
                    print(f"         plan {plan_id}: submitted {result.hash[:16]}...")
                    account.increment_sequence_number()

        if once:
            return
        time.sleep(POLL_SECONDS)


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    contract = argv[0]
    secret = argv[1] if len(argv) > 1 and argv[1].startswith("S") else None
    network = argv[argv.index("--network") + 1] if "--network" in argv else "testnet"
    loop(contract, secret, network, "--once" in argv or "--read-only" in argv)


if __name__ == "__main__":
    main()
