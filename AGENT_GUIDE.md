# Idea Clarifier MCP — Agent Guide

## Which tool to use?

| Situation | Tool | Questions | Output |
|---|---|---|---|
| **Yeni proje fikri, aşama 1** — niyet, hedef, kavramsal mantık | `start_intent_clarification` | 7 sabit seçenekli soru | Ham cevaplar |
| **Yeni proje fikri, aşama 2** — ürün ve gerekiyorsa teknik kararlar | `start_clarification` | 12-25 hedefli, kategorili | `decisions.json` |
| **Mevcut proje** — planlama öncesi belirli kararları netleştirmek | `start_plan_clarification` | 5-15, kategorisiz | `plan_notes.json` |

## Workflow

```
1. start_intent_clarification  →  2. kullanıcı cevaplar  →  3. get_answers (TEK çağrı)
          ↓
   ajan kendi içinde kısa intent brief çıkarır (dosyaya yazmaz)
          ↓
4. start_clarification         →  5. add_glossary (1-N kez) →  6. get_answers → 7. write_decisions

Mevcut proje planlama için: start_plan_clarification → get_answers → write_decisions
```

**Zorunlu yeni proje akışı:** Ajan önce `start_intent_clarification` çağırır. Kullanıcının niyeti,
hedefi, amacı ve ürünün kavramsal çalışma mantığı anlaşılmadan ürün/teknik soru üretilmez.
Intent aşamasında kullanıcı hazır seçeneklerden seçim yapar ve gerekirse kendi cevabını seçime ekler.
Intent cevapları geldikten sonra ajan kendi içinde kısa bir intent brief çıkarır; bu brief dosyaya yazılmaz.

**İkinci aşama:** Ajan intent brief'e dayanarak `start_clarification` sorularını üretir — sayfa **hemen** açılır.
Kullanıcı soruları okurken ajan `add_glossary` ile terimleri bir veya birden fazla çağrıda gönderir.
Tarayıcı 2.5 saniyede bir poll eder, sözlük kartını günceller. Ajan boş `add_glossary(session_id, terms=[])`
çağrısıyla terimlerin tamamlandığını bildirince polling durur.
Sözlük kartı **kapalı** gelir — kullanıcı isterse tıklayıp açar.

**ÖNEMLİ:** Ajan `get_answers`'ı loop'ta poll etmez. Kullanıcının "cevapladım" demesini bekler,
sonra **tek bir** `get_answers` çağrısı yapar.

**Çoklu seçim:** Sorularda birden fazla şık seçilebilir. Kullanıcının seçtiği cevaplar çelişkiliyse,
ajan IDE'deki konuşmada bunu kesinleştirir — yeni MCP oturumu açmaya gerek yoktur.

---

## Soru Yazma İlkeleri

Her ikinci aşama sorusunu üretmeden önce bu kuralları kontrol et:

1. **Önce niyet** — intent cevapları anlaşılmadan teknik karar sorma.
2. **Tek karar ekseni** — her soru için zihninde bir `decision_axis` belirle.
3. **Tekrar yok** — aynı `decision_axis` ikinci kez sorulamaz; aynı kararı farklı kelimelerle tekrar sorma.
4. **Seçim tipini açık yaz** — choice sorularda `type` alanını mutlaka `single_choice` veya `multi_choice` olarak yaz.
5. **Doğru seçim tipi** — tek bir ana karar gerekiyorsa `single_choice`, birden fazla cevap aynı anda geçerliyse `multi_choice`.
6. **Her şık bir karar noktası** — "seçilirse ne olur" somut olmalı; belirsiz genel ifade olmamalı.
7. **Şık açıklaması = trade-off** — teknik terimi açıkla + avantaj/dezavantajı belirt.
8. **Şıklar birbirini dışlasın** — aynı şeyi farklı kelimeyle söyleyen iki şık koyma.
9. **Bir şık "minimal/MVP"** — her soruda en az bir "basit tut" seçeneği olsun.
10. **Kullanıcı gözünden yaz** — soru metninde geliştirici jargonu olmasın; açıklamada olabilir.
11. **Soru tek boyutlu** — bir soruda iki farklı konu sorma; gerekirse iki ayrı soruya böl.

MCP runtime aynı `decision_axis`, duplicate `id` ve bariz benzer soru metinlerini reddeder.
Yine de tekrarları önlemenin ilk sorumluluğu ajanın karar ekseni defterini doğru tutmasıdır.

---

## Step 1 — Clarify intent first

Yeni proje fikrinde doğrudan teknik veya kapsam sorularına geçme. Önce sabit seçenekli intent oturumunu aç:

```python
result = start_intent_clarification(
    idea="Ekipler için görev takip uygulaması — proje yönetimi ve deadline takibi",
    project_path="C:/path/to/my-project"
)
```

Kullanıcı "cevapladım / bitti" dedikten sonra:

```python
intent_result = get_answers(session_id=result["session_id"])
```

Bu ham cevaplardan kendi içinde kısa bir intent brief çıkar:

```text
- Amaç:
- Hedef kullanıcı:
- Problem bağlamı:
- Kavramsal çalışma mantığı:
- Başarı ölçütü:
- Kapsam dışı:
- Açık varsayım:
```

Bu brief'i dosyaya yazma. İkinci aşama sorularını sadece bu brief'e göre üret.
Intent cevaplarında `answer` string veya array olabilir. Kullanıcı custom cevap eklediyse bu cevap seçili
opsiyonlarla aynı `answer` dizisine eklenir ve `custom: true` gelir.

---

## Step 2 — Generate decision questions

### Question schema

```python
{
    "id":                  "q_vision_01",    # unique, snake_case
    "category":            "project_vision", # see categories below
    "type":                "single_choice",  # explicit: single_choice | multi_choice
    "decision_axis":       "target_user_segment",
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
- `decision_axis` — MCP tarafından doğrulanan benzersiz karar ekseni; aynı eksen tekrar sorulmaz.
- `type` — choice sorularda açıkça yazılır; default'a güvenme.
- Toplamda genellikle **12-25 hedefli soru** üret; teknik kategorileri yalnızca intent cevapları gerektiriyorsa ekle.

### Glossary (terim sözlüğü)

Teknik kategorilerde soru üretirken jargon terimleri için bir **glossary** listesi oluştur.
Terimler `start_*` ile birlikte veya — **tercihen** — sayfa açıldıktan sonra `add_glossary` ile
bir veya birden fazla adımda gönderilir. Tarayıcı 2.5 saniyede bir poll edip sözlük kartını
günceller; boş `add_glossary(session_id, terms=[])` çağrısıyla terimler tamamlanınca polling durur.

Sözlük kartı sayfa yüklendiğinde **kapalı (collapsed)** gelir — kullanıcı tıklayıp açar.
Terim yokken kartta spinner ve "Terimler hazırlanıyor…" yazar.

```python
glossary = [
    {"term": "ORM", "explanation": "Object-Relational Mapping — Veritabanı tablolarını kod nesnelerine dönüştüren araç. SQL yazmadan veri okuma/yazma yapmayı sağlar."},
    {"term": "JWT", "explanation": "JSON Web Token — Kimlik doğrulama için kullanılan şifreli token. Kullanıcı giriş yaptıktan sonra sunucu bu token'ı verir, tarayıcı her istekte bunu gönderir."},
    {"term": "SSR", "explanation": "Server-Side Rendering — Sayfanın HTML'inin sunucuda oluşturulup tarayıcıya gönderilmesi. İlk yükleme hızlıdır, SEO dostudur."},
]
```

Glossary kuralları:
- Her terim için **tek cümlelik** açıklama yeterlidir; 2-3 cümleyi geçme.
- Açıklama teknik dilde olabilir ama **ilk cümle mutlaka anlaşılır Türkçe** olmalı.
- Sadece sorularda geçen terimleri ekle — kullanılmayan terim ekleme.
- Terim sayısı soru sayısının %10-20'si civarında olmalı (20 soruda 2-4 terim gibi).

---

## Categories (önerilen sıra)

```
── Katman 1: Fikir ──────────────────────────────────────────────────────────
  project_vision   gerekli karar eksenleri  ← ALWAYS FIRST

── Katman 2: Ürün ───────────────────────────────────────────────────────────
  core_flows       gerektiği kadar  ← kullanıcı akışları & mekanikler
  feature_scope    gerektiği kadar  ← özellik seti & MVP sınırı
  content_model    gerektiği kadar  ← iş-seviyesi veri modeli & durumlar

── Katman 3: Deneyim ────────────────────────────────────────────────────────
  ui_ux            gerektiği kadar  ← ekranlar, navigasyon, etkileşimler

── Katman 4: Teknik ─────────────────────────────────────────────────────────
  tech_stack | architecture | database | security
  performance | api | deployment | business_logic
  (yalnızca intent cevapları gerektiriyorsa)
```

---

### `project_vision` — ALWAYS FIRST

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

### `core_flows`

Ürünün çekirdeği: kullanıcı adım adım ne yapıyor? Her soru aşağıdaki açılardan birini hedeflemeli:

- **Happy path** — Temel varlık (görev, sipariş, kayıt…) oluştur → ata/yapılandır → tamamla adımları. Aralarındaki onay/geçiş kuralları.
- **Ret / geri alma** — Bir işlem reddedilirse, silinirse veya geri alınırsa ne olur? Kim yapabilir?
- **Zaman / deadline tetikleyicisi** — Süre dolunca ne tetiklenir? Otomatik mı, manuel mi?
- **Eşzamanlı kullanım** — İki kullanıcı aynı kaydı aynı anda düzenlerse çatışma nasıl çözülür?
- **Onboarding** — Yeni kullanıcı/ekip ilk girişte ne görür, ilk ne yapar?

---

### `feature_scope`

Neyin içinde neyin dışında olduğunu belirle; ilerleyen teknik sorular bu sınıra göre şekillensin:

- **MVP çekirdeği** — Lansman için kesinlikle olması gereken 3–5 özellik hangisi?
- **Kapsam dışı** — Rakiplerde var ama ilk versiyonda olmayacak özellikler?
- **Öncelik sıralaması** — İki özellik çakıştığında hangisi önce gider?
- **Başarı metriği** — İlk ayda "bu çalıştı" diyebilmek için hangi kullanıcı davranışı görülmeli?
- **Ücretli katman sınırı** — Freemium/lisans modelinde ücretsiz ve ücretli arasındaki çizgi nerede?

---

### `content_model`

Teknik DB seçiminden bağımsız, iş düzeyinde "neler var, nasıl ilişkili?":

- **Hiyerarşi** — Varlıklar nasıl iç içe geçiyor? (Workspace → Proje → Sprint → Görev → Alt görev mi, düz mı?)
- **Durum makinesi** — Temel varlığın durumları ve geçiş kuralları (kim, ne zaman, hangi duruma geçirebilir?)
- **Atama & sahiplik** — Bir varlık kaç kişiye atanabilir? Sahiplik transfer edilebilir mi?
- **Zorunlu alanlar** — Kullanıcının bir varlık oluştururken doldurmak zorunda olduğu minimum alanlar?
- **Esnek alanlar** — Kullanıcı kendi alan tanımlayabilecek mi? (custom fields, etiket, metadata)

---

### `ui_ux`

"Dark mode mu?" değil, ürünün görsel-işlevsel iskeletini belirle:

- **Navigasyon modeli** — Kullanıcı bölümler arasında nasıl geçiş yapıyor? (sidebar, tab bar, breadcrumb, modal?)
- **Ana ekran / dashboard** — Giriş yapan kullanıcı ne görüyor? Kişisel pano mu, ekip özeti mi?
- **Temel görünüm türleri** — Liste, kanban, takvim, gantt — hangisi MVP'de zorunlu?
- **Boş durum (empty state)** — Hiç veri yokken ekran ne söylüyor? CTA var mı?
- **Mobil vs masaüstü önceliği** — Tasarım masaüstünden mi küçültülüyor, mobilden mi büyütülüyor?

---

### Teknik katman (yalnızca gerekiyorsa)

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

## Step 3 — Call `start_clarification` (then `add_glossary`)

```python
# Intent brief hazırlandıktan sonra: karar sorularını gönder, sayfa hemen açılsın
result = start_clarification(
    idea="Ekipler için görev takip uygulaması — proje yönetimi ve deadline takibi",
    project_path="C:/path/to/my-project",
    questions=[
        {
            "id": "q_vision_01",
            "category": "project_vision",
            "type": "single_choice",
            "decision_axis": "primary_problem_type",
            "question": "Bu proje hangi temel sorunu çözüyor?",
            "options": ["Bireysel verimlilik","Ekip koordinasyonu","Müşteri hizmeti","Süreç otomasyonu"],
            "option_descriptions": [
                "Kişisel görev takibi, odak artırma. Tek kullanıcı deneyimi ön planda.",
                "Ekip üyeleri arası görev dağıtımı ve iletişim. Çoklu kullanıcı + rol yönetimi.",
                "Müşteri talep ve şikayetleri takip edilir. CRM entegrasyonu ve ticket sistemi.",
                "Tekrarlayan süreçleri otomatikleştirir. Tetikleyici, koşul ve eylem zinciri içerir."
            ]
        },
        # ... 12-25 targeted questions across only the needed categories
    ]
)
# → { session_id, url, question_count, message }
# Browser opens immediately! User starts reading questions.
session_id = result["session_id"]

# SONRA: kullanıcı soruları okurken, ajan sözlük terimlerini gönderir
add_glossary(session_id=session_id, terms=[
    {"term": "CRM", "explanation": "Müşteri İlişkileri Yönetimi — müşteri verilerini ve etkileşimleri tek yerde toplar."},
    {"term": "MVP", "explanation": "Minimum Viable Product — ürünün sadece temel özelliklerle çıkan ilk sürümü."},
    {"term": "CDN", "explanation": "Content Delivery Network — statik dosyaları dünyanın farklı noktalarından hızlı sunan ağ."},
])
# → { success: true, total_terms: 3, added: 3 }

# Daha fazla terim eklenebilir (teknik katman soruları üretildikçe):
add_glossary(session_id=session_id, terms=[
    {"term": "ORM", "explanation": "Object-Relational Mapping — veritabanı tablolarını kod nesnelerine dönüştüren araç."},
    {"term": "SSR", "explanation": "Server-Side Rendering — HTML'in sunucuda oluşturulup tarayıcıya gönderilmesi."},
])
# → { success: true, total_terms: 5, added: 2 }
# Browser glossary card updates live — no page reload needed!
```

Tell the user: "Tarayıcınızda sorular açıldı. Lütfen yanıtlayın, ben burada bekliyorum."

---

## Step 4 — Wait for user, then `get_answers` ONCE

Ajan `get_answers`'ı **loop'ta poll etmez.** Kullanıcının tarayıcıda "Kararları Kaydet" butonuna
basmasını bekler. Kullanıcı IDE'de "cevapladım", "bitti", "tamam" gibi bir sinyal verdiğinde
ajan **tek bir** `get_answers` çağrısı yapar:

```python
result = get_answers(session_id=session_id)
```

When `status == "completed"`, the response includes:
- `answers` — {question_id: {answer, ai_decides, custom, undecided, undecided_note}}
- `ai_decision_needed` — list of question_ids where user clicked "AI KARAR VERSİN"
- `undecided_questions` — list of {question_id, question_text, note} where user was unsure

**For `undecided_questions`**: discuss each one with the user HERE in the IDE — do NOT open a new browser session. After the conversation, include your conclusions in `ai_decisions` when calling `write_decisions`.

**Multi-select notes:** `answer` field may be a string or an array of strings (if user picked multiple options).
If the selected options appear contradictory, discuss with the user in the IDE to resolve — no new MCP session needed.

---

## Step 5 — Fill AI decisions, then `write_decisions`

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
| `start_intent_clarification(idea, project_path)` | Yeni proje fikri için zorunlu ilk niyet oturumu |
| `start_clarification(idea, project_path, questions)` | Intent cevaplarından sonra yeni proje kararları → decisions.json |
| `start_plan_clarification(context, project_path, questions)` | Mevcut proje planlama öncesi → plan_notes.json |
| `add_glossary(session_id, terms)` | Herhangi bir zamanda, 1-N kez — tarayıcı canlı güncellenir |
| `get_answers(session_id)` | Kullanıcı "cevapladım" dedikten sonra TEK çağrı |

### Waiting flow — aynıdır

```python
# Kullanıcının "cevapladım / bitti" demesini BEKLE
# Sonra tek kez:
result = get_answers(session_id=result["session_id"])

write_decisions(session_id=result["session_id"], ai_decisions={...})
# → plan_notes.json oluşur
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
    ],
    glossary=[
        {"term": "OAuth", "explanation": "Open Authorization — Başka bir servis (Google, GitHub) üzerinden kullanıcı girişi yapma standardı. Şifre paylaşmadan yetkilendirme sağlar."},
        {"term": "JWT", "explanation": "JSON Web Token — Kimlik doğrulama için kullanılan şifreli token. Kullanıcı giriş yaptıktan sonra sunucu bu token'ı verir."},
        {"term": "POC", "explanation": "Proof of Concept — Bir fikrin çalışabilirliğini test etmek için yazılan küçük, deneysel kod."},
        {"term": "OIDC", "explanation": "OpenID Connect — OAuth 2.0 üzerine kurulu kimlik katmanı. Kullanıcının kim olduğunu doğrulayan standart."},
        {"term": "E2E", "explanation": "End-to-End test — Uygulamayı baştan sona, gerçek kullanıcı gibi test eden otomatik test türü."},
    ]
)
# Çıktı: project_path/plan_notes.json (düz liste, kategorisiz)
```

### Waiting flow — aynıdır

```python
# Kullanıcının "cevapladım / bitti" demesini BEKLE
# Sonra tek kez:
result = get_answers(session_id=result["session_id"])

write_decisions(session_id=result["session_id"], ai_decisions={...})
# → plan_notes.json oluşur
```
