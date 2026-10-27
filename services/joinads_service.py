import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from config.settings import Config
from services.metric_report_service import _normalize_domain

logger = logging.getLogger(__name__)

REVENUE_FIELDS = ("revenue", "revenue_client")
# Valor que o office poe no dominio de linhas sem dado; nao e um dominio real
OFFICE_PLACEHOLDER_DOMAIN = "Unknown Domain"
# Campo de receita do relatorio analytical -> campo equivalente no key-value (UTM)
UTM_REVENUE_FIELDS = {"revenue": "earnings", "revenue_client": "earnings_client"}


class JoinAdsError(Exception):
    """Falha ao consultar a API de clientes da JoinAds"""


class JoinAdsAuthError(JoinAdsError):
    """Token ausente ou recusado (401/403); tratado como auth_error pelo runner"""


class JoinAdsService:
    """Cliente da API de clientes da JoinAds (office.joinads.me) - relatorios DOM

    Devolve linhas no mesmo formato que o GamService entrega depois do csvToJson:
    domain, date (YYYY-MM-DD), impressions, clicks e revenue (moeda, nao micros;
    a API ja devolve em dolar, entao nao ha conversao), mais custom_key/custom_value
    no relatorio UTM. A agregacao fica no MetricsReportService.
    """

    timeout = 60
    max_attempts = 3
    backoff_seconds = 1.0

    def __init__(self, network_code, report_type=None, joinads_network=None,
                 domains=None, revenue_field="revenue"):
        self.network_code = network_code
        self.base_url = (Config.JOINADS_API_URL or "").rstrip("/")
        self.token = Config.JOINADS_API_TOKEN
        self.joinads_network = str(joinads_network).strip() if joinads_network else None
        self.domains = [d for d in (domains or []) if str(d).strip()]
        if revenue_field not in REVENUE_FIELDS:
            raise ValueError(f"revenue_field invalido: {revenue_field!r}")
        self.revenue_field = revenue_field

        if report_type:
            self.start = report_type.start
            self.end = report_type.end
        else:
            self.start = 1
            self.end = 0

    def joinads_revenue_by_domain(self):
        """Relatorio de revenue by domain (um request por dia x dominio)"""
        rows = []
        for day in self._days():
            for domain in self._request_domains():
                params = {
                    "start_date": day,
                    "end_date": day,
                    "report_type": "analytical",
                }
                if domain:
                    params["domain"] = domain
                rows.extend(self._get("/api/clients-endpoints/earnings", params))
        return self._normalize(rows, self.revenue_field, utm=False)

    def joinads_revenue_by_utm_campaign(self):
        """Relatorio de revenue by utm_campaign (um request por dia x dominio)"""
        rows = []
        for day in self._days():
            for domain in self._request_domains():
                params = {
                    "start_date": day,
                    "end_date": day,
                    "report_type": "Analytical",
                    "custom_key": "utm_campaign",
                }
                if domain:
                    params["domain"] = domain
                if self.joinads_network:
                    # O key-value nao devolve 'network': o filtro e feito no servidor
                    params["network"] = self.joinads_network
                rows.extend(self._get("/api/clients-endpoints/key-value", params))
        return self._normalize(rows, UTM_REVENUE_FIELDS[self.revenue_field], utm=True)

    def _get_date_range(self):
        """Mesmo calculo de datas do GamService (fuso -03:00)"""
        now = datetime.now(timezone(timedelta(hours=-3)))
        return now - timedelta(days=self.start), now - timedelta(days=self.end)

    def _days(self):
        start_date, end_date = self._get_date_range()
        current, last = start_date.date(), end_date.date()
        days = []
        while current <= last:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _request_domains(self):
        """Com allowlist, um request por dominio. Sem ela, um request sem 'domain': o office
        devolve os dominios do usuario do token e dos usuarios filhos (nunca 'todos')."""
        return self.domains or [None]

    def _get(self, path, params):
        """GET com retry para 5xx/timeout; devolve a lista de linhas"""
        if not self.token:
            raise JoinAdsAuthError("JOINADS_API_TOKEN nao configurado")

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

        response = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt == self.max_attempts:
                    raise JoinAdsError(
                        f"Falha de conexao com a API JoinAds ({type(e).__name__})"
                    )
                logger.warning(f"[{self.network_code}] JoinAds {path}: {type(e).__name__}, tentativa {attempt}")
                time.sleep(self.backoff_seconds * attempt)
                continue

            if response.status_code >= 500 and attempt < self.max_attempts:
                logger.warning(f"[{self.network_code}] JoinAds {path}: HTTP {response.status_code}, tentativa {attempt}")
                time.sleep(self.backoff_seconds * attempt)
                continue
            break

        if response.status_code in (401, 403):
            raise JoinAdsAuthError(f"API JoinAds recusou o token (HTTP {response.status_code})")
        if response.status_code != 200:
            raise JoinAdsError(f"API JoinAds retornou HTTP {response.status_code} em {path}")

        try:
            payload = response.json()
        except ValueError:
            raise JoinAdsError(f"Resposta da API JoinAds nao e JSON em {path}")

        return self._extract_rows(payload, path)

    @staticmethod
    def _extract_rows(payload, path):
        """Aceita lista pura ou embrulhada ({code, data} / results); fecha em duvida"""
        if isinstance(payload, dict):
            if payload.get("code") == "error":
                raise JoinAdsError(f"API JoinAds retornou erro em {path}")
            for key in ("data", "results"):
                if key in payload:
                    payload = payload[key]
                    break
            else:
                raise JoinAdsError(f"Formato inesperado da resposta JoinAds em {path}")
        if payload is None:
            return []
        if not isinstance(payload, list):
            # ex.: {"message": "..."} dentro de data quando o backend falha
            raise JoinAdsError(f"Formato inesperado da resposta JoinAds em {path}")
        return [r for r in payload if isinstance(r, dict)]

    def _normalize(self, rows, revenue_key, utm):
        allowed = {_normalize_domain(d) for d in self.domains}
        dropped_network = dropped_domain = dropped_empty = dropped_zero = unlabeled_utm = 0
        result = []

        for row in rows:
            # No UTM a API entrega o dominio em 'name'
            domain = row.get("domain") or row.get("name")
            date = str(row.get("date") or "")[:10]
            if not domain or not date or domain == OFFICE_PLACEHOLDER_DOMAIN:
                dropped_empty += 1
                continue

            if self.joinads_network is not None:
                if utm and row.get("network") is None:
                    # Sem o campo, vale o filtro por 'network' enviado na requisicao
                    unlabeled_utm += 1
                elif str(row.get("network") or "").strip() != self.joinads_network:
                    dropped_network += 1
                    continue

            if allowed and _normalize_domain(domain) not in allowed:
                dropped_domain += 1
                continue

            item = {
                "domain": domain,
                "date": date,
                "impressions": int(float(row.get("impressions") or 0)),
                "clicks": int(float(row.get("clicks") or 0)),
                "revenue": float(row.get(revenue_key) or 0),
            }
            if not (item["impressions"] or item["clicks"] or item["revenue"]):
                # O GAM nao devolve linha toda zerada; o Mercury guarda (ex.: UTM so com requests)
                dropped_zero += 1
                continue
            if utm:
                item["custom_key"] = row.get("custom_key", "")
                item["custom_value"] = row.get("custom_value", "")
            result.append(item)

        logger.info(
            f"[{self.network_code}] JoinAds: {len(rows)} linhas recebidas, {len(result)} mantidas "
            f"(descartadas: {dropped_empty} sem dominio/data, {dropped_network} de outra network, "
            f"{dropped_domain} fora da allowlist, {dropped_zero} zeradas)"
        )
        if unlabeled_utm:
            logger.info(
                f"[{self.network_code}] JoinAds UTM: {unlabeled_utm} linhas sem campo 'network' "
                f"avaliadas (a network foi filtrada no servidor pelo parametro enviado)"
            )
        return result
