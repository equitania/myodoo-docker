ARG PYTHON_VERSION=3.12.9
FROM python:${PYTHON_VERSION}-bookworm

LABEL maintainer="info@ownerp.com"

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

# Install system dependencies
RUN apt-get update && apt-get dist-upgrade -y && apt-get install -y \
    apt-transport-https wget gpg gnupg2 locales tzdata \
    ca-certificates software-properties-common lsb-release less sudo zsh \
    libldap2-dev libldap-common libpq-dev libsasl2-dev libxml2-dev \
    libxslt-dev build-essential libjpeg-dev htop dnsutils unzip sqlite3 \
    nano git mc screen openssh-client pkg-config geoip-bin geoip-database \
    fontconfig iputils-ping xfonts-75dpi xfonts-base fonts-dejavu-core \
    fonts-freefont-ttf fonts-freefont-otf fonts-noto-core fonts-inconsolata \
    fonts-font-awesome fonts-roboto-unhinted gsfonts libjs-underscore lsb-base \
    && ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Configure locale and timezone
RUN echo "de_DE.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen && \
    update-locale LANG=de_DE.UTF-8 && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime
ENV LANG=de_DE.UTF-8 LC_ALL=de_DE.UTF-8

# Install Node.js and global npm packages
RUN curl -fsSL https://deb.nodesource.com/setup_current.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g less less-plugin-clean-css rtlcss && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# install latest postgresql-client
RUN echo 'deb http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && GNUPGHOME="$(mktemp -d)" \
    && export GNUPGHOME \
    && repokey='B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8' \
    && gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "${repokey}" \
    && gpg --batch --armor --export "${repokey}" > /etc/apt/trusted.gpg.d/pgdg.gpg.asc \
    && gpgconf --kill all \
    && rm -rf "$GNUPGHOME" \
    && apt-get update  \
    && apt-get install --no-install-recommends -y postgresql-client \
    && rm -f /etc/apt/sources.list.d/pgdg.list \
    && rm -rf /var/lib/apt/lists/*

# Install wkhtmltox dynamically based on architecture
RUN ARCH="$(dpkg --print-architecture)" \
    && case "${ARCH}" in \
        amd64) \
            curl -k -o wkhtmltox.deb -SL https://rm.ownerp.io/staff/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb ;; \
        arm64) \
            curl -k -o wkhtmltox.deb -SL https://rm.ownerp.io/staff/wkhtmltox_0.12.6.1-3.bookworm_arm64.deb ;; \
        *) \
            echo "Unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libxrender1 \
        libfontconfig1 \
        libxext6 \
        libx11-6 \
    && dpkg --force-depends -i wkhtmltox.deb \
    && apt-get install -f -y \
    && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
    && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
    && rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# Copy requirements file and install Python dependencies
COPY requirements.txt .
RUN python3.12 -m pip install --no-cache-dir -r requirements.txt