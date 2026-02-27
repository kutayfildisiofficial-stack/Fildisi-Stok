import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone # timedelta ve timezone eklendi
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

# --- Format Fonksiyonları (Birebir Aynı) ---
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

# --- ANA UYGULAMA (GİRİŞ BAŞARILI) ---
st.subheader("STOK YÖNETİM PANELİ")

# Tüm Sekmeler
tab_stok, tab_yonetim, tab_rapor, tab_gecmis, tab_yedek = st.tabs([
    "📦 STOK GİRİŞ/ÇIKIŞ", 
    "⚙️ ÜRÜN/KALİBRE TANIMLARI", 
    "📊 RAPORLAR", 
    "📜 HAREKET GEÇMİŞİ", 
    "💾 YEDEK"
])

# Veri Çekme İşlemleri
conn = get_conn()
df_urun = pd.read_sql("SELECT id, ad FROM urun ORDER BY ad", conn)
df_kalibre = pd.read_sql("SELECT u.ad as u_ad, k.kalibre, k.glaze, k.satis_fiyati, k.id as k_id FROM kalibre k JOIN urun u ON u.id=k.urun_id ORDER BY u.ad", conn)
df_stok = pd.read_sql("""SELECT u.ad, k.kalibre, k.glaze, SUM(l.kalan_kg) as kg, SUM(l.kalan_palet) as palet, k.satis_fiyati, k.id as k_id
                         FROM lot l JOIN kalibre k ON k.id=l.kalibre_id JOIN urun u ON u.id=k.urun_id
                         GROUP BY k.id, u.ad, k.kalibre, k.glaze, k.satis_fiyati
                         HAVING SUM(l.kalan_kg) > 0 OR SUM(l.kalan_palet) > 0 ORDER BY u.ad DESC""", conn)
conn.close()

# Ortak Liste Formatları
urun_listesi = df_urun['ad'].tolist() if not df_urun.empty else []
kalibre_listesi = [f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}" for _, r in df_kalibre.iterrows()]
kalibre_dict = {f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}": r['k_id'] for _, r in df_kalibre.iterrows()}


# ==========================================
# TAB 1: STOK GİRİŞ / ÇIKIŞ İŞLEMLERİ & TABLO
# ==========================================
with tab_stok:
    c1, c2, c3, c4 = st.columns([3, 1, 1, 3])
    secili_kalibre = c1.selectbox("Ürün:", kalibre_listesi, key="islem_sec")
    islem_kg = c2.text_input("Miktar(KG):")
    islem_palet = c3.text_input("Palet:")
    islem_aciklama = c4.text_input("Açıklama:")

    col_g, col_c = st.columns(2)
    
    # HAREKET FONKSİYONU
    def hareket(tip):
        kg = safe_float(islem_kg)
        palet = safe_float(islem_palet)
        aciklama = islem_aciklama.strip()
        if not secili_kalibre or (kg <= 0 and palet <= 0): return
        
        k_id = kalibre_dict[secili_kalibre]
        # Zaman Türkiye saati olarak ayarlandı
        tarih, saat = get_tr_now().strftime("%d-%m-%Y"), get_tr_now().strftime("%H:%M:%S")
        
        c = get_conn(); cursor = c.cursor()
        if tip == "Giriş":
            cursor.execute("INSERT INTO lot(kalibre_id, giris_kg, kalan_kg, giris_palet, kalan_palet, tarih) VALUES(%s,%s,%s,%s,%s,%s)", (k_id, kg, kg, palet, palet, tarih))
        else:
            cursor.execute("SELECT SUM(kalan_kg), SUM(kalan_palet) FROM lot WHERE kalibre_id=%s", (k_id,))
            res = cursor.fetchone()
            if kg > (res[0] or 0) or palet > (res[1] or 0):
                st.error("Yetersiz Stok!")
                return
            
            for alan, miktar in [("kalan_kg", kg), ("kalan_palet", palet)]:
                kalan = miktar
                cursor.execute(f"SELECT id, {alan} FROM lot WHERE kalibre_id=%s AND {alan}>0 ORDER BY id DESC", (k_id,))
                for l_id, l_val in cursor.fetchall():
                    if kalan <= 0: break
                    dus = min(l_val, kalan)
                    cursor.execute(f"UPDATE lot SET {alan}={alan}-%s WHERE id=%s", (dus, l_id))
                    kalan -= dus
                    
        cursor.execute("INSERT INTO stok_hareket(kalibre_id, tip, kg, palet, tarih, saat, aciklama) VALUES(%s,%s,%s,%s,%s,%s,%s)", (k_id, tip, kg, palet, tarih, saat, aciklama))
        c.commit(); c.close()
        st.success(f"{tip} Başarılı!"); st.rerun()

    if col_g.button("📥 Stok Giriş", use_container_width=True): hareket("Giriş")
    if col_c.button("📤 Stok Çıkış", use_container_width=True): hareket("Çıkış")

    st.divider()
    
    # STOK TABLOSU
st.subheader("GÜNCEL STOK DURUMU")
display_data = []
t_kg, t_palet, t_val = 0, 0, 0

for _, r in df_stok.iterrows():
    # Verileri güvenli bir şekilde alalım
    kg = r['kg'] or 0
    palet = r['palet'] or 0
    fiyat = r['satis_fiyati'] or 0
    val = kg * fiyat
    
    # Toplamları hesaplayalım
    t_kg += kg
    t_palet += palet
    t_val += val
    
    # İstediğin birleşik format: ÜRÜN ADI - KALİBRE (%GLAZE)
    urun_detay = f"{r['ad']} - {r['kalibre']} (%{r['glaze']})"
    
    # Yeni sütun yapısına göre veriyi listeye ekle
    display_data.append([
        urun_detay, 
        f"{kg:,.0f}".replace(",", "."), 
        int(palet), 
        format_tl(fiyat), 
        format_tl(val)
    ])

# Tabloyu oluştururken sütun başlıklarını da güncelliyoruz
df_final = pd.DataFrame(
    display_data, 
    columns=["ÜRÜN DETAY", "STOK (KG)", "PALET", "BİRİM FİYAT", "TOPLAM DEĞER"]
)

st.dataframe(df_final, use_container_width=True, hide_index=True)"]), use_container_width=True)


# ==========================================
# TAB 2: ÜRÜN & KALİBRE YÖNETİMİ
# ==========================================
with tab_yonetim:
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("ÜRÜN YÖNETİMİ")
        yeni_urun = st.text_input("Yeni Ürün Adı:")
        if st.button("Ürün Ekle"):
            if yeni_urun.strip():
                try:
                    c = get_conn(); cur = c.cursor()
                    cur.execute("INSERT INTO urun(ad) VALUES(%s)", (yeni_urun.strip(),))
                    c.commit(); c.close(); st.success("Ürün eklendi!"); st.rerun()
                except: st.error("Bu ürün zaten mevcut.")
        
        sil_urun = st.selectbox("Ürün Seç:", urun_listesi)
        if st.button("❌ Seçili Ürünü Sil"):
            if sil_urun:
                c = get_conn(); cur = c.cursor()
                cur.execute("DELETE FROM urun WHERE ad=%s", (sil_urun,))
                c.commit(); c.close(); st.warning("Silindi!"); st.rerun()

    with c2:
        st.subheader("KALİBRE & GLAZE TANIMLARI")
        sec_urun_k = st.selectbox("Ürün Seç:", urun_listesi, key="k_ekle_urun")
        ekle_kalibre = st.text_input("Kalibre:")
        ekle_glaze = st.text_input("Glaze (%):")
        ekle_fiyat = st.text_input("Fiyat:")
        
        if st.button("Kalibre/Glaze Ekle"):
            if sec_urun_k and ekle_kalibre.strip() and ekle_glaze.strip():
                f = safe_float(ekle_fiyat)
                c = get_conn(); cur = c.cursor()
                cur.execute("SELECT id FROM urun WHERE ad=%s", (sec_urun_k,))
                u_id = cur.fetchone()[0]
                cur.execute("INSERT INTO kalibre(urun_id, kalibre, glaze, satis_fiyati) VALUES(%s,%s,%s,%s)", (u_id, ekle_kalibre.strip(), ekle_glaze.strip(), f))
                c.commit(); c.close(); st.success("Eklendi!"); st.rerun()

    st.divider()
    st.subheader("TANIM SİLME & FİYAT GÜNCELLEME")
    yonet_kalibre = st.selectbox("Ürün-Kalibre-Glaze Seç:", kalibre_listesi, key="y_k_sec")
    
    col_sil, col_fiyat, col_btn = st.columns([2, 2, 2])
    if col_sil.button("❌ Seçili Tanımı Sil", use_container_width=True):
        if yonet_kalibre:
            k_id = kalibre_dict[yonet_kalibre]
            c = get_conn(); cur = c.cursor()
            cur.execute("DELETE FROM kalibre WHERE id=%s", (k_id,))
            c.commit(); c.close(); st.warning("Tanım Silindi!"); st.rerun()
            
    guncel_fiyat = col_fiyat.text_input("Yeni Fiyat:", key="g_fiyat")
    if col_btn.button("💰 Fiyatı Güncelle", use_container_width=True):
        yeni_f = safe_float(guncel_fiyat)
        if yonet_kalibre and yeni_f > 0:
            k_id = kalibre_dict[yonet_kalibre]
            c = get_conn(); cur = c.cursor()
            cur.execute("UPDATE kalibre SET satis_fiyati=%s WHERE id=%s", (yeni_f, k_id))
            c.commit(); c.close(); st.success("Fiyat Güncellendi!"); st.rerun()


# ==========================================
# TAB 3: RAPORLAR (EKSTRE EKRAN VE CSV)
# ==========================================
with tab_rapor:
    st.subheader("📄 EKSTRELER")
    
    # CSV Rapor
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["ÜRÜN ADI", "KALİBRE", "GLAZE", "STOK (KG)", "PALET", "TOPLAM DEĞER"])
    for row in display_data:
        writer.writerow([row[0], row[1], row[2], row[3], row[4], row[6]])
    writer.writerow([])
    writer.writerow(["TOPLAM", "", "", f"{t_kg:,.0f}".replace(",", "."), int(t_palet), format_tl(t_val)])
    
    # Dosya ismine Türkiye saati eklendi
    st.download_button("📊 EKSTRE (CSV)", data=output.getvalue().encode('utf-8-sig'), file_name=f"Fildisi_Stok_Rapor_{get_tr_now().strftime('%d_%m_%Y')}.csv", # get_tr_now eklendi
            mime="text/csv",
                      )
    
    st.write("")
    # Ekran Rapor
    if st.button("📄 EKSTRE (EKRAN)"):
        rapor_metni = f"{'ÜRÜN ADI':<20} | {'KALİBRE':<10} | {'GLAZE':<6} | {'STOK (KG)':>12} | {'PALET':>6} | {'TOPLAM DEĞER':>18}\n"
        rapor_metni += "-"*105 + "\n"
        
        for _, r in df_stok.iterrows():
            kg, palet, fiy = r['kg'] or 0, r['palet'] or 0, r['satis_fiyati'] or 0
            val = kg * fiy
            satir = f"{r['ad'][:20]:<20} | {r['kalibre']:<10} | %{r['glaze']:<5} | {kg:>12,.0f} | {int(palet):>6} | {format_tl(val):>18}\n".replace(",", ".")
            rapor_metni += satir
            
        rapor_metni += "-"*105 + "\n"
        rapor_metni += f"{'TOPLAM':<41} | {t_kg:>12,.0f} | {int(t_palet):>6} | {format_tl(t_val):>18}".replace(",", ".")
        
        st.code(rapor_metni, language="text")


# ==========================================
# TAB 4: STOK HAREKET GEÇMİŞİ & GERİ AL
# ==========================================
with tab_gecmis:
    st.subheader("STOK HAREKET GEÇMİŞİ")
    c = get_conn()
    h_df = pd.read_sql("""SELECT h.id as "ID", u.ad as "ÜRÜN ADI", k.kalibre as "KALİBRE", k.glaze as "GLAZE", 
                          h.tip as "TİP", h.kg as "STOK (KG)", h.palet as "PALET", h.tarih as "TARİH", h.saat as "SAAT", h.aciklama as "AÇIKLAMA"
                          FROM stok_hareket h JOIN kalibre k ON k.id=h.kalibre_id JOIN urun u ON u.id=k.urun_id ORDER BY h.id DESC""", c)
    c.close()
    
    h_df_disp = h_df.copy()
    h_df_disp["GLAZE"] = h_df_disp["GLAZE"].map(lambda x: f"%{x}")
    h_df_disp["STOK (KG)"] = h_df_disp["STOK (KG)"].map(lambda x: f"{x:,.0f}".replace(",", "."))
    st.dataframe(h_df_disp, use_container_width=True)
    
    st.divider()
    st.subheader("İşlem Geri Al (Undo)")
    secili_id = st.selectbox("Geri Alınacak İşlemin ID'sini Seçin:", h_df["ID"].tolist() if not h_df.empty else [])
    
    if st.button("↩️ SEÇİLİ İŞLEMİ GERİ AL"):
        if secili_id:
            try:
                c = get_conn(); cur = c.cursor()
                cur.execute("SELECT kalibre_id, tip, kg, palet FROM stok_hareket WHERE id=%s", (secili_id,))
                res = cur.fetchone()
                if res:
                    k_id, tip, kg, palet = res
                    if tip == "Giriş":
                        cur.execute("DELETE FROM lot WHERE id = (SELECT id FROM lot WHERE kalibre_id=%s AND giris_kg=%s ORDER BY id DESC LIMIT 1)", (k_id, kg))
                    else:
                        cur.execute("UPDATE lot SET kalan_kg = kalan_kg + %s, kalan_palet = kalan_palet + %s WHERE id = (SELECT id FROM lot WHERE kalibre_id=%s ORDER BY id DESC LIMIT 1)", (kg, palet, k_id))
                    
                    cur.execute("DELETE FROM stok_hareket WHERE id=%s", (secili_id,))
                    c.commit(); c.close(); st.success(f"{secili_id} nolu işlem geri alındı."); st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")


# ==========================================
# TAB 5: TÜM VERİLERİ YEDEKLE / YÜKLE
# ==========================================
with tab_yedek:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("💾 TÜM VERİLERİ YEDEKLE")
        if st.button("Yedek Oluştur (JSON)"):
            c = get_conn(); cur = c.cursor()
            yedek_verisi = {}
            for tablo in ["urun", "kalibre", "lot", "stok_hareket"]:
                cur.execute(f"SELECT * FROM {tablo}")
                cols = [desc[0] for desc in cur.description]
                yedek_verisi[tablo] = [dict(zip(cols, row)) for row in cur.fetchall()]
            c.close()
            
            j_data = json.dumps(yedek_verisi, ensure_ascii=False, indent=4, default=str)
            # Dosya ismine Türkiye saati eklendi
            dosya_adi = f"Fildisi_Grup_Yedek_{get_tr_now().strftime('%Y%m%d_%H%M')}.json"
            st.download_button("Dosyayı İndir", data=j_data, file_name=dosya_adi, mime="application/json")

    with c2:
        st.subheader("📥 YEDEKLENEN VERİLERİ GERİ YÜKLE")
        st.warning("KRİTİK UYARI: Bu işlem mevcut TÜM verilerinizi silecek!")
        yuklenen_dosya = st.file_uploader("JSON Yedek Dosyasını Seçin", type=['json'])
        if yuklenen_dosya is not None:
            if st.button("Verileri Geri Yükle"):
                try:
                    yedek = json.load(yuklenen_dosya)
                    c = get_conn(); cur = c.cursor()
                    
                    for tablo in ["stok_hareket", "lot", "kalibre", "urun"]:
                        cur.execute(f"TRUNCATE TABLE {tablo} RESTART IDENTITY CASCADE")
                    
                    for r in yedek.get("urun", []):
                        cur.execute("INSERT INTO urun (id, ad) VALUES (%s, %s)", (r['id'], r['ad']))
                        
                    for r in yedek.get("kalibre", []):
                        cur.execute("INSERT INTO kalibre (id, urun_id, kalibre, glaze, satis_fiyati) VALUES (%s, %s, %s, %s, %s)", 
                                    (r['id'], r['urun_id'], r['kalibre'], r['glaze'], r['satis_fiyati']))
                        
                    for r in yedek.get("lot", []):
                        cur.execute("INSERT INTO lot (id, kalibre_id, giris_kg, kalan_kg, giris_palet, kalan_palet, tarih) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                                    (r['id'], r['kalibre_id'], r['giris_kg'], r['kalan_kg'], r['giris_palet'], r['kalan_palet'], r['tarih']))
                        
                    for r in yedek.get("stok_hareket", []):
                        cur.execute("INSERT INTO stok_hareket (id, kalibre_id, tip, kg, palet, tarih, saat, aciklama) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", 
                                    (r['id'], r['kalibre_id'], r['tip'], r['kg'], r['palet'], r['tarih'], r['saat'], r['aciklama']))
                        
                    c.commit(); c.close(); st.success("Veriler başarıyla geri yüklendi!"); st.rerun()
                except Exception as e:
                    st.error(f"Geri Yükleme Hatası: {e}")







