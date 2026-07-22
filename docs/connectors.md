# Connector Framework

Connector Framework giver AI Office en fælles read-only kontrakt til offentlige
websitedata. `BaseConnector` definerer forbindelse, forbindelsestest,
siteinformation, indlæg, sider, kategorier, tags, medier og frakobling.

`ConnectorFactory` vælger kun en connector ud fra dokumenterede Website
Discovery-fakta. Første implementation er `WordPressConnector`.

## WordPressConnector

Connectoren forsøger først den offentlige WordPress REST API. Hvis REST-roden
ikke er offentligt tilgængelig, falder den tilbage til begrænset analyse af
offentlig HTML. Den bruger ingen loginflow, credentials, cookies, tokens eller
write-metoder.

Importerede elementer får et stabilt hash. `Database.save_content` springer
uændrede elementer over og opdaterer kun, når hashet ændres. Mere end 20
ændrede sider i én import opretter eventet `website_content_updated`; eventet
opretter ikke selv projekter eller opgaver.

## Sikkerhedsgrænser

- Kun offentlige HTTP(S)-svar læses.
- User-Agent er `SU-Media-AI-Office/0.1 Website Discovery`.
- Timeout er ti sekunder pr. forespørgsel.
- Sessionscookies ryddes efter hver forespørgsel.
- Der findes ingen POST-, PUT-, PATCH- eller DELETE-kald.
- Rå HTML gemmes aldrig i databasen.
