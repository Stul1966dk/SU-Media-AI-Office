# Notification Service

## Formål

Notification Service er den fælles kanal, som SU Media AI Offices nuværende og fremtidige medarbejdere bruger til at sende beskeder til CEO.

## Første kanal

Telegram via botten SU Media AI Office.

## Ansvar

- modtage en struktureret besked fra en integration eller medarbejder,
- formatere den ensartet,
- sende den til den konfigurerede kanal,
- registrere om afsendelsen lykkedes,
- håndtere midlertidige fejl på en kontrolleret måde,
- undgå at logge tokens og andre hemmeligheder.

## Salgsbesked i version 0.1

```text
SU Media AI Office
Affiliate Manager

Nyt salg
Tidspunkt: ...
Annoncør: ...
Website: ...
Ordrebeløb: ...
Provision: ...
Samlet provision i dag: ...
```

Alle salg skal udløse en besked, fordi dette er et udtrykkeligt motivationsønske fra CEO.

## Afgrænsning

Servicen afgør ikke, om et salg er nyt, og den udfører ikke forretningsanalyse. Afsenderen leverer en valideret hændelse; servicen leverer beskeden.

## Sikkerhed

Bot-token og Chat ID skal senere indlæses fra sikker konfiguration og må ikke versionsstyres.
