ARG PYTHON_VERSION=3.12.12
FROM python:${PYTHON_VERSION}-bookworm as builder

LABEL maintainer="info@ownerp.com"

ARG DEBIAN_FRONTEND=noninteractive
ARG POSTGRESQL_VERSION=16

# Install system dependencies for build
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

# Install PostgreSQL client with specified version
RUN echo 'deb http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && GNUPGHOME="$(mktemp -d)" \
    && export GNUPGHOME \
    && repokey='B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8' \
    && gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "${repokey}" \
    && gpg --batch --armor --export "${repokey}" > /etc/apt/trusted.gpg.d/pgdg.gpg.asc \
    && gpgconf --kill all \
    && rm -rf "$GNUPGHOME" \
    && apt-get update  \
    && apt-get install --no-install-recommends -y postgresql-client-${POSTGRESQL_VERSION} \
    && rm -f /etc/apt/sources.list.d/pgdg.list \
    && rm -rf /var/lib/apt/lists/*

# Install wkhtmltox for amd64
RUN curl -k -o wkhtmltox.deb -SL https://rm.ownerp.io/staff/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
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

# Production stage
FROM python:${PYTHON_VERSION}-bookworm

LABEL maintainer="info@ownerp.com"

ARG DEBIAN_FRONTEND=noninteractive
ARG POSTGRESQL_VERSION=16

# Install PostgreSQL repository and runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg2 \
    wget \
    ca-certificates \
    && echo 'deb http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && GNUPGHOME="$(mktemp -d)" \
    && export GNUPGHOME \
    && repokey='B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8' \
    && gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "${repokey}" \
    && gpg --batch --armor --export "${repokey}" > /etc/apt/trusted.gpg.d/pgdg.gpg.asc \
    && gpgconf --kill all \
    && rm -rf "$GNUPGHOME" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    libldap2-dev \
    libpq-dev \
    libsasl2-dev \
    libxml2-dev \
    libxslt-dev \
    libjpeg-dev \
    postgresql-client-${POSTGRESQL_VERSION} \
    libxrender1 \
    libfontconfig1 \
    libxext6 \
    libx11-6 \
    locales \
    && rm -f /etc/apt/sources.list.d/pgdg.list \
    && rm -rf /var/lib/apt/lists/*

# Configure locale and timezone
RUN echo "de_DE.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen && \
    update-locale LANG=de_DE.UTF-8 && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

ENV LANG=de_DE.UTF-8 LC_ALL=de_DE.UTF-8

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy wkhtmltox from builder
COPY --from=builder /usr/local/bin/wkhtmltopdf /usr/local/bin/
COPY --from=builder /usr/local/bin/wkhtmltoimage /usr/local/bin/

# Create symbolic links
RUN ln -s /usr/local/bin/wkhtmltopdf /usr/bin/ && \
    ln -s /usr/local/bin/wkhtmltoimage /usr/bin/

# own .bashrc 
COPY .bashrc /root/.bashrc
# Optional: bash is the standard shell
SHELL ["/bin/bash", "-lc"]