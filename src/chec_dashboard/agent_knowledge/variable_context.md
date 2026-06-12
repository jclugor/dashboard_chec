# Contexto de Variables CHEC

Este archivo resume, para revision humana, el contexto usado por el flujo de interpretabilidad de series de tiempo hasta el paso 3 de `arquitecturayflujo.md`.

Fuente: `ContextoProyectoSimuladorCHEC.md`, secciones 1 y 2.

## Modos de variables

- **Modo A - Evento, Impacto e Indicadores:** fecha, duracion, usuarios, transformadores, UITI, UITI_VANO y causa.
- **Modo B - Infraestructura de Proteccion y Maniobra:** equipos que despejan y aislan fallas.
- **Modo C - Topologia y Configuracion Espacial:** circuito, vano, coordenadas, distancia y aporte.
- **Modo D - Caracteristicas Fisicas y Electricas del Vano:** conductor, longitud, fases, neutro, cable de guarda y taxonomia.
- **Modo E - Activos:** apoyos y transformadores asociados al vano.
- **Modo F - Entorno, Riesgo y Clima:** riesgo vegetal, rayos, precipitacion, visibilidad, viento, rafagas y temperatura.

## Uso en el dashboard

El flujo de series de tiempo usa este contexto para explicar comportamientos por circuito y periodo:

1. Traduce columnas observadas a variables de dominio.
2. Agrupa variables por modo conceptual.
3. Combina los modos con las reglas fisico/logicas de `variable_interactions.yml`.
4. Genera un diagnostico preliminar semantico sin documentos, bitacoras, RAG, modelo predictivo ni simulacion.

La version ejecutable es `variable_context.yml`.
