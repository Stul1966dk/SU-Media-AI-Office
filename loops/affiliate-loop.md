# Affiliate-loop

## Formål

Affiliate-loopet skal omsætte observationer til målbare forbedringer af provisionen. Det operative salgsloop og det strategiske forbedringsloop holdes adskilt.

## Operativt loop i version 0.1

```text
Hent Partner-ads-data
  -> validér data
  -> find nye salg
  -> gem nye salg
  -> send én notifikation pr. salg
  -> registrér resultat og fejl
  -> gentag efter 30 minutter
```

Mål: Alle nye salg registreres én gang og meddeles én gang.

Stopregel: Det tilbagevendende loop fortsætter, mens integrationen er i drift. Ved gentagne fejl skal systemet eskalere i stedet for at sende uendelig støj.

## Strategisk loop, senere version

```text
Observer ændring i provision
  -> sammenhold med relevante data
  -> formulér fakta og hypoteser
  -> prioritér en konkret arbejdsordre
  -> fastsæt baseline og mål
  -> CEO udfører eller godkender handlingen
  -> mål efter aftalt periode
  -> vurder resultatet
  -> gem erfaringen
  -> vælg næste handling
```

## Krav til en forbedring

Et strategisk loop må ikke starte uden:

- en dokumenteret baseline,
- et målbart ønsket resultat,
- et estimeret tidsforbrug,
- en forventet effekt med angivet usikkerhed,
- en måledato,
- en stopregel.

Hvis resultatet udebliver, skal loopet revurdere hypotesen frem for blindt at gentage samme handling.
