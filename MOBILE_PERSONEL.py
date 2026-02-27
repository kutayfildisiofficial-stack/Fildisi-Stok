import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone
import io
import csv
import json

# =========================================================
# VERİTABANI
# =========================================================

DB_URI = "postgresql://neondb_owner:npg_CuvX8ByQ5oFk@ep-cool-rain-abpiie2h-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"

def get_conn():
    return psycopg2.connect(DB_URI)

def get_tr_now():
    return datetime.now(timezone(timedelta(hours=3)))

def safe_float(val):
    try:
        return float(str(val).replace(",", "."))
    except:
        return 0.0

def format_tl(value):
    s = f"{value:,.2f}"
    main, decimal = s.split(".")
    return f"₺{main.replace(',', '.')},{decimal}"

# =========================================================
# LOGIN
# =========================================================

st.set_page_config(page_title="FİLDİŞİ GRUP - STOK TAKİP", layout="wide")

if "logged_in" not in st.session_state:
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

    st.stop()

# =========================================================
# VERİ ÇEK
# =========================================================

def load_data():
    conn = get_conn()

    df_urun = pd.read_sql("SELECT id, ad FROM urun ORDER BY ad", conn)

    df_kalibre = pd.read_sql("""
        SELECT u.ad as u_ad, k.kalibre, k.glaze,
               k.satis_fiyati, k.id as k_id
        FROM kalibre k
        JOIN urun u ON u.id = k.urun_id
        ORDER BY u.ad
    """, conn)

    df_stok = pd.read_sql("""
        SELECT u.ad, k.kalibre, k.glaze,
               SUM(l.kalan_kg) as kg,
               SUM(l.kalan_palet) as palet,
               k.satis_fiyati,
               k.id as k_id
        FROM lot l
        JOIN kalibre k ON k.id=l.kalibre_id
        JOIN urun u ON u.id=k.urun_id
        GROUP BY k.id, u.ad, k.kalibre, k.glaze, k.satis_fiyati
        HAVING SUM(l.kalan_kg) > 0 OR SUM(l.kalan_palet) > 0
        ORDER BY u.ad DESC
    """, conn)

    conn.close()
    return df_urun, df_kalibre, df_stok

df_urun, df_kalibre, df_stok = load_data()

urun_listesi = df_urun["ad"].tolist() if not df_urun.empty else []
kalibre_listesi = [
    f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}"
    for _, r in df_kalibre.iterrows()
]
kalibre_dict = {
    f"{r['u_ad']} - {r['kalibre']} - %{r['glaze']}": r["k_id"]
    for _, r in df_kalibre.iterrows()
}

# =========================================================
# SEKME YAPISI
# =========================================================

st.subheader("STOK YÖNETİM PANELİ")

tab_stok, tab_yonetim, tab_rapor, tab_gecmis, tab_yedek = st.tabs([
    "📦 STOK GİRİŞ/ÇIKIŞ",
    "⚙️ ÜRÜN/KALİBRE TANIMLARI",
    "📊 RAPORLAR",
    "📜 HAREKET GEÇMİŞİ",
    "💾 YEDEK"
])

# =========================================================
# TAB 1 - STOK
# =========================================================

with tab_stok:

    c1, c2, c3, c4 = st.columns([3,1,1,3])

    secili_kalibre = c1.selectbox("Ürün:", kalibre_listesi)
    islem_kg = c2.text_input("Miktar(KG):")
    islem_palet = c3.text_input("Palet:")
    islem_aciklama = c4.text_input("Açıklama:")

    def hareket(tip):
        kg = safe_float(islem_kg)
        palet = safe_float(islem_palet)

        if not secili_kalibre or (kg <= 0 and palet <= 0):
            return

        k_id = kalibre_dict[secili_kalibre]
        tarih = get_tr_now().strftime("%d-%m-%Y")
        saat = get_tr_now().strftime("%H:%M:%S")

        conn = get_conn()
        cur = conn.cursor()

        if tip == "Giriş":
            cur.execute("""
                INSERT INTO lot
                (kalibre_id,giris_kg,kalan_kg,giris_palet,kalan_palet,tarih)
                VALUES(%s,%s,%s,%s,%s,%s)
            """, (k_id,kg,kg,palet,palet,tarih))

        else:
            cur.execute("""
                SELECT SUM(kalan_kg), SUM(kalan_palet)
                FROM lot WHERE kalibre_id=%s
            """, (k_id,))
            res = cur.fetchone()

            if kg > (res[0] or 0) or palet > (res[1] or 0):
                st.error("Yetersiz Stok!")
                conn.close()
                return

            for alan, miktar in [("kalan_kg",kg),("kalan_palet",palet)]:
                kalan = miktar
                cur.execute(f"""
                    SELECT id,{alan}
                    FROM lot
                    WHERE kalibre_id=%s AND {alan}>0
                    ORDER BY id DESC
                """,(k_id,))
                for l_id,l_val in cur.fetchall():
                    if kalan<=0:
                        break
                    dus = min(l_val,kalan)
                    cur.execute(f"""
                        UPDATE lot SET {alan}={alan}-%s
                        WHERE id=%s
                    """,(dus,l_id))
                    kalan -= dus

        cur.execute("""
            INSERT INTO stok_hareket
            (kalibre_id,tip,kg,palet,tarih,saat,aciklama)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
        """,(k_id,tip,kg,palet,tarih,saat,islem_aciklama))

        conn.commit()
        conn.close()

        st.success(f"{tip} Başarılı!")
        st.rerun()

    col_g,col_c = st.columns(2)

    if col_g.button("📥 Stok Giriş",use_container_width=True):
        hareket("Giriş")

    if col_c.button("📤 Stok Çıkış",use_container_width=True):
        hareket("Çıkış")

    st.divider()

    # STOK TABLOSU
    display_data=[]
    t_kg=t_palet=t_val=0

    for _,r in df_stok.iterrows():
        kg=r["kg"] or 0
        palet=r["palet"] or 0
        fiyat=r["satis_fiyati"] or 0
        val=kg*fiyat

        t_kg+=kg
        t_palet+=palet
        t_val+=val

        display_data.append([
            r["ad"],
            r["kalibre"],
            f"%{r['glaze']}",
            f"{kg:,.0f}".replace(",","."), 
            int(palet),
            format_tl(val)
        ])

    st.subheader("GÜNCEL STOK DURUMU")

    st.dataframe(
        pd.DataFrame(display_data,
        columns=["ÜRÜN","KALİBRE","GLAZE","STOK (KG)","PALET","TOPLAM DEĞER"]),
        use_container_width=True
    )

# =========================================================
# TAB 3 RAPOR (CSV FIXED)
# =========================================================

with tab_rapor:

    output=io.StringIO()
    writer=csv.writer(output,delimiter=";")

    writer.writerow(["ÜRÜN","KALİBRE","GLAZE","STOK (KG)","PALET","TOPLAM DEĞER"])

    for row in display_data:
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["TOPLAM","","",
                     f"{t_kg:,.0f}".replace(",","."),
                     int(t_palet),
                     format_tl(t_val)])

    st.download_button(
        "📊 EKSTRE (CSV)",
        data=output.getvalue().encode("utf-8-sig"),
        file_name=f"Fildisi_Stok_Rapor_{get_tr_now().strftime('%d_%m_%Y')}.csv",
        mime="text/csv"
    )

# =========================================================
# (TAB 4 VE TAB 5 AYNI MANTIĞINLA DEVAM EDİYOR)
# =========================================================
