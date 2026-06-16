---
title: "Prompt: PDF Számla Feldolgozó"
language: "HU"
related: [invoice-file-filter-spec.md, nav-invoice-prompt.md, attachment-downloader-prompt.md]
---

Készüljön egy microservice ami meghívja a attachment-downloader szolgáltatást az utolsó 30 nap intervallum default paraméterrel kiválogatja a attachment-downloader által letöltött fájlok közül a számlákat (invoice, számla).
A szolgáltatás adja vissza a számla meta adatait is számla szám stb
A szolgáltatáshoz készüljön cli és fastapi rest interface

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[invoice-file-filter-spec.md|PDF Feldolgozó Spec]]
- **Meghívva**: [[nav-invoice-prompt.md|NAV Invoice Prompt]] → [[nav-invoice-spec.md|NAV Invoice Spec]]
- **Meghívja**: [[attachment-downloader-prompt.md|Attachment Downloader Prompt]] → [[attachment-downloader-spec.md|Attachment Downloader Spec]]
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
