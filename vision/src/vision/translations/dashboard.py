"""English translations for the dashboard UI area."""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # ui_dashboard.html
    "Mind": "All",
    "Nincs adat": "No data",
    "Timesheet összesítő": "Timesheet Summary",
    "Napi": "Daily",
    "Havi": "Monthly",
    "Éves": "Yearly",
    "Összes számla": "Total Invoices",
    "PDF kapcsolva": "PDF linked",
    "Fizetetlen számla": "Unpaid Invoice",
    "Nincs tartozás": "No outstanding debt",
    "Bank tranzakció": "Bank transaction",
    "elmúlt 30 nap": "last 30 days",
    "szállító": "supplier",
    "vevő": "customer",
    "Bevétel vs Kiadás": "Income vs Expense",
    "Utolsó 3 hónap": "Last 3 months",
    "Utolsó 6 hónap": "Last 6 months",
    "Utolsó 12 hónap": "Last 12 months",
    "Top szállítók": "Top Suppliers",
    "Top vevők": "Top Customers",
    "Legutóbbi tranzakciók": "Recent Transactions",
    "Dátum": "Date",
    "Típus": "Type",
    "Összeg": "Amount",
    "Számla": "Invoice",
    "Jóváírás": "Credit",
    "Terhelés": "Debit",
    "Legutóbbi számlák": "Recent Invoices",
    "Számlaszám": "Invoice number",
    "Szállító": "Supplier",
    "Bruttó": "Gross",
    "Státusz": "Status",
    "Nincs partner hozzárendelve": "No partner assigned",
    "— nincs partner —": "— no partner —",
    "Legutóbbi timesheet bejegyzések": "Recent Timesheet Entries",
    "Felhasználó": "User",
    "Projekt": "Project",
    "Ügyfél": "Client",
    "Tevékenység": "Activity",
    "Óra": "Hours",
    "Bevétel (bank, halmozott)": "Income (bank, cumulative)",
    "Kiadás (bank, halmozott)": "Expense (bank, cumulative)",
    "Kimenő számlák (halmozott)": "Outgoing invoices (cumulative)",
    "Bejövő számlák (halmozott)": "Incoming invoices (cumulative)",
    " óra": " hours",
    # dividend.html
    "Osztalékelőleg-számítás": "Dividend Advance Calculation",
    "Év:": "Year:",
    "Frissít": "Refresh",
    "Bevétel": "Revenue",
    "kimenő számla": "outgoing invoice(s)",
    "Kiadás": "Expenses",
    "bejövő számla": "incoming invoice(s)",
    "Bruttó nyereség": "Gross Profit",
    "Kivehető osztalékelőleg": "Available Dividend Advance",
    "Bruttó nyereség − TAO − HIPA": "Gross profit − TAO − HIPA",
    "Számítás részletei": "Calculation Details",
    "Bevétel (kimenő számlák nettó)": "Revenue (net of outgoing invoices)",
    "Kiadás (bejövő számlák nettó)": "Expenses (net of incoming invoices)",
    "bevétel alapján": "based on revenue",
    "Kivehető osztalékelőleg (nettó nyereség)": "Available dividend advance (net profit)",
    "Nettó felvehető": "Net Available",
    "SZOCHO nélkül": "without SZOCHO",
    "SZOCHO levonással": "with SZOCHO deducted",
    "SZOCHO-alap a plafonig:": "SZOCHO base up to the cap:",
    "éves plafon:": "annual cap:",
    "Havi bontás": "Monthly Breakdown",
    "Hónap": "Month",
    "Nyereség": "Profit",
    # adok.html
    "Adók": "Taxes",
    "Összes adó": "Total Tax",
    "Bruttó bevétel:": "Gross revenue:",
    "Jövedelem": "Income",
    "Összesen": "Total",
    "Becsült bevételek mentve": "Estimated revenues saved",
    "Becsült adók": "Estimated Taxes",
    "Becsült bruttó bevétel:": "Estimated gross revenue:",
    "Mentés": "Save",
    "Becsült bevétel": "Estimated Revenue",
    "Összes Adó": "Total Tax",
    "Eredmény": "Result",
    "Tranzakciók": "Transactions",
    "Megnevezés": "Description",
    "Adónem": "Tax Type",
    "Nincs rögzített adófizetés": "No recorded tax payment for",
    "-ben.": ".",
    # fizetes_kalkulator.html
    "Fizetés Calculator": "Payroll Calculator",
    "Kalkulátor adatai mentve": "Calculator data saved",
    "Bér / osztalék optimalizáció": "Wage / Dividend Optimization",
    "Tétel": "Item",
    "Nettó munkabér": "Net Wage",
    "Ehhez szükséges bruttó bér": "Gross wage required for this",
    "Nyugdíjjárulék": "Pension contribution",
    "Egészségbizt. + munkaerőpiaci j.": "Health insurance + labor market contribution",
    "Munkáltatói szocho": "Employer social contribution tax",
    "Bér teljes céges költsége": "Total company cost of wage",
    "Minimálisan szükséges havi árbevétel": "Minimum monthly revenue required",
    "bérköltség + egyéb átlagos költség (5%, min. 100 000 Ft) + HIPA (2%) fedezésére, nulla eredménnyel": (
        "to cover the wage cost + other average costs (5%, min. HUF 100,000) + HIPA (2%), at zero result"
    ),
    "Tervezett havi árbevétel": "Planned Monthly Revenue",
    "minimumra állítás": "set to minimum",
    "Egyéb átlagos költség": "Other average cost",
    "Bér és költségek után maradó eredmény": "Result remaining after wage and costs",
    "Osztalékra jutó összeg": "Amount allocated to dividend",
    "Osztalék SZJA": "Dividend personal income tax",
    "Osztalék szocho": "Dividend social contribution tax",
    "Nettó osztalék": "Net Dividend",
    "Összes nettó magánszemélynél": "Total net to individual",
    "/hó": "/month",
    "A számítás közelítő becslés. A nettó munkabérből indul ki, onnan származtatja a bruttó bért (33,5% munkavállalói terhelés: 15% SZJA + 10% nyugdíjjárulék + 8,5% egészségbiztosítási és munkaerőpiaci járulék) és a munkáltatói szochót (13%), majd ebből számolja a bérköltség fedezéséhez minimálisan szükséges havi árbevételt — feltételezve, hogy a cégnek emellett az árbevétel 5%-ának megfelelő (de legalább 100 000 Ft) egyéb átlagos költsége (rezsi, könyvelés, stb.) és 2%-os HIPA (helyi iparűzési adó) fizetési kötelezettsége is van. A tervezett árbevétel mezőben ennél magasabb összeget megadva a fennmaradó eredmény társasági adóját (TAO 9%) és a kifizethető osztalék terheit (SZJA 15% + szocho 13%) is kiszámítja. Az osztalék szochójára 2026-ban éves plafon vonatkozik: a minimálbér (322 800 Ft) 24-szerese, azaz 7 747 200 Ft — a magánszemély bérjövedelme ebbe beleszámít, és csak a plafonból megmaradó rész után kell osztalék szochót fizetni (évi legfeljebb 1 007 136 Ft).": (
        "This calculation is an approximate estimate. It starts from the net wage and derives the gross "
        "wage from it (33.5% employee deductions: 15% personal income tax + 10% pension contribution + "
        "8.5% health insurance and labor market contribution) and the employer's social contribution tax "
        "(13%), then calculates the minimum monthly revenue needed to cover the wage cost — assuming the "
        "company also has other average costs (overhead, bookkeeping, etc.) equal to 5% of revenue (but "
        "at least HUF 100,000) and a 2% local business tax (HIPA) obligation. Entering a higher amount in "
        "the planned revenue field also calculates the corporate tax (TAO 9%) on the remaining result and "
        "the charges on the payable dividend (15% personal income tax + 13% social contribution tax). In "
        "2026, an annual cap applies to the dividend's social contribution tax: 24 times the minimum wage "
        "(HUF 322,800), i.e. HUF 7,747,200 — the individual's wage income counts toward this, and social "
        "contribution tax on the dividend is only due on the remainder of the cap (at most HUF 1,007,136 "
        "per year)."
    ),
    "Éves plafon:": "Annual cap:",
    "minimálbér": "minimum wage",
    "a bérjövedelem kimeríti, az osztalék után nincs szocho.": (
        "the wage income exhausts it, no social contribution tax is due on the dividend."
    ),
    "a bér és az osztalék együtt a plafon alatt marad.": (
        "the wage and the dividend together stay under the cap."
    ),
    "ebből az osztaléknak csak ~": "of this, only ~",
    "/hó része szochoköteles.": "/month of the dividend is subject to social contribution tax.",
    # pitch.html
    "Tiro — A digitális cégtitkár": "Tiro — The digital company secretary",
    "Funkciók": "Features",
    "Ki volt Tiro?": "Who was Tiro?",
    "Lépj be": "Log in",
    "AI cégtitkár": "AI company secretary",
    "<span>Tiro</span> intézte ura feljegyzéseit és ügyeit, hogy Cicero <span>államférfiként</span> dolgozhasson.": (
        "<span>Tiro</span> managed his master's notes and affairs, so that Cicero could work as a "
        "<span>statesman</span>."
    ),
    "Ezt a szerepet tölti be ez az alkalmazás is — csendben, megbízhatóan intézi a számokat, hogy azzal foglalkozhass, amiben a legjobb vagy.": (
        "This application fills the same role — quietly and reliably handling the numbers, so you can "
        "focus on what you're best at."
    ),
    "Élő Dashboard": "Live Dashboard",
    "Tiro digitális cégtitkár irányítópultja": "Tiro digital company secretary dashboard",
    "Integrált pénzügyi forrás": "Integrated financial sources",
    "Privát AI — adatszivárgás nélkül": "Private AI — no data leakage",
    "Valós": "Real",
    "Élő tranzakciós adatok": "Live transaction data",
    "Intelligencia terület": "Intelligence areas",
    "A probléma": "The Problem",
    "A számok ott vannak.": "The numbers are right there.",
    "A válasz sehol.": "The answer is nowhere.",
    "A tulajdonos nem ERP-t akar. Egy cégtitkárt akar, aki összerakja a képet — azonnal, magyarul, a saját céges adataiból.": (
        "The owner doesn't want an ERP. They want a company secretary who puts the picture together — "
        "instantly, in plain language, from their own company data."
    ),
    "Mennyi készpénzem van összesen — cégenként és együtt?": (
        "How much cash do I have in total — per company and combined?"
    ),
    "Mikor fogy el a pénzem, ha ez a trend folytatódik?": "When will I run out of money if this trend continues?",
    "Mennyi osztalékot vehetek ki adóoptimálisan?": "How much dividend can I take out in a tax-optimal way?",
    "Melyik projektem a legnyereségesebb ebben a negyedévben?": (
        "Which of my projects is the most profitable this quarter?"
    ),
    "Melyik ügyfél termeli a valódi profitot?": "Which client generates the real profit?",
    "Melyik költség nőtt meg és miért?": "Which cost has increased and why?",
    "Mikor érdemes osztalékot kivenni idén?": "When is it worth taking out a dividend this year?",
    "Milyen adókockázataim vannak most?": "What tax risks do I have right now?",
    "A név mögött": "Behind the Name",
    "Marcus Tullius Tiro Kr. e. 103 körül született — rabszolgaként, Cicero apjának háztartásában. Alig két évvel volt fiatalabb Marcus Tullius Cicerónál, a híres szónoknál és államférfinál, és vele együtt nevelkedett. Felnőttként Cicero titkára, íródeákja lett.": (
        "Marcus Tullius Tiro was born around 103 BC — as a slave, in the household of Cicero's father. He "
        "was barely two years younger than Marcus Tullius Cicero, the famous orator and statesman, and grew "
        "up together with him. As an adult he became Cicero's secretary and scribe."
    ),
    'Kr. e. 63 körül Tiro kidolgozta a <strong style="color:var(--text)">Tironi jegyeket</strong> (notae Tironianae) — az első latin gyorsírási rendszert. Ezzel szóról szóra le tudta jegyezni Cicero beszédeit valós időben, köztük a híres Catilina-beszédeket a szenátusban. Cicero Kr. e. 53-ban felszabadította.': (
        'Around 63 BC, Tiro developed the <strong style="color:var(--text)">Tironian notes</strong> (notae '
        "Tironianae) — the first Latin shorthand system. With it he could record Cicero's speeches word for "
        "word in real time, including the famous Catiline orations in the Senate. Cicero freed him in 53 BC."
    ),
    'Cicero Kr. e. 43-as meggyilkolása után Tiro gyűjtötte össze, szerkesztette és adta ki ura leveleit és beszédeit — így maradtak fenn az utókornak —, és megírta Cicero életrajzát is. Állítólag közel száz évet élt. Ma <strong style="color:var(--accent)">a gyorsírás atyjaként</strong> tartják számon: a Tironi jegyek több mint ezer évig használatban maradtak, és a mai <strong style="color:var(--text)">„&amp;"</strong> jel is az egyik Tiro-féle rövidítésből ered.': (
        "After Cicero's assassination in 43 BC, Tiro collected, edited and published his master's letters "
        "and speeches — which is how they survived to posterity — and also wrote Cicero's biography. He is "
        'said to have lived to nearly a hundred. Today he is regarded as <strong style="color:var(--accent)">'
        'the father of shorthand</strong>: the Tironian notes remained in use for more than a thousand years, '
        'and today\'s <strong style="color:var(--text)">"&amp;"</strong> sign also originates from one of '
        "Tiro's abbreviations."
    ),
    "A megoldás": "The Solution",
    "9 területen ad azonnali választ": "Gives instant answers in 9 areas",
    "Nem szoftvert adunk el — egy digitális cégtitkárt, aki elvégzi a papírmunkát.": (
        "We're not selling software — a digital company secretary who does the paperwork."
    ),
    "Cash-flow előrejelzés": "Cash Flow Forecast",
    "Meddig elegendő a pénz, mikor várható likviditási feszültség.": (
        "How long the money will last, when a liquidity squeeze is expected."
    ),
    "Havi egyenleg trendje grafikonon": "Monthly balance trend on a chart",
    "Várható hiány figyelmeztetés": "Expected shortfall warning",
    "Optimális kifizetési idő": "Optimal payment timing",
    "Cash-flow előrejelzés illusztráció": "Cash flow forecast illustration",
    "Automatikus költségelemzés": "Automatic Expense Analysis",
    "Kategorizált kiadások, szokatlan tételek, előfizetések nyomon követése.": (
        "Categorized expenses, tracking of unusual items and subscriptions."
    ),
    "Melyik kategória nőtt": "Which category has grown",
    "Ismétlődő kiadások listája": "List of recurring expenses",
    "Rendkívüli tételek kiemelése": "Highlighting of exceptional items",
    "Automatikus költségelemzés illusztráció": "Automatic expense analysis illustration",
    "Projekt profitabilitás": "Project Profitability",
    "Projekt/ügyfél szintű margin": "Project/client level margin",
    "Veszteséges projektek azonosítása": "Identifying loss-making projects",
    "Historikus összehasonlítás": "Historical comparison",
    "Projekt profitabilitás illusztráció": "Project profitability illustration",
    "Következő fejlesztés": "Coming Next",
    "Természetes nyelven kérdezheted majd a saját adataidat — privát AI modellel, adatszivárgás nélkül.": (
        "You'll be able to ask your own data questions in natural language — with a private AI model, "
        "no data leakage."
    ),
    "Mikor volt a legmagasabb bevételünk és miért?": "When was our revenue highest and why?",
    "Miért csökkent a profitunk Q3-ban?": "Why did our profit decrease in Q3?",
    "Melyik ügyfél fizet a legtöbbet?": "Which client pays the most?",
    "AI CFO Owner Chat illusztráció": "AI CFO Owner Chat illustration",
    "Adóoptimalizálás": "Tax Optimization",
    "Osztalék időzítési javaslat": "Dividend timing suggestion",
    "ÁFA cash-flow optimalizálás": "VAT cash flow optimization",
    "Beruházási lehetőségek": "Investment opportunities",
    "Adóoptimalizálás illusztráció": "Tax optimization illustration",
    "Tulajdonosi dashboard": "Owner Dashboard",
    "Céges pénzek + bankok együtt": "Company funds + banks together",
    "Wise + IBKR egy helyen": "Wise + IBKR in one place",
    "Projekt áttekintő": "Project overview",
    "Tulajdonosi dashboard illusztráció": "Owner dashboard illustration",
    "Korai figyelmeztető": "Early Warning",
    "Cash-flow probléma előrejelzés": "Cash flow problem forecast",
    "Marketing ROI romlás jelzés": "Marketing ROI decline alert",
    "Koncentrációs kockázat riasztás": "Concentration risk alert",
    "Korai figyelmeztető illusztráció": "Early warning illustration",
    "Bér- és fizetéskalkulátor": "Wage and Payroll Calculator",
    "Nettó/bruttó bérszámfejtés, járulékok és adók automatikus kiszámítása magyar szabályozás szerint.": (
        "Automatic net/gross payroll, contribution and tax calculation according to Hungarian regulations."
    ),
    "Bruttó ↔ nettó átváltás": "Gross <-> net conversion",
    "Munkáltatói terhek kimutatása": "Employer cost breakdown",
    "Cafeteria és kedvezmények kezelése": "Cafeteria and allowance management",
    "Munkaidő és projektkövetés": "Time and Project Tracking",
    "Munkatársak és alvállalkozók rögzítik a ledolgozott órákat, projektenként és ügyfelenként csoportosítva.": (
        "Employees and subcontractors log their worked hours, grouped by project and client."
    ),
    "Napi/heti óra-rögzítés": "Daily/weekly hour logging",
    "Projekt szintű kimutatás": "Project-level reporting",
    "Alvállalkozói elszámolás alapja": "Basis for subcontractor billing",
    "Munkaidő és projektkövetés illusztráció": "Time and project tracking illustration",
    "Hogyan működik": "How It Works",
    "Négy lépésben él a saját adataidból": "Comes to life from your own data in four steps",
    "Nincs manuális adatbevitel — Tiro a forrásból olvas.": "No manual data entry — Tiro reads from the source.",
    "Csatlakoztatás": "Connect",
    "Gmail, NAV Online Számla, bankszámlák és IBKR összekötése — egyszeri beállítás.": (
        "Connecting Gmail, NAV Online Invoice, bank accounts and IBKR — a one-time setup."
    ),
    "Szinkronizálás": "Sync",
    "Tiro automatikusan letölti a számlákat, tranzakciókat és PDF mellékleteket.": (
        "Tiro automatically downloads invoices, transactions and PDF attachments."
    ),
    "Összefésülés": "Reconcile",
    "Számlák, kifizetések és fájlok automatikus párosítása és egyeztetése.": (
        "Automatic matching and reconciliation of invoices, payments and files."
    ),
    "Válasz": "Answer",
    "Nyitod a dashboardot — vagy hamarosan egyszerűen megkérdezed, amit tudni akarsz.": (
        "You open the dashboard — or soon you'll simply ask what you want to know."
    ),
    "Integrációk": "Integrations",
    "Minden forrásból közvetlenül": "Directly from every source",
    "Nem kell manuálisan exportálni — a rendszer a forrásból olvas.": (
        "No need to export manually — the system reads directly from the source."
    ),
    "aktív": "active",
    "hamarosan": "coming soon",
    "Kész átadni a papírmunkát Tirónak?": "Ready to hand the paperwork over to Tiro?",
    "Az élő dashboard azonnal elérhető — nézd meg, hogyan dolgozik.": (
        "The live dashboard is available right now — see how it works."
    ),
    "Élő Dashboard megnyitása": "Open Live Dashboard",
    "Főoldal": "Home",
    "Készítette": "Made by",
}
