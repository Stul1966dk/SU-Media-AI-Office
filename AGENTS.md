# Projektregler

## Git-procedure efter afsluttet arbejde

Når et sprint eller en selvstændig delopgave er implementeret, skal følgende
procedure gennemføres:

1. Kør `git status --short`.
2. Kontrollér, at credentials, tokens, databaser, backups, logs og genererede
   artifacts ikke stages.
3. Stage kun de filer, der hører til den afsluttede opgave.
4. Kør de relevante tests.
5. Opret et commit med en konkret dansk commitbesked.
6. Push committen til `origin/main`.
7. Oplys commit-hash, commitbesked, testresultat og eventuelle filer, der
   fortsat ikke er committed.

Der må ikke committes, hvis tests fejler, eller hvis der er tvivl om
følsomme eller uvedkommende filer. Stop i så fald og bed brugeren om
godkendelse.

## Obligatorisk Streamlit hot-reload-kontrol

Efter enhver ændring i `core/` eller `dashboard/` skal følgende gennemføres,
før arbejdet må betragtes som afsluttet:

1. Kør `python -m unittest tests.test_streamlit_hot_reload_gate`.
2. Genindlæs den allerede kørende lokale Streamlit-side i browseren. En frisk
   testproces er ikke tilstrækkelig.
3. Kontrollér, at siden ikke viser traceback, `ImportError`,
   `AttributeError` eller anden runtime-fejl.
4. Kontrollér browserens fejllog efter genindlæsningen.
5. Kør derefter de øvrige relevante tests.

Hvis den lokale Streamlit-app ikke kører, skal det oplyses i afleveringen, og
hot-reload-kontrollen må ikke rapporteres som gennemført.
