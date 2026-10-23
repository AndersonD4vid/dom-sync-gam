from datetime import datetime
from typing import Any, Dict, Optional

from pymongo import ASCENDING

from repositories.base_repository import BaseRepository


class SyncUpdateStatusRepository(BaseRepository):
    """Registra o estado mais recente de cada sincronizacao."""

    COLLECTION_NAME = 'DomSyncUpdateStatus'

    def __init__(self):
        super().__init__(self.COLLECTION_NAME)
        self._ensure_indexes()

    def _ensure_indexes(self):
        self.collection.create_index(
            [
                ('source_collection', ASCENDING),
                ('period_key', ASCENDING),
                ('network', ASCENDING),
            ],
            unique=True,
            name='idx_source_period_network',
        )

    def _filter(self, source_collection: str, period_key: str, network: str):
        return {
            'source_collection': source_collection,
            'period_key': period_key,
            'network': str(network),
        }

    def _base_update(
        self,
        source_collection: str,
        report_type: str,
        period_key: str,
        period_start: str,
        period_end: str,
        network: str,
        status: str,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        update = {
            'source_collection': source_collection,
            'report_type': report_type,
            'period_key': period_key,
            'period_start': period_start,
            'period_end': period_end,
            'network': str(network),
            'status': status,
            'last_attempt_at': now,
            'updated_at': now,
        }
        if error:
            update['last_error'] = error[:500]
        else:
            update['last_error'] = None
        return update

    def mark_attempt(
        self,
        source_collection: str,
        report_type: str,
        period_key: str,
        period_start: str,
        period_end: str,
        network: str,
    ):
        update = self._base_update(
            source_collection,
            report_type,
            period_key,
            period_start,
            period_end,
            network,
            'running',
        )
        return self.collection.update_one(
            self._filter(source_collection, period_key, network),
            {
                '$set': update,
                '$setOnInsert': {'created_at': datetime.utcnow()},
            },
            upsert=True,
        )

    def mark_no_data(
        self,
        source_collection: str,
        report_type: str,
        period_key: str,
        period_start: str,
        period_end: str,
        network: str,
    ):
        update = self._base_update(
            source_collection,
            report_type,
            period_key,
            period_start,
            period_end,
            network,
            'no_data',
        )
        update['records_found'] = 0
        update['records_processed'] = 0
        return self.collection.update_one(
            self._filter(source_collection, period_key, network),
            {
                '$set': update,
                '$setOnInsert': {'created_at': datetime.utcnow()},
            },
            upsert=True,
        )

    def mark_error(
        self,
        source_collection: str,
        report_type: str,
        period_key: str,
        period_start: str,
        period_end: str,
        network: str,
        status: str,
        error: str,
    ):
        update = self._base_update(
            source_collection,
            report_type,
            period_key,
            period_start,
            period_end,
            network,
            status,
            error,
        )
        return self.collection.update_one(
            self._filter(source_collection, period_key, network),
            {
                '$set': update,
                '$setOnInsert': {'created_at': datetime.utcnow()},
            },
            upsert=True,
        )

    def mark_success(
        self,
        source_collection: str,
        report_type: str,
        period_key: str,
        period_start: str,
        period_end: str,
        network: str,
        records_found: int,
        records_processed: int,
        stats: Dict[str, Any],
        status: str = 'success',
    ):
        now = datetime.utcnow()
        update = {
            'source_collection': source_collection,
            'report_type': report_type,
            'period_key': period_key,
            'period_start': period_start,
            'period_end': period_end,
            'network': str(network),
            'status': status,
            'records_found': records_found,
            'records_processed': records_processed,
            'records_matched': stats.get('matched', 0),
            'records_modified': stats.get('modified', 0),
            'records_upserted': stats.get('upserted', 0),
            'last_success_at': now,
            'last_data_update_at': now,
            'last_error': None,
            'updated_at': now,
        }
        return self.collection.update_one(
            self._filter(source_collection, period_key, network),
            {
                '$set': update,
                '$setOnInsert': {'created_at': datetime.utcnow()},
            },
            upsert=True,
        )
