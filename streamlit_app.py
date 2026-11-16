from io import BytesIO
import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

st.set_page_config(
    page_title="Nómina Ancora",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).parent
LOGO_PATH = BASE / "imagenes" / "ancora_blanco.png"

# Fuente de datos: Google Sheet en vivo (mismo patrón sin API key que
# Facturación/Tarjetas de Crédito/Town Hall: export?format=xlsx, hoja
# compartida "cualquiera con el link"). Única pestaña con datos reales es
# "Base" -- el resto de pestañas por área del libro vienen vacías (no se usan).
NOMINA_SHEET_ID = "1vCdFJLlzS-ZtxkN2RYBy6HkxTglEOZVinBDmYzRDCUw"  # 2026

# 2025 y 2027 confirmados con el usuario (2026-11-12): mismo concepto de
# nómina, un archivo por año, cada uno con su propio esquema de columnas
# (no es un error que no calcen entre sí).
NOMINA_SHEET_ID_2025 = "1NGfQPQwUIJxv9y9YI6O1gM4jVeuI7wydftMZai0NPnI"
NOMINA_SHEET_ID_2027 = "1rD3KGOsffG1MO0Gkoz5eBe4s3p9t8zzCOQAPCinhxVQ"

# Ingresos de la empresa, para "nómina como % de ingresos" -- mismo Sheet que
# usa el tablero Town Hall (pestaña "Ingresos"), reutilizado aquí tal cual
# (confirmado con el usuario, 2026-11-13). Trae bloques por año en la
# columna A ("2024", "2025", "2026 Real", "PTO 2026") sin pestaña de 2027.
INGRESOS_SHEET_ID = "1hKrCVzzBZHIKOvlCdriTPHgdC36bXIxJb4osUhZVYE4"

# "Fianzas"/"Marketing" son el mismo concepto que "Garantías"/"Mercadotecnia"
# con otro nombre (confirmado con el usuario, 2026-11-12) -- se fusionan.
# "Monterrey"/"Guadalajara" son oficinas foráneas, no áreas de negocio; se
# dejan como su propia categoría a propósito (no se inventó a qué área
# pertenecen).
ALIAS_AREA = {"Fianzas": "Garantías", "Marketing": "Mercadotecnia"}

# Mapeo de línea de negocio (hoja "Ingresos", en MAYÚSCULAS) al nombre de
# área que usa Nómina -- confirmado con el usuario, 2026-11-13: "FIANZAS" de
# Ingresos es la línea de fianzas/garantías (mapea a "Garantías", NO al
# departamento de "Finanzas" de Nómina, que es otra cosa). "INTERNACIONAL"
# se fusiona en "Daños" (mismo criterio que ya usa Town Hall). "ANI" y
# "BONO" no son línea de negocio con nómina propia -- se excluyen.
ALIAS_LINEA_INGRESOS = {
    "AFFINITY": "Affinity", "AUTOS": "Autos", "BENEFICIOS": "Beneficios",
    "DAÑOS": "Daños", "INTERNACIONAL": "Daños", "FIANZAS": "Garantías",
    "LF": "Líneas Financieras", "LP": "Líneas Personales",
}

COLS_NUM = ["Nómina Mensual", "Carga Social Mensual", "Vales", "Sueldo Anual",
            "Carga Social Anual", "Vales Anual", "GMM", "Costo Anual"]

# ── Paleta de marca Ancora (misma que Consejo/Clientes/Town Hall) ──────────────
MARCA_NAVY = "#13375c"
MARCA_CLARO = "#F6F6F6"
MARCA_TEAL = "#1d7b8a"
MARCA_ORO = "#e9ba40"
C_NEG = "#c0514a"

PALETA_CAT = [MARCA_TEAL, MARCA_ORO, "#3a6ea5", "#d97b3c", "#4aa3b0", "#8a6d4b",
              "#6f9bc4", "#b58fb0", "#9aa5b1", "#c99a2e", "#5d7a9e", "#7a9e6e"]

def color_for(i):
    return PALETA_CAT[i % len(PALETA_CAT)]

EJE_COLOR = "#c7d2e0"
GRID_COLOR = "#2e4d70"
DOMINIO_COLOR = "#3a5578"
FUENTE = "Montserrat, sans-serif"

def estilizar(chart):
    return (
        chart
        .properties(background="transparent")
        .configure_view(strokeOpacity=0)
        .configure_axis(labelColor=EJE_COLOR, titleColor=EJE_COLOR,
                        gridColor=GRID_COLOR, domainColor=DOMINIO_COLOR,
                        labelFont=FUENTE, titleFont=FUENTE,
                        labelFontSize=11, titleFontSize=12)
        .configure_legend(labelColor=EJE_COLOR, titleColor=EJE_COLOR,
                          labelFont=FUENTE, titleFont=FUENTE)
        .configure_title(color=MARCA_CLARO, font=FUENTE)
    )

EJE_DOLAR = alt.Axis(labelExpr="'$' + format(datum.value, ',.0f')")

def fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"${v:,.0f}"

def pct(v):
    """Para crecimientos/variaciones -- lleva signo."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{'+' if v >= 0 else ''}{v*100:.1f}%"

def pct_plain(v):
    """Para proporciones/tasas (ej. % del total, % carga social) -- sin signo."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v*100:.1f}%"

# ── Carga ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Cargando nómina...")
def load_data():
    """Lee la pestaña 'Base' (única con datos reales). La hoja trae 7 filas
    basura al final (totales/fórmulas que quedaron repartidas en celdas sin
    nombre de colaborador) -- se descartan exigiendo COLABORADOR no vacío."""
    url = f"https://docs.google.com/spreadsheets/d/{NOMINA_SHEET_ID}/export?format=xlsx"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(BytesIO(resp.content), sheet_name="Base", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["COLABORADOR"].notna()].copy()
    df["Área"] = df["Área"].replace(ALIAS_AREA)
    df["Departamento"] = df["Departamento"].fillna("Sin departamento")
    for c in COLS_NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["Pct Carga Social"] = df["Carga Social Mensual"] / df["Nómina Mensual"].replace(0, pd.NA)
    df["Sustitución"] = df["Sustitución"].map(lambda v: v is True)
    df["Nueva Creación"] = pd.to_numeric(df["Nueva Creación"], errors="coerce").fillna(0) > 0
    return df.reset_index(drop=True)

@st.cache_data(ttl=300, show_spinner=False)
def load_2026_real():
    """Pestaña 'Real' del mismo Sheet de 2026 (confirmado con el usuario,
    2026-11-16): nómina REAL pagada mes a mes (no la plantilla/proyección de
    'Base'). Trae gente que ya no sigue en 'Base' y algunos colaboradores con
    varias filas (distintos conceptos de pago que sí se suman, igual que el
    caso ya confirmado de 2027). Fila 'TOTAL' embebida al final -- se excluye
    por 'Colaborador'=='TOTAL' exclusivamente, no por '# Colaborador' vacío
    (mismo motivo que [[utilidad-cliente-suma-total-duplica]] / el caso de
    Beneficios-Médico en 2027: varias filas reales no traen '# Colaborador')."""
    url = f"https://docs.google.com/spreadsheets/d/{NOMINA_SHEET_ID}/export?format=xlsx"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(BytesIO(resp.content), sheet_name="Real", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    nombre_norm = df["Colaborador"].map(lambda v: str(v).strip().upper() if pd.notna(v) else v)
    df = df[nombre_norm.notna() & (nombre_norm != "TOTAL")].copy()
    df["Área"] = df["Área"].replace(ALIAS_AREA)
    df["Departamento"] = df["Departamento"].fillna("Sin departamento")
    df["Total"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0.0)
    return df.reset_index(drop=True)

@st.cache_data(ttl=300, show_spinner=False)
def load_2025():
    """Archivo propio de 2025 -- misma gente, otro esquema (Sueldo/Carga
    Social/Anualizado en vez de Mensual/Anual por separado). 'Anualizado'
    se usa tal cual como costo anual (confirmado con el usuario, aunque la
    magnitud no calce con 2026: son cambios reales de sueldo/estructura,
    no un error de lectura)."""
    url = f"https://docs.google.com/spreadsheets/d/{NOMINA_SHEET_ID_2025}/export?format=xlsx"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(BytesIO(resp.content), sheet_name="Base", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Colaborador"].notna()].copy()
    df["Área"] = df["Área"].replace(ALIAS_AREA)
    df["Departamento"] = df["Departamento"].fillna("Sin departamento")
    df["Anualizado"] = pd.to_numeric(df["Anualizado"], errors="coerce").fillna(0.0)
    return df.reset_index(drop=True)

@st.cache_data(ttl=300, show_spinner=False)
def load_2027():
    """Archivo propio de 2027 (presupuesto), hoja 'Nómina Bruta'. Algunos
    colaboradores traen 2 filas -- un segundo concepto que SÍ se suma
    (confirmado con el usuario, ej. bono/comisión). La hoja trae una fila
    'TOTAL' embebida que duplicaría la suma si no se excluye -- mismo patrón
    que [[utilidad-cliente-suma-total-duplica]]; se excluye por Nombre=='TOTAL'
    exclusivamente. OJO: varios colaboradores reales vienen sin '# Colaborador'
    (ej. Ricardo Ayala Sánchez) -- exigir ese campo no vacío (como se hacía
    antes) los excluía por error y bajaba el total ~$831k (confirmado con el
    usuario, 2026-11-13); por eso el total y la cuenta de gente usan 'Nombre',
    no '# Colaborador'."""
    url = f"https://docs.google.com/spreadsheets/d/{NOMINA_SHEET_ID_2027}/export?format=xlsx"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(BytesIO(resp.content), sheet_name="Nómina Bruta", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    nombre_norm = df["Nombre"].map(lambda v: str(v).strip().upper() if pd.notna(v) else v)
    df = df[nombre_norm.notna() & (nombre_norm != "TOTAL")].copy()
    df["Área"] = df["Área"].replace(ALIAS_AREA)
    df["Departamento"] = df["Departamento"].fillna("Sin departamento")
    df["Total"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0.0)
    return df.reset_index(drop=True)

@st.cache_data(ttl=300, show_spinner=False)
def load_ingresos():
    """Pestaña 'Ingresos' del Sheet de Town Hall -- bloques apilados por año
    en la hoja (col A trae la etiqueta '2024'/'2025'/'2026 Real'/'PTO 2026'/
    'PTO 2027', luego encabezado AREA/meses/TOTAL, luego una fila por área y
    una fila TOTAL con el total del año en la columna TOTAL). Se usa 2025
    (real), 'PTO 2026' (presupuesto completo del año) y '2026 Real' (avance
    real, se va actualizando mes a mes en vivo) -- confirmado con el
    usuario, 2026-11-13 y 2026-11-16. 'PTO 2027' se agregó al Sheet después
    (2026-11-16) y se usa tal cual para el año 2027."""
    url = f"https://docs.google.com/spreadsheets/d/{INGRESOS_SHEET_ID}/export?format=xlsx"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(BytesIO(resp.content), sheet_name="Ingresos", header=None)
    col0 = df[0].astype(str).str.strip()

    def _bloque(etiqueta):
        """Devuelve (total_año, {línea_nómina: monto}) para el bloque dado."""
        idxs = df.index[col0 == etiqueta].tolist()
        if not idxs:
            return None, {}
        inicio = idxs[0]
        por_linea = {}
        total = None
        for i in range(inicio + 1, min(inicio + 14, len(df))):
            etiqueta_fila = str(df.iat[i, 0]).strip()
            if etiqueta_fila.upper() == "TOTAL":
                total = float(df.iat[i, 13])
                break
            linea = ALIAS_LINEA_INGRESOS.get(etiqueta_fila.upper())
            if linea is not None:
                monto = pd.to_numeric(df.iat[i, 13], errors="coerce")
                por_linea[linea] = por_linea.get(linea, 0.0) + (float(monto) if pd.notna(monto) else 0.0)
        return total, por_linea

    total_2025, linea_2025 = _bloque("2025")
    total_2026, linea_2026 = _bloque("PTO 2026")
    total_2026_real, linea_2026_real = _bloque("2026 Real")
    total_2027, linea_2027 = _bloque("PTO 2027")
    return ({"2025": total_2025, "2026": total_2026, "2026_real": total_2026_real, "2027": total_2027},
            {"2025": linea_2025, "2026": linea_2026, "2026_real": linea_2026_real, "2027": linea_2027})

try:
    DF = load_data()
except Exception as e:
    st.error(f"Error al descargar/leer los datos del Sheet:\n\n{e}")
    st.stop()

if DF.empty:
    st.error("No se encontraron colaboradores en la hoja 'Base' del Sheet de Nómina.")
    st.stop()

# 2025/2027 alimentan solo la página "Tendencia" -- si fallan, el resto del
# tablero (que corre sobre 2026) sigue funcionando igual.
try:
    DF_2025 = load_2025()
except Exception:
    DF_2025 = pd.DataFrame()
try:
    DF_2027 = load_2027()
except Exception:
    DF_2027 = pd.DataFrame()
try:
    DF_2026_REAL = load_2026_real()
except Exception:
    DF_2026_REAL = pd.DataFrame()
try:
    INGRESOS_ANUAL, INGRESOS_POR_LINEA = load_ingresos()
except Exception:
    INGRESOS_ANUAL = {"2025": None, "2026": None, "2026_real": None, "2027": None}
    INGRESOS_POR_LINEA = {"2025": {}, "2026": {}, "2026_real": {}, "2027": {}}

RESUMEN_ANUAL = {
    "2025": {"costo": DF_2025["Anualizado"].sum() if not DF_2025.empty else None,
             "hc": len(DF_2025) if not DF_2025.empty else None,
             "por_area": DF_2025.groupby("Área")["Anualizado"].sum().to_dict() if not DF_2025.empty else {}},
    "2026": {"costo": DF["Costo Anual"].sum(), "hc": len(DF),
             "por_area": DF.groupby("Área")["Costo Anual"].sum().to_dict()},
    "2027": {"costo": DF_2027["Total"].sum() if not DF_2027.empty else None,
             "hc": DF_2027["Nombre"].nunique() if not DF_2027.empty else None,
             "por_area": DF_2027.groupby("Área")["Total"].sum().to_dict() if not DF_2027.empty else {}},
    "2026_real": {"costo": DF_2026_REAL["Total"].sum() if not DF_2026_REAL.empty else None,
                  "hc": DF_2026_REAL["Colaborador"].nunique() if not DF_2026_REAL.empty else None,
                  "por_area": DF_2026_REAL.groupby("Área")["Total"].sum().to_dict() if not DF_2026_REAL.empty else {}},
}

# Desglose por departamento dentro de cada área, por año -- alimenta el
# filtro de área de "Costo por área, por año" (al elegir un área se cambia
# el eje de la gráfica de Área a Departamento). Los 3 archivos sí traen
# columna "Departamento".
RESUMEN_DEPTO_ANUAL = {
    "2025": (DF_2025.groupby(["Área", "Departamento"])["Anualizado"].sum()
             if not DF_2025.empty else pd.Series(dtype=float)),
    "2026": DF.groupby(["Área", "Departamento"])["Costo Anual"].sum(),
    "2027": (DF_2027.groupby(["Área", "Departamento"])["Total"].sum()
             if not DF_2027.empty else pd.Series(dtype=float)),
}

# Misma idea que RESUMEN_DEPTO_ANUAL pero como tabla (Área, Departamento,
# Costo, Colaboradores) -- alimenta el filtro de año de la página "Por Área".
# Colaboradores cuenta nombres/IDs únicos (no filas) para no duplicar al
# colaborador de 2027 con 2 filas (bono/comisión).
def _agg_area_depto(df, costo_col, nombre_col):
    if df.empty:
        return pd.DataFrame(columns=["Área", "Departamento", "Costo", "Colaboradores"])
    return df.groupby(["Área", "Departamento"]).agg(
        Costo=(costo_col, "sum"), Colaboradores=(nombre_col, "nunique"),
    ).reset_index()

AGG_AREA_DEPTO_AÑO = {
    "2025": _agg_area_depto(DF_2025, "Anualizado", "Colaborador"),
    "2026": _agg_area_depto(DF, "Costo Anual", "COLABORADOR"),
    "2027": _agg_area_depto(DF_2027, "Total", "Nombre"),
}

# Roster por colaborador, por año -- alimenta la tabla "Detalle por
# colaborador" dentro de "Por Área". Solo 2026 trae el desglose mensual
# completo (Nómina/Carga Social/Vales/GMM/Sustitución); 2025 y 2027 solo
# traen el costo anual por persona.
if not DF_2025.empty:
    DETALLE_AÑO_2025 = DF_2025.rename(
        columns={"Colaborador": "Colaborador", "Anualizado": "Costo Anual"}
    )[["Colaborador", "Área", "Departamento", "Costo Anual"]]
else:
    DETALLE_AÑO_2025 = pd.DataFrame(columns=["Colaborador", "Área", "Departamento", "Costo Anual"])

DETALLE_AÑO_2026 = DF.rename(columns={"COLABORADOR": "Colaborador"})[
    ["Colaborador", "Área", "Departamento", "Nómina Mensual", "Carga Social Mensual",
     "Vales", "GMM", "Costo Anual", "Sustitución", "Nueva Creación"]
]

if not DF_2027.empty:
    DETALLE_AÑO_2027 = DF_2027.groupby(["Nombre", "Área", "Departamento"], as_index=False)["Total"].sum().rename(
        columns={"Nombre": "Colaborador", "Total": "Costo Anual"})
else:
    DETALLE_AÑO_2027 = pd.DataFrame(columns=["Colaborador", "Área", "Departamento", "Costo Anual"])

DETALLE_AÑO = {"2025": DETALLE_AÑO_2025, "2026": DETALLE_AÑO_2026, "2027": DETALLE_AÑO_2027}

años = ["2025", "2026", "2027"]
COLOR_AÑO = {"2025": "#9aa5b1", "2026": MARCA_TEAL, "2027": MARCA_ORO}

# ── Estilos (mismos que los otros tableros Ancora) ─────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], .stApp,
.stApp *:not([data-testid="stIconMaterial"]) {
    font-family: 'Montserrat', sans-serif !important;
}
[data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded' !important; }
[data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"],
p, span:not([data-testid="stIconMaterial"]), label, td, th, li,
div[data-testid="stMetricValue"], div[data-testid="stMetricDelta"], .stDataFrame { font-weight: 500; }
h1, h2, h3, h4, h5, h6, div[data-testid="stMetricLabel"] p { font-weight: 600 !important; }
section[data-testid="stSidebar"] img { pointer-events: none; }
section[data-testid="stSidebar"] [data-testid="StyledFullScreenButton"] { display: none; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
section[data-testid="stSidebar"] .block-container { padding-top: 0 !important; }
div[data-testid="stRadio"] > div { gap: 2px !important; }
div[data-testid="stRadio"] label {
    display: flex !important; align-items: center !important;
    padding: 10px 14px !important; border-radius: 8px !important;
    cursor: pointer !important; font-size: 0.9rem !important;
    margin-bottom: 2px !important; transition: background 0.15s !important; border: none !important;
}
div[data-testid="stRadio"] label:hover { background: rgba(255,255,255,0.08) !important; }
div[data-testid="stRadio"] label:has(input:checked) {
    background: rgba(255,255,255,0.13) !important; font-weight: 600 !important;
}
div[data-testid="stRadio"] label > div:first-child { display: none !important; }
div[data-testid="stRadio"] { border: none !important; }
div[data-testid="stMetricValue"] {
    font-size: 1.35rem !important; line-height: 1.2 !important;
    white-space: nowrap !important; overflow: visible !important;
}
div[data-testid="stMetricValue"] > div { overflow: visible !important; }
</style>
""", unsafe_allow_html=True)

components.html(
    "<script>try{var d=window.parent.document.documentElement;"
    "d.setAttribute('translate','no');d.classList.add('notranslate');}catch(e){}</script>",
    height=0,
)

# "Costo por área, por año" pedido en Recharts real (igual que Facturación:
# React + Recharts vía CDN, sin build step) en vez de Altair -- único
# componente React de este tablero, el resto sigue siendo Streamlit/Altair.
_area_lineas_component = components.declare_component(
    "nomina_costo_area_lineas", path=str(BASE / "components" / "nomina_costo_area_lineas"))

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    st.markdown("---")
    st.caption("TABLEROS")
    pagina = st.radio(
        "",
        ["General", "General 2026 Real", "Por Área"],
        label_visibility="collapsed",
        key="nav",
    )
    st.markdown("---")
    st.caption(f"Nómina Ancora · {len(DF)} colaboradores")

# ══════════════════════════════════════════════════════════════════════════════
# PANORAMA (General / General 2026 Real)
# ══════════════════════════════════════════════════════════════════════════════
def render_general(sufijo, usar_real):
    """Cuerpo compartido de "General" (PTO) y "General 2026 Real" -- pedido
    explícito del usuario, 2026-11-16: manejar PTO y Real en pestañas
    separadas (se probó primero como un botón dentro de una sola página,
    pero se revirtió a dos pestañas). Para 2026, usa 'PTO 2026'/'2026 Real'
    de Ingresos y 'Base'/'Real' de Nómina según `usar_real`; 2025 y 2027 son
    iguales en ambas páginas (no tienen versión Real todavía). Las keys de
    los widgets llevan sufijo para no chocar entre páginas."""
    clave_ing_2026 = "2026_real" if usar_real else "2026"
    clave_nomina_2026 = "2026_real" if usar_real else "2026"
    etiqueta_2026 = "Real" if usar_real else "PTO"

    st.title("Nómina Ancora")
    st.caption("Cómo se comportó el costo de nómina entre 2025 y 2027.")
    if usar_real:
        st.caption("Vista REAL de 2026: Ingresos de la pestaña '2026 Real' y "
                   "Nómina de la pestaña 'Real' del Sheet de Nómina 2026 (lo "
                   "realmente pagado mes a mes, no la plantilla de 'Base'). "
                   "2025 y 2027 son iguales que en \"General\" -- no tienen "
                   "versión Real todavía.")
    else:
        st.caption("Cada año viene de un archivo propio con su propio esquema de "
                   "columnas (no es la misma hoja repetida) -- 2025 y 2027 están "
                   "confirmados con el usuario, incluyendo las diferencias de "
                   "magnitud que puedan verse raras a primera vista.")

    if RESUMEN_ANUAL["2025"]["costo"] is None or RESUMEN_ANUAL["2027"]["costo"] is None:
        st.warning("No se pudo cargar 2025 y/o 2027 -- revisa que los Sheets "
                   "sigan compartidos \"cualquiera con el link\".")

    cols = st.columns(3)
    for i, (col, a) in enumerate(zip(cols, años)):
        costo = RESUMEN_ANUAL[a]["costo"]
        hc = RESUMEN_ANUAL[a]["hc"]
        anterior = RESUMEN_ANUAL[años[i - 1]] if i > 0 else None
        with col, st.container(border=True):
            # Esta tarjeta es puro costo de Nómina -- no tiene versión PTO/Real
            # (solo Ingresos la tiene), así que el botón de arriba no la
            # cambia; por eso NO lleva la etiqueta "(PTO)"/"(Real)" (quitada
            # 2026-11-16 porque confundía: parecía que la cifra iba a cambiar).
            st.markdown(f"##### {a}")
            if costo is None:
                st.metric("Costo anual", "—")
                st.metric("Colaboradores", "—")
            else:
                # Crecimiento vs el año anterior (2025 es el primero, sin
                # comparación posible). Mismo criterio que la gráfica
                # "Por área" de Town Hall.
                crec_costo = crec_hc = None
                if anterior is not None and anterior["costo"]:
                    crec_costo = pct((costo - anterior["costo"]) / anterior["costo"])
                if anterior is not None and anterior["hc"]:
                    crec_hc = pct((hc - anterior["hc"]) / anterior["hc"])
                st.metric("Costo anual", fmt(costo), delta=crec_costo)
                st.metric("Colaboradores", hc, delta=crec_hc)

    st.divider()
    st.subheader("Nómina como % de ingresos")
    st.caption("Ingresos: pestaña 'Ingresos' del Sheet de Town Hall (2027 usa "
               "'PTO 2027', presupuesto).")
    cols_ing = st.columns(3)
    for col, a in zip(cols_ing, años):
        clave_ing = clave_ing_2026 if a == "2026" else a
        clave_nomina = clave_nomina_2026 if a == "2026" else a
        ingreso_a = INGRESOS_ANUAL.get(clave_ing)
        costo_a = RESUMEN_ANUAL[clave_nomina]["costo"]
        etiqueta_ing = f"Ingresos ({etiqueta_2026})" if a == "2026" else "Ingresos"
        etiqueta_nom = f"Nómina ({etiqueta_2026})" if a == "2026" else "Nómina"
        with col, st.container(border=True):
            st.markdown(f"##### {a}")
            if ingreso_a is None or costo_a is None:
                st.metric(etiqueta_ing, "—")
                st.metric(etiqueta_nom, "—")
                st.metric("Nómina / Ingresos", "—")
            else:
                st.metric(etiqueta_ing, fmt(ingreso_a))
                st.metric(etiqueta_nom, fmt(costo_a))
                st.metric("Nómina / Ingresos", pct_plain(costo_a / ingreso_a))

    st.divider()
    st.subheader("Nómina vs ingresos por línea de negocio")
    st.caption("Solo las líneas con ingreso propio en el Sheet de Town Hall "
               "(Affinity, Autos, Beneficios, Daños, Garantías, Líneas "
               "Financieras, Líneas Personales) -- el resto de las áreas de "
               "Nómina son departamentos internos sin ingreso directo.")
    año_linea_sel = st.selectbox("Año", años, index=años.index("2026"), key=f"año_linea_sel_{sufijo}")
    clave_ing_linea = clave_ing_2026 if año_linea_sel == "2026" else año_linea_sel
    clave_nomina_linea = clave_nomina_2026 if año_linea_sel == "2026" else año_linea_sel
    lineas_ing = INGRESOS_POR_LINEA.get(clave_ing_linea, {})
    costo_año_linea = RESUMEN_ANUAL[clave_nomina_linea]["por_area"]
    lineas_orden = sorted(lineas_ing.keys(), key=lambda l: -lineas_ing.get(l, 0))

    if not lineas_orden:
        st.warning(f"No se pudo cargar Ingresos de {año_linea_sel}.")
    else:
        filas_linea = []
        tabla_linea = []
        for l in lineas_orden:
            ingreso_l = lineas_ing.get(l, 0.0)
            nomina_l = costo_año_linea.get(l, 0.0)
            filas_linea.append({"x": l, "serie": "Ingresos", "valor": ingreso_l})
            filas_linea.append({"x": l, "serie": "Nómina", "valor": nomina_l})
            tabla_linea.append({"Línea": l, "Ingresos": ingreso_l, "Nómina": nomina_l,
                                 "Nómina / Ingresos": (nomina_l / ingreso_l) if ingreso_l else None})

        _area_lineas_component(filas=filas_linea, series=["Ingresos", "Nómina"],
                                colores={"Ingresos": "#7a9e6e", "Nómina": MARCA_ORO},
                                tipos={"Nómina": "line"}, default=None, key=f"linea_negocio_{sufijo}")

        tabla_df = pd.DataFrame(tabla_linea)
        tabla_df["Ingresos"] = tabla_df["Ingresos"].map(fmt)
        tabla_df["Nómina"] = tabla_df["Nómina"].map(fmt)
        tabla_df["Nómina / Ingresos"] = tabla_df["Nómina / Ingresos"].map(pct_plain)
        st.dataframe(tabla_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Costo por área, por año")
    areas_tend = sorted(set().union(*[RESUMEN_ANUAL[a]["por_area"].keys() for a in años]),
                        key=lambda ar: -RESUMEN_ANUAL["2026"]["por_area"].get(ar, 0))
    COLOR_AREA_TEND = {ar: color_for(i) for i, ar in enumerate(areas_tend)}

    area_lineas_sel = st.selectbox("Área", ["Todas"] + areas_tend, key=f"area_lineas_sel_{sufijo}")

    if area_lineas_sel == "Todas":
        # None (no 0) cuando un área no existe ese año -- así Recharts deja
        # un hueco (connectNulls) en vez de dibujar una caída falsa a cero.
        filas_lineas = [
            {"x": a, "serie": ar, "valor": RESUMEN_ANUAL[a]["por_area"].get(ar)}
            for a in años for ar in areas_tend
        ]
        _area_lineas_component(filas=filas_lineas, series=areas_tend, colores=COLOR_AREA_TEND,
                                default=None, key=f"area_lineas_{sufijo}")
        st.caption("Una barra por área y año -- el costo anual de esa área en cada uno de los 3 años.")
    else:
        # Al elegir un área, el eje X cambia de Año a Departamento (dentro
        # de esa área) y cada serie/barra pasa a ser un año -- 2025/2027
        # también traen columna Departamento, aunque con otro esquema.
        # None (no 0) cuando ese departamento no existe ese año, mismo
        # criterio que arriba.
        def _valor_depto(a, d):
            s = RESUMEN_DEPTO_ANUAL[a]
            if not isinstance(s.index, pd.MultiIndex):
                return None
            v = s.get((area_lineas_sel, d))
            return float(v) if v is not None else None

        deptos_sel = set()
        for a in años:
            s = RESUMEN_DEPTO_ANUAL[a]
            if isinstance(s.index, pd.MultiIndex) and area_lineas_sel in s.index.get_level_values(0):
                deptos_sel.update(s.loc[area_lineas_sel].index.tolist())
        deptos_sel = sorted(deptos_sel, key=lambda d: -(_valor_depto("2026", d) or 0))

        filas_lineas = [
            {"x": d, "serie": a, "valor": _valor_depto(a, d)}
            for d in deptos_sel for a in años
        ]
        _area_lineas_component(filas=filas_lineas, series=años, colores=COLOR_AÑO,
                                default=None, key=f"area_lineas_{sufijo}")
        st.caption(f"Departamentos de {area_lineas_sel} -- una barra por año (2025/2026/2027). "
                   "Sin barra = ese departamento no existía ese año.")

    st.divider()
    st.subheader("Detalle 2026")
    st.caption("Promedios por colaborador -- solo disponibles en el archivo "
               "2026, que trae vales y GMM desglosados por persona.")

    costo_total = DF["Costo Anual"].sum()
    nomina_mensual = DF["Nómina Mensual"].sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Nómina mensual total", fmt(nomina_mensual))
    c2.metric("Nómina mensual promedio", fmt(nomina_mensual / len(DF)))
    c3.metric("Costo anual promedio", fmt(costo_total / len(DF)))
    c4.metric("% carga social promedio", pct_plain(DF["Pct Carga Social"].mean()))
    c5.metric("GMM promedio (quien lo tiene)", fmt(DF.loc[DF["GMM"] > 0, "GMM"].mean()))

if pagina == "General":
    render_general("gen", usar_real=False)
if pagina == "General 2026 Real":
    render_general("real", usar_real=True)

# ══════════════════════════════════════════════════════════════════════════════
# POR ÁREA
# ══════════════════════════════════════════════════════════════════════════════
if pagina == "Por Área":
    st.title("Nómina por área")
    año_area_sel = st.selectbox("Año", años, index=años.index("2026"), key="año_area_sel")
    agg_año = AGG_AREA_DEPTO_AÑO[año_area_sel]

    if agg_año.empty:
        st.warning(f"No se pudo cargar el archivo de {año_area_sel}.")
        st.stop()

    por_area = agg_año.groupby("Área").agg(Costo_Anual=("Costo", "sum"),
                                            Colaboradores=("Colaboradores", "sum")).reset_index()
    por_area = por_area.sort_values("Costo_Anual", ascending=False)
    por_area["Etiqueta"] = por_area["Costo_Anual"].map(fmt)

    st.subheader("Costo anual por área")
    chart_area = alt.Chart(por_area).encode(
        y=alt.Y("Área:N", sort=por_area["Área"].tolist(), title=None),
        x=alt.X("Costo_Anual:Q", title=None, axis=EJE_DOLAR),
        color=alt.Color("Área:N", scale=alt.Scale(domain=por_area["Área"].tolist(),
                         range=[color_for(i) for i in range(len(por_area))]), legend=None),
        tooltip=[alt.Tooltip("Área:N"), alt.Tooltip("Etiqueta:N", title="Costo anual"),
                 alt.Tooltip("Colaboradores:Q", title="Colaboradores")],
    )
    barras = chart_area.mark_bar(cornerRadiusEnd=2)
    texto = chart_area.mark_text(align="left", baseline="middle", fontSize=10, dx=4,
                                  color=EJE_COLOR).encode(text="Etiqueta:N")
    st.altair_chart(estilizar((barras + texto).properties(height=max(320, 26 * len(por_area)))),
                    use_container_width=True)

    st.divider()
    st.subheader("Desglose por departamento, dentro de un área")
    area_sel = st.selectbox("Área", por_area["Área"].tolist(), key="area_sel")
    df_a = agg_año[agg_año["Área"] == area_sel]
    por_depto = df_a.rename(columns={"Costo": "Costo_Anual"}).sort_values("Costo_Anual", ascending=False)
    por_depto["Etiqueta"] = por_depto["Costo_Anual"].map(fmt)

    c1, c2 = st.columns([2, 1])
    with c1:
        chart_depto = alt.Chart(por_depto).encode(
            y=alt.Y("Departamento:N", sort=por_depto["Departamento"].tolist(), title=None),
            x=alt.X("Costo_Anual:Q", title=None, axis=EJE_DOLAR),
            tooltip=[alt.Tooltip("Departamento:N"), alt.Tooltip("Etiqueta:N", title="Costo anual"),
                     alt.Tooltip("Colaboradores:Q", title="Colaboradores")],
        )
        barras_d = chart_depto.mark_bar(cornerRadiusEnd=2, color=MARCA_TEAL)
        texto_d = chart_depto.mark_text(align="left", baseline="middle", fontSize=10, dx=4,
                                         color=EJE_COLOR).encode(text="Etiqueta:N")
        st.altair_chart(estilizar((barras_d + texto_d).properties(
            height=max(220, 28 * len(por_depto)))), use_container_width=True)
    with c2:
        st.metric(f"Colaboradores en {area_sel}", int(df_a["Colaboradores"].sum()))
        st.metric("Costo anual del área", fmt(df_a["Costo"].sum()))
        st.metric("% del costo total de nómina", pct_plain(df_a["Costo"].sum() / por_area["Costo_Anual"].sum()))

    st.divider()
    st.subheader("Detalle por colaborador")
    st.caption("Información confidencial de sueldo y prestaciones -- uso interno. "
               "Solo 2026 trae el desglose mensual completo (Nómina/Carga Social/"
               "Vales/GMM/Sustitución); 2025 y 2027 solo traen el costo anual.")

    tabla_año = DETALLE_AÑO[año_area_sel]
    c3, c4 = st.columns([1, 2])
    with c3:
        det_area_f = st.selectbox("Área", ["Todas"] + por_area["Área"].tolist(), key="det_area")
    with c4:
        det_busca = st.text_input("Buscar colaborador", key="det_busca", placeholder="Nombre...")

    tabla = tabla_año.copy()
    if det_area_f != "Todas":
        tabla = tabla[tabla["Área"] == det_area_f]
    if det_busca:
        tabla = tabla[tabla["Colaborador"].str.upper().str.contains(det_busca.upper(), na=False)]

    tabla = tabla.sort_values("Costo Anual", ascending=False)
    cols_moneda = [c for c in ["Nómina Mensual", "Carga Social Mensual", "Vales", "GMM", "Costo Anual"]
                   if c in tabla.columns]
    mostrar = tabla.copy()
    for c in cols_moneda:
        mostrar[c] = mostrar[c].map(fmt)

    st.caption(f"{len(tabla)} de {len(tabla_año)} colaboradores -- {año_area_sel}")
    st.dataframe(mostrar, use_container_width=True, hide_index=True, height=560)
