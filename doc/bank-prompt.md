---
title: "Bank – Konszolidált Bankkivonat Mikroszerviz"
description: "Erste és Wise bankkivonatok egységes feldolgozása és REST API-n való visszaadása az invoice-core számára"
type: "service-prompt"
status: "tervezett"
port: 8005
language: "HU"
last_updated: "2026-06-19"
depends_on: [wise-spec.md, invoice-core-spec.md]
related: [INDEX.md, wise-spec.md, wise-prompt.md, invoice-core-spec.md]
tags: [bank, erste, wise, csv, fastapi, typer, konszolidáció]
---

# Bank – Konszolidált Bankkivonat Mikroszerviz - Prompt

implementálni egy robusztus, Python-alapú microservice használatával, amely  a visszaadja az Erste bank tranzakcióit bank/balance-statements/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv és a Wise bank tranzakcióit bank/balance-statements/wise/statement_25546267_HUF_2026-01-01_2026-06-17.csv egységes 
consolidákt formában.


Készüljön. egy GET végpont a /balance-statement/{bank} a wise szűrésnek megfelelően.
A dátumok legynek **ISO 8601 / RFC 3339** formátumban kezelve, a konszolidált válaszban 
legyen benne melyik bank statement.

A szolgáltatáshoz készüljön cli és fastapi rest interface.

A project struktúra kövesse a wise project-et.
A szolgáltatást az invoice-core fogja hívni.

---

## 🔗 Wiki Linkek
- **Minta projekt**: [[wise-spec.md|Wise Spec]] | [[wise-prompt.md|Wise Prompt]] (projektstruktúra alapja)
- **Hívó szolgáltatás**: [[invoice-core-spec.md|Invoice-Core Spec]] → [[invoice-core-prompt.md|Invoice-Core Prompt]]
- **Projekt Index**: [[INDEX.md|Tiro Index]]
