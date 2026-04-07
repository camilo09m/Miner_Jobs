# Miner_Jobs - Fase 1

Proyecto para construir un dataset de ofertas laborales tecnológicas y modelar el perfil demandado del ingeniero de software en plataformas online.

## 1. Fuentes de datos utilizadas

Se utilizaron **ambas APIs** solicitadas en la pauta:

1. Remotive: `https://remotive.com/api/remote-jobs`
2. GetOnBrd: `https://www.getonbrd.com/api/v0`

La implementación final consume ambas fuentes, normaliza sus campos y genera un dataset unificado.

## 2. Justificación: API en vez de scraping

Se optó por API oficial porque:

1. Es más robusta ante cambios de interfaz web.
2. Tiene menor costo de mantenimiento y menor riesgo de fallas.
3. Evita problemas éticos y técnicos asociados a scraping masivo.
4. Mejora la reproducibilidad académica.

Por lo tanto, **no se implementó scraping** en esta fase.

## 3. Consideraciones técnicas por fuente

### GetOnBrd

- `GET /api/v0/jobs` devuelve `401 Unauthorized`.
- `GET /api/v0/search/jobs` funciona si se incluye al menos un filtro (`country_code`, `query` o `remote`).
- En esta entrega se usó por defecto `country_code=CL`.

### Remotive

- Endpoint usado: `/api/remote-jobs`.
- Permite filtro por `search` y límite por `limit`.
- Entrega aviso legal y de atribución en la respuesta; los jobs vienen en la clave `jobs`.

## 4. Estructura del proyecto

```
Miner_Jobs/
	src/
		extract_getonbrd.py
	data/
		raw/
			getonbrd_jobs_raw_pages.json
			remotive_jobs_raw.json
		processed/
			jobs_multisource_dataset.json
			jobs_multisource_dataset.csv
			extraction_metadata.json
		samples/
			jobs_multisource_sample_50.json
			jobs_multisource_sample_50.csv
	README.md
```

## 5. Esquema del dataset unificado

Cada registro normalizado incluye, entre otros:

- Identificación del empleo: `job_id`, `job_title`, `public_url`.
- Origen: `source_platform`, `source_endpoint`.
- Contexto de consulta: `query_country_code`, `query_remote`, `query_text`.
- Empresa: `company_name`, `company_slug`, `company_country`, `company_web`.
- Perfil laboral: `category_name`, `seniority_name`, `modality_name`, `remote`, `remote_modality`.
- Atributos técnicos: `tag_ids`, `tech_keywords`.
- Atributos técnicos: `tag_ids`, `tech_keywords`, `tech_keywords_candidates`.
- Compensación y postulaciones: `min_salary`, `max_salary`, `applications_count`.
- Texto del aviso (limpio): `description_text`, `functions_text`, `projects_text`, `benefits_text`, `desirable_text`.
- Trazabilidad temporal: `published_at_utc`, `extracted_at_utc`.

## 6. Ejecución reproducible

Desde la raíz de `Miner_Jobs`:

```bash
python3 src/extract_getonbrd.py
```

Parámetros por defecto:

- `country_code=CL` (GetOnBrd)
- `per_page=120` (GetOnBrd)
- `max_pages=1` (GetOnBrd)
- `remotive_limit=120` (Remotive)
- `sample_size=50`
- `seed=42`

Extracción de skills mejorada (híbrida):

1. Catálogo base de skills con aliases (normalizados).
2. Detección por patrones compilados (más flexible que regex sueltas).
3. Campo `tech_keywords_candidates` para skills potenciales no catalogadas.

Puedes extender el catálogo sin editar código:

```bash
python3 src/extract_getonbrd.py --skills-catalog config/skills_catalog.json
```

Formato esperado del JSON:

```json
{
  "fastapi": ["fastapi", "fast api"],
  "nestjs": ["nestjs", "nest.js"]
}
```

Ejemplos:

```bash
python3 src/extract_getonbrd.py --max-pages 3
python3 src/extract_getonbrd.py --max-pages 0
python3 src/extract_getonbrd.py --query python
```

## 7. Resultado generado en esta entrega

Ejecución con configuración por defecto:

- Total combinado: `141` registros.
- GetOnBrd: `120` registros.
- Remotive: `21` registros.
- Muestra representativa: `50` registros.

Con esto se cumple el requisito mínimo de contar con al menos 50 registros completos y además se cumple la condición de usar ambas fuentes proporcionadas.

## 8. Limitaciones y consideraciones

1. El volumen devuelto por cada API depende de filtros y del estado del mercado al momento de ejecutar.
2. Algunos campos salariales vienen nulos o en texto libre, por lo que la normalización puede quedar incompleta en ciertos registros.
3. Los esquemas entre APIs son distintos, por lo que algunos atributos no existen en ambas fuentes.

## 9. Siguientes pasos sugeridos

1. Agregar limpieza semántica avanzada de skills y seniority.
2. Construir métricas comparativas entre fuentes (global vs LATAM/Chile).
3. Incorporar versionado de snapshots para análisis temporal de tendencias.
