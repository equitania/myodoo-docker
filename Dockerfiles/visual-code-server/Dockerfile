FROM linuxserver/code-server:version-v3.6.2
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# Version 3.6.2
# Date 09.11.2020

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y wget gnupg2 locales tzdata && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# Set LOCALE to UTF8..
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8

#Postgres for Debian
RUN wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O- | sudo apt-key add - && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ stretch-pgdg main" | sudo tee /etc/apt/sources.list.d/postgresql.list' && \
    apt-get update && \
    apt-get install -y postgresql-client-12

# Install basics..
RUN set -x; \
		apt-get install -y --no-install-recommends \
		ca-certificates \
        python3 \
        python3-distutils \
		htop \
		dnsutils \
        iputils-ping \
		curl \
		unzip \
		zip \
		mc \
		screen \
		tmux \
		zsh

# TODO tmux
# https://askubuntu.com/questions/442766/tmux-exited-on-startup

RUN sh -c "curl https://bootstrap.pypa.io/get-pip.py | sudo python3"

RUN sh -c "sudo chsh --shell=/usr/bin/zsh $USER"

# https://gist.github.com/MichalZalecki/4a87880bbe7a3a5428b5aebebaa5cd97
# terminal colors with xterm
ENV TERM xterm
# set the zsh theme
ENV ZSH_THEME bira

# run the installation script
RUN wget https://github.com/robbyrussell/oh-my-zsh/raw/master/tools/install.sh -O - | zsh || true

# Update bash..
COPY ./.zshrc /config/

RUN set -x; \
    python3 -m pip install --no-cache-dir pip --upgrade \
    && python3 -m pip install --no-cache-dir wheel --upgrade \
    && python3 -m pip install --no-cache-dir odoorpc \
    && python3 -m pip install --no-cache-dir wget \
    && python3 -m pip install --no-cache-dir Faker \
    && python3 -m pip install --no-cache-dir randomuser \
    && python3 -m pip install --no-cache-dir debugpy

RUN set -x; \
    apt -y autoremove \
    && apt -y autoclean

# Finished with build.
