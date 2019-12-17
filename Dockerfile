FROM docker.io/ubuntu:18.04

COPY src /root/sensor

RUN apt-get -y update && \
    apt-get -y install software-properties-common wget && \
    wget -q http://apt-stable.ntop.org/18.04/all/apt-ntop-stable.deb && \
    dpkg -i apt-ntop-stable.deb && \
    apt-get clean all && \
    apt-get -y update && \
    apt-get -y install pfring && \
    DEBIAN_FRONTEND="noninteractive" apt-get -y install tshark && \
    apt-get -y install python3 python3-pip python3-lxml && \
    pip3 install cacheout && \
    pip3 install pyshark && \
    chmod 750 /usr/bin/dumpcap && \
    chgrp root /usr/bin/dumpcap && \
    apt-get clean all && \
    apt-get autoclean && \
    apt-get autoremove && \
    rm -f apt-ntop-stable.deb

ENTRYPOINT ["/bin/bash","-c","/usr/bin/python3 /root/sensor/main.py -i $interface -t $tag -s $ip -p $port -c $cache -r $switch -T $timeout -d $debug"]