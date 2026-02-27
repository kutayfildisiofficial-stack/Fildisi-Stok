import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone
import io
import csv
import json

# --- PostgreSQL Bağlantı Bilgisi ---
DB_URI = "postgresql://neondb_owner:npg_CuvX8ByQ5oFk@ep-cool-rain-abpiie2h-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"

def get_conn():
    return psycopg2.connect(DB_URI)

# --- Yardımcı Fonksiyonlar ---
def get_tr_now():
    """Türkiye yerel saatini (UTC+3) döndürür."""
    return datetime.now(timezone(timedelta(hours=3)))

def safe_float(val):
    try: return float(str(val).replace(",", "."))
    except: return 0.0

def format_tl(value):
    s = f"{value:,.2f}"
    main, decimal = s.split(".")
    return f"₺{main.replace(',', '.')},{decimal}"

# --- Sayfa Yapılandırması ---
st.set_page_config(page_title="FİLDİŞİ GRUP - STOK TAKİP", layout="wide")

# --- Giriş Kontrolü ---
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

# --- VERİ ÇEKME ---
try:
    conn = get_conn()
    df_urun = pd.read_sql("SELECT id, ad FROM urun ORDER BY ad", conn)
    df_kalibre = pd.read_sql("SELECT u.ad as u_ad, k.kalibre, k.glaze, k.satis_fiyati, k.id as k_id FROM kalibre k JOIN urun u ON u.id=k.urun_id ORDER BY u.ad", conn)
    # Ham stok verisi
    df_stok_raw = pd.read_sql("""
        SELECT u.ad, k.kalibre, k.glaze, SUM(l.kalan_kg) as kg, SUM(l.kalan_palet) as palet, k.satis_fiyati, k.id as k_id
        FROM lot l 
        JOIN kalibre k ON k.id=l.kalibre_id 
        JOIN urun u ON u.id=k.urun_id
        GROUP BY k.id, u.ad, k.kalibre, k.glaze, k.satis_fiyati
        HAVING SUM(l.kalan_kg) > 0 OR SUM(l.kalan_palet) > 0 
        ORDER BY u.ad DESC
    """, conn)
    conn.close()
except Exception as e:
    st.error(f"Veritabanı Hatası: {e}")
    st.stop()

# --- Listeler ve Sözlükler ---
urun_listesi = df_urun['ad'].tolist() if not df_urun.empty else []
kalibre_listesi = [f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}" for _, r in df_kalibre.iterrows()]
kalibre_dict = {f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}": r['k_id'] for _, r in df_kalibre.iterrows()}

# --- Veri Hazırlama (Tablo ve Rapor İçin Ortak) ---
display_data = []
t_kg, t_palet, t_val = 0, 0, 0
for _, r in df_stok_raw.iterrows():
    kg, palet, fiy = r['kg'] or 0, r['palet'] or 0, r['satis_fiyati'] or 0
    val = kg * fiy
    t_kg += kg; t_palet += palet; t_val += val
    
    # Görseldeki "Ürün - Kalibre (%Glaze)" formatı
    detay = f"{r['ad']} - {r['kalibre']} (%{r['glaze']})"
    display_data.append([
        detay, 
        f"{kg:,.0f}".replace(",", "."), 
        int(palet), 
        format_tl(fiy), 
        format_tl(val)
    ])

df_final = pd.DataFrame(display_data, columns=["ÜRÜN DETAY", "STOK (KG)", "PALET", "BİRİM FİYAT", "TOPLAM DEĞER"])

# --- ANA PANEL ---
st.subheader("🐘 FİLDİŞİ GRUP - STOK YÖNETİM PANELİ")

tab_stok, tab_yonetim, tab_rapor, tab_gecmis, tab_yedek = st.tabs([
    "📦 STOK İŞLEMLERİ", "⚙️ TANIMLAMALAR", "📊 RAPORLAR", "📜 GEÇMİŞ", "💾 YEDEK"
])

# ==========================================
# TAB 1: STOK GİRİŞ / ÇIKIŞ
# ==========================================
with tab_stok:
    c1, c2, c3, c4 = st.columns([3, 1, 1, 3])
    secili_kalibre = c1.selectbox("Ürün Seçiniz:", kalibre_listesi, key="stok_islem_sec")
    islem_kg = c2.text_input("Miktar (KG):", key="kg_in")
    islem_palet = c3.text_input("Palet Sayısı:", key="pal_in")
    islem_aciklama = c4.text_input("Açıklama:", key="desc_in")

    def hareket_yap(tip):
        kg = safe_float(islem_kg)
        palet = safe_float(islem_palet)
        if not secili_kalibre or (kg <= 0 and palet <= 0):
            st.warning("Lütfen miktar giriniz!")
            return
        
        k_id = kalibre_dict[secili_kalibre]
        tarih, saat = get_tr_now().strftime("%d-%m-%Y"), get_tr_now().strftime("%H:%M:%S")
        
        try:
            c = get_conn(); cur = c.cursor()
            if tip == "Giriş":
                cur.execute("INSERT INTO lot(kalibre_id, giris_kg, kalan_kg, giris_palet, kalan_palet, tarih) VALUES(%s,%s,%s,%s,%s,%s)", (k_id, kg, kg, palet, palet, tarih))
            else:
                cur.execute("SELECT SUM(kalan_kg), SUM(kalan_palet) FROM lot WHERE kalibre_id=%s", (k_id,))
                res = cur.fetchone()
                if kg > (res[0] or 0) or palet > (res[1] or 0):
                    st.error("Yetersiz Stok!"); c.close(); return
                
                for alan, miktar in [("kalan_kg", kg), ("kalan_palet", palet)]:
                    kalan = miktar
                    cur.execute(f"SELECT id, {alan} FROM lot WHERE kalibre_id=%s AND {alan}>0 ORDER BY id ASC", (k_id,))
                    for l_id, l_val in cur.fetchall():
                        if kalan <= 0: break
                        dus = min(l_val, kalan)
                        cur.execute(f"UPDATE lot SET {alan}={alan}-%s WHERE id=%s", (dus, l_id))
                        kalan -= dus
            
            cur.execute("INSERT INTO stok_hareket(kalibre_id, tip, kg, palet, tarih, saat, aciklama) VALUES(%s,%s,%s,%s,%s,%s,%s)", (k_id, tip, kg, palet, tarih, saat, islem_aciklama))
            c.commit(); c.close(); st.success(f"{tip} Kaydedildi!"); st.rerun()
        except Exception as e:
            st.error(f"İşlem Hatası: {e}")

    cg, cc = st.columns(2)
    if cg.button("📥 STOK GİRİŞ", use_container_width=True): hareket_yap("Giriş")
    if cc.button("📤 STOK ÇIKIŞ", use_container_width=True): hareket_yap("Çıkış")

    st.divider()
    st.subheader("📊 GÜNCEL STOK DURUMU")
    st.dataframe(df_final, use_container_width=True, hide_index=True)

# ==========================================
# TAB 2: TANIMLAMALAR
# ==========================================
with tab_yonetim:
    col_u, col_k = st.columns(2)
    with col_u:
        st.subheader("Ürün Yönetimi")
        y_urun = st.text_input("Yeni Ürün Adı:")
        if st.button("➕ Ürün Ekle"):
            if y_urun:
                c = get_conn(); cur = c.cursor()
                try:
                    cur.execute("INSERT INTO urun(ad) VALUES(%s)", (y_urun.strip(),))
                    c.commit(); st.success("Ürün eklendi!"); st.rerun()
                except: st.error("Bu ürün zaten var."); c.rollback()
                finally: c.close()

    with col_k:
        st.subheader("Kalibre/Glaze Tanımı")
        s_u = st.selectbox("Ürün Seç:", urun_listesi, key="sel_u")
        e_k = st.text_input("Kalibre:")
        e_g = st.text_input("Glaze (%):")
        e_f = st.text_input("Birim Fiyat (TL):")
        if st.button("➕ Tanımı Kaydet"):
            if s_u and e_k and e_g:
                c = get_conn(); cur = c.cursor()
                cur.execute("SELECT id FROM urun WHERE ad=%s", (s_u,))
                u_id = cur.fetchone()[0]
                cur.execute("INSERT INTO kalibre(urun_id, kalibre, glaze, satis_fiyati) VALUES(%s,%s,%s,%s)", (u_id, e_k, e_g, safe_float(e_f)))
                c.commit(); c.close(); st.success("Eklendi!"); st.rerun()

# ==========================================
# TAB 3: RAPORLAR
# ==========================================
with tab_rapor:
    st.subheader("📄 STOK RAPORLARI")
    
    # CSV Hazırlama
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["ÜRÜN DETAY", "STOK (KG)", "PALET", "BİRİM FİYAT", "TOPLAM DEĞER"])
    for row in display_data:
        writer.writerow(row) # display_data zaten 5 sütunlu
    
    writer.writerow([])
    writer.writerow(["TOPLAM", f"{t_kg:,.0f}".replace(",", "."), int(t_palet), "", format_tl(t_val)])
    
    st.download_button(
        label="📥 EKSTRE İNDİR (CSV)",
        data=output.getvalue().encode('utf-8-sig'),
        file_name=f"Fildisi_Stok_{get_tr_now().strftime('%d_%m_%Y')}.csv",
        mime="text/csv"
    )

    if st.button("📄 EKRANDA GÖRÜNTÜLE"):
        st.table(df_final)

# ==========================================
# TAB 4: GEÇMİŞ & UNDO
# ==========================================
with tab_gecmis:
    st.subheader("📜 SON HAREKETLER")
    c = get_conn()
    h_df = pd.read_sql("""
        SELECT h.id as "ID", u.ad || ' - ' || k.kalibre as "ÜRÜN", h.tip as "TİP", h.kg as "KG", h.palet as "PALET", h.tarih as "TARİH", h.saat as "SAAT"
        FROM stok_hareket h JOIN kalibre k ON k.id=h.kalibre_id JOIN urun u ON u.id=k.urun_id ORDER BY h.id DESC LIMIT 50
    """, c)
    c.close()
    st.dataframe(h_df, use_container_width=True, hide_index=True)

# ==========================================
# TAB 5: YEDEKLEME
# ==========================================
with tab_yedek:
    st.subheader("💾 VERİ YEDEKLEME")
    if st.button("Yedek Dosyası Oluştur (JSON)"):
        c = get_conn(); cur = c.cursor()
        data = {}
        for t in ["urun", "kalibre", "lot", "stok_hareket"]:
            cur.execute(f"SELECT * FROM {t}")
            cols = [d[0] for d in cur.description]
            data[t] = [dict(zip(cols, row)) for row in cur.fetchall()]
        c.close()
        st.download_button("Yedeği İndir", json.dumps(data, default=str), f"Yedek_{get_tr_now().date()}.json", "application/json")

st.divider()
st.caption("Fildişi Grup Stok Takip Sistemi © 2026")
