FROM linuxserver/code-server:version-v3.7.1
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# Version 3.7.1
# Date 19.11.2020

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y wget gnupg2 locales tzdata software-properties-common && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# Set LOCALE to UTF8..
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8

#Postgres for Debian
RUN wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O- | sudo apt-key add - && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ bionic-pgdg main" | sudo tee /etc/apt/sources.list.d/postgresql.list' && \
    apt-get update && \
    apt-get install -y postgresql-client-12

# Python 3.8
RUN sudo add-apt-repository ppa:deadsnakes/ppa -y && \
    sudo apt -y update && \
    sudo apt -y install python3.8 python3.8-dev python3-pip

# Install basics..
RUN set -x; \
		apt-get install -y --no-install-recommends \
		ca-certificates \
		ghostscript \
		graphviz \
		antiword  \
		poppler-utils \
		htop \
		dnsutils \
		curl \
		build-essential \
		libfreetype6-dev \
		libjpeg-dev \
		libpq-dev \
		libxml2-dev \
		libxslt1-dev \
		libldap2-dev \
		libsasl2-dev \
		libffi-dev \		
		unzip \
		sqlite3 \
		nano \
		mc \
		tmux \
		pkg-config \
		geoip-bin \
		geoip-database \
		node-less \
		node-clean-css \
		imagemagick \
		xfonts-75dpi \
		xfonts-base \
		zsh

# run the installation script
RUN wget https://github.com/robbyrussell/oh-my-zsh/raw/master/tools/install.sh -O - | zsh || true

# Update bash..
COPY ./.zshrc /config/

# TODO tmux
# https://askubuntu.com/questions/442766/tmux-exited-on-startup

RUN sh -c "sudo chsh --shell=/usr/bin/zsh root"
RUN set -x; \
    python3 -m pip install --no-cache-dir pip --upgrade \
    && python3 -m pip install --no-cache-dir wheel --upgrade \
    && python3 -m pip install --no-cache-dir setuptools --upgrade \
    && python3 -m pip install --no-cache-dir odoorpc \
    && python3 -m pip install --no-cache-dir wget \
    && python3 -m pip install --no-cache-dir Faker \
    && python3 -m pip install --no-cache-dir randomuser \
    && python3 -m pip install --no-cache-dir debugpy \
    && python3 -m pip install --no-cache-dir virtualenv \
    && python3 -m pip install --no-cache-dir six

COPY create_virtualenv_python38_v13.sh .

RUN /bin/bash -c "./create_virtualenv_python38_v13.sh"

# PDF export engine install..
RUN set -x; \
    curl -k -o wkhtmltox.deb -SL https://rm.myodoo.net/staff/wkhtmltox_0.12.5-1.bionic_amd64.deb \
        && dpkg --force-depends -i wkhtmltox.deb \
        && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
        && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
        && apt-get -y install -f --no-install-recommends \
        && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
        && rm -rf /var/lib/apt/lists/* wkhtmltox.deb

RUN set -x; \
    apt -y autoremove \
    && apt -y autoclean

# Expose the odoo ports (for linked containers)
EXPOSE 8069 8072

# Finished with build.
