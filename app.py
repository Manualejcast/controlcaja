"""
Control de Caja — Restaurante
Registro de ingresos, propinas, USDT, IVA, retenciones y conciliación.
"""

import inspect
import io
import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

BCV_URL = "https://www.bcv.org.ve/"
BCV_HISTORICO_API = "https://bcv.today/api/v1/history/{fecha}.json"
BCV_HISTORICO_API_RESPALDO = "https://bcv-api.rafnixg.dev/rates/{fecha}"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "caja_restaurante.db"
LOGO_SIDEBAR = BASE_DIR / "logo_giardino.jpg"

MONEDAS = ["USD (Dólares)", "Bs (Bolívares)", "USDT (Tether)"]

BANCOS_VENEZUELA = sorted([
    "100% Banco",
    "Banco Activo",
    "Banco Agrícola de Venezuela",
    "Banco Bicentenario del Pueblo",
    "Banco Caroní",
    "Banco de Venezuela",
    "Banco del Tesoro",
    "Banco Digital de Los Trabajadores",
    "Banco Exterior de Venezuela",
    "Banco Internacional de Desarrollo",
    "Banco Mercantil",
    "Banco Nacional de Crédito (BNC)",
    "Banco Plaza",
    "Banco Sofitasa",
    "Banco Venezolano de Crédito (BVC)",
    "Bancamiga",
    "Bancaribe",
    "Bancrecer",
    "Banesco",
    "Banfanb",
    "Banplus",
    "Bantrab",
    "BBVA Provincial",
    "BFC Banco Fondo Común",
    "DelSur Banco Universal",
    "Instituto Municipal de Crédito Popular (IMCP)",
    "Mi Banco",
    "N58 Banco Digital",
])

CANALES_DIGITALES = [
    "Zelle",
    "Binance / USDT",
    "Pago Móvil",
    "Punto de venta (POS)",
    "Efectivo en caja",
    "Otro canal",
]

TODOS_BANCOS = sorted(set(BANCOS_VENEZUELA + CANALES_DIGITALES))

# ── Identidad visual Il Giardino ──
GIARDINO_SUCCESS = "#10B981"   # Verde oliva / esmeralda — positivos e ingresos
GIARDINO_BG      = "#1a1f2e"   # Gris pizarra oscuro — fondo general
GIARDINO_CARD    = "#252b3b"   # Gris intermedio — tarjetas KPI
GIARDINO_TEXT    = "#FFFFFF"   # Blanco puro — montos principales
GIARDINO_MUTED   = "#8B95A8"   # Gris medio — etiquetas secundarias
GIARDINO_SUBTLE  = "#6B7280"   # Gris tenue — metadatos y ejes

# ── Sistema de color semántico (auditoría de diseño) ──
GIARDINO_BRAND_GREEN = "#2F5233"  # Verde oscuro de marca (logo)
GIARDINO_BANK        = "#10B981"  # Verde — banco / ingresos confirmados
GIARDINO_CASH        = "#E8762D"  # Naranja — efectivo / caja
GIARDINO_EXPENSE     = "#D64545"  # Rojo — egresos (uso exclusivo)
GIARDINO_RECEIVABLE  = "#3B82F6"  # Azul — cuentas por cobrar / pendiente

TIPOS_MOVIMIENTO = {
    "Ingreso bancario": {
        "icono": "🏦",
        "icono_mat": "account_balance",
        "descripcion": "Transferencia o depósito que llegó a una cuenta bancaria.",
        "requiere_banco": True,
        "requiere_referencia": True,
        "moneda_default": "USD (Dólares)",
        "color": GIARDINO_SUCCESS,
    },
    "Propina": {
        "icono": "🎁",
        "icono_mat": "redeem",
        "descripcion": "Propina recibida por el personal (registros históricos).",
        "requiere_banco": False,
        "requiere_referencia": False,
        "moneda_default": "USD (Dólares)",
        "color": GIARDINO_CASH,
        "solo_historial": True,
    },
    "Pago USDT": {
        "icono": "₮",
        "icono_mat": "currency_bitcoin",
        "descripcion": "Pago recibido en criptomoneda USDT (Binance, wallet, etc.).",
        "requiere_banco": False,
        "requiere_referencia": True,
        "moneda_default": "USDT (Tether)",
        "color": "#0F766E",
    },
    "IVA": {
        "icono": "📋",
        "icono_mat": "receipt_long",
        "descripcion": "IVA cobrado o registrado en operaciones del día.",
        "requiere_banco": False,
        "requiere_referencia": False,
        "moneda_default": "Bs (Bolívares)",
        "color": GIARDINO_SUBTLE,
    },
    "Retención de IVA": {
        "icono": "📉",
        "icono_mat": "percent",
        "descripcion": "IVA retenido por un cliente o ente (agente de retención).",
        "requiere_banco": False,
        "requiere_referencia": False,
        "moneda_default": "Bs (Bolívares)",
        "color": "#8B95A8",
    },
    "Retención ISLR": {
        "icono": "📊",
        "icono_mat": "account_balance_wallet",
        "descripcion": "Retención de impuesto sobre la renta aplicada a facturas.",
        "requiere_banco": False,
        "requiere_referencia": False,
        "moneda_default": "Bs (Bolívares)",
        "color": "#4B5563",
    },
    "Zelle / Digital": {
        "icono": "💸",
        "icono_mat": "send",
        "descripcion": "Ingreso por Zelle u otro canal digital internacional.",
        "requiere_banco": False,
        "requiere_referencia": True,
        "moneda_default": "USD (Dólares)",
        "color": "#059669",
    },
    "Efectivo en caja": {
        "icono": "💵",
        "icono_mat": "payments",
        "descripcion": "Dinero en efectivo que quedó en la caja física del restaurante.",
        "requiere_banco": False,
        "requiere_referencia": False,
        "moneda_default": "USD (Dólares)",
        "color": GIARDINO_CASH,
    },
    "Otro ingreso": {
        "icono": "➕",
        "icono_mat": "add_circle",
        "descripcion": "Cualquier otro ingreso no clasificado arriba.",
        "requiere_banco": False,
        "requiere_referencia": False,
        "moneda_default": "USD (Dólares)",
        "color": GIARDINO_SUBTLE,
    },
}


def tipos_para_registro():
    """Categorías disponibles al registrar (sin Propina — se maneja aparte)."""
    return [t for t, info in TIPOS_MOVIMIENTO.items() if not info.get("solo_historial")]


def canales_ingreso_legacy():
    """Valores históricos de `tipo` que representan canal/método, no concepto contable."""
    return frozenset(tipos_para_registro()) | frozenset(
        t for t in TIPOS_MOVIMIENTO if t != "Propina"
    )


def icono_mat_html(nombre):
    """Glifo Material Symbols para HTML embebido (clase .mi)."""
    return f'<span class="mi">{nombre}</span>'


def tipo_icono_mat(tipo):
    return TIPOS_MOVIMIENTO.get(tipo, {}).get("icono_mat", "label")


def tipo_etiqueta_html(tipo):
    return f'{icono_mat_html(tipo_icono_mat(tipo))} {tipo}'


def page_header_html(titulo, subtitulo, icono_mat):
    return (
        f'<div class="page-header"><h2>{icono_mat_html(icono_mat)} {titulo}</h2>'
        f'<p>{subtitulo}</p></div>'
    )


def bcv_badge_html(sync_ok):
    if sync_ok:
        return f'{icono_mat_html("sync")} Sincronizado'
    return f'{icono_mat_html("edit")} Manual / pendiente'


COMISION_POS_PORCENTAJE = 0.05
IVA_PORCENTAJE = 0.16
TASA_BCV_RESPALDO = 607.39
MONEDAS_SALDO = ("usd", "bs", "usdt")

ESTADO_PAGADO = "Pagado"
ESTADO_CUENTA_ABIERTA = "Cuenta Abierta"

OPCIONES_ESTADO_COBRO = [
    ":material/check_circle: Pagado al momento",
    ":material/schedule: Cuenta Abierta (Paga luego)",
]

CANALES_CIERRE_CUENTA = {
    "Efectivo": ("Efectivo en caja", ""),
    "Punto / POS": ("Punto de venta (POS)", "POS / Tarjeta"),
    "Zelle / Digital": ("Zelle", ""),
}

# Métodos unificados para cobrar cuentas abiertas (ingreso bancario + efectivo/digital)
METODOS_COBRO_CLIENTE = {
    "TRANSFERENCIA": {
        "label": "Transferencia",
        "banco": "Transferencia Bancaria",
        "metodo": "TRANSFERENCIA",
        "moneda_default": "Bs (Bolívares)",
    },
    "PAGO MÓVIL": {
        "label": "Pago Móvil",
        "banco": "Pago Móvil",
        "metodo": "PAGO MÓVIL",
        "moneda_default": "Bs (Bolívares)",
    },
    "POS / Tarjeta": {
        "label": "POS / Tarjeta",
        "banco": "Punto de venta (POS)",
        "metodo": "POS / Tarjeta",
        "moneda_default": "Bs (Bolívares)",
    },
    "Efectivo en caja": {
        "label": "Efectivo en caja",
        "banco": "Efectivo en caja",
        "metodo": "",
        "moneda_default": "USD (Dólares)",
    },
    "Zelle / Digital": {
        "label": "Zelle / Digital",
        "banco": "Zelle",
        "metodo": "",
        "moneda_default": "USD (Dólares)",
    },
}

TIPO_MOV_INGRESO = "Ingreso"
TIPO_MOV_EGRESO = "Egreso"
TIPO_MOV_PROPINA = "Propina"
TIPOS_NATURALEZA = (TIPO_MOV_INGRESO, TIPO_MOV_EGRESO, TIPO_MOV_PROPINA)

CATEGORIA_INGRESO_DEFAULT = "Venta de Comida"
CATEGORIA_PROPINA = "Propina al personal"

MONEDAS_EGRESO = ["Bs (Bolívares)", "USD (Dólares)"]

CATEGORIAS_GASTO = [
    "Proveedores / Materia Prima",
    "Servicios (Luz, Agua, Internet)",
    "Nómina / Personal",
    "Mantenimiento",
    "Otros",
]

COLORES_GASTO = {
    "Proveedores / Materia Prima": "#D64545",
    "Servicios (Luz, Agua, Internet)": "#B83A3A",
    "Nómina / Personal": "#E07A7A",
    "Mantenimiento": "#C25555",
    "Otros": "#9CA3AF",
}


def categorias_concepto_lista():
    """Conceptos contables válidos para filtros y formularios."""
    return sorted(set(CATEGORIAS_GASTO + [CATEGORIA_INGRESO_DEFAULT, CATEGORIA_PROPINA]))


CUENTAS_SALIDA = sorted(set(["Efectivo en caja"] + TODOS_BANCOS))

GIARDINO_BG_LIGHT   = "#f7f5f0"   # Fondo principal — blanco almendra suave
GIARDINO_SIDEBAR    = "#1a2332"   # Barra lateral oscura
GIARDINO_CARD_LIGHT = "#ffffff"   # Tarjetas blancas
GIARDINO_TEXT_DARK  = "#111827"   # Texto principal sobre fondo claro

MENU_NAVEGACION = [
    ("panel", "Panel del día", ":material/dashboard:"),
    ("nuevo", "Nuevo movimiento", ":material/add_circle:"),
    ("propinas", "Propinas", ":material/redeem:"),
    ("egreso", "Egresos / Gastos", ":material/payments:"),
    ("cobrar", "Cuentas por cobrar", ":material/account_balance_wallet:"),
    ("clientes", "Base de Clientes", ":material/groups:"),
    ("historial", "Historial", ":material/history:"),
    ("corregir", "Corregir / Eliminar", ":material/edit_square:"),
]

NAV_PANEL_VISIBLE_KEY = "nav_panel_visible"

PALETA_GRAFICOS = [
    GIARDINO_BANK,
    GIARDINO_BRAND_GREEN,
    GIARDINO_CASH,
    "#6B7280",
    "#059669",
    "#8B95A8",
    "#4B5563",
    "#9CA3AF",
]


def aplicar_estilos():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* ══ TEMA IL GIARDINO — sistema de diseño unificado ══
           Marca   = verde oscuro #2F5233 (headers, botones, menú activo)
           Banco   = verde esmeralda #10B981 (ingresos confirmados)
           Efectivo= naranja #E8762D (caja)
           Egresos = rojo #D64545 (exclusivo)
           Bordes finos (3px) o íconos. Nunca fondo saturado de tarjeta. */
        :root {
            --brand:       #2F5233;
            --brand-soft:  rgba(47, 82, 51, 0.10);
            --brand-border:rgba(47, 82, 51, 0.45);
            --bank:        #10B981;
            --cash:        #E8762D;
            --expense:     #D64545;
            --receivable:  #3B82F6;
            --success:     #10B981;
            --bg-main:     #f7f5f0;
            --bg-card:     #ffffff;
            --border-card: #e5e7eb;
            --text-main:   #111827;
            --text-muted:  #6b7280;
            --text-subtle: #9ca3af;
            --sidebar-bg:  #1a2332;
            --radius-card: 14px;
            --pad-card:    1.25rem 1.5rem;
            --shadow-card: 0 1px 3px rgba(15, 23, 42, 0.06), 0 4px 14px rgba(15, 23, 42, 0.05);
        }

        .stApp {
            background: var(--bg-main) !important;
        }

        [data-testid="stAppViewContainer"] {
            background: var(--bg-main) !important;
        }

        [data-testid="stMain"] {
            background: var(--bg-main) !important;
        }

        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
            color: var(--text-main);
        }

        .block-container {
            padding: 1.5rem 2rem 2.5rem 2rem;
            max-width: 1480px;
        }

        header[data-testid="stHeader"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }

        #MainMenu { visibility: hidden; }
        footer    { visibility: hidden; }

        /* Ocultar sidebar nativo de Streamlit (navegación en panel propio) */
        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }

        /* ── Botón compacto alternar menú ── */
        .header-toggle-col .stButton > button {
            width: 2.35rem !important;
            min-width: 2.35rem !important;
            height: 2.35rem !important;
            padding: 0 !important;
            background: var(--bg-card) !important;
            border: 1px solid var(--border-card) !important;
            color: var(--text-main) !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            font-size: 1rem !important;
            line-height: 1 !important;
            box-shadow: none !important;
        }

        .header-toggle-col .stButton > button:hover {
            border-color: var(--brand-border) !important;
            background: var(--brand-soft) !important;
        }

        .header-toggle-col .stButton > button p {
            display: none !important;
        }

        .header-toggle-col .stButton > button [data-testid="stIconMaterial"] {
            font-size: 1.2rem !important;
            margin: 0 !important;
        }

        /* ── Header unificado del panel ── */
        span.panel-header-anchor + div[data-testid="stHorizontalBlock"] {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-left: 3px solid var(--brand);
            border-radius: var(--radius-card);
            padding: 0.85rem 1.15rem;
            margin-bottom: 1rem;
            box-shadow: var(--shadow-card);
            align-items: center !important;
        }

        .header-brand-block {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .header-brand-block .app-header-title {
            font-size: 1.35rem;
            font-weight: 700;
            line-height: 1.2;
            color: var(--text-main);
            margin: 0;
        }

        .header-brand-block .app-header-sub {
            font-size: 0.9rem;
            color: var(--text-muted);
            margin: 0.15rem 0 0 0;
        }

        .header-date-col div[data-testid="stDateInput"] {
            margin-bottom: 0 !important;
        }

        .header-date-col div[data-testid="stDateInput"] > div {
            justify-content: flex-end;
        }

        div[data-testid="stDateInput"] input {
            background-color: #FFFFFF !important;
            color: #1a1a1a !important;
            border: 1px solid #D0D0D0 !important;
            border-radius: 8px !important;
        }

        div[data-testid="stDateInput"] label {
            color: #666666 !important;
            font-size: 13px !important;
        }

        .page-top-toggle {
            margin-bottom: 0.75rem;
        }

        /* ── Panel de navegación lateral (fondo verde oliva, panel real) ── */
        div[data-testid$="olumn"]:has(.nav-panel-marker) {
            background: linear-gradient(180deg, #6B7A45 0%, #515E33 100%) !important;
            border-radius: 0 16px 16px 0 !important;
            /* extiende el verde hasta los bordes del contenedor (izq + arriba + abajo) */
            margin: -1.5rem 0 -2.5rem -2rem !important;
            padding: 1.5rem 0.85rem 2rem 1.75rem !important;
            box-shadow: 4px 0 24px rgba(15, 23, 42, 0.18);
            align-self: stretch;
            position: sticky;
            top: 0;
            min-height: 100vh !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) [data-testid="stMarkdown"] p,
        div[data-testid$="olumn"]:has(.nav-panel-marker) .stCaption {
            color: rgba(255, 255, 255, 0.72) !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) hr {
            border-color: rgba(255,255,255,0.14) !important;
            margin: 0.75rem 0 !important;
        }

        /* ── Navegación con botones (íconos grandes, texto claro) ── */
        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton {
            margin-bottom: 3px !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton > button {
            width: 100% !important;
            justify-content: flex-start !important;
            text-align: left !important;
            background: transparent !important;
            border: none !important;
            border-left: 3px solid transparent !important;
            border-radius: 8px !important;
            color: rgba(255, 255, 255, 0.82) !important;
            padding: 0.6rem 0.85rem !important;
            box-shadow: none !important;
            transition: all 0.15s ease;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton > button p {
            font-size: 1.02rem !important;
            font-weight: 500 !important;
            color: inherit !important;
            letter-spacing: 0.01em;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton > button:hover {
            background: rgba(255, 255, 255, 0.08) !important;
            color: #ffffff !important;
            border-left-color: transparent !important;
        }

        /* Ítem activo: resaltado claro sobre el verde, no botón sólido aparte */
        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton > button[kind="primary"] {
            background: rgba(255, 255, 255, 0.16) !important;
            border-left: 3px solid #ffffff !important;
            color: #ffffff !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton > button[kind="primary"] p {
            font-weight: 700 !important;
            color: #ffffff !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .stButton > button[kind="primary"]:hover {
            background: rgba(255, 255, 255, 0.22) !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) div[role="radiogroup"] {
            gap: 2px !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) div[role="radiogroup"] > label {
            background: transparent !important;
            padding: 0.62rem 0.75rem !important;
            margin: 0 !important;
            border-radius: 8px !important;
            border-left: 3px solid transparent !important;
            font-weight: 500 !important;
            font-size: 0.88rem !important;
            color: #94a3b8 !important;
            transition: all 0.15s ease;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) div[role="radiogroup"] > label:has(input:checked) {
            background: rgba(47, 82, 51, 0.38) !important;
            border-left: 3px solid #5f9168 !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            color: #f8fafc !important;
        }

        [data-testid="stSidebarNav"] a[aria-current="page"] {
            background-color: rgba(47, 82, 51, 0.1) !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) div[role="radiogroup"] > label:hover {
            background: rgba(255, 255, 255, 0.04) !important;
            color: #e2e8f0 !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) div[role="radiogroup"] label > div:first-child {
            display: none !important;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .sidebar-subtitle {
            color: rgba(255, 255, 255, 0.6) !important;
            font-size: 0.72rem !important;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin: -0.25rem 0 1rem 0 !important;
            padding: 0 0.25rem;
        }

        /* ── Cabecera (contenido) ── */
        .app-header {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-left: 3px solid var(--brand);
            border-radius: var(--radius-card);
            padding: 1.1rem 1.5rem;
            margin-bottom: 0.5rem;
            box-shadow: var(--shadow-card);
        }

        .app-header-title {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.15;
            color: var(--text-main);
            margin: 0;
        }

        .app-header-sub {
            font-size: 1rem;
            color: var(--text-muted);
            margin: 0.35rem 0 0 0;
        }

        /* ── Tarjeta base unificada (mismo radio, borde y padding en TODAS las páginas) ── */
        .dash-panel,
        .glass-panel {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: var(--radius-card);
            padding: var(--pad-card);
            margin-bottom: 16px;
            box-shadow: var(--shadow-card);
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--bg-card) !important;
            border: 1px solid var(--border-card) !important;
            border-radius: var(--radius-card) !important;
            padding: var(--pad-card) !important;
            box-shadow: var(--shadow-card) !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"]:has(.accent-marker.accent-egresos) {
            border-left: 3px solid var(--expense) !important;
        }

        .accent-marker, .reg-pill-marker { display: none; }

        .page-header h2 .mi {
            font-size: 1.35rem;
            margin-right: 0.15rem;
            vertical-align: -3px;
        }

        /* Columnas-tarjeta (registro): fondo blanco real, contenido dentro */
        [data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .reg-card-marker) {
            background: var(--bg-card) !important;
            border: 1px solid var(--border-card) !important;
            border-radius: var(--radius-card) !important;
            box-shadow: var(--shadow-card) !important;
        }
        .reg-card-marker { display: none; }

        /* Ícono Material embebido en HTML (perfil profesional) */
        .mi {
            font-family: 'Material Symbols Rounded';
            font-weight: normal;
            font-style: normal;
            line-height: 1;
            letter-spacing: normal;
            text-transform: none;
            display: inline-block;
            vertical-align: middle;
            white-space: nowrap;
            direction: ltr;
            -webkit-font-feature-settings: 'liga';
            -webkit-font-smoothing: antialiased;
            font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
            position: relative;
            top: -1px;
        }

        .kpi-row { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }

        .accent-ventas { border-left: 3px solid var(--bank); }
        .accent-propinas { border-left: 3px solid var(--cash); }
        .accent-egresos { border-left: 3px solid var(--expense); }
        .accent-brand { border-left: 3px solid var(--brand); }
        .accent-cobrar { border-left: 3px solid var(--receivable); }

        .kpi-cobrar-top-item {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 0.35rem 0;
            border-bottom: 1px solid var(--border-card);
            font-size: 0.88rem;
        }
        .kpi-cobrar-top-item:last-child { border-bottom: none; }
        .kpi-cobrar-top-name { color: var(--text-main); font-weight: 500; }
        .kpi-cobrar-top-amount { color: var(--receivable); font-weight: 600; }
        .kpi-cobrar-link-wrap { margin-top: 0.75rem; font-size: 0.88rem; }

        .dash-panel-hero {
            border-left: none !important;
        }
        .dash-panel-hero.accent-egresos {
            border-left: 3px solid var(--expense) !important;
        }
        .dash-panel-hero.accent-propinas {
            border-left: 3px solid var(--cash) !important;
        }

        .empty-day-notice {
            color: var(--text-muted);
            font-size: 0.95rem;
            margin: -0.5rem 0 1rem 0;
            padding: 0.65rem 0.85rem;
            background: rgba(107, 114, 128, 0.08);
            border: 1px solid var(--border-card);
            border-radius: 10px;
        }

        .kpi-card-footer-delta {
            margin-top: 0.45rem;
            font-size: 0.88rem;
        }

        .kpi-label {
            font-size: 0.92rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.4rem;
        }

        .kpi-delta { font-size: 0.95rem; font-weight: 600; white-space: nowrap; }
        .kpi-delta.up   { color: var(--bank); }
        .kpi-delta.down { color: var(--text-muted); }
        .kpi-delta.neu  { color: var(--text-subtle); }

        .hero-metric-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
        }

        .hero-kpi-main {
            display: flex;
            align-items: center;
            gap: 1.15rem;
            flex: 1;
            min-width: 0;
        }

        .hero-logo {
            width: 56px;
            height: 56px;
            object-fit: contain;
            border-radius: 10px;
            flex-shrink: 0;
        }

        .hero-value {
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--text-main);
            line-height: 1.15;
            margin-top: 0.15rem;
        }

        .hero-context {
            font-size: 1rem;
            color: var(--text-muted);
            margin-top: 0.75rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border-card);
        }

        .kpi-grupo-title {
            font-size: 0.92rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.85rem;
        }

        .mini-stats-row {
            display: flex;
            gap: 1.5rem;
            flex-wrap: wrap;
        }

        .mini-stat { flex: 1; min-width: 90px; }
        .mini-stat-label { font-size: 0.88rem; color: var(--text-muted); margin-bottom: 0.3rem; }
        .mini-stat-value { font-size: 1.35rem; font-weight: 600; color: var(--text-main); }

        .stat-simple-value {
            font-size: 2rem;
            font-weight: 600;
            color: var(--text-main);
            margin: 0.35rem 0;
        }

        .stat-simple-label { font-size: 1rem; color: var(--text-muted); }

        .empty-chart-msg {
            color: var(--text-muted);
            font-size: 1rem;
            text-align: center;
            padding: 2.5rem 1rem;
            margin: 0;
        }

        /* Historial: scroll horizontal y notas legibles */
        .hist-table-wrap [data-testid="stDataFrame"],
        .hist-table-wrap [data-testid="stDataFrameResizable"] {
            overflow-x: auto !important;
        }
        .hist-table-wrap [data-testid="stDataFrame"] td,
        .hist-table-wrap [data-testid="stDataFrameResizable"] td {
            white-space: normal !important;
            word-break: break-word !important;
            max-width: 420px;
            vertical-align: top !important;
        }
        .hist-table-wrap [data-testid="stDataFrame"] th,
        .hist-table-wrap [data-testid="stDataFrameResizable"] th {
            white-space: nowrap !important;
        }

        .ingresos-usd-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95rem;
            margin-top: 0.75rem;
        }
        .ingresos-usd-table th,
        .ingresos-usd-table td {
            padding: 0.5rem 0.65rem;
            border-bottom: 1px solid var(--border-card);
            text-align: left;
        }
        .ingresos-usd-table th {
            color: var(--text-muted);
            font-weight: 600;
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .ingresos-usd-table td:last-child,
        .ingresos-usd-table th:last-child {
            text-align: right;
            font-weight: 600;
        }

        div[data-testid$="olumn"]:has(.nav-panel-marker) .sidebar-logo-wrap {
            background: #ffffff;
            border-radius: 12px;
            padding: 0.75rem 0.65rem;
            margin-bottom: 0.35rem;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
        }
        div[data-testid$="olumn"]:has(.nav-panel-marker) .sidebar-logo-wrap img {
            border-radius: 6px;
        }

        .kpi-section-label {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-subtle);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin: 0.5rem 0 0.75rem 0;
        }

        /* Ocultar leyenda Plotly fantasma */
        [data-testid="stPlotlyChart"] .legend,
        [data-testid="stPlotlyChart"] g.legend,
        [data-testid="stPlotlyChart"] .infolayer .legend,
        [data-testid="stPlotlyChart"] .plotly .legend,
        [data-testid="stPlotlyChart"] .gtitle,
        [data-testid="stPlotlyChart"] .infolayer .g-gtitle {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            overflow: hidden !important;
        }

        .panel-title {
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--text-main);
            margin-bottom: 0.15rem;
        }

        .panel-subtitle {
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-bottom: 0.75rem;
        }

        .page-header { margin-bottom: 1.25rem; }

        .page-header h2 {
            font-size: 1.65rem;
            font-weight: 700;
            color: var(--text-main);
            margin: 0 0 0.25rem 0;
        }

        .page-header p { color: var(--text-muted); margin: 0; font-size: 0.95rem; }

        .section-divider { border: none; border-top: 1px solid var(--border-card); margin: 1rem 0; }

        .hint-box {
            background: rgba(16, 185, 129, 0.07);
            border: 1px solid rgba(16, 185, 129, 0.22);
            border-radius: 12px;
            padding: 1rem 1.15rem;
            margin: 0.75rem 0 1rem 0;
            color: #047857;
            font-size: 0.88rem;
            line-height: 1.5;
        }

        .hint-box.info {
            background: rgba(232, 118, 45, 0.10);
            border-color: rgba(232, 118, 45, 0.35);
            color: #a85318;
        }

        .hint-box.warn {
            background: rgba(234, 179, 8, 0.10);
            border-color: rgba(234, 179, 8, 0.40);
            color: #854d0e;
        }

        .kpi-multi-delta {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 0.2rem;
            margin-top: 0.5rem;
        }

        .kpi-multi-delta .kpi-delta {
            font-size: 0.78rem;
        }

        .flujo-moneda-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.92rem;
            margin-top: 0.35rem;
        }

        .flujo-moneda-table th,
        .flujo-moneda-table td {
            padding: 0.45rem 0.55rem;
            text-align: right;
            border-bottom: 1px solid var(--border-card);
            color: var(--text-main);
        }

        .flujo-moneda-table th:first-child,
        .flujo-moneda-table td:first-child {
            text-align: left;
            color: var(--text-muted);
            font-weight: 600;
        }

        .kpi-section-label {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 8px;
        }

        /* ── Inputs (tema claro) ── */
        .stTextInput input, .stNumberInput input, .stTextArea textarea,
        div[data-baseweb="select"] > div {
            background: #ffffff !important;
            border-color: var(--border-card) !important;
            color: var(--text-main) !important;
            -webkit-text-fill-color: var(--text-main) !important;
            border-radius: 10px !important;
        }

        .stTextInput input:disabled, .stNumberInput input:disabled,
        div[data-baseweb="input"] input:disabled {
            color: var(--text-main) !important;
            -webkit-text-fill-color: var(--text-main) !important;
            opacity: 1 !important;
            background: #f3f4f6 !important;
        }

        label, .stMarkdown p, .stMarkdown span, .stMarkdown li,
        .stMarkdown ul, .stMarkdown strong,
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stMarkdownContainer"] strong,
        h1, h2, h3, h4 {
            color: var(--text-main) !important;
        }

        .stCaption, small { color: var(--text-muted) !important; font-size: 0.92rem !important; }

        div[data-testid="stMetric"] {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 0.85rem 1rem;
            box-shadow: var(--shadow-card);
        }

        div[data-testid="stMetric"] label { color: var(--text-muted) !important; }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--text-main) !important;
            font-weight: 600 !important;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--border-card);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: var(--shadow-card);
        }

        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primaryFormSubmit"] {
            background: var(--brand) !important;
            border: none !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            color: #ffffff !important;
            box-shadow: 0 2px 8px rgba(47, 82, 51, 0.30) !important;
        }

        .stButton > button[kind="primary"]:hover,
        .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {
            background: #25411f !important;
            box-shadow: 0 4px 14px rgba(47, 82, 51, 0.42) !important;
        }

        /* Botón de descarga Excel (Historial) — texto legible */
        .stDownloadButton > button {
            background: var(--brand) !important;
            border: none !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            color: #ffffff !important;
            box-shadow: 0 2px 8px rgba(47, 82, 51, 0.30) !important;
        }
        .stDownloadButton > button:hover {
            background: #25411f !important;
            color: #ffffff !important;
            box-shadow: 0 4px 14px rgba(47, 82, 51, 0.42) !important;
        }
        .stDownloadButton > button p,
        .stDownloadButton > button span,
        .stDownloadButton > button div,
        .stDownloadButton > button [data-testid="stMarkdownContainer"],
        .stDownloadButton > button [data-testid="stMarkdownContainer"] p {
            color: #ffffff !important;
        }

        /* Botones secundarios: legibles en cualquier tema (hover no oculta el texto) */
        .stButton > button[kind="secondary"] {
            background: #ffffff !important;
            color: var(--text-main) !important;
            border: 1px solid #d7dbe0 !important;
            box-shadow: none !important;
        }
        .stButton > button[kind="secondary"]:hover {
            background: var(--brand-soft) !important;
            color: var(--brand) !important;
            border-color: var(--brand) !important;
        }
        .stButton > button[kind="secondary"]:hover * {
            color: var(--brand) !important;
        }
        .stButton > button[kind="secondary"]:active,
        .stButton > button[kind="secondary"]:focus {
            color: var(--brand) !important;
            border-color: var(--brand) !important;
        }

        /* Tarjetas de categoría (cuadrícula) — ícono arriba y etiqueta debajo */
        [class*="st-key-reg_cat_"] .stButton > button,
        [class*="st-key-reg_btn_ayuda"] .stButton > button {
            min-height: 90px !important;
            line-height: 1.2 !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 0.4rem !important;
            padding: 0.6rem 0.35rem !important;
        }
        [class*="st-key-reg_cat_"] .stButton > button [data-testid="stMarkdownContainer"] p,
        [class*="st-key-reg_btn_ayuda"] .stButton > button [data-testid="stMarkdownContainer"] p {
            white-space: normal !important;
            overflow-wrap: break-word !important;
            word-break: normal !important;
            text-align: center !important;
            margin: 0 !important;
            font-size: 0.76rem !important;
            line-height: 1.2 !important;
        }
        [class*="st-key-reg_cat_"] .stButton > button [data-testid="stIconMaterial"],
        [class*="st-key-reg_btn_ayuda"] .stButton > button [data-testid="stIconMaterial"] {
            font-size: 1.6rem !important;
            width: auto !important;
            height: auto !important;
        }

        /* Método de cobro: texto en una línea junto al ícono */
        [class*="st-key-reg_met_"] .stButton > button [data-testid="stMarkdownContainer"] p {
            font-size: 0.76rem !important;
            white-space: nowrap !important;
            margin: 0 !important;
        }

        /* Switch / toggle visible en cualquier tema */
        [data-testid="stCheckbox"] [data-baseweb="checkbox"] > div:first-child {
            background-color: #cbd5e1 !important;
            border: 1px solid #94a3b8 !important;
        }
        [data-testid="stCheckbox"] [data-baseweb="checkbox"] > div:first-child > div {
            background-color: #ffffff !important;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.35) !important;
        }
        [data-testid="stCheckbox"] [data-baseweb="checkbox"]:has(input:checked) > div:first-child {
            background-color: var(--brand) !important;
            border-color: var(--brand) !important;
        }

        div[data-testid="stAlert"] { border-radius: 12px; }

        hr { border-color: var(--border-card) !important; }
        div[data-testid="stToggle"] label { color: var(--text-main) !important; }

        /* Texto de opciones (radio/checkbox) siempre oscuro en el contenido */
        div[data-testid="stRadio"] label,
        div[data-testid="stRadio"] label p,
        div[data-testid="stRadio"] [data-testid="stWidgetLabel"] p,
        div[data-testid="stCheckbox"] label,
        div[data-testid="stCheckbox"] label p {
            color: var(--text-main) !important;
        }

        /* ── Formulario Nuevo movimiento ── */
        .reg-col-panel { margin-bottom: 0; }

        .cat-desc-box {
            background: var(--brand-soft);
            border: 1px solid var(--brand-border);
            border-radius: 12px;
            padding: 0.85rem 1rem;
            margin: 0.75rem 0 1rem 0;
            font-size: 0.92rem;
            color: var(--text-muted);
            line-height: 1.45;
        }

        .cat-desc-box b { color: var(--brand); }

        /* Tarjetas de categoría — colores activo/hover (layout en st-key-reg_cat_*) */
        [class*="st-key-reg_cat_"] .stButton > button {
            width: 100% !important;
            background: var(--bg-card) !important;
            border: 1px solid var(--border-card) !important;
            color: var(--text-muted) !important;
            box-shadow: none !important;
        }
        [class*="st-key-reg_cat_"] .stButton > button:hover {
            border-color: var(--brand-border) !important;
            color: var(--text-main) !important;
            background: var(--brand-soft) !important;
        }
        [class*="st-key-reg_cat_"] .stButton > button[kind="primary"] {
            background: var(--brand-soft) !important;
            border: 2px solid var(--brand) !important;
            color: var(--text-main) !important;
            box-shadow: 0 0 16px rgba(47, 82, 51, 0.15) !important;
        }
        [class*="st-key-reg_cat_"] .stButton > button[kind="primary"]:hover {
            box-shadow: 0 0 22px rgba(47, 82, 51, 0.24) !important;
        }

        /* Píldoras método de cobro / tipo de cuenta */
        [class*="st-key-reg_met_"] .stButton > button,
        [class*="st-key-reg_cuenta_"] .stButton > button {
            width: 100% !important;
            border-radius: 999px !important;
            padding: 0.55rem 0.75rem !important;
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            background: transparent !important;
            border: 1px solid transparent !important;
            color: var(--text-muted) !important;
            box-shadow: none !important;
        }
        [class*="st-key-reg_met_"] .stButton > button[kind="primary"],
        [class*="st-key-reg_cuenta_"] .stButton > button[kind="primary"] {
            background: var(--brand-soft) !important;
            border: 1px solid var(--brand-border) !important;
            color: var(--text-main) !important;
        }
        [data-testid="stVerticalBlock"]:has(.reg-metodo-pill) > [data-testid="stHorizontalBlock"] {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 999px;
            padding: 4px;
            margin-top: 0.5rem;
        }
        [data-testid="stVerticalBlock"]:has(.reg-cuenta-pill) > [data-testid="stHorizontalBlock"] {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 999px;
            padding: 4px;
            margin-bottom: 0.5rem;
        }

        .bcv-field-label {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.88rem;
            color: var(--text-muted);
            margin-bottom: 0.35rem;
        }

        .bcv-sync-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.30);
            color: var(--success);
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
        }

        div:has(> .reg-monto-marker) {
            position: relative;
        }

        div:has(> .reg-monto-marker) div[data-testid="stNumberInput"] {
            position: relative;
        }

        div:has(> .reg-monto-marker) div[data-testid="stNumberInput"] input {
            font-size: 2.25rem !important;
            font-weight: 600 !important;
            padding: 1rem 3.75rem 1rem 1.15rem !important;
            border: 2px solid var(--brand-border) !important;
            border-radius: 14px !important;
            background: var(--brand-soft) !important;
            box-shadow: 0 0 20px rgba(47, 82, 51, 0.08) !important;
            color: var(--text-main) !important;
            height: auto !important;
        }

        div:has(> .reg-monto-marker) div[data-testid="stNumberInput"] label {
            font-size: 0.92rem !important;
            color: var(--text-muted) !important;
            margin-bottom: 0.4rem !important;
        }

        div:has(> .reg-monto-marker[data-currency="Bs"]) div[data-testid="stNumberInput"]::after,
        div:has(> .reg-monto-marker[data-currency="$"]) div[data-testid="stNumberInput"]::after,
        div:has(> .reg-monto-marker[data-currency="₮"]) div[data-testid="stNumberInput"]::after {
            position: absolute;
            right: 1.15rem;
            top: 50%;
            transform: translateY(-10%);
            font-size: 1.35rem;
            font-weight: 600;
            color: var(--text-subtle);
            pointer-events: none;
        }

        /* Egresos: monto y botón en rojo (uso exclusivo de egresos) */
        div:has(> .reg-monto-marker[data-flow="out"]) div[data-testid="stNumberInput"] input {
            border-color: var(--expense) !important;
            background: rgba(214, 69, 69, 0.06) !important;
            box-shadow: 0 0 20px rgba(214, 69, 69, 0.08) !important;
        }

        .eg-submit .stFormSubmitButton > button[kind="primaryFormSubmit"] {
            background: var(--expense) !important;
            box-shadow: 0 2px 8px rgba(214, 69, 69, 0.30) !important;
        }

        .eg-submit .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {
            background: #bf3a3a !important;
            box-shadow: 0 4px 14px rgba(214, 69, 69, 0.42) !important;
        }

        div:has(> .reg-monto-marker[data-currency="Bs"]) div[data-testid="stNumberInput"]::after { content: "Bs"; }
        div:has(> .reg-monto-marker[data-currency="$"]) div[data-testid="stNumberInput"]::after { content: "$"; }
        div:has(> .reg-monto-marker[data-currency="₮"]) div[data-testid="stNumberInput"]::after { content: "₮"; }

        .reg-toggle-row div[data-testid="stToggle"] {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 12px;
            padding: 0.5rem 0.75rem;
        }

        .reg-extra-fields {
            margin-top: 1.25rem;
            padding-top: 1.25rem;
            border-top: 1px solid var(--border-card);
        }

        .reg-extra-fields .panel-title {
            font-size: 0.95rem;
            margin-bottom: 0.75rem;
        }

        .reg-submit .stFormSubmitButton > button {
            margin-top: 0.5rem;
            padding: 0.75rem 1.5rem !important;
            font-size: 1rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def estilo_plotly(fig, titulo=None, height=320):
    """Aplica el tema dashboard claro Il Giardino a gráficos Plotly."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=GIARDINO_SUBTLE, family="Inter", size=11),
        margin=dict(t=45 if titulo else 15, b=30, l=10, r=10),
        height=height,
        title=dict(
            text=titulo,
            font=dict(size=13, color=GIARDINO_TEXT_DARK, family="Inter"),
            x=0,
            xanchor="left",
        ) if titulo else None,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=GIARDINO_MUTED, size=10)),
        hoverlabel=dict(
            bgcolor=GIARDINO_CARD_LIGHT,
            font_color=GIARDINO_TEXT_DARK,
            bordercolor="rgba(47,82,51,0.40)",
        ),
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(15,23,42,0.06)",
        zerolinecolor="rgba(15,23,42,0.08)",
        tickfont=dict(color=GIARDINO_SUBTLE),
        linecolor="rgba(15,23,42,0.10)",
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(15,23,42,0.06)",
        zerolinecolor="rgba(15,23,42,0.08)",
        tickfont=dict(color=GIARDINO_SUBTLE),
        linecolor="rgba(15,23,42,0.10)",
    )
    return fig


def kpi_delta_badge(delta, label="vs ayer"):
    """Indicador de tendencia (verde/rojo) — único uso de color saturado en KPIs."""
    if delta is None:
        return ""
    if delta > 0:
        return f'<span class="kpi-delta up">▲ +{delta:.1f}% {label}</span>'
    if delta < 0:
        return f'<span class="kpi-delta down">▼ {delta:.1f}% {label}</span>'
    return f'<span class="kpi-delta neu">— sin cambio {label}</span>'


def hero_metric_card(total_bs, delta_bs, contexto_line, etiqueta="Neto Bs hoy", delta_label="vs ayer"):
    return (
        f'<div class="dash-panel dash-panel-hero">'
        f'<div class="hero-metric-row">'
        f'<div><div class="kpi-label">{etiqueta}</div>'
        f'<div class="hero-value">{total_bs}</div></div>'
        f'{kpi_delta_badge(delta_bs, delta_label)}'
        f'</div>'
        f'<div class="hero-context">{contexto_line}</div>'
        f'</div>'
    )


def kpi_grupo_card(titulo, accent_class, mini_stats, footer_delta=None, footer_extra=None):
    items = ""
    for lbl, val in mini_stats:
        lbl_html = f'<div class="mini-stat-label">{lbl}</div>' if lbl else ""
        items += (
            f'<div class="mini-stat">{lbl_html}'
            f'<div class="mini-stat-value">{val}</div></div>'
        )
    footer = (
        f'<div class="kpi-card-footer-delta">{footer_delta}</div>'
        if footer_delta else ""
    )
    extra = (
        f'<div class="kpi-card-footer-delta">{footer_extra}</div>'
        if footer_extra else ""
    )
    return (
        f'<div class="dash-panel {accent_class}">'
        f'<div class="kpi-grupo-title">{titulo}</div>'
        f'<div class="mini-stats-row">{items}</div>{footer}{extra}'
        f'</div>'
    )


def kpi_cuentas_cobrar_card(totales_moneda, n_clientes, top_filas):
    """Tarjeta KPI de cuentas por cobrar (solo lectura) para Panel del día."""
    if n_clientes == 0:
        top_html = (
            f'<p style="color:{GIARDINO_SUBTLE};font-size:0.88rem;margin:0.5rem 0 0 0;">'
            "Sin saldos pendientes de cobro.</p>"
        )
        stats_html = ""
    else:
        stats_html = ""
        for lbl, val in mini_stats_moneda(
            totales_moneda, {"usd": 0.0, "bs": 0.0, "usdt": 0.0}
        ):
            stats_html += (
                f'<div class="mini-stat"><div class="mini-stat-label">{lbl}</div>'
                f'<div class="mini-stat-value">{val}</div></div>'
            )
        filas = []
        for c in top_filas[:4]:
            filas.append(
                f'<div class="kpi-cobrar-top-item">'
                f'<span class="kpi-cobrar-top-name">{c["nombre"] or c["cedula"]}</span>'
                f'<span class="kpi-cobrar-top-amount">'
                f'{formatear_saldo_cobrar(c["saldo_pendiente"], c["moneda"])}</span>'
                f'</div>'
            )
        top_html = "".join(filas)
    return (
        f'<div class="dash-panel accent-cobrar">'
        f'<div class="kpi-grupo-title">Cuentas por cobrar</div>'
        f'<div class="mini-stats-row">{stats_html}</div>'
        f'<div class="stat-simple-label">{n_clientes} cliente(s) con saldo pendiente</div>'
        f'{top_html}'
        f'</div>'
    )


def stat_simple_html(etiqueta, valor, detalle=""):
    det = f'<div class="stat-simple-label">{detalle}</div>' if detalle else ""
    return (
        f'<div style="padding:0.5rem 0;">'
        f'<div class="stat-simple-label">{etiqueta}</div>'
        f'<div class="stat-simple-value">{valor}</div>{det}'
        f'</div>'
    )


def panel_titulo(titulo, subtitulo=None, icono_mat=None):
    prefix = f"{icono_mat_html(icono_mat)} " if icono_mat else ""
    if subtitulo:
        sub = f'<div class="panel-subtitle">{subtitulo}</div>'
    else:
        sub = ""
    return f'<div class="panel-title">{prefix}{titulo}</div>{sub}'


def calcular_delta(hoy, ayer):
    if ayer == 0:
        return None if hoy == 0 else 100.0
    return ((hoy - ayer) / ayer) * 100


def calcular_delta_moneda(hoy, ayer):
    """Delta % moneda a moneda. N/A si solo uno de los dos días tiene movimiento."""
    hoy = float(hoy or 0)
    ayer = float(ayer or 0)
    if hoy == 0 and ayer == 0:
        return None
    if hoy == 0 or ayer == 0:
        return "N/A"
    return ((hoy - ayer) / ayer) * 100


def kpi_delta_multimoneda(hoy_dict, ayer_dict, label="vs ayer"):
    keys = monedas_visibles_kpi(hoy_dict, ayer_dict)
    if not keys:
        return f'<span class="kpi-delta neu">— sin cambio {label}</span>'
    partes = []
    simbolos = {"usd": "USD", "bs": "Bs", "usdt": "USDT"}
    for key in keys:
        d = calcular_delta_moneda(hoy_dict.get(key, 0), ayer_dict.get(key, 0))
        sym = simbolos[key]
        if d == "N/A":
            partes.append(f'<span class="kpi-delta neu">{sym} N/A {label}</span>')
        else:
            badge = kpi_delta_badge(d, f"{sym} {label}")
            if badge:
                partes.append(badge)
    if not partes:
        return f'<span class="kpi-delta neu">— sin cambio {label}</span>'
    return f'<div class="kpi-multi-delta">{"".join(partes)}</div>'


def tasa_respaldo_aviso_html():
    return (
        f'<div class="hint-box warn">'
        f'{icono_mat_html("warning")} '
        f'<b>Tasa de respaldo</b> — puede estar desactualizada. '
        f'Los equivalentes en Bs de este panel no son confiables hasta sincronizar el BCV.'
        f'</div>'
    )


# =============================================================================
# BASE DE DATOS
# =============================================================================

import os

class SQLiteCloudRow(dict):
    def __init__(self, keys, values):
        super().__init__(zip(keys, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

class SQLiteCloudCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    def execute(self, *args, **kwargs):
        self._cursor.execute(*args, **kwargs)
        return self

    def executemany(self, *args, **kwargs):
        self._cursor.executemany(*args, **kwargs)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        columns = [col[0] for col in self._cursor.description]
        return SQLiteCloudRow(columns, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        columns = [col[0] for col in self._cursor.description]
        return [SQLiteCloudRow(columns, r) for r in rows]

    def close(self):
        self._cursor.close()

class SQLiteCloudConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return SQLiteCloudCursorWrapper(self._conn.cursor())

    def execute(self, *args, **kwargs):
        return SQLiteCloudCursorWrapper(self._conn.execute(*args, **kwargs))

    def commit(self):
        try:
            self._conn.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()

def get_connection():
    # Intenta obtener la URL de SQLite Cloud desde secrets de Streamlit o variables de entorno
    sqlite_cloud_url = None
    try:
        if "SQLITE_CLOUD_URL" in st.secrets:
            sqlite_cloud_url = st.secrets["SQLITE_CLOUD_URL"]
    except Exception:
        pass
        
    if not sqlite_cloud_url:
        sqlite_cloud_url = os.environ.get("SQLITE_CLOUD_URL")

    if sqlite_cloud_url:
        import sqlitecloud
        conn = sqlitecloud.connect(sqlite_cloud_url)
        try:
            conn.execute("USE DATABASE caja_restaurante.db")
        except Exception:
            pass
        return SQLiteCloudConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                tipo TEXT NOT NULL,
                monto REAL NOT NULL,
                moneda TEXT NOT NULL,
                banco TEXT,
                referencia TEXT,
                notas TEXT,
                tipo_movimiento TEXT NOT NULL DEFAULT 'Ingreso',
                categoria TEXT,
                creado_en TEXT NOT NULL
            )
            """
        )
        conn.commit()
        _migrar_tabla_antigua(conn)
        _agregar_columnas_nuevas(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasa_bcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tasa REAL NOT NULL,
                fecha_valor TEXT,
                actualizado_en TEXT NOT NULL
            )
            """
        )
        conn.commit()
        _init_historico_tasas(conn)
        _init_tabla_clientes(conn)
        _init_tabla_pagos_cliente(conn)


def _init_historico_tasas(conn):
    """Banco local de tasas BCV por día (fecha ISO única)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS historico_tasas (
            fecha TEXT NOT NULL UNIQUE,
            tasa REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.execute(
        """
        INSERT OR IGNORE INTO historico_tasas (fecha, tasa)
        SELECT date(fecha), MAX(tasa_bcv)
        FROM movimientos
        WHERE COALESCE(tasa_bcv, 0) > 0
          AND moneda LIKE '%Bs%'
        GROUP BY date(fecha)
        """
    )
    conn.commit()


def _init_tabla_clientes(conn):
    """Tabla maestra de clientes — cédula como identificador único."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            telefono TEXT DEFAULT '',
            creado_en TEXT NOT NULL,
            actualizado_en TEXT NOT NULL
        )
        """
    )
    conn.commit()
    _sembrar_clientes_desde_movimientos(conn)


def _init_tabla_pagos_cliente(conn):
    """Historial de pagos parciales/totales contra cuentas abiertas."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pagos_cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_cedula TEXT NOT NULL,
            cliente_nombre TEXT DEFAULT '',
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            moneda TEXT NOT NULL DEFAULT 'Bs (Bolívares)',
            metodo TEXT DEFAULT '',
            banco TEXT DEFAULT '',
            notas TEXT DEFAULT '',
            movimiento_caja_id INTEGER,
            creado_en TEXT NOT NULL
        )
        """
    )
    conn.commit()
    _migrar_consumo_credito_y_pagos(conn)
    _migrar_pagos_cliente_multimoneda(conn)


def _migrar_pagos_cliente_multimoneda(conn):
    """Campos de conversión en pagos: monto real, moneda deuda, tasa aplicada."""
    columnas = {
        fila[1] for fila in conn.execute("PRAGMA table_info(pagos_cliente)").fetchall()
    }
    nuevas = {
        "moneda_deuda": "TEXT DEFAULT ''",
        "monto_aplicado_deuda": "REAL DEFAULT 0",
        "tasa_conversion": "REAL DEFAULT 0",
    }
    for col, definicion in nuevas.items():
        if col not in columnas:
            conn.execute(f"ALTER TABLE pagos_cliente ADD COLUMN {col} {definicion}")
    conn.execute(
        """
        UPDATE pagos_cliente
        SET moneda_deuda = moneda,
            monto_aplicado_deuda = monto,
            tasa_conversion = 0
        WHERE COALESCE(monto_aplicado_deuda, 0) = 0
          AND COALESCE(TRIM(moneda_deuda), '') = ''
        """
    )
    conn.commit()


def _migrar_consumo_credito_y_pagos(conn):
    """Marca consumos a crédito y migra cierres antiguos al historial de pagos."""
    conn.execute(
        """
        UPDATE movimientos
        SET es_consumo_credito = 1
        WHERE COALESCE(es_consumo_credito, 0) = 0
          AND (
            COALESCE(estado_pago, 'Pagado') = ?
            OR (
                TRIM(COALESCE(cliente_cedula, '')) != ''
                AND TRIM(COALESCE(fecha_pago, '')) != ''
                AND date(fecha) != date(fecha_pago)
            )
          )
        """,
        (ESTADO_CUENTA_ABIERTA,),
    )
    ya_migrados = conn.execute(
        "SELECT COUNT(*) FROM pagos_cliente WHERE notas LIKE 'Migrado:%'"
    ).fetchone()[0]
    if ya_migrados > 0:
        conn.commit()
        return

    filas = conn.execute(
        """
        SELECT
            UPPER(TRIM(cliente_cedula)) AS cedula,
            MAX(cliente_nombre) AS nombre,
            fecha_pago AS fecha,
            SUM(
                CASE WHEN moneda LIKE '%Bs%'
                THEN monto - COALESCE(comision_pos, 0)
                ELSE monto END
            ) AS monto,
            MAX(moneda) AS moneda,
            MAX(COALESCE(metodo_detalle, '')) AS metodo,
            MAX(COALESCE(banco, '')) AS banco
        FROM movimientos
        WHERE COALESCE(es_consumo_credito, 0) = 1
          AND COALESCE(estado_pago, 'Pagado') = ?
          AND TRIM(COALESCE(fecha_pago, '')) != ''
          AND TRIM(COALESCE(cliente_cedula, '')) != ''
          AND date(fecha) != date(fecha_pago)
        GROUP BY UPPER(TRIM(cliente_cedula)), fecha_pago
        """,
        (ESTADO_PAGADO,),
    ).fetchall()
    ahora = datetime.now().isoformat(timespec="seconds")
    for f in filas:
        conn.execute(
            """
            INSERT INTO pagos_cliente
                (cliente_cedula, cliente_nombre, fecha, monto, moneda,
                 metodo, banco, notas, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f["cedula"],
                f["nombre"] or "",
                f["fecha"],
                float(f["monto"] or 0),
                f["moneda"] or "Bs (Bolívares)",
                f["metodo"] or "",
                f["banco"] or "",
                "Migrado: cierre cuenta abierta (modelo anterior)",
                ahora,
            ),
        )
    conn.commit()


def _sembrar_clientes_desde_movimientos(conn):
    """Importa clientes únicos ya registrados en movimientos históricos."""
    conn.execute(
        """
        INSERT OR IGNORE INTO clientes (cedula, nombre, telefono, creado_en, actualizado_en)
        SELECT cedula, nombre, telefono, creado_en, actualizado_en
        FROM (
            SELECT
                UPPER(TRIM(cliente_cedula)) AS cedula,
                TRIM(cliente_nombre) AS nombre,
                TRIM(COALESCE(cliente_telefono, '')) AS telefono,
                MIN(creado_en) AS creado_en,
                MAX(creado_en) AS actualizado_en
            FROM movimientos
            WHERE TRIM(COALESCE(cliente_cedula, '')) != ''
              AND TRIM(COALESCE(cliente_nombre, '')) != ''
            GROUP BY UPPER(TRIM(cliente_cedula))
        )
        """
    )
    conn.commit()


def _normalizar_cedula(cedula):
    return str(cedula or "").strip().upper()


def buscar_cliente_por_cedula(cedula):
    cedula = _normalizar_cedula(cedula)
    if not cedula:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cedula, nombre, telefono, creado_en FROM clientes WHERE cedula = ?",
            (cedula,),
        ).fetchone()
    return dict(row) if row else None


def registrar_cliente_nuevo(cedula, nombre, telefono):
    """Inserta un cliente nuevo. Falla si la cédula ya existe."""
    cedula = _normalizar_cedula(cedula)
    nombre = str(nombre or "").strip()
    telefono = str(telefono or "").strip()
    ahora = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO clientes (cedula, nombre, telefono, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cedula, nombre, telefono, ahora, ahora),
        )
        conn.commit()
    return buscar_cliente_por_cedula(cedula)


def actualizar_cliente(cedula, nombre, telefono):
    """Actualiza nombre y teléfono de un cliente existente."""
    cedula = _normalizar_cedula(cedula)
    ahora = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE clientes
            SET nombre = ?, telefono = ?, actualizado_en = ?
            WHERE cedula = ?
            """,
            (str(nombre or "").strip(), str(telefono or "").strip(), ahora, cedula),
        )
        conn.commit()
        return cur.rowcount > 0


def cliente_tiene_cuenta_abierta(cedula):
    """True si el cliente tiene saldo pendiente por cobrar en alguna moneda."""
    return any(s["saldo"] > 0.0001 for s in saldos_por_moneda_cliente(cedula))


def contar_movimientos_cliente(cedula):
    """Movimientos históricos asociados a la cédula (no se borran al eliminar cliente)."""
    cedula = _normalizar_cedula(cedula)
    if not cedula:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM movimientos
            WHERE UPPER(TRIM(cliente_cedula)) = ?
            """,
            (cedula,),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def eliminar_cliente(cedula):
    """Elimina un cliente del directorio. Los movimientos históricos se conservan."""
    cedula = _normalizar_cedula(cedula)
    if not cedula:
        return False, "Cédula no válida."
    if cliente_tiene_cuenta_abierta(cedula):
        return (
            False,
            "Este cliente tiene cuentas abiertas pendientes. "
            "Ciérrelas en «Cuentas por Cobrar» antes de eliminarlo.",
        )
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM clientes WHERE cedula = ?", (cedula,))
        conn.commit()
        if cur.rowcount == 0:
            return False, "Cliente no encontrado."
    return True, ""


def cargar_clientes_resumen():
    """Clientes con conteo de visitas (movimientos asociados por cédula)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.cedula,
                c.nombre,
                c.telefono,
                c.creado_en,
                COUNT(m.id) AS visitas
            FROM clientes c
            LEFT JOIN movimientos m
                ON UPPER(TRIM(COALESCE(m.cliente_cedula, ''))) = c.cedula
            GROUP BY c.cedula
            ORDER BY c.nombre COLLATE NOCASE ASC
            """
        ).fetchall()
    if not rows:
        return pd.DataFrame(
            columns=["cedula", "nombre", "telefono", "creado_en", "visitas"]
        )
    df = pd.DataFrame([dict(r) for r in rows])
    df["fecha_registro"] = pd.to_datetime(
        df["creado_en"], errors="coerce"
    ).dt.strftime("%d/%m/%Y %H:%M")
    return df


def _programar_sync_cliente_registro(nombre="", telefono=""):
    """Programa nombre/teléfono para aplicar antes de crear los widgets."""
    st.session_state["_reg_cliente_sync"] = {
        "nombre": nombre,
        "telefono": telefono,
    }


def _aplicar_sync_cliente_registro():
    """Aplica nombre/teléfono pendientes antes de instanciar los text_input."""
    sync = st.session_state.pop("_reg_cliente_sync", None)
    if sync is None:
        return
    st.session_state.reg_cliente_nombre = sync.get("nombre", "")
    st.session_state.reg_cliente_telefono = sync.get("telefono", "")


def _limpiar_estado_cliente_registro():
    st.session_state.reg_cliente_cedula = ""
    _programar_sync_cliente_registro("", "")
    st.session_state.reg_cliente_verificado = False
    st.session_state.reg_cliente_es_nuevo = True
    st.session_state.reg_cliente_msg = ""


def _on_toggle_cliente_registro():
    if not st.session_state.reg_registrar_cliente:
        _limpiar_estado_cliente_registro()


def _on_cedula_editada():
    st.session_state.reg_cliente_verificado = False
    st.session_state.reg_cliente_es_nuevo = True
    st.session_state.reg_cliente_msg = ""
    _programar_sync_cliente_registro("", "")


def _ejecutar_verificacion_cedula():
    cedula = _normalizar_cedula(st.session_state.get("reg_cliente_cedula", ""))
    if not cedula:
        st.session_state.reg_cliente_msg = "Ingrese la cédula antes de verificar."
        st.session_state.reg_cliente_verificado = False
        st.session_state.reg_cliente_es_nuevo = True
        _programar_sync_cliente_registro("", "")
        return

    cliente = buscar_cliente_por_cedula(cedula)
    if cliente:
        _programar_sync_cliente_registro(
            cliente["nombre"],
            cliente.get("telefono") or "",
        )
        st.session_state.reg_cliente_es_nuevo = False
        st.session_state.reg_cliente_verificado = True
        st.session_state.reg_cliente_msg = (
            f"✓ Cliente registrado: <b>{cliente['nombre']}</b> — verifique los datos."
        )
    else:
        _programar_sync_cliente_registro("", "")
        st.session_state.reg_cliente_es_nuevo = True
        st.session_state.reg_cliente_verificado = True
        st.session_state.reg_cliente_msg = (
            "🆕 Cédula no registrada — complete nombre y teléfono del cliente nuevo."
        )


def _render_seccion_cliente():
    """Cédula → buscar → nombre y teléfono (obligatorios si se registra cliente)."""
    _aplicar_sync_cliente_registro()

    st.text_input(
        "Cédula / RIF",
        key="reg_cliente_cedula",
        placeholder="Ej: V-27187185",
        on_change=_on_cedula_editada,
    )
    st.button(
        "Buscar cédula en directorio",
        key="reg_btn_verificar_cedula",
        use_container_width=True,
        on_click=_ejecutar_verificacion_cedula,
    )
    msg = st.session_state.get("reg_cliente_msg", "")
    if msg:
        st.markdown(
            f'<p style="color:{GIARDINO_SUBTLE};font-size:0.9rem;margin:0.35rem 0 0.75rem 0;">{msg}</p>',
            unsafe_allow_html=True,
        )

    if not st.session_state.get("reg_cliente_verificado", False):
        return

    es_nuevo = st.session_state.get("reg_cliente_es_nuevo", True)
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.text_input(
            "Nombre del Cliente",
            key="reg_cliente_nombre",
            placeholder="Nombre completo",
            disabled=not es_nuevo,
        )
    with c2:
        st.text_input(
            "Teléfono",
            key="reg_cliente_telefono",
            placeholder="0414-1234567",
            disabled=not es_nuevo,
        )


def _resolver_datos_cliente_registro(ss):
    """Asocia el movimiento al cliente; persiste cliente nuevo si no existe."""
    cedula = _normalizar_cedula(ss.reg_cliente_cedula)
    existente = buscar_cliente_por_cedula(cedula)
    if existente:
        return existente["cedula"], existente["nombre"], existente.get("telefono") or ""

    nombre = str(ss.reg_cliente_nombre or "").strip()
    telefono = str(ss.reg_cliente_telefono or "").strip()
    try:
        registrar_cliente_nuevo(cedula, nombre, telefono)
    except sqlite3.IntegrityError:
        existente = buscar_cliente_por_cedula(cedula)
        if existente:
            return existente["cedula"], existente["nombre"], existente.get("telefono") or ""
    return cedula, nombre, telefono


def _agregar_columnas_nuevas(conn):
    """Agrega columnas nuevas con ALTER TABLE si aún no existen.
    No toca datos existentes — completamente seguro para bases de datos en producción."""
    columnas_existentes = {
        fila[1]
        for fila in conn.execute("PRAGMA table_info(movimientos)").fetchall()
    }
    nuevas_columnas = {
        "iva_activo":         "INTEGER DEFAULT 0",
        "tipo_cuenta":        "TEXT    DEFAULT 'Regular'",
        "cantidad_personas":  "INTEGER DEFAULT 1",
        "metodo_detalle":     "TEXT    DEFAULT ''",
        "propina":            "REAL    DEFAULT 0",
        "propina_moneda":     "TEXT    DEFAULT ''",
        "tasa_bcv":           "REAL    DEFAULT 0",
        "es_tarjeta_credito": "INTEGER DEFAULT 0",
        "comision_pos":       "REAL    DEFAULT 0",
        "cliente_nombre":     "TEXT    DEFAULT ''",
        "cliente_cedula":     "TEXT    DEFAULT ''",
        "cliente_telefono":   "TEXT    DEFAULT ''",
        "estado_pago":        "TEXT    DEFAULT 'Pagado'",
        "fecha_pago":         "TEXT    DEFAULT ''",
        "tipo_movimiento":    "TEXT    DEFAULT 'Ingreso'",
        "categoria":          "TEXT    DEFAULT ''",
        "es_consumo_credito": "INTEGER DEFAULT 0",
        "monto_total_pos":    "REAL    DEFAULT 0",
    }
    for col, definicion in nuevas_columnas.items():
        if col not in columnas_existentes:
            conn.execute(f"ALTER TABLE movimientos ADD COLUMN {col} {definicion}")
    _migrar_naturaleza_y_categorias(conn)
    conn.commit()


def _normalizar_tipo_movimiento_str(valor):
    """Canoniza a Ingreso | Egreso | Propina (compatible con registros legacy)."""
    v = str(valor or "").strip()
    if not v:
        return TIPO_MOV_INGRESO
    upper = v.upper()
    if upper in ("EGRESO", "EGRESOS"):
        return TIPO_MOV_EGRESO
    if upper in ("PROPINA", "PROPINAS"):
        return TIPO_MOV_PROPINA
    if upper in ("INGRESO", "INGRESOS"):
        return TIPO_MOV_INGRESO
    if v in TIPOS_NATURALEZA:
        return v
    return TIPO_MOV_INGRESO


def _inferir_naturaleza_fila(tipo, tipo_movimiento, categoria=""):
    """Infiere naturaleza cuando el campo explícito falta o está desactualizado."""
    tm = _normalizar_tipo_movimiento_str(tipo_movimiento)
    tipo_s = str(tipo or "").strip()
    cat_s = str(categoria or "").strip()

    if tipo_s == "Propina" or cat_s == CATEGORIA_PROPINA:
        return TIPO_MOV_PROPINA
    if tm == TIPO_MOV_PROPINA:
        return TIPO_MOV_PROPINA
    if tm == TIPO_MOV_EGRESO or tipo_s in CATEGORIAS_GASTO or cat_s in CATEGORIAS_GASTO:
        return TIPO_MOV_EGRESO
    return TIPO_MOV_INGRESO


def _resolver_categoria_guardado(tipo, tipo_movimiento=None, categoria=None):
    """Concepto contable del movimiento (columna `categoria`)."""
    if categoria and str(categoria).strip():
        return str(categoria).strip()
    naturaleza = _inferir_naturaleza_fila(tipo, tipo_movimiento)
    tipo_s = str(tipo or "").strip()
    if naturaleza == TIPO_MOV_EGRESO:
        return tipo_s if tipo_s in CATEGORIAS_GASTO else (tipo_s or "Otros")
    if naturaleza == TIPO_MOV_PROPINA:
        return CATEGORIA_PROPINA
    if tipo_s in CATEGORIAS_GASTO:
        return tipo_s
    return CATEGORIA_INGRESO_DEFAULT


def _resolver_naturaleza_guardado(tipo, tipo_movimiento=None):
    return _inferir_naturaleza_fila(tipo, tipo_movimiento)


def _categoria_display_fila(row):
    """Categoría legible para UI a partir de fila DB (con fallback legacy)."""
    cat = str(row.get("categoria") or "").strip()
    if cat:
        return cat
    tipo_s = str(row.get("tipo") or "").strip()
    naturaleza = _tipo_movimiento_valor(row)
    if naturaleza == TIPO_MOV_EGRESO:
        return tipo_s if tipo_s in CATEGORIAS_GASTO else tipo_s
    if naturaleza == TIPO_MOV_PROPINA or tipo_s == "Propina":
        return CATEGORIA_PROPINA
    if tipo_s in canales_ingreso_legacy():
        return CATEGORIA_INGRESO_DEFAULT
    return tipo_s or CATEGORIA_INGRESO_DEFAULT


def _canal_display_fila(row):
    """Canal de cobro/pago separado del concepto contable."""
    banco = str(row.get("banco") or "").strip()
    metodo = str(row.get("metodo_detalle") or "").strip()
    tipo_s = str(row.get("tipo") or "").strip()
    if banco:
        return banco
    if metodo:
        return metodo
    if tipo_s in canales_ingreso_legacy():
        return tipo_s
    return "—"


def _migrar_naturaleza_y_categorias(conn):
    """Normaliza tipo_movimiento y rellena `categoria` en registros existentes."""
    conn.execute(
        """
        UPDATE movimientos
        SET tipo_movimiento = 'Ingreso'
        WHERE COALESCE(TRIM(tipo_movimiento), '') = ''
        """
    )
    conn.execute(
        """
        UPDATE movimientos
        SET tipo_movimiento = 'Ingreso'
        WHERE UPPER(TRIM(tipo_movimiento)) = 'INGRESO'
        """
    )
    conn.execute(
        """
        UPDATE movimientos
        SET tipo_movimiento = 'Egreso'
        WHERE UPPER(TRIM(tipo_movimiento)) = 'EGRESO'
        """
    )
    conn.execute(
        """
        UPDATE movimientos
        SET tipo_movimiento = 'Propina'
        WHERE TRIM(tipo) = 'Propina'
           OR UPPER(TRIM(tipo_movimiento)) = 'PROPINA'
        """
    )

    gastos_sql = ",".join("?" * len(CATEGORIAS_GASTO))
    conn.execute(
        f"""
        UPDATE movimientos
        SET tipo_movimiento = 'Egreso'
        WHERE tipo IN ({gastos_sql})
          AND COALESCE(tipo_movimiento, 'Ingreso') NOT IN ('Egreso', 'Propina')
        """,
        CATEGORIAS_GASTO,
    )

    rows = conn.execute(
        "SELECT id, tipo, banco, metodo_detalle, tipo_movimiento, categoria FROM movimientos"
    ).fetchall()
    canales = canales_ingreso_legacy()
    for row in rows:
        rid = row["id"]
        tipo_s = str(row["tipo"] or "").strip()
        cat_actual = str(row["categoria"] or "").strip()
        tm = _inferir_naturaleza_fila(tipo_s, row["tipo_movimiento"], cat_actual)
        cat = cat_actual or _resolver_categoria_guardado(tipo_s, tm)
        banco = str(row["banco"] or "").strip()

        if tm == TIPO_MOV_INGRESO and tipo_s in canales and not banco:
            banco_nuevo = tipo_s
            if tipo_s == "Ingreso bancario" and row["metodo_detalle"]:
                banco_nuevo = str(row["metodo_detalle"]).strip() or tipo_s
            conn.execute(
                "UPDATE movimientos SET banco = ? WHERE id = ?",
                (banco_nuevo, rid),
            )

        conn.execute(
            """
            UPDATE movimientos
            SET tipo_movimiento = ?, categoria = ?
            WHERE id = ?
            """,
            (tm, cat, rid),
        )


def _migrar_tabla_antigua(conn):
    """Migra datos de la tabla anterior 'ingresos' si existe."""
    tablas = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ingresos'"
    ).fetchone()
    if not tablas:
        return

    filas = conn.execute("SELECT * FROM ingresos").fetchall()
    for fila in filas:
        conn.execute(
            """
            INSERT INTO movimientos (fecha, tipo, monto, moneda, banco, referencia, notas, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fila["fecha"] if isinstance(fila, sqlite3.Row) else fila[1],
                "Ingreso bancario",
                fila["monto"] if isinstance(fila, sqlite3.Row) else fila[2],
                fila["moneda"] if isinstance(fila, sqlite3.Row) else fila[3],
                fila["banco"] if isinstance(fila, sqlite3.Row) else fila[4],
                fila["referencia"] if isinstance(fila, sqlite3.Row) else fila[5],
                "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    conn.execute("DROP TABLE ingresos")
    conn.commit()


def guardar_movimiento(
    fecha_hora, tipo, monto, moneda, banco, referencia, notas,
    iva_activo=False, tipo_cuenta="Regular", cantidad_personas=1,
    metodo_detalle="", propina=0.0, propina_moneda="",
    tasa_bcv=0.0, es_tarjeta_credito=False, comision_pos=0.0,
    cliente_nombre="", cliente_cedula="", cliente_telefono="",
    estado_pago=ESTADO_PAGADO, fecha_pago="",
    tipo_movimiento=None, categoria=None,
    es_consumo_credito=False,
    monto_total_pos=0.0,
):
    naturaleza = _resolver_naturaleza_guardado(tipo, tipo_movimiento)
    cat = _resolver_categoria_guardado(tipo, naturaleza, categoria)
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO movimientos
                (fecha, tipo, monto, moneda, banco, referencia, notas,
                 iva_activo, tipo_cuenta, cantidad_personas,
                 metodo_detalle, propina, propina_moneda,
                 tasa_bcv, es_tarjeta_credito, comision_pos,
                 cliente_nombre, cliente_cedula, cliente_telefono,
                 estado_pago, fecha_pago, tipo_movimiento, categoria, es_consumo_credito,
                 monto_total_pos, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fecha_hora, tipo, float(monto), moneda,
                banco or "", referencia or "", notas or "",
                1 if iva_activo else 0,
                tipo_cuenta or "Regular",
                int(cantidad_personas) if cantidad_personas else 1,
                metodo_detalle or "",
                float(propina) if propina else 0.0,
                propina_moneda or "",
                float(tasa_bcv) if tasa_bcv else 0.0,
                1 if es_tarjeta_credito else 0,
                float(comision_pos) if comision_pos else 0.0,
                cliente_nombre or "",
                cliente_cedula or "",
                cliente_telefono or "",
                estado_pago or ESTADO_PAGADO,
                fecha_pago or "",
                naturaleza,
                cat,
                1 if es_consumo_credito else 0,
                float(monto_total_pos) if monto_total_pos else 0.0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cur.lastrowid


def actualizar_movimiento(
    registro_id, fecha_hora, tipo, monto, moneda, banco, referencia, notas,
    iva_activo=False, tipo_cuenta="Regular", cantidad_personas=1,
    metodo_detalle="", propina=0.0, propina_moneda="",
    tasa_bcv=0.0, es_tarjeta_credito=False, comision_pos=0.0,
    cliente_nombre="", cliente_cedula="", cliente_telefono="",
    estado_pago=ESTADO_PAGADO, fecha_pago="",
    tipo_movimiento=None, categoria=None,
    monto_total_pos=0.0,
):
    naturaleza = _resolver_naturaleza_guardado(tipo, tipo_movimiento)
    cat = _resolver_categoria_guardado(tipo, naturaleza, categoria)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE movimientos
            SET fecha=?, tipo=?, monto=?, moneda=?, banco=?, referencia=?, notas=?,
                iva_activo=?, tipo_cuenta=?, cantidad_personas=?,
                metodo_detalle=?, propina=?, propina_moneda=?,
                tasa_bcv=?, es_tarjeta_credito=?, comision_pos=?,
                cliente_nombre=?, cliente_cedula=?, cliente_telefono=?,
                estado_pago=?, fecha_pago=?, tipo_movimiento=?, categoria=?,
                monto_total_pos=?
            WHERE id=?
            """,
            (
                fecha_hora, tipo, float(monto), moneda,
                banco or "", referencia or "", notas or "",
                1 if iva_activo else 0,
                tipo_cuenta or "Regular",
                int(cantidad_personas) if cantidad_personas else 1,
                metodo_detalle or "",
                float(propina) if propina else 0.0,
                propina_moneda or "",
                float(tasa_bcv) if tasa_bcv else 0.0,
                1 if es_tarjeta_credito else 0,
                float(comision_pos) if comision_pos else 0.0,
                cliente_nombre or "",
                cliente_cedula or "",
                cliente_telefono or "",
                estado_pago or ESTADO_PAGADO,
                fecha_pago or "",
                naturaleza,
                cat,
                float(monto_total_pos) if monto_total_pos else 0.0,
                registro_id,
            ),
        )
        conn.commit()


def eliminar_movimiento(registro_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM movimientos WHERE id=?", (registro_id,))
        conn.commit()


def cargar_movimientos(fecha_desde=None, fecha_hasta=None, tipo_filtro=None, banco_filtro=None):
    query = "SELECT * FROM movimientos WHERE 1=1"
    params = []

    if fecha_desde:
        query += " AND date(fecha) >= date(?)"
        params.append(fecha_desde.isoformat())
    if fecha_hasta:
        query += " AND date(fecha) <= date(?)"
        params.append(fecha_hasta.isoformat())
    if tipo_filtro and tipo_filtro != "Todos":
        query += " AND (categoria = ? OR (COALESCE(TRIM(categoria), '') = '' AND tipo = ?))"
        params.extend([tipo_filtro, tipo_filtro])
    if banco_filtro and banco_filtro != "Todos":
        query += " AND banco = ?"
        params.append(banco_filtro)

    query += " ORDER BY fecha DESC, id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        if not rows:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(movimientos)").fetchall()]
            return pd.DataFrame(columns=cols)
    return pd.DataFrame([dict(r) for r in rows])


# =============================================================================
# UTILIDADES DE PRESENTACIÓN
# =============================================================================

def formatear_monto(valor, moneda):
    if pd.isna(valor):
        return "—"
    if "USDT" in str(moneda):
        return f"₮ {valor:,.2f}"
    if "USD" in str(moneda):
        return f"${valor:,.2f}"
    return f"Bs {valor:,.2f}"


def formatear_tasa_bcv(valor, moneda):
    if "Bs" not in str(moneda):
        return "—"
    if pd.isna(valor) or float(valor or 0) <= 0:
        return "—"
    return f"Bs {float(valor):,.4f}"


def calcular_comision_pos(monto, es_tarjeta_credito):
    if es_tarjeta_credito and float(monto) > 0:
        return round(float(monto) * COMISION_POS_PORCENTAJE, 2)
    return 0.0


def calcular_desglose_iva(monto_base, iva_activo=False):
    """Devuelve (monto_final, monto_iva). Con IVA: final = base × 1.16."""
    base = float(monto_base or 0)
    if not iva_activo or base <= 0:
        return base, 0.0
    iva = round(base * IVA_PORCENTAJE, 2)
    total = round(base * (1 + IVA_PORCENTAJE), 2)
    return total, iva


def construir_fecha_hora(fecha_mov, hora_mov):
    return f"{fecha_mov.isoformat()} {hora_mov.strftime('%H:%M:%S')}"


def resumen_por_moneda(df):
    if df.empty:
        return {}
    return df.groupby("moneda")["monto"].sum().to_dict()


def neto_liquido_por_moneda(df):
    """Neto real por moneda: ingresos − egresos. Excluye propinas del flujo de caja."""
    if df.empty:
        return {}
    df_flujo = df[~df.apply(es_propina_mov, axis=1)].copy()
    if df_flujo.empty:
        return {}

    def _monto_firmado(row):
        monto = abs(float(row.get("monto", 0) or 0))
        if es_egreso(row):
            return -monto
        if es_ingreso(row):
            return monto
        return 0.0

    df_flujo["_signed"] = df_flujo.apply(_monto_firmado, axis=1)
    return df_flujo.groupby("moneda")["_signed"].sum().to_dict()


def formatear_monto_neto(valor, moneda):
    """Formato con signo explícito delante del símbolo (ej. -$440.00)."""
    if pd.isna(valor):
        return "—"
    val = float(valor)
    sign = "-" if val < 0 else ""
    abs_val = abs(val)
    if "USDT" in str(moneda):
        return f"{sign}₮ {abs_val:,.2f}"
    if "USD" in str(moneda):
        return f"{sign}${abs_val:,.2f}"
    return f"{sign}Bs {abs_val:,.2f}"


def formatear_bs_neto_etiqueta(valor):
    entero = int(round(abs(float(valor or 0))))
    sign = "-" if float(valor or 0) < 0 else ""
    return f"{sign}Bs {entero:,}".replace(",", ".")


def resumen_por_tipo(df):
    if df.empty:
        return pd.DataFrame()
    return df.groupby(["tipo", "moneda"], as_index=False)["monto"].sum()


def resumen_por_banco(df):
    if df.empty:
        return pd.DataFrame()
    con_banco = df[df["banco"].astype(str).str.strip() != ""]
    if con_banco.empty:
        return pd.DataFrame()
    return con_banco.groupby(["banco", "moneda"], as_index=False)["monto"].sum()


def _parse_numero_bcv(texto):
    """Convierte '607,39190000' o '1.234,56' al formato float."""
    t = str(texto).strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    return float(t)


def _normalizar_fecha_iso(valor):
    """Convierte dd/mm/yyyy, yyyy-mm-dd u otros a ISO (yyyy-mm-dd)."""
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor.isoformat()
    texto = str(valor).strip()
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _leer_tasa_historico(fecha_iso):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT fecha, tasa FROM historico_tasas WHERE fecha = ?",
            (fecha_iso,),
        ).fetchone()
    return dict(row) if row else None


def _actualizar_tasa_historico(fecha_iso, tasa):
    """Guarda o reemplaza la tasa de un día (p. ej. ingreso manual del cajero)."""
    fecha_iso = _normalizar_fecha_iso(fecha_iso)
    tasa = float(tasa or 0)
    if not fecha_iso or tasa <= 0:
        return
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO historico_tasas (fecha, tasa)
            VALUES (?, ?)
            ON CONFLICT(fecha) DO UPDATE SET tasa = excluded.tasa
            """,
            (fecha_iso, tasa),
        )
        conn.commit()


def _http_get_json(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_tasa_bcv_api_historica(fecha_iso):
    """Opción B: consulta repositorios públicos de histórico BCV."""
    candidatos = [
        BCV_HISTORICO_API.format(fecha=fecha_iso),
        BCV_HISTORICO_API_RESPALDO.format(fecha=fecha_iso),
    ]
    for url in candidatos:
        try:
            data = _http_get_json(url)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            continue

        if isinstance(data, dict):
            if data.get("USD") is not None:
                return float(data["USD"]), "BCV Today (histórico)"
            if data.get("monto") is not None:
                return float(data["monto"]), "API histórica BCV"
            usd = data.get("usd") or data.get("rate")
            if isinstance(usd, dict):
                usd = usd.get("rate") or usd.get("value")
            if usd is not None:
                return float(usd), "API histórica BCV"
    return None, None


def resolver_tasa_para_fecha(fecha_mov):
    """
    Devuelve (tasa, fuente, aviso).
    1) Histórico local  2) BCV en vivo (hoy)  3) API histórica  4) aviso manual.
    """
    fecha_iso = _normalizar_fecha_iso(fecha_mov)
    if not fecha_iso:
        return 0.0, "", "Fecha no válida para consultar la tasa."

    if isinstance(fecha_mov, str):
        fecha_mov = date.fromisoformat(fecha_iso)

    if fecha_mov >= date.today():
        try:
            tasa, fecha_valor, fuente = obtener_tasa_bcv()
            if tasa and tasa > 0:
                dia = _normalizar_fecha_iso(fecha_valor) or fecha_iso
                _actualizar_tasa_historico(dia, tasa)
                return float(tasa), fuente, ""
        except (ValueError, TypeError, OSError):
            pass
        local = _leer_tasa_historico(fecha_iso)
        if local:
            return float(local["tasa"]), "Histórico local (hoy)", ""
        return 0.0, "", "No se pudo obtener la tasa del BCV para hoy."

    local = _leer_tasa_historico(fecha_iso)
    if local:
        return float(local["tasa"]), "Histórico local", ""

    tasa_api, fuente_api = _fetch_tasa_bcv_api_historica(fecha_iso)
    if tasa_api and tasa_api > 0:
        _actualizar_tasa_historico(fecha_iso, tasa_api)
        return float(tasa_api), fuente_api, ""

    return (
        0.0,
        "",
        f"No hay tasa guardada para el {fecha_mov.strftime('%d/%m/%Y')}. "
        "Ingrésela manualmente; al guardar el movimiento quedará registrada en el histórico.",
    )


def sincronizar_historico_tasa_hoy():
    """Al iniciar la app, guarda la tasa vigente del día en historico_tasas."""
    try:
        tasa, fecha_valor, _ = obtener_tasa_bcv()
        if tasa and tasa > 0:
            dia = _normalizar_fecha_iso(fecha_valor) or date.today().isoformat()
            _actualizar_tasa_historico(dia, tasa)
    except (ValueError, TypeError, OSError):
        pass


def _campos_tasa_formulario(prefix):
    return {
        "tasa": f"{prefix}_tasa_bcv",
        "fuente": f"{prefix}_tasa_fuente",
        "aviso": f"{prefix}_tasa_aviso",
        "fecha_ref": f"{prefix}_tasa_fecha_ref",
    }


def aplicar_tasa_bcv_a_formulario(fecha_mov, prefix="reg"):
    """Actualiza tasa BCV del formulario según la fecha seleccionada."""
    campos = _campos_tasa_formulario(prefix)
    tasa, fuente, aviso = resolver_tasa_para_fecha(fecha_mov)
    st.session_state[campos["fecha_ref"]] = fecha_mov
    st.session_state[campos["fuente"]] = fuente
    st.session_state[campos["aviso"]] = aviso or ""
    if tasa and tasa > 0:
        st.session_state[campos["tasa"]] = float(tasa)


def _sync_tasa_si_fecha_cambio(fecha_key, prefix="reg"):
    ss = st.session_state
    campos = _campos_tasa_formulario(prefix)
    fecha = ss.get(fecha_key)
    if fecha and ss.get(campos["fecha_ref"]) != fecha:
        aplicar_tasa_bcv_a_formulario(fecha, prefix)


def _ensure_tasa_formulario(fecha_key, prefix="reg"):
    """Garantiza tasa BCV vigente cuando falta o la fecha del formulario cambió."""
    ss = st.session_state
    campos = _campos_tasa_formulario(prefix)
    fecha = ss.get(fecha_key) or date.today()
    tasa_actual = float(ss.get(campos["tasa"], 0) or 0)
    if ss.get(campos["fecha_ref"]) != fecha or tasa_actual <= 0:
        aplicar_tasa_bcv_a_formulario(fecha, prefix)


def _on_reg_fecha_cambiada():
    aplicar_tasa_bcv_a_formulario(st.session_state.reg_fecha, "reg")


def _on_prop_fecha_cambiada():
    aplicar_tasa_bcv_a_formulario(st.session_state.prop_fecha, "prop")


def _on_prop_moneda_cambiada():
    if "Bs" in str(st.session_state.get("prop_moneda", "")):
        aplicar_tasa_bcv_a_formulario(st.session_state.prop_fecha, "prop")


def _on_eg_fecha_cambiada():
    aplicar_tasa_bcv_a_formulario(st.session_state.eg_fecha, "eg")


def _leer_tasa_bcv_db():
    with get_connection() as conn:
        fila = conn.execute(
            "SELECT tasa, fecha_valor, actualizado_en FROM tasa_bcv ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not fila:
        return None
    return dict(fila)


def _guardar_tasa_bcv_db(tasa, fecha_valor):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO tasa_bcv (tasa, fecha_valor, actualizado_en) VALUES (?, ?, ?)",
            (float(tasa), fecha_valor or "", datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def _fetch_tasa_bcv_web():
    """Obtiene la tasa USD del BCV desde bcv.org.ve."""
    req = urllib.request.Request(
        BCV_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    match = re.search(
        r"<span>\s*USD\s*</span>[\s\S]{0,500}?<strong[^>]*>([\d,\.]+)</strong>",
        html,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"USD[\s\S]{0,200}?<strong[^>]*>([\d,\.]+)</strong>",
            html,
            re.IGNORECASE,
        )
    if not match:
        return None, None

    tasa = _parse_numero_bcv(match.group(1))

    fecha_match = re.search(
        r"Fecha Valor:\s*[^>]*>([^<]+)</span>",
        html,
        re.IGNORECASE,
    )
    fecha_valor = fecha_match.group(1).strip() if fecha_match else date.today().strftime("%d/%m/%Y")
    return tasa, fecha_valor


@st.cache_data(ttl=3600, show_spinner=False)
def obtener_tasa_bcv():
    """
    Devuelve (tasa_usd, fecha_valor, fuente).
    Se actualiza automáticamente cada hora desde bcv.org.ve.
    Si falla la web, usa el último valor guardado en la base de datos.
    """
    try:
        tasa, fecha_valor = _fetch_tasa_bcv_web()
        if tasa and tasa > 0:
            _guardar_tasa_bcv_db(tasa, fecha_valor)
            dia = _normalizar_fecha_iso(fecha_valor) or date.today().isoformat()
            _actualizar_tasa_historico(dia, tasa)
            return tasa, fecha_valor, "BCV en línea"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        pass

    guardada = _leer_tasa_bcv_db()
    if guardada:
        tasa = float(guardada["tasa"])
        dia = _normalizar_fecha_iso(guardada.get("fecha_valor")) or date.today().isoformat()
        _actualizar_tasa_historico(dia, tasa)
        return (
            tasa,
            guardada.get("fecha_valor") or "—",
            "Última tasa guardada",
        )

    return TASA_BCV_RESPALDO, "—", "Tasa de respaldo"


def monto_a_usd(monto, moneda, tasa_bcv):
    """Convierte cualquier moneda registrada a USD usando tasa BCV para Bs."""
    mon = str(moneda)
    if "USDT" in mon or ("USD" in mon and "Bs" not in mon):
        return float(monto)
    if "Bs" in mon:
        return float(monto) / tasa_bcv if tasa_bcv > 0 else 0.0
    return float(monto)


def monto_neto_banco(monto, comision_pos=0):
    """Monto que realmente ingresa al banco (bruto menos comisión POS)."""
    return float(monto) - float(comision_pos or 0)


def _estado_pago_valor(row):
    v = row.get("estado_pago") if hasattr(row, "get") else getattr(row, "estado_pago", ESTADO_PAGADO)
    return str(v or ESTADO_PAGADO).strip() or ESTADO_PAGADO


def es_cuenta_abierta(row):
    return _estado_pago_valor(row) == ESTADO_CUENTA_ABIERTA


def _tipo_movimiento_valor(row):
    v = row.get("tipo_movimiento") if hasattr(row, "get") else getattr(row, "tipo_movimiento", TIPO_MOV_INGRESO)
    tipo = row.get("tipo") if hasattr(row, "get") else getattr(row, "tipo", "")
    categoria = row.get("categoria") if hasattr(row, "get") else getattr(row, "categoria", "")
    return _inferir_naturaleza_fila(tipo, v, categoria)


def es_egreso(row):
    return _tipo_movimiento_valor(row) == TIPO_MOV_EGRESO


def es_propina_mov(row):
    return _tipo_movimiento_valor(row) == TIPO_MOV_PROPINA


def es_ingreso(row):
    return _tipo_movimiento_valor(row) == TIPO_MOV_INGRESO


def _es_cuenta_efectivo(banco):
    return "efectivo" in str(banco or "").strip().lower()


def _saldos_moneda_vacio():
    return {"usd": 0.0, "bs": 0.0, "usdt": 0.0}


def _clave_moneda_saldo(moneda):
    """Clave interna usada por calcular_saldos_dia (mismo criterio que _calcular_kpis_dia)."""
    mon = str(moneda or "")
    if "USDT" in mon:
        return "usdt"
    if "Bs" in mon:
        return "bs"
    if "USD" in mon:
        return "usd"
    return "usd"


def _monto_neto_abs_fila(row):
    return abs(
        monto_neto_banco(
            _escalar_fila(row, "monto"),
            _escalar_fila(row, "comision_pos"),
        )
    )


def _sumar_por_moneda_df(df):
    """Suma montos netos por moneda sin convertir (patrón _calcular_kpis_dia)."""
    totales = _saldos_moneda_vacio()
    if df.empty:
        return totales
    for _, r in df.iterrows():
        clave = _clave_moneda_saldo(r.get("moneda", ""))
        totales[clave] += _monto_neto_abs_fila(r)
    return totales


def _restar_saldos_moneda(ingresos, egresos):
    return {k: float(ingresos.get(k, 0) or 0) - float(egresos.get(k, 0) or 0) for k in MONEDAS_SALDO}


def _bloque_saldos_vacio():
    return {
        "ingresos": _saldos_moneda_vacio(),
        "egresos": _saldos_moneda_vacio(),
        "saldo": _saldos_moneda_vacio(),
    }


def _bloque_saldos_categoria(ingresos_df, egresos_df):
    ing = _sumar_por_moneda_df(ingresos_df)
    eg = _sumar_por_moneda_df(egresos_df)
    return {"ingresos": ing, "egresos": eg, "saldo": _restar_saldos_moneda(ing, eg)}


def equivalente_a_bs(saldos_moneda, tasa_bcv):
    """Total aproximado en Bs — solo para etiqueta secundaria, nunca como cifra principal."""
    tasa = float(tasa_bcv or 0)
    if tasa <= 0:
        return 0.0
    usd = float(saldos_moneda.get("usd", 0) or 0)
    usdt = float(saldos_moneda.get("usdt", 0) or 0)
    bs = float(saldos_moneda.get("bs", 0) or 0)
    return bs + (usd + usdt) * tasa


def monedas_visibles_kpi(hoy_dict, ayer_dict):
    """Monedas con movimiento en al menos uno de los dos períodos comparados."""
    visibles = []
    for key in MONEDAS_SALDO:
        hoy = float(hoy_dict.get(key, 0) or 0)
        ayer = float(ayer_dict.get(key, 0) or 0)
        if hoy == 0 and ayer == 0:
            continue
        visibles.append(key)
    return visibles


def mini_stats_moneda(saldos_moneda, saldos_ayer_moneda=None):
    ayer = saldos_ayer_moneda if saldos_ayer_moneda is not None else saldos_moneda
    keys = monedas_visibles_kpi(saldos_moneda, ayer)
    if not keys:
        return [("—", "Sin movimiento")]
    items = []
    for key in keys:
        val = float(saldos_moneda.get(key, 0) or 0)
        if key == "bs":
            items.append(("Bs", formatear_bs_etiqueta(val)))
        elif key == "usdt":
            items.append(("USDT", formatear_monto(val, "USDT")))
        else:
            items.append(("USD", formatear_monto(val, "USD")))
    return items


def equivalente_bs_footer_html(saldos_moneda, tasa_bcv, fecha_tasa):
    tasa = float(tasa_bcv or 0)
    if tasa <= 0:
        return ""
    eq = equivalente_a_bs(saldos_moneda, tasa)
    fecha_txt = fecha_tasa if fecha_tasa and str(fecha_tasa) != "—" else "sin fecha"
    return (
        f'<div class="stat-simple-label" style="margin-top:0.45rem;">'
        f'Equivalente a tasa vigente ({fecha_txt}): {tasa:,.2f} Bs/USD → '
        f'{formatear_bs_etiqueta(eq)}</div>'
    )


def hero_metric_multimoneda_card(
    neto, neto_ayer, contexto_line, equivalente_html, etiqueta, delta_label,
    accent_class="",
):
    stats_html = ""
    for lbl, val in mini_stats_moneda(neto, neto_ayer):
        stats_html += (
            f'<div class="mini-stat"><div class="mini-stat-label">{lbl}</div>'
            f'<div class="mini-stat-value">{val}</div></div>'
        )
    delta_html = kpi_delta_multimoneda(neto, neto_ayer, delta_label)
    eq_block = equivalente_html or ""
    extra_cls = f" {accent_class}" if accent_class else ""
    return (
        f'<div class="dash-panel dash-panel-hero{extra_cls}">'
        f'<div class="kpi-label">{etiqueta}</div>'
        f'<div class="mini-stats-row">{stats_html}</div>'
        f'{delta_html}{eq_block}'
        f'<div class="hero-context">{contexto_line}</div>'
        f'</div>'
    )


def flujo_caja_multimoneda_html(ingresos, egresos, neto):
    """Tabla ingresos / egresos / neto por moneda (sin conversión)."""
    visibles = [
        key for key in MONEDAS_SALDO
        if any(float(d.get(key, 0) or 0) != 0 for d in (ingresos, egresos, neto))
    ]
    if not visibles:
        return '<p class="empty-chart-msg">Sin movimientos de caja.</p>'
    cols = {"usd": "USD", "bs": "Bs", "usdt": "USDT"}
    head = "".join(f'<th>{cols[k]}</th>' for k in visibles)
    filas = [
        ("Ingresos", ingresos),
        ("Egresos", egresos),
        ("Neto líquido", neto),
    ]
    body = ""
    for titulo, datos in filas:
        celdas = ""
        for key in visibles:
            if key == "bs":
                celdas += f'<td>{formatear_bs_etiqueta(datos.get(key, 0))}</td>'
            elif key == "usdt":
                celdas += f'<td>{formatear_monto(datos.get(key, 0), "USDT")}</td>'
            else:
                celdas += f'<td>{formatear_monto(datos.get(key, 0), "USD")}</td>'
        body += f'<tr><td>{titulo}</td>{celdas}</tr>'
    return (
        f'<table class="flujo-moneda-table">'
        f'<thead><tr><th></th>{head}</tr></thead>'
        f'<tbody>{body}</tbody></table>'
    )


def _monto_en_bs(row, tasa_bcv=0.0):
    """Convierte el monto neto del movimiento a bolívares."""
    bruto = abs(monto_neto_banco(row.get("monto", 0), row.get("comision_pos", 0)))
    moneda = str(row.get("moneda", ""))
    if "Bs" in moneda:
        return bruto
    tasa = float(row.get("tasa_bcv", 0) or 0)
    if tasa <= 0:
        tasa = float(tasa_bcv or 0)
    if tasa <= 0:
        tasa, _, _ = obtener_tasa_bcv()
    return bruto * tasa


def monto_impacto_caja(row):
    """Impacto con signo en caja: positivo ingreso, negativo egreso."""
    if _es_consumo_credito(row):
        return 0.0
    if es_cuenta_abierta(row):
        return 0.0
    monto = monto_neto_banco(
        _escalar_fila(row, "monto"),
        _escalar_fila(row, "comision_pos"),
    )
    return -abs(monto) if es_egreso(row) else float(monto)


def calcular_saldos_dia(df_caja):
    """Saldos netos del día desglosados por moneda (sin conversión silenciosa)."""
    vacio = {
        "ingresos": _saldos_moneda_vacio(),
        "egresos": _saldos_moneda_vacio(),
        "neto": _saldos_moneda_vacio(),
        "banco": _bloque_saldos_vacio(),
        "efectivo": _bloque_saldos_vacio(),
        "egresos_count": 0,
    }
    if df_caja.empty:
        return vacio

    ingresos = df_caja[df_caja.apply(es_ingreso, axis=1)]
    egresos = df_caja[df_caja.apply(es_egreso, axis=1)]

    ing = _sumar_por_moneda_df(ingresos)
    eg = _sumar_por_moneda_df(egresos)
    neto = _restar_saldos_moneda(ing, eg)

    ing_banco = ingresos[~ingresos["banco"].apply(_es_cuenta_efectivo)]
    eg_banco = egresos[~egresos["banco"].apply(_es_cuenta_efectivo)]
    ing_efect = ingresos[ingresos["banco"].apply(_es_cuenta_efectivo)]
    eg_efect = egresos[egresos["banco"].apply(_es_cuenta_efectivo)]

    return {
        "ingresos": ing,
        "egresos": eg,
        "neto": neto,
        "banco": _bloque_saldos_categoria(ing_banco, eg_banco),
        "efectivo": _bloque_saldos_categoria(ing_efect, eg_efect),
        "egresos_count": len(egresos),
    }


def estado_pago_desde_ui(etiqueta_ui):
    texto = str(etiqueta_ui or "")
    if "Cuenta Abierta" in texto or "Paga luego" in texto:
        return ESTADO_CUENTA_ABIERTA
    return ESTADO_PAGADO


def _escalar_fila(row, campo, default=0.0):
    """Extrae un float de una fila apply() aunque haya columnas duplicadas."""
    if campo not in row.index:
        return float(default)
    val = row[campo]
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return float(default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(default)


def monto_neto_caja(row):
    """Neto que impacta la caja del día (0 si la cuenta sigue abierta)."""
    if _es_consumo_credito(row):
        return 0.0
    if es_cuenta_abierta(row):
        return 0.0
    return monto_neto_banco(
        _escalar_fila(row, "monto"),
        _escalar_fila(row, "comision_pos"),
    )


def movimiento_en_flujo_caja(row, fecha_inicio, fecha_fin=None):
    """True si el movimiento suma al flujo de caja del rango consultado."""
    if fecha_fin is None:
        fecha_fin = fecha_inicio
    if _es_consumo_credito(row):
        return False
    if es_cuenta_abierta(row):
        return False
    fp = str(row.get("fecha_pago") or "").strip()
    if fp:
        try:
            d = pd.to_datetime(fp).date()
            return fecha_inicio <= d <= fecha_fin
        except (ValueError, TypeError):
            pass
    try:
        d = pd.to_datetime(row["fecha"]).date()
        return fecha_inicio <= d <= fecha_fin
    except (ValueError, TypeError):
        return False


def df_flujo_caja(df, fecha_inicio, fecha_fin=None):
    if df.empty:
        return df
    return df[df.apply(lambda r: movimiento_en_flujo_caja(r, fecha_inicio, fecha_fin), axis=1)].copy()


def cargar_movimientos_panel_dia(fecha_inicio, fecha_fin=None):
    """Movimientos del rango + cobros de cuentas abiertas cerradas dentro del rango."""
    if fecha_fin is None:
        fecha_fin = fecha_inicio
    df_periodo = cargar_movimientos(fecha_desde=fecha_inicio, fecha_hasta=fecha_fin)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM movimientos
            WHERE TRIM(COALESCE(fecha_pago, '')) != ''
              AND date(fecha_pago) >= date(?)
              AND date(fecha_pago) <= date(?)
              AND (date(fecha) < date(?) OR date(fecha) > date(?))
              AND COALESCE(es_consumo_credito, 0) = 0
            """,
            (
                fecha_inicio.isoformat(),
                fecha_fin.isoformat(),
                fecha_inicio.isoformat(),
                fecha_fin.isoformat(),
            ),
        ).fetchall()
    if not rows:
        return df_periodo
    df_cobros = pd.DataFrame([dict(r) for r in rows])
    return pd.concat([df_periodo, df_cobros], ignore_index=True).drop_duplicates(subset=["id"])


def _es_consumo_credito(row):
    v = row.get("es_consumo_credito") if hasattr(row, "get") else getattr(row, "es_consumo_credito", 0)
    return bool(int(v or 0))


def _monto_neto_deuda(row):
    """Monto neto de un movimiento de consumo a crédito."""
    bruto = float(row.get("monto", 0) if hasattr(row, "get") else row["monto"])
    com = float(row.get("comision_pos", 0) if hasattr(row, "get") else row.get("comision_pos", 0) or 0)
    moneda = str(row.get("moneda", "") if hasattr(row, "get") else row["moneda"])
    if "Bs" in moneda:
        return bruto - com
    return bruto


def formatear_saldo_cobrar(monto, moneda):
    return formatear_monto(monto, moneda)


def monedas_misma_familia(moneda_a, moneda_b):
    return _clave_moneda_saldo(moneda_a) == _clave_moneda_saldo(moneda_b)


def convertir_monto_entre_monedas(monto, moneda_origen, moneda_destino, tasa_bcv):
    """
    Convierte monto entre monedas usando tasa BCV explícita.
    Devuelve (monto_en_moneda_destino, tasa_usada). tasa_usada=0 si no hubo conversión.
    """
    monto = float(monto or 0)
    if monedas_misma_familia(moneda_origen, moneda_destino):
        return monto, 0.0

    tasa = float(tasa_bcv or 0)
    if tasa <= 0:
        return monto, 0.0

    origen = _clave_moneda_saldo(moneda_origen)
    destino = _clave_moneda_saldo(moneda_destino)

    if origen == "bs":
        usd = monto / tasa
    else:
        usd = monto

    if destino == "bs":
        return usd * tasa, tasa
    return usd, tasa


def monto_pago_para_cubrir_saldo(saldo_deuda, moneda_deuda, moneda_pago, tasa_bcv):
    """Cuánto cobrar en moneda_pago para cubrir saldo_deuda en moneda_deuda."""
    monto, _ = convertir_monto_entre_monedas(saldo_deuda, moneda_deuda, moneda_pago, tasa_bcv)
    return monto


def _deuda_por_moneda_cliente(cedula):
    cedula = _normalizar_cedula(cedula)
    totales = {}
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT monto, moneda, comision_pos
            FROM movimientos
            WHERE UPPER(TRIM(cliente_cedula)) = ?
              AND COALESCE(estado_pago, 'Pagado') = ?
              AND COALESCE(tipo_movimiento, 'Ingreso') = 'Ingreso'
            """,
            (cedula, ESTADO_CUENTA_ABIERTA),
        ).fetchall()
    for r in rows:
        mon = str(dict(r).get("moneda") or "Bs (Bolívares)")
        totales[mon] = totales.get(mon, 0.0) + _monto_neto_deuda(dict(r))
    return totales


def _pagos_aplicados_por_moneda_cliente(cedula):
    cedula = _normalizar_cedula(cedula)
    totales = {}
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT moneda, moneda_deuda, monto, monto_aplicado_deuda
            FROM pagos_cliente
            WHERE UPPER(TRIM(cliente_cedula)) = ?
            """,
            (cedula,),
        ).fetchall()
    for r in rows:
        row = dict(r)
        mon_deuda = str(row.get("moneda_deuda") or row.get("moneda") or "")
        aplicado = float(row.get("monto_aplicado_deuda") or 0)
        if aplicado <= 0:
            aplicado = float(row.get("monto") or 0)
        totales[mon_deuda] = totales.get(mon_deuda, 0.0) + aplicado
    return totales


def saldos_por_moneda_cliente(cedula):
    """Desglose de deuda / pagado / saldo por moneda original."""
    deudas = _deuda_por_moneda_cliente(cedula)
    pagos = _pagos_aplicados_por_moneda_cliente(cedula)
    monedas = set(deudas.keys()) | set(pagos.keys())
    resultado = []
    for mon in monedas:
        deuda = float(deudas.get(mon, 0) or 0)
        pagado = float(pagos.get(mon, 0) or 0)
        saldo = max(0.0, deuda - pagado)
        if deuda > 0 or pagado > 0 or saldo > 0:
            resultado.append({
                "moneda": mon,
                "deuda_original": deuda,
                "total_pagado": pagado,
                "saldo": saldo,
            })
    return resultado


def saldo_pendiente_cliente(cedula, moneda=None):
    saldos = saldos_por_moneda_cliente(cedula)
    if moneda:
        for s in saldos:
            if monedas_misma_familia(s["moneda"], moneda):
                return float(s["saldo"])
        return 0.0
    return sum(float(s["saldo"]) for s in saldos)


def cliente_totalmente_saldado(cedula):
    return all(s["saldo"] <= 0.0001 for s in saldos_por_moneda_cliente(cedula))


def totales_cobrar_por_moneda(pendientes):
    totales = _saldos_moneda_vacio()
    for p in pendientes:
        clave = _clave_moneda_saldo(p.get("moneda", ""))
        totales[clave] += float(p.get("saldo_pendiente") or 0)
    return totales


def contar_clientes_con_saldo(pendientes):
    return len({p["cedula"] for p in pendientes})


def _clave_cobrar_fila(cedula, moneda):
    return f"{cedula}|{moneda}"


def _parse_clave_cobrar_fila(clave):
    cedula, moneda = clave.split("|", 1)
    return cedula, moneda


def cargar_cuentas_por_cobrar_completo():
    """Filas con saldo pendiente por cliente y moneda (sin mezclar monedas)."""
    with get_connection() as conn:
        deudas = conn.execute(
            """
            SELECT
                UPPER(TRIM(cliente_cedula)) AS cedula,
                MAX(cliente_nombre) AS nombre,
                moneda,
                SUM(
                    CASE WHEN moneda LIKE '%Bs%'
                    THEN monto - COALESCE(comision_pos, 0)
                    ELSE monto END
                ) AS deuda_original,
                MIN(fecha) AS fecha_mas_antigua,
                COUNT(*) AS movimientos
            FROM movimientos
            WHERE COALESCE(estado_pago, 'Pagado') = ?
              AND COALESCE(tipo_movimiento, 'Ingreso') = 'Ingreso'
              AND TRIM(COALESCE(cliente_cedula, '')) != ''
            GROUP BY UPPER(TRIM(cliente_cedula)), moneda
            """,
            (ESTADO_CUENTA_ABIERTA,),
        ).fetchall()
        pagos = conn.execute(
            """
            SELECT
                UPPER(TRIM(cliente_cedula)) AS cedula,
                COALESCE(NULLIF(TRIM(moneda_deuda), ''), moneda) AS moneda_deuda,
                SUM(
                    CASE WHEN COALESCE(monto_aplicado_deuda, 0) > 0
                    THEN monto_aplicado_deuda
                    ELSE monto END
                ) AS total_pagado,
                MAX(fecha) AS fecha_ultimo_pago
            FROM pagos_cliente
            GROUP BY UPPER(TRIM(cliente_cedula)),
                     COALESCE(NULLIF(TRIM(moneda_deuda), ''), moneda)
            """
        ).fetchall()
    pagos_map = {(r["cedula"], r["moneda_deuda"]): dict(r) for r in pagos}
    resultado = []
    for d in deudas:
        cedula = d["cedula"]
        moneda = d["moneda"] or "Bs (Bolívares)"
        deuda = float(d["deuda_original"] or 0)
        p = pagos_map.get((cedula, moneda), {})
        pagado = float(p.get("total_pagado") or 0)
        saldo = max(0.0, deuda - pagado)
        if saldo <= 0.0001:
            continue
        ultimo = p.get("fecha_ultimo_pago") or ""
        resultado.append({
            "cedula": cedula,
            "nombre": d["nombre"] or "",
            "moneda": moneda,
            "deuda_original": deuda,
            "total_pagado": pagado,
            "monto_pendiente": saldo,
            "saldo_pendiente": saldo,
            "fecha_mas_antigua": d["fecha_mas_antigua"],
            "fecha_ultimo_pago": ultimo,
            "movimientos": int(d["movimientos"] or 0),
            "clave_fila": _clave_cobrar_fila(cedula, moneda),
        })
    resultado.sort(key=lambda x: x["saldo_pendiente"], reverse=True)
    return resultado


def cargar_cuentas_abiertas_resumen():
    """Compatibilidad — misma fuente que cuentas por cobrar."""
    return cargar_cuentas_por_cobrar_completo()


def cargar_historial_pagos_cliente(cedula):
    cedula = _normalizar_cedula(cedula)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, fecha, monto, moneda, moneda_deuda, monto_aplicado_deuda,
                   tasa_conversion, metodo, banco, notas, creado_en
            FROM pagos_cliente
            WHERE UPPER(TRIM(cliente_cedula)) = ?
            ORDER BY datetime(fecha) DESC, id DESC
            """,
            (cedula,),
        ).fetchall()
    return [dict(r) for r in rows]


def _finalizar_consumos_credito_cliente(cedula, fecha_pago, banco, metodo):
    """Marca consumos abiertos como pagados cuando el saldo llega a cero."""
    cedula = _normalizar_cedula(cedula)
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE movimientos
            SET estado_pago = ?,
                fecha_pago = ?,
                banco = ?,
                metodo_detalle = CASE WHEN ? != '' THEN ? ELSE metodo_detalle END
            WHERE UPPER(TRIM(cliente_cedula)) = ?
              AND COALESCE(estado_pago, 'Pagado') = ?
              AND COALESCE(tipo_movimiento, 'Ingreso') = 'Ingreso'
            """,
            (
                ESTADO_PAGADO,
                fecha_pago,
                banco,
                metodo,
                metodo,
                cedula,
                ESTADO_CUENTA_ABIERTA,
            ),
        )
        conn.commit()
        return cur.rowcount


def registrar_pago_cliente(
    cedula, monto, metodo_key, moneda_deuda=None, fecha_hora=None, notas=""
):
    """
    Registra un pago (parcial o total) contra la deuda del cliente en moneda_deuda.
    Guarda monto/moneda real del cobro + equivalente aplicado a la deuda + tasa usada.
    """
    cedula = _normalizar_cedula(cedula)
    monto = float(monto)
    if monto <= 0:
        return False, "El monto debe ser mayor a cero."

    if metodo_key not in METODOS_COBRO_CLIENTE:
        return False, "Método de pago no válido."

    info_met = METODOS_COBRO_CLIENTE[metodo_key]
    moneda_pago = info_met["moneda_default"]
    fecha_hora = fecha_hora or datetime.now().isoformat(timespec="seconds")

    try:
        fecha_pago = pd.to_datetime(fecha_hora).date()
    except (ValueError, TypeError):
        fecha_pago = date.today()

    with get_connection() as conn:
        row_cli = conn.execute(
            """
            SELECT MAX(cliente_nombre) AS nombre
            FROM movimientos
            WHERE UPPER(TRIM(cliente_cedula)) = ?
              AND COALESCE(estado_pago, 'Pagado') = ?
            """,
            (cedula, ESTADO_CUENTA_ABIERTA),
        ).fetchone()
    if not row_cli:
        return False, "No se encontraron consumos abiertos para este cliente."

    nombre = row_cli["nombre"] or ""
    saldos = [s for s in saldos_por_moneda_cliente(cedula) if s["saldo"] > 0.0001]
    if not saldos:
        return False, "Este cliente no tiene saldo pendiente."

    if not moneda_deuda:
        if len(saldos) == 1:
            moneda_deuda = saldos[0]["moneda"]
        else:
            return False, "Indique la moneda de la deuda a cobrar."

    saldo_deuda = saldo_pendiente_cliente(cedula, moneda_deuda)
    if saldo_deuda <= 0:
        return False, "No hay saldo pendiente en esa moneda."

    tasa_pago, _, aviso_tasa = resolver_tasa_para_fecha(fecha_pago)
    if not monedas_misma_familia(moneda_pago, moneda_deuda) and tasa_pago <= 0:
        msg = aviso_tasa or "No hay tasa BCV para la fecha del pago."
        return False, f"No se puede convertir entre monedas: {msg}"

    monto_aplicado, tasa_usada = convertir_monto_entre_monedas(
        monto, moneda_pago, moneda_deuda, tasa_pago
    )

    if monto_aplicado > saldo_deuda + 0.01:
        return False, (
            f"El pago equivale a {formatear_saldo_cobrar(monto_aplicado, moneda_deuda)} "
            f"y supera el saldo pendiente "
            f"({formatear_saldo_cobrar(saldo_deuda, moneda_deuda)})."
        )

    tasa_mov = float(tasa_pago) if "Bs" in moneda_pago else 0.0

    mov_id = guardar_movimiento(
        fecha_hora,
        "Ingreso bancario" if info_met["banco"] != "Efectivo en caja" else "Efectivo en caja",
        monto,
        moneda_pago,
        info_met["banco"],
        "",
        f"Cobro cuenta abierta — {nombre} ({cedula})"
        + (f" · {notas}" if notas else ""),
        estado_pago=ESTADO_PAGADO,
        fecha_pago=fecha_hora,
        metodo_detalle=info_met["metodo"],
        cliente_nombre=nombre,
        cliente_cedula=cedula,
        es_consumo_credito=False,
        tasa_bcv=tasa_mov,
        tipo_movimiento=TIPO_MOV_INGRESO,
        categoria=CATEGORIA_INGRESO_DEFAULT,
    )

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pagos_cliente
                (cliente_cedula, cliente_nombre, fecha, monto, moneda,
                 moneda_deuda, monto_aplicado_deuda, tasa_conversion,
                 metodo, banco, notas, movimiento_caja_id, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cedula,
                nombre,
                fecha_hora,
                monto,
                moneda_pago,
                moneda_deuda,
                monto_aplicado,
                float(tasa_usada or 0),
                info_met["label"],
                info_met["banco"],
                notas or "",
                mov_id,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()

    if tasa_mov > 0:
        _actualizar_tasa_historico(fecha_pago.isoformat(), tasa_mov)

    nuevo_saldo = saldo_pendiente_cliente(cedula, moneda_deuda)
    if cliente_totalmente_saldado(cedula):
        _finalizar_consumos_credito_cliente(
            cedula, fecha_hora, info_met["banco"], info_met["metodo"]
        )
        return True, "Pago registrado. Cuenta saldada por completo."

    return True, (
        f"Pago parcial registrado. Saldo restante en {moneda_deuda.split('(')[0].strip()}: "
        f"{formatear_saldo_cobrar(nuevo_saldo, moneda_deuda)}."
    )


def cerrar_cuenta_cliente(cedula, canal_label):
    """Compatibilidad — cierra saldo completo vía registrar_pago_cliente (por moneda)."""
    saldos = [s for s in saldos_por_moneda_cliente(cedula) if s["saldo"] > 0.0001]
    if not saldos:
        return 0
    mapa_legacy = {
        "Efectivo": "Efectivo en caja",
        "Punto / POS": "POS / Tarjeta",
        "Zelle / Digital": "Zelle / Digital",
    }
    metodo = mapa_legacy.get(canal_label, "Efectivo en caja")
    if metodo not in METODOS_COBRO_CLIENTE:
        metodo = "Efectivo en caja"
    info_met = METODOS_COBRO_CLIENTE[metodo]
    moneda_pago = info_met["moneda_default"]
    tasa_pago, _, _ = resolver_tasa_para_fecha(date.today())
    cerrados = 0
    for s in saldos:
        monto_cobro = monto_pago_para_cubrir_saldo(
            s["saldo"], s["moneda"], moneda_pago, tasa_pago
        )
        ok, _ = registrar_pago_cliente(
            cedula, monto_cobro, metodo, moneda_deuda=s["moneda"]
        )
        if ok:
            cerrados += 1
    return cerrados


def monto_a_usd_fila(row, tasa_fallback):
    """Convierte el monto neto al banco a USD usando la tasa BCV del registro."""
    neto = monto_neto_banco(row["monto"], row.get("comision_pos", 0))
    tasa = float(row.get("tasa_bcv", 0) or 0)
    if tasa <= 0:
        tasa = float(tasa_fallback)
    return monto_a_usd(neto, row["moneda"], tasa)


def formatear_usd(valor):
    if pd.isna(valor):
        return "—"
    return f"${float(valor):,.2f}"


GRUPOS_RESUMEN_INGRESOS = {
    "Efectivo": ["Efectivo en caja"],
    "Banco": ["Ingreso bancario"],
    "Pago USDT": ["Pago USDT"],
    "Zelle / Digital": ["Zelle / Digital"],
}

COLORES_GRUPO_INGRESO = {
    "Efectivo": GIARDINO_CASH,
    "Banco": GIARDINO_BANK,
    "Pago USDT": "#0F766E",
    "Zelle / Digital": "#059669",
}


def _tipo_a_grupo_ingreso(tipo):
    for grupo, tipos in GRUPOS_RESUMEN_INGRESOS.items():
        if tipo in tipos:
            return grupo
    return None


def resumen_ingresos_cuatro_grupos_usd(df_caja, tasa_bcv):
    """Totales en USD equivalente para Efectivo, Banco, USDT y Zelle."""
    vacio = pd.DataFrame(columns=["grupo", "usd"])
    if df_caja.empty:
        return vacio

    df_ing = df_caja[
        df_caja.apply(lambda r: es_ingreso(r) and not es_cuenta_abierta(r), axis=1)
    ].copy()
    df_ing = df_ing[df_ing["tipo"] != "Propina"]
    if df_ing.empty:
        return vacio

    totales = {g: 0.0 for g in GRUPOS_RESUMEN_INGRESOS}
    for _, r in df_ing.iterrows():
        grupo = _tipo_a_grupo_ingreso(r["tipo"])
        if grupo:
            totales[grupo] += monto_a_usd_fila(r, tasa_bcv)

    filas = [{"grupo": k, "usd": v} for k, v in totales.items() if v > 0]
    if not filas:
        return vacio
    return pd.DataFrame(filas).sort_values("usd", ascending=False)


def tabla_ingresos_usd_html(resumen_df):
    if resumen_df.empty:
        return '<p class="empty-chart-msg">Sin ingresos en los 4 grupos principales.</p>'
    filas = ""
    for _, r in resumen_df.iterrows():
        filas += (
            f'<tr><td>{r["grupo"]}</td>'
            f'<td>{formatear_usd(r["usd"])}</td></tr>'
        )
    return (
        f'<table class="ingresos-usd-table">'
        f'<thead><tr><th>Categoría</th><th>USD equivalente</th></tr></thead>'
        f'<tbody>{filas}</tbody></table>'
    )


def grafico_dona_ingresos_grupos(resumen_df, height=300):
    if resumen_df.empty:
        return None
    colores = [COLORES_GRUPO_INGRESO.get(g, GIARDINO_SUBTLE) for g in resumen_df["grupo"]]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=resumen_df["grupo"],
                values=resumen_df["usd"],
                hole=0.4,
                marker=dict(colors=colores),
                textinfo="percent",
                textposition="inside",
                opacity=0.92,
                showlegend=False,
                name="Ingresos por grupo",
                hovertemplate="%{label}<br>%{percent}<br>$%{value:,.2f}<extra></extra>",
            )
        ]
    )
    finalizar_grafico(fig, height=height, leyenda=False)
    return fig


def total_comision_pos(df):
    if df.empty or "comision_pos" not in df.columns:
        return 0.0
    return float(df["comision_pos"].fillna(0).sum())


def formatear_bs_etiqueta(valor):
    """Formato compacto para etiquetas del gráfico POS: Bs 56.783"""
    entero = int(round(float(valor or 0)))
    return f"Bs {entero:,}".replace(",", ".")


def pos_kpi_card(titulo, valor):
    """Tarjeta POS — mismo marco que dash-panel."""
    return (
        f'<div class="dash-panel accent-ventas" style="margin-bottom:0;height:100%;">'
        f'<div class="mini-stat-label">{titulo}</div>'
        f'<div class="mini-stat-value" style="font-size:1.55rem;">{valor}</div>'
        f'</div>'
    )


def pos_movimientos_card(total, credito, debito):
    """Tarjeta con conteo de movimientos POS dividido crédito / débito."""
    return (
        f'<div class="dash-panel accent-ventas" style="margin-bottom:12px;">'
        f'<div class="kpi-grupo-title">Movimientos POS ({total})</div>'
        f'<div class="mini-stats-row">'
        f'<div class="mini-stat">'
        f'<div class="mini-stat-label">Crédito</div>'
        f'<div class="mini-stat-value">{credito}</div>'
        f'</div>'
        f'<div class="mini-stat">'
        f'<div class="mini-stat-label">Débito</div>'
        f'<div class="mini-stat-value">{debito}</div>'
        f'</div>'
        f'</div></div>'
    )


def _filtrar_movimientos_pos(df):
    """Ingresos bancarios cobrados por POS / Tarjeta (crédito y débito)."""
    col_metodo = df.get("metodo_detalle", pd.Series("", index=df.index)).astype(str).str.strip()
    return df[col_metodo == "POS / Tarjeta"].copy()


def calcular_metricas_pos(df):
    """Calcula métricas de conciliación POS del día (solo ingresos en flujo de caja)."""
    if df.empty:
        return None

    df = df[df.apply(es_ingreso, axis=1)].copy()
    df = df[~df.apply(es_cuenta_abierta, axis=1)].copy()
    if df.empty:
        return None

    df_pos = _filtrar_movimientos_pos(df)
    if df_pos.empty:
        return None

    bruto = float(df_pos["monto"].sum())
    comision = float(df_pos.get("comision_pos", pd.Series(0, index=df_pos.index)).fillna(0).sum())
    neto_pos = float(
        df_pos.apply(
            lambda r: monto_neto_banco(r["monto"], r.get("comision_pos", 0)),
            axis=1,
        ).sum()
    )

    col_credito = df_pos.get("es_tarjeta_credito", pd.Series(0, index=df_pos.index)).fillna(0)
    mov_credito = int((col_credito.astype(int) > 0).sum())
    mov_debito = len(df_pos) - mov_credito

    df_ingreso = df[df["tipo"] == "Ingreso bancario"]
    ingreso_bancario = float(
        df_ingreso.apply(
            lambda r: monto_neto_caja(r),
            axis=1,
        ).sum()
    )

    return {
        "ingreso_bancario": ingreso_bancario,
        "bruto_pos": bruto,
        "comision": comision,
        "neto_pos": neto_pos,
        "mov_total": len(df_pos),
        "mov_credito": mov_credito,
        "mov_debito": mov_debito,
    }


def grafico_conciliacion_pos(bruto, comision, neto):
    """Gráfico de 3 barras verticales — conciliación POS premium."""
    categorias = ["Bruto POS", "Comisión 5%", "Neto al banco"]
    valores = [bruto, comision, neto]
    colores = [GIARDINO_BRAND_GREEN, GIARDINO_SUBTLE, GIARDINO_BANK]
    etiquetas = [formatear_bs_etiqueta(v) for v in valores]

    fig = go.Figure(
        data=[
            go.Bar(
                x=categorias,
                y=valores,
                marker=dict(color=colores, line=dict(width=0)),
                text=etiquetas,
                textposition="outside",
                textfont=dict(color=GIARDINO_TEXT_DARK, size=14, family="Inter"),
                cliponaxis=False,
                showlegend=False,
                name="Conciliación POS",
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        ]
    )

    finalizar_grafico(fig, height=300, leyenda=False)
    fig.update_layout(margin=dict(t=48, b=24, l=8, r=8))
    max_y = max(valores) if valores else 0
    aplicar_eje_y_limpio(fig, max_y)
    fig.update_xaxes(
        showgrid=False,
        zeroline=True,
        zerolinecolor="rgba(0,0,0,0.08)",
        zerolinewidth=1,
        showline=False,
        title=None,
        tickfont=dict(color=GIARDINO_MUTED, size=11),
    )
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        showticklabels=True,
        title=None,
        tickfont=dict(color=GIARDINO_SUBTLE, size=11),
        gridcolor="rgba(0,0,0,0)",
    )
    return fig


def resumen_por_banco_en_usd(df, tasa_bcv):
    """Agrupa ingresos y egresos por banco — saldo neto en USD."""
    con_banco = df[df["banco"].astype(str).str.strip() != ""].copy()
    if con_banco.empty:
        return pd.DataFrame()

    con_banco["monto_usd"] = con_banco.apply(
        lambda r: -monto_a_usd_fila(r, tasa_bcv) if es_egreso(r) else monto_a_usd_fila(r, tasa_bcv),
        axis=1,
    )
    return (
        con_banco.groupby("banco", as_index=False)["monto_usd"]
        .sum()
        .sort_values("monto_usd", ascending=False)
    )


def finalizar_grafico(fig, height=320, leyenda=False):
    """Aplica tema claro Il Giardino. Sin leyenda visible ni textos fantasma."""
    estilo_plotly(fig, height=height)

    fig.for_each_trace(
        lambda t: t.update(
            showlegend=False,
            legendgroup=None,
            legendgrouptitle_text=None,
        )
    )

    fig.update_layout(
        showlegend=False,
        legend_title_text="",
        title=None,
        coloraxis_showscale=False,
        margin=dict(t=10, b=30, l=10, r=10),
        xaxis_title=None,
        yaxis_title=None,
        annotations=[],
    )

    try:
        fig.update_coloraxes(showscale=False, colorbar=dict(thickness=0, len=0))
    except (ValueError, AttributeError):
        pass

    return fig


def _ticks_eje_y(max_val):
    if max_val <= 0:
        return [0]
    return [0, max_val / 2, max_val]


def _formato_tick_y(valor):
    v = float(valor)
    if v >= 1000:
        return formatear_bs_etiqueta(v).replace("Bs ", "")
    return f"{int(round(v))}"


def aplicar_eje_y_limpio(fig, max_y):
    ticks = _ticks_eje_y(max_y)
    fig.update_yaxes(
        tickmode="array",
        tickvals=ticks,
        ticktext=[_formato_tick_y(t) for t in ticks],
        tickfont=dict(color=GIARDINO_MUTED, size=12),
        showgrid=False,
        zeroline=False,
        title=None,
    )


def grafico_barras_categoria(por_tipo, height=300):
    col = "monto_neto"
    max_y = float(por_tipo[col].max()) if not por_tipo.empty else 0
    textos = [formatear_bs_etiqueta(v) for v in por_tipo[col]]
    colores = [
        TIPOS_MOVIMIENTO.get(t, {}).get("color", GIARDINO_SUBTLE)
        for t in por_tipo["tipo"]
    ]
    fig = go.Figure(
        data=[
            go.Bar(
                x=por_tipo["tipo"],
                y=por_tipo[col],
                marker_color=colores,
                marker_line_width=0,
                text=textos,
                textposition="outside",
                textfont=dict(color=GIARDINO_TEXT_DARK, size=13),
                cliponaxis=False,
                showlegend=False,
                name="Ingresos por categoría",
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        ]
    )
    finalizar_grafico(fig, height=height, leyenda=False)
    fig.update_layout(margin=dict(t=44, b=30, l=8, r=8))
    fig.update_xaxes(
        tickangle=-25,
        showgrid=False,
        tickfont=dict(color=GIARDINO_MUTED, size=12),
    )
    aplicar_eje_y_limpio(fig, max_y)
    return fig


def grafico_flujo_caja_dia(ingresos_bs, egresos_bs, neto_bs, height=300):
    """Barras: Ingresos, Egresos y Neto líquido del día."""
    categorias = ["Ingresos", "Egresos", "Neto líquido"]
    valores = [ingresos_bs, egresos_bs, neto_bs]
    colores = [GIARDINO_BANK, GIARDINO_EXPENSE, GIARDINO_BRAND_GREEN]
    textos = [formatear_bs_etiqueta(v) for v in valores]

    fig = go.Figure(
        data=[
            go.Bar(
                x=categorias,
                y=valores,
                marker=dict(color=colores, line=dict(width=0)),
                text=textos,
                textposition="outside",
                textfont=dict(color=GIARDINO_TEXT_DARK, size=13, family="Inter"),
                cliponaxis=False,
                showlegend=False,
                name="Flujo de caja",
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        ]
    )
    finalizar_grafico(fig, height=height, leyenda=False)
    fig.update_layout(margin=dict(t=44, b=30, l=8, r=8))
    max_y = max(max(abs(v) for v in valores), ingresos_bs, egresos_bs) if valores else 0
    fig.update_xaxes(showgrid=False, tickfont=dict(color=GIARDINO_MUTED, size=12))
    aplicar_eje_y_limpio(fig, max_y)
    return fig


def kpi_card_mini(label, valor):
    """KPI compacto neutro (historial y resúmenes)."""
    return (
        f'<div class="dash-panel accent-brand" style="flex:1;min-width:150px;margin-bottom:0;">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="mini-stat-value" style="font-size:1.45rem;">{valor}</div>'
        f'</div>'
    )


# =============================================================================
# PANTALLAS
# =============================================================================

def _calcular_kpis_dia(df, fecha_inicio=None, fecha_fin=None):
    """Separa ventas reales de propinas; excluye cuentas abiertas del flujo de caja."""
    if df.empty:
        return {
            "ventas_usd": 0, "ventas_bs": 0, "ventas_usdt": 0,
            "prop_usd": 0, "prop_bs": 0, "total_mov": 0, "ventas_mov": 0,
            "comensales": 0,
            "cuentas_abiertas": 0,
        }

    if fecha_inicio is not None:
        if fecha_fin is None:
            fecha_fin = fecha_inicio
        df_caja = df_flujo_caja(df, fecha_inicio, fecha_fin)
        fechas = pd.to_datetime(df["fecha"], errors="coerce").dt.date
        cuentas_abiertas = int(
            df[
                df.apply(es_cuenta_abierta, axis=1)
                & fechas.between(fecha_inicio, fecha_fin)
            ].shape[0]
        )
        df_periodo = df[fechas.between(fecha_inicio, fecha_fin)].copy()
    else:
        df_caja = df[~df.apply(es_cuenta_abierta, axis=1)].copy()
        cuentas_abiertas = int(df.apply(es_cuenta_abierta, axis=1).sum())
        df_periodo = df.copy()

    df_ventas = df_caja[
        df_caja.apply(es_ingreso, axis=1) & (df_caja["tipo"] != "Propina")
    ].copy()
    if df_ventas.empty:
        ventas_usd = ventas_bs = ventas_usdt = 0.0
    else:
        df_ventas["neto"] = df_ventas.apply(monto_neto_caja, axis=1)
        ventas_usd  = df_ventas[df_ventas["moneda"].str.contains("USD",  na=False)]["monto"].sum()
        ventas_bs   = df_ventas[df_ventas["moneda"].str.contains("Bs",   na=False)]["neto"].sum()
        ventas_usdt = df_ventas[df_ventas["moneda"].str.contains("USDT", na=False)]["monto"].sum()

    # Comensales atendidos: ventas Ingreso (tipo != Propina) del período, SIN filtro
    # df_flujo_caja — incluye cuentas abiertas (personas atendidas aunque no hayan pagado).
    # NOTA: cantidad_personas es por movimiento, no por mesa/orden; un pago dividido
    # (ej. banco + efectivo) sumará comensales dos veces. Comportamiento conocido.
    df_ventas_comensales = df_periodo[
        df_periodo.apply(es_ingreso, axis=1) & (df_periodo["tipo"] != "Propina")
    ].copy()
    if df_ventas_comensales.empty or "cantidad_personas" not in df_ventas_comensales.columns:
        comensales = 0
    else:
        comensales = int(
            df_ventas_comensales["cantidad_personas"].fillna(1).astype(int).sum()
        )

    df_propinas = df_caja[df_caja.apply(es_propina_mov, axis=1)].copy()
    if df_propinas.empty:
        prop_tipo_usd = prop_tipo_bs = 0.0
    else:
        prop_tipo_usd = df_propinas[
            df_propinas["moneda"].str.contains("USD", na=False)
        ]["monto"].sum()
        prop_tipo_bs = df_propinas[
            df_propinas["moneda"].str.contains("Bs", na=False)
        ]["monto"].sum()

    if "propina" in df_caja.columns and "propina_moneda" in df_caja.columns:
        prop_col_usd = df_caja[df_caja["propina_moneda"].str.contains("USD", na=False)]["propina"].sum()
        prop_col_bs  = df_caja[df_caja["propina_moneda"].str.contains("Bs",  na=False)]["propina"].sum()
    else:
        prop_col_usd = prop_col_bs = 0

    return {
        "ventas_usd":  ventas_usd,
        "ventas_bs":   ventas_bs,
        "ventas_usdt": ventas_usdt,
        "prop_usd":    prop_tipo_usd + prop_col_usd,
        "prop_bs":     prop_tipo_bs  + prop_col_bs,
        "total_mov":   len(df),
        "ventas_mov":  len(df_ventas),
        "comensales":  comensales,
        "cuentas_abiertas": cuentas_abiertas,
    }


def pantalla_panel(fecha_inicio, fecha_fin=None):
    if fecha_fin is None:
        fecha_fin = fecha_inicio
    if fecha_fin < fecha_inicio:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

    es_un_dia = fecha_inicio == fecha_fin
    delta_label = "vs ayer" if es_un_dia else "vs período anterior"
    sufijo = "del día" if es_un_dia else "del período"

    df = cargar_movimientos_panel_dia(fecha_inicio, fecha_fin)
    df_caja = df_flujo_caja(df, fecha_inicio, fecha_fin)

    duracion = (fecha_fin - fecha_inicio).days + 1
    prev_fin = fecha_inicio - timedelta(days=1)
    prev_inicio = prev_fin - timedelta(days=duracion - 1)
    df_prev = cargar_movimientos_panel_dia(prev_inicio, prev_fin)
    df_caja_prev = df_flujo_caja(df_prev, prev_inicio, prev_fin)

    tasa_panel, fecha_tasa_panel, fuente_tasa_panel = obtener_tasa_bcv()
    es_tasa_respaldo = fuente_tasa_panel == "Tasa de respaldo"

    saldos = calcular_saldos_dia(df_caja)
    saldos_ayer = calcular_saldos_dia(df_caja_prev)

    kpis = _calcular_kpis_dia(df, fecha_inicio, fecha_fin)

    eq_neto = (
        ""
        if es_tasa_respaldo
        else equivalente_bs_footer_html(saldos["neto"], tasa_panel, fecha_tasa_panel)
    )
    delta_label_full = delta_label

    mov_label = "movimiento" if kpis["total_mov"] == 1 else "movimientos"
    contexto_hero = (
        f'{kpis["total_mov"]} {mov_label} en flujo de caja · '
        f'montos por moneda sin conversión'
    )

    if es_tasa_respaldo:
        st.markdown(tasa_respaldo_aviso_html(), unsafe_allow_html=True)

    st.markdown(
        hero_metric_multimoneda_card(
            saldos["neto"],
            saldos_ayer["neto"],
            contexto_hero,
            eq_neto,
            etiqueta="Neto del día" if es_un_dia else "Neto del período",
            delta_label=delta_label_full,
        ),
        unsafe_allow_html=True,
    )

    if df.empty:
        msg = (
            "Sin movimientos registrados para esta fecha."
            if es_un_dia
            else "Sin movimientos registrados en este rango de fechas."
        )
        st.markdown(
            f'<p class="empty-day-notice">{msg}</p>',
            unsafe_allow_html=True,
        )
        st.info(
            "Registra un **Nuevo movimiento** o un **Egreso / Gasto** para comenzar."
        )
        return

    col_sb, col_se, col_eg = st.columns(3, gap="medium")
    eq_banco = (
        ""
        if es_tasa_respaldo
        else equivalente_bs_footer_html(saldos["banco"]["saldo"], tasa_panel, fecha_tasa_panel)
    )
    eq_efectivo = (
        ""
        if es_tasa_respaldo
        else equivalente_bs_footer_html(saldos["efectivo"]["saldo"], tasa_panel, fecha_tasa_panel)
    )
    eq_egresos = (
        ""
        if es_tasa_respaldo
        else equivalente_bs_footer_html(saldos["egresos"], tasa_panel, fecha_tasa_panel)
    )

    with col_sb:
        st.markdown(
            kpi_grupo_card(
                "Saldo bancario real",
                "accent-ventas",
                mini_stats_moneda(saldos["banco"]["saldo"], saldos_ayer["banco"]["saldo"]),
                footer_delta=kpi_delta_multimoneda(
                    saldos["banco"]["saldo"], saldos_ayer["banco"]["saldo"], delta_label_full
                ),
                footer_extra=eq_banco,
            ),
            unsafe_allow_html=True,
        )
    with col_se:
        st.markdown(
            kpi_grupo_card(
                "Saldo efectivo caja",
                "accent-propinas",
                mini_stats_moneda(saldos["efectivo"]["saldo"], saldos_ayer["efectivo"]["saldo"]),
                footer_delta=kpi_delta_multimoneda(
                    saldos["efectivo"]["saldo"], saldos_ayer["efectivo"]["saldo"], delta_label_full
                ),
                footer_extra=eq_efectivo,
            ),
            unsafe_allow_html=True,
        )
    with col_eg:
        st.markdown(
            kpi_grupo_card(
                f"Egresos {sufijo}",
                "accent-egresos",
                mini_stats_moneda(saldos["egresos"], saldos_ayer["egresos"])
                + [("Registros", str(saldos["egresos_count"]))],
                footer_delta=kpi_delta_multimoneda(
                    saldos["egresos"], saldos_ayer["egresos"], delta_label_full
                ),
                footer_extra=eq_egresos,
            ),
            unsafe_allow_html=True,
        )

    if kpis.get("cuentas_abiertas", 0) > 0:
        st.markdown(
            f'<div class="hint-box info">{icono_mat_html("schedule")} <b>{kpis["cuentas_abiertas"]} cuenta(s) abierta(s) {sufijo}</b> — '
            f'no suman al efectivo de caja hasta que se cobren en '
            f'<b>{icono_mat_html("account_balance_wallet")} Cuentas por cobrar</b>.</div>',
            unsafe_allow_html=True,
        )

    pendientes_cobro = cargar_cuentas_por_cobrar_completo()
    totales_cobrar = totales_cobrar_por_moneda(pendientes_cobro)
    n_cobrar = contar_clientes_con_saldo(pendientes_cobro)
    col_cobrar, col_cobrar_sp = st.columns([1, 2], gap="medium")
    with col_cobrar:
        st.markdown(
            kpi_cuentas_cobrar_card(totales_cobrar, n_cobrar, pendientes_cobro),
            unsafe_allow_html=True,
        )
        if st.button(
            "Ver todos en Cuentas por cobrar →",
            key="panel_nav_cobrar",
            use_container_width=True,
        ):
            st.session_state.nav_key = "cobrar"
            st.rerun()

    metricas_pos = calcular_metricas_pos(df_caja) if not df_caja.empty else None
    col_v, col_p = st.columns(2, gap="medium")
    with col_v:
        st.markdown(
            kpi_grupo_card(
                "Ventas",
                "accent-ventas",
                [
                    ("USD", formatear_monto(kpis["ventas_usd"], "USD")),
                    ("USDT", formatear_monto(kpis["ventas_usdt"], "USDT")),
                    ("Movimientos", str(kpis["ventas_mov"])),
                    ("Comensales", str(kpis["comensales"])),
                ],
            ),
            unsafe_allow_html=True,
        )
    with col_p:
        st.markdown(
            kpi_grupo_card(
                "Propinas",
                "accent-propinas",
                [
                    ("USD", formatear_monto(kpis["prop_usd"], "USD")),
                    ("Bs", formatear_bs_etiqueta(kpis["prop_bs"])),
                ],
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            "Ver módulo de Propinas →",
            key="panel_nav_propinas",
            use_container_width=True,
        ):
            st.session_state.nav_key = "propinas"
            st.rerun()

    col_main, col_side = st.columns([2, 1], gap="medium")

    with col_main:
        with st.container(border=True):
            st.markdown(
                panel_titulo(
                    f"Flujo de caja {sufijo}",
                    "Ingresos · Egresos · Neto por moneda (sin conversión)",
                ),
                unsafe_allow_html=True,
            )
            tiene_flujo = any(
                saldos["ingresos"][k] or saldos["egresos"][k] for k in MONEDAS_SALDO
            )
            if tiene_flujo:
                st.markdown(
                    flujo_caja_multimoneda_html(
                        saldos["ingresos"], saldos["egresos"], saldos["neto"]
                    ),
                    unsafe_allow_html=True,
                )
                if tasa_panel > 0 and not es_tasa_respaldo:
                    st.caption(
                        f"Equivalente neto a tasa vigente ({fecha_tasa_panel}): "
                        f"{tasa_panel:,.2f} Bs/USD → "
                        f"{formatear_bs_etiqueta(equivalente_a_bs(saldos['neto'], tasa_panel))}"
                    )
            else:
                st.markdown('<p class="empty-chart-msg">Sin movimientos de caja hoy.</p>', unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown(panel_titulo("Movimientos por hora", "Impacto neto en caja (ingresos − egresos)"), unsafe_allow_html=True)
            por_hora = df_caja.copy()
            por_hora["hora"] = pd.to_datetime(por_hora["fecha"], errors="coerce").dt.strftime("%H:00")
            por_hora["monto_neto"] = por_hora.apply(monto_impacto_caja, axis=1)
            agg_hora = por_hora.groupby("hora")["monto_neto"].sum().reset_index().sort_values("hora")

            if len(agg_hora) >= 2:
                max_y = float(agg_hora["monto_neto"].max())
                fig_line = go.Figure(
                    data=[
                        go.Scatter(
                            x=agg_hora["hora"],
                            y=agg_hora["monto_neto"],
                            mode="lines+markers",
                            line=dict(color=GIARDINO_SUCCESS, width=2),
                            marker=dict(color=GIARDINO_BRAND_GREEN, size=6),
                            fill="tozeroy",
                            fillcolor="rgba(16,185,129,0.12)",
                            showlegend=False,
                            name="Movimientos por hora",
                            hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
                        )
                    ]
                )
                finalizar_grafico(fig_line, height=260, leyenda=False)
                fig_line.update_layout(margin=dict(t=20, b=30, l=8, r=8))
                fig_line.update_xaxes(showgrid=False, tickfont=dict(color=GIARDINO_MUTED, size=12))
                aplicar_eje_y_limpio(fig_line, max_y)
                st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})
            else:
                st.markdown(
                    '<p class="empty-chart-msg">Aún no hay suficientes movimientos para graficar.</p>',
                    unsafe_allow_html=True,
                )

    with col_side:
        tasa_bcv, fecha_bcv, fuente_bcv = obtener_tasa_bcv()
        resumen_grupos = resumen_ingresos_cuatro_grupos_usd(df_caja, tasa_bcv)

        with st.container(border=True):
            st.markdown(
                panel_titulo(
                    "Resumen de Ingresos Totales por Categoría",
                    f"Participación en USD equivalente · BCV: Bs {tasa_bcv:,.2f} / $",
                ),
                unsafe_allow_html=True,
            )
            st.caption(f"Fuente: {fuente_bcv} · Fecha valor BCV: {fecha_bcv}")

            if resumen_grupos.empty:
                st.markdown(
                    '<p class="empty-chart-msg">Sin ingresos en Efectivo, Banco, USDT o Zelle.</p>',
                    unsafe_allow_html=True,
                )
            elif len(resumen_grupos) == 1:
                fila = resumen_grupos.iloc[0]
                st.markdown(
                    stat_simple_html(
                        fila["grupo"],
                        formatear_usd(fila["usd"]),
                        "100% de los ingresos del período (USD equivalente)",
                    ),
                    unsafe_allow_html=True,
                )
            else:
                fig_grupos = grafico_dona_ingresos_grupos(resumen_grupos)
                if fig_grupos:
                    st.plotly_chart(
                        fig_grupos,
                        use_container_width=True,
                        config={"displayModeBar": False},
                    )

            st.markdown(
                f'<div style="font-weight:600;color:{GIARDINO_TEXT_DARK};margin:0.85rem 0 0.25rem 0;">'
                f'Detalle de Ingresos (USD Equivalente)</div>',
                unsafe_allow_html=True,
            )
            st.markdown(tabla_ingresos_usd_html(resumen_grupos), unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown(
                panel_titulo(
                    "Desglose en dólares (USD)",
                    f"Saldo neto por banco / canal · BCV: Bs {tasa_bcv:,.2f} / $",
                ),
                unsafe_allow_html=True,
            )

            por_banco_usd = resumen_por_banco_en_usd(df_caja, tasa_bcv)
            if por_banco_usd.empty:
                st.caption("Sin banco asignado en el período.")
            elif len(por_banco_usd) >= 2:
                for _, fila in por_banco_usd.iterrows():
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:0.4rem 0;border-bottom:1px solid #e5e7eb;">'
                        f'<span style="color:{GIARDINO_TEXT_DARK};font-size:0.95rem;">{fila["banco"]}</span>'
                        f'<span style="font-weight:600;color:{GIARDINO_TEXT_DARK};font-size:0.95rem;">'
                        f'${fila["monto_usd"]:,.2f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                fila = por_banco_usd.iloc[0]
                st.markdown(
                    stat_simple_html(
                        fila["banco"],
                        f"${fila['monto_usd']:,.2f}",
                        "Único canal con movimiento (USD neto)",
                    ),
                    unsafe_allow_html=True,
                )

    if metricas_pos:
        st.markdown(
            '<div class="kpi-section-label">Conciliación punto de venta (POS)</div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            st.markdown(
                panel_titulo(
                    "Reporte financiero POS",
                    "Comparativa bruto · comisión 5% · neto al banco",
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                pos_movimientos_card(
                    metricas_pos["mov_total"],
                    metricas_pos["mov_credito"],
                    metricas_pos["mov_debito"],
                ),
                unsafe_allow_html=True,
            )
            k1, k2, k3 = st.columns(3, gap="medium")
            with k1:
                st.markdown(
                    pos_kpi_card("Ingreso bancario", formatear_bs_etiqueta(metricas_pos["ingreso_bancario"])),
                    unsafe_allow_html=True,
                )
            with k2:
                st.markdown(
                    pos_kpi_card("Ingreso bruto POS", formatear_bs_etiqueta(metricas_pos["bruto_pos"])),
                    unsafe_allow_html=True,
                )
            with k3:
                st.markdown(
                    pos_kpi_card("Comisión POS (5%)", formatear_bs_etiqueta(metricas_pos["comision"])),
                    unsafe_allow_html=True,
                )

            fig_pos = grafico_conciliacion_pos(
                metricas_pos["bruto_pos"],
                metricas_pos["comision"],
                metricas_pos["neto_pos"],
            )
            st.plotly_chart(fig_pos, use_container_width=True, config={"displayModeBar": False})

    with st.container(border=True):
        rango_txt = (
            fecha_inicio.strftime("%d/%m/%Y")
            if es_un_dia
            else f"{fecha_inicio.strftime('%d/%m/%Y')} — {fecha_fin.strftime('%d/%m/%Y')}"
        )
        st.markdown(panel_titulo("Detalle de movimientos", rango_txt), unsafe_allow_html=True)

        tasa_panel, _, _ = obtener_tasa_bcv()
        tabla = df.copy()
        tabla["Hora"] = pd.to_datetime(tabla["fecha"], errors="coerce").dt.strftime("%H:%M")
        tabla["Flujo"] = tabla.apply(
            lambda r: "Egreso" if es_egreso(r) else "Ingreso",
            axis=1,
        )
        tabla["Monto"] = tabla.apply(lambda r: formatear_monto(r["monto"], r["moneda"]), axis=1)
        tabla["Comisión POS"] = tabla.apply(
            lambda r: formatear_monto(r.get("comision_pos", 0), r["moneda"])
            if float(r.get("comision_pos", 0) or 0) > 0
            else "—",
            axis=1,
        )
        tabla["Neto al banco"] = tabla.apply(
            lambda r: "— (crédito)" if es_cuenta_abierta(r) else (
                f"- {formatear_monto(monto_neto_banco(r['monto'], r.get('comision_pos', 0)), r['moneda'])}"
                if es_egreso(r)
                else formatear_monto(
                    monto_neto_banco(r["monto"], r.get("comision_pos", 0)),
                    r["moneda"],
                )
            ),
            axis=1,
        )
        tabla["Estado"] = tabla.apply(
            lambda r: "Gasto" if es_egreso(r) else (
                "Crédito" if es_cuenta_abierta(r) else "Pagado"
            ),
            axis=1,
        )
        tabla["Categoría"] = tabla["tipo"]
        tabla["Tasa del día"] = tabla.apply(
            lambda r: formatear_tasa_bcv(r.get("tasa_bcv", 0), r["moneda"]),
            axis=1,
        )
        tabla["Conversión USD"] = tabla.apply(
            lambda r: formatear_usd(monto_a_usd_fila(r, tasa_panel)),
            axis=1,
        )
        tabla["IVA 16%"] = tabla.get("iva_activo", pd.Series(0, index=tabla.index)).apply(
            lambda v: "Sí" if v else "—"
        )
        tabla["Tipo Cuenta"] = tabla.get("tipo_cuenta", pd.Series("Regular", index=tabla.index)).fillna("Regular")
        tabla["Personas"] = tabla.get("cantidad_personas", pd.Series(1, index=tabla.index)).fillna(1).astype(int)

        st.dataframe(
            tabla[
                [
                    "Hora", "Flujo", "Categoría", "Monto", "moneda", "Estado", "Tasa del día", "Conversión USD",
                    "Comisión POS", "Neto al banco", "banco", "referencia",
                    "IVA 16%", "Tipo Cuenta", "Personas", "notas",
                ]
            ].rename(
                columns={
                    "moneda": "Moneda",
                    "banco": "Banco / Canal",
                    "referencia": "Referencia",
                    "notas": "Notas / Concepto",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Hora": st.column_config.TextColumn(width="small"),
                "Categoría": st.column_config.TextColumn(width="medium"),
                "Monto": st.column_config.TextColumn(width="small"),
                "Estado": st.column_config.TextColumn(width="small"),
                "Moneda": st.column_config.TextColumn(width="small"),
                "Tasa del día": st.column_config.TextColumn(width="small"),
                "Conversión USD": st.column_config.TextColumn(width="small"),
                "Comisión POS": st.column_config.TextColumn(width="small"),
                "Neto al banco": st.column_config.TextColumn(width="small"),
                "Notas": st.column_config.TextColumn(width="large"),
            },
        )


METODOS_INGRESO = {
    "TRANSFERENCIA": ("🔄", "Bs (Bolívares)"),
    "PAGO MÓVIL":    ("📱", "Bs (Bolívares)"),
    "POS / Tarjeta": ("💳", "Bs (Bolívares)"),
}

METODO_ETIQUETAS = {
    "TRANSFERENCIA": "Transferencia",
    "PAGO MÓVIL": "Pago Móvil",
    "POS / Tarjeta": "POS / Tarjeta",
}

METODO_ICONOS_MAT = {
    "TRANSFERENCIA": "swap_horiz",
    "PAGO MÓVIL": "smartphone",
    "POS / Tarjeta": "credit_card",
}

REGISTRO_GRID = [
    ["Ingreso bancario", "Pago USDT", "IVA"],
    ["Retención de IVA", "Retención ISLR", "Zelle / Digital"],
    ["Efectivo en caja", "Otro ingreso", None],
]

TEXTO_AYUDA_REGISTRO = (
    "<b>Guía rápida</b><br><br>"
    "• <b>Ingreso bancario</b>: elige Transferencia, Pago Móvil o POS (siempre en Bs).<br>"
    "• <b>Propinas</b>: regístralas en la sección <b>Propinas</b> del menú.<br>"
    "• <b>POS crédito</b>: marca tarjeta de crédito para aplicar comisión 5%.<br>"
    "• <b>Cuenta familiar</b>: permite registrar monto Bs 0.<br>"
    "• Puedes elegir fechas pasadas para registrar pagos atrasados."
)


def _moneda_por_tipo(tipo, metodo=None):
    if tipo == "Ingreso bancario":
        return "Bs (Bolívares)"
    if tipo == "Zelle / Digital":
        return "USD (Dólares)"
    if tipo == "Pago USDT":
        return "USDT (Tether)"
    return TIPOS_MOVIMIENTO.get(tipo, {}).get("moneda_default", "USD (Dólares)")


def _render_grid_categorias(tipos_lista, ss):
    """Cuadrícula 3×3 de categorías como en el mockup."""
    for fila in REGISTRO_GRID:
        cols = st.columns(3, gap="small")
        for col, celda in zip(cols, fila):
            with col:
                if celda is None:
                    if st.button(
                        "Ayuda",
                        key="reg_btn_ayuda",
                        icon=":material/help:",
                        use_container_width=True,
                    ):
                        st.session_state["reg_show_ayuda"] = not st.session_state.get(
                            "reg_show_ayuda", False
                        )
                    continue
                if celda not in tipos_lista:
                    continue
                info = TIPOS_MOVIMIENTO[celda]
                activo = ss.reg_tipo == celda
                if st.button(
                    celda,
                    key=f"reg_cat_{celda}",
                    icon=f":material/{info['icono_mat']}:",
                    use_container_width=True,
                    type="primary" if activo else "secondary",
                ):
                    if ss.reg_tipo != celda:
                        ss.reg_tipo = celda
                        ss.reg_moneda = _moneda_por_tipo(celda)
                        st.rerun()


def _render_metodo_cobro(ss):
    """Selector tipo píldora: Transferencia · Pago Móvil · POS."""
    st.markdown(
        panel_titulo("Método de cobro", "¿Cómo llegó el pago?"),
        unsafe_allow_html=True,
    )
    st.markdown('<span class="reg-pill-marker reg-metodo-pill"></span>', unsafe_allow_html=True)
    cols = st.columns(3, gap="small")
    for col, metodo in zip(cols, METODOS_INGRESO.keys()):
        with col:
            texto = METODO_ETIQUETAS[metodo]
            activo = ss.reg_metodo == metodo
            if st.button(
                texto,
                key=f"reg_met_{metodo}",
                icon=f":material/{METODO_ICONOS_MAT[metodo]}:",
                use_container_width=True,
                type="primary" if activo else "secondary",
            ):
                if ss.reg_metodo != metodo:
                    ss.reg_metodo = metodo
                    ss.reg_moneda = METODOS_INGRESO[metodo][1]
                    st.rerun()


def _render_tipo_cuenta(ss):
    """Píldoras Cliente Regular / Cuenta Familiar."""
    st.markdown(
        f'<div style="font-size:0.88rem;color:{GIARDINO_SUBTLE};margin:0.75rem 0 0.35rem 0;">'
        "Tipo de cuenta</div>",
        unsafe_allow_html=True,
    )
    st.markdown('<span class="reg-pill-marker reg-cuenta-pill"></span>', unsafe_allow_html=True)
    c1, c2 = st.columns(2, gap="small")
    es_regular = ss.reg_tipo_cuenta == "Cliente Regular"
    with c1:
        if st.button(
            "Cliente Regular",
            key="reg_cuenta_regular",
            icon=":material/person:",
            use_container_width=True,
            type="primary" if es_regular else "secondary",
        ):
            if not es_regular:
                ss.reg_tipo_cuenta = "Cliente Regular"
                st.rerun()
    with c2:
        if st.button(
            "Cuenta Familiar",
            key="reg_cuenta_familiar",
            icon=":material/groups:",
            use_container_width=True,
            type="primary" if not es_regular else "secondary",
        ):
            if es_regular:
                ss.reg_tipo_cuenta = "Cuenta Familiar (Exonerada)"
                st.rerun()


def _simbolo_moneda(moneda_str):
    if "USDT" in str(moneda_str):
        return "₮"
    if "USD" in str(moneda_str) and "Bs" not in str(moneda_str):
        return "$"
    return "Bs"


def _registro_defaults(tasa_bcv_auto):
    tipos = tipos_para_registro()
    tipo_ini = tipos[0] if tipos else "Ingreso bancario"
    return {
        "reg_tipo": tipo_ini,
        "reg_metodo": "TRANSFERENCIA",
        "reg_tarjeta_credito": False,
        "reg_registrar_cliente": False,
        "reg_fecha": date.today(),
        "reg_hora": datetime.now().time().replace(second=0, microsecond=0),
        "reg_moneda": _moneda_por_tipo(tipo_ini),
        "reg_tasa_bcv": float(tasa_bcv_auto),
        "reg_tasa_fecha_ref": None,
        "reg_tasa_fuente": "",
        "reg_tasa_aviso": "",
        "reg_tipo_cuenta": "Cliente Regular",
        "reg_monto": 0.0,
        "reg_banco": TODOS_BANCOS[0] if TODOS_BANCOS else "",
        "reg_usar_banco": False,
        "reg_referencia": "",
        "reg_iva_activo": False,
        "reg_cantidad_personas": 1,
        "reg_cliente_nombre": "",
        "reg_cliente_cedula": "",
        "reg_cliente_telefono": "",
        "reg_cliente_verificado": False,
        "reg_cliente_es_nuevo": True,
        "reg_cliente_msg": "",
        "reg_estado_cobro": OPCIONES_ESTADO_COBRO[0],
        "reg_notas": "",
        "reg_propina_pos": 0.0,
    }


def _init_registro_state(tasa_bcv_auto):
    for clave, valor in _registro_defaults(tasa_bcv_auto).items():
        st.session_state.setdefault(clave, valor)


def _reset_registro_state(tasa_bcv_auto):
    """Restablece el formulario. Debe llamarse ANTES de instanciar los widgets."""
    for clave, valor in _registro_defaults(tasa_bcv_auto).items():
        st.session_state[clave] = valor
    st.session_state.pop("_reg_cliente_sync", None)


def _solicitar_reset_registro(tasa_bcv_auto, mensaje_exito):
    """Programa el reset para la siguiente ejecución (post-rerun)."""
    st.session_state["reg_pendiente_reset"] = True
    st.session_state["reg_mensaje_exito"] = mensaje_exito
    st.session_state["reg_mostrar_balloons"] = True
    st.rerun()


def _moneda_registro(tipo, info):
    moneda = _moneda_por_tipo(tipo)
    bloqueada = tipo in ("Ingreso bancario", "Zelle / Digital", "Pago USDT")
    return moneda, bloqueada


def _validar_registro(info, ss, es_familiar, es_bs, es_pos, es_cuenta_abierta=False):
    faltantes = []
    if not es_familiar and float(ss.reg_monto) <= 0:
        faltantes.append("Monto del cobro")
    if es_cuenta_abierta and not ss.reg_registrar_cliente:
        faltantes.append("Cliente obligatorio para cuenta abierta")
    if info["requiere_referencia"] and not es_cuenta_abierta and not str(ss.reg_referencia).strip():
        faltantes.append("Referencia / Nº de transacción")
    if info["requiere_banco"] and not es_cuenta_abierta and not str(ss.reg_banco).strip():
        faltantes.append("Banco de destino")
    if es_bs and float(ss.reg_tasa_bcv) <= 0:
        faltantes.append("Tasa BCV del día")
    if ss.reg_registrar_cliente:
        if not str(ss.reg_cliente_nombre).strip():
            faltantes.append("Nombre del Cliente")
        if not _normalizar_cedula(ss.reg_cliente_cedula):
            faltantes.append("Cédula / RIF")
        if not str(ss.reg_cliente_telefono).strip():
            faltantes.append("Teléfono")
    return faltantes


def pantalla_registrar():
    tipos_lista = tipos_para_registro()
    tasa_bcv_auto, fecha_bcv, fuente_bcv = obtener_tasa_bcv()

    if st.session_state.get("reg_pendiente_reset"):
        _reset_registro_state(tasa_bcv_auto)
        st.session_state.pop("reg_pendiente_reset", None)

    _init_registro_state(tasa_bcv_auto)
    ss = st.session_state
    _sync_tasa_si_fecha_cambio("reg_fecha", "reg")

    if st.session_state.get("reg_mensaje_exito"):
        st.success(st.session_state.pop("reg_mensaje_exito"))
    if st.session_state.pop("reg_mostrar_balloons", False):
        st.balloons()

    if ss.reg_tipo not in tipos_lista:
        ss.reg_tipo = tipos_lista[0]

    if ss.reg_tipo in ("Ingreso bancario", "Zelle / Digital", "Pago USDT"):
        ss.reg_moneda = _moneda_por_tipo(ss.reg_tipo, ss.reg_metodo if ss.reg_tipo == "Ingreso bancario" else None)

    st.markdown(
        page_header_html(
            "Nuevo movimiento",
            "Registra ingresos, pagos y cobros del restaurante",
            "add_circle",
        ),
        unsafe_allow_html=True,
    )

    col_sel, col_form = st.columns([2, 3], gap="large", border=True)

    # ── Columna izquierda: categoría + método ──
    with col_sel:
        st.markdown('<span class="reg-card-marker"></span>', unsafe_allow_html=True)
        st.markdown(panel_titulo("1. Categoría", "Selecciona el tipo de cobro"), unsafe_allow_html=True)
        _render_grid_categorias(tipos_lista, ss)

        tipo = ss.reg_tipo
        info = TIPOS_MOVIMIENTO[tipo]
        st.markdown(
            f'<div class="cat-desc-box"><span class="mi">{info.get("icono_mat", "label")}</span> '
            f'<b>{tipo}</b><br>{info["descripcion"]}</div>',
            unsafe_allow_html=True,
        )

        if st.session_state.get("reg_show_ayuda"):
            st.markdown(
                f'<div class="hint-box info">{TEXTO_AYUDA_REGISTRO}</div>',
                unsafe_allow_html=True,
            )

    moneda_forzada, moneda_bloqueada = _moneda_registro(tipo, info)
    metodo_detalle = ss.reg_metodo if tipo == "Ingreso bancario" else ""
    moneda_actual = moneda_forzada if moneda_bloqueada else ss.reg_moneda
    es_bs = "Bs" in moneda_actual
    simbolo = _simbolo_moneda(moneda_actual)

    # ── Columna derecha: formulario ──
    with col_form:
        st.markdown('<span class="reg-card-marker"></span>', unsafe_allow_html=True)
        st.markdown(panel_titulo("2. Datos del cobro", "Completa el formulario"), unsafe_allow_html=True)

        es_pos = False
        if tipo == "Ingreso bancario":
            _render_metodo_cobro(ss)
            es_pos = ss.reg_metodo == "POS / Tarjeta"

        st.toggle(
            "¿Deseas registrar el movimiento a un cliente?",
            key="reg_registrar_cliente",
            on_change=_on_toggle_cliente_registro,
        )

        if ss.reg_registrar_cliente:
            _render_seccion_cliente()

        if es_pos:
            st.toggle(
                "¿El pago fue con Tarjeta de Crédito?",
                key="reg_tarjeta_credito",
                help="Si aplica, se calcula una comisión del 5% sobre el monto.",
            )

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.date_input(
                "Fecha del movimiento",
                max_value=date.today(),
                help="Puedes elegir fechas pasadas para registrar pagos viejos.",
                key="reg_fecha",
                on_change=_on_reg_fecha_cambiada,
            )
        with c2:
            st.time_input("Hora aproximada", key="reg_hora")

        if moneda_bloqueada:
            st.caption(f"Moneda asignada automáticamente: **{moneda_forzada}**")
            if ss.reg_moneda != moneda_forzada:
                ss.reg_moneda = moneda_forzada
        else:
            st.selectbox("Moneda", MONEDAS, key="reg_moneda")

        if es_bs:
            fuente_tasa = ss.get("reg_tasa_fuente") or fuente_bcv
            sync_ok = bool(fuente_tasa) and not ss.get("reg_tasa_aviso")
            badge = bcv_badge_html(sync_ok)
            st.markdown(
                f'<div class="bcv-field-label">'
                f'<span>Tasa BCV del día (Bs / $)</span>'
                f'<span class="bcv-sync-badge">{badge}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.number_input(
                "Tasa BCV",
                min_value=0.0,
                step=0.0001,
                format="%.4f",
                label_visibility="collapsed",
                help=f"Fuente: {fuente_tasa} · Fecha mov.: {ss.reg_fecha.strftime('%d/%m/%Y')}",
                key="reg_tasa_bcv",
            )
            if ss.get("reg_tasa_aviso"):
                st.warning(ss.reg_tasa_aviso)
            elif fuente_tasa:
                st.caption(
                    f"Fuente: **{fuente_tasa}** · "
                    f"Tasa para el {ss.reg_fecha.strftime('%d/%m/%Y')}"
                )

        _render_tipo_cuenta(ss)

        st.radio(
            "Estado del cobro:",
            OPCIONES_ESTADO_COBRO,
            horizontal=True,
            key="reg_estado_cobro",
        )
        if estado_pago_desde_ui(ss.reg_estado_cobro) == ESTADO_CUENTA_ABIERTA:
            st.markdown(
                '<div class="hint-box info"><span class="mi">schedule</span> <b>Cuenta abierta</b> — el consumo queda en el historial '
                'pero <b>no sumará a la caja de hoy</b> hasta cobrarlo en '
                '<b><span class="mi">account_balance_wallet</span> Cuentas por cobrar</b>.</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div class="reg-monto-marker" data-currency="{simbolo}"></div>',
            unsafe_allow_html=True,
        )
        st.number_input(
            "Monto del cobro",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            key="reg_monto",
            help="Monto base del cobro. Si activas IVA abajo, se sumará 16% al registrar.",
        )

        monto_base = float(ss.get("reg_monto", 0) or 0)
        iva_activo_ui = bool(ss.get("reg_iva_activo", False))
        monto_registro, monto_iva = calcular_desglose_iva(monto_base, iva_activo_ui)

        comision_pos = calcular_comision_pos(monto_registro, es_pos and ss.reg_tarjeta_credito)
        if es_pos and ss.reg_tarjeta_credito and monto_registro > 0:
            neto_banco = monto_registro - comision_pos
            st.info(
                f"Comisión POS 5%: **Bs {comision_pos:,.2f}** · "
                f"Neto estimado al banco: **Bs {neto_banco:,.2f}**"
            )

        if es_pos:
            st.number_input(
                "Propina incluida en el punto (Bs/USD)",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key="reg_propina_pos",
                help=(
                    "Opcional. Monto de propina incluido en el lote Credicard/POS. "
                    "Se registra aparte en Propinas con la misma referencia bancaria."
                ),
            )
            prop_pos = float(ss.get("reg_propina_pos", 0) or 0)
            if prop_pos > 0 and monto_registro > 0:
                lote_total = monto_registro + prop_pos
                st.caption(
                    f"Lote POS bruto (conciliación Credicard): "
                    f"**{formatear_monto(lote_total, moneda_actual)}** "
                    f"= cuenta {formatear_monto(monto_registro, moneda_actual)} "
                    f"+ propina {formatear_monto(prop_pos, moneda_actual)}"
                )

        # Campos adicionales (colapsados visualmente bajo el monto)
        st.markdown('<div class="reg-extra-fields">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Detalles adicionales</div>', unsafe_allow_html=True)

        if info["requiere_banco"]:
            st.selectbox("Banco de destino", TODOS_BANCOS, key="reg_banco")
        elif tipo == "Pago USDT":
            st.selectbox(
                "Plataforma / Wallet",
                ["Binance / USDT", "Trust Wallet", "MetaMask", "Otro wallet"],
                key="reg_banco",
            )
        elif tipo in ("Zelle / Digital", "Otro ingreso"):
            st.checkbox("¿Asociar a un banco o canal?", key="reg_usar_banco")
            if ss.reg_usar_banco:
                st.selectbox("Banco / canal", TODOS_BANCOS, key="reg_banco")
        elif tipo == "Efectivo en caja":
            st.text_input("Banco / canal", value="Efectivo en caja", disabled=True)

        if info["requiere_referencia"]:
            st.text_input(
                "Referencia / Nº de transacción",
                placeholder="Obligatorio para este tipo de movimiento",
                key="reg_referencia",
            )
        else:
            st.text_input(
                "Referencia (opcional)",
                placeholder="Comprobante, factura, etc.",
                key="reg_referencia",
            )

        fx1, fx2 = st.columns(2, gap="medium")
        with fx1:
            st.toggle(
                "¿Incluye 16% de IVA?",
                help="Suma 16% al monto base del cobro al registrar el movimiento.",
                key="reg_iva_activo",
            )
            if ss.reg_iva_activo and monto_base > 0:
                st.info(
                    f"Monto base: **{formatear_monto(monto_base, moneda_actual)}** · "
                    f"IVA (16%): **{formatear_monto(monto_iva, moneda_actual)}** · "
                    f"Total a registrar: **{formatear_monto(monto_registro, moneda_actual)}**"
                )
        with fx2:
            st.number_input(
                "Cantidad de comensales",
                min_value=0,
                max_value=500,
                step=1,
                key="reg_cantidad_personas",
            )

        st.text_area(
            "Notas o comentarios del pedido",
            placeholder="Ej: mesa 7, cumpleaños, menú ejecutivo, cliente corporativo...",
            height=75,
            key="reg_notas",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="reg-submit">', unsafe_allow_html=True)
        guardar = st.button(
            "Registrar movimiento",
            type="primary",
            use_container_width=True,
            key="reg_btn_guardar",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        if guardar:
            es_familiar = ss.reg_tipo_cuenta == "Cuenta Familiar (Exonerada)"
            moneda_guardar = moneda_forzada if moneda_bloqueada else ss.reg_moneda
            es_bs = "Bs" in moneda_guardar
            estado_pago = estado_pago_desde_ui(ss.reg_estado_cobro)
            es_cuenta_abierta = estado_pago == ESTADO_CUENTA_ABIERTA
            banco = ss.reg_banco
            if es_cuenta_abierta:
                banco = "Cuenta Abierta (pendiente)"
            elif tipo == "Efectivo en caja":
                banco = "Efectivo en caja"
            elif tipo in ("Zelle / Digital", "Otro ingreso") and not ss.reg_usar_banco:
                banco = ""

            faltantes = _validar_registro(
                info, ss, es_familiar, es_bs, es_pos, es_cuenta_abierta=es_cuenta_abierta
            )
            if faltantes:
                st.warning("Por favor, rellene todos los campos obligatorios antes de continuar.")
                st.caption("Campos pendientes: " + ", ".join(faltantes))
            else:
                monto_base = float(ss.reg_monto or 0)
                monto_final, monto_iva = calcular_desglose_iva(monto_base, ss.reg_iva_activo)
                comision_pos = 0.0 if es_cuenta_abierta else calcular_comision_pos(
                    monto_final, es_pos and ss.reg_tarjeta_credito
                )
                propina_pos = (
                    float(ss.get("reg_propina_pos", 0) or 0)
                    if es_pos and not es_cuenta_abierta
                    else 0.0
                )
                monto_total_pos = (
                    monto_final + propina_pos if propina_pos > 0 else 0.0
                )
                fecha_hora = construir_fecha_hora(ss.reg_fecha, ss.reg_hora)
                fecha_pago = "" if es_cuenta_abierta else fecha_hora
                fecha_txt = ss.reg_fecha.strftime("%d/%m/%Y")
                if ss.reg_registrar_cliente:
                    cedula_cli, nombre_cli, telefono_cli = _resolver_datos_cliente_registro(ss)
                else:
                    cedula_cli, nombre_cli, telefono_cli = "", "", ""

                guardar_movimiento(
                    fecha_hora,
                    tipo,
                    monto_final,
                    moneda_guardar,
                    banco,
                    ss.reg_referencia,
                    ss.reg_notas,
                    iva_activo=ss.reg_iva_activo,
                    tipo_cuenta=ss.reg_tipo_cuenta,
                    cantidad_personas=ss.reg_cantidad_personas,
                    metodo_detalle=metodo_detalle if not es_cuenta_abierta else "",
                    tasa_bcv=ss.reg_tasa_bcv if es_bs else 0.0,
                    es_tarjeta_credito=es_pos and ss.reg_tarjeta_credito and not es_cuenta_abierta,
                    comision_pos=comision_pos,
                    cliente_nombre=nombre_cli,
                    cliente_cedula=cedula_cli,
                    cliente_telefono=telefono_cli,
                    estado_pago=estado_pago,
                    fecha_pago=fecha_pago,
                    tipo_movimiento=TIPO_MOV_INGRESO,
                    categoria=CATEGORIA_INGRESO_DEFAULT,
                    es_consumo_credito=es_cuenta_abierta,
                    monto_total_pos=monto_total_pos,
                )
                if propina_pos > 0:
                    ref_pos = str(ss.reg_referencia or "").strip()
                    guardar_movimiento(
                        fecha_hora,
                        "Propina",
                        propina_pos,
                        moneda_guardar,
                        banco,
                        ref_pos,
                        (
                            f"Propina incluida en lote POS · ref. {ref_pos}"
                            if ref_pos
                            else "Propina incluida en lote POS"
                        ),
                        metodo_detalle=metodo_detalle,
                        tasa_bcv=ss.reg_tasa_bcv if es_bs else 0.0,
                        cliente_nombre=nombre_cli,
                        cliente_cedula=cedula_cli,
                        cliente_telefono=telefono_cli,
                        estado_pago=estado_pago,
                        fecha_pago=fecha_pago,
                        tipo_movimiento=TIPO_MOV_PROPINA,
                        categoria=CATEGORIA_PROPINA,
                    )
                if es_bs and float(ss.reg_tasa_bcv) > 0:
                    _actualizar_tasa_historico(ss.reg_fecha.isoformat(), ss.reg_tasa_bcv)
                mensaje = (
                    f"{tipo} guardado para el {fecha_txt}."
                    + (
                        f" Total con IVA: {formatear_monto(monto_final, moneda_guardar)} "
                        f"(base {formatear_monto(monto_base, moneda_guardar)} "
                        f"+ IVA {formatear_monto(monto_iva, moneda_guardar)})."
                        if ss.reg_iva_activo and monto_iva > 0
                        else ""
                    )
                    + (f" Comisión POS: Bs {comision_pos:,.2f}" if comision_pos > 0 else "")
                    + (
                        f" Propina POS: {formatear_monto(propina_pos, moneda_guardar)} "
                        f"(registrada aparte, ref. {ss.reg_referencia})."
                        if propina_pos > 0
                        else ""
                    )
                    + (" Cuenta abierta — pendiente de cobro." if es_cuenta_abierta else "")
                )
                _solicitar_reset_registro(tasa_bcv_auto, mensaje)


def cargar_propinas_periodo(fecha_inicio, fecha_fin=None):
    if fecha_fin is None:
        fecha_fin = fecha_inicio
    if fecha_fin < fecha_inicio:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio
    df = cargar_movimientos(fecha_desde=fecha_inicio, fecha_hasta=fecha_fin)
    if df.empty:
        return df
    col_prop = df.get("propina", pd.Series(0, index=df.index)).fillna(0)
    mask = (df["tipo"] == "Propina") | (col_prop > 0)
    return df[mask].copy()


def totales_propinas_por_moneda(df):
    totales = _saldos_moneda_vacio()
    if df.empty:
        return totales
    for _, r in df.iterrows():
        if r["tipo"] == "Propina":
            clave = _clave_moneda_saldo(r.get("moneda", ""))
            totales[clave] += float(r.get("monto", 0) or 0)
        prop = float(r.get("propina", 0) or 0)
        if prop > 0:
            clave = _clave_moneda_saldo(r.get("propina_moneda", r.get("moneda", "")))
            totales[clave] += prop
    return totales


def _propina_defaults(tasa_bcv_auto):
    return {
        "prop_fecha": date.today(),
        "prop_hora": datetime.now().time().replace(second=0, microsecond=0),
        "prop_moneda": "USD (Dólares)",
        "prop_monto": 0.0,
        "prop_banco": "Efectivo en caja",
        "prop_notas": "",
        "prop_tasa_bcv": float(tasa_bcv_auto),
        "prop_tasa_fecha_ref": None,
        "prop_tasa_fuente": "",
        "prop_tasa_aviso": "",
    }


def _solicitar_reset_propina(tasa_bcv_auto, mensaje):
    st.session_state.prop_pendiente_reset = True
    st.session_state.prop_reset_tasa = tasa_bcv_auto
    st.session_state.prop_mensaje_ok = mensaje
    st.rerun()


def pantalla_propinas():
    tasa_bcv_auto, fecha_bcv, fuente_bcv = obtener_tasa_bcv()

    if st.session_state.get("prop_pendiente_reset"):
        for k, v in _propina_defaults(st.session_state.get("prop_reset_tasa", tasa_bcv_auto)).items():
            st.session_state[k] = v
        st.session_state.pop("prop_pendiente_reset", None)
        if st.session_state.get("prop_mensaje_ok"):
            st.success(st.session_state.pop("prop_mensaje_ok"))

    for k, v in _propina_defaults(tasa_bcv_auto).items():
        st.session_state.setdefault(k, v)

    _ensure_tasa_formulario("prop_fecha", "prop")

    st.markdown(
        page_header_html(
            "Propinas",
            "Control separado del personal — no se mezcla con ventas del restaurante",
            "redeem",
        ),
        unsafe_allow_html=True,
    )

    hoy = date.today()
    with st.container(border=True):
        rango = st.date_input(
            "Rango de fechas",
            value=(hoy, hoy),
            max_value=hoy,
            key="rango_propinas",
        )

    if isinstance(rango, (list, tuple)):
        if len(rango) >= 2:
            fecha_inicio, fecha_fin = rango[0], rango[1]
        elif len(rango) == 1:
            fecha_inicio = fecha_fin = rango[0]
        else:
            fecha_inicio = fecha_fin = hoy
    else:
        fecha_inicio = fecha_fin = rango

    if fecha_fin < fecha_inicio:
        st.error("La fecha final no puede ser anterior a la inicial.")
        return

    df = cargar_propinas_periodo(fecha_inicio, fecha_fin)
    totales = totales_propinas_por_moneda(df)
    n_reg = len(df)

    stats_html = ""
    for lbl, val in mini_stats_moneda(totales, _saldos_moneda_vacio()):
        stats_html += (
            f'<div class="mini-stat"><div class="mini-stat-label">{lbl}</div>'
            f'<div class="mini-stat-value">{val}</div></div>'
        )
    st.markdown(
        f'<div class="dash-panel dash-panel-hero accent-propinas">'
        f'<div class="kpi-label">Total propinas del período</div>'
        f'<div class="mini-stats-row">{stats_html}</div>'
        f'<div class="hero-context">{n_reg} registro(s) · montos por moneda sin conversión</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not df.empty:
        with st.expander("Detalle de propinas del período", expanded=False):
            tabla = df.copy()
            tabla["Fecha"] = pd.to_datetime(tabla["fecha"], errors="coerce").dt.strftime(
                "%d/%m/%Y %H:%M"
            )
            tabla["Propina"] = tabla.apply(
                lambda r: formatear_monto(
                    r["monto"] if r["tipo"] == "Propina" else r.get("propina", 0),
                    r["moneda"] if r["tipo"] == "Propina" else r.get("propina_moneda", r["moneda"]),
                ),
                axis=1,
            )
            tabla["Origen"] = tabla.apply(
                lambda r: "Registro directo" if r["tipo"] == "Propina" else f'Adjunta a {r["tipo"]}',
                axis=1,
            )
            st.dataframe(
                tabla[["Fecha", "Propina", "Origen", "banco", "notas"]].rename(
                    columns={"banco": "Canal", "notas": "Notas"}
                ),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown(
        '<div class="kpi-section-label">Registrar nueva propina</div>',
        unsafe_allow_html=True,
    )

    ss = st.session_state
    es_bs = "Bs" in ss.prop_moneda

    with st.container(border=True):
        st.markdown('<span class="accent-marker accent-propinas"></span>', unsafe_allow_html=True)
        st.markdown(
            panel_titulo("Nueva propina", "Queda aparte del flujo de ingresos ordinarios"),
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.date_input(
                "Fecha",
                key="prop_fecha",
                on_change=_on_prop_fecha_cambiada,
            )
        with c2:
            st.time_input("Hora", key="prop_hora")

        c3, c4 = st.columns(2, gap="medium")
        with c3:
            st.selectbox(
                "Moneda",
                ["USD (Dólares)", "Bs (Bolívares)"],
                key="prop_moneda",
                on_change=_on_prop_moneda_cambiada,
            )
        with c4:
            st.selectbox(
                "Canal / donde quedó",
                ["Efectivo en caja", "Efectivo en caja (Bs)", "Binance / USDT"] + BANCOS_VENEZUELA[:6],
                key="prop_banco",
            )

        if es_bs:
            fuente_tasa = ss.get("prop_tasa_fuente") or fuente_bcv
            sync_ok = bool(fuente_tasa) and not ss.get("prop_tasa_aviso")
            badge = bcv_badge_html(sync_ok)
            st.markdown(
                f'<div class="bcv-field-label">'
                f'<span>Tasa BCV del día (Bs / $)</span>'
                f'<span class="bcv-sync-badge">{badge}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.number_input(
                "Tasa BCV",
                min_value=0.0,
                step=0.0001,
                format="%.4f",
                label_visibility="collapsed",
                disabled=True,
                help=(
                    f"Tasa oficial para el {ss.prop_fecha.strftime('%d/%m/%Y')} · "
                    f"Fuente: {fuente_tasa or 'BCV'}"
                ),
                key="prop_tasa_bcv",
            )
            if ss.get("prop_tasa_aviso"):
                st.warning(ss.prop_tasa_aviso)
            elif fuente_tasa:
                st.caption(
                    f"Fuente: **{fuente_tasa}** · "
                    f"Tasa para el {ss.prop_fecha.strftime('%d/%m/%Y')}"
                )

        st.number_input(
            "Monto de la propina",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            key="prop_monto",
        )
        st.text_area(
            "Notas (mesa, turno, reparto…)",
            height=70,
            key="prop_notas",
        )

        if st.button("Registrar propina", type="primary", use_container_width=True, key="prop_btn_guardar"):
            faltantes = []
            if float(ss.prop_monto) <= 0:
                faltantes.append("Monto de la propina")
            if es_bs and float(ss.prop_tasa_bcv) <= 0:
                faltantes.append("Tasa BCV")
            if faltantes:
                st.warning("Complete los campos obligatorios.")
                st.caption("Pendientes: " + ", ".join(faltantes))
            else:
                fecha_hora = construir_fecha_hora(ss.prop_fecha, ss.prop_hora)
                guardar_movimiento(
                    fecha_hora,
                    "Propina",
                    ss.prop_monto,
                    ss.prop_moneda,
                    ss.prop_banco,
                    "",
                    ss.prop_notas,
                    categoria=CATEGORIA_PROPINA,
                    tipo_movimiento=TIPO_MOV_PROPINA,
                    tasa_bcv=ss.prop_tasa_bcv if es_bs else 0.0,
                )
                if es_bs and float(ss.prop_tasa_bcv) > 0:
                    _actualizar_tasa_historico(ss.prop_fecha.isoformat(), ss.prop_tasa_bcv)
                _solicitar_reset_propina(
                    tasa_bcv_auto,
                    f"Propina registrada — {formatear_monto(ss.prop_monto, ss.prop_moneda)}",
                )


def _egreso_defaults(tasa_bcv_auto):
    return {
        "eg_fecha": date.today(),
        "eg_hora": datetime.now().time().replace(second=0, microsecond=0),
        "eg_moneda": MONEDAS_EGRESO[0],
        "eg_monto": 0.0,
        "eg_cuenta": CUENTAS_SALIDA[0] if CUENTAS_SALIDA else "Efectivo en caja",
        "eg_categoria": CATEGORIAS_GASTO[0],
        "eg_concepto": "",
        "eg_referencia": "",
        "eg_tasa_bcv": float(tasa_bcv_auto),
        "eg_tasa_fecha_ref": None,
        "eg_tasa_fuente": "",
        "eg_tasa_aviso": "",
    }


def _solicitar_reset_egreso(tasa_bcv_auto, mensaje):
    st.session_state._egreso_reset_pendiente = True
    st.session_state._egreso_reset_tasa = tasa_bcv_auto
    st.session_state._egreso_mensaje_ok = mensaje


def _moneda_str_desde_clave(key):
    return {
        "usd": "USD (Dólares)",
        "bs": "Bs (Bolívares)",
        "usdt": "USDT (Tether)",
    }[key]


def _etiqueta_moneda_corta(key):
    return {"usd": "USD", "bs": "Bs", "usdt": "USDT"}[key]


def cargar_egresos_periodo(fecha_inicio, fecha_fin=None):
    if fecha_fin is None:
        fecha_fin = fecha_inicio
    if fecha_fin < fecha_inicio:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio
    df = cargar_movimientos(fecha_desde=fecha_inicio, fecha_hasta=fecha_fin)
    if df.empty:
        return df
    return df[df.apply(es_egreso, axis=1)].copy()


def formatear_montos_multimoneda(montos_dict):
    """Texto compacto por moneda nativa, omitiendo ceros."""
    partes = []
    for key in MONEDAS_SALDO:
        val = float(montos_dict.get(key, 0) or 0)
        if val == 0:
            continue
        partes.append(formatear_monto(val, _moneda_str_desde_clave(key)))
    return " · ".join(partes) if partes else "—"


def agrupar_egresos_con_monedas(df, columna):
    if df.empty:
        return []
    grupos = {}
    for _, r in df.iterrows():
        nombre = str(r.get(columna) or "—").strip() or "—"
        clave = _clave_moneda_saldo(r.get("moneda", ""))
        monto = _monto_neto_abs_fila(r)
        if nombre not in grupos:
            grupos[nombre] = _saldos_moneda_vacio()
        grupos[nombre][clave] += monto
    items = [{"nombre": k, "montos": v} for k, v in grupos.items()]
    items.sort(key=lambda x: max(x["montos"].values()), reverse=True)
    return items


def tendencia_egresos_diaria(df, moneda_key):
    if df.empty:
        return pd.DataFrame(columns=["dia", "monto"])
    sub = df[
        df.apply(lambda r: _clave_moneda_saldo(r.get("moneda", "")) == moneda_key, axis=1)
    ].copy()
    if sub.empty:
        return pd.DataFrame(columns=["dia", "monto"])
    sub["monto_abs"] = sub.apply(_monto_neto_abs_fila, axis=1)
    sub["dia"] = pd.to_datetime(sub["fecha"], errors="coerce").dt.date
    por_dia = (
        sub.groupby("dia", as_index=False)["monto_abs"]
        .sum()
        .rename(columns={"monto_abs": "monto"})
        .sort_values("dia")
    )
    return por_dia


def grafico_tendencia_egreso_moneda(por_dia, moneda_key, height=260):
    if por_dia.empty:
        return None
    mon_str = _moneda_str_desde_clave(moneda_key)
    etiqueta = _etiqueta_moneda_corta(moneda_key)
    x = [d.strftime("%d/%m") for d in por_dia["dia"]]
    y = por_dia["monto"].tolist()
    textos = [formatear_monto(v, mon_str) for v in y]
    fig = go.Figure(
        data=[
            go.Bar(
                x=x,
                y=y,
                marker=dict(color=GIARDINO_EXPENSE, line=dict(width=0)),
                text=textos,
                textposition="outside",
                textfont=dict(color=GIARDINO_TEXT_DARK, size=12, family="Inter"),
                cliponaxis=False,
                showlegend=False,
                name=f"Egresos {etiqueta}",
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        ]
    )
    finalizar_grafico(fig, height=height, leyenda=False)
    fig.update_layout(margin=dict(t=40, b=28, l=8, r=8))
    fig.update_xaxes(showgrid=False, tickfont=dict(color=GIARDINO_MUTED, size=11))
    aplicar_eje_y_limpio(fig, max(y) if y else 0)
    return fig


def _lista_grupos_egreso_html(grupos):
    filas = []
    for g in grupos[:12]:
        filas.append(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
            f'padding:0.5rem 0;border-bottom:1px solid var(--border-card);">'
            f'<span style="color:var(--text-main);font-size:0.95rem;">{g["nombre"]}</span>'
            f'<span style="font-weight:600;color:var(--text-main);font-size:0.95rem;'
            f'text-align:right;margin-left:1rem;">'
            f'{formatear_montos_multimoneda(g["montos"])}</span></div>'
        )
    return (
        f'<div class="dash-panel accent-egresos">'
        f'{"".join(filas)}'
        f'</div>'
    )


def _render_bloque_desglose_egresos(titulo, subtitulo, grupos, etiqueta_simple):
    st.markdown(panel_titulo(titulo, subtitulo), unsafe_allow_html=True)
    if not grupos:
        st.markdown(
            '<p class="empty-chart-msg">Sin datos en el período.</p>',
            unsafe_allow_html=True,
        )
        return
    if len(grupos) == 1:
        g = grupos[0]
        st.markdown(
            f'<div class="dash-panel accent-egresos">'
            f'{stat_simple_html(g["nombre"], formatear_montos_multimoneda(g["montos"]), f"Única {etiqueta_simple} con movimiento")}'
            f'</div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(_lista_grupos_egreso_html(grupos), unsafe_allow_html=True)


def _render_tabla_detalle_egresos(df, fecha_inicio, fecha_fin):
    rango_txt = (
        fecha_inicio.strftime("%d/%m/%Y")
        if fecha_inicio == fecha_fin
        else f"{fecha_inicio.strftime('%d/%m/%Y')} — {fecha_fin.strftime('%d/%m/%Y')}"
    )
    with st.expander(f"Detalle de egresos ({rango_txt})", expanded=False):
        st.caption(
            "Atajo filtrado al rango actual. El historial completo está en "
            "**Historial y reportes**."
        )
        tabla = df.copy()
        tabla["Fecha"] = pd.to_datetime(tabla["fecha"], errors="coerce").dt.strftime(
            "%d/%m/%Y %H:%M"
        )
        tabla["Monto"] = tabla.apply(
            lambda r: formatear_monto(r["monto"], r["moneda"]), axis=1
        )
        tabla["Categoría"] = tabla["tipo"]
        tabla_display = tabla[
            ["Fecha", "Categoría", "Monto", "moneda", "banco", "referencia", "notas"]
        ].rename(
            columns={
                "moneda": "Moneda",
                "banco": "Cuenta de salida",
                "referencia": "Referencia",
                "notas": "Concepto",
            }
        )
        st.dataframe(tabla_display, use_container_width=True, hide_index=True)


def _render_dashboard_egresos(fecha_inicio, fecha_fin):
    if fecha_fin < fecha_inicio:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

    es_un_dia = fecha_inicio == fecha_fin
    delta_label = "vs ayer" if es_un_dia else "vs período anterior"
    sufijo = "del día" if es_un_dia else "del período"

    df = cargar_egresos_periodo(fecha_inicio, fecha_fin)

    duracion = (fecha_fin - fecha_inicio).days + 1
    prev_fin = fecha_inicio - timedelta(days=1)
    prev_inicio = prev_fin - timedelta(days=duracion - 1)
    df_prev = cargar_egresos_periodo(prev_inicio, prev_fin)

    totales = _sumar_por_moneda_df(df)
    totales_prev = _sumar_por_moneda_df(df_prev)

    tasa_panel, fecha_tasa_panel, fuente_tasa_panel = obtener_tasa_bcv()
    es_tasa_respaldo = fuente_tasa_panel == "Tasa de respaldo"
    eq_egresos = (
        ""
        if es_tasa_respaldo
        else equivalente_bs_footer_html(totales, tasa_panel, fecha_tasa_panel)
    )

    n_reg = len(df)
    mov_label = "registro" if n_reg == 1 else "registros"
    contexto_hero = (
        f'{n_reg} {mov_label} {sufijo} · montos por moneda sin conversión'
    )

    if es_tasa_respaldo:
        st.markdown(tasa_respaldo_aviso_html(), unsafe_allow_html=True)

    st.markdown(
        hero_metric_multimoneda_card(
            totales,
            totales_prev,
            contexto_hero,
            eq_egresos,
            etiqueta=f"Egresos {sufijo}",
            delta_label=delta_label,
            accent_class="accent-egresos",
        ),
        unsafe_allow_html=True,
    )

    if df.empty:
        st.markdown(
            f'<p class="empty-day-notice">Sin egresos registrados en este rango.</p>',
            unsafe_allow_html=True,
        )
        return

    grupos_cat = agrupar_egresos_con_monedas(df, "tipo")
    grupos_cta = agrupar_egresos_con_monedas(df, "banco")

    col_cat, col_cta = st.columns(2, gap="medium")
    with col_cat:
        with st.container(border=True):
            _render_bloque_desglose_egresos(
                "Top categorías",
                "Agrupado por categoría con desglose por moneda",
                grupos_cat,
                "categoría",
            )
    with col_cta:
        with st.container(border=True):
            _render_bloque_desglose_egresos(
                "Por cuenta de salida",
                "Efectivo, bancos y demás cuentas",
                grupos_cta,
                "cuenta",
            )

    monedas_tendencia = [
        k for k in MONEDAS_SALDO if float(totales.get(k, 0) or 0) > 0
    ]
    if monedas_tendencia:
        st.markdown(
            '<div class="kpi-section-label">Tendencia día a día</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(len(monedas_tendencia), gap="medium")
        for col, moneda_key in zip(cols, monedas_tendencia):
            por_dia = tendencia_egresos_diaria(df, moneda_key)
            with col:
                with st.container(border=True):
                    st.markdown(
                        panel_titulo(
                            f"Egresos {_etiqueta_moneda_corta(moneda_key)}",
                            "Total diario en moneda nativa",
                        ),
                        unsafe_allow_html=True,
                    )
                    fig = grafico_tendencia_egreso_moneda(por_dia, moneda_key)
                    if fig:
                        st.plotly_chart(
                            fig,
                            use_container_width=True,
                            config={"displayModeBar": False},
                        )

    _render_tabla_detalle_egresos(df, fecha_inicio, fecha_fin)


def _render_formulario_egreso():
    tasa_bcv_auto, fecha_bcv, fuente_bcv = obtener_tasa_bcv()
    ss = st.session_state

    if ss.get("_egreso_reset_pendiente"):
        for k, v in _egreso_defaults(ss.get("_egreso_reset_tasa", tasa_bcv_auto)).items():
            ss[k] = v
        ss._egreso_reset_pendiente = False
        if ss.get("_egreso_mensaje_ok"):
            st.success(ss._egreso_mensaje_ok)
            ss._egreso_mensaje_ok = ""

    for k, v in _egreso_defaults(tasa_bcv_auto).items():
        ss.setdefault(k, v)

    _sync_tasa_si_fecha_cambio("eg_fecha", "eg")

    es_bs = "Bs" in ss.eg_moneda

    with st.container(border=True):
        st.markdown('<span class="accent-marker accent-egresos"></span>', unsafe_allow_html=True)
        st.markdown(
            panel_titulo("Nuevo egreso", "Registra pagos y salidas de caja o banco"),
            unsafe_allow_html=True,
        )

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.date_input("Fecha", key="eg_fecha", on_change=_on_eg_fecha_cambiada)
        with c2:
            st.time_input("Hora", key="eg_hora")

        c3, c4 = st.columns(2, gap="medium")
        with c3:
            st.selectbox("Moneda", MONEDAS_EGRESO, key="eg_moneda")
        with c4:
            st.selectbox("Cuenta de salida", CUENTAS_SALIDA, key="eg_cuenta")

        if es_bs:
            fuente_tasa = ss.get("eg_tasa_fuente") or fuente_bcv
            sync_ok = bool(fuente_tasa) and not ss.get("eg_tasa_aviso")
            badge = bcv_badge_html(sync_ok)
            st.markdown(
                f'<div class="bcv-field-label">'
                f'<span>Tasa BCV del día (Bs / $)</span>'
                f'<span class="bcv-sync-badge">{badge}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.number_input(
                "Tasa BCV",
                min_value=0.0,
                step=0.0001,
                format="%.4f",
                label_visibility="collapsed",
                help=f"Fuente: {fuente_tasa} · Fecha: {ss.eg_fecha.strftime('%d/%m/%Y')}",
                key="eg_tasa_bcv",
            )
            if ss.get("eg_tasa_aviso"):
                st.warning(ss.eg_tasa_aviso)
            elif fuente_tasa:
                st.caption(
                    f"Fuente: **{fuente_tasa}** · "
                    f"Tasa para el {ss.eg_fecha.strftime('%d/%m/%Y')}"
                )

        simbolo = "Bs" if es_bs else "$"
        st.markdown(
            f'<div class="reg-monto-marker" data-currency="{simbolo}" data-flow="out"></div>',
            unsafe_allow_html=True,
        )
        st.number_input(
            "Monto del egreso",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            key="eg_monto",
        )

        st.selectbox("Categoría del gasto", CATEGORIAS_GASTO, key="eg_categoria")

        st.text_input(
            "Referencia (opcional)",
            placeholder="Factura, comprobante, número de transferencia…",
            key="eg_referencia",
        )

        st.text_area(
            "Concepto / descripción",
            placeholder='Ej: "Compra de hortalizas al proveedor X", "Pago luz mes de junio"…',
            height=90,
            key="eg_concepto",
        )

    st.markdown('<div class="reg-submit eg-submit">', unsafe_allow_html=True)
    with st.form("formulario_egreso", clear_on_submit=False):
        guardar = st.form_submit_button(
            "Registrar egreso", type="primary", use_container_width=True
        )
    st.markdown("</div>", unsafe_allow_html=True)

    if guardar:
        faltantes = []
        if float(ss.eg_monto) <= 0:
            faltantes.append("Monto del egreso")
        if not str(ss.eg_concepto).strip():
            faltantes.append("Concepto / descripción")
        if not str(ss.eg_cuenta).strip():
            faltantes.append("Cuenta de salida")

        if faltantes:
            st.warning("Por favor, complete los campos obligatorios.")
            st.caption("Pendientes: " + ", ".join(faltantes))
        else:
            fecha_hora = construir_fecha_hora(ss.eg_fecha, ss.eg_hora)
            fecha_txt = ss.eg_fecha.strftime("%d/%m/%Y")
            guardar_movimiento(
                fecha_hora,
                ss.eg_categoria,
                ss.eg_monto,
                ss.eg_moneda,
                ss.eg_cuenta,
                ss.eg_referencia,
                ss.eg_concepto,
                tasa_bcv=ss.eg_tasa_bcv if es_bs else 0.0,
                tipo_movimiento=TIPO_MOV_EGRESO,
                categoria=ss.eg_categoria,
            )
            if es_bs and float(ss.eg_tasa_bcv) > 0:
                _actualizar_tasa_historico(ss.eg_fecha.isoformat(), ss.eg_tasa_bcv)
            _solicitar_reset_egreso(
                tasa_bcv_auto,
                f"Egreso registrado — {ss.eg_categoria} · "
                f"{formatear_monto(ss.eg_monto, ss.eg_moneda)} · {fecha_txt}",
            )
            st.rerun()


def pantalla_registrar_egreso():
    st.markdown(
        page_header_html(
            "Egresos / Gastos",
            "Resumen del período y registro de salidas",
            "payments",
        ),
        unsafe_allow_html=True,
    )

    hoy = date.today()
    with st.container(border=True):
        rango = st.date_input(
            "Rango de fechas (mismo día = un solo día)",
            value=(hoy, hoy),
            max_value=hoy,
            key="rango_egresos",
        )

    if isinstance(rango, (list, tuple)):
        if len(rango) >= 2:
            fecha_inicio, fecha_fin = rango[0], rango[1]
        elif len(rango) == 1:
            fecha_inicio = fecha_fin = rango[0]
        else:
            fecha_inicio = fecha_fin = hoy
    else:
        fecha_inicio = fecha_fin = rango

    if fecha_fin < fecha_inicio:
        st.error("La fecha final no puede ser anterior a la inicial.")
        return

    _render_dashboard_egresos(fecha_inicio, fecha_fin)

    st.markdown(
        '<div class="kpi-section-label">Registrar nuevo egreso</div>',
        unsafe_allow_html=True,
    )
    _render_formulario_egreso()


def _fmt_fecha_iso(fecha_str):
    if not str(fecha_str or "").strip():
        return "—"
    try:
        return pd.to_datetime(fecha_str).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(fecha_str)


def pantalla_cuentas_por_cobrar():
    st.markdown(
        page_header_html(
            "Cuentas por cobrar",
            "Clientes morosos, pagos parciales e historial de cobros",
            "account_balance_wallet",
        ),
        unsafe_allow_html=True,
    )

    pendientes = cargar_cuentas_por_cobrar_completo()
    totales_pend = totales_cobrar_por_moneda(pendientes)
    n_clientes = contar_clientes_con_saldo(pendientes)

    if pendientes:
        stats_hero = mini_stats_moneda(totales_pend, {"usd": 0.0, "bs": 0.0, "usdt": 0.0})
        stats_html = ""
        for lbl, val in stats_hero:
            stats_html += (
                f'<div class="mini-stat"><div class="mini-stat-label">{lbl}</div>'
                f'<div class="mini-stat-value">{val}</div></div>'
            )
        st.markdown(
            f'<div class="dash-panel dash-panel-hero">'
            f'<div class="kpi-label">Total por cobrar</div>'
            f'<div class="mini-stats-row">{stats_html}</div>'
            f'<div class="hero-context">{n_clientes} cliente(s) con saldo pendiente · '
            f'montos en moneda original</div></div>',
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown(
            panel_titulo(
                "Clientes con saldo pendiente",
                "Ordenados por deuda de mayor a menor",
                "receipt_long",
            ),
            unsafe_allow_html=True,
        )

        if not pendientes:
            st.info("No hay cuentas abiertas pendientes de cobro.")
        else:
            filas = []
            for p in pendientes:
                filas.append({
                    "Cédula": p["cedula"],
                    "Nombre": p["nombre"],
                    "Moneda": p["moneda"],
                    "Deuda original": formatear_saldo_cobrar(p["deuda_original"], p["moneda"]),
                    "Total pagado": formatear_saldo_cobrar(p["total_pagado"], p["moneda"]),
                    "Saldo pendiente": formatear_saldo_cobrar(p["saldo_pendiente"], p["moneda"]),
                    "Último pago": _fmt_fecha_iso(p.get("fecha_ultimo_pago")),
                    "Consumo más antiguo": _fmt_fecha_iso(p.get("fecha_mas_antigua")),
                })
            st.dataframe(
                pd.DataFrame(filas),
                use_container_width=True,
                hide_index=True,
            )

    with st.container(border=True):
        st.markdown(
            panel_titulo("Registrar pago", "Parcial o total — el saldo se calcula automáticamente"),
            unsafe_allow_html=True,
        )

        if not pendientes:
            st.caption("Cuando registres consumos a crédito aparecerán aquí para cobrar.")
        else:
            opciones = {
                p["clave_fila"]: (
                    f"{p['nombre'] or p['cedula']} — "
                    f"{formatear_saldo_cobrar(p['saldo_pendiente'], p['moneda'])}"
                )
                for p in pendientes
            }
            clave_sel = st.selectbox(
                "Cliente / deuda",
                options=list(opciones.keys()),
                format_func=lambda k: opciones[k],
                key="cobrar_clave",
            )
            sel = next(p for p in pendientes if p["clave_fila"] == clave_sel)
            moneda_deuda = sel["moneda"]

            metodo_opts = list(METODOS_COBRO_CLIENTE.keys())
            metodo_labels = {k: METODOS_COBRO_CLIENTE[k]["label"] for k in metodo_opts}
            c1, c2, c3 = st.columns([2, 2, 1], gap="medium")
            with c1:
                metodo = st.selectbox(
                    "Método de pago",
                    metodo_opts,
                    format_func=lambda k: metodo_labels[k],
                    key="cobrar_metodo",
                )
            moneda_pago = METODOS_COBRO_CLIENTE[metodo]["moneda_default"]
            tasa_cobro, _, _ = resolver_tasa_para_fecha(date.today())
            monto_saldo_pago = monto_pago_para_cubrir_saldo(
                float(sel["saldo_pendiente"]),
                moneda_deuda,
                moneda_pago,
                tasa_cobro,
            )
            with c2:
                monto_pago = st.number_input(
                    f"Monto de este pago ({moneda_pago.split('(')[0].strip()})",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    value=float(monto_saldo_pago),
                    key="cobrar_monto",
                )
            with c3:
                st.markdown('<div style="height:1.75rem"></div>', unsafe_allow_html=True)
                if st.button("Saldo completo", key="cobrar_saldo_full", use_container_width=True):
                    st.session_state.cobrar_monto = float(monto_saldo_pago)
                    st.rerun()

            st.caption(
                f"Deuda en **{moneda_deuda}** · "
                f"Original: **{formatear_saldo_cobrar(sel['deuda_original'], moneda_deuda)}** · "
                f"Pagado: **{formatear_saldo_cobrar(sel['total_pagado'], moneda_deuda)}** · "
                f"Pendiente: **{formatear_saldo_cobrar(sel['saldo_pendiente'], moneda_deuda)}**"
            )

            if not monedas_misma_familia(moneda_pago, moneda_deuda):
                aplicado, tasa_prev = convertir_monto_entre_monedas(
                    monto_pago, moneda_pago, moneda_deuda, tasa_cobro
                )
                if tasa_prev > 0:
                    st.info(
                        f"Con tasa del día del pago ({tasa_prev:,.2f} Bs/USD): "
                        f"**{formatear_monto(monto_pago, moneda_pago)}** ≈ "
                        f"**{formatear_saldo_cobrar(aplicado, moneda_deuda)}** aplicados a la deuda."
                    )
                else:
                    st.warning(
                        "No hay tasa BCV para hoy. No se puede calcular la conversión del pago."
                    )

            notas_pago = st.text_input(
                "Notas (opcional)",
                key="cobrar_notas",
                placeholder="Referencia, observación…",
            )

            if st.button("Registrar pago", type="primary", key="cobrar_btn_registrar"):
                ok, msg = registrar_pago_cliente(
                    sel["cedula"],
                    monto_pago,
                    metodo,
                    moneda_deuda=moneda_deuda,
                    notas=notas_pago.strip(),
                )
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    if pendientes:
        with st.container(border=True):
            st.markdown(
                panel_titulo("Historial de pagos", "Por cliente"),
                unsafe_allow_html=True,
            )
            opciones_hist = {
                p["cedula"]: f"{p['cedula']} — {p['nombre']}"
                for p in pendientes
            }
            # Un cliente puede aparecer varias veces (por moneda); deduplicar para historial
            cedulas_hist = list(dict.fromkeys(p["cedula"] for p in pendientes))
            opciones_hist = {c: opciones_hist[c] for c in cedulas_hist}
            cedula_hist = st.selectbox(
                "Ver historial de",
                options=list(opciones_hist.keys()),
                format_func=lambda c: opciones_hist[c],
                key="cobrar_hist_cedula",
            )
            historial = cargar_historial_pagos_cliente(cedula_hist)
            if not historial:
                st.caption("Sin pagos registrados aún para este cliente.")
            else:
                filas_hist = []
                for h in historial:
                    mon_deuda = h.get("moneda_deuda") or h["moneda"]
                    aplicado = float(h.get("monto_aplicado_deuda") or h["monto"] or 0)
                    tasa = float(h.get("tasa_conversion") or 0)
                    filas_hist.append({
                        "Fecha": _fmt_fecha_iso(h["fecha"]),
                        "Monto pagado": formatear_monto(h["monto"], h["moneda"]),
                        "Moneda pago": h["moneda"],
                        "Aplicado a deuda": formatear_saldo_cobrar(aplicado, mon_deuda),
                        "Moneda deuda": mon_deuda,
                        "Tasa usada": f"{tasa:,.4f}" if tasa > 0 else "—",
                        "Método": h["metodo"] or "—",
                        "Canal": h["banco"] or "—",
                        "Notas": h["notas"] or "—",
                    })
                st.dataframe(
                    pd.DataFrame(filas_hist),
                    use_container_width=True,
                    hide_index=True,
                )


def pantalla_clientes():
    st.markdown(
        page_header_html(
            "Base de Clientes",
            "Clientes registrados, cuentas por cobrar y visitas",
            "groups",
        ),
        unsafe_allow_html=True,
    )

    pendientes = cargar_cuentas_abiertas_resumen()
    totales_pend = totales_cobrar_por_moneda(pendientes)
    n_clientes = contar_clientes_con_saldo(pendientes)

    if pendientes:
        fa0 = pd.to_datetime(pendientes[0]["fecha_mas_antigua"], errors="coerce")
        antiguo_txt = fa0.strftime("%d/%m/%Y") if pd.notna(fa0) else "sin fecha registrada"
        stats_hero = mini_stats_moneda(totales_pend, {"usd": 0.0, "bs": 0.0, "usdt": 0.0})
        stats_html = ""
        for lbl, val in stats_hero:
            stats_html += (
                f'<div class="mini-stat"><div class="mini-stat-label">{lbl}</div>'
                f'<div class="mini-stat-value">{val}</div></div>'
            )
        st.markdown(
            f'<div class="dash-panel dash-panel-hero">'
            f'<div class="kpi-label">Total por cobrar</div>'
            f'<div class="mini-stats-row">{stats_html}</div>'
            f'<div class="hero-context">{n_clientes} cliente(s) con cuenta abierta · '
            f'consumo más antiguo: {antiguo_txt}</div></div>',
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown(
            panel_titulo("Cuentas por Cobrar", "Saldos pendientes de clientes de confianza", "receipt_long"),
            unsafe_allow_html=True,
        )

        if not pendientes:
            st.info("No hay cuentas abiertas pendientes de cobro.")
        else:
            filas_pend = []
            for p in pendientes:
                fa = pd.to_datetime(p["fecha_mas_antigua"], errors="coerce")
                consumo_txt = fa.strftime("%d/%m/%Y %H:%M") if pd.notna(fa) else "—"
                filas_pend.append({
                    "Cédula": p["cedula"],
                    "Nombre": p["nombre"],
                    "Moneda": p["moneda"],
                    "Monto Pendiente": formatear_saldo_cobrar(p["monto_pendiente"], p["moneda"]),
                    "Consumo más antiguo": consumo_txt,
                    "Movimientos": int(p["movimientos"]),
                })
            st.dataframe(
                pd.DataFrame(filas_pend),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Para registrar pagos (parciales o totales) ve a **Cuentas por cobrar** en el menú lateral."
            )
            if st.button("Ir a Cuentas por cobrar →", key="cli_nav_cobrar"):
                st.session_state.nav_key = "cobrar"
                st.rerun()

    with st.container(border=True):
        st.markdown(
            panel_titulo("Directorio de clientes", "Todos los clientes registrados"),
            unsafe_allow_html=True,
        )

        df = cargar_clientes_resumen()

        if df.empty:
            st.info(
                "Aún no hay clientes en la base de datos. "
                "Registra el primero desde **Nuevo movimiento** activando "
                "«¿Registrar datos del cliente?»."
            )
        else:
            total = len(df)
            visitas = int(df["visitas"].sum())
            k1, k2 = st.columns(2, gap="medium")
            with k1:
                st.metric("Clientes registrados", total)
            with k2:
                st.metric("Visitas totales (movimientos)", visitas)

            tabla = df.rename(
                columns={
                    "cedula": "Cédula",
                    "nombre": "Nombre",
                    "telefono": "Teléfono",
                    "fecha_registro": "Fecha de Registro",
                    "visitas": "Visitas Totales",
                }
            )[["Cédula", "Nombre", "Teléfono", "Fecha de Registro", "Visitas Totales"]]

            st.dataframe(
                tabla,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Cédula": st.column_config.TextColumn(width="medium"),
                    "Nombre": st.column_config.TextColumn(width="large"),
                    "Teléfono": st.column_config.TextColumn(width="medium"),
                    "Fecha de Registro": st.column_config.TextColumn(width="medium"),
                    "Visitas Totales": st.column_config.NumberColumn(width="small"),
                },
            )

        with st.expander("Editar cliente", expanded=False):
            st.caption("Seleccione un cliente por cédula para corregir nombre o teléfono.")
            if df.empty:
                st.caption("No hay clientes para editar.")
            else:
                opciones = {
                    row["cedula"]: f"{row['cedula']} — {row['nombre']}"
                    for _, row in df.iterrows()
                }
                cedula_sel = st.selectbox(
                    "Cliente (por cédula)",
                    options=list(opciones.keys()),
                    format_func=lambda c: opciones[c],
                    key="cli_edit_cedula",
                )
                cliente = buscar_cliente_por_cedula(cedula_sel)
                if cliente:
                    ec1, ec2 = st.columns(2, gap="medium")
                    with ec1:
                        nuevo_nombre = st.text_input(
                            "Nombre",
                            value=cliente["nombre"],
                            key=f"cli_edit_nombre_{cedula_sel}",
                        )
                    with ec2:
                        nuevo_tel = st.text_input(
                            "Teléfono",
                            value=cliente.get("telefono") or "",
                            key=f"cli_edit_tel_{cedula_sel}",
                        )
                    if st.button("Guardar cambios", type="primary", key="cli_btn_guardar"):
                        if not nuevo_nombre.strip():
                            st.warning("El nombre no puede estar vacío.")
                        elif not nuevo_tel.strip():
                            st.warning("El teléfono no puede estar vacío.")
                        elif actualizar_cliente(cedula_sel, nuevo_nombre, nuevo_tel):
                            st.success(f"Cliente {cedula_sel} actualizado correctamente.")
                            st.rerun()
                        else:
                            st.error("No se pudo actualizar el cliente.")

        with st.expander("Eliminar cliente", expanded=False):
            st.caption(
                "Quita al cliente del directorio. "
                "Los movimientos ya registrados en caja **no se borran**."
            )
            if df.empty:
                st.caption("No hay clientes para eliminar.")
            else:
                opciones_del = {
                    row["cedula"]: f"{row['cedula']} — {row['nombre']}"
                    for _, row in df.iterrows()
                }
                cedula_del = st.selectbox(
                    "Cliente a eliminar",
                    options=list(opciones_del.keys()),
                    format_func=lambda c: opciones_del[c],
                    key="cli_del_cedula",
                )
                n_mov = contar_movimientos_cliente(cedula_del)
                if cliente_tiene_cuenta_abierta(cedula_del):
                    st.error(
                        "Este cliente tiene **cuentas abiertas**. "
                        "Debe cobrarlas antes de poder eliminarlo del directorio."
                    )
                elif n_mov > 0:
                    st.warning(
                        f"Este cliente tiene **{n_mov} movimiento(s)** en el historial. "
                        "Al eliminarlo solo desaparece del directorio; los registros de caja se mantienen."
                    )
                confirmar = st.checkbox(
                    "Confirmo que deseo eliminar este cliente del directorio",
                    key=f"cli_del_confirm_{cedula_del}",
                )
                if st.button("Eliminar cliente", key="cli_btn_eliminar"):
                    if not confirmar:
                        st.warning("Marque la casilla de confirmación para continuar.")
                    else:
                        ok, msg = eliminar_cliente(cedula_del)
                        if ok:
                            st.success(f"Cliente {cedula_del} eliminado del directorio.")
                            st.rerun()
                        else:
                            st.error(msg or "No se pudo eliminar el cliente.")


HIST_NATURALEZA_TABS = [
    ("todos", "🔳 Todos", None),
    ("ingreso", "▲ Ingresos", TIPO_MOV_INGRESO),
    ("egreso", "▼ Egresos", TIPO_MOV_EGRESO),
    ("propina", "◽ Propina", TIPO_MOV_PROPINA),
]

HIST_COLOR_INGRESO = GIARDINO_BANK
HIST_COLOR_EGRESO = GIARDINO_EXPENSE
HIST_COLOR_PROPINA = "#B45309"

HIST_EXCEL_SHEET = "Historial_Caja_Il_Giardino"
HIST_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HIST_EXCEL_COLUMNAS = [
    "ID",
    "Fecha y Hora",
    "Naturaleza",
    "Concepto",
    "Medio de Pago",
    "Monto",
    "Moneda",
    "Monto Total POS",
    "Tasa BCV",
    "Referencia",
    "Comisión POS",
    "Cliente",
    "Cédula / RIF",
    "IVA 16%",
    "Tipo de Cuenta",
    "Comensales",
    "Notas",
]


def _monto_numerico_historial(row):
    """Monto con signo contable: egresos negativos, ingresos/propinas positivos."""
    monto = abs(float(row.get("monto", 0) or 0))
    if es_egreso(row):
        return -monto
    return monto


def _tasa_bcv_numerica(row):
    if "Bs" not in str(row.get("moneda", "")):
        return None
    tasa = float(row.get("tasa_bcv", 0) or 0)
    return tasa if tasa > 0 else None


def _monto_total_pos_numerico(row):
    """Lote bruto POS (cuenta + propina) para conciliación Credicard."""
    total = float(row.get("monto_total_pos", 0) or 0)
    return total if total > 0 else None


def preparar_dataframe_excel_historial(df):
    """DataFrame listo para Excel — mismos filtros que la tabla en pantalla."""
    if df.empty:
        return pd.DataFrame(columns=HIST_EXCEL_COLUMNAS)

    filas = []
    for _, row in df.iterrows():
        comision = float(row.get("comision_pos", 0) or 0)
        filas.append({
            "ID": int(row.get("id", 0) or 0),
            "Fecha y Hora": (
                ts.strftime("%d/%m/%Y %H:%M")
                if pd.notna(ts := pd.to_datetime(row["fecha"], errors="coerce"))
                else ""
            ),
            "Naturaleza": _tipo_movimiento_valor(row),
            "Concepto": _categoria_display_fila(row),
            "Medio de Pago": _canal_display_fila(row),
            "Monto": _monto_numerico_historial(row),
            "Moneda": row.get("moneda", ""),
            "Monto Total POS": _monto_total_pos_numerico(row),
            "Tasa BCV": _tasa_bcv_numerica(row),
            "Referencia": str(row.get("referencia") or "").strip(),
            "Comisión POS": comision if comision > 0 else None,
            "Cliente": str(row.get("cliente_nombre") or "").strip(),
            "Cédula / RIF": str(row.get("cliente_cedula") or "").strip(),
            "IVA 16%": "Sí" if row.get("iva_activo") else "—",
            "Tipo de Cuenta": str(row.get("tipo_cuenta") or "Regular").strip(),
            "Comensales": int(row.get("cantidad_personas") or 1),
            "Notas": str(row.get("notas") or "").strip(),
        })
    return pd.DataFrame(filas, columns=HIST_EXCEL_COLUMNAS)


def _auto_ancho_columnas_excel(worksheet, export_df, max_ancho=52):
    for idx, col in enumerate(export_df.columns):
        series = export_df[col].fillna("").astype(str)
        ancho = max(len(str(col)), series.map(len).max() if not series.empty else 0) + 2
        worksheet.set_column(idx, idx, min(ancho, max_ancho))


def generar_excel_historial(df):
    """Construye un .xlsx en memoria con formato ejecutivo (xlsxwriter + BytesIO)."""
    export_df = preparar_dataframe_excel_historial(df)
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, sheet_name=HIST_EXCEL_SHEET, index=False)
        workbook = writer.book
        worksheet = writer.sheets[HIST_EXCEL_SHEET]

        fmt_header = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#2F5233",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
        })
        fmt_texto = workbook.add_format({"border": 1, "valign": "top"})
        fmt_monto = workbook.add_format({"num_format": "#,##0.00", "border": 1, "align": "right"})
        fmt_tasa = workbook.add_format({"num_format": "#,##0.0000", "border": 1, "align": "right"})
        fmt_entero = workbook.add_format({"num_format": "0", "border": 1, "align": "center"})

        for col_idx, nombre in enumerate(export_df.columns):
            worksheet.write(0, col_idx, nombre, fmt_header)

        for row_idx, row in enumerate(export_df.itertuples(index=False), start=1):
            for col_idx, valor in enumerate(row):
                col_name = export_df.columns[col_idx]
                if pd.isna(valor):
                    valor_celda = ""
                else:
                    valor_celda = valor
                if col_name == "Monto" and valor_celda != "":
                    worksheet.write_number(row_idx, col_idx, float(valor_celda), fmt_monto)
                elif col_name == "Monto Total POS" and valor_celda != "":
                    worksheet.write_number(row_idx, col_idx, float(valor_celda), fmt_monto)
                elif col_name == "Tasa BCV" and valor_celda != "":
                    worksheet.write_number(row_idx, col_idx, float(valor_celda), fmt_tasa)
                elif col_name == "Comisión POS" and valor_celda != "":
                    worksheet.write_number(row_idx, col_idx, float(valor_celda), fmt_monto)
                elif col_name in ("ID", "Comensales") and valor_celda != "":
                    worksheet.write_number(row_idx, col_idx, int(valor_celda), fmt_entero)
                else:
                    worksheet.write(row_idx, col_idx, valor_celda, fmt_texto)

        worksheet.freeze_panes(1, 0)
        ultima_fila = len(export_df)
        if ultima_fila > 0:
            worksheet.autofilter(0, 0, ultima_fila, len(export_df.columns) - 1)
        _auto_ancho_columnas_excel(worksheet, export_df)

    buffer.seek(0)
    return buffer.getvalue()


def _etiqueta_naturaleza_export(naturaleza):
    if naturaleza is None:
        return "Todos"
    if naturaleza == TIPO_MOV_INGRESO:
        return "Ingresos"
    if naturaleza == TIPO_MOV_EGRESO:
        return "Egresos"
    if naturaleza == TIPO_MOV_PROPINA:
        return "Propina"
    return str(naturaleza)


def _nombre_archivo_historial_excel(desde, hasta, naturaleza):
    etiqueta = _etiqueta_naturaleza_export(naturaleza)
    return f"Historial_Il_Giardino_{desde:%Y%m%d}_{hasta:%Y%m%d}_{etiqueta}.xlsx"


def _render_descarga_excel_historial(df, desde, hasta, naturaleza):
    if df.empty:
        return
    excel_bytes = generar_excel_historial(df)
    st.download_button(
        label="📊 Descargar Historial en Excel (.xlsx)",
        data=excel_bytes,
        file_name=_nombre_archivo_historial_excel(desde, hasta, naturaleza),
        mime=HIST_EXCEL_MIME,
        type="primary",
        use_container_width=True,
        key=f"hist_excel_{_etiqueta_naturaleza_export(naturaleza)}_{desde}_{hasta}",
    )


def filtrar_historial_naturaleza(df, naturaleza):
    if df.empty or naturaleza is None:
        return df
    return df[df.apply(lambda r: _tipo_movimiento_valor(r) == naturaleza, axis=1)].copy()


def _formatear_monto_historial(row):
    txt = formatear_monto(row["monto"], row["moneda"])
    if _tipo_movimiento_valor(row) == TIPO_MOV_EGRESO:
        return f"- {txt}"
    return txt


def preparar_tabla_historial(df):
    """Arma el DataFrame de Historial con categoría contable y canal separados."""
    tabla = df.copy()
    tabla["Fecha"] = pd.to_datetime(tabla["fecha"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
    tabla["Naturaleza"] = tabla.apply(_tipo_movimiento_valor, axis=1)
    tabla["Categoría"] = tabla.apply(_categoria_display_fila, axis=1)
    tabla["Canal"] = tabla.apply(_canal_display_fila, axis=1)
    tabla["Monto"] = tabla.apply(_formatear_monto_historial, axis=1)
    tabla["IVA 16%"] = tabla.get("iva_activo", pd.Series(0, index=tabla.index)).apply(
        lambda v: "Sí" if v else "—"
    )
    tabla["Tipo Cuenta"] = tabla.get("tipo_cuenta", pd.Series("Regular", index=tabla.index)).fillna("Regular")
    tabla["Personas"] = tabla.get("cantidad_personas", pd.Series(1, index=tabla.index)).fillna(1).astype(int)
    tabla["Tasa BCV"] = tabla.apply(
        lambda r: formatear_tasa_bcv(r.get("tasa_bcv", 0), r["moneda"]), axis=1
    )
    tabla["Comisión POS"] = tabla.apply(
        lambda r: f"Bs {float(r.get('comision_pos', 0) or 0):,.2f}"
        if float(r.get("comision_pos", 0) or 0) > 0
        else "—",
        axis=1,
    )
    tabla["Cliente"] = tabla.get("cliente_nombre", pd.Series("", index=tabla.index)).fillna("").replace("", "—")
    tabla["Cédula"] = tabla.get("cliente_cedula", pd.Series("", index=tabla.index)).fillna("").replace("", "—")
    return tabla[
        ["id", "Fecha", "Naturaleza", "Categoría", "Canal", "Monto", "moneda", "Tasa BCV",
         "referencia", "Comisión POS", "Cliente", "Cédula",
         "IVA 16%", "Tipo Cuenta", "Personas", "notas"]
    ].rename(columns={
        "id": "ID",
        "moneda": "Moneda",
        "referencia": "Referencia",
        "notas": "Notas",
    })


def estilizar_tabla_historial(df_display):
    """Colores por naturaleza en Monto y Naturaleza (sin afectar ordenamiento)."""

    def _estilo_fila(row):
        nat = row.get("Naturaleza", "")
        if nat == TIPO_MOV_EGRESO:
            color = HIST_COLOR_EGRESO
        elif nat == TIPO_MOV_PROPINA:
            color = HIST_COLOR_PROPINA
        else:
            color = HIST_COLOR_INGRESO
        css = f"color: {color}; font-weight: 600;"
        return [
            css if col in ("Naturaleza", "Monto") else ""
            for col in row.index
        ]

    return df_display.style.apply(_estilo_fila, axis=1)


def _render_tabla_historial(df, desde=None, hasta=None, naturaleza=None):
    if df.empty:
        st.markdown(
            f'<p style="color:{GIARDINO_SUBTLE};margin:0;">'
            "No hay movimientos con este filtro.</p>",
            unsafe_allow_html=True,
        )
        return
    tabla_display = preparar_tabla_historial(df)
    st.markdown('<div class="hist-table-wrap">', unsafe_allow_html=True)
    st.dataframe(
        estilizar_tabla_historial(tabla_display),
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID":           st.column_config.NumberColumn(width="small"),
            "Fecha":        st.column_config.TextColumn(width="medium"),
            "Naturaleza":   st.column_config.TextColumn(width="small"),
            "Categoría":    st.column_config.TextColumn(width="medium"),
            "Canal":        st.column_config.TextColumn(width="medium"),
            "Monto":        st.column_config.TextColumn(width="small"),
            "Moneda":       st.column_config.TextColumn(width="small"),
            "Tasa BCV":     st.column_config.TextColumn(
                width="small",
                help="Tasa BCV vigente en la fecha del movimiento (solo pagos en Bs)",
            ),
            "Referencia":   st.column_config.TextColumn(width="medium"),
            "Comisión POS": st.column_config.TextColumn(width="small"),
            "Cliente":      st.column_config.TextColumn(width="medium"),
            "Cédula":       st.column_config.TextColumn(width="small"),
            "IVA 16%":      st.column_config.TextColumn(width="small"),
            "Tipo Cuenta":  st.column_config.TextColumn(width="medium"),
            "Personas":     st.column_config.NumberColumn(width="small"),
            "Notas":        st.column_config.TextColumn(
                width="large",
                help="Desplaza horizontalmente la tabla para leer notas completas",
            ),
        },
    )
    st.markdown("</div>", unsafe_allow_html=True)
    if desde is not None and hasta is not None:
        _render_descarga_excel_historial(df, desde, hasta, naturaleza)


def _render_historial_kpis_neto(df):
    """Tarjetas superiores del historial: neto líquido por moneda (st.metric)."""
    netos = neto_liquido_por_moneda(df)
    col_reg, col_usd, col_bs, col_usdt = st.columns(4)
    with col_reg:
        st.metric("Registros", len(df))

    specs = [
        (col_usd, "USD (Dólares)", "USD", "Neto USD"),
        (col_bs, "Bs (Bolívares)", "Bs", "Neto Bs"),
        (col_usdt, "USDT (Tether)", "USDT", "Neto USDT"),
    ]
    for col, moneda_key, moneda_fmt, etiqueta in specs:
        neto = float(netos.get(moneda_key, 0) or 0)
        if moneda_fmt == "Bs":
            valor = formatear_bs_neto_etiqueta(neto)
        else:
            valor = formatear_monto_neto(neto, moneda_fmt)
        with col:
            if neto < 0:
                st.metric(
                    etiqueta,
                    valor,
                    delta="Flujo neto negativo",
                    delta_color="inverse",
                )
            elif neto > 0:
                st.metric(
                    etiqueta,
                    valor,
                    delta="Flujo neto positivo",
                    delta_color="normal",
                )
            else:
                st.metric(etiqueta, valor)


def pantalla_historial():
    st.markdown(
        page_header_html(
            "Historial y reportes",
            "Consulta rangos de fechas y filtra por categoría o banco",
            "history",
        ),
        unsafe_allow_html=True,
    )

    hoy = date.today()

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            desde = st.date_input("Desde", value=hoy - timedelta(days=7), key="hist_desde")
        with c2:
            hasta = st.date_input("Hasta", value=hoy, key="hist_hasta")
        with c3:
            filtro_tipo = st.selectbox(
                "Concepto / categoría",
                ["Todos"] + categorias_concepto_lista(),
            )
        with c4:
            filtro_banco = st.selectbox("Banco / canal", ["Todos"] + TODOS_BANCOS)

    if desde > hasta:
        st.error("La fecha 'Desde' no puede ser mayor que 'Hasta'.")
        return

    df = cargar_movimientos(desde, hasta, filtro_tipo, filtro_banco)

    if df.empty:
        with st.container(border=True):
            st.markdown(
                f'<p style="color:{GIARDINO_SUBTLE};margin:0;">'
                'No hay movimientos con esos filtros.</p>',
                unsafe_allow_html=True,
            )
        return

    _render_historial_kpis_neto(df)

    col_t, col_b = st.columns(2, gap="medium")

    with col_t:
        with st.container(border=True):
            st.markdown(panel_titulo("Distribución por concepto", "Treemap"), unsafe_allow_html=True)
            agg_tipo = df.copy()
            agg_tipo["concepto"] = agg_tipo.apply(_categoria_display_fila, axis=1)
            agg_tipo = agg_tipo.groupby("concepto")["monto"].sum().reset_index()
            fig = px.treemap(
                agg_tipo,
                path=["concepto"],
                values="monto",
                color="concepto",
                color_discrete_sequence=PALETA_GRAFICOS,
            )
            estilo_plotly(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with col_b:
        with st.container(border=True):
            st.markdown(panel_titulo("Tendencia diaria", "Evolución del periodo"), unsafe_allow_html=True)
            agg_dia = df.copy()
            agg_dia["dia"] = pd.to_datetime(agg_dia["fecha"], errors="coerce").dt.strftime("%d/%m")
            agg_dia = agg_dia.groupby("dia")["monto"].sum().reset_index()
            fig2 = px.line(
                agg_dia,
                x="dia",
                y="monto",
                markers=True,
                labels={"dia": "Día", "monto": "Monto"},
            )
            fig2.update_traces(
                line=dict(color=GIARDINO_BRAND_GREEN, width=2.5),
                marker=dict(color=GIARDINO_BANK, size=7),
            )
            estilo_plotly(fig2, height=340)
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    with st.container(border=True):
        st.markdown(
            panel_titulo("Todos los registros", f"{desde.strftime('%d/%m/%Y')} — {hasta.strftime('%d/%m/%Y')}"),
            unsafe_allow_html=True,
        )

        tab_todos, tab_ing, tab_egr, tab_prop = st.tabs(
            [label for _, label, _ in HIST_NATURALEZA_TABS]
        )
        pares = [
            (tab_todos, None),
            (tab_ing, TIPO_MOV_INGRESO),
            (tab_egr, TIPO_MOV_EGRESO),
            (tab_prop, TIPO_MOV_PROPINA),
        ]
        for tab, naturaleza in pares:
            with tab:
                df_tab = filtrar_historial_naturaleza(df, naturaleza)
                _render_tabla_historial(df_tab, desde, hasta, naturaleza)


def obtener_movimiento_por_id(registro_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM movimientos WHERE id = ?",
            (int(registro_id),),
        ).fetchone()
    return dict(row) if row else None


def _filtrar_movimientos_busqueda(df, texto):
    """Filtra por texto libre en concepto, monto, cédula, referencia, banco y notas."""
    q = str(texto or "").strip().lower()
    if not q or df.empty:
        return df

    def coincide(fila):
        campos = [
            fila.get("tipo", ""),
            fila.get("notas", ""),
            fila.get("referencia", ""),
            fila.get("banco", ""),
            fila.get("cliente_cedula", ""),
            fila.get("cliente_nombre", ""),
            fila.get("monto", ""),
            fila.get("moneda", ""),
        ]
        blob = " ".join(str(c) for c in campos).lower()
        return q in blob

    return df[df.apply(coincide, axis=1)]


def _tabla_busqueda_corregir(df):
    """Prepara columnas ID, Fecha, Cuenta, Concepto, Monto para la tabla de búsqueda."""
    if df.empty:
        return pd.DataFrame(columns=["ID", "Fecha", "Cuenta", "Concepto", "Monto"])

    out = df.copy()
    out["Fecha"] = pd.to_datetime(out["fecha"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
    out["Cuenta"] = out.apply(
        lambda r: str(r.get("banco") or "").strip()
        or str(r.get("tipo_cuenta") or "Regular"),
        axis=1,
    )
    out["Concepto"] = out.apply(
        lambda r: f"Egreso: {r['tipo']}" if es_egreso(r) else str(r["tipo"]),
        axis=1,
    )
    out["Monto"] = out.apply(
        lambda r: (
            f"- {formatear_monto(r['monto'], r['moneda'])}"
            if es_egreso(r)
            else formatear_monto(r["monto"], r["moneda"])
        ),
        axis=1,
    )
    return out[["id", "Fecha", "Cuenta", "Concepto", "Monto"]].rename(columns={"id": "ID"})


def pantalla_corregir():
    st.markdown(
        page_header_html(
            "Corregir o eliminar",
            "Filtra, haz clic en una fila o escribe el ID para editar al instante",
            "edit_square",
        ),
        unsafe_allow_html=True,
    )

    tasa_bcv_auto, fecha_bcv, fuente_bcv = obtener_tasa_bcv()

    with st.container(border=True):
        st.markdown(
            panel_titulo("Paso 1 — Buscar registro", "Filtre por rango de fechas y texto libre"),
            unsafe_allow_html=True,
        )

        f1, f2 = st.columns([1, 2], gap="medium")
        with f1:
            rango_fechas = st.date_input(
                "Rango de fechas",
                value=(date.today() - timedelta(days=30), date.today()),
                key="corr_fecha",
                format="DD/MM/YYYY",
            )
        with f2:
            filtro_texto = st.text_input(
                "Buscar",
                key="corr_busqueda",
                placeholder="Concepto, monto, cédula, referencia, banco…",
            )

        if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
            filtro_desde, filtro_hasta = rango_fechas
        elif isinstance(rango_fechas, date):
            filtro_desde = filtro_hasta = rango_fechas
        else:
            filtro_desde = filtro_hasta = date.today()

        if filtro_desde > filtro_hasta:
            st.error("La fecha inicial del rango no puede ser mayor que la final.")
            return

        df_dia = cargar_movimientos(fecha_desde=filtro_desde, fecha_hasta=filtro_hasta)
        df_filtrado = _filtrar_movimientos_busqueda(df_dia, filtro_texto)
        if not df_filtrado.empty and "id" in df_filtrado.columns:
            df_filtrado = df_filtrado.sort_values("id", ascending=False)
        tabla_display = _tabla_busqueda_corregir(df_filtrado)

        if df_filtrado.empty:
            st.info("No hay movimientos que coincidan con los filtros seleccionados.")
        else:
            st.caption(
                f"{len(df_filtrado)} registro(s) del {filtro_desde.strftime('%d/%m/%Y')} "
                f"al {filtro_hasta.strftime('%d/%m/%Y')} · más reciente arriba · "
                "haz clic en una fila para seleccionarla"
            )
            _df_kwargs = {
                "use_container_width": True,
                "hide_index": True,
                "column_config": {
                    "ID": st.column_config.NumberColumn(width="small"),
                    "Fecha": st.column_config.TextColumn(width="medium"),
                    "Cuenta": st.column_config.TextColumn(width="medium"),
                    "Concepto": st.column_config.TextColumn(width="large"),
                    "Monto": st.column_config.TextColumn(width="small"),
                },
            }
            if "on_select" in inspect.signature(st.dataframe).parameters:
                ids_key = tuple(tabla_display["ID"].tolist())
                if st.session_state.get("_corr_ids_key") != ids_key:
                    st.session_state._corr_ids_key = ids_key
                    st.session_state._corr_sel_idx = None

                evento = st.dataframe(
                    tabla_display,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="corr_tabla_movimientos",
                    **_df_kwargs,
                )
                if evento.selection.rows:
                    idx = evento.selection.rows[0]
                    if st.session_state.get("_corr_sel_idx") != idx:
                        st.session_state._corr_sel_idx = idx
                        st.session_state.corregir_id_editar = int(
                            tabla_display.iloc[idx]["ID"]
                        )
            else:
                st.dataframe(tabla_display, **_df_kwargs)

        st.markdown("---")
        st.markdown(
            panel_titulo(
                "Paso 2 — Seleccionar por ID",
                "Haz clic en la tabla o escribe el número de la columna ID",
            ),
            unsafe_allow_html=True,
        )
        id_editar = st.number_input(
            "Escribe el ID del registro que deseas corregir o eliminar:",
            min_value=0,
            value=0,
            step=1,
            key="corregir_id_editar",
        )

    if id_editar <= 0:
        st.caption("Haz clic en una fila de la tabla o ingresa un ID mayor a 0.")
        return

    actual_row = obtener_movimiento_por_id(id_editar)
    if not actual_row:
        st.warning(f"No existe un registro con ID **{int(id_editar)}**.")
        return

    actual = pd.Series(actual_row)

    with st.container(border=True):
        st.markdown(
            panel_titulo(
                f"Editando registro #{int(id_editar)}",
                f"{pd.to_datetime(actual['fecha']).strftime('%d/%m/%Y %H:%M')} · "
                f"{actual['tipo']} · {formatear_monto(actual['monto'], actual['moneda'])}",
            ),
            unsafe_allow_html=True,
        )

        registro_id = int(id_editar)
        tipos_edicion = list(TIPOS_MOVIMIENTO.keys())
        if actual["tipo"] not in tipos_edicion:
            tipos_edicion = [actual["tipo"]] + tipos_edicion

        with st.form("form_editar"):
            e1, e2 = st.columns(2)
            with e1:
                fecha_parse = pd.to_datetime(actual["fecha"])
                ed_fecha = st.date_input("Fecha", value=fecha_parse.date())
                ed_hora = st.time_input("Hora", value=fecha_parse.time())
            with e2:
                ed_tipo = st.selectbox(
                    "Categoría",
                    tipos_edicion,
                    index=tipos_edicion.index(actual["tipo"])
                    if actual["tipo"] in tipos_edicion
                    else 0,
                )

            e3, e4 = st.columns(2)
            with e3:
                ed_moneda = st.selectbox(
                    "Moneda",
                    MONEDAS,
                    index=MONEDAS.index(actual["moneda"]) if actual["moneda"] in MONEDAS else 0,
                )
            with e4:
                ed_monto = st.number_input(
                    "Monto", value=float(actual["monto"]), min_value=0.0, step=0.01, format="%.2f"
                )

            ed_es_bs = "Bs" in ed_moneda
            ed_tasa_bcv = 0.0
            if ed_es_bs:
                tasa_guardada = float(actual.get("tasa_bcv", 0) or 0)
                valor_tasa = tasa_guardada if tasa_guardada > 0 else float(tasa_bcv_auto)
                st.caption(
                    f"Tasa BCV referencia ({fuente_bcv} · {fecha_bcv}): Bs {tasa_bcv_auto:,.4f} / $"
                )
                ed_tasa_bcv = st.number_input(
                    "Tasa BCV (Bs / $)",
                    min_value=0.01,
                    value=valor_tasa,
                    step=0.0001,
                    format="%.4f",
                )

            ed_banco = st.selectbox(
                "Banco / canal",
                [""] + TODOS_BANCOS,
                index=([""] + TODOS_BANCOS).index(actual["banco"])
                if actual["banco"] in TODOS_BANCOS
                else 0,
            )
            ed_ref = st.text_input("Referencia", value=str(actual["referencia"] or ""))

            st.markdown("---")

            ec1, ec2 = st.columns(2)
            with ec1:
                ed_iva = st.toggle(
                    "¿Incluye 16% de IVA?",
                    value=bool(actual.get("iva_activo", 0)),
                )
            with ec2:
                ed_personas = st.number_input(
                    "Cantidad de personas",
                    min_value=0, max_value=500,
                    value=int(actual.get("cantidad_personas", 1) or 1),
                    step=1,
                )

            _tc_opciones = ["Cliente Regular", "Cuenta Familiar (Exonerada)"]
            _tc_guardado = str(actual.get("tipo_cuenta", "Regular") or "Regular")
            _tc_idx = 1 if "Familiar" in _tc_guardado else 0
            ed_tipo_cuenta = st.radio(
                "Tipo de cuenta", _tc_opciones, index=_tc_idx, horizontal=True,
            )

            _met_guardado = str(actual.get("metodo_detalle", "") or "")
            _met_opts = [""] + list(METODOS_INGRESO.keys())
            _met_idx = _met_opts.index(_met_guardado) if _met_guardado in _met_opts else 0
            ed_metodo = st.selectbox(
                "Método de cobro (solo Ingreso bancario)",
                _met_opts,
                index=_met_idx,
                format_func=lambda m: METODO_ETIQUETAS.get(m, "— Sin método —") if m else "— Sin método —",
            )

            ed_es_tarjeta = False
            if ed_metodo == "POS / Tarjeta":
                ed_es_tarjeta = st.toggle(
                    "¿El pago fue con Tarjeta de Crédito?",
                    value=bool(actual.get("es_tarjeta_credito", 0)),
                )
                ed_comision = calcular_comision_pos(ed_monto, ed_es_tarjeta)
                if ed_es_tarjeta and ed_monto > 0:
                    st.info(
                        f"Comisión POS 5%: **Bs {ed_comision:,.2f}** · "
                        f"Neto estimado al banco: **Bs {ed_monto - ed_comision:,.2f}**"
                    )
            else:
                ed_comision = 0.0

            st.markdown("**Propina registrada**")
            ep1, ep2 = st.columns(2)
            with ep1:
                ed_propina = st.number_input(
                    "Monto propina",
                    min_value=0.0, step=0.01, format="%.2f",
                    value=float(actual.get("propina", 0) or 0),
                )
            with ep2:
                _prop_mon_opts = ["", "USD (Dólares)", "Bs (Bolívares)"]
                _prop_mon_val = str(actual.get("propina_moneda", "") or "")
                _prop_mon_idx = _prop_mon_opts.index(_prop_mon_val) if _prop_mon_val in _prop_mon_opts else 0
                ed_propina_moneda = st.selectbox("Moneda propina", _prop_mon_opts, index=_prop_mon_idx)

            st.markdown("**Datos del cliente**")
            ec_n, ec_c, ec_t = st.columns(3)
            with ec_n:
                ed_cliente_nombre = st.text_input(
                    "Nombre del cliente",
                    value=str(actual.get("cliente_nombre", "") or ""),
                )
            with ec_c:
                ed_cliente_cedula = st.text_input(
                    "Cédula / RIF",
                    value=str(actual.get("cliente_cedula", "") or ""),
                )
            with ec_t:
                ed_cliente_telefono = st.text_input(
                    "Teléfono",
                    value=str(actual.get("cliente_telefono", "") or ""),
                )

            ed_notas = st.text_area(
                "Notas / comentarios del pedido", value=str(actual["notas"] or ""), height=80
            )

            c1, c2 = st.columns(2)
            with c1:
                btn_guardar = st.form_submit_button(
                    "Guardar cambios", use_container_width=True, type="primary"
                )
            with c2:
                btn_borrar = st.form_submit_button("Eliminar registro", use_container_width=True)

            if btn_guardar:
                if ed_metodo == "POS / Tarjeta":
                    comision_final = calcular_comision_pos(ed_monto, ed_es_tarjeta)
                    tarjeta_final = ed_es_tarjeta
                else:
                    comision_final = 0.0
                    tarjeta_final = False

                actualizar_movimiento(
                    registro_id,
                    construir_fecha_hora(ed_fecha, ed_hora),
                    ed_tipo,
                    ed_monto,
                    ed_moneda,
                    ed_banco,
                    ed_ref,
                    ed_notas,
                    iva_activo=ed_iva,
                    tipo_cuenta=ed_tipo_cuenta,
                    cantidad_personas=ed_personas,
                    metodo_detalle=ed_metodo,
                    propina=ed_propina,
                    propina_moneda=ed_propina_moneda,
                    tasa_bcv=ed_tasa_bcv if ed_es_bs else 0.0,
                    es_tarjeta_credito=tarjeta_final,
                    comision_pos=comision_final,
                    cliente_nombre=ed_cliente_nombre.strip(),
                    cliente_cedula=ed_cliente_cedula.strip(),
                    cliente_telefono=ed_cliente_telefono.strip(),
                )
                st.success("Cambios aplicados.")
                st.rerun()

            if btn_borrar:
                eliminar_movimiento(registro_id)
                st.success("Registro eliminado.")
                st.rerun()


# =============================================================================
# APLICACIÓN PRINCIPAL
# =============================================================================

_LOGO_CANDIDATES = [
    LOGO_SIDEBAR,
    BASE_DIR / "logo_giardino.png",
    Path(r"C:\Users\agudelo.jr\.cursor\projects\c-Users-agudelo-jr-Projects-control-caja-restaurante\assets\c__Users_agudelo.jr_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_logo_IL_GIARDINO_Ristorante.jpg-002075e6-018e-41e5-85ee-49f3bdeabfb9.png"),
]


def ensure_logo():
    """Copia logo al proyecto si aún no existe."""
    if LOGO_SIDEBAR.exists():
        return
    dest = BASE_DIR / "logo.png"
    if dest.exists():
        return
    for src in _LOGO_CANDIDATES:
        if src != dest and src != LOGO_SIDEBAR and src.exists():
            try:
                dest.write_bytes(src.read_bytes())
                return
            except Exception:
                continue


def render_nav_logo():
    """Logo Il Giardino en el panel de navegación."""
    try:
        if LOGO_SIDEBAR.exists():
            st.markdown('<div class="sidebar-logo-wrap">', unsafe_allow_html=True)
            st.image(str(LOGO_SIDEBAR), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("---")
    except Exception:
        pass


def render_nav_panel():
    """Menú de navegación principal — botones en la columna lateral fija."""
    st.markdown('<span class="nav-panel-marker"></span>', unsafe_allow_html=True)
    render_nav_logo()
    st.markdown(
        '<p class="sidebar-subtitle">Control de Caja</p>',
        unsafe_allow_html=True,
    )
    activo = st.session_state.get("nav_key", "panel")
    keys = [k for k, _, _ in MENU_NAVEGACION]
    if activo not in keys:
        activo = "panel"

    for key, label, icono in MENU_NAVEGACION:
        if st.button(
            label,
            key=f"navbtn_{key}",
            icon=icono,
            use_container_width=True,
            type="primary" if key == activo else "secondary",
        ):
            if key != activo:
                st.session_state.nav_key = key
                st.rerun()

    return st.session_state.get("nav_key", activo)


def init_nav_panel_state():
    if NAV_PANEL_VISIBLE_KEY not in st.session_state:
        st.session_state[NAV_PANEL_VISIBLE_KEY] = True


def render_compact_nav_toggle():
    """Botón compacto para mostrar u ocultar el panel de navegación."""
    init_nav_panel_state()
    visible = st.session_state[NAV_PANEL_VISIBLE_KEY]
    icon = ":material/chevron_left:" if visible else ":material/menu:"
    help_text = "Ocultar menú" if visible else "Mostrar menú"
    if st.button(
        "Menú",
        icon=icon,
        key="btn_toggle_nav_panel",
        help=help_text,
    ):
        st.session_state[NAV_PANEL_VISIBLE_KEY] = not visible
        st.rerun()


def render_panel_header():
    """Header unificado: toggle + logo/nombre/fecha + selector de rango de fechas."""
    st.markdown('<span class="panel-header-anchor"></span>', unsafe_allow_html=True)
    col_toggle, col_brand, col_date = st.columns([0.06, 0.54, 0.40], gap="small")

    with col_date:
        st.markdown('<div class="header-date-col">', unsafe_allow_html=True)
        rango = st.date_input(
            "Rango de fechas (mismo día = un solo día)",
            value=(date.today(), date.today()),
            max_value=date.today(),
            key="rango_panel",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if isinstance(rango, (list, tuple)):
        if len(rango) >= 2:
            fecha_inicio, fecha_fin = rango[0], rango[1]
        elif len(rango) == 1:
            fecha_inicio = fecha_fin = rango[0]
        else:
            fecha_inicio = fecha_fin = date.today()
    else:
        fecha_inicio = fecha_fin = rango

    with col_toggle:
        st.markdown('<div class="header-toggle-col">', unsafe_allow_html=True)
        render_compact_nav_toggle()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_brand:
        if fecha_inicio == fecha_fin:
            resumen_txt = f"Resumen del {fecha_inicio.strftime('%d/%m/%Y')}"
        else:
            resumen_txt = (
                f"Resumen del {fecha_inicio.strftime('%d/%m/%Y')} "
                f"al {fecha_fin.strftime('%d/%m/%Y')}"
            )
        st.markdown(
            f'<div class="header-brand-block">'
            f'<div class="header-brand-text">'
            f'<p class="app-header-title">Il Giardino Ristorante</p>'
            f'<p class="app-header-sub">{resumen_txt}</p>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    return fecha_inicio, fecha_fin


def render_page_top_toggle():
    """Toggle compacto para pantallas distintas al panel del día."""
    st.markdown('<div class="page-top-toggle"><div class="header-toggle-col">', unsafe_allow_html=True)
    render_compact_nav_toggle()
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_main_content(nav):
    """Contenido principal según la sección activa del menú."""
    if nav == "panel":
        fecha_inicio, fecha_fin = render_panel_header()
        pantalla_panel(fecha_inicio, fecha_fin)
    elif nav == "nuevo":
        pantalla_registrar()
    elif nav == "propinas":
        pantalla_propinas()
    elif nav == "egreso":
        pantalla_registrar_egreso()
    elif nav == "cobrar":
        pantalla_cuentas_por_cobrar()
    elif nav == "clientes":
        pantalla_clientes()
    elif nav == "historial":
        pantalla_historial()
    elif nav == "corregir":
        pantalla_corregir()


def get_logo_bytes():
    """Devuelve los bytes del logo — funciona independiente del directorio de trabajo."""
    ensure_logo()
    for p in _LOGO_CANDIDATES:
        try:
            if p.exists():
                return p.read_bytes()
        except Exception:
            continue
    return None


def main():
    st.set_page_config(
        page_title="Il Giardino · Caja",
        page_icon="🌿",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    aplicar_estilos()
    init_db()
    sincronizar_historico_tasa_hoy()
    init_nav_panel_state()

    if st.session_state[NAV_PANEL_VISIBLE_KEY]:
        col_nav, col_main = st.columns([1, 4.2], gap="medium")
        with col_nav:
            nav = render_nav_panel()
        with col_main:
            if nav != "panel":
                render_page_top_toggle()
            render_main_content(nav)
    else:
        nav = st.session_state.get("nav_key", "panel")
        if nav != "panel":
            render_page_top_toggle()
        render_main_content(nav)


if __name__ == "__main__":
    main()
