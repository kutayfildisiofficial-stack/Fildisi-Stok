import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime
import io
import csv

# Sayfa Yapılandırması
st.set_page_config(page_title="FİLDİŞİ GRUP - STOK", layout="wide")

# PostgreSQL Bağlantısı
DB_URI = "postgresql://neondb_owner:npg_CuvX8ByQ5oFk@ep-cool-rain-abpiie2h-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"

def get_data():
    try:
        conn = psycopg2.connect(DB_URI)
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
        st.error(f"Veritabanı hatası: {e}")
        return None, None

# Giriş Kontrolü
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 GİRİŞ")
    user = st.text_input("Kullanıcı Adı", value="FLD2026")
    pw = st.text_input("Şifre", type="password")
    if st.button("Giriş Yap"):
        if user == "FLD2026" and pw == "18811938": 
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Hatalı bilgiler!")
else:
    st.title("🐘 FİLDİŞİ GRUP - ANLIK STOK")
    df_stok, df_hareket = get_data()

    if df_stok is not None:
        # Hesaplamalar
        df_stok["TOPLAM DEĞER"] = df_stok["STOK (KG)"] * df_stok["BİRİM FİYAT"]
        t_kg = df_stok["STOK (KG)"].sum()
        t_palet = df_stok["PALET"].sum()
        t_val = df_stok["TOPLAM DEĞER"].sum()

        # Üst Metrikler
        col1, col2, col3 = st.columns(3)
        col1.metric("Toplam Stok (KG)", f"{t_kg:,.0f}".replace(",", "."))
        col2.metric("Toplam Palet", int(t_palet))
        col3.metric("Toplam Değer", f"₺{t_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        # --- EKRAN İÇİN GÖRSEL TABLO (GLAZE %50 YAPILDI) ---
        df_display = df_stok.copy()
        df_display["GLAZE"] = df_display["GLAZE"].map(lambda x: f"%{x}") # İSTEK: %50 formatı
        df_display["STOK (KG)"] = df_display["STOK (KG)"].map(lambda x: f"{x:,.0f}".replace(",", "."))
        df_display["PALET"] = df_display["PALET"].map(lambda x: f"{int(x)}")
        df_display["BİRİM FİYAT"] = df_display["BİRİM FİYAT"].map(lambda x: f"₺{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        df_display["TOPLAM DEĞER"] = df_display["TOPLAM DEĞER"].map(lambda x: f"₺{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        
        st.subheader("📊 Güncel Stok Durumu")
        st.dataframe(df_display, use_container_width=True)

        # --- CSV HAZIRLAMA (GÖRSEL image_5fbbdc.png UYUMLU) ---
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        
        # Başlıklar (Görseldeki gibi Birim Fiyat yok)
        writer.writerow(["ÜRÜN ADI", "KALİBRE", "GLAZE", "STOK (KG)", "PALET", "TOPLAM DEĞER"])
        
        for _, row in df_stok.iterrows():
            writer.writerow([
                row["ÜRÜN ADI"], 
                row["KALİBRE"], 
                f"%{row['GLAZE']}", # Excel'de %50 görünümü
                f"{row['STOK (KG)']:,.0f}".replace(",", ""), # Excel sayı olarak tanısın
                int(row["PALET"]), 
                f"₺{row['TOPLAM DEĞER']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            ])
            
        # Görseldeki gibi bir boşluk satırı ve TOPLAM satırı
        writer.writerow([])
        writer.writerow([
            "TOPLAM", 
            "", 
            "", 
            f"{t_kg:,.0f}".replace(",", ""), 
            int(t_palet), 
            f"₺{t_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        ])
        
        st.download_button(
            label="📥 Excel'e Aktar (CSV)",
            data=output.getvalue().encode('utf-8-sig'),
            file_name=f"Fildisi_Stok_Rapor_{datetime.now().strftime('%d_%m_%Y')}.csv",
            mime="text/csv",
        )

        st.divider()

        # --- HAREKET GEÇMİŞİ ---
        df_h_disp = df_hareket.copy()
        df_h_disp["KG"] = df_h_disp["KG"].map(lambda x: f"{x:,.0f}".replace(",", "."))
        df_h_disp["PALET"] = df_h_disp["PALET"].map(lambda x: f"{int(x)}")
        
        st.subheader("📜 Son 10 Stok Hareketi")
        st.table(df_h_disp)

    if st.button("🔄 Verileri Yenile"):
        st.rerun()

    st.caption("Copyright © 2026 - Kutay Fildişi - Tüm hakları saklıdır.")
