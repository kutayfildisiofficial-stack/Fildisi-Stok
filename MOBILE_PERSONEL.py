import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
import pytz
import csv

# ==========================================
# AYARLAR
# ==========================================
DB_CONFIG = {
    "host": "localhost",
    "database": "stok_db",
    "user": "postgres",
    "password": "1234"
}

st.set_page_config(page_title="Fildişi Stok", layout="wide")

# ==========================================
# BAĞLANTI
# ==========================================
def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_tr_now():
    tz = pytz.timezone("Europe/Istanbul")
    return datetime.now(tz)

def safe_float(x):
    try:
        return float(str(x).replace(",", "."))
    except:
        return 0.0

def format_tl(x):
    return f"{x:,.2f} ₺".replace(",", ".")

# ==========================================
# VERİLERİ ÇEK
# ==========================================
def load_data():
    conn = get_conn()
    df = pd.read_sql("""
        SELECT 
            k.id,
            u.ad,
            k.kalibre,
            k.glaze,
            k.satis_fiyati,
            SUM(l.kalan_kg) as kg,
            SUM(l.kalan_palet) as palet
        FROM kalibre k
        JOIN urun u ON u.id = k.urun_id
        LEFT JOIN lot l ON l.kalibre_id = k.id
        GROUP BY k.id, u.ad, k.kalibre, k.glaze, k.satis_fiyati
        ORDER BY u.ad
    """, conn)
    conn.close()
    return df

df_stok = load_data()

# ==========================================
# ÜST TOPLAM KARTLARI
# ==========================================
toplam_kg = (df_stok["kg"].fillna(0)).sum()
toplam_palet = (df_stok["palet"].fillna(0)).sum()
toplam_deger = (df_stok["kg"].fillna(0) * df_stok["satis_fiyati"].fillna(0)).sum()

c1, c2, c3 = st.columns(3)
c1.metric("Toplam KG", f"{toplam_kg:,.0f}".replace(",", "."))
c2.metric("Toplam Palet", int(toplam_palet))
c3.metric("Toplam Değer", format_tl(toplam_deger))

st.divider()

# ==========================================
# STOK İŞLEM ALANI
# ==========================================
st.subheader("Stok İşlemi")

kalibre_dict = {f"{r['ad']} - {r['kalibre']} (%{r['glaze']})": r["id"]
                for _, r in df_stok.iterrows()}

secili = st.selectbox("Ürün Seç", list(kalibre_dict.keys()))
kg_input = st.text_input("KG")
palet_input = st.text_input("Palet")
aciklama = st.text_input("Açıklama")

def hareket(tip):
    kg = safe_float(kg_input)
    palet = safe_float(palet_input)

    if kg <= 0 and palet <= 0:
        st.warning("Miktar gir.")
        return

    k_id = kalibre_dict[secili]
    tarih = get_tr_now().strftime("%d-%m-%Y")
    saat = get_tr_now().strftime("%H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()

    if tip == "Giriş":
        cur.execute("""
            INSERT INTO lot(kalibre_id, giris_kg, kalan_kg, giris_palet, kalan_palet, tarih)
            VALUES(%s,%s,%s,%s,%s,%s)
        """, (k_id, kg, kg, palet, palet, tarih))

    else:
        cur.execute("SELECT SUM(kalan_kg), SUM(kalan_palet) FROM lot WHERE kalibre_id=%s", (k_id,))
        res = cur.fetchone()
        mevcut_kg = res[0] or 0
        mevcut_palet = res[1] or 0

        if kg > mevcut_kg or palet > mevcut_palet:
            st.error("Yetersiz stok!")
            conn.close()
            return

        for alan, miktar in [("kalan_kg", kg), ("kalan_palet", palet)]:
            kalan = miktar
            cur.execute(f"""
                SELECT id, {alan} FROM lot
                WHERE kalibre_id=%s AND {alan}>0
                ORDER BY id ASC
            """, (k_id,))
            for l_id, l_val in cur.fetchall():
                if kalan <= 0:
                    break
                dus = min(l_val, kalan)
                cur.execute(f"""
                    UPDATE lot SET {alan}={alan}-%s
                    WHERE id=%s
                """, (dus, l_id))
                kalan -= dus

    cur.execute("""
        INSERT INTO stok_hareket(kalibre_id, tip, kg, palet, tarih, saat, aciklama)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
    """, (k_id, tip, kg, palet, tarih, saat, aciklama))

    conn.commit()
    conn.close()
    st.success(f"{tip} başarılı")
    st.rerun()

col1, col2 = st.columns(2)

if col1.button("📥 Giriş", use_container_width=True):
    hareket("Giriş")

if col2.button("📤 Çıkış", use_container_width=True):
    hareket("Çıkış")

# ==========================================
# STOK TABLOSU
# ==========================================
st.divider()
st.subheader("Güncel Stok")

display_data = []

for _, r in df_stok.iterrows():
    kg = r["kg"] or 0
    palet = r["palet"] or 0
    fiyat = r["satis_fiyati"] or 0
    deger = kg * fiyat

    display_data.append([
        f"{r['ad']} - {r['kalibre']} (%{r['glaze']})",
        f"{kg:,.0f}".replace(",", "."),
        int(palet),
        format_tl(fiyat),
        format_tl(deger)
    ])

df_display = pd.DataFrame(display_data,
                          columns=["Ürün", "KG", "Palet", "Birim Fiyat", "Toplam Değer"])

st.dataframe(df_display, use_container_width=True)

# ==========================================
# CSV EXPORT
# ==========================================
csv_file = "stok_rapor.csv"

with open(csv_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(df_display.columns)
    for row in display_data:
        writer.writerow(row)

with open(csv_file, "rb") as f:
    st.download_button("CSV İndir", f, file_name="stok_rapor.csv")
