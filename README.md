# 99N Bot Discord

Bot Discord untuk Clan **99N** (Clash of Clans) berbasis **discord.py 2.7.1**. Bot berjalan **fail-soft**: bila `COC_API_TOKEN` diisi ia membaca Clash of Clans API resmi secara live, dan bila token kosong — atau API menolak/mengalami gangguan — ia otomatis melayani dari snapshot JSON yang di-commit di `data/`. Ilustrasi Town Hall asli (`assets/Town_Hall<level>.webp`) ikut di repo. Tidak perlu checkout proyek lain: clone lalu jalan.

---

## ⚡ Fitur Utama

- **Live API dengan fallback graceful**: `bot/coc_api.py` memanggil API Supercell lewat stdlib `urllib` dengan cache TTL. Setiap kegagalan (403 token/IP, 5xx, timeout) dialihkan ke snapshot lokal dan dicatat — command Discord tidak pernah crash; penyebabnya bisa dibaca lewat `/freshness`.
- **Self-contained**: Snapshot JSON (`data/`) dan asset Town Hall (`assets/`) ikut di repo; `refresh.py` menarik snapshot terbaru langsung dari GitHub tanpa checkout `99N`.
- **Slash-only secara default**: Semua 32 perintah (23 top-level + 9 subcommand `/notif`) adalah `hybrid_command`, jadi berjalan sebagai `/` tanpa prefix. `BOT_PREFIX` kosong juga mematikan permintaan privileged intent `message_content` — tidak perlu toggle apa pun di Discord Developer Portal.
- **Embed kaya**: Badge clan & liga resmi dari payload CoC, progress bar Unicode, rasio (win rate, turnout raid), form strip hasil war (`🟩🟥🟨`), dan medali 🥇🥈🥉 untuk peringkat. Kartu `member`/`th` menampilkan gambar WebP Town Hall 1–19.
- **Pengaturan notifikasi ramah pemula**: `/notif panel` membuka satu pesan berisi dropdown semua notifikasi (dengan status dan penjelasan kapan ia menyala), tombol nyala/mati, serta picker channel & role bawaan Discord. Tersedia juga `/notif preset` dan autocomplete pada argumen event.
- **Logging terstruktur**: Konsol + file berputar `logs/bot.log` (5 MB × 3). Perintah `/logs` membaca ekornya dari Discord, dan opsi `LOG_CHANNEL_ID` mencerminkan log ke channel.
- **Notifikasi Otomatis (14 Event)**: Dispatcher background memeriksa perubahan snapshot dengan anti-spam cerdas (state tersimpan terpisah dari config).
- **Multi-Guild & Quiet Hours**: Konfigurasi per server di `config/guilds/<guild_id>.json` dengan dukungan jam tenang.

---

## 📦 Instalasi & Menjalankan Bot

### 1. Prasyarat
- Python 3.9+ (teruji di 3.9 dan 3.14)
- Pip

### 2. Setup Virtual Environment & Dependencies
```bash
cd "99N Bot Discord"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfigurasi Environment (`.env`)
```bash
cp .env.example .env
```

Minimal yang perlu diisi — bot langsung jalan hanya dengan token Discord:
```env
DISCORD_BOT_TOKEN=your_bot_token_here
BOT_PREFIX=                        # kosong = slash-only, tanpa privileged intent
DISCORD_GUILD_ID=                  # Opsional: ID server untuk instant slash sync
DATA_DIR=./data                    # Snapshot JSON yang ikut di repo ini
ASSET_DIR=./assets                 # Asset WebP Town Hall yang ikut di repo ini
CONFIG_DIR=./config/guilds         # Folder penyimpanan konfigurasi per guild
BOT_TIMEZONE=Asia/Jakarta
```

#### Mode live Clash of Clans API (opsional)
```env
COC_API_TOKEN=                     # dari https://developer.clashofclans.com
CLAN_TAG=#2J0YP2LQL
COC_CACHE_SECONDS=600
COC_PLAYER_LIMIT=                  # batasi lookup profil per anggota (kosong = semua)
```

> **Penting — IP allowlist.** Supercell menolak token dari IP yang belum terdaftar dengan HTTP `403 accessDenied`. Tambahkan IP publik mesin ini ke key tersebut di https://developer.clashofclans.com. Bila IP tidak bisa di-allowlist (mis. IP dinamis), set `COC_API_BASE_URL=https://cocproxy.royaleapi.dev/v1` atau biarkan token kosong untuk memakai snapshot.

Arahkan `DATA_DIR`/`ASSET_DIR` ke checkout `99N` (`../99N/data`, `../99N/assets`) bila ingin membaca data scraper terbaru, bukan salinan yang di-commit.

#### Logging (opsional)
```env
LOG_LEVEL=INFO                     # DEBUG | INFO | WARNING | ERROR | CRITICAL
LOG_CHANNEL_ID=                    # isi channel id untuk mencerminkan log ke Discord
BOT_LOG_DIR=                       # override lokasi logs/ (default: repo ini)
```

### 4. Menjalankan Bot
```bash
python3 bot.py
```

### 5. Menyegarkan Snapshot
```bash
python3 refresh.py            # data/ saja
python3 refresh.py --assets   # sekalian asset Town Hall
```
Mengambil dari `raw.githubusercontent.com` (repo `fthyll/99N`, branch `main`) hanya snapshot terbaru tiap folder — sekitar 0,8 MB, bukan 11 MB arsip penuh. Atur `REFRESH_REPO`/`REFRESH_BRANCH` untuk sumber lain.

---

## 📋 Daftar Perintah

Semua perintah adalah slash command (`/`). Tabel memakai nama slash.

### 🏛️ Clan Commands
| Perintah | Deskripsi |
|---|---|
| `/clan` | Ringkasan clan: badge resmi, level, piala, rekor & win-rate war (dengan bar), win streak, kapital, liga, lokasi, label. |
| `/roster [sort] [role] [limit]` | Daftar anggota dengan penanda 👑/⭐, filter role (`elder`, `coLeader`, dll), sorting (`trophies`, `donations`, `th`), plus total & net donasi. |
| `/top [metric] [limit]` | Peringkat anggota (🥇🥈🥉 + bar) berdasarkan piala, donasi, atau level TH. |

### 👤 Player Commands
| Perintah | Deskripsi |
|---|---|
| `/member <nama/tag>` | Kartu profil lengkap pemain beserta gambar level Town Hall. |
| `/th <level>` | Preview gambar Town Hall level 1 hingga 19. |
| `/topplayers [metric]` | Leaderboard pemain berdasarkan war stars atau donasi capital. |
| `/trend <nama/tag> [metric]` | Grafik tren 14 hari terakhir pemain (piala, donasi, war stars). |
| `/compare <nama1> <nama2>` | Membandingkan statistik 2 pemain secara berdampingan. |
| `/cwl` | Klasemen CWL dengan bar poin dan penanda baris clan sendiri. |
| `/inactive` | Anggota yang belum donasi, dengan jumlah dan persentase aktif. |

### ⚔️ War Commands
| Perintah | Deskripsi |
|---|---|
| `/war` | Status war: bar bintang, siapa unggul, destruction, sisa serangan, jumlah anggota belum menyerang. |
| `/attacks` | Anggota yang masih punya sisa serangan beserta bar per pemain. |
| `/lineup` | Perbandingan susunan base kita vs musuh, diringkas berapa matchup seimbang/lebih mudah/lebih sulit. |
| `/warlog` | Riwayat war + form strip (🟩🟥🟨). |
| `/warstats` | Win rate (dengan bar), rekor, streak, margin bintang, form terakhir. |

### 🏕️ Raid Weekend Commands
| Perintah | Deskripsi |
|---|---|
| `/raid` | Ringkasan Raid Weekend: loot, district hancur, porsi loot top-3, hadiah, dan top looter ber-medali. |
| `/raidmembers` | Rincian serangan (dari kapasitas 5+1 bonus) dan Capital Gold tiap anggota, plus turnout clan. |
| `/raidabsent` | Anggota yang belum menyerang, dihitung dari diff roster clan. |

### ⚙️ Admin & Notification Management
| Perintah | Deskripsi |
|---|---|
| `/notif panel` | **Panel interaktif**: dropdown semua notifikasi + tombol on/off + picker channel & role milik Discord. Cara termudah mengatur notifikasi. |
| `/notif preset <profil> [#ch]` | Terapkan profil siap pakai sekaligus: `essential`, `war-only`, `raid-only`, `all`. |
| `/notif list` | Status tiap notifikasi, dikelompokkan (War/Raid/Clan/CWL/System) dengan nama manusiawi. |
| `/notif set <event> <on/off>` | Nyalakan/matikan notifikasi. Parameternya autocomplete — ketik `reminder` untuk menemukan `war.attack_reminder` dan `raid.reminder`. |
| `/notif channel <event\|all> [#ch]` | Tujuan pesan notifikasi. |
| `/notif ping <event\|all> [@role]` | Role yang dimention saat event terpicu. |
| `/notif quiet [start] [end] [on/off]` | Jam tenang agar bot tidak mengirim notifikasi di malam hari. |
| `/notif test <event>` | Menguji pengiriman kartu embed event ke channel saat ini. |
| `/notif reset` | Menghapus state anti-spam agar notifikasi bisa dikirim ulang. |
| `/broadcast <pesan> [#ch]` | Pengumuman resmi ke channel. |
| `/config` | Konfigurasi server yang sedang aktif. |
| `/freshness` | Sumber data (live vs snapshot), usia, dan error API terakhir. |
| `/logs [lines] [level]` | Menampilkan ekor `logs/bot.log` dari Discord (admin). |

> **Cara tercepat mengatur notifikasi:** jalankan `/notif panel`. Pilih notifikasi dari dropdown, tekan **Turn on**, lalu pilih channel lewat picker. Tidak perlu mengetik ID channel atau nama event ber-titik. Untuk setup sekali jalan, pakai `/notif preset essential`.

Nama event yang ditampilkan di UI memakai label manusiawi (`War result`, `Raid reminder`); kunci teknis (`war.result`) tetap dipakai di dalam file config dan tetap diterima sebagai argumen.

---

## 🔔 Notifikasi Otomatis (14 Event)

1. `war.preparation`: Musuh war ditemukan & masa persiapan dimulai.
2. `war.result`: Hasil akhir war (Menang / Kalah / Seri).
3. `war.ending_soon`: Sisa waktu war < 2 jam dengan serangan belum selesai.
4. `war.attack_reminder`: Pengingat anggota yang masih punya tiket serangan.
5. `war.cleanup`: Rekap evaluasi serangan setelah war selesai.
6. `raid.start`: Pembukaan Raid Weekend Clan Capital.
7. `raid.summary`: Rekap medali dan gold saat Raid Weekend berakhir.
8. `raid.reminder`: Pengingat serangan Raid Weekend.
9. `clan.roster`: Anggota baru bergabung atau keluar.
10. `clan.donation_reset`: Reset season donasi bulanan.
11. `clan.donation_weekly`: Rekap mingguan pendonor tertinggi.
12. `clan.inactive`: Anggota tidak aktif yang belum donasi.
13. `cwl.round`: Pergantian ronde Clan War League.
14. `system.stale`: Peringatan data scraper macet >24 jam.

---

## 🗂️ Struktur Penting

| Path | Isi |
|---|---|
| `bot.py` | Entry point: intents, logging, cog, sync command, dispatcher. |
| `bot/coc_api.py` | Client API CoC (TTL cache, fallback snapshot, `last_errors`). |
| `bot/offload.py` | `WarmCache`: refresh background agar event loop tidak stall. |
| `bot/logging_setup.py` | Konfigurasi logging (konsol + file berputar). |
| `bot/discord_log.py` | Handler opsional yang mencerminkan log ke channel Discord. |
| `bot/embeds.py`, `bot/formatting.py` | Pembangun kartu & helper render (bar, pct, form, medali). |
| `bot/notifier.py` | Dispatcher 14 event + state anti-spam. |
| `bot/notif_panel.py` | Panel interaktif `/notif panel` (dropdown, tombol, picker channel/role). |
| `scripts/preview_embeds.py` | Render semua embed dari data nyata ke `embed_preview.md`. |
| `scripts/preview_panel.py` | Render isi panel notifikasi ke `panel_preview.md`. |
| `scripts/boot_probe.py` | Uji startup tanpa token (cog, command tree, logging). |
| `scripts/command_probe.py` | Verifikasi subcommand & binding autocomplete di command tree. |
| `scripts/panel_probe.py` | Verifikasi struktur panel (opsi, baris, persistensi config). |
| `scripts/live_check.py` | Start bot asli, buktikan online, lalu tutup. |

---

## 🧪 Pengujian

214 unit test memakai stdlib `unittest`:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -t .
```

Verifikasi manual:
```bash
python3 scripts/boot_probe.py                 # startup + logging, tanpa token Discord
python3 scripts/command_probe.py              # subcommand /notif + binding autocomplete
python3 scripts/panel_probe.py                # struktur panel (opsi, baris, persistensi)
python3 scripts/preview_embeds.py             # tulis embed_preview.md dari data nyata
python3 scripts/preview_panel.py              # tulis panel_preview.md
python3 scripts/live_check.py 25              # start sungguhan, cetak ONLINE=True/False
```

`scripts/live_check.py` butuh `DISCORD_BOT_TOKEN` yang valid dan keluar dengan kode 1 bila bot tidak pernah mencapai ready.

---

## 📄 Lisensi
MIT License © 2026 99N Clan
