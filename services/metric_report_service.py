from typing import Optional, Dict, List, Any
from DTO.metric_data_dto import MetricDataDTO
import logging

logger = logging.getLogger(__name__)


def _normalize_domain(domain):
    """Minusculo, sem espacos e sem 'www.' inicial (comparacao exata depois)"""
    domain = str(domain).strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


class MetricsReportService:
    """Servico de processamento e enriquecimento de metricas DOM"""

    def __init__(self, network: str, domains: Optional[List[str]] = None):
        self.network = network
        self.domains = (
            {_normalize_domain(d) for d in domains} if domains else None
        )

    def _domain_allowed(self, domain) -> bool:
        """Sem allowlist, tudo passa; com ela, so dominios exatos da lista"""
        return self.domains is None or _normalize_domain(domain) in self.domains

    def process_domain_metrics(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Processa metricas de revenue by domain.
        Agrega sub-units (Ad unit 2) por dominio+date, somando impressions/clicks/revenue.
        """
        logger.info(f"[{self.network}] process_domain_metrics: received {len(items)} items")
        if items:
            logger.info(f"[{self.network}] process_domain_metrics: SAMPLE input row: {items[0]}")

        # Agregar por domain+date (GAM retorna linhas separadas por sub-unit)
        aggregated = {}
        skipped_empty = 0
        skipped_dash = 0
        skipped_domains = 0

        for row in items:
            domain = row.get('domain', '')
            if not domain or domain == '-' or domain == '(not set)':
                if not domain:
                    skipped_empty += 1
                else:
                    skipped_dash += 1
                continue

            if not self._domain_allowed(domain):
                skipped_domains += 1
                continue

            date = row.get('date', '')
            key = (domain, date)

            impressions = int(row.get('impressions', 0))
            clicks = int(row.get('clicks', 0))
            revenue = float(row.get('revenue', 0))

            if key in aggregated:
                aggregated[key]['impressions'] += impressions
                aggregated[key]['clicks'] += clicks
                aggregated[key]['revenue'] += revenue
            else:
                aggregated[key] = {
                    'domain': domain,
                    'date': date,
                    'impressions': impressions,
                    'clicks': clicks,
                    'revenue': revenue,
                }

        result = []
        for (domain, date), data in aggregated.items():
            imp = data['impressions']
            clk = data['clicks']
            rev = data['revenue']
            ctr = round((clk / imp * 100), 2) if imp > 0 else 0.0
            ecpm = round((rev / imp * 1000), 6) if imp > 0 else 0.0

            metric = MetricDataDTO(
                domain=domain,
                network=str(self.network),
                date=date,
                impressions=imp,
                clicks=clk,
                ctr=ctr,
                ecpm=ecpm,
                revenue=round(rev, 6),
            )
            result.append(metric.to_dict())

        logger.info(
            f"[{self.network}] process_domain_metrics: output {len(result)} records "
            f"(aggregated from {len(items)}, skipped: {skipped_empty} empty, {skipped_dash} dash/not-set, "
            f"{skipped_domains} fora da allowlist)"
        )
        if result:
            logger.info(f"[{self.network}] process_domain_metrics: SAMPLE output: {result[0]}")

        return result

    def process_utm_campaign_metrics(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Processa metricas de revenue by utm_campaign.
        Filtra apenas items com custom_key = 'utm_campaign'.
        Agrega sub-units por domain+utm_campaign+date, somando impressions/clicks/revenue.
        """
        logger.info(f"[{self.network}] process_utm_campaign_metrics: received {len(items)} items")

        # Agregar por domain+utm_campaign+date
        aggregated = {}
        skipped = 0

        for row in items:
            domain = row.get('domain', '')
            if not domain or domain == '-' or domain == '(not set)':
                skipped += 1
                continue

            if not self._domain_allowed(domain):
                skipped += 1
                continue

            custom_key = row.get('custom_key', '')
            custom_value = row.get('custom_value', '')

            if custom_key != 'utm_campaign' or not custom_value:
                skipped += 1
                continue

            date = row.get('date', '')
            key = (domain, custom_value, date)

            impressions = int(row.get('impressions', 0))
            clicks = int(row.get('clicks', 0))
            revenue = float(row.get('revenue', 0))

            if key in aggregated:
                aggregated[key]['impressions'] += impressions
                aggregated[key]['clicks'] += clicks
                aggregated[key]['revenue'] += revenue
            else:
                aggregated[key] = {
                    'domain': domain,
                    'utm_campaign': custom_value,
                    'date': date,
                    'impressions': impressions,
                    'clicks': clicks,
                    'revenue': revenue,
                }

        result = []
        for (domain, utm_campaign, date), data in aggregated.items():
            imp = data['impressions']
            clk = data['clicks']
            rev = data['revenue']
            ctr = round((clk / imp * 100), 2) if imp > 0 else 0.0
            ecpm = round((rev / imp * 1000), 6) if imp > 0 else 0.0

            metric = MetricDataDTO(
                domain=domain,
                network=str(self.network),
                date=date,
                impressions=imp,
                clicks=clk,
                ctr=ctr,
                ecpm=ecpm,
                revenue=round(rev, 6),
                utm_campaign=utm_campaign,
            )
            result.append(metric.to_dict())

        logger.info(
            f"[{self.network}] process_utm_campaign_metrics: output {len(result)} records "
            f"(aggregated from {len(items)}, skipped: {skipped})"
        )
        if result:
            logger.info(f"[{self.network}] process_utm_campaign_metrics: SAMPLE output: {result[0]}")

        return result
