"""Genera la brochure del progetto in PDF.

    python scripts/genera_brochure.py

Documento completo: cosa stiamo costruendo, il problema da cui nasce, come
funziona, i numeri misurati, cosa NON promette, la sicurezza, lo stato, e in
coda le domande e risposte per la preparazione alla candidatura.

In italiano perche' e' materiale dell'autore: il repository pubblico resta in
inglese. Escluso da git.
"""
from __future__ import annotations

import datetime as dt
import pathlib

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

USCITA = pathlib.Path(__file__).resolve().parents[1] / "stellar-pac-brochure.pdf"

SCURO = colors.HexColor("#11141b")
CIANO = colors.HexColor("#0d7f8c")
CIANO_C = colors.HexColor("#e8f6f8")
GRIGIO = colors.HexColor("#5a6070")
BORDO = colors.HexColor("#d3d8e0")
ROSSO = colors.HexColor("#a4343a")
ROSSO_C = colors.HexColor("#fdeef0")
VERDE = colors.HexColor("#1f7a4d")
AMBRA_C = colors.HexColor("#fdf6e3")

ss = getSampleStyleSheet()
S = {
    "h0": ParagraphStyle("h0", parent=ss["Title"], fontSize=30, leading=34,
                         textColor=SCURO, alignment=TA_CENTER, spaceAfter=2),
    "sub0": ParagraphStyle("sub0", parent=ss["Normal"], fontSize=13, leading=19,
                           textColor=CIANO, alignment=TA_CENTER, spaceAfter=22),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, leading=21,
                         textColor=CIANO, spaceBefore=16, spaceAfter=7),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12.5, leading=16,
                         textColor=SCURO, spaceBefore=12, spaceAfter=5),
    "p": ParagraphStyle("p", parent=ss["Normal"], fontSize=10, leading=15.2,
                        alignment=TA_JUSTIFY, spaceAfter=7),
    "pc": ParagraphStyle("pc", parent=ss["Normal"], fontSize=10, leading=15.2,
                         alignment=TA_CENTER, textColor=GRIGIO, spaceAfter=7),
    "small": ParagraphStyle("small", parent=ss["Normal"], fontSize=8.6, leading=12.4,
                            textColor=GRIGIO, spaceAfter=5),
    "cell": ParagraphStyle("cell", parent=ss["Normal"], fontSize=9, leading=12.6),
    "cellb": ParagraphStyle("cellb", parent=ss["Normal"], fontSize=9, leading=12.6,
                            fontName="Helvetica-Bold"),
    "risp": ParagraphStyle("risp", parent=ss["Normal"], fontSize=10.5, leading=15,
                           textColor=ROSSO, leftIndent=9, spaceAfter=6),
    "dom": ParagraphStyle("dom", parent=ss["Heading2"], fontSize=11.5, leading=15,
                          textColor=SCURO, spaceBefore=13, spaceAfter=5),
    "inc": ParagraphStyle("inc", parent=ss["Normal"], fontSize=9.4, leading=13.6,
                          alignment=TA_JUSTIFY, textColor=GRIGIO,
                          leftIndent=16, spaceAfter=9),
}


def P(t, s="p"):
    return Paragraph(t, S[s])


def riquadro(testo, sfondo=CIANO_C, bordo=CIANO):
    t = Table([[P(testo, "p")]], colWidths=[166 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), sfondo),
        ("BOX", (0, 0), (-1, -1), 0.9, bordo),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return KeepTogether([Spacer(1, 3), t, Spacer(1, 9)])


def tabella(righe, larghezze, intestata=True, evidenzia=None):
    dati = [[P(c, "cellb" if (intestata and i == 0) else "cell") for c in r]
            for i, r in enumerate(righe)]
    t = Table(dati, colWidths=larghezze, repeatRows=1 if intestata else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, BORDO),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
          ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    if intestata:
        st += [("BACKGROUND", (0, 0), (-1, 0), SCURO),
               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    for i in range(1 + (1 if intestata else 0), len(dati), 2):
        st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6f8fa")))
    if evidenzia:
        for i in evidenzia:
            st.append(("BACKGROUND", (0, i), (-1, i), AMBRA_C))
    t.setStyle(TableStyle(st))
    return KeepTogether([Spacer(1, 2), t, Spacer(1, 10)])


def flusso():
    passi = [
        ("1", "L'utente crea un piano", "Sceglie asset di partenza e arrivo, importo,\ncadenza e fee del keeper. Paga il rent: ~1,60 EUR."),
        ("2", "Deposita il budget", "I fondi restano nel contratto. Solo l'owner\npuo' riprenderseli."),
        ("3", "Il contratto aspetta", "Soroban non ha uno scheduler: nessun contratto\nsi sveglia da solo."),
        ("4", "Chiunque chiama execute()", "Il chiamante incassa la fee. Nessun operatore\nprivilegiato, nessun server da tenere vivo."),
        ("5", "Lo swap va sul router", "Il contratto autorizza UN solo trasferimento,\ndi importo esatto, verso la pair dichiarata."),
        ("6", "L'output va all'owner", "La destinazione e' letta dallo storage,\nmai dagli argomenti della chiamata."),
    ]
    dati = []
    for n, tit, desc in passi:
        dati.append([P(f"<b>{n}</b>", "cellb"), P(f"<b>{tit}</b><br/>"
                     f"<font size=8.5 color='#5a6070'>{desc.replace(chr(10), '<br/>')}</font>", "cell")])
    t = Table(dati, colWidths=[11 * mm, 155 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), CIANO),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDO),
        ("LEFTPADDING", (1, 0), (1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([Spacer(1, 2), t, Spacer(1, 10)])


QA = [
    ("Perche' `to` nello swap e' il contratto e non l'owner?",
     "Perche' nel router `to` non e' solo il destinatario: e' anche il pagatore.",
     "Soroban non ha `msg.sender` e la firma del router non ha un parametro `from`. La pair "
     "preleva l'importo da `to`. Se passassi l'owner, il router preleverebbe dal <b>suo "
     "portafoglio</b> invece che dal budget depositato: il piano farebbe una cosa diversa da "
     "quella dichiarata, e l'utente verrebbe prosciugato altrove mentre il budget resta fermo.",
     "«Come lo sai?» Sta nel sorgente di Soroswap, e un test lo dimostra. La prima versione del "
     "mock prelevava da se' stessa e <b>avrebbe lasciato passare l'errore</b>: un mock che non "
     "imita il comportamento vero non e' un test."),
    ("Perche' `execute` e' pubblica e senza `require_auth`?",
     "Perche' e' il cuore del disegno, non una dimenticanza.",
     "Se la chiamata fosse riservata servirebbe un operatore privilegiato: un server da tenere "
     "vivo e un punto in cui il servizio si puo' spegnere. Rendendola pubblica e pagando chi la "
     "chiama, il sistema non dipende da nessuno.",
     "«Quindi chiunque puo' toccare i miei fondi?» No. La destinazione e' letta <b>dallo "
     "storage</b>, non dagli argomenti. Il chiamante fornisce solo l'indirizzo su cui incassare "
     "la fee, che l'owner ha fissato alla creazione."),
    ("Perche' il contratto non puo' avere una chiave di admin?",
     "Perche' averla lo farebbe rientrare nel perimetro CASP di MiCA.",
     "Il considerando 22 esclude i servizi prestati «in modo completamente decentralizzato senza "
     "alcun intermediario». La domanda che conta non e' «gira su catena permissionless» ma "
     "<b>chi puo' ancora cambiare l'esito</b>. Squalificano admin key, chiavi di upgrade, "
     "estrazione di fee, front-end gestito, governance, treasury.",
     "«E se l'emittente di un asset cambia?» Asset, router e pair sono <b>parametri del piano</b>: "
     "l'owner cancella e ricrea, il contratto non si tocca. E' anche il motivo per cui questo "
     "prodotto <b>non potra' mai avere ricavi da fee</b>."),
    ("Perche' la difesa dal MEV smette di funzionare sopra ~200 euro?",
     "Perche' non e' una difesa nel codice: e' che l'attacco non conviene.",
     "Su un ordine da 5 euro l'attaccante <b>ci rimette 0,10 euro</b>: muovere il prezzo gli costa "
     "piu' di quanto estrae. A 200 euro guadagna 0,11, marginale. A 5.000 guadagna 18, e a quel "
     "punto qualcuno lo automatizza.",
     "«Quindi il contratto non protegge?» Non da quello. E' una difesa <b>economica, non "
     "crittografica</b>. `min_out` resta come parapetto contro illiquidita' o depeg. Sopra i 200 "
     "euro servirebbe un oracolo, e la soglia va documentata all'utente."),
    ("Cosa succede se qualcuno passa una `pair` sbagliata?",
     "L'esecuzione fallisce e nessun fondo si muove.",
     "L'autorizzazione copre <b>un solo trasferimento</b>, di importo esatto, verso la pair "
     "dichiarata. Se non e' quella che il router usa, il trasferimento tentato non combacia e "
     "l'intera transazione torna indietro.",
     "«Si puo' bloccare un piano?» Solo il proprio, e `cancel` restituisce tutto il residuo. Un "
     "valore sbagliato <b>non puo' dirottare fondi: solo impedire l'esecuzione</b>."),
    ("Perche' EURC e non USDC?",
     "Per non introdurre un rischio di cambio silenzioso a ogni versamento.",
     "Circle emette EURC <b>nativo</b> su Stellar: un piano EURC verso XLM non attraversa il "
     "dollaro. Con USDC ogni esecuzione avrebbe una conversione EUR/USD implicita che non compare "
     "da nessuna parte.",
     "«E la liquidita'?» Misurata sul lato Soroban, quello raggiungibile dal contratto: EURC ha "
     "0,027% di slippage a 50 euro contro 0,086% di USDC. La scelta valutaria e' confermata anche "
     "sui numeri."),
    ("Perche' un contratto Soroban non usa il path payment?",
     "Perche' non puo': la SDEX classica gli e' preclusa.",
     "I contratti Soroban non possono interagire con la SDEX, ne' con claimable balance o "
     "sponsorship. Lo swap deve passare per una DEX Soroban, che sono AMM.",
     "«Allora le misure sulla SDEX?» Riguardano un mercato che il contratto non raggiunge. "
     "<b>Ed e' l'origine del divario dello 0,49%.</b>"),
    ("Come si verifica che l'owner possa ricevere l'asset?",
     "`create_plan` interroga `balance(owner)` sull'asset di destinazione.",
     "Senza trustline quella chiamata <b>fallisce</b> con «trustline entry is missing for "
     "account» — non ritorna zero. E' proprio questo che la rende utilizzabile come controllo.",
     "«Perche' non `authorized`?» Appartiene all'interfaccia Stellar Asset, quindi romperebbe i "
     "piani con destinazione un token <b>nativo Soroban</b>. `balance` sta nell'interfaccia "
     "standard: esiste ovunque."),
    ("Il codice e' stato scritto con assistenza AI. E' un problema?",
     "Il problema non e' chi ha digitato: e' se chi lo presenta lo capisce e lo mantiene.",
     "Ogni decisione ha un numero misurato dietro: le costanti TTL da un'interrogazione alla rete, "
     "la soglia MEV da un calcolo sulla liquidita' reale, l'immutabilita' da un considerando. Il "
     "threat model documenta anche una vulnerabilita' <b>dichiarata e poi ritirata</b>, e il "
     "rapporto di scansione dichiara che lo strumento raccomandato <b>non funziona</b>.",
     "«E i limiti?» Chi ha scritto il codice ha scritto anche i test, quindi ne condividono i "
     "punti ciechi. <b>Nessun umano indipendente l'ha ancora letto</b>: e' precisamente il motivo "
     "per cui esiste l'audit, e per cui non va in mainnet prima."),
]


def costruisci() -> None:
    f = []

    # ---------- copertina ----------
    f += [Spacer(1, 46 * mm),
          P("stellar-pac", "h0"),
          P("Piani di accumulo ricorrenti come contratto immutabile su Stellar", "sub0"),
          HRFlowable(width="42%", color=CIANO, thickness=1.4, spaceAfter=16),
          P("Un contratto Soroban che compra a scadenze fisse, eseguito da un keeper "
            "permissionless. Nessun conto da aprire, nessuna controparte che detiene i tuoi "
            "fondi, nessuno che possa chiudere il piano.", "pc"),
          Spacer(1, 14),
          tabella([["Stato", "Deployato e verificato su testnet"],
                   ["Audit", "Nessuno"],
                   ["Mainnet", "No"],
                   ["Licenza", "Apache-2.0"],
                   ["Repository", "github.com/Crono03/stellar-pac"]],
                  [42 * mm, 90 * mm], intestata=False),
          Spacer(1, 20),
          P(f"Documento generato il {dt.date.today().strftime('%d/%m/%Y')}", "pc"),
          PageBreak()]

    # ---------- 1. il problema ----------
    f += [P("1. Il problema da cui nasce", "h1"),
          P("Non e' un'idea nata su Stellar. Nasce da una misura su un conto reale: per comprare "
            "<b>5 euro</b> di ETF, un broker tradizionale chiedeva <b>1 euro di commissione</b>. "
            "Il 20% del capitale.", "p"),
          riquadro("Il costo d'ordine non e' un parametro da ottimizzare: e' un <b>filtro "
                   "binario</b>. O e' zero, o non si versa. Con 1 euro di commissione, un "
                   "versamento ha senso solo sopra i <b>200 euro</b> — sotto, la commissione "
                   "mangia piu' di quanto il mercato rende in mesi."),
          P("Questo prodotto sposta quella soglia. Non a zero — la promessa «zero commissioni» "
            "sarebbe falsa e lo dimostreremo piu' avanti — ma di quasi due ordini di grandezza.", "p"),
          tabella([["Canale", "Costo per operazione", "Soglia minima"],
                   ["Ordine manuale su broker", "1,00 EUR", "200 EUR"],
                   ["Fineco fuori lista", "2,95 EUR", "590 EUR"],
                   ["<b>Questo contratto</b>", "<b>0,011 EUR</b>", "<b>2,22 EUR</b>"]],
                  [58 * mm, 50 * mm, 44 * mm], evidenzia=[3])]

    # ---------- 2. cosa fa ----------
    f += [P("2. Cosa fa, in sei passi", "h1"),
          P("L'utente crea un piano — <i>ogni mese converti 10 EURC in XLM</i> — lo finanzia, e "
            "il piano vive. Da quel momento nessuno deve fare niente perche' funzioni.", "p"),
          flusso()]

    # ---------- 3. il vincolo ----------
    f += [PageBreak(),
          P("3. Il vincolo che definisce tutto", "h1"),
          P("<b>Soroban non ha uno scheduler.</b> Nessun contratto puo' svegliarsi da solo: "
            "qualcuno, dall'esterno, deve chiamarlo.", "p"),
          riquadro("Questo vincolo <b>e' il prodotto</b>. Se Soroban avesse il cron, un contratto "
                   "di accumulo sarebbe banale e ne esisterebbero dieci. Risolvere bene il "
                   "problema del trigger e' tutto il valore.", AMBRA_C, colors.HexColor("#c9a227")),
          P("La risposta e' un <b>keeper permissionless</b>: <font face='Courier'>execute()</font> "
            "e' pubblica, chiunque puo' chiamarla, e chi lo fa incassa una fee prelevata dal "
            "piano. Nessun operatore privilegiato, nessun server da tenere vivo, nessun punto in "
            "cui il servizio si puo' spegnere.", "p"),
          P("L'invariante che non si piega", "h2"),
          riquadro("<b>Solo l'owner puo' far uscire valore da un piano verso un indirizzo suo.</b> "
                   "Un keeper puo' innescare l'esecuzione e incassare la fee che l'owner ha "
                   "fissato alla creazione. Nient'altro. E' la prima cosa che un audit deve "
                   "verificare, ed e' il motivo per cui <font face='Courier'>withdraw</font> e "
                   "<font face='Courier'>cancel</font> chiamano "
                   "<font face='Courier'>require_auth</font> mentre "
                   "<font face='Courier'>execute</font> no.", ROSSO_C, ROSSO),
          P("Le altre due scelte strutturali", "h2"),
          tabella([["Scelta", "Perche'", "Cosa costa"],
                   ["<b>Immutabile</b>: nessuna admin key, nessun upgrade, nessuna fee allo sviluppatore",
                    "Il considerando 22 di MiCA esclude i servizi «completamente decentralizzati senza alcun intermediario». Admin key, upgrade e fee riportano dentro il perimetro CASP",
                    "Il progetto <b>non potra' mai avere ricavi da fee di protocollo</b>. Il reddito, se arriva, e' un grant"],
                   ["<b>Difesa MEV per taglia</b>, non nel codice",
                    "Sotto ~200 euro per esecuzione un attacco sandwich costa all'attaccante piu' di quanto estrae",
                    "Sopra quella soglia la difesa smette di valere, e va detto all'utente"]],
                  [42 * mm, 66 * mm, 58 * mm])]

    # ---------- 4. i numeri ----------
    f += [PageBreak(),
          P("4. I numeri, tutti misurati", "h1"),
          P("Nessuna cifra in questo documento e' una stima. Ognuna viene da una transazione "
            "eseguita o da una lettura della rete, e ognuna e' riproducibile con gli script nel "
            "repository.", "p"),
          P("Costo una tantum, per piano", "h2"),
          tabella([["Voce", "XLM", "EUR"],
                   ["Caricamento del WASM (11.687 byte)", "0,698", "0,099"],
                   ["Creazione dell'istanza", "0,002", "0,000"],
                   ["<b>create_plan</b>", "<b>11,281</b>", "<b>1,600</b>"]],
                  [86 * mm, 34 * mm, 34 * mm], evidenzia=[3]),
          P("Creare una entry persistente costa circa <b>mille volte piu'</b> che scriverci sopra: "
            "si paga in anticipo il rent per tutta la sua vita. E' il costo dominante, e sposta la "
            "soglia sensata del prodotto a <b>150-300 euro di versamenti complessivi</b> per "
            "piano — non a un singolo versamento minuscolo.", "p"),
          P("Costo per esecuzione", "h2"),
          tabella([["Voce", "Costo", "Natura"],
                   ["Divario fra venue Soroban e SDEX classica", "<b>0,49%</b>", "proporzionale, <b>incomprimibile</b>"],
                   ["Fee del keeper (margine 3x)", "0,22% su 5 EUR", "<b>zero se esegui tu</b>"],
                   ["Slippage a 2-50 EUR", "0,001-0,054%", "trascurabile"],
                   ["Scrittura su ledger", "0,002 EUR", "fissa"],
                   ["<b>Totale</b>", "<b>~0,71%</b>", ""]],
                  [72 * mm, 40 * mm, 54 * mm], evidenzia=[5]),
          riquadro("Il divario di venue e' la scoperta piu' scomoda. Un contratto Soroban "
                   "<b>non puo' raggiungere la DEX classica</b> di Stellar: niente path payment, "
                   "niente libri ordini. Deve passare per una DEX Soroban, e quelle prezzano circa "
                   "<b>0,49% peggio</b>. Misurato sulle due venue <i>simultaneamente</i>, perche' "
                   "due letture a minuti di distanza non sono un confronto."),
          ]

    # ---------- 5. cosa non promette ----------
    f += [P("5. Cosa questo prodotto NON promette", "h1"),
          riquadro("<b>Non e' piu' economico di un piano di accumulo gratuito di broker.</b> "
                   "Se il tuo broker offre un PAC a zero commissioni su un asset che ti "
                   "interessa, usalo: costa meno.", ROSSO_C, ROSSO),
          tabella([["Canale", "Costo su 5 EUR"],
                   ["Ordine manuale su broker", "1,00 EUR = <b>20%</b>"],
                   ["<b>Questo contratto</b>", "0,036 EUR = <b>0,71%</b>"],
                   ["PAC programmato gratuito di broker", "<b>0,00 EUR</b>"]],
                  [104 * mm, 62 * mm], evidenzia=[3]),
          P("Ventotto volte meglio di un ordine manuale. Peggio di un piano gratuito. Dirlo per "
            "primo e' piu' solido che farselo scoprire da un revisore.", "p"),
          P("Dove sta il valore, allora", "h2"),
          P("Non nel prezzo. In cio' che un broker non da':", "p"),
          tabella([["Proprieta'", "Cosa significa in pratica"],
                   ["Asset che un broker non lista", "Se non e' nel catalogo, non esiste. Qui il catalogo non c'e'"],
                   ["<b>Non-custodia</b>", "Nessuno detiene i fondi al posto tuo, nemmeno il contratto: solo tu puoi farli uscire"],
                   ["<b>Permissionless</b>", "Nessun conto da aprire, nessuna soglia d'ingresso, nessun offboarding"],
                   ["Nessuno puo' chiuderlo", "Non c'e' un'entita' che possa sospendere il tuo piano o cambiarne le regole"]],
                  [46 * mm, 120 * mm]),
          P("Quest'ultimo punto non e' teorico: nel 2026 exchange e broker hanno delistato asset e "
            "chiuso l'accesso a intere aree geografiche. Un piano che nessuno puo' chiudere e' una "
            "proprieta' diversa dal prezzo, e per alcuni vale piu' dello 0,71%.", "p")]

    # ---------- 6. sicurezza ----------
    f += [PageBreak(),
          P("6. Sicurezza: cosa e' coperto e cosa no", "h1"),
          P("Il repository contiene un <b>modello di minacce STRIDE</b> completo. Non ha voci "
            "aperte, e non ha individuato vulnerabilita' sfruttabili — che e' un'affermazione "
            "su quell'analisi, non una garanzia.", "p"),
          tabella([["Minaccia", "Stato"],
                   ["Fingersi l'owner per prelevare", "<font color='#1f7a4d'><b>coperta</b></font> — require_auth sull'owner letto dallo storage"],
                   ["Il keeper devia i fondi", "<font color='#1f7a4d'><b>coperta</b></font> — la destinazione non arriva dagli argomenti"],
                   ["Un router malevolo svuota il budget", "<font color='#1f7a4d'><b>coperta</b></font> — autorizzazione per un solo trasferimento di importo esatto"],
                   ["Un admin cambia le regole", "<font color='#1f7a4d'><b>impossibile</b></font> — non esiste admin"],
                   ["Rientranza dal router", "<font color='#1f7a4d'><b>non applicabile</b></font> — Soroban la vieta a livello di host"],
                   ["I piani sono pubblici", "<font color='#a4343a'><b>accettata</b></font> — un piano ricorrente e' un profilo leggibile da chiunque"],
                   ["Nessuno esegue i piani", "<font color='#a4343a'><b>reale</b></font> — sotto ~6.755 esecuzioni/mese esegui tu"]],
                  [58 * mm, 108 * mm]),
          riquadro("Una correzione che vale la pena conoscere. Una prima stesura del modello "
                   "classificava la <b>rientranza</b> come «la vulnerabilita' piu' seria "
                   "individuata». Il ragionamento e' corretto su Ethereum e <b>non si applica "
                   "qui</b>: Soroban vieta la rientranza a livello di host, per scelta esplicita. "
                   "Nessuna modifica e' stata fatta — applicare comunque la contromisura sarebbe "
                   "stato <i>cargo cult</i>. La voce e' rimasta nel documento perche' un auditor "
                   "si porra' la stessa domanda."),
          P("Le lacune, dichiarate", "h2"),
          tabella([["Lacuna", "Perche'"],
                   ["<b>Nessun audit</b>", "L'Audit Bank di Stellar richiede prima il finanziamento SCF"],
                   ["<b>Nessuna scansione Soroban-specifica</b>", "Scout non supporta l'SDK 27, e su un panic del build script riporta «Analyzed / 0» — un falso pulito, scoperto piantando un difetto che avrebbe dovuto rilevare"],
                   ["<b>Nessun keeper indipendente</b>", "Sotto ~6.755 esecuzioni al mese a nessun terzo conviene tenere acceso un processo"]],
                  [56 * mm, 110 * mm])]

    # ---------- 7. stato ----------
    f += [P("7. Stato del progetto", "h1"),
          tabella([["Componente", "Stato"],
                   ["Contratto Soroban", "<font color='#1f7a4d'><b>completo</b></font>, 14 test verdi, lint finanziari puliti"],
                   ["Keeper", "<font color='#1f7a4d'><b>funzionante</b></font>, simula prima di inviare"],
                   ["Testnet", "<font color='#1f7a4d'><b>verificato end-to-end</b></font> con il router Soroswap reale"],
                   ["Eventi", "<font color='#1f7a4d'><b>tutti e cinque</b></font>, con l'id del piano come topic"],
                   ["Mainnet", "<font color='#a4343a'><b>no</b></font>"],
                   ["Audit", "<font color='#a4343a'><b>no</b></font>"]],
                  [50 * mm, 116 * mm]),
          P("La prova che conta", "h2"),
          P("Un'esecuzione reale su testnet, attraverso il router Soroswap vero:", "p"),
          tabella([["", "prima", "dopo"],
                   ["Budget del piano", "20 XLM", "15 XLM"],
                   ["Prossima esecuzione", "adesso", "<b>+30 giorni esatti</b>"],
                   ["USDC dell'owner", "0", "<b>0,4993884</b>"]],
                  [66 * mm, 44 * mm, 56 * mm]),
          P("5 XLM prelevati dal budget, 0,1 al keeper, <b>4,9 scambiati</b>. Al rapporto delle "
            "riserve della pool l'atteso era 0,5006; sono arrivati 0,4994. La differenza e' la "
            "commissione dello 0,3% della pool stessa. <b>I conti tornano al centesimo.</b>", "p")]

    # ---------- 8. Q&A ----------
    f += [PageBreak(),
          P("8. Domande e risposte", "h1"),
          P("Preparazione alla candidatura. Copri le risposte e prova a dire ad alta voce solo la "
            "riga rossa: se esce quella, il resto viene da se'. Se non esce, quel pezzo non e' "
            "ancora tuo — ed e' un'informazione utile, non un fallimento.", "p"),
          HRFlowable(width="100%", color=BORDO, thickness=0.6, spaceAfter=4)]
    for i, (q, b, p, inc) in enumerate(QA, 1):
        f.append(KeepTogether([
            Paragraph(f"{i}. {q}", S["dom"]),
            Paragraph(f"&#9654;&nbsp; <b>{b}</b>", S["risp"]),
            Paragraph(p, S["p"]),
            Paragraph(f"<i>Se ti incalzano.</i> {inc}", S["inc"])]))

    # ---------- 9. banco di prova ----------
    f += [PageBreak(),
          P("9. Il banco di prova", "h1"),
          P("Le risposte si imparano meglio vedendole fallire. "
            "<font face='Courier'>python scripts/lab.py</font> deploya un contratto fresco e mette "
            "alla prova nove situazioni contro testnet. Ogni caso dichiara cosa <i>dovrebbe</i> "
            "succedere, esegue, e confronta.", "p"),
          tabella([["Caso", "Cosa prova", "Atteso"],
                   ["1", "Un piano valido si crea e si finanzia", "riesce"],
                   ["2", "Un estraneo preleva dal tuo piano", "fallisce"],
                   ["3", "Un estraneo cancella il tuo piano", "fallisce"],
                   ["4", "<b>Un estraneo esegue il tuo piano</b>", "<b>riesce</b>"],
                   ["5", "Esecuzione ripetuta subito dopo", "fallisce"],
                   ["6", "Fee del keeper >= importo del versamento", "fallisce"],
                   ["7", "Destinazione senza trustline", "fallisce"],
                   ["8", "<b>Destinazione XLM nativo, stesso conto</b>", "<b>riesce</b>"],
                   ["9", "Pair sbagliata, poi recupero con cancel", "fallisce, poi recupera"]],
                  [14 * mm, 108 * mm, 44 * mm], evidenzia=[4, 8]),
          riquadro("I due casi evidenziati sono i piu' istruttivi. Nel <b>4</b> un estraneo esegue "
                   "e riesce: sembra un buco e non lo e', perche' gli asset comprati arrivano a te "
                   "e lui incassa solo la fee — l'invariante si <i>osserva nei saldi</i>, non si "
                   "crede. Nell'<b>8</b> il controllo sulla trustline <b>non</b> deve scattare: "
                   "una difesa che blocca i casi leciti e' un danno, non una protezione."),
          P("Non costa nulla: testnet, XLM di friendbot, e ogni piano creato si puo' cancellare "
            "recuperando il residuo. Si possono lanciare i casi singolarmente con "
            "<font face='Courier'>python scripts/lab.py 4</font>.", "p"),
          Spacer(1, 10),
          HRFlowable(width="100%", color=BORDO, thickness=0.6, spaceAfter=8),
          P("github.com/Crono03/stellar-pac &nbsp;·&nbsp; Apache-2.0 &nbsp;·&nbsp; "
            "documento interno, non destinato alla pubblicazione", "small")]

    doc = SimpleDocTemplate(str(USCITA), pagesize=A4,
                            leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=18 * mm,
                            title="stellar-pac — brochure di progetto",
                            author="stellar-pac")
    doc.build(f, onLaterPages=numero, onFirstPage=lambda c, d: None)
    print(f"  scritto {USCITA.name}  ({USCITA.stat().st_size / 1024:.0f} KB)")


def numero(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRIGIO)
    canvas.drawString(22 * mm, 12 * mm, "stellar-pac")
    canvas.drawRightString(188 * mm, 12 * mm, str(doc.page))
    canvas.setStrokeColor(BORDO)
    canvas.line(22 * mm, 15 * mm, 188 * mm, 15 * mm)
    canvas.restoreState()


if __name__ == "__main__":
    costruisci()
