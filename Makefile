IMAGE ?= ghcr.io/bdomars/banbot:latest
GIT_REV ?= $(shell git rev-parse --short=6 HEAD)

.PHONY: run build push image

run:
	uv run python -m banbot.main

build:
	podman build . -t $(IMAGE) --build-arg GIT_REV=$(GIT_REV)

push:
	podman push $(IMAGE)

image: build push
