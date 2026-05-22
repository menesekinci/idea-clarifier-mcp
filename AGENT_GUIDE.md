# Idea Clarifier MCP — Agent Guide

## Which tool to use?

| Situation | Tool | Questions | Output |
|---|---|---|---|
| **Yeni proje fikri** — teknoloji, mimari, DB, güvenlik kararları | `start_clarification` | 40-50, kategorili | `decisions.json` |
| **Mevcut proje** — planlama öncesi belirli kararları netleştirmek | `start_plan_clarification` | 5-15, kategorisiz | `plan_notes.json` |

## Workflow

```
1. Generate questions  →  2. start_clarification        →  3. poll get_answers  →  4. write_decisions
                              veya
                          start_plan_clarification
```

---

## Soru Yazma İlkeleri

Her soruyu üretmeden önce bu 6 kuralı kontrol et:

1. **Her şık bir karar noktası** — "seçilirse ne olur" somut olmalı; belirsiz genel ifade olmamalı.
2. **Şık açıklaması = trade-off** — teknik terimi açıkla + avantaj/dezavantajı belirt.
3. **Şıklar birbirini dışlasın** — aynı şeyi farklı kelimeyle söyleyen iki şık koyma.
4. **Bir şık "minimal/MVP"** — her soruda en az bir "basit tut" seçeneği olsun.
5. **Kullanıcı gözünden yaz** — soru metninde geliştirici jargonu olmasın; açıklamada olabilir.
6. **Soru tek boyutlu** — bir soruda iki farklı konu sorma; gerekirse iki ayrı soruya böl.

---

## Step 1 — Generate questions

### Question schema

```python
{
    "id":                  "q_vision_01",    # unique, snake_case
    "category":            "project_vision", # see categories below
    "question":            "Hedef kitle kim?",
    "options": [
        "Bireysel kullanıcılar",
        "Küçük ekipler (2–10 kişi)",
        "KOBİ (10–100 kişi)",
        "Kurumsal (100+ kişi)"
    ],
    "option_descriptions": [
        "Tek kişilik kullanım. Basit UX, minimum onboarding. Çok kullanıcı/izin mantığı gerekmez.",
        "Ekip paylaşımı ve görev ataması var. Rol yönetimi (yönetici/üye) gerektirir.",
        "Çok departman, yönetici hiyerarşisi, raporlama panoları. Kurumsal özellikler başlar.",
        "SSO/LDAP, SLA, audit log, veri izolasyonu gibi enterprise özellikler şart."
    ]
}
```

- `options` — tam olarak **4** şık.
- `option_descriptions` — tam olarak **4** açıklama (şıkla birebir eşleşir).
- Her kategori için en az **5 soru** üret.

---

## Categories (zorunlu sıra)

```
── Katman 1: Fikir ──────────────────────────────────────────────────────────
  project_vision   7 soru   ← ALWAYS FIRST

── Katman 2: Ürün ───────────────────────────────────────────────────────────
  core_flows       5+ soru  ← kullanıcı akışları & mekanikler
  feature_scope    5+ soru  ← özellik seti & MVP sınırı
  content_model    5+ soru  ← iş-seviyesi veri modeli & durumlar

── Katman 3: Deneyim ────────────────────────────────────────────────────────
  ui_ux            5+ soru  ← ekranlar, navigasyon, etkileşimler

── Katman 4: Teknik ─────────────────────────────────────────────────────────
  tech_stack | architecture | database | security
  performance | api | deployment | business_logic
  (her biri 5+ soru)
```

---

### `project_vision` — 7 soru, ALWAYS FIRST

Fikri anlamadan teknik hiçbir soru sorma.

```
1. Bu proje hangi temel sorunu çözüyor?
   [Bireysel verimlilik, Ekip koordinasyonu, Müşteri hizmeti, Süreç otomasyonu]

2. Hedef kitle kim?
   [Bireysel kullanıcılar, Küçük ekipler (2–10), KOBİ (10–100), Kurumsal (100+)]

3. Hangi platformda çalışacak?
   [Web uygulaması (tarayıcı), Mobil (iOS/Android), Masaüstü uygulaması, API servisi]

4. Kullanıcılar esas olarak ne yapacak?
   [Veri girer ve takip eder, İşbirliği yapar ve iletişim kurar, Rapor ve analiz görür, Otomasyon tetikler]

5. Beklenen kullanıcı ölçeği?
   [Kişisel (<10), Küçük takım (10–100), Orta ölçek (100–10k), Büyük ölçek (10k+)]

6. Gelir/sürdürülebilirlik modeli?
   [Ücretsiz/açık kaynak, Freemium + abonelik, Tek seferlik lisans, Kullanım başına ücret]

7. Rakiplere göre temel fark nedir?
   [Daha basit/odaklı UX, Daha derin özellik seti, Fiyat avantajı, Dikey sektör uzmanlığı]
```

---

### `core_flows` — 5+ soru

Ürünün çekirdeği: kullanıcı adım adım ne yapıyor? Her soru aşağıdaki açılardan birini hedeflemeli:

- **Happy path** — Temel varlık (görev, sipariş, kayıt…) oluştur → ata/yapılandır → tamamla adımları. Aralarındaki onay/geçiş kuralları.
- **Ret / geri alma** — Bir işlem reddedilirse, silinirse veya geri alınırsa ne olur? Kim yapabilir?
- **Zaman / deadline tetikleyicisi** — Süre dolunca ne tetiklenir? Otomatik mı, manuel mi?
- **Eşzamanlı kullanım** — İki kullanıcı aynı kaydı aynı anda düzenlerse çatışma nasıl çözülür?
- **Onboarding** — Yeni kullanıcı/ekip ilk girişte ne görür, ilk ne yapar?

---

### `feature_scope` — 5+ soru

Neyin içinde neyin dışında olduğunu belirle; ilerleyen teknik sorular bu sınıra göre şekillensin:

- **MVP çekirdeği** — Lansman için kesinlikle olması gereken 3–5 özellik hangisi?
- **Kapsam dışı** — Rakiplerde var ama ilk versiyonda olmayacak özellikler?
- **Öncelik sıralaması** — İki özellik çakıştığında hangisi önce gider?
- **Başarı metriği** — İlk ayda "bu çalıştı" diyebilmek için hangi kullanıcı davranışı görülmeli?
- **Ücretli katman sınırı** — Freemium/lisans modelinde ücretsiz ve ücretli arasındaki çizgi nerede?

---

### `content_model` — 5+ soru

Teknik DB seçiminden bağımsız, iş düzeyinde "neler var, nasıl ilişkili?":

- **Hiyerarşi** — Varlıklar nasıl iç içe geçiyor? (Workspace → Proje → Sprint → Görev → Alt görev mi, düz mı?)
- **Durum makinesi** — Temel varlığın durumları ve geçiş kuralları (kim, ne zaman, hangi duruma geçirebilir?)
- **Atama & sahiplik** — Bir varlık kaç kişiye atanabilir? Sahiplik transfer edilebilir mi?
- **Zorunlu alanlar** — Kullanıcının bir varlık oluştururken doldurmak zorunda olduğu minimum alanlar?
- **Esnek alanlar** — Kullanıcı kendi alan tanımlayabilecek mi? (custom fields, etiket, metadata)

---

### `ui_ux` — 5+ soru

"Dark mode mu?" değil, ürünün görsel-işlevsel iskeletini belirle:

- **Navigasyon modeli** — Kullanıcı bölümler arasında nasıl geçiş yapıyor? (sidebar, tab bar, breadcrumb, modal?)
- **Ana ekran / dashboard** — Giriş yapan kullanıcı ne görüyor? Kişisel pano mu, ekip özeti mi?
- **Temel görünüm türleri** — Liste, kanban, takvim, gantt — hangisi MVP'de zorunlu?
- **Boş durum (empty state)** — Hiç veri yokken ekran ne söylüyor? CTA var mı?
- **Mobil vs masaüstü önceliği** — Tasarım masaüstünden mi küçültülüyor, mobilden mi büyütülüyor?

---

### Teknik katman (her biri 5+ soru)

```
tech_stack     — dil, framework, paket yöneticisi, tip sistemi, API katmanı
architecture   — servis topolojisi, cache, kuyruk, real-time, dosya depolama
database       — birincil DB, ORM, migrasyon, replica, şema tasarımı
security       — kimlik doğrulama, yetkilendirme, rate limiting, secret yönetimi, audit log
performance    — CDN, sorgu optimizasyonu, bundle, yanıt süresi hedefi, sayfalama
api            — API stili, versiyonlama, dokümantasyon, webhook, hata formatı
deployment     — hosting, konteyner, CI/CD, ortam stratejisi, observability
business_logic — kullanıcı modeli, faturalandırma, bildirim, veri export, feature flags
```

---

## Step 2 — Call `start_clarification`

```python
result = start_clarification(
    idea="Ekipler için görev takip uygulaması — proje yönetimi ve deadline takibi",
    project_path="C:/path/to/my-project",
    questions=[
        {
            "id": "q_vision_01",
            "category": "project_vision",
            "question": "Bu proje hangi temel sorunu çözüyor?",
            "options": ["Bireysel verimlilik","Ekip koordinasyonu","Müşteri hizmeti","Süreç otomasyonu"],
            "option_descriptions": [
                "Kişisel görev takibi, odak artırma. Tek kullanıcı deneyimi ön planda.",
                "Ekip üyeleri arası görev dağıtımı ve iletişim. Çoklu kullanıcı + rol yönetimi.",
                "Müşteri talep ve şikayetleri takip edilir. CRM entegrasyonu ve ticket sistemi.",
                "Tekrarlayan süreçleri otomatikleştirir. Tetikleyici, koşul ve eylem zinciri içerir."
            ]
        },
        # ... 40+ more questions across all categories
    ]
)
# → { session_id, url, question_count, message }
# Also creates: project_path/.clarifier/session.json (crash recovery)
```

Tell the user: "Tarayıcınızda sorular açıldı. Lütfen yanıtlayın, ben burada bekliyorum."

---

## Step 3 — Poll `get_answers`

```python
while True:
    result = get_answers(session_id=session_id)

    if result["status"] == "completed":
        break

    time.sleep(5)
```

When `status == "completed"`, the response includes:
- `answers` — {question_id: {answer, ai_decides, custom, undecided, undecided_note}}
- `ai_decision_needed` — list of question_ids where user clicked "AI KARAR VERSİN"
- `undecided_questions` — list of {question_id, question_text, note} where user was unsure

**For `undecided_questions`**: discuss each one with the user HERE in the IDE — do NOT open a new browser session. After the conversation, include your conclusions in `ai_decisions` when calling `write_decisions`.

---

## Step 4 — Fill AI decisions, then `write_decisions`

```python
# result["ai_decision_needed"] → list of question_ids where user clicked "AI KARAR VERSİN"
write_decisions(
    session_id=session_id,
    ai_decisions={
        "q_tech_03": "pnpm — en hızlı kurulum, gelecekteki monorepo için workspace desteği",
        "q_sec_04":  ".env + CI/CD secrets — MVP aşaması için yeterli güvenlik"
    }
)
# Writes: project_path/decisions.json
# Cleans: project_path/.clarifier/session.json
```

---

## Tool reference

| Tool | When |
|---|---|
| `start_clarification(idea, project_path, questions)` | Yeni proje fikri → decisions.json |
| `start_plan_clarification(context, project_path, questions)` | Mevcut proje planlama öncesi → plan_notes.json |
| `get_answers(session_id)` | Her iki mod için — her 5 saniyede poll et |
| `write_decisions(session_id, ai_decisions)` | Status `completed` olduktan sonra |

---

## `start_plan_clarification` — Mevcut Proje Planlama Netleştirici

### Ne zaman kullanılır?

Mevcut bir projede kodu araştırdıktan sonra, implementasyon planı yazmadan önce kullanıcıdan
belirli kararları almak gerektiğinde. Örnek senaryolar:
- "Bu servisi refactor mi edelim, yoksa yeni bir tane mi yazalım?"
- "Migration breaking change olabilir — kullanıcı bunu kabul ediyor mu?"
- "Hangi endpoint'e dokunacağız?"

### Soru şeması (esnek)

```python
{
    "id":                  "p_01",       # required
    "question":            str,          # required
    "options":             list[str],    # exactly 4 option strings (A, B, C, D)
    "option_descriptions": list[str],    # exactly 4 plain-language descriptions
}
```

- `category` alanı gerekmez.
- Her soruda tam olarak 4 şık zorunludur — `start_clarification` ile aynı kural.

### Örnek çağrı — "FastAPI projesine OAuth eklemek"

```python
result = start_plan_clarification(
    context="Mevcut FastAPI projesine Google OAuth login ekleniyor",
    project_path="C:/path/to/my-api",
    questions=[
        {
            "id": "p_01",
            "question": "Mevcut JWT middleware refactor edilmeli mi?",
            "options": ["Evet — temizden yazalım", "Hayır — üzerine ekleyelim", "Kısmen — sadece token doğrulama", "Karar verilmedi — önce POC"],
            "option_descriptions": [
                "Mevcut kodu silerek OAuth'a özel yeni bir middleware yazarız. Daha temiz ama riski yüksek.",
                "Mevcut JWT kodu kalır, OAuth token'larını da handle edecek katman eklenir.",
                "Sadece token doğrulama kısmı yeniden yazılır, geri kalan dokunulmaz.",
                "Küçük bir proof-of-concept yapılır, ardından refactor kararı verilir. En düşük erken risk."
            ]
        },
        {
            "id": "p_02",
            "question": "Hangi OAuth provider(lar) desteklenmeli?",
            "options": ["Sadece Google", "Google + GitHub", "Google + GitHub + Microsoft", "Hepsi + custom OIDC"],
            "option_descriptions": [
                "En yaygın seçim. Tek provider, az kod, kolay bakım.",
                "Hem bireysel hem kurumsal kullanıcıları kapsıyor.",
                "Kurumsal (Microsoft) da dahil — enterprise kullanım için.",
                "Herhangi bir OpenID Connect provider desteklenir — en esnek ama en karmaşık."
            ]
        },
        {
            "id": "p_03",
            "question": "Erişim tokenı süresi ne kadar olmalı?",
            "options": ["15 dakika", "1 saat", "1 gün", "7 gün"],
            "option_descriptions": [
                "En güvenli seçenek. Token sık sık yenilenir, ele geçirilse kısa sürede geçersiz. Refresh token mekanizması şart.",
                "Güvenlik ve kolaylık dengesi. Kurumsal API'ler için yaygın tercih.",
                "Geliştirici odaklı uygulamalarda kullanışlı. Güvenlik riski orta.",
                "Uzun oturum, az yenileme. Mobil uygulamalar için pratik ama token sızıntısı riski artar."
            ]
        },
        {
            "id": "p_04",
            "question": "Breaking change kabul edilebilir mi?",
            "options": ["Evet — tam kırılma", "Kısmen — geçiş süreci ile", "Hayır — geriye dönük uyumlu", "Henüz karar vermedim"],
            "option_descriptions": [
                "Eski tokenlar anında geçersiz. En hızlı geliştirme; mevcut istemciler yeniden authenticate olmalı.",
                "Belirli bir süre eski ve yeni sistem paralel çalışır. Yavaş ama kullanıcı dostu geçiş.",
                "Eski JWT tokenlar kalıcı olarak desteklenir. En az risk, en fazla bakım yükü.",
                "Şimdilik bilinmiyor; sorular yanıtlandıktan sonra netleşecek."
            ]
        },
        {
            "id": "p_05",
            "question": "Test coverage beklentisi nedir?",
            "options": ["Sadece unit test", "Unit + integration", "E2E dahil tam coverage", "Test yok — MVP hızı"],
            "option_descriptions": [
                "Sadece servis katmanı test edilir. Hızlı yazar.",
                "Servis + HTTP endpoint testleri. Dengeli.",
                "Auth akışını baştan sona test eder. En güvenilir ama en yavaş.",
                "Test yok — şimdilik çalışması yeterli."
            ]
        },
    ]
)
# Çıktı: project_path/plan_notes.json (düz liste, kategorisiz)
```

### Polling loop — aynıdır

```python
while True:
    result = get_answers(session_id=result["session_id"])
    if result["status"] == "completed":
        break
    time.sleep(5)

write_decisions(session_id=result["session_id"], ai_decisions={...})
# → plan_notes.json oluşur
```
