import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone
import io
import csv

# --- Türkiye Saati Fonksiyonu ---
def get_tr_now():
    return datetime.now(timezone(timedelta(hours=3)))

# Sayfa Yapılandırması (HER ZAMAN EN ÜSTTE OLMALI)
st.set_page_config(page_title="FİLDİŞİ GRUP - STOK", layout="wide")

# PostgreSQL Bağlantı Bilgisi
DB_URI = "postgresql://neondb_owner:npg_CuvX8ByQ5oFk@ep-cool-rain-abpiie2h-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"

# --- VERİ ÇEKME FONKSİYONU (Önbellekli) ---
@st.cache_data(ttl=60) # Veriyi 60 saniye boyunca hafızada tutar, hızı artırır
def get_data():
    try:
        conn = psycopg2.connect(DB_URI)
        
        # Stok Durumu Sorgusu
        query_stok = """
            SELECT u.ad as "ÜRÜN ADI", k.kalibre as "KALİBRE", k.glaze as "GLAZE", 
                   SUM(l.kalan_kg) as "STOK (KG)", SUM(l.kalan_palet) as "PALET", 
                   k.satis_fiyati as "BİRİM FİYAT"
            FROM lot l 
            JOIN kalibre k ON k.id = l.kalibre_id 
            JOIN urun u ON u.id = k.urun_id
            GROUP BY k.id, u.ad, k.kalibre, k.glaze, k.satis_fiyati
            HAVING SUM(l.kalan_kg) > 0 OR SUM(l.kalan_palet) > 0 
            ORDER BY u.ad DESC
        """
        df_stok = pd.read_sql(query_stok, conn)
        
        # Hareket Geçmişi Sorgusu
        query_harket = """
            SELECT h.tarih as "TARİH", h.saat as "SAAT", 
                   u.ad || ' - ' || k.kalibre || ' (%' || k.glaze || ')' as "ÜRÜN DETAY", 
                   h.tip as "İŞLEM", h.kg as "KG", h.palet as "PALET", h.aciklama as "AÇIKLAMA"
            FROM stok_hareket h 
            JOIN kalibre k ON k.id = h.kalibre_id 
            JOIN urun u ON u.id = k.urun_id 
            ORDER BY h.id DESC LIMIT 10
        """
        df_hareket = pd.read_sql(query_harket, conn)
        conn.close()
        return df_stok, df_hareket
    except Exception as e:
        return None, str(e)

# --- ANA UYGULAMA AKIŞI ---
st.title("🐘 FİLDİŞİ GRUP - ANLIK STOK")

# Verileri çek
df_stok, df_hareket_veya_hata = get_data()

# Hata kontrolü
if df_stok is None:
    st.error(f"Veritabanına bağlanılamadı: {df_hareket_veya_hata}")
else:
    # Veri İşleme
    df_stok["TOPLAM DEĞER"] = df_stok["STOK (KG)"] * df_stok["BİRİM FİYAT"]
    t_kg = df_stok["STOK (KG)"].sum()
    t_palet = df_stok["PALET"].sum()
    t_val = df_stok["TOPLAM DEĞER"].sum()

    # Üst Metrik Paneli
    m1, m2, m3 = st.columns(3)
    m1.metric("Toplam Stok (KG)", f"{t_kg:,.0f}".replace(",", "."))
    m2.metric("Toplam Palet", int(t_palet))
    m3.metric("Toplam Değer", f"₺{t_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    # Görselleştirme Tablosu
    st.subheader("📊 Güncel Stok Durumu")
    df_display = df_stok.copy()
    df_display["GLAZE"] = df_display["GLAZE"].apply(lambda x: f"%{x}")
    df_display["STOK (KG)"] = df_display["STOK (KG)"].apply(lambda x: f"{x:,.0f}".replace(",", "."))
    df_display["BİRİM FİYAT"] = df_display["BİRİM FİYAT"].apply(lambda x: f"₺{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    df_display["TOPLAM DEĞER"] = df_display["TOPLAM DEĞER"].apply(lambda x: f"₺{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # Excel (CSV) İndirme İşlemi
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["ÜRÜN ADI", "KALİBRE", "GLAZE", "STOK (KG)", "PALET", "TOPLAM DEĞER"])
    for _, row in df_stok.iterrows():
        writer.writerow([row["ÜRÜN ADI"], row["KALİBRE"], f"%{row['GLAZE']}", int(row["STOK (KG)"]), int(row["PALET"]), f"{row['TOPLAM DEĞER']:.2f}"])
    writer.writerow(["TOPLAM", "", "", int(t_kg), int(t_palet), f"{t_val:.2f}"])

    st.download_button(
        label="📥 Excel'e Aktar (CSV)",
        data=output.getvalue().encode('utf-8-sig'),
        file_name=f"Fildisi_Stok_{get_tr_now().strftime('%d_%m_%Y')}.csv",
        mime="text/csv",
    )

    st.divider()

    # Son Hareketler
    st.subheader("📜 Son 10 Stok Hareketi")
    st.dataframe(df_hareket_veya_hata, use_container_width=True, hide_index=True)

# Manuel Yenileme Butonu
if st.sidebar.button("🔄 Verileri Şimdi Yenile"):
    st.cache_data.clear()
    st.rerun()

st.caption("Copyright © 2026 - Kutay Fildişi - Tüm hakları saklıdır.")
