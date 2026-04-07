#!/usr/bin/env python3
"""Extractor multi-fuente de empleos (GetOnBrd + Remotive).

Genera:
- un unico JSON crudo combinado con la respuesta de ambas APIs

No requiere dependencias externas (solo libreria estandar).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import random
import re
import time
import unicodedata
from collections import Counter, defaultdict
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL_BASE_GETONBRD = "https://www.getonbrd.com/api/v0"
URL_REMOTIVE = "https://remotive.com/api/remote-jobs"
AGENTE_USUARIO = "UFRO-MinerJobs/1.1"

# Catalogo base de habilidades. Se puede extender por archivo JSON via --catalogo-habilidades.
ALIAS_HABILIDADES_POR_DEFECTO: Dict[str, List[str]] = {
    "python": ["python"],
    "java": ["java"],
    "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"],
    "react": ["react", "reactjs", "react.js"],
    "react-native": ["react native", "react-native"],
    "angular": ["angular", "angularjs"],
    "vue": ["vue", "vuejs", "vue.js"],
    "node": ["node", "nodejs", "node.js"],
    "go": ["go", "golang"],
    "c++": ["c++"],
    "c#": ["c#", "c sharp"],
    ".net": [".net", "dotnet", "asp.net", "aspnet"],
    "php": ["php"],
    "ruby": ["ruby", "ruby on rails", "rails"],
    "django": ["django"],
    "flask": ["flask"],
    "fastapi": ["fastapi", "fast api"],
    "spring": ["spring", "spring boot", "springboot"],
    "aws": ["aws", "amazon web services"],
    "azure": ["azure", "microsoft azure"],
    "gcp": ["gcp", "google cloud", "google cloud platform"],
    "sql": ["sql"],
    "postgresql": ["postgres", "postgresql"],
    "mysql": ["mysql"],
    "mongodb": ["mongodb", "mongo db"],
    "redis": ["redis"],
    "elasticsearch": ["elasticsearch", "elastic", "opensearch"],
    "docker": ["docker"],
    "kubernetes": ["kubernetes", "k8s"],
    "terraform": ["terraform"],
    "ansible": ["ansible"],
    "airflow": ["airflow", "apache airflow"],
    "spark": ["spark", "apache spark", "pyspark"],
    "hadoop": ["hadoop"],
    "kafka": ["kafka", "apache kafka"],
    "rabbitmq": ["rabbitmq"],
    "graphql": ["graphql"],
    "rest": ["rest", "rest api", "restful"],
    "git": ["git"],
    "github": ["github"],
    "gitlab": ["gitlab"],
    "ci/cd": ["ci/cd", "ci cd", "cicd", "continuous integration", "continuous delivery"],
    "jenkins": ["jenkins"],
    "github-actions": ["github actions"],
    "linux": ["linux"],
    "bash": ["bash", "shell script", "shell scripting"],
    "powerbi": ["power bi", "powerbi"],
    "tableau": ["tableau"],
    "ml": ["machine learning", "ml"],
    "nlp": ["nlp", "natural language processing"],
    "pytorch": ["pytorch", "torch"],
    "tensorflow": ["tensorflow", "tf"],
    "llm": ["llm", "large language model", "large language models", "openai", "langchain", "rag"],
}

PALABRAS_VACIAS_CANDIDATAS = {
    "and",
    "for",
    "the",
    "with",
    "from",
    "this",
    "that",
    "you",
    "will",
    "our",
    "your",
    "buscamos",
    "experiencia",
    "conocimiento",
    "equipo",
    "cargo",
    "years",
}


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


def limpiar_html(texto_bruto: Any) -> str:
    if not texto_bruto:
        return ""

    texto = str(texto_bruto)
    texto = re.sub(r"(?i)<br\s*/?>", "\n", texto)
    texto = re.sub(r"(?i)</(p|div|li|ul|ol|h1|h2|h3|h4|h5|h6)>", "\n", texto)
    texto = re.sub(r"(?i)<li>", "- ", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto).replace("\xa0", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s+", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def unix_a_iso(unix_ts: Any) -> str:
    if unix_ts in (None, ""):
        return ""
    try:
        return dt.datetime.fromtimestamp(int(unix_ts), tz=dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def normalizar_para_coincidencia(texto: Any) -> str:
    valor = str(texto or "")
    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(caracter for caracter in valor if not unicodedata.combining(caracter))
    valor = valor.lower()
    valor = re.sub(r"[^a-z0-9+#./ _-]+", " ", valor)
    valor = re.sub(r"\s+", " ", valor).strip()
    return valor


def cargar_alias_habilidades(ruta: str | None) -> Dict[str, List[str]]:
    aliases = {
        habilidad: list(valores)
        for habilidad, valores in ALIAS_HABILIDADES_POR_DEFECTO.items()
    }
    if not ruta:
        return aliases

    ruta_personalizada = Path(ruta)
    if not ruta_personalizada.exists():
        raise SystemExit(f"El archivo de habilidades no existe: {ruta}")

    try:
        datos = json.loads(ruta_personalizada.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON invalido en --catalogo-habilidades: {exc}") from exc

    if not isinstance(datos, dict):
        raise SystemExit(
            "El archivo de habilidades debe ser un objeto JSON: {habilidad: [aliases...]}"
        )

    for habilidad, aliases_brutos in datos.items():
        canonica = str(habilidad).strip().lower()
        if not canonica:
            continue

        combinados = aliases.get(canonica, [])
        if isinstance(aliases_brutos, list):
            combinados.extend(str(item) for item in aliases_brutos if str(item).strip())
        else:
            combinados.append(str(aliases_brutos))

        aliases[canonica] = sorted({alias.strip() for alias in combinados if alias.strip()})

    return aliases


def compilar_patrones_habilidades(
    alias_habilidades: Dict[str, List[str]],
) -> Dict[str, List[re.Pattern[str]]]:
    compilados: Dict[str, List[re.Pattern[str]]] = {}
    for habilidad, aliases in alias_habilidades.items():
        patrones: List[re.Pattern[str]] = []
        valores = aliases[:] if aliases else [habilidad]
        for alias in valores:
            alias_normalizado = normalizar_para_coincidencia(alias)
            if not alias_normalizado:
                continue

            escapado = re.escape(alias_normalizado)
            escapado = escapado.replace(r"\ ", r"[\s_\-./]+")
            patrones.append(re.compile(rf"(?<![a-z0-9]){escapado}(?![a-z0-9])"))

        if patrones:
            compilados[habilidad] = patrones

    return compilados


def normalizar_iso(valor_bruto: Any) -> str:
    if valor_bruto in (None, ""):
        return ""

    valor = str(valor_bruto).strip()
    try:
        parseado = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
        if parseado.tzinfo is None:
            parseado = parseado.replace(tzinfo=dt.timezone.utc)
        return parseado.astimezone(dt.timezone.utc).isoformat()
    except ValueError:
        return valor


def extraer_rango_salarial(texto_salarial: Any) -> tuple[Any, Any]:
    if not texto_salarial:
        return None, None

    tokens = re.findall(r"\d[\d,.]*\s*[kK]?", str(texto_salarial))
    valores: List[int] = []

    for token in tokens:
        limpio = token.replace(",", "").strip()
        factor = 1
        if limpio.lower().endswith("k"):
            factor = 1000
            limpio = limpio[:-1].strip()
        try:
            numero = float(limpio) * factor
            valores.append(int(numero))
        except ValueError:
            continue

    if not valores:
        return None, None

    if len(valores) == 1:
        return valores[0], valores[0]

    return min(valores), max(valores)


def extraer_ids_relacion(obj_relacion: Any) -> List[str]:
    if not isinstance(obj_relacion, dict):
        return []

    datos = obj_relacion.get("data")
    if isinstance(datos, list):
        return [
            str(item.get("id"))
            for item in datos
            if isinstance(item, dict) and item.get("id") is not None
        ]
    if isinstance(datos, dict) and datos.get("id") is not None:
        return [str(datos.get("id"))]

    return []


def unir_con_barra_vertical(valores: Iterable[Any]) -> str:
    resultado: List[str] = []
    for valor in valores:
        if valor is None:
            continue
        limpio = str(valor).strip()
        if limpio and limpio not in resultado:
            resultado.append(limpio)
    return "|".join(resultado)


def extraer_palabras_clave_tecnicas(
    texto: str,
    patrones_compilados: Dict[str, List[re.Pattern[str]]],
) -> str:
    texto_normalizado = normalizar_para_coincidencia(texto)
    encontradas: List[str] = []

    for habilidad, patrones in patrones_compilados.items():
        if any(patron.search(texto_normalizado) for patron in patrones):
            encontradas.append(habilidad)

    return unir_con_barra_vertical(encontradas)


def extraer_candidatas_habilidades(
    texto: str,
    habilidades_conocidas: str,
    maximo_candidatas: int = 8,
) -> str:
    conocidas = {
        item.strip().lower()
        for item in habilidades_conocidas.split("|")
        if item.strip()
    }
    tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9.+#-]{1,24}\b", texto)
    conteos: Counter[str] = Counter()

    for token in tokens:
        token_minuscula = token.lower()
        if token_minuscula in conocidas:
            continue
        if token_minuscula in PALABRAS_VACIAS_CANDIDATAS:
            continue
        if token.isdigit():
            continue

        tiene_forma_tecnica = (
            any(caracter in token for caracter in ".#+")
            or bool(re.search(r"\d", token))
            or bool(re.fullmatch(r"[A-Z]{2,10}", token))
            or bool(re.search(r"[A-Z][a-z]+[A-Z]", token))
        )
        if not tiene_forma_tecnica:
            continue

        conteos[token_minuscula] += 1

    candidatas = [habilidad for habilidad, _ in conteos.most_common(maximo_candidatas)]
    return unir_con_barra_vertical(candidatas)


def generar_slug(texto: Any) -> str:
    valor = str(texto or "").lower().strip()
    valor = re.sub(r"[^a-z0-9]+", "-", valor)
    return valor.strip("-")


def obtener_catalogo(nombre_catalogo: str, pausa_request: float) -> Dict[str, str]:
    pagina = 1
    total_paginas = 1
    por_pagina = 120
    mapeo: Dict[str, str] = {}

    while pagina <= total_paginas:
        carga = solicitar_json_url(
            f"{URL_BASE_GETONBRD}/{nombre_catalogo}",
            parametros={"page": pagina, "per_page": por_pagina},
        )

        for item in carga.get("data", []):
            if not isinstance(item, dict):
                continue
            id_item = str(item.get("id", "")).strip()
            atributos = item.get("attributes", {})
            nombre_item = ""
            if isinstance(atributos, dict):
                nombre_item = str(atributos.get("name", "")).strip()
            if id_item and nombre_item:
                mapeo[id_item] = nombre_item

        meta = carga.get("meta", {})
        total_paginas = int(meta.get("total_pages", total_paginas) or total_paginas)
        pagina += 1
        if pausa_request > 0:
            time.sleep(pausa_request)

    return mapeo


class ResolvedorEmpresa:
    def __init__(self, pausa_request: float) -> None:
        self.pausa_request = pausa_request
        self.cache: Dict[str, Dict[str, str]] = {}
        self.conteo_consultas = 0

    def obtener(self, id_empresa: str) -> Dict[str, str]:
        if not id_empresa:
            return {
                "company_slug": "",
                "company_name": "",
                "company_country": "",
                "company_web": "",
            }

        if id_empresa in self.cache:
            return self.cache[id_empresa]

        info_empresa = {
            "company_slug": "",
            "company_name": "",
            "company_country": "",
            "company_web": "",
        }
        try:
            carga = solicitar_json_url(f"{URL_BASE_GETONBRD}/companies/{id_empresa}")
            datos_empresa = carga.get("data", {})
            atributos = datos_empresa.get("attributes", {}) if isinstance(datos_empresa, dict) else {}

            info_empresa = {
                "company_slug": str(datos_empresa.get("id", "")) if isinstance(datos_empresa, dict) else "",
                "company_name": str(atributos.get("name", "")) if isinstance(atributos, dict) else "",
                "company_country": str(atributos.get("country", "")) if isinstance(atributos, dict) else "",
                "company_web": str(atributos.get("web", "")) if isinstance(atributos, dict) else "",
            }
        except RuntimeError:
            pass

        self.cache[id_empresa] = info_empresa
        self.conteo_consultas += 1
        if self.pausa_request > 0:
            time.sleep(self.pausa_request)
        return info_empresa


def normalizar_empleo_getonbrd(
    empleo: Dict[str, Any],
    contexto_consulta: Dict[str, Any],
    modalidades: Dict[str, str],
    seniorities: Dict[str, str],
    resolvedor_empresa: ResolvedorEmpresa,
    patrones_habilidades: Dict[str, List[re.Pattern[str]]],
) -> Dict[str, Any]:
    atributos = empleo.get("attributes", {}) if isinstance(empleo, dict) else {}
    enlaces = empleo.get("links", {}) if isinstance(empleo, dict) else {}

    ids_empresa = extraer_ids_relacion(atributos.get("company", {}))
    id_empresa = ids_empresa[0] if ids_empresa else ""
    info_empresa = resolvedor_empresa.obtener(id_empresa)

    ids_modalidad = extraer_ids_relacion(atributos.get("modality", {}))
    id_modalidad = ids_modalidad[0] if ids_modalidad else ""
    ids_seniority = extraer_ids_relacion(atributos.get("seniority", {}))
    id_seniority = ids_seniority[0] if ids_seniority else ""

    texto_descripcion = limpiar_html(atributos.get("description"))
    texto_proyectos = limpiar_html(atributos.get("projects"))
    texto_funciones = limpiar_html(atributos.get("functions"))
    texto_beneficios = limpiar_html(atributos.get("benefits"))
    texto_deseables = limpiar_html(atributos.get("desirable"))
    texto_perfil = "\n".join(
        [
            str(atributos.get("title", "") or ""),
            texto_descripcion,
            texto_funciones,
            texto_deseables,
        ]
    )

    palabras_clave = extraer_palabras_clave_tecnicas(texto_perfil, patrones_habilidades)
    candidatas = extraer_candidatas_habilidades(texto_perfil, palabras_clave)

    return {
        "source_platform": "GetOnBrd",
        "source_endpoint": "/search/jobs",
        "query_country_code": str(contexto_consulta.get("country_code", "")),
        "query_remote": str(contexto_consulta.get("remote", "")),
        "query_text": str(contexto_consulta.get("query", "")),
        "job_id": str(empleo.get("id", "") or ""),
        "job_title": str(atributos.get("title", "") or ""),
        "category_name": str(atributos.get("category_name", "") or ""),
        "company_id": str(id_empresa),
        "company_slug": info_empresa.get("company_slug", ""),
        "company_name": info_empresa.get("company_name", ""),
        "company_country": info_empresa.get("company_country", ""),
        "company_web": info_empresa.get("company_web", ""),
        "remote": atributos.get("remote", None),
        "remote_modality": str(atributos.get("remote_modality", "") or ""),
        "remote_zone": str(atributos.get("remote_zone", "") or ""),
        "countries": unir_con_barra_vertical(atributos.get("countries", [])),
        "language": str(atributos.get("lang", "") or ""),
        "modality_id": id_modalidad,
        "modality_name": modalidades.get(id_modalidad, ""),
        "seniority_id": id_seniority,
        "seniority_name": seniorities.get(id_seniority, ""),
        "tag_ids": unir_con_barra_vertical(extraer_ids_relacion(atributos.get("tags", {}))),
        "tech_keywords": palabras_clave,
        "tech_keywords_candidates": candidatas,
        "perks": unir_con_barra_vertical(atributos.get("perks", [])),
        "min_salary": atributos.get("min_salary", None),
        "max_salary": atributos.get("max_salary", None),
        "applications_count": atributos.get("applications_count", None),
        "response_time_min_days": (
            atributos.get("response_time_in_days", {}).get("min")
            if isinstance(atributos.get("response_time_in_days", {}), dict)
            else None
        ),
        "response_time_max_days": (
            atributos.get("response_time_in_days", {}).get("max")
            if isinstance(atributos.get("response_time_in_days", {}), dict)
            else None
        ),
        "published_at_unix": atributos.get("published_at", None),
        "published_at_utc": unix_a_iso(atributos.get("published_at", None)),
        "location_city_ids": unir_con_barra_vertical(extraer_ids_relacion(atributos.get("location_cities", {}))),
        "location_region_ids": unir_con_barra_vertical(extraer_ids_relacion(atributos.get("location_regions", {}))),
        "location_tenant_ids": unir_con_barra_vertical(extraer_ids_relacion(atributos.get("location_tenants", {}))),
        "description_text": texto_descripcion,
        "projects_text": texto_proyectos,
        "functions_text": texto_funciones,
        "benefits_text": texto_beneficios,
        "desirable_text": texto_deseables,
        "public_url": str(enlaces.get("public_url", "") if isinstance(enlaces, dict) else ""),
        "extracted_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def normalizar_empleo_remotive(
    empleo: Dict[str, Any],
    consulta_global: str,
    patrones_habilidades: Dict[str, List[re.Pattern[str]]],
) -> Dict[str, Any]:
    texto_descripcion = limpiar_html(empleo.get("description"))
    etiquetas = empleo.get("tags", []) if isinstance(empleo.get("tags", []), list) else []
    salario_min, salario_max = extraer_rango_salarial(empleo.get("salary"))

    texto_perfil = "\n".join(
        [
            str(empleo.get("title", "") or ""),
            texto_descripcion,
            unir_con_barra_vertical(etiquetas),
        ]
    )

    palabras_clave = extraer_palabras_clave_tecnicas(texto_perfil, patrones_habilidades)
    candidatas = extraer_candidatas_habilidades(texto_perfil, palabras_clave)

    return {
        "source_platform": "Remotive",
        "source_endpoint": "/remote-jobs",
        "query_country_code": "",
        "query_remote": "true",
        "query_text": str(consulta_global or ""),
        "job_id": str(empleo.get("id", "") or ""),
        "job_title": str(empleo.get("title", "") or ""),
        "category_name": str(empleo.get("category", "") or ""),
        "company_id": "",
        "company_slug": generar_slug(empleo.get("company_name", "")),
        "company_name": str(empleo.get("company_name", "") or ""),
        "company_country": "",
        "company_web": "",
        "remote": True,
        "remote_modality": "remote_global",
        "remote_zone": str(empleo.get("candidate_required_location", "") or ""),
        "countries": str(empleo.get("candidate_required_location", "") or ""),
        "language": "",
        "modality_id": "",
        "modality_name": "",
        "seniority_id": "",
        "seniority_name": "",
        "tag_ids": unir_con_barra_vertical(etiquetas),
        "tech_keywords": palabras_clave,
        "tech_keywords_candidates": candidatas,
        "perks": "",
        "min_salary": salario_min,
        "max_salary": salario_max,
        "applications_count": None,
        "response_time_min_days": None,
        "response_time_max_days": None,
        "published_at_unix": None,
        "published_at_utc": normalizar_iso(empleo.get("publication_date")),
        "location_city_ids": "",
        "location_region_ids": "",
        "location_tenant_ids": "",
        "description_text": texto_descripcion,
        "projects_text": "",
        "functions_text": "",
        "benefits_text": "",
        "desirable_text": "",
        "public_url": str(empleo.get("url", "") or ""),
        "extracted_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def extraer_empleos_getonbrd(
    argumentos: argparse.Namespace,
) -> Dict[str, Any]:
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


def extraer_empleos_remotive(
    argumentos: argparse.Namespace,
) -> Dict[str, Any]:
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


def deduplicar_registros(registros: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vistos: set[str] = set()
    unicos: List[Dict[str, Any]] = []

    for fila in registros:
        clave = f"{fila.get('source_platform', '')}::{fila.get('job_id', '')}"
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(fila)

    return unicos


def construir_muestra_representativa(
    registros: List[Dict[str, Any]],
    tamano_muestra: int,
    semilla: int,
) -> List[Dict[str, Any]]:
    if tamano_muestra >= len(registros):
        return registros[:]

    aleatorio = random.Random(semilla)
    grupos: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for fila in registros:
        grupos[str(fila.get("source_platform", "unknown"))].append(fila)

    fuentes = list(grupos.keys())
    if tamano_muestra < len(fuentes):
        return aleatorio.sample(registros, tamano_muestra)

    obligatorios: List[Dict[str, Any]] = []
    claves_seleccionadas: set[str] = set()
    for fuente in fuentes:
        elegido = aleatorio.choice(grupos[fuente])
        obligatorios.append(elegido)
        claves_seleccionadas.add(f"{elegido.get('source_platform', '')}::{elegido.get('job_id', '')}")

    faltantes = tamano_muestra - len(obligatorios)
    bolsa = [
        fila
        for fila in registros
        if f"{fila.get('source_platform', '')}::{fila.get('job_id', '')}" not in claves_seleccionadas
    ]

    if faltantes > 0:
        obligatorios.extend(aleatorio.sample(bolsa, faltantes))

    aleatorio.shuffle(obligatorios)
    return obligatorios


def escribir_json(ruta: Path, filas: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as archivo:
        json.dump(filas, archivo, ensure_ascii=False, indent=2)


def escribir_csv(ruta: Path, filas: List[Dict[str, Any]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)

    if not filas:
        with ruta.open("w", encoding="utf-8") as archivo:
            archivo.write("")
        return

    campos_base = list(filas[0].keys())
    conjunto_base = set(campos_base)
    campos_extra = sorted(
        {
            clave
            for fila in filas
            for clave in fila.keys()
            if clave not in conjunto_base
        }
    )
    nombres_campos = campos_base + campos_extra

    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=nombres_campos)
        escritor.writeheader()
        escritor.writerows(filas)


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
