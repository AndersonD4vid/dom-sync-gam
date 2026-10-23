import re
import logging
from pymongo.errors import ConnectionFailure
from services.gam_service import GamService
from services.metric_report_service import MetricsReportService
from services.process_metrics import MetricsProcessor
from repositories.sync_update_status_repository import SyncUpdateStatusRepository

logger = logging.getLogger(__name__)

SOURCE_COLLECTIONS = {
    'domain': 'DomRevenueByDomain',
    'utm_campaign': 'DomRevenueByUtmCampaign',
}


class ReportType:
    def __init__(self, start, end):
        self.start = start  # dias atras para inicio
        self.end = end


def parse_day_parameter(day):
    """Parse do parametro day, suportando formatos dinamicos como last_X_days"""
    if day is None:
        day = "today"
    if day == "yesterday":
        return ReportType(start=1, end=1)
    elif day == "today":
        return ReportType(start=0, end=0)
    elif day == "last_7_days":
        return ReportType(start=7, end=0)
    elif day == "last_30_days":
        return ReportType(start=30, end=0)
    else:
        # Tenta parsear formato dinamico: last_X_days
        match = re.match(r'^last_(\d+)_days$', day)
        if match:
            days = int(match.group(1))
            return ReportType(start=days, end=0)
        return None


def run(network, report_type, day):
    """Executa um relatorio DOM com rate limiting"""

    period = parse_day_parameter(day)
    if period is None:
        logger.error(f"Periodo invalido: {day}")
        return None

    # 1. Criar o servico GAM
    source_collection = SOURCE_COLLECTIONS.get(report_type)
    if source_collection is None:
        logger.error(f"Tipo de relatorio invalido: {report_type}")
        return None

    gam_service = GamService(network, period)

    # As datas reais ficam registradas junto com o nome do periodo.
    period_start, period_end = gam_service._get_date_range()
    period_start = period_start.date().isoformat()
    period_end = period_end.date().isoformat()

    def update_status(method, *args, **kwargs):
        """Status nao deve interromper a sincronizacao principal."""
        try:
            repository = SyncUpdateStatusRepository()
            getattr(repository, method)(*args, **kwargs)
        except Exception as e:
            logger.error(
                f"[{network}] Falha ao atualizar status de sincronizacao: {str(e)[:200]}"
            )

    status_args = (
        source_collection,
        report_type,
        day,
        period_start,
        period_end,
        str(network),
    )
    update_status('mark_attempt', *status_args)

    # 2. Executar o relatorio baseado no tipo
    try:
        if report_type == "domain":
            data = gam_service.gam_revenue_by_domain()
        elif report_type == "utm_campaign":
            data = gam_service.gam_revenue_by_utm_campaign()
        else:
            logger.error(f"Tipo de relatorio invalido: {report_type}")
            return None
    except Exception as e:
        # Verifica se eh erro de autenticacao
        if "NO_NETWORKS_TO_ACCESS" in str(e):
            logger.warning(f"Sem acesso a network {network}: {str(e)[:100]}")
            update_status(
                'mark_error',
                *status_args,
                status='auth_error',
                error=str(e),
            )
            return False
        else:
            logger.error(f"Erro ao obter dados para a network {network}: {str(e)[:100]}")
            update_status(
                'mark_error',
                *status_args,
                status='error',
                error=str(e),
            )
            return None

    # Verifica se ha dados
    if not data or len(data) == 0:
        logger.warning(f"[{network}] Nenhum dado retornado do GAM (report_type={report_type}, day={day})")
        update_status('mark_no_data', *status_args)
        return []

    logger.info(f"[{network}] GAM retornou {len(data)} linhas (report_type={report_type})")
    if data:
        logger.info(f"[{network}] GAM SAMPLE first record keys: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0])}")
        logger.info(f"[{network}] GAM SAMPLE first record: {data[0]}")

    # 3. Processar metricas
    metrics_service = MetricsReportService(network)

    if report_type == "domain":
        processed_data = metrics_service.process_domain_metrics(data)
    else:
        processed_data = metrics_service.process_utm_campaign_metrics(data)

    logger.info(
        f"[{network}] Apos processamento: {len(processed_data)} registros "
        f"(de {len(data)} originais, report_type={report_type})"
    )

    if not processed_data:
        logger.warning(
            f"[{network}] Todos os registros foram filtrados no processamento "
            f"(report_type={report_type})"
        )
        update_status('mark_no_data', *status_args)
        return {'total': 0, 'processed': 0, 'errors': 0}

    # 4. Salvar no banco usando o processador
    try:
        processor = MetricsProcessor()
    except ConnectionFailure as e:
        logger.error(
            f"[{network}] Falha na conexao com MongoDB ao criar MetricsProcessor: {str(e)[:200]}"
        )
        raise

    if report_type == "domain":
        stats = processor.process_domain_bulk(processed_data)
    else:
        stats = processor.process_utm_bulk(processed_data)

    update_status(
        'mark_success',
        *status_args,
        records_found=len(data),
        records_processed=len(processed_data),
        stats=stats,
        status='partial' if stats.get('errors', 0) else 'success',
    )
    logger.info(f"[{network}] Dados salvos com sucesso: {stats}")
    return stats
