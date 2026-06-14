---
title: "Prompt: PDF Számla Feldolgozó"
language: "HU"
related: [pdf-szamla-spec.md, nav-számla-prompt.md, attachment-downloader-prompt.md]
---

Készüljön egy microservice ami meghívja a attachment-downloader szolgáltatást az utolsó 30 nap intervallum default paraméterrel kiválogatja a attachment-downloader által letöltött fájlok közül a számlákat (invoice, számla).
A szolgáltatás adja vissza a számla meta adatait is számla szám stb
A szolgáltatáshoz készüljön cli és fastapi rest interface

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[pdf-szamla-spec.md|PDF Szamla Spec]]
- **Meghívva**: [[nav-számla-prompt.md|NAV Szamla Prompt]] → [[nav-szamla-spec.md|NAV Szamla Spec]]
- **Meghívja**: [[attachment-downloader-prompt.md|Graphtrek Email Prompt]] → [[attachment-downloader-spec.md|Graphtrek Email Spec]]
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
