# Reglas de Interaccion de Variables

Fuente: `ContextoProyectoSimuladorCHEC.md`, seccion `3.1 Tabla Descriptiva de Conexiones Clave`.

Este archivo es la version revisable por humanos de las reglas fisico/logicas que el sistema usa al analizar eventos seleccionados. La version ejecutable esta en `variable_interactions.yml`.

| Grupo origen | Grupo destino | Relacion / peso | Uso en el analisis |
| --- | --- | --- | --- |
| Series climaticas | Nodos de riesgo | Acumulacion Ambiental / 0.85 | Considerar lluvia, viento, nubosidad, visibilidad y temperatura como estres ambiental previo. |
| Entorno y riesgo | Eventos / causa | Causa Directa / 0.90 | Revisar riesgo vegetal, descargas y rafagas como senales operativas asociadas a la causa. |
| Fisicas y electricas | Eventos / causa | Susceptibilidad Material / 0.80 | Usar conductor, longitud, fases, neutro y taxonomia para explicar susceptibilidad del vano. |
| Topologia | Proteccion | Propagacion de Falla / 0.95 | Relacionar circuito, vano, distancia y cantidad de vanos con el equipo que opera. |
| Activos finales | Entorno y riesgo | Vulnerabilidad Estructural / 0.75 | Contrastar apoyo, altura, norma, clase y tierras con exposicion ambiental. |
| Carga y consumo | Impacto | Impacto Demografico / 0.85 | Usar usuarios, transformadores, capacidad y consumo para dimensionar impacto. |
| Proteccion | Impacto | Aislamiento y Tiempos / 0.80 | Relacionar tipo/equipo de proteccion con duracion y usuarios afectados. |
| Eventos | Indicadores | Calculo Regulatorio / 1.00 | Explicar UiTI desde duracion y usuarios afectados. |
| Atributos espaciales | Topologia | Geometria de Red / 1.00 | Usar coordenadas y FID de vano como trazabilidad espacial. |
