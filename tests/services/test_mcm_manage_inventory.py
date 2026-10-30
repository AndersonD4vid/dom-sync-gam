"""Tests for the MCM Manage Inventory network (data from the JoinAds clients API)"""
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from config import networks as networks_config
from core.multiprocess.worker import NetworkWorker
from helpers.jsonfy import csvToJson
from services.dom_report_runner import ReportType, run
from services.gam_service import GamService
from services.joinads_service import JoinAdsAuthError, JoinAdsError, JoinAdsService
from services.metric_report_service import MetricsReportService

MI = '23154702080'
JOINADS_NETWORK = '22088551542'
PARENT = '22088551542'
DOMAINS = ['beneficiosocial.org', 'linkdobem.org']
TOKEN = 'tok-secret-123'
BASE = 'https://office.test'


@pytest.fixture(autouse=True)
def joinads_config(monkeypatch):
    from config.settings import Config
    monkeypatch.setattr(Config, 'JOINADS_API_URL', BASE, raising=False)
    monkeypatch.setattr(Config, 'JOINADS_API_TOKEN', TOKEN, raising=False)
    with patch('services.joinads_service.time.sleep'):
        yield


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def _earn(domain='linkdobem.org', network=JOINADS_NETWORK, date='2026-01-01', **kw):
    row = {'domain': domain, 'date': date, 'network': network, 'ad_unit_name': 'u', 'country': 'BR',
           'impressions': 100, 'clicks': 2, 'revenue': 10.0, 'revenue_client': 7.5}
    row.update(kw)
    return row


def _utm(domain='linkdobem.org', network=JOINADS_NETWORK, **kw):
    row = {'date': '2026-01-01', 'name': domain, 'custom_key': 'utm_campaign', 'custom_value': 'camp',
           'impressions': 100, 'clicks': 2, 'earnings': 10.0, 'earnings_client': 7.5}
    if network is not None:
        row['network'] = network
    row.update(kw)
    return row


def _svc(period=(0, 0), **kw):
    kw.setdefault('joinads_network', JOINADS_NETWORK)
    kw.setdefault('domains', DOMAINS)
    return JoinAdsService(MI, ReportType(*period), **kw)


def _wrap(rows):
    return {'code': 'success', 'data': rows}


class TestRequests:
    def test_url_params_and_headers_domain(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([]))) as get:
            _svc().joinads_revenue_by_domain()
        assert get.call_count == 2
        call = get.call_args_list[0]
        assert call.args[0] == f'{BASE}/api/clients-endpoints/earnings'
        assert call.kwargs['headers'] == {'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/json'}
        assert call.kwargs['timeout'] == 60
        params = call.kwargs['params']
        assert params['start_date'] == params['end_date']
        assert params['report_type'] == 'analytical'
        assert params['domain'] == 'beneficiosocial.org'

    def test_url_and_params_utm(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([]))) as get:
            _svc().joinads_revenue_by_utm_campaign()
        call = get.call_args_list[0]
        assert call.args[0] == f'{BASE}/api/clients-endpoints/key-value'
        assert call.kwargs['params']['report_type'] == 'Analytical'
        assert call.kwargs['params']['custom_key'] == 'utm_campaign'
        assert call.kwargs['params']['network'] == JOINADS_NETWORK

    def test_one_call_per_day_and_domain_never_empty(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([]))) as get:
            _svc(period=(2, 0)).joinads_revenue_by_domain()
        assert get.call_count == 3 * len(DOMAINS)
        pairs = {(c.kwargs['params']['start_date'], c.kwargs['params']['domain']) for c in get.call_args_list}
        assert len(pairs) == 3 * len(DOMAINS)
        assert all(c.kwargs['params']['domain'] for c in get.call_args_list)
        assert all(c.kwargs['params']['start_date'] == c.kwargs['params']['end_date'] for c in get.call_args_list)

    def test_without_domains_uses_token_scope(self):
        # Sem allowlist: um request por dia sem 'domain'; o office devolve os dominios do usuario e dos filhos
        for domains in (None, []):
            with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([]))) as get:
                _svc(period=(2, 0), domains=domains).joinads_revenue_by_domain()
            assert get.call_count == 3
            assert all('domain' not in c.kwargs['params'] for c in get.call_args_list)

    def test_utm_without_domains_keeps_network_param(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([]))) as get:
            _svc(domains=None).joinads_revenue_by_utm_campaign()
        params = get.call_args_list[0].kwargs['params']
        assert 'domain' not in params
        assert params['network'] == JOINADS_NETWORK

    def test_wrapped_and_bare_list_formats(self):
        rows = [_earn()]
        for payload in (_wrap(rows), rows, {'results': rows}):
            with patch('services.joinads_service.requests.get', return_value=_resp(payload)):
                out = _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
            assert len(out) == 1

    def test_error_payload_raises(self):
        for payload in ({'code': 'error', 'message': 'x'}, _wrap({'message': 'boom'}), {'foo': 1}):
            with patch('services.joinads_service.requests.get', return_value=_resp(payload)):
                with pytest.raises(JoinAdsError):
                    _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()

    def test_retry_on_5xx_then_success(self):
        seq = [_resp({}, 503), _resp({}, 500), _resp(_wrap([_earn()]))]
        with patch('services.joinads_service.requests.get', side_effect=seq) as get:
            out = _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
        assert get.call_count == 3 and len(out) == 1

    def test_retry_on_timeout_then_fail(self):
        with patch('services.joinads_service.requests.get', side_effect=requests.Timeout('t')) as get:
            with pytest.raises(JoinAdsError):
                _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
        assert get.call_count == 3

    def test_4xx_is_not_retried(self):
        with patch('services.joinads_service.requests.get', return_value=_resp({}, 422)) as get:
            with pytest.raises(JoinAdsError):
                _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
        assert get.call_count == 1


class TestFilters:
    def test_network_filter_drops_other_networks(self):
        rows = [_earn(), _earn(network='23154379558'), _earn(network='23025038160'),
                _earn(network=f' {JOINADS_NETWORK} ')]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
        assert len(out) == 2

    def test_missing_network_field_is_dropped(self):
        row = _earn()
        del row['network']
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([row]))):
            assert _svc(domains=['linkdobem.org']).joinads_revenue_by_domain() == []

    def test_allowlist_drops_foreign_domain(self):
        rows = [_earn(domain='evil.com'), _earn(domain='sub.linkdobem.org'), _earn(domain='WWW.LinkDoBem.org')]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
        assert [r['domain'] for r in out] == ['WWW.LinkDoBem.org']

    def test_rows_without_domain_or_date_dropped(self):
        rows = [_earn(domain=''), _earn(date=''), _earn()]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            assert len(_svc(domains=['linkdobem.org']).joinads_revenue_by_domain()) == 1

    def test_drop_counts_are_logged(self, caplog):
        rows = [_earn(), _earn(network='1'), _earn(domain='x.com'), _earn(domain='')]
        with caplog.at_level(logging.INFO), \
                patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            _svc(domains=['linkdobem.org']).joinads_revenue_by_domain()
        assert '1 sem dominio/data, 1 de outra network, 1 fora da allowlist' in caplog.text

    def test_utm_rows_without_network_are_kept(self):
        rows = [_utm(network=None), _utm(network=None, domain='x.com')]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=['linkdobem.org']).joinads_revenue_by_utm_campaign()
        assert len(out) == 1 and out[0]['domain'] == 'linkdobem.org'

    def test_without_allowlist_keeps_child_domains_of_the_network(self):
        rows = [_earn(), _earn(domain='filho.com'), _earn(domain='outra.com', network='23154379558'),
                _earn(domain='Unknown Domain', network='Unknown Network'), _earn(domain='Unknown Domain')]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=None).joinads_revenue_by_domain()
        assert sorted(r['domain'] for r in out) == ['filho.com', 'linkdobem.org']

    def test_utm_without_allowlist_drops_office_placeholder_rows(self):
        rows = [_utm(network=None), _utm(network=None, domain='filho.com'),
                _utm(network=None, domain='Unknown Domain')]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=None).joinads_revenue_by_utm_campaign()
        assert sorted(r['domain'] for r in out) == ['filho.com', 'linkdobem.org']

    def test_all_zero_rows_are_dropped_like_gam(self):
        # O GAM nao devolve linha sem impressao, clique e receita; o Mercury devolve
        zero = dict(impressions=0, clicks=0, revenue=0.0, revenue_client=0.0)
        rows = [_earn(), _earn(domain='tv.linkdobem.org', **zero), _earn(domain='x.org', impressions=0, clicks=1)]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=None).joinads_revenue_by_domain()
        assert sorted(r['domain'] for r in out) == ['linkdobem.org', 'x.org']

    def test_all_zero_utm_rows_are_dropped_like_gam(self):
        rows = [_utm(network=None), _utm(network=None, custom_value='zerada', impressions=0, clicks=0, earnings=0.0)]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=None).joinads_revenue_by_utm_campaign()
        assert [r['custom_value'] for r in out] == ['camp']

    def test_utm_rows_with_other_network_are_dropped(self):
        rows = [_utm(network=None), _utm(network='23154379558'), _utm()]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            out = _svc(domains=['linkdobem.org']).joinads_revenue_by_utm_campaign()
        assert len(out) == 2


class TestRevenueField:
    def test_domain_revenue_vs_revenue_client(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([_earn()]))):
            gross = _svc(domains=['linkdobem.org'], revenue_field='revenue').joinads_revenue_by_domain()
            net = _svc(domains=['linkdobem.org'], revenue_field='revenue_client').joinads_revenue_by_domain()
        assert gross[0]['revenue'] == 10.0
        assert net[0]['revenue'] == 7.5

    def test_utm_earnings_vs_earnings_client(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([_utm()]))):
            gross = _svc(domains=['linkdobem.org'], revenue_field='revenue').joinads_revenue_by_utm_campaign()
            net = _svc(domains=['linkdobem.org'], revenue_field='revenue_client').joinads_revenue_by_utm_campaign()
        assert gross[0]['revenue'] == 10.0
        assert net[0]['revenue'] == 7.5

    def test_invalid_revenue_field(self):
        with pytest.raises(ValueError):
            _svc(revenue_field='bogus')

    def test_output_feeds_metrics_service(self):
        rows = [_earn(), _earn(ad_unit_name='other', impressions=50, clicks=1, revenue_client=2.5)]
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap(rows))):
            data = _svc(domains=['linkdobem.org'], revenue_field='revenue_client').joinads_revenue_by_domain()
        out = MetricsReportService(MI, domains=['linkdobem.org']).process_domain_metrics(data)
        assert len(out) == 1
        assert out[0]['network'] == MI and out[0]['impressions'] == 150 and out[0]['revenue'] == 10.0

    def test_utm_output_feeds_metrics_service(self):
        with patch('services.joinads_service.requests.get', return_value=_resp(_wrap([_utm()]))):
            data = _svc(domains=['linkdobem.org']).joinads_revenue_by_utm_campaign()
        out = MetricsReportService(MI, domains=['linkdobem.org']).process_utm_campaign_metrics(data)
        assert out[0]['utm_campaign'] == 'camp' and out[0]['domain'] == 'linkdobem.org'


class TestAuth:
    def test_401_raises_auth_error(self):
        for status in (401, 403):
            with patch('services.joinads_service.requests.get', return_value=_resp({}, status)):
                with pytest.raises(JoinAdsAuthError):
                    _svc().joinads_revenue_by_domain()

    def test_empty_token_raises_without_http(self, monkeypatch):
        from config.settings import Config
        monkeypatch.setattr(Config, 'JOINADS_API_TOKEN', '')
        with patch('services.joinads_service.requests.get') as get:
            with pytest.raises(JoinAdsAuthError):
                _svc().joinads_revenue_by_domain()
        get.assert_not_called()

    def test_token_never_logged(self, caplog):
        seq = [_resp({}, 500), _resp(_wrap([_earn(), _earn(network='1')])), _resp({}, 401)]
        with caplog.at_level(logging.DEBUG), \
                patch('services.joinads_service.requests.get', side_effect=seq):
            with pytest.raises(JoinAdsAuthError) as exc:
                _svc().joinads_revenue_by_domain()
        assert TOKEN not in caplog.text and TOKEN[:6] not in caplog.text
        assert TOKEN not in str(exc.value)


class TestDomainAllowlist:
    def _rows(self, *domains):
        return [
            {'domain': d, 'date': '2026-01-01', 'impressions': 10, 'clicks': 1, 'revenue': 1.0,
             'custom_key': 'utm_campaign', 'custom_value': 'x'}
            for d in domains
        ]

    def test_no_allowlist_keeps_everything(self):
        out = MetricsReportService(MI).process_domain_metrics(self._rows('a.com', 'b.org'))
        assert len(out) == 2

    def test_case_insensitive_and_www(self):
        svc = MetricsReportService(MI, domains=['LinkDoBem.org'])
        out = svc.process_domain_metrics(self._rows('linkdobem.org', 'LINKDOBEM.ORG', 'www.linkdobem.org'))
        assert sum(r['impressions'] for r in out) == 30

    def test_exact_match_com_vs_org(self):
        svc = MetricsReportService(MI, domains=['linkdobem.org'])
        out = svc.process_domain_metrics(self._rows('linkdobem.com', 'sub.linkdobem.org', 'linkdobem.org'))
        assert [r['domain'] for r in out] == ['linkdobem.org']

    def test_utm_allowlist(self):
        svc = MetricsReportService(MI, domains=['linkdobem.org'])
        out = svc.process_utm_campaign_metrics(self._rows('linkdobem.com', 'WWW.linkdobem.org'))
        assert [r['domain'] for r in out] == ['WWW.linkdobem.org']


def _run(source=None, report_type='domain', **extra):
    """Executa o runner com GAM, JoinAds, metricas e status mockados"""
    gam = MagicMock()
    gam._get_date_range.return_value = (MagicMock(), MagicMock())
    gam.gam_revenue_by_domain.return_value = [{'domain': 'linkdobem.org'}]
    ja = MagicMock()
    ja._get_date_range.return_value = (MagicMock(), MagicMock())
    ja.joinads_revenue_by_domain.return_value = [{'domain': 'linkdobem.org'}]
    ja.joinads_revenue_by_utm_campaign.return_value = [{'domain': 'linkdobem.org'}]
    metrics = MagicMock()
    metrics.process_domain_metrics.return_value = []
    metrics.process_utm_campaign_metrics.return_value = []
    repo = MagicMock()
    with patch('services.dom_report_runner.GamService', return_value=gam) as gam_cls, \
            patch('services.dom_report_runner.JoinAdsService', return_value=ja) as ja_cls, \
            patch('services.dom_report_runner.MetricsReportService', return_value=metrics) as metrics_cls, \
            patch('services.dom_report_runner.SyncUpdateStatusRepository', return_value=repo):
        result = run(MI, report_type, 'yesterday', network_name='N', source=source, **extra)
    return result, gam_cls, ja_cls, metrics_cls, repo, ja, gam


class TestRouting:
    def test_gam_source_is_unchanged(self):
        for source in (None, 'gam'):
            _, gam_cls, ja_cls, metrics_cls, _, _, gam = _run(source=source)
            gam_cls.assert_called_once()
            assert len(gam_cls.call_args.args) == 2 and gam_cls.call_args.kwargs == {}
            ja_cls.assert_not_called()
            gam.gam_revenue_by_domain.assert_called_once()
            assert metrics_cls.call_args.args == (MI,) and metrics_cls.call_args.kwargs == {}

    def test_joinads_source_uses_joinads_service(self):
        _, gam_cls, ja_cls, metrics_cls, repo, ja, _ = _run(
            source='joinads_api', joinads_network=JOINADS_NETWORK, domains=DOMAINS,
            revenue_field='revenue')
        gam_cls.assert_not_called()
        assert ja_cls.call_args.args[0] == MI
        assert ja_cls.call_args.kwargs == {
            'joinads_network': JOINADS_NETWORK, 'domains': DOMAINS, 'revenue_field': 'revenue'}
        ja.joinads_revenue_by_domain.assert_called_once()
        assert metrics_cls.call_args.args[0] == MI
        assert metrics_cls.call_args.kwargs['domains'] == DOMAINS
        assert repo.mark_attempt.call_args.args[-1] == MI

    def test_joinads_utm_route(self):
        _, _, _, _, _, ja, _ = _run(source='joinads_api', report_type='utm_campaign', domains=DOMAINS)
        ja.joinads_revenue_by_utm_campaign.assert_called_once()

    def test_joinads_auth_error_status(self):
        ja = MagicMock()
        ja._get_date_range.return_value = (MagicMock(), MagicMock())
        ja.joinads_revenue_by_domain.side_effect = JoinAdsAuthError('sem token')
        repo = MagicMock()
        with patch('services.dom_report_runner.JoinAdsService', return_value=ja), \
                patch('services.dom_report_runner.SyncUpdateStatusRepository', return_value=repo):
            result = run(MI, 'domain', 'yesterday', network_name='N', source='joinads_api', domains=DOMAINS)
        assert result is False
        assert repo.mark_error.call_args.kwargs['status'] == 'auth_error'

    def test_empty_token_end_to_end_auth_error_without_http(self, monkeypatch):
        from config.settings import Config
        monkeypatch.setattr(Config, 'JOINADS_API_TOKEN', None)
        repo = MagicMock()
        with patch('services.joinads_service.requests.get') as get, \
                patch('services.dom_report_runner.SyncUpdateStatusRepository', return_value=repo):
            result = run(MI, 'domain', 'yesterday', network_name='N', source='joinads_api',
                         joinads_network=JOINADS_NETWORK, domains=DOMAINS)
        assert result is False
        get.assert_not_called()
        assert repo.mark_error.call_args.kwargs['status'] == 'auth_error'

    def test_runner_fallback_reads_entry_from_config(self):
        entry = {'network_code': MI, 'name': 'X', 'source': 'joinads_api',
                 'joinads_network': JOINADS_NETWORK, 'domains': DOMAINS, 'revenue_field': 'revenue'}
        ja = MagicMock()
        ja._get_date_range.return_value = (MagicMock(), MagicMock())
        ja.joinads_revenue_by_domain.return_value = []
        with patch('services.dom_report_runner.get_network_by_code', return_value=entry), \
                patch('services.dom_report_runner.JoinAdsService', return_value=ja) as ja_cls, \
                patch('services.dom_report_runner.SyncUpdateStatusRepository'):
            run(MI, 'domain', 'yesterday')
        assert ja_cls.call_args.kwargs['revenue_field'] == 'revenue'
        assert ja_cls.call_args.kwargs['joinads_network'] == JOINADS_NETWORK


class TestWorkerAndConfig:
    def test_worker_passes_entry_fields(self):
        network = {
            'network_code': MI, 'name': 'DOM-MI-LATAM', 'source': 'joinads_api',
            'joinads_network': JOINADS_NETWORK, 'domains': ['linkdobem.org'],
            'revenue_field': 'revenue_client',
        }
        limiter = MagicMock()
        mock_run = MagicMock(return_value={'total': 1})
        with patch('core.multiprocess.worker.run', mock_run):
            result = NetworkWorker(limiter).process_network((0, network, MagicMock(type='domain', day='today')))
        assert result['network_code'] == MI
        limiter.wait_if_needed.assert_called_once_with(MI)
        assert mock_run.call_args.args[0] == MI
        assert mock_run.call_args.kwargs == {
            'network_name': 'DOM-MI-LATAM', 'source': 'joinads_api', 'joinads_network': JOINADS_NETWORK,
            'domains': ['linkdobem.org'], 'revenue_field': 'revenue_client'}

    def test_worker_plain_entry_keeps_old_call(self):
        network = {'network_code': '111', 'name': 'N'}
        mock_run = MagicMock(return_value=[])
        with patch('core.multiprocess.worker.run', mock_run):
            NetworkWorker(MagicMock()).process_network((0, network, MagicMock(type='domain', day='today')))
        assert mock_run.call_args.kwargs == {'network_name': 'N'}

    def test_mi_entry_uses_joinads_api_without_parent(self):
        entry = networks_config.get_network_by_code(MI)
        assert entry['source'] == 'joinads_api'
        assert entry['joinads_network'] == PARENT
        assert entry['revenue_field'] == 'revenue'
        # Sem allowlist: o escopo vem do token (dominios do usuario e dos usuarios filhos no office)
        assert 'domains' not in entry
        # A credencial GAM do cliente nao pode depender de acesso a network pai
        assert 'parent_network_code' not in entry
        # Desabilitada ate o deploy do filtro `network` no office e o token do cliente
        assert entry['enabled'] is False
        assert MI not in [n['network_code'] for n in networks_config.get_enabled_networks()]

    def test_worker_passes_parent_network_code(self):
        network = {'network_code': MI, 'name': 'N', 'parent_network_code': PARENT, 'domains': DOMAINS}
        mock_run = MagicMock(return_value={'total': 1})
        with patch('core.multiprocess.worker.run', mock_run):
            NetworkWorker(MagicMock()).process_network((0, network, MagicMock(type='domain', day='today')))
        assert mock_run.call_args.kwargs['parent_network_code'] == PARENT


def _auth(svc):
    svc.json_key_path = '/tmp/key.json'
    with patch('services.gam_service.oauth2.GoogleServiceAccountClient'),             patch('services.gam_service.ad_manager.AdManagerClient') as client_cls:
        svc.auth()
    return client_cls


class TestGamParent:
    def test_client_uses_parent_code(self):
        svc = GamService(MI, parent_network_code=PARENT)
        assert _auth(svc).call_args.kwargs['network_code'] == PARENT
        assert svc.network_code == MI

    def test_client_without_parent_uses_own_code(self):
        assert _auth(GamService('123456')).call_args.kwargs['network_code'] == '123456'

    def test_dimension_with_parent_only(self):
        svc = GamService(MI, parent_network_code=PARENT)
        assert 'CHILD_NETWORK_CODE' in svc._report_query_domain()['dimensions']
        assert 'CHILD_NETWORK_CODE' in svc._report_query_utm_campaign()['dimensions']
        plain = GamService('123456')
        assert plain._report_query_domain()['dimensions'] == ['DATE', 'AD_UNIT_NAME']
        assert plain._report_query_utm_campaign()['dimensions'] == ['DATE', 'AD_UNIT_NAME', 'CUSTOM_CRITERIA']

    def test_filters_rows_by_child_code(self):
        rows = [
            {'domain': 'a.org', 'child_network_code': MI},
            {'domain': 'b.org', 'child_network_code': f' {MI} '},
            {'domain': 'c.org', 'child_network_code': '999'},
            {'domain': 'd.org'},
        ]
        svc = GamService(MI, parent_network_code=PARENT)
        with patch.object(svc, 'auth'), patch.object(svc, '_report_service'),                 patch.object(svc, '_report_run', return_value=rows):
            assert [r['domain'] for r in svc.gam_revenue_by_domain()] == ['a.org', 'b.org']
            assert [r['domain'] for r in svc.gam_revenue_by_utm_campaign()] == ['a.org', 'b.org']

    def test_no_filter_without_parent(self):
        rows = [{'domain': 'a.org'}, {'domain': 'b.org', 'child_network_code': '1'}]
        svc = GamService('123456')
        with patch.object(svc, 'auth'), patch.object(svc, '_report_service'),                 patch.object(svc, '_report_run', return_value=rows):
            assert svc.gam_revenue_by_domain() == rows

    def test_real_header_is_parsed(self):
        lines = [
            'Dimension.DATE,Ad unit 1,Ad unit 2,Dimension.CHILD_NETWORK_CODE,Ad unit ID 1,Ad unit ID 2,'
            'Column.AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,Column.AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS,'
            'Column.AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE',
            f'2026-01-01,linkdobem.org,home,{MI},1,2,10,1,2000000',
        ]
        rows = csvToJson(lines)
        assert rows[0]['child_network_code'] == MI
        assert rows[0]['domain'] == 'linkdobem.org'
        assert rows[0]['revenue'] == 2.0
        out = MetricsReportService(MI, domains=DOMAINS).process_domain_metrics(rows)
        assert len(out) == 1 and 'child_network_code' not in out[0]


class TestParentRouting:
    def test_runner_passes_parent_and_keeps_child_identity(self):
        _, gam_cls, ja_cls, metrics_cls, repo, _, _ = _run(parent_network_code=PARENT, domains=DOMAINS)
        assert gam_cls.call_args.args[0] == MI
        assert gam_cls.call_args.kwargs == {'parent_network_code': PARENT}
        ja_cls.assert_not_called()
        assert metrics_cls.call_args.args[0] == MI
        assert repo.mark_attempt.call_args.args[-1] == MI
        assert PARENT not in repo.mark_attempt.call_args.args

    def test_joinads_source_ignores_parent(self):
        _, gam_cls, ja_cls, _, _, _, _ = _run(source='joinads_api', parent_network_code=PARENT, domains=DOMAINS)
        gam_cls.assert_not_called()
        ja_cls.assert_called_once()

    def test_runner_fallback_reads_parent_from_config(self):
        entry = {'network_code': MI, 'name': 'X', 'parent_network_code': PARENT, 'domains': DOMAINS}
        gam = MagicMock()
        gam._get_date_range.return_value = (MagicMock(), MagicMock())
        gam.gam_revenue_by_domain.return_value = []
        with patch('services.dom_report_runner.get_network_by_code', return_value=entry),                 patch('services.dom_report_runner.GamService', return_value=gam) as gam_cls,                 patch('services.dom_report_runner.SyncUpdateStatusRepository'):
            run(MI, 'domain', 'yesterday')
        assert gam_cls.call_args.kwargs['parent_network_code'] == PARENT
