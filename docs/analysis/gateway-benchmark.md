---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "gateway-benchmark",
  "kind": "analysis",
  "version": 1,
  "title": "Benchmark gatewaya data-plane wobec doraźnego SQLite",
  "status": "proposed",
  "owner": "wellmanifest/data-gateway",
  "scope": "repository",
  "created": "2026-10-13",
  "updated": "2026-10-13",
  "review_after": "2026-10-27",
  "source_revision": "cbe197e2d9897cbb40913554535b5efa2ed8600e",
  "affected_repositories": [
    "wellmanifest/data-gateway"
  ],
  "evidence": [
    "repo://wellmanifest/data-gateway/benchmarks/bench.py",
    "repo://wellmanifest/data-gateway/tests/test_schema_equivalence.py",
    "https://github.com/wellmanifest/data-plane/blob/24aca17ed102cdb7051ae95bf22575d15d1a756e/spec/SQLITE_COEXISTENCE.md"
  ]
}
---

# Benchmark gatewaya data-plane wobec doraźnego SQLite

<!-- docs:section question -->
## Question

Czy przejście ze zwykłego CRUD w SQLite z tabelą logu na ścieżkę data-plane
(zdarzenia, projekcja, receipt idempotencji, łańcuch audytu wellmanifest/logs,
linia `data-plane.line/v1`) poprawia projekt na każdym poziomie? Jeśli nie, to
które regresje da się usunąć bez utraty gwarancji?

<!-- docs:section scope -->
## Scope

Kernel `data_gateway` na `0684159` (przed zmianą) i z poprawkami z tego ticketu.
Obciążenie: N zapisów `resource.publish` po 512 B, N odczytów `resource.read` i
ponowienie 10% zapisów. Porównanie obejmuje trzy strony:

- `baseline`: zwykła tabela, wiersz logu JSON przy zapisie, odczyty bez logu;
- `baseline_equivalent`: to samo, ale każdy odczyt zatwierdza wiersz logu;
  gateway ma ten sam obowiązek audytu;
- `gateway`.

Wszystkie strony zapisują z `synchronous=FULL`, tak jak wymaga profil SQLite
data-plane. Benchmark nie obejmuje transportów sieciowych, PostgreSQL ani
współbieżności wielu pisarzy.

<!-- docs:section method -->
## Method

`python3 benchmarks/bench.py --n 150 --rounds 3 --dir ~/.cache/dp-bench` (oraz `--clients 8` dla zapisu współbieżnego) na
dysku, bo na tmpfs fsync jest darmowy i zafałszowuje wynik. Strony są
przeplatane w każdej rundzie, a raport podaje medianę z rund dla p50 i p95.

- **Czas ścienny i CPU:** mierzone osobno. Czas CPU wątku jest odporny na
  obciążenie hosta, a host miał load average 34–50 na 16 rdzeniach.
- **Miejsce:** liczone po `wal_checkpoint(TRUNCATE)`.
- **Atrybucja kosztów:** cProfile oraz warianty, w których usuwano po jednym
  źródle kosztu.

`--check` kończy się kodem 1, gdy któryś z progów nie przechodzi:

- czas ścienny zapisu gatewaya ≤ 1,5 × baseline;
- czas ścienny odczytu ≤ równoważny baseline;
- ponowione żądania nie mają żadnych skutków.

<!-- docs:section evidence -->
## Evidence

Mediany p50 na dysku, w µs. Miejsce w bajtach na zapis.

| Strona | Zapis wall | Zapis CPU | Odczyt wall | Odczyt CPU | Miejsce/zapis | Skutki duplikatów |
|---|---|---|---|---|---|---|
| baseline | 4168 | 392 | 19 | 19 | 1229 | 15 |
| baseline_equivalent | 3874 | 338 | 3820 | 294 | 1393 | 15 |
| gateway przed | 5148 | 1399 | 4663 | 1039 | 5379 | 0 |
| gateway po | 6456 | 1120 | 272 | 272 | — | 0 |

Wiersz „po” pochodzi z osobnego przebiegu przed poprawką pomiaru miejsca;
w tym samym przebiegu baseline zapisywał w 7812 µs. Gateway przed poprawkami
nie przechodzi progu odczytu (4663 > 3820), a po poprawkach przechodzi wszystkie
progi.

Atrybucja CPU na tmpfs (µs na operację, mediana z 5 rund):

| Wariant | Zapis | Odczyt |
|---|---|---|
| przed | 671 | 442 |
| skompilowana walidacja schematów | 471 | 294 |
| wszystkie cztery poprawki | 403 | 230 |

Zapis współbieżny, 8 wątków, `--clients 8`, mediana z 3 rund na dysku. Dysk był
wtedy bardzo obciążony (fsync ok. 20 ms), więc liczą się proporcje:

| Strona | Zapisy/s | p50 zapisu | Średnia grupa |
|---|---|---|---|
| baseline (8 połączeń) | 7,5 | 32 ms | — |
| gateway, każde polecenie osobno (`commit_window=None`) | 10,1 | 335 ms | 1,0 |
| gateway, grupowe zatwierdzanie (`commit_window=2 ms`) | 35,4 | 62 ms | 8,0 |

Rozkład miejsca gatewaya na cykl zapis+odczyt:

| Tabela | B |
|---|---|
| audit (2 rekordy) | 2062 |
| events | 1379 |
| blobs | 696 |
| receipts | 314 |
| resources | 177 |

<!-- docs:section facts -->
## Facts

- **Gwarancje:** gateway daje cztery gwarancje, których żaden baseline nie
  daje:
  - idempotentne ponowienia (0 skutków wobec 15);
  - wykrywanie zmiany rekordu audytu przez łańcuch hashy;
  - odtworzenie projekcji ze zdarzeń;
  - brak skutków po odrzuconym zapisie, przy zachowanym audycie odrzucenia.
- **Odczyt przed zmianą:** regresją dominował fsync audytu każdego zapytania.
  Zatwierdzanie audytu zapytań z WAL `synchronous=NORMAL` skraca odczyt z ok.
  4,7 ms do 0,27 ms. Zapisy dalej używają `FULL`.
- **Walidacja schematów:** skompilowane walidatory (fastjsonschema) zastępują
  ogólny walidator Draft 2020-12.
  - `tests/test_schema_equivalence.py` porównuje werdykty obu na ponad 1000
    instancjach z każdego schematu katalogu.
  - Test wykrył jedną rozbieżność: draft-07 sprawdzał `contentEncoding`, który
    w 2020-12 jest tylko adnotacją. Słowa kluczowe będące wyłącznie adnotacjami
    są teraz usuwane przed kompilacją.
- **Parsowanie i hash wejścia:** kernel parsuje linię raz dla klasyfikacji i
  `inputHash` zamiast czterech razy. Hash wejścia pozostaje ten sam:
  `sha256(format_line(parse(text)))`.
- **Zapis (wall):** wynik zależy od fsync i mieści się w progu 1,5×.
- **Grupowe zatwierdzanie:**
  - Polecenia współbieżne dzielą jedną transakcję i jeden fsync.
  - Każde polecenie ma własny `SAVEPOINT`, więc odrzucone polecenie wycofuje
    tylko siebie, a jego audyt zostaje.
  - Odpowiedź wychodzi dopiero po COMMIT, a błąd COMMIT trafia do każdego
    członka grupy, więc trwałość potwierdzonego polecenia się nie zmienia.
  - Polecenie samo w kolejce zatwierdza się od razu, więc pojedynczy klient
    nie czeka okna.
  - Testy: `tests/test_group_commit.py`.
- **Pozostające regresje:**
  - CPU zapisu: ok. 3 razy więcej niż w baseline;
  - miejsce: ok. 3,9 razy więcej niż w `baseline_equivalent`.

<!-- docs:section hypotheses -->
## Hypotheses

- Kompresja rekordów `audit` i `events` zlib ze stałym, wersjonowanym słownikiem
  zmniejszyłaby te tabele do ok. 27–28% (pomiar na 600 rekordach). Całość
  spadłaby wtedy z ok. 5,4 KB do ok. 2,7 KB na zapis, kosztem ok. 30 µs CPU na
  rekord.
- Iteracyjne `canonical()` w data-plane (−17% na zdarzenie) i argument `parsed=`
  w `line_to_request` obniżą CPU zapisu o kolejne ok. 10–15%, gdy gateway
  przypnie nową rewizję data-plane.

<!-- docs:section limitations -->
## Limitations

- Host był mocno obciążony przez inne procesy. Czas ścienny ma duży rozrzut
  (p95 do 10× p50), dlatego progi działają tylko w obrębie jednego przebiegu, a
  benchmark nie jest częścią CI.
- `synchronous=NORMAL` dla audytu zapytań oznacza, że przy utracie zasilania
  mogą zginąć ostatnie rekordy audytu odczytów. Awaria procesu ich nie usuwa.
  Mutacje i ich audyt mają nadal pełną trwałość.
- Benchmark mierzy tylko kernel, bez REST, gRPC i MCP.

<!-- docs:section recommendations -->
## Recommendations

1. Przyjąć grupowe zatwierdzanie (domyślnie okno 2 ms). Przy 8 klientach
   przepustowość zapisu rośnie 3,5× wobec osobnych transakcji i 4,7× wobec
   baseline.
2. Przyjąć poprawki z tego ticketu, które usuwają regresję odczytu i obniżają
   CPU bez utraty gwarancji. Uruchamiać `make bench` przy zmianach kernela lub
   magazynu.
3. Przypiąć rewizję data-plane z iteracyjnym `canonical()` i `parsed=` (osobny
   ticket w data-plane).
4. Kompresję ze słownikiem wprowadzać tylko po decyzji właściciela, bo
   zobowiązuje do trwałego formatu przechowywania.
5. Przed wdrożeniem pilotażowym w projekcie adoptującym uruchomić ten sam
   benchmark na jego rzeczywistym obciążeniu.
