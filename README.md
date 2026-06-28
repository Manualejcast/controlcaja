# Control de Caja — Restaurante Il Giardino 🏦💰

Este proyecto es una aplicación web interactiva desarrollada con **Streamlit** y **Python** para gestionar el control de caja, ingresos, propinas, transacciones en USDT, IVA, retenciones y conciliaciones de forma eficiente en el restaurante **Il Giardino**.

La aplicación proporciona una interfaz visual limpia y moderna con indicadores clave de rendimiento (KPIs), gráficos dinámicos y reportes estructurados para facilitar la auditoría de diseño y la toma de decisiones financieras.

---

## 🚀 Características Principales

*   **Registro de Transacciones:** Control detallado de ingresos y egresos clasificados por canal (Efectivo, Zelle, Pago Móvil, Punto de Venta, Binance/USDT, etc.).
*   **Múltiples Monedas:** Soporte para USD (Dólares), Bs (Bolívares) e integración automática de tasas de cambio referenciales del BCV (Banco Central de Venezuela) y APIs históricas.
*   **Conciliación y Auditoría:** Herramientas de control interno para cuadrar el efectivo físico en caja frente a los registros del sistema.
*   **Visualización de Datos:** Gráficos dinámicos e interactivos construidos con **Plotly** para analizar tendencias de ingresos, distribución de propinas y canales de pago.
*   **Reportes en Excel:** Exportación directa de datos financieros mediante la integración de **XlsxWriter**.
*   **Base de Datos Local:** Gestión de persistencia de datos ligera y robusta utilizando **SQLite** (`caja_restaurante.db`).

---

## 🛠️ Tecnologías Utilizadas

*   **Lenguaje:** Python 3.8+
*   **Frontend & UI:** [Streamlit](https://streamlit.io/)
*   **Procesamiento de Datos:** [Pandas](https://pandas.pydata.org/)
*   **Visualización:** [Plotly](https://plotly.com/)
*   **Generación de Reportes:** [XlsxWriter](https://xlsxwriter.readthedocs.io/)
*   **Base de Datos:** SQLite

---

## 💻 Instalación y Configuración Local

Sigue estos pasos para poner en marcha el proyecto localmente:

### 1. Clonar el repositorio
Si ya subiste el proyecto a GitHub, puedes clonarlo con:
```bash
git clone https://github.com/tu-usuario/control-caja-restaurante.git
cd control-caja-restaurante
```

### 2. Crear y activar un entorno virtual
Se recomienda el uso de un entorno virtual de Python para mantener limpias las dependencias:

**En Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**En macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias
Instala todas las librerías necesarias especificadas en el archivo `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 4. Ejecutar la aplicación
Para iniciar el servidor local de Streamlit, ejecuta:
```bash
streamlit run app.py
```

La aplicación se abrirá automáticamente en tu navegador web predeterminado (usualmente en `http://localhost:8501`).

---

## 📂 Estructura del Proyecto

```text
control-caja-restaurante/
│
├── .streamlit/             # Configuración visual y temas de Streamlit
│   └── config.toml         # Paleta de colores e identidad visual de Il Giardino
│
├── app.py                  # Archivo principal de la aplicación con toda la lógica y UI
├── requirements.txt        # Dependencias de Python requeridas
├── logo_giardino.jpg       # Imagen del logo oficial de Il Giardino
├── .gitignore              # Archivos y carpetas excluidos del control de versiones
└── README.md               # Documentación del proyecto (este archivo)
```

> 💡 **Nota Importante:** El archivo de base de datos local `caja_restaurante.db` está incluido en el `.gitignore` por motivos de seguridad y privacidad de datos, previniendo que información financiera real o confidencial del restaurante sea cargada a repositorios públicos de GitHub.
