"""Keeper: cerca i piani scaduti e li esegue, incassando la fee.

    python keeper/keeper.py <CONTRACT_ID> <CHIAVE_SEGRETA> [--rete testnet|mainnet]
    python keeper/keeper.py <CONTRACT_ID> <CHIAVE_SEGRETA> --una-volta
    python keeper/keeper.py <CONTRACT_ID> --solo-lettura

COSA NON E' QUESTO KEEPER.
Non e' un componente privilegiato del sistema. Il contratto non lo conosce e
non dipende da lui: `execute` e' pubblica, e chiunque puo' chiamarla. Se questo
processo si spegne, i piani restano validi e il primo che passa li esegue.

L'ECONOMIA, DETTA PRIMA DEL CODICE PERCHE' CAMBIA A CHI SERVE.
Per esecuzione: incassa 0,0783 XLM (fee al margine 3x), paga ~0,0261 XLM di
rete, guadagna **0,0074 EUR**. Perche' a un terzo indipendente convenga tenere
in piedi un processo servirebbero ~6.755 esecuzioni al mese. Con cinque piani
mensili il ricavo e' **4 centesimi al mese**.

Conclusione onesta: **all'inizio il keeper lo esegue l'owner per se' stesso.**
E li' la fee non e' un costo, perche' se la paga da solo: il suo esborso reale
e' il solo costo di rete, 0,0037 EUR. La fee esiste per un'altra ragione --
**non e' come il sistema funziona, e' cio' che lo fa sopravvivere alla tua
assenza.** Se il tuo computer e' spento, il piano non salta: qualcun altro lo
esegue e viene pagato per il disturbo.

DUE ATTRITI DA SAPERE
1. La fee e' pagata nell'asset di partenza (EURC), ma le transazioni si pagano
   in XLM: un keeper terzo incassa EURC e consuma XLM, quindi deve convertire.
2. Per ricevere EURC serve una trustline, cioe' 0,5 XLM bloccati: recuperati
   in ~10 esecuzioni, ma sono una barriera d'ingresso.
"""
from __future__ import annotations

import sys
import time

from stellar_sdk import (Account, Keypair, Network, SorobanServer,
                         TransactionBuilder, scval)

RETI = {
    "mainnet": ("https://mainnet.sorobanrpc.com", Network.PUBLIC_NETWORK_PASSPHRASE),
    "testnet": ("https://soroban-testnet.stellar.org", Network.TESTNET_NETWORK_PASSPHRASE),
}
PAUSA = 60          # secondi fra una scansione e l'altra
STROOP = 10 ** 7


def eseguibili(srv: SorobanServer, rete: str, contratto: str) -> list[int]:
    """Chiede al contratto quali piani sono pronti. Simulazione: non costa nulla.

    Distingue "nessun piano pronto" da "contratto irraggiungibile" **alzando
    un'eccezione** nel secondo caso. La prima versione restituiva lista vuota
    per entrambi: un contract id sbagliato stampava "nessun piano pronto" e il
    keeper girava a vuoto per sempre, sembrando sano. Un guasto di
    configurazione che si traveste da funzionamento normale e' peggio di un
    errore rumoroso.
    """
    tx = (TransactionBuilder(Account(Keypair.random().public_key, 0), rete, base_fee=100)
          .append_invoke_contract_function_op(contratto, "eseguibili", [])
          .set_timeout(60).build())
    r = srv.simulate_transaction(tx)
    if getattr(r, "error", None):
        raise RuntimeError(f"il contratto non risponde: {str(r.error)[:120]}")
    if not r.results:
        raise RuntimeError("simulazione senza risultato: contract id giusto?")
    v = scval.to_native(r.results[0].xdr)
    return list(v) if v else []


def prova(srv: SorobanServer, rete: str, contratto: str, kp: Keypair,
          conto: Account, id_piano: int):
    """Simula `execute` PRIMA di inviarla.

    E' la differenza fra un keeper che guadagna e uno che perde. Se un altro
    keeper e' arrivato per primo, o se `min_out` non e' soddisfatto, la
    transazione fallirebbe **e la fee di rete andrebbe pagata lo stesso**.
    Simulare costa zero e permette di rinunciare in tempo.
    """
    tx = (TransactionBuilder(conto, rete, base_fee=1_000_000)
          .append_invoke_contract_function_op(
              contratto, "execute",
              [scval.to_address(kp.public_key), scval.to_uint32(id_piano)])
          .set_timeout(120).build())
    # Cattura generica di proposito: `PrepareTransactionFailedError` non esiste
    # in questa versione dell'SDK, e comunque QUALUNQUE fallimento della
    # simulazione ha la stessa conseguenza per il keeper -- rinunciare a questo
    # piano e passare al prossimo. Distinguere le cause non cambierebbe l'azione.
    try:
        return srv.prepare_transaction(tx), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:130]}"


def ciclo(contratto: str, segreto: str | None, nome_rete: str, una_volta: bool):
    url, rete = RETI[nome_rete]
    srv = SorobanServer(url)
    kp = Keypair.from_secret(segreto) if segreto else None

    print(f"  rete       {nome_rete}")
    print(f"  contratto  {contratto}")
    print(f"  keeper     {kp.public_key if kp else '(sola lettura)'}\n")

    while True:
        try:
            pronti = eseguibili(srv, rete, contratto)
        except Exception as e:
            print(f"  [{time.strftime('%H:%M:%S')}] ERRORE: {e}")
            if una_volta:
                return
            time.sleep(PAUSA)
            continue

        ora = time.strftime("%H:%M:%S")
        if not pronti:
            print(f"  [{ora}] nessun piano pronto")
        else:
            print(f"  [{ora}] {len(pronti)} pronti: {pronti}")
            if kp is None:
                print("         sola lettura, non eseguo")
            else:
                conto = srv.load_account(kp.public_key)
                for id_piano in pronti:
                    pronta, errore = prova(srv, rete, contratto, kp, conto, id_piano)
                    if errore:
                        # Il caso normale, non un guasto: qualcuno e' arrivato
                        # prima, oppure il parapetto min_out ha fermato il giro.
                        print(f"         piano {id_piano}: rinuncio — {errore}")
                        continue
                    pronta.sign(kp)
                    esito = srv.send_transaction(pronta)
                    print(f"         piano {id_piano}: inviata {esito.hash[:16]}…")
                    conto.increment_sequence_number()

        if una_volta:
            return
        time.sleep(PAUSA)


def main() -> None:
    arg = sys.argv[1:]
    if not arg:
        print(__doc__)
        return
    contratto = arg[0]
    segreto = arg[1] if len(arg) > 1 and arg[1].startswith("S") else None
    nome_rete = arg[arg.index("--rete") + 1] if "--rete" in arg else "testnet"
    ciclo(contratto, segreto, nome_rete, "--una-volta" in arg or "--solo-lettura" in arg)


if __name__ == "__main__":
    main()
