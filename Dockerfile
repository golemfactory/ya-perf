FROM alpine:latest
VOLUME /golem/output
RUN apk add --no-cache --update bash iperf3 jq py3-pip
RUN pip install pingparsing