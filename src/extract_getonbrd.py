#!/usr/bin/env python3
"""Extractor multi-fuente de empleos (GetOnBrd + Remotive).

Genera:
- un unico JSON crudo combinado con la respuesta de ambas APIs.

No requiere dependencias externas (solo libreria estandar).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL_BASE_GETONBRD = "https://www.getonbrd.com/api/v0"
URL_REMOTIVE = "https://remotive.com/api/remote-jobs"
AGENTE_USUARIO = "UFRO-MinerJobs/1.1"


def solicitar_json_url(
    url: str,
    parametros: Dict[str, Any] | None = None,
    reintentos: int = 3,
) -> Dict[str, Any]:
    parametros_validos = {
        clave: valor
        for clave, valor in (parametros or {}).items()
        if valor is not None and valor != ""
    }

    if parametros_validos:
        consulta = urlencode(parametros_validos, doseq=True)
        separador = "&" if "?" in url else "?"
        url_final = f"{url}{separador}{consulta}"
    else:
        url_final = url

    ultimo_error: Exception | None = None
    for intento in range(1, reintentos + 1):
        solicitud = Request(
            url_final,
            headers={
                "User-Agent": AGENTE_USUARIO,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(solicitud, timeout=30) as respuesta:
                carga = respuesta.read().decode("utf-8")
            return json.loads(carga)
        except IncompleteRead as exc:
            # Algunos servidores cierran antes de completar Content-Length.
            # Si el payload parcial es JSON valido, se usa; si no, se reintenta.
            try:
                return json.loads(exc.partial.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                ultimo_error = exc
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            ultimo_error = exc

        if intento < reintentos:
            time.sleep(1.2 * intento)

    raise RuntimeError(f"No fue posible consultar {url_final}: {ultimo_error}")


def extraer_empleos_getonbrd(argumentos: argparse.Namespace) -> Dict[str, Any]:
    contexto_consulta = {
        "country_code": argumentos.codigo_pais,
        "query": argumentos.consulta,
        "remote": argumentos.remoto or "",
    }

    pagina_actual = 1
    total_paginas = 1
    paginas_descargadas = 0
    paginas_brutas: List[Dict[str, Any]] = []
    empleos_crudos: List[Dict[str, Any]] = []

    while pagina_actual <= total_paginas:
        if argumentos.max_paginas and pagina_actual > argumentos.max_paginas:
            break

        parametros = {
            "page": pagina_actual,
            "per_page": argumentos.por_pagina,
            "country_code": argumentos.codigo_pais,
            "query": argumentos.consulta,
            "remote": argumentos.remoto,
        }
        carga = solicitar_json_url(f"{URL_BASE_GETONBRD}/search/jobs", parametros=parametros)
        paginas_brutas.append(carga)
        paginas_descargadas += 1

        meta = carga.get("meta", {})
        total_paginas = int(meta.get("total_pages", total_paginas) or total_paginas)
        empleos_pagina = carga.get("data", [])

        empleos_crudos.extend(
            empleo for empleo in empleos_pagina if isinstance(empleo, dict)
        )

        print(
            f"  - GetOnBrd pagina {pagina_actual} procesada | registros acumulados: {len(empleos_crudos)}"
        )
        pagina_actual += 1
        if argumentos.pausa_request > 0:
            time.sleep(argumentos.pausa_request)

    return {
        "jobs_raw": empleos_crudos,
        "raw_pages": paginas_brutas,
        "query_context": contexto_consulta,
        "pages_downloaded": paginas_descargadas,
        "total_pages_available": total_paginas,
    }


def extraer_empleos_remotive(argumentos: argparse.Namespace) -> Dict[str, Any]:
    parametros = {
        "limit": argumentos.limite_remotive,
        "search": argumentos.consulta,
    }
    carga = solicitar_json_url(URL_REMOTIVE, parametros=parametros)

    empleos_crudos = [
        empleo
        for empleo in carga.get("jobs", [])
        if isinstance(empleo, dict)
    ]

    return {
        "jobs_raw": empleos_crudos,
        "raw_payload": carga,
        "job_count_reported": carga.get("job-count"),
        "total_job_count_reported": carga.get("total-job-count"),
    }


def escribir_json(ruta: Path, filas: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as archivo:
        json.dump(filas, archivo, ensure_ascii=False, indent=2)


def analizar_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        description="Extrae payloads crudos desde GetOnBrd y Remotive y los combina en un unico JSON."
    )
    analizador.add_argument(
        "--codigo-pais",
        "--country-code",
        dest="codigo_pais",
        default="CL",
        help="Filtro de pais ISO para GetOnBrd (por ejemplo: CL, MX, AR).",
    )
    analizador.add_argument(
        "--consulta",
        "--query",
        dest="consulta",
        default="",
        help="Texto de busqueda para ambas fuentes (cuando aplique).",
    )
    analizador.add_argument(
        "--remoto",
        "--remote",
        dest="remoto",
        choices=["true", "false"],
        default=None,
        help="Filtro remoto para GetOnBrd.",
    )
    analizador.add_argument(
        "--por-pagina",
        "--per-page",
        dest="por_pagina",
        type=int,
        default=120,
        help="Cantidad de registros por pagina en GetOnBrd (maximo recomendado: 120).",
    )
    analizador.add_argument(
        "--max-paginas",
        "--max-pages",
        dest="max_paginas",
        type=int,
        default=1,
        help="Paginas maximas de GetOnBrd (1 por defecto). Usa 0 para todas las paginas.",
    )
    analizador.add_argument(
        "--limite-remotive",
        "--remotive-limit",
        dest="limite_remotive",
        type=int,
        default=120,
        help="Cantidad maxima de empleos a solicitar en Remotive.",
    )
    analizador.add_argument(
        "--pausa-request",
        "--request-delay",
        dest="pausa_request",
        type=float,
        default=0.15,
        help="Pausa entre requests para uso responsable del API.",
    )
    analizador.add_argument(
        "--directorio-salida",
        "--output-dir",
        dest="directorio_salida",
        default="data",
        help="Directorio base de salida.",
    )
    return analizador.parse_args()


def principal() -> None:
    argumentos = analizar_argumentos()

    print("[1/4] Extrayendo GetOnBrd (sin normalizacion)...")
    getonbrd = extraer_empleos_getonbrd(argumentos)

    print("[2/4] Extrayendo Remotive (sin normalizacion)...")
    remotive = extraer_empleos_remotive(argumentos)

    total_getonbrd = len(getonbrd["jobs_raw"])
    total_remotive = len(remotive["jobs_raw"])
    total_combinado = total_getonbrd + total_remotive
    if total_combinado == 0:
        raise SystemExit("No se encontraron registros en ninguna fuente con los filtros indicados.")

    print("[3/4] Combinando payloads crudos en un unico JSON...")
    salida_combinada = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "filters": {
            "getonbrd": getonbrd["query_context"],
            "remotive": {
                "search": argumentos.consulta,
                "limit": argumentos.limite_remotive,
            },
        },
        "counts": {
            "getonbrd_jobs": total_getonbrd,
            "remotive_jobs": total_remotive,
            "total_jobs": total_combinado,
            "getonbrd_pages_downloaded": getonbrd["pages_downloaded"],
            "getonbrd_total_pages_available": getonbrd["total_pages_available"],
            "remotive_job_count_reported": remotive["job_count_reported"],
            "remotive_total_job_count_reported": remotive["total_job_count_reported"],
        },
        "sources": {
            "getonbrd": {
                "endpoint": f"{URL_BASE_GETONBRD}/search/jobs",
                "raw_pages": getonbrd["raw_pages"],
            },
            "remotive": {
                "endpoint": URL_REMOTIVE,
                "raw_payload": remotive["raw_payload"],
            },
        },
    }

    print("[4/4] Escribiendo archivo JSON combinado...")
    ruta_salida = Path(argumentos.directorio_salida) / "raw" / "jobs_apis_raw_combined.json"
    escribir_json(ruta_salida, salida_combinada)

    print("Proceso finalizado.")
    print(f"  - GetOnBrd: {total_getonbrd}")
    print(f"  - Remotive: {total_remotive}")
    print(f"  - Total: {total_combinado}")
    print(f"  - Archivo generado: {ruta_salida}")


if __name__ == "__main__":
    principal()
