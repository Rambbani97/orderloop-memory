# Ground Truth — OrderLoop dataset (penilai ONLY)

> **JANGAN diberikan ke agent.** File ini hanya untuk penilai kualitas (blind rating) dan harness scoring otomatis.
> Dibuat otomatis dari `data/tickets.jsonl` — jangan edit manual; edit JSONL lalu regenerate.

## Tiket per cluster

### T-001 — C1 (Sedang, integrasi, email)
- **Subjek:** Stripe webhooks stopped working after we rotated our API keys
- **Root cause:** Webhook signing secret (whsec_...) dirotasi bersama API key di Stripe; secret baru belum dimasukkan ke OrderLoop, semua event gagal verifikasi signature (HTTP 400).
- **Correct fix:**
  1. Di dashboard Stripe, buka Developers > Webhooks > endpoint OrderLoop > Reveal signing secret baru
  2. Di OrderLoop, buka Settings > Integrations > Stripe > paste signing secret baru, Save
  3. Klik 'Send test event' (payment_intent.succeeded) dan pastikan 200 OK
  4. Re-play event yang gagal dari Stripe dashboard dan verifikasi ORD-88412 berubah ke Paid
  5. Catat rotasi secret di runbook agar rotasi berikutnya diikuti update di OrderLoop

### T-002 — C1 (Sedang, integrasi, in-app chat)
- **Subjek:** Paid orders not updating — customers charged but no confirmation
- **Root cause:** Webhook signing secret Stripe dirotasi, belum diperbarui di OrderLoop.
- **Correct fix:**
  1. Di dashboard Stripe, buka Developers > Webhooks > endpoint OrderLoop > Reveal signing secret baru
  2. Di OrderLoop, buka Settings > Integrations > Stripe > paste signing secret baru, Save
  3. Klik 'Send test event' (payment_intent.succeeded) dan pastikan 200 OK
  4. Re-play event yang gagal dari Stripe dashboard dan verifikasi ORD-89107 berubah ke Paid
  5. Catat rotasi secret di runbook agar rotasi berikutnya diikuti update di OrderLoop
- **Memory key (seed):** T-001

### T-003 — C1 (Sedang, integrasi, X DM)
- **Subjek:** tolong dong orderan ga masuk2
- **Root cause:** Webhook signing secret Stripe dirotasi, belum diperbarui di OrderLoop.
- **Correct fix:**
  1. Di dashboard Stripe, buka Developers > Webhooks > endpoint OrderLoop > Reveal signing secret baru
  2. Di OrderLoop, buka Settings > Integrations > Stripe > paste signing secret baru, Save
  3. Klik 'Send test event' (payment_intent.succeeded) dan pastikan 200 OK
  4. Re-play event yang gagal dari Stripe dashboard dan verifikasi salah satu dari 9 order berubah ke Paid
  5. Catat rotasi secret di runbook agar rotasi berikutnya diikuti update di OrderLoop
- **Memory key (seed):** T-001

### T-004 — C2 (Sulit, login-sso, email)
- **Subjek:** SSO login loop — users redirected back to login after authenticating via Okta
- **Root cause:** Sertifikat X.509 IdP (Okta) kedaluwarsa setelah ~1 tahun; OrderLoop menolak SAML response karena signature tidak bisa divalidasi, terjadi redirect loop tanpa pesan error yang jelas.
- **Correct fix:**
  1. Di Okta, buka aplikasi OrderLoop > Sign On > lihat tanggal kedaluwarsa sertifikat (expired)
  2. Generate sertifikat baru / unduh metadata XML terbaru dari Okta
  3. Di OrderLoop, buka Settings > Security > SSO/SAML > upload metadata XML baru (atau paste sertifikat baru), Save
  4. Uji login SSO dengan 1 akun staf, pastikan masuk dashboard
  5. Catat tanggal kedaluwarsa baru + set pengingat 30 hari sebelumnya
  6. Komunikasikan ke tim bahwa password login darurat tetap tersedia selama perbaikan

### T-005 — C2 (Sulit, login-sso, help-center form)
- **Subjek:** SAML authentication failing — "Signature validation failed" in logs
- **Root cause:** Sertifikat signing IdP (Azure AD) kedaluwarsa; SAML response ditolak karena signature tidak bisa divalidasi.
- **Correct fix:**
  1. Di Azure AD, buka enterprise app OrderLoop > lihat tanggal kedaluwarsa sertifikat (expired)
  2. Unduh federation metadata baru dari Azure portal
  3. Di OrderLoop, buka Settings > Security > SSO/SAML > upload metadata XML baru, Save
  4. Uji login SSO dengan 1 akun staf, pastikan masuk dashboard
  5. Catat tanggal kedaluwarsa baru + set pengingat 30 hari sebelumnya
  6. Komunikasikan ke tim bahwa password login darurat tetap tersedia selama perbaikan
- **Memory key (seed):** T-004

### T-006 — C2 (Sulit, login-sso, in-app chat)
- **Subjek:** Nobody can log in!!!
- **Root cause:** Sertifikat signing IdP (Microsoft/Azure AD) kedaluwarsa; SAML response ditolak, terjadi redirect loop.
- **Correct fix:**
  1. Di Azure AD, buka enterprise app OrderLoop > lihat tanggal kedaluwarsa sertifikat (expired)
  2. Unduh federation metadata baru dari Azure portal
  3. Di OrderLoop, buka Settings > Security > SSO/SAML > upload metadata XML baru, Save
  4. Uji login SSO dengan 1 akun staf, pastikan masuk dashboard
  5. Catat tanggal kedaluwarsa baru + set pengingat 30 hari sebelumnya
  6. Jelaskan langkah demi langkah dengan bahasa sederhana untuk pengguna non-teknis
- **Memory key (seed):** T-004

### T-007 — C3 (Sedang, billing, email)
- **Subjek:** Incorrect VAT on invoice INV-2026-4417 after plan upgrade
- **Root cause:** Upgrade mid-cycle tidak memicu proration credit otomatis untuk sisa hari plan lama; pajak dihitung dari harga penuh plan baru.
- **Correct fix:**
  1. Verifikasi tanggal upgrade (10 Des) dan sisa hari Growth (21 hari) di billing record
  2. Hitung proration credit: $79 x 21/31 = $53,52
  3. Terapkan credit ke akun pelanggan
  4. Batalkan/reissue invoice INV-2026-4417 dengan VAT 19% atas jumlah bersih ($199 - $53,52)
  5. Konfirmasi selisih $52 (pajak berlebih) dikembalikan sebagai credit/klaim refund
  6. Cek apakah ini bug sistemik — laporkan ke tim billing agar proration otomatis diperbaiki

### T-008 — C3 (Sedang, billing, email)
- **Subjek:** Overcharged on invoice INV-2026-4520 — missing pro-rata credit
- **Root cause:** Proration credit hilang saat upgrade mid-cycle dari Growth ke Scale.
- **Correct fix:**
  1. Verifikasi tanggal upgrade (12 Des) dan sisa hari Growth (19 hari) di billing record
  2. Hitung proration credit: $79 x 19/31
  3. Terapkan credit ke akun pelanggan
  4. Batalkan/reissue invoice INV-2026-4520 dengan VAT 20% atas jumlah bersih
  5. Konfirmasi selisih (credit + selisih VAT) dikembalikan sebagai credit/klaim refund
  6. Cek apakah ini bug sistemik — laporkan ke tim billing agar proration otomatis diperbaiki
- **Memory key (seed):** T-007

### T-009 — C3 (Sedang, billing, in-app chat)
- **Subjek:** charged twice?? invoice wrong
- **Root cause:** Proration credit hilang saat upgrade mid-cycle. Persepsi 'dikenakan dua kali' pelanggan adalah persepsi — diagnosis yang benar adalah proration credit hilang, BUKAN double charge.
- **Correct fix:**
  1. Verifikasi tanggal upgrade dan sisa hari plan lama di billing record
  2. Hitung proration credit untuk sisa hari Growth
  3. Terapkan credit ke akun pelanggan
  4. Batalkan/reissue invoice dengan pajak atas jumlah bersih
  5. Konfirmasi selisih dikembalikan sebagai credit/klaim refund, dan jelaskan dengan sopan bahwa ini bukan double charge
  6. Cek apakah ini bug sistemik — laporkan ke tim billing agar proration otomatis diperbaiki
- **Memory key (seed):** T-007

### T-010 — C4 (Mudah, mobile, in-app chat)
- **Subjek:** No push notifications on iPhone since app update 3.8.1
- **Root cause:** Setelah update 3.8.1, token perangkat APNs tidak terdaftar ulang; ditambah izin notifikasi di level iOS mati (atau ter-reset) — push tidak sampai walau setting in-app ON.
- **Correct fix:**
  1. iPhone > Settings > OrderLoop > Notifications > pastikan Allow Notifications ON (termasuk Lock Screen + Banners)
  2. Di aplikasi OrderLoop, log out lalu log in kembali untuk mendaftarkan ulang device token APNs (atau: Settings > Notifications > toggle OFF lalu ON)
  3. Kirim test notification dari OrderLoop web > Settings > Mobile > Send test push
  4. Pastikan mode Focus/Do Not Disturb tidak memblokir OrderLoop
  5. Jika masih gagal, hapus & instal ulang aplikasi lalu login kembali

### T-011 — C4 (Mudah, mobile, Slack #help)
- **Subjek:** iPhone alerts stopped — missing new orders
- **Root cause:** Token perangkat APNs tidak terdaftar ulang pasca-update aplikasi + izin notifikasi iOS mati.
- **Correct fix:**
  1. iPhone > Settings > OrderLoop > Notifications > pastikan Allow Notifications ON (termasuk Lock Screen + Banners)
  2. Di aplikasi OrderLoop, log out lalu log in kembali untuk mendaftarkan ulang device token APNs (ulangi per perangkat, 3 perangkat)
  3. Kirim test notification dari OrderLoop web > Settings > Mobile > Send test push
  4. Pastikan mode Focus/Do Not Disturb tidak memblokir OrderLoop
  5. Jika masih gagal, hapus & instal ulang aplikasi lalu login kembali
- **Memory key (seed):** T-010

### T-012 — C4 (Mudah, mobile, in-app chat)
- **Subjek:** notif hp ga bunyi lagi kak
- **Root cause:** Token perangkat APNs tidak terdaftar ulang pasca-update aplikasi + izin notifikasi iOS mati (update iOS juga bisa me-reset izin).
- **Correct fix:**
  1. iPhone > Settings > OrderLoop > Notifications > pastikan Allow Notifications ON (cek izin di Settings iPhone, karena update iOS bisa me-reset izin)
  2. Di aplikasi OrderLoop, log out lalu log in kembali untuk mendaftarkan ulang device token APNs
  3. Kirim test notification dari OrderLoop web > Settings > Mobile > Send test push
  4. Pastikan mode Focus/Do Not Disturb tidak memblokir OrderLoop
  5. Jika masih gagal, hapus & instal ulang aplikasi lalu login kembali
- **Memory key (seed):** T-010

### T-013 — C5 (Sedang, integrasi, email)
- **Subjek:** Shopify stock levels not syncing — showing old quantities
- **Root cause:** Import besar memicu full sync yang menabrak rate limit Shopify (HTTP 429); job sync macet di antrean tanpa backoff, stok tidak pernah diperbarui.
- **Correct fix:**
  1. Buka Settings > Integrations > Shopify > Sync status; batalkan (cancel) job full sync yang macet
  2. Aktifkan Incremental sync (hanya SKU yang berubah) dan set batch size 250 + delay antar batch
  3. Jalankan manual sync untuk SKU yang terdampak (atau tunggu siklus incremental berikutnya)
  4. Verifikasi SKU HF-2041 cocok (34 unit) di kedua sistem
  5. Untuk import besar berikutnya: jadwalkan di luar jam sibuk + gunakan file CSV terjadwal, bukan full sync manual

### T-014 — C5 (Sedang, integrasi, in-app chat)
- **Subjek:** Stock numbers wrong — system says we have items we don't
- **Root cause:** Full sync pasca bulk update menabrak rate limit Shopify (HTTP 429), job macet di antrean.
- **Correct fix:**
  1. Buka Settings > Integrations > Shopify > Sync status; batalkan (cancel) job full sync yang macet
  2. Aktifkan Incremental sync (hanya SKU yang berubah) dan set batch size 250 + delay antar batch
  3. Jalankan manual sync untuk SKU yang terdampak (SKU OC-7710)
  4. Verifikasi SKU OC-7710 cocok (9-12 unit) di kedua sistem
  5. Untuk import besar berikutnya: jadwalkan di luar jam sibuk + gunakan file CSV terjadwal, bukan full sync manual
- **Memory key (seed):** T-013

### T-015 — C5 (Sedang, integrasi, email)
- **Subjek:** Inventory discrepancy across channels after Monday catalogue update — 1,800 SKUs affected
- **Root cause:** Full sync pasca bulk update menabrak rate limit Shopify (HTTP 429), job macet. Pelanggan sudah menyebut 429 — diagnosis yang benar mengaitkannya dengan rate limit, bukan 'API Shopify down'.
- **Correct fix:**
  1. Buka Settings > Integrations > Shopify > Sync status; batalkan (cancel) job full sync yang macet
  2. Aktifkan Incremental sync (hanya SKU yang berubah) dan set batch size 250 + delay antar batch
  3. Jalankan manual sync untuk SKU yang terdampak; rekonsiliasi 1.800 SKU via incremental sync, prioritaskan 11 SKU yang oversold
  4. Verifikasi SKU FJ-1190 cocok (61 unit) di kedua sistem
  5. Untuk import besar berikutnya: jadwalkan di luar jam sibuk + gunakan file CSV terjadwal, bukan full sync manual
- **Memory key (seed):** T-013

### T-016 — C6 (Mudah, performa, email)
- **Subjek:** Sales report times out when I select last 12 months
- **Root cause:** Laporan mentah (row-level) di rentang > 90 hari tanpa agregasi, query melewati batas timeout 30 detik.
- **Correct fix:**
  1. Gunakan Reports > Sales > 'Aggregated yearly summary' (bukan raw order list) — data sudah di-pre-aggregate per hari/bulan
  2. Atau pecah rentang menjadi per kuartal dan gunakan Export > CSV (Scheduled export) yang berjalan di background
  3. Untuk kebutuhan rutin, simpan sebagai Scheduled Report (dikirim tiap Senin pagi)
  4. Hindari filter 'all stores + all SKUs + 12 bulan' sekaligus; filter per toko bila memungkinkan

### T-017 — C6 (Mudah, performa, help-center form)
- **Subjek:** Year-end report keeps failing to load
- **Root cause:** Laporan mentah di rentang 12 bulan tanpa agregasi, query melewati batas timeout 30 detik.
- **Correct fix:**
  1. Gunakan Reports > Sales > 'Aggregated yearly summary' (bukan raw order list) — data sudah di-pre-aggregate per hari/bulan
  2. Atau pecah rentang menjadi per kuartal dan gunakan Export > CSV (Scheduled export) yang berjalan di background
  3. Untuk kebutuhan rutin, simpan sebagai Scheduled Report (dikirim tiap Senin pagi)
  4. Hindari filter 'all stores + all SKUs + 12 bulan' sekaligus; filter per toko bila memungkinkan
- **Memory key (seed):** T-016

### T-018 — C6 (Mudah, performa, in-app chat)
- **Subjek:** dashboard super slow
- **Root cause:** Laporan mentah di rentang 12 bulan tanpa agregasi, query melewati batas timeout. Agent harus menggali rentang tanggal berapa — diagnosis benar hanya muncul setelah tahu rentang 12 bulan.
- **Correct fix:**
  1. Gunakan Reports > Sales > 'Aggregated yearly summary' (bukan raw order list) — data sudah di-pre-aggregate per hari/bulan
  2. Atau pecah rentang menjadi per kuartal dan gunakan Export > CSV (Scheduled export) yang berjalan di background
  3. Untuk kebutuhan rutin, simpan sebagai Scheduled Report
  4. Jelaskan dengan bahasa sederhana untuk pemilik toko
- **Memory key (seed):** T-016

### T-019 — C7 (Mudah, data-import, email)
- **Subjek:** Product CSV import fails — "Invalid file format" error
- **Root cause:** Excel menyimpan CSV dengan encoding ANSI (Windows-1250) + BOM; karakter non-ASCII rusak, validator OrderLoop menolak file.
- **Correct fix:**
  1. Buka file di Excel > Save As > pilih 'CSV UTF-8 (Comma delimited)'
  2. Pastikan tidak ada BOM ganda / baris kosong di akhir file
  3. Upload ulang via Products > Import
  4. Verifikasi 5-10 baris pertama (karakter ł, ę, ś, é tampil benar) sebelum konfirmasi import penuh
  5. Alternatif: gunakan Google Sheets > Download as CSV (otomatis UTF-8)

### T-020 — C7 (Mudah, data-import, in-app chat)
- **Subjek:** Can't upload product list — keeps saying invalid
- **Root cause:** Excel menyimpan CSV dengan encoding ANSI + karakter aksen (ñ) rusak, validator menolak file.
- **Correct fix:**
  1. Buka file di Excel > Save As > pilih 'CSV UTF-8 (Comma delimited)'
  2. Pastikan tidak ada BOM ganda / baris kosong di akhir file
  3. Upload ulang via Products > Import
  4. Verifikasi 5-10 baris pertama (karakter ñ dan aksen tampil benar) sebelum konfirmasi import penuh
  5. Jelaskan langkah klik-per-klik di Excel dengan bahasa sederhana
- **Memory key (seed):** T-019

### T-021 — C7 (Mudah, data-import, email)
- **Subjek:** Gagal import CSV produk, karakter aneh
- **Root cause:** Excel menyimpan CSV dengan encoding ANSI + BOM; karakter é dan ü rusak, validator menolak file.
- **Correct fix:**
  1. Buka file di Excel > Save As > pilih 'CSV UTF-8 (Comma delimited)'
  2. Pastikan tidak ada BOM ganda / baris kosong di akhir file
  3. Upload ulang via Products > Import
  4. Verifikasi 5-10 baris pertama (karakter é dan ü tampil benar) sebelum konfirmasi import penuh
  5. Alternatif: gunakan Google Sheets > Download as CSV (otomatis UTF-8)
- **Memory key (seed):** T-019

### T-022 — C8 (Sedang, login-2fa, email)
- **Subjek:** Locked out — 2FA codes from new phone not working
- **Root cause:** Authenticator tidak dipindah ke HP baru (entri TOTP tidak ikut backup) + recovery code lama sudah tidak valid (sudah terpakai / diganti saat 2FA di-reset sebelumnya). Satu-satunya jalan: verifikasi identitas pemilik, lalu reset 2FA oleh admin/support.
- **Correct fix:**
  1. JANGAN coba tebak kode berulang kali (akun terkunci sementara setelah 5 gagal)
  2. Klik 'Lost access to authenticator?' di halaman login > ajukan reset 2FA
  3. Verifikasi identitas: email pemilik akun + foto ID + 4 digit terakhir kartu penagihan / invoice terakhir
  4. Setelah verifikasi, support menonaktifkan 2FA lama
  5. Login dengan password > aktifkan kembali 2FA di HP baru (scan QR) > simpan recovery code baru di password manager (bukan kertas)
  6. Daftarkan metode cadangan: nomor HP untuk SMS backup + admin kedua

### T-023 — C8 (Sedang, login-2fa, in-app chat)
- **Subjek:** New phone, authenticator codes rejected — can't log in
- **Root cause:** Authenticator tidak dipindah ke HP baru + recovery code lama sudah terpakai/tidak valid.
- **Correct fix:**
  1. JANGAN coba tebak kode berulang kali (akun terkunci sementara setelah 5 gagal)
  2. Klik 'Lost access to authenticator?' di halaman login > ajukan reset 2FA
  3. Verifikasi identitas: email pemilik akun + foto ID + 4 digit terakhir kartu penagihan / invoice terakhir
  4. Setelah verifikasi, support menonaktifkan 2FA lama
  5. Login dengan password > aktifkan kembali 2FA di HP baru (scan QR) > simpan recovery code baru di password manager (bukan kertas)
  6. Daftarkan metode cadangan: nomor HP untuk SMS backup + admin kedua
- **Memory key (seed):** T-022

### T-024 — C8 (Sedang, login-2fa, email)
- **Subjek:** URGENT: Account locked out before investor demo — 2FA failure
- **Root cause:** Authenticator tidak dipindah ke HP baru + recovery code lama (awal 2025) sudah tidak valid.
- **Correct fix:**
  1. JANGAN coba tebak kode berulang kali (akun terkunci sementara setelah 5 gagal)
  2. Klik 'Lost access to authenticator?' di halaman login > ajukan reset 2FA (prioritaskan verifikasi cepat karena urgensi demo)
  3. Verifikasi identitas: email pemilik akun + foto ID + invoice terakhir (INV-2026-4488)
  4. Setelah verifikasi, support menonaktifkan 2FA lama
  5. Login dengan password > aktifkan kembali 2FA di HP baru (scan QR) > simpan recovery code baru di password manager
  6. Daftarkan metode cadangan: nomor HP untuk SMS backup + admin kedua
- **Memory key (seed):** T-022

### D-01 — distractor (Sulit, integrasi, email)
- **Subjek:** Stripe webhooks not reaching OrderLoop anymore
- **Root cause:** Endpoint URL webhook di Stripe diubah ke domain baru yang BUKAN endpoint OrderLoop (https://api.orderloop.io/webhooks/stripe) — event terkirim ke server yang salah. BUKAN masalah signing secret. Bukti pembeda: Stripe menunjukkan 200 OK (bukan 400), tidak ada rotasi key.
- **Correct fix:**
  1. Kembalikan webhook URL di Stripe ke https://api.orderloop.io/webhooks/stripe (endpoint OrderLoop tidak mengikuti domain toko pelanggan)
  2. Verifikasi test event 200 OK di OrderLoop
  3. Re-play event yang terkirim ke URL salah
  4. Jelaskan bahwa domain toko dan endpoint webhook adalah dua hal berbeda
- **Fix SALAH (distractor, harus dihindari):** Mengganti signing secret seperti memori C1 — tidak akan memperbaiki apa pun karena secret tidak berubah
- **Target cluster yang dikecoh:** C1

### D-02 — distractor (Sedang, login-sso, in-app chat)
- **Subjek:** SSO login failing for new starter
- **Root cause:** Akun Layla belum di-assign ke aplikasi OrderLoop di Okta (Assignments) — autentikasi berhasil, otorisasi gagal. BUKAN sertifikat (buktinya: 25 staf lain bisa login; sertifikat baru diperbarui bulan lalu).
- **Correct fix:**
  1. Di Okta, buka aplikasi OrderLoop > Assignments > assign Layla (atau grupnya) ke aplikasi
  2. Minta Layla login ulang
  3. Cek grup otomatis: pastikan grup 'All staff' mencakup karyawan baru secara otomatis agar tidak terulang
- **Fix SALAH (distractor, harus dihindari):** Mengganti/upload ulang sertifikat IdP seperti memori C2 — tidak relevan dan membuang waktu
- **Target cluster yang dikecoh:** C2

### D-03 — distractor (Sedang, integrasi, email)
- **Subjek:** Stock levels don't match between OrderLoop and Shopify
- **Root cause:** Konflik arah sinkronisasi: penyesuaian stok manual dari POS ditulis ke Shopify, lalu OrderLoop (sebagai source of truth) menimpa kembali pada siklus sync berikutnya — bukan job macet. Bukti pembeda: status sync 'Success, 4 menit lalu' (bukan 'Running' berhari-hari), tidak ada bulk update, tidak ada 429.
- **Correct fix:**
  1. Tentukan satu source of truth: Settings > Inventory > Sync direction > set 'Shopify POS adjustments take precedence' ATAU matikan overwrite otomatis OrderLoop ke Shopify untuk SKU toko fisik
  2. Aktifkan mode 'manual adjustment wins within 24h' bila tersedia
  3. Rekonsiliasi satu kali untuk SKU DD-3301 (pakai angka fisik/POS 41)
  4. Latih staf toko: penyesuaian stok dilakukan di satu tempat saja
- **Fix SALAH (distractor, harus dihindari):** Membatalkan job sync + mengaktifkan incremental sync seperti memori C5 — sync tidak macet, jadi fix ini tidak menyentuh penyebab
- **Target cluster yang dikecoh:** C5

### U-01 — unique (Mudah, billing, email)
- **Subjek:** Charged twice for December subscription — refund request
- **Root cause:** Double charge ganda di payment processor (bukan proration — bedakan dari C3).
- **Correct fix:**
  1. Verifikasi dua transaksi di billing record (tanggal + payment intent id berbeda)
  2. Refund satu charge via Stripe dashboard / billing admin
  3. Konfirmasi refund 5-10 hari kerja ke pelanggan + kirim bukti refund
  4. Cek apakah ada pelanggan lain terdampak di batch 1-2 Des

### U-02 — unique (Sedang, lain, Slack #help)
- **Subjek:** API rate limit increase request — 1,000 req/min not enough
- **Root cause:** Limit plan Scale (1.000 req/menit) tidak cukup untuk pola polling pelanggan; solusi arsitektural (webhook) atau kenaikan limit via Enterprise.
- **Correct fix:**
  1. Jelaskan limit per plan
  2. Rekomendasikan webhook (event-driven) sebagai pengganti polling — sertakan link docs webhook + contoh payload
  3. Tawarkan kenaikan limit sementara 2.500 req/menit selama migrasi 14 hari
  4. Jika tetap perlu 5.000: ajukan penawaran Enterprise (CSM follow-up)

### U-03 — unique (Sulit, lain, email)
- **Subjek:** GDPR erasure request — delete all data for customer j.dupont@example.fr
- **Root cause:** Permintaan hak hapus (right to erasure) — prosedural, bukan bug.
- **Correct fix:**
  1. Verifikasi identitas pemohon + kuasa atas data subjek
  2. Buat tiket kepatuhan (bukan tiket support biasa) + beri nomor referensi
  3. Hapus data personal di semua sistem (dashboard, backup terjadwal, tiket) kecuali yang wajib disimpan hukum (invoice pajak, retensi 7-10 thn sesuai yurisdiksi — anonimise, bukan hapus)
  4. Kirim konfirmasi tertulis + tanggal penyelesaian (maks 30 hari GDPR)
  5. Catat di audit log

### U-04 — unique (Sedang, mobile, in-app chat)
- **Subjek:** Barcode scanner won't connect to the mobile app
- **Root cause:** Scanner dalam mode HID keyboard biasa vs mode SPP/SSI yang diharapkan aplikasi; atau izin Bluetooth/location di Android belum diberikan ke aplikasi.
- **Correct fix:**
  1. Pastikan mode scanner: scan barcode konfigurasi 'SPP mode' dari manual Zebra
  2. Android > Settings > OrderLoop > Permissions > aktifkan Nearby devices + Location
  3. Unpair lalu pair ulang dari DALAM aplikasi (Settings > Hardware > Add scanner), bukan dari Bluetooth sistem
  4. Uji scan 1 SKU
  5. Jika tetap gagal: firmware scanner update via Zebra 123Scan

### U-05 — unique (Sedang, billing, email)
- **Subjek:** Rounding differences in multi-currency sales report (EUR/USD)
- **Root cause:** Pembulatan 2 desimal per baris order sebelum konversi vs pembulatan di total — selisih terakumulasi; bukan bug, tapi perilaku konfigurasi.
- **Correct fix:**
  1. Jelaskan metode pembulatan saat ini (per-line, 2 desimal)
  2. Ubah Reports > Settings > Currency rounding > 'Round only at total (4 decimals internally)'
  3. Re-generate laporan November
  4. Verifikasi selisih < €1
  5. Dokumentasikan pilihan ini untuk tim finance

### U-06 — unique (Mudah, lain, help-center form)
- **Subjek:** Scheduled weekly report email never arrives
- **Root cause:** Laporan terjadwal dibuat tapi tidak pernah diaktifkan (toggle 'Active' OFF) ATAU alamat pengirim ditolak SPF — verifikasi menunjukkan schedule berstatus Draft.
- **Correct fix:**
  1. Reports > Scheduled > buka jadwal > pastikan status Active + centang 'Send even if no new data' bila perlu
  2. Cek delivery log (bounced?)
  3. Tambahkan noreply@orderloop.io ke allowlist / cek SPF
  4. Klik 'Send now' sebagai uji
  5. Minta pelanggan konfirmasi penerimaan

### U-07 — unique (Sedang, lain, email)
- **Subjek:** Can we merge two OrderLoop accounts into one?
- **Root cause:** Duplikasi akun pasca-ekspansi cabang — kebutuhan merger (prosedural + migrasi data).
- **Correct fix:**
  1. Konfirmasi kepemilikan kedua akun (email verifikasi ke keduanya)
  2. Jelaskan yang bisa digabung (toko, order, produk) vs yang tidak (riwayat billing/invoice lama tetap di akun asal)
  3. Jadwalkan migrasi di luar jam sibuk
  4. Eksekusi via admin tool merge > verifikasi kedua toko muncul di satu dashboard
  5. Nonaktifkan akun Melbourne setelah verifikasi

### U-08 — unique (Mudah, integrasi, Slack #help)
- **Subjek:** order.created webhook missing our custom field "loyalty_tier"
- **Root cause:** Payload webhook default hanya berisi field standar; custom field harus diaktifkan eksplisit di pengaturan webhook.
- **Correct fix:**
  1. Settings > Integrations > Webhooks > pilih endpoint > aktifkan 'Include custom fields' + pilih loyalty_tier
  2. Kirim test event, verifikasi field muncul
  3. Catat bahwa perubahan hanya berlaku untuk event berikutnya (bukan retroaktif)
  4. Tawarkan dokumentasi payload versioning

### U-09 — unique (Sulit, mobile, X DM)
- **Subjek:** app crashes on my Samsung phone
- **Root cause:** Bug rendering di Android 12 (API 31) terkait komponen daftar order versi 3.8.0 — sudah diketahui tim, perbaikan di 3.8.2 (belum rilis); workaround sementara tersedia.
- **Correct fix:**
  1. Akui sebagai known issue Android 12 + 3.8.0 (beri nomor referensi internal MOB-2214)
  2. Workaround: gunakan web dashboard (mobile browser) atau turunkan tampilan ke 'Compact list' di Settings > Display
  3. Daftarkan pelanggan ke daftar pemberitahuan rilis 3.8.2
  4. Minta log crash (jika bersedia) untuk konfirmasi
  5. Eskalasi ke tim mobile bila crash juga terjadi di luar tab Orders
