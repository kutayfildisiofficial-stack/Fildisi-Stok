import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone
import io
import csv
import json

# --- PostgreSQL Bağlantı Bilgileri ---
DB_URI = "postgresql://neondb_owner:npg_CuvX8ByQ5oFk@ep-cool-rain-abpiie2h-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"

def get_conn():
    return psycopg2.connect(DB_URI)

# --- Türkiye Saati Fonksiyonu ---
def get_tr_now():
    """Türkiye yerel saatini (UTC+3) döndürür."""
    return datetime.now(timezone(timedelta(hours=3)))

# --- Format Fonksiyonları ---
def safe_float(val):
    try: return float(str(val).replace(",", "."))
    except: return 0.0

def format_tl(value):
    s = f"{value:,.2f}"
    main, decimal = s.split(".")
    return f"₺{main.replace(',', '.')},{decimal}"

# --- Sayfa ve Giriş Yapılandırması ---
st.set_page_config(page_title="FİLDİŞİ GRUP - STOK TAKİP", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 GİRİŞ")
    user_entry = st.text_input("Kullanıcı Adı:", value="FLD2026")
    pass_entry = st.text_input("Şifre:", type="password")
    if st.button("Giriş Yap"):
        if user_entry == "FLD2026" and pass_entry == "18811938":
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Geçersiz kullanıcı adı veya şifre!")
    st.caption("Copyright © 2026 - Kutay Fildişi - Tüm hakları saklıdır.")
    st.stop()

# --- ANA UYGULAMA ---
st.subheader("STOK YÖNETİM PANELİ")

tab_stok, tab_yonetim, tab_rapor, tab_gecmis, tab_yedek = st.tabs([
    "📦 STOK GİRİŞ/ÇIKIŞ", 
    "⚙️ ÜRÜN/KALİBRE TANIMLARI", 
    "📊 RAPORLAR", 
    "📜 HAREKET GEÇMİŞİ", 
    "💾 YEDEK"
])

# Veri Çekme
conn = get_conn()
df_urun = pd.read_sql("SELECT id, ad FROM urun ORDER BY ad", conn)
df_kalibre = pd.read_sql("SELECT u.ad as u_ad, k.kalibre, k.glaze, k.satis_fiyati, k.id as k_id FROM kalibre k JOIN urun u ON u.id=k.urun_id ORDER BY u.ad", conn)
df_stok = pd.read_sql("""SELECT u.ad, k.kalibre, k.glaze, SUM(l.kalan_kg) as kg, SUM(l.kalan_palet) as palet, k.satis_fiyati, k.id as k_id
                         FROM lot l JOIN kalibre k ON k.id=l.kalibre_id JOIN urun u ON u.id=k.urun_id
                         GROUP BY k.id, u.ad, k.kalibre, k.glaze, k.satis_fiyati
                         HAVING SUM(l.kalan_kg) > 0 OR SUM(l.kalan_palet) > 0 ORDER BY u.ad DESC""", conn)
conn.close()

kalibre_listesi = [f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}" for _, r in df_kalibre.iterrows()]
kalibre_dict = {f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}": r['k_id'] for _, r in df_kalibre.iterrows()}

# ==========================================
# TAB 1: STOK GİRİŞ / ÇIKIŞ & TABLO
# ==========================================
with tab_stok:
    c1, c2, c3, c4 = st.columns([3, 1, 1, 3])
    secili_kalibre = c1.selectbox("Ürün Seç:", kalibre_listesi, key="islem_sec")
    islem_kg = c2.text_input("Miktar(KG):")
    islem_palet = c3.text_input("Palet:")
    islem_aciklama = c4.text_input("Açıklama:")

    col_g, col_c = st.columns(2)
    
    def hareket(tip):
        kg = safe_float(islem_kg); palet = safe_float(islem_palet); aciklama = islem_aciklama.strip()
        if not secili_kalibre or (kg <= 0 and palet <= 0): return
        k_id = kalibre_dict[secili_kalibre]
        tarih, saat = get_tr_now().strftime("%d-%m-%Y"), get_tr_now().strftime("%H:%M:%S")
        
        c = get_conn(); cursor = c.cursor()
        if tip == "Giriş":
            cursor.execute("INSERT INTO lot(kalibre_id, giris_kg, kalan_kg, giris_palet, kalan_palet, tarih) VALUES(%s,%s,%s,%s,%s,%s)", (k_id, kg, kg, palet, palet, tarih))
        else:
            cursor.execute("SELECT SUM(kalan_kg), SUM(kalan_palet) FROM lot WHERE kalibre_id=%s", (k_id,))
            res = cursor.fetchone()
            if kg > (res[0] or 0) or palet > (res[1] or 0):
                st.error("Yetersiz Stok!"); return
            for alan, miktar in [("kalan_kg", kg), ("kalan_palet", palet)]:
                kalan_miktar = miktar
                cursor.execute(f"SELECT id, {alan} FROM lot WHERE kalibre_id=%s AND {alan}>0 ORDER BY id DESC", (k_id,))
                for l_id, l_val in cursor.fetchall():
                    if kalan_miktar <= 0: break
                    dus = min(l_val, kalan_miktar)
                    cursor.execute(f"UPDATE lot SET {alan}={alan}-%s WHERE id=%s", (dus, l_id))
                    kalan_miktar -= dus
        
        cursor.execute("INSERT INTO stok_hareket(kalibre_id, tip, kg, palet, tarih, saat, aciklama) VALUES(%s,%s,%s,%s,%s,%s,%s)", (k_id, tip, kg, palet, tarih, saat, aciklama))
        c.commit(); c.close(); st.success(f"{tip} Başarılı!"); st.rerun()

    if col_g.button("📥 GİRİŞ", use_container_width=True): hareket("Giriş")
    if col_c.button("📤 ÇIKIŞ", use_container_width=True): hareket("Çıkış")

    st.divider()
    st.subheader("GÜNCEL STOK DURUMU (KDV Hariçtir)")
    display_data = []
    t_kg, t_palet, t_val = 0, 0, 0
    for _, r in df_stok.iterrows():
        kg, palet, fiyat = r['kg'] or 0, r['palet'] or 0, r['satis_fiyati'] or 0
        val = kg * fiyat
        t_kg += kg; t_palet += palet; t_val += val
        detay = f"{r['ad']} {r['kalibre']} (%{r['glaze']})"
        display_data.append([detay, int(kg), int(palet), format_tl(fiyat), format_tl(val)])
    
    st.dataframe(pd.DataFrame(display_data, columns=["ÜRÜN DETAYI", "STOK (KG)", "PALET", "BİRİM FİYAT", "TOPLAM DEĞER"]), use_container_width=True, hide_index=True)

# ==========================================
# TAB 2: ÜRÜN & KALİBRE YÖNETİMİ
# ==========================================
with tab_yonetim:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("ÜRÜN YÖNETİMİ")
        yeni_urun = st.text_input("Yeni Ürün Ekle:")
        if st.button("➕ Ürün Ekle"):
            if yeni_urun.strip():
                try:
                    c = get_conn(); cur = c.cursor()
                    cur.execute("INSERT INTO urun(ad) VALUES(%s)", (yeni_urun.strip(),))
                    c.commit(); c.close(); st.success("Ürün eklendi!"); st.rerun()
                except: st.error("Bu ürün zaten mevcut.")
        
        st.divider()
        # ÜRÜN İSMİ DÜZENLEME BÖLÜMÜ
        st.write("📝 **Ürün İsmi Düzenle**")
        duzenle_sec = st.selectbox("Düzenlenecek Ürün:", df_urun['ad'].tolist() if not df_urun.empty else [], key="edit_urun_sec")
        yeni_isim = st.text_input("Yeni İsim:", key="edit_urun_name")
        if st.button("💾 İsmi Güncelle"):
            if duzenle_sec and yeni_isim.strip():
                c = get_conn(); cur = c.cursor()
                cur.execute("UPDATE urun SET ad=%s WHERE ad=%s", (yeni_isim.strip(), duzenle_sec))
                c.commit(); c.close(); st.success("Ürün ismi güncellendi!"); st.rerun()

        st.divider()
        sil_urun = st.selectbox("❌ Silinecek Ürün:", df_urun['ad'].tolist() if not df_urun.empty else [])
        if st.button("Seçili Ürünü Sil"):
            if sil_urun:
                c = get_conn(); cur = c.cursor()
                cur.execute("DELETE FROM urun WHERE ad=%s", (sil_urun,))
                c.commit(); c.close(); st.warning("Silindi!"); st.rerun()

    with c2:
        st.subheader("KALİBRE & GLAZE TANIMLA")
        sec_urun_k = st.selectbox("Ürün Seç:", df_urun['ad'].tolist() if not df_urun.empty else [], key="k_ekle_urun")
        ekle_kalibre = st.text_input("Kalibre:")
        ekle_glaze = st.text_input("Glaze (%):")
        ekle_fiyat = st.text_input("Birim Fiyat:")
        if st.button("Tanımla"):
            if sec_urun_k and ekle_kalibre.strip() and ekle_glaze.strip():
                f = safe_float(ekle_fiyat); c = get_conn(); cur = c.cursor()
                cur.execute("SELECT id FROM urun WHERE ad=%s", (sec_urun_k,))
                u_id = cur.fetchone()[0]
                cur.execute("INSERT INTO kalibre(urun_id, kalibre, glaze, satis_fiyati) VALUES(%s,%s,%s,%s)", (u_id, ekle_kalibre.strip(), ekle_glaze.strip(), f))
                c.commit(); c.close(); st.success("Tanımlandı!"); st.rerun()

    st.divider()
    st.subheader("TANIM YÖNETİMİ (SİL / FİYAT GÜNCELLE)")
    yonet_kalibre = st.selectbox("Tanım Seç:", kalibre_listesi, key="y_k_sec")
    col_sil, col_fiyat, col_btn = st.columns([2, 2, 2])
    if col_sil.button("❌ Seçili Tanımı Sil", use_container_width=True):
        if yonet_kalibre:
            k_id = kalibre_dict[yonet_kalibre]; c = get_conn(); cur = c.cursor()
            cur.execute("DELETE FROM kalibre WHERE id=%s", (k_id,))
            c.commit(); c.close(); st.warning("Tanım Silindi!"); st.rerun()
    
    guncel_fiyat = col_fiyat.text_input("Yeni Fiyat:", key="g_fiyat")
    if col_btn.button("💰 Fiyatı Güncelle", use_container_width=True):
        yeni_f = safe_float(guncel_fiyat)
        if yonet_kalibre and yeni_f > 0:
            k_id = kalibre_dict[yonet_kalibre]; c = get_conn(); cur = c.cursor()
            cur.execute("UPDATE kalibre SET satis_fiyati=%s WHERE id=%s", (yeni_f, k_id))
            c.commit(); c.close(); st.success("Fiyat Güncellendi!"); st.rerun()

# ==========================================
# TAB 3: RAPORLAR
# ==========================================
with tab_rapor:
    # CSV Rapor
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["ÜRÜN DETAYI", "STOK (KG)", "PALET", "TOPLAM DEĞER (KDV HARİÇTİR)"])
    for row in display_data:
        # Excel'in KG'yi 1.000 -> 1 yapmaması için doğrudan sayı yazıyoruz
        writer.writerow([row[0], row[1], row[2], row[4]])
    writer.writerow([])
    writer.writerow(["TOPLAM", int(t_kg), int(t_palet), format_tl(t_val)])
    
    st.download_button("📊 EKSTRE (CSV) İNDİR", data=output.getvalue().encode('utf-8-sig'), file_name=f"Fildisi_Stok_Rapor_{get_tr_now().strftime('%d_%m_%Y')}.csv", mime="text/csv")
    
    if st.button("📄 EKSTRE (EKRAN) GÖRÜNTÜLE"):
        rapor_metni = f"{'ÜRÜN DETAYI':<40} | {'STOK (KG)':>12} | {'PALET':>6} | {'TOPLAM DEĞER':>18}\n"
        rapor_metni += "-"*85 + "\n"
        for row in display_data:
            # Ekranda binlik ayırıcı için nokta formatı
            kg_formatli = f"{row[1]:,.0f}".replace(",", ".")
            rapor_metni += f"{row[0][:40]:<40} | {kg_formatli:>12} | {row[2]:>6} | {row[4]:>18}\n"
        rapor_metni += "-"*85 + "\n"
        rapor_metni += f"{'TOPLAM (KDV HARİÇTİR)':<40} | {f'{t_kg:,.0f}'.replace(',', '.'):>12} | {int(t_palet):>6} | {format_tl(t_val):>18}"
        st.code(rapor_metni, language="text")

# ==========================================
# TAB 4: STOK HAREKET GEÇMİŞİ
# ==========================================
with tab_gecmis:
    st.subheader("📜 STOK HAREKET GEÇMİŞİ")
    c = get_conn()
    h_df = pd.read_sql("""SELECT h.id, u.ad, k.kalibre, k.glaze, h.tip, h.kg, h.palet, h.tarih, h.saat, h.aciklama 
                          FROM stok_hareket h JOIN kalibre k ON k.id=h.kalibre_id JOIN urun u ON u.id=k.urun_id ORDER BY h.id DESC""", c)
    c.close()
    
    if not h_df.empty:
        h_df_disp = pd.DataFrame()
        h_df_disp["ÜRÜN BİLGİSİ"] = h_df.apply(lambda r: f"{r['ad']} {r['kalibre']} (%{r['glaze']})", axis=1)
        h_df_disp["TİP"] = h_df["tip"]
        h_df_disp["KG"] = h_df["kg"].map(lambda x: f"{x:,.0f}".replace(",", "."))
        h_df_disp["PALET"] = h_df["palet"].astype(int)
        h_df_disp["TARİH"] = h_df["tarih"]
        h_df_disp["SAAT"] = h_df["saat"]
        h_df_disp["AÇIKLAMA"] = h_df["aciklama"]
        
        st.dataframe(h_df_disp, use_container_width=True, hide_index=True)
        
        st.divider()
        st.subheader("↩️ İşlem Geri Al")
        undo_map = {f"ID: {r['id']} | {r['ad']} {r['kalibre']} ({r['tip']})": r['id'] for _, r in h_df.iterrows()}
        secili_label = st.selectbox("Geri Alınacak İşlemi Seçin:", list(undo_map.keys()))
        if st.button("↩️ SEÇİLİ İŞLEMİ GERİ AL"):
            sid = undo_map[secili_label]
            try:
                c = get_conn(); cur = c.cursor()
                cur.execute("SELECT kalibre_id, tip, kg, palet FROM stok_hareket WHERE id=%s", (sid,))
                k_id, tip, kg, palet = cur.fetchone()
                if tip == "Giriş":
                    cur.execute("DELETE FROM lot WHERE id = (SELECT id FROM lot WHERE kalibre_id=%s AND giris_kg=%s ORDER BY id DESC LIMIT 1)", (k_id, kg))
                else:
                    cur.execute("UPDATE lot SET kalan_kg = kalan_kg + %s, kalan_palet = kalan_palet + %s WHERE id = (SELECT id FROM lot WHERE kalibre_id=%s ORDER BY id DESC LIMIT 1)", (kg, palet, k_id))
                cur.execute("DELETE FROM stok_hareket WHERE id=%s", (sid,))
                c.commit(); c.close(); st.success("İşlem geri alındı!"); st.rerun()
            except Exception as e: st.error(f"Hata: {e}")

# ==========================================
# TAB 5: YEDEK
# ==========================================
with tab_yedek:
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 YEDEK OLUŞTUR (JSON)"):
            c = get_conn(); cur = c.cursor(); yedek = {}
            for t in ["urun", "kalibre", "lot", "stok_hareket"]:
                cur.execute(f"SELECT * FROM {t}"); cols = [d[0] for d in cur.description]
                yedek[t] = [dict(zip(cols, row)) for row in cur.fetchall()]
            c.close()
            st.download_button("Dosyayı İndir", data=json.dumps(yedek, ensure_ascii=False, indent=4, default=str), file_name=f"Yedek_{get_tr_now().strftime('%Y%m%d_%H%M')}.json")
    with c2:
        st.warning("Geri yükleme mevcut tüm verileri siler!")
        f = st.file_uploader("Yedek Dosyası Seç:", type=['json'])
        if f and st.button("📥 VERİLERİ GERİ YÜKLE"):
            try:
                data = json.load(f); c = get_conn(); cur = c.cursor()
                for t in ["stok_hareket", "lot", "kalibre", "urun"]: cur.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
                for r in data.get("urun", []): cur.execute("INSERT INTO urun (id, ad) VALUES (%s, %s)", (r['id'], r['ad']))
                for r in data.get("kalibre", []): cur.execute("INSERT INTO kalibre (id, urun_id, kalibre, glaze, satis_fiyati) VALUES (%s, %s, %s, %s, %s)", (r['id'], r['urun_id'], r['kalibre'], r['glaze'], r['satis_fiyati']))
                for r in data.get("lot", []): cur.execute("INSERT INTO lot (id, kalibre_id, giris_kg, kalan_kg, giris_palet, kalan_palet, tarih) VALUES (%s, %s, %s, %s, %s, %s, %s)", (r['id'], r['kalibre_id'], r['giris_kg'], r['kalan_kg'], r['giris_palet'], r['kalan_palet'], r['tarih']))
                for r in data.get("stok_hareket", []): cur.execute("INSERT INTO stok_hareket (id, kalibre_id, tip, kg, palet, tarih, saat, aciklama) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (r['id'], r['kalibre_id'], r['tip'], r['kg'], r['palet'], r['tarih'], r['saat'], r['aciklama']))
                c.commit(); c.close(); st.success("Geri yüklendi!"); st.rerun()
            except Exception as e: st.error(f"Hata: {e}")

st.caption("Copyright © 2026 - Kutay Fildişi - Tüm hakları saklıdır.")
