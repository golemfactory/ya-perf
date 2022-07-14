FROM alpine:latest
VOLUME /golem/output
RUN apk add --no-cache --update bash iperf3 jq py3-pip openssh
RUN pip install pingparsing
ENV SSHPASS=pass.123
# Set root password
RUN echo -e "$SSHPASS\n$SSHPASS" | passwd
# Generate ssh key
RUN mkdir /root/.ssh && \
    chmod 700 /root/.ssh && \
    ssh-keygen -A
RUN ssh-keygen -q -t rsa -N '' -f /root/.ssh/id_rsa && \
    chmod 600 /root/.ssh/id_rsa && \
    chmod 600 /root/.ssh/id_rsa.pub && \
    cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys && \
    chmod 600 /root/.ssh/authorized_keys
# Setup config
RUN echo "Host *" >> /root/.ssh/config && \
    echo "  StrictHostKeyChecking=no" >> /root/.ssh/config
# Enable logging to root with password
RUN echo "UseDNS no" >> /etc/ssh/sshd_config && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config