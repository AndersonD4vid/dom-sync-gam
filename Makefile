IMAGE ?= dom-sync-gam:local
CONTAINER ?= dom-sync
PLATFORM ?= linux/amd64

.PHONY: build up down ps logs shell \
        domain-today domain-yesterday domain-7d domain-month \
        utm-today utm-yesterday utm-7d utm-month all-7d \
        dev prod

# Use the environment as the last make goal:
#   make up dev
#   make domain-today prod
ENV_GOALS := $(filter dev prod,$(MAKECMDGOALS))
RUN_GOALS := $(filter up down ps logs shell domain-today domain-yesterday domain-7d domain-month utm-today utm-yesterday utm-7d utm-month all-7d,$(MAKECMDGOALS))

ifneq ($(words $(ENV_GOALS)),1)
ifneq ($(strip $(RUN_GOALS)),)
$(error Inform the environment at the end of the command: 'dev' or 'prod' (example: make up dev))
endif
endif

ifeq ($(ENV_GOALS),dev)
ENV_FILE := .env.development
else ifeq ($(ENV_GOALS),prod)
ENV_FILE := .env
endif

build:
	docker build --platform $(PLATFORM) -t $(IMAGE) .

up: build
	docker rm -f $(CONTAINER) 2>/dev/null || true
	docker run -d \
		--name $(CONTAINER) \
		--env-file $(ENV_FILE) \
		-v "$(PWD)/credentials/service-account-key.json:/app/credentials/service-account-key.json:ro" \
		$(IMAGE) tail -f /dev/null

down:
	docker rm -f $(CONTAINER)

ps:
	docker ps --filter name=$(CONTAINER)

logs:
	docker exec $(CONTAINER) tail -n 100 /app/dom_processing.log

shell:
	docker exec -it $(CONTAINER) /bin/bash

domain-today:
	docker exec $(CONTAINER) python soap_multiprocess.py --run --type domain --day today --workers 2

domain-yesterday:
	docker exec $(CONTAINER) python soap_multiprocess.py --run --type domain --day yesterday --workers 2

domain-7d:
	docker exec $(CONTAINER) python soap_multiprocess.py --run --type domain --day last_7_days --workers 2

domain-month:
	DAYS=$$(date +%d | sed 's/^0//'); docker exec $(CONTAINER) python soap_multiprocess.py --run --type domain --day last_$$((DAYS - 1))_days --workers 2

utm-today:
	docker exec $(CONTAINER) python soap_multiprocess.py --run --type utm_campaign --day today --workers 2

utm-yesterday:
	docker exec $(CONTAINER) python soap_multiprocess.py --run --type utm_campaign --day yesterday --workers 2

utm-7d:
	docker exec $(CONTAINER) python soap_multiprocess.py --run --type utm_campaign --day last_7_days --workers 2

utm-month:
	DAYS=$$(date +%d | sed 's/^0//'); docker exec $(CONTAINER) python soap_multiprocess.py --run --type utm_campaign --day last_$$((DAYS - 1))_days --workers 2

all-7d: domain-7d utm-7d

# Environment selectors. They are intentionally no-op targets; their presence
# in MAKECMDGOALS selects ENV_FILE for the other targets.
dev prod:
	@:
