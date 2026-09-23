# Revisione del debito tecnico e della programmazione

Verifica del 23 settembre 2026, successiva al controllo di compatibilità con Home Assistant 2026.9.3. Le modifiche già presenti nel progetto sono state conservate. Al momento della verifica non era stato effettuato un rilascio né aggiornato un impianto Home Assistant.

## Correzioni del controllo climatico

| Problema | Correzione |
| --- | --- |
| Priorità replicate tra comandi, richiesta alla caldaia e stato mostrato | Una decisione condivisa in `control.py` gestisce emergenza, sensori assenti, antigelo, stagione, spegnimento e finestre. |
| Spegnimento esplicito annullato dal programma | La scelta Off viene conservata anche dopo un riavvio, rispettando le priorità di sicurezza e il comportamento fuori stagione. |
| Un attuatore in errore interrompeva l'aggiornamento degli altri | Errori isolati per dispositivo, comandi attesi fino al completamento e cache invalidate per consentire il tentativo successivo. |
| Comandi alla caldaia sovrapposti o riferiti a un coordinatore sostituito | Coordinamento serializzato, riconciliazione dello stato reale e arresto del coordinatore precedente. |
| Temperature non finite, unità diverse e arrotondamenti dei termostati | Conversioni centralizzate, valori finiti, limiti e passi dei dispositivi. I servizi climate usano l'unità configurata in HA. |
| Override scaduto o rientro a casa applicati con un ciclo di ritardo | Le transizioni vengono risolte prima di calcolare il programma e inviare i comandi. |
| Presenza sconosciuta, meteo offline o pre-riscaldamento interrotto da eventi estranei | Gestione dei dati indisponibili; avvicinamento conservato fino a dieci minuti, annullato se la persona si allontana. |
| Apprendimento e contatori contaminati da campioni non validi o ripristino impreciso | Controllo del segno della variazione termica, azzeramento del campione dopo una pausa, ripristino dei contatori senza arrotondamento e identificazione dei mesi comprensiva dell'anno. |
| Configurazioni problematiche e riferimenti dopo una ricarica | Rifiuto di ingressi Vesta circolari e attuatori condivisi tra stanze; campi opzionali cancellabili; sensori associati alla stanza corrente; listener aggiornati anche se la configurazione globale parte dopo le stanze. |

La gestione della caldaia e delle conversioni è stata estratta in `boiler.py` e `temperature.py`. Sono stati eliminati percorsi duplicati di controllo e ricaricamenti ridondanti. La documentazione distingue ora la richiesta di calore dal tempo di funzionamento effettivamente misurato.

## Programmazione oraria

- Il modello **Sempre Eco** termina alle `24:00`, includendo anche l'ultimo minuto. I programmi esistenti non vengono riscritti: un eventuale termine alle `23:59` resta modificabile nell'editor.
- L'editor conserva i minuti esatti. `00:00` nel campo di fine indica la mezzanotte finale; un intervallo notturno si rappresenta con due blocchi su giorni consecutivi.
- Gli override riconoscono anche due fasce consecutive con la stessa modalità. La mezzanotte, da sola, non interrompe un override durante un intervallo privo di fasce.
- “Prossima fascia attiva” ignora anche i blocchi HA con `mode: off`. I marcatori degli override salvati dalle versioni precedenti vengono adattati senza interrompere un override ancora valido.
- L'assegnazione di un programma Vesta o dell'ereditarietà globale rimuove il vecchio override HA che poteva interferire. L'eliminazione di un programma libera i riferimenti nelle configurazioni.
- La **migrazione della configurazione a versione 8** conserva l'ereditarietà effettiva delle vecchie stanze. Le versioni di configurazione future vengono rifiutate senza modificarle.
- Salvataggi serializzati e pubblicazione dei dati solo dopo la persistenza impediscono di mostrare come salvate modifiche fallite. Letture e scritture non condividono liste modificabili con i chiamanti.
- Il pannello offre l'assegnazione globale, mostra gli errori delle operazioni, ignora risposte superate e conserva i moduli aperti quando cambia il layout.

Fuori dalle fasce native Vesta il riscaldamento è spento, salvo le priorità superiori; un helper Schedule HA nello stato OFF usa invece la temperatura Eco. La differenza è ora esplicitata nel README.

## Verifica

| Controllo | Risultato |
| --- | --- |
| Python 3.14 / HA 2026.9.3 | 181 test superati |
| Python 3.13 / HA 2026.2.3 | 177 superati, 4 esclusi perché riguardano i dispositivi figli introdotti in HA 2026.9 |
| JavaScript, `node --test tests/frontend.test.cjs` | 8 test superati |
| Pyflakes, compilazione Python e `git diff --check` | Nessun errore |

La prova del ciclo di vita carica realmente le piattaforme HA, registra pannello e API, avvia una stanza prima della configurazione globale, cambia il programma, ricarica e rimuove la stanza. Solo la directory del bundle JavaScript di HA viene sostituita nel test; gli asset Vesta restano reali. La CI esegue entrambe le versioni HA, i test JavaScript e Pyflakes.

Non sono state eseguite prove su caldaia e valvole fisiche né una verifica visuale completa del pannello in un browser HA. I test JavaScript verificano la logica del componente con un ambiente DOM simulato. Le stime dei risparmi rimangono stime, non misure di consumo.

Riferimenti ufficiali usati per la compatibilità e le unità: [release HA 2026.9.3](https://github.com/home-assistant/core/releases/tag/2026.9.3), [ClimateEntity](https://developers.home-assistant.io/docs/core/entity/climate/), [implementazione climate di HA 2026.9.3](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/climate/__init__.py).
