IMAGE ?= ghcr.io/bdomars/banbot:latest
GIT_REV ?= $(shell git rev-parse --short=12 HEAD)

.PHONY: run build push image

run:
	uv run banbot.py

build:
	podman build . -t $(IMAGE) --build-arg GIT_REV=$(GIT_REV)

push:
	podman push $(IMAGE)

image: build push
