# Proyecto de VaR histórico en Streamlit

Aplicación con dos páginas: **Resultados** y **Datos**. Reproduce el cálculo de
tu Excel mediante rendimientos logarítmicos y un percentil histórico inclusivo.
Los archivos se procesan en memoria y no se envían a servicios externos. Si
publicas la app, el procesamiento ocurre en el servidor donde la alojes.

## Iniciar en Windows / VS Code

1. Descomprime el ZIP y abre la carpeta `var_streamlit`.
2. Con Python 3.11 o superior instalado, haz doble clic en `INICIAR_WINDOWS.bat`.
   La primera vez necesita Internet para instalar las dependencias.
3. Se abrirá la aplicación en el navegador. Deja abierta la terminal y usa
   `Ctrl+C` cuando quieras detenerla.

También puedes abrir una terminal de VS Code en esa carpeta y ejecutar:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

En Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

No utiliza API, claves ni descargas de cotizaciones. Admite todos los activos
que agregues, dentro de la memoria disponible. El límite por archivo es 50 MB;
puedes cambiarlo en `.streamlit/config.toml`.

## Flujo

1. Carga uno o varios `.xlsx` o `.csv`. Por compatibilidad, `.cvc` se interpreta
   como un archivo de texto CSV.
2. Revisa la hoja, fila de encabezados, columna de fecha y columnas de precios.
   La detección propone valores y siempre permite corregirlos. En archivos con
   OHLC se propone `Adj Close`, `Close` o `Cierre`, en ese orden de preferencia.
   Si comparas activos, utiliza un criterio de precio consistente.
3. Revisa los tickers propuestos. Se obtienen de la columna de ticker si es
   constante, de la cabecera del precio o del nombre del archivo. No se consulta
   una bolsa para verificar el símbolo. Puedes cambiar cualquier ticker.
4. La app valida fechas y precios, informa filas inválidas y conserva solo la
   intersección de fechas. En **Datos** puedes ver y descargar lo descartado.
5. Define capital, unidad monetaria, ponderaciones y confianza. Las
   ponderaciones personalizadas deben sumar 100%. El modo igual usa exactamente
   `1/n`, sin redondear el cálculo.
6. Consulta VaR en porcentaje y dinero, composición y gráficos en **Resultados**.
   **Datos** presenta precios, rendimientos LN, escenarios y contribuciones.

Los controles se comparten entre las páginas. Cada cambio recalcula el análisis;
una configuración inválida retira el resultado anterior hasta corregirla.

## Formatos admitidos

Un archivo por activo. Ejemplo: `TSLA.csv`:

```csv
Fecha,Close
2025-01-02,100.00
2025-01-03,101.50
2025-01-06,99.80
```

Una misma hoja también puede contener varios activos:

```csv
Fecha,TSLA,NKE,SPY
2025-01-02,100,80,500
2025-01-03,101,79,505
2025-01-06,99,81,503
```

Para decimales con coma, utiliza CSV separado por punto y coma y selecciona
`,` como separador decimal. Se reconocen fechas de Excel, `24.09.2025`, ISO y
fechas con `/`. El control día/mes/año resuelve fechas ambiguas como 01/02/2025.
Una columna numérica de Excel se interpreta como fecha solo dentro del rango
de números de serie válido; no se interpreta cualquier número como nanosegundos.

La hoja original de tu Excel también se puede cargar: se detecta la fila 3,
se proponen las tres primeras columnas de precios y se descarta la fila de
montos porque carece de fecha. El capital y las ponderaciones se configuran en
la app; no se importan automáticamente de esa fila.

## Reglas de validación

- Se necesitan fechas y al menos una columna de precios por archivo.
- Los precios deben ser numéricos, positivos y finitos. No se rellenan vacíos
  ni se interpolan precios ausentes.
- Fechas inválidas y precios inválidos se descartan, mostrando la cantidad y
  los registros. Si una serie queda vacía, se bloquea el análisis.
- Duplicados con el mismo precio se eliminan y se contabilizan. Una misma fecha
  con precios diferentes bloquea el análisis para evitar elegir uno arbitrariamente.
- Tickers repetidos se bloquean. Para un archivo en formato largo con varios
  tickers en una columna, sepáralos por archivo o conviértelos a columnas de precios.
- Se conservan las fechas presentes en **todos** los activos incluidos.
- Se requieren como mínimo tres fechas comunes (dos rendimientos). Se muestra
  un aviso cuando hay menos de 100 rendimientos: poder calcular no garantiza
  que la muestra sea suficiente para estimar bien la cola.

## Cálculo equivalente al Excel

Para cada activo `i`, una vez alineados y ordenados los precios:

```text
r_i,t = LN(P_i,t / P_i,t-1)
monto_i = capital × ponderación_i / 100
resultado_t = SUMA(r_i,t × monto_i)
percentil = PERCENTILE.INC(resultados, 1 − confianza)
VaR monetario = −percentil
VaR porcentual = −percentil / capital
```

El código utiliza `numpy.quantile(..., method="linear")`, con interpolación
inclusiva. La primera observación no tiene precio previo y no genera rendimiento.
Por eso no se crea el error `#DIV/0!` de la última fila del Excel original.

`resultado_t` es una ganancia o pérdida **aproximada**, obtenida al aplicar
rendimientos logarítmicos a posiciones monetarias. Mantiene la metodología
solicitada; no es el beneficio exacto de comprar cantidades fijas de títulos.
Los retornos LN tampoco son, por sí mismos, una distribución lognormal.
Este VaR usa la distribución empírica histórica, sin imponer normalidad.

La app trabaja con posiciones largas, sin apalancamiento ni ventas en corto,
y asume precios en una moneda común. No incluye conversiones de divisas,
comisiones, dividendos adicionales ni proyección a varios días. La unidad del
capital es una etiqueta; no convierte los precios.

Cada escenario compara dos fechas comunes consecutivas. Cuando se eliminan
fechas, el intervalo puede abarcar más de una sesión; **Datos** muestra la fecha
anterior y los días calendario. No se presenta un VaR de varios días ni se
escala automáticamente por raíz del tiempo.

Si el percentil inferior es positivo, el VaR con esta convención es negativo.
La app conserva ese signo para reproducir el Excel y lo explica en pantalla.
El VaR no indica la magnitud de las pérdidas más allá del umbral.

## Reproducir el ejemplo

Activa **Usar ejemplo del Excel**, deja capital 300, ponderaciones iguales y
confianza 95%. Los CSV de `examples` contienen únicamente las fechas y los
precios del archivo que compartiste, sin sus fórmulas ni sus resultados:

- 251 precios por activo, del 24/09/2024 al 24/09/2025.
- 250 rendimientos válidos.
- Percentil de resultados: `−9.669051610255686`.
- VaR monetario: `9.669051610255686`.
- VaR porcentual: `3.223017203418562%` (3.22% en pantalla).

El activo BNB mantiene la etiqueta y los precios de tu archivo. El ejemplo no
verifica que el símbolo corresponda a una cotización bursátil determinada.

## Modificar el proyecto

| Archivo | Qué cambiar |
| --- | --- |
| `config.py` | Capital y confianza iniciales, nombres de columnas reconocidos y avisos de muestra |
| `loaders.py` | Formatos de archivos, interpretación de fechas/precios y limpieza |
| `core.py` | Intersección de fechas y metodología del VaR |
| `interface.py` | Controles, tablas, gráficos y textos de las dos páginas |
| `app.py` | Configuración general y navegación |
| `views/results.py`, `views/data.py` | Entradas de las páginas |
| `tests/` | Pruebas de regresión, validaciones y navegación |

Para comprobar cambios:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Referencias de implementación

- [PERCENTILE.INC, Microsoft](https://support.microsoft.com/en-us/excel/functions/percentile-inc-function)
- [numpy.quantile, NumPy](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html)
- [Navegación entre páginas, Streamlit](https://docs.streamlit.io/develop/concepts/multipage-apps/page-and-navigation)
- [Pruebas AppTest, Streamlit](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)

Las dependencias están fijadas en `requirements.txt`. El proyecto se verificó
con Python 3.12; también está escrito para Python 3.11.
