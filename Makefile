.PHONY: build
build:
	docker compose up -d

.PHONY: upd
upd:
	docker compose up -d

.PHONY: upd-dev
upd-dev:
	docker compose -f docker-compose-dev.yml up -d

.PHONY: prune
prune:
	docker system prune --all --volumes
