---
title: "Specifikáció: Wise Banki Mikorszerviz"
description: "Wise bankkivonat letöltés és szinkronizálás az invoice-core rendszerrel"
language: "HU"
last_updated: "2026-06-10"
related: [INDEX.md, invoice-core-spec.md, wise-spec.md]
---

# Wise Banki Mikorszerviz - Prompt

Wise API dokumentáció https://docs.wise.com/api-reference alapján implementálni egy robusztus, Python-alapú microservice használatával, amely automatizálja a Wise banki kivonatai letöltését.
A szolgáltatáshoz készüljön cli és fastapi rest interface.

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[wise-spec.md|Wise Integráció Spec]]
- **Cél adatbázis**: [[invoice-core-prompt.md|Invoice-Core Prompt]] → [[invoice-core-spec.md|Invoice-Core Spec]] (közvetlen PostgreSQL írás)
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]