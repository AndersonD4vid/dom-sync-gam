import logging
import time
from google.api_core.exceptions import Unauthorized, PermissionDenied, TooManyRequests
from services.dom_report_runner import run


class NetworkWorker:
    """Worker SOAP que processa networks com rate limiting e retry"""

    def __init__(self, network_rate_limiter):
        self.network_rate_limiter = network_rate_limiter
        self.logger = logging.getLogger(__name__)

    def process_network(self, args):
        """Processa uma network com rate limiting adequado"""
        job_id, network, params = args
        network_code = network['network_code']
        network_name = network['name']

        start_time = time.time()
        request_count = 0

        try:
            self.logger.info(f"[{network_code}] Iniciando processamento: {network_name}")

            result = self._api_call_with_retry(
                network_code,
                run,
                network_code,
                params.type,
                params.day,
                network_name=network_name,
            )
            request_count += 1

            if result is False:
                self.logger.debug(f"[{network_code}] Sem acesso a network")
                return {
                    'job_id': job_id,
                    'network_code': network_code,
                    'network_name': network_name,
                    'status': 'auth_error',
                    'error': 'Sem acesso para executar',
                    'request_count': request_count
                }

            return {
                'job_id': job_id,
                'network_code': network_code,
                'network_name': network_name,
                'status': 'success',
                'result': result,
                'request_count': request_count,
                'duration': time.time() - start_time
            }

        except (Unauthorized, PermissionDenied) as e:
            self.logger.debug(f"[{network_code}] Erro de autenticacao")
            return {
                'job_id': job_id,
                'network_code': network_code,
                'network_name': network_name,
                'status': 'auth_error',
                'error': 'Sem acesso',
                'duration': time.time() - start_time
            }

        except Exception as e:
            self.logger.error(f"[{network_code}] Erro: {str(e)[:100]}")
            return {
                'job_id': job_id,
                'network_code': network_code,
                'network_name': network_name,
                'status': 'error',
                'error': str(e)[:100],
                'duration': time.time() - start_time
            }

    def _api_call_with_retry(self, network_code, func, *args, **kwargs):
        """Executa uma chamada de API com retry e rate limiting"""
        max_retries = 10
        initial_delay = 10.0
        max_delay = 120.0

        for attempt in range(max_retries):
            try:
                # Aplica rate limiting para esta network
                self.network_rate_limiter.wait_if_needed(str(network_code))

                # Faz a chamada
                return func(*args, **kwargs)

            except Exception as e:
                if "429" in str(e) or "Resource has been exhausted" in str(e):
                    if attempt == max_retries - 1:
                        raise TooManyRequests(str(e))

                    # Calcula delay com backoff exponencial
                    delay = min(initial_delay * (2 ** attempt), max_delay)
                    # Adiciona jitter
                    delay *= (1 + 0.2 * (time.time() % 1))

                    self.logger.warning(
                        f"[{network_code}] Rate limit (429). Tentativa {attempt + 1}/{max_retries}. "
                        f"Aguardando {delay:.2f} segundos..."
                    )

                    time.sleep(delay)
                else:
                    raise

        return None
