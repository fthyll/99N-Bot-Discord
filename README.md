# 99N Bot Discord

Bot Discord untuk Clan **99N** (Clash of Clans) berbasis **discord.py 2.7.1**. Bot ini tidak memanggil API Supercell dan tidak bergantung pada checkout repo lain: semua data dibaca dari snapshot JSON yang di-commit di `data/` (bisa disegarkan dengan `refresh.py`), dan ilustrasi Town Hall asli (`assets/Town_Hall<level>.webp`) ikut di repo. Token Supercell tetap hanya di environment scraper.

---

## ⚡ Fitur Utama

- **Zero-API & Self-contained**: Tidak memanggil API Supercell, tidak butuh checkout repo lain. Snapshot JSON (`data/`) dan asset Town Hall (`assets/`) ikut di repo; `refresh.py` menarik data terbaru langsung dari GitHub.
- **Dukungan Perintah Ganda**: Semua perintah tersedia sebagai pesan prefix (default: `!`) dan Discord Application Slash Commands (`/`).
- **Rich Embeds & Gambar Town Hall**: Perintah `!member` dan `!th` menyertakan gambar WebP resmi Town Hall (level 1 sampai level 19) langsung di kartu Discord.
- **Notifikasi Otomatis (14 Event)**: Background dispatcher mengecek perubahan snapshot setiap 5 menit dengan anti-spam cerdas (state tersimpan terpisah dari config).
- **Multi-Guild & Quiet Hours**: Konfigurasi per server tersimpan di `config/guilds/<guild_id>.json` dengan dukungan jam tenang malam hari.

---

## 📦 Instalasi & Menjalankan Bot

### 1. Prasyarat
- Python 3.9+
- Pip

Tidak perlu checkout `99N` di sebelah repo ini: snapshot JSON (`data/`) dan asset Town Hall (`assets/`) sudah ikut di dalam repo.

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

Isi variabel di `.env`:
```env
DISCORD_BOT_TOKEN=your_bot_token_here
BOT_PREFIX=!
DISCORD_GUILD_ID=                  # Opsional: ID server untuk instant slash sync saat dev
DATA_DIR=./data                    # Snapshot JSON yang ikut di repo ini
ASSET_DIR=./assets                 # Asset WebP Town Hall yang ikut di repo ini
CONFIG_DIR=./config/guilds         # Folder penyimpanan konfigurasi per guild
BOT_TIMEZONE=Asia/Jakarta
```

Arahkan `DATA_DIR`/`ASSET_DIR` ke checkout `99N` (`../99N/data`, `../99N/assets`) bila ingin membaca data scraper terbaru, bukan salinan yang di-commit.

### 4. Menjalankan Bot
```bash
python3 bot.py
```

### 5. Menyegarkan Snapshot
`data/` dan `assets/` sudah di-commit agar bot langsung jalan setelah clone. Untuk menarik snapshot terbaru tanpa perlu checkout `99N`:
```bash
python3 refresh.py            # data/ saja
python3 refresh.py --assets   # sekalian asset Town Hall
```
Script ini mengambil dari `raw.githubusercontent.com` (repo `fthyll/99N`, branch `main`) hanya snapshot terbaru tiap folder — sekitar 0,8 MB, bukan 11 MB arsip penuh. Atur `REFRESH_REPO`/`REFRESH_BRANCH` bila ingin sumber lain.

---

## 📋 Daftar Perintah

### 🏛️ Clan Commands
| Prefix | Slash | Deskripsi |
|---|---|---|
| `!clan` | `/clan` | Menampilkan ringkasan profil clan (badge, level, piala, rekor war). |
| `!roster [sort] [role]` | `/roster` | Daftar anggota clan dengan filter role (`elder`, `coLeader`, dll) & sorting (`trophies`, `donations`, `th`). |
| `!top [metric] [limit]` | `/top` | Peringkat anggota teratas berdasarkan piala, donasi, atau level TH. |

### 👤 Player Commands
| Prefix | Slash | Deskripsi |
|---|---|---|
| `!member <nama/tag>` | `/member` | Kartu profil lengkap pemain beserta gambar level Town Hall. |
| `!th <level>` | `/th` | Melihat preview gambar Town Hall level 1 hingga 19. |
| `!topplayers [metric]` | `/topplayers` | Leaderboard pemain clan berdasarkan war stars atau donasi capital. |
| `!trend <nama/tag> [metric]` | `/trend` | Grafik tren 14 hari terakhir pemain (piala, donasi, war stars). |
| `!compare <nama1> <nama2>` | `/compare` | Membandingkan statistik 2 pemain secara berdampingan. |
| `!cwl` | `/cwl` | Klasemen dan status Clan War League terkini. |
| `!inactive` | `/inactive` | Menampilkan anggota yang belum melakukan donasi di snapshot ini. |

### ⚔️ War Commands
| Prefix | Slash | Deskripsi |
|---|---|---|
| `!war` | `/war` | Status live war (bintang, persentase damage, sisa waktu). |
| `!attacks` | `/attacks` | Daftar anggota yang masih memiliki sisa serangan war. |
| `!lineup` | `/lineup` | Perbandingan susunan base kita vs musuh di map war. |
| `!warlog` | `/warlog` | Riwayat hasil war sebelumnya. |
| `!warstats` | `/warstats` | Statistik keseluruhan (win rate, rekor streak, rata-rata bintang). |

### 🏕️ Raid Weekend Commands
| Prefix | Slash | Deskripsi |
|---|---|---|
| `!raid` | `/raid` | Ringkasan Raid Weekend (total medali, raid attack, gold dijarah). |
| `!raidmembers` | `/raidmembers` | Rincian serangan dan hasil Capital Gold tiap anggota. |
| `!raidabsent` | `/raidabsent` | Daftar anggota yang belum menyerang di Raid Weekend. |

### ⚙️ Admin & Notification Management
| Perintah | Deskripsi |
|---|---|
| `/notif list` | Menampilkan status aktif/nonaktif ke-14 notifikasi event. |
| `/notif set <event> <on/off>` | Mengaktifkan atau menonaktifkan event notifikasi tertentu. |
| `/notif channel <event\|all> [#ch]` | Mengarahkan tujuan pesan notifikasi ke channel tertentu. |
| `/notif ping <event\|all> [@role]` | Mengatur role yang dimention saat event terpicu. |
| `/notif quiet [start] [end] [on/off]` | Mengatur jam tenang agar bot tidak mengirim notifikasi di malam hari. |
| `/notif test <event>` | Menguji coba pengiriman kartu embed event ke channel saat ini. |
| `/notif reset` | Menghapus state anti-spam agar notifikasi lama dapat dikirim ulang jika perlu. |
| `!broadcast <pesan> [#ch]` | Mengirim pengumuman resmi dari clan/admin ke channel. |
| `!config` | Memeriksa konfigurasi server yang sedang aktif. |
| `!freshness` | Memeriksa usia data snapshot scraper (deteksi data basi). |

---

## 🔔 Notifikasi Otomatis (14 Event)

1. `war.preparation`: Saat musuh war ditemukan & masa persiapan dimulai.
2. `war.result`: Hasil akhir war (Menang / Kalah / Seri) diumumkan.
3. `war.ending_soon`: Peringatan sisa waktu war < 2 jam dengan serangan belum selesai.
4. `war.attack_reminder`: Pengingat bagi anggota yang masih memiliki tiket serangan.
5. `war.cleanup`: Rekap evaluasi serangan anggota setelah war selesai.
6. `raid.start`: Pembukaan Raid Weekend Clan Capital.
7. `raid.summary`: Rekap perolehan medali dan gold saat Raid Weekend berakhir.
8. `raid.reminder`: Pengingat serangan Raid Weekend bagi yang belum selesai.
9. `clan.roster`: Pengumuman anggota baru bergabung atau keluar dari clan.
10. `clan.donation_reset`: Notifikasi reset season donasi bulanan.
11. `clan.donation_weekly`: Rekap mingguan pendonor tertinggi di clan.
12. `clan.inactive`: Notifikasi anggota tidak aktif yang belum donasi.
13. `cwl.round`: Pergantian hari/ronde pertempuran di Clan War League.
14. `system.stale`: Peringatan otomatis jika data scraper macet atau tidak terupdate >24 jam.

---

## 🧪 Pengujian Unit Test

Proyek ini dilengkapi dengan 86 unit test komprehensif menggunakan standard library `unittest`:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -t .
```

---

## 📄 Lisensi
MIT License © 2026 99N Clan
