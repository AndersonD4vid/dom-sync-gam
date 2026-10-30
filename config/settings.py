import os
from dotenv import load_dotenv


class ConfigSingleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigSingleton, cls).__new__(cls)
            load_dotenv()
            cls._instance.load_config()
        return cls._instance

    def load_config(self):
        self.json_key_path = os.getenv('GAM_KEY_FILE')

        # API de clientes da JoinAds (office.joinads.me)
        self.JOINADS_API_URL = os.getenv('JOINADS_API_URL', 'https://office.joinads.me')
        self.JOINADS_API_TOKEN = os.getenv('JOINADS_API_TOKEN')

        # Configuracao do Redis
        self.REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
        self.REDIS_DB = int(os.getenv('REDIS_DB', 0))
        self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

        # MongoDB
        self.MONGO_HOST = os.getenv('MONGO_HOST', 'localhost')
        self.MONGO_PORT = int(os.getenv('MONGO_PORT', 27017))
        self.MONGO_DB = os.getenv('MONGO_DB', 'admanager')
        self.MONGO_USER = os.getenv('MONGO_USER', 'joinads')
        self.MONGO_PASSWORD = os.getenv('MONGO_PASSWORD', 'joinads')
        self.MONGO_AUTH_SOURCE = os.getenv('MONGO_AUTH_SOURCE', 'admin')
        self.MONGO_REPLICA_SET = os.getenv('MONGO_REPLICA_SET', '')
        self.MONGO_TLS = os.getenv('MONGO_TLS', 'false').lower() in ('true', '1', 'yes')
        self.MONGO_DIRECT_CONNECTION = os.getenv('MONGO_DIRECT_CONNECTION', '').lower() in ('true', '1', 'yes')

        replica_param = f'&replicaSet={self.MONGO_REPLICA_SET}' if self.MONGO_REPLICA_SET else ''
        tls_param = f'&tls={str(self.MONGO_TLS).lower()}'
        direct_param = '&directConnection=true' if self.MONGO_DIRECT_CONNECTION else ''
        self.MONGODB_URI = (
            f'mongodb://{self.MONGO_USER}:{self.MONGO_PASSWORD}'
            f'@{self.MONGO_HOST}:{self.MONGO_PORT}'
            f'/{self.MONGO_DB}?authSource={self.MONGO_AUTH_SOURCE}{replica_param}{tls_param}{direct_param}'
        )


Config = ConfigSingleton()
