FROM myodoo/prepare-v13:2.1.1
LABEL maintainer=info@myodoo.de
# Mit diesem Skript überprüft das passende Dockerimage gemäß des Releasefiles
# Date 26.05.2021

CMD "echo" "MyOdoo build will start now.."

# create the odoo user
RUN adduser --home=/opt/odoo --disabled-password --gecos "" --shell=/bin/bash odoo
RUN chown -R odoo:odoo /opt/odoo/

# changing user is required by openerp which won't start with root
# makes the container more unlikely to be unwillingly changed in interactive mode
USER odoo

RUN /bin/bash -c "mkdir -p /opt/odoo/{odoo-server/odoo,bin,etc,data,data/filestore}"

COPY build_myodoo.py /opt/odoo/
COPY release.file /opt/odoo/
#COPY custom_modules.* /opt/odoo/

RUN /bin/bash -c "mkdir -p /opt/odoo/{bin,etc,data,data/filestore}" && \
    cd /opt/odoo/ && \
    python3 build_myodoo.py

RUN /bin/bash -c "mkdir -p /opt/odoo/var/{run,log,egg-cache}"

# Execution environment
USER 0
ADD odoo.conf /opt/sources/odoo.conf
WORKDIR /app
VOLUME ["/opt/odoo/var", "/opt/odoo/etc", "/opt/odoo/data"]
# Set the default entrypoint (non overridable) to run when starting the container
ENTRYPOINT ["/app/bin/boot"]
CMD ["help"]
# Expose the odoo ports (for linked containers)
EXPOSE 8069 8072
ADD bin /app/bin/
