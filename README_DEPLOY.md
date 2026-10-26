# Publicar atualização na VPS

Este documento descreve como publicar uma nova imagem Docker no GitHub Container Registry (GHCR), atualizar o container na VPS, consultar networks, visualizar logs e executar atualizações manuais das receitas.

## 1. Build e publicação da imagem

Execute esta seção no terminal do computador local, dentro da pasta do projeto.

### 1.1. Acessar o projeto

~~~bash
cd "/Users/andersondev/Desktop/Workspace/SoftCash/AdxPay Hub/dom-sync"
~~~

### 1.2. Conferir as alterações

~~~bash
git status
git log -1 --oneline
~~~

Confirme que as alterações desejadas estão no último commit.

### 1.3. Conferir o Docker

Abra o Docker Desktop e aguarde o serviço iniciar:

~~~bash
docker version
~~~

### 1.4. Fazer login no GHCR

Não coloque o token diretamente no comando. Leia-o de forma oculta:

~~~bash
read -s GHCR_TOKEN
~~~

Cole o token do GitHub e pressione Enter. O token precisa ter permissão write:packages.

~~~bash
echo "$GHCR_TOKEN" | docker login ghcr.io \
  -u andersond4vid \
  --password-stdin

unset GHCR_TOKEN
~~~

### 1.5. Criar e publicar a imagem

~~~bash
docker buildx build \
  --platform linux/amd64 \
  -t ghcr.io/andersond4vid/dom-sync-gam:latest \
  --push \
  .
~~~

O ponto final (.) indica que a pasta atual é o contexto do build. O comando cria uma imagem compatível com a VPS, aplica a tag latest e publica a imagem no GHCR.

O .env e a credencial não são incluídos na imagem. Na VPS atual, a credencial está em `credentials/dom.json`; ela é montada no caminho canônico `/app/credentials/service-account-key.json` dentro do container.

## 2. Atualização da imagem na VPS

### 2.1. Entrar na VPS

~~~bash
ssh enccpdo1@cloud26030901
cd ~/dom-sync
~~~

Confirme os arquivos necessários:

~~~bash
test -f .env && echo ".env OK"
test -f credentials/dom.json && echo "credencial OK"
~~~

O .env da VPS deve conter as configurações de produção e o caminho:

~~~env
GAM_KEY_FILE=credentials/service-account-key.json
~~~

### 2.2. Baixar a imagem atualizada

~~~bash
docker pull ghcr.io/andersond4vid/dom-sync-gam:latest
~~~

Baixe a imagem antes de remover o container atual para reduzir o tempo de indisponibilidade.

Se o download apresentar unauthorized ou denied, faça login na VPS:

~~~bash
read -s GHCR_TOKEN
echo "$GHCR_TOKEN" | docker login ghcr.io \
  -u andersond4vid \
  --password-stdin
unset GHCR_TOKEN
~~~

Na VPS, o token precisa ter pelo menos a permissão read:packages. Depois, repita o docker pull.

### 2.3. Remover o container antigo

Este comando interrompe e remove somente o container Docker. Os dados das receitas permanecem no MongoDB.

~~~bash
docker rm -f dom-sync
~~~

### 2.4. Criar o container atualizado

~~~bash
docker run -d \
  --name dom-sync \
  --restart unless-stopped \
  --env-file .env \
  -e GAM_KEY_FILE=credentials/service-account-key.json \
  -v "$PWD/credentials/dom.json:/app/credentials/service-account-key.json:ro" \
  ghcr.io/andersond4vid/dom-sync-gam:latest \
  tail -f /dev/null
~~~

O container permanece ativo para que os comandos manuais e o cron possam executar tarefas usando docker exec.

### 2.5. Conferir o container

~~~bash
docker ps --filter name=dom-sync
docker logs dom-sync
~~~

O status esperado é semelhante a Up ... (healthy). Os logs devem incluir mensagens semelhantes a Redis is ready e Executing: tail -f /dev/null.

## 3. Consultar networks e logs

### 3.1. Listar as networks disponíveis

~~~bash
docker exec dom-sync python soap_multiprocess.py
~~~

Esse comando apenas lista as networks; ele não atualiza o banco de dados.

### 3.2. Consultar logs do container

~~~bash
docker logs dom-sync
docker logs -f dom-sync
~~~

Para sair do acompanhamento em tempo real, pressione Ctrl+C.

### 3.3. Consultar logs de receitas por domínio

~~~bash
tail -n 100 ~/dom-sync-domain.log
tail -f ~/dom-sync-domain.log
~~~

### 3.4. Consultar logs de receitas por UTM campaign

~~~bash
tail -n 100 ~/dom-sync-utm.log
tail -f ~/dom-sync-utm.log
~~~

## 4. Atualização manual das receitas

O processamento usa upsert: registros existentes são atualizados e registros novos são inseridos no MongoDB.

### 4.1. Receitas por domínio — hoje

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type domain \
  --day today
~~~

### 4.2. Receitas por domínio — ontem

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type domain \
  --day yesterday
~~~

### 4.3. Receitas por domínio — ontem e hoje

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type domain \
  --day last_2_days
~~~

### 4.4. Receitas por UTM campaign — hoje

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type utm_campaign \
  --day today
~~~

### 4.5. Receitas por UTM campaign — ontem

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type utm_campaign \
  --day yesterday
~~~

### 4.6. Receitas por UTM campaign — ontem e hoje

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type utm_campaign \
  --day last_2_days
~~~

Para atualizar domínio e UTM, execute os dois comandos correspondentes.

## 5. Executar somente uma network

Use --network seguido do código da network desejada.

Por domínio:

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type domain \
  --day last_2_days \
  --network 23062194970
~~~

Por UTM campaign:

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type utm_campaign \
  --day last_2_days \
  --network 23062194970
~~~

Sem --network, todas as networks habilitadas serão processadas.

## 6. Outros períodos disponíveis

~~~text
--day last_7_days
--day last_30_days
--day last_90_days
~~~

Exemplo:

~~~bash
docker exec dom-sync python soap_multiprocess.py \
  --run \
  --type domain \
  --day last_7_days
~~~

## 7. Consultar o cron da VPS

Mostrar os agendamentos:

~~~bash
crontab -l
~~~

Editar os agendamentos:

~~~bash
crontab -e
~~~

Jobs esperados:

~~~cron
# DOM Sync - domain (cada 10 minutos)
*/10 * * * * docker exec dom-sync python soap_multiprocess.py --run --type domain >> /home/enccpdo1/dom-sync-domain.log 2>&1
0 3 * * * docker exec dom-sync python soap_multiprocess.py --run --type domain --day last_7_days >> /home/enccpdo1/dom-sync-domain.log 2>&1

# DOM Sync - utm_campaign (cada 10 minutos)
*/10 * * * * docker exec dom-sync python soap_multiprocess.py --run --type utm_campaign >> /home/enccpdo1/dom-sync-utm.log 2>&1
0 3 * * * docker exec dom-sync python soap_multiprocess.py --run --type utm_campaign --day last_7_days >> /home/enccpdo1/dom-sync-utm.log 2>&1
~~~

## 8. Checklist rápido de atualização

No computador local:

~~~bash
docker buildx build \
  --platform linux/amd64 \
  -t ghcr.io/andersond4vid/dom-sync-gam:latest \
  --push \
  .
~~~

Na VPS:

~~~bash
cd ~/dom-sync
docker pull ghcr.io/andersond4vid/dom-sync-gam:latest

docker rm -f dom-sync

docker run -d \
  --name dom-sync \
  --restart unless-stopped \
  --env-file .env \
  -e GAM_KEY_FILE=credentials/service-account-key.json \
  -v "$PWD/credentials/dom.json:/app/credentials/service-account-key.json:ro" \
  ghcr.io/andersond4vid/dom-sync-gam:latest \
  tail -f /dev/null

docker ps --filter name=dom-sync
docker logs dom-sync
docker exec dom-sync python soap_multiprocess.py
~~~

