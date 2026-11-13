# Nómina Ancora

Tablero de Streamlit con el costo de nómina de Ancora (2025, 2026 y 2027),
por área, departamento y colaborador, incluyendo la comparación contra los
ingresos de la empresa por línea de negocio.

## Fuentes de datos

Todo se lee en vivo desde Google Sheets (sin API key, exportando a xlsx):

- **Nómina 2025**: hoja "Base".
- **Nómina 2026**: hoja "Base".
- **Nómina 2027 (presupuesto)**: hoja "Nómina Bruta".
- **Ingresos**: pestaña "Ingresos" del mismo Sheet que usa el tablero
  Town Hall (bloques por año: 2025 real y "PTO 2026" presupuesto).

## Componentes

- `streamlit_app.py`: app principal (Streamlit + Altair para la mayoría de
  las gráficas).
- `components/nomina_costo_area_lineas/`: único componente en React +
  Recharts (vía CDN, sin build step) de este tablero, usado para la
  gráfica "Costo por área, por año" y "Nómina vs ingresos por línea de
  negocio".

## Despliegue

Streamlit Community Cloud, archivo principal `streamlit_app.py`.
