IMAGE ?= ghcr.io/bdomars/banbot:latest

.PHONY: run build push image

run:
	uv run banbot.py

build:
	podman build . -t $(IMAGE)

push:
	podman push $(IMAGE)

image: build push
