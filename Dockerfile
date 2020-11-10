FROM fedora
MAINTAINER https://github.com/jameerpathan111

COPY / /robottelo/
WORKDIR /robottelo
RUN date
