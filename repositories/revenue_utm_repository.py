from repositories.base_repository import BaseRepository
from datetime import datetime
from pymongo import UpdateOne, ASCENDING
import logging

logger = logging.getLogger(__name__)


class RevenueUtmRepository(BaseRepository):
    """Repositorio para colecao dom_revenue_by_utm_campaign"""

    UNIQUE_FIELDS = ['domain', 'network', 'utm_campaign', 'date']

    def __init__(self):
        super().__init__('dom_revenue_by_utm_campaign')
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Cria indices unicos para a colecao"""
        try:
            self.collection.create_index(
                [
                    ('domain', ASCENDING),
                    ('network', ASCENDING),
                    ('utm_campaign', ASCENDING),
                    ('date', ASCENDING),
                ],
                unique=True,
                name='idx_domain_network_utm_date'
            )
        except Exception as e:
            logger.debug(f"Indice ja existe ou erro ao criar: {e}")

    def _parse_utm(self, utm_campaign):
        """Extrai utmBase e source do utm_campaign"""
        if utm_campaign and '_' in utm_campaign:
            base, source = utm_campaign.split('_', 1)
            return base, source
        return utm_campaign, None

    def save_daily_stats(self, stats_data):
        """Salva estatisticas diarias usando updateOrCreate"""

        # 👇 NOVO: parse utm_campaign
        base, source = self._parse_utm(stats_data.get('utm_campaign'))
        stats_data['utmBase'] = base
        stats_data['source'] = source

        search_criteria = {
            'domain': stats_data.get('domain'),
            'network': stats_data.get('network'),
            'utm_campaign': stats_data.get('utm_campaign'),
            'date': stats_data.get('date'),
        }

        return self.update_or_insert(search_criteria, stats_data)

    def bulk_save_stats(self, stats_list):
        """Salva multiplas estatisticas em bulk"""
        try:
            bulk_operations = []

            for data in stats_list:
                # 👇 NOVO: parse utm_campaign
                base, source = self._parse_utm(data.get('utm_campaign'))
                data['utmBase'] = base
                data['source'] = source

                filter_dict = {field: data[field] for field in self.UNIQUE_FIELDS if field in data}

                update_data = data.copy()
                update_data['updated_at'] = datetime.utcnow()
                update_data.setdefault('created_at', datetime.utcnow())

                bulk_operations.append(
                    UpdateOne(
                        filter_dict,
                        {
                            '$set': update_data,
                            '$setOnInsert': {'created_at': datetime.utcnow()}
                        },
                        upsert=True
                    )
                )

            if bulk_operations:
                result = self.collection.bulk_write(bulk_operations)
                return {
                    'matched': result.matched_count,
                    'modified': result.modified_count,
                    'upserted': result.upserted_count
                }

            return {'matched': 0, 'modified': 0, 'upserted': 0}

        except Exception as e:
            logger.error(f"Erro em bulk_save_stats: {e}")
            raise